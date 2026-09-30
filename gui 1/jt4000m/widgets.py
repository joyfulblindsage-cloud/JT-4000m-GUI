"""P1.15 — reusable synth-style Tkinter widgets (presentation layer only).

These widgets know NOTHING about SysEx: no offsets, no raw-byte mutation,
no checksums.  They operate purely on normalized values in ``[0.0, 1.0]``
plus a display string, and communicate with the rest of the application
through callbacks supplied by ``gui.py``, which routes every change through
the public EditorModel API.

Widgets
-------
Knob        — draggable rotary control (drag / Shift-drag fine / wheel /
              arrows / Home-End / double-click reset / editable value entry)
EnvelopeView— ADSR curve visualization (approximate visual mapping only,
              NOT a hardware-accurate simulation)
FilterView  — approximate cutoff/resonance response visualization
              (clearly labeled as approximation inside the widget)
MixBar      — horizontal A/B balance visualization (OSC1 ↔ OSC2)
"""
from __future__ import annotations

import math
import tkinter as tk

BG = "#292a2d"
FG = "#e8e8e8"
MUTED = "#9aa0a6"
ACCENT = "#4c6ef5"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class Knob(tk.Canvas):
    """Synth-style rotary parameter control.

    The knob is *stateless* with respect to the model: it never stores a
    second source of truth.  ``value``/``display`` are pushed in from the
    GUI projection; user gestures call ``on_change(raw_int)``, which the GUI
    forwards to EditorModel, and the final value is always re-read back from
    the model afterwards.

    Parameters
    ----------
    label          : str   — parameter name shown under the knob
    minimum,maximum: int   — registry range (used for normalization ONLY;
                             no invented units)
    on_change      : callable(int) — fired when the user commits a new value
    on_reset       : callable()    — double-click (reset gesture); optional
    default_raw    : int           — reset target (registry default)
    """

    STEP_COARSE = 4          # wheel / arrow step, in normalized units
    STEP_FINE = 1.0          # wheel / arrow step, in raw units (fine mode)

    def __init__(self, parent, *, label: str, minimum: int = 0, maximum: int = 127,
                 diameter: int = 58, on_change=None, on_reset=None,
                 default_raw: int = 0, show_entry: bool = True) -> None:
        height = diameter + 34 if not show_entry else diameter + 52
        super().__init__(parent, width=diameter + 8, height=height, bg=BG,
                         highlightthickness=0, bd=0)
        self.label = label
        self.minimum = minimum
        self.maximum = max(minimum + 1, maximum)
        self.on_change = on_change
        self.on_reset = on_reset
        self.default_raw = default_raw
        self._d = diameter
        self._cx = (diameter + 8) / 2
        self._cy = diameter / 2 + 2
        self._r = diameter / 2 - 6
        self._norm = 0.0            # last painted position
        self._drag_last: tuple[int, int] | None = None
        self._focused = False
        self._hover = False

        if show_entry:
            self.entry = tk.Entry(parent, width=12, bg="#17181a", fg=FG,
                                  insertbackground=FG, relief="flat",
                                  highlightthickness=1, highlightbackground="#3b3d40")
            self.entry.bind("<Return>", self._entry_apply)
            self.entry.bind("<FocusIn>", lambda _e: self.entry.configure(
                highlightbackground=ACCENT))
            self.entry.bind("<FocusOut>", lambda _e: self.entry.configure(
                highlightbackground="#3b3d40"))
        else:
            self.entry = None

        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._double_click)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._wheel_step(+1, e))
        self.bind("<Button-5>", lambda e: self._wheel_step(-1, e))
        self.bind("<Enter>", self._set_hover(True))
        self.bind("<Leave>", self._set_hover(False))
        self.bind("<FocusIn>", self._set_focus(True))
        self.bind("<FocusOut>", self._set_focus(False))
        self.bind("<Up>", lambda e: (self._step(+1, e), "break")[1])
        self.bind("<Down>", lambda e: (self._step(-1, e), "break")[1])
        self.bind("<Left>", lambda e: (self._step(-1, e), "break")[1])
        self.bind("<Right>", lambda e: (self._step(+1, e), "break")[1])
        self.bind("<Home>", lambda e: (self._emit_norm(0.0), "break")[1])
        self.bind("<End>", lambda e: (self._emit_norm(1.0), "break")[1])
        self.configure(takefocus=True)
        self._paint()

    # ---------------------------------------------------------------- public
    def set_value(self, raw: int, text: str | None = None) -> None:
        """Projection update from the model (never fires callbacks)."""
        norm = _clamp((raw - self.minimum) / (self.maximum - self.minimum))
        self._norm = norm
        self._paint()
        if self.entry is not None and text is not None:
            try:
                self.entry.delete(0, "end")
                self.entry.insert(0, text)
            except tk.TclError:
                pass

    @property
    def current_norm(self) -> float:
        return self._norm

    # ------------------------------------------------------------- internals
    def _raw_from_norm(self, norm: float) -> int:
        span = self.maximum - self.minimum
        return int(round(self.minimum + _clamp(norm) * span))

    def _emit_norm(self, norm: float) -> None:
        norm = _clamp(norm)
        raw = self._raw_from_norm(norm)
        self._norm = norm
        self._paint()
        if self.on_change is not None:
            self.on_change(raw)

    def _press(self, event) -> str:
        self.focus_set()
        self._drag_last = (event.x_root, event.y_root)
        return "break"

    def _release(self, _event) -> None:
        self._drag_last = None

    def _drag(self, event) -> str:
        if self._drag_last is None:
            return "break"
        dx = event.y_root - self._drag_last[1]
        dy = self._drag_last[0] - event.x_root
        delta = max(dx, dy) if (abs(dx) >= abs(dy)) else (dx + dy) / 2.0
        fine = bool(event.state & 0x0001)          # Shift held
        step = 0.004 if fine else 0.012
        self._emit_norm(self._norm + delta * step)
        self._drag_last = (event.x_root, event.y_root)
        return "break"

    def _wheel(self, event) -> str:
        direction = 1 if getattr(event, "delta", 0) > 0 else -1
        return self._wheel_step(direction, event)

    def _wheel_step(self, direction: int, event) -> str:
        fine = bool(getattr(event, "state", 0) & 0x0001)
        if fine:
            raw = self._raw_from_norm(self._norm) + direction
            self._emit_norm((raw - self.minimum) / (self.maximum - self.minimum))
        else:
            self._emit_norm(self._norm + direction * self.STEP_COARSE / 128.0)
        return "break"

    def _step(self, direction: int, event) -> str:
        fine = bool(getattr(event, "state", 0) & 0x0001)
        if fine:
            raw = self._raw_from_norm(self._norm) + direction
            self._emit_norm((raw - self.minimum) / (self.maximum - self.minimum))
        else:
            self._emit_norm(self._norm + direction / 16.0)
        return "break"

    def _double_click(self, _event) -> str:
        if self.on_reset is not None:
            self.on_reset()
        else:
            self._emit_norm((self.default_raw - self.minimum)
                            / (self.maximum - self.minimum))
        return "break"

    def _entry_apply(self, _event) -> str:
        """Editable numeric field: accept 'raw', 'raw%' or a semantic label."""
        if self.entry is None:
            return "break"
        text = self.entry.get().strip()
        try:
            if text.endswith("%"):
                self._emit_norm(float(text[:-1]) / 100.0)
            else:
                self._emit_norm((int(text) - self.minimum)
                                / (self.maximum - self.minimum))
        except ValueError:
            if self.on_change is not None:
                self.on_change("__label__:" + text)
        return "break"

    def _set_hover(self, state: bool):
        def _cb(_e=None):
            self._hover = state
            self._paint()
        return _cb

    def _set_focus(self, state: bool):
        def _cb(_e=None):
            self._focused = state
            self._paint()
        return _cb

    def _paint(self) -> None:
        self.delete("all")
        cx, cy, r = self._cx, self._cy, self._r
        ring = "#3b3d40"
        if self._focused:
            ring = ACCENT
        elif self._hover:
            ring = "#6c7076"
        self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=ring, width=2,
                         fill="#17181a")
        # active arc from start angle to current position
        a0, a1 = 135.0, 135.0 - 270.0 * self._norm
        steps = max(2, int(abs(a1 - a0)))
        pts: list[float] = []
        for i in range(steps + 1):
            ang = math.radians(a0 + (a1 - a0) * i / steps)
            pts += [cx + (r - 1) * math.cos(ang), cy - (r - 1) * math.sin(ang)]
        if len(pts) >= 4:
            self.create_line(*pts, fill=ACCENT, width=3, cap="butt")
        # pointer line
        ang = math.radians(135.0 - 270.0 * self._norm)
        self.create_line(cx, cy, cx + (r - 8) * math.cos(ang),
                         cy - (r - 8) * math.sin(ang), fill="#f1f1f1", width=2)
        self.create_text(cx, cy + r + 12, text=self.label, fill=MUTED,
                         font=("TkDefaultFont", 8, "bold"))


