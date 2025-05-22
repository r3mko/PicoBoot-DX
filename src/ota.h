#pragma once

#ifdef ENABLE_OTA
// initialize Wi-Fi AP and HTTP upload server
void ota_init(void);
// call periodically from your main loop to service network
void ota_poll(void);
#else
// stubs expand to nothing when OTA is disabled
static inline void ota_init(void) {}
static inline void ota_poll(void) {}
#endif
