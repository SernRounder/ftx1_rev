#include "cw_decode.h"
#include "custom_mode_ui.h"
#include "cw_panel.h"
#ifdef CW_VFP
void ft8_fft_prepare(void);
unsigned ft8_fft_backend(void);
#endif

#define STOCK(offset, type) ((type)(0x60400000u + (offset)))
#define UI ((const volatile uint8_t *)0x60935bb4u)
#define LOAD(p) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define STORE(p, v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)
#define INIT __attribute__((section(".data.ft8")))

typedef void (*void_fn)(void);
typedef unsigned (*uint_fn)(void);
typedef void *(*frame_fn)(unsigned);
typedef void (*fill_fn)(void *, unsigned, unsigned, unsigned, unsigned, unsigned);
typedef void (*bitmap_fn)(void *, unsigned, unsigned, const void *);
typedef void (*text_fn)(void *, const uint16_t *, unsigned, unsigned, unsigned, unsigned,
                        unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);
typedef void (*popup_fn)(const volatile uint8_t *, unsigned);
typedef unsigned (*hit_fn)(unsigned, unsigned, uint16_t *);
typedef unsigned (*capture_fn)(const volatile uint16_t *);
typedef void (*invalidate_fn)(const volatile void *, unsigned);

enum {
    MENU_NONE, MENU_CW,
#ifdef FT8_CUSTOM_MODES
    EVENT_CLOSE = 0x1138,
#else
    EVENT_CLOSE = 0x1134,
#endif
    FRAMES = 4, MAX_PCM = 2000, SCREEN_WIDTH = 800,
    CW_LOWER = 2, CW_UPPER = 3,
    DRAW_NONE, DRAW_DOCK,
    /* Interleaving verdicts for the captured word stream. */
    WORDS_MONO = 0, WORDS_DUPLICATED, WORDS_STEREO,
};

struct rect {
    unsigned x, y, w, h;
};

enum { DOCK_ROW_HEIGHT = 14, DOCK_HEIGHT = CW_SEGMENTS * DOCK_ROW_HEIGHT, DOCK_Y = 420 - DOCK_HEIGHT };
static const struct rect dock = {0, DOCK_Y, 800, DOCK_HEIGHT};
static const struct rect close_button = {732, DOCK_Y, 68, DOCK_HEIGHT};
static const unsigned background = 0x1082;
/* Decoded text starts right of the diagnostics caption column. */
enum { ROW_X = 140 };

struct audio_frame {
    unsigned sequence, count;
    int16_t pcm[MAX_PCM];
};

struct cw_work {
    struct cw_decoder decoder;
    struct audio_frame frames[FRAMES];
    unsigned read, write, sequence, expected, have_expected;
    unsigned revision, session, receiver, rx_frames;
    /* Stream classification, maintained in the capture context. */
    unsigned frame_words, demux, verdict, votes;
    long long ema_eo, ema_ee, ema_oo;
    unsigned ema_pair;
    /* Peak amplitude of the last copied frame, sampled in the capture
       context: separates "the DMA stream itself is silent" (P = 0) from
       "the decoder never sees the audio" (P > 0, L = 0). */
    unsigned rx_peak;
    /* Worker-side scratch when only one interleaved channel is fed. */
    int16_t scratch[MAX_PCM / 2];
};

/* In the combined build the radio adapter grants this arena only after
   the FT8 workspace and any borrowed TX DMA descriptor are released. */
static struct cw_work *const work = (void *)0x603d0880;
_Static_assert(sizeof(struct cw_work) < 0x8000, "CW workspace size");

static unsigned requested INIT = MENU_NONE;
static unsigned session INIT = 0;
static unsigned capture_enabled INIT = 0;
static unsigned last_paint INIT = 0;
static unsigned redraw INIT = 1;
static unsigned swallow_close_release INIT = 0;
#ifdef FT8_CUSTOM_MODES
static unsigned prepared INIT = 0;
#else
static unsigned displayed INIT = DRAW_NONE;
static const void *last_frame INIT = 0;
static unsigned mode_report INIT = 0;
static unsigned pending_back INIT = 0;
static unsigned back_owner INIT = 0;
static struct custom_mode_selection selection INIT = {0};
static int task_id INIT = 0;
#endif

