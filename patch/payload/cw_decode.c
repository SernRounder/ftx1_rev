#include "cw_decode.h"

enum { DOT_Q = 256, SEGMENT_DOTS = 5 * 3, REACQUIRE_STEPS = 500 };

/* 2*cos(2*pi*f/4000), from 20 to 1000 Hz in 10 Hz steps.
   Frequencies above 1000 Hz use the negated reflected coefficient. */
enum { GUARD_STEP = 7, GUARD_COUNT = 4, GUARD_STEPS = GUARD_COUNT * GUARD_STEP,
       COEFF_MID = 1000 / CW_PITCH_STEP - (CW_PITCH_MIN / CW_PITCH_STEP - GUARD_STEPS) };
#ifdef CW_VFP
/* Store every fourth entry. Sine interpolation reconstructs the
   intermediate cosines to the precision of the stored Q30 entries. */
static const int32_t coefficient[] = {
    2146423994, 2137953040, 2121044561, 2095765288, 2062214987, 2020526066, 1970863052, 1913421941,
    1848429428, 1776142009, 1696844968, 1610851256, 1518500250, 1420156417, 1316207875, 1207064863,
    1093158116, 974937175, 852868601, 727434145, 599128838, 468459044, 335940456, 202096064,
    67454091, -67454091,
};
#ifdef __arm__
#define cw_feed cw_feed_vfp
#define cw_discontinuity cw_discontinuity_vfp
#endif
#else
static const int16_t coefficient[] = {
    32752, 32732, 32703, 32667, 32623, 32570, 32510, 32441, 32365, 32280,
    32188, 32087, 31979, 31863, 31739, 31607, 31467, 31319, 31164, 31001,
    30831, 30653, 30467, 30274, 30073, 29865, 29649, 29427, 29197, 28959,
    28715, 28463, 28205, 27939, 27667, 27388, 27102, 26809, 26510, 26204,
    25892, 25573, 25248, 24917, 24580, 24236, 23887, 23532, 23170, 22804,
    22431, 22053, 21670, 21281, 20887, 20488, 20084, 19675, 19261, 18842,
    18418, 17990, 17558, 17121, 16680, 16235, 15786, 15333, 14876, 14416,
    13952, 13485, 13014, 12540, 12063, 11583, 11100, 10614, 10126, 9635,
    9142, 8647, 8149, 7650, 7148, 6645, 6140, 5634, 5126, 4617,
    4107, 3596, 3084, 2571, 2058, 1544, 1029, 515, 0,
};
#endif
#ifdef CW_VFP
_Static_assert(sizeof(coefficient) / sizeof(coefficient[0]) == (COEFF_MID + 3) / 4 + 1,
               "pitch coefficient table");

static double pitch_coefficient(unsigned bin)
{
    static const double weight[]
#ifdef FT8_HOOK_VECTORS
        __attribute__((section(".cw_tone_table")))
#endif
        = { 0.0, 0.25015428172222415, 0.50024684161857225, 0.75021597309210508 };
    const int reflected = bin > COEFF_MID;
    if (reflected)
        bin = 2 * COEFF_MID - bin;
    const unsigned part = bin % 4;
    const double a = coefficient[bin / 4];
    const double value = part ? weight[4 - part] * a + weight[part] * coefficient[bin / 4 + 1] : a;
    return (reflected ? -value : value) * (1.0 / (1u << 30));
}
#else
_Static_assert(sizeof(coefficient) / sizeof(coefficient[0]) == COEFF_MID + 1,
               "pitch coefficient table");

static int pitch_coefficient(unsigned bin)
{
    return bin <= COEFF_MID ? coefficient[bin] : -coefficient[2 * COEFF_MID - bin];
}
#endif

static unsigned difference(unsigned a, unsigned b)
{
    return a < b ? b - a : a - b;
}

void cw_reset(struct cw_decoder *d)
{
    unsigned char *bytes = (void *)d;
    for (unsigned i = 0; i < sizeof(*d); ++i)
        bytes[i] = 0;
}

void cw_discontinuity(struct cw_decoder *d)
{
    d->fill = d->mark = d->started = d->ticks = d->level = 0;
    d->peak = d->noise = 0;
    d->key_score = 0;
    d->hop = d->scans = d->mark_age = 0;
    d->decimation = d->input_sum = d->locked = 0;
    d->votes = 0;
#ifdef CW_VFP
    d->replay_wait = 0;
#endif
    d->run_count = d->run_write = d->marks = d->timing = d->unit = 0;
    d->gap_unit = 0;
    d->letter = d->length = d->pending_space = d->gap_done = 0;
}