class EnvelopeView(tk.Canvas):
    """ADSR curve visualization.

    Pure presentation: normalized visual mapping of four 0..127 registry
    values.  This is explicitly NOT a hardware-accurate envelope simulation —
    time/value relationships were never established offline, so segments use
    equal-width layout and honest labels.
    """

    def __init__(self, parent, *, title: str, width: int = 150, height: int = 64,
                 on_segment=None) -> None:
        super().__init__(parent, width=width, height=height + 16, bg="#17181a",
                         highlightthickness=1, highlightbackground="#3b3d40", bd=0)
        self.title = title
        self.width = width
        self.height = height
        self.on_segment = on_segment          # callable(key, norm) on drag
        self._vals = {"attack": 0.0, "decay": 0.0, "sustain": 0.0, "release": 0.0}
        self._seg = None
        self._dragging = False
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda e: self._paint())
        self._paint()

    def set_values(self, attack: int, decay: int, sustain: int, release: int) -> None:
        self._vals = {
            "attack": _clamp(attack / 127.0),
            "decay": _clamp(decay / 127.0),
            "sustain": _clamp(sustain / 127.0),
            "release": _clamp(release / 127.0),
        }
        self._paint()

    # ------------------------------------------------------------- geometry
    def _points(self):
        w, h = self.width, self.height
        pad = 6
        seg_w = (w - 2 * pad) / 4.0
        x0 = pad
        y_base = h - pad
        y_top = pad
        p0 = (x0, y_base)
        p1 = (x0 + seg_w, y_top)                                   # attack peak
        p2 = (x0 + 2 * seg_w, y_base - (y_base - y_top) * self._vals["sustain"])
        p3 = (x0 + 3 * seg_w, p2[1])                              # sustain hold
        p4 = (x0 + 4 * seg_w, y_base)                             # release end
        return p0, p1, p2, p3, p4

    def _segment_at(self, x: float, y: float):
        """Nearest draggable segment for a point, plus its parameter key."""
        p0, p1, p2, p3, p4 = self._points()
        mid = (p0[0] + p4[0]) / 2
        if x < (p0[0] + p1[0]) / 2:
            return "attack", p0, p1
        if x < (p1[0] + p2[0]) / 2 or (x < mid and y <= p1[1] + 12):
            return "decay", p1, p2
        if x < (p2[0] + p3[0]) + 2:
            return "sustain", p2, p3
        return "release", p3, p4

    def _press(self, event) -> str:
        if self.on_segment is None:
            return "break"
        self._dragging = True
        self._motion(event)
        return "break"

    def _motion(self, event) -> None:
        if not self._dragging or self.on_segment is None:
            return
        key, _a, _b = self._segment_at(event.x, event.y)
        norm = _clamp((self.height - 6 - event.y) / (self.height - 12))
        self._vals[key] = norm
        self._paint()
        self.on_segment(key, norm)

    def _release(self, _event) -> None:
        self._dragging = False

    def _paint(self) -> None:
        self.delete("all")
        p0, p1, p2, p3, p4 = self._points()
        self.create_line(*p0, *p1, *p2, *p3, *p4, fill="#7aa2ff", width=2)
        self.create_line(p0[0], p0[1], p4[0], p4[1], fill="#3b3d40")
        for pt in (p1, p2, p4):
            self.create_oval(pt[0] - 2, pt[1] - 2, pt[0] + 2, pt[1] + 2,
                             fill="#cdd6f4", outline="")
        self.create_text(4, self.height + 8, anchor="w", text=self.title,
                         fill=MUTED, font=("TkDefaultFont", 7, "bold"))
        self.create_text(self.width - 4, self.height + 8, anchor="e",
                         text="visual approximation", fill="#5f6368",
                         font=("TkDefaultFont", 6, "italic"))


