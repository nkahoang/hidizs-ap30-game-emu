/* Game modules run their code at GAME_CODE_RUN and their data at
 * GAME_DATA_RUN (0x030815c4 and 0x03023b48 in HIFIYF18; the build scripts pass
 * them with --defsym), with bss straight after the data. The data must start with the
 * window structure. Sizes are checked against the slot by build.py. */
ENTRY(gw_window)

SECTIONS
{
    .text GAME_CODE_RUN : {
        *(.text .text.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
    }
    __code_end = .;

    .data GAME_DATA_RUN : {
        KEEP(*(.window))
        *(.data .data.*)
        . = ALIGN(4);
    }
    __data_end = .;

    .bss : {
        *(.bss .bss.* COMMON)
        . = ALIGN(4);
    }
    __bss_end = .;

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.note*) }
}
