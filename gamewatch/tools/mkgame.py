#!/usr/bin/env python3
"""Turn a Game & Watch ROM dump (+ optional MAME-style SVG artwork and a key
map) into build/game_data.c for the AP30 module.

  mkgame.py --rom tl-28 --svg gnw_tbridge.svg --keys games/tbridge.json -o build/game_data.c

Without --svg every LCD segment is drawn as a small box in a grid, which is
enough to see a ROM running and to work out which segment is which.
"""
import argparse, json, re, subprocess, sys, tempfile, os
import xml.etree.ElementTree as ET

SCREEN_W, SCREEN_H = 296, 240
ROM_PAGE = 0x2c0
KEYS = ["power", "back", "right", "left", "up", "down", "vol_a", "vol_b", "play"]
LINES = {"fixed": 8, "ba": 9, "b": 10, "acl": 11}


def pack_rom(data):
    if len(data) == 4 * ROM_PAGE:
        return data
    if len(data) != 0x1000:
        sys.exit("ROM must be 4096 bytes (or 2816 packed), got %d" % len(data))
    out = b""
    for n in range(4):
        blk = data[n * 0x400:(n + 1) * 0x400]
        if any(blk[ROM_PAGE:]) and any(b != 0xff for b in blk[ROM_PAGE:]):
            print("warning: ROM block %d has data past 0x2c0; is this an SM510 ROM?" % n, file=sys.stderr)
        out += blk[:ROM_PAGE]
    return out


def keymap(path):
    m = [0xff, 0] * len(KEYS)
    if not path:
        return m
    cfg = json.load(open(path))
    for name, v in cfg.get("keys", {}).items():
        if name not in KEYS:
            sys.exit("unknown key %r (use %s)" % (name, ", ".join(KEYS)))
        i = KEYS.index(name)
        if isinstance(v, str):
            m[2 * i] = LINES[v]
        elif "s" in v:
            if not 1 <= v["s"] <= 8:
                sys.exit("%s: s must be 1-8" % name)
            m[2 * i], m[2 * i + 1] = v["s"] - 1, v["k"]
        else:
            m[2 * i], m[2 * i + 1] = LINES["fixed"], v["k"]
    return m


def seg_id(title):
    """MAME names a segment group.segment.common."""
    m = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", title or "")
    if not m:
        return None
    g, s, h = map(int, m.groups())
    if g > 2 or s > 15 or h > 3:
        return None
    return g * 64 + s * 4 + h


