#!/usr/bin/env python3
"""Capture repeatable Tkinter UI screenshots and widget geometry as JSON.

Run under a display server, e.g.:
  xvfb-run -a -s "-screen 0 1400x900x24" python tools/capture_ui_review.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import ImageGrab

from jt4000m.gui import Editor


SIZES = ((900, 700), (900, 600), (900, 560), (900, 500))


def widget_record(widget: tk.Misc, root: tk.Tk) -> dict:
    try:
        widget.update_idletasks()
        x, y = widget.winfo_rootx() - root.winfo_rootx(), widget.winfo_rooty() - root.winfo_rooty()
        width, height = widget.winfo_width(), widget.winfo_height()
        mapped = bool(widget.winfo_ismapped())
        record = {
            "path": str(widget),
            "class": widget.winfo_class(),
            "widget_name": widget.winfo_name(),
            "mapped": mapped,
            "x": x, "y": y, "width": width, "height": height,
            "right": x + width, "bottom": y + height,
        }
        if mapped and width > 1 and height > 1:
            record["outside_window"] = (
                x < 0 or y < 0 or x + width > root.winfo_width()
                or y + height > root.winfo_height()
            )
        else:
            record["outside_window"] = False
        return record
    except tk.TclError as exc:
        return {"path": str(widget), "error": str(exc)}


def collect_widgets(widget: tk.Misc, root: tk.Tk, out: list[dict]) -> None:
    out.append(widget_record(widget, root))
    for child in widget.winfo_children():
        collect_widgets(child, root, out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-visual-review"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    app = Editor()
    app.withdraw()
    cases = []
    failures = []
    try:
        for width, height in SIZES:
            app.geometry(f"{width}x{height}+0+0")
            app.deiconify()
            app.update()
            app.update_idletasks()
            # Let Tk finish idle geometry propagation and short animation callbacks.
            app.after(150, app.quit)
            app.mainloop()
            app.update_idletasks()
            actual = {"width": app.winfo_width(), "height": app.winfo_height()}
            widgets: list[dict] = []
            collect_widgets(app, app, widgets)
            visible = [w for w in widgets if w.get("mapped") and not w.get("error")]
            outside = [w for w in visible if w.get("outside_window")]
            screenshot = args.output / f"ui-{width}x{height}.png"
            ImageGrab.grab().save(screenshot)
            case = {
                "requested_size": {"width": width, "height": height},
                "actual_size": actual,
                "screenshot": screenshot.name,
                "visible_widget_count": len(visible),
                "widgets_outside_window_count": len(outside),
                "widgets_outside_window": outside,
                "widgets": widgets,
            }
            cases.append(case)
            if actual != {"width": width, "height": height}:
                failures.append(f"Requested {width}x{height}, got {actual['width']}x{actual['height']}")
            # The window has a fixed minimum width; compact-height cases must remain reachable.
            if actual["width"] != 900:
                failures.append(f"Window width changed unexpectedly at {width}x{height}: {actual['width']}")
            app.withdraw()
            app.update_idletasks()
    finally:
        try:
            app.destroy()
        except tk.TclError:
            pass

    report = {
        "schema_version": 1,
        "application": "JT-4000M Studio",
        "python": sys.version,
        "display": "virtual display (GitHub Actions)",
        "sizes_tested": [f"{w}x{h}" for w, h in SIZES],
        "checks": {
            "requested_window_size_reached": not failures,
            "widget_geometry_is_recorded": True,
            "out_of_window_widgets_are_reported_not_yet_fatal": True,
        },
        "failures": failures,
        "cases": cases,
    }
    report_path = args.output / "geometry-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(report_path),
        "screenshots": [case["screenshot"] for case in cases],
        "failures": failures,
        "out_of_window_counts": {
            f"{case['requested_size']['width']}x{case['requested_size']['height']}":
                case["widgets_outside_window_count"] for case in cases
        },
    }, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
