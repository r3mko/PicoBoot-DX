#ifndef LED_H
#define LED_H

#include <stdbool.h>
#include "pico/stdlib.h"

// Initialize the onboard LED (and Wi-Fi LED on Pico W)
void led_init(void);

// Turn the LED on or off
void led_set(bool on);

// Blink the LED `count` times with on/off delays in ms
void led_blink(uint count, uint on_ms, uint off_ms);

// While `condition()` returns true, blink the LED with on/off delays
// This can be used to show “activity” while waiting.
void led_blink_while(bool (*condition)(void), uint on_ms, uint off_ms);

#endif // LED_H
