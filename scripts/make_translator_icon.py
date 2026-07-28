#!/usr/bin/env python3
"""Draw the toolbar icon for the Moly.hu Translator plugin.

Original artwork. Two overlapping speech bubbles carrying a letter each is the
usual way to say "translation" in an icon, and it stays readable when a
toolbar renders it at 16px: the two-bubble silhouette survives the downscale
even once the letters have blurred away. The letters are "A" and the Hungarian
"A" with an acute accent, since that is the direction this plugin translates
in.

Kept to bold shapes on purpose - an earlier attempt drew an open book with
page ruling, which looked fine at 128px and turned to mush at toolbar size.

Run: python3 scripts/make_translator_icon.py
"""

import pathlib

from PIL import Image, ImageDraw, ImageFont

SIZE = 512  # drawn large, downsampled for antialiasing
OUTPUT = pathlib.Path(__file__).parent.parent / 'calibre_translator' / 'images'
FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
)

SOURCE = (46, 91, 138, 255)   # blue bubble, the original language
TARGET = (240, 160, 24, 255)  # amber bubble, the translation
GLYPH = (255, 255, 255, 255)


def load_font(size):
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit('no bold sans font found; install fonts-dejavu')


def bubble(draw, box, tail, colour):
    """A rounded rectangle with a triangular tail, drawn as one shape."""
    draw.rounded_rectangle(box, radius=44, fill=colour)
    draw.polygon(tail, fill=colour)


def centred(draw, text, font, centre, colour):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (centre[0] - (right + left) / 2, centre[1] - (bottom + top) / 2),
        text, font=font, fill=colour,
    )


def draw_icon():
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = load_font(150)

    # Back bubble, upper left: the source language.
    bubble(draw, (16, 26, 300, 268), [(74, 250), (74, 330), (150, 258)], SOURCE)
    centred(draw, 'A', font, (158, 142), GLYPH)

    # Front bubble, lower right, overlapping: the translation. Drawn second so
    # it sits on top, which is what makes the pair read as one object.
    draw.rounded_rectangle((196, 236, 496, 486), radius=44, fill=(0, 0, 0, 0))
    bubble(draw, (204, 244, 496, 486), [(430, 468), (430, 500), (356, 476)], TARGET)
    centred(draw, 'Á', font, (350, 356), GLYPH)

    return image


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    target = OUTPUT / 'moly_hu_translator.png'
    icon.resize((128, 128), Image.LANCZOS).save(target)
    print('wrote', target)


if __name__ == '__main__':
    main()
