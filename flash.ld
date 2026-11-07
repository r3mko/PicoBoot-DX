/*
 * Extra linker script, loaded after the SDK's memmap_*.ld.
 * The SDK already declares the FLASH region, so don't redeclare it here
 * (that causes "redeclaration of memory region `FLASH'").
 * The firmware occupies the first APP_SIZE bytes of flash, the payload follows.
 */
FLASH_SIZE = 2048K;
APP_SIZE   =  512K;

MEMORY
{
    PAYLOAD(r) : ORIGIN = ORIGIN(FLASH) + APP_SIZE, LENGTH = FLASH_SIZE - APP_SIZE
}

flash_payload     = ORIGIN(PAYLOAD);
flash_payload_end = ORIGIN(PAYLOAD) + LENGTH(PAYLOAD);

ASSERT(__flash_binary_end <= flash_payload, "picoboot-dx firmware is larger than APP_SIZE and overlaps the payload area")
