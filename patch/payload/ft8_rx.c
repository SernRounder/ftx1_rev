#include "ft8_rx.h"
#include "ft8_locator.h"
#include "ft8_profile.h"
#ifdef FT8_RADIO
#include "ft8_live.h"
#endif

#include <math.h>
#include <string.h>
#include <ft8/message.h>

#ifdef FT8_VFP_ONLY
void ft8_vfp_fft(monitor_t *, const int16_t *);
bool ft8_vfp_candidate(const ftx_waterfall_t *, const ftx_candidate_t *, int,
                       ftx_message_t *, ftx_decode_status_t *);
#endif

enum { SLOT_SECONDS = 15, MAX_CANDIDATES = 140, MIN_SCORE = 10, LDPC_ITERATIONS = 25 };
_Static_assert(FT8_MESSAGE_CHARS >= FTX_MAX_MESSAGE_LENGTH, "Result text storage too short");

#ifdef FT8_RADIO
int ftx_find_candidates_in_band(const ftx_waterfall_t *, int, ftx_candidate_t *,
                               int, int, int, int, int, int, int);
enum { FIRST_OFFSET = -10, LAST_OFFSET = 20 };

static int search(struct ft8_rx *rx, int finish)
{
    const ftx_waterfall_t *wf = &rx->monitor.wf;
    const int start = rx->next_offset;
    if (start > LAST_OFFSET)
        return rx->candidate_count;
    if (!finish && ft8_radio_decode_expired())
        return 0;
    /* All three Costas sequences are immutable once their last bin arrives. */
    if (!finish && (start >= LAST_OFFSET || start + FT8_NN > wf->num_blocks))
        return 0;
    /* The last seven symbols are Costas sync. Searching offsets whose
       payload has not arrived spends the TX guard on unusable candidates. */
    int stop = start + 1;
    if (finish) {
        stop = LAST_OFFSET;
        const int ready = wf->num_blocks - (FT8_NN - FT8_LENGTH_SYNC) + 1;
        if (ft8_radio_offset_set() && ready < stop)
            stop = ready;
    }
    PROFILE_START(scan);
    rx->candidate_count = ftx_find_candidates_in_band(wf, FT8_RX_CANDIDATES,
        rx->candidates, MIN_SCORE, 0, wf->num_bins, start, stop, rx->candidate_count, finish);
    PROFILE_END(scan, PROF_SEARCH, (finish << 15) | rx->candidate_count);
    rx->next_offset = finish ? LAST_OFFSET + 1 : stop;
    return rx->candidate_count;
}
#endif

int ft8_rx_init(struct ft8_rx *rx, unsigned sample_rate)
{
    if (sample_rate != 12000 && sample_rate != 16000)
        return 0;
    const monitor_config_t config = {
        .f_min = 200,
        .f_max = 3000,
        .sample_rate = (int)sample_rate,
        .time_osr = 2,
        .freq_osr = 2,
        .protocol = FTX_PROTOCOL_FT8,
    };
    if (!monitor_init(&rx->monitor, &config))
        return 0;
    rx->sample_rate = sample_rate;
    rx->locator = 0;
    ft8_rx_begin_slot(rx);
    return 1;
}

void ft8_rx_set_locator(struct ft8_rx *rx, uint32_t locator)
{
    rx->locator = locator;
}

void ft8_rx_destroy(struct ft8_rx *rx)
{
    monitor_free(&rx->monitor);
}

void ft8_rx_begin_slot(struct ft8_rx *rx)
{
    rx->samples = 0;
    rx->symbol_fill = 0;
#ifdef FT8_RADIO
    rx->candidate_count = 0;
    rx->next_offset = FIRST_OFFSET;
#endif
    monitor_reset(&rx->monitor);
    memset(rx->monitor.last_frame, 0, rx->monitor.nfft * sizeof(float));
}

