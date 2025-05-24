/**
 * Copyright (c) 2025 Remko Kleinjan
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#pragma once
#include <stdint.h>       // for uint32_t
#include "hardware/pio.h" // for PIO, pio_src_dest, pio_encode_*

void on_transfer_program_init(PIO pio, uint sm, uint offset, uint clk_pin, uint cs_pin, uint out_pin);
void clocked_output_program_init(PIO pio, uint sm, uint offset, uint data_pin, uint clk_pin, uint cs_pin);
static inline void pio_load_and_start(PIO pio, uint sm, uint32_t count, pio_src_dest dest);