static cw_power power_at(const struct cw_decoder *d, unsigned bin, unsigned count,
                         unsigned behind)
{
#ifdef CW_VFP
    const double coef = pitch_coefficient(bin);
    double a = 0, b = 0;
#else
    const int coef = pitch_coefficient(bin);
    int32_t a = 0, b = 0;
#endif
    unsigned position = (d->cursor + CW_AUDIO - behind - count) % CW_AUDIO;
    for (unsigned i = 0; i < count; ++i) {
#ifdef CW_VFP
        const double next = d->audio[position++] + coef * a - b;
#else
        const int32_t next = d->audio[position++] + (int32_t)(((int64_t)coef * a) >> 14) - b;
#endif
        b = a;
        a = next;
        if (position == CW_AUDIO)
            position = 0;
    }
#ifdef CW_VFP
    return a * a + b * b - coef * a * b;
#else
    const int64_t cross = (((int64_t)coef * a) >> 14) * b;
    const uint64_t energy = (uint64_t)((int64_t)a * a + (int64_t)b * b - cross) >> 12;
    return energy > UINT32_MAX ? UINT32_MAX : (unsigned)energy;
#endif
}

static cw_power power(const struct cw_decoder *d, unsigned bin, unsigned count)
{
    return power_at(d, bin, count, 0);
}

/* The guards estimate nearby interference. Only the configured pitch
   can acquire lock or feed the key detector. */
static void measure_pitch(struct cw_decoder *d)
{
    const unsigned bin = d->pitch + GUARD_STEPS;
    const cw_power center = power(d, bin, CW_WINDOW);
    /* Sample the noise around the pitch. Exclude the largest probe so
       one nearby carrier cannot raise the gate by itself. The short moving
       average keeps individual bursts of noise from splitting a dot. */
#ifdef CW_VFP
    cw_power total = 0;
#else
    uint64_t total = 0;
#endif
    cw_power highest = 0;
    for (unsigned i = 0; i <= 2 * GUARD_COUNT; ++i) {
        if (i == GUARD_COUNT)
            continue;
        const cw_power probe = power(d, d->pitch + i * GUARD_STEP, CW_WINDOW);
        total += probe;
        if (probe > highest)
            highest = probe;
    }
    const cw_power noise = (total - highest) / (2 * GUARD_COUNT - 1);
    const cw_power local = noise / 3;
    d->noise = d->noise ? d->noise - d->noise / 4 + local / 4 : local;
    if (d->locked)
        return;
#ifdef CW_VFP
    const unsigned acquire_ratio = 6;
#else
    /* Without onset replay, a premature lock in noise can corrupt timing
       before the first real mark; require stronger initial evidence. */
    const unsigned acquire_ratio = 12;
#endif
    if (center < 8 || center / acquire_ratio < noise || center / 2 < highest) {
        d->votes = 0;
        return;
    }
    const unsigned strong = center / 8 >= noise &&
                            power(d, bin, CW_WINDOW / 3) / 24 >= d->noise;
    if (++d->votes >= 3 || strong) {
        d->locked = 1;
        d->weak = !strong;
        d->mark_age = 0;
    }
}

static void append(struct cw_decoder *d, char value)
{
    if (d->new_segment) {
        d->text_row = (d->text_row + 1) % CW_SEGMENTS;
        d->text_length[d->text_row] = 0;
        if (d->text_count < CW_SEGMENTS)
            ++d->text_count;
        d->new_segment = 0;
    } else if (!d->text_count) {
        d->text_count = 1;
    }
    unsigned *const length = &d->text_length[d->text_row];
    char *const row = d->text[d->text_row];
    if (*length == CW_COLUMNS) {
        for (unsigned i = 1; i < CW_COLUMNS; ++i)
            row[i - 1] = row[i];
        --*length;
    }
    row[(*length)++] = value;
    row[*length] = 0;
}

/* A letter flushed with full timing confidence prints as-is; one flushed
   from a collapsed or overlong code prints in lowercase so weak material
   still reaches the operator instead of being dropped silently. */
