// Uninitialized static variable - should go to .bss
static int uninitialized_var;
static char buffer[256];

int func_a();

int func_b() {
    uninitialized_var++;
    buffer[0] = 'B';
    return uninitialized_var;
}

int main() {
    return func_a() + func_b();
}
