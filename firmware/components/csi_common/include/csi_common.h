#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Fixed MAC of the sender. The receiver only accepts CSI from this address. */
extern const uint8_t CSI_TX_MAC[6];

/**
 * Initialise NVS, netif, event loop and Wi-Fi (station mode, HT20, fixed channel,
 * power save off). The Wi-Fi driver is started but NOT connected to any AP.
 *
 * @param is_sender true: use CSI_TX_MAC as station MAC and apply CONFIG_CSI_TX_POWER_QDBM.
 */
esp_err_t csi_wifi_start(bool is_sender);

/**
 * Initialise ESP-NOW with a broadcast peer on the CSI channel, HT20 / MCS0 long GI.
 * Must be called after csi_wifi_start().
 */
esp_err_t csi_espnow_start(void);

#ifdef __cplusplus
}
#endif
