/*
 * simple_program.c - Basic C program for testing memory analysis
 * 
 * This program contains various types of data that will show up in different
 * memory sections, making it useful for testing our memory analysis tools.
 */

#include <stdint.h>
#include "uart_driver.h"

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
    
    // Initialize UART with test configuration
    uart_config_t uart_cfg = {
        .baudrate = 115200,
        .data_bits = 8,
        .stop_bits = 1,
        .parity = 0
    };
    uart_init(&uart_cfg);
    
    // Test UART functionality
    const char test_msg[] = "Hello from UART!";
    uart_transmit(test_msg, sizeof(test_msg) - 1);
    
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
        
        // Check UART status
        uint8_t status = uart_get_status();
        if (status & UART_STATUS_ERROR) {
            error_flags |= 0x04;  // UART error flag
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

// UART driver implementation - functions declared in uart_driver.h
// Global variable definition (declared in header)
volatile uint32_t uart_tx_count = 0;

// Static variables for UART driver
static uart_config_t current_config;
static volatile uint8_t uart_status = 0;

// UART initialization function - DEFINED here, DECLARED in uart_driver.h
void uart_init(const uart_config_t *config)
{
    if (config) {
        current_config = *config;
        uart_status = UART_STATUS_TX_READY | UART_STATUS_RX_READY;
        uart_tx_count = 0;
    }
}

// UART transmit function - DEFINED here, DECLARED in uart_driver.h
int uart_transmit(const char *data, uint32_t length)
{
    if (!data || length == 0) {
        return -1;
    }
    
    // Simulate transmission
    for (uint32_t i = 0; i < length; i++) {
        // Simulate sending byte
        volatile char dummy = data[i];
        dummy++; // Use the variable to prevent optimization
        uart_tx_count++;
    }
    
    return (int)length;
}

// UART receive function - DEFINED here, DECLARED in uart_driver.h  
int uart_receive(char *buffer_ptr, uint32_t max_length)
{
    if (!buffer_ptr || max_length == 0) {
        return -1;
    }
    
    // Simulate receiving some test data
    const char test_data[] = "Test UART data";
    uint32_t data_len = sizeof(test_data) - 1; // Exclude null terminator
    
    if (data_len > max_length) {
        data_len = max_length;
    }
    
    for (uint32_t i = 0; i < data_len; i++) {
        buffer_ptr[i] = test_data[i];
    }
    
    return (int)data_len;
}

// UART status function - DEFINED here, DECLARED in uart_driver.h
uint8_t uart_get_status(void)
{
    return uart_status;
}