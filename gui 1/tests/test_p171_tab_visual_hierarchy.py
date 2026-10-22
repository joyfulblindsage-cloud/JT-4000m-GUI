"""P1.71 — workspace tab selection remains visually legible."""
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


@pytest.mark.parametrize("active", ["SYNTH", "PRESETS", "RESEARCH"])
@gui_test
def test_active_workspace_tab_has_distinct_visual_state(active):
    from jt4000m.gui import Editor

    app = Editor()
    try:
        app.current_tab.set(active)
        app._switch_tab()
        for name, button in app.tab_buttons.items():
            selected = name == active
            assert button.cget("bg") == ("#17465A" if selected else "#080D14")
            assert button.cget("fg") == ("#42D9FF" if selected else "#91A7C0")
            assert button.cget("font").endswith(
                "bold" if selected else "normal"
            )
    finally:
        app.destroy()
