#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convert a captured screenshot to PNG and cut a padded proof crop from it.

usage: python shotcrop.py <src_image> <shot_png> <x> <y> <w> <h> <pad> <proof_png> [zoom]
"""
import os
import sys
from PIL import Image

src, shot_png = sys.argv[1], sys.argv[2]
x, y, w, h, pad = (int(v) for v in sys.argv[3:8])
proof = sys.argv[8]
zoom = int(sys.argv[9]) if len(sys.argv) > 9 else 1

im = Image.open(src).convert("RGB")
if os.path.abspath(src) != os.path.abspath(shot_png):
    im.save(shot_png, "PNG")
box = (max(0, x - pad), max(0, y - pad), min(im.size[0], x + w + pad), min(im.size[1], y + h + pad))
crop = im.crop(box)
if zoom > 1:
    crop = crop.resize((crop.size[0] * zoom, crop.size[1] * zoom), Image.NEAREST)
crop.save(proof, "PNG")
print("source %dx%d -> %s" % (im.size[0], im.size[1], shot_png))
print("crop box %r -> %s (%dx%d zoom=%d)" % (box, proof, crop.size[0], crop.size[1], zoom))