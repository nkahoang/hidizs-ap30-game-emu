/* Sharp SM510 core for the AP30 Game & Watch module.
 * Behaviour follows the Sharp data book as documented by MAME's sm510 core
 * (BSD-3-Clause, hap); this is an independent implementation. */
#ifndef SM510_H
#define SM510_H

#include <stdint.h>

#define SM510_ROM_PAGE 0x2c0            /* valid bytes in each 1 KB block */
#define SM510_ROM_SIZE (4 * SM510_ROM_PAGE) /* packed ROM: 2816 bytes */
#define SM510_LCD_WORDS 5               /* 144 segment bits */

typedef struct {
    const uint8_t *rom;   /* packed: block n at n * SM510_ROM_PAGE */
    uint16_t pc, prev_pc;
    uint16_t stack[2];
    uint16_t div;         /* 15-bit divider, 32768 Hz */
    uint8_t op, prev_op, param;
    uint8_t acc, bl, bm, bmask, c;
    uint8_t skip, halt, gamma;
    uint8_t w;            /* S output latch (input strobes) */
    uint8_t r;            /* R output latch (buzzer) */
    uint8_t l, x, y, bp, bc;
    uint8_t k_fixed;      /* K bits that are on regardless of S */
    uint8_t k_line;       /* S line of the held key, 0xff if none */
    uint8_t k_mask;       /* K bits of the held key */
    uint8_t ba, b;        /* BA and B(beta) pins, 1 = released */
    uint8_t ram[128];
} sm510_t;

/* Power-on: clears everything, then resets. */
void sm510_init(sm510_t *s, const uint8_t *packed_rom);
/* ACL reset: keeps RAM and the divider. */
void sm510_reset(sm510_t *s);
/* Run for a number of machine cycles (16384 per second). */
void sm510_run(sm510_t *s, int cycles);
/* Segment states. Bit index = group * 64 + segment * 4 + common,
 * group 0 = a, 1 = b, 2 = bs. This matches MAME's "group.segment.common". */
void sm510_lcd(const sm510_t *s, uint32_t out[SM510_LCD_WORDS]);

#endif
