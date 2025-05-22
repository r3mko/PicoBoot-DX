#pragma once

#include <stdint.h>

#if ENABLE_OTA

// Real declarations only when ENABLE_OTA==1
void ota_init(void);
void ota_poll(void);

#else

// Stub inlines when ENABLE_OTA==0
static inline void ota_init(void) {}
static inline void ota_poll(void) {}

#endif  // ENABLE_OTA
