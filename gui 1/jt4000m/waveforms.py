"""Waveform preview drawing for the JT-4000M editor (presentation layer).

This module knows NOTHING about SysEx offsets, raw bytes or MIDI.  It receives
plain display strings produced by the Parameter Registry / evidence decoder
(e.g. "SAW", "PULSE", "Unknown (0x07)") and draws an animated waveform tile.

Evidence policy:
    * Only values with a confirmed label in the project's enum tables get a
      drawn shape.
    * Unknown values are rendered as a flat "no established shape" line —
      we never invent a waveform for a value that has no confirmed meaning
      (Hardware TODO).
"""
from __future__ import annotations

import math
from collections.abc import Callable

# Display labels -> shape kind.  Labels come from model.ENUM_OPTIONS via
# display_value(); this is presentation metadata only, NOT a parameter map.
_SHAPES = {
    "OFF": "off",
    "TRI": "triangle",
    "TRIANGLE": "triangle",
    "SQUARE": "square",
    "PULSE": "pulse",
    "SAW": "saw",
    "SAWTOOTH": "saw",
    "RAMP": "ramp",
    "SUPER SAW": "supersaw",
    "RANDOM": "random",
}


def shape_for(display_label: str) -> str | None:
    """Map a registry display label to a drawable shape kind.

    Returns None for unknown/unlabelled values ("Unknown (0xNN)") — the
    caller must then show the 'shape not established' placeholder.
    """
    return _SHAPES.get(display_label.strip().upper())


def _cycle_points(kind: str, phase: float, cycles: int, width: int,
                  samples_per_cycle: int = 64) -> list[tuple[float, float]]:
    """Generate (x, y) polyline points for one period of `kind`.

    y is normalized to [-1, 1]; the caller maps it into the canvas box.
    """
    pts: list[tuple[float, float]] = []
    total = cycles * samples_per_cycle
    for i in range(total + 1):
        t = i / samples_per_cycle            # position in cycles (float)
        u = (t + phase) % 1.0                # [0,1) inside current cycle
        if kind == "saw":
            v = 2.0 * u - 1.0
        elif kind == "ramp":                 # reversed saw
            v = 1.0 - 2.0 * u
        elif kind == "square":
            v = 1.0 if u < 0.5 else -1.0
        elif kind == "pulse":                # narrower high part
            v = 1.0 if u < 0.25 else -1.0
        elif kind == "triangle":
            v = 4.0 * u - 1.0 if u < 0.5 else 3.0 - 4.0 * u
        elif kind == "supersaw":             # saw + detuned saw (unison-ish look)
            v2 = 2.0 * ((u * 1.08) % 1.0) - 1.0
            v = max(-1.0, min(1.0, (2.0 * u - 1.0) * 0.7 + v2 * 0.5))
        elif kind == "random":               # deterministic sample&hold
            seg = int(t + phase)
            h = abs(math.sin(seg * 12.9898) * 43758.5453)
            v = (h % 2.0) - 1.0
        else:                                # "off" / unknown
            v = 0.0
        x = i / total * width
        pts.append((x, v))
    return pts


class WaveTile:
    """One animated waveform preview bound to a tk.Canvas region."""

    def __init__(self, canvas, on_phase: Callable[[], None], width: int = 150,
                 height: int = 44) -> None:
        self.canvas = canvas
        self.width = width
        self.height = height
        self.kind: str | None = None          # None => no bank loaded yet
        self.display: str = ""
        self._on_phase = on_phase
        self._items: list[int] = []
        self._running = False

    # ------------------------------------------------------------- public API
    def set_wave(self, display_label: str) -> None:
        """Update the tile from a registry display string (evidence-safe)."""
        self.display = display_label
        self.kind = shape_for(display_label)

    def draw(self, phase: float = 0.0) -> None:
        c = self.canvas
        for item in self._items:
            c.delete(item)
        self._items.clear()
        pad = 3
        w = self.width - 2 * pad
        h = self.height - 2 * pad
        mid = pad + h / 2.0
        amp = h / 2.0 - 2
        self._items.append(c.create_rectangle(pad, pad, pad + w, pad + h,
                                              outline="#3b3d40", fill="#111214"))
        self._items.append(c.create_line(pad, mid, pad + w, mid,
                                         fill="#2c2e31"))
        if self.kind in (None, "off"):
            # OFF or unknown value: flat line + honest caption. No invented
            # shape for unconfirmed enum values.
            self._items.append(c.create_line(pad, mid, pad + w, mid,
                                             fill="#7a8288", width=2))
            caption = "—" if self.kind == "off" else "? no established shape"
            self._items.append(c.create_text(pad + w / 2, pad + 7, text=caption,
                                             fill="#7a8288", font=("TkDefaultFont", 7)))
            return
        pts = _cycle_points(self.kind, phase, cycles=2, width=w)
        flat = [coord for x, v in pts for coord in (pad + x, mid - v * amp)]
        color = "#7ee787" if self.kind != "supersaw" else "#9dceff"
        self._items.append(c.create_line(*flat, fill=color, width=2, smooth=False))

    # ---------------------------------------------------------------- animation
    def start(self, interval_ms: int = 60) -> None:
        if self._running:
            return
        self._running = True
        self._tick_state = 0
        self._animate(interval_ms)

    def stop(self) -> None:
        self._running = False

    def _animate(self, interval_ms: int) -> None:
        if not self._running:
            return                            # destroyed / stopped: no re-schedule
        try:
            self._tick_state += 1
            self.draw(phase=(self._tick_state % 24) / 24.0)
            self._on_phase()
            self.canvas.after(interval_ms, lambda: self._animate(interval_ms))
        except tk_tcl_error():
            self._running = False


def tk_tcl_error():
    import tkinter as tk
    return tk.TclError
