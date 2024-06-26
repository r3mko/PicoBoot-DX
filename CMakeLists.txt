cmake_minimum_required(VERSION 3.13...3.28)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Pull in Raspberry Pi Pico SDK (must be before project)
include(pico_sdk_import.cmake)

project(picoboot-dx C CXX ASM)

# Initialise the Raspberry Pi Pico SDK
pico_sdk_init()

add_executable(picoboot-dx src/picoboot-dx.c src/pio.c)

pico_generate_pio_header(picoboot-dx  
        ${CMAKE_CURRENT_LIST_DIR}/src/picoboot-dx.pio
)

pico_set_program_name(picoboot-dx "picoboot-dx")
pico_set_program_version(picoboot-dx "0.3")
pico_set_binary_type(picoboot-dx copy_to_ram)

pico_enable_stdio_uart(picoboot-dx 0)
pico_enable_stdio_usb(picoboot-dx 1)

target_include_directories(picoboot-dx PRIVATE src)

target_link_libraries(picoboot-dx PRIVATE pico_stdlib hardware_pio hardware_dma)

pico_add_extra_outputs(picoboot-dx)