"""Find the LLVM tools (clang, ld.lld, llvm-objcopy, llvm-nm) on any OS.

Order: the LLVM_BIN environment variable, Homebrew's llvm and lld on macOS,
then whatever is on PATH. Apple's own clang is not enough: it ships without
ld.lld and llvm-objcopy.
"""
import os, shutil, sys

_BREW = ["/opt/homebrew/opt/llvm/bin", "/opt/homebrew/opt/lld/bin", "/usr/local/opt/llvm/bin", "/usr/local/opt/lld/bin"]
HELP = """
  macOS:    brew install llvm lld
  Linux:    sudo apt install clang lld llvm        (or your distribution's equivalent)
  Windows:  winget install LLVM.LLVM               (then open a new terminal)
Or set LLVM_BIN to the folder that contains clang, ld.lld, llvm-objcopy and llvm-nm."""


def tool(name):
    exe = name + (".exe" if os.name == "nt" else "")
    dirs = ([os.environ["LLVM_BIN"]] if os.environ.get("LLVM_BIN") else []) + _BREW
    if os.name == "nt":
        dirs.append(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "LLVM", "bin"))
    for d in dirs:
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    if name == "ld.lld" and os.environ.get("LLD"):
        return os.environ["LLD"]
    p = shutil.which(name)
    if p:
        return p
    sys.exit("cannot find %s.%s" % (name, HELP))


def check():
    """Returns a list of (tool, path); exits with instructions if one is missing."""
    return [(n, tool(n)) for n in ("clang", "ld.lld", "llvm-objcopy", "llvm-nm")]
