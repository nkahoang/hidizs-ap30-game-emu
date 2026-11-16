#!/usr/bin/env python3
"""Run an AP30 game module on the PC, against the real resident firmware code.

Unicorn emulates the Cortex-M3. The resident module of the firmware is loaded
at its run address, so drawing, messages and the window calls execute the
vendor's own code and write the vendor's own framebuffer in RAM. Only two
things are faked: the key-read function and the 10 ms tick counter.

  harness.py snake            stock Snake from build/stock (make unpack) -> build/gw/snake.png
  harness.py gw               the Game & Watch module in build/gw/work/code.bin, with checks

This checks calling conventions, addresses, memory use and drawing. It cannot
check anything that depends on real hardware (LCD refresh, key ladder, timing
of the main loop).
"""
import os, struct, sys
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_MEM_UNMAPPED, UC_HOOK_BLOCK, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
sys.path.insert(0, os.path.join(ROOT, "gamewatch", "tools"))

BASE = 0x03050000
RAM0, RAM1 = 0x03000000, 0x030a0000
WIN = 0x03023b48
TICKS = 0x0302288c
MSG_BITS = 0x03023280
GET_KEY = 0x03062fa6
KEYVAR = 0x0309ff00          # harness-owned word, top of RAM
RET = 0x0309ff10             # return address for calls from the harness
STACK_TOP = 0x03004000
FB_A, FB_B, FB_SPLIT = 0x03006688, 0x0306fd50, 190
W, H = 296, 240


