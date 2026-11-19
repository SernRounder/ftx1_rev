#include "payload/ft8_rx.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <common/wave.h>

enum { SLOT_12K = 180000, SLOT_16K = 240000, CHUNK = 1999 };

static struct ft8_rx rx;
static float recording[SLOT_12K];
static int16_t chunk[CHUNK];

static int contains(const struct ft8_rx_result *result, size_t count, const char *text)
{
    for (size_t i = 0; i < count; ++i)
        if (strcmp(result[i].text, text) == 0)
            return 1;
    return 0;
}

static void feed_recording(unsigned rate)
{
    const unsigned count = rate * 15;
    for (unsigned start = 0; start < count; start += CHUNK) {
        const unsigned n = count - start < CHUNK ? count - start : CHUNK;
        for (unsigned i = 0; i < n; ++i) {
            const unsigned pos = (start + i) * 12000;
            const unsigned index = pos / rate;
            const unsigned next = index + 1 < SLOT_12K ? index + 1 : index;
            const float f = (float)(pos % rate) / rate;
            chunk[i] = (int16_t)(32767.0f * (recording[index] * (1 - f) + recording[next] * f));
        }
        assert(ft8_rx_push(&rx, chunk, n) == n);
    }
}

static void run(unsigned rate)
{
    struct ft8_rx_result results[FT8_RX_MAX_RESULTS];
    assert(ft8_rx_init(&rx, rate));
    assert(ft8_rx_finish(&rx, results, FT8_RX_MAX_RESULTS) == 0);
    assert(ft8_rx_push(&rx, chunk, 23) == 23);
    ft8_rx_begin_slot(&rx); /* Abandon a partial slot after a gap. */
    feed_recording(rate);
    assert(ft8_rx_push(&rx, chunk, 1) == 0);
    size_t decoded = ft8_rx_finish(&rx, results, FT8_RX_MAX_RESULTS);
    assert(contains(results, decoded, "CQ R7IW LN35"));
    assert(contains(results, decoded, "CQ DX R6WA LN32"));
    assert(ft8_rx_finish(&rx, results, 1) == 1);
    printf("%u Hz, %zu messages\n", rate, decoded);
    for (size_t i = 0; i < decoded; ++i)
        printf("%4u Hz %+5d ms  %s\n", results[i].frequency_hz, results[i].offset_ms, results[i].text);

    ft8_rx_begin_slot(&rx);
    memset(chunk, 0, sizeof(chunk));
    unsigned remaining = rate * 15;
    while (remaining != 0)
        remaining -= (unsigned)ft8_rx_push(&rx, chunk, CHUNK);
    assert(ft8_rx_finish(&rx, results, FT8_RX_MAX_RESULTS) == 0);
    ft8_rx_destroy(&rx);
}

int main(int argc, char **argv)
{
    int samples = SLOT_12K;
    int rate = 0;
    assert(argc == 2);
    assert(load_wav(recording, &samples, &rate, argv[1]) == 0);
    assert(samples == SLOT_12K && rate == 12000);
    assert(!ft8_rx_init(&rx, 8000));
    run(12000);
    run(16000);
    return 0;
}
