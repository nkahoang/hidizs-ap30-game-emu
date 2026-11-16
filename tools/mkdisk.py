#!/usr/bin/env python3
"""Make a FAT32 disk image for the PC harness. Pure Python, runs anywhere.

  mkdisk.py OUT.img FILE[=NAME] ...

Each FILE goes into the root directory under an 8.3 NAME (default: its own
name, upper-cased). The image is 64 MB with a partition table, like the
player's internal storage: MBR, one FAT32 partition, 512-byte clusters.
"""
import os, struct, sys

SEC = 512
TOTAL = 131072            # 64 MB
PART = 1                  # partition starts at sector 1, like the macOS-made images
RSVD, NFATS, ROOT = 32, 2, 2


def name83(name):
    stem, _, ext = name.upper().partition(".")
    if not stem or len(stem) > 8 or len(ext) > 3:
        sys.exit("%r is not an 8.3 name" % name)
    return stem.ljust(8).encode() + ext.ljust(3).encode()


def build(files):
    psecs = TOTAL - PART
    fatsz = (psecs - RSVD) // (SEC // 4 + NFATS) + 2          # sectors per FAT, with room to spare
    data0 = RSVD + NFATS * fatsz                              # first data sector, partition-relative
    nclus = psecs - data0
    assert nclus >= 65525, "too small for FAT32"

    img = bytearray(TOTAL * SEC)
    # MBR: one FAT32 (0x0b) partition
    struct.pack_into("<B3sB3sII", img, 0x1be, 0, b"\xfe\xff\xff", 0x0b, b"\xfe\xff\xff", PART, psecs)
    img[510:512] = b"\x55\xaa"

    p = PART * SEC
    bpb = bytearray(SEC)
    bpb[0:3] = b"\xeb\x58\x90"
    bpb[3:11] = b"MSDOS5.0"
    struct.pack_into("<HBHBHHBHHHII", bpb, 11, SEC, 1, RSVD, NFATS, 0, 0, 0xf8, 0, 32, 64, PART, psecs)
    struct.pack_into("<IHHIHH", bpb, 36, fatsz, 0, 0, ROOT, 1, 6)
    bpb[64:67] = bytes([0x80, 0, 0x29])
    bpb[67:71] = b"\x30\x41\x50\x12"
    bpb[71:82] = b"AP30TEST   "
    bpb[82:90] = b"FAT32   "
    bpb[510:512] = b"\x55\xaa"
    img[p:p + SEC] = bpb
    img[p + 6 * SEC:p + 7 * SEC] = bpb                        # backup boot sector

    fat = [0x0ffffff8, 0x0fffffff]
    clus_data = {}

    def alloc(data):
        n = max(1, -(-len(data) // SEC))
        first = len(fat)
        for i in range(n):
            fat.append(first + i + 1 if i + 1 < n else 0x0fffffff)
        clus_data[first] = data
        return first

    entries = bytearray(b"AP30TEST   " + bytes([0x08]) + bytes(20))
    root_first = alloc(b"")                                   # cluster 2, filled in below
    assert root_first == ROOT
    for src, name in files:
        data = open(src, "rb").read()
        first = alloc(data) if data else 0
        e = bytearray(32)
        e[0:11] = name83(name)
        e[11] = 0x20
        struct.pack_into("<H", e, 20, first >> 16)
        struct.pack_into("<HHHI", e, 22, 0, 0x5b6f, first & 0xffff, len(data))   # date 2025-11-15
        entries += e
    assert len(entries) <= SEC, "too many files for a one-cluster root directory"
    clus_data[ROOT] = bytes(entries)

    fsinfo = bytearray(SEC)
    struct.pack_into("<I", fsinfo, 0, 0x41615252)
    struct.pack_into("<III", fsinfo, 484, 0x61417272, 0xffffffff, 0xffffffff)   # free count: not recorded
    fsinfo[510:512] = b"\x55\xaa"
    img[p + SEC:p + 2 * SEC] = fsinfo
    img[p + 7 * SEC:p + 8 * SEC] = fsinfo

    raw = struct.pack("<%dI" % len(fat), *fat)
    for k in range(NFATS):
        o = p + (RSVD + k * fatsz) * SEC
        img[o:o + len(raw)] = raw
    for first, data in clus_data.items():
        o = p + (data0 + first - 2) * SEC
        img[o:o + len(data)] = data
    return bytes(img)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    files = []
    for spec in sys.argv[2:]:
        src, _, name = spec.partition("=")
        files.append((src, name or os.path.basename(src)))
    open(sys.argv[1], "wb").write(build(files))
    print("wrote", sys.argv[1])


if __name__ == "__main__":
    main()
