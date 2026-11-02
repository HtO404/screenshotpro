---
name: screenshot-pro
description: Produce verified annotated screenshots of a Windows app UI. Measure control rectangles with UI Automation (never estimate them), write a JSON spec of targets, render boxes/badges/arrows/pixelation plus a legend bar, and accept the figure only when the 15-assertion verifier exits 0.
whenToUse: Use when the task asks for a screenshot with callouts, numbered steps, redacted fields or an operation-order figure of a desktop application — especially when the result must be proved correct rather than merely look right.
---

# screenshot-pro

You are producing a **documentation figure**, not art. The figure has to be right about
one thing: **which pixel rectangle belongs to which UI control**. That is measured, or the
figure is worthless.

## The iron rule

> **Coordinates are MEASURED, never estimated.**

Every rectangle in the output comes from `dump.json`, which `tools/measure_win.py` produced
by reading UI Automation. You never type a coordinate, never recompute one, never round one,
never scale one, and never nudge one because the box looks tight. Your spec names a control;
the machine supplies the numbers.

Two consequences you will feel immediately:

- If a control is missing from `dump.json`, it **cannot** be annotated. Report it as a
  measurement gap. Do not invent a rectangle for it.
- If a box looks wrong, the defect is upstream (capture, DPI, wrong window). Re-measure.
  Do not patch the picture.

## Outputs of a successful run

```text
figures/<name>/
  shot.png            the captured window, unmodified
  dump.json           every UIA control with screen_rect + image_rect
  measure-log.txt     launch, capture check, per-control readback
  spec.json           what you wrote: targets, labels, redactions
  out/<name>.png      the figure
  out/render-report.json   what was actually drawn (machine-checkable)
```

## Three commands

```bash
# 1. measure  (Windows; needs the app's exe path)
python tools/measure_win.py --exe "C:/path/to/App.exe" --out figures/<name>

# 2. annotate (after you write figures/<name>/spec.json)
python tools/render.py figures/<name>/spec.json

# 3. verify  (exit 0 == every assertion passed)
python tools/verify.py figures/<name>/spec.json
```

Useful flags:

| Flag | Use |
|---|---|
| `--wait N` | seconds to wait after launch before capture (default 6; raise it for slow apps) |
| `--require-name "Save"` | assert a control name exists and lies inside the shot; repeatable |
| `--log <path>` | write the measurement log elsewhere |
| `verify.py ... --report <path>` | point the verifier at a specific `render-report.json` |

Always read `measure-log.txt` after step 1. It is the only place that tells you whether the
capture is trustworthy (`capture_check.mean_abs_diff`, `suggested_offset`, negative-control
diff). A warning there is a measurement problem; annotating over it produces a confident,
wrong figure.

## Step 2 in detail: writing `spec.json`

Schema is fixed: `"schema": "annot-spec/1"`. Paths are resolved relative to the spec file.

| Field | Type | Default | Notes |
|---|---|---|---|
| `schema` | string | required | must be exactly `annot-spec/1` |
| `dump` | path | required | normally `"dump.json"` beside the spec |
| `shot` | path | `dump.shot.file` | normally `"shot.png"` beside the spec |
| `figure` | string | `""` | free label copied into the report |
| `output` | path | required | e.g. `"out/<name>.png"`; folders are created |
| `steps[]` | list | required | ordered; badge numbers default to 1..n |
| `steps[].n` | int | list order | badge number **and** legend row id — keep them unique |
| `steps[].target` | object | required | selector, see below |
| `steps[].label` | string | `""` | legend row text; empty = this step gets no legend row |
| `steps[].box` | bool | `true` | highlight box around the control |
| `steps[].arrow` | bool | `true` | arrow from the badge to the box edge |
| `redact[]` | list | `[]` | `{"target": {...}, "mode": "pixelate", "block": 12}` |
| `legend.enabled` | bool | `true` | append the legend bar under the screenshot |
| `legend.title` | string | `""` | legend heading |
| `legend.max_text_w` | int/null | `null` | wrap width for legend text |
| `style.*` | object | see below | overrides the visual defaults |

### Selectors

A selector is an object with **exactly one** of these keys, compared for equality against
the controls in `dump.json`:

| Key | Pick it when |
|---|---|
| `automation_id` | always first choice — stable across languages and renames |
| `name` | the visible label is unique and stable |
| `path` | the tree position is the only stable identity (e.g. `/Pane[1]/Tree[1]/Button[1]`) |
| `index` | last resort, and only if you re-read `dump.json` in the same session |

The selector must match **exactly one** control. Zero or two matches is a hard error from
the renderer (assertion 1), which is the cheapest possible place to catch a mistake.

How to find a selector: open `dump.json`, filter `controls[]` by the `name` you can already
see in the screenshot, then take that control's `automation_id` (or `path`) rather than its
coordinates.

### Style defaults you may override in `style`

`font_path` (default `C:/Windows/Fonts/msyhbd.ttc`), `font_index`, `font_size`, `badge_fill`,
`badge_text`, `badge_radius`, `box_color`, `box_width`, `box_pad`, `arrow_width`,
`arrow_head_len`, `arrow_head_w`, `min_gap`.

