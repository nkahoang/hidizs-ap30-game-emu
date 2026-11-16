#include "sm510.h"

static unsigned rom_r(const sm510_t *s, unsigned a)
{
    unsigned off = a & 0x3ff;
    if (off >= SM510_ROM_PAGE)
        return 0;
    return s->rom[((a >> 10) & 3) * SM510_ROM_PAGE + off];
}

static unsigned ram_addr(const sm510_t *s)
{
    return (s->bmask | s->bm << 4 | s->bl) & 0x7f;
}

static unsigned ram_r(const sm510_t *s)
{
    return s->ram[ram_addr(s)] & 0xf;
}

static void ram_w(sm510_t *s, unsigned v)
{
    s->ram[ram_addr(s)] = v & 0xf;
}

static unsigned read_k(const sm510_t *s)
{
    unsigned k = s->k_fixed;
    if (s->k_line < 8 && (s->w >> s->k_line & 1))
        k |= s->k_mask;
    return k & 0xf;
}

static void push(sm510_t *s)
{
    s->stack[1] = s->stack[0];
    s->stack[0] = s->pc;
}

static void pop(sm510_t *s)
{
    s->pc = s->stack[0] & 0xfff;
    s->stack[0] = s->stack[1];
}

static void branch(sm510_t *s, unsigned pu, unsigned pm, unsigned pl)
{
    s->pc = (pu << 10 | (pm << 6 & 0x3c0) | (pl & 0x3f)) & 0xfff;
}

/* The low 6 bits of PC are an LFSR, not a counter. */
static void inc_pc(sm510_t *s)
{
    unsigned pc = s->pc;
    unsigned feed = ((pc >> 1 ^ pc) & 1) ? 0 : 0x20;
    s->pc = feed | (pc >> 1 & 0x1f) | (pc & ~0x3f);
}

/* One machine cycle is two 32768 Hz clocks. */
static void tick(sm510_t *s)
{
    s->div = (s->div + 2) & 0x7fff;
    if (s->div == 0)
        s->gamma = 1;
}

static void exc(sm510_t *s)
{
    unsigned a = s->acc;
    s->acc = ram_r(s);
    ram_w(s, a);
    s->bm ^= s->op & 3;
}

static void incb(sm510_t *s)
{
    s->bl = (s->bl + 1) & 0xf;
    s->skip = s->bl == 0;
}

static void decb(sm510_t *s)
{
    s->bl = (s->bl - 1) & 0xf;
    s->skip = s->bl == 0xf;
}

static void execute(sm510_t *s)
{
    unsigned op = s->op;
    unsigned bit = 1u << (op & 3);
    unsigned t;

    switch (op >> 4) {
    case 0x2: /* LAX: only the first of a run of LAX takes effect */
        if ((s->prev_op & 0xf0) != 0x20)
            s->acc = op & 0xf;
        return;
    case 0x3: /* ADX */
        t = s->acc + (op & 0xf);
        s->skip = (op & 0xf) != 10 && (t & 0x10);
        s->acc = t & 0xf;
        return;
    case 0x4: /* LB */
        s->bm = (s->bm & 4) | (op & 3);
        s->bl = (op >> 2 & 3) | ((op & 0xc) ? 0xc : 0);
        return;
    case 0x7:
        if ((op & 0xc) == 0xc) { /* TML */
            push(s);
            branch(s, s->param >> 6 & 3, op & 3, s->param);
        } else { /* TL */
            branch(s, s->param >> 6 & 3, op & 0xf, s->param);
        }
        return;
    case 0x8: case 0x9: case 0xa: case 0xb: /* T */
        s->pc = (s->pc & ~0x3f) | (op & 0x3f);
        return;
    case 0xc: case 0xd: case 0xe: case 0xf: /* TM */
        tick(s);
        push(s);
        t = rom_r(s, op & 0x3f);
        branch(s, t >> 6 & 3, 4, t);
        return;
    }

    switch (op & 0xfc) {
    case 0x04: ram_w(s, ram_r(s) & ~bit); return;       /* RM */
    case 0x0c: ram_w(s, ram_r(s) | bit); return;        /* SM */
    case 0x10: exc(s); return;                          /* EXC */
    case 0x14: exc(s); incb(s); return;                 /* EXCI */
    case 0x18: s->acc = ram_r(s); s->bm ^= op & 3; return; /* LDA */
    case 0x1c: exc(s); decb(s); return;                 /* EXCD */
    case 0x54: s->skip = (ram_r(s) & bit) != 0; return; /* TMI */
    }

    switch (op) {
    case 0x00: return;                                  /* SKIP */
    case 0x01: s->bp = s->acc; return;                  /* ATBP */
    case 0x02: return;                                  /* SBM (see below) */
    case 0x03: s->pc = (s->prev_pc & ~0xf) | s->acc; return; /* ATPL */
    case 0x08: s->acc = (s->acc + ram_r(s)) & 0xf; return;   /* ADD */
    case 0x09:                                          /* ADD11 */
        t = s->acc + ram_r(s) + s->c;
        s->c = t >> 4 & 1;
        s->skip = s->c;
        s->acc = t & 0xf;
        return;
    case 0x0a: s->acc ^= 0xf; return;                   /* COMA */
    case 0x0b: t = s->acc; s->acc = s->bl; s->bl = t; return; /* EXBLA */
    case 0x51: s->skip = s->b != 0; return;             /* TB */
    case 0x52: s->skip = !s->c; return;                 /* TC */
    case 0x53: s->skip = s->acc == ram_r(s); return;    /* TAM */
    case 0x58: s->skip = !s->gamma; s->gamma = 0; return; /* TIS */
    case 0x59: s->l = s->acc; return;                   /* ATL */
    case 0x5a: s->skip = !s->acc; return;               /* TA0 */
    case 0x5b: s->skip = s->acc == s->bl; return;       /* TABL */
    case 0x5d: s->halt = 1; return;                     /* CEND */
    case 0x5e: s->skip = s->ba != 0; return;            /* TAL */
    case 0x5f:                                          /* LBL */
        s->bl = s->param & 0xf;
        s->bm = (s->param & 0x7f) >> 4;
        return;
    case 0x60: s->y = s->acc; return;                   /* ATFC */
    case 0x61: s->r = s->acc; return;                   /* ATR */
    case 0x62: s->w = s->w << 1; return;                /* WR */
    case 0x63: s->w = s->w << 1 | 1; return;            /* WS */
    case 0x64: incb(s); return;                         /* INCB */
    case 0x65: s->div = 0; return;                      /* IDIV */
    case 0x66: s->c = 0; return;                        /* RC */
    case 0x67: s->c = 1; return;                        /* SC */
    case 0x68: s->skip = (s->div & 0x4000) != 0; return; /* TF1 */
    case 0x69: s->skip = (s->div & 0x0800) != 0; return; /* TF4 */
    case 0x6a: s->acc = read_k(s); return;              /* KTA */
    case 0x6b:                                          /* ROT */
        t = s->acc & 1;
        s->acc = s->acc >> 1 | s->c << 3;
        s->c = t;
        return;
    case 0x6c: decb(s); return;                         /* DECB */
    case 0x6d: s->bc = s->c != 0; return;               /* BDC */
    case 0x6e: pop(s); return;                          /* RTN0 */
    case 0x6f: pop(s); s->skip = 1; return;             /* RTN1 */
    }
    /* anything else is an illegal opcode: treated as a no-op */
}