class FilterView(tk.Canvas):
    """Approximate low-pass response visualization.

    Deliberately schematic: cutoff moves the knee, resonance adds a visible
    bump.  No claim of analog accuracy — the JT-4000M filter response was
    never measured offline.
    """

    def __init__(self, parent, *, width: int = 150, height: int = 56) -> None:
        super().__init__(parent, width=width, height=height + 14, bg="#17181a",
                         highlightthickness=1, highlightbackground="#3b3d40", bd=0)
        self.width = width
        self.height = height
        self._cutoff = 0.5
        self._reso = 0.0
        self._paint()

    def set_values(self, cutoff: int, resonance: int) -> None:
        self._cutoff = _clamp(cutoff / 127.0)
        self._reso = _clamp(resonance / 127.0)
        self._paint()

    def _paint(self) -> None:
        self.delete("all")
        w, h = self.width, self.height
        knee_x = 6 + (w - 12) * self._cutoff
        bump = 1 + 3.5 * self._reso
        pts: list[float] = []
        n = 48
        for i in range(n + 1):
            x = 6 + (w - 12) * i / n
            t = (x - 6) / max(1.0, knee_x - 6)
            if t <= 1.0:
                y = 8 + 2 * math.sin(min(t, 1.0) * math.pi) * bump * 6
            else:
                atten = min(1.0, (t - 1.0) / 3.0)
                y = 10 + atten * (h - 22)
            pts += [x, y]
        self.create_line(*pts, fill="#ffb74d", width=2, smooth=False)
        self.create_line(6, h - 6, w - 6, h - 6, fill="#3b3d40")
        self.create_text(4, h + 7, anchor="w", text="FILTER", fill=MUTED,
                         font=("TkDefaultFont", 7, "bold"))
        self.create_text(w - 4, h + 7, anchor="e", text="approx.", fill="#5f6368",
                         font=("TkDefaultFont", 6, "italic"))


