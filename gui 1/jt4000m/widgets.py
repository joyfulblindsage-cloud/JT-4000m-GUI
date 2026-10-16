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

BG = "#131D2B"
FG = "#DCE8F5"
MUTED = "#8CA2BA"
ACCENT = "#42D9FF"


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
    on_gesture_start: callable()   — P1.35: fired once at the beginning of a
                             continuous user gesture (mouse press).  The GUI
                             opens one undo session there, exactly like the
                             ButtonPress binding of a tk.Scale.
    on_gesture_end  : callable()   — P1.35: fired once when the gesture ends
                             (mouse release); the GUI closes the undo session.
                             Wheel/arrow/Home-End edits are discrete and never
                             open a gesture (they keep the ordinary one-step
                             path, mirroring Scale keyboard behavior).
    """

    STEP_COARSE = 4          # wheel / arrow step, in normalized units
    STEP_FINE = 1.0          # wheel / arrow step, in raw units (fine mode)
    START_ANGLE = 270.0      # minimum pointer sits at 6 o'clock
    SWEEP_DEGREES = 240.0    # synth-style arc; deliberately not a full turn
    ARC_STEP_DEGREES = 5.0   # fewer canvas points keeps Windows dragging light
    DRAG_PIXELS_PER_RANGE = 180.0

    def __init__(self, parent, *, label: str, minimum: int = 0, maximum: int = 127,
                 diameter: int = 58, on_change=None, on_reset=None,
                 default_raw: int = 0, show_entry: bool = True,
                 on_gesture_start=None, on_gesture_end=None,
                 start_angle: float = 270.0, sweep_degrees: float = 240.0,
                 angle_direction: int = -1) -> None:
        height = diameter + 34 if not show_entry else diameter + 52
        super().__init__(parent, width=diameter + 8, height=height, bg=BG,
                         highlightthickness=0, bd=0)
        self.label = label
        self.minimum = minimum
        self.maximum = max(minimum + 1, maximum)
        self.on_change = on_change
        self.on_reset = on_reset
        self.on_gesture_start = on_gesture_start
        self.on_gesture_end = on_gesture_end
        self.default_raw = default_raw
        # Configurable arc geometry lets compact ADSR knobs use a top-right
        # minimum and lower-left maximum without changing existing knob feel.
        self.start_angle = float(start_angle)
        self.sweep_degrees = max(1.0, min(300.0, float(sweep_degrees)))
        self.angle_direction = 1 if angle_direction >= 0 else -1
        self._d = diameter
        self._cx = (diameter + 8) / 2
        self._cy = diameter / 2 + 2
        self._r = diameter / 2 - 6
        self._norm = 0.0            # last painted position
        self._drag_last: tuple[int, int] | None = None
        self._gesture_active = False    # P1.35: continuous drag session flag
        self._focused = False
        self._hover = False

        if show_entry:
            self.entry = tk.Entry(parent, width=12, bg="#0D1521", fg=FG,
                                  insertbackground=FG, relief="flat",
                                  highlightthickness=1, highlightbackground="#2A3A4F")
            self.entry.bind("<Return>", self._entry_apply)
            self.entry.bind("<FocusIn>", lambda _e: self.entry.configure(
                highlightbackground=ACCENT))
            self.entry.bind("<FocusOut>", lambda _e: self.entry.configure(
                highlightbackground="#2A3A4F"))
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
        # P1.35: open one continuous undo session per mouse gesture, exactly
        # like the ButtonPress binding of a tk.Scale in gui.py.
        if not self._gesture_active:
            self._gesture_active = True
            if self.on_gesture_start is not None:
                self.on_gesture_start()
        return "break"

    def _release(self, _event) -> None:
        self._drag_last = None
        # P1.35: close the undo session on release (fires once per gesture).
        if self._gesture_active:
            self._gesture_active = False
            if self.on_gesture_end is not None:
                self.on_gesture_end()

    def _drag(self, event) -> str:
        if self._drag_last is None:
            return "break"
        # Synth/VST-style control: vertical movement is the single source of
        # drag delta. Mixing dx and dy made diagonal/vertical motions feel
        # inconsistent and could reverse/halve a movement unexpectedly.
        dy = self._drag_last[1] - event.y_root
        fine = bool(event.state & 0x0001)          # Shift held = precision
        pixels_per_range = self.DRAG_PIXELS_PER_RANGE * (4.0 if fine else 1.0)
        self._emit_norm(self._norm + dy / pixels_per_range)
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
        """Paint in-place; dragging must not delete/recreate every canvas item."""
        cx, cy, r = self._cx, self._cy, self._r
        if not hasattr(self, "_ring_item"):
            self._ring_item = self.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline="#2A3A4F", width=2, fill="#0D1521")
            self._arc_item = self.create_line(
                cx, cy, cx, cy, fill=ACCENT, width=3, cap="butt")
            self._pointer_item = self.create_line(
                cx, cy, cx, cy, fill="#F3F7FF", width=2)
            self._label_item = self.create_text(
                cx, cy + r + 12, text=self.label, fill=MUTED,
                font=("TkDefaultFont", 8, "bold"))
        ring = ACCENT if self._focused else ("#55718D" if self._hover else "#2A3A4F")
        self.itemconfigure(self._ring_item, outline=ring)
        # Map values across a bounded, configurable arc. Defaults preserve
        # the original knob geometry; ADSR columns can choose their own arc.
        a0 = self.start_angle
        a1 = self.start_angle + self.angle_direction * self.sweep_degrees * self._norm
        steps = max(2, int(abs(a1 - a0) / self.ARC_STEP_DEGREES))
        pts: list[float] = []
        for i in range(steps + 1):
            ang = math.radians(a0 + (a1 - a0) * i / steps)
            pts.extend((cx + (r - 1) * math.cos(ang),
                        cy - (r - 1) * math.sin(ang)))
        self.coords(self._arc_item, *pts)
        ang = math.radians(a1)
        self.coords(self._pointer_item, cx, cy,
                     cx + (r - 8) * math.cos(ang),
                     cy - (r - 8) * math.sin(ang))


class EnvelopeView(tk.Canvas):
    """ADSR curve visualization.

    Pure presentation: normalized visual mapping of four 0..127 registry
    values.  This is explicitly NOT a hardware-accurate envelope simulation —
    time/value relationships were never established offline, so segments use
    equal-width layout and honest labels.
    """

    def __init__(self, parent, *, title: str, width: int = 150, height: int = 64,
                 on_segment=None) -> None:
        super().__init__(parent, width=width, height=height + 16, bg="#0D1521",
                         highlightthickness=1, highlightbackground="#2A3A4F", bd=0)
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
        self.bind("<Configure>", self._on_resize)
        self._paint()

    def _on_resize(self, event) -> None:
        # Draw from the real client area, not the requested constructor size.
        width = max(80, int(event.width))
        height = max(42, int(event.height) - 16)
        if width == self.width and height == self.height:
            return
        self.width, self.height = width, height
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
        """Return ADSR points with all four values represented visually.

        The actual JT-4000M time curves are not calibrated, so attack/decay/
        release values control relative segment widths (larger = longer),
        while sustain controls the held level.  This is a readable schematic,
        not a claim of hardware-accurate timing.
        """
        w, h = self.width, self.height
        pad = 8
        x0, x_end = pad, max(pad + 4, w - pad)
        y_base, y_top = h - pad, pad
        usable = x_end - x0
        # A non-zero floor keeps every segment visible at parameter value 0.
        weights = [
            0.12 + self._vals["attack"],
            0.12 + self._vals["decay"],
            1.0,  # visible sustain/hold interval
            0.12 + self._vals["release"],
        ]
        total = sum(weights)
        widths = [usable * weight / total for weight in weights]
        x1 = x0 + widths[0]
        x2 = x1 + widths[1]
        x3 = x2 + widths[2]
        level = y_base - (y_base - y_top) * self._vals["sustain"]
        return ((x0, y_base), (x1, y_top), (x2, level),
                (x3, level), (x_end, y_base))

    def _segment_at(self, x: float, y: float):
        """Return the nearest ADSR segment and its editable parameter."""
        p0, p1, p2, p3, p4 = self._points()
        if x < p1[0]:
            return "attack", p0, p1
        if x < p2[0]:
            return "decay", p1, p2
        if x < p3[0]:
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
        key, a, b = self._segment_at(event.x, event.y)
        if key == "sustain":
            norm = _clamp((self.height - 8 - event.y) / max(1, self.height - 16))
        else:
            # Time controls are represented horizontally; vertical movement
            # alone must not accidentally alter Attack/Decay/Release.
            norm = _clamp((event.x - a[0]) / max(1.0, b[0] - a[0]))
        self._vals[key] = norm
        self._paint()
        self.on_segment(key, norm)

    def _release(self, _event) -> None:
        self._dragging = False

    def _paint(self) -> None:
        self.delete("all")
        p0, p1, p2, p3, p4 = self._points()
        self.create_line(*p0, *p1, *p2, *p3, *p4, fill="#47D8F5", width=2)
        self.create_line(p0[0], p0[1], p4[0], p4[1], fill="#2A3A4F")
        for pt in (p1, p2, p4):
            self.create_oval(pt[0] - 2, pt[1] - 2, pt[0] + 2, pt[1] + 2,
                             fill="#EAF7FF", outline="")
        self.create_text(4, self.height + 8, anchor="w", text=self.title,
                         fill=MUTED, font=("TkDefaultFont", 7, "bold"))
        self.create_text(self.width - 4, self.height + 8, anchor="e",
                         text="visual approximation", fill="#71859B",
                         font=("TkDefaultFont", 6, "italic"))


class FilterView(tk.Canvas):
    """Approximate low-pass response visualization.

    Deliberately schematic: cutoff moves the knee, resonance adds a visible
    bump.  No claim of analog accuracy — the JT-4000M filter response was
    never measured offline.
    """

    def __init__(self, parent, *, width: int = 150, height: int = 56) -> None:
        super().__init__(parent, width=width, height=height + 14, bg="#0D1521",
                         highlightthickness=1, highlightbackground="#2A3A4F", bd=0)
        self.width = width
        self.height = height
        self._cutoff = 0.5
        self._reso = 0.0
        self.bind("<Configure>", self._on_resize)
        self._paint()

    def _on_resize(self, event) -> None:
        # Canvas includes a fixed caption band below the response curve.
        width = max(100, int(event.width))
        height = max(42, int(event.height) - 14)
        if width == self.width and height == self.height:
            return
        self.width, self.height = width, height
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
        self.create_line(*pts, fill="#FFB454", width=2, smooth=False)
        self.create_line(6, h - 6, w - 6, h - 6, fill="#2A3A4F")
        self.create_text(4, h + 7, anchor="w", text="FILTER", fill=MUTED,
                         font=("TkDefaultFont", 7, "bold"))
        self.create_text(w - 4, h + 7, anchor="e", text="approx.", fill="#71859B",
                         font=("TkDefaultFont", 6, "italic"))


class MixBar(tk.Frame):
    """OSC1 ↔ OSC2 balance strip (visualization of osc_balance)."""

    def __init__(self, parent, *, width: int = 150, on_change=None) -> None:
        super().__init__(parent, bg=BG)
        self.width = width
        self.on_change = on_change
        self.canvas = tk.Canvas(self, width=width, height=26, bg="#0D1521",
                                highlightthickness=1, highlightbackground="#2A3A4F",
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
        c.create_line(4, 13, w - 4, 13, fill="#2A3A4F", width=3)
        c.create_line(4, 13, x, 13, fill="#47D8F5", width=3)
        c.create_oval(x - 5, 8, x + 5, 18, fill="#EAF7FF", outline="")
        c.create_text(6, 4, anchor="w", text="OSC1", fill=MUTED,
                      font=("TkDefaultFont", 6, "bold"))
        c.create_text(w - 6, 4, anchor="e", text="OSC2", fill=MUTED,
                      font=("TkDefaultFont", 6, "bold"))
