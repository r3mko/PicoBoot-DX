cmake_minimum_required(VERSION 3.13)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Pull in Raspberry Pi Pico SDK 2 (must be before project)
include(pico_sdk_2_import.cmake)

project(picoboot-dx C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

# —————————————————————————————————————
#    Configure OTA flag
# —————————————————————————————————————
set(ENABLE_OTA OFF)
if (PICO_BOARD STREQUAL "pico_w" OR PICO_BOARD STREQUAL "pico2_w")
    set(ENABLE_OTA ON)
endif()

# —————————————————————————————————————
#    Define your executable (now that we know all sources)
# —————————————————————————————————————
add_executable(picoboot-dx
    src/picoboot-dx.c
    src/pio.c
    src/ota.c          # ← include OTA code always; it'll compile to stubs if disabled
)

# Generate PIO headers, metadata, stdio, etc.
pico_generate_pio_header(picoboot-dx ${CMAKE_CURRENT_LIST_DIR}/src/picoboot-dx.pio)
pico_set_program_name(picoboot-dx "picoboot-dx")
pico_set_program_description(picoboot-dx "RP2040/RP2350 based modchip for the Nintendo GameCube")
pico_set_program_version(picoboot-dx "0.6")
pico_set_program_url(picoboot-dx "https://github.com/r3mko/PicoBoot-DX")
pico_set_binary_type(picoboot-dx copy_to_ram)

pico_enable_stdio_uart(picoboot-dx 0)
pico_enable_stdio_usb(picoboot-dx 1)

#target_include_directories(picoboot-dx PRIVATE src)

target_include_directories(picoboot-dx PRIVATE
    src
    ${PICO_SDK_PATH}/lib/lwip/src/include
    ${PICO_SDK_PATH}/src/rp2_common/pico_lwip/include
)

# —————————————————————————————————————
#    Global compile-time flag for OTA
# —————————————————————————————————————
target_compile_definitions(picoboot-dx
    PRIVATE ENABLE_OTA=${ENABLE_OTA}
)

# —————————————————————————————————————
#    Core libraries
# —————————————————————————————————————
target_link_libraries(picoboot-dx
    PRIVATE pico_stdlib
            hardware_pio
            hardware_dma
)

# —————————————————————————————————————
#    Only link the extra networking/flash bits when OTA is enabled
# —————————————————————————————————————
if (ENABLE_OTA)
    target_link_libraries(picoboot-dx
        PRIVATE pico_cyw43_arch_lwip_threadsafe_background
                pico_lwip_httpd
                hardware_flash
                hardware_sync
    )
endif()

# Produce UF2, map/bin, etc.
pico_add_extra_outputs(picoboot-dx)
