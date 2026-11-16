/* cachesim ROM frames total_kb : page-cache misses for several policies */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define ENABLE_SOUND 0
#define ENABLE_LCD 1
#define PEANUT_GB_12_COLOUR 0
#define PEANUT_GB_HIGH_LCD_ACCURACY 0
#include "../../third_party/peanut_gb/peanut_gb.h"
static uint8_t *rom; static size_t rom_size; static uint8_t cart_ram[0x8000];
#define NCFG 6
static struct cfg { int shift, lru, pin; int slots; int *page; unsigned *stamp; int next; unsigned long miss; int last; } C[NCFG];
static unsigned clk;
static void touch(struct cfg *c, unsigned a)
{
    int p = a >> c->shift, i, v = -1;
    if (p == c->last) return;
    c->last = p; clk++;
    for (i = 0; i < c->slots; i++) if (c->page[i] == p) { c->stamp[i] = clk; return; }
    c->miss++;
    if (c->lru) { unsigned best = ~0u; for (i = 0; i < c->slots; i++) { if (c->page[i] < 0) { v = i; break; } if (c->pin && (c->page[i] << c->shift) < 0x4000) continue; if (c->stamp[i] < best) { best = c->stamp[i]; v = i; } } }
    else { do { v = c->next; c->next = (c->next + 1) % c->slots; } while (c->pin && c->page[v] >= 0 && (c->page[v] << c->shift) < 0x4000); }
    c->page[v] = p; c->stamp[v] = clk;
}
static uint8_t rom_read(struct gb_s *gb, const uint_fast32_t a) { for (int i = 0; i < NCFG; i++) touch(&C[i], a); return rom[a & (rom_size - 1)]; }
static uint8_t ram_read(struct gb_s *gb, const uint_fast32_t a) { return cart_ram[a & 0x7fff]; }
static void ram_write(struct gb_s *gb, const uint_fast32_t a, const uint8_t v) { cart_ram[a & 0x7fff] = v; }
static void on_error(struct gb_s *gb, const enum gb_error_e e, const uint16_t a) { }
static void draw_line(struct gb_s *gb, const uint8_t *px, const uint_fast8_t line) { }
int main(int argc, char **argv)
{
    static struct gb_s gb;
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, SEEK_END); rom_size = ftell(f); rewind(f); rom = malloc(rom_size); fread(rom, 1, rom_size, f); fclose(f);
    int frames = atoi(argv[2]), kb = atoi(argv[3]);
    static const int cfg[NCFG][3] = { {12,0,1}, {12,1,0}, {12,1,1}, {11,1,0}, {10,1,0}, {9,1,0} };
    for (int i = 0; i < NCFG; i++) { C[i].shift = cfg[i][0]; C[i].lru = cfg[i][1]; C[i].pin = cfg[i][2]; C[i].slots = kb * 1024 >> C[i].shift; C[i].page = malloc(sizeof(int) * C[i].slots); C[i].stamp = calloc(C[i].slots, sizeof(unsigned)); for (int j = 0; j < C[i].slots; j++) C[i].page[j] = -1; C[i].last = -1; }
    memset(cart_ram, 0xff, sizeof cart_ram);
    if (gb_init(&gb, rom_read, ram_read, ram_write, on_error, NULL)) return 2;
    gb_init_lcd(&gb, draw_line);
    for (int i = 0; i < frames; i++) {
        /* mash through menus: Start and A alternately, plus some walking */
        unsigned ph = i / 20 % 8, m = ph == 0 ? JOYPAD_START : ph == 2 ? JOYPAD_A : ph == 4 ? JOYPAD_DOWN : ph == 6 ? JOYPAD_RIGHT : 0;
        gb.direct.joypad = ~m;
        gb_run_frame(&gb);
    }
    for (int i = 0; i < NCFG; i++)
        printf("  page %4d B, %-4s%-5s %3d slots: %7lu reads = %5.2f per frame, %6.1f KB per second\n", 1 << C[i].shift, C[i].lru ? "LRU" : "FIFO", C[i].pin ? "+pin" : "", C[i].slots, C[i].miss, (double)C[i].miss / frames, (double)C[i].miss / frames * 60 * (1 << C[i].shift) / 1024);
    return 0;
}
