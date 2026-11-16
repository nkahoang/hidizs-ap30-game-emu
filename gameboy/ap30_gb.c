/* Game Boy front-end for the Hidizs AP30 (firmware HIFIYF18, v1.7.8).
 * Core: Peanut-GB (MIT). What the firmware functions do is described in
 * docs/FINDINGS.md, "Game module API". */
#include <stdint.h>
#include <stddef.h>

#define ENABLE_SOUND 0
#define ENABLE_LCD 1
#define PEANUT_GB_12_COLOUR 0
#define PEANUT_GB_HIGH_LCD_ACCURACY 0
#include "../third_party/peanut_gb/peanut_gb.h"

/* ---- firmware ----
 * Addresses come from build/gb/fw_addrs.h, which gameboy/build.py writes
 * from the table for the firmware being patched (fw/<version>.json). */
#include "fw_addrs.h"
#define FW(addr, ret, args) ((ret (*) args)((addr) | 1))
#define fw_set_window FW(FWA_set_window, void, (unsigned x0, unsigned y0, unsigned x1, unsigned y1))
#define fw_put_pixel  FW(FWA_put_pixel, void, (unsigned rgb565))
#define fw_fill_rect  FW(FWA_fill_rect, void, (int x0, int y0, int x1, int y1))
#define fw_msg_send   FW(FWA_msg_send, void, (unsigned id))
#define fw_msg_take   FW(FWA_msg_take, int, (unsigned id))
#define fw_get_key    FW(FWA_get_key, unsigned, (void))
#define fw_task_switch FW(FWA_task_switch, void, (unsigned task, void *arg))
#define fw_idle_reset FW(FWA_idle_reset, void, (void))
#define fw_game_enter FW(FWA_game_enter, void, (void))
#define fw_game_leave FW(FWA_game_leave, void, (void))
#define fw_enter2     FW(FWA_enter2, void, (void))
/* files on the current disk; names are 11-character 8.3, space padded */
#define fw_file_open  FW(FWA_file_open, int, (const char *path, const char *name11, const char *mode))
#define fw_file_read  FW(FWA_file_read, unsigned, (void *buf, unsigned size, int handle))
#define fw_file_seek  FW(FWA_file_seek, int, (unsigned offset, unsigned whence, int handle))
#define fw_file_close FW(FWA_file_close, int, (int handle))
#define fw_file_create FW(FWA_file_create, int, (const char *path, const char *name11))   /* -1 if it exists */
#define fw_file_write FW(FWA_file_write, unsigned, (const void *buf, unsigned offset512, unsigned size, int handle))
#define fw_dir_entry  FW(FWA_dir_entry, int, (uint8_t *out32, unsigned dir_cluster, unsigned index))
/* text, used the way the stock Snake uses it */
#define fw_draw_string FW(FWA_draw_string, void, (int x, int y, const uint16_t *utf16))
#define fw_text_font  FW(FWA_text_font, unsigned, (unsigned))
#define fw_text_mode  FW(FWA_text_mode, unsigned, (unsigned))
#define fw_text_lang  FW(FWA_text_lang, unsigned, (unsigned))
#define FW_ROOT_CLUSTER ((const volatile uint8_t *)(FWA_fs_state + 0x0d))   /* u32, unaligned */
/* Which storage the firmware's file calls act on: 2 = internal, 4 = microSD.
 * With a card inserted the firmware makes the card current. */
#define fw_fs_setup   FW(FWA_fs_setup, int, (unsigned disk))
#define FW_CUR_DISK   (*(volatile uint8_t *)(FWA_fs_disk + 1))
#define DISK_INTERNAL 2

#define FW_COLOUR  (*(volatile uint16_t *)FWA_colour)
#define FW_TICKS   (*(volatile uint32_t *)FWA_ticks)  /* 10 ms */
#define FW_KEY_ADC (*(volatile uint16_t *)(FWA_adc + 2))  /* key ladder, 10 bits */
#define FW_FB_INDEX (*(volatile uint16_t *)FWA_lcd_state)
#define FW_ROTATED  (*(volatile uint32_t *)(FWA_lcd_state + 0x14))
#define FB_A ((uint16_t *)FWA_fb_a)   /* rows 0-189 */
#define FB_B ((uint16_t *)FWA_fb_b)   /* rows 190-239 */
#define FB_SPLIT 190
#define LCD_W 296

