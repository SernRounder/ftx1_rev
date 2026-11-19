#ifndef FTX1_FT8_TX_H
#define FTX1_FT8_TX_H

#include "ft8_arm_api.h"

enum {
    FT8_TX_SYMBOLS = 79,              /* FT8 channel symbols */
    FT8_TX_SPS = 2560,                /* samples per symbol at 16 kHz */
    FT8_TX_SAMPLES = FT8_TX_SYMBOLS * FT8_TX_SPS, /* 12.64 s waveform */
    FT8_TX_MIN_HZ = 200, FT8_TX_MAX_HZ = 2800, FT8_TX_DEFAULT_HZ = 1000,
};

/* Streaming synthesizer state. The native image shares a pulse table in ROM. */
struct ft8_tx {
#ifndef FT8_RADIO
    float pulse[3 * FT8_TX_SPS];
#endif
    float phase, dphi_base, dphi_peak;
    uint32_t produced;
    uint8_t tones[FT8_TX_SYMBOLS];
};

/* Encode a standard message (calls/grid/report) into 79 tones. */
int ft8_tx_encode(const char *text, uint8_t tones[FT8_TX_SYMBOLS]);
/* Encode free text (<= 13 chars) as an i3=0 free-text message. */
int ft8_tx_encode_free(const char *text, uint8_t tones[FT8_TX_SYMBOLS]);
/* Prepare streaming synthesis at a base audio frequency of 200..2800 Hz. */
int ft8_tx_start(struct ft8_tx *tx, const uint8_t *tones, unsigned frequency_hz);
/* Produce the next mono 16 kHz samples. Returns 0 once the waveform is done. */
size_t ft8_tx_next(struct ft8_tx *tx, int16_t *pcm, size_t capacity);

#endif
