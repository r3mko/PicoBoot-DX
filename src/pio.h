/**
 * Copyright (c) 2025 Remko Kleinjan
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#pragma once
#include <stdint.h>
#include "hardware/pio.h"

void on_transfer_program_init(PIO pio, uint sm, uint offset, uint clk_pin, uint cs_pin);
void clocked_output_program_init(PIO pio, uint sm, uint offset, uint clk_pin, uint cs_pin, uint data_pin);
void pio_prepare_transfer(PIO pio, uint sm, uint32_t count, uint dest);
