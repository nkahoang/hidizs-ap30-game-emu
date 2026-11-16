#!/usr/bin/env python3
"""One entry point for everything, on macOS, Linux and Windows.

  python ap30.py check                      is the toolchain and the firmware in place?
  python ap30.py info                       show the stock firmware's layout and checksum
  python ap30.py unpack                     unpack the stock firmware into build/stock
  python ap30.py gb [--date YYYY-MM-DD]     Game Boy image  -> build/gb/HIFIYF18.IMG
  python ap30.py gw --rom FILE [--svg FILE] [--keys FILE]     Game & Watch image -> build/gw/HIFIYF18.IMG
  python ap30.py gw-demo                    Game & Watch image with the built-in test ROM
  python ap30.py rollback [--date YYYY-MM-DD]                 stock firmware, newer date -> build/rollback/HIFIYF18.IMG
  python ap30.py flash VOLUME [--image FILE] [--roms DIR] [--no-image]
  python ap30.py findaddrs IMAGE [-o fw/NAME.json]            draft address table for another firmware version
  python ap30.py test                       PC tests that need no ROMs      (pip install unicorn pillow)
  python ap30.py test-gb ROM.gb             run one of your ROMs in the harness
"""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import toolchain

PY = sys.executable
STOCK = os.path.join(ROOT, "firmware", "HIFIYF18.IMG")
B = lambda *p: os.path.join(ROOT, "build", *p)
T = lambda *p: os.path.join(ROOT, *p)


def run(*cmd, **kw):
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def need_stock():
    if not os.path.isfile(STOCK):
        sys.exit("put your stock firmware at firmware/HIFIYF18.IMG (see firmware/README.md)")


def check():
    for name, path in toolchain.check():
        print("%-13s %s" % (name, path))
    need_stock()
    print("firmware      %s" % os.path.relpath(STOCK, ROOT))
    print("ok")


def unpack(force=False):
    need_stock()
    if force or not os.path.isfile(B("stock", "code.bin")):
        run(PY, T("tools", "rknanofw.py"), "unpack", STOCK, B("stock"))


def opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


def rollback(date):
    need_stock()
    work = B("rollback", "work")
    shutil.rmtree(work, ignore_errors=True)
    run(PY, T("tools", "rknanofw.py"), "unpack", STOCK, work, stdout=subprocess.DEVNULL)
    y, m, d = date.split("-")
    with open(os.path.join(work, "header.bin"), "r+b") as f:
        f.write(bytes([int(y[2:], 16), int(y[:2], 16), int(d, 16), int(m, 16)]))
    out = B("rollback", "HIFIYF18.IMG")
    run(PY, T("tools", "rknanofw.py"), "pack", work, out)
    run(PY, T("tools", "rknanofw.py"), "info", out)
    shutil.rmtree(work, ignore_errors=True)


def native_cc():
    for c in ("cc", "gcc", "clang"):
        if shutil.which(c):
            return c
    sys.exit("the tests need a C compiler for this computer (cc, gcc or clang)")


def stubs():
    os.makedirs(B("common"), exist_ok=True)
    cflags = ["--target=thumbv7m-none-eabi", "-mcpu=cortex-m3", "-mthumb", "-Os", "-ffreestanding", "-fno-builtin"]
    for name, addr in (("mdread", "0x0306853e"), ("mdwrite", "0x03068586")):
        o, elf = B("common", name + "_stub.o"), B("common", name + "_stub.elf")
        run(toolchain.tool("clang"), *cflags, "-c", T("common", name + "_stub.c"), "-o", o)
        run(toolchain.tool("ld.lld"), "-Ttext=" + addr, "-e", name, "-o", elf, o)
        run(toolchain.tool("llvm-objcopy"), "-O", "binary", "-j", ".text", elf, B("common", name + "_stub.bin"))


def gw_demo():
    os.makedirs(B("gw"), exist_ok=True)
    run(PY, T("gamewatch", "tools", "demo_rom.py"), B("gw", "demo.rom"))
    run(PY, T("gamewatch", "build.py"), "--rom", B("gw", "demo.rom"), "--keys", T("gamewatch", "games", "demo.json"))


def main():
    args = sys.argv[1:]
    cmd = args.pop(0) if args else "help"
    exe = ".exe" if os.name == "nt" else ""
    if cmd == "check":
        check()
    elif cmd == "info":
        need_stock(); run(PY, T("tools", "rknanofw.py"), "info", STOCK)
    elif cmd == "unpack":
        unpack(force=True)
    elif cmd == "gb":
        need_stock(); run(PY, T("gameboy", "build.py"), *args)
    elif cmd == "gw":
        need_stock(); run(PY, T("gamewatch", "build.py"), *args)
    elif cmd == "gw-demo":
        need_stock(); gw_demo()
    elif cmd == "rollback":
        rollback(opt(args, "--date", "2026-10-31"))
    elif cmd == "findaddrs":
        run(PY, T("tools", "findaddrs.py"), *args)
    elif cmd == "flash":
        run(PY, T("tools", "flash.py"), *args)
    elif cmd == "test":
        unpack(); gw_demo()
        host = B("gw", "host_test" + exe)
        run(native_cc(), "-w", "-I" + T("gamewatch", "src"), "-o", host, T("gamewatch", "test", "host_test.c"), T("gamewatch", "src", "sm510.c"))
        run(host, B("gw", "demo.rom"))
        run(PY, T("common", "harness.py"), "snake")
        run(PY, T("common", "harness.py"), "gw")
    elif cmd == "test-gb":
        if not args:
            sys.exit("usage: ap30.py test-gb ROM.gb")
        rom = os.path.abspath(args[0])
        unpack(); stubs()
        os.makedirs(B("gb"), exist_ok=True)
        run(native_cc(), "-O2", "-w", "-o", B("gb", "gb_host" + exe), T("gameboy", "gb_host.c"))
        run(PY, T("gameboy", "build.py"))
        with open(B("gb", "test.sav"), "wb") as f:
            f.write(b"\xff" * 32768)
        run(PY, T("tools", "mkdisk.py"), B("gb", "test.img"), rom + "=TEST.GB", B("gb", "test.sav") + "=TEST.SAV")
        run(PY, T("gameboy", "test", "harness_gb.py"), rom, B("gb", "test.img"), "0", "300")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