#define MSG_UPDATE 0x189
#define MSG_FULL   0x18c
#define TASK_MAINMENU 10

/* Picture: 160x144 scaled 1.5x to 240x216, centred. */
#define OUT_W 240
#define OUT_H 216
#define XOFF 28          /* must be even: the framebuffer swaps pixel pairs */
#define YOFF 12

/* The ROM stays in its file and is read in 1 KB pages through a cache that
 * replaces the least recently used page (chosen by simulation on real games:
 * with the same memory, 4 KB pages needed up to 7 reads per frame in Zelda,
 * 1 KB pages almost none).
 * Cache memory comes from two places: the module's own bss (pool A, shared
 * with cartridge RAM) and the RAM above the module's code that the stock
 * game slot leaves unused (pool B). */
#define PAGE_SHIFT 10
#define PAGE_SIZE (1u << PAGE_SHIFT)
#define MAX_PAGES 4096                      /* 4 MB ROM */
#define POOL_A_SIZE (48 * 1024)
#define POOL_B_ADDR FWA_pool_b              /* the build keeps the code below this */
#define POOL_B_END FWA_pool_b_end           /* just below the audio player's code */
#define POOL_B ((uint8_t *)POOL_B_ADDR)
#define POOL_B_PAGES ((POOL_B_END - POOL_B_ADDR) / PAGE_SIZE)
#define MAX_SLOTS (POOL_A_SIZE / PAGE_SIZE + POOL_B_PAGES)
#define NO_SLOT 0xff

static uint8_t pool_a[POOL_A_SIZE];
static uint8_t page_slot[MAX_PAGES];        /* ROM page -> cache slot */
static uint16_t slot_page[MAX_SLOTS];       /* cache slot -> ROM page */
static uint8_t *slot_mem[MAX_SLOTS];
static uint32_t slot_used[MAX_SLOTS];       /* when each slot was last switched to */
static uint32_t use_clock;
static uint8_t *cur_mem;                    /* page of the last read */
static uint32_t cur_page;
static uint8_t n_slots;
static uint8_t *cart_ram;
static uint32_t cart_ram_mask, rom_pages;
static int rom_file;
uint32_t gb_misses;                         /* page reads since start */
static uint8_t miss_sec, shown_miss;

/* ROM picker */
#define MAX_ROMS 32
#define LIST_ROWS 9
#define LIST_X 40
#define LIST_Y 36
#define ROW_H 20
static uint8_t rom_names[MAX_ROMS][11];     /* 8.3 names as stored on disk */
uint8_t gb_running, gb_n_roms, gb_sel;      /* (not static: the PC harness reads them) */
static uint8_t list_top, wait_release, status_due;
static uint8_t orig_disk;                   /* disk to give back to the firmware on exit */
uint8_t gb_sticky;                          /* left/right stay held until tapped again */
static uint8_t h_latch, pad_prev;

/* cartridge RAM saved to NAME.SAV; created empty the first time a game runs */
static char rom_name[12], sav_name[12];
static uint32_t cart_ram_size;
uint8_t gb_save_ok, gb_sram_dirty;
static uint8_t saved_flash;
static uint32_t sram_tick;

static struct gb_s gb;
static uint32_t last_tick, frame_acc, sec_tick;
static uint16_t pal[4];
static uint8_t dead, dirty, can_draw;
static uint8_t latch, combo, grace;
uint32_t gb_frames;                 /* frames emulated since start */
static uint8_t fps_emu, fps_drawn, shown_emu, shown_drawn;

void *memset(void *d, int c, size_t n) { uint8_t *p = d; while (n--) *p++ = c; return d; }
void *memcpy(void *d, const void *s, size_t n) { uint8_t *p = d; const uint8_t *q = s; while (n--) *p++ = *q++; return d; }
void __aeabi_memclr(void *d, size_t n) { memset(d, 0, n); }
void __aeabi_memclr4(void *d, size_t n) { memset(d, 0, n); }
void __aeabi_memclr8(void *d, size_t n) { memset(d, 0, n); }
void __aeabi_memcpy(void *d, const void *s, size_t n) { memcpy(d, s, n); }
void __aeabi_memcpy4(void *d, const void *s, size_t n) { memcpy(d, s, n); }
void __aeabi_memcpy8(void *d, const void *s, size_t n) { memcpy(d, s, n); }