size_t ft8_rx_push(struct ft8_rx *rx, const int16_t *pcm, size_t count)
{
    const unsigned remaining = SLOT_SECONDS * rx->sample_rate - rx->samples;
    if (count > remaining)
        count = remaining;
    const unsigned symbol_samples = (unsigned)rx->monitor.block_size;
    for (size_t i = 0; i < count; ++i) {
#ifdef FT8_VFP_ONLY
        rx->symbol[rx->symbol_fill++] = pcm[i];
#else
        rx->symbol[rx->symbol_fill++] = pcm[i] * (1.0f / 32768.0f);
#endif
        if (rx->symbol_fill == symbol_samples) {
            PROFILE_START(fft);
#ifdef FT8_VFP_ONLY
            ft8_vfp_fft(&rx->monitor, rx->symbol);
#else
            monitor_process(&rx->monitor, rx->symbol);
#endif
            rx->symbol_fill = 0;
            PROFILE_END(fft, PROF_FFT, rx->monitor.wf.num_blocks);
#ifdef FT8_RADIO
            search(rx, 0);
#endif
        }
    }
    rx->samples += (unsigned)count;
    return count;
}

#ifdef FT8_RADIO
/* A 15 s buffer has 93 complete symbols. Advance 12 symbols (1.92 s),
   leaving 81, enough to retain a complete 79-symbol message across scans.
   The FFT history and the partially filled symbol remain continuous. */
unsigned ft8_radio_roll_blocks(uint32_t end_ms);

unsigned ft8_rx_roll(struct ft8_rx *rx, uint32_t end_ms)
{
    const unsigned advance = ft8_radio_roll_blocks(end_ms);
    ftx_waterfall_t *wf = &rx->monitor.wf;
    wf->num_blocks -= advance;
    memmove(wf->mag, wf->mag + advance * wf->block_stride,
            wf->num_blocks * wf->block_stride * sizeof(*wf->mag));
    rx->samples -= advance * rx->monitor.block_size;
    rx->candidate_count = 0;
    rx->next_offset = FIRST_OFFSET;
    return rx->samples;
}
#endif

static int already_seen(const ftx_message_t *seen, size_t n, const ftx_message_t *message)
{
    for (size_t i = 0; i < n; ++i) {
        if (seen[i].hash == message->hash &&
            memcmp(seen[i].payload, message->payload, sizeof(message->payload)) == 0)
            return 1;
    }
    return 0;
}

static uint32_t sender_locator(const char *text, const ftx_message_offsets_t *offsets)
{
    const int offset = offsets->offsets[2];
    if (offsets->types[2] != FTX_FIELD_GRID || offset < 0 || offset >= FT8_MESSAGE_CHARS)
        return 0;
    const char *grid = text + offset;
    if (grid[0] == 'R' && grid[1] == ' ')
        grid += 2;
    if (strcmp(grid, "RR73") == 0)
        return 0;
    return ft8_locator_parse(grid);
}

/* Waterfall magnitudes are quantized in half dB. Convert to proportional
   power using a six-entry fraction table and a power-of-two exponent. */
static float bin_power(int mag)
{
    static const float fraction[] = {1.0f, 1.122f, 1.259f, 1.413f, 1.585f, 1.778f};
    const int steps = mag / 6;
    const union { uint32_t bits; float value; } power = { (uint32_t)(103 + steps) << 23 };
    return power.value * fraction[mag % 6];
}

static int estimate_snr(const ftx_waterfall_t *wf, const ftx_candidate_t *c)
{
    float total = 0, noise = 0;
    int symbols = 0, samples = 0;
    const int freq = c->freq_offset;
    for (int i = 0; i < 21; ++i) {
        const int block = c->time_offset + (i / 7) * 36 + i % 7;
        if (block < 0 || block >= wf->num_blocks)
            continue;
        const WF_ELEM_T *bins = wf->mag + block * wf->block_stride +
            (c->time_sub * wf->freq_osr + c->freq_sub) * wf->num_bins;
        total += bin_power(WF_ELEM_MAG_INT(bins[freq + kFT8_Costas_pattern[i % 7]]));
        ++symbols;
        /* Sample on both sides of the signal, beyond the Hann main lobe. */
        if (freq >= 3) {
            noise += bin_power(WF_ELEM_MAG_INT(bins[freq - 3]));
            ++samples;
        }
        if (freq + 10 < wf->num_bins) {
            noise += bin_power(WF_ELEM_MAG_INT(bins[freq + 10]));
            ++samples;
        }
    }
    const float excess = total * samples - noise * symbols;
    if (excess <= 0)
        return -30;
    /* Hann ENBW is 4.6875 Hz for the 0.32 s FFT. Reference to 2500 Hz. */
    const float db = 10.0f * log10f((excess / (noise * symbols)) * (4.6875f / 2500.0f));
    if (db <= -30)
        return -30; /* Lower values collide with acknowledgements in packgrid. */
    if (db >= 49)
        return 49;
    return (int)(db + (db < 0 ? -0.5f : 0.5f));
}

