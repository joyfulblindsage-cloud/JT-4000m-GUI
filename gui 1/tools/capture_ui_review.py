#!/usr/bin/env python3
"""Capture repeatable Tkinter screenshots and widget geometry as JSON.

Run under a display server, e.g.:
  xvfb-run -a -s "-screen 0 1400x900x24" python tools/capture_ui_review.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import tkinter as tk

from PIL import ImageGrab

from jt4000m.gui import Editor


SIZES = ((900, 700), (900, 600), (900, 560), (900, 500))
EDGE_TOLERANCE_PX = 2


def bounds(widget: tk.Misc) -> tuple[int, int, int, int]:
    """Return widget bounds in absolute screen coordinates."""
    return (
        widget.winfo_rootx(),
        widget.winfo_rooty(),
        widget.winfo_rootx() + widget.winfo_width(),
        widget.winfo_rooty() + widget.winfo_height(),
    )


def widget_record(widget: tk.Misc, root: tk.Tk) -> dict:
    try:
        widget.update_idletasks()
        root_x, root_y, right, bottom = bounds(widget)
        root_left, root_top, root_right, root_bottom = bounds(root)
        x, y = root_x - root_left, root_y - root_top
        width, height = right - root_x, bottom - root_y
        mapped = bool(widget.winfo_ismapped())
        record = {
            "path": str(widget),
            "class": widget.winfo_class(),
            "widget_name": widget.winfo_name(),
            "mapped": mapped,
            "x": x, "y": y, "width": width, "height": height,
            "right": x + width, "bottom": y + height,
            "outside_window": bool(
                mapped and width > 1 and height > 1 and (
                    x < 0 or y < 0 or x + width > root.winfo_width()
                    or y + height > root.winfo_height()
                )
            ),
            "clipped_by_ancestors": [],
        }

        # A child may fit inside the top-level window but still be cut off by
        # an intermediate Frame. Record every mapped ancestor it exceeds.
        if mapped and width > 1 and height > 1:
            ancestor = widget.winfo_parent()
            while ancestor:
                parent = widget.nametowidget(ancestor)
                if parent == widget:
                    break
                if parent.winfo_ismapped() and parent != root:
                    pl, pt, pr, pb = bounds(parent)
                    overflow = {
                        "left": max(0, pl - root_x),
                        "top": max(0, pt - root_y),
                        "right": max(0, right - pr),
                        "bottom": max(0, bottom - pb),
                    }
                    if any(value > EDGE_TOLERANCE_PX for value in overflow.values()):
                        record["clipped_by_ancestors"].append({
                            "path": str(parent),
                            "class": parent.winfo_class(),
                            "overflow_px": overflow,
                        })
                if parent == root:
                    break
                ancestor = parent.winfo_parent()
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
            app.after(150, app.quit)
            app.mainloop()
            app.update_idletasks()

            actual = {"width": app.winfo_width(), "height": app.winfo_height()}
            widgets: list[dict] = []
            collect_widgets(app, app, widgets)
            visible = [w for w in widgets if w.get("mapped") and not w.get("error")]
            outside = [w for w in visible if w.get("outside_window")]
            clipped = [w for w in visible if w.get("clipped_by_ancestors")]

            # Critical ADSR controls are a release gate, unlike low-priority
            # decorative/read-only content. Check the knob, its label and reset
            # affordance separately so ancestor clipping cannot silently pass.
            critical_keys = (
                "vca_attack", "vca_decay", "vca_sustain", "vca_release",
                "vcf_attack", "vcf_decay", "vcf_sustain", "vcf_release",
                "filter_env_amount",
            )
            critical_records = []
            for key in critical_keys:
                knob = app._knobs.get(key)
                label = app.section_labels.get(key)
                reset_pair = app.reset_buttons.get(key)
                critical_widgets = [("knob", knob), ("label", label)]
                if reset_pair:
                    critical_widgets.append(("reset", reset_pair[0]))
                for part, widget in critical_widgets:
                    if widget is None:
                        failures.append(f"{width}x{height}: missing critical {part} for {key}")
                        continue
                    record = widget_record(widget, app)
                    record["parameter"] = key
                    record["role"] = part
                    critical_records.append(record)
                    if not record.get("mapped"):
                        failures.append(f"{width}x{height}: critical {part} for {key} is not mapped")
                    if record.get("outside_window"):
                        failures.append(f"{width}x{height}: critical {part} for {key} is outside window")
                    if record.get("clipped_by_ancestors"):
                        failures.append(f"{width}x{height}: critical {part} for {key} is clipped by an ancestor")

            # Crop to the actual application window, not the full virtual desktop.
            left, top, right, bottom = bounds(app)
            screenshot = args.output / f"ui-{width}x{height}.png"
            ImageGrab.grab(bbox=(left, top, right, bottom)).save(screenshot)
            cases.append({
                "requested_size": {"width": width, "height": height},
                "actual_size": actual,
                "screenshot": screenshot.name,
                "visible_widget_count": len(visible),
                "widgets_outside_window_count": len(outside),
                "widgets_outside_window": outside,
                "widgets_clipped_by_ancestors_count": len(clipped),
                "widgets_clipped_by_ancestors": clipped,
                "critical_adsr_controls": critical_records,
                "widgets": widgets,
            })

            if actual != {"width": width, "height": height}:
                failures.append(f"Requested {width}x{height}, got {actual['width']}x{actual['height']}")
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
        "schema_version": 2,
        "application": "JT-4000M Studio",
        "python": sys.version,
        "display": "virtual display (GitHub Actions)",
        "sizes_tested": [f"{w}x{h}" for w, h in SIZES],
        "checks": {
            "requested_window_size_reached": not failures,
            "widget_geometry_is_recorded": True,
            "out_of_window_widgets_are_reported_not_yet_fatal": True,
            "ancestor_clipping_is_reported_not_yet_fatal": True,
            "critical_adsr_controls_must_be_mapped_and_unclipped": True,
            "screenshots_are_cropped_to_application_window": True,
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
        "ancestor_clipping_counts": {
            f"{case['requested_size']['width']}x{case['requested_size']['height']}":
                case["widgets_clipped_by_ancestors_count"] for case in cases
        },
    }, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