static unsigned ladder(unsigned adc);
static void on_error(struct gb_s *g, const enum gb_error_e e, const uint16_t a);
static void draw_line(struct gb_s *g, const uint8_t *px, const uint_fast8_t line);
static uint8_t key_prev, key_now;

static uint8_t *load_page(unsigned page)
{
    unsigned slot = 0, i, got;
    uint32_t oldest = 0xffffffff;
    uint8_t *mem;

    for (i = 0; i < n_slots; i++)
        if (slot_used[i] < oldest) {
            oldest = slot_used[i];
            slot = i;
        }
    mem = slot_mem[slot];
    if (slot_page[slot] != 0xffff)
        page_slot[slot_page[slot]] = NO_SLOT;
    fw_file_seek(page << PAGE_SHIFT, 0, rom_file);
    got = fw_file_read(mem, PAGE_SIZE, rom_file);
    if (got < PAGE_SIZE)
        memset(mem + got, 0xff, PAGE_SIZE - got);
    slot_page[slot] = page;
    page_slot[page] = slot;
    gb_misses++;
    miss_sec++;
    return mem;
}

static uint8_t rom_read(struct gb_s *g, const uint_fast32_t a)
{
    unsigned page = (a >> PAGE_SHIFT) & (rom_pages - 1), slot;
    (void)g;

    if (page != cur_page) {         /* most reads stay on the same page */
        slot = page_slot[page];
        cur_mem = slot != NO_SLOT ? slot_mem[slot] : load_page(page);
        cur_page = page;
        slot_used[page_slot[page]] = ++use_clock;
    }
    return cur_mem[a & (PAGE_SIZE - 1)];
}

static uint8_t ram_read(struct gb_s *g, const uint_fast32_t a) { (void)g; return cart_ram ? cart_ram[a & cart_ram_mask] : 0xff; }
static void ram_write(struct gb_s *g, const uint_fast32_t a, const uint8_t v)
{
    (void)g;
    if (cart_ram) {
        cart_ram[a & cart_ram_mask] = v;
        gb_sram_dirty = 1;
        sram_tick = FW_TICKS;
    }
}

/* Rewrites the save file in place. Nothing is created or resized. */
static void flush_save(void)
{
    int h;

    if (!gb_save_ok || !gb_sram_dirty)
        return;
    gb_sram_dirty = 0;
    h = fw_file_open("\\", sav_name, "W");
    if (h < 0)
        return;
    fw_file_write(cart_ram, 0, cart_ram_size, h);
    fw_file_close(h);
    saved_flash = 2;
}

/* Lists the .GB and .GBC files in the root of the current disk. */
static void scan_roms(void)
{
    const volatile uint8_t *rc = FW_ROOT_CLUSTER;
    unsigned root = rc[0] | rc[1] << 8 | rc[2] << 16 | (unsigned)rc[3] << 24, i;
    uint8_t e[32];

    gb_n_roms = 0;
    for (i = 0; i < 512 && gb_n_roms < MAX_ROMS; i++) {
        if (fw_dir_entry(e, root, i) || !e[0])
            break;
        /* skip deleted entries, long-name parts, folders, labels, hidden files */
        if (e[0] == 0xe5 || e[11] == 0x0f || (e[11] & 0x1a))
            continue;
        if (e[8] == 'G' && e[9] == 'B' && (e[10] == ' ' || e[10] == 'C'))
            memcpy(rom_names[gb_n_roms++], e, 11);
    }
}


/* Opens ROM.GB in the root of the current disk and sets up the cache.
 * Returns 0, or an error number shown as a screen colour. */
