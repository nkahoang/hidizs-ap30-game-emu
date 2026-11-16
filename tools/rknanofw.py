#!/usr/bin/env python3
"""Unpack / repack Rockchip RKnano firmware images (Hidizs AP30 HIFIYFxx.IMG).

    rknanofw.py info   FW.IMG
    rknanofw.py unpack FW.IMG OUTDIR
    rknanofw.py pack   OUTDIR NEW.IMG

Layout handled:
    0x000   header (0x200 bytes, "RKnanoFW" magic at 0x1f8, fw size at 0x1f4)
    0x200   code, fonts, tables, ROCK26IMAGERES image resources (contiguous)
    ...     zero padding up to fw size
    fwsize  copy of the header, zero padding
    last 4  Rockchip RKCRC of everything before it

Pixels are big-endian RGB565. pack keeps every section at its original size and offset. Images are edited by
replacing the BMP files in OUTDIR/images (same width and height as the original).
"""
import json
import os
import struct
import sys

MAGIC = b"RKnanoFW"
RES_MAGIC = b"ROCK26IMAGERES"
HDR_SIZE = 0x200
NAME_REC = 108

# name, header field holding the offset, header field holding the size
SECTIONS = [
    ("code", 0x54, 0x70),
    ("font0", 0x78, 0x7C),
    ("font1", 0x80, 0x84),
    ("charmap", 0xCC, 0xD0),
    ("menu", 0xF8, 0xFC),
    ("res", 0x14C, 0x150),
]


def die(msg):
    sys.exit("error: " + msg)


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _crc_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C10DB7) if c & 0x80000000 else (c << 1)
        table.append(c & 0xFFFFFFFF)
    return table


def rkcrc(data):
    table = _crc_table()
    c = 0
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ table[(c >> 24) ^ b]
    return c


def parse(img):
    """Validate the layout and return (sections, fw_size)."""
    if img[0x1F8:0x200] != MAGIC:
        die("no RKnanoFW magic at 0x1f8")
    fw_size = u32(img, 0x1F4)
    if fw_size + HDR_SIZE > len(img) - 4:
        die("firmware size field points outside the file")
    secs = []
    pos = HDR_SIZE
    for name, off_f, size_f in SECTIONS:
        off, size = u32(img, off_f), u32(img, size_f)
        if off != pos:
            die("section %s at 0x%x, expected 0x%x (not contiguous)" % (name, off, pos))
        secs.append({"name": name, "offset": off, "size": size})
        pos = off + size
    if pos > fw_size:
        die("sections overrun the firmware size")
    if any(img[pos:fw_size]):
        die("non-zero data between last section and header copy")
    if img[fw_size:fw_size + HDR_SIZE] != img[:HDR_SIZE]:
        die("header copy differs from header")
    if any(img[fw_size + HDR_SIZE:len(img) - 4]):
        die("non-zero data after header copy")
    return secs, fw_size


def parse_res(res):
    """Return the image entry list of a ROCK26IMAGERES section."""
    if not res.startswith(RES_MAGIC):
        die("resource section has no ROCK26IMAGERES magic")
    count = u32(res, 0x10)
    ents = []
    for i in range(count):
        w, h, x, y, size, off = struct.unpack_from("<4H2I", res, 0x20 + 16 * i)
        if size != w * h * 2 or off + size > len(res):
            die("image %d: unexpected entry (not raw 16-bit pixels)" % i)
        ents.append({"index": i, "w": w, "h": h, "x": x, "y": y, "offset": off})
    names_at = max(e["offset"] + e["w"] * e["h"] * 2 for e in ents)
    for e in ents:
        rec = res[names_at + NAME_REC * e["index"]:][:NAME_REC]
        name = rec.split(b"\0", 1)[0].decode("ascii", "replace")
        # each name record ends with offset, width, height of its image
        if struct.unpack_from("<3I", rec, NAME_REC - 12) != (e["offset"], e["w"], e["h"]):
            name = ""
        e["name"] = name
    return ents


def image_filename(e):
    name = e["name"] or "IMAGE.BMP"
    safe = "".join(c if c.isalnum() or c in "_-(),." else "_" for c in name)
    if safe.upper().endswith(".BMP"):
        safe = safe[:-4]
    return "%03d_%s.bmp" % (e["index"], safe)


