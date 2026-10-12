/*
 * CSI receiver: extracts CSI from ESP-NOW packets sent by csi_send and prints it
 * over the serial port, one text line per packet, in the same CSV layout as the
 * Espressif esp-csi "get-started" example:
 *
 *   CSI_DATA,<id>,<mac>,<rssi>,...,<len>,<first_word>,"[im0,re0,im1,re1,...]"
 *
 * The CSI callback runs inside the Wi-Fi task, so it only copies the data into a
 * queue (as recommended by the ESP-IDF docs). A separate low-priority task formats
 * and prints. If the serial link cannot keep up, packets are dropped and counted.
 * Once per second a "CSI_STAT,<ms>,<rx_total>,<dropped>" line is printed.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "csi_common.h"

#define CSI_MAX_LEN 384
/* ESP-NOW vendor action frame: category(1) + OUI(3) + random(4) + element header(7) = 15 */
#define ESPNOW_APP_DATA_OFFSET 15
#define ID_UNKNOWN UINT32_MAX

typedef struct {
    wifi_pkt_rx_ctrl_t rx_ctrl;
    uint32_t id;
    uint16_t len;
    uint8_t first_word_invalid;
    int8_t data[CSI_MAX_LEN];
} csi_item_t;

static const char *TAG = "csi_recv";
static QueueHandle_t s_queue;
static volatile uint32_t s_rx_total;
static volatile uint32_t s_dropped;

static void csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    if (info == NULL || info->buf == NULL || memcmp(info->mac, CSI_TX_MAC, sizeof(CSI_TX_MAC)) != 0) {
        return;
    }
    s_rx_total++;

    static csi_item_t item; /* only ever used from the Wi-Fi task; xQueueSend copies it */
    item.rx_ctrl = info->rx_ctrl;
    item.len = info->len > CSI_MAX_LEN ? CSI_MAX_LEN : info->len;
    item.first_word_invalid = info->first_word_invalid;
    memcpy(item.data, info->buf, item.len);

    item.id = ID_UNKNOWN;
    if (info->payload != NULL && info->payload_len >= ESPNOW_APP_DATA_OFFSET + sizeof(uint32_t)) {
        memcpy(&item.id, info->payload + ESPNOW_APP_DATA_OFFSET, sizeof(uint32_t));
    }

    if (xQueueSend(s_queue, &item, 0) != pdTRUE) {
        s_dropped++;
    }
}

static void print_task(void *arg)
{
    static char line[2560];
    csi_item_t item;
    unsigned burst = 0;
    int64_t next_stat_us = esp_timer_get_time() + 1000000;

    printf("CSI_INFO,channel=%d,send_ltf=%s\n", CONFIG_CSI_CHANNEL,
#ifdef CONFIG_CSI_USE_HTLTF
           "lltf+htltf"
#else
           "lltf"
#endif
    );
    printf("type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,"
           "noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,"
           "data\n");

    for (;;) {
        if (xQueueReceive(s_queue, &item, pdMS_TO_TICKS(100)) == pdTRUE) {
            const wifi_pkt_rx_ctrl_t *c = &item.rx_ctrl;
            char *p = line;
            char *const end = line + sizeof(line);

            p += snprintf(p, end - p, "CSI_DATA,%lu," MACSTR ",%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%u,%d,\"[",
                          (unsigned long)item.id, MAC2STR(CSI_TX_MAC), c->rssi, c->rate, c->sig_mode, c->mcs, c->cwb,
                          c->smoothing, c->not_sounding, c->aggregation, c->stbc, c->fec_coding, c->sgi,
                          c->noise_floor, c->ampdu_cnt, c->channel, c->secondary_channel, (int)c->timestamp, c->ant,
                          c->sig_len, c->sig_mode, (unsigned)item.len, item.first_word_invalid);
            for (int i = 0; i < item.len && p < end - 8; i++) {
                p += snprintf(p, end - p, i ? ",%d" : "%d", item.data[i]);
            }
            snprintf(p, end - p, "]\"\n");
            fputs(line, stdout);

            /* never hog the CPU: let the idle task (and its watchdog) run */
            if ((++burst % 8) == 0) {
                vTaskDelay(1);
            }
        }

        if (esp_timer_get_time() >= next_stat_us) {
            next_stat_us += 1000000;
            printf("CSI_STAT,%lu,%lu,%lu\n", (unsigned long)(esp_timer_get_time() / 1000), (unsigned long)s_rx_total,
                   (unsigned long)s_dropped);
        }
    }
}

static esp_err_t csi_start(void)
{
    wifi_csi_config_t cfg = {
        .lltf_en = true,
#ifdef CONFIG_CSI_USE_HTLTF
        .htltf_en = true,
#else
        .htltf_en = false,
#endif
        .stbc_htltf2_en = false,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = false,
        .shift = 0,
    };
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_rx_cb, NULL));
    return esp_wifi_set_csi(true);
}

void app_main(void)
{
    s_queue = xQueueCreate(CONFIG_CSI_QUEUE_LEN, sizeof(csi_item_t));
    configASSERT(s_queue != NULL);

    ESP_ERROR_CHECK(csi_wifi_start(false));
    ESP_ERROR_CHECK(csi_espnow_start());

    /* Core 1: the Wi-Fi driver runs on core 0, keep the slow serial writes away from it */
    xTaskCreatePinnedToCore(print_task, "csi_print", 4096, NULL, 3, NULL, 1);

    ESP_ERROR_CHECK(csi_start());
    ESP_LOGW(TAG, "CSI receiver running on channel %d", CONFIG_CSI_CHANNEL);
}
