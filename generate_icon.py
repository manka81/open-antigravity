"""
Icon Generator using PIL to create high-resolution icon.ico and icon.png.
"""
from PIL import Image, ImageDraw

def create_app_icon():
    size = (256, 256)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Dark Rounded Background
    draw.rounded_rectangle([(10, 10), (246, 246)], radius=50, fill="#0d1117", outline="#30363d", width=3)

    # 2. Glowing Shield Outer
    shield_pts = [
        (128, 45),
        (195, 65),
        (205, 120),
        (190, 180),
        (128, 220),
        (66, 180),
        (51, 120),
        (61, 65)
    ]
    draw.polygon(shield_pts, fill="#161b22", outline="#58a6ff", width=4)

    # 3. Globe Ring / Ellipse
    draw.ellipse([(85, 80), (171, 180)], outline="#388bfd", width=3)
    draw.line([(60, 130), (196, 130)], fill="#388bfd", width=3)

    # 4. Lightning Bolt in Center (Green / Neon)
    bolt_pts = [
        (135, 75),
        (105, 130),
        (128, 130),
        (115, 185),
        (155, 120),
        (132, 120)
    ]
    draw.polygon(bolt_pts, fill="#3fb950", outline="#2ea043", width=2)

    # 5. Status Dot
    draw.ellipse([(185, 45), (210, 70)], fill="#3fb950", outline="#ffffff", width=2)

    img.save("icon.png", format="PNG")
    img.save("icon.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
    print("Icons icon.png and icon.ico successfully generated.")

if __name__ == "__main__":
    create_app_icon()