class Machine:
    def __init__(self, code_bin, module, bss_fill=0):
        self.cb = cb = open(code_bin, "rb").read()
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.ctl_set_cpu_model(17)  # UC_CPU_ARM_CORTEX_M3
        uc.mem_map(RAM0, RAM1 - RAM0)
        uc.mem_map(0xe000e000, 0x1000)   # system control space (SysTick)
        self.insns = 0
        self.fault = None

        def entry(i):
            return struct.unpack_from("<8I", cb, 8 + 32 * i)

        # resident module: code, initialised data, zero bss
        cl, cr, cn, dl, dr, dn, ba, bn = entry(0)
        uc.mem_write(cr, cb[cl - BASE:cl - BASE + cn])
        uc.mem_write(dr, cb[dl - BASE:dl - BASE + dn])
        self.resident_code = (cr, cr + cn)
        # the game module, loaded the way the table describes it
        cl, cr, cn, dl, dr, dn, ba, bn = entry(module)
        uc.mem_write(cr, cb[cl - BASE:cl - BASE + cn])
        uc.mem_write(dr, cb[dl - BASE:dl - BASE + dn])
        uc.mem_write(ba, bytes([bss_fill]) * bn)
        self.mod = dict(code=(cr, cr + cn), data=(dr, ba + bn))
        # fake key read: ldr r0,[pc,#4]; ldr r0,[r0]; bx lr; .word KEYVAR
        uc.mem_write(GET_KEY, bytes.fromhex("014800687047") + struct.pack("<I", KEYVAR))
        uc.mem_write(RET, b"\xfe\xe7")  # b .
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        uc.hook_add(UC_HOOK_BLOCK, self._count)  # per-instruction hooks break Thumb IT blocks in Unicorn
        # No per-instruction or memory hooks: Unicorn mis-executes Thumb IT
        # blocks while one is active (the firmware's put_pixel stops advancing).
        # Stray writes are found by comparing RAM snapshots instead.
        self.snap = bytes(uc.mem_read(RAM0, RAM1 - RAM0))

    def _unmapped(self, uc, access, addr, size, value, _):
        self.fault = "unmapped access at 0x%08x (pc 0x%08x)" % (addr, uc.reg_read(UC_ARM_REG_PC))
        return False

    def _count(self, uc, addr, size, _):
        self.insns += size // 2  # approximate: most Thumb instructions are 2 bytes

    def stray_writes(self):
        """Addresses changed since load that a game has no business changing:
        anything past the module's own bss, and any code."""
        now = bytes(self.uc.mem_read(RAM0, RAM1 - RAM0))
        ok = [(RAM0, self.mod["data"][1]),                     # stack, firmware globals, framebuffer, module data+bss
              (FB_B, FB_B + (H - FB_SPLIT) * W * 2),           # framebuffer tail
              (KEYVAR, KEYVAR + 0x20)]
        bad = []
        for i in range(0, len(now), 4):
            if now[i:i + 4] != self.snap[i:i + 4] and not any(a <= RAM0 + i < b for a, b in ok):
                bad.append(RAM0 + i)
        return bad

    def call(self, fn, *args, limit=20_000_000):
        uc = self.uc
        for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            uc.reg_write(reg, v)
        uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        uc.reg_write(UC_ARM_REG_LR, RET | 1)
        start = self.insns
        try:
            uc.emu_start(fn | 1, RET, count=limit)
        except UcError as e:
            raise RuntimeError(self.fault or "%s at pc 0x%08x" % (e, uc.reg_read(UC_ARM_REG_PC)))
        if uc.reg_read(UC_ARM_REG_PC) != RET:
            raise RuntimeError("call to 0x%08x did not return within %d instructions" % (fn, limit))
        self.last_insns = self.insns - start
        return uc.reg_read(UC_ARM_REG_R0)

    def u32(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def win(self, slot):
        return self.u32(WIN + slot)

    def init(self):    return self.call(self.win(0x14), 0)
    def service(self): return self.call(self.win(0x08))
    def paint(self):   return self.call(self.win(0x10))
    def deinit(self):  return self.call(self.win(0x18))

    def key(self, value=0):
        self.uc.mem_write(KEYVAR, struct.pack("<I", value))
        r = self.call(self.win(0x0c))
        self.uc.mem_write(KEYVAR, bytes(4))
        return r - (1 << 32) if r & 0x80000000 else r

    def set_ticks(self, t):
        self.uc.mem_write(TICKS, struct.pack("<I", t & 0xffffffff))

    def frame(self, ticks):
        """One pass of the main loop as the window manager does it."""
        self.set_ticks(ticks)
        self.service()
        r = self.key()
        self.paint()
        return r

    def screen(self):
        """Decode the firmware framebuffer (two RAM areas, pixel pairs swapped)."""
        a = self.uc.mem_read(FB_A, FB_SPLIT * W * 2)
        b = self.uc.mem_read(FB_B, (H - FB_SPLIT) * W * 2)
        raw = bytes(a) + bytes(b)
        px = struct.unpack("<%dH" % (W * H), raw)
        return [[px[y * W + (x ^ 1)] for x in range(W)] for y in range(H)]


def save_png(scr, path):
    img = Image.new("RGB", (W, H))
    img.putdata([((p >> 11) * 255 // 31, (p >> 5 & 63) * 255 // 63, (p & 31) * 255 // 31) for row in scr for p in row])
    img.save(path)


def snake():
    m = Machine(os.path.join(BUILD, "stock/code.bin"), 81)
    # Text drawing reads the font from storage (clock gates at 0x40180000 and
    # the eMMC controller), which is not emulated: make draw_string return.
    m.uc.mem_write(0x03063e38, b"\x70\x47")
    m.set_ticks(1000)
    m.init()
    m.paint()
    out = os.path.join(BUILD, "gw/snake.png")
    scr = m.screen()
    save_png(scr, out)
    field = scr[100][100]
    print("stock Snake: init + paint ran (%d instructions for paint), field colour 0x%04x -> %s" % (m.last_insns, field, out))
    # start the game (Play, short release) and steer right
    m.key(0x40000100)
    for t in range(1001, 1400):
        m.frame(t)
    save_png(m.screen(), os.path.join(BUILD, "gw/snake_run.png"))
    assert scr[5][5] == 0 and field == 0x0a2a, "unexpected picture"
    print("stock Snake: ok")


def expected(masks, w, h, scale, bits, bg, fg):
    xoff, yoff = (W - w * scale) // 2, (H - h * scale) // 2
    scr = [[bg] * W for _ in range(H)]
    for sid, rows in masks.items():
        if not bits[sid >> 5] >> (sid & 31) & 1:
            continue
        for y, runs in rows.items():
            for x0, x1 in runs:
                for yy in range(yoff + y * scale, yoff + (y + 1) * scale):
                    for xx in range(xoff + x0 * scale, xoff + x1 * scale):
                        scr[yy][xx] = fg
    return scr


def compare(m, want, what):
    got = m.screen()
    bad = sum(1 for y in range(H) for x in range(W) if got[y][x] != want[y][x])
    if bad:
        save_png(got, os.path.join(BUILD, "gw/fail_got.png"))
        save_png(want, os.path.join(BUILD, "gw/fail_want.png"))
        raise AssertionError("%s: %d pixels differ (see build/gw/fail_*.png)" % (what, bad))
    print("  ok: %s" % what)


def gw(scale=1):
    import mkgame
    masks, w, h = mkgame.grid_masks(scale)
    bg, fg = mkgame.rgb565("#b8c4a8"), mkgame.rgb565("#101810")
    for fill in (0x00, 0xaa):
        print("module from build/gw/work/code.bin, bss pre-filled with 0x%02x" % fill)
        m = Machine(os.path.join(BUILD, "gw/work/code.bin"), 86, bss_fill=fill)
        t = 5000
        m.set_ticks(t)
        m.init()
        worst = 0
        for _ in range(30):                       # 0.3 s
            t += 1; m.frame(t); worst = max(worst, m.last_insns)
        compare(m, expected(masks, w, h, scale, [0x55555555, 0x55555555, 0, 0, 0], bg, fg), "row a pattern after start")

        for _ in range(330):                      # to 3.6 s
            t += 1; m.frame(t)
        compare(m, expected(masks, w, h, scale, [0x55555555, 0x55555555, 0, 0, 3], bg, fg), "seconds counter = 3 on bs after 3.6 s")

        # hold Left (key bit 0x008 -> S1, K1), delivered as down then repeats
        m.set_ticks(t); m.service(); assert m.key(0x10000008) == 0; m.paint()
        for i in range(20):
            t += 1; m.set_ticks(t); m.service(); m.key(0x30000008 if i % 12 == 11 else 0); m.paint()
        compare(m, expected(masks, w, h, scale, [0x55555555, 0x55555555, 0x11111111, 0x11111111, 3], bg, fg), "Left held shows K1 on row b")
        assert m.key(0x40000008) == 0             # short release
        for _ in range(130):                      # to 5.1 s
            t += 1; m.frame(t)
        compare(m, expected(masks, w, h, scale, [0x55555555, 0x55555555, 0, 0, 5], bg, fg), "released, counter = 5")

        # a long stall must not make the game fast-forward or hang
        t += 100000; m.frame(t)
        assert m.last_insns < 2_000_000, "stall took %d instructions" % m.last_insns

        # forced full repaint (another window was on top)
        m.call(0x03067ed4, 0x18c)
        m.uc.mem_write(FB_A, bytes(FB_SPLIT * W * 2))
        t += 1; m.frame(t)
        got = m.screen()
        assert got[0][0] == bg and got[239][295] == bg, "full repaint did not clear the screen"
        print("  ok: full repaint")

        # long press on Back leaves the game the way Snake does
        r = m.key(0x20000002)
        assert r == -1, "exit key returned %d" % r
        assert m.uc.mem_read(0x030057c0, 1)[0] == 10 and m.u32(0x030057c0 + 0x184) & 0xffff == 7, "task switch not requested"
        m.deinit()
        print("  ok: exit to main menu requested")
        bad = m.stray_writes()
        assert not bad, "memory changed outside the module: " + ", ".join("%08x" % x for x in bad[:8])
        sp_low = min(i for i in range(STACK_TOP - 0x1000, STACK_TOP, 4) if m.u32(i)) if any(m.u32(i) for i in range(STACK_TOP - 0x1000, STACK_TOP, 4)) else STACK_TOP
        print("  ok: no stray writes; deepest stack use %d bytes; busiest loop pass %d instructions" % (STACK_TOP - sp_low, worst))
    save_png(m.screen(), os.path.join(BUILD, "gw/gw.png"))
    print("all harness checks passed")


if __name__ == "__main__":
    {"snake": snake, "gw": gw}[sys.argv[1] if len(sys.argv) > 1 else "gw"]()
