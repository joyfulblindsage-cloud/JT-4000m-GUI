# GUI visual review artifacts

The GitHub Actions workflow `GUI visual review` launches the real Tkinter editor in a virtual X display and captures four window sizes:

- 900×700 — baseline
- 900×600
- 900×560
- 900×500 — compact-height limit

Each run uploads the `JT4000M-UI-Visual-Review` artifact, containing PNG screenshots and `geometry-report.json`. The JSON records each widget's Tk path, class, mapped state, position, size, and whether its bounding box extends beyond the top-level window.

## Reading the report

- `failures` currently covers failure to reach the requested window dimensions.
- `widgets_outside_window` is a diagnostic list, not yet a failing assertion: some custom/overlapping widgets may intentionally draw outside their own allocated area. Review the report and screenshots before turning this into a strict gate.
- These are automated geometry/screenshot artifacts, not a pixel-perfect golden-image test. Font rendering can vary across environments.

## Local run

From `gui 1/` with the project and Pillow installed:

```bash
xvfb-run -a -s "-screen 0 1400x900x24" python tools/capture_ui_review.py --output artifacts/ui-visual-review
```
