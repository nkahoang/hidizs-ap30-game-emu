/* Game & Watch front-end for the Hidizs AP30 (firmware HIFIYF18, v1.7.8).
 *
 * Built as a replacement for one of the stock game modules. Every firmware
 * address below is a run address in the resident module of that exact
 * firmware build and is wrong for any other build. See docs/FINDINGS.md,
 * "Game module API". */
#include "sm510.h"
#include "game.h"

/* ---- firmware (resident module, Thumb) ---- */
#define FW(addr, ret, args) ((ret (*) args)((addr) | 1))
#define fw_set_window FW(0x03064ea8, void, (unsigned x0, unsigned y0, unsigned x1, unsigned y1))
#define fw_put_pixel  FW(0x03064dc4, void, (unsigned rgb565))
#define fw_fill_rect  FW(0x03064688, void, (int x0, int y0, int x1, int y1))
#define fw_msg_send   FW(0x03067ed4, void, (unsigned id))
#define fw_msg_take   FW(0x03067ef0, int, (unsigned id))
#define fw_get_key    FW(0x03062fa6, unsigned, (void))
#define fw_task_switch FW(0x030680d4, void, (unsigned task, void *arg))
#define fw_idle_reset FW(0x03065bc4, void, (void))
#define fw_game_enter FW(0x030664a2, void, (void))
#define fw_game_leave FW(0x0306645a, void, (void))
#define fw_enter2     FW(0x03053822, void, (void))

#define FW_COLOUR (*(volatile uint16_t *)0x03022dec) /* fill_rect colour */
#define FW_TICKS  (*(volatile uint32_t *)0x0302288c) /* 10 ms ticks */

/* Paint-request flags. Same message numbers the stock Snake uses. */
#define MSG_UPDATE 0x189
#define MSG_FULL   0x18c

#define KEY_TYPE(v)  ((v) >> 28)
#define KEY_BACK     0x002
#define TASK_MAINMENU 10

static sm510_t cpu;
static uint32_t last_tick;
static uint32_t frac;                       /* cycle remainder, 1/100 */
static uint32_t prev[SM510_LCD_WORDS];      /* previous LCD sample */
static uint32_t want[SM510_LCD_WORDS];      /* debounced state */
static uint32_t shown[SM510_LCD_WORDS];     /* what is on the screen */
#ifdef GW_KEYTEST
static uint32_t last_key;                   /* last non-zero key value */
static uint16_t adc_prev, adc_min;          /* key ladder: last sample, lowest of this press */
#define FW_KEY_ADC (*(volatile uint16_t *)0x03005a8e) /* ADC channel 1, 10 bits */
#define ADC_IDLE 950
#endif

void *memset(void *d, int c, unsigned n)
{
    uint8_t *p = d;
    while (n--)
        *p++ = c;
    return d;
}

void *memcpy(void *d, const void *s, unsigned n)
{
    uint8_t *p = d;
    const uint8_t *q = s;
    while (n--)
        *p++ = *q++;
    return d;
}

/* Walks one segment record and returns the next one. Draws it in `colour`
 * when `draw` is set. Record: id, y0, rows, xbase/2, then per row
 * ((repeat-1) << 3 | runs) followed by runs of (gap, length). */
static const uint8_t *segment(const uint8_t *p, int draw, unsigned colour)
{
    unsigned sc = gw_cfg.scale;
    unsigned y = p[1], rows = p[2], xbase = p[3] * 2u;
    p += 4;
    while (rows--) {
        unsigned rep = (*p >> 3) + 1, runs = *p & 7, x = xbase;
        p++;
        while (runs--) {
            unsigned len = p[1];
            x += p[0];
            p += 2;
            if (draw && len) {
                unsigned x0 = x * sc + gw_cfg.xoff, y0 = y * sc + gw_cfg.yoff;
                unsigned n = len * sc * rep * sc;
                fw_set_window(x0, y0, x0 + len * sc - 1, y0 + rep * sc - 1);
                while (n--)
                    fw_put_pixel(colour);
            }
            x += len;
        }
        y += rep;
    }
    return p;
}

static void set_key(unsigned bit)
{
    unsigned i;
    const uint8_t *m = gw_keymap;

    cpu.k_line = 0xff;
    cpu.k_fixed = 0;
    cpu.ba = cpu.b = 1;
    for (i = 0; i < 9; i++, m += 2) {
        if (!(bit >> i & 1))
            continue;
        switch (m[0]) {
        case GW_IN_FIXED: cpu.k_fixed = m[1]; break;
        case GW_IN_BA:    cpu.ba = 0; break;
        case GW_IN_B:     cpu.b = 0; break;
        case GW_IN_ACL:   sm510_reset(&cpu); break;
        default:
            if (m[0] < 8) {
                cpu.k_line = m[0];
                cpu.k_mask = m[1];
            }
        }
    }
}

