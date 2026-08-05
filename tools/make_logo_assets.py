#!/usr/bin/env python3
"""
Rasterise the QuantumForge vector emblem into every brand asset used by the
application and its packaging.

Source of truth (design):  docs/quantumforge_logo.svg
Outputs:
    src/quantumforge/app/resource/image/icon_016.png
    src/quantumforge/app/resource/image/icon_032.png
    src/quantumforge/app/resource/image/icon_048.png
    src/quantumforge/app/resource/image/icon_128.png
    src/quantumforge/app/resource/image/icon_256.png
    src/quantumforge/app/resource/image/icon_512.png
    bin/quantumforge.ico                          (multi-resolution)
    docs/quantumforge_logo.png                    (emblem only, no text)

The emblem is drawn purely from vector primitives (circles, lines, rotated
ellipse polylines, vertical gradient) in a 512-unit design space, then
super-sampled (4x) and Lanczos-downscaled for anti-aliased, scalable output.

Usage:
    python3 tools/make_logo_assets.py
"""
import math
import os
import sys

from PIL import Image, ImageDraw

# --------------------------------------------------------------------------
# Design space (matches docs/quantumforge_logo.svg)
# --------------------------------------------------------------------------
DESIGN = 512.0
CX = CY = 256.0

RIM_R = 251.0
DISC_R = 247.0
INNER_RING_R = 227.0

NAVY = (10, 42, 107)        # #0A2A6B
ROYAL = (20, 85, 200)       # #1455C8
BRIGHT = (46, 134, 224)     # #2E86E0
RIM_DARK = (6, 24, 63)      # #06183F
LIGHT_BLUE = (127, 184, 255)  # #7FB8FF
SHEEN = (159, 208, 255)     # #9FD0FF
ORBITAL = (191, 228, 255)   # #BFE4FF
BOND = (233, 238, 246)      # #E9EEF6
NODE_FILL = (201, 214, 230) # #C9D6E6
NODE_EDGE = (92, 107, 130)  # #5C6B82
NODE_HI = (255, 255, 255)
CORE_OUT = (15, 79, 176)    # #0F4FB0
CORE_MID = (91, 180, 255)   # #5BB4FF
CORE_IN = (234, 249, 255)   # #EAF9FF

NODE_R = 19.0
NODES = [
    (256.0, 158.0),
    (340.74, 207.0),
    (340.74, 305.0),
    (256.0, 354.0),
    (171.26, 305.0),
    (171.26, 207.0),
]
# spoke bonds (centre -> node) + hexagon perimeter bonds
SPOKES = [(CX, CY, x, y) for (x, y) in NODES]
PERIM = [
    (NODES[0][0], NODES[0][1], NODES[1][0], NODES[1][1]),
    (NODES[1][0], NODES[1][1], NODES[2][0], NODES[2][1]),
    (NODES[2][0], NODES[2][1], NODES[3][0], NODES[3][1]),
    (NODES[3][0], NODES[3][1], NODES[4][0], NODES[4][1]),
    (NODES[4][0], NODES[4][1], NODES[5][0], NODES[5][1]),
    (NODES[5][0], NODES[5][1], NODES[0][0], NODES[0][1]),
]

SS = 4  # super-sample factor


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def disc_gradient(size):
    """Vertical navy->royal->bright gradient clipped to the disc circle."""
    k = size / DESIGN
    grad = Image.new("RGB", (size, size), (0, 0, 0))
    px = grad.load()
    for y in range(size):
        t = y / (size - 1)
        if t < 0.5:
            c = lerp(NAVY, ROYAL, t / 0.5)
        else:
            c = lerp(ROYAL, BRIGHT, (t - 0.5) / 0.5)
        for x in range(size):
            px[x, y] = c
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    r = DISC_R * k
    md.ellipse([CX * k - r, CY * k - r, CX * k + r, CY * k + r], fill=255)
    out = grad.convert("RGBA")
    out.putalpha(mask)
    return out


def rotated_ellipse_points(rx, ry, angle_deg, cx, cy, n=120):
    a = math.radians(angle_deg)
    cosA, sinA = math.cos(a), math.sin(a)
    pts = []
    for i in range(n + 1):
        th = 2 * math.pi * i / n
        x = rx * math.cos(th)
        y = ry * math.sin(th)
        xr = x * cosA - y * sinA + cx
        yr = x * sinA + y * cosA + cy
        pts.append((xr, yr))
    return pts