static int contains(const struct rect *box, unsigned x, unsigned y)
{
    return x - box->x < box->w && y - box->y < box->h;
}

unsigned cw_panel_hit(unsigned x, unsigned y, uint16_t *detail)
{
    if (cw_visible() && contains(&close_button, x, y)) {
        *detail = 0;
        return EVENT_CLOSE;
    }
    return STOCK(0xc61e0, hit_fn)(x, y, detail);
}

static void stop_capture(void)
{
    STORE(&capture_enabled, 0);
#ifdef FT8_CUSTOM_MODES
    STORE(&prepared, 0);
#endif
}

int cw_local_touch(unsigned pressed, unsigned event)
{
    if (event != EVENT_CLOSE)
        return 0;
    if (pressed) {
        if (cw_visible()) {
            cw_set_active(0);
#ifndef FT8_CUSTOM_MODES
            STORE(&pending_back, selection.state);
#endif
            swallow_close_release = 1;
            redraw = 1;
            return 2;
        }
        return 0;
    }
    if (swallow_close_release) {
        swallow_close_release = 0;
        return 2;
    }
    return 0;
}

/* The captured word stream may be plain 16 kHz mono, or two interleaved
   channels (identical AF duplicated, or two different channels). Feeding
   interleaved words as mono smears the tone across the band and the gate
   never opens. Classify by pair statistics: a duplicated stream has a near
   zero cross-pair distance, a mono stream has highly correlated channel
   halves (band-limited audio), and a true two-channel stream does not.
   Runs in the worker on the copied frame only: the DMA completion path
   must not touch payload beyond the validated count. */
static void classify_words(struct cw_work *w, const int16_t *pcm, unsigned count)
{
    long long eo = 0, ee = 0, oo = 0;
    unsigned pair = 0, pairs = 0;
    for (unsigned i = 0; i + 3 < count; i += 2) {
        const int e = pcm[i], o = pcm[i + 1];
        const int e2 = pcm[i + 2], o2 = pcm[i + 3];
        eo += (long long)e * o;
        ee += (long long)e * e;
        oo += (long long)o * o;
        pair += (unsigned)(e > o ? e - o : o - e);
        pair += (unsigned)(e2 > o2 ? e2 - o2 : o2 - e2);
        pairs += 2;
    }
    if (!pairs)
        return;
    if (w->ema_ee == 0 && w->ema_oo == 0) {
        w->ema_eo = eo;
        w->ema_ee = ee;
        w->ema_oo = oo;
        w->ema_pair = pair / pairs;
        return;
    }
    w->ema_eo += eo - (w->ema_eo >> 3);
    w->ema_ee += ee - (w->ema_ee >> 3);
    w->ema_oo += oo - (w->ema_oo >> 3);
    w->ema_pair += pair / pairs - (w->ema_pair >> 3);
    const long long denom = w->ema_ee + w->ema_oo;
    if (denom < (long long)pairs * 2048)
        return; /* too quiet to judge; keep the previous mode */
    /* Correlation verdicts compared without division: the ratio
       512*eo/(ee+oo) against 179 (distinct channels) and 307 (one
       band-limited channel), scaled into 64-bit multiplies. */
    unsigned verdict = w->demux;
    if (w->ema_pair <= 2)
        verdict = WORDS_DUPLICATED;
    else if (512 * w->ema_eo < 179 * denom)
        verdict = WORDS_STEREO;
    else if (512 * w->ema_eo > 307 * denom)
        verdict = WORDS_MONO;
    if (verdict != w->verdict) {
        w->verdict = verdict;
        w->votes = 1;
    } else if (w->votes < 3) {
        ++w->votes;
    }
    if (w->votes >= 3)
        w->demux = w->verdict;
}