size_t ft8_rx_finish(struct ft8_rx *rx, struct ft8_rx_result *out, size_t capacity)
{
#ifdef FT8_RADIO
    if (rx->samples < FT8_MIN_RX_BLOCKS * rx->monitor.block_size || capacity == 0 || ft8_radio_decode_expired())
#else
    if (rx->samples != SLOT_SECONDS * rx->sample_rate || capacity == 0)
#endif
        return 0;
    if (capacity > FT8_RX_MAX_RESULTS)
        capacity = FT8_RX_MAX_RESULTS;

    const monitor_t *monitor = &rx->monitor;
    const ftx_waterfall_t *wf = &monitor->wf;
#ifdef FT8_RADIO
    const ftx_candidate_t *candidates = rx->candidates;
    const int count = search(rx, 1);
#else
    ftx_candidate_t candidates[MAX_CANDIDATES];
    const int count = ftx_find_candidates(wf, MAX_CANDIDATES, candidates, MIN_SCORE);
#endif
    ftx_message_t seen[FT8_RX_MAX_RESULTS];
    size_t decoded = 0;
    for (int i = 0; i < count && decoded < capacity; ++i) {
#ifdef FT8_RADIO
        if (ft8_radio_decode_expired() || (i && !(i % 2) && ft8_radio_decode_pause(1)))
            break;
#endif
        const ftx_candidate_t *c = &candidates[i];
        ftx_message_t message;
        ftx_decode_status_t status;
        PROFILE_START(attempt);
#ifdef FT8_VFP_ONLY
        const int valid = ft8_vfp_candidate(wf, c, LDPC_ITERATIONS, &message, &status);
#else
        const int valid = ftx_decode_candidate(wf, c, LDPC_ITERATIONS, &message, &status);
#endif
        PROFILE_END(attempt, PROF_CANDIDATE, (valid << 15) | i);
        if (!valid || already_seen(seen, decoded, &message))
            continue;
        ftx_message_offsets_t offsets;
        struct ft8_rx_result *row = &out[decoded];
        PROFILE_START(unpack);
        const int unpacked = ftx_message_decode(&message, NULL, row->text, &offsets);
        PROFILE_END(unpack, PROF_UNPACK, unpacked == FTX_MESSAGE_RC_OK);
        if (unpacked != FTX_MESSAGE_RC_OK)
            continue;
        row->recipient = offsets.types[0] == FTX_FIELD_CALL && offsets.offsets[0] >= 0
            && offsets.offsets[0] < FT8_MESSAGE_CHARS ? offsets.offsets[0] + 1 : 0;
        row->sender = offsets.types[1] == FTX_FIELD_CALL && offsets.offsets[1] >= 0
            && offsets.offsets[1] < FT8_MESSAGE_CHARS ? offsets.offsets[1] + 1 : 0;
#ifdef FT8_RADIO
        /* Native FT8 uses two subdivisions in each dimension and 160 ms symbols. */
        row->frequency_hz = ((monitor->min_bin + c->freq_offset) * 50 + c->freq_sub * 25 + 4) / 8;
        row->offset_ms = c->time_offset * 160 + c->time_sub * 80;
#else
        const float bin = monitor->min_bin + c->freq_offset + (float)c->freq_sub / wf->freq_osr;
        const float block = c->time_offset + (float)c->time_sub / wf->time_osr;
        row->frequency_hz = (uint16_t)(bin / monitor->symbol_period + 0.5f);
        row->offset_ms = (int16_t)(block * (1000.0f * monitor->symbol_period));
#endif
        PROFILE_START(metrics);
        row->snr_db = estimate_snr(wf, c);
        row->distance_km = ft8_locator_distance(rx->locator, sender_locator(row->text, &offsets));
        PROFILE_END(metrics, PROF_METRICS, i);
        seen[decoded++] = message;
    }
    return decoded;
}
