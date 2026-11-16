#!/usr/bin/env python3
"""Copy a firmware image, and optionally Game Boy ROMs, to the player.

  flash.py VOLUME                                      image only (build/gb/HIFIYF18.IMG)

VOLUME is where the player's storage is mounted: "/Volumes/NO NAME" on macOS,
/media/you/XXXX on Linux, a drive letter such as E:\\ on Windows.

  flash.py "/Volumes/NO NAME"
  flash.py "/Volumes/NO NAME" --roms roms/gameboy      image and ROMs
  flash.py "/Volumes/NO NAME" --roms roms/gameboy --no-image     ROMs only
  flash.py "/Volumes/NO NAME" --image build/rollback/HIFIYF18.IMG

Before running it: format the player's internal storage from the player's own
menu, take the microSD card out, then connect USB. The player has only ever
accepted an update right after a fresh format.

What it does:
  - refuses an image whose checksum is wrong
  - copies without macOS metadata files and compares every copy byte for byte
  - gives ROMs 8.3 names (the module shows and opens short names only)
  - for a cartridge with battery-backed memory, creates NAME.SAV at the right
    size if it is not there yet. An existing save is never touched.

It does not eject the volume. Do that yourself, then restart the player.
"""
import argparse, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rknanofw

RAM_KB = {0: 0, 1: 2, 2: 8, 3: 32, 4: 128, 5: 64}
BATTERY = {0x03, 0x06, 0x09, 0x0f, 0x10, 0x13, 0x1b, 0x1e}
DEVICE_NAME = "HIFIYF18.IMG"   # the updater opens exactly this name


def copy(src, dst):
    shutil.copyfile(src, dst)          # data only: no extended attributes, so no ._ file
    side = os.path.join(os.path.dirname(dst), "._" + os.path.basename(dst))
    if os.path.exists(side):
        os.remove(side)
    with open(src, "rb") as a, open(dst, "rb") as b:
        if a.read() != b.read():
            sys.exit("copy of %s does not match the original" % os.path.basename(dst))


def short_name(path, used):
    stem = re.sub(r"[^A-Z0-9]", "", os.path.splitext(os.path.basename(path))[0].upper())[:8] or "ROM"
    name, n = stem, 1
    while name in used:
        n += 1
        name = stem[:8 - len(str(n))] + str(n)
    used.add(name)
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("volume", help='where the player is mounted: "/Volumes/NO NAME", /media/you/XXXX or E:\\')
    ap.add_argument("--image", default=os.path.join(ROOT, "build", "gb", "HIFIYF18.IMG"))
    ap.add_argument("--no-image", action="store_true", help="copy ROMs only")
    ap.add_argument("--roms", help="folder with .gb files to copy")
    a = ap.parse_args()
    if not os.path.isdir(a.volume):
        sys.exit("%s is not mounted" % a.volume)

    if not a.no_image:
        img = open(a.image, "rb").read()
        stored = int.from_bytes(img[-4:], "little")
        if rknanofw.rkcrc(img[:-4]) != stored:
            sys.exit("%s: checksum is wrong, not copying" % a.image)
        copy(a.image, os.path.join(a.volume, DEVICE_NAME))
        print("image  %s -> %s (checksum ok, copy verified)" % (os.path.relpath(a.image), DEVICE_NAME))

    if a.roms:
        used = set()
        for f in sorted(os.listdir(a.roms)):
            if f.startswith(".") or not f.lower().endswith((".gb", ".gbc")):
                continue
            src = os.path.join(a.roms, f)
            hdr = open(src, "rb").read(0x150)
            name = short_name(src, used)
            ext = "GBC" if f.lower().endswith(".gbc") else "GB"
            copy(src, os.path.join(a.volume, "%s.%s" % (name, ext)))
            note = ""
            ram = RAM_KB.get(hdr[0x149], 0) * 1024
            if hdr[0x143] == 0xc0:
                note = "  (Game Boy Color only: will not run)"
            if ram and hdr[0x147] in BATTERY:
                sav = os.path.join(a.volume, name + ".SAV")
                if ram > 32768:
                    note += "  (needs %d KB of save memory: not supported)" % (ram // 1024)
                elif os.path.exists(sav):
                    note += "  (kept existing %s.SAV)" % name
                else:
                    with open(sav, "wb") as o:
                        o.write(b"\xff" * ram)
                    note += "  (+ new %s.SAV, %d KB)" % (name, ram // 1024)
            print("rom    %-40s -> %s.%s%s" % (f, name, ext, note))
    for f in os.listdir(a.volume):
        if f.startswith("._"):
            os.remove(os.path.join(a.volume, f))
    if hasattr(os, "sync"):
        os.sync()
    print("done. Eject the volume safely, then restart the player.")


if __name__ == "__main__":
    main()