def draw_emblem(out_size):
    """Render the emblem at out_size (square), RGBA, transparent background."""
    size = out_size * SS
    k = size / DESIGN

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    # 1. outer dark rim
    rr = RIM_R * k
    d.ellipse([CX * k - rr, CY * k - rr, CX * k + rr, CY * k + rr],
              fill=RIM_DARK + (255,))

    # 2. blue gradient disc
    canvas.alpha_composite(disc_gradient(size))

    d = ImageDraw.Draw(canvas)

    # 3. top rim-light (glossy upper highlight) - drawn as an alpha arc band
    hl_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hld = ImageDraw.Draw(hl_layer)
    arc_r_out = (DISC_R - 4) * k
    arc_r_in = (DISC_R - 30) * k
    # build a crescent polygon across the top
    top_pts = []
    steps = 64
    for i in range(steps + 1):
        th = math.radians(200 + 140 * i / steps)  # ~200..340 deg => top arc
        top_pts.append((CX * k + arc_r_out * math.cos(th),
                        CY * k + arc_r_out * math.sin(th)))
    for i in range(steps + 1):
        th = math.radians(340 - 140 * i / steps)
        top_pts.append((CX * k + arc_r_in * math.cos(th),
                        CY * k + arc_r_in * math.sin(th)))
    hld.polygon(top_pts, fill=SHEEN + (60,))
    canvas.alpha_composite(hl_layer)

    d = ImageDraw.Draw(canvas)
    # 4. inner contour ring
    ir = INNER_RING_R * k
    d.ellipse([CX * k - ir, CY * k - ir, CX * k + ir, CY * k + ir],
              outline=LIGHT_BLUE + (76,), width=max(2, int(round(3 * k))))

    # 5. quantum orbital arcs (3 rotated ellipses)
    orb = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    od = ImageDraw.Draw(orb)
    w_orb = max(2, int(round(3.4 * k)))
    for ang in (0, 60, 120):
        pts = rotated_ellipse_points(172 * k, 64 * k, ang, CX * k, CY * k)
        od.line(pts, fill=ORBITAL + (140,), width=w_orb, joint="curve")
    canvas.alpha_composite(orb)

    d = ImageDraw.Draw(canvas)
    # 6. hexagonal lattice bonds
    bonds = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bonds)
    w_bond = max(3, int(round(9.5 * k)))
    for (x1, y1, x2, y2) in SPOKES + PERIM:
        bd.line([(x1 * k, y1 * k), (x2 * k, y2 * k)],
                fill=BOND + (242,), width=w_bond)
        # round caps
        cap = w_bond / 2.0
        bd.ellipse([x1 * k - cap, y1 * k - cap, x1 * k + cap, y1 * k + cap],
                   fill=BOND + (242,))
        bd.ellipse([x2 * k - cap, y2 * k - cap, x2 * k + cap, y2 * k + cap],
                   fill=BOND + (242,))
    canvas.alpha_composite(bonds)

    d = ImageDraw.Draw(canvas)
    # 7. silver lattice nodes (flat vector style + highlight)
    nr = NODE_R * k
    for (x, y) in NODES:
        cxp, cyp = x * k, y * k
        d.ellipse([cxp - nr, cyp - nr, cxp + nr, cyp + nr],
                  fill=NODE_FILL + (255,),
                  outline=NODE_EDGE + (255,), width=max(1, int(round(1.5 * k))))
        hi = nr * 0.40
        d.ellipse([cxp - nr * 0.55, cyp - nr * 0.7,
                   cxp - nr * 0.55 + hi * 2, cyp - nr * 0.7 + hi * 2],
                  fill=NODE_HI + (235,))
    # 8. central glowing quantum core
    cr = NODE_R * 1.21 * k
    d.ellipse([CX * k - cr, CY * k - cr, CX * k + cr, CY * k + cr],
              fill=CORE_OUT + (255,))
    cr2 = cr * 0.62
    d.ellipse([CX * k - cr2, CY * k - cr2, CX * k + cr2, CY * k + cr2],
              fill=CORE_MID + (255,))
    cr3 = cr * 0.30
    d.ellipse([CX * k - cr3, CY * k - cr3 * 1.3, CX * k + cr3, CY * k - cr3 * 1.3 + cr3 * 2],
              fill=CORE_IN + (255,))

    if out_size != size:
        canvas = canvas.resize((out_size, out_size), Image.LANCZOS)
    return canvas


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
ICON_SIZES = [16, 32, 48, 128, 256, 512]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    icon_dir = os.path.join(REPO, "src", "quantumforge", "app", "resource", "image")
    icons = {}
    for s in ICON_SIZES:
        img = draw_emblem(s)
        path = os.path.join(icon_dir, f"icon_{s:03d}.png")
        img.save(path, "PNG")
        icons[s] = img
        print(f"wrote {os.path.relpath(path, REPO)}  ({s}x{s})")

    # multi-resolution Windows icon (built from the 512 master)
    ico_path = os.path.join(REPO, "bin", "quantumforge.ico")
    icons[512].save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {os.path.relpath(ico_path, REPO)}  (multi-resolution ICO)")

    # docs banner: emblem only, generous canvas, transparent
    banner = draw_emblem(1024)
    banner_path = os.path.join(REPO, "docs", "quantumforge_logo.png")
    banner.save(banner_path, "PNG")
    print(f"wrote {os.path.relpath(banner_path, REPO)}  (1024x1024 emblem, no text)")

    print("\nSHA-256 (update docs/ASSET_PROVENANCE_MANIFEST.md):")
    import hashlib
    for rel in [
        "src/quantumforge/app/resource/image/icon_256.png",
        "bin/quantumforge.ico",
        "docs/quantumforge_logo.png",
        "docs/quantumforge_logo.svg",
    ]:
        p = os.path.join(REPO, rel)
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        print(f"  {rel}: {h}")


if __name__ == "__main__":
    main()
