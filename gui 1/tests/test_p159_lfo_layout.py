"""P1.59 — compact LFO controls remain accessible at the supported window sizes."""
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


@pytest.mark.parametrize("height", [500, 700])
@gui_test
def test_lfo_controls_and_reset_affordances_fit_compact_workspace(height):
    from jt4000m.gui import Editor

    app = Editor()
    try:
        app.geometry(f"900x{height}+0+0")
        app.update()
        expected = {
            "lfo1_wave", "lfo1_destination", "lfo1_rate", "lfo1_amount",
            "lfo2_wave", "lfo2_rate", "lfo2_amount",
        }
        assert expected <= set(app._lfo_controls)
        assert expected <= set(app._lfo_reset_buttons)

        assert all(int(scale.cget("length")) >= 58 for scale in app._lfo_scales)

        for key in sorted(expected):
            panel_key = "lfo1_wave" if key.startswith("lfo1") else "lfo2_wave"
            panel = app._lfo_panel_frames[panel_key]
            for role, widget in (
                ("control", app._lfo_controls[key]),
                ("reset", app._lfo_reset_buttons[key]),
            ):
                assert widget.winfo_ismapped(), f"{height}px: {key} {role} is not mapped"
                widget.update_idletasks()
                panel.update_idletasks()
                left = panel.winfo_rootx()
                top = panel.winfo_rooty()
                right = left + panel.winfo_width()
                bottom = top + panel.winfo_height()
                wleft = widget.winfo_rootx()
                wtop = widget.winfo_rooty()
                wright = wleft + widget.winfo_width()
                wbottom = wtop + widget.winfo_height()
                assert wleft >= left - 2, f"{height}px: {key} {role} clipped on left"
                assert wtop >= top - 2, f"{height}px: {key} {role} clipped on top"
                assert wright <= right + 2, f"{height}px: {key} {role} clipped on right"
                assert wbottom <= bottom + 2, f"{height}px: {key} {role} clipped on bottom"
    finally:
        app.destroy()
