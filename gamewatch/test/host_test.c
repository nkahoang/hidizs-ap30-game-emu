/* Native test of the SM510 core. Usage: host_test demo.rom */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sm510.h"

static int fails;
#define CHECK(cond, ...) do { if (!(cond)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint8_t rom[SM510_ROM_SIZE];

/* put a straight-line program at the reset vector, following the PC LFSR */
static void program(const uint8_t *code, int n)
{
    unsigned pl = 0;
    memset(rom, 0, sizeof rom);
    for (int i = 0; i < n; i++) {
        rom[3 * SM510_ROM_PAGE + (7 << 6 | pl)] = code[i];
        pl = (((pl >> 1 ^ pl) & 1) ? 0 : 0x20) | pl >> 1;
    }
}

static sm510_t run(const uint8_t *code, int n, int cycles)
{
    sm510_t s;
    program(code, n);
    sm510_init(&s, rom);
    sm510_run(&s, cycles);
    return s;
}

#define RUN(cycles, ...) ({ const uint8_t c_[] = { __VA_ARGS__ }; run(c_, sizeof c_, cycles); })

static void test_ops(void)
{
    sm510_t s;

    s = RUN(1, 0x27);                               /* LAX 7 */
    CHECK(s.acc == 7, "LAX acc=%d", s.acc);
    s = RUN(2, 0x27, 0x23);                         /* second LAX in a row is ignored */
    CHECK(s.acc == 7, "LAX LAX acc=%d", s.acc);
    s = RUN(3, 0x29, 0x38, 0x21);                   /* 9+8 carries: skip next */
    CHECK(s.acc == 1 && s.skip == 0, "ADX carry acc=%d", s.acc);
    s = RUN(4, 0x29, 0x38, 0x00, 0x33);
    CHECK(s.acc == 4, "ADX skip acc=%d", s.acc);
    s = RUN(3, 0x29, 0x3a, 0x31);                   /* ADX 10 never skips */
    CHECK(s.acc == 4, "ADX 10 acc=%d", s.acc);
    s = RUN(4, 0x5f, 0x35, 0x2c, 0x10);             /* LBL 35; LAX c; EXC */
    CHECK(s.ram[0x35] == 0xc && s.acc == 0 && s.bm == 3 && s.bl == 5, "LBL/EXC");
    s = RUN(4, 0x5f, 0x35, 0x2c, 0x12);             /* EXC 2 flips BM bit 1 */
    CHECK(s.ram[0x35] == 0xc && s.bm == 1, "EXC bm=%d", s.bm);
    s = RUN(2, 0x4b);                               /* LB: bm=3, bl=1110 */
    CHECK(s.bm == 3 && s.bl == 0xe, "LB bm=%d bl=%x", s.bm, s.bl);
    s = RUN(2, 0x41);                               /* LB with low BL: bl=0 */
    CHECK(s.bm == 1 && s.bl == 0, "LB bm=%d bl=%x", s.bm, s.bl);
    s = RUN(4, 0x5f, 0x2f, 0x64, 0x2a);             /* INCB wraps: skip */
    CHECK(s.bl == 0 && s.acc == 0, "INCB skip");
    s = RUN(3, 0x0d, 0x0f, 0x05);                   /* SM 1, SM 3, RM 1 at 00 */
    CHECK(s.ram[0] == 8, "SM/RM ram=%x", s.ram[0]);
    s = RUN(3, 0x02, 0x0d, 0x0e);                   /* SBM affects one instruction */
    CHECK(s.ram[0x40] == 2 && s.ram[0] == 4, "SBM %x %x", s.ram[0x40], s.ram[0]);
    s = RUN(4, 0x67, 0x29, 0x6b, 0x6b);             /* SC; LAX 9; ROT; ROT */
    CHECK(s.acc == 0xe && s.c == 0, "ROT acc=%x c=%d", s.acc, s.c);
    s = RUN(5, 0x0f, 0x28, 0x67, 0x09, 0x2f);       /* ram=8, acc=8, C=1: ADD11 = 1 carry, skip */
    CHECK(s.acc == 1 && s.c == 1, "ADD11 acc=%x c=%d", s.acc, s.c);
    s = RUN(2, 0x25, 0x0a);                         /* COMA */
    CHECK(s.acc == 0xa, "COMA");
    s = RUN(3, 0x63, 0x62, 0x63);                   /* WS WR WS */
    CHECK(s.w == 5, "W=%x", s.w);
    s = RUN(3, 0x25, 0x59, 0x60);                   /* ATL, ATFC */
    CHECK(s.l == 5 && s.y == 5, "ATL/ATFC");
    s = RUN(2, 0x5a, 0x21);                         /* TA0 with acc 0: skip */
    CHECK(s.acc == 0, "TA0");
    s = RUN(3, 0x52, 0x21, 0x00);                   /* TC with C=0: skip */
    CHECK(s.acc == 0, "TC");

    /* TML pushes, RTN1 returns and skips */
    program((const uint8_t[]){ 0x7c, 0x00, 0x21, 0x32 }, 4); /* TML 0.0.0; LAX 1; ADX 2 */
    rom[0] = 0x6f;                                  /* RTN1 at 0.0.0 */
    sm510_init(&s, rom);
    sm510_run(&s, 5);
    CHECK(s.acc == 2, "TML/RTN1 acc=%d", s.acc);

    /* TM goes through the table in page 0 to page x.4.x */
    program((const uint8_t[]){ 0xc5, 0x34 }, 2);    /* TM 5; ADX 4 */
    rom[5] = 1 << 6 | 0;                            /* table entry: 1.4.0 */
    rom[1 * SM510_ROM_PAGE + (4 << 6)] = 0x23;      /* LAX 3 */
    rom[1 * SM510_ROM_PAGE + (4 << 6) + 0x20] = 0x6e; /* RTN0 */
    sm510_init(&s, rom);
    sm510_run(&s, 6);
    CHECK(s.acc == 7, "TM/RTN0 acc=%d", s.acc);

    /* inputs */
    program((const uint8_t[]){ 0x6a }, 1);          /* KTA */
    sm510_init(&s, rom);
    s.k_line = 0; s.k_mask = 6;
    sm510_run(&s, 1);
    CHECK(s.acc == 0, "KTA with S low acc=%x", s.acc);
    program((const uint8_t[]){ 0x63, 0x6a }, 2);    /* WS; KTA */
    sm510_init(&s, rom);
    s.k_line = 0; s.k_mask = 6; s.k_fixed = 8;
    sm510_run(&s, 2);
    CHECK(s.acc == 0xe, "KTA acc=%x", s.acc);
    program((const uint8_t[]){ 0x5e, 0x21, 0x51, 0x32 }, 4); /* TAL; LAX 1; TB; ADX 2 */
    sm510_init(&s, rom);
    s.ba = 0;
    sm510_run(&s, 4);
    CHECK(s.acc == 1, "TAL/TB acc=%x", s.acc);     /* BA low: no skip; B high: skip */
}