void sm510_reset(sm510_t *s)
{
    s->skip = 0;
    s->halt = 0;
    s->bmask = 0;
    s->op = s->prev_op = 0;
    branch(s, 3, 7, 0);
    s->prev_pc = s->pc;
    s->bp = 1;
    s->bc = 0;
    s->y = 0;
    s->r = 0;
}

void sm510_init(sm510_t *s, const uint8_t *packed_rom)
{
    uint8_t *p = (uint8_t *)s;
    unsigned i;
    for (i = 0; i < sizeof *s; i++)
        p[i] = 0;
    s->rom = packed_rom;
    s->k_line = 0xff;
    s->ba = s->b = 1;
    sm510_reset(s);
}

void sm510_run(sm510_t *s, int cycles)
{
    while (cycles > 0) {
        if (s->halt) {
            if (s->gamma || read_k(s)) {
                /* wake-up */
                cycles--;
                tick(s);
                s->halt = 0;
                branch(s, 1, 0, 0);
            } else {
                /* nothing can happen until the divider wraps */
                int left = (0x8000 - s->div) >> 1;
                if (left > cycles) {
                    s->div += cycles * 2;
                    return;
                }
                cycles -= left;
                s->div = 0;
                s->gamma = 1;
                continue;
            }
        }

        cycles--;
        tick(s);
        s->prev_op = s->op;
        s->prev_pc = s->pc;
        s->op = rom_r(s, s->pc);
        inc_pc(s);

        /* LBL, TL and TML are two bytes */
        if (s->op == 0x5f || (s->op & 0xf0) == 0x70) {
            cycles--;
            tick(s);
            s->param = rom_r(s, s->pc);
            inc_pc(s);
        }

        if (s->skip) {
            s->skip = 0;
            s->op = 0;
        } else {
            execute(s);
        }
        /* SBM sets the high bit of BM for the next instruction only */
        s->bmask = s->op == 0x02 ? 0x40 : 0;
    }
}

void sm510_lcd(const sm510_t *s, uint32_t out[SM510_LCD_WORDS])
{
    unsigned i, blink;

    for (i = 0; i < SM510_LCD_WORDS; i++)
        out[i] = 0;
    if (s->bc || !(s->bp & 1))
        return;
    for (i = 0; i < 32; i++)
        out[i >> 3] |= (uint32_t)(s->ram[0x60 + i] & 0xf) << ((i & 7) * 4);
    blink = (s->div & 0x4000) ? s->y : 0;
    out[4] = ((s->l & ~blink) & 0xf) | (uint32_t)(s->x & 0xf) << 4;
}
