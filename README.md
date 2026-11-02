# screenshotpro

**Annotated UI screenshots whose coordinates are measured, not drawn by hand.**

You give it a Windows executable. It launches the app, captures the whole window with
`PrintWindow`, dumps the entire UI Automation control tree, and stores both. A JSON spec
then says *which* control to point at — never *where* it is. The renderer turns that into
a figure with boxes, numbered badges, arrows, pixelated secrets and a legend bar; the
verifier proves the figure with 15 assertions and exits non-zero if any of them breaks.

It ships as two things that do not depend on each other:

| Form | What you get | Needs DSH? |
|---|---|---|
| **Standalone CLI** | `python tools/render.py` + `tools/verify.py` (+ `tools/measure_win.py` on Windows) | No — Python 3.9+ and Pillow |
| **DSH plugin bundle** | A `Screenshot Pro` agent preset that mounts this skill and the tools it needs | Yes — any DSH host |

---

## The rule the whole repo is built around

> **Coordinates are measured, never estimated.**

Every rectangle comes from UI Automation data in `dump.json`. Nothing is hand-tuned,
rescaled or nudged. If a rectangle is wrong, the bug is in the measurement step — not in
the spec, and never in the renderer. This is why the pipeline can be verified at all:
assertion 3 compares the report against the dump field by field, and assertion 8 fails
when a box lands on blank pixels, which is exactly what a guessed coordinate produces.

## Capability table

| Stage | Standalone command | Reads | Writes | Contract |
|---|---|---|---|---|
| Measure | `python tools/measure_win.py --exe <app.exe> --out figures/<name>` | the running app (UI Automation) | `shot.png`, `dump.json`, `measure-log.txt` | `dump.schema = uia-dump/1`, `shot` size == window rect, `image_rect == screen_rect - window origin` |
| Annotate | `python tools/render.py figures/<name>/spec.json` | `spec.json`, `shot.png`, `dump.json` | `out/<name>.png`, `out/render-report.json` | `spec.schema = annot-spec/1`, output width == input width |
| Verify | `python tools/verify.py figures/<name>/spec.json` | the spec, the dump, the report, the rendered PNG | a PASS/FAIL table | exit `0` only when all 15 assertions pass |
| Self-test | `python tests/run_tests.py` | nothing — it builds its own synthetic fixture | fixture + figure in a temp dir | 15/15 PASS, plus a deliberately broken report that must FAIL |

Figure features: highlighted boxes with padding, numbered circular badges that avoid
collisions and refuse to cover a control, arrows from badge to box edge, `pixelate`
redaction of a measured control rect, and an auto-sized legend bar appended under the
screenshot (canvas width never changes).

## Install

### Standalone (no DSH)

```bash
git clone https://github.com/HtO404/screenshotpro.git
cd screenshotpro
python -m pip install -r requirements.txt   # Pillow; numpy only for measure_win.py
python tests/run_tests.py                   # 15/15 PASS, offline
```

Then, per figure:

```bash
python tools/measure_win.py --exe "C:/Program Files/YourApp/YourApp.exe" --out figures/main-window
# read figures/main-window/dump.json, write figures/main-window/spec.json
python tools/render.py  figures/main-window/spec.json
python tools/verify.py  figures/main-window/spec.json
```

`tools/measure_win.py` is Windows-only (PowerShell + UI Automation via `tools/uia_dump.ps1`).
The annotate and verify halves are plain Pillow code and run anywhere, including CI, on a
`shot.png` + `dump.json` pair captured on any machine.

### As a DSH plugin

`package.json` declares `dsh.bundle.patch`, and `cordis.patch.yml` inserts one agent preset
(`Screenshot Pro`) that mounts `@deepseek-ai/dsh-persona`, `@deepseek-ai/dsh-tool-skill`,
`@deepseek-ai/dsh-skill-filesystem`, a shell for the current platform, file/job/todo/ask-user
tools, and adds this repo's `skills/` directory as a skill root.

**You must edit one line before installing.** `dsh-skill-filesystem` resolves every entry of
`config.customSkillDirs` with `node:path.resolve()`, so a relative path would resolve against
the DSH host's process cwd instead of this package, and no placeholder is expanded
(source: `dsh-skill-filesystem/lib/index.js` — `customSkillDirs: z.array(z.string())` and
`(config.customSkillDirs ?? []).map((root) => resolve(root))`). Put the absolute path of
this repo's `skills/` directory there:

