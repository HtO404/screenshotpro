#!/usr/bin/env python3
"""Measure side of the screenshot-annotation pipeline.

Given a Windows desktop exe: launch it, capture the whole window with
PrintWindow, export the full UIA control tree, cross-check the capture
against a screen BitBlt of the visible part, and land
{shot.png, dump.json} plus a measurement log.

Coordinates in dump.json are pixels with the image top-left as origin.
No scaling is ever applied: shot.size == window.screen_rect size, and
image_rect == screen_rect - window.screen_rect origin.
"""
import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

import numpy as np
from PIL import Image

IMAGE_EXT = ".png"
EXE_IMAGE_NAME = ""  # basename of --exe; resolved in main(), never hardcoded
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          r"System32\WindowsPowerShell\v1.0\powershell.exe")
SHIFT_RANGE = 3
NEGATIVE_SHIFT = 30
DIFF_LIMIT = 3.0
NEGATIVE_MIN = 5.0
SETTLE_MS = 800
CAPTURE_ROUNDS = 3
RETRY_MS = 700
REQUIRED_NAMES = []  # names from --require-name; resolved in main()


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Log:
    def __init__(self):
        self.buf = []
        self.path = None

    def __call__(self, msg=""):
        line = str(msg)
        self.buf.append(line)
        print(line)

    def flush(self):
        if not self.path:
            return
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.buf) + "\n")


