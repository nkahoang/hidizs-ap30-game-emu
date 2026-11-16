#!/usr/bin/env python3
"""Run the Game Boy module (build/gb/work/code.bin) in the PC harness and
compare its picture with the native build of the same core.

  harness_gb.py ROM.gb DISK.img INDEX [frames]

DISK.img is a raw FAT32 disk image (with partition table) that has the same
ROM in its root; INDEX is its position in the picker's list. The firmware's own filesystem code reads it; only
the lowest level (MDRead) is replaced, by test/mdread_stub.c.
"""
import os, struct, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "common"))
import harness as h

BUILD = os.path.join(ROOT, "build")
sys.path.insert(0, os.path.join(ROOT, "tools"))
from toolchain import tool
ADC = 0x03005a8e
PAL = [0xe7da, 0x9d6f, 0x4b08, 0x1102]
SHADE = {0xe0: 0, 0xa0: 1, 0x58: 2, 0x10: 3}
XOFF, YOFF = 28, 12


def native(rom, frames):
    ppm = os.path.join(BUILD, "gb/ref.ppm")
    subprocess.run([os.path.join(BUILD, "gb", "gb_host" + (".exe" if os.name == "nt" else "")), rom, "ppm", ppm, str(frames)], check=True, stderr=subprocess.DEVNULL)
    d = open(ppm, "rb").read()
    px = d[-160 * 144 * 3:]
    return [[SHADE[px[(y * 160 + x) * 3]] for x in range(160)] for y in range(144)]


def scaled(fb):
    """The front-end's 1.5x scaling, written out independently."""
    out = {}
    for line in range(144):
        row = []
        for i in range(80):
            a, b = fb[line][2 * i], fb[line][2 * i + 1]
            row += [a, b if i & 1 else a, b]
        y = YOFF + line * 3 // 2
        for yy in ([y, y + 1] if line & 1 else [y]):
            out[yy] = [PAL[v] for v in row]
    return out


R = lambda off: off - 0x2988c + 0x03050000   # resident code offset -> run address
DISK = 0x10000000


def symbols():
    out = subprocess.run([tool("llvm-nm"), os.path.join(BUILD, "gb/gb.elf")], capture_output=True, text=True).stdout
    return {l.split()[2]: int(l.split()[0], 16) for l in out.splitlines() if len(l.split()) == 3}


def machine(disk, fill=0):
    m = h.Machine(os.path.join(BUILD, "gb/work/code.bin"), 86, bss_fill=fill)
    m.disk_len = len(disk)
    m.uc.mem_map(DISK, (len(disk) + 0xfff) & ~0xfff)
    m.uc.mem_write(DISK, disk)
    m.uc.mem_write(R(0x41dca), open(os.path.join(BUILD, "common/mdread_stub.bin"), "rb").read())
    m.uc.mem_write(R(0x41e12), open(os.path.join(BUILD, "common/mdwrite_stub.bin"), "rb").read())
    m.uc.mem_write(R(0x2cf26), b"\x70\x47")            # debug printf (UART): return
    m.uc.mem_write(R(0x3d6c4), b"\x70\x47")            # draw_string (font comes from storage): return
    assert m.call(R(0x31db2), 2) == 0, "mount failed"   # what the firmware does at boot
    m.uc.mem_write(ADC, struct.pack("<H", 1023))        # no button held
    m.snap = bytes(m.uc.mem_read(h.RAM0, h.RAM1 - h.RAM0))
    m.t = 1000
    m.set_ticks(m.t)
    return m


def run(m, n, adc=1023, step=2):
    m.uc.mem_write(ADC, struct.pack("<H", adc))
    for _ in range(n):
        m.t += step
        m.set_ticks(m.t); m.service(); m.key(); m.paint()


