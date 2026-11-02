# examples

Two shapes, no images: this directory ships **no screenshots** and no captured window.
Everything below is the structure of the data the tools exchange, so you can read it without
running anything.

## `minimal-spec.json`

A complete, valid `annot-spec/1` document with two steps, one redaction and a legend. It is
meant to be copied next to a `shot.png` + `dump.json` pair and edited. Two things to change
for your own figure:

1. Every `target` must match **exactly one** control in your `dump.json`. The keys here
   (`automation_id: btnBrowse`, `automation_id: btnRun`, `automation_id: lblOutDir`) belong to
   the synthetic fixture, not to your app. Two steps on the **same** control would fail
   assertion 5 as well — badges of identical rectangles cannot be separated.
2. `label` text is what appears in the legend bar. Keep it short — assertion 12 rejects text
   wider than the canvas.

Run it with:

```bash
python tools/render.py examples/minimal-spec.json
python tools/verify.py examples/minimal-spec.json
```

(The checked-in file will not resolve without a `shot.png`/`dump.json` beside it. For a
self-contained run use `python tests/run_tests.py`, which generates its fixture in a temp
directory.)

## The minimum `dump.json` the tools accept

`tools/measure_win.py` writes the real thing; this is the smallest shape `render.py` will
consume. Only `schema`, `controls[].{index,image_rect}` and the image itself are load-bearing;
the rest is what makes a figure verifiable.

```json
{
  "schema": "uia-dump/1",
  "window": {
    "title": "Example App",
    "screen_rect": { "x": 100, "y": 100, "w": 800, "h": 600 }
  },
  "shot": { "file": "shot.png", "width": 800, "height": 600 },
  "capture_check": {
    "method": "PrintWindow+BitBlt",
    "mean_abs_diff": 0.9,
    "suggested_offset": { "dx": 0, "dy": 0 }
  },
  "controls": [
    {
      "index": 0,
      "depth": 1,
      "type": "Button",
      "name": "Browse...",
      "automation_id": "btnBrowse",
      "path": "/Pane[1]/Button[1]",
      "screen_rect": { "x": 116, "y": 152, "w": 96, "h": 40 },
      "image_rect": { "x": 16, "y": 52, "w": 96, "h": 40 }
    }
  ]
}
```

Note the contract in the last two lines: `image_rect == screen_rect - window.screen_rect`
origin, with no scaling (`window.screen_rect` w/h must equal `shot` w/h, which must equal the
PNG size). `render.py` refuses a dump where those disagree, and assertion 3 refuses a report
that drifts from the dump by even one pixel.

## Adding a real figure to this directory

Do not commit screenshots of software you are not allowed to publish, and do not commit
captures that contain personal paths, account names or real customer data. If you need a
recorded sample, add `spec.json` + `dump.json` and let `.gitignore` keep the large `shot.png`
out of the repository.

