#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""造 fixture: 合成一张"工具主窗口"截图 + 与之严格对应的 dump.json + spec.json.

用法:  python make_fixture.py [输出目录, 默认 ./fixture]

合成图按控件矩形逐个绘制, 保证每个被标注区域都有真实内容(std > 8),
不是一块纯色 -> verify 的"框在空白处"嗅探才有意义.
"""

import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "C:/Windows/Fonts/msyhbd.ttc"
ORIGIN = {"x": 281, "y": 138}
CANVAS = {"w": 900, "h": 640}

# (type, name, automation_id, path, x, y, w, h)  x/y/w/h 为 image_rect(图片坐标)
CONTROLS = [
    ("Pane", "", "", "/Pane[1]", 0, 0, 900, 640),
    ("Pane", "标题栏", "titleBar", "/Pane[1]/Pane[1]", 0, 0, 900, 36),
    ("Pane", "工具栏", "toolBar", "/Pane[1]/Pane[2]", 8, 44, 884, 56),
    ("Button", "浏览…", "btnBrowse", "/Pane[1]/Pane[2]/Button[1]", 16, 52, 96, 40),
    ("Edit", "输出目录", "edOutDir", "/Pane[1]/Pane[2]/Edit[1]", 170, 52, 470, 40),
    ("Button", "执行", "btnRun", "/Pane[1]/Pane[2]/Button[2]", 736, 52, 80, 40),
    ("Tree", "任务", "treeTasks", "/Pane[1]/Tree[1]", 8, 108, 180, 524),
    ("List", "结果列表", "listResults", "/Pane[1]/List[1]", 220, 108, 672, 420),
    ("Text", "输出目录：D:\\workspace\\demo\\output", "lblOutDir", "/Pane[1]/Text[1]", 220, 536, 672, 28),
    ("Static", "就绪 | 3 项 / 3 成功 | DPI 100%", "lblStatus", "/Pane[1]/Text[2]", 8, 600, 884, 32),
    ("Button", "导入", "btnImport", "/Pane[1]/Tree[1]/Button[1]", 16, 140, 150, 28),
    ("Button", "重试", "btnRetry", "/Pane[1]/Tree[1]/Button[2]", 16, 172, 150, 28),
    ("Button", "设置", "btnSetting", "/Pane[1]/Tree[1]/Button[3]", 16, 204, 150, 28),
    ("Button", "日志", "btnLog", "/Pane[1]/Tree[1]/Button[4]", 16, 236, 150, 28),
]


def font(size):
    return ImageFont.truetype(FONT, size, index=0)


def button(draw, x, y, w, h, label, ft, selected=False):
    fill = "#DDEAFB" if selected else "#E9EBEF"
    line = "#8FB3E8" if selected else "#B9BFC8"
    draw.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=5, fill=fill, outline=line, width=1)
    draw.text((x + w / 2.0, y + h / 2.0), label, font=ft, fill="#1F2933", anchor="mm")


def build_image():
    rng = np.random.default_rng(20261102)
    canvas = np.empty((CANVAS["h"], CANVAS["w"], 3), dtype=np.int16)
    canvas[:, :] = (243, 245, 248)
    canvas += rng.integers(-3, 4, canvas.shape)
    img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(img)
    f16, f15, f14, f13 = font(16), font(15), font(14), font(13)

    # 标题栏
    draw.rectangle([0, 0, CANVAS["w"] - 1, 35], fill="#243447")
    draw.text((14, 18), "示例工具", font=f16, fill="#FFFFFF", anchor="lm")

    # 工具栏
    draw.rounded_rectangle([8, 44, 891, 99], radius=6, fill="#FFFFFF", outline="#D0D4DA", width=1)
    button(draw, 16, 52, 96, 40, "浏览…", f15)
    draw.rectangle([170, 52, 639, 91], fill="#FFFFFF", outline="#B9BFC8")
    draw.text((181, 72), "D:\\workspace\\output", font=f15, fill="#1F2933", anchor="lm")
    draw.rectangle([600, 60, 601, 84], fill="#1F2933")
    button(draw, 736, 52, 80, 40, "执行", f15)

    # 左树
    draw.rectangle([8, 108, 187, 631], fill="#FBFCFD", outline="#D0D4DA")
    draw.text((18, 124), "任务", font=f15, fill="#5A6472", anchor="lm")
    button(draw, 16, 140, 150, 28, "导入", f14, selected=True)
    button(draw, 16, 172, 150, 28, "重试", f14)
    button(draw, 16, 204, 150, 28, "设置", f14)
    button(draw, 16, 236, 150, 28, "日志", f14)
    draw.text((18, 300), "轨道 1  …  已就绪", font=f13, fill="#6B7280", anchor="lm")
    draw.text((18, 326), "轨道 2  …  已就绪", font=f13, fill="#6B7280", anchor="lm")
    draw.text((18, 352), "轨道 3  …  运行中", font=f13, fill="#6B7280", anchor="lm")

    # 右侧列表
    draw.rectangle([220, 108, 891, 527], fill="#FFFFFF", outline="#D0D4DA")
    draw.rectangle([221, 109, 890, 140], fill="#F0F2F5")
    draw.text((232, 125), "文件名", font=f14, fill="#5A6472", anchor="lm")
    draw.text((560, 125), "状态", font=f14, fill="#5A6472", anchor="lm")
    draw.text((712, 125), "耗时", font=f14, fill="#5A6472", anchor="lm")
    rows = [("report_20261102_1105.xlsx", "成功", "3.2s"),
            ("report_20261101_1105.xlsx", "成功", "3.4s"),
            ("report_20261031_1105.xlsx", "失败", "0.8s"),
            ("report_20261030_1105.xlsx", "成功", "3.1s"),
            ("report_20261029_1105.xlsx", "成功", "3.3s"),
            ("report_20261028_1105.xlsx", "成功", "3.0s"),
            ("report_20261027_1105.xlsx", "成功", "3.5s")]
    for i, (name, state, cost) in enumerate(rows):
        top = 148 + i * 44
        draw.text((232, top + 14), name, font=f13, fill="#1F2933", anchor="lm")
        draw.text((560, top + 14), state, font=f13, fill="#137333" if state == "成功" else "#B3261E", anchor="lm")
        draw.text((712, top + 14), cost, font=f13, fill="#1F2933", anchor="lm")
        draw.line([221, top + 28, 890, top + 28], fill="#EDEFF2")

    # 输出目录行(打码目标)
    draw.text((224, 550), "输出目录：D:\\workspace\\demo\\output", font=f15,
              fill="#1F2933", anchor="lm")
    # 状态栏
    draw.rectangle([8, 600, 891, 631], fill="#F3F5F7", outline="#D0D4DA")
    draw.text((18, 616), "就绪  |  3 项 / 3 成功  |  DPI 100%", font=f14, fill="#5A6472", anchor="lm")
    return img


def control_list():
    out = []
    for index, (ctype, name, aid, path, x, y, w, h) in enumerate(CONTROLS):
        out.append({
            "index": index,
            "depth": len([seg for seg in path.split("/") if seg]),
            "type": ctype,
            "name": name,
            "automation_id": aid,
            "path": path,
            "screen_rect": {"x": x + ORIGIN["x"], "y": y + ORIGIN["y"], "w": w, "h": h},
            "image_rect": {"x": x, "y": y, "w": w, "h": h},
        })
    return out


def build_dump():
    return {
        "schema": "uia-dump/1",
        "captured_at": "2026-11-02T11:05:00+08:00",
        "exe": "C:\\示例工具\\示例工具.exe",
        "pid": 12345,
        "dpi_scale": 1.0,
        "window": {"hwnd": 1234567, "title": "示例工具 — 主窗口",
                   "screen_rect": {"x": ORIGIN["x"], "y": ORIGIN["y"],
                                   "w": CANVAS["w"], "h": CANVAS["h"]}},
        "shot": {"file": "shot.png", "width": CANVAS["w"], "height": CANVAS["h"]},
        "capture_check": {"method": "PrintWindow+BitBlt",
                          "overlap": {"x": 0, "y": 0, "w": CANVAS["w"], "h": CANVAS["h"]},
                          "mean_abs_diff": 1.2, "suggested_offset": {"dx": 0, "dy": 0}},
        "controls": control_list(),
    }


def build_spec():
    return {
        "schema": "annot-spec/1",
        "figure": "main-window",
        "shot": "shot.png",
        "dump": "dump.json",
        "style": {"font_path": FONT, "font_size": 20,
                  "badge_fill": "#E23B2E", "badge_text": "#FFFFFF", "badge_radius": 14,
                  "box_color": "#E23B2E", "box_width": 3, "box_pad": 4,
                  "arrow_width": 3, "arrow_head_len": 10, "arrow_head_w": 8, "min_gap": 18},
        "legend": {"enabled": True, "title": "图例：主窗口操作顺序", "row_h": 34,
                   "pad_x": 16, "pad_y": 12, "bg": "#F7F7F7", "text_color": "#1F1F1F",
                   "max_text_w": None},
        "steps": [
            {"n": 1, "target": {"name": "浏览…"}, "box": True, "arrow": True,
             "label": "第 1 步：点「浏览…」选择待处理的 xlsx 文件。"},
            {"n": 2, "target": {"automation_id": "btnRun"}, "box": True, "arrow": True,
             "label": "第 2 步：点「执行」开始跑这 3 项。"},
            {"n": 3, "target": {"path": "/Pane[1]/Tree[1]/Button[1]"}, "box": True, "arrow": True,
             "label": "第 3 步：在左树里选中「导入」。"},
            {"n": 4, "target": {"index": 11}, "box": True, "arrow": True,
             "label": "第 4 步：失败后点「重试」重跑该条。"},
        ],
        "redact": [
            {"target": {"automation_id": "lblOutDir"}, "mode": "pixelate", "block": 12},
        ],
        "output": "out/main-window.png",
    }


def main(argv):
    out_dir = os.path.abspath(argv[1] if len(argv) > 1 else
                             os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture"))
    os.makedirs(out_dir, exist_ok=True)
    img = build_image()
    img.save(os.path.join(out_dir, "shot.png"))
    dump = build_dump()
    for control in dump["controls"]:
        screen, image = control["screen_rect"], control["image_rect"]
        expect = (screen["x"] - ORIGIN["x"], screen["y"] - ORIGIN["y"], screen["w"], screen["h"])
        got = (image["x"], image["y"], image["w"], image["h"])
        if expect != got:
            raise SystemExit("fixture 自检失败: index %s image_rect %r != screen-origin %r"
                             % (control["index"], got, expect))
    with open(os.path.join(out_dir, "dump.json"), "w", encoding="utf-8") as fh:
        json.dump(dump, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "spec.json"), "w", encoding="utf-8") as fh:
        json.dump(build_spec(), fh, ensure_ascii=False, indent=2)
    print("fixture dir : %s" % out_dir)
    print("shot        : %dx%d" % img.size)
    print("controls    : %d" % len(dump["controls"]))
    print("selector    : name/automation_id/path/index 四种均有步骤或打码覆盖")


if __name__ == "__main__":
    main(sys.argv)
