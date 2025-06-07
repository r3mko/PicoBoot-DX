/**
 * Copyright (c) 2022 Maciej Kobus
 * Copyright (c) 2025 Remko Kleinjan
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/structs/bus_ctrl.h"

#include "pio.h"
#include "picoboot-dx.pio.h"
#include "ipl.h"
#include "led.h"

const uint PIN_CS = 4;              // U10 chip select
const uint PIN_CLK = 5;             // EXI bus clock line
const uint PIN_DATA = 6;            // Data pin used for output 

const uint BOOST_CLOCK = 250000;    // Set 250MHz clock to get more cycles. 

int chan;

bool dma_busy(void) {
    // Wrap the Pico SDK call so we can pass it to led_blink_while()
    return dma_channel_is_busy(chan);
}

void main() {
    // Set 250MHz clock to get more cycles in between CLK pulses.
    // This is the lowest value I was able to make the code work.
    // Should be still considered safe for most Pico boards.
    set_sys_clock_khz(BOOST_CLOCK, true);

    // Prioritize DMA engine as it does the most work
    bus_ctrl_hw->priority = BUSCTRL_BUS_PRIORITY_DMA_W_BITS | BUSCTRL_BUS_PRIORITY_DMA_R_BITS;

    gpio_set_slew_rate(PIN_DATA, GPIO_SLEW_RATE_FAST);
    gpio_set_drive_strength(PIN_DATA, GPIO_DRIVE_STRENGTH_8MA);

    PIO pio = pio0;

    //
    // State Machine: Transfer Start
    //
    // Counts all consecutive transfers and sets IRQ 
    // when first 1 kilobyte transfer starts.
    //

    uint transfer_start_sm = pio_claim_unused_sm(pio, true);
    uint transfer_start_offset = pio_add_program(pio, &on_transfer_program);

    on_transfer_program_init(pio, transfer_start_sm, transfer_start_offset, PIN_CLK, PIN_CS);
    // Wait for 224 CS pulses before firing the IRQ
    // this marks the boundary where the first 1 kB (1024 bytes) transfer is about to start
    pio_prepare_transfer(pio, transfer_start_sm, 224, pio_x);

    //
    // State Machine: Clocked Output
    // 
    // It waits for IRQ signal from first SM and samples clock signal
    // to output IPL data bits.
    //

    uint clocked_output_sm = pio_claim_unused_sm(pio, true);
    uint clocked_output_offset = pio_add_program(pio, &clocked_output_program);

    clocked_output_program_init(pio, clocked_output_sm, clocked_output_offset, PIN_DATA, PIN_CLK, PIN_CS);
    // Set up the clocked‐output SM to shift out 8192 bits (1024 bytes)
    // using 8191 here because the PIO countdown is zero-based
    pio_prepare_transfer(pio, clocked_output_sm, 8191, pio_y);

    // Set up DMA for reading IPL to PIO TX FIFO
    chan = dma_claim_unused_channel(true);

    dma_channel_config c = dma_channel_get_default_config(chan);
    // Set transfer size to 32 bits
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    // Read address increments (for array)
    channel_config_set_read_increment(&c, true);
    // Write address fixed (TX FIFO register)
    channel_config_set_write_increment(&c, false);
    // Use PIO TX FIFO as DMA trigger
    channel_config_set_dreq(&c, pio_get_dreq(pio, clocked_output_sm, true));

    dma_channel_configure(
        chan,                           // DMA channel
        &c,                             // Config
        &pio->txf[clocked_output_sm],   // Dest: PIO TX FIFO
        ipl,                            // Source: ipl array
        count_of(ipl),                  // Number of words
        true                            // Start immediately
    );

    // Start PIO state machines
    pio_sm_set_enabled(pio, transfer_start_sm, true);
    pio_sm_set_enabled(pio, clocked_output_sm, true);

    // Initialize and light up builtin LED
    led_init();

    // Blink fast while waiting
    led_blink_while(dma_busy, 20, 20);

    // Reset clock to default
    set_sys_clock_khz((BOOST_CLOCK / 2), true);
    
    // Stop PIO state machines
    pio_sm_set_enabled(pio, transfer_start_sm, false);
    pio_sm_set_enabled(pio, clocked_output_sm, false);

    // Blink slow (3 times) when done
    led_blink(3, 250, 250);

    // Idle
    while (true) {
        tight_loop_contents();
    }
}
