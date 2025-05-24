/**
 * Copyright (c) 2025 Remko Kleinjan
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "led.h"
#include "pico/time.h"

#ifdef CYW43_WL_GPIO_LED_PIN
#include "pico/cyw43_arch.h"
#define LED_PIN CYW43_WL_GPIO_LED_PIN // WL chip’s LED on Pico W / Pico 2 W
#else
#include "hardware/gpio.h"
#define LED_PIN PICO_DEFAULT_LED_PIN  // GPIO25 on Pico / Pico 2
#endif

void led_init(void) {
#ifdef CYW43_WL_GPIO_LED_PIN
    cyw43_arch_init();
    cyw43_arch_gpio_put(LED_PIN, true);
#else
    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);
    gpio_put(LED_PIN, true);
#endif
}

void led_set(bool on) {
#ifdef CYW43_WL_GPIO_LED_PIN
    cyw43_arch_gpio_put(LED_PIN, on);
#else
    gpio_put(LED_PIN, on);
#endif
}

void led_blink(uint count, uint on_ms, uint off_ms) {
    for (uint i = 0; i < count; i++) {
        led_set(false);
        sleep_ms(on_ms);
        led_set(true);
        sleep_ms(off_ms);
    }
}

void led_blink_while(bool (*condition)(void), uint on_ms, uint off_ms) {
    while (condition()) {
        led_set(false);
        sleep_ms(on_ms);
        led_set(true);
        sleep_ms(off_ms);
    }
}
