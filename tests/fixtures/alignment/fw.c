/* Firmware for the --exclude-alignment tests; see build.sh. */

/* An embedded image without a symbol, like an .incbin'd kernel. */
__asm__(".section .kernel_blob,\"a\"\n"
        ".fill 0x123, 1, 0xab\n"
        ".previous\n");

volatile int counter = 5;
int table[3] = {1, 2, 3};
static const char banner[] = "membrowse alignment test";

const char *msg(void) { return "unlabelled string literal at end"; }

int add(int a, int b) { return a + b + counter + table[1] + banner[0]; }

void Reset_Handler(void)
{
    while (1) {
        counter = add(counter, 1);
        msg();
    }
}
