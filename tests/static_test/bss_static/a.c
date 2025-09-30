// Uninitialized static variable - should go to .bss
static int uninitialized_var;
static char buffer[256];

int func_a() {
    uninitialized_var++;
    buffer[0] = 'A';
    return uninitialized_var;
}
