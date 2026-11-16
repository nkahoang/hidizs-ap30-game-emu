/* Native test runner for the Game Boy core.
 *   gb_host ROM.gb serial [frames]     print serial output (Blargg test ROMs)
 *   gb_host ROM.gb ppm OUT.ppm frames [joypad-script]
 * joypad-script: comma list of frame:mask, mask = pressed JOYPAD_* bits. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define ENABLE_SOUND 0
#define ENABLE_LCD 1
#define PEANUT_GB_12_COLOUR 0
#ifndef PEANUT_GB_HIGH_LCD_ACCURACY
#define PEANUT_GB_HIGH_LCD_ACCURACY 0   /* same as the device build */
#endif
#include "../third_party/peanut_gb/peanut_gb.h"

static uint8_t *rom; static size_t rom_size;
static uint8_t cart_ram[0x8000];
static uint8_t fb[144][160];

static uint8_t rom_read(struct gb_s *gb, const uint_fast32_t a) { (void)gb; return a < rom_size ? rom[a] : 0xff; }
static uint8_t ram_read(struct gb_s *gb, const uint_fast32_t a) { (void)gb; return cart_ram[a & 0x7fff]; }
static void ram_write(struct gb_s *gb, const uint_fast32_t a, const uint8_t v) { (void)gb; cart_ram[a & 0x7fff] = v; }
static void on_error(struct gb_s *gb, const enum gb_error_e e, const uint16_t a) { (void)gb; fprintf(stderr, "gb error %d at %04x\n", e, a); exit(3); }
static void serial_tx(struct gb_s *gb, const uint8_t c) { (void)gb; putchar(c); fflush(stdout); }
static void draw_line(struct gb_s *gb, const uint8_t *px, const uint_fast8_t line) { (void)gb; for (int x = 0; x < 160; x++) fb[line][x] = px[x] & 3; }

int main(int argc, char **argv)
{
    static struct gb_s gb;
    if (argc < 3) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END); rom_size = ftell(f); rewind(f);
    rom = malloc(rom_size); fread(rom, 1, rom_size, f); fclose(f);
    memset(cart_ram, 0xff, sizeof cart_ram);   /* same power-on contents as the device build */
    enum gb_init_error_e r = gb_init(&gb, rom_read, ram_read, ram_write, on_error, NULL);
    if (r) { fprintf(stderr, "gb_init failed: %d\n", r); return 2; }
    fprintf(stderr, "sizeof(struct gb_s) = %zu\n", sizeof gb);
    if (!strcmp(argv[2], "serial")) {
        int frames = argc > 3 ? atoi(argv[3]) : 4000;
        gb_init_serial(&gb, serial_tx, NULL);
        for (int i = 0; i < frames; i++) gb_run_frame(&gb);
        putchar('\n');
        return 0;
    }
    gb_init_lcd(&gb, draw_line);
    int frames = atoi(argv[4]);
    const char *script = argc > 5 ? argv[5] : "";
    for (int i = 0; i < frames; i++) {
        const char *p = script; unsigned mask = 0;
        while (*p) { int fr; unsigned m; if (sscanf(p, "%d:%x", &fr, &m) == 2 && i >= fr && i < fr + 6) mask = m; p = strchr(p, ','); if (!p) break; p++; }
        gb.direct.joypad = ~mask;
        gb_run_frame(&gb);
    }
    f = fopen(argv[3], "wb");
    fprintf(f, "P6 160 144 255\n");
    static const uint8_t shade[4] = { 0xe0, 0xa0, 0x58, 0x10 };
    for (int y = 0; y < 144; y++) for (int x = 0; x < 160; x++) { uint8_t s = shade[fb[y][x]]; fputc(s, f); fputc(s, f); fputc(s, f); }
    fclose(f);
    return 0;
}
