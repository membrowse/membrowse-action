/* Test firmware for memory analysis - minimal embedded setup */

#include <stdint.h>

// Global variables in different sections
uint32_t global_data = 0x12345678;
uint32_t global_bss;
const uint32_t global_const = 0xDEADBEEF;

// Large buffers to create measurable memory usage
uint8_t large_buffer[1024];
const uint8_t large_const_buffer[512] = {0x01, 0x02, 0x03, 0x04};

// Function prototypes
void main(void);
void init_hardware(void);
void process_data(void);
void interrupt_handler(void);
void reset_handler(void);
void _exit(int status);

// Required system calls for minimal embedded system
void _exit(int status) {
    (void)status;
    while(1) {}
}

// Main function
void main(void) {
    init_hardware();
    
    // Simple loop to create some code
    while(1) {
        process_data();
        for(volatile int i = 0; i < 1000; i++) {
            global_data++;
        }
    }
}

// Hardware initialization function
void init_hardware(void) {
    // Initialize global variables
    global_bss = 0xAAAAAAAA;
    
    // Fill buffer with pattern
    for(int i = 0; i < sizeof(large_buffer); i++) {
        large_buffer[i] = i & 0xFF;
    }
}

// Data processing function
void process_data(void) {
    // Some computation to create meaningful symbols
    uint32_t temp = global_data;
    temp ^= global_const;
    temp += large_const_buffer[0];
    global_data = temp;
}

// Interrupt handler (typical embedded function)
void interrupt_handler(void) {
    global_bss ^= 0x55555555;
}

// Stack pointer (defined in linker script)
extern uint32_t _estack;

// Vector table for ARM Cortex-M
__attribute__((section(".isr_vector")))
const uint32_t vector_table[] = {
    (uint32_t)&_estack,        // Initial stack pointer
    (uint32_t)reset_handler,   // Reset handler
    (uint32_t)interrupt_handler, // NMI handler
    (uint32_t)interrupt_handler, // Hard fault handler
    // Add more vectors as needed...
};

// Reset handler - entry point
void reset_handler(void) {
    // Simple BSS initialization (avoid memset)
    extern uint32_t _sbss, _ebss;
    volatile uint32_t *p = &_sbss;
    while (p < &_ebss) {
        *p++ = 0;
    }
    
    // Simple data initialization (avoid memcpy) 
    extern uint32_t _sdata, _edata, _sidata;
    volatile uint32_t *src = &_sidata;
    volatile uint32_t *dst = &_sdata;
    while (dst < &_edata) {
        *dst++ = *src++;
    }
    
    main();
}