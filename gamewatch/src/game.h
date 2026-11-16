/* Per-game data, generated into build/game_data.c by tools/mkgame.py. */
#ifndef GAME_H
#define GAME_H

#include <stdint.h>

/* gw_keymap line values; 0-7 mean "K bits read while S line n is high" */
#define GW_IN_FIXED 8   /* K bits read regardless of S */
#define GW_IN_BA    9   /* BA pin (pulled low while held) */
#define GW_IN_B     10  /* B (beta) pin (pulled low while held) */
#define GW_IN_ACL   11  /* reset the CPU */
#define GW_IN_NONE  0xff

struct gw_cfg {
    uint16_t bg, fg;      /* RGB565 */
    uint8_t scale;        /* screen pixels per artwork pixel */
    uint8_t xoff, yoff;   /* screen position of the artwork */
};

extern const uint8_t gw_rom[];      /* packed SM510 ROM, 2816 bytes */
extern const uint8_t gw_segs[];     /* segment records, ended by 0xff */
extern const uint8_t gw_keymap[18]; /* (line, K mask) for AP30 key bits 0-8 */
extern const struct gw_cfg gw_cfg;

#endif
