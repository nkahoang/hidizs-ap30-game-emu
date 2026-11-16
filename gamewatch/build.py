#!/usr/bin/env python3
"""Build the Game & Watch module and put it into a firmware image.

  build.py --rom ROM [--svg ART.svg] [--keys games/x.json] [--scale N]
           [--slot 86] [--date 2026-10-22] [--no-image]

Output (all under build/gw/):
  gw.elf, gw_code.bin, gw_data.bin   the module
  work/                              unpacked firmware with the module patched in
  HIFIYF18.IMG                       image to flash (unless --no-image)

The module replaces one stock game (default: module 86, the largest slot) and
never uses more code, data or bss than that game did, so it runs in memory the
firmware already gives to games.
"""
import argparse, os, shutil, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build", "gw")
sys.path.insert(0, os.path.join(ROOT, "tools"))
from toolchain import tool
BASE = 0x03050000
GAME_CODE_RUN, GAME_DATA_RUN = 0x030815c4, 0x03023b48
STOCK_SHA256 = "c7601873cb3be8d1320225c69669e504576f7bcb1126595a9040492338e79840"


def run(*cmd):
    subprocess.run(cmd, check=True)


def sym(elf, name):
    out = subprocess.run([tool("llvm-nm"), elf], check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if p[-1] == name:
            return int(p[0], 16)
    sys.exit("symbol %s not found" % name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--svg")
    ap.add_argument("--keys")
    ap.add_argument("--scale", default="1")
    ap.add_argument("--bg"), ap.add_argument("--fg")
    ap.add_argument("--slot", type=int, default=86, help="game module to replace (81-111)")
    ap.add_argument("--date", default="2026-10-22", help="header date; must be newer than what is installed")
    ap.add_argument("--stock", default=os.path.join(ROOT, "firmware", "HIFIYF18.IMG"))
    ap.add_argument("--no-image", action="store_true")
    ap.add_argument("--keytest", action="store_true", help="show raw key values instead of the game")
    a = ap.parse_args()
    os.makedirs(BUILD, exist_ok=True)

    # 1. game data
    cmd = [sys.executable, os.path.join(HERE, "tools/mkgame.py"), "--rom", a.rom, "--scale", a.scale,
           "-o", os.path.join(BUILD, "game_data.c"), "--preview", os.path.join(BUILD, "preview.png")]
    for k in ("svg", "keys", "bg", "fg"):
        if getattr(a, k):
            cmd += ["--" + k, getattr(a, k)]
    run(*cmd)

    # 2. compile and link
    cflags = ["--target=thumbv7m-none-eabi", "-mcpu=cortex-m3", "-mthumb", "-Oz", "-ffreestanding", "-fno-builtin",
              "-nostdlib", "-ffunction-sections", "-fdata-sections", "-fno-unwind-tables",
              "-fno-asynchronous-unwind-tables", "-Wall", "-Wextra", "-I" + os.path.join(HERE, "src")]
    if a.keytest:
        cflags.append("-DGW_KEYTEST")
    objs = []
    for src in (os.path.join(HERE, "src/ap30.c"), os.path.join(HERE, "src/sm510.c"), os.path.join(BUILD, "game_data.c")):
        o = os.path.join(BUILD, os.path.basename(src)[:-2] + ".o")
        run(tool("clang"), *cflags, "-c", src, "-o", o)
        objs.append(o)
    elf = os.path.join(BUILD, "gw.elf")
    run(tool("ld.lld"), "-T", os.path.join(ROOT, "common", "ap30.ld"), "--gc-sections",
        "--defsym=GAME_CODE_RUN=0x%08x" % GAME_CODE_RUN, "--defsym=GAME_DATA_RUN=0x%08x" % GAME_DATA_RUN, "-o", elf, *objs,
        "-Map=" + os.path.join(BUILD, "gw.map"))
    code_bin, data_bin = os.path.join(BUILD, "gw_code.bin"), os.path.join(BUILD, "gw_data.bin")
    run(tool("llvm-objcopy"), "-O", "binary", "-j", ".text", elf, code_bin)
    run(tool("llvm-objcopy"), "-O", "binary", "-j", ".data", elf, data_bin)
    code, data = open(code_bin, "rb").read(), open(data_bin, "rb").read()
    bss = sym(elf, "__bss_end") - sym(elf, "__data_end")
    assert sym(elf, "__code_end") - GAME_CODE_RUN == len(code)
    assert sym(elf, "__data_end") - GAME_DATA_RUN == len(data)
    und = subprocess.run([tool("llvm-nm"), "-u", elf], capture_output=True, text=True).stdout.strip()
    if und:
        sys.exit("undefined symbols:\n" + und)

    # 3. check against the slot in the stock firmware
    import hashlib
    stock = open(a.stock, "rb").read()
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA256:
        sys.exit("%s is not stock HIFIYF18 v1.7.8; the firmware addresses in ap30.c would be wrong" % a.stock)
    work = os.path.join(BUILD, "work")
    shutil.rmtree(work, ignore_errors=True)   # always start from stock
    run(sys.executable, os.path.join(ROOT, "tools", "rknanofw.py"), "unpack", a.stock, work)
    cb = bytearray(open(os.path.join(work, "code.bin"), "rb").read())
    if not 81 <= a.slot <= 111:
        sys.exit("--slot must be a game module (81-111)")
    ent = 8 + 32 * a.slot
    cl, cr, cn, dl, dr, dn, ba, bn = struct.unpack_from("<8I", cb, ent)
    assert cr == GAME_CODE_RUN and dr == GAME_DATA_RUN and dl == cl + cn and ba == dr + dn, "unexpected slot layout"
    print("module %d: code %d/%d  data %d/%d  bss %d/%d bytes" % (a.slot, len(code), cn, len(data), dn, bss, bn))
    over = [n for n, used, room in (("code", len(code), cn), ("data", len(data), dn), ("bss", bss, bn)) if used > room]
    if over:
        sys.exit("does not fit in module %d: %s too large. Try --scale 2, or a larger slot." % (a.slot, ", ".join(over)))

    # 4. patch: code and data keep their stock file positions; only the
    #    lengths and the bss start in the table entry change
    off = cl - BASE
    cb[off:off + cn + dn] = bytes(cn + dn)
    cb[off:off + len(code)] = code
    cb[off + cn:off + cn + len(data)] = data
    struct.pack_into("<8I", cb, ent, cl, cr, len(code), dl, dr, len(data), dr + len(data), bss)
    open(os.path.join(work, "code.bin"), "wb").write(cb)
    if a.no_image:
        return

    # 5. header date and pack
    y, m, d = a.date.split("-")
    hdr = bytearray(open(os.path.join(work, "header.bin"), "rb").read())
    hdr[0:4] = bytes([int(y[2:], 16), int(y[:2], 16), int(d, 16), int(m, 16)])
    open(os.path.join(work, "header.bin"), "wb").write(hdr)
    img = os.path.join(BUILD, "HIFIYF18.IMG")
    run(sys.executable, os.path.join(ROOT, "tools", "rknanofw.py"), "pack", work, img)
    run(sys.executable, os.path.join(ROOT, "tools", "rknanofw.py"), "info", img)
    new = open(img, "rb").read()
    diff = [i for i in range(len(stock)) if stock[i] != new[i]]
    print("differs from stock in %d bytes, file offsets 0x%x-0x%x" % (len(diff), diff[0], diff[-1]))


if __name__ == "__main__":
    main()
