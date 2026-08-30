cmake_minimum_required(VERSION 3.13)
include($ENV{PICO_SDK_PATH}/pico_sdk_init.cmake)
project(pps_pico C CXX ASM)
pico_sdk_init()

add_executable(pps_pico pps_pico.c)
pico_generate_pio_header(pps_pico ${CMAKE_CURRENT_LIST_DIR}/ppscap.pio)

# External 25 MHz OCXO-derived clock on XIN (crystal removed).
target_compile_definitions(pps_pico PRIVATE
    XOSC_MHZ=25
    PICO_XOSC_STARTUP_DELAY_MULTIPLIER=64
    PICO_FLASH_SPI_CLKDIV=4
    # SDK boot clocks from the 25 MHz source: conservative 100 MHz at stock
    # voltage (VCO 25*48=1200 MHz, /3/4); main() raises vreg and re-locks
    # to 200 MHz (/3/2). USB PLL: 1200/5/5 = 48 MHz (unused but required).
    SYS_CLK_HZ=100000000
    PLL_SYS_VCO_FREQ_HZ=1200000000
    PLL_SYS_POSTDIV1=3
    PLL_SYS_POSTDIV2=4
    USB_CLK_HZ=48000000
    PLL_USB_VCO_FREQ_HZ=1200000000
    PLL_USB_POSTDIV1=5
    PLL_USB_POSTDIV2=5
)

target_link_libraries(pps_pico pico_stdlib hardware_pio hardware_pll
                      hardware_clocks hardware_vreg hardware_uart)
pico_add_extra_outputs(pps_pico)
# UART is driven manually; no stdio retargeting needed.
pico_enable_stdio_usb(pps_pico 0)
pico_enable_stdio_uart(pps_pico 0)