unsigned cw_capture(const volatile uint16_t *frame)
{
    const unsigned enabled = LOAD(&capture_enabled);
    if (enabled)
        STOCK(0x3000, invalidate_fn)(frame, (MAX_PCM + 2) * sizeof(*frame));
    const unsigned original = STOCK(0x450b4, capture_fn)(frame);
    if (!enabled)
        return original;
    const unsigned count = frame[0];
    if (!count)
        return original;
    ++work->rx_frames;
    work->frame_words = count;
    /* The payload is only read after the count passes the same bound the
       copy loop always used; a bad DMA header must not drive reads past
       the buffer. */
    if (count > MAX_PCM)
        return original;
    const unsigned sequence = work->sequence++;
    const unsigned index = work->write;
    if (index - LOAD(&work->read) >= FRAMES)
        return original;
    struct audio_frame *slot = &work->frames[index % FRAMES];
    slot->sequence = sequence;
    slot->count = count;
    unsigned peak = 0;
    for (unsigned i = 0; i < count; ++i) {
        const int sample = (int16_t)frame[i + 2];
        slot->pcm[i] = (int16_t)sample;
        const unsigned level = (unsigned)(sample < 0 ? -sample : sample);
        if (level > peak)
            peak = level;
    }
    work->rx_peak = peak;
    STORE(&work->write, index + 1);
    return original;
}

#ifdef FT8_CUSTOM_MODES
static int worker_ready(void)
{
    const unsigned ready = LOAD(&prepared);
    return ready && ready == LOAD(&session);
}

static int capture_if_enabled(const volatile uint16_t *frame, unsigned *metadata)
{
    if (LOAD(&requested) != MENU_CW || !worker_ready() || !LOAD(&capture_enabled))
        return 0;
    *metadata = cw_capture(frame);
    return 1;
}
#endif

static unsigned receiver(unsigned *pitch)
{
    /* Stock common status byte used by the panel's red TX LEDs. */
    if (UI[0x1f] & 0x22)
        return 0;
    const unsigned layout = *(volatile const uint8_t *)0x60939947;
    const unsigned side = STOCK(0x25838, unsigned (*)(unsigned, unsigned))(layout, UI[0xa4] >> 7);
    if (side > 1)
        return 0;
    const volatile uint8_t *const vfo = UI + side * 0x4c;
    /* The stock VFO label renderer reads the operating mode at +0xa3. */
    const unsigned mode = vfo[0xa3] & 0x1f;
    if (mode != CW_LOWER && mode != CW_UPPER)
        return 0;
    const unsigned raw = vfo[0xdd];
    if (UI[0] != 0x20 || raw > CW_PITCH_MAX_RAW)
        return 0;
    *pitch = raw;
    unsigned key = (side << 5) | mode;
    for (unsigned i = 0xa8; i < 0xad; ++i)
        key = (key * 16777619u) ^ vfo[i];
    return key ? key : 1;
}

/* The worker is the sole decoder writer. A revision brackets each audio
   block so the lower priority LCD task can take a consistent snapshot. */