static void flush_letter(struct cw_decoder *d, int confident)
{
    /* Index a binary Morse tree rooted at 1, dot = left, dash = right. */
    static const char tree[] =
        "??ETIANMSURWDKGOHVF?L?PJBXCYZQ??"
        "54?3???2???????16???????7???8?90";
    if (!d->length)
        return;
    if (d->pending_space && d->text_count && !d->new_segment)
        append(d, ' ');
    char value = d->letter < sizeof(tree) - 1 ? tree[d->letter] : '?';
    if (!confident && value >= 'A' && value <= 'Z')
        value += 'a' - 'A';
    append(d, value);
    d->pending_space = d->length = d->letter = 0;
}

static void finish_segment(struct cw_decoder *d)
{
    /* The next decoded character opens the row. Idle audio cannot enqueue
       blank rows or push a previous segment out of the three-row history. */
    d->new_segment = d->text_count != 0;
    d->pending_space = 0;
}

static void consume(struct cw_decoder *d, unsigned mark, unsigned duration)
{
    if (mark) {
        if (d->length >= 6) {
            /* More keying elements than any Morse letter: emit the partial
               code as a low-confidence guess and restart on this element. */
            flush_letter(d, 0);
        }
        const unsigned node = d->length ? d->letter : 1;
        d->letter = 2 * node + (duration >= 2 * d->unit);
        ++d->length;
        return;
    }
    /* Gap classification lives on its own clock: tone-gate clipping
       shortens marks and lengthens gaps by the same absolute amount, so a
       single unit cannot serve both domains. The ratio between element,
       letter, and word gaps survives clipping; comparing them against a
       gap-domain unit preserves it. */
    if (duration >= 2 * d->gap_unit)
        flush_letter(d, 1);
    if (duration > SEGMENT_DOTS * d->gap_unit)
        finish_segment(d);
    else if (duration >= 5 * d->gap_unit && !d->new_segment)
        d->pending_space = 1;
}

static void remember(struct cw_decoder *d, unsigned mark, unsigned ticks)
{
    d->runs[d->run_write++ % CW_RUNS] = (struct cw_run){ticks, mark};
    if (d->run_count < CW_RUNS)
        ++d->run_count;
    if (mark)
        ++d->marks;
}

static unsigned estimate(const struct cw_decoder *d)
{
    unsigned best = ~0u, unit = 0;
    /* 10 WPM covers slow hand-sent practice traffic; 45 covers fast bug
       sending. Keying ratios are scale-invariant, so a wrong initial guess
       still adapts after lock. */
    for (unsigned wpm = 10; wpm <= 45; ++wpm) {
        const unsigned dot = 240 * DOT_Q / wpm;
        unsigned score = 0;
        for (unsigned i = d->run_write - d->run_count; i != d->run_write; ++i) {
            const struct cw_run run = d->runs[i % CW_RUNS];
            const unsigned duration = run.ticks * DOT_Q;
            if (!run.mark && duration >= 4 * dot)
                continue;
            const unsigned short_error = difference(duration, dot);
            const unsigned long_error = difference(duration, 3 * dot);
            const unsigned error = short_error < long_error ? short_error : long_error;
            unsigned relative = error * 32 / dot;
            if (relative > 64)
                relative = 64;
            score += run.mark ? 4 * relative : relative;
        }
        if (score < best) {
            best = score;
            unit = dot;
        }
    }
    return unit;
}

/* Pull the tracked dot length toward a fresh measurement: halfway when
   far off, a fine trim when close. Unstable fists and gate-clipped marks
   move the estimate faster than an eighth-weight blend can follow. */
static unsigned blend_unit(unsigned unit, unsigned measured)
{
    return difference(measured, unit) * 4 > unit ? (unit + measured) / 2
                                                 : (7 * unit + measured) / 8;
}