def rgb565_to_bmp(raw, w, h):
    row_pad = (-w * 3) % 4
    rows = []
    for y in range(h - 1, -1, -1):  # BMP is bottom-up
        row = bytearray()
        for (p,) in struct.iter_unpack(">H", raw[y * w * 2:(y + 1) * w * 2]):
            r, g, b = p >> 11, (p >> 5) & 0x3F, p & 0x1F
            row += bytes(((b << 3) | (b >> 2), (g << 2) | (g >> 4), (r << 3) | (r >> 2)))
        rows.append(bytes(row) + b"\0" * row_pad)
    body = b"".join(rows)
    head = struct.pack("<2sIHHI", b"BM", 54 + len(body), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    return head + info + body


def bmp_to_rgb565(bmp, w, h, path):
    if bmp[:2] != b"BM":
        die("%s: not a BMP file" % path)
    data_off = u32(bmp, 10)
    bw, bh, _planes, bpp, comp = struct.unpack_from("<iiHHI", bmp, 18)
    if bpp not in (24, 32) or comp not in (0, 3):
        die("%s: need an uncompressed 24 or 32 bit BMP" % path)
    if (bw, abs(bh)) != (w, h):
        die("%s: is %dx%d, firmware slot is %dx%d" % (path, bw, abs(bh), w, h))
    step = bpp // 8
    stride = (w * step + 3) & ~3
    if data_off + stride * h > len(bmp):
        die("%s: truncated" % path)
    out = bytearray()
    for y in range(h):
        src = y if bh < 0 else h - 1 - y
        row = bmp[data_off + src * stride:][:w * step]
        for i in range(0, w * step, step):
            b, g, r = row[i], row[i + 1], row[i + 2]
            out += struct.pack(">H", ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    return bytes(out)


def cmd_info(path):
    img = open(path, "rb").read()
    secs, fw_size = parse(img)
    stored, calc = u32(img, len(img) - 4), rkcrc(img[:-4])
    print("file size   0x%x" % len(img))
    print("fw size     0x%x" % fw_size)
    print("build date  %02x%02x-%02x-%02x" % (img[1], img[0], img[3], img[2]))
    print("crc         stored %08x, computed %08x (%s)" % (stored, calc, "ok" if stored == calc else "BAD"))
    for s in secs:
        print("  %-8s offset 0x%07x  size 0x%07x" % (s["name"], s["offset"], s["size"]))
    res = next(s for s in secs if s["name"] == "res")
    ents = parse_res(img[res["offset"]:res["offset"] + res["size"]])
    print("images      %d" % len(ents))


def cmd_unpack(path, out):
    img = open(path, "rb").read()
    secs, fw_size = parse(img)
    if u32(img, len(img) - 4) != rkcrc(img[:-4]):
        die("CRC mismatch, image is corrupt")
    os.makedirs(os.path.join(out, "images"), exist_ok=True)
    with open(os.path.join(out, "header.bin"), "wb") as f:
        f.write(img[:HDR_SIZE])
    for s in secs:
        with open(os.path.join(out, s["name"] + ".bin"), "wb") as f:
            f.write(img[s["offset"]:s["offset"] + s["size"]])
    res = next(s for s in secs if s["name"] == "res")
    blob = img[res["offset"]:res["offset"] + res["size"]]
    ents = parse_res(blob)
    for e in ents:
        e["file"] = image_filename(e)
        raw = blob[e["offset"]:e["offset"] + e["w"] * e["h"] * 2]
        with open(os.path.join(out, "images", e["file"]), "wb") as f:
            f.write(rgb565_to_bmp(raw, e["w"], e["h"]))
    manifest = {"source": os.path.basename(path), "file_size": len(img),
                "fw_size": fw_size, "sections": secs, "images": ents}
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("unpacked %d sections and %d images to %s" % (len(secs), len(ents), out))


def cmd_pack(src, out_path):
    with open(os.path.join(src, "manifest.json")) as f:
        man = json.load(f)
    header = open(os.path.join(src, "header.bin"), "rb").read()
    if len(header) != HDR_SIZE or header[0x1F8:] != MAGIC:
        die("header.bin is not a valid RKnano header")
    if u32(header, 0x1F4) != man["fw_size"]:
        die("header.bin firmware size does not match manifest")
    img = bytearray(man["file_size"])
    img[:HDR_SIZE] = header
    for (name, off_f, size_f), s in zip(SECTIONS, man["sections"]):
        data = bytearray(open(os.path.join(src, name + ".bin"), "rb").read())
        if (u32(header, off_f), u32(header, size_f)) != (s["offset"], s["size"]):
            die("header.bin and manifest disagree about section " + name)
        if len(data) != s["size"]:
            die("%s.bin is 0x%x bytes, must stay 0x%x" % (name, len(data), s["size"]))
        if name == "res":
            changed = 0
            for e in man["images"]:
                p = os.path.join(src, "images", e["file"])
                if not os.path.exists(p):
                    continue
                raw = bmp_to_rgb565(open(p, "rb").read(), e["w"], e["h"], p)
                if data[e["offset"]:e["offset"] + len(raw)] != raw:
                    data[e["offset"]:e["offset"] + len(raw)] = raw
                    changed += 1
            print("images changed: %d" % changed)
        img[s["offset"]:s["offset"] + s["size"]] = data
    img[man["fw_size"]:man["fw_size"] + HDR_SIZE] = header
    struct.pack_into("<I", img, len(img) - 4, rkcrc(bytes(img[:-4])))
    with open(out_path, "wb") as f:
        f.write(img)
    print("wrote %s (0x%x bytes, crc %08x)" % (out_path, len(img), u32(img, len(img) - 4)))


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "info":
        cmd_info(a[1])
    elif len(a) == 3 and a[0] == "unpack":
        cmd_unpack(a[1], a[2])
    elif len(a) == 3 and a[0] == "pack":
        cmd_pack(a[1], a[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