static unsigned win_service(void)
{
    uint32_t now = FW_TICKS, dt = now - last_tick, cur[SM510_LCD_WORDS];
    unsigned i, changed = 0;

    if (!dt)
        return 0;
    last_tick = now;
    if (dt > 10)
        dt = 10; /* never try to catch up more than 100 ms */
    frac += dt * 16384;
    sm510_run(&cpu, frac / 100);
    frac %= 100;

    /* A segment changes on screen once two samples in a row agree, which
     * hides the short gaps while the game rewrites its display memory. */
    sm510_lcd(&cpu, cur);
#ifdef GW_KEYTEST
    /* Key test: show the last raw key value instead of the game.
     * Row a, line 1: one box per key bit 0-15.
     * Row a, line 2: bits 24-27 in boxes 0-3.
     * Row a, line 3: the box whose number is the event type (bits 28-31). */
    cur[0] = cur[1] = cur[2] = cur[3] = 0;
    for (i = 0; i < 16; i++) {
        unsigned on = (last_key >> i & 1)
                    | (i < 4 ? (last_key >> (24 + i) & 1) << 1 : 0)
                    | (last_key && i == KEY_TYPE(last_key) ? 4 : 0);
        cur[i >> 3] |= (uint32_t)on << ((i & 7) * 4);
    }
    /* Row b, line 1: the key ladder's ADC value right now, in binary
     * (box 0 = 1, box 1 = 2, ... box 9 = 512).
     * Row b, line 3: the lowest value seen during the last press. */
    {
        unsigned adc = FW_KEY_ADC;
        if (adc < ADC_IDLE && (adc_prev >= ADC_IDLE || adc < adc_min))
            adc_min = adc;
        adc_prev = adc;
        for (i = 0; i < 10; i++) {
            unsigned on = (adc >> i & 1) | (adc_min >> i & 1) << 2;
            cur[2 + (i >> 3)] |= (uint32_t)on << ((i & 7) * 4);
        }
    }
#endif
    for (i = 0; i < SM510_LCD_WORDS; i++) {
        want[i] = (cur[i] & prev[i]) | (want[i] & (cur[i] | prev[i]));
        prev[i] = cur[i];
        changed |= want[i] ^ shown[i];
    }
    if (changed)
        fw_msg_send(MSG_UPDATE);
    return 0;
}

static int win_key(void)
{
    unsigned v = fw_get_key(), type = KEY_TYPE(v);
    uint16_t arg[14];

    if (!v)
        return 0;
#ifdef GW_KEYTEST
    last_key = v;
#endif
    if (v == (0x20000000u | KEY_BACK)) {
        /* long press on Back: return to the main menu, as Snake does */
        fw_idle_reset();
        memset(arg, 0, sizeof arg);
        arg[0] = 7;
        fw_task_switch(TASK_MAINMENU, arg);
        FW_COLOUR = 0;
        return -1;
    }
    if (type >= 1 && type <= 3) {
        set_key(v & 0x1ff);
        fw_idle_reset();
    } else if (type == 4 || type == 5) {
        set_key(0);
    }
    return 0;
}

static void win_paint(void)
{
    uint16_t saved = FW_COLOUR;
    const uint8_t *p = gw_segs;
    int full = fw_msg_take(MSG_FULL) == 1;
    unsigned i;

    if (full) {
        FW_COLOUR = gw_cfg.bg;
        fw_fill_rect(0, 0, 295, 239);
        for (i = 0; i < SM510_LCD_WORDS; i++)
            shown[i] = 0;
    }
    if (fw_msg_take(MSG_UPDATE) == 1 || full) {
        while (*p != 0xff) {
            unsigned id = *p;
            uint32_t bit = 1u << (id & 31);
            uint32_t diff = (want[id >> 5] ^ shown[id >> 5]) & bit;
            p = segment(p, diff != 0, (want[id >> 5] & bit) ? gw_cfg.fg : gw_cfg.bg);
        }
        for (i = 0; i < SM510_LCD_WORDS; i++)
            shown[i] = want[i];
    }
    FW_COLOUR = saved;
}

static void win_init(void *arg)
{
    unsigned i;
    (void)arg;

    sm510_init(&cpu, gw_rom);
    frac = 0;
#ifdef GW_KEYTEST
    last_key = 0;
    adc_prev = adc_min = 1023;
#endif
    for (i = 0; i < SM510_LCD_WORDS; i++)
        prev[i] = want[i] = shown[i] = 0;
    last_tick = FW_TICKS;
    fw_msg_send(MSG_FULL);
    fw_game_enter();
    fw_enter2();
}

static void win_deinit(void)
{
    fw_game_leave();
    fw_idle_reset();
}

/* The firmware's window structure. It must be the first thing in .data. */
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
