# 演示图

两张真实公开站点截图上的标注演示：**框选 + 步骤编号 + 箭头 + 底部图例条 + 区域打码**。

| 子目录 | 站点 | 步骤 | 打码区域 |
| --- | --- | --- | --- |
| `wikipedia/` | https://en.wikipedia.org/wiki/Screenshot | 4 | 右上角账号入口区（Donate / Create account / Log in） |
| `mdn/` | https://developer.mozilla.org/en-US/ | 3 | 顶部第三方广告条 |

## 每个子目录里有什么

| 文件 | 说明 |
| --- | --- |
| `shot.png` | 原始截图，1254x707 |
| `dump.json` | 控件测量表，`controls[].image_rect` 直接来自 `Element.getBoundingClientRect()` |
| `spec.json` | 标注规格：只写 selector 和文案，**不含任何像素坐标** |
| `out/<figure>.png` | 成品图（原图零偏移 + 底部图例） |
| `out/render-report.json` | 渲染报告：每条步骤解析出的 rect / 徽标圆心 / 箭头端点 |
| `_proof_crop.png` | 坐标对齐证据：按 dump 里的 rect 外扩 6px 裁出来的一小块，放大后肉眼核对 |

所有路径字段（spec 的 `shot` / `dump` / `output`，report 的 `image.path`）都是**相对 spec 所在目录**的相对路径，可以整个目录搬走。

## 离线重跑

```bash
# 渲染：spec + shot.png + dump.json -> out/<figure>.png + out/render-report.json
python tools/render.py demo/wikipedia/spec.json
python tools/verify.py demo/wikipedia/spec.json

python tools/render.py demo/mdn/spec.json
python tools/verify.py demo/mdn/spec.json
```

两张图都是 15/15 断言 PASS、退出码 0，逐行结果见 [`VERIFY.md`](VERIFY.md)。
渲染与校验只读这三类文件（spec.json / dump.json / shot.png），不联网、不连浏览器。

## 坐标是怎么来的（为什么框能压在元素上）

1. 用 Chromium DevTools 协议打开页面，`--force-device-scale-factor=1`，`devicePixelRatio = 1`；页面未滚动（`scroll = (0,0)`）。
2. 每个控件记录 `getBoundingClientRect()`，四舍五入成整数 → `dump.json` 的 `image_rect`。
3. 视口按 CSS 像素算是 1239x707，而截图是 **1254x707**：缩放比 **1:1**，多出来的 15px 是右侧滚动条槽，不是缩放。
4. 用 `_proof_crop.png` 直接验证：按 rect 外扩 6px 从截图里裁一块，框里必须**正好**是那个元素。两张图都核对过：
   - `wikipedia/_proof_crop.png`：搜索框（含放大镜图标与 "Search Wikipedia" 占位符）刚好落在裁剪框内。
   - `mdn/_proof_crop.png`：顶栏放大镜按钮的圆角胶囊刚好落在裁剪框内。

重新生成裁剪证据（在 `demo/` 下执行）：

```bash
python _tools/shotcrop.py wikipedia/shot.png wikipedia/shot.png 266 17 404 32 6 wikipedia/_proof_crop.png 3
python _tools/shotcrop.py mdn/shot.png mdn/shot.png 1093 107 80 34 6 mdn/_proof_crop.png 4
```

## Why `demo/mdn` has two specs

`spec.json` is the default render. `spec-dense.json` is the *same figure* with one extra
style switch turned on:

```json
"badge_avoid_dense_pixels": true
```

With it, the badge placer may walk up to `3 * radius` further from its target and prefers a
spot whose pixels are visually quieter (it scores the greyscale std inside the badge disc, using
`shot.png` itself — no extra input). The `out/mdn-tour.png` committed here is the one produced
by `spec-dense.json`, because it moves badge 1 off the "Dark" theme label and into whitespace.

The switch is **opt-in and off by default**, and it is not a universal improvement: on
`demo/wikipedia` the same switch moved badge 2 *further* onto the "View history" text, so that
figure was reverted to the default spec and no dense spec is shipped for it. Try it per figure,
keep it when it helps.

```bash
python tools/render.py demo/mdn/spec-dense.json    # the switched-on variant
python tools/render.py demo/mdn/spec.json          # the default variant
```
