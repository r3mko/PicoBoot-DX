/**
 * Copyright (c) 2025 Remko Kleinjan
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#pragma once
#include <stdbool.h>
#include "pico/types.h"

// Initialize the onboard LED (and Wi-Fi LED on Pico W)
void led_init(void);

// Turn the LED on or off
void led_set(bool on);

// Blink the LED `count` times with on/off delays in ms
void led_blink(uint count, uint on_ms, uint off_ms);

// While `condition()` returns true, blink the LED with on/off delays
// This can be used to show “activity” while waiting.
void led_blink_while(bool (*condition)(void), uint on_ms, uint off_ms);
