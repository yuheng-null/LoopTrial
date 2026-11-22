/* SPDX-License-Identifier: GPL-3.0-or-later
 * STM32F103C8T6, reset clock (8 MHz HSI). Register layout: ST RM0008 rev 21.
 * This example uses only USART pins and SysTick. All plant state lives in RAM.
 */
#include <stdint.h>
#include "looptrial.h"

#define REG32(a) (*(volatile uint32_t *)(a))
#define RCC_APB2ENR REG32(0x40021018)
#define RCC_APB1ENR REG32(0x4002101c)
#define GPIOA_CRL   REG32(0x40010800)
#define GPIOB_CRL   REG32(0x40010c00)
#define AFIO_MAPR   REG32(0x40010004)
#define SYST_CSR    REG32(0xe000e010)
#define SYST_RVR    REG32(0xe000e014)
#define SYST_CVR    REG32(0xe000e018)

typedef struct { volatile uint32_t sr, dr, brr, cr1; } uart;
#define USART1 ((uart *)0x40013800)
#define USART2 ((uart *)0x40004400)
static lt_decoder wired, radio;
static void put_byte(void *port, char byte) {
    uart *dev = port;
    while (!(dev->sr & (1u << 7))) {}
    dev->dr = (unsigned char)byte;
}
static void poll_uart(uart *dev, lt_decoder *decoder) {
    uint32_t status = dev->sr;
    if (status & ((1u << 5) | 0x0f)) {
        char byte = (char)dev->dr;
        if (status & 0x0f) decoder->discard = 1;
        lt_receive(decoder, byte, put_byte, dev);
    }
}
static void uart_init(uart *dev) {
    dev->brr = (8000000u + 4800u) / 9600u;
    dev->cr1 = (1u << 13) | (1u << 3) | (1u << 2);
}
static void run_board(void) {
    RCC_APB2ENR |= (1u << 0) | (1u << 2) | (1u << 3) | (1u << 14);
    RCC_APB1ENR |= (1u << 17);
    AFIO_MAPR |= 1u << 2;
    /* PA2,PB6: alternate-function push-pull 2 MHz. PA3,PB7: floating input. */
    GPIOA_CRL = (GPIOA_CRL & ~(0xffu << 8)) | (0x4au << 8);
    GPIOB_CRL = (GPIOB_CRL & ~(0xffu << 24)) | (0x4au << 24);
    uart_init(USART1);
    uart_init(USART2);
    /* Opaque per-unit reconnect check; never included in published records. */
    lt_init(REG32(0x1ffff7e8) ^ REG32(0x1ffff7ec) ^ REG32(0x1ffff7f0));
    SYST_RVR = 8000u - 1u;
    SYST_CVR = 0;
    SYST_CSR = 7;
    for (;;) {
        poll_uart(USART1, &radio);
        poll_uart(USART2, &wired);
    }
}
extern uint32_t _stack_top, _data_load, _data_start, _data_end, _bss_start, _bss_end;
void reset_handler(void) {
    uint32_t *src = &_data_load;
    for (uint32_t *dst = &_data_start; dst < &_data_end;) *dst++ = *src++;
    for (uint32_t *dst = &_bss_start; dst < &_bss_end;) *dst++ = 0;
    run_board();
}
static void fault(void) { for (;;) {} }
__attribute__((used,section(".vectors")))
const uintptr_t vectors[16] = {
    (uintptr_t)&_stack_top, (uintptr_t)reset_handler,
    (uintptr_t)fault, (uintptr_t)fault, (uintptr_t)fault, (uintptr_t)fault,
    (uintptr_t)fault, 0, 0, 0, 0, (uintptr_t)fault, (uintptr_t)fault, 0,
    (uintptr_t)fault, (uintptr_t)lt_tick
};
