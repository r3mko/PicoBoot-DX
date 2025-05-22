#include "ota.h"

#if ENABLE_OTA

#include <string.h>
#include "pico/stdlib.h"
#include "hardware/flash.h"
#include "hardware/sync.h"
#include "cyw43_arch.h"          // only pulled in when ENABLE_OTA=1
#include "cyw43_arch_lwip.h"
#include "lwip/apps/httpd.h"
#include "lwip/err.h"
#include "lwip/pbuf.h"

// --- UF2 parsing helpers (512-byte blocks) ------------------

#define UF2_BLOCK_SIZE 512
#define FLASH_TARGET_OFFSET   0x1000000  // adjust to your firmware region
static uint32_t write_addr = FLASH_TARGET_OFFSET;

static void write_uf2_block(const uint8_t *block) {
    // parse target addr from UF2 header (little endian at offset 12)
    uint32_t addr = *(uint32_t*)(block + 12);
    const uint8_t *data = block + 32;
    uint32_t n_words = (UF2_BLOCK_SIZE - 32) / 4;
    uint32_t ints[n_words];
    memcpy(ints, data, n_words*4);

    uint32_t cs = save_and_disable_interrupts();
    flash_range_program(addr, data, n_words*4);
    restore_interrupts(cs);
}

// --- HTTP upload handler ------------------------------------

static const char upload_html[] =
"<html><body>"
"<h1>Picoboot-dx OTA</h1>"
"<form method=\"POST\" action=\"/upload\" enctype=\"multipart/form-data\">"
"<input type=\"file\" name=\"firmware\"/><br><br>"
"<input type=\"submit\" value=\"Upload UF2\">"
"</form></body></html>";

static err_t http_get_index(struct httpd_state *s, struct pbuf *p) {
    httpd_resp_send(s, upload_html, sizeof(upload_html)-1);
    return ERR_OK;
}

static err_t http_post_upload(struct httpd_state *s, struct pbuf *p) {
    // we assume the POST body *is* raw UF2 blocks (no multipart parsing for POC)
    struct pbuf *q = p;
    while (q) {
        uint8_t *payload = (uint8_t*)q->payload;
        size_t len = q->len;
        // process in 512-byte chunks
        for (size_t off = 0; off + UF2_BLOCK_SIZE <= len; off += UF2_BLOCK_SIZE) {
            write_uf2_block(payload + off);
        }
        q = q->next;
    }
    // reply and ask user to reset manually
    const char msg[] = "<html><body><h2>Upload complete. Please reset device.</h2></body></html>";
    httpd_resp_send(s, msg, sizeof(msg)-1);
    return ERR_OK;
}

static const tCGI cgi_handlers[] = {
    { "/", http_get_index },
};

static const TCGIUpload upload_handlers[] = {
    { "/upload", http_post_upload }
};

void ota_init(void) {
    // bring up CYW43 & start AP
    cyw43_arch_init();
    cyw43_arch_enable_ap_mode(& (cyw43_wifi_ap_config_t) {
        .ssid = "Picoboot-dx",
        .password = "picoboot-dx123",
        .channel = 1,
        .security = CYW43_SECURITY_WPA2_AES_PSK
    });

    // start LWIP HTTPD
    httpd_init();
    http_set_cgi_handlers(cgi_handlers, 1);
    httpd_register_upload_handler(upload_handlers, 1);
    printf("OTA service running at http://192.168.4.1/\n");
}

void ota_poll(void) {
    // service lwip timers / background
    cyw43_arch_poll();
    // httpd is called internally by lwip’s timers
}

#endif  // ENABLE_OTA