def create_save_test(rom, S):
    """A cartridge with battery memory and no .SAV on the disk: the module must
    create the file at full size, then save into it like any other."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import mkdisk
    m = machine(mkdisk.build([(rom, "TEST.GB")]))
    assert b"TEST    SAV" not in bytes(m.uc.mem_read(DISK, m.disk_len))
    pick(m, S, 0)
    size = m.u32(S["cart_ram_size"])
    if not size:
        return
    assert m.uc.mem_read(S["gb_save_ok"], 1)[0] == 1, "save file was not created"
    img = bytes(m.uc.mem_read(DISK, m.disk_len))
    e = img.find(b"TEST    SAV")
    assert e > 0 and struct.unpack_from("<I", img, e + 28)[0] == size, "new save has the wrong size"
    run(m, 200)           # let the game finish its own start-up writes to cartridge RAM first
    pattern = bytes((i * 5 + 9) & 0xff for i in range(size))
    m.uc.mem_write(S["pool_a"], pattern)
    m.uc.mem_write(S["gb_sram_dirty"], b"\x01")
    m.uc.mem_write(S["sram_tick"], struct.pack("<I", m.t))
    run(m, 130)
    assert bytes(m.uc.mem_read(DISK, m.disk_len)).count(pattern) == 1, "save not written into the new file"
    assert m.key(0x20000002) == -1
    m.deinit()
    assert not stray(m)
    # a second run finds the file and loads what was saved
    m2 = machine(bytes(m.uc.mem_read(DISK, m.disk_len)))
    pick(m2, S, 0)
    assert bytes(m2.uc.mem_read(S["pool_a"], size)) == pattern, "saved data did not come back"
    print("no save file on the disk: created at %d bytes, saved into, and loaded again on the next start" % size)


SD = 0x14000000
CUR_DISK = 0x0307e711


def sd_card_test(disk, S):
    """With a microSD card in, the firmware is looking at the card. The module
    must find its ROMs on internal storage anyway and give the card back."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import mkdisk
    note = os.path.join(BUILD, "gb", "card.txt")
    open(note, "w").write("this is the card")
    card = mkdisk.build([(note, "CARD.TXT")])
    m = machine(disk)
    m.uc.mem_map(SD, len(card))
    m.uc.mem_write(SD, card)
    # card presence and probe go to the SD controller, which is not emulated
    for off in (0x41ea8, 0x41eca, 0x41eec, 0x30512):          # 0x30512: GPIO read (card detect)
        m.uc.mem_write(R(off), b"\x00\x20\x70\x47")    # movs r0,#0 ; bx lr
    # the card driver's capacity, status and probe entries would touch the controller too
    RET0 = 0x0309ff40
    m.uc.mem_write(RET0, b"\x00\x20\x70\x47")
    table = 0x0306f480
    for e in range(2):
        if struct.unpack("<H", m.uc.mem_read(table + e * 0x28 + 0x24, 2))[0] == 4:
            for field in (0x0c, 0x10, 0x14):
                m.uc.mem_write(table + e * 0x28 + field, struct.pack("<I", RET0 | 1))
    assert m.call(R(0x31db2), 4) == 0, "could not mount the card image"
    assert m.uc.mem_read(CUR_DISK, 1)[0] == 4

    def root_names():
        root = m.u32(0x0307e729)
        out = []
        for i in range(16):
            m.call(R(0x3256c), 0x0309e200, root, i)
            e = bytes(m.uc.mem_read(0x0309e200, 32))
            if e[0] == 0:
                break
            if e[11] not in (0x0f, 0x08) and e[0] != 0xe5:
                out.append(e[:11].decode("latin1"))
        return out

    assert root_names() == ["CARD    TXT"], root_names()
    m.snap = bytes(m.uc.mem_read(h.RAM0, h.RAM1 - h.RAM0))
    pick(m, S, 0)
    assert m.uc.mem_read(S["gb_n_roms"], 1)[0] >= 1, "no ROMs found with a card inserted"
    assert m.uc.mem_read(CUR_DISK, 1)[0] == 2, "module did not switch to internal storage"
    run(m, 60)
    assert m.u32(S["gb_frames"]) > 20, "game did not run"
    assert m.key(0x20000002) == -1
    m.deinit()
    assert m.uc.mem_read(CUR_DISK, 1)[0] == 4, "card was not given back to the firmware"
    assert root_names() == ["CARD    TXT"], "firmware does not see the card's files after exit"
    assert not stray(m)
    print("microSD inserted: ROMs still found on internal storage, game runs, card restored on exit")


def stray(m):
    """Like Machine.stray_writes, but the module may also use the RAM above
    its code (cache pool B) and the firmware's filesystem state changes."""
    now = bytes(m.uc.mem_read(h.RAM0, h.RAM1 - h.RAM0))
    ok = [(h.RAM0, m.mod["data"][1]), (h.FB_B, h.FB_B + 50 * 296 * 2), (h.KEYVAR, h.KEYVAR + 0x20),
          (0x0307e300, 0x030815c4),            # firmware data after the resident code (filesystem state)
          (0x03085800, 0x0308b800)]            # cache pool B (its start depends on the build; this is the lowest)
    return [h.RAM0 + i for i in range(0, len(now), 4)
            if now[i:i + 4] != m.snap[i:i + 4] and not any(a <= h.RAM0 + i < b for a, b in ok)]


UP, DOWN, START, A_BTN = 121, 365, 610, 855