def grid_masks(scale):
    """Diagnostic layout: a and b as 16x4 grids, bs as 2x4."""
    w, h = SCREEN_W // scale, SCREEN_H // scale
    cw, ch = w // 17, h // 11
    masks = {}
    for g, rows0 in ((0, 0), (1, 5)):
        for s in range(16):
            for c in range(4):
                masks[g * 64 + s * 4 + c] = box(s * cw + cw // 2, (rows0 + c) * ch + ch // 2, cw - 2, ch - 2)
    for s in range(2):
        for c in range(4):
            masks[128 + s * 4 + c] = box((s * 4 + c) * cw + cw // 2, 10 * ch + ch // 4, cw - 2, ch // 2)
    return masks, w, h


def box(x, y, w, h):
    return {yy: [(x, x + max(w, 1))] for yy in range(y, y + max(h, 1))}


SHAPES = {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "text", "image", "use"}


def svg_masks(path, scale, ss=3):
    """Render the SVG once with every segment in its own flat colour."""
    from PIL import Image
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    tree = ET.parse(path)
    root = tree.getroot()
    local = lambda e: e.tag.split("}")[-1]

    vb = root.get("viewBox")
    if vb:
        _, _, vw, vh = map(float, vb.replace(",", " ").split())
    else:
        vw, vh = float(re.sub(r"[a-z%]+$", "", root.get("width"))), float(re.sub(r"[a-z%]+$", "", root.get("height")))
    fit = min(SCREEN_W / scale / vw, SCREEN_H / scale / vh)
    w, h = max(1, int(vw * fit)), max(1, int(vh * fit))

    found = set()

    def paint(e, colour):
        st = "fill:%s;stroke:none;opacity:1;fill-opacity:1" % colour
        e.set("style", st)
        for k in ("fill", "stroke", "opacity", "filter", "mask", "clip-path"):
            e.attrib.pop(k, None)

    def walk(e, sid):
        if local(e) in ("defs", "title", "desc", "metadata", "namedview"):
            return
        t = next((c.text for c in e if local(c) == "title"), None)
        mine = seg_id(t)
        if mine is not None:
            sid = mine
            found.add(sid)
        if sid is not None:
            paint(e, "#%02x00ff" % (sid + 1))
        elif local(e) in SHAPES:
            e.set("style", "display:none")
        elif e is not root:
            for k in ("filter", "mask", "clip-path", "opacity"):
                e.attrib.pop(k, None)
        for c in e:
            walk(c, sid)

    walk(root, None)
    if not found:
        sys.exit("no segments found in %s (expected <title>group.segment.common</title>)" % path)
    root.set("shape-rendering", "crispEdges")

    with tempfile.TemporaryDirectory() as td:
        src, png = os.path.join(td, "s.svg"), os.path.join(td, "s.png")
        tree.write(src)
        subprocess.run(["rsvg-convert", "-w", str(w * ss), "-h", str(h * ss), "-b", "white", "-o", png, src], check=True)
        px = Image.open(png).convert("RGB").load()

    need = (ss * ss + 1) // 2
    masks = {}
    for y in range(h):
        count = {}
        row = {}
        for x in range(w):
            count.clear()
            for sy in range(ss):
                for sx in range(ss):
                    r, g, b = px[x * ss + sx, y * ss + sy]
                    if g == 0 and b == 255 and r:
                        count[r - 1] = count.get(r - 1, 0) + 1
            for sid, n in count.items():
                if n >= need:
                    runs = row.setdefault(sid, [])
                    if runs and runs[-1][1] == x:
                        runs[-1] = (runs[-1][0], x + 1)
                    else:
                        runs.append((x, x + 1))
        for sid, runs in row.items():
            masks.setdefault(sid, {})[y] = runs
    missing = sorted(found - set(masks))
    if missing:
        print("warning: %d segments too small to draw at this size" % len(missing), file=sys.stderr)
    return masks, w, h


def encode(sid, rows):
    """rows: {y: [(x0, x1), ...]} -> one or more records for this segment."""
    out = bytearray()
    xbase = min(r[0][0] for r in rows.values()) & ~1
    ys = sorted(rows)
    recs = []  # (y, rep, runs)
    for y in ys:
        runs = rows[y]
        if recs and recs[-1][0] + recs[-1][1] == y and recs[-1][2] == runs and recs[-1][1] < 32:
            recs[-1] = (recs[-1][0], recs[-1][1] + 1, runs)
        else:
            recs.append((y, 1, runs))

    def run_bytes(runs):
        b, x = [], xbase
        for x0, x1 in runs:
            gap = x0 - x
            while gap > 255:
                b.append((255, 0)); gap -= 255
            n = x1 - x0
            while n > 255:
                b.append((gap, 255)); gap = 0; n -= 255
            b.append((gap, n))
            x = x1
        return b

    # a record holds consecutive rows; rows with more than 7 runs, and gaps
    # between rows, start a new record with the same id
    groups, cur = [], None
    for y, rep, runs in recs:
        # at most 7 encoded runs per row; the rest goes to another record
        chunks, part = [], []
        for r in runs:
            part.append(r)
            if len(run_bytes(part)) > 7:
                part.pop(); chunks.append(run_bytes(part)); part = [r]
        chunks.append(run_bytes(part))
        for ci, ch in enumerate(chunks):
            if ci == 0 and cur and cur["y"] + cur["h"] == y and len(cur["rows"]) < 255:
                cur["rows"].append((rep, ch)); cur["h"] += rep
            else:
                cur = {"y": y, "h": rep, "rows": [(rep, ch)]}
                groups.append(cur)
    for g in groups:
        out += bytes([sid, g["y"], len(g["rows"]), xbase // 2])
        for rep, ch in g["rows"]:
            out.append((rep - 1) << 3 | len(ch))
            for gap, n in ch:
                out += bytes([gap, n])
    return out


def rgb565(s):
    v = int(s.lstrip("#"), 16)
    r, g, b = v >> 16, v >> 8 & 0xff, v & 0xff
    return (r >> 3) << 11 | (g >> 2) << 5 | b >> 3


def c_array(name, data, ctype="uint8_t"):
    lines = [", ".join("0x%02x" % b for b in data[i:i + 16]) for i in range(0, len(data), 16)]
    return "const %s %s[] = {\n  %s\n};\n" % (ctype, name, ",\n  ".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--svg")
    ap.add_argument("--keys", help="JSON key map (see games/*.json)")
    ap.add_argument("--scale", type=int, default=1, choices=(1, 2, 3, 4), help="screen pixels per artwork pixel")
    ap.add_argument("--bg", default="#b8c4a8")
    ap.add_argument("--fg", default="#101810")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--preview", help="write a PNG with every segment on")
    a = ap.parse_args()

    rom = pack_rom(open(a.rom, "rb").read())
    if a.svg:
        masks, w, h = svg_masks(a.svg, a.scale)
    else:
        masks, w, h = grid_masks(a.scale)
    if w > 255 * 2 or h > 255:
        sys.exit("artwork too large; raise --scale")
    xoff, yoff = (SCREEN_W - w * a.scale) // 2, (SCREEN_H - h * a.scale) // 2

    segs = bytearray()
    for sid in sorted(masks):
        segs += encode(sid, masks[sid])
    segs.append(0xff)

    if a.preview:
        try:
            from PIL import Image
        except ImportError:
            Image = None
            print("note: Pillow is not installed, skipping the preview picture", file=sys.stderr)
    if a.preview and Image:
        img = Image.new("RGB", (SCREEN_W, SCREEN_H), a.bg)
        for rows in masks.values():
            for y, runs in rows.items():
                for x0, x1 in runs:
                    img.paste(a.fg, (xoff + x0 * a.scale, yoff + y * a.scale, xoff + x1 * a.scale, yoff + (y + 1) * a.scale))
        img.save(a.preview)

    with open(a.out, "w") as f:
        f.write('/* generated by mkgame.py - do not edit */\n#include "game.h"\n\n')
        f.write(c_array("gw_rom", rom))
        f.write(c_array("gw_segs", segs))
        f.write(c_array("gw_keymap", keymap(a.keys)).replace("[]", "[18]"))
        f.write("const struct gw_cfg gw_cfg = { 0x%04x, 0x%04x, %d, %d, %d };\n" % (rgb565(a.bg), rgb565(a.fg), a.scale, xoff, yoff))
    print("rom %d bytes, %d segments, artwork %dx%d x%d, segment data %d bytes" % (len(rom), len(masks), w, h, a.scale, len(segs)))


if __name__ == "__main__":
    main()
