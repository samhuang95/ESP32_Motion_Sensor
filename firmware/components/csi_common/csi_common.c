/*
 * Shared Wi-Fi / ESP-NOW bring-up for the CSI sender and receiver.
 * Derived from the Espressif esp-csi "get-started" examples (Apache-2.0 / CC0),
 * simplified for the original ESP32 (ESP-WROOM-32) and HT20.
 */
#include "csi_common.h"

#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

static const char *TAG = "csi_common";

const uint8_t CSI_TX_MAC[6] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};

static const uint8_t BROADCAST_MAC[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

esp_err_t csi_wifi_start(bool is_sender)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), TAG, "nvs erase");
        ret = nvs_flash_init();
    }
    ESP_RETURN_ON_ERROR(ret, TAG, "nvs init");

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&cfg), TAG, "wifi init");
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG, "wifi storage");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "wifi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20), TAG, "wifi bandwidth");

    if (is_sender) {
        /* esp_wifi_set_mac() is only allowed while the interface is disabled. */
        ESP_RETURN_ON_ERROR(esp_wifi_set_mac(WIFI_IF_STA, CSI_TX_MAC), TAG, "set mac");
    }

    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "wifi start");
    ESP_RETURN_ON_ERROR(esp_wifi_set_ps(WIFI_PS_NONE), TAG, "wifi ps");
    ESP_RETURN_ON_ERROR(esp_wifi_set_channel(CONFIG_CSI_CHANNEL, WIFI_SECOND_CHAN_NONE), TAG, "wifi channel");

    if (is_sender) {
        ESP_RETURN_ON_ERROR(esp_wifi_set_max_tx_power(CONFIG_CSI_TX_POWER_QDBM), TAG, "tx power");
    }
    return ESP_OK;
}

esp_err_t csi_espnow_start(void)
{
    ESP_RETURN_ON_ERROR(esp_now_init(), TAG, "esp-now init");

    esp_now_peer_info_t peer = {
        .channel = CONFIG_CSI_CHANNEL,
        .ifidx = WIFI_IF_STA,
        .encrypt = false,
    };
    memcpy(peer.peer_addr, BROADCAST_MAC, sizeof(BROADCAST_MAC));
    ESP_RETURN_ON_ERROR(esp_now_add_peer(&peer), TAG, "add peer");

    esp_now_rate_config_t rate = {
        .phymode = WIFI_PHY_MODE_HT20,
        .rate = WIFI_PHY_RATE_MCS0_LGI,
        .ersu = false,
        .dcm = false,
    };
    ESP_RETURN_ON_ERROR(esp_now_set_peer_rate_config(BROADCAST_MAC, &rate), TAG, "peer rate");
    return ESP_OK;
}