static int open_rom(const uint8_t *name)
{
    static const uint8_t ram_kb[6] = { 0, 2, 8, 32, 128, 64 };
    uint8_t hdr[0x150];
    unsigned i, ram, a_pages;

    memcpy(rom_name, name, 11);
    memcpy(sav_name, name, 8);
    memcpy(sav_name + 8, "SAV", 3);
    rom_name[11] = sav_name[11] = 0;
    rom_file = fw_file_open("\\", rom_name, "R");
    if (rom_file < 0)
        return 1;                                   /* cannot open it */
    if (fw_file_read(hdr, sizeof hdr, rom_file) != sizeof hdr || hdr[0x148] > 7)
        return 2;                                   /* not a Game Boy ROM */
    rom_pages = (0x8000u << hdr[0x148]) >> PAGE_SHIFT;
    ram = hdr[0x149] < 6 ? ram_kb[hdr[0x149]] * 1024u : 0;
    if (ram > 32 * 1024)
        return 3;                                   /* too much cartridge RAM */
    cart_ram = ram ? pool_a : NULL;
    cart_ram_mask = ram - 1;
    memset(pool_a, 0xff, ram);
    a_pages = (POOL_A_SIZE - ram) / PAGE_SIZE;
    n_slots = 0;
    for (i = 0; i < a_pages; i++)
        slot_mem[n_slots++] = pool_a + ram + i * PAGE_SIZE;
    for (i = 0; i < POOL_B_PAGES; i++)
        slot_mem[n_slots++] = POOL_B + i * PAGE_SIZE;
    for (i = 0; i < n_slots; i++) {
        slot_page[i] = 0xffff;
        slot_used[i] = 0;
    }
    memset(page_slot, NO_SLOT, sizeof page_slot);
    use_clock = 0;
    cur_page = 0xffffffff;

    cart_ram_size = ram;
    gb_save_ok = gb_sram_dirty = 0;
    if (ram) {
        int h = fw_file_open("\\", sav_name, "R");
        if (h >= 0) {
            if (fw_file_read(cart_ram, ram, h) == ram)
                gb_save_ok = 1;
            else
                memset(cart_ram, 0xff, ram);    /* too short: not ours, leave it alone */
            fw_file_close(h);
        } else if ((h = fw_file_create("\\", sav_name)) >= 0) {
            /* no save yet: make an empty one at full size, so that every
             * later write only replaces data in place */
            gb_save_ok = fw_file_write(cart_ram, 0, ram, h) == ram;
            fw_file_close(h);
        }
    }
    return 0;
}

static void start_rom(unsigned n)
{
    memset(&gb, 0, sizeof gb);
    dead = open_rom(rom_names[n]);
    if (!dead && gb_init(&gb, rom_read, ram_read, ram_write, on_error, NULL) != GB_INIT_NO_ERROR)
        dead = 4;
    if (!dead)
        gb_init_lcd(&gb, draw_line);
    frame_acc = 0;
    last_tick = sec_tick = FW_TICKS;
    h_latch = pad_prev = 0;
    status_due = 1;
    wait_release = 1;       /* the press that chose the game is not passed on */
    gb_running = 1;
    fw_msg_send(MSG_FULL);
}

static unsigned debounced_key(void)
{
    unsigned k = ladder(FW_KEY_ADC);
    if (k == key_prev)
        key_now = k;
    key_prev = k;
    return key_now;
}

/* The picker uses the firmware's own key events (as the stock menus do),
 * not the raw ladder reading: the first picker build read the ladder and
 * chose a game by itself after a few seconds. */
static void pick_key(unsigned v)
{
    unsigned type = v >> 28, key = v & 0x1ff;

    if ((type == 1 || type == 3) && (key & 0x030)) {
        if ((key & 0x020) && gb_sel + 1 < gb_n_roms)
            gb_sel++;
        else if ((key & 0x010) && gb_sel)
            gb_sel--;
        if (gb_sel < list_top || gb_sel >= list_top + LIST_ROWS) {
            list_top = gb_sel < list_top ? gb_sel : gb_sel - LIST_ROWS + 1;
            fw_msg_send(MSG_FULL);
        }
        fw_msg_send(MSG_UPDATE);
    } else if (type == 4 && (key & 0x1c0)) {   /* short press of A, B or Start */
        gb_sticky = (key & 0x040) != 0;        /* B: sticky left/right */
        start_rom(gb_sel);
    }
}