void cw_worker_step(void)
{
#ifdef FT8_CUSTOM_MODES
    if (LOAD(&requested) != MENU_CW || !worker_ready())
        return;
#endif
    const unsigned current = LOAD(&session);
    unsigned pitch = 0;
    const unsigned tuned = LOAD(&requested) == MENU_CW ? receiver(&pitch) : 0;
    const int pitch_changed = tuned && pitch != work->decoder.pitch;
#ifdef CW_VFP
    if (tuned) {
        ft8_fft_prepare();
        if (ft8_fft_backend() != 2)
            return;
    }
#endif
    const unsigned read = work->read;
    if (current == work->session && tuned == work->receiver && !pitch_changed &&
        (!tuned || read == LOAD(&work->write)))
        return;
    const unsigned revision = work->revision;
    STORE(&work->revision, revision + 1);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    if (current != work->session || tuned != work->receiver || pitch_changed) {
        STORE(&capture_enabled, 0);
        STORE(&work->read, LOAD(&work->write));
        work->have_expected = 0;
        if (current != work->session) {
            cw_reset(&work->decoder);
            work->rx_frames = 0;
        } else
            cw_discontinuity(&work->decoder);
        work->session = current;
        work->receiver = tuned;
        cw_set_pitch(&work->decoder, pitch);
        STORE(&capture_enabled, tuned != 0);
    } else {
        const struct audio_frame *slot = &work->frames[read % FRAMES];
        if (work->have_expected && work->expected != slot->sequence)
            cw_discontinuity(&work->decoder);
        work->expected = slot->sequence + 1;
        work->have_expected = 1;
        const unsigned prior_demux = work->demux;
        classify_words(work, slot->pcm, slot->count);
        if (!!prior_demux != !!work->demux)
            cw_discontinuity(&work->decoder);
        const int16_t *pcm = slot->pcm;
        unsigned n = slot->count;
        if (work->demux) {
            /* Feed one channel of the interleaved stream; Morse timing and
               tone ratios survive the word-rate change untouched. */
            n /= 2;
            for (unsigned i = 0; i < n; ++i)
                work->scratch[i] = slot->pcm[2 * i];
            pcm = work->scratch;
        }
        cw_feed(&work->decoder, pcm, n);
        STORE(&work->read, read + 1);
    }
    STORE(&work->revision, revision + 2);
}

static void clear_workspace(void)
{
    unsigned char *bytes = (void *)work;
    for (unsigned i = 0; i < sizeof(*work); ++i)
        bytes[i] = 0;
}

#ifdef FT8_CUSTOM_MODES
static int start_worker(void)
{
    const unsigned current = LOAD(&session);
    if (!ft8_radio_cw_available() || !ft8_radio_start_worker())
        return 0;
    STORE(&capture_enabled, 0);
    clear_workspace();
    STORE(&prepared, current);
    return 1;
}
#else
static void cw_worker(unsigned unused)
{
    (void)unused;
    for (;;) {
        cw_worker_step();
        cw_worker_step();
        STOCK(0x797c8, int (*)(unsigned))(1);
    }
}

struct task_params {
    unsigned attr, exinf;
    void (*entry)(unsigned);
    unsigned priority, stack_bytes;
    void *stack;
    const char *name;
};

static int start_worker(void)
{
    static const struct task_params params = {
        0, 0, cw_worker, 6, 4096, (void *)0x606d0000, "cw-rx",
    };
    if (task_id > 0)
        return 1;
    if (task_id == 0) {
        clear_workspace();
        const int created = STOCK(0x78fb0, int (*)(unsigned, const struct task_params *))(0, &params);
        if (created <= 0)
            return 0;
        task_id = -created;
    }
    if (STOCK(0x7a830, int (*)(int, unsigned))(-task_id, 0) != 0)
        return 0;
    task_id = -task_id;
    return 1;
}

static int worker_ready(void)
{
    return task_id > 0;
}
#endif

static void fill(void *frame, const struct rect *box, unsigned color)
{
    STOCK(0x625a0, fill_fn)(frame, color, box->y, box->x, box->w, box->h);
}

static void text(void *frame, const char *label, unsigned x, unsigned y, unsigned bg,
                 unsigned size, unsigned align)
{
    uint16_t glyphs[72];
    unsigned count = 0;
    while (count < sizeof(glyphs) / sizeof(glyphs[0]) && label[count]) {
        glyphs[count] = (uint8_t)label[count];
        ++count;
    }
    STOCK(0x23d64, text_fn)(frame, glyphs, count, size, size, 0xffff, bg, x, y, align, 0, 1);
}

static char *put_text(char *dest, const char *text)
{
    while (*text)
        *dest++ = *text++;
    return dest;
}

static char *put_u32(char *dest, unsigned value)
{
    char reverse[10];
    unsigned n = 0;
    do {
        reverse[n++] = (char)('0' + value % 10);
        value /= 10;
    } while (value);
    while (n)
        *dest++ = reverse[--n];
    return dest;
}