```yaml
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              customSkillDirs:
                - '/home/me/screenshotpro/skills'   # <- your absolute path
```

After that the preset is complete; add it to a profile like any other bundle and the
`screenshot-pro` skill appears in the session catalog.

## Minimal reproducible example

The smallest full loop needs no real application and no network. `tests/run_tests.py` does
exactly this, and you can do it by hand in three commands:

```bash
python tools/make_fixture.py /tmp/fx      # synthetic window + dump.json + spec.json
python tools/render.py       /tmp/fx/spec.json
python tools/verify.py       /tmp/fx/spec.json
```

Expected tail of the third command — fifteen rows, all `PASS`, exit code `0` (this is the
verifier's own output, verbatim; row 9 prints last because it reads the rows before it):

```text
[PASS] 1 spec 内每个 target selector 在 dump.controls 中恰好命中 1 条 -- 5 个 selector 全部唯一命中
[PASS] 2 目标 control 的 image_rect 完全落在 shot 尺寸内 -- 5 个目标均在界内
...
[PASS] 13 legend.height 容得下所有行(最大行底 <= shot.h + legend.height <= 输出高) -- legend.height 120, 画布 760
[PASS] 9 退出码约定(全过 0 / 任一失败 1) -- exit 0 (0 项失败)

结果: 15/15 断言通过 -> PASS (exit 0)
```

The spec it renders is ordinary JSON (see `examples/minimal-spec.json`):

```json
{
  "schema": "annot-spec/1",
  "figure": "main-window",
  "shot": "shot.png",
  "dump": "dump.json",
  "steps": [
    { "n": 1, "target": { "automation_id": "btnBrowse" }, "label": "Step 1: pick the input file." },
    { "n": 2, "target": { "automation_id": "btnRun" }, "label": "Step 2: start the run." }
  ],
  "redact": [ { "target": { "automation_id": "lblOutDir" }, "mode": "pixelate", "block": 12 } ],
  "legend": { "enabled": true, "title": "Operation order" },
  "output": "out/main-window.png"
}
```

## `spec.json` reference

| Field | Type | Default | Meaning |
|---|---|---|---|
| `schema` | string | required | must be `annot-spec/1` |
| `dump` | path | required | `dump.json` from the measure stage, relative to the spec |
| `shot` | path | `dump.shot.file` | the screenshot, relative to the spec |
| `figure` | string | `""` | copied into the report for traceability |
| `output` | path | required | rendered PNG, relative to the spec |
| `steps[].n` | int | 1-based order | badge number, also the legend row id |
| `steps[].target` | object | required | selector, exactly one key of `automation_id` / `name` / `path` / `index` — must match exactly one control |
| `steps[].label` | string | `""` | legend text; empty means no legend row for this step |
| `steps[].box` | bool | `true` | draw the highlight box |
| `steps[].arrow` | bool | `true` | draw the badge→box arrow |
| `redact[]` | list | `[]` | `{target, mode: "pixelate", block: 12}` — mosaic a measured control |
| `legend.enabled` | bool | `true` | append the legend bar |
| `legend.title` / `row_h` / `pad_x` / `pad_y` / `bg` / `text_color` / `max_text_w` / `font_size` | — | see `STYLE_DEFAULTS` in `tools/render.py` | legend look |
| `style.*` | — | see `tools/render.py` | `font_path`, `font_size`, `badge_fill`, `badge_radius`, `box_color`, `box_width`, `box_pad`, `arrow_width`, `min_gap`, ... |

## `dump.json` reference

| Field | Meaning |
|---|---|
| `schema` | must be `uia-dump/1` |
| `window.screen_rect` | window rect in screen pixels; its `w`/`h` must equal the image size |
| `shot` | `{file, width, height}` for `shot.png` |
| `capture_check` | `{method, overlap, mean_abs_diff, suggested_offset}` — proof the capture is not stale |
| `controls[]` | one entry per UIA node: `index`, `depth`, `type`, `name`, `automation_id`, `path`, `screen_rect`, `image_rect` |
| `controls[].image_rect` | pixels with the image top-left as origin; `== screen_rect - window origin`, never rescaled |

## The 15 assertions

`tools/verify.py` prints one row per assertion and exits `1` if any row fails.

| # | Invariant | Guards against |
|---|---|---|
| 1 | each `target` selector hits exactly one control | a typo'd or ambiguous selector silently annotating the wrong widget |
| 2 | every `image_rect` lies fully inside the shot | a box clipped by the canvas edge |
| 3 | report `image_rect` == dump `image_rect`, field by field | a second coordinate conversion sneaking into the renderer |
| 4 | output PNG width == input width | the figure being scaled |
| 5 | badges never overlap (centre distance >= 2r) | two step numbers merging into one blob |
| 6a | badge/control overlap area <= threshold | a badge covering the very text it points at |
| 6b | reported `overlap_controls` matches the real overlap | an under-reported occlusion (hiding the problem) |
| 6c | no badge inside another step's box | the reader attributing a number to the wrong step |
| 7 | arrow tip within tolerance of its own box edge | an arrow pointing at empty space |
| 8 | annotated region pixel std > threshold | a box drawn over blank pixels — i.e. a guessed coordinate |
| 9 | exit code 0 only when every row passes | CI green-washing a broken figure |
| 10 | `height == shot.h + legend.height`, width unchanged | a legend that shifts or rescales the screenshot |
| 11 | legend row ids == ids of labelled steps | a missing, duplicated or orphaned legend row |
| 12 | legend text non-empty and fits `canvas - 2*pad_x` | text running off the canvas |
| 13 | `legend.height` fits every row | a clipped last row |

## Layout

```text
screenshotpro/
  cordis.patch.yml              DSH bundle: inserts the Screenshot Pro preset
  package.json                  npm metadata + dsh.bundle.patch
  tools/
    measure_win.py              launch exe -> shot.png + dump.json + measure-log.txt
    uia_dump.ps1                the PowerShell/UI Automation half of measure_win.py
    render.py                   spec.json -> annotated PNG + render-report.json
    verify.py                   15 assertions, PASS/FAIL table, exit 0/1
    make_fixture.py             synthetic window + dump + spec (no real app needed)
  skills/screenshot-pro/SKILL.md   the agent-facing manual
  tests/run_tests.py             offline round-trip: fixture -> render -> verify
  examples/                      minimal spec + dump shape, no screenshots
  demo/                          walkthrough figures rendered with these tools
```

## Limits

- **Windows only** for the measure stage. Annotate/verify are portable Pillow code.
- **No OCR, no image recognition.** The tool never guesses what a control is; if UI
  Automation does not expose it, it is not annotatable — say so instead of drawing.
- **No DPI scaling.** The dump records pixels of the captured window; mixing DPIs across
  captures is a measurement bug, and the verifier will catch the symptom, not the cause.
- **The default font is a Windows font** (`msyhbd.ttc`); pass `style.font_path` on any
  other platform or the renderer will complain about the missing font.
- Everything here is offline. There are no network calls in any script.

## 中文说明

**screenshotpro = 坐标只测不估的界面截图标注工具。**

给它一个 Windows 程序的 exe，它会启动程序、用 `PrintWindow` 抓整窗截图、导出完整 UI
Automation 控件树，落地成 `shot.png` + `dump.json`。之后你只在 `spec.json` 里写「标哪个控件」
（`automation_id` / `name` / `path` / `index` 四选一，必须唯一命中），**从不写坐标**。
`render.py` 画框、编号徽标、箭头、马赛克打码和底部图例条；`verify.py` 用 15 条断言验收，
任何一条不过就退出码 1。

两种用法，互不依赖：

1. **纯命令行**：装好 Python 3.9+ 和 Pillow 即可，不需要 DSH。三步命令见上文
   「Minimal reproducible example」，或直接 `python tests/run_tests.py` 离线自测（15 条全过）。
2. **作为 DSH 插件**：`package.json` 声明了 `dsh.bundle.patch`，`cordis.patch.yml` 插入一个
   `Screenshot Pro` preset。安装前**必须改一行**：`dsh-skill-filesystem` 的
   `customSkillDirs` 只认绝对路径（它内部用 `node:path.resolve()`，相对路径会相对 DSH 宿主
   的进程工作目录解析，也没有任何占位符展开），把本仓 `skills/` 目录的绝对路径填进去。

铁律只有一条：**坐标只测不估。** 图上的每个矩形都来自 `dump.json` 的 UI Automation 数据；
矩形不对就去修测量，不要在 spec 里手调、不要缩放、不要「看着差不多」。

自测是离线的：`python tests/run_tests.py` 会生成合成窗口，跑完整 render + verify，
再故意改坏一个报告字段，确认校验器真的会 FAIL。

## License

MIT — see `LICENSE`. The bundled fixture is synthetic: no real application screenshot,
no real control names, no personal paths.