static void run_ended(struct cw_decoder *d, unsigned mark, unsigned ticks)
{
    /* Even a 60 WPM dot lasts ~21 ms, while gate leakage on broadband noise
       survives only a couple of correlated 5 ms analysis steps. Runs shorter
       than three steps are noise, not keying. */
    if (ticks < 3)
        return;
    const unsigned duration = ticks * DOT_Q;
    if (!d->timing) {
        if (mark && ticks >= 240 / 45)
            d->mark_age = 0;
        remember(d, mark, ticks);
        if (d->marks < 6)
            return;
        d->unit = estimate(d);
        d->gap_unit = d->unit;
        d->timing = 1;
        for (unsigned i = d->run_write - d->run_count; i != d->run_write; ++i) {
            const struct cw_run run = d->runs[i % CW_RUNS];
            consume(d, run.mark, run.ticks * DOT_Q);
        }
        return;
    }
    if (mark) {
        const unsigned measured = duration >= 2 * d->unit ? duration / 3 : duration;
        if (difference(measured, d->unit) * 2 <= d->unit) {
            d->unit = blend_unit(d->unit, measured);
            d->mark_age = 0;
        } else {
            /* Timing collapsed: keep the partial letter visible as a
               lowercase guess, then retrain from a clean slate. */
            d->timing = d->marks = d->run_count = 0;
            flush_letter(d, 0);
            d->length = d->letter = 0;
            remember(d, mark, ticks);
            return;
        }
    } else if (duration * 4 >= d->unit * 3 &&
               difference(duration, d->gap_unit) * 4 <= d->gap_unit * 3) {
        /* Element gaps carry their own clock and arrive more often than
           marks. Tracking them in the gap domain keeps element/letter
           classification correct when the tone gate clips marks short or
           the fist drifts, which is what stops runs of single-dot "e".
           Letter and word gaps fall outside the window and never blend. */
        d->gap_unit = blend_unit(d->gap_unit, duration);
    }
    /* The gap estimate may adapt to clipped envelopes, but short noise
       holes cannot pull it below the element time of the marks. */
    if (d->gap_unit * 4 < d->unit * 3)
        d->gap_unit = d->unit * 3 / 4;
    consume(d, mark, duration);
}

#ifdef CW_DEBOUNCE
/* The caller applies a lower gate while keyed. Require consecutive hops
   across that gate to commit an edge, restarting on any contrary hop. */
static unsigned key_state(struct cw_decoder *d, cw_power tone, cw_power gate)
{
    const unsigned observed = tone >= gate;
    if (observed == d->mark) {
        d->key_score = 0;
        return d->mark;
    }
    int hops = d->weak ? 4 : 2;
    /* Bridge a brief dropout after a mark has already passed dot length. */
    const unsigned elapsed = d->ticks * DOT_Q;
    if (!d->weak && d->timing && d->mark && d->unit >= 10 * DOT_Q &&
        elapsed > d->unit && elapsed < 3 * d->unit)
        hops = 7;
    if (++d->key_score < hops)
        return d->mark;
    d->key_score = 0;
    return observed;
}
#else
/* Two-state max-log filter: the state scores describe key up/down. The
   switch cost bounds prior odds; each observation adds an approximate
   log likelihood ratio from the tone power relative to the noise gate. */
static unsigned key_state(struct cw_decoder *d, cw_power tone, cw_power gate)
{
    int cost = d->weak ? 12 : 5;
    /* A transition midway through a likely dash has lower prior odds.
       The long weak-signal window already smooths brief dropouts. */
    if (!d->weak && d->timing && d->mark && d->unit >= 10 * DOT_Q && d->ticks * DOT_Q > d->unit &&
        d->ticks * DOT_Q < 3 * d->unit)
        cost += 24;
    int prior = d->key_score;
    if (prior > cost)
        prior = cost;
    if (prior < -cost)
        prior = -cost;
    /* Saturation prevents a single strong spike from opening the gate. */
#ifdef CW_VFP
    const int margin = tone >= 2 * gate ? 2 : (int)(2 * tone / gate) - 2;
#else
    const int margin = tone / 2 >= gate ? 2 : (int)(2 * (uint64_t)tone / gate) - 2;
#endif
    const int evidence = (tone >= gate ? 6 : -6) + margin;
    d->key_score = prior + evidence;
    return d->mark ? d->key_score > -cost : d->key_score >= cost;
}
#endif

