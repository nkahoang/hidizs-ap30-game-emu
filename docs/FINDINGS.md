# Hidizs AP30 firmware (HIFIYF18.IMG): findings

Reverse-engineering log and status notes. Last updated 2026-11-17.

> **Paths.** This log was written before the repository was reorganised. Read old paths as follows:
> `HIFIYF18.IMG` → `firmware/HIFIYF18.IMG`; `rknanofw.py` → `tools/rknanofw.py`; `unpacked/` → `build/stock/` (`make unpack`);
> `gw/src`, `gw/tools`, `gw/games`, `gw/build.py` → `gamewatch/…`; `gw/gb/…`, `gw/build_gb.py` → `gameboy/…`, `gameboy/build.py`;
> `gw/test/harness.py`, `gw/ap30.ld`, the `md*_stub.c` files → `common/`; `gw/test/harness_gb.py` → `gameboy/test/`;
> `gw/third_party` → `third_party`; `gw/build/…` → `build/gw/…` and `build/gb/…`; the old top-level `build/` (logo test, early rollback images) is not part of the repository.
> The current commands are in the top-level `README.md` and `Makefile`.


## Status at a glance

- **Custom firmware flashing works.** On 2026-11-16 the AP30 accepted a modified image (test logo on the boot screen, header date bumped, CRC recomputed), showed "Updating...", and now boots with the logo. See [Updating the firmware](#updating-the-firmware).
- **There is no signature or encryption.** Integrity is the `RKnanoFW` magic, the header/header-copy match and a CRC-32 trailer, all of which `rknanofw.py` handles.
- **There is no tested brick recovery.** The AP30 has **no reset pinhole** (confirmed by the owner), so the Echo Mini mask-ROM procedure can't be followed as written. Read [Safety rules](#safety-rules-no-reset-hole) before flashing anything.
- **Unconfirmed:** why tests 1–3 only flashed briefly and test 4 worked (formatting internal storage is the leading explanation), and whether the date bump is needed.
- **The Game & Watch emulator module runs on the device** (2026-11-17, demo ROM, launched as Game > Tank Battle; Up, Left and Right respond). Custom code in a game slot is therefore confirmed to work. Background: `gw/` holds an SM510 CPU emulator that replaces stock game module 86. It passes its tests on the PC, running against the real resident firmware code in an ARM emulator. `gw/build/HIFIYF18.IMG` is a test image with a built-in demo ROM. See [Game & Watch emulator](#game--watch-emulator-gw).
- **The Game Boy emulator runs on the device** (2026-11-17): Dr. Mario plays at full emulation speed. `gw/build/gb/HIFIYF18.IMG` is the installed image. See [Game Boy emulator](#game-boy-emulator-gwgb).
- The analysis sections below are static analysis of the image unless they say otherwise.

## Files in this folder

| Path | What it is |
|---|---|
| `HIFIYF18.IMG` | Stock firmware v1.7.8, header date 2026-10-19. SHA-256 `c7601873cb3be8d1320225c69669e504576f7bcb1126595a9040492338e79840` |
| `rknanofw.py` | Unpack and repack tool (`info` / `unpack` / `pack`). The round trip is byte-identical. |
| `unpacked/` | Output of `rknanofw.py unpack` on the stock image: header, six section blobs, `manifest.json`, 478 BMPs. Treat it as a read-only reference. |
| `build/mod/` | Working copy used for the test build: logo added to `images/000_POWERON0_(0,0).bmp`, header date 2026-10-20 |
| `build/HIFIYF18.IMG` | **Currently installed on the device.** Test logo, date 2026-10-20, CRC `8b2561f8`, SHA-256 `a565abdd9f1dbb7e542b34df3a76e536c39d82ab828b629fa145b72ab5c29dbc` |
| `build/rollback-out/HIFIYF18.IMG` | Rollback image: untouched stock content, date bumped to 2026-10-21 so it counts as newer than the installed build. CRC `fc8c6f46`, SHA-256 `9bc984278923e53c2a6f02213e8fcf4035376f65694e89e443e305827c5c87f2`. Differs from stock only at `0x2`, `0x1b90002` and the CRC. Not yet flashed. |
| `build/POWERON0_preview.png`, `build/POWERON0_fromimg.png` | Previews of the test boot image |
| `tools/annotate_disasm.py` | Annotates `llvm-objdump` output with string and literal-pool targets (see [Disassembly setup](#disassembly-setup)) |
| `testlogo.png` | 411×410 test logo used for the boot-screen test |
| `HIFIYF05.IMG` | Older stock firmware, header date 2026-08-19, CRC ok. Smaller `code` (`0x1649f8`) and `menu` sections. Not analysed. SHA-256 `d69ca5012ff13fbf55d22dbb517a3419938e0673530d75452d6a82ee07c9cfc3` |
| `gw/` | Game & Watch emulator: sources, build script, tests. See [Game & Watch emulator](#game--watch-emulator-gw). |

## Updating the firmware

### Procedure that worked (test 4)

1. Charge the battery fully.
2. Remove the microSD card. The official Echo Mini instructions require this; it was not recorded whether a card was in for tests 1–3.
3. Format internal storage from the player's own menu, **immediately before each copy**. Tests 3 and 5 used an image that later flashed fine and were skipped without a fresh format.
4. Connect USB. Internal storage mounts on macOS (as `NO NAME` after the format; it was `AP30` before).
5. Check the image before copying:
   ```sh
   python3 rknanofw.py info build/HIFIYF18.IMG    # crc line must say "ok"
   ```
6. Copy it to the root of internal storage as `HIFIYF18.IMG`, without macOS metadata, and verify the copy:
   ```sh
   cp -X build/HIFIYF18.IMG "/Volumes/NO NAME/HIFIYF18.IMG" && sync
   rm -f "/Volumes/NO NAME/._HIFIYF18.IMG"
   cmp build/HIFIYF18.IMG "/Volumes/NO NAME/HIFIYF18.IMG" && echo OK
   ```
7. Eject. If a terminal is sitting inside the volume, `diskutil eject` is refused; `cd` out first, or run `diskutil unmountDisk force <disk>` once the copy is verified.
8. Restart the player. A real update shows "Updating..." for a while, then reboots. The player deletes the file afterwards, whether or not it applied it.
9. Don't power off or unplug during the update.

### Building a modified image

```sh
python3 rknanofw.py unpack HIFIYF18.IMG work          # or start from build/mod
# replace BMPs in work/images/ (same width and height; 24- or 32-bit uncompressed)
# optional: set the header date (bytes 0-3: 0x26 0x20 <day BCD> <month BCD>)
printf '\x26\x20\x20\x10' | dd of=work/header.bin bs=1 seek=0 count=4 conv=notrunc
python3 rknanofw.py pack work NEW.IMG                  # writes both header copies and the CRC
python3 rknanofw.py info NEW.IMG
```

- `pack` refuses images with the wrong size and keeps every section at its stock size and offset.
- To make a BMP with an overlay, ImageMagick works: `magick base.bmp \( logo.png -resize 80x80 \) -geometry +206+10 -composite -alpha off -type TrueColor BMP3:base.bmp`.
- Before copying an image, render the edited BMP back out of the packed image to check it:
  `python3 rknanofw.py unpack NEW.IMG check` and open `check/images/...`.

### Going back to stock

- Use `build/rollback-out/HIFIYF18.IMG` (stock content dated 2026-10-21) with the same procedure.
- Plain stock (dated 2026-10-19) is older than the installed build. Whether the updater accepts an older date is not known; the dual-slot code (see below) only copies `fw2` over `fw1` when `fw2` is newer, which suggests an older image may be skipped.
- An official release dated later than 2026-10-20 should install normally.

### Version and file name

- The version the code compares is the first 4 header bytes, read as `(u16[0] << 16) + u16[1]`. These bytes are the build date: `26 20` = 2026, then day and month in BCD (`19 10` = 19 October). This is the same layout ReChord documents for the Echo Mini.
- The device accepted `HIFIYF18.IMG` (it processed and deleted the file in every test). The firmware contains the pattern `HIFIYF00IMG`. Static analysis of the updater (code offset `0x83c58`): it does not accept any two digits. It writes two decimal digits taken from the byte at settings `0x03022894 + 0x2df` into the pattern and opens exactly that name in the root; if that byte is `0xf5` it opens `ECHOMINI.IMG` instead. The byte is presumably 18 on this unit. On the Echo Mini the updater accepts any two digits (`HIFIECnn.IMG`) or `ECHOMINI.IMG`; whether the AP30 matches `HIFIYFnn.IMG` the same way is untested.
- Some official Echo Mini updates format internal storage, so keep nothing there that you need.

### Device update tests (2026-11-16)

The device started on stock 1.7.8 (header date 2026-10-19). Every file was copied as `HIFIYF18.IMG` with `cp -X`, the `._` file removed, and the volume ejected before rebooting.

| # | Image | Header date | Conditions | Result |
|---|---|---|---|---|
| 1 | Test logo in POWERON0, stock date (SHA-256 `acc6e7302a1b3c96b924ff943dfb8c13c5384e9f13eb3e48affeb033d7ef9a68`) | 2026-10-19 | Internal storage with ~96 MB of hidden data | Update screen flashes briefly, no change, file deleted |
| 2 | Untouched stock | 2026-10-19 | Same | Same brief flash, file deleted |
| 3 | Test logo, date bumped (`build/HIFIYF18.IMG`) | 2026-10-20 | Same | Same brief flash, no change |
| 4 | Same image as test 3 | 2026-10-20 | Internal storage formatted from the player's menu (empty FAT32, 226 MB volume, 212 MB free) | **"Updating..." shown, update completed, test logo on the boot screen** |
| 5 | Game & Watch demo image (`gw/build/HIFIYF18.IMG`), 2026-11-17 | 2026-10-22 | Copied onto the volume as left after test 4; not reformatted just before the copy, as far as is known | Did not work (owner's report; what the screen showed was not recorded). File deleted. |
| 6 | Same image as test 5 | 2026-10-22 | Internal storage formatted again right before the copy (owner's report; the volume's `.fseventsd` folder was gone and used space had dropped, which fits) | **"Updating..." shown, update completed, player boots, Game & Watch module runs** (owner's report, 2026-11-17). First code change flashed successfully. |
| 7–9 | Game Boy builds dated 2026-10-24, -25 and -26 | newer each time | Freshly formatted each time. For the last one (2026-11-17) the volume also held six ROMs and three save files, 2.8 MB, copied in the same session | "Updating..." each time (owner's reports). So other files on the volume do not stop an update, as long as it was just formatted. |

What this proves:
- The AP30 accepts a modified image with changed resource pixels, a changed header date and a recomputed CRC.
- `rknanofw.py pack` produces images the device flashes.
- The brief flash in tests 1–3 was not a rejection of the modification, since stock behaved the same.

Tests 5 and 6 repeat the pattern of tests 3 and 4: the same image is skipped, then accepted after a fresh format. The working rule is therefore **format internal storage from the player's menu immediately before every copy**; a format left over from an earlier update is not enough. Why (the player writing hidden data after an update, free space, or file position on the volume) is not known.

Not yet separated:
- Whether the header date matters at all. Every image that flashed so far was also newer than the installed one, so the date has never been tested on its own. The owner suspects it is irrelevant. A freshly formatted volume plus an image dated the same as or older than the installed build would settle it.
- Whether a microSD card being present matters.
- Whether the date bump was needed. A stock-dated modified image on freshly formatted storage would answer this.
- What the brief flash said. Filming it would tell.

## Safety rules (no reset hole)

The Echo Mini's recovery needs its reset pinhole to power the device fully off before entering mask-ROM mode. The AP30 has no such hole, so there is **no known way to recover a device that won't boot**. Until one is found:

1. **Change resources only.** Replace images with same-sized images. Avoid code patches, header layout changes and section-size changes; `rknanofw.py` enforces the last two.
2. **Check every image before copying.** `rknanofw.py info` must show `crc ... (ok)`, and the re-extracted BMP must look right.
3. **Keep the stock image and the rollback image** (`build/rollback-out/HIFIYF18.IMG`) on your computer.
4. **Full battery, microSD card removed, no unplugging** while it updates.
5. **Flash one change at a time**, so a failure points to one cause.

Partial safety net, static analysis only: the firmware keeps two slots and repairs a bad one from the good one once it is running, and the slot copy writes the header last, so a power cut leaves the destination invalid rather than half-valid. Whether the **bootloader** falls back to `fw2` when `fw1` can't boot is not confirmed (see [Dual-slot recovery](#dual-slot-recovery-static-analysis-only)).

Ways to look for a recovery path, none tried yet:
- See whether the AP30 shows a Rockchip USB device (`2207:xxxx`) when it's fully off (power off from the menu, or after the battery runs flat) and USB is plugged in while holding different keys. On macOS: `system_profiler SPUSBDataType | grep -i -A3 rockchip`. Only watching what enumerates is harmless; don't send it any commands.
- Open the case and look for a reset, boot or mask-ROM test pad.
- Ask Hidizs support whether they have a USB recovery tool for the AP30.

## Platform

- Rockchip **RKnanoD** SoC (dual Cortex-M3), "RKnano SDK 1.0". The OS is a bare-metal RTOS, not Linux.
- The code is Thumb-2 and keeps debug strings, including source paths such as `..\..\Common\FwUpdate\FwUpdate.c`.
- The vendor tree is shared with the **Snowsky Echo Mini**: the code contains both `HIFIYF00IMG` and `ECHOMINIIMG` / `ECHO MINI` strings.
- Hi-res codecs (FLAC, ALAC, APE, DSF, DFF) run on the second core, which the code calls "B". Its strings are `A 2 B send dec_open...` and `StartBBSystem`.
- Stock header build date: 2026-10-19.

## Image layout

All offsets are file offsets. The six sections are contiguous.

| Offset | Size | Header field (offset / size) | Content |
|---|---|---|---|
| `0x0000000` | `0x200` | n/a | Header |
| `0x0000200` | `0x188714` | `0x54` / `0x70` | `code`: main CPU firmware, starting with the module table (see [Module table](#module-table-and-load-addresses)) |
| `0x0188914` | `0x201c06` | `0x78` / `0x7c` | `font0`: bitmap font |
| `0x038a51a` | `0x211c06` | `0x80` / `0x84` | `font1`: bitmap font |
| `0x059c120` | `0x1ca34a` | `0xcc` / `0xd0` | `charmap`: probably a character-mapping table (format not decoded) |
| `0x076646a` | `0x1af4a4` | `0xf8` / `0xfc` | `menu`: offset-indexed table, probably menu strings (not decoded) |
| `0x091590e` | `0x127a526` | `0x14c` / `0x150` | `res`: `ROCK26IMAGERES` UI images |
| `0x1b8fe34` | | | Zero padding |
| `0x1b90000` | `0x200` | | Exact copy of the header. Its offset is the firmware size stored at header `0x1f4`. |
| `0x1b90200` | | | Zero padding |
| `0x1c00000` | 4 | | CRC |

### Header (0x200 bytes)

| Offset | Meaning |
|---|---|
| `0x00` | Build date and version: `26 20 19 10` = 2026-10-19 (year BCD, day BCD, month BCD) |
| `0x04` | Version bytes `08 00 00 00 00 00 00 00` |
| `0x10` | `"Rockchip"` |
| `0x30` | `"RKnano SDK 1.0"` |
| `0x50`–`0x150` | Section table (see the layout table above). Unknown flag words at `0x74`, `0xc8`, `0xf4`, `0x148`, `0x19c`. |
| `0x1f4` | Firmware size `0x1b90000`, which is also the offset of the header copy |
| `0x1f8` | Magic `"RKnanoFW"` |

ReChord's stock Echo Mini header has the same shape: the same `0x7c`/`0x84` values (`0x00201C06`, `0x00211C06`), the same optional-part groups at `0xc8`, `0xf4` and `0x148`, and the same `0x1CA34A` size in the `0xc8` group.

### CRC

The last 4 bytes are a little-endian Rockchip RKCRC over everything before them: CRC-32, non-reflected, polynomial `0x04c10db7`, initial value 0, no final XOR. It is implemented in `rknanofw.py` and verified to match the stock file. ReChord reports that the Echo Mini rejects a wrong trailer before writing anything ("bad CRC Image").

### ROCK26IMAGERES (`res` section)

| Offset (in section) | Content |
|---|---|
| `0x00` | `"ROCK26IMAGERES  "` (16 bytes) |
| `0x10` | Image count, u32 = 478 |
| `0x20` | Entry table, 16 bytes per image: `u16 w, u16 h, u16 x, u16 y, u32 size, u32 offset` |
| `0x2200` | Pixel data, contiguous, `size = w*h*2` |
| After the pixel data | Name table, 108 bytes per image: null-padded name, then the image's `offset, w, h` as u32 at bytes 96–107 |

- Pixels are **big-endian RGB565**. Little-endian decoding gives visibly wrong colours.
- The screen is 296×240, which is the size of full-screen images such as `POWERON0`, `MAINMENU_*` and `USB_BACKGROUND`.
- `POWERON0_(0,0).BMP` (image 0) is the boot screen; replacing it is confirmed on the device.
- Names encode a draw position, for example `DIALOGBOX_BUTTONNO_(96,136).BMP`.
- This is the same table format Echo-Mini-Customizer and Flame Ocean edit.

## Integrity and security checks

- There is **no cryptographic signature and no encryption**. Confirmed on the device by test 4.
- The routine around file offset `0x5f1a0` (code offset `0x5efa0`) prints `fw1 Sign error!`, but the "sign" check only compares the 8-byte `RKnanoFW` magic at header `0x1f8`.
- The same routine compares the header against its copy and handles a second firmware slot. Strings: `fw1 compare error!`, `fw2 compare error! 0x%x`, `FW2Valid = 1`, `No find fw2!`, `fw1 && fw2 error!`, `fw1valid = %d fw2valid = %d`.
- It also compares versions read from the first 4 bytes of the header (the date field) to choose between slots.
- Community reports for the Echo Mini (same platform) say modified images flash without any verification.

## Dual-slot recovery (static analysis only)

The firmware keeps two copies of itself on flash and repairs a bad copy from the good one. None of this has been observed on a device.

- **Slots:** `fw1` is at sector 0. `fw2` is at `((fw size + 0x104000) >> 9) & ~0x7ff` sectors, i.e. after `fw1` on a 1 MB boundary. If `fw2` is not at the expected place the check steps in 0x800-sector increments looking for the magic.
- **Validity test:** a slot is valid when its header has the `RKnanoFW` magic at `0x1f8` and the 0x200-byte header equals the header copy at `slot start + fw size`. The body is not checksummed.
- **Boot-time check** (code offset `0x5efa0`, module 1). It returns 0 when both slots are valid and their headers are identical, and −1 otherwise. A direction flag at RAM `0x030238d8` is set to 1 when `fw1` must be rewritten from `fw2`. The `fw2` start sector is kept at RAM `0x030238c4`.

| State found | Action |
|---|---|
| Both valid, headers identical | Nothing |
| `fw1` bad, `fw2` valid | Restore `fw1` from `fw2` |
| `fw2` bad or missing | Rewrite `fw2` from `fw1` |
| Both valid, `fw2` version newer | Copy `fw2` over `fw1` |
| Both valid, `fw2` same or older | Rewrite `fw2` from `fw1` |
| Both bad | Prints `fw1 && fw2 error!`; no repair in this code |

- **Version compare:** the first 4 header bytes (the date field) read as two 16-bit halves, `(u16[0] << 16) + u16[1]`.
- **Copy routine** (`FwRecovery`, code offset `0x83aa2`, module 8; arguments are destination sector, source sector, size in bytes). It fills the destination's first 16 sectors with `0xff`, copies the body in 16-sector chunks, and writes the first 16 sectors (the header) last. Every chunk is written, read back and compared (helper at `0x83a18`). A power cut mid-copy therefore leaves the destination invalid, not half-valid.
- **Wrapper** at `0x83b9e` picks the direction from the flag, runs the copy, then logs `Delete fwfile!`.
- **Updater** (`0x83c2e`) logs `Fw2 Update Start` / `Fw2 Update End` and then calls the same copy routine at `0x840e0`. This suggests it writes `fw2` first and then copies it to `fw1`; the write order was not traced in full.
- **Reboot routine** (code offset `0x2d62a`, resident module; arguments are address and flag). It writes the string `NanoCRebootFlag` to RAM `0x0309fff0` before a `SYSRESETREQ`. With flag bit 1 set it first writes `0xffff18af` to register `0x5002004c`. With address `0x8c` it jumps through a vector instead of resetting. What the loader does with the marker or the register is not known.

Not confirmed:

- Whether the bootloader starts `fw2` when `fw1` cannot boot. The check above lives in the main firmware, which has to be loaded from a slot first, and the loader is not in this image. ReChord mentions a bootloader A/B fallback on the Echo Mini.
- Whether a USB mask-ROM mode is reachable on the AP30 (see [Safety rules](#safety-rules-no-reset-hole)).
- What posts `MSG_SYS_FW_RECOVERY` and whether a key combination forces recovery. Callers were not traced (see the module table note below).

## Storage: internal vs SD card (static analysis only)

File data from both sources goes through one block-device layer in the resident module (`MemDev.c`). The filesystem sits on top and has one active volume at a time.

### Block-device layer

- **Calls:** `MDRead(dev, lba, nSec, buf)` at code offset `0x41dca` and `MDWrite(dev, lba, nSec, buf)` at `0x41e12`. Sectors are 512 bytes.
- **Device ID:** the high 16 bits select a driver and the low byte is a unit number passed to it. `0x41db0` looks the driver up in a 2-entry table at code offset `0x48d0c` (run address `0x0306f480`), `0x28` bytes per entry.

| Table offset | Field |
|---|---|
| `+0x04` | read |
| `+0x08` | write |
| `+0x0c` | get capacity/info |
| `+0x10` | status ioctl (used for presence and change checks) |
| `+0x14` | probe |
| `+0x1c` | set access tag (internal driver only) |
| `+0x24` | driver ID, u16 |
| `+0x26` | removable flag, u8 |

| Driver ID | Removable | Read / write (code offsets) | What |
|---|---|---|---|
| 3 | no | `0x38dfc` / `0x3aa44` | Internal storage |
| 4 | yes | `0x38c62` / `0x3a9f0` | SD card |

### Internal storage (driver 3)

- It sits on the SD/MMC controller code (`SDCtrl.c`), port 1, so it is an eMMC-style device, not raw NAND. The name "NAND" survives only as a tag value.
- The first `0x2000` sectors (4 MB) of the device are skipped: every access adds `0x2000` to the LBA. What lives there is not known (possibly the loader).
- There is no partition table. The unit number selects a region by adding up region sizes held in RAM:

| Unit | Device ID | Start | Size source |
|---|---|---|---|
| 0 | `0x30000` | 0 | `[0x030238c0]`; holds `fw1` and `fw2` |
| 1 | `0x30001` | after unit 0 | `[0x030238cc]`; purpose not identified |
| 2 | `0x30002` | after units 0 and 1 and the unit-3 size | Rest of the device; the internal FAT volume |
| 3 | `0x30003` | after units 0, 1 and 2 | `[0x030238d0]`; purpose not identified |

- **Write guard:** `0x38dc4` reports an LBA as protected when it falls inside unit 0 and the access tag at `[0x03022684]` is not `"NAND"` (`0x444e414e`). The updater sets the tag before writing firmware and clears it afterwards (the `0x6a136` calls in `FwRecovery`'s helper). Where the write path consults this check was not traced.
- **On the device:** the internal FAT volume is visible over USB (226 MB, FAT32). Before the format on 2026-11-16 it showed about 96 MB used with only the firmware file visible.

### SD card (driver 4)

- Port 0 of the same controller. The unit number is ignored.
- LBAs are passed straight through with no offset, so LBA 0 is the card's own MBR. For byte-addressed (non-high-capacity) cards the driver shifts the LBA left by 9.
- Reads fail when the card is absent or the range exceeds the capacity at `+0x10` of the card structure (pointer at `[0x0300566c]`).
- The USB mass-storage inquiry string is `HIFI MP3     SD         1.00`.

### Filesystem selection

- `MemDevSetup(disk)` at code offset `0x420d2` (`fat.c`) maps a disk number to a device ID and makes it current:

| Disk number | Device ID |
|---|---|
| 2 | `0x30002` (internal) |
| 3 | `0x30002` (internal, same region) |
| 4 | `0x40000` (SD card) |

- For a removable device it checks presence and runs the probe first, and logs `MemDevSetup MDProbe Error` on failure.
- The current disk number is stored at `[0x0307e711]` and the current device ID at `[0x0307e718]`.
- Every FAT sector read and write (`0x31554`, `0x31568`) uses the device ID at `[0x0307e718]`. Code above the filesystem never names a device; it switches disk first and then uses the same file calls.
- Disk 3 shares the internal region with disk 2 but takes a different path in cluster lookup (`0x3164a`). It looks like a hidden system volume; not confirmed.
- The FAT code logs `FsType ==== %d   FATType==%d` and contains an `EXFAT` signature and a `CheckMbr Error` message, so exFAT cards appear to be handled.

Not confirmed: which disk number the updater searches for `HIFIYF00IMG` (in practice it finds the file in the root of the internal volume).

## Memory map and hardware seen in the image (static analysis only)

The image does not state chip sizes. These are the address ranges and devices the code actually uses, so RAM figures are lower bounds.

### RAM

| Core | Range used | Size | Evidence |
|---|---|---|---|
| A (main) | `0x03000000`–`0x030a0000` | 640 KB | Initial stack pointer `0x03004000` (resident vector table at code offset `0x2988c`); module data and bss up to about `0x0304b418`; code from `0x03050000` to `0x0309f7cc`; `NanoCRebootFlag` marker at `0x0309fff0` |
| B (codecs) | `0x01000000`–`0x0102d184` | at least 181 KB | Codec modules 71–80: code at `0x01000000` (largest `0x1626c`), data at `0x01020000` (largest `0xd184`) |

- Core A layout: 16 KB stack below `0x03004000`, then data and bss, then code. All code runs from RAM: the resident module is 189 KB and the largest overlay (module 39) is 122 KB.
- Module 35's table entry (data `0xc834` at `0x03048b50`) would overlap the resident code if loaded as written, so it is probably not loaded that way. It is excluded from the figures above.
- No external RAM or memory-controller setup was found.

### Peripherals and devices

- **Register bases:** peripheral registers are addressed in `0x40000000`–`0x4024ffff` (most used pages: `0x4011`, `0x4000`, `0x4018`) and at `0x50010000` and `0x50020000`.
- **Clock:** the constant 24,000,000 appears 21 times, consistent with a 24 MHz crystal. `24576000` and `22579200` also appear, the usual audio master-clock rates.
- **DAC:** I2C bus 5, 8-bit address `0x66` (7-bit `0x33`), 400 kHz, with 3-byte register addresses plus a control byte (`0x3bafc`). Register addresses used include `0x010003`, `0x01000b`, `0x05000a`, `0x05000b`, `0x090001`. That protocol and map match the Cirrus Logic CS43131/CS43198 family; the exact part is not confirmed. The log string `dac66_Right` suggests a second DAC for the left channel, but no second address was found in the resident module.
- **Other I2C devices:** 8-bit address `0xa2` on bus 0 (the address of a PCF8563-type real-time clock; not confirmed) and `0x38` on bus 3 (not identified).
- **Display:** 296×240, 16-bit colour, from the image resources. The controller is chosen at run time by `LcdDriverIndex`; the part is not identified.
- **Sample rates:** constants for 44.1 kHz to 384 kHz PCM and for DSD rates 2.8224, 5.6448 and 11.2896 MHz are present.
- **USB:** mass storage (`HIFI MP3 SD`, `HIFI MP3 CD-ROM`, `USB MP3` inquiry strings) and USB audio (`USBAudio.c`).
- **Other:** `KeyDevice` and `ADCDevice` strings (keys and ADC), `battery.c` with charge states, and a `BT Music` window. The Bluetooth module is not identified.
- **Internal storage size:** not stated. It must hold at least 4 MB reserved plus two 27.6 MB firmware slots, about 60 MB, in addition to the 226 MB user volume.

## Keys (static analysis only)

### Raw scan

The scan routine is at code offset `0x3c558`. It returns one key bit per scan, so **two keys can never be seen at once**.

1. A GPIO input (port 2, pin 5) is checked first. If it is active the result is `0x1`.
2. Otherwise ADC channel 1 is read (10-bit) and matched against a resistor ladder:

| ADC value | Key bit |
|---|---|
| 0–69 | `0x004` |
| 100–183 | `0x010` |
| 200–309 | `0x008` |
| 320–429 | `0x020` |
| 442–559 | `0x002` |
| 560–679 | `0x100` |
| 700–849 | `0x040` |
| 850–949 | `0x080` |
| 950 and above | none |

Because the keys share one ADC ladder, holding several keys at once reads as a single different value. That matters for any mask-ROM key combination, which the boot ROM would read on its own terms.

### Key value

The state machine at `0x3c5fa` runs once per tick and produces a 32-bit value: event type in the top 4 bits, key bit in the low bits. A window's key handler fetches it with the function at code offset `0x3c832`.

| Type | Meaning | When |
|---|---|---|
| `0x10000000` | Down | Same key seen for 2 ticks |
| `0x20000000` | Long-press start | Held for 40 ticks |
| `0x30000000` | Repeat | Every 12 ticks while still held |
| `0x40000000` | Short release | Released before 40 ticks |
| `0x50000000` | Long release | Released after 40 ticks |

The tick length was not measured. Snake also handles `0x41000000` and `0x42000000`, which clear and set its lock flag; these are not produced by the ADC scan and look like hold-lock events.

### Device result (2026-11-17)

With the Game & Watch demo ROM, which maps Left, Up, Play and Right: the owner reports that **Up, Left and Right work**, which confirms `0x010`, `0x008` and `0x004` and the "down" event type for them. Down was not mapped in that build. The owner also names buttons **A, B and Select** on the device; none of them did anything, so whichever of them is `0x100` either does not send "down"/"repeat" events or is not `0x100` at all. Which physical button gives which bit is being checked with the key-test build (`gw/build.py --keytest`), which shows the last raw key value on screen.

### Key ladder measured on the device (2026-11-17)

Read from the key-test build (raw ADC channel 1, lowest value during a press), reported by the owner. Every button lands inside the range the firmware's table gives for one key bit, so the table and the button names are now **confirmed on the device**:

| Physical button | ADC value | Firmware range | Key bit |
|---|---|---|---|
| Right | 0 | 0–69 | `0x004` |
| Up | 120–121 | 100–183 | `0x010` |
| Left | 241 (243 seen) | 200–309 | `0x008` |
| Down | 365 | 320–429 | `0x020` |
| Select | 488 | 442–559 | `0x002` (Back; a long press returns to the main menu) |
| Start / Play | 610 | 560–679 | `0x100` |
| B | 733 | 700–849 | `0x040` |
| A | 855 | 850–949 | `0x080` |

- The steps are even, about 122 apart, which is what a series resistor chain with one tap per button gives. In that wiring a button nearer the top of this table hides any button below it, so two buttons held together read as the upper one alone. **Confirmed on the device:** holding A and adding Right makes the reading drop to 0, the same as Right alone. Two ladder buttons can therefore never be read together, by the firmware or by reading the ADC directly. Priority, strongest first: Right, Up, Left, Down, Select, Start, B, A. Only the key on the GPIO (probably power) is independent of the ladder.
- The live reading jitters by a count or two while a button is held. That is ordinary analogue noise; the firmware's wide ranges absorb it.
- `0x040` and `0x080` are B and A, not volume keys as guessed earlier.

### Roles, inferred from the games

| Key bit | Role | Evidence |
|---|---|---|
| `0x001` | Probably power | Only key on a GPIO |
| `0x002` | Back / exit | Snake exits on `0x20000002` and `0x40000002` |
| `0x010` | Up | Snake direction 0: y − 1 |
| `0x020` | Down | Snake direction 1: y + 1 |
| `0x008` | Left | Snake direction 2: x − 1 |
| `0x004` | Right | Snake direction 3: x + 1 |
| `0x100` | Play/pause ("PP") | Snake start and pause; other games print `PP:Start` |
| `0x040`, `0x080` | B and A | Confirmed on the device, see the table above |

The device has physical up, down, left and right buttons (confirmed by the owner). The assignment above comes from Snake's key handler and step function, and was **corrected on 2026-11-16**: an earlier version of this table had up/down and left/right swapped because it assumed a field of 20 columns by 16 rows. Snake's own drawing calls show the opposite. It fills the field with `fill_rect(0x44, 0x1e, 0xe3, 0xe5)`, which is 160 pixels wide and 200 tall, so the coordinate limited to 16 is x and the one limited to 20 is y. Running stock Snake in the PC harness (`gw/test/harness.py snake`) draws that portrait field. Still not checked on the device.

## Sound output path (static analysis only)

The USB audio module (module 11, `USBAudio.c`) plays raw PCM without the decoder core, so it is the model for sound from a custom module. Its start routine is at code offset `0x80c12`; the addresses below are resident code offsets.

1. Open the codec (module-local function at `0x80bd0`); on failure it logs `Codec Open Error1`.
2. Toggle three GPIO outputs with short delays: port 2 pin 14, port 2 pin 2 and port 0 pin 12 (`0x2c488` configure, `0x304b8` direction, `0x304f2` level; `0x3f3e4` is a delay). These look like DAC or amplifier power and mute lines.
3. Set the sample rate: `0x3bb70(rate)`.
4. Set up I2S: `0x301ec(1, 2, 1, rate, 0, 0xf, 0)`. The first argument is the port (I2S1) and `0xf` matches 16-bit samples.
5. Start a DMA transfer: `0x3adb0(5, buffer, 0x40030024, length, config, callback)`. `0x40030024` is the I2S transmit register. The callback (module-local, `0x80b5e`) is called when the block has been sent and queues the next one.
6. Start transmit: `0x2a1da(1, 4)`.
7. Set the volume: `0x3bcba(level)`, with the level taken from the settings structure at `0x03022894 + 0x12`.

- The PCM buffer is two `0x800`-byte halves at `0x0302d02c`, used alternately. Defaults in the module are 48,000 Hz and 16 bits.
- USB data arrives in a `0x9000`-byte ring at `0x03023f8c` and is copied to the DMA halves.
- Argument meanings above are inferred from values, not confirmed.

Plan for a custom module: copy this sequence, allocate two small PCM blocks in the module's bss, and fill the idle block from the DMA callback. A Game & Watch beeper or a Game Boy's four channels would be mixed on core A inside that callback. Music playback must be stopped first, since it owns the same I2S port and DMA channel.

## Echo Mini projects (same SoC, not verified on the AP30)

Read 2026-11-16. Sources: ReChord docs (`docs/FLASHING.md`, `docs/fw1-packing.md`, `docs/bootloader-analysis.md`, `docs/DEBRICK-LINUX.md`), and the Echo-Mini-Customizer, Flame Ocean and Echo-Mini-Themes READMEs.

| Project | What it does |
|---|---|
| Flame Ocean (web app, losses/flame-ocean-website) | Parses the firmware, views and replaces RGB565 images, replaces fonts from TTF/OTF/WOFF files, exports the modified image. Resource-only modding. |
| Echo-Mini-Customizer (PyQt5) | Edits the same ROCK26 image table (16-byte entries, 108-byte name records, big-endian RGB565) and the UTF-16LE string table (theme names, 21 languages). Patches Thumb-2 code so each theme gets its own boot and charge animation (`CMP R0,#0x43` -> `#0x00`, adjusted `ADDW` offsets, enlarged tables). Recomputes the Rockchip CRC. |
| Echo-Mini-Themes | Prebuilt theme images made with Flame Ocean. Install: remove the microSD card, copy the IMG to internal storage, reboot. |
| ReChord (GPL-3.0) | From-source replacement firmware with its own packer, CRC tool and debrick guide. Boots and plays on hardware. |

Details relevant to the AP30:

- **Official Echo Mini update** (stock `Read me.txt`, quoted by ReChord): copy `HIFIECxx.IMG` to the root of internal storage, remove the microSD card, reboot. ReChord flashes its build as `HIFIEC90.IMG` and says the updater accepts `HIFIECnn.IMG` (any two digits) or `ECHOMINI.IMG`.
- **Container:** on the Echo Mini, `0x1f8` holds `RKnanoFW`, `0x200` a load base (`0x03050000`) and `0x204` an entry count (91), followed by a table of 16-byte memory-map entries. The AP30 has the same base and an entry count of 113, but its table uses **32-byte entries** (8 words per module, see [Module table](#module-table-and-load-addresses)), so the two formats are not identical. The Echo Mini image also has a separate second-stage loader section and a separate `section_3` application, which the AP30 image doesn't have.
- **Boot validation:** ReChord found that the `fw1/fw2` validators on the Echo Mini are boot-ROM functions called through a table filled at run time, and that there is no signature check.
- **Audio:** decoded PCM is fed to I2S1 into a Cirrus CS43131 (dual CS43131 on the Echo Mini). This agrees with the I2S port and DAC protocol found above.
- **Other hardware:** eMMC internal storage, DW-MMC SD driver, Bluetooth through an external UART module, backlight PWM on GPIO2.4, mask-ROM routines for LCD, I2S, DAC, USB and keys. The project's `docs/HARDWARE.md` is an early, self-described uncertain note; where it differs from the analysis here, the analysis here is more specific.
- **Debrick (Echo Mini only):** press the reset pinhole to power off, hold every button except power, plug in USB. The device shows as `2207:262d` (Rockchip mask ROM). A patched `rkdeveloptool` then runs `ld` -> `td` -> `wl 0 <full stock IMG>` -> `rd`; never `db`. **The AP30 has no reset pinhole**, so this can't be followed as written.

## Verified with rknanofw.py

- Unpack then repack gives a byte-identical file (same SHA-256).
- Inverting one 296×240 image and repacking changed exactly 142,080 bytes (that image) plus the 4 CRC bytes. The new CRC validates.
- A BMP with the wrong dimensions is rejected and no output file is written.
- An image packed by the tool was flashed and booted on the device (test 4).

## Disassembly setup

The `code` section is plain Thumb-2 and disassembles cleanly from offset 0 of `unpacked/code.bin`. Code offset = file offset − `0x200`.

```sh
L=/opt/homebrew/opt/llvm/bin
cp unpacked/code.bin c.bin
$L/llvm-objcopy -I binary -O elf32-littlearm --rename-section .data=.text,code c.bin c.elf
$L/llvm-objdump -d --triple=thumbv7m-none-eabi --no-show-raw-insn c.elf > raw.txt
python3 tools/annotate_disasm.py c.bin raw.txt dis.txt   # adds '; -> addr "string"' and '; =literal'
```

Keep `c.bin` named `c.bin`: the annotator matches llvm-objcopy's `_binary_c_bin_start` symbol names.

- Strings are mostly loaded with PC-relative `adr`, so they resolve without knowing the load address.
- RAM globals sit around `0x03000000`–`0x030b0000`. In Ghidra, a base of 0 for `code.bin` is enough for string cross-references.
- Every log call names its source file and line, which makes navigation easy. The `FILE: %s, LINE: %d:` debug printf is at code offset `0x2cf26` (run address `0x0305369a`).
- **Branch targets in the flat disassembly are wrong when a call crosses modules.** The true run address of a target is `module run address + (displayed target − module start offset)`. For example `bl 0x5508a` inside module 8 and `bl 0x2fe16` inside module 1 both resolve to the printf at `0x0305369a`. This is why a plain search for callers of a function finds nothing.

### Module table and load addresses

`code.bin` starts with a module table: `u32 base = 0x03050000`, `u32 count = 0x71` (113), then 8 words per module from offset 8: code load address, code run address, code length, data load address, data run address, data length, bss address, bss length.

- Code offset = load address − `0x03050000`.
- Module 0 is the resident code: code offsets `0x2988c`–`0x57b8c`, run address `0x03050000`.
- Most other modules are overlays that share a run address (many at `0x030815c4`). Module 1 (`0x5dd40`–`0x5f3e4`, run `0x030815c4`) holds the boot-time firmware check. Module 8 (`0x83a18`–`0x841b0`, run `0x03082028`) is `FwUpdate.c`.
- Modules 63–69 (`0x104c`–`0x2988c`) have run address 0 and look like character tables, not code. Modules 71–80 (`0xef088`–`0x188714`) run at `0x01000000` and contain `HifiFileOpen: timeout!!` strings; they are the second-core codec images.

Module map (code offsets), identified by the source paths and strings inside each module:

| Modules | What |
|---|---|
| 0 | Resident firmware |
| 1 | `main.c` init, boot-time firmware check |
| 5 | `MDBBuildWin.c` |
| 8 | `FwUpdate.c` |
| 9 | `FunUSB.c` (logs `Firmware Upgrade...`) |
| 10–12 | USB control, USB audio, USB mass storage |
| 17 | `PicWin.c` |
| 21 | `MainMenu.c` (logs `MSG_SYS_FW_RECOVERY Reboot...`) |
| 27 | `MusicWin.c` |
| 31 | `BrowserUI.c` |
| 33–34 | `AudioControl.c` |
| 41–57 | Codec front-ends (MP3, WMA, AAC, WAV, OGG, FLAC, ALAC, APE, DFF, DSF) |
| 81–111 | Games (see "Game modules") |
| 112 | BT Music window |

Unlisted entries are empty or not identified.

### Game modules

Modules 81–111 are 31 games at code offsets `0x8b990`–`0xb9148`. All of them are linked the same way:

- Code is Thumb-2 and runs at `0x030815c4`. Only one game is loaded at a time.
- Data runs at `0x03023b48` and is stored in the file directly after the code. Bss follows the data in RAM.
- The data starts with a 7-word window structure: two null pointers, then five function pointers. In Snake these are service (periodic tick), key handler, paint, init and deinit, in that order. Other UI windows (MainMenu, MusicWin) use the same structure.
- Firmware functions are called with plain `bl` to fixed addresses in the resident module.
- UI strings are UTF-16 in the data section.

Smallest games:

| Module | Offset | Code | Data | Identified by |
|---|---|---|---|---|
| 81 | `0x8b990` | `0xb00` | `0x80` | Snake (`..\UI\game\Block_Game.c`, title `SNAKE`) |
| 88 | `0x9616c` | `0xb3c` | `0xec` | Minesweeper (`Mine`, `OK:Dig`, `PP:Flag`) |
| 87 | `0x95578` | `0xb70` | `0x84` | Unnamed (`Score`, `Life`, `PP:Start`) |
| 102 | `0xa8268` | `0xc24` | `0xbe` | Unnamed (`Score`, `Life`) |
| 93 | `0x9aff0` | `0xc34` | `0x66` | Unnamed (`Score`, `Move:`) |

The largest is module 86 (`0x91ed8`, code `0x35e8`). Module 92 is 2048 and module 91 is a "24 points" game. The `menu` section names more games (Tank Battle, Maze, Chinese Chess, Jigsaw Puzzle, Block Shooter, Block Puzzle+, Retro Block Puzzle) that are not yet matched to module numbers.

Snake calls 17 distinct resident functions. The most used, as code offsets with call counts: `0x3df14` (20), `0x41760` (12), `0x3d6c4` (9), `0x3dca0` (8), `0x4177c` (6), `0x3f450` (5). `0x41760` and `0x4177c` take a small message ID and look like send-message and check-message. The rest are not identified.

Building a replacement game (done in `gw/`, not yet flashed; a code change, so see [Safety rules](#safety-rules-no-reset-hole) first):

1. Compile for Cortex-M3 Thumb, freestanding. Homebrew `llvm` (clang) plus `lld` do this and are installed; `gw/build.py` has the exact flags.
2. Link `.text` at `0x030815c4` and `.data` at `0x03023b48`, with the window structure first in `.data` and `.bss` after it.
3. Give each firmware function as an absolute symbol: run address = code offset − `0x2988c` + `0x03050000`.
4. Write the raw code and data over an existing game's slot and update that module's code, data and bss lengths in the table.
5. Repack with `rknanofw.py`.

Constraints: the code section has no free space (module 80 ends exactly at its end) and `rknanofw.py` keeps section sizes fixed, so code plus data must fit in the slot being replaced. It is assumed, not confirmed, that the loader zeroes bss and that RAM beyond what existing games use is unsafe.

### Game module API (static analysis plus PC emulation)

Worked out from Snake (module 81) on 2026-11-16. "Checked in emulation" means the vendor code was executed in Unicorn by `gw/test/harness.py` and behaved as described. Nothing here has been observed on the device.

**Window structure** (7 words at the start of module data, `0x03023b48`), used by the window manager at code offsets `0x31334`–`0x31530`:

| Offset | Field |
|---|---|
| `+0x00`, `+0x04` | Child and parent links, filled by the firmware |
| `+0x08` | `service()`: called every pass of the main loop; returns 0 |
| `+0x0c` | `key()`: called every pass; reads the key itself; returns −1 after asking to leave, else 0 |
| `+0x10` | `paint()`: called every pass; the game decides what to redraw |
| `+0x14` | `init(arg)` |
| `+0x18` | `deinit()` |

**Resident functions.** Run address = code offset − `0x2988c` + `0x03050000`; call them as Thumb (bit 0 set).

| Code offset | Run address | What |
|---|---|---|
| `0x3e734` | `0x03064ea8` | `set_window(x0, y0, x1, y1)`, inclusive. Checked in emulation. |
| `0x3e650` | `0x03064dc4` | `put_pixel(rgb565)`: writes at the cursor and advances through the window, row by row. Checked in emulation. |
| `0x3df14` | `0x03064688` | `fill_rect(x0, y0, x1, y1)`, inclusive, in the colour at `0x03022dec`. Checked in emulation. |
| `0x3dcd4` | `0x03064448` | `draw_point(x, y, rgb565)` |
| `0x3d6c4` | `0x03063e38` | `draw_string(x, y, utf16)` in the current colour. Reads the font from storage. |
| `0x3dca0` | `0x03064414` | Sets byte `+0x10` of the settings structure and returns the old value. Snake sets 2 around its text; probably a language or font index. |
| `0x3dc2e`, `0x3dc52` | | Text-related state setters that return the old value; Snake saves and restores them in paint. |
| `0x41760` | `0x03067ed4` | `msg_send(id)`: sets a bit in the bitmap at `0x03023280` |
| `0x4177c` | `0x03067ef0` | `msg_take(id)`: returns 1 and clears the bit if it was set |
| `0x417a2` | | `msg_clear(id)` |
| `0x3c832` | `0x03062fa6` | `get_key()`: returns the key value described under [Keys](#keys-static-analysis-only), 0 for none |
| `0x41960` | `0x030680d4` | `task_switch(task, arg)`: stores the task number at `0x030057c0` and copies 28 bytes of `arg`. Snake leaves with task 10 and `arg[0] = 7`, then returns −1 from `key()`. |
| `0x3f450` | `0x03065bc4` | Clears message `0x1c` and stamps the tick counter into `0x03022e74`; looks like "user is active" for the screen-off timer |
| `0x3fd2e`, `0x3fce6` | `0x030664a2`, `0x0306645a` | Called by Snake in init and deinit. They start and re-arm the software timer at `0x03005774` (period from a table of 0, 6000, 30000, 60000 ticks), which looks like the idle power-off timer. |
| `0x2d0ae` | `0x03053822` | Clears `[0x0300414c]`; Snake calls it at the end of init |
| `0x2f3c0` | | `rand()` (linear congruential, seed at `0x030055f4`) |
| `0x40be6` | | Returns the tick counter |

- **Files** (from `FwUpdate.c`, module 8; open, seek and read **confirmed on the device on 2026-11-17** by the Game Boy module loading a ROM; before that checked in emulation: the firmware's own FAT code was run in the harness against a FAT32 disk image with a partition table, with only `MDRead` replaced, and open, read, seek, close, end-of-file and a missing file all behaved as below):

| Code offset | Run address | What |
|---|---|---|
| `0x334a4` | `0x03059c18` | `FileOpen(path, name, mode)`: `path` is a C string (the updater passes `"\\"`, the root), `name` is an 11-character 8.3 name without the dot, space padded (`"HIFIYF18IMG"`), `mode` is `"R"`. Returns a handle, or −1. Handles index a table of 8 file blocks at `0x0307f254`. |
| `0x337fa` | `0x03059f6e` | `FileRead(buffer, size, handle)`: returns the bytes read, 0 on error |
| `0x33d82` | `0x0305a4f6` | `FileSeek(offset, 0, handle)` |
| `0x336b2` | `0x03059e26` | Called once at the end of the updater with the handle; almost certainly `FileClose(handle)` |

  **Writing and listing** (checked in emulation on 2026-11-17 with `MDRead` and `MDWrite` replaced by stubs over a disk image; not yet used on the device):

  | Code offset | Run address | What |
  |---|---|---|
  | `0x379fe` | `0x0305e172` | `FileWrite(buffer, fileOffset, size, handle)`: `fileOffset` must be a multiple of 512 and not beyond the current file size; the file must have been opened with mode `"W"`. Returns the bytes written. |
  | `0x3256c` | `0x03058ce0` | `GetFDTInfo(out32, dirCluster, index)`: copies the raw 32-byte FAT directory entry number `index` of a directory. Returns 0; the listing ends at an entry whose first byte is 0. Entries with attribute `0x0f` are long-name parts, first byte `0xe5` is a deleted entry, attribute bit `0x10` a folder, `0x08` the volume label. |
  | `0x377d0` | `0x0305df44` | `FileCreate(path, name)`: makes an empty file (attribute `0x20`) and returns a handle opened for writing, or −1 if the name already exists. Two instructions that jump into `0x37528` with the attribute in `r2`; `0x377d4` is the same with attribute `0x22` (hidden). |
  | `0x3781c` | | `FileDelete(path, name)`. The thumbnail module (18) calls it and then `0x377d4` to recreate its cache file `PICTURE.OGG`, and then writes it with `FileWrite`. Not tested. |

  The root directory's cluster is the u32 at `0x0307e729`. Opening an existing 32 KB file with `"W"`, writing all of it at offset 0 and closing it rewrote the data in place: reading it back matched, macOS read the same contents from the image afterwards, the other files were unchanged and `fsck_msdos` found no errors. **Creating files (2026-11-17, emulation only):** `FileCreate` followed by one `FileWrite` at offset 0 made new files of 32 KB, 8 KB and 2 KB; each read back correctly through the firmware, macOS read the same bytes from the image, the other files were unchanged and `fsck_msdos` found nothing wrong with the directory or the cluster chains. Creating a name that exists returned −1. The Game Boy module now uses this to make a missing save file at full size the first time a game starts; later saves still only rewrite it in place. **In-place rewriting is confirmed on the device** (save files copied back from the player on 2026-11-17 contained data for Pokémon Red and Zelda); creating a file has not run on the device yet.

  They act on the current disk (see [Filesystem selection](#filesystem-selection)); which disk is current while a game runs is not known. `FileSysSetup(disk)` at code offset `0x31db2` (run `0x03058526`) selects a disk and parses its boot record (it handles an MBR); the firmware calls it at boot with 2 and 4. `FileRead` returns 0 at end of file. `FileOpen` returns the index of the first free file block, so the first open file is handle 0. A long file name on the PC side is fine as long as the 8.3 name is what is asked for (`ROM.GB` is `"ROM     GB "`).
- **Colours** are plain RGB565 as passed (`0xf800` red, `0xffe0` yellow). The big-endian order applies to the image resources, not to these calls.
- **Message IDs `0x184`–`0x18c`** are used by Snake as private "redraw this part" flags between its own service, key and paint functions.
- **Time:** `0x0302288c` is a tick counter incremented by the SysTick handler (`0x40bdc`). The boot code calls the period setter with 10, so one tick is 10 ms. Snake does not use it; Snake's speed depends on how often the main loop calls `service()`.
- **Framebuffer:** drawing goes to RAM, not straight to the LCD. Rows 0–189 are at `0x03006688` and rows 190–239 at `0x0306fd50`, which is a zero-filled hole inside the resident code. Each row is 296 16-bit pixels with every pair of pixels swapped (pixel x is stored at index x XOR 1). `set_window` tracks the dirty row range at `0x03022e4c`; the flush to the LCD was not traced.
- **Orientation:** when `[0x03022e5c]` is non-zero the same calls address a 240×296 portrait screen. Snake assumes landscape (it clears 0–295 by 0–239).
- **Text needs hardware:** `draw_string` touches the clock gates at `0x40180000` and then storage, so it cannot run in the PC harness.

## Game & Watch emulator (`gw/`)

Built 2026-11-16. **Flashed and running on the device since 2026-11-17** (demo ROM only; no real game ROM tried yet). It emulates the Sharp SM510 microcontroller and runs an unmodified ROM dump. That covers the Game & Watch titles that MAME lists with an SM510 (for example Turtle Bridge, Fire Attack, Snoopy Tennis, and the New Wide Screen titles); the older SM5A titles and the later SM511/SM512 ones need a different core. No Nintendo ROM or artwork is included: you supply your own dump and, optionally, the matching MAME SVG.

| Path | What |
|---|---|
| `gw/src/sm510.c`, `sm510.h` | The CPU core, plain C, no dependencies. Behaviour follows MAME's `sm510` core (BSD-3-Clause), written independently. |
| `gw/src/ap30.c` | The device side: window structure, timing from the 10 ms tick, key mapping, segment drawing |
| `gw/tools/mkgame.py` | Converts ROM + SVG + key map into `build/game_data.c` |
| `gw/tools/demo_rom.py` | Writes a small original test ROM (pattern on row a, keys on row b, seconds counter on bs) |
| `gw/games/*.json` | Key maps. `demo.json` for the test ROM, `tbridge.json` for Turtle Bridge (wiring from MAME's driver) |
| `gw/build.py` | Does everything: data, compile, link, patch module 86, set the header date, pack |
| `gw/test/host_test.c` | Native tests of the CPU core |
| `gw/test/harness.py` | Runs a game module in Unicorn against the real resident code and checks the framebuffer |
| `gw/build/HIFIYF18.IMG` | Test image with the demo ROM, dated 2026-10-22, CRC `57342583`, SHA-256 `83a8f4d0a5ca2af089e8b7f99fc6c174d47450b17986dc7667ad84e504302a45`. Differs from stock only in module 86, its table entry, the header date and the CRC. |

Build and test:

```sh
cd gw
.venv/bin/python tools/demo_rom.py build/demo.rom
.venv/bin/python build.py --rom build/demo.rom --keys games/demo.json      # demo image
cc -Isrc -o build/host_test test/host_test.c src/sm510.c && build/host_test build/demo.rom
.venv/bin/python test/harness.py gw        # module against the real firmware code
.venv/bin/python test/harness.py snake     # stock Snake, as a check of the harness itself

# a real game: your own ROM dump and the MAME artwork for it
.venv/bin/python build.py --rom tl-28 --svg gnw_tbridge.svg --keys games/tbridge.json
```

Needs Homebrew `llvm` and `lld` (both installed) and `rsvg-convert` for artwork. `gw/.venv` has Unicorn and Pillow.

How it works:

- **Slot:** it replaces module 86 (stock game at code offset `0x91ed8`, the largest: code `0x35e8`, data `0xb8`, bss `0x808`). `build.py` refuses to build if code, data or bss is larger than the stock game's, so the module only ever uses memory the firmware already gives to a game. The demo build uses 6116 of 13800 code bytes, of which 2816 are the ROM; about 7.6 KB is left for artwork. That stock game is lost. It is almost certainly **Tank Battle**, the 6th entry under Game (see the task table note below).
- **Which menu entry:** a table in the resident data (code offset `0x5d410`, run address `0x03005884`) maps task numbers to module numbers; games start at task 14 = module 81 and continue in order (with module 109 listed twice and module 100 repeated near the end). The `menu` section lists the game names in the same order: Retro Block Puzzle, Snake, Box Pusher, Brick Breaker, Block Shooter, Tank Battle, Gomoku, Minesweeper, Maze, Sudoku, Make 24, Number Merge, ... Minesweeper (module 88, 8th), Make 24 (module 91, 11th) and Number Merge (module 92 "2048", 12th) line up by position, which puts module 86 at Tank Battle. Only the first two names are in the opposite order to their modules (81 is Snake, 82 is the block puzzle).
- **Data layout:** the ROM is stored packed (only the 704 valid bytes of each 1 KB block). Artwork is stored per LCD segment as runs of pixels and drawn with `set_window` + `put_pixel`. Only segments that changed are redrawn. `--scale 2` halves the artwork size if a game does not fit.
- **Without `--svg`** every segment is a box in a grid (rows a and b as 16×4, bs as 2×4), enough to see a ROM run.
- **Timing:** `service()` reads the tick counter and runs 163.84 CPU cycles per tick (16,384 per second). It never catches up more than 100 ms.
- **Keys:** the JSON maps AP30 keys to SM510 inputs: K bits on a strobe line (`{"s": 1, "k": 8}`), `"ba"`, `"b"` or `"acl"` (reset). Only one key at a time, as the hardware reports. A long press on Back leaves the game the same way Snake does.
- **Key test:** `build.py --keytest` builds a variant that shows the last raw key value instead of the game. Top row of boxes, line 1: one box per key bit 0–15, counted from the left starting at 0. Line 2: bits 24–27 in boxes 0–3. Line 3: the box whose number is the event type (1 down, 2 long, 3 repeat, 4 short release, 5 long release). `gw/build/keytest/HIFIYF18.IMG` is that build, dated 2026-10-23. It also shows the key ladder's raw ADC reading on the second row of boxes: line 1 is the live value in binary (box 0 = 1 ... box 9 = 512), line 3 the lowest value of the last press. The firmware keeps the latest ADC samples as a u16 array at `0x03005a8c` (getter at code offset `0x3ad62`); the key ladder is channel 1, at `0x03005a8e`. Reading it directly gives the key state at any moment, without the firmware's press/repeat/release events. Copied to the player on 2026-11-17; result pending.
- **Not done:** sound (the buzzer output is tracked in `cpu.r` but not played), multi-screen games (one SVG only), background artwork, SM5A/SM511 cores, saving.

What the tests cover, and what they do not:

- Native tests: 24 opcode-level checks, and the demo ROM over 20 emulated seconds including halt, wake-up and key input.
- Harness: the patched `code.bin` is loaded the way the module table describes it, and init, service, key, paint and deinit are called against the vendor's own drawing and message code. The framebuffer is compared pixel for pixel with the expected picture at five points. It also checks a forced full repaint, the exit request, that a long stall does not hang, that nothing outside the module's memory and the firmware's own globals changes, and that it works with bss pre-filled with garbage (the loader may not zero it). Stock Snake renders correctly in the same harness, which is the evidence that the harness models the firmware properly.
- **Not covered:** anything on real hardware. The CPU core has been tested with hand-written code only, not against a real game ROM or against MAME. The main-loop behaviour, the LCD flush, the key values and the 10 ms tick are static-analysis results.

First flash (your call; this breaks safety rule 1, "change resources only"):

- The module's code is only loaded when its game is opened, so a fault in it should not stop the player from booting. That is an inference from the overlay design, not something observed.
- If the game hangs there is no reset hole; the fallback is to let the battery run flat. Whether a long press on power still works during a hang is not known.
- Use the same procedure as test 4 (formatted internal storage, microSD out, full battery). The image is dated 2026-10-22, newer than both the installed build and the rollback image, so the rollback image must carry a later date: `build/rollback-1031/HIFIYF18.IMG` is stock content dated 2026-10-31 (whether the date matters at all is still untested).
- Check first that the other games and music still work, then find the replaced game in the Games menu. Expected with the demo ROM: grey-green screen, two full-width rows of boxes with every other box lit in the top one, and a counter in the small boxes at the bottom that goes up once a second. Left, Up, Play and Right each light one line of the second row. Long-press Back to leave.
- Things to report back: whether up/down/left/right match the corrected key table, whether the counter keeps real time, and whether the picture flickers.

## Game Boy emulator (`gw/gb/`)

Built 2026-11-17. **Flashed and running on the device the same day** (see the device result below). Core: Peanut-GB (MIT licence, `gw/third_party/peanut_gb/peanut_gb.h`, downloaded from GitHub), original Game Boy only, no sound.

| Path | What |
|---|---|
| `gw/gb/ap30_gb.c` | Device front-end: timing, direct framebuffer output, buttons from the key ladder |
| `gw/gb/libc/` | Three stub headers so the core compiles without a C library |
| `gw/gb/gb_host.c` | Native runner (serial output for test ROMs, screenshots) |
| `gw/build_gb.py` | Builds the module with one ROM inside, patches the firmware, renames the menu entry, packs |
| `gw/test/harness_gb.py` | Runs the module in Unicorn against the resident firmware and compares with the native core |
| `gw/third_party/gb-test-roms/` | Blargg's `cpu_instrs.gb` and `instr_timing.gb` (downloaded) |
| `build/gb/HIFIYF18.IMG` | Current build (see "Second device round" and "microSD card"). Dated 2026-10-27, CRC `c66fff10`, SHA-256 `3741235f287e4faf29d112eeae7f576762569715c9a38b4bb0f71c135c4224a9`. Not yet flashed; the device has the 2026-10-26 build. |
| `gw/build/gb/storage/` | Files to put in the root of the player's storage: `DRMARIO.GB`, `POKEMON.GB`, `POKEMON.SAV` (32 KB of `0xff`) |

```sh
cd gw
cc -O2 -w -o build/gb_host gb/gb_host.c
build/gb_host third_party/gb-test-roms/cpu_instrs.gb serial 3500        # "Passed all tests"
.venv/bin/python build_gb.py
.venv/bin/python test/harness_gb.py "../roms/gameboy/Dr. Mario (World).gb" DISK.img 300   # DISK.img: raw FAT32 image with the ROM as ROM.GB
```

### ROM from storage (built 2026-11-17)

The source no longer has a ROM built in. The first version of this opened a fixed `ROM.GB`; it was flashed (image dated 2026-10-25) and **worked on the device on 2026-11-17**: with Dr. Mario copied to internal storage as `ROM.GB`, the game started from the file (owner's report). That confirms `FileOpen`, `FileSeek` and `FileRead` on the device, that the current disk during a game is internal storage when no card is in, and that the RAM above the module's code (pool B) is usable. The ROM is read on demand:

- **Paging:** the ROM is read in 4 KB pages through a cache; the oldest page is replaced first. Cache memory is the module's bss (52 KB, shared with cartridge RAM) plus 28 KB of RAM above the module's code (`0x03084c00`–`0x0308bc00`, the space stock game 86's slot leaves below the audio code at `0x0308bf84`). That gives 20 pages for a cartridge without RAM and 12 with 32 KB of cartridge RAM.
- **Cartridge RAM** up to 32 KB is emulated in RAM and starts as `0xff`. **It is not saved**: leaving the game loses it.
- **Only Tank Battle is given up now**; the nine games the built-in ROM overwrote are back.
- **Screen colours on failure:** red = no `ROM.GB`, magenta = not a Game Boy ROM, yellow = more than 32 KB of cartridge RAM, blue = the core refused the ROM or hit an invalid instruction.
- **A third bar**, red, below the picture: ROM pages read from storage in the last second, 4 pixels each.
- **Harness results:** Dr. Mario from the disk image matches the native core after 301 frames with 8 page reads (the whole ROM). Pokémon Yellow (1 MB, MBC5, 32 KB RAM) matches after 600 frames with 48 page reads and reaches its title screen. No memory outside the module, pool B and the firmware's filesystem state changes.
- **Unknown until it runs on the device:** whether the file calls behave the same there, which disk is current, how long a page read takes, and whether the RAM above the code is really free (same reasoning as the data area, which did work).

### ROM picker and saves (built 2026-11-17, not yet flashed)

- **Picker:** at start the module lists the `.GB` and `.GBC` files in the root of the current disk (up to 32, hidden files skipped) by their 8.3 names. Up and Down move a green block cursor, A or Start starts the game. The button that chose the game is ignored until released. Names are drawn with the firmware's `draw_string`, wrapped in the same three state calls Snake uses; **the text has not been seen anywhere yet**, because the PC harness cannot run it. The cursor is drawn with `fill_rect` so the picker is usable even if the text fails.
- **Saves:** for a cartridge with RAM the module looks for the ROM's name with the extension `SAV`. If that file exists and is at least as large as the cartridge RAM it is loaded. It is rewritten in place two seconds after the game last wrote cartridge RAM, and again on exit if anything changed. The file is never created or resized by the player: **make it on the computer first**, at the cartridge RAM size (32,768 bytes for Pokémon Yellow). A blue square at the top right shows a write just happened; a white square means the cartridge has RAM but no usable save file.
- **Cache:** the first 16 KB of the ROM stays cached once loaded; other pages are replaced oldest first. Pool B is now `0x03085800`–`0x0308b800` (6 pages).
- **Size:** code is 14,644 bytes, more than module 86's slot, so it also uses module 87's file space (Gomoku, by position) and RAM up to `0x03085800`. Modules 86 and 87 both start the Game Boy.
- **Harness results:** the picker lists both ROMs from the test disk and each can be chosen with button readings. Dr. Mario matches the native core after 301 frames, Pokémon Yellow after 400. For Pokémon, a changed cartridge RAM was written to the disk after two quiet seconds and again on exit; macOS read the same save contents from the image afterwards, both ROM files were unchanged and `fsck_msdos` reported no errors. No memory outside the module, pool B and the firmware's filesystem state changed.
- **Device, Dr. Mario from `ROM.GB` (2026-11-17):** the red bar was visible only for an instant at start, as expected for a 32 KB ROM that fits the cache whole.
- **Page reads:** Pokémon's intro caused roughly one page read per frame in the harness with 11 cache pages. Whether that is fast enough on the device is unknown; the red bar shows it.

### Second device round (2026-11-17): picker build on the device, and the fixes

Owner's report on the 2026-10-26 build with six ROMs on internal storage:

| What | Observed |
|---|---|
| Picker | Works and shows the list, **but chose a game by itself after 2–3 seconds** |
| Tetris | green about 66%, yellow about 33% |
| Super Mario Land | green 100%, yellow 50%; holding a direction and pressing A does not work, so moving jumps are hard |
| Zelda | green about 66%, yellow about 33%, red bar on all the time |
| Pokémon | green 100%, yellow 50%, red bar on all the time |

Photos from the device: [Dr. Mario](images/dr-mario.jpg) (first Game Boy build, ROM built in; green bar full, yellow about 70%) and [Pokémon Red](images/pokemon-red.jpg) (2026-10-26 build, 1 MB MBC3 ROM paged from internal storage, at the starter selection; green bar about 60% of the picture width, yellow about 30%).

So text drawing from a game works, directory listing works, and games with mappers and cartridge RAM run. Saving was not reported on. What was changed in response (build dated 2026-10-27, tested on the PC only):

- **Picker self-selection.** That build read the key ladder directly, and something made it see A or Start with no button pressed; the cause is not known (one guess: the idle level sags into A's range, 850–949, when the backlight dims). The picker now uses the firmware's own key events, as the stock menus do: Up/Down on press and repeat, and a short press of A or Start to start. In games, A's ladder window is narrowed to 810–899 (measured 855) to keep away from the idle level.
- **Cache.** A simulation on the real games (`gw/build/cachesim.c`) showed the 4 KB oldest-first cache was the problem: Zelda needed 7.6 page reads per frame with 44 KB of cache. With 1 KB pages and least-recently-used replacement the same memory needs 0.01. The module now uses that; in the harness Zelda reads 45 pages in 300 frames.
- **Speed.** The core is compiled at `-O2` (about 12% fewer instructions per frame than `-Os`). Up to four frames are emulated per main-loop pass with only the last drawn, so a slow pass costs smoothness before game speed. The meters are redrawn once a second, not on every frame. Tetris and Zelda cost about 2.4 million ARM instructions per frame in the harness against 1.3 for Dr. Mario (they do not idle between frames), which fits the device being short of full speed for them.
- **Sticky left/right.** Starting a game with B in the picker turns it on: tapping Left or Right keeps it held until the same direction is tapped again or the other one is tapped. With the d-pad released the ladder can see A and B, so running jumps work. A or Start starts a game with normal buttons.
- **Diagnostics on the picker's bottom line**, refreshed once a second, in hex: the key ladder reading, then four words of the firmware's clock bookkeeping at `0x030065c0` (offsets `0x08`, `0x60`, `0x64`, `0x68`). The clock-setting code was looked for and not found; peripheral clock dividers are at code offsets `0x2be08`–`0x2c33c` and use that structure. Whether the firmware runs games at a reduced CPU clock is an open question these numbers should answer.
- **Size.** Code is 18,748 bytes, so pool B now starts at `0x03086000` (22 KB) and module 88's file space is used as well. Modules 86, 87 and 88 all start the Game Boy (Tank Battle, Gomoku and Minesweeper by position).
- **Reference setting.** The native reference build must use `PEANUT_GB_HIGH_LCD_ACCURACY 0` like the device build; with the default of 1 Zelda differs by 5 pixels (sprite ordering). The earlier matches were unaffected.
- **Harness results for this build:** picker ignores a raw ladder value in A's range, moves on Down events and starts on A's release; Dr. Mario, Zelda and Pokémon Yellow match the native core (301, 301 and 400 frames); autosave and save on exit pass for Zelda (8 KB) and Pokémon (32 KB); no stray writes. Sticky left/right is not covered by a test.

### microSD card (2026-11-17)

Owner's report on the 2026-10-26 build: with a microSD card inserted, opening the Game Boy gives a solid red screen; with the card removed it works. Photo of the picker on the device: [rom-picker.jpg](images/rom-picker.jpg), which also confirms that `draw_string` works from a game.

- **Cause.** Red means the picker found no ROMs. When a card is present the firmware makes it the current disk: the card-detect code at code offset `0x3cfb8` reads a GPIO (port 0, pin 11), stores 4 in the settings bytes `+0x0e`/`+0x0f` and calls `FileSysSetup(4)`. The file calls then act on the card, where there are no ROMs, and the module's directory listing reads raw FAT entries, which would not work on an exFAT card in any case.
- **How the firmware switches disks.** Its own code does `settings[+0x0e] = disk; FileSysSetup(disk)` (for example at `0x2e3ea` and `0x2e41c`). The current disk number is the byte at `0x0307e711`.
- **Fix.** On start the module remembers the current disk and, if it is not 2, calls `FileSysSetup(2)`; on exit it calls `FileSysSetup` with the remembered number. It does not touch the settings byte. ROMs and saves therefore always come from internal storage.
- **Harness.** A second disk image stands in for the card (the `MDRead`/`MDWrite` stubs pick the image by device ID; card detect and the card driver's capacity, status and probe entries are stubbed). With the card mounted as current, the module finds the ROMs on internal storage, runs, and after exit the firmware's directory listing shows the card's file again.
- **Not known:** whether anything in the firmware keeps reading the card while a game runs (music playing from the card, for instance). If so it would read internal storage during the game.

### The older firmware, `HIFIYF05.IMG` (2026-08-19)

Compared with v1.7.8 on 2026-11-17 to see whether one build could serve both. It cannot as it stands, but the two are close enough that a port is mostly bookkeeping.

| | v1.7.8 (`HIFIYF18`) | older (`HIFIYF05`) |
|---|---|---|
| Modules | 113 | 93 |
| Resident code | offset `0x2988c`, length `0x2e300` | offset `0x2960c`, length `0x2de88` |
| Games | 28 modules with a score string, run address `0x030815c4`, data `0x03023b48`, largest `0x35e8` | 10, run address `0x0308114c`, data `0x03023a98`, largest `0x1080` |
| Snake | module 81 | module 81 |
| LCD state structure | `0x03022e48` | `0x03022d98` |

- **Same functions, different addresses.** Of the 20 firmware functions the modules use, 18 were found in the older image by searching for their first 40 bytes (exactly, or with branch targets masked). They sit 0x280 to 0x678 bytes lower, and the shift is not constant, so a single offset will not do. `task_switch` and `FileSysSetup` were not found by this search and need a look by hand.
- **RAM variables moved too** (the LCD structure is 0xb0 lower), so every absolute address in the front-ends would need a per-version value.
- **Slots are smaller.** The largest old game is 4 KB, so the Game Boy module would have to span more of them.
- **Tooling added the same day.** `fw/1.7.8.json` is now the single place for the Game Boy module's firmware addresses, and `tools/findaddrs.py` drafts such a table for another image from byte signatures of the v1.7.8 functions (`tools/fw_signatures.json`: the first 64 bytes of each function with branch targets and pc-relative offsets masked, plus where each variable's address is loaded). On v1.7.8 it reproduces the table exactly. On this older image it finds 24 of 25 functions and all 9 variables; only `task_switch` is missing, and it proposes module 92 as the slot. The build refuses a draft until it is marked verified. Nothing has been built or run for the older image.
- **What a port needs:** a per-version address table (most of it can be generated by the signature search), the game run and data addresses from the module table, and a new choice of slots. Nothing version-specific was found in how windows, drawing or files work.

How the first (built-in ROM) build was put into the firmware:

- **Code** (12,264 bytes at `-Os`; 13,112 with file loading) replaces module 86's code and stays within that game's own 13,800 bytes.
- **The ROM is the module's initialised data** (32 KB), so the firmware's loader copies it to RAM with the module. In the file it occupies the space of modules 87–95. Those nine table entries are set equal to entry 86, so all ten menu entries start the Game Boy and none points at overwritten code. Games given up: Tank Battle and the nine that follow it in the list (Gomoku through Pair Link, by position).
- **Menu name:** `menu.bin` starts with a u16 language count (21) and a u32 offset per language block; every block has the same layout, with one record per string (8 bytes of `0xff`, then UTF-16). The Tank Battle record is at block offset `0x129d6` and is rewritten to "Game Boy" in all 21 blocks.
- **RAM:** data and bss use `0x03023b48`–`0x0302fd98` (about 50 KB). The stock games stop at `0x030250fc`, so **this goes beyond what a stock game uses.** The module table shows what else lives there: the thumbnail task (module 18, data from `0x030250fc`) and modules 19/20 (data from `0x030264f4`, unidentified, probably picture decoders). Module 18's code range overlaps stock game 86's code, so it cannot be loaded while that game runs; modules 19/20 not being active during a game is an assumption. The audio player's data starts at `0x030360e8` and is not touched; `build_gb.py` refuses to build past it.

How it runs:

- **Display:** 160×144 scaled 1.5× to 240×216, centred. Lines are written straight into the firmware framebuffer, then `paint()` calls `set_window` and one `put_pixel` so the firmware marks the area changed. If the firmware reports a rotated screen or a non-zero buffer index, nothing is drawn.
- **Timing:** 0.5973 frames per 10 ms tick, at most two frames per main-loop pass, only the last one drawn. If the CPU is too slow the game slows down; the player's menus stay responsive.
- **Speed meter:** two thin bars above the picture, 4 pixels per frame per second. Green = frames emulated, yellow = frames drawn. Full width (240 pixels) = 60.
- **Buttons:** read from the key ladder ADC directly, with the firmware's own ranges, accepted after two equal samples. Because a direction hides A and B, a direction stays held for 120 ms after release, and for as long as A or B is held if one is pressed within that time. Long press on Select leaves (the firmware's Back).
- **Not done:** sound, cartridges with RAM or saves (mapper ROMs load but their RAM reads as `0xff`), ROMs from storage, Game Boy Color.

Tests:

- Native: Blargg `cpu_instrs` passes all 11 tests and `instr_timing` passes. Dr. Mario runs to gameplay.
- Harness: after 301 frames the module's framebuffer matches the native core pixel for pixel through an independently written copy of the scaling, with bss pre-zeroed and pre-filled with garbage. Nothing outside the picture area changes, no memory outside the module changes, the exit works, and Start presses delivered as ladder values get from the title into the game.
- **Device result (2026-11-17, owner's photo and report):** the update applied after a fresh format, Dr. Mario starts from the Game menu and is "very playable". In the photo, in gameplay, the green bar spans the full picture width, so the core emulates all 60 frames per second; the yellow bar reaches about 70% of the width, so roughly 40 screen redraws per second. The picture is centred, with correct shades and no visible tearing. This also shows that the direct framebuffer writes, the dirty marking in `paint()`, the ADC button reading and the 50 KB of RAM beyond a stock game's all work on the device. Not yet reported: whether the menu name changed, and whether music and menus behave normally after leaving the game.
- **Speed before the device test was the open question.** The harness counts roughly 1.5 million ARM instructions per emulated frame (an estimate from basic-block sizes), about 90 million per second for full speed. The player's CPU clock is not known, so it may run slow. The speed meter will show it.

## Useful string locations (code offsets of the referencing `adr` instruction)

| Code offset | String |
|---|---|
| `0x2d63a` | `Reboot, addr = 0x%x, flag = %d` (Service.c) |
| `0x5f0a0` – `0x5f0ec` | `FW2Valid`, `No find fw2!`, `fw1 && fw2 error!`, `fw2 error!` |
| `0x82a12` / `0x82a42` | `Firmware Upgrade...` / `System Reboot...` |
| `0x83118` | `MSG_SYS_FW_RECOVERY Reboot...` |
| `0x83136` | `### FwUpdate SUCCESS,REBOOT... ####` |
| `0x83c2e` | Start of the function that logs `FwUpdate Enter` (FwUpdate.c) |
| `0x83d4e` / `0x840d4` | `Fw2 Update Start` / `Fw2 Update End` |
| `0x8413e` | `FwUpdate Exit` |

Other string anchors (file offsets): `NanoCRebootFlag` `0x5e46c`, `HIFIYF00IMG` `0x5bf21` and `0x5f5f0`, `ECHOMINIIMG` `0x5f5fc`, `gSysConfig.crc` `0x47108`, `crcval = %d, pconfig->crc` `0x5ee5c`.

## Open questions

1. **Brick recovery.** The AP30 has no reset pinhole. Is RKnanoD mask-ROM USB mode reachable another way (key combination from a full power-off, a test pad, a vendor tool)? This is the most important open item.
2. **Why tests 1–3 only flashed briefly** and test 4 worked: formatting, the microSD card, or something else. Filming the screen would help.
3. **Is the date bump needed?** Try a stock-dated modified image on freshly formatted storage. Also: does the updater skip an image that is older than the installed one (relevant for going back to plain stock)?
4. **File name matching:** does the AP30 accept any `HIFIYFnn.IMG` like the Echo Mini's `HIFIECnn.IMG`?
5. **Update write order:** the slot copy is power-loss safe (see [Dual-slot recovery](#dual-slot-recovery-static-analysis-only)); the write of the new image into `fw2` was not traced in full.
6. **Bootloader fallback:** whether the bootloader starts `fw2` when `fw1` cannot boot.
7. What posts `MSG_SYS_FW_RECOVERY`, and what the loader does with the `NanoCRebootFlag` marker and the `0x5002004c` register write.
8. The formats of `font0`, `font1`, `charmap` and `menu`. Flame Ocean replaces Echo Mini fonts, so its code is a likely reference.
9. The board hardware (exact DAC part, Bluetooth module, LCD controller).
10. A cross-reference pass that maps branch targets through the module table.
11. ~~What the resident functions called by the games do.~~ Answered for drawing, keys, messages and time; see [Game module API](#game-module-api-static-analysis-plus-pc-emulation). Still open: text drawing arguments, sound, and file access from a game.
12. Does the Game & Watch module run on the device? See the first-flash checklist under [Game & Watch emulator](#game--watch-emulator-gw).

## Related projects (same SoC)

- ReChord, a from-source CFW for the Echo Mini with a debrick guide: https://github.com/brnomt/ReChord
- Echo Mini reverse-engineering write-up (fonts, resources, Flame Ocean): https://im.not.ci/echo-mini-rse/
- Flame Ocean, web firmware editor: https://github.com/losses/flame-ocean-website
- Echo-Mini-Customizer, a theme editor: https://github.com/BlackVllad/Echo-Mini-Customizer
- Echo-Mini-Themes, prebuilt theme images: https://github.com/Pernoshend/Echo-Mini-Themes
- HiFiOasis entry listing HIFIYF18 as v1.7.8: https://www.hifioasis.com/?p=13957
