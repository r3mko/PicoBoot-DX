#ifndef LWIPOPTS_H
#define LWIPOPTS_H

/* ---------- Platform specific locking ---------- */
#define NO_SYS                          0
#define SYS_LIGHTWEIGHT_PROT            1

/* ---------- Memory options ---------- */
#define MEM_ALIGNMENT                   4
#define MEM_SIZE                        (16 * 1024)

/* ---------- Pbuf options ---------- */
#define PBUF_POOL_SIZE                  8
#define PBUF_POOL_BUFSIZE               256

/* ---------- TCP options ---------- */
#define LWIP_TCP                        1
#define TCP_MSS                         1360
#define TCP_SND_BUF                     (2 * TCP_MSS)
#define TCP_WND                         (2 * TCP_MSS)
#define TCP_SND_QUEUELEN                (4 * TCP_SND_BUF/TCP_MSS)

/* ---------- ICMP options ---------- */
#define LWIP_ICMP                       1

/* ---------- DHCP options ---------- */
#define LWIP_DHCP                       1

/* ---------- DNS options ---------- */
#define LWIP_DNS                        1

/* ---------- UDP options ---------- */
#define LWIP_UDP                        1
#define UDP_TTL                         255

/* ---------- HTTPD options ---------- */
#define LWIP_HTTPD_SSI                  1
#define LWIP_HTTPD_CGI                  1
#define LWIP_HTTPD_CUSTOM_FILES         0

/* ---------- Stats options ---------- */
#define LWIP_STATS                      0

/* ---------- Debugging options ---------- */
#define LWIP_NOASSERT                   1

#endif /* LWIPOPTS_H */