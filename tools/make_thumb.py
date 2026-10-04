#!/usr/bin/env python3
"""Generate assets/thumb.png -- the mod's thumbnail shown in the in-game Mods menu.

Deterministic, dependency free (only zlib/struct from the standard library) so the asset can
always be reproduced from the repository:

    python3 tools/make_thumb.py [out.png]

The picture is intentionally simple: a winter night sky over a snowline with the ice crystal that
the mod adds to South Clock Town rendered as a faceted gem.
"""

import pathlib
import struct
import sys
import zlib

WIDTH = 512
HEIGHT = 512


def clamp(v):
    return 0 if v < 0 else 255 if v > 255 else int(v)


def mix(a, b, t):
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return tuple(clamp(a[i] + (b[i] - a[i]) * t) for i in range(3))


def luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def draw():
    img = [[(0, 0, 0)] * WIDTH for _ in range(HEIGHT)]

    sky_top = (8, 12, 40)
    sky_bottom = (36, 58, 106)
    for y in range(HEIGHT):
        row = mix(sky_top, sky_bottom, y / (HEIGHT - 1))
        for x in range(WIDTH):
            img[y][x] = row

    # Stars: a cheap hash keeps them reproducible without importing random.
    for i in range(260):
        h = (i * 2654435761) & 0xFFFFFFFF
        x = h % WIDTH
        y = (h >> 11) % (HEIGHT * 3 // 5)
        size = 1 + (h >> 29) % 2
        bright = 150 + ((h >> 17) & 0x7F)
        for dy in range(size):
            for dx in range(size):
                xx, yy = min(x + dx, WIDTH - 1), min(y + dy, HEIGHT - 1)
                img[yy][xx] = mix(img[yy][xx], (bright, bright, min(255, bright + 30)), 0.9)

    # Moon, upper right.
    mx, my, mr = 404, 96, 46
    for y in range(my - mr - 2, my + mr + 3):
        for x in range(mx - mr - 2, mx + mr + 3):
            if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                continue
            d = ((x - mx) ** 2 + (y - my) ** 2) ** 0.5
            if d <= mr:
                shade = 232 - int(28 * (d / mr))
                img[y][x] = (shade, shade, clamp(shade + 12))
            elif d <= mr + 2:
                img[y][x] = mix(img[y][x], (200, 210, 230), (mr + 2 - d) / 2 * 0.5)

    # Snow covered ground with a soft horizon.
    horizon = int(HEIGHT * 0.78)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if y >= horizon:
                t = (y - horizon) / (HEIGHT - horizon)
                img[y][x] = mix((214, 228, 244), (150, 172, 206), t)

    def crystal_outline():
        """Six sided gem: a tall hexagon, plus the facet lines below."""
        cx, cy = WIDTH // 2, int(HEIGHT * 0.52)
        w, h = 96, 150
        pts = [(cx, cy - h), (cx + w, cy - h // 3), (cx + int(w * 0.72), cy + h * 0.78),
               (cx, cy + h), (cx - int(w * 0.72), cy + h * 0.78), (cx - w, cy - h // 3)]
        return cx, cy, w, h, pts

    cx, cy, w, h, pts = crystal_outline()

    def inside_polygon(x, y, poly):
        hit = False
        n = len(poly)
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if (y0 > y) != (y1 > y):
                xint = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if x < xint:
                    hit = not hit
        return hit

    core = (150, 226, 255)
    edge = (28, 74, 132)
    highlight = (246, 253, 255)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if not inside_polygon(x + 0.5, y + 0.5, pts):
                continue
            # Radial shading from the top vertex down, with vertical facet bands.
            t = (y - (cy - h)) / (2 * h)
            col = mix(highlight, core, min(1.0, t * 1.6))
            band = abs(((x - cx) / (w * 1.3) + 0.5) * 6) % 1.0
            col = mix(col, edge, 0.35 if band > 0.86 else 0.0)
            col = mix(col, edge, max(0.0, t - 0.62) * 1.1)
            img[y][x] = col

    # Facet edges: draw the polygon border and the two inner ridges.
    def line(x0, y0, x1, y1, colour, width=3):
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            t = i / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            for dy in range(-width // 2, width // 2 + 1):
                for dx in range(-width // 2, width // 2 + 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < WIDTH and 0 <= yy < HEIGHT:
                        img[yy][xx] = mix(img[yy][xx], colour, 0.85)

    n = len(pts)
    for i in range(n):
        line(*pts[i], *pts[(i + 1) % n], (230, 248, 255), 3)
    line(*pts[0], cx, cy + h, (196, 236, 255), 2)
    line(pts[1][0], pts[1][1], cx, cy + h, (120, 190, 235), 2)
    line(pts[4][0], pts[4][1], cx, cy + h, (120, 190, 235), 2)

    # Frosty glow and a cast shadow on the snow.
    for y in range(HEIGHT):
        for x in range(WIDTH):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d < 240:
                img[y][x] = mix(img[y][x], (170, 220, 255), (1 - d / 240) ** 2 * 0.18)
    sy = int(pts[2][1]) + 6
    if 0 <= sy < HEIGHT:
        for x in range(cx - 130, cx + 130):
            if 0 <= x < WIDTH:
                fade = 1 - abs(x - cx) / 130
                img[sy][x] = mix(img[sy][x], (96, 120, 158), 0.35 * fade)

    # Falling snow over everything, so the image reads as "winter".
    for i in range(180):
        hsh = (i * 40503) & 0xFFFFFFFF
        x = hsh % WIDTH
        y = (hsh >> 9) % HEIGHT
        r = 1 + (hsh >> 25) % 3
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < WIDTH and 0 <= yy < HEIGHT and luma(img[yy][xx]) < 215:
                        img[yy][xx] = mix(img[yy][xx], (255, 255, 255), 0.75)

    return img


def write_png(path, img):
    raw = b"".join(b"\x00" + b"".join(bytes(c) + b"\xff" for c in row) for row in img)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return len(png)


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "assets/thumb.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    size = write_png(out, draw())
    print(f"{out} - {WIDTH}x{HEIGHT} RGBA, {size} bytes")


if __name__ == "__main__":
    main()