def pick(m, S, index, sticky=False):
    """Drive the ROM picker with firmware key events: Down `index` times,
    then a short press of A (or B for sticky left/right)."""
    m.init()
    run(m, 3)
    assert m.uc.mem_read(S["gb_running"], 1)[0] == 0, "picker not shown"
    # the fault of the first picker build: a ladder reading in A's range must not choose anything
    run(m, 6, 920); run(m, 6, A_BTN); run(m, 3)
    assert m.uc.mem_read(S["gb_running"], 1)[0] == 0, "picker reacted to the raw ladder value"
    for _ in range(index):
        assert m.key(0x10000020) == 0       # Down pressed
        m.paint()
        assert m.key(0x40000020) == 0       # Down released
    assert m.uc.mem_read(S["gb_sel"], 1)[0] == index, "cursor did not move"
    assert m.key(0x10000040 if sticky else 0x10000080) == 0
    assert m.uc.mem_read(S["gb_running"], 1)[0] == 0, "started on press instead of release"
    assert m.key(0x40000040 if sticky else 0x40000080) == 0
    assert m.uc.mem_read(S["gb_running"], 1)[0] == 1, "A did not start the game"
    assert m.uc.mem_read(S["gb_sticky"], 1)[0] == int(sticky)
    m.uc.mem_write(ADC, struct.pack("<H", 1023))


def main():
    rom, disk_path, index = sys.argv[1], sys.argv[2], int(sys.argv[3])
    target = int(sys.argv[4]) if len(sys.argv) > 4 else 300
    disk = open(disk_path, "rb").read()
    S = symbols()
    for fill in (0x00, 0xaa):
        m = machine(disk, fill)
        m.init(); run(m, 2)
        n = m.uc.mem_read(S["gb_n_roms"], 1)[0]
        names = [bytes(m.uc.mem_read(S["rom_names"] + 11 * i, 11)).decode() for i in range(n)]
        m = machine(disk, fill)
        pick(m, S, index)
        print("bss fill 0x%02x: picker lists %s, chose %r" % (fill, names, names[index]))
        per_frame = []
        while m.u32(S["gb_frames"]) < target:
            before = m.u32(S["gb_frames"])
            m.t += 2
            m.set_ticks(m.t); m.service(); k = m.last_insns
            ran = m.u32(S["gb_frames"]) - before
            if ran:
                per_frame.append(k / ran)
            m.key(); m.paint()
        got = m.screen()
        frames = m.u32(S["gb_frames"])
        want = scaled(native(rom, frames))
        bad = sum(1 for y, row in want.items() for x in range(240) if got[y][XOFF + x] != row[x])
        h.save_png(got, os.path.join(BUILD, "gb/harness_%02x.png" % fill))
        assert bad == 0, "picture differs from the native core in %d pixels after %d frames" % (bad, frames)
        print("  %d frames, picture matches the native core pixel for pixel; %d ROM pages read" % (frames, m.u32(S["gb_misses"])))

        ram_size = m.u32(S["cart_ram_size"])
        if ram_size:
            assert m.uc.mem_read(S["gb_save_ok"], 1)[0] == 1, "save file was not accepted"
            # pretend the game just saved: change cartridge RAM, then let two quiet seconds pass
            pattern = bytes((i * 13 + 5) & 0xff for i in range(ram_size))
            m.uc.mem_write(S["pool_a"], pattern)
            m.uc.mem_write(S["gb_sram_dirty"], b"\x01")
            m.uc.mem_write(S["sram_tick"], struct.pack("<I", m.t))
            run(m, 60)
            assert bytes(m.uc.mem_read(DISK, m.disk_len)).count(pattern) == 0, "save written too early"
            run(m, 60)
            img = bytes(m.uc.mem_read(DISK, m.disk_len))
            assert img.count(pattern) == 1, "save data not found on the disk after autosave"
            assert m.uc.mem_read(S["gb_sram_dirty"], 1)[0] == 0
            misses = m.u32(S["gb_misses"])
            run(m, 120)
            print("  autosave wrote %d bytes of cartridge RAM to the disk; game kept running (%d more page reads)" % (ram_size, m.u32(S["gb_misses"]) - misses))
            # and on exit
            pattern2 = bytes((i * 7 + 1) & 0xff for i in range(ram_size))
            m.uc.mem_write(S["pool_a"], pattern2)
            m.uc.mem_write(S["gb_sram_dirty"], b"\x01")
            assert m.key(0x20000002) == -1
            m.deinit()
            img = bytes(m.uc.mem_read(DISK, m.disk_len))
            assert img.count(pattern2) == 1 and img.count(pattern) == 0, "exit did not rewrite the save in place"
            open(os.path.join(BUILD, "gb/disk_after.img"), "wb").write(img)
            open(os.path.join(BUILD, "gb/disk_after.sav"), "wb").write(pattern2)
            print("  exit rewrote the save in place")
        else:
            assert m.key(0x20000002) == -1
            m.deinit()
        bad = stray(m)
        assert not bad, "memory changed outside the module: " + ", ".join("%08x" % x for x in bad[:8])
        print("  no stray writes; about %.2f million ARM instructions per emulated frame" % (sum(per_frame) / len(per_frame) / 1e6))
    create_save_test(rom, S)
    sd_card_test(disk, S)


if __name__ == "__main__":
    main()