static void pick_paint(int full)
{
    unsigned i;

    if (full) {
        static const uint16_t title[] = { 'G','A','M','E',' ','B','O','Y',0 };
        unsigned font = fw_text_font(2), mode = fw_text_mode(1), lang = fw_text_lang(2);

        FW_COLOUR = 0;
        fw_fill_rect(0, 0, 295, 239);
        FW_COLOUR = 0xffe0;
        fw_draw_string(LIST_X, 8, title);
        FW_COLOUR = 0xffff;
        for (i = 0; i < LIST_ROWS && list_top + i < gb_n_roms; i++) {
            const uint8_t *n = rom_names[list_top + i];
            uint16_t t[13];
            unsigned j, k = 0;
            for (j = 0; j < 8 && n[j] != ' '; j++)
                t[k++] = n[j];
            t[k++] = '.';
            for (j = 8; j < 11 && n[j] != ' '; j++)
                t[k++] = n[j];
            t[k] = 0;
            fw_draw_string(LIST_X, LIST_Y + i * ROW_H, t);
        }
        {
            static const uint16_t hint[] = { 'A',':','P','L','A','Y',' ',' ','B',':','S','T','I','C','K','Y',' ','L','/','R',0 };
            FW_COLOUR = 0x07ff;
            fw_draw_string(120, 8, hint);
        }
        fw_text_lang(lang & 0xff);
        fw_text_mode(mode);
        fw_text_font(font);
        status_due = 1;
    }
    if (status_due) {
        /* diagnostics: key ladder reading and four words of the firmware's
         * clock bookkeeping (0x030065c0 + 8, 0x60, 0x64, 0x68), in hex */
        static const uint8_t off[4] = { 0x08, 0x60, 0x64, 0x68 };
        uint16_t t[44];
        unsigned k = 0, w, j, font = fw_text_font(2), mode = fw_text_mode(1), lang = fw_text_lang(2);
        uint32_t v = FW_KEY_ADC;
        status_due = 0;
        for (w = 0; w < 5; w++) {
            for (j = w ? 8 : 3; j--; )
                t[k++] = "0123456789ABCDEF"[v >> (j * 4) & 15];
            t[k++] = ' ';
            if (w < 4)
                v = *(volatile uint32_t *)(FWA_clocks + off[w]);
        }
        t[k] = 0;
        FW_COLOUR = 0;
        fw_fill_rect(0, 220, 295, 239);
        FW_COLOUR = 0x8410;
        fw_draw_string(2, 222, t);
        fw_text_lang(lang & 0xff);
        fw_text_mode(mode);
        fw_text_font(font);
    }
    /* the cursor is a plain block, so it shows even if text does not */
    FW_COLOUR = 0;
    fw_fill_rect(16, LIST_Y, 31, LIST_Y + LIST_ROWS * ROW_H - 1);
    FW_COLOUR = 0x07e0;
    i = LIST_Y + (gb_sel - list_top) * ROW_H;
    fw_fill_rect(18, i + 4, 29, i + 13);
}
static void on_error(struct gb_s *g, const enum gb_error_e e, const uint16_t a) { (void)g; (void)e; (void)a; dead = 4; }

static uint16_t *fb_row(unsigned y)
{
    return (y < FB_SPLIT ? FB_A + y * LCD_W : FB_B + (y - FB_SPLIT) * LCD_W) + XOFF;
}

/* Called by the core for each visible line. Writes straight into the
 * firmware's framebuffer: pixel x lives at index x ^ 1. */
static void draw_line(struct gb_s *g, const uint8_t *px, const uint_fast8_t line)
{
    unsigned y = YOFF + line * 3 / 2, i;
    uint16_t *row = fb_row(y);
    (void)g;

    for (i = 0; i < 80; i++) {
        uint16_t a = pal[px[2 * i] & 3], b = pal[px[2 * i + 1] & 3];
        unsigned x = 3 * i;
        row[x ^ 1] = a;
        row[(x + 1) ^ 1] = (i & 1) ? b : a;
        row[(x + 2) ^ 1] = b;
    }
    if (line & 1)   /* odd lines are two rows tall */
        memcpy(fb_row(y + 1), row, OUT_W * 2);
}

/* The buttons share one resistor ladder, so only one is ever visible and a
 * direction hides A and B. To allow "move and jump", a direction stays held
 * for a moment after release, and for as long as A or B is then held. */
#define K_DIRS (JOYPAD_RIGHT | JOYPAD_LEFT | JOYPAD_UP | JOYPAD_DOWN)
#define GRACE_TICKS 12

static unsigned ladder(unsigned adc)
{
    if (adc < 70)  return JOYPAD_RIGHT;
    if (adc < 100) return 0;
    if (adc < 184) return JOYPAD_UP;
    if (adc < 200) return 0;
    if (adc < 310) return JOYPAD_LEFT;
    if (adc < 320) return 0;
    if (adc < 430) return JOYPAD_DOWN;
    if (adc < 442) return 0;
    if (adc < 560) return JOYPAD_SELECT;
    if (adc < 680) return JOYPAD_START;
    if (adc < 700) return 0;
    if (adc < 810) return JOYPAD_B;     /* measured 733 */
    if (adc < 900) return JOYPAD_A;     /* measured 855; idle is 1023 */
    return 0;
}

