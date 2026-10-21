"""P1.70 — oscillator controls stay visible in compact synth layouts."""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    _HAS_DISPLAY = True
except tk.TclError:
    _HAS_DISPLAY = False

gui_test = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")


@pytest.mark.parametrize("height", [500, 560, 600, 700])
@gui_test
def test_oscillator_controls_remain_visible_and_inside_panel(height):
    from jt4000m.gui import Editor

    app = Editor()
    try:
        app.geometry(f"900x{height}+0+0")
        app.update()
        expected = {
            "osc1_pwm_fm", "osc1_coarse", "osc1_fine",
            "osc2_pwm", "osc2_coarse", "osc2_fine",
        }
        assert expected <= set(app.section_labels)
        assert expected <= set(app.reset_buttons)

        for key in sorted(expected):
            label = app.section_labels[key]
            controls = label.master.master
            panel = controls.master
            scale = next(
                child for child in label.master.winfo_children()
                if isinstance(child, tk.Scale)
            )
            reset = app.reset_buttons[key][0]
            for role, widget in (("label", label), ("scale", scale), ("reset", reset)):
                app.update_idletasks()
                assert widget.winfo_ismapped(), f"{height}px: {key} {role} is not mapped"
                left, top = panel.winfo_rootx(), panel.winfo_rooty()
                right = left + panel.winfo_width()
                bottom = top + panel.winfo_height()
                wleft, wtop = widget.winfo_rootx(), widget.winfo_rooty()
                wright = wleft + widget.winfo_width()
                wbottom = wtop + widget.winfo_height()
                assert wleft >= left - 2, f"{height}px: {key} {role} clipped on left"
                assert wtop >= top - 2, f"{height}px: {key} {role} clipped on top"
                assert wright <= right + 2, f"{height}px: {key} {role} clipped on right"
                assert wbottom <= bottom + 2, f"{height}px: {key} {role} clipped on bottom"
    finally:
        app.destroy()
