"""Generate the 3D honeycomb pattern, the logo and the app icons.

Run once after changing colors; the generated files are committed.
Needs Pillow:  .venv\\Scripts\\python -m pip install pillow
Run:           .venv\\Scripts\\python tools\\make_graphics.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

# Königsblau palette
ROYAL_BRIGHT = (58, 104, 240)   # #3a68f0
ROYAL = (31, 79, 209)           # #1f4fd1
ROYAL_DEEP = (16, 42, 128)      # #102a80
NAVY = (8, 20, 64)              # #081440
WHITE = (255, 255, 255)

LIGHT = (-math.sqrt(0.5), -math.sqrt(0.5))  # light falls in from the top left


def hex_points(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Corners of a pointy-top hexagon."""
    return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in (-90, -30, 30, 90, 150, 210)]


def bevel(cx: float, cy: float, r_outer: float, r_inner: float):
    """The six slanted edge faces of a raised hexagon and how brightly each is lit (-1..1)."""
    outer, inner = hex_points(cx, cy, r_outer), hex_points(cx, cy, r_inner)
    faces = []
    for i in range(6):
        j = (i + 1) % 6
        angle = math.radians(-60 + 60 * i)  # outward normal of the edge i -> j
        light = math.cos(angle) * LIGHT[0] + math.sin(angle) * LIGHT[1]
        faces.append(([outer[i], outer[j], inner[j], inner[i]], light))
    return faces, inner


def fmt(points) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


# --- SVG pattern ---------------------------------------------------------------

def honeycomb_svg(r: float = 22, gap: float = 1.5, depth: float = 5) -> str:
    """One seamless tile of raised hexagon cells, drawn as white/black overlays."""
    width, height = math.sqrt(3) * r, 3 * r
    centers = [(width / 2, r), (0, 2.5 * r), (width, 2.5 * r), (0, -0.5 * r), (width, -0.5 * r)]
    shapes = []
    for cx, cy in centers:
        outer_r = r - gap
        faces, inner = bevel(cx, cy, outer_r, outer_r - depth)
        for polygon, light in faces:
            if light >= 0:
                shapes.append(f'<polygon points="{fmt(polygon)}" fill="#fff" '
                              f'fill-opacity="{0.06 + 0.30 * light:.3f}"/>')
            else:
                shapes.append(f'<polygon points="{fmt(polygon)}" fill="#000" '
                              f'fill-opacity="{0.08 + 0.34 * -light:.3f}"/>')
        shapes.append(f'<polygon points="{fmt(inner)}" fill="url(#top)"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}" height="{height:.3f}" '
        f'viewBox="0 0 {width:.3f} {height:.3f}">'
        '<defs><linearGradient id="top" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#fff" stop-opacity=".16"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity=".03"/>'
        '</linearGradient></defs>' + "".join(shapes) + "</svg>\n"
    )


def logo_svg() -> str:
    """App logo: a raised royal-blue honeycomb cell with a euro sign."""
    cx = cy = 32
    faces, inner = bevel(cx, cy, 30, 23)
    shapes = []
    for polygon, light in faces:
        color = _mix(ROYAL, WHITE, 0.45 * light) if light >= 0 else _mix(ROYAL, NAVY, 0.7 * -light)
        shapes.append(f'<polygon points="{fmt(polygon)}" fill="{_hex(color)}"/>')
    shapes.append(f'<polygon points="{fmt(inner)}" fill="url(#face)"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        '<defs><linearGradient id="face" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{_hex(ROYAL_BRIGHT)}"/>'
        f'<stop offset="1" stop-color="{_hex(ROYAL_DEEP)}"/>'
        '</linearGradient></defs>' + "".join(shapes) +
        '<text x="32" y="33" text-anchor="middle" dominant-baseline="central" '
        'font-family="Segoe UI, system-ui, sans-serif" font-weight="700" font-size="27" '
        'fill="#fff">€</text></svg>\n'
    )


# --- PNG icons -----------------------------------------------------------------

def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(color) -> str:
    return "#" + "".join(f"{c:02x}" for c in color)


def _euro_font(size: int):
    for path in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def draw_icon(size: int, maskable: bool) -> Image.Image:
    scale = 4  # draw large, then shrink for smooth edges
    s = size * scale
    canvas = Image.new("RGBA", (s, s))
    draw = ImageDraw.Draw(canvas)
    for y in range(s):  # vertical royal-blue gradient
        draw.line([(0, y), (s, y)], fill=_mix(ROYAL_BRIGHT, NAVY, y / s) + (255,))

    # Subtle honeycomb in the background
    overlay = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    r = s / 7
    width = math.sqrt(3) * r
    row = 0
    y = -r
    while y < s + r:
        x = -width + (width / 2 if row % 2 else 0)
        while x < s + width:
            faces, inner = bevel(x, y, r * 0.95, r * 0.95 - r * 0.2)
            for polygon, light in faces:
                if light >= 0:
                    odraw.polygon(polygon, fill=(255, 255, 255, round(18 + 50 * light)))
                else:
                    odraw.polygon(polygon, fill=(0, 0, 0, round(20 + 60 * -light)))
            x += width
        y += 1.5 * r
        row += 1
    canvas.alpha_composite(overlay)

    # The big raised cell in the middle (smaller on maskable icons: safe zone)
    radius = s * (0.30 if maskable else 0.36)
    cx = cy = s / 2
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(hex_points(cx + s * 0.012, cy + s * 0.022, radius), fill=(0, 0, 20, 110))
    canvas.alpha_composite(shadow)
    faces, inner = bevel(cx, cy, radius, radius * 0.80)
    for polygon, light in faces:
        color = _mix((226, 234, 255), WHITE, light) if light >= 0 else _mix((200, 214, 250), (120, 145, 215), -light)
        draw.polygon(polygon, fill=color + (255,))
    top = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(top)
    for i in range(2 * s):  # diagonal face gradient: light top-left, slightly darker bottom-right
        tdraw.line([(i, 0), (i - s, s)], fill=_mix((250, 252, 255), (214, 225, 252), i / (2 * s)) + (255,), width=3)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).polygon(inner, fill=255)
    canvas.paste(top, (0, 0), mask)
    draw.text((cx, cy + s * 0.01), "€", font=_euro_font(round(radius * 0.95)), fill=ROYAL + (255,), anchor="mm")

    if not maskable:  # rounded square for the normal icon
        corner = Image.new("L", (s, s), 0)
        ImageDraw.Draw(corner).rounded_rectangle([0, 0, s - 1, s - 1], radius=round(s * 0.22), fill=255)
        canvas.putalpha(corner)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    (STATIC / "img").mkdir(parents=True, exist_ok=True)
    (STATIC / "icons").mkdir(parents=True, exist_ok=True)
    (STATIC / "img" / "honeycomb.svg").write_text(honeycomb_svg(), encoding="utf-8")
    (STATIC / "icons" / "logo.svg").write_text(logo_svg(), encoding="utf-8")
    draw_icon(512, maskable=False).save(STATIC / "icons" / "icon-512.png")
    draw_icon(192, maskable=False).save(STATIC / "icons" / "icon-192.png")
    draw_icon(512, maskable=True).save(STATIC / "icons" / "maskable-512.png")
    draw_icon(180, maskable=True).convert("RGB").save(STATIC / "icons" / "apple-touch-icon.png")
    draw_icon(32, maskable=False).save(STATIC / "icons" / "favicon-32.png")
    print("Grafiken erzeugt in", STATIC)


if __name__ == "__main__":
    main()
