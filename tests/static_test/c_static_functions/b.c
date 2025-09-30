static int helper_function(int x) {
    return x * 3;
}

int func_a();

int func_b() {
    return helper_function(7);
}

int main() {
    return func_a() + func_b();
}