/* Caption column: mode hint while not receiving CW, otherwise the configured
   tone, the armed code speed once locked, and the captured frame count.
   pitch and frame count show which tone and stream are being processed. */
static void build_caption(char *caption, const struct cw_work *w)
{
    char *out = caption;
    if (!w->receiver)
        out = put_text(out, "CW-U/L");
    else if (cw_wpm(&w->decoder)) {
        out = put_u32(out, cw_wpm(&w->decoder));
        out = put_text(out, "WPM ");
    } else
        out = put_text(out, "WAIT ");
    if (w->receiver) {
        out = put_u32(out, cw_tone_hz(&w->decoder));
        out = put_text(out, " R");
        out = put_u32(out, w->rx_frames);
    }
    *out = 0;
}

/* Idle diagnostics replace the unused first text row, splitting the chain
   into separately observable stages: F = words per captured frame,
   D = stream verdict (0 mono, 1 duplicated, 2 stereo), P = raw peak
   amplitude measured at capture, L = energy at the configured tone. */
static void build_diag(char *diag, const struct cw_work *w)
{
    char *out = put_text(diag, "F");
    out = put_u32(out, w->frame_words);
    out = put_text(out, " D");
    out = put_u32(out, w->demux);
    out = put_text(out, " P");
    out = put_u32(out, w->rx_peak);
    out = put_text(out, " L");
    out = put_u32(out, cw_level(&w->decoder));
    *out = 0;
}

static int draw_dock(void *frame)
{
    char rows[CW_SEGMENTS][CW_COLUMNS + 1] = {{0}};
    char caption[26];
    const char *offline = "CW OFFLINE";
    if (worker_ready()) {
        const unsigned before = LOAD(&work->revision);
        if (before & 1)
            return 0;
        const unsigned count = work->decoder.text_count;
        const unsigned first = work->decoder.text_row + CW_SEGMENTS + 1 - count;
        for (unsigned i = 0; i < count; ++i) {
            const unsigned index = (first + i) % CW_SEGMENTS;
            for (unsigned j = 0; j < work->decoder.text_length[index]; ++j)
                rows[i][j] = work->decoder.text[index][j];
        }
        build_caption(caption, work);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if (before != LOAD(&work->revision))
            return 0;
    } else {
        caption[0] = 0;
    }
    fill(frame, &dock, background);
    fill(frame, &close_button, 0x1f);
    text(frame, worker_ready() ? caption : offline, 7, DOCK_Y + DOCK_ROW_HEIGHT + 1,
         background, 12, 1);
    text(frame, "CLOSE", 739, DOCK_Y + DOCK_ROW_HEIGHT + 1, 0x1f, 12, 1);
    for (unsigned i = 0; i < CW_SEGMENTS; ++i)
        if (rows[i][0])
            text(frame, rows[i], ROW_X, DOCK_Y + i * DOCK_ROW_HEIGHT + 1, background, 12, 1);
    if (worker_ready() && !rows[0][0]) {
        char diag[30];
        build_diag(diag, work);
        text(frame, diag, ROW_X, DOCK_Y + 1, background, 12, 1);
    }
    return 1;
}

void cw_sync(int blocked)
{
    if (blocked) {
        cw_set_active(0);
        return;
    }
    if (LOAD(&requested) == MENU_CW && !worker_ready()) {
        const unsigned now = STOCK(0x1669c, uint_fn)();
        if (redraw || now - last_paint >= 100000) {
            start_worker();
            last_paint = now;
        }
    }
}

void cw_set_active(int active)
{
    if (active == (LOAD(&requested) == MENU_CW))
        return;
    stop_capture();
    if (active) {
        STORE(&session, session + 1);
        STORE(&requested, MENU_CW);
        start_worker();
    } else {
        STORE(&requested, MENU_NONE);
    }
    redraw = 1;
}

int cw_visible(void)
{
    return LOAD(&requested) == MENU_CW && custom_mode_visible();
}

