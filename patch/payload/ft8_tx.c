/* Streaming FT8 synthesizer following the ft8_lib reference generator (gen_ft8.c). */
#include "ft8_tx.h"

#include <math.h>
#include <ft8/encode.h>
#include <ft8/message.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define FT8_SYMBOL_BT 2.0f
#define GFSK_CONST_K 5.336446f /* == pi * sqrt(2 / log(2)) */
#define SAMPLE_RATE 16000.0f

#ifdef FT8_RADIO
static const float pulse_table[] = {
#include "ft8_native_pulse.h"
};
enum { PULSE_FIRST_BIN = 22, PULSE_LAST_BIN = 168 };
_Static_assert(sizeof(pulse_table) / sizeof(pulse_table[0]) ==
               PULSE_LAST_BIN - PULSE_FIRST_BIN + 1, "GFSK table length");

static float pulse_at(unsigned index)
{
    const unsigned midpoint = 3 * FT8_TX_SPS / 2;
    const unsigned offset = index < midpoint ? midpoint - index : index - midpoint;
    const unsigned bin = offset / 16, fraction = offset % 16;
    if (bin < PULSE_FIRST_BIN)
        return 1.0f;
    if (bin >= PULSE_LAST_BIN)
        return 0.0f;
    const float value = pulse_table[bin - PULSE_FIRST_BIN];
    return fraction ? value + (pulse_table[bin + 1 - PULSE_FIRST_BIN] - value) *
                              (fraction / 16.0f) : value;
}
#define PULSE(tx, index) pulse_at(index)
#else
#define PULSE(tx, index) ((tx)->pulse[index])
#endif

int ft8_tx_encode(const char *text, uint8_t tones[FT8_TX_SYMBOLS])
{
    ftx_message_t message;
    if (!text || ftx_message_encode(&message, NULL, text) != FTX_MESSAGE_RC_OK)
        return 0;
    ft8_encode(message.payload, tones);
    return 1;
}

int ft8_tx_encode_free(const char *text, uint8_t tones[FT8_TX_SYMBOLS])
{
    ftx_message_t message;
    if (!text || ftx_message_encode_free(&message, text) != FTX_MESSAGE_RC_OK)
        return 0;
    ft8_encode(message.payload, tones);
    return 1;
}

int ft8_tx_start(struct ft8_tx *tx, const uint8_t *tones, unsigned frequency_hz)
{
    if (!tx || !tones || frequency_hz < FT8_TX_MIN_HZ || frequency_hz > FT8_TX_MAX_HZ)
        return 0;
    for (unsigned i = 0; i < FT8_TX_SYMBOLS; ++i)
        tx->tones[i] = tones[i];
#ifndef FT8_RADIO
    /* GFSK smoothing pulse truncated at three symbol lengths. */
    for (int i = 0; i < 3 * FT8_TX_SPS; ++i) {
        const float t = i / (float)FT8_TX_SPS - 1.5f;
        tx->pulse[i] = (erff(GFSK_CONST_K * FT8_SYMBOL_BT * (t + 0.5f)) -
                        erff(GFSK_CONST_K * FT8_SYMBOL_BT * (t - 0.5f))) / 2.0f;
    }
#endif
    tx->dphi_base = 2.0f * (float)M_PI * frequency_hz / SAMPLE_RATE;
    tx->dphi_peak = 2.0f * (float)M_PI / FT8_TX_SPS;
    tx->phase = 0.0f;
    tx->produced = 0;
    return 1;
}

size_t ft8_tx_next(struct ft8_tx *tx, int16_t *pcm, size_t capacity)
{
    if (!tx || !pcm || capacity == 0)
        return 0;
    size_t produced = 0;
    const uint32_t ramp = FT8_TX_SPS / 8;
    while (produced < capacity && tx->produced < FT8_TX_SAMPLES) {
        const uint32_t k = tx->produced;
        const unsigned symbol = k / FT8_TX_SPS;
        const unsigned p = k - symbol * FT8_TX_SPS;
        /* Each sample overlaps the pulse tails of three symbols; the symbols
           before the first and after the last extend the edge tones. */
        const uint8_t previous = tx->tones[symbol ? symbol - 1 : 0];
        const uint8_t current = tx->tones[symbol];
        const uint8_t next =
            tx->tones[symbol + 1 < FT8_TX_SYMBOLS ? symbol + 1 : FT8_TX_SYMBOLS - 1];
        const float dphi = tx->dphi_base +
                           tx->dphi_peak * (previous * PULSE(tx, p + 2 * FT8_TX_SPS) +
                                            current * PULSE(tx, p + FT8_TX_SPS) +
                                            next * PULSE(tx, p));
        float sample = sinf(tx->phase);
        /* At supported tones one sample advances by less than one turn. */
        const float turn = 2.0f * (float)M_PI;
        const float phase = tx->phase + dphi;
        tx->phase = phase >= turn ? phase - turn : phase;
        if (k < ramp)
            sample *= (1.0f - cosf(2.0f * (float)M_PI * k / (2.0f * ramp))) / 2.0f;
        else if (k >= FT8_TX_SAMPLES - ramp) {
            const uint32_t i = FT8_TX_SAMPLES - 1 - k;
            sample *= (1.0f - cosf(2.0f * (float)M_PI * i / (2.0f * ramp))) / 2.0f;
        }
        pcm[produced++] = (int16_t)(sample * 32767.0f);
        ++tx->produced;
    }
    return produced;
}
