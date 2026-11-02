#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""截图标注·校验侧: 对 spec / dump / render-report / 输出图 逐条断言.

用法:  python verify.py <spec.json> [--report <render-report.json>]
退出码: 全部通过 0, 任一失败 1
本文件的 selector 解析与几何判定是独立实现(不复用 render.py), 避免同一个 bug 同时骗过渲染与校验.
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageFont

SELECTOR_KEYS = ("name", "automation_id", "path", "index")
REPORT_NAME = "render-report.json"
STD_MIN = 8.0
ARROW_TOL = 1.0
VEIL_MAX = 0.25
FONT_FALLBACK = "C:/Windows/Fonts/msyhbd.ttc"
LEGEND_DEFAULTS = {
    "enabled": True, "title": "", "row_h": 34, "pad_x": 16, "pad_y": 12,
    "bg": "#F7F7F7", "text_color": "#1F1F1F", "max_text_w": None, "font_size": 18,
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def match_controls(controls, selector):
    if not isinstance(selector, dict) or len(selector) != 1:
        return [], "selector 结构非法 %r" % (selector,)
    key, want = next(iter(selector.items()))
    if key not in SELECTOR_KEYS:
        return [], "selector 键非法 %r" % (key,)
    hits = [c for c in controls if key in c and c[key] == want]
    return hits, "%s=%r" % (key, want)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def boundary_dist(px, py, rect):
    x0, y0 = float(rect["x"]), float(rect["y"])
    x1, y1 = x0 + float(rect["w"]), y0 + float(rect["h"])
    return min(seg_dist(px, py, x0, y0, x1, y0), seg_dist(px, py, x1, y0, x1, y1),
               seg_dist(px, py, x1, y1, x0, y1), seg_dist(px, py, x0, y1, x0, y0))


def point_in_rect(px, py, rect):
    return (rect["x"] <= px <= rect["x"] + rect["w"]
            and rect["y"] <= py <= rect["y"] + rect["h"])


def circle_rect_area(cx, cy, r, rect):
    """圆与矩形相交面积(独立实现, 与 render.py 不共享代码)."""
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
    """算遮挡时排除自身 target 与包含它的祖先容器, 否则根 Pane 会让每条徽标都 100%."""
    out = []
    for control in controls:
        rect = control.get("image_rect")
        if control.get("index") == target_index or not isinstance(rect, dict):
            continue
        if (contains_rect(rect, target_rect)
                and rect["w"] * rect["h"] > target_rect["w"] * target_rect["h"]):
            continue
        out.append((control.get("index"), rect, control.get("name") or ""))
    return out


def region_std(arr, rect):
    height, width = arr.shape[0], arr.shape[1]
    x0 = max(0, int(rect["x"]))
    y0 = max(0, int(rect["y"]))
    x1 = min(width, int(rect["x"]) + int(rect["w"]))
    y1 = min(height, int(rect["y"]) + int(rect["h"]))
    if x1 <= x0 or y1 <= y0:
        return None
    return float(np.std(arr[y0:y1, x0:x1].astype(np.float64)))


def rect_eq(a, b):
    return all(int(a.get(k, -10 ** 9)) == int(b.get(k, -10 ** 9)) for k in ("x", "y", "w", "h"))


class Table(object):
    def __init__(self):
        self.rows = []

    def add(self, num, title, ok, details=None, info=""):
        self.rows.append({"num": num, "title": title, "ok": bool(ok),
                          "details": list(details or []), "info": info})
        return bool(ok)

    def print_all(self):
        for row in self.rows:
            head = "[%s] %s %s" % ("PASS" if row["ok"] else "FAIL", row["num"], row["title"])
            if row["ok"] and row["info"]:
                head += " -- " + row["info"]
            if not row["ok"]:
                if row["details"]:
                    head += " -- " + "; ".join(row["details"][:8])
                    if len(row["details"]) > 8:
                        head += " ...(共 %d 项)" % len(row["details"])
                else:
                    head += " -- 失败"
            print(head)


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("用法: python verify.py <spec.json> [--report <render-report.json>]\n")
        return 2
    spec_path = os.path.abspath(argv[1])
    base = os.path.dirname(spec_path)
    report_arg = None
    if "--report" in argv[1:]:
        idx = argv.index("--report")
        if idx + 1 < len(argv):
            report_arg = argv[idx + 1]

    def resolve(path):
        return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))

    try:
        spec = load_json(spec_path)
        dump = load_json(resolve(spec["dump"]))
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: 无法加载 spec/dump: %s" % exc)
        return 1

    controls = dump.get("controls") or []
    out_rel = spec.get("output")
    out_path = resolve(out_rel) if out_rel else None
    if report_arg:
        report_path = resolve(report_arg)
    elif out_path:
        report_path = os.path.join(os.path.dirname(out_path), REPORT_NAME)
    else:
        report_path = os.path.join(base, REPORT_NAME)
    shot_rel = spec.get("shot") or (dump.get("shot") or {}).get("file") or "shot.png"
    in_path = resolve(shot_rel)

    print("spec   : %s" % spec_path)
    print("dump   : %s" % resolve(spec["dump"]))
    print("input  : %s" % in_path)
    print("output : %s" % out_path)
    print("report : %s" % report_path)

    table = Table()
    report = None
    report_err = ""
    try:
        report = load_json(report_path)
        if report.get("schema") != "annot-report/1":
            report_err = "report.schema=%r 应为 annot-report/1" % report.get("schema")
    except (OSError, ValueError) as exc:
        report_err = "report 不可读: %s" % exc

    in_img = None
    try:
        in_img = Image.open(in_path).convert("RGB")
    except OSError as exc:
        print("ERROR: 输入图不可读: %s" % exc)
        return 1
    in_w, in_h = in_img.size
    in_arr = np.asarray(in_img)
    print("input  : %dx%d" % (in_w, in_h))

    out_img = None
    out_err = ""
    try:
        out_img = Image.open(out_path).convert("RGB")
    except (OSError, ValueError, TypeError) as exc:
        out_err = "输出图不可读: %s" % exc

    # ---- 1. 每个 target selector 恰好命中 1 条 ----
    items = []
    for order, step in enumerate(spec.get("steps") or [], 1):
        items.append(("step %s" % step.get("n", order), step.get("target")))
    for order, red in enumerate(spec.get("redact") or [], 1):
        items.append(("redact %d" % order, red.get("target")))
    resolved = {}
    details = []
    for label, selector in items:
        hits, desc = match_controls(controls, selector)
        if len(hits) != 1:
            details.append("%s: %s 命中 %d 条" % (label, desc, len(hits)))
        else:
            resolved[label] = hits[0]
    table.add(1, "spec 内每个 target selector 在 dump.controls 中恰好命中 1 条",
              not details, details,
              "%d 个 selector 全部唯一命中" % len(items))

    # ---- 2. image_rect 完全落在 shot 尺寸内 ----
    details = []
    for label, control in resolved.items():
        rect = control.get("image_rect") or {}
        try:
            x, y = int(rect["x"]), int(rect["y"])
            w, h = int(rect["w"]), int(rect["h"])
        except (KeyError, TypeError, ValueError):
            details.append("%s: image_rect 字段缺失 %r" % (label, rect))
            continue
        if x < 0 or y < 0 or x + w > in_w or y + h > in_h:
            details.append("%s: image_rect={x:%d,y:%d,w:%d,h:%d} 越界 shot %dx%d"
                           % (label, x, y, w, h, in_w, in_h))
    table.add(2, "目标 control 的 image_rect 完全落在 shot 尺寸内", not details, details,
              "%d 个目标均在界内" % len(resolved) if not details else "")

    # ---- 3. report 的 image_rect 与 dump 逐字段相等 ----
    details = []
    if report is None:
        details.append(report_err or "report 不可读")
    else:
        if report_err:
            details.append(report_err)
        for step in report.get("steps") or []:
            n = step.get("n")
            idx = step.get("target_index")
            if not isinstance(idx, int) or not (0 <= idx < len(controls)):
                details.append("step %s: target_index=%r 不在 dump.controls 范围内" % (n, idx))
                continue
            want = controls[idx].get("image_rect") or {}
            got = step.get("image_rect") or {}
            if not rect_eq(got, want):
                details.append("step %s: dump=%r report=%r" % (n, want, got))
            hit = resolved.get("step %s" % n)
            if hit is not None and hit.get("index") != idx:
                details.append("step %s: report target_index=%r 但 spec selector 命中的是 index=%r"
                               % (n, idx, hit.get("index")))
        for red in report.get("redactions") or []:
            idx = red.get("target_index")
            if not isinstance(idx, int) or not (0 <= idx < len(controls)):
                details.append("redact target_index=%r 不在 dump.controls 范围内" % (idx,))
                continue
            want = controls[idx].get("image_rect") or {}
            got = red.get("rect") or {}
            if not rect_eq(got, want):
                details.append("redact index=%s: dump=%r report=%r" % (idx, want, got))
    table.add(3, "render-report 记录的 image_rect 与 dump 逐字段完全相等(无二次换算)",
              not details, details, "steps+redactions 全部一致" if not details else "")

    # ---- 4. 输出宽度 == 输入宽度(原图区域不缩放/不裁剪), 高度规则见断言 10 ----
    if out_img is None:
        table.add(4, "输出 PNG 宽度等于输入宽度(原图区域未缩放)", False, [out_err or "输出图不可读"])
    else:
        detail = []
        if out_img.size[0] != in_w:
            detail.append("输出宽 %d != 输入宽 %d" % (out_img.size[0], in_w))
        if not any((step.get("label") or "") for step in (spec.get("steps") or [])):
            if out_img.size[1] != in_h:
                detail.append("无 label 时输出高 %d != 输入高 %d" % (out_img.size[1], in_h))
        table.add(4, "输出 PNG 宽度等于输入宽度(原图区域未缩放)", not detail, detail,
                  "输出 %dx%d / 输入 %dx%d" % (out_img.size[0], out_img.size[1], in_w, in_h))

    steps = (report or {}).get("steps") or []
    badges = []
    for step in steps:
        badge = step.get("badge") or {}
        try:
            badges.append((step.get("n"), float(badge["cx"]), float(badge["cy"]), float(badge["r"])))
        except (KeyError, TypeError, ValueError):
            badges = None
            break

    # ---- 5. 徽标两两不重叠 ----
    if report is None:
        table.add(5, "徽标两两不重叠(圆心距 >= 2r)", False, [report_err or "report 不可读"])
    elif badges is None:
        table.add(5, "徽标两两不重叠(圆心距 >= 2r)", False, ["report.badge 字段缺失或非法"])
    else:
        details = []
        min_need = None
        worst = None
        for i in range(len(badges)):
            for j in range(i + 1, len(badges)):
                n1, x1, y1, r1 = badges[i]
                n2, x2, y2, r2 = badges[j]
                dist = math.hypot(x2 - x1, y2 - y1)
                need = r1 + r2
                if min_need is None or dist - need < min_need:
                    min_need = dist - need
                    worst = (n1, n2, dist, need)
                if dist < need - 1e-9:
                    details.append("step %s(%.0f,%.0f r%.0f) 与 step %s(%.0f,%.0f r%.0f) 圆心距 %.2f < 2r=%.2f"
                                   % (n1, x1, y1, r1, n2, x2, y2, r2, dist, need))
        info = ""
        if worst is not None:
            info = "最小圆心距 %.2f, 需求 %.2f (step %s / step %s)" % (worst[2], worst[3], worst[0], worst[1])
        elif badges:
            info = "仅 1 个徽标"
        table.add(5, "徽标两两不重叠(圆心距 >= 2r)", not details, details, info)

    # ---- 6a/6b/6c. 徽标遮挡: 无关控件 / 报告一致性 / 其它步骤的框 ----
    veil_details = []
    truth_details = []
    box_details = []
    veil_worst = None
    if report is None:
        veil_details.append(report_err or "report 不可读")
        truth_details.append(report_err or "report 不可读")
        box_details.append(report_err or "report 不可读")
    else:
        for step in steps:
            n = step.get("n")
            idx = step.get("target_index")
            badge = step.get("badge") or {}
            try:
                cx, cy, r = float(badge["cx"]), float(badge["cy"]), float(badge["r"])
            except (KeyError, TypeError, ValueError):
                veil_details.append("step %s: badge 圆心/半径缺失" % n)
                truth_details.append("step %s: badge 圆心/半径缺失" % n)
                continue
            for other in steps:
                if other is step:
                    continue
                orect = other.get("box_rect") or {}
                try:
                    inside = point_in_rect(cx, cy, {"x": float(orect["x"]), "y": float(orect["y"]),
                                                    "w": float(orect["w"]), "h": float(orect["h"])})
                except (KeyError, TypeError, ValueError):
                    box_details.append("step %s: box_rect 缺失" % other.get("n"))
                    continue
                if inside:
                    box_details.append("step %s 的徽标(%.0f,%.0f) 落在 step %s 的框 %r 内"
                                       % (n, cx, cy, other.get("n"), orect))
            if not isinstance(idx, int) or not (0 <= idx < len(controls)):
                veil_details.append("step %s: target_index=%r 无法定位自身 target" % (n, idx))
                truth_details.append("step %s: target_index=%r 无法定位自身 target" % (n, idx))
                continue
            target = controls[idx].get("image_rect")
            if not isinstance(target, dict):
                veil_details.append("step %s: 自身 target 无 image_rect" % n)
                truth_details.append("step %s: 自身 target 无 image_rect" % n)
                continue
            area = math.pi * r * r
            leaked = []
            worst = 0.0
            label = ""
            for cidx, crect, cname in veil_sources(controls, idx, target):
                got = circle_rect_area(cx, cy, r, crect)
                if got < 1.0:
                    continue
                leaked.append(cidx)
                ratio = min(1.0, got / area)
                if ratio > worst:
                    worst = ratio
                    label = "control index=%s(%s)" % (cidx, cname or "-")
            if veil_worst is None or worst > veil_worst[1]:
                veil_worst = (n, worst, label)
            if worst > VEIL_MAX + 1e-9:
                veil_details.append("step %s: 徽标(%d,%d) r%d 压住 %s 达 %.2f%% > %.0f%%"
                                    % (n, round(cx), round(cy), round(r), label,
                                       worst * 100.0, VEIL_MAX * 100.0))
            reported = badge.get("overlap_controls")
            if not isinstance(reported, list):
                truth_details.append("step %s: report 缺 badge.overlap_controls 字段" % n)
            else:
                try:
                    reported_set = sorted(int(v) for v in reported)
                except (TypeError, ValueError):
                    reported_set = None
                if reported_set is None:
                    truth_details.append("step %s: badge.overlap_controls 内容非法 %r" % (n, reported))
                elif reported_set != sorted(leaked):
                    truth_details.append("step %s: report overlap_controls=%r 与实际 %r 不一致%s"
                                         % (n, reported_set, sorted(leaked),
                                            " [瞒报]" if not reported and leaked else ""))
    veil_info = ""
    if veil_worst is not None:
        if veil_worst[1] > 0:
            veil_info = "最大遮挡 %.2f%% (step %s, %s)" % (veil_worst[1] * 100.0, veil_worst[0], veil_worst[2])
        else:
            veil_info = "0 个徽标压住无关控件"
    table.add("6a", "徽标与任何 control 的 image_rect 重叠面积/徽标面积 <= %.0f%%"
              % (VEIL_MAX * 100.0), not veil_details, veil_details, veil_info)
    table.add("6b", "report 的 badge.overlap_controls 与实际遮挡一致(不得瞒报)",
              not truth_details, truth_details,
              "%d 个徽标的遮挡记录与实际一致" % len(steps) if not truth_details else "")
    table.add("6c", "徽标不落在其它步骤的框内(自己的框不算)", not box_details, box_details,
              "%d 个徽标均未侵入其它框" % len(steps) if not box_details else "")

    # ---- 7. 箭头终点到自己目标框边界距离 <= 1.0 ----
    if report is None:
        table.add(7, "箭头终点到自己目标框边界距离 <= %.1fpx" % ARROW_TOL, False,
                  [report_err or "report 不可读"])
    else:
        details = []
        worst = None
        checked = 0
        for step in steps:
            arrow = step.get("arrow")
            if not arrow:
                continue
            checked += 1
            box = step.get("box_rect") or {}
            try:
                dist = boundary_dist(float(arrow["x2"]), float(arrow["y2"]),
                                     {"x": float(box["x"]), "y": float(box["y"]),
                                      "w": float(box["w"]), "h": float(box["h"])})
            except (KeyError, TypeError, ValueError):
                details.append("step %s: arrow/box_rect 字段缺失" % step.get("n"))
                continue
            if worst is None or dist > worst[1]:
                worst = (step.get("n"), dist)
            if dist > ARROW_TOL + 1e-9:
                details.append("step %s: 端点(%s,%s) 到框边界 %.3fpx > %.1f"
                               % (step.get("n"), arrow.get("x2"), arrow.get("y2"), dist, ARROW_TOL))
        info = ""
        if worst is not None:
            info = "%d 个箭头, 最大偏离 %.3fpx" % (checked, worst[1])
        elif not details:
            info = "无箭头步骤"
        table.add(7, "箭头终点到自己目标框边界距离 <= %.1fpx" % ARROW_TOL, not details, details, info)

    # ---- 8. 被标注区域像素 std > 8 (从输入图取, 防"框在空白处") ----
    details = []
    metrics = []
    for order, step in enumerate(spec.get("steps") or [], 1):
        label = "step %s" % step.get("n", order)
        control = resolved.get(label)
        if control is None:
            details.append("%s: selector 未唯一命中, 无法取像素" % label)
            continue
        rect = control.get("image_rect") or {}
        std = region_std(in_arr, rect)
        if std is None:
            details.append("%s: 区域为空 %r" % (label, rect))
        else:
            metrics.append("%s std=%.2f" % (label, std))
            if std <= STD_MIN:
                details.append("%s: 区域 %r 的 std=%.2f <= %.1f (框在空白处)" % (label, rect, std, STD_MIN))
    for order, red in enumerate(spec.get("redact") or [], 1):
        label = "redact %d" % order
        control = resolved.get(label)
        if control is None:
            details.append("%s: selector 未唯一命中, 无法取像素" % label)
            continue
        rect = control.get("image_rect") or {}
        std = region_std(in_arr, rect)
        if std is None:
            details.append("%s: 区域为空 %r" % (label, rect))
        else:
            metrics.append("%s std=%.2f" % (label, std))
            if std <= STD_MIN:
                details.append("%s: 区域 %r 的 std=%.2f <= %.1f (框在空白处)" % (label, rect, std, STD_MIN))
    info = ""
    if metrics:
        info = "最低 %s" % min(metrics, key=lambda s: float(s.split("std=")[1]))
    table.add(8, "被标注区域像素 std > %.0f" % STD_MIN, not details, details, info)

    # ---- 10..13. 底部长条图例 ----
    labels = [(step.get("n"), step.get("label") or "") for step in (spec.get("steps") or [])]
    labeled = [n for n, lab in labels if lab]
    legend = (report or {}).get("legend") or {}
    try:
        legend_h = int(legend.get("height") or 0)
    except (TypeError, ValueError):
        legend_h = 0
    rows = legend.get("rows") or []
    lcfg = dict(LEGEND_DEFAULTS)
    lcfg.update(spec.get("legend") or {})
    out_size = out_img.size if out_img is not None else None

    d10 = []
    if out_size is None:
        d10.append(out_err or "输出图不可读")
    else:
        if out_size[0] != in_w:
            d10.append("输出宽 %d != 输入宽 %d" % (out_size[0], in_w))
        if labeled:
            want_h = in_h + legend_h
            if out_size[1] != want_h:
                d10.append("有 label: 输出高 %d != shot.h %d + legend.height %d = %d"
                           % (out_size[1], in_h, legend_h, want_h))
        elif out_size[1] != in_h:
            d10.append("无 label: 输出高 %d != shot.h %d" % (out_size[1], in_h))
    table.add(10, "有 label 时输出高 == shot.h + legend.height 且宽不变; 无 label 时尺寸 == shot",
              not d10, d10, "输出 %dx%d, shot %dx%d, legend.height %d"
              % ((out_size or (0, 0)) + (in_w, in_h, legend_h)) if not d10 else "")

    d11 = []
    try:
        got_n = [int(row.get("n")) for row in rows]
    except (TypeError, ValueError):
        got_n = []
        d11.append("legend.rows 的 n 非法: %r" % [row.get("n") for row in rows])
    want_n = [int(n) for n in labeled]
    if sorted(got_n) != sorted(want_n):
        d11.append("legend.rows 的 n=%r 与带 label 的 steps %r 不一致(漏/多/重复)" % (got_n, want_n))
    table.add(11, "legend.rows 的 n 集合 == 带 label 的 steps 的 n 集合", not d11, d11,
              "%d 行逐一对齐 %r" % (len(got_n), sorted(want_n)) if not d11 else "")

    d12 = []
    fpath = (spec.get("style") or {}).get("font_path") or FONT_FALLBACK
    fidx = int((spec.get("style") or {}).get("font_index", 0))
    try:
        lfont = ImageFont.truetype(fpath, int(lcfg["font_size"]), index=fidx)
    except OSError as exc:
        lfont = None
        d12.append("图例字体不可用: %s" % exc)
    pad_x = int(lcfg["pad_x"])
    limit = in_w - 2 * pad_x
    for row in rows:
        text = row.get("text") or ""
        if not text.strip():
            d12.append("行 %s 文本为空" % row.get("n"))
        if lfont is not None:
            wid = int(math.ceil(lfont.getlength(text)))
            if wid > limit:
                d12.append("行 %s 文本宽 %d > 画布宽-%d*2=%d" % (row.get("n"), wid, pad_x, limit))
        try:
            rep_w = int(row.get("w"))
        except (TypeError, ValueError):
            d12.append("行 %s 缺少 w" % row.get("n"))
            continue
        if rep_w > limit:
            d12.append("行 %s 记录的 w=%d > %d" % (row.get("n"), rep_w, limit))
    table.add(12, "每条图例文本非空且绘制宽度 <= 画布宽-2*pad_x", not d12, d12,
              "%d 行文本均在 %dpx 内" % (len(rows), limit) if not d12 else "")

    d13 = []
    row_h = int(lcfg["row_h"])
    if rows:
        try:
            bottom = max(int(r["y"]) for r in rows) + row_h
        except (KeyError, TypeError, ValueError):
            bottom = None
            d13.append("legend.rows 缺 y 字段")
        if bottom is not None:
            if legend_h < bottom - in_h:
                d13.append("legend.height %d < 最大行底 %d - shot.h %d = %d"
                           % (legend_h, bottom, in_h, bottom - in_h))
            if out_size is not None and bottom > out_size[1]:
                d13.append("最后一行底 %d 越过输出高 %d" % (bottom, out_size[1]))
    elif labeled:
        d13.append("有 label 但 legend.rows 为空")
    table.add(13, "legend.height 容得下所有行(最大行底 <= shot.h + legend.height <= 输出高)",
              not d13, d13, "legend.height %d, 画布 %d" % (legend_h, (out_size or (0, 0))[1]) if not d13 else "")

    # ---- 9. 退出码 ----
    failed = [row for row in table.rows if not row["ok"]]
    code = 0 if not failed else 1
    table.add(9, "退出码约定(全过 0 / 任一失败 1)", True, [],
              "exit %d (%d 项失败)" % (code, len(failed)))

    print("")
    table.print_all()
    print("")
    total = len(table.rows)
    passed = len([row for row in table.rows if row["ok"]])
    print("结果: %d/%d 断言通过 -> %s (exit %d)"
          % (passed, total, "PASS" if code == 0 else "FAIL", code))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
