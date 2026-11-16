/* Harness-only replacement for the firmware's MDRead(dev, lba, nSec, buf):
 * copies from a disk image mapped at 0x10000000 (internal) or 0x14000000 (microSD). Linked at MDRead's address. */
__attribute__((section(".text.mdread")))
int mdread(unsigned dev, unsigned lba, unsigned n, volatile unsigned char *buf)
{
    const volatile unsigned char *s = (const volatile unsigned char *)(((dev >> 16) == 4 ? 0x14000000u : 0x10000000u) + lba * 512u);
    n *= 512u;
    while (n--)
        *buf++ = *s++;
    return 0;
}
