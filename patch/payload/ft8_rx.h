#ifndef FTX1_FT8_RX_H
#define FTX1_FT8_RX_H

#include "ft8_arm_api.h"
#include <common/monitor.h>

enum { FT8_RX_MAX_RESULTS = 24, FT8_RX_MAX_SYMBOL_SAMPLES = 2560 };
#ifdef FT8_RADIO
enum { FT8_RX_CANDIDATES = 140 };
#endif

struct ft8_rx {
    monitor_t monitor;
#ifdef FT8_VFP_ONLY
    int16_t symbol[FT8_RX_MAX_SYMBOL_SAMPLES];
#else
    float symbol[FT8_RX_MAX_SYMBOL_SAMPLES];
#endif
    unsigned sample_rate;
    unsigned samples;
    unsigned symbol_fill;
    uint32_t locator;
#ifdef FT8_RADIO
    ftx_candidate_t *candidates;
    int candidate_count, next_offset;
#endif
};

/* Callers own the receiver storage and choose the UTC slot boundary. */
int ft8_rx_init(struct ft8_rx *rx, unsigned sample_rate);
void ft8_rx_destroy(struct ft8_rx *rx);
void ft8_rx_begin_slot(struct ft8_rx *rx);
/* Consumes mono signed PCM until the end of the current 15-second slot. */
size_t ft8_rx_push(struct ft8_rx *rx, const int16_t *pcm, size_t count);
size_t ft8_rx_finish(struct ft8_rx *rx, struct ft8_rx_result *out, size_t capacity);
#ifdef FT8_RADIO
unsigned ft8_rx_roll(struct ft8_rx *rx, uint32_t end_ms);
int ft8_radio_decode_pause(unsigned sleep);
int ft8_radio_decode_expired(void);
#endif
void ft8_rx_set_locator(struct ft8_rx *rx, uint32_t locator);

#endif
