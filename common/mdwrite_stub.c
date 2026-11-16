/* Harness-only replacement for the firmware's MDWrite(dev, lba, nSec, buf):
 * copies into the disk image mapped at 0x10000000 (internal) or 0x14000000 (microSD). Linked at MDWrite's address. */
__attribute__((section(".text.mdwrite")))
int mdwrite(unsigned dev, unsigned lba, unsigned n, const volatile unsigned char *buf)
{
    volatile unsigned char *d = (volatile unsigned char *)(((dev >> 16) == 4 ? 0x14000000u : 0x10000000u) + lba * 512u);
    n *= 512u;
    while (n--)
        *d++ = *buf++;
    return 0;
}