static void test_demo(const char *path)
{
    uint8_t raw[0x1000];
    uint32_t lcd[SM510_LCD_WORDS];
    sm510_t s;
    FILE *f = fopen(path, "rb");

    if (!f || fread(raw, 1, sizeof raw, f) != sizeof raw) {
        printf("cannot read %s\n", path);
        exit(2);
    }
    fclose(f);
    for (int n = 0; n < 4; n++)
        memcpy(rom + n * SM510_ROM_PAGE, raw + n * 0x400, SM510_ROM_PAGE);

    sm510_init(&s, rom);
    sm510_run(&s, 2000);
    sm510_lcd(&s, lcd);
    CHECK(lcd[0] == 0x55555555 && lcd[1] == 0x55555555, "row a %08x %08x", lcd[0], lcd[1]);
    CHECK(lcd[2] == 0 && lcd[3] == 0, "row b %08x %08x", lcd[2], lcd[3]);
    CHECK(lcd[4] == 0 && s.halt, "bs %x halt %d", lcd[4], s.halt);

    /* 3.5 seconds, fed in uneven slices as the device does */
    for (int left = 16384 * 7 / 2 - 2000; left > 0; left -= 163)
        sm510_run(&s, left < 163 ? left : 163);
    sm510_lcd(&s, lcd);
    CHECK(lcd[4] == 3, "seconds counter %x", lcd[4]);

    /* a key on S1 shows up on row b and wakes the CPU */
    s.k_line = 0; s.k_mask = 9;
    sm510_run(&s, 500);
    sm510_lcd(&s, lcd);
    CHECK(lcd[2] == 0x99999999 && lcd[3] == 0x99999999, "row b key %08x %08x", lcd[2], lcd[3]);
    /* after release the ROM sleeps; row b is rewritten at the next 1 Hz wake-up */
    s.k_line = 0xff;
    sm510_run(&s, 16384);
    sm510_lcd(&s, lcd);
    CHECK(lcd[2] == 0 && lcd[3] == 0 && s.halt, "row b released %08x %08x", lcd[2], lcd[3]);
    CHECK(lcd[4] == 4, "seconds counter %x", lcd[4]);

    /* 16-second wrap of the 4-bit counter exercises the ADX skip */
    sm510_run(&s, 16384 * 16);
    sm510_lcd(&s, lcd);
    CHECK(lcd[4] == 4, "counter after wrap %x", lcd[4]);
}

int main(int argc, char **argv)
{
    test_ops();
    if (argc > 1)
        test_demo(argv[1]);
    printf(fails ? "%d FAILED\n" : "all core tests passed\n", fails);
    return fails != 0;
}
