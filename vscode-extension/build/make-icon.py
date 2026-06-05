#!/usr/bin/env python3
"""Generate a placeholder marketplace icon (128x128 icon.png).

A Telegram-blue rounded square with a white checkmark — conveys "remote
approval". Replace with real branding art before a polished launch.

Run: python3 build/make-icon.py
"""
import os
from PIL import Image, ImageDraw

SIZE = 128
TOP = (42, 171, 238)     # #2AABEE  (Telegram blue, lighter)
BOTTOM = (24, 140, 200)   # #188CC8  (darker)
OUT = os.path.join(os.path.dirname(__file__), "..", "icon.png")


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), top)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def main():
    base = vertical_gradient(SIZE, TOP, BOTTOM)

    # Rounded-square alpha mask so corners are transparent.
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=28, fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(base, (0, 0), mask)

    # White checkmark.
    draw = ImageDraw.Draw(icon)
    draw.line([(34, 66), (56, 88), (96, 42)], fill=(255, 255, 255, 255), width=13, joint="curve")
    # Round the stroke ends so it looks clean.
    for pt in [(34, 66), (56, 88), (96, 42)]:
        draw.ellipse([pt[0] - 6, pt[1] - 6, pt[0] + 6, pt[1] + 6], fill=(255, 255, 255, 255))

    icon.save(os.path.abspath(OUT))
    print(f"wrote {os.path.abspath(OUT)} ({icon.size[0]}x{icon.size[1]})")


if __name__ == "__main__":
    main()
