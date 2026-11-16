#!/usr/bin/env python3
"""Write a small original SM510 test ROM (no Nintendo code).

What it does, forever:
  - sets S1 high, so keys on input line S1 are readable
  - fills LCD row "a" (16 segments x 4 commons) with the pattern 0101
  - copies the K inputs into every nibble of LCD row "b"
  - shows a 4-bit seconds counter on the bs segments (register L)
  - sleeps with CEND until the 1 Hz divider signal or a key wakes it

It exercises the LFSR program counter, two-byte opcodes, skips, the halt and
wake-up path, the divider and all three LCD outputs.
"""
import sys


def pl_sequence():
    """Order in which the low 6 PC bits step through a page."""
    seq, pl = [], 0
    for _ in range(63):
        seq.append(pl)
        pl = (0 if ((pl >> 1 ^ pl) & 1) else 0x20) | pl >> 1
    return seq


SEQ = pl_sequence()


def assemble(rom, pu, pm, prog):
    """prog: list of ('label', name) | ('op', byte) | ('t', label) | ('tl', (pu, pm, label_or_pl))."""
    labels, pos = {}, 0
    for kind, v in prog:
        if kind == "label":
            labels[v] = SEQ[pos]
        else:
            pos += 2 if kind in ("tl", "op2") else 1
    pos = 0

    def put(b):
        nonlocal pos
        rom[pu << 10 | pm << 6 | SEQ[pos]] = b
        pos += 1

    for kind, v in prog:
        if kind == "op":
            put(v)
        elif kind == "op2":
            put(v[0]); put(v[1])
        elif kind == "t":
            put(0x80 | labels[v])
        elif kind == "tl":
            tpu, tpm, tgt = v
            put(0x70 | tpm); put(tpu << 6 | (labels[tgt] if isinstance(tgt, str) else tgt))
    return labels


def build():
    rom = bytearray(0x1000)
    main = [
        ("op", 0x63),                 # WS      S1 = 1
        ("label", "main"),
        ("op2", (0x5f, 0x60)),        # LBL 60
        ("label", "fa"),
        ("op", 0x25),                 # LAX 5
        ("op", 0x14),                 # EXCI    store, BL++, skip on wrap
        ("t", "fa"),
        ("op2", (0x5f, 0x70)),        # LBL 70
        ("label", "fb"),
        ("op", 0x6a),                 # KTA
        ("op", 0x14),                 # EXCI
        ("t", "fb"),
        ("op", 0x58),                 # TIS     skip unless a second has passed
        ("t", "sec"),
        ("op", 0x5d),                 # CEND    sleep; wake-up enters at 1.0.0
        ("label", "sec"),
        ("op2", (0x5f, 0x00)),        # LBL 00
        ("op", 0x18),                 # LDA
        ("op", 0x31),                 # ADX 1   skips on carry
        ("op", 0x00),                 # SKIP
        ("op", 0x10),                 # EXC     store new count
        ("op", 0x18),                 # LDA
        ("op", 0x59),                 # ATL     show it on bs
        ("t", "main"),
    ]
    labels = assemble(rom, 3, 7, main)          # reset vector 3.7.0
    assemble(rom, 1, 0, [("tl", (3, 7, labels["main"]))])  # wake-up vector 1.0.0
    return bytes(rom)


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build())
