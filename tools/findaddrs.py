#!/usr/bin/env python3
"""Find the firmware functions and variables the emulators need in a
firmware image, so a new firmware version does not mean starting over.

  findaddrs.py IMAGE                 print an address table for IMAGE (JSON)
  findaddrs.py IMAGE -o fw/X.json    ... and save it
  findaddrs.py --learn IMAGE TABLE   (maintainers) rebuild tools/fw_signatures.json
                                     from a known-good image and its table

How it works. For the known-good version (fw/1.7.8.json) every address was
found by hand. `--learn` records, for each function, its first bytes with the
parts that move between builds blanked out (branch targets, pc-relative
offsets), and for each variable where inside which function its address is
loaded. Finding then searches another image's resident code for those byte
patterns and reads the variable addresses out of the matched functions.

The result is a starting point, not a guarantee: it is marked
"verified": false, anything not found is listed under "missing", and a match
only says the first bytes of a function look the same. Read the output, check
it against docs/FINDINGS.md, and test in the PC harness before flashing.
"""
import hashlib, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rknanofw

SIGS = os.path.join(HERE, "fw_signatures.json")
SIG_LEN = 64
# variable -> (function whose code loads it, what is added to the loaded literal)
VARS = {
    "colour":    "fill_rect",
    "ticks":     "idle_reset",
    "adc":       "adc_ready",
    "lcd_state": "set_window",
    "fb_a":      "put_pixel",
    "fb_b":      "put_pixel",
    "fs_state":  "path_dir",
    "fs_disk":   "file_open",
    "clocks":    "clk_get",
}


class Image:
    def __init__(self, path):
        img = open(path, "rb").read()
        secs, _ = rknanofw.parse(img)
        code = next(s for s in secs if s["name"] == "code")
        self.sha = hashlib.sha256(img).hexdigest()
        self.date = "20%02x-%02x-%02x" % (img[0], img[3], img[2])
        self.code = c = img[code["offset"]:code["offset"] + code["size"]]
        self.base, n = struct.unpack_from("<II", c, 0)
        self.mods = [struct.unpack_from("<8I", c, 8 + 32 * i) for i in range(n)]
        cl, cr, cn = self.mods[0][:3]
        self.res_off, self.res_run, self.res_len = cl - self.base, cr, cn
        self.res = c[self.res_off:self.res_off + cn]

    def run(self, off):            # offset inside the resident code -> run address
        return self.res_run + off

    def off(self, run):
        return run - self.res_run

    def module_with(self, text):
        for i, m in enumerate(self.mods):
            if m[2] and text in self.code[m[0] - self.base:m[0] - self.base + m[2]]:
                return i, m
        return None, None


def insns(b):
    """Yield (offset, size, halfword1, halfword2) for Thumb-2 code."""
    i = 0
    while i + 1 < len(b):
        h = b[i] | b[i + 1] << 8
        if (h & 0xe000) == 0xe000 and (h & 0x1800):
            if i + 3 >= len(b):
                return
            yield i, 4, h, b[i + 2] | b[i + 3] << 8
            i += 4
        else:
            yield i, 2, h, 0
            i += 2


def mask_of(b):
    """1-bits are compared. Blank what changes when code moves."""
    m = bytearray(b"\xff" * len(b))
    for o, size, h, h2 in insns(b):
        if size == 4 and (h & 0xf800) == 0xf000 and (h2 & 0x8000):      # BL, B.W, Bcc.W
            m[o:o + 4] = b"\0\0\0\0"
        elif size == 4 and (h & 0xff7f) == 0xf85f:                      # LDR.W Rt,[pc,#imm12]
            m[o + 2] = 0; m[o + 3] &= 0xf0
        elif size == 4 and (h & 0xfbff) in (0xf20f, 0xf2af):            # ADR.W
            m[o:o + 4] = b"\0\0\0\0"
        elif size == 2 and (h & 0xf800) == 0x4800:                      # LDR Rt,[pc,#imm8]
            m[o] = 0
        elif size == 2 and (h & 0xf800) == 0xa000:                      # ADR
            m[o] = 0
        elif size == 2 and ((h & 0xf000) == 0xd000 or (h & 0xf800) == 0xe000 or (h & 0xf500) == 0xb100):
            m[o] = 0                                                     # short branches: keep opcode, drop distance
            if (h & 0xf800) == 0xe000:
                m[o + 1] &= 0xf8
            if (h & 0xf500) == 0xb100:
                m[o] = 0x07; m[o + 1] &= 0xfd
    return bytes(m)


def literal_at(res, o):
    """Value loaded by a pc-relative LDR at offset o of the resident code, or None."""
    h = res[o] | res[o + 1] << 8
    if (h & 0xf800) == 0x4800:
        a = ((o + 4) & ~3) + (h & 0xff) * 4
    elif (h & 0xff7f) == 0xf85f:
        h2 = res[o + 2] | res[o + 3] << 8
        d = h2 & 0xfff
        a = ((o + 4) & ~3) + (d if h & 0x80 else -d)
    else:
        return None
    return struct.unpack_from("<I", res, a)[0] if 0 <= a <= len(res) - 4 else None


