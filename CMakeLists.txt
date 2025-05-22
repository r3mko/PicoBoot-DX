cmake_minimum_required(VERSION 3.13...3.31)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Pull in Raspberry Pi Pico SDK 2 (must be before project)
include(pico_sdk_2_import.cmake)

project(picoboot-dx C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

add_executable(picoboot-dx src/picoboot-dx.c src/pio.c)

pico_generate_pio_header(picoboot-dx ${CMAKE_CURRENT_LIST_DIR}/src/picoboot-dx.pio)

pico_set_program_name(picoboot-dx "picoboot-dx")
pico_set_program_description(picoboot-dx "RP2040/RP2350 based modchip for the Nintendo GameCube")
pico_set_program_version(picoboot-dx "0.6")
pico_set_program_url(picoboot-dx "https://github.com/r3mko/PicoBoot-DX")
pico_set_binary_type(picoboot-dx copy_to_ram)

pico_enable_stdio_uart(picoboot-dx 0)
pico_enable_stdio_usb(picoboot-dx 1)

target_include_directories(picoboot-dx PRIVATE src)

target_link_libraries(picoboot-dx PRIVATE pico_stdlib hardware_pio hardware_dma)

# Only link in the CYW43-LED driver on Pico W / Pico 2 W builds
if(PICO_CYW43_SUPPORTED)
    target_link_libraries(picoboot-dx PRIVATE pico_cyw43_arch_none)
endif()

pico_add_extra_outputs(picoboot-dx)
