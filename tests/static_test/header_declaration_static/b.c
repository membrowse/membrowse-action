#include "c.h"

int func_a();

int func_b() {
    return foo + 2;
}

int main() {
    return func_a() + func_b();
}