static unsigned read_pad(unsigned dt)
{
    unsigned k = debounced_key(), out;   /* accepted once two samples agree */

    if (wait_release) {
        if (k)
            return 0;
        wait_release = 0;
    }
    if (gb_sticky) {
        /* Tap left or right to start moving, tap the same again to stop.
         * With the d-pad released, A and B are visible to the ladder. */
        unsigned h = k & (JOYPAD_LEFT | JOYPAD_RIGHT);
        if (h && h != pad_prev)
            h_latch = h_latch == h ? 0 : h;
        pad_prev = h;
        return (k & ~(JOYPAD_LEFT | JOYPAD_RIGHT)) | h_latch;
    }

    if (k & K_DIRS) {
        latch = k; grace = GRACE_TICKS; combo = 0;
        out = k;
    } else if (k & (JOYPAD_A | JOYPAD_B)) {
        if (grace)
            combo = 1;
        out = k | (combo ? latch : 0);
    } else {
        out = k;
        if (combo) {
            combo = 0; grace = 0; latch = 0;
        } else if (grace) {
            grace = grace > dt ? grace - dt : 0;
            if (grace)
                out |= latch;
            else
                latch = 0;
        }
    }
    return out;
}

static unsigned win_service(void)
{
    uint32_t now = FW_TICKS, dt = now - last_tick, n;

    if (!gb_running) {
        if (now - sec_tick >= 100) {
            sec_tick = now;
            status_due = 1;
            fw_msg_send(MSG_UPDATE);
        }
        return 0;
    }
    if (!dt || dead)
        return 0;
    last_tick = now;
    if (dt > 8)
        dt = 8;
    gb.direct.joypad = ~read_pad(dt);

    /* 59.73 frames per second = 0.5973 per tick. Up to four per pass, only
     * the last one drawn, so a slow pass costs picture smoothness before it
     * costs game speed. Beyond that the game slows down instead. */
    frame_acc += dt * 5973;
    n = frame_acc / 10000;
    frame_acc %= 10000;
    if (n > 4)
        n = 4;
    while (n--) {
        gb.display.lcd_draw_line = (n == 0 && can_draw) ? draw_line : NULL;
        gb_run_frame(&gb);
        gb_frames++;
        fps_emu++;
        if (n == 0) {
            fps_drawn++;
            dirty = 1;
            fw_msg_send(MSG_UPDATE);
        }
    }
    /* cartridge RAM untouched for two seconds after a change: the game has
     * finished saving, so write it out */
    if (gb_sram_dirty && now - sram_tick >= 200)
        flush_save();
    if (now - sec_tick >= 100) {
        sec_tick = now;
        if (saved_flash)
            saved_flash--;
        shown_emu = fps_emu; shown_drawn = fps_drawn; shown_miss = miss_sec;
        fps_emu = fps_drawn = miss_sec = 0;
        status_due = 1;                 /* redraw the meters, once a second */
        fw_msg_send(MSG_UPDATE);
    }
    return 0;
}

static int win_key(void)
{
    unsigned v = fw_get_key();
    uint16_t arg[14];

    if (!v)
        return 0;
    fw_idle_reset();
    if (v == 0x20000002u) {   /* long press on Select: back to the menu */
        flush_save();
        memset(arg, 0, sizeof arg);
        arg[0] = 7;
        fw_task_switch(TASK_MAINMENU, arg);
        FW_COLOUR = 0;
        return -1;
    }
    if (!gb_running)
        pick_key(v);
    return 0;
}

