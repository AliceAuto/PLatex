from PIL import Image, ImageDraw, ImageFont
import math
import os


def create_platex_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size
    pad = int(s * 0.06)
    r = int(s * 0.20)

    bg = [
        (99, 102, 241),
        (139, 92, 246),
        (168, 85, 247),
        (192, 132, 252),
    ]
    steps = s
    for y in range(s):
        t = y / max(s - 1, 1)
        idx = t * (len(bg) - 1)
        i_lo = int(idx)
        i_hi = min(i_lo + 1, len(bg) - 1)
        frac = idx - i_lo
        r_col = int(bg[i_lo][0] + frac * (bg[i_hi][0] - bg[i_lo][0]))
        g_col = int(bg[i_lo][1] + frac * (bg[i_hi][1] - bg[i_lo][1]))
        b_col = int(bg[i_lo][2] + frac * (bg[i_hi][2] - bg[i_lo][2]))
        draw.line([(0, y), (s, y)], fill=(r_col, g_col, b_col, 255))

    draw.rounded_rectangle([pad, pad, s - pad - 1, s - pad - 1], radius=r)

    inner_pad = int(s * 0.12)
    inner_r = int(s * 0.14)
    draw.rounded_rectangle(
        [inner_pad, inner_pad, s - inner_pad - 1, s - inner_pad - 1],
        radius=inner_r,
        fill=(30, 27, 45, 230),
    )

    cx, cy = s // 2, s // 2

    font_path = None
    candidate_paths = [
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for fp in candidate_paths:
        if os.path.exists(fp):
            font_path = fp
            break

    if font_path and os.path.exists(font_path):
        try:
            font_big = ImageFont.truetype(font_path, int(s * 0.52))
            font_small = ImageFont.truetype(font_path, int(s * 0.18))
        except Exception:
            font_big = ImageFont.load_default()
            font_small = ImageFont.load_default()
    else:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    letter = "P"
    bbox = draw.textbbox((0, 0), letter, font=font_big)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    lx = cx - tw // 2 - bbox[0]
    ly = cy - th // 2 - bbox[1] - int(s * 0.04)

    shadow_color = (0, 0, 0, 60)
    for dx in range(3):
        draw.text((lx + dx + 2, ly + 2), letter, font=font_big, fill=shadow_color)

    highlight_color = (199, 210, 254)
    draw.text((lx, ly), letter, font=font_big, fill=highlight_color)

    sub = "LTX"
    bbox_sub = draw.textbbox((0, 0), sub, font=font_small)
    sw = bbox_sub[2] - bbox_sub[0]
    sh = bbox_sub[3] - bbox_sub[1]
    sx = cx - sw // 2 - bbox_sub[0]
    sy = ly + th + int(s * 0.02) - int(s * 0.03)

    accent_color = (167, 139, 250)
    draw.text((sx, sy), sub, font=font_small, fill=accent_color)

    dot_cx = int(s * 0.72)
    dot_cy = int(s * 0.28)
    dot_r = int(s * 0.055)
    draw.ellipse(
        [dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r],
        fill=(251, 191, 36, 255),
    )

    return img


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(out_dir, exist_ok=True)

    ico_path = os.path.join(out_dir, "platex-client.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        icon_img = create_platex_icon(sz)
        images.append(icon_img)
        print(f"  Generated {sz}x{sz}")

    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[1:],
    )
    print(f"\nSaved ICO to: {ico_path}")

    png_path = os.path.join(out_dir, "platex-client.png")
    png_img = create_platex_icon(512)
    png_img.save(png_path, format="PNG")
    print(f"Saved PNG to: {png_path}")


if __name__ == "__main__":
    main()
