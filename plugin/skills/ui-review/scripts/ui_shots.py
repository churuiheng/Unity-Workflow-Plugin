"""Crop, zoom, line up and compare game screenshots for a UI review.

    python ui_shots.py crop    <in.png> <x,y,w,h> <out.png> [--zoom N]
    python ui_shots.py strip   <out.png> <in1.png> <in2.png> ... [--crop x,y,w,h] [--zoom N] [--labels a,b,c]
    python ui_shots.py compare <before.png> <after.png> <out.png> [--crop x,y,w,h] [--zoom N]

Crop boxes are x,y,width,height in screenshot pixels. Zoom uses nearest-neighbour so UI pixels stay honest
(no smoothing that hides aliased corners). Needs Pillow: pip install pillow.
"""
import argparse
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    sys.exit("ui_shots.py needs Pillow: pip install pillow")

GAP = 8
LABEL_H = 26
BACK = (24, 24, 28)
TEXT = (240, 236, 226)


def box(text):
    if not text:
        return None
    parts = [int(float(v)) for v in text.split(",")]
    if len(parts) != 4:
        sys.exit(f"crop box must be x,y,w,h, got {text!r}")
    x, y, w, h = parts
    return (x, y, x + w, y + h)


def load(path, crop, zoom):
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    if zoom and zoom != 1:
        im = im.resize((im.width * zoom, im.height * zoom), Image.NEAREST)
    return im


def line_up(images, labels):
    labelled = any(labels)
    h = max(i.height for i in images) + (LABEL_H if labelled else 0)
    w = sum(i.width for i in images) + GAP * (len(images) - 1)
    out = Image.new("RGB", (w, h), BACK)
    draw = ImageDraw.Draw(out)
    x = 0
    for im, label in zip(images, labels):
        out.paste(im, (x, LABEL_H if labelled else 0))
        if label:
            draw.text((x + 6, 6), label, fill=TEXT)
        x += im.width + GAP
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crop")
    c.add_argument("src")
    c.add_argument("box")
    c.add_argument("out")
    c.add_argument("--zoom", type=int, default=1)

    s = sub.add_parser("strip")
    s.add_argument("out")
    s.add_argument("srcs", nargs="+")
    s.add_argument("--crop")
    s.add_argument("--zoom", type=int, default=1)
    s.add_argument("--labels", default="")

    m = sub.add_parser("compare")
    m.add_argument("before")
    m.add_argument("after")
    m.add_argument("out")
    m.add_argument("--crop")
    m.add_argument("--zoom", type=int, default=1)

    a = ap.parse_args()
    if a.cmd == "crop":
        load(a.src, box(a.box), a.zoom).save(a.out)
    elif a.cmd == "strip":
        labels = a.labels.split(",") if a.labels else [""] * len(a.srcs)
        labels += [""] * (len(a.srcs) - len(labels))
        line_up([load(p, box(a.crop), a.zoom) for p in a.srcs], labels).save(a.out)
    else:
        line_up([load(a.before, box(a.crop), a.zoom), load(a.after, box(a.crop), a.zoom)],
                ["before", "after"]).save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
