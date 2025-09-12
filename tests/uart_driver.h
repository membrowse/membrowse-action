/*
 * uart_driver.h - UART driver header for testing source file mapping
 * 
 * This header declares functions that will be defined in the C file,
 * allowing us to test whether the source file mapping captures
 * declaration vs definition locations.
 */

#ifndef UART_DRIVER_H
#define UART_DRIVER_H

#include <stdint.h>

// UART configuration structure
typedef struct {
    uint32_t baudrate;
    uint8_t data_bits;
    uint8_t stop_bits;
    uint8_t parity;
} uart_config_t;

// UART status flags  
#define UART_STATUS_TX_READY    0x01
#define UART_STATUS_RX_READY    0x02
#define UART_STATUS_ERROR       0x04

// Function declarations - these will be defined in simple_program.c
void uart_init(const uart_config_t *config);
int uart_transmit(const char *data, uint32_t length);
int uart_receive(char *buffer, uint32_t max_length);
uint8_t uart_get_status(void);

// Global variable declaration - defined in simple_program.c
extern volatile uint32_t uart_tx_count;

#endif /* UART_DRIVER_H */