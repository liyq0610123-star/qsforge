"""
Generate assets/qsforge.ico from scratch so we don't commit binary art
we can't regenerate. Run this once (or whenever the brand changes):

    python tools/make_icon.py

Output: assets/qsforge.ico with sizes 16, 32, 48, 64, 128, 256.

Design brief
------------
The icon has to hold up at both 256px (installer / about dialog) and 16px
(taskbar / Alt-Tab). That means two rules:

  1. Silhouette must read as a "rounded dark square with a bright A" even
     at 16px. So the A is bold, centred, and occupies >55% of the tile.
  2. No fussy decoration. At 128+ we add a subtle highlight and a fine 1px
     inner stroke for depth; at 16–32 these details are suppressed so the
     glyph stays crisp and the tile doesn't look grey.

Colour palette is a polished version of the in-app navy theme:
  - Deep navy gradient   (#12213E → #0A1222)
  - Accent blue          (#5B8DEF) for the geometric underline mark
  - Bright white glyph   (#F4F7FC)
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "qsforge.ico"

# Brand colours ---------------------------------------------------------------
NAVY_TOP = (18, 33, 62, 255)       # #12213E — slightly brighter for top edge
NAVY_BOT = (10, 18, 34, 255)       # #0A1222 — deep base for shadow side
ACCENT   = (91, 141, 239, 255)     # #5B8DEF — same blue used in the UI
HIGHLIGHT = (255, 255, 255, 40)    # faint specular top sheen
STROKE   = (255, 255, 255, 28)     # 1px inner rim at large sizes
GLYPH    = (244, 247, 252, 255)    # near-white, easier on dark bg than pure #FFF

SIZES = [256, 128, 64, 48, 32, 16]


def _font_for(size_px: int) -> ImageFont.ImageFont:
    """Pick the most polished bold sans available on the host system."""
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",    # Segoe UI Bold (default on Win10/11)
        "C:/Windows/Fonts/SegUIVar.ttf",    # Segoe UI Variable (Win11)
        "C:/Windows/Fonts/seguisb.ttf",     # Segoe UI Semibold
        "C:/Windows/Fonts/arialbd.ttf",     # Arial Bold fallback
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size=size_px)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _vgradient(w: int, h: int, top: tuple[int, int, int, int],
               bot: tuple[int, int, int, int]) -> Image.Image:
    """Return a WxH vertical gradient image (RGBA)."""
    grad = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        a = int(top[3] + (bot[3] - top[3]) * t)
        grad.putpixel((0, y), (r, g, b, a))
    return grad.resize((w, h))


def _rounded_mask(size: int, radius: int) -> Image.Image:
    """1-bit alpha mask for a rounded square."""
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [(0, 0), (size - 1, size - 1)], radius=radius, fill=255
    )
    return m


def _build_tile(size: int) -> Image.Image:
    """Render a single size. Detail level scales with size."""
    # Supersample at 3x for sizes ≥ 48 so anti-aliasing is butter-smooth.
    scale = 3 if size >= 48 else 2 if size >= 24 else 1
    S = size * scale

    # 1. Gradient fill clipped to a rounded square.
    radius = int(S * 0.23)
    grad = _vgradient(S, S, NAVY_TOP, NAVY_BOT)
    mask = _rounded_mask(S, radius)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(tile)

    # 2. Soft specular highlight along the top — gives the tile a subtle
    #    "glass" feel at large sizes. Skip at tiny sizes (would just look
    #    like noise).
    if size >= 48:
        hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hl)
        hl_h = int(S * 0.38)
        hd.ellipse(
            [(-int(S * 0.15), -int(S * 0.55)),
             (int(S * 1.15), hl_h)],
            fill=HIGHLIGHT,
        )
        hl = hl.filter(ImageFilter.GaussianBlur(S * 0.03))
        # Clip highlight to the rounded square.
        highlight = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        highlight.paste(hl, (0, 0), mask)
        tile = Image.alpha_composite(tile, highlight)
        d = ImageDraw.Draw(tile)

    # 3. Crisp bold "A" glyph, optically centred.
    #    Font size tuned per resolution — smaller tiles need a relatively
    #    larger glyph to stay legible.
    if size <= 16:
        glyph_ratio = 0.72
        nudge = -0.02
    elif size <= 32:
        glyph_ratio = 0.64
        nudge = -0.04
    else:
        glyph_ratio = 0.56
        nudge = -0.05

    font = _font_for(int(S * glyph_ratio))
    bbox = d.textbbox((0, 0), "A", font=font, anchor="lt")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    gx = (S - tw) / 2 - bbox[0]
    gy = (S - th) / 2 - bbox[1] + S * nudge
    d.text((gx, gy), "A", fill=GLYPH, font=font)

    # 4. Precision accent mark — a short, thin blue bar that sits right
    #    under the A's baseline. Replaces the wider accent strip from the
    #    first-pass design; the narrower mark reads better and feels more
    #    "instrument panel" than "boutique monogram".
    if size >= 24:
        bar_w = int(S * 0.28)
        bar_h = max(2, int(S * 0.035))
        bar_y = int(S * 0.78)
        bx = (S - bar_w) // 2
        d.rounded_rectangle(
            [(bx, bar_y), (bx + bar_w, bar_y + bar_h)],
            radius=bar_h // 2,
            fill=ACCENT,
        )

    # 5. 1px inner hairline stroke for definition against dark backgrounds
    #    in Windows Explorer / installer chrome. Large sizes only.
    if size >= 64:
        stroke_img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stroke_img)
        sd.rounded_rectangle(
            [(0, 0), (S - 1, S - 1)], radius=radius,
            outline=STROKE, width=max(1, int(S * 0.006)),
        )
        tile = Image.alpha_composite(tile, stroke_img)

    # Downsample to the target size.
    if scale != 1:
        tile = tile.resize((size, size), Image.LANCZOS)
    return tile


def build_icon() -> None:
    layers = [_build_tile(s) for s in SIZES]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes each explicit size into the .ico container so the OS
    # always picks the right pre-rendered tile instead of rescaling.
    largest = layers[0]
    largest.save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=layers[1:],
    )
    print(
        f"Wrote {OUT}  "
        f"({OUT.stat().st_size / 1024:.1f} KB, {len(SIZES)} resolutions)"
    )

    # Also dump a PNG preview so designers can eyeball the final 256px
    # tile without opening an .ico viewer.
    preview = OUT.with_suffix(".preview.png")
    largest.save(preview, format="PNG")
    print(f"Preview: {preview}")


if __name__ == "__main__":
    build_icon()
