/*
 * CSI sender: broadcasts a tiny ESP-NOW packet at a fixed rate.
 * The receiver extracts Channel State Information (CSI) from every packet.
 * The packet payload is a 32-bit counter so the receiver can detect lost packets.
 */
#include <stdint.h>

#include "esp_log.h"
#include "esp_now.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "csi_common.h"

#define SEND_PERIOD_TICKS pdMS_TO_TICKS(CONFIG_CSI_SEND_PERIOD_MS)
#define REPORT_PERIOD_MS 5000

_Static_assert(SEND_PERIOD_TICKS >= 1,
               "CSI_SEND_PERIOD_MS is shorter than one FreeRTOS tick (raise CONFIG_FREERTOS_HZ)");

static const char *TAG = "csi_send";
static const uint8_t BROADCAST_MAC[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

void app_main(void)
{
    ESP_ERROR_CHECK(csi_wifi_start(true));
    ESP_ERROR_CHECK(csi_espnow_start());

    ESP_LOGI(TAG, "CSI sender: channel=%d period=%d ms (%d Hz) tx_power=%d (x0.25 dBm)", CONFIG_CSI_CHANNEL,
             CONFIG_CSI_SEND_PERIOD_MS, 1000 / CONFIG_CSI_SEND_PERIOD_MS, CONFIG_CSI_TX_POWER_QDBM);

    uint32_t counter = 0;
    uint32_t send_errors = 0;
    TickType_t last_wake = xTaskGetTickCount();
    TickType_t last_report = last_wake;

    for (;;) {
        if (esp_now_send(BROADCAST_MAC, (const uint8_t *)&counter, sizeof(counter)) != ESP_OK) {
            send_errors++;
        }
        counter++;

        vTaskDelayUntil(&last_wake, SEND_PERIOD_TICKS);

        if ((last_wake - last_report) >= pdMS_TO_TICKS(REPORT_PERIOD_MS)) {
            last_report = last_wake;
            ESP_LOGI(TAG, "sent=%lu send_errors=%lu", (unsigned long)counter, (unsigned long)send_errors);
        }
    }
}
