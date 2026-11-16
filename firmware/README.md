# Put your stock firmware here

This project does not include Hidizs firmware. Download the official AP30
update from the [Hidizs download center](https://www.hidizs.net/pages/download-center)
and place the image here as:

    firmware/HIFIYF18.IMG

Everything in this folder except this file is ignored by git.

The tools were written against **v1.7.8 only**:

| | |
|---|---|
| File | `HIFIYF18.IMG` |
| Header date | 2026-10-19 |
| Size | 29,360,132 bytes |
| SHA-256 | `c7601873cb3be8d1320225c69669e504576f7bcb1126595a9040492338e79840` |

The emulator modules call firmware functions at fixed addresses, so the build
scripts check this hash and refuse any other version. Check your copy with:

    python ap30.py info
