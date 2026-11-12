cmake_minimum_required(VERSION 3.13...3.31)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Pull in Raspberry Pi Pico SDK 2 (must be before project)
include(pico_sdk_2_import.cmake)

# linker/memory_extra.incl uses the SDK's linker script overrides (SDK 2.3+)
if (PICO_SDK_VERSION_STRING VERSION_LESS "2.3.0")
    message(FATAL_ERROR "PicoBoot-DX needs Pico SDK 2.3.0 or newer (found ${PICO_SDK_VERSION_STRING})")
endif()

project(picoboot-dx 
    LANGUAGES C CXX ASM
)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

add_executable(picoboot-dx
    src/picoboot-dx.c
    src/pio.c
    src/led.c
    src/picoboot-dx.pio
)

# Extra warnings for our own sources only (the SDK sources are compiled into the same target)
set_source_files_properties(src/picoboot-dx.c src/pio.c src/led.c PROPERTIES
    COMPILE_OPTIONS "-Wall;-Wextra"
)

pico_generate_pio_header(picoboot-dx
    ${CMAKE_CURRENT_LIST_DIR}/src/picoboot-dx.pio
)

pico_set_program_name(picoboot-dx "picoboot-dx")
pico_set_program_description(picoboot-dx "RP2040/RP2350 based modchip for the Nintendo GameCube")
pico_set_program_version(picoboot-dx "0.11")
pico_set_program_url(picoboot-dx "https://github.com/r3mko/PicoBoot-DX")

if(NOT PICO_CYW43_SUPPORTED)
    pico_set_binary_type(picoboot-dx
        copy_to_ram
    )
endif()

pico_enable_stdio_uart(picoboot-dx 0)
pico_enable_stdio_usb(picoboot-dx 1)

target_include_directories(picoboot-dx PRIVATE
    src
)

target_link_libraries(picoboot-dx PRIVATE
    pico_stdlib
    hardware_pio
    hardware_dma
)

# Only link in the CYW43-LED driver on Pico W / Pico 2 W builds
if(PICO_CYW43_SUPPORTED)
    target_link_libraries(picoboot-dx PRIVATE
        pico_cyw43_arch_none
    )

    # The CYW43 is initialised at 250MHz, divide by 4 to keep its SPI clock
    # at 250 / 4 / 2 = 31.25MHz (max 50MHz) instead of the default 62.5MHz
    target_compile_definitions(picoboot-dx PRIVATE
        CYW43_PIO_CLOCK_DIV_INT=4
    )
endif()

# Payload region and symbols: linker/memory_extra.incl replaces the SDK's empty one
pico_add_linker_script_override_path(picoboot-dx ${CMAKE_CURRENT_LIST_DIR}/linker FILES memory_extra.incl)

pico_add_extra_outputs(picoboot-dx)
