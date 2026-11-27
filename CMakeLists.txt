# Copyright (c) 2025 FredForte
# SPDX-License-Identifier: MIT

if(CONFIG_ZMK_BATTERY_NRF_VDDH_NO_OS)
    zephyr_library()
    zephyr_library_sources(drivers/sensor/battery_nrf_vddh_no_os.c)
endif()
