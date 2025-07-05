/*
 * simple_program.c - Basic C program for testing memory analysis
 * 
 * This program contains various types of data that will show up in different
 * memory sections, making it useful for testing our memory analysis tools.
 */

#include <stdint.h>

// Initialized data (goes to .data section)
volatile uint32_t global_counter = 42;
const char version_string[] = "v1.0.0";

// Uninitialized data (goes to .bss section)
static uint8_t buffer[256];
volatile uint32_t error_flags;

// Read-only data (goes to .rodata section)
const uint32_t lookup_table[16] = {
    0x00000001, 0x00000002, 0x00000004, 0x00000008,
    0x00000010, 0x00000020, 0x00000040, 0x00000080,
    0x00000100, 0x00000200, 0x00000400, 0x00000800,
    0x00001000, 0x00002000, 0x00004000, 0x00008000
};

// Function prototypes
void initialize_system(void);
uint32_t calculate_checksum(const uint8_t *data, uint32_t length);
void delay_ms(uint32_t milliseconds);

// Main function (goes to .text section)
int main(void)
{
    // Initialize system
    initialize_system();
    
    // Main application loop
    while (1) {
        // Increment counter
        global_counter++;
        
        // Calculate checksum of buffer
        uint32_t checksum = calculate_checksum(buffer, sizeof(buffer));
        
        // Update error flags based on checksum
        if (checksum == 0) {
            error_flags |= 0x01;  // Buffer empty flag
        } else {
            error_flags &= ~0x01; // Clear empty flag
        }
        
        // Small delay
        delay_ms(100);
        
        // Break after some iterations for testing
        if (global_counter > 1000) {
            break;
        }
    }
    
    return 0;
}

// System initialization function
void initialize_system(void)
{
    // Clear error flags
    error_flags = 0;
    
    // Initialize buffer with test pattern
    for (uint32_t i = 0; i < sizeof(buffer); i++) {
        buffer[i] = (uint8_t)(i & 0xFF);
    }
}

// Simple checksum calculation
uint32_t calculate_checksum(const uint8_t *data, uint32_t length)
{
    uint32_t sum = 0;
    
    for (uint32_t i = 0; i < length; i++) {
        sum += data[i];
        sum ^= lookup_table[i & 0x0F]; // Use lookup table
    }
    
    return sum;
}

// Simple delay function
void delay_ms(uint32_t milliseconds)
{
    // Simple busy-wait delay (not accurate, just for testing)
    volatile uint32_t count = milliseconds * 1000;
    while (count--) {
        // Do nothing, just consume cycles - portable version
        volatile int dummy = 0;
        dummy++;
    }
}

// Interrupt handler example (goes to .text section)
// Note: removed interrupt attribute for portability
void timer_interrupt_handler(void)
{
    // Simple interrupt handler
    global_counter++;
    error_flags &= ~0x02; // Clear timeout flag
}

// Another function to add more code size
void utility_function(void)
{
    // Some utility operations
    uint32_t temp = 0;
    
    for (int i = 0; i < 10; i++) {
        temp += lookup_table[i];
        buffer[i] = (uint8_t)(temp & 0xFF);
    }
    
    global_counter += temp;
}