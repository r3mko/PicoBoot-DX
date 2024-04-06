/**
 * Copyright (c) 2022 Maciej Kobus
 * Copyright (c) 2023 Remko Kleinjan
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/structs/bus_ctrl.h"
#include "pio.h"
#include "picoboot-dx.pio.h"
#include "ipl.h"

const uint PIN_CS = 4;              // U10 chip select
const uint PIN_CLK = 5;             // EXI bus clock line
const uint PIN_DATA_BASE = 6;       // Base pin used for output, 1 consecutive pin is used 
const uint PIN_LED = 25;            // Status LED

const uint BOOST_CLOCK = 250000;    // Set 250MHz clock to get more cycles. 

void main() {
    // Initialize and light up builtin LED, it will basically
    // act as a power LED.
    // TODO: Use the LED to signalize system faults?
    gpio_init(PIN_LED);
    gpio_set_dir(PIN_LED, GPIO_OUT);
    gpio_put(PIN_LED, true);

    // Set 250MHz clock to get more cycles in between CLK pulses.
    // This is the lowest value I was able to make the code work.
    // Should be still considered safe for most Pico boards.
    set_sys_clock_khz(BOOST_CLOCK, true);

    // Prioritize DMA engine as it does the most work
    bus_ctrl_hw->priority = BUSCTRL_BUS_PRIORITY_DMA_W_BITS | BUSCTRL_BUS_PRIORITY_DMA_R_BITS;

    gpio_set_slew_rate(PIN_DATA_BASE, GPIO_SLEW_RATE_FAST);

    gpio_set_drive_strength(PIN_DATA_BASE, GPIO_DRIVE_STRENGTH_8MA);

    PIO pio = pio0;

    //
    // State Machine: Transfer Start
    //
    // Counts all consecutive transfers and sets IRQ 
    // when first 1 kilobyte transfer starts.
    //

    uint transfer_start_sm = pio_claim_unused_sm(pio, true);
    uint transfer_start_offset = pio_add_program(pio, &on_transfer_program);

    on_transfer_program_init(pio, transfer_start_sm, transfer_start_offset, PIN_CLK, PIN_CS, PIN_DATA_BASE);

    pio_sm_put(pio, transfer_start_sm, (uint32_t) 224); // CS pulses
    pio_sm_exec(pio, transfer_start_sm, pio_encode_pull(true, true));
    pio_sm_exec(pio, transfer_start_sm, pio_encode_mov(pio_x, pio_osr));
    pio_sm_exec(pio, transfer_start_sm, pio_encode_out(pio_null, 32));

    //
    // State Machine: Clocked Output
    // 
    // It waits for IRQ signal from first SM and samples clock signal
    // to output IPL data bits.
    //

    uint clocked_output_sm = pio_claim_unused_sm(pio, true);
    uint clocked_output_offset = pio_add_program(pio, &clocked_output_program);

    clocked_output_program_init(pio, clocked_output_sm, clocked_output_offset, PIN_DATA_BASE, PIN_CLK, PIN_CS);

    pio_sm_put(pio, clocked_output_sm, 8191); // 8192 bits, 1024 bytes, minus 1 because counting starts from 0 
    pio_sm_exec(pio, clocked_output_sm, pio_encode_pull(true, true));
    pio_sm_exec(pio, clocked_output_sm, pio_encode_mov(pio_y, pio_osr));
    pio_sm_exec(pio, clocked_output_sm, pio_encode_out(pio_null, 32));

    // Set up DMA for reading IPL to PIO FIFO
    int chan = dma_claim_unused_channel(true);

    dma_channel_config c = dma_channel_get_default_config(chan);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, true);
    channel_config_set_write_increment(&c, false);
    channel_config_set_dreq(&c, pio_get_dreq(pio, clocked_output_sm, true));

    dma_channel_configure(
        chan,
        &c,
        &pio->txf[clocked_output_sm],
        ipl,
        count_of(ipl),
        true // start immediately
    );

    // Start PIO state machines
    pio_sm_set_enabled(pio, transfer_start_sm, true);
    pio_sm_set_enabled(pio, clocked_output_sm, true);

    // Wait for the DMA to finish
    //dma_channel_wait_for_finish_blocking(chan);
    // Blink fast while waiting
    while (dma_channel_is_busy(chan)) {
        gpio_put(PIN_LED, false);
        sleep_ms(100);
        gpio_put(PIN_LED, true);
        sleep_ms(100);
    }

    // Reset clock to default
    set_sys_clock_khz((BOOST_CLOCK / 2), true);
    
    // Stop PIO state machines
    pio_sm_set_enabled(pio, transfer_start_sm, false);
    pio_sm_set_enabled(pio, clocked_output_sm, false);

    // Blink slow (3 times) when done
    for (uint BLINK = 0; BLINK < 3; BLINK++) {
        gpio_put(PIN_LED, false);
        sleep_ms(250);
        gpio_put(PIN_LED, true);
        sleep_ms(250);
    }

    while (true) {
        tight_loop_contents();
    }
}