def ps_process_snapshot():
    """Return {pid: image_name} for the exe image we care about."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    found = {}
    for row in csv.reader(io.StringIO(out.stdout or "")):
        if len(row) >= 2 and EXE_IMAGE_NAME and row[0].lower() == EXE_IMAGE_NAME.lower():
            try:
                found[int(row[1])] = row[0]
            except ValueError:
                pass
    return found


def kill_pid(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                   capture_output=True, text=True, errors="replace")


def run_ps1(ps1, exe, workdir, wait_sec, log, settle_ms=SETTLE_MS,
            capture_rounds=CAPTURE_ROUNDS, retry_ms=RETRY_MS, timeout=300):
    cmd = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", ps1, "-Exe", exe, "-WorkDir", workdir, "-WaitSec", str(wait_sec),
           "-SettleMs", str(settle_ms), "-CaptureRounds", str(capture_rounds),
           "-RetryMs", str(retry_ms), "-DiffThreshold", str(DIFF_LIMIT)]
    log("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    stdout = (proc.stdout or b"").decode("utf-8", "replace")
    stderr = (proc.stderr or b"").decode("utf-8", "replace")
    for line in stdout.splitlines():
        log("  [ps] " + line)
    for line in stderr.splitlines():
        log("  [ps:err] " + line)
    log("  [ps] exit=%d" % proc.returncode)
    return proc.returncode, stdout, stderr


def load_rgb(path):
    im = Image.open(path)
    im.load()
    return im, np.asarray(im.convert("RGB"), dtype=np.int16)


def diff_at(shot_reg, bb, dx, dy):
    """Mean abs diff treating bb[x+dx, y+dy] as the counterpart of shot_reg[x, y]."""
    h, w = shot_reg.shape[:2]
    x0, x1 = max(0, -dx), min(w, w - dx)
    y0, y1 = max(0, -dy), min(h, h - dy)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return float("inf"), 0
    a = shot_reg[y0:y1, x0:x1]
    b = bb[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
    return float(np.mean(np.abs(a - b))), int((x1 - x0) * (y1 - y0))


def sweep_offset(shot_reg, bb, rng):
    table = []
    best = None
    for dy in range(-rng, rng + 1):
        for dx in range(-rng, rng + 1):
            d, n = diff_at(shot_reg, bb, dx, dy)
            table.append((dx, dy, d, n))
            if best is None or d < best[2]:
                best = (dx, dy, d, n)
    return best, table


def rect_inside(r, w, h):
    return (r["x"] >= 0 and r["y"] >= 0 and r["w"] > 0 and r["h"] > 0
            and r["x"] + r["w"] <= w and r["y"] + r["h"] <= h)


def build_dump(meta, rows, shot_size, capture_check, exe):
    wr = meta["window_rect"]
    ox, oy = wr["x"], wr["y"]
    controls = []
    for r in rows:
        sr = r["screen_rect"]
        controls.append({
            "index": r["index"],
            "depth": r["depth"],
            "type": r["type"],
            "name": r["name"],
            "automation_id": r["automation_id"],
            "path": r["path"],
            "screen_rect": {"x": sr["x"], "y": sr["y"], "w": sr["w"], "h": sr["h"]},
            "image_rect": {"x": sr["x"] - ox, "y": sr["y"] - oy, "w": sr["w"], "h": sr["h"]},
        })
    dpi = meta.get("dpi_for_window") or 0
    dpi_scale = round(dpi / 96.0, 4) if dpi else 1.0
    return {
        "schema": "uia-dump/1",
        "captured_at": now_iso(),
        "exe": exe,
        "pid": meta["pid"],
        "dpi_scale": dpi_scale,
        "window": {
            "hwnd": meta["hwnd"],
            "title": meta["window_title"],
            "screen_rect": {"x": ox, "y": oy, "w": wr["w"], "h": wr["h"]},
        },
        "shot": {"file": "shot" + IMAGE_EXT, "width": shot_size[0], "height": shot_size[1]},
        "capture_check": capture_check,
        "controls": controls,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Capture a Windows app window + UIA control tree.")
    ap.add_argument("--exe", required=True, help="absolute path of the exe to measure")
    ap.add_argument("--out", required=True, help="output figure directory")
    ap.add_argument("--wait", type=int, default=6, help="seconds after launch before capture")
    ap.add_argument("--log", default=None, help="log file path (default <out>/measure-log.txt)")
    ap.add_argument("--require-name", action="append", default=[], metavar="NAME",
                    help="assert this UIA control name exists and is fully inside the shot; repeatable")
    ap.add_argument("--settle-ms", type=int, default=SETTLE_MS,
                    help="ms to wait after raising the window before each capture attempt")
    ap.add_argument("--capture-rounds", type=int, default=CAPTURE_ROUNDS,
                    help="capture attempts before giving up; each one re-raises and re-checks")
    ap.add_argument("--retry-ms", type=int, default=RETRY_MS,
                    help="ms between capture attempts")
    args = ap.parse_args(argv)

    exe = os.path.abspath(args.exe)
    out = os.path.abspath(args.out)

    global EXE_IMAGE_NAME, REQUIRED_NAMES
    EXE_IMAGE_NAME = os.path.basename(exe)
    REQUIRED_NAMES[:] = list(args.require_name or [])

    os.makedirs(out, exist_ok=True)
    log = Log()
    log.path = args.log or os.path.join(out, "measure-log.txt")
    log("measure_win.py exe=%s out=%s wait=%d" % (exe, out, args.wait))
    log("launcher=" + sys.executable)
    log("captured_at=" + now_iso())

    if not os.path.isfile(exe):
        log("FATAL exe not found: " + exe)
        log.flush()
        return 2
    ps1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uia_dump.ps1")
    if not os.path.isfile(ps1):
        log("FATAL ps1 not found: " + ps1)
        log.flush()
        return 2

    baseline = set(ps_process_snapshot())
    log("baseline %s pids=%s (pre-existing, not launched by this run)"
        % (EXE_IMAGE_NAME, sorted(baseline) or "none"))

    workdir = tempfile.mkdtemp(prefix="screenshotpro-measure-")
    log("workdir=" + workdir)
    rc, _, _ = run_ps1(ps1, exe, workdir, args.wait, log,
                       settle_ms=args.settle_ms, capture_rounds=args.capture_rounds,
                       retry_ms=args.retry_ms)

    leftover = {}
    try:
        after = ps_process_snapshot()
        leftover = {p: n for p, n in after.items() if p not in baseline}
        if leftover:
            log("RESIDUAL pid(s) after capture: %s -> killing" % sorted(leftover))
            for p in leftover:
                kill_pid(p)
            after2 = ps_process_snapshot()
            leftover = {p: n for p, n in after2.items() if p not in baseline}
    finally:
        log("residual check after run: %s" % (sorted(leftover) or "none"))

    def fail(msg):
        log("FAILED: " + msg)
        log("residual=%s" % (sorted(leftover) or "none"))
        log.flush()
        shutil.rmtree(workdir, ignore_errors=True)
        return 1

    meta_path = os.path.join(workdir, "meta.json")
    if rc != 0 or not os.path.isfile(meta_path):
        return fail("powershell capture failed (exit=%s)" % rc)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    if "error" in meta:
        return fail("capture error: %s" % meta["error"])

    rounds = meta.get("capture_round_log") or []
    if isinstance(rounds, dict):
        rounds = [rounds]
    log("capture rounds=%s accepted=%s (settle_ms=%d max_rounds=%d retry_ms=%d)"
        % (meta.get("capture_rounds"), meta.get("capture_accepted"),
           args.settle_ms, args.capture_rounds, args.retry_ms))
    for row in rounds:
        log("  round %s: foreground=%s wait_ms=%s diff=%s on_top=%s top=%s"
            % (row.get("round"), row.get("foreground"), row.get("wait_ms"), row.get("diff"),
               row.get("on_top"), row.get("top")))

    gwr = meta["getwindowrect"]
    wr = meta["window_rect"]
    ins = meta["frame_inset"]
    log("GetWindowRect     x=%d y=%d w=%d h=%d" % (gwr["x"], gwr["y"], gwr["w"], gwr["h"]))
    log("DWM visible frame x=%d y=%d w=%d h=%d  (hresult=%s used=%s)"
        % (wr["x"], wr["y"], wr["w"], wr["h"],
           meta["dwm_extended_frame"]["hresult"], meta["dwm_extended_frame"]["used"]))
    log("frame inset L=%d T=%d R=%d B=%d  <- Win11 DWM invisible resize border, not painted by the app"
        % (ins["left"], ins["top"], ins["right"], ins["bottom"]))
    if (ins["left"] or ins["top"] or ins["right"] or ins["bottom"]):
        log("NOTE GetWindowRect overshoots the visible window; the ring is transparent (the screen shows")
        log("     whatever is behind it, PrintWindow leaves it unpainted). The visible frame is used as")
        log("     window.screen_rect and the PrintWindow bitmap is cropped to it, so shot == what is on screen.")
    ur = meta["uia_top_rect"]
    log("window(UIA top)   x=%d y=%d w=%d h=%d  title=%r" % (ur["x"], ur["y"], ur["w"], ur["h"], meta["window_title"]))
    if (ur["x"], ur["y"], ur["w"], ur["h"]) != (gwr["x"], gwr["y"], gwr["w"], gwr["h"]):
        log("NOTE GetWindowRect and UIA top-level rect differ; GetWindowRect is authoritative.")
    log("screen=%dx%d virtual=%dx%d dpi_aware=%s dpi_for_window=%s dpi_scale=%.4f"
        % (meta["screen_w"], meta["screen_h"], meta["virtual_screen"]["w"], meta["virtual_screen"]["h"],
           meta["dpi_aware"], meta.get("dpi_for_window"), (meta.get("dpi_for_window") or 0) / 96.0))
    log("printwindow flags=%s ok=%s size=%sx%s" % (meta["printwindow_flags"], meta["printwindow_ok"],
                                                   meta["printwindow_size"]["w"], meta["printwindow_size"]["h"]))

    pw_img, pw = load_rgb(os.path.join(workdir, "printwindow.png"))
    log("printwindow image=%dx%d" % pw_img.size)
    if pw_img.size != (wr["w"], wr["h"]):
        return fail("PrintWindow image %dx%d != window.screen_rect %dx%d (no scaling allowed)"
                    % (pw_img.size[0], pw_img.size[1], wr["w"], wr["h"]))

    ov = meta["overlap"]
    log("overlap(window-local) x=%d y=%d w=%d h=%d (%.1f%% of the shot)"
        % (ov["x"], ov["y"], ov["w"], ov["h"], 100.0 * ov["w"] * ov["h"] / (wr["w"] * wr["h"])))
    if not meta["bitblt_ok"] or not os.path.isfile(os.path.join(workdir, "bitblt.png")):
        return fail("no on-screen area captured with BitBlt; cannot cross-check")
    bb_img, bb = load_rgb(os.path.join(workdir, "bitblt.png"))
    log("bitblt image=%dx%d" % bb_img.size)
    if bb_img.size != (ov["w"], ov["h"]):
        return fail("BitBlt image %dx%d != overlap %dx%d" % (bb_img.size[0], bb_img.size[1], ov["w"], ov["h"]))

    shot_reg = pw[ov["y"]:ov["y"] + ov["h"], ov["x"]:ov["x"] + ov["w"]]
    d0, n0 = diff_at(shot_reg, bb, 0, 0)
    log("mean_abs_diff @ (0,0) = %.4f over %d px" % (d0, n0))
    best, table = sweep_offset(shot_reg, bb, SHIFT_RANGE)
    log("offset sweep -%d..%d (dx,dy -> mean_abs_diff), %d candidates:" % (SHIFT_RANGE, SHIFT_RANGE, len(table)))
    for dx, dy, d, n in sorted(table, key=lambda t: (t[1], t[0])):
        log("   %+d,%+d  %.4f%s" % (dx, dy, d, "  <== best" if (dx, dy) == (best[0], best[1]) else ""))
    log("suggested_offset dx=%d dy=%d (diff %.4f)" % (best[0], best[1], best[2]))
    d1, _ = diff_at(shot_reg, bb, 1, 0)
    d1v, _ = diff_at(shot_reg, bb, 0, 1)
    log("sensitivity: 1 px shift -> horizontal %.4f, vertical %.4f (0 px -> %.4f)" % (d1, d1v, d0))

    neg = []
    for name, dx, dy in (("E", NEGATIVE_SHIFT, 0), ("W", -NEGATIVE_SHIFT, 0),
                         ("S", 0, NEGATIVE_SHIFT), ("N", 0, -NEGATIVE_SHIFT)):
        d, n = diff_at(shot_reg, bb, dx, dy)
        neg.append((name, dx, dy, d, n))
        log("negative-test shift %s(%+d,%+d) mean_abs_diff=%.4f over %d px" % (name, dx, dy, d, n))
    neg_max = max(t[3] for t in neg)
    neg_min = min(t[3] for t in neg)

    with open(os.path.join(workdir, "tree.json"), encoding="utf-8") as f:
        tree = json.load(f)
    rows = tree if isinstance(tree, list) else [tree]
    rows = [r for r in rows if isinstance(r, dict)]
    log("controls=%d (skipped_empty=%s, cap=400 depth<=6 RawViewWalker)"
        % (len(rows), meta.get("controls_skipped_empty")))

    if d0 >= DIFF_LIMIT:
        hint = ""
        if meta.get("capture_on_top") is False:
            top = meta.get("capture_top_window") or {}
            hint = (" -- the screen at the capture point belongs to %s (pid %s, title %r), not to "
                    "the app: the desktop is locked or another window covers it. No capture "
                    "setting can fix this; unlock the desktop and re-run."
                    % (top.get("proc") or "?", top.get("pid"), top.get("title") or ""))
        return fail("cross-check mean_abs_diff %.4f >= %.1f: coordinate frame mismatch%s"
                    % (d0, DIFF_LIMIT, hint))
    if (best[0], best[1]) != (0, 0):
        return fail("suggested_offset (%d,%d) != (0,0)" % (best[0], best[1]))
    if neg_max < NEGATIVE_MIN:
        return fail("negative test insensitive: best shifted diff %.4f < %.1f" % (neg_max, NEGATIVE_MIN))
    if len(rows) < 15:
        return fail("only %d controls (<15)" % len(rows))

    capture_check = {
        "method": "PrintWindow+BitBlt",
        "overlap": {"x": ov["x"], "y": ov["y"], "w": ov["w"], "h": ov["h"]},
        "mean_abs_diff": round(d0, 3),
        "suggested_offset": {"dx": best[0], "dy": best[1]},
    }
    dump = build_dump(meta, rows, pw_img.size, capture_check, exe)

    by_name = {}
    for c in dump["controls"]:
        by_name.setdefault(c["name"], c)
    for want in REQUIRED_NAMES:
        c = by_name.get(want)
        if c is None:
            return fail("required control %r not found in UIA tree" % want)
        ir = c["image_rect"]
        ok_inside = rect_inside(ir, *pw_img.size)
        log("required %r image_rect x=%d y=%d w=%d h=%d inside=%s"
            % (want, ir["x"], ir["y"], ir["w"], ir["h"], ok_inside))
        if not ok_inside:
            return fail("required control %r image_rect not inside the image" % want)

    shot_path = os.path.join(out, "shot" + IMAGE_EXT)
    pw_img.convert("RGB").save(shot_path, format="PNG")
    with open(os.path.join(out, "dump.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log("wrote " + shot_path + " (%dx%d)" % pw_img.size)
    log("wrote " + os.path.join(out, "dump.json"))
    log("checks: shot==screen_rect OK | mean_abs_diff %.4f < %.1f OK | offset (%d,%d) OK | controls %d >= 15 OK | negative 30px max %.4f >= %.1f OK (min %.4f)"
        % (d0, DIFF_LIMIT, best[0], best[1], len(rows), neg_max, NEGATIVE_MIN, neg_min))
    log("residual=%s" % (sorted(leftover) or "none"))
    log("OK")
    log.flush()
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