static void win_paint(void)
{
    uint16_t saved = FW_COLOUR;

    if (!gb_running) {
        int full = fw_msg_take(MSG_FULL) == 1;
        if (fw_msg_take(MSG_UPDATE) == 1 || full)
            pick_paint(full);
        FW_COLOUR = saved;
        return;
    }
    if (fw_msg_take(MSG_FULL) == 1) {
        /* red: no ROM found or it cannot be opened, magenta: not a ROM, yellow: too much cartridge
         * RAM, blue: the core refused it or hit an invalid instruction */
        static const uint16_t err[5] = { 0, 0xf800, 0xf81f, 0xffe0, 0x001f };
        FW_COLOUR = err[dead];
        fw_fill_rect(0, 0, 295, 239);
    }
    if (fw_msg_take(MSG_UPDATE) == 1) {
        if (dirty) {
            /* Tell the firmware the picture area changed: set_window widens
             * its dirty range, put_pixel raises its "changed" flag. The pixel
             * it writes is the one that is already there. */
            dirty = 0;
            fw_set_window(XOFF, YOFF, XOFF + OUT_W - 1, YOFF + OUT_H - 1);
            fw_put_pixel(fb_row(YOFF)[1]);
        }
        if (!status_due) {
            FW_COLOUR = saved;
            return;
        }
        status_due = 0;
        /* speed meter: top bar = frames emulated per second, bar below =
         * frames drawn per second, 4 pixels per frame (full width = 60) */
        FW_COLOUR = 0;
        fw_fill_rect(XOFF, 2, XOFF + OUT_W - 1, 8);
        FW_COLOUR = 0x07e0;
        if (shown_emu)
            fw_fill_rect(XOFF, 2, XOFF + (shown_emu > 60 ? 60 : shown_emu) * 4 - 1, 4);
        FW_COLOUR = 0xffe0;
        if (shown_drawn)
            fw_fill_rect(XOFF, 6, XOFF + (shown_drawn > 60 ? 60 : shown_drawn) * 4 - 1, 8);
        /* red bar below the picture: ROM pages read from storage in the last second */
        FW_COLOUR = 0;
        fw_fill_rect(XOFF, 231, XOFF + OUT_W - 1, 233);
        FW_COLOUR = 0xf800;
        if (shown_miss)
            fw_fill_rect(XOFF, 231, XOFF + (shown_miss > 60 ? 60 : shown_miss) * 4 - 1, 233);
        /* blue square, top right: the save file was just written;
         * white square: this cartridge has RAM but no usable .SAV file */
        FW_COLOUR = saved_flash ? 0x001f : (cart_ram && !gb_save_ok) ? 0xffff : 0;
        fw_fill_rect(280, 2, 287, 8);
    }
    FW_COLOUR = saved;
}

static void win_init(void *arg)
{
    (void)arg;
    dirty = 0;
    key_prev = key_now = latch = combo = grace = 0;
    gb_frames = gb_misses = 0;
    fps_emu = fps_drawn = shown_emu = shown_drawn = miss_sec = shown_miss = 0;
    pal[0] = 0xe7da; pal[1] = 0x9d6f; pal[2] = 0x4b08; pal[3] = 0x1102;  /* light to dark */
    can_draw = FW_FB_INDEX == 0 && FW_ROTATED == 0;
    rom_file = -1;
    cart_ram = NULL;
    gb_save_ok = gb_sram_dirty = saved_flash = 0;
    gb_running = gb_sel = list_top = wait_release = 0;
    gb_sticky = h_latch = pad_prev = status_due = 0;
    dead = 0;
    /* ROMs and saves live on internal storage. If a microSD card is in, the
     * firmware is looking at the card (often exFAT, which the listing code
     * here does not read), so switch to internal while the game runs. */
    orig_disk = FW_CUR_DISK;
    if (orig_disk != DISK_INTERNAL && fw_fs_setup(DISK_INTERNAL) != 0)
        orig_disk = DISK_INTERNAL;      /* could not switch: leave things as they are */
    scan_roms();
    if (!gb_n_roms) {
        dead = 1;
        gb_running = 1;
    }
    last_tick = sec_tick = FW_TICKS;
    fw_msg_send(MSG_FULL);
    fw_game_enter();
    fw_enter2();
}

static void win_deinit(void)
{
    flush_save();
    if (rom_file >= 0)
        fw_file_close(rom_file);
    rom_file = -1;
    if (orig_disk != DISK_INTERNAL) {   /* hand the card back to the firmware */
        fw_fs_setup(orig_disk);
        orig_disk = DISK_INTERNAL;
    }
    fw_game_leave();
    fw_idle_reset();
}

struct window {
    void *child, *parent;
    unsigned (*service)(void);
    int (*key)(void);
    void (*paint)(void);
    void (*init)(void *);
    void (*deinit)(void);
};

__attribute__((section(".window"), used))
struct window gw_window = { 0, 0, win_service, win_key, win_paint, win_init, win_deinit };
