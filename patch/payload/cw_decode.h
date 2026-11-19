#ifndef FTX1_CW_DECODE_H
#define FTX1_CW_DECODE_H

#include <stdint.h>

enum {
    CW_RATE = 16000, CW_DECIMATION = 4, CW_WINDOW = 240, CW_HOP = 20, CW_RUNS = 32,
    CW_SEGMENTS = 3, CW_COLUMNS = 52,
    CW_PITCH_MIN = 300, CW_PITCH_STEP = 10, CW_PITCH_MAX_RAW = 75,
};
#ifdef CW_VFP
enum {
    CW_REPLAY_HOPS = CW_RATE / CW_DECIMATION / CW_HOP / 10,
    CW_LEAD_IN_HOPS = 40,
    CW_AUDIO = CW_WINDOW + (CW_REPLAY_HOPS + CW_LEAD_IN_HOPS) * CW_HOP,
};
#else
enum { CW_AUDIO = CW_WINDOW };
#endif

struct cw_run {
    uint16_t ticks;
    uint8_t mark;
};

#ifdef CW_VFP
typedef double cw_power;
/* Float stores every possible four-sample mean exactly. Filtering uses double. */
typedef float cw_sample;
#else
typedef unsigned cw_power;
typedef int16_t cw_sample;
#endif

struct cw_decoder {
    cw_sample audio[CW_AUDIO];
    struct cw_run runs[CW_RUNS];
    unsigned cursor, fill, hop, scans, decimation;
    int input_sum;
    cw_power peak, noise;
    unsigned pitch, mark, started, ticks, mark_age, locked;
    unsigned level;
#ifdef CW_VFP
    unsigned replay_wait, replay_lead_in;
    cw_power replay_noise;
#endif
    int key_score;
    unsigned votes, weak;
    unsigned run_count, run_write, marks, timing, unit, gap_unit;
    unsigned letter, length, pending_space, gap_done;
    unsigned text_row, text_count, new_segment;
    unsigned text_length[CW_SEGMENTS];
    char text[CW_SEGMENTS][CW_COLUMNS + 1];
};

void cw_reset(struct cw_decoder *);
void cw_discontinuity(struct cw_decoder *);
void cw_feed(struct cw_decoder *, const int16_t *, unsigned);
unsigned cw_wpm(const struct cw_decoder *);
/* The pitch index comes from the selected VFO, using the stock 10 Hz steps. */
void cw_set_pitch(struct cw_decoder *, unsigned raw);
unsigned cw_tone_hz(const struct cw_decoder *);
unsigned cw_level(const struct cw_decoder *);

#endif