class MixBar(tk.Frame):
    """OSC1 ↔ OSC2 balance strip (visualization of osc_balance)."""

    def __init__(self, parent, *, width: int = 150, on_change=None) -> None:
        super().__init__(parent, bg=BG)
        self.width = width
        self.on_change = on_change
        self.canvas = tk.Canvas(self, width=width, height=26, bg="#17181a",
                                highlightthickness=1, highlightbackground="#3b3d40",
                                bd=0)
        self.canvas.pack(fill="x")
        self._pos = 0.5
        self.canvas.bind("<ButtonPress-1>", self._set_from_event)
        self.canvas.bind("<B1-Motion>", self._set_from_event)
        self._paint()

    def set_value(self, raw: int) -> None:
        self._pos = _clamp(raw / 127.0)
        self._paint()

    def _set_from_event(self, event) -> str:
        pos = _clamp((event.x - 4) / (self.width - 8))
        self._pos = pos
        self._paint()
        if self.on_change is not None:
            self.on_change(int(round(pos * 127)))
        return "break"

    def _paint(self) -> None:
        c = self.canvas
        c.delete("all")
        w = self.width
        x = 4 + (w - 8) * self._pos
        c.create_line(4, 13, w - 4, 13, fill="#3b3d40", width=3)
        c.create_line(4, 13, x, 13, fill="#7aa2ff", width=3)
        c.create_oval(x - 5, 8, x + 5, 18, fill="#cdd6f4", outline="")
        c.create_text(6, 4, anchor="w", text="OSC1", fill=MUTED,
                      font=("TkDefaultFont", 6, "bold"))
        c.create_text(w - 6, 4, anchor="e", text="OSC2", fill=MUTED,
                      font=("TkDefaultFont", 6, "bold"))
