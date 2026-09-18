"""Build the 'Reviewing an Edit' image for slide 8.

Screenshot on top with the proposed edit boxed, an arrow down to a magnified
strip of that same edit. Borders and arrow are black.

The explanatory sidebar text is deliberately NOT baked in here - it lives as an
editable PowerPoint text box, added by build_deck.py.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
SRC = os.path.join(OUT, "src_document_page.png")
os.makedirs(OUT, exist_ok=True)

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# Region of the source screenshot holding the proposed edit + evidence + buttons
CROP = (548, 684, 1128, 778)

CANVAS_W, CANVAS_H = 2020, 1430
SHOT_X, SHOT_Y, SHOT_W = 60, 70, 1900
ZOOM_X, ZOOM_Y, ZOOM_W = 60, 1060, 1900

shot = Image.open(SRC).convert("RGB")
scale = SHOT_W / shot.width
shot_r = shot.resize((SHOT_W, int(shot.height * scale)), Image.LANCZOS)

canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), WHITE)
canvas.paste(shot_r, (SHOT_X, SHOT_Y))
d = ImageDraw.Draw(canvas)

# box the edit inside the full screenshot
bx0 = SHOT_X + int(CROP[0] * scale)
by0 = SHOT_Y + int(CROP[1] * scale)
bx1 = SHOT_X + int(CROP[2] * scale)
by1 = SHOT_Y + int(CROP[3] * scale)
for w in range(5):
    d.rectangle([bx0 - w, by0 - w, bx1 + w, by1 + w], outline=BLACK)

# magnified strip, aligned to the screenshot's width
zoom = shot.crop(CROP)
zoom_r = zoom.resize((ZOOM_W, int(zoom.height * (ZOOM_W / zoom.width))),
                     Image.LANCZOS)
for w in range(5):
    d.rectangle([ZOOM_X - 6 - w, ZOOM_Y - 6 - w,
                 ZOOM_X + zoom_r.width + 6 + w,
                 ZOOM_Y + zoom_r.height + 6 + w], outline=BLACK)
canvas.paste(zoom_r, (ZOOM_X, ZOOM_Y))

# arrow from the boxed edit down into the strip
cx = (bx0 + bx1) // 2
d.line([cx, by1 + 12, cx, ZOOM_Y - 48], fill=BLACK, width=7)
d.polygon([(cx, ZOOM_Y - 16), (cx - 22, ZOOM_Y - 52), (cx + 22, ZOOM_Y - 52)],
          fill=BLACK)

path = os.path.join(OUT, "fig_document_callout.png")
canvas.save(path, "PNG")
print("wrote", path, canvas.size, f"aspect {canvas.width/canvas.height:.2f}:1")
