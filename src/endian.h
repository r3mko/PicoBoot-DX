#pragma once
#include <stdint.h>

// RP2040/RP2350 is little-endian; convert from little-endian to big-endian.
static inline uint32_t BigEndian32(uint32_t value) {
    return __builtin_bswap32(value);  // Compiles to a single REV instruction
}