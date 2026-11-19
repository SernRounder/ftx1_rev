/* Round-trip the streaming synthesizer: encode -> synth -> decode. */
#include "payload/ft8_rx.h"
#include "payload/ft8_tx.h"
#include "payload/ft8_adif.h"
#include "payload/ft8_dma_tx.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct ft8_tx tx;
static struct ft8_rx rx;
static int16_t pcm[FT8_TX_SAMPLES];
static struct ft8_rx_result results[FT8_RX_MAX_RESULTS];

static struct ft8_dma_tx dma;
static size_t cleaned;

static void clean_dma(const void *buffer, size_t size)
{
    assert((uintptr_t)buffer % 32 == 0);
    assert(size == FT8_DMA_TX_BYTES);
    ++cleaned;
}

static void check_direct_dma(void)
{
    int16_t stereo[FT8_DMA_TX_SAMPLES * 4];
    for (int i = 0; i < 2 * FT8_DMA_TX_SAMPLES; ++i) {
        stereo[2 * i] = (int16_t)(i - 400);
        stereo[2 * i + 1] = (int16_t)(2000 + i);
    }
    memset(dma.frames, 0xa5, sizeof(dma.frames));
    assert(!ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    assert(ft8_dma_tx_begin(&dma));
    assert(ft8_dma_tx_drained(&dma));
    for (unsigned i = 0; i < FT8_DMA_TX_SLOTS; ++i)
        assert(ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    assert(cleaned == FT8_DMA_TX_SLOTS);
    assert(!ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));

    const struct ft8_dma_tx_frame *frame = ft8_dma_tx_select(&dma);
    assert(frame == &dma.frames[0]);
    assert(frame->words[0] == 800 && frame->words[1] == 0x1234);
    for (unsigned i = 0; i < FT8_DMA_TX_SAMPLES; ++i)
        assert(frame->words[2 + i] == (uint16_t)stereo[2 * i]);
    for (unsigned i = 2 + FT8_DMA_TX_SAMPLES; i < sizeof(*frame) / sizeof(uint16_t); ++i)
        assert(frame->words[i] == 0);
    assert(!ft8_dma_tx_select(&dma));
    assert(!ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    assert(!ft8_dma_tx_complete(&dma, &dma.frames[1]));
    assert(ft8_dma_tx_complete(&dma, frame));
    assert(!ft8_dma_tx_complete(&dma, frame));
    assert(ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    for (unsigned i = 1; i <= FT8_DMA_TX_SLOTS; ++i) {
        frame = ft8_dma_tx_select(&dma);
        assert(frame == &dma.frames[i % FT8_DMA_TX_SLOTS]);
        assert(!ft8_dma_tx_drained(&dma));
        assert(ft8_dma_tx_complete(&dma, frame));
    }
    assert(ft8_dma_tx_drained(&dma));

    assert(ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    assert(ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    frame = ft8_dma_tx_select(&dma);
    assert(frame);
    ft8_dma_tx_inhibit(&dma);
    assert(!ft8_dma_tx_begin(&dma));
    assert(!ft8_dma_tx_select(&dma));
    assert(!ft8_dma_tx_submit(&dma, stereo, FT8_DMA_TX_SAMPLES, clean_dma));
    assert(ft8_dma_tx_complete(&dma, frame));
    assert(ft8_dma_tx_begin(&dma));
    assert(ft8_dma_tx_drained(&dma));
    assert(!ft8_dma_tx_submit(&dma, stereo, 2000, clean_dma));
    assert(ft8_dma_tx_submit(&dma, stereo, 2 * FT8_DMA_TX_SAMPLES, clean_dma));
    frame = ft8_dma_tx_select(&dma);
    assert(frame && frame->words[0] == 1600 && frame->words[1601] == (uint16_t)stereo[3198]);
    assert(frame->words[1602] == 0 && ft8_dma_tx_complete(&dma, frame));
    puts("PASS: direct SPI PCM frame layout and DMA buffer ownership");
}

static size_t render(const char *text, unsigned frequency_hz, size_t chunk_limit, int free_text)
{
    uint8_t tones[FT8_TX_SYMBOLS];
    assert(free_text ? ft8_tx_encode_free(text, tones) : ft8_tx_encode(text, tones));
    assert(ft8_tx_start(&tx, tones, frequency_hz));
    size_t total = 0;
    while (total < FT8_TX_SAMPLES) {
        const size_t capacity = chunk_limit && chunk_limit < FT8_TX_SAMPLES - total
                                    ? chunk_limit : FT8_TX_SAMPLES - total;
        const size_t produced = ft8_tx_next(&tx, pcm + total, capacity);
        assert(produced == capacity);
        total += produced;
    }
    assert(ft8_tx_next(&tx, pcm, 1) == 0);
    return total;
}

static int roundtrip(const char *text, unsigned frequency_hz, size_t chunk_limit, int free_text)
{
    assert(render(text, frequency_hz, chunk_limit, free_text) == FT8_TX_SAMPLES);
    assert(ft8_rx_init(&rx, 16000));
    int16_t chunk[1999];
    size_t pushed = 0;
    while (pushed < FT8_SLOT_SAMPLES) {
        const size_t n = FT8_SLOT_SAMPLES - pushed < 1999 ? FT8_SLOT_SAMPLES - pushed : 1999;
        for (size_t i = 0; i < n; ++i)
            chunk[i] = pushed + i < FT8_TX_SAMPLES ? pcm[pushed + i] : 0;
        assert(ft8_rx_push(&rx, chunk, n) == n);
        pushed += n;
    }
    const size_t decoded = ft8_rx_finish(&rx, results, FT8_RX_MAX_RESULTS);
    for (size_t i = 0; i < decoded; ++i)
        if (strcmp(results[i].text, text) == 0)
            return results[i].frequency_hz;
    return -1;
}

/* Non-standard callsigns encode via hashing and decode back as <...>. */
static int roundtrip_hashed(const char *text)
{
    assert(render(text, 1000, 0, 0) == FT8_TX_SAMPLES);
    assert(ft8_rx_init(&rx, 16000));
    int16_t chunk[1999];
    size_t pushed = 0;
    while (pushed < FT8_SLOT_SAMPLES) {
        const size_t n = FT8_SLOT_SAMPLES - pushed < 1999 ? FT8_SLOT_SAMPLES - pushed : 1999;
        for (size_t i = 0; i < n; ++i)
            chunk[i] = pushed + i < FT8_TX_SAMPLES ? pcm[pushed + i] : 0;
        assert(ft8_rx_push(&rx, chunk, n) == n);
        pushed += n;
    }
    const size_t decoded = ft8_rx_finish(&rx, results, FT8_RX_MAX_RESULTS);
    for (size_t i = 0; i < decoded; ++i)
        if (strstr(results[i].text, "<...>"))
            return 1;
    return 0;
}

static int measured_report(int attenuation)
{
    const char *text = "K1ABC W9XYZ R-12";
    render(text, 1000, 0, 0);
    assert(ft8_rx_init(&rx, 16000));
    uint32_t random = 42;
    int16_t chunk[1600];
    for (unsigned first = 0; first < FT8_SLOT_SAMPLES; first += 1600) {
        for (unsigned i = 0; i < 1600; ++i) {
            random = random * 1664525u + 1013904223u;
            const int noise = (int)(random >> 18) - 8192;
            const int signal = first + i < FT8_TX_SAMPLES ? pcm[first + i] / attenuation : 0;
            chunk[i] = signal + noise;
        }
        assert(ft8_rx_push(&rx, chunk, 1600) == 1600);
    }
    const size_t count = ft8_rx_finish(&rx, results, FT8_RX_MAX_RESULTS);
    ft8_rx_destroy(&rx);
    for (size_t i = 0; i < count; ++i)
        if (strcmp(results[i].text, text) == 0) {
            assert(results[i].sender == 7);
            return results[i].snr_db;
        }
    assert(!"No decode in synthetic noise");
    return -100;
}

int main(void)
{
    check_direct_dma();
    const int strong = measured_report(24), weak = measured_report(48);
    assert(strong >= -15 && strong <= -3 && weak >= -21 && weak <= -9 && strong - weak >= 3);
    printf("PASS: estimated reports %d and %d dB at two injected noise ratios\n", strong, weak);
    uint8_t tones[FT8_TX_SYMBOLS];
    int16_t reference[FT8_TX_SAMPLES];

    /* Standard messages at several audio frequencies and chunk shapes. */
    for (unsigned i = 0; i < 3; ++i) {
        static const char *const messages[] = {
            "CQ W9XYZ FN31", "K1ABC W9XYZ -08", "K1ABC W9XYZ RRR",
        };
        static const unsigned frequencies[] = { 1000, 440, 2500 };
        static const size_t limits[] = { 777, 0 /* whole waveform */, 3 };
        const int hz = roundtrip(messages[i], frequencies[i], limits[i], 0);
        assert(hz > 0 && (unsigned)hz <= frequencies[i] + 44);
        printf("%4u Hz  %s\n", (unsigned)hz, messages[i]);
    }
    /* Free text. */
    assert(roundtrip("HELLO WORLD", 800, 1000, 1) > 0);
    puts("800 Hz  HELLO WORLD");
    /* Non-standard callsign takes the hashed path. */
    assert(roundtrip_hashed("CQ N0CALL PM95"));
    puts("1000 Hz  CQ <...> PM95");

    /* Free text limits: > 13 chars is rejected; empty pads to spaces, so the
       transmit layer must refuse to arm an empty FREE message. */
    assert(!ft8_tx_encode_free("THIS IS TOO LONG", tones));
    assert(ft8_tx_encode_free("", tones));

    /* Rejected inputs: oversize text and out-of-range audio frequency.
       Empty strings pad to spaces here; the arming layer refuses them. */
    assert(!ft8_tx_encode("THIS MESSAGE IS FAR TOO LONG", tones));
    assert(ft8_tx_encode("", tones));
    assert(!ft8_tx_start(&tx, tones, 100));
    assert(!ft8_tx_start(&tx, tones, 2900));

    /* Deterministic synthesis. */
    render("CQ W9XYZ FN31", 1000, 0, 0);
    memcpy(reference, pcm, sizeof(reference));
    render("CQ W9XYZ FN31", 1000, 512, 0);
    assert(memcmp(reference, pcm, sizeof(reference)) == 0);

    /* ADIF record builder: exact bytes for a known QSO. */
    {
        struct ft8_qso qso = {.band = "20m", .freq = "14.074", .power = "3.7",
                              .report_sent = "-08", .report_received = "-12"};
        char record[FT8_ADIF_RECORD_MAX];
        memcpy(qso.call, "WM3PEN", 7);
        memcpy(qso.my_call, "W9XYZ", 6);
        memcpy(qso.my_grid, "PM95", 5);
        const uint8_t bcd[7] = {0x26, 0x11, 0x10, 0x02, 0x12, 0x00, 0x30};
        const size_t len = ft8_adif_record(record, sizeof(record), &qso, bcd);
        assert(len == strlen(record));
        assert(strcmp(record,
            "<CALL:6>WM3PEN<QSO_DATE:8>20261110<TIME_ON:6>120030"
            "<MODE:3>FT8<BAND:3>20m<FREQ:6>14.074<TX_PWR:3>3.7"
            "<RST_SENT:3>-08<RST_RCVD:3>-12<STATION_CALLSIGN:5>W9XYZ"
            "<MY_GRIDSQUARE:4>PM95<eor>\n") == 0);
        memcpy(qso.grid, "IN94", 5);
        assert(ft8_adif_record(record, sizeof(record), &qso, bcd) > 0);
        assert(strstr(record, "<GRIDSQUARE:4>IN94") != NULL);
        const uint8_t invalid_date[7] = {0x26, 0x02, 0x29, 0x02, 0x12, 0x00, 0x30};
        assert(ft8_adif_record(record, sizeof(record), &qso, invalid_date) == 0);
        assert(ft8_adif_record(record, sizeof(record) - 1, &qso, bcd) == 0);
        memset(qso.freq, '9', sizeof(qso.freq)); /* no terminator */
        assert(ft8_adif_record(record, sizeof(record), &qso, bcd) == 0);
        qso.grid[0] = 0;
        /* Worked set: add, hit, and length limits. */
        struct ft8_worked worked;
        memset(&worked, 0, sizeof(worked));
        ft8_adif_worked_add(&worked, "WM3PEN");
        assert(ft8_adif_worked_before(&worked, "WM3PEN", strlen("WM3PEN")));
        assert(!ft8_adif_worked_before(&worked, "K1ABC", strlen("K1ABC")));
        ft8_adif_worked_add(&worked, "WAYTOOLONGCALLX");  /* >13 chars untracked */
        assert(!ft8_adif_worked_before(&worked, "WAYTOOLONGCALLX", 15));
        ft8_adif_worked_add(&worked, "12CHARSCALL");   /* 13-char compound fits */
        assert(ft8_adif_worked_before(&worked, "12CHARSCALL", 12));
        const char logged[] = "<CALL:5>K4ABC<MODE:3>FT8<eor>\r\n<CALL:5>K5ABC<MODE:3>FT8";
        ft8_adif_worked_read(&worked, logged, 8);
        ft8_adif_worked_read(&worked, logged + 8, sizeof(logged) - 9);
        assert(ft8_adif_worked_before(&worked, "K4ABC", 5));
        assert(!ft8_adif_worked_before(&worked, "K5ABC", 5));
        puts(record);
    }

    puts("PASS: synth round-trips through the receiver");
    return 0;
}
