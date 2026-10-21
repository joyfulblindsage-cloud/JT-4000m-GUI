# GUI visual review artifacts

The GitHub Actions workflow `GUI visual review` launches the real Tkinter editor in a virtual X display and captures four window sizes:

- 900×700 — baseline
- 900×600
- 900×560
- 900×500 — compact-height limit

Each run uploads the `JT4000M-UI-Visual-Review` artifact, containing PNG screenshots cropped to the application window and `geometry-report.json`. The JSON records each widget's Tk path, class, mapped state, position, size, whether its bounding box extends beyond the top-level window, and mapped ancestors whose bounds the widget exceeds.

## Reading the report

- `failures` currently covers failure to reach the requested window dimensions.
- `widgets_outside_window` and `widgets_clipped_by_ancestors` are diagnostic lists for general widgets. Border/padding geometry can create small apparent overlaps; the ancestor check ignores overflows of 2 px or less. The ADSR and LFO control-specific checks are hard failures if a critical control or reset affordance is unmapped, outside the window, or clipped by an ancestor.
- These are automated geometry/screenshot artifacts, not a pixel-perfect golden-image test. Font rendering can vary across environments.

## Local run

From `gui 1/` with the project and Pillow installed:

```bash
xvfb-run -a -s "-screen 0 1400x900x24" python tools/capture_ui_review.py --output artifacts/ui-visual-review
```