int cw_draw(void *frame, int force)
{
    const unsigned now = STOCK(0x1669c, uint_fn)();
    if (!force && !redraw && now - last_paint < 100000)
        return 0;
    if (!draw_dock(frame))
        return 0;
    last_paint = now;
    redraw = 0;
    return 1;
}

#ifdef FT8_CUSTOM_MODES
const struct cw_panel_api cw_panel_api = {
    capture_if_enabled,
};
#else
void cw_touch(unsigned pressed, unsigned event);
void cw_readback_hook(void);

void cw_report_packet(uint8_t *packet, unsigned length)
{
    if (!length || !ft8_link_status_frame(packet[0], length) ||
        !(packet[FT8_LINK_STATUS_OFFSET] & FT8_LINK_STATUS_MASK))
        return;
    const unsigned flags = packet[FT8_LINK_MODE_FLAGS_OFFSET];
    if (flags & FT8_LINK_MODE_TAG)
        STORE(&mode_report, flags & ~FT8_LINK_SPA);
    ft8_link_restore_status(packet, length);
}

void cw_key_send_hook(const uint8_t *pkt, unsigned len)
{
    if (len == 5 && pkt[0] == 0xe0 && pkt[2] == 0x03 && pkt[3] == 0x0a) {
        const unsigned route = custom_mode_back_route(&back_owner, pkt[1],
                                                     cw_visible() ? selection.state : 0);
        if (route) {
            if (pkt[1] == 0)
                STORE(&pending_back, route);
            return;
        }
    }
    STOCK(0x14a1c, void (*)(const uint8_t *, unsigned))(pkt, len);
}

void cw_ui_worker(void)
{
    STOCK(0x41ff8, void_fn)();
    const unsigned state = LOAD(&mode_report);
    const unsigned back = __atomic_exchange_n(&pending_back, 0u, __ATOMIC_ACQ_REL);
    const int swr = swr_scan_active();
    if ((!swr || !(state & FT8_LINK_MODE_MASK)) && custom_mode_update(&selection, state))
        cw_set_active((state & FT8_LINK_MODE_MASK) == FT8_LINK_MODE_CW);
    else if (back && back == selection.state && !swr) {
        cw_set_active(0);
        custom_mode_close(&selection);
    }
    cw_sync(swr);
    custom_mode_retry_close(&selection);
}

void cw_pre_swap(void)
{
    const int swr = swr_scan_active();
    if (swr || custom_mode_visible()) {
        const unsigned next = cw_visible() ? DRAW_DOCK : DRAW_NONE;
        if (displayed == DRAW_DOCK && next != DRAW_DOCK) {
            for (unsigned idx = 3; idx <= 4; ++idx) {
                uint16_t *buf = STOCK(0x448b8, frame_fn)(idx);
                if (buf)
                    STOCK(0xbdd61, void (*)(void *, unsigned))(buf + DOCK_Y * SCREEN_WIDTH,
                                                              DOCK_HEIGHT * SCREEN_WIDTH * sizeof(uint16_t));
            }
            displayed = DRAW_NONE;
            last_frame = 0;
            if (!swr)
                custom_mode_restore_stock();
        }
        if (next == DRAW_DOCK) {
            uint16_t *const frame = STOCK(0x448b8, frame_fn)(*(const volatile unsigned *)0x607c4bb0);
            if (frame) {
                const int wiped = frame[(DOCK_Y + DOCK_HEIGHT - 1) * SCREEN_WIDTH] == 0;
                if (cw_draw(frame, displayed != DRAW_DOCK || frame != last_frame || wiped)) {
                    displayed = DRAW_DOCK;
                    last_frame = frame;
                }
            }
        }
    } else {
        redraw = 1;
    }
    ((void (*)(void))0x604b0bad)();
}

const void *const cw_hooks[] __attribute__((section(".ft8_hooks"), used)) = {
    (const void *)cw_panel_hit, (const void *)cw_touch, (const void *)cw_ui_worker,
    (const void *)cw_pre_swap, (const void *)cw_key_send_hook,
    (const void *)cw_readback_hook, (const void *)cw_capture,
};
#endif
