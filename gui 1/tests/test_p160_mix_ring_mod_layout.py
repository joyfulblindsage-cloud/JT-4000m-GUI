"""P1.60 — MIX/RING and MOD/PORTAMENTO controls fit compact layouts."""
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
def test_mix_ring_and_mod_portamento_controls_fit_workspace(height):
    from jt4000m.gui import Editor

    app = Editor()
    try:
        app.geometry(f"900x{height}+0+0")
        app.update()
        expected = {
            "osc_balance", "ring_mod_toggle", "ring_mod_amount",
            "modulation", "portamento_time", "portamento_amount",
            "portamento_mode",
        }
        assert expected <= set(app.section_labels)
        assert expected <= set(app.reset_buttons)

        panel_for = {
            "osc_balance": "mix_ring",
            "ring_mod_toggle": "mix_ring",
            "ring_mod_amount": "mix_ring",
            "modulation": "mod_portamento",
            "portamento_time": "mod_portamento",
            "portamento_amount": "mod_portamento",
            "portamento_mode": "mod_portamento",
        }
        for key in sorted(expected):
            panel = app._p160_panel_frames[panel_for[key]]
            widgets = [
                ("label", app.section_labels[key]),
                ("reset", app.reset_buttons[key][0]),
            ]
            if key in app._midi_only_scales:
                widgets.append(("slider", app._midi_only_scales[key]))
            if key in app._knobs:
                widgets.append(("knob", app._knobs[key]))

            for role, widget in widgets:
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
