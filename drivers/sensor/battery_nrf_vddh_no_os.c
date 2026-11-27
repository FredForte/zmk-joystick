/*
 * Copyright (c) 2021 The ZMK Contributors
 * Copyright (c) 2025 FredForte
 *
 * SPDX-License-Identifier: MIT
 *
 * Replacement for ZMK's zmk,battery-nrf-vddh sensor driver that sets
 * adc_sequence.oversampling = 0. On nRF52840, SAADC hardware does not support
 * oversampling when sharing the peripheral with multi-channel analog inputs
 * (such as a 2-axis joystick), which otherwise causes ADC reads to freeze on
 * the first 60-second battery poll.
 */

#define DT_DRV_COMPAT zmk_battery_nrf_vddh_no_os

#include <errno.h>
#include <stdint.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(battery_nrf_vddh_no_os, CONFIG_SENSOR_LOG_LEVEL);

#define VDDHDIV (5)

static const struct device *adc = DEVICE_DT_GET(DT_NODELABEL(adc));

struct battery_value {
    uint16_t adc_raw;
    uint16_t millivolts;
    uint8_t state_of_charge;
};

struct vddh_no_os_data {
    struct adc_channel_cfg acc;
    struct adc_sequence as;
    struct battery_value value;
};

static uint8_t lithium_ion_mv_to_pct(int16_t bat_mv) {
    /* Simple linear approximation based on Adafruit's LiPo discharge curve */
    if (bat_mv >= 4200) {
        return 100;
    } else if (bat_mv <= 3450) {
        return 0;
    }

    return (uint8_t)(bat_mv * 2 / 15 - 459);
}

static int vddh_no_os_sample_fetch(const struct device *dev, enum sensor_channel chan) {
    if (chan != SENSOR_CHAN_GAUGE_VOLTAGE && chan != SENSOR_CHAN_GAUGE_STATE_OF_CHARGE &&
        chan != SENSOR_CHAN_ALL) {
        LOG_DBG("Selected channel is not supported: %d.", chan);
        return -ENOTSUP;
    }

    struct vddh_no_os_data *drv_data = dev->data;
    struct adc_sequence *as = &drv_data->as;

    int rc = adc_read(adc, as);
    as->calibrate = false;

    if (rc != 0) {
        LOG_ERR("Failed to read ADC: %d", rc);
        return rc;
    }

    int32_t val = drv_data->value.adc_raw;
    rc = adc_raw_to_millivolts(adc_ref_internal(adc), drv_data->acc.gain, as->resolution, &val);
    if (rc != 0) {
        LOG_ERR("Failed to convert raw ADC to mV: %d", rc);
        return rc;
    }

    drv_data->value.millivolts = (uint16_t)(val * VDDHDIV);
    drv_data->value.state_of_charge = lithium_ion_mv_to_pct(drv_data->value.millivolts);

    LOG_DBG("ADC raw %d ~ %d mV => %d%%", drv_data->value.adc_raw, drv_data->value.millivolts,
            drv_data->value.state_of_charge);

    return 0;
}

static int vddh_no_os_channel_get(const struct device *dev, enum sensor_channel chan,
                                  struct sensor_value *val_out) {
    const struct vddh_no_os_data *drv_data = dev->data;

    switch (chan) {
    case SENSOR_CHAN_GAUGE_VOLTAGE:
        val_out->val1 = drv_data->value.millivolts / 1000;
        val_out->val2 = (drv_data->value.millivolts % 1000) * 1000U;
        break;

    case SENSOR_CHAN_GAUGE_STATE_OF_CHARGE:
        val_out->val1 = drv_data->value.state_of_charge;
        val_out->val2 = 0;
        break;

    default:
        return -ENOTSUP;
    }

    return 0;
}

static const struct sensor_driver_api vddh_no_os_api = {
    .sample_fetch = vddh_no_os_sample_fetch,
    .channel_get = vddh_no_os_channel_get,
};

static int vddh_no_os_init(const struct device *dev) {
    struct vddh_no_os_data *drv_data = dev->data;

    if (!device_is_ready(adc)) {
        LOG_ERR("ADC device is not ready %s", adc->name);
        return -ENODEV;
    }

    /*
     * Use SAADC slot 1 (AIN1 / P0.03 is not broken out on nice!nano v2) so
     * battery sensing never collides with external analog pins (AIN0/5/7).
     */
    drv_data->as = (struct adc_sequence){
        .channels = BIT(1),
        .buffer = &drv_data->value.adc_raw,
        .buffer_size = sizeof(drv_data->value.adc_raw),
        .oversampling = 0,
        .calibrate = true,
    };

#ifdef CONFIG_ADC_NRFX_SAADC
    drv_data->acc = (struct adc_channel_cfg){
        .gain = ADC_GAIN_1_2,
        .reference = ADC_REF_INTERNAL,
        .acquisition_time = ADC_ACQ_TIME(ADC_ACQ_TIME_MICROSECONDS, 40),
        .channel_id = 1,
        .input_positive = SAADC_CH_PSELN_PSELN_VDDHDIV5,
    };

    drv_data->as.resolution = 12;
#else
#error Unsupported ADC
#endif

    const int rc = adc_channel_setup(adc, &drv_data->acc);
    LOG_DBG("VDDHDIV5 (no oversampling) setup returned %d", rc);

    return rc;
}

static struct vddh_no_os_data vddh_no_os_data;

DEVICE_DT_INST_DEFINE(0, &vddh_no_os_init, NULL, &vddh_no_os_data, NULL, POST_KERNEL,
                      CONFIG_SENSOR_INIT_PRIORITY, &vddh_no_os_api);