static void detect_key(struct cw_decoder *d, unsigned behind)
{
    /* Integrate weak tones longer while retaining short edges at high speed. */
    const unsigned width = d->weak ? CW_WINDOW : CW_WINDOW / 3;
    const unsigned available = d->fill - behind;
    const unsigned count = available < width ? available : width;
    const cw_power tone = power_at(d, d->pitch + GUARD_STEPS, count, behind) / (d->weak ? 9 : 1);
    const cw_power noise = d->noise;
#ifdef CW_VFP
    d->peak *= 63.0 / 64;
#else
    d->peak -= d->peak / 64 + (d->peak % 64 != 0);
#endif
    if (tone > d->peak && tone / 4 >= noise)
        d->peak = tone;
    const cw_power threshold = d->peak / (d->weak ? 8u : d->mark ? 4u : 3u);
    const unsigned ratio = d->weak ? (d->mark ? 1u : 2u) : (d->mark ? 4u : 6u);
#ifdef CW_VFP
    cw_power gate = ratio * noise;
    d->level = d->peak >= 4 ? 1 + (unsigned)(d->peak / 4096) : 0;
#else
    unsigned gate = noise <= UINT32_MAX / ratio ? ratio * noise : UINT32_MAX;
#endif
    if (gate < threshold)
        gate = threshold;
    if (gate < 4)
        gate = 4;
    const unsigned signal = key_state(d, tone, gate);
    if (d->ticks < UINT16_MAX)
        ++d->ticks;
    if (signal != d->mark) {
        if (d->started)
            run_ended(d, d->mark, d->ticks);
        d->mark = signal;
        d->started = 1;
        d->gap_done = 0;
#ifdef CW_VFP
        d->ticks = 0;
#else
        d->ticks = !d->timing && !d->marks && signal ? (d->weak ? 8u : 2u) : 0;
#endif
    }
    if (d->timing && !d->mark) {
        const unsigned silence = d->ticks * DOT_Q;
        if (!d->gap_done && silence >= 3 * d->gap_unit) {
            flush_letter(d, 1);
            d->gap_done = 1;
        }
        if (!d->new_segment && silence > SEGMENT_DOTS * d->gap_unit)
            finish_segment(d);
    }
}

static void analyze(struct cw_decoder *d)
{
#ifdef CW_VFP
    const unsigned was_locked = d->locked;
#endif
    if ((d->scans++ & 1u) == 0)
        measure_pitch(d);
    if (!d->locked)
        return;
#ifdef CW_VFP
    if (!was_locked) {
        const unsigned available = (d->fill - 1) / CW_HOP;
        d->replay_lead_in = available < CW_LEAD_IN_HOPS ? available : CW_LEAD_IN_HOPS;
        d->replay_wait = CW_REPLAY_HOPS;
        d->replay_noise = d->noise;
        return;
    }
    if (d->replay_wait) {
        if (--d->replay_wait)
            return;
        /* Replay the onset at the configured pitch, including its lead-in.
           Only the live path below processes the current hop. */
        const cw_power live_noise = d->noise;
        d->noise = d->replay_noise;
        unsigned hops = CW_REPLAY_HOPS + d->replay_lead_in;
        while (hops) {
            detect_key(d, hops * CW_HOP);
            --hops;
        }
        d->noise = live_noise;
    }
#endif
    detect_key(d, 0);
    if (++d->mark_age >= REACQUIRE_STEPS) {
        flush_letter(d, 1);
        cw_discontinuity(d);
    }
}

void cw_feed(struct cw_decoder *d, const int16_t *audio, unsigned count)
{
    for (unsigned i = 0; i < count; ++i) {
        d->input_sum += audio[i];
        if (++d->decimation != CW_DECIMATION)
            continue;
#ifdef CW_VFP
        /* Preserve both fractional bits of the four-sample mean. */
        d->audio[d->cursor++] = d->input_sum * (1.0f / CW_DECIMATION);
#else
        d->audio[d->cursor++] = d->input_sum / CW_DECIMATION;
#endif
        d->input_sum = d->decimation = 0;
        if (d->cursor == CW_AUDIO)
            d->cursor = 0;
        if (d->fill < CW_AUDIO)
            ++d->fill;
        if (++d->hop == CW_HOP) {
            d->hop = 0;
            if (d->fill >= CW_WINDOW)
                analyze(d);
        }
    }
}

unsigned cw_wpm(const struct cw_decoder *d)
{
    return d->timing ? (240 * DOT_Q + d->unit / 2) / d->unit : 0;
}

void cw_set_pitch(struct cw_decoder *d, unsigned raw)
{
    d->pitch = raw;
}

unsigned cw_tone_hz(const struct cw_decoder *d)
{
    return CW_PITCH_MIN + CW_PITCH_STEP * d->pitch;
}

unsigned cw_level(const struct cw_decoder *d)
{
#ifdef CW_VFP
    return d->level;
#else
    return d->peak;
#endif
}