## Step 3 output: `render-report.json`

The renderer writes down everything it drew — `target_index`, `image_rect`, `box_rect`,
`badge {cx, cy, r, overlap_controls, overlap_ratio}`, `arrow {x1, y1, x2, y2}`, the redaction
rects, and `legend.rows`. The verifier checks the renderer against the dump; you never write
this file.

## The 15 assertions, and what each one protects

`verify.py` prints one row per assertion. Read a FAIL as a diagnosis, not an obstacle —
every row exists because that mistake actually produces a plausible-looking wrong figure.

| # | Assertion (as printed) | What it stops |
|---|---|---|
| 1 | 每个 target selector 恰好命中 1 条 | a mistyped or ambiguous selector silently annotating the wrong widget |
| 2 | `image_rect` 完全落在 shot 内 | a box hanging off the canvas edge |
| 3 | report 的 `image_rect` 与 dump 逐字段相等 | a second coordinate conversion (offset/scale) creeping into the renderer |
| 4 | 输出 PNG 宽度 == 输入宽度 | the screenshot being resized on the way out |
| 5 | 徽标两两不重叠（圆心距 >= 2r） | two step numbers merging into an unreadable blob |
| 6a | 徽标与控件重叠面积 / 徽标面积 <= 阈值 | a badge covering the exact text it points at |
| 6b | `overlap_controls` 与实际遮挡一致 | under-reporting occlusion instead of fixing it |
| 6c | 徽标不落在其它步骤的框内 | a number visually attributed to the wrong step |
| 7 | 箭头终点到自己目标框边界 <= 容差 | an arrow whose tip points at empty space |
| 8 | 被标注区域像素 std > 阈值 | **a box over blank pixels — the signature of an estimated coordinate** |
| 9 | 退出码约定（全过 0 / 任一失败 1） | CI turning green on a broken figure |
| 10 | 有 label 时高度 == shot.h + legend.height，宽度不变 | the legend shifting or rescaling the screenshot |
| 11 | `legend.rows` 的 n 集合 == 带 label 的 steps | a missing, duplicated or orphaned legend row |
| 12 | 图例文本非空且宽度 <= 画布宽 - 2*pad_x | text running off the canvas |
| 13 | `legend.height` 容得下所有行 | a clipped last legend row |

(Assertion 9 is the exit-code contract and prints `PASS` unless an earlier row failed.)

## Failure playbook

| Symptom | Real cause | Fix |
|---|---|---|
| 1 fails, 0 hits | control is not in the UIA tree (custom-drawn UI, different window) | report it as a measurement gap, or re-measure with the window actually focused |
| 1 fails, 2+ hits | selector too loose | switch to `automation_id`, or use `path` |
| 2 or 8 fails | captured window does not match the dump (moved, DPI change, wrong window) | re-measure; never shrink the box by hand |
| 3 fails | someone edited the report or scaled the shot | re-render from the untouched dump |
| 5 / 6c fail | too many steps crowded in one region | reduce steps, or move the redundant step into text |
| 6a fails | a badge sits on top of text | change the step's target region or accept fewer badges |
| 10–13 fail | legend text too long | shorten `label`, set `legend.max_text_w`, or split the figure |
| `.ttf/ttc` font error | no CJK font at the default path | pass `style.font_path` for your platform |

## Do not

- Do not hand-write or adjust `image_rect`, `box_rect`, `badge` or `arrow` anywhere.
- Do not edit `render-report.json` to satisfy the verifier.
- Do not weaken or delete an assertion to make a figure pass.
- Do not annotate a control UI Automation did not expose.
- Do not reuse an `index` selector across sessions — indexes shift.
- Do not claim a figure is correct because it looks right. Cite the PASS table.

## Before you report done

1. `python tools/render.py <spec>` exits `0`.
2. `python tools/verify.py <spec>` exits `0` with 15 rows, every one `PASS`.
3. You pasted that table (or its pass count) in your report.
4. You named anything the measurement step could not cover.

---

## 中文速查

**坐标只测不估。** 图上每个矩形都来自 `dump.json`（UI Automation 实测），你只写「标哪个控件」。

```bash
python tools/measure_win.py --exe "C:/path/to/App.exe" --out figures/<名>   # 1 测量
python tools/render.py  figures/<名>/spec.json                          # 2 出图
python tools/verify.py  figures/<名>/spec.json                          # 3 验收(exit 0 才算过)
```

selector 四选一（`automation_id` / `name` / `path` / `index`），必须唯一命中；优先
`automation_id`。测量完先读 `measure-log.txt`：capture check 有问题就是测量问题，不要在图上凑。
15 条断言里最要紧的是第 8 条——「被标注区域像素 std > 阈值」，它专门抓「框画在空白处」，
也就是**坐标是估的**这个错误。任何一条 FAIL 都是诊断，不是障碍：修因，不要改断言、
不要改 `render-report.json`。

