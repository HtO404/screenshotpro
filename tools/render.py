#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""截图标注·渲染侧: spec.json + shot.png + dump.json -> 标注 PNG + render-report.json

用法:  python render.py <spec.json>

* spec 只给 selector, 不含任何像素坐标; 所有几何量来自 dump.json 的 controls[].image_rect
* 画布 = 原图尺寸, 不缩放不裁剪
* spec 内的相对路径以 spec.json 所在目录为基准
"""

import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SPEC_SCHEMA = "annot-spec/1"
DUMP_SCHEMA = "uia-dump/1"
REPORT_SCHEMA = "annot-report/1"
REPORT_NAME = "render-report.json"
SELECTOR_KEYS = ("name", "automation_id", "path", "index")
# badge_avoid_dense_pixels: a badge may sit up to DENSE_REACH_R * badge_radius farther than
# the nearest legal spot if that buys a substantially emptier patch of pixels (see disc_std).
# All earlier criteria (inside/veil/crowd/overflow) still win outright. Off by default.
DENSE_REACH_R = 3

STYLE_DEFAULTS = {
    "font_path": "C:/Windows/Fonts/msyhbd.ttc",
    "font_index": 0,
    "font_size": 20,
    "badge_fill": "#E23B2E",
    "badge_text": "#FFFFFF",
    "badge_radius": 14,
    "box_color": "#E23B2E",
    "box_width": 3,
    "box_pad": 4,
    "arrow_width": 3,
    "arrow_head_len": 10,
    "arrow_head_w": 8,
    "min_gap": 6,
    "badge_avoid_dense_pixels": False,
}

LEGEND_DEFAULTS = {
    "enabled": True,
    "title": "",
    "row_h": 34,
    "pad_x": 16,
    "pad_y": 12,
    "bg": "#F7F7F7",
    "text_color": "#1F1F1F",
    "max_text_w": None,
    "font_size": 18,
}


class RenderError(RuntimeError):
    pass


def fail(msg):
    raise RenderError(msg)


def warn(msg):
    sys.stderr.write("WARN: %s\n" % msg)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        fail("读不到 %s (%s)" % (path, exc))


def path_of(base, rel):
    if not isinstance(rel, str) or not rel:
        fail("路径字段为空: %r" % (rel,))
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(base, rel))


def style_of(spec):
    st = dict(STYLE_DEFAULTS)
    st.update(spec.get("style") or {})
    for key in ("font_size", "font_index", "badge_radius", "box_width", "box_pad",
                "arrow_width", "arrow_head_len", "arrow_head_w", "min_gap"):
        st[key] = int(st[key])
    return st


def as_rect(raw, where):
    try:
        rect = {"x": int(raw["x"]), "y": int(raw["y"]), "w": int(raw["w"]), "h": int(raw["h"])}
    except (TypeError, KeyError, ValueError):
        fail("%s: image_rect 不合法 %r" % (where, raw))
    if rect["w"] <= 0 or rect["h"] <= 0:
        fail("%s: image_rect 宽高必须为正 %r" % (where, rect))
    return rect


def match_controls(controls, selector):
    if not isinstance(selector, dict) or len(selector) != 1:
        fail("selector 必须恰好含一个键 %s, 实际 %r" % (SELECTOR_KEYS, selector))
    key, want = next(iter(selector.items()))
    if key not in SELECTOR_KEYS:
        fail("不支持的 selector 键 %r (允许 %s)" % (key, SELECTOR_KEYS))
    return [c for c in controls if key in c and c[key] == want], key, want


def pick_control(controls, selector, where):
    hits, key, want = match_controls(controls, selector)
    if len(hits) != 1:
        fail("%s: selector %s=%r 命中 %d 条 (必须恰好 1 条)" % (where, key, want, len(hits)))
    return hits[0]


def inflate(rect, pad):
    return {"x": rect["x"] - pad, "y": rect["y"] - pad,
            "w": rect["w"] + 2 * pad, "h": rect["h"] + 2 * pad}


def center_of(rect):
    return (rect["x"] + rect["w"] / 2.0, rect["y"] + rect["h"] / 2.0)


def edges_of(rect):
    return (float(rect["x"]), float(rect["y"]),
            float(rect["x"] + rect["w"]), float(rect["y"] + rect["h"]))


def dist_to_rect(cx, cy, rect):
    dx = max(rect["x"] - cx, 0.0, cx - (rect["x"] + rect["w"]))
    dy = max(rect["y"] - cy, 0.0, cy - (rect["y"] + rect["h"]))
    return math.hypot(dx, dy)


def circle_rect_area(cx, cy, r, rect):
    """圆与矩形的相交面积(按 x 纵条积分, 256 条, 误差 << 1%)."""
    x0 = max(cx - r, float(rect["x"]))
    x1 = min(cx + r, float(rect["x"]) + float(rect["w"]))
    if x1 <= x0:
        return 0.0
    y0 = float(rect["y"])
    y1 = y0 + float(rect["h"])
    dx = (x1 - x0) / 256.0
    total = 0.0
    for i in range(256):
        xm = x0 + (i + 0.5) * dx
        inner = r * r - (xm - cx) ** 2
        if inner <= 0.0:
            continue
        half = math.sqrt(inner)
        lo = max(cy - half, y0)
        hi = min(cy + half, y1)
        if hi > lo:
            total += (hi - lo) * dx
    return total


def contains_rect(outer, inner):
    return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
            and outer["x"] + outer["w"] >= inner["x"] + inner["w"]
            and outer["y"] + outer["h"] >= inner["y"] + inner["h"])


def veil_sources(controls, target_index, target_rect):
    """徽标压住谁算"无关控件": 排除自身 target 与包含它的祖先容器(根 Pane 必然覆盖整窗)."""
    out = []
    for control in controls:
        rect = control.get("image_rect")
        if control.get("index") == target_index or not isinstance(rect, dict):
            continue
        if (contains_rect(rect, target_rect)
                and rect["w"] * rect["h"] > target_rect["w"] * target_rect["h"]):
            continue
        out.append((control.get("index"), rect))
    return out


def disc_std(gray, cx, cy, r):
    """Std of the grayscale pixels inside the badge disc (0..255). Higher = busier pixels.

    Badges only dodge UI Automation controls today; body text on a rendered page is not a
    control, so a badge can sit on top of a word. This measures the pixels the badge would
    cover, which is the only signal available without any new input.
    """
    import numpy as np  # optional: only needed when badge_avoid_dense_pixels is on

    h, w = gray.shape
    x0 = max(0, int(math.floor(cx - r)))
    x1 = min(w, int(math.ceil(cx + r)) + 1)
    y0 = max(0, int(math.floor(cy - r)))
    y1 = min(h, int(math.ceil(cy + r)) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    roi = gray[y0:y1, x0:x1]
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r
    if not mask.any():
        return 0.0
    return float(roi[mask].std())


def badge_candidates(box, st):
    """候选位 = 左/右/上/下 四方向 x (基准 + 沿该方向各滑移一格 2r+min_gap) = 12 个."""
    radius = st["badge_radius"]
    gap = st["min_gap"]
    shift = 2.0 * radius + gap
    midx, midy = center_of(box)
    left = box["x"] - gap - radius
    right = box["x"] + box["w"] + gap + radius
    top = box["y"] - gap - radius
    bottom = box["y"] + box["h"] + gap + radius
    out = []
    for side, anchor_x in (("left", left), ("right", right)):
        for k in (0, -1, 1):
            out.append((side, anchor_x, midy + k * shift))
    for side, anchor_y in (("top", top), ("bottom", bottom)):
        for k in (0, -1, 1):
            out.append((side, midx + k * shift, anchor_y))
    return out


def pick_badge(item, controls, placed, st, canvas_w, canvas_h, gray=None):
    """打分选位: 整圆在画布内优先 -> 压住无关控件面积 -> 压住其它徽标面积 -> 越界面积 -> 离目标框距离.

    gray 非空时 (style.badge_avoid_dense_pixels=true): 先按原有四级判据(整圆在画布内 /
    压控件 / 压徽标 / 越界)选出最优等级, 再在该等级里允许比最近位多走 DENSE_REACH_R * r 的距离,
    用候选圆覆盖像素的灰度 std(越小越空)挑位 —— 这样徽标会避开网页正文文字这类"不是控件"
    的密集区, 但不会远离自己的目标框。gray 为 None 时打分与原来逐字节一致, 默认输出不变。
    """
    radius = st["badge_radius"]
    badge_area = math.pi * radius * radius
    need = 2.0 * radius + st["min_gap"]
    canvas = {"x": 0, "y": 0, "w": canvas_w, "h": canvas_h}
    sources = veil_sources(controls, item["control"].get("index"), item["image_rect"])
    cands = []
    for side, cx, cy in badge_candidates(item["box_rect"], st):
        inside = circle_rect_area(cx, cy, radius, canvas)
        veil = 0.0
        for _idx, rect in sources:
            veil += circle_rect_area(cx, cy, radius, rect)
        crowd = 0.0
        for other in placed:
            gap_now = math.hypot(other["cx"] - cx, other["cy"] - cy)
            if gap_now < need:
                crowd += (need - gap_now) * need
        base = (0 if inside >= badge_area - 0.5 else 1, veil, crowd,
                badge_area - inside)
        gap = dist_to_rect(cx, cy, item["box_rect"])
        dense = None
        if gray is not None:
            dense = round(disc_std(gray, cx, cy, radius), 2)
        cands.append({"side": side, "cx": cx, "cy": cy,
                      "base": base, "gap": gap, "dense": dense})
    if gray is None:
        best = min(cands, key=lambda c: c["base"] + (c["gap"],))
    else:
        best_base = min(c["base"] for c in cands)
        pool = [c for c in cands if c["base"] == best_base]
        near = min(c["gap"] for c in pool)
        reach = near + DENSE_REACH_R * radius
        best = min([c for c in pool if c["gap"] <= reach + 1e-9],
                   key=lambda c: (c["dense"], c["gap"]))
    side, cx, cy, dense = best["side"], best["cx"], best["cy"], best["dense"]
    badge = {"cx": float(cx), "cy": float(cy), "r": radius, "n": item["n"], "side": side}
    if dense is not None:
        badge["dense_score"] = dense
    return badge


def badge_veil(item, controls):
    """按最终(取整后)圆心算实际遮挡, 写进 report 供 verify 对账."""
    badge = item["badge"]
    cx, cy, radius = int(round(badge["cx"])), int(round(badge["cy"])), int(badge["r"])
    area = math.pi * radius * radius
    hit = []
    worst = 0.0
    for idx, rect in veil_sources(controls, item["control"].get("index"), item["image_rect"]):
        got = circle_rect_area(cx, cy, radius, rect)
        if got >= 1.0:
            hit.append(idx)
            worst = max(worst, min(1.0, got / area))
    return sorted(hit), round(worst, 4)


def separate_badges(badges, st, canvas_w, canvas_h):
    """规则 4: 按 cy 排序, 重叠时把下方那个沿背离自己目标(即背离对方徽标)的方向推开, 最多 3 轮."""
    need = 2.0 * st["badge_radius"] + st["min_gap"]
    for _ in range(3):
        moved = False
        order = sorted(badges, key=lambda b: (b["cy"], b["cx"]))
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                upper, lower = order[i], order[j]
                dx, dy = lower["cx"] - upper["cx"], lower["cy"] - upper["cy"]
                dist = math.hypot(dx, dy)
                if dist >= need - 1e-9:
                    continue
                if dist < 1e-9:
                    ux, uy = 0.0, 1.0
                else:
                    ux, uy = dx / dist, dy / dist
                push = need - dist
                lower["cx"] += ux * push
                lower["cy"] += uy * push
                lower["side"] = "pushed"
                moved = True
        if not moved:
            break
    bad = []
    for i in range(len(badges)):
        for j in range(i + 1, len(badges)):
            a, b = badges[i], badges[j]
            dist = math.hypot(b["cx"] - a["cx"], b["cy"] - a["cy"])
            if dist < need - 1e-9:
                bad.append("step%s/step%s 圆心距 %.2f < %.2f" % (a["n"], b["n"], dist, need))
    if bad:
        fail("徽标碰撞避让 3 轮后仍重叠, 拒绝出图: " + "; ".join(bad))
    for b in badges:
        if (b["cx"] - b["r"] < 0 or b["cy"] - b["r"] < 0
                or b["cx"] + b["r"] > canvas_w or b["cy"] + b["r"] > canvas_h):
            fail("徽标被推出画布: step%s 圆心(%.1f,%.1f) r=%d 画布 %dx%d"
                 % (b["n"], b["cx"], b["cy"], b["r"], canvas_w, canvas_h))


def ray_box_hit(cx, cy, tx, ty, box, where):
    """规则 5: 从徽标圆心指向框中心的射线与框边界的最近交点."""
    x0, y0, x1, y1 = edges_of(box)
    dx, dy = tx - cx, ty - cy
    hits = []
    if abs(dx) > 1e-12:
        for xb in (x0, x1):
            t = (xb - cx) / dx
            if t > 1e-9:
                yy = cy + t * dy
                if y0 - 1e-9 <= yy <= y1 + 1e-9:
                    hits.append(t)
    if abs(dy) > 1e-12:
        for yb in (y0, y1):
            t = (yb - cy) / dy
            if t > 1e-9:
                xx = cx + t * dx
                if x0 - 1e-9 <= xx <= x1 + 1e-9:
                    hits.append(t)
    if not hits:
        fail("%s: 徽标圆心(%.1f,%.1f) -> 框中心(%.1f,%.1f) 的射线未与框边界相交" % (where, cx, cy, tx, ty))
    t = min(hits)
    return cx + t * dx, cy + t * dy


def draw_box(draw, box, st):
    x0, y0, x1, y1 = edges_of(box)
    draw.rectangle([int(round(x0)), int(round(y0)), int(round(x1)) - 1, int(round(y1)) - 1],
                   outline=st["box_color"], width=st["box_width"])


def draw_arrow(draw, arrow, st):
    x1, y1 = float(arrow["x1"]), float(arrow["y1"])
    x2, y2 = float(arrow["x2"]), float(arrow["y2"])
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        fail("箭头长度为零: %r" % (arrow,))
    ux, uy = dx / dist, dy / dist
    head = float(st["arrow_head_len"])
    half_w = float(st["arrow_head_w"]) / 2.0
    bx, by = x2 - ux * head, y2 - uy * head
    px, py = -uy, ux
    draw.line([x1, y1, bx, by], fill=st["box_color"], width=st["arrow_width"])
    draw.polygon([(x2, y2), (bx + px * half_w, by + py * half_w),
                  (bx - px * half_w, by - py * half_w)], fill=st["box_color"])


def draw_badge(draw, badge, n, st, font):
    cx, cy, radius = int(round(badge["cx"])), int(round(badge["cy"])), int(badge["r"])
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=st["badge_fill"])
    draw.text((cx, cy), str(n), font=font, fill=st["badge_text"], anchor="mm")


def pixelate(img, rect, block):
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    block = max(1, int(block))
    region = img.crop((x, y, x + w, y + h))
    small = region.resize((max(1, w // block), max(1, h // block)), Image.BOX)
    img.paste(small.resize((w, h), Image.NEAREST), (x, y))


def text_width(font, text):
    if not text:
        return 0
    return int(math.ceil(font.getlength(text)))


def truncate_text(font, text, limit):
    out = text
    while out and text_width(font, out + "…") > limit:
        out = out[:-1]
    return (out + "…") if out else "…"


def legend_layout(spec, st, canvas_w, shot_h, labeled):
    """底部长条图例排版; 无 label 或 legend.enabled 为假 -> None(画布与行为完全不变)."""
    cfg = dict(LEGEND_DEFAULTS)
    cfg.update(spec.get("legend") or {})
    if not labeled or not cfg.get("enabled"):
        return None
    font_size = int(cfg["font_size"])
    font = ImageFont.truetype(st["font_path"], font_size, index=st["font_index"])
    pad_x, pad_y, row_h = int(cfg["pad_x"]), int(cfg["pad_y"]), int(cfg["row_h"])
    radius = int(st["badge_radius"])
    limit = int(cfg.get("max_text_w") or max(1, canvas_w - 2 * pad_x))
    full_widths = [text_width(font, label) for _n, label in labeled]
    cols = 2 if (len(labeled) > 8 or sum(full_widths) > limit) else 1
    per_col = (len(labeled) + cols - 1) // cols
    col_w = canvas_w // 2 if cols == 2 else canvas_w
    row_limit = max(1, min(limit, col_w - 2 * pad_x - 2 * radius - 10))
    title = cfg.get("title") or ""
    title_h = font_size + 10 if title else 0
    height = pad_y * 2 + title_h + per_col * row_h
    rows = []
    for i, (n, label) in enumerate(labeled):
        text = label
        if text_width(font, label) > row_limit:
            text = truncate_text(font, label, row_limit)
            warn("图例行 %s 文本宽 %d > 上限 %d, 已截断为 %r"
                 % (n, text_width(font, label), row_limit, text))
        col = i // per_col
        top = shot_h + pad_y + title_h + (i % per_col) * row_h
        rows.append({"n": n, "text": text, "col": col, "y": top,
                     "x": pad_x + col * col_w + 2 * radius + 10,
                     "w": text_width(font, text)})
    return {"cfg": cfg, "font": font, "height": height, "rows": rows, "title": title,
            "title_h": title_h, "shot_h": shot_h, "radius": radius, "row_h": row_h,
            "width": canvas_w, "pad_x": pad_x, "pad_y": pad_y}


def draw_legend(draw, legend, st):
    cfg = legend["cfg"]
    radius = legend["radius"]
    row_h = legend["row_h"]
    top = legend["shot_h"]
    draw.rectangle([0, top, legend["width"] - 1, top + legend["height"] - 1], fill=cfg["bg"])
    if legend["title"]:
        draw.text((legend["pad_x"], top + legend["pad_y"] + legend["title_h"] // 2 - 2),
                  legend["title"], font=legend["font"], fill=cfg["text_color"], anchor="lm")
    for row in legend["rows"]:
        cy = row["y"] + row_h // 2
        cx = row["x"] - radius - 10
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=st["badge_fill"])
        draw.text((cx, cy), str(row["n"]), font=legend["font"], fill=st["badge_text"], anchor="mm")
        draw.text((row["x"], cy), row["text"], font=legend["font"],
                  fill=cfg["text_color"], anchor="lm")


def run(spec_path):
    spec_path = os.path.abspath(spec_path)
    base = os.path.dirname(spec_path)
    spec = load_json(spec_path)
    if spec.get("schema") != SPEC_SCHEMA:
        fail("spec.schema 必须是 %r, 实际 %r" % (SPEC_SCHEMA, spec.get("schema")))
    st = style_of(spec)

    dump_path = path_of(base, spec.get("dump"))
    dump = load_json(dump_path)
    if dump.get("schema") != DUMP_SCHEMA:
        fail("dump.schema 必须是 %r, 实际 %r" % (DUMP_SCHEMA, dump.get("schema")))
    controls = dump.get("controls") or []
    if not controls:
        fail("dump.controls 为空")

    shot_meta = dump.get("shot") or {}
    shot_path = path_of(base, spec.get("shot") or shot_meta.get("file") or "shot.png")
    img = Image.open(shot_path).convert("RGB")
    canvas_w, canvas_h = img.size
    shot_h = canvas_h

    if shot_meta and (int(shot_meta.get("width", canvas_w)) != canvas_w
                      or int(shot_meta.get("height", canvas_h)) != canvas_h):
        fail("dump.shot %sx%s 与实际图片 %dx%d 不一致"
             % (shot_meta.get("width"), shot_meta.get("height"), canvas_w, canvas_h))
    win_rect = (dump.get("window") or {}).get("screen_rect") or {}
    if win_rect and (int(win_rect.get("w", canvas_w)) != canvas_w
                     or int(win_rect.get("h", canvas_h)) != canvas_h):
        fail("dump.window.screen_rect %sx%s 与 shot 尺寸 %dx%d 不一致(契约要求相等)"
             % (win_rect.get("w"), win_rect.get("h"), canvas_w, canvas_h))
    ox = int(win_rect.get("x", 0))
    oy = int(win_rect.get("y", 0))

    plan = []
    origin_warn = []
    for order, step in enumerate(spec.get("steps") or [], 1):
        where = "step %s" % step.get("n", order)
        selector = step.get("target")
        if not isinstance(selector, dict):
            fail("%s: 缺少 target selector" % where)
        control = pick_control(controls, selector, where)
        rect = as_rect(control.get("image_rect"), where)
        screen = control.get("screen_rect")
        if isinstance(screen, dict):
            expect = {"x": int(screen["x"]) - ox, "y": int(screen["y"]) - oy,
                      "w": int(screen["w"]), "h": int(screen["h"])}
            if expect != rect:
                origin_warn.append("%s: image_rect=%r 但 screen_rect-窗口原点=%r" % (where, rect, expect))
        plan.append({"n": step.get("n", order), "control": control, "image_rect": rect,
                     "box_rect": inflate(rect, st["box_pad"]), "label": step.get("label") or "",
                     "box_on": bool(step.get("box", True)), "arrow_on": bool(step.get("arrow", True))})
    for item in origin_warn:
        warn("image_rect 与 screen_rect 不自洽(测量侧契约问题) " + item)

    gray = None
    if st.get("badge_avoid_dense_pixels"):
        import numpy as _np
        gray = _np.asarray(img.convert("L"), dtype=_np.float32)

    badges = []
    for item in plan:
        badge = pick_badge(item, controls, badges, st, canvas_w, canvas_h, gray)
        item["badge"] = badge
        badges.append(badge)
    separate_badges(badges, st, canvas_w, canvas_h)
    for item in plan:
        hit, ratio = badge_veil(item, controls)
        item["badge"]["overlap_controls"] = hit
        item["badge"]["overlap_ratio"] = ratio

    for item in plan:
        if not item["arrow_on"]:
            item["arrow"] = None
            continue
        badge = item["badge"]
        tx, ty = center_of(item["box_rect"])
        ex, ey = ray_box_hit(badge["cx"], badge["cy"], tx, ty, item["box_rect"], "step %s" % item["n"])
        dx, dy = ex - badge["cx"], ey - badge["cy"]
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            fail("step %s: 徽标圆心与目标框边界重合, 无法画箭头" % item["n"])
        sx = badge["cx"] + dx / dist * badge["r"]
        sy = badge["cy"] + dy / dist * badge["r"]
        item["arrow"] = {"x1": int(round(sx)), "y1": int(round(sy)),
                         "x2": int(round(ex)), "y2": int(round(ey))}

    labeled = [(item["n"], item["label"]) for item in plan if item["label"]]
    legend = legend_layout(spec, st, canvas_w, shot_h, labeled)
    legend_h = legend["height"] if legend else 0
    full_h = shot_h + legend_h
    if legend_h:
        canvas = Image.new("RGB", (canvas_w, full_h), legend["cfg"]["bg"])
        canvas.paste(img, (0, 0))
    else:
        canvas = img

    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(st["font_path"], st["font_size"], index=st["font_index"])
    for item in plan:
        if item["box_on"]:
            draw_box(draw, item["box_rect"], st)
    for item in plan:
        if item["arrow"]:
            draw_arrow(draw, item["arrow"], st)
    for item in plan:
        draw_badge(draw, item["badge"], item["n"], st, font)

    redactions = []
    for order, item in enumerate(spec.get("redact") or [], 1):
        where = "redact %d" % order
        selector = item.get("target")
        if not isinstance(selector, dict):
            fail("%s: 缺少 target selector" % where)
        control = pick_control(controls, selector, where)
        rect = as_rect(control.get("image_rect"), where)
        mode = item.get("mode", "pixelate")
        if mode != "pixelate":
            fail("%s: 不支持的 mode %r (只支持 pixelate)" % (where, mode))
        pixelate(canvas, rect, item.get("block", 12))
        redactions.append({"target_index": control.get("index"), "rect": rect, "mode": mode})

    if legend:
        draw_legend(draw, legend, st)

    out_rel = spec.get("output")
    out_path = path_of(base, out_rel)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    canvas.save(out_path)

    report = {
        "schema": REPORT_SCHEMA,
        "figure": spec.get("figure", ""),
        "image": {"path": out_rel, "width": canvas_w, "height": full_h},
        "steps": [{
            "n": item["n"],
            "target_index": item["control"].get("index"),
            "image_rect": item["image_rect"],
            "box_rect": item["box_rect"],
            "badge": {"cx": int(round(item["badge"]["cx"])),
                      "cy": int(round(item["badge"]["cy"])),
                      "r": int(item["badge"]["r"]),
                      "overlap_controls": item["badge"]["overlap_controls"],
                      "overlap_ratio": item["badge"]["overlap_ratio"]},
            "arrow": item["arrow"],
        } for item in plan],
        "redactions": redactions,
        "legend": {"height": legend_h, "rows": legend["rows"] if legend else []},
    }
    if gray is not None:
        for step_rep, item in zip(report["steps"], plan):
            if "dense_score" in item["badge"]:
                step_rep["badge"]["dense_score"] = item["badge"]["dense_score"]
    report_path = os.path.join(out_dir if out_dir else base, REPORT_NAME)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print("figure : %s" % report["figure"])
    print("canvas : %dx%d (原图 %dx%d 零偏移 + 图例 %d)" % (canvas_w, full_h, canvas_w, shot_h, legend_h))
    for step in report["steps"]:
        print("  step %-2s target_index=%-3s image_rect=%s box=%s badge=(%d,%d)r%d "
              "overlap=%s/%.2f%% arrow=%s"
              % (step["n"], step["target_index"], step["image_rect"], step["box_rect"],
                 step["badge"]["cx"], step["badge"]["cy"], step["badge"]["r"],
                 step["badge"]["overlap_controls"], step["badge"]["overlap_ratio"] * 100.0,
                 step["arrow"]))
    for red in report["redactions"]:
        print("  redact target_index=%s rect=%s mode=%s" % (red["target_index"], red["rect"], red["mode"]))
    print("png    : %s" % out_path)
    print("report : %s" % report_path)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("用法: python render.py <spec.json>\n")
        return 2
    try:
        run(argv[1])
    except RenderError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