def learn(image_path, table_path):
    im, tab = Image(image_path), json.load(open(table_path))
    if im.sha != tab["sha256"]:
        sys.exit("that table is for a different image")
    out = {"from": tab["name"], "functions": {}, "variables": {}}
    for name, addr in tab["functions"].items():
        o = im.off(int(addr, 16))
        b = im.res[o:o + SIG_LEN]
        out["functions"][name] = {"bytes": b.hex(), "mask": mask_of(b).hex()}
    for var, func in VARS.items():
        want, fo = int(tab["variables"][var], 16), im.off(int(tab["functions"][func], 16))
        hit = next((o for o, size, h, h2 in insns(im.res[fo:fo + 0x140]) if literal_at(im.res, fo + o) == want), None)
        if hit is None:
            sys.exit("%s is not loaded near the start of %s" % (var, func))
        out["variables"][var] = {"function": func, "offset": hit}
    json.dump(out, open(SIGS, "w"), indent=1)
    print("wrote %s: %d functions, %d variables" % (os.path.relpath(SIGS), len(out["functions"]), len(out["variables"])))


def find(image_path):
    im, sigs = Image(image_path), json.load(open(SIGS))
    res, missing, notes = im.res, [], []
    funcs = {}
    for name, s in sigs["functions"].items():
        b, m = bytes.fromhex(s["bytes"]), bytes.fromhex(s["mask"])
        hits = []
        for n in (SIG_LEN, 40, 24):                 # shorter prefixes if the long one finds nothing
            want = bytes(x & y for x, y in zip(b[:n], m[:n]))
            first = next(i for i in range(n) if m[i] == 0xff)
            pos = res.find(bytes([b[first]]))
            hits = []
            while pos != -1:
                o = pos - first
                if o >= 0 and o % 2 == 0 and bytes(x & y for x, y in zip(res[o:o + n], m[:n])) == want:
                    hits.append(o)
                pos = res.find(bytes([b[first]]), pos + 1)
            if hits:
                if n != SIG_LEN:
                    notes.append("%s: matched on its first %d bytes only" % (name, n))
                break
        if len(hits) == 1:
            funcs[name] = hits[0]
        elif not hits:
            missing.append(name)
        else:
            missing.append(name)
            notes.append("%s: %d candidates: %s" % (name, len(hits), ", ".join("0x%08x" % im.run(h) for h in hits[:6])))
    variables = {}
    for var, v in sigs["variables"].items():
        if v["function"] not in funcs:
            missing.append(var)
            continue
        val = literal_at(res, funcs[v["function"]] + v["offset"])
        if val is None or not 0x03000000 <= val < 0x030a0000:
            missing.append(var)
            notes.append("%s: no usable literal at %s+0x%x" % (var, v["function"], v["offset"]))
        else:
            variables[var] = "0x%08x" % val

    game = {}
    i, m = im.module_with(b"Block_Game.c")
    if m:
        game["code_run"], game["data_run"] = "0x%08x" % m[1], "0x%08x" % m[4]
        games = [(k, e) for k, e in enumerate(im.mods) if e[2] and e[1] == m[1] and e[4] == m[4] and k >= i]
        big = max(games, key=lambda g: g[1][2])
        game["slot"] = big[0]
        notes.append("slot %d is the largest module at the games' address (%d bytes of code); check which menu entry it is" % (big[0], big[1][2]))
    else:
        missing.append("game layout (no module contains Block_Game.c)")
    i, m = im.module_with(b"AudioControl.c")
    if m:
        game["audio_code"], game["audio_data"] = "0x%08x" % m[1], "0x%08x" % m[4]
    else:
        missing.append("audio module addresses")
    game["menu_name"] = None
    return {
        "name": "unknown (header date %s)" % im.date, "file": os.path.basename(image_path), "sha256": im.sha,
        "verified": False,
        "note": "Generated by tools/findaddrs.py from signatures of %s. Not checked by a person, never run on a device." % sigs["from"],
        "functions": {k: "0x%08x" % im.run(o) for k, o in funcs.items()},
        "variables": variables, "game": game, "missing": missing, "notes": notes,
    }


def main():
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "--learn":
        return learn(a[1], a[2])
    if not a or a[0].startswith("-"):
        sys.exit(__doc__)
    out = find(a[0])
    text = json.dumps(out, indent=2)
    if len(a) == 3 and a[1] == "-o":
        open(a[2], "w").write(text + "\n")
        print("wrote %s: %d functions, %d variables found, %d missing" % (a[2], len(out["functions"]), len(out["variables"]), len(out["missing"])), file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
