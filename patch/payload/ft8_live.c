#include "ft8_live.h"
#include "ft8_locator.h"
#include "ft8_tx.h"
#include "ft8_profile.h"
#include "ft8_ui_layout.h"
#ifdef FT8_CUSTOM_MODES
#include "cw_panel.h"
#endif

#ifdef FT8_SD_PLUGIN
#include "ft8_plugin.h"
#endif
#ifdef FT8_HOOK_VECTORS
/* Keep the streaming data plane in the first region. UI and new policies
   enter through the tail vector table and can evolve independently. */
#pragma clang section text=".ft8_live_text" rodata=".ft8_live_rodata"
#endif

#ifndef FT8_DEFAULT_GRID
#define FT8_DEFAULT_GRID ""
#endif

#define CORE ((const struct ft8_arm_api *)0x606c2fc0u)
#define LOAD(p) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define STORE(p, v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)
#define INIT __attribute__((section(".data.ft8")))
#ifdef FT8_RADIO
#define LOCK_RX() ((unsigned (*)(void))0x604bfa8cu)()
#define UNLOCK_RX(state) ((void (*)(unsigned))0x604bfaacu)(state)
#endif

enum {
#ifdef FT8_PROFILE
    RING_FRAMES = 6,
#elif defined(FT8_RADIO)
    /* Leave room in the stock pool for both slot histories. */
    RING_FRAMES = 9,
#else
    RING_FRAMES = 8,
#endif
#ifdef FT8_RADIO
    RX_QUEUE_FRAMES = RING_FRAMES - 1,
#endif
    TX_BLOCK = 800, TX_BLOCK_MS = 50, TX_LEAD_BLOCKS = 6,
    TX_BLOCKS = TX_LEAD_BLOCKS + (FT8_TX_SAMPLES + TX_BLOCK - 1) / TX_BLOCK,
    TX_LEASE_MS = 13500, TX_MAX_CATCHUP = 3, TX_MAX_SLOT_AGE_MS = 150,
#ifdef FT8_RADIO
    TX_ARM_TIMEOUT_MS = 17000,
#endif
};

struct frame_slot {
    uint32_t epoch, sequence, count, end_ms;
#ifdef FT8_RADIO
    uint32_t sample_start, rx_phase;
#endif
    int16_t pcm[FT8_FRAME_MAX_SAMPLES];
};

struct workspace {
    uint32_t write, read, capture_sequence;
    uint32_t worker_epoch, skip, samples, expect, waiting_for_frame, synced;
#ifdef FT8_RADIO
    uint32_t skip_rx;
    uint32_t captured_samples, expected_sample, rx_phase;
    uint8_t ring_index[RX_QUEUE_FRAMES], worker_slot;
#ifdef FT8_PROFILE
    unsigned scan_started;
#endif
    uint32_t shown_list;
    struct ft8_rx_result results[2][FT8_LIST_RESULTS], decoded[FT8_LIST_RESULTS];
#endif
    struct ft8_rx *rx;
    uint32_t published_revision;
    unsigned char published[sizeof(struct ft8_live_view)];
    struct ft8_live_view view;
#ifdef FT8_RADIO
    struct ft8_live_view screen;
#endif
    struct ft8_ui_state ui;
    struct frame_slot ring[RING_FRAMES];
    struct ft8_tx_io tx_io;
    uint32_t ui_revision, tx_ready, tx_pending, tx_cancel;
    uint32_t tx_phase, tx_epoch, tx_ticket, tx_hz;
    uint32_t tx_started_ms, tx_lease_ms, tx_submitted;
    uint32_t tx_end_status, tx_completed;
#ifdef FT8_RADIO
    uint8_t tx_is_free, tx_auto;
#endif
    uint8_t tx_tones[FT8_TX_SYMBOLS];
    char tx_text[FT8_MESSAGE_CHARS];
    int16_t tx_mono[TX_BLOCK];
#ifndef FT8_RADIO
    int16_t tx_block[TX_BLOCK * 2];
    _Alignas(8) unsigned char decoder[FT8_ARM_WORK_BYTES];
#endif
    _Alignas(8) unsigned char synth[sizeof(struct ft8_tx)];
};

static struct workspace *workspace INIT = NULL;
#ifdef FT8_RADIO
struct ft8_live_view *ft8_live_screen(void)
{
    struct workspace *w = LOAD(&workspace);
    return w ? &w->screen : NULL;
}
#endif
/* One writer (UI task). The low bit denotes a running menu session. */
static uint32_t epoch INIT = 0;
static uint32_t position_grid INIT = 0;
#ifdef FT8_RADIO
static uint32_t capturing INIT = 0;
#endif

/* The native clock is the wrapping stock 32-bit microsecond counter. */
static uint32_t elapsed_ms(uint32_t now, uint32_t then)
{
#ifdef FT8_RADIO
    if (now < then)
        now += UINT32_MAX / 1000 + 1;
#endif
    return now - then;
}

static uint32_t current_grid(void)
{
#ifdef FT8_RADIO
    const uint32_t gps = LOAD(&workspace) ? CORE->radio->station_grid() : 0;
    if (gps)
        return gps;
#endif
    const uint32_t grid = LOAD(&position_grid);
    return grid ? grid : ft8_locator_parse(FT8_DEFAULT_GRID);
}

static int set_position(int32_t latitude_e6, int32_t longitude_e6)
{
    const uint32_t grid = ft8_locator_coordinates(latitude_e6, longitude_e6);
    STORE(&position_grid, grid);
    return grid != 0;
}

static int set_grid(const char *text)
{
    const uint32_t grid = ft8_locator_parse(text);
    if (!grid)
        return 0;
    STORE(&position_grid, grid);
    return 1;
}

static int core_present(void)
{
    return CORE->magic == FT8_ARM_MAGIC && CORE->version == FT8_ARM_VERSION &&
           CORE->work_bytes == FT8_ARM_WORK_BYTES && CORE->stack_bytes == FT8_ARM_STACK_BYTES;
}

void ft8_live_set_active(int active)
{
#ifdef FT8_RADIO
    const int have_radio = core_present();
    if (active && have_radio && !CORE->radio->menu(1))
        return;
#endif
    uint32_t current = LOAD(&epoch);
    if ((current & 1u) != (unsigned)active)
        STORE(&epoch, current + 1u);
#ifdef FT8_RADIO
    if (!active && have_radio)
        CORE->radio->menu(0);
#endif
}

static int bind(void *memory, size_t length)
{
    if (!memory || (uintptr_t)memory % 8 || length < sizeof(struct workspace) ||
        LOAD(&workspace) || (LOAD(&epoch) & 1u) || !core_present())
        return 0;
    struct workspace *w = memory;
    w->write = w->read = w->capture_sequence = 0;
    w->worker_epoch = w->skip = w->samples = w->expect = w->waiting_for_frame = w->synced = 0;
#ifdef FT8_RADIO
    w->skip_rx = 0;
    for (unsigned i = 0; i < RX_QUEUE_FRAMES; ++i)
        w->ring_index[i] = i;
    w->worker_slot = RX_QUEUE_FRAMES;
    w->screen.epoch = 0;
    w->shown_list = 0;
    w->view.rx_total = w->view.rx_list = w->view.rx_scans = 0;
    w->captured_samples = w->expected_sample = w->rx_phase = 0;
#ifdef FT8_PROFILE
    w->scan_started = 0;
#endif
#endif
    w->rx = NULL;
    w->published_revision = 0;
    w->view.epoch = w->view.status = w->view.count = w->view.grid = 0;
    w->view.tx_count = w->view.tx_status = 0;
#ifdef FT8_RADIO
    w->view.tx_wait_s = 0;
    w->view.tx_current[0] = 0;
    __builtin_memset(w->view.slot_total, 0, sizeof(w->view.slot_total));
    __builtin_memset(w->view.slot_batch, 0, sizeof(w->view.slot_batch));
    __builtin_memset(w->view.slot_count, 0, sizeof(w->view.slot_count));
    w->view.slot_timed = 0;
#endif
    w->tx_phase = FT8_TX_IDLE;
    w->ui_revision = w->tx_ready = w->tx_pending = w->tx_cancel = 0;
    w->tx_epoch = w->tx_ticket = 0;
    for (size_t i = 0; i < sizeof(w->ui); ++i)
        ((unsigned char *)&w->ui)[i] = 0;
#ifdef FT8_RADIO
    CORE->radio->station_call(w->ui.my_call);
#endif
    w->ui.selection = FT8_TX_CQ;
    for (size_t i = 0; i < FT8_TX_ROWS; ++i)
        for (size_t j = 0; j < FT8_MESSAGE_CHARS; ++j)
            w->view.tx[i][j] = 0;
    for (size_t i = 0; i < sizeof(w->published); ++i)
        w->published[i] = 0;
    STORE(&workspace, w);
    return 1;
}

#ifdef FT8_PROFILE
__attribute__((section(".text.ft8_debug_capture")))
#endif
uint32_t ft8_live_capture(const volatile uint16_t *frame)
{
    typedef uint32_t (*stock_frame_fn)(const volatile uint16_t *);
#ifdef FT8_CUSTOM_MODES
    unsigned cw_metadata;
    if (core_present() && CORE->custom->capture(frame, &cw_metadata))
        return cw_metadata;
#endif
#ifdef FT8_RADIO
    STORE(&capturing, 1);
#endif
    const uint32_t session = LOAD(&epoch);
    struct workspace *w = LOAD(&workspace);
#ifdef FT8_RADIO
    const int receive = w && (session & 1u) &&
        LOAD(&w->tx_phase) - FT8_TX_SENDING > FT8_TX_STOPPING - FT8_TX_SENDING;
    if (receive) {
        typedef void (*invalidate_fn)(const volatile void *, size_t);
        /* The stock DMA buffers are cache-line aligned. Invalidate the
           read-only header and lane before the CPU consumes their new data. */
        ((invalidate_fn)0x60403000u)(frame, (FT8_FRAME_MAX_SAMPLES + 2) * sizeof(*frame));
    }
#endif
    const uint32_t original = ((stock_frame_fn)0x604450b4u)(frame);
#ifdef FT8_PROFILE
    if (w && (session & 1u))
        ft8_profile_capture(PROF_DMA_FIRST, LOAD(&w->tx_phase));
#endif
#ifdef FT8_RADIO
    if (!receive)
#else
    if (!w || !(session & 1u))
#endif
        goto out;

    uint32_t count = frame[0];
    uint32_t skip = 0;
    uint32_t end = LOAD(&w->tx_ready) ? w->tx_io.now_ms() : 0;
    const uint32_t write = w->write;
#ifdef FT8_RADIO
    if (!count || count > FT8_FRAME_MAX_SAMPLES)
        goto out;
    unsigned phase = ft8_radio_rx_phase(end);
    if (phase < FT8_PERIOD_MS) {
        /* The DMA timestamp describes the end of this frame. Keep only
           samples on the receive side of either slot boundary. */
        const unsigned after_start = phase * 16;
        if (after_start < count) {
            skip = count - after_start;
            count = after_start;
        }
        if (phase > FT8_CAPTURE_END_MS) {
            const unsigned tail = (phase - FT8_CAPTURE_END_MS) * 16;
            if (tail >= count)
                goto out;
            count -= tail;
            end -= phase - FT8_CAPTURE_END_MS;
            if (end > UINT32_MAX / 1000)
                end += UINT32_MAX / 1000 + 1;
            phase = FT8_CAPTURE_END_MS;
        }
        if (!count)
            goto out;
    }
    const uint32_t sample_start = w->captured_samples;
    if (count <= FT8_FRAME_MAX_SAMPLES)
        w->captured_samples += count;
#endif
    const uint32_t sequence = LOAD(&w->capture_sequence);
    STORE(&w->capture_sequence, sequence + 1);
#ifdef FT8_RADIO
    const uint32_t read = LOAD(&w->read);
    struct frame_slot *slot = &w->ring[w->ring_index[write % RX_QUEUE_FRAMES]];
    if (write - read == RX_QUEUE_FRAMES) {
        PROFILE_MARK(PROF_PCM_DROP, slot->count);
        STORE(&w->read, read + 1);
    }
#else
    if (!count || count > FT8_FRAME_MAX_SAMPLES || write - LOAD(&w->read) == RING_FRAMES) {
        PROFILE_MARK(PROF_PCM_DROP, count);
        goto out;
    }
    struct frame_slot *slot = &w->ring[write % RING_FRAMES];
#endif
    slot->epoch = session;
    slot->sequence = sequence;
    slot->count = count;
    slot->end_ms = end;
#ifdef FT8_RADIO
    slot->sample_start = sample_start;
    slot->rx_phase = phase == FT8_PERIOD_MS ? 0 : phase + 1;
    if (phase == FT8_CAPTURE_END_MS)
        PROFILE_MARK(PROF_SEALED, count);
#endif
    for (uint32_t i = 0; i < count; ++i)
        slot->pcm[i] = (int16_t)frame[i + skip + 2];
    STORE(&w->write, write + 1);
#ifdef FT8_PROFILE
    ft8_profile_capture(PROF_QUEUED_FIRST, count);
#endif
out:
#ifdef FT8_RADIO
    STORE(&capturing, 0);
#endif
    return original;
}

#ifdef FT8_RADIO
__attribute__((section(".text.ft8_publish_view"), noinline))
#endif
static void publish(struct workspace *w, uint32_t status, uint32_t count)
{
    w->view.epoch = w->worker_epoch;
    w->view.status = status;
    w->view.count = count;
    const uint32_t revision = w->published_revision;
    __atomic_store_n(&w->published_revision, revision + 1, __ATOMIC_SEQ_CST);
    const unsigned char *src = (const unsigned char *)&w->view;
#ifdef FT8_RADIO
    const size_t bytes = sizeof(w->view);
#else
    const size_t bytes = offsetof(struct ft8_live_view, rows) + count * sizeof(w->view.rows[0]);
#endif
    for (size_t i = 0; i < bytes; ++i)
        __atomic_store_n(&w->published[i], src[i], __ATOMIC_RELAXED);
    STORE(&w->published_revision, revision + 2);
}

/* Worker-side notification for a confirmed transmission. No transmit control. */
static int record_tx(const char *text)
{
    struct workspace *w = LOAD(&workspace);
    size_t n = 0;
    if (!w || !text)
        return 0;
    while (n < FT8_MESSAGE_CHARS && text[n]) {
        if ((unsigned char)text[n] < 0x20u || (unsigned char)text[n] > 0x7eu)
            return 0;
        ++n;
    }
    if (!n || n == FT8_MESSAGE_CHARS)
        return 0;
    if (w->view.tx_count < FT8_TX_ROWS)
        ++w->view.tx_count;
    for (uint32_t i = w->view.tx_count - 1; i > 0; --i)
        for (size_t j = 0; j < FT8_MESSAGE_CHARS; ++j)
            w->view.tx[i][j] = w->view.tx[i - 1][j];
    for (size_t i = 0; i <= n; ++i)
        w->view.tx[0][i] = text[i];
    publish(w, w->view.status, w->view.count);
    return 1;
}

/* Worker owns the TX state. UI posts one request and a cancellation ticket. */
static int attach_tx(const struct ft8_tx_io *io)
{
    struct workspace *w = LOAD(&workspace);
    if (!w || !io || LOAD(&w->tx_ready) || (LOAD(&epoch) & 1u) ||
        !io->now_ms || !io->start || !io->submit || !io->drained || !io->stop)
        return 0;
    w->tx_io = *io;
    STORE(&w->tx_ready, 1);
    return 1;
}

static int tx_available(const struct workspace *w)
{
    if (!w || !LOAD(&w->tx_ready))
        return 0;
#ifdef FT8_RADIO
    return CORE->radio->tx_available();
#else
    return 1;
#endif
}

static int tx_arm(const char *text, uint32_t frequency_hz)
{
#ifdef FT8_RADIO
    const int automatic = (frequency_hz & FT8_TX_AUTO_FLAG) != 0;
    frequency_hz &= ~FT8_TX_AUTO_FLAG;
#endif
    struct workspace *w = LOAD(&workspace);
    const uint32_t session = LOAD(&epoch);
    const uint32_t phase = w ? LOAD(&w->tx_phase) : FT8_TX_OFFLINE;
#ifdef FT8_RADIO
    if (!ft8_radio_offset_set())
        return 0;
#endif
    if (!text || !(session & 1u) || !tx_available(w) ||
        LOAD(&w->tx_pending) || (phase != FT8_TX_IDLE && phase != FT8_TX_NO_SLOT
#ifdef FT8_RADIO
                                && phase != FT8_TX_FAULT
#endif
                               ) ||
        frequency_hz < FT8_TX_MIN_HZ || frequency_hz > FT8_TX_MAX_HZ)
        return 0;
    size_t n = 0;
    while (n < FT8_MESSAGE_CHARS && text[n])
        ++n;
    if (!n || n == FT8_MESSAGE_CHARS || !CORE->encode(text, w->tx_tones))
        return 0;
    for (size_t i = 0; i <= n; ++i)
        w->tx_text[i] = text[i];
    w->tx_epoch = session;
    w->tx_ticket = LOAD(&w->tx_cancel);
    w->tx_hz = frequency_hz;
#ifdef FT8_RADIO
    w->tx_auto = automatic;
    w->tx_is_free = !automatic && w->ui.selection == FT8_TX_FREE;
#endif
    STORE(&w->tx_pending, 1);
    return 1;
}

__attribute__((noinline)) static int tx_cancelled(const struct workspace *w)
{
#ifdef FT8_RADIO
    if (w->tx_auto && CORE->radio->auto_state() != 2)
        return 1;
#endif
    return w->tx_epoch != LOAD(&epoch) || w->tx_ticket != LOAD(&w->tx_cancel);
}

static void tx_phase(struct workspace *w, uint32_t phase)
{
    STORE(&w->tx_phase, phase);
    w->view.tx_status = phase;
#ifdef FT8_RADIO
    if (phase >= FT8_TX_ARMED && phase <= FT8_TX_STOPPING)
        __builtin_memcpy(w->view.tx_current, w->tx_text, sizeof(w->view.tx_current));
    else
        w->view.tx_current[0] = 0;
#endif
    publish(w, w->view.status, w->view.count);
}

#ifdef FT8_PROFILE
#define TX_TRACE(stage, value) PROFILE_MARK(PROF_TX_FAULT, ((stage) << 12) | ((value) & 4095u))
#else
#define TX_TRACE(stage, value) ((void)0)
#endif

PROFILE_CODE(release) static void tx_release(struct workspace *w, uint32_t next, int completed)
{
    if (w->tx_phase == FT8_TX_STOPPING) {
        next = w->tx_end_status;
        completed = w->tx_completed;
    }
    if (w->tx_phase >= FT8_TX_SENDING && w->tx_phase <= FT8_TX_STOPPING &&
        w->tx_io.stop() != 1) {
        w->tx_end_status = next;
        w->tx_completed = completed;
        tx_phase(w, FT8_TX_STOPPING);
        return;
    }
    if (completed && !tx_cancelled(w)) {
        record_tx(w->tx_text);
#ifdef FT8_RADIO
        if (!w->tx_is_free)
            CORE->radio->qso_event(w->tx_text, current_grid(), 0, w->tx_hz);
#endif
    }
    tx_phase(w, next);
}

#ifdef FT8_RADIO
static int tx_arm_expired(struct workspace *w, uint32_t now)
{
    if (elapsed_ms(now, w->tx_started_ms) < TX_ARM_TIMEOUT_MS + 15000)
        return 0;
    tx_phase(w, FT8_TX_NO_SLOT);
    return 1;
}
#endif

static void tx_check(struct workspace *w)
{
    if (w->tx_phase == FT8_TX_STOPPING) {
        tx_release(w, FT8_TX_FAULT, 0);
        return;
    }
    if (w->tx_phase != FT8_TX_IDLE && tx_cancelled(w)) {
        tx_release(w, FT8_TX_IDLE, 0);
        return;
    }
    if (LOAD(&w->tx_pending)) {
        if (!tx_cancelled(w)
#ifndef FT8_RADIO
            && w->synced && w->worker_epoch == w->tx_epoch
#endif
        ) {
            const int prepared = CORE->tx_open(w->synth, sizeof(w->synth), w->tx_tones, w->tx_hz) != NULL;
            if (!prepared)
                TX_TRACE(1, 0);
#ifdef FT8_RADIO
            w->tx_started_ms = w->tx_io.now_ms();
#endif
            tx_phase(w, prepared ? FT8_TX_ARMED : FT8_TX_FAULT);
        } else {
            tx_phase(w, FT8_TX_IDLE);
        }
        STORE(&w->tx_pending, 0);
    }
#ifdef FT8_RADIO
    if (w->tx_phase == FT8_TX_ARMED)
        tx_arm_expired(w, w->tx_io.now_ms());
#endif
}

static int tx_start(struct workspace *w, uint32_t boundary_ms)
{
    if (w->tx_phase != FT8_TX_ARMED || tx_cancelled(w))
        return 0;
    const uint32_t now = w->tx_io.now_ms();
#ifdef FT8_RADIO
    if (!ft8_radio_offset_set() || tx_arm_expired(w, now) ||
        (w->tx_auto && !CORE->radio->auto_key(boundary_ms)))
        return 0;
#endif
    w->tx_submitted = 0;
    w->tx_started_ms = now;
    const uint32_t age = elapsed_ms(now, boundary_ms);
    if (age > TX_MAX_SLOT_AGE_MS) {
        TX_TRACE(2, age);
        tx_phase(w, FT8_TX_FAULT);
        return 0;
    }
    w->tx_lease_ms = TX_LEASE_MS - age;
    if (w->tx_io.start(w->tx_lease_ms) != 1) {
        TX_TRACE(3, CORE->radio->tx_fault());
        tx_phase(w, FT8_TX_FAULT);
        return 0;
    }
    tx_phase(w, FT8_TX_SENDING);
    if (tx_cancelled(w))
        tx_release(w, FT8_TX_IDLE, 0);
    return 1;
}

static void tx_pump(struct workspace *w)
{
    if (w->tx_phase != FT8_TX_SENDING && w->tx_phase != FT8_TX_DRAINING)
        return;
    if (tx_cancelled(w)) {
        tx_release(w, FT8_TX_IDLE, 0);
        return;
    }
    const uint32_t elapsed = elapsed_ms(w->tx_io.now_ms(), w->tx_started_ms);
    const uint32_t due = elapsed / TX_BLOCK_MS + 1;
    if (elapsed >= w->tx_lease_ms || (w->tx_phase == FT8_TX_SENDING &&
                                     due > w->tx_submitted + TX_MAX_CATCHUP)) {
        TX_TRACE(4 + (elapsed < w->tx_lease_ms), due - w->tx_submitted);
        tx_release(w, FT8_TX_FAULT, 0);
        return;
    }
    while (w->tx_submitted < due && w->tx_submitted < TX_BLOCKS) {
        size_t n = 0;
        if (w->tx_submitted >= TX_LEAD_BLOCKS) {
            n = CORE->tx_next((struct ft8_tx *)w->synth, w->tx_mono, TX_BLOCK);
            if (!n || n > TX_BLOCK) {
                TX_TRACE(6, w->tx_submitted);
                tx_release(w, FT8_TX_FAULT, 0);
                return;
            }
        }
#ifdef FT8_RADIO
        for (size_t i = n; i < TX_BLOCK; ++i)
            w->tx_mono[i] = 0;
        const int16_t *pcm = w->tx_mono;
#else
        for (size_t i = 0; i < TX_BLOCK; ++i) {
            const int16_t sample = i < n ? w->tx_mono[i] : 0;
            w->tx_block[2 * i] = sample;
            w->tx_block[2 * i + 1] = sample;
        }
        const int16_t *pcm = w->tx_block;
#endif
        if (tx_cancelled(w) || w->tx_io.submit(pcm, TX_BLOCK) != 1) {
            TX_TRACE(7, w->tx_submitted);
            tx_release(w, FT8_TX_FAULT, 0);
            return;
        }
        ++w->tx_submitted;
    }
    if (w->tx_submitted == TX_BLOCKS && w->tx_phase == FT8_TX_SENDING)
        tx_phase(w, FT8_TX_DRAINING);
    if (w->tx_phase == FT8_TX_DRAINING && elapsed >= TX_BLOCKS * TX_BLOCK_MS) {
        const int drained = w->tx_io.drained();
        if (drained < 0)
            TX_TRACE(8, CORE->radio->tx_fault());
        if (drained)
            tx_release(w, drained == 1 ? FT8_TX_IDLE : FT8_TX_FAULT, drained == 1);
    }
}

/* ---- In-page interaction (UI task) ---- */

static void ui_changed(struct workspace *w)
{
    STORE(&w->ui_revision, LOAD(&w->ui_revision) + 1);
}

int ft8_live_draw(void *frame, const struct ft8_live_view *view)
{
#ifndef FT8_RADIO
    static const struct ft8_ui_state unbound_ui; /* zeroed, no workspace yet */
#endif
    if (!core_present())
        return 0;
    struct workspace *w = LOAD(&workspace);
#ifdef FT8_RADIO
    if (!w)
        return 0;
    CORE->ui_draw(frame, view, &w->ui);
#else
    CORE->ui_draw(frame, view, w ? &w->ui : &unbound_ui);
#endif
    return 1;
}

#ifdef FT8_RADIO
uint32_t ft8_live_hit(uint32_t x, uint32_t y)
{
    struct workspace *w = LOAD(&workspace);
    return w ? CORE->hit(&w->ui, x, y) : y >= FT8_SOFT_Y && x < FT8_SOFT_W ? FT8_EVENT_BACK : 0;
}
#else
static int hit_zone(uint32_t x, uint32_t y, uint32_t zx, uint32_t zy, uint32_t zw, uint32_t zh)
{
    return x - zx < zw && y - zy < zh;
}

/* Map a touch to an FT8_EVENT_* id, or 0 for a passive page area. */
uint32_t ft8_live_hit(uint32_t x, uint32_t y)
{
    struct workspace *w = LOAD(&workspace);
    if (!w)
        return 0;
#ifdef FT8_RADIO
    if (w->ui.keyboard) {
        const uint16_t *key = ft8_stock_key_table(w->ui.keyboard_layout);
        for (unsigned i = 0; i < FT8_STOCK_KEYS; ++i, key += 5)
            if ((unsigned)(key[4] - 0x1200) < 256 &&
                hit_zone(x, y, key[0], key[1], key[2], key[3]))
                return FT8_EVENT_KEY + (key[4] & 255);
        return 0;
    }
#endif
    if (hit_zone(x, y, FT8_STOP_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H))
        return FT8_EVENT_STOP;
#ifndef FT8_RADIO
    if (w->ui.keyboard) {
        if (!hit_zone(x, y, FT8_KEYBOARD_X, FT8_KEYBOARD_Y, FT8_KEYBOARD_W, FT8_KEYBOARD_H))
            return 0;
        const uint32_t col = (x - FT8_KEY_X0) / FT8_KEY_W;
        const uint32_t row = (y - FT8_KEY_Y0) / FT8_KEY_H;
        if (col >= FT8_KEY_COLS || row >= FT8_KEY_ROWS ||
            !ft8_keyboard_keys[row * FT8_KEY_COLS + col])
            return 0;
        return FT8_EVENT_KEY + row * FT8_KEY_COLS + col;
    }
#endif
    if (hit_zone(x, y, FT8_BAND_X, FT8_BAND_Y, FT8_BAND_W, FT8_BAND_STEP * FT8_LIVE_ROWS)) {
        const uint32_t row = (y - FT8_BAND_Y) / FT8_BAND_STEP;
        if (row < FT8_LIVE_ROWS)
            return FT8_EVENT_ROW + row;
    }
    if (hit_zone(x, y, FT8_MSG_X, FT8_MSG_Y, FT8_MSG_W, FT8_MSG_STEP * FT8_TX_MESSAGES))
        return FT8_EVENT_MSG + (y - FT8_MSG_Y) / FT8_MSG_STEP;
    if (hit_zone(x, y, FT8_TXNEXT_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H))
        return FT8_EVENT_TXNEXT;
    if (hit_zone(x, y, FT8_MYFIELD_X, FT8_MYFIELD_Y, FT8_MYFIELD_W, FT8_MYFIELD_H))
        return FT8_EVENT_MYFIELD;
#ifdef FT8_RADIO
    if (hit_zone(x, y, FT8_GRID_X, FT8_MYFIELD_Y, FT8_GRID_W, FT8_OFFSET_Y + FT8_OFFSET_H - FT8_MYFIELD_Y))
        return y < FT8_OFFSET_Y ? FT8_EVENT_GRID : FT8_EVENT_OFFSET;
#endif
    if (hit_zone(x, y, FT8_DXFIELD_X, FT8_DXFIELD_Y, FT8_DXFIELD_W, FT8_DXFIELD_H))
        return FT8_EVENT_DXFIELD;
    return 0;
}

#endif

#ifndef FT8_RADIO
static void select_sender(struct ft8_ui_state *ui, const struct ft8_rx_result *result, uint32_t row)
{
    if (!result->sender)
        return;
    const char *call = result->text + result->sender - 1;
    size_t length = 0, same = 0;
    while (call[length] && call[length] != ' ') {
        if (length == sizeof(ui->dx_call) - 1 || call[length] == '<')
            return;
        same += ui->my_call[length] == call[length];
        ++length;
    }
    if (!length || (same == length && !ui->my_call[length]))
        return;
    for (size_t i = 0; i < length; ++i)
        ui->dx_call[i] = call[i];
    ui->dx_call[length] = 0;
#ifndef FT8_RADIO
    ui->tx_offset_hz = result->frequency_hz;
#endif
    ui->dx_row = row + 1;
    ui->tx_report = result->snr_db + FT8_REPORT_BIAS;
    if (ui->selection == FT8_TX_CQ)
        ui->selection = 0;
}

#endif

static void open_keyboard(struct workspace *w, uint32_t target, const char *current)
{
    struct ft8_ui_state *ui = &w->ui;
    ui->keyboard = target;
    size_t n = 0;
    while (n + 1 < sizeof(ui->typing) && current[n]) {
        ui->typing[n] = current[n];
        ++n;
    }
    ui->typing[n] = 0;
    ui->typing_length = (uint32_t)n;
#ifdef FT8_RADIO
    ui->typing_cursor = n;
    ui->keyboard_layout = target >= FT8_KEYBOARD_OFFSET ? 2 : 0;
#endif
}

static void close_keyboard(struct workspace *w)
{
    struct ft8_ui_state *ui = &w->ui;
    char *field = ui->keyboard == FT8_KEYBOARD_MY ? ui->my_call :
                  ui->keyboard == FT8_KEYBOARD_DX ? ui->dx_call : ui->free_text;
#ifdef FT8_RADIO
    if (ui->keyboard >= FT8_KEYBOARD_GRID) {
        if (ui->keyboard >= FT8_KEYBOARD_TIME && ui->keyboard <= FT8_KEYBOARD_CLOCK &&
            ((w->tx_phase != FT8_TX_IDLE && w->tx_phase != FT8_TX_FAULT && w->tx_phase != FT8_TX_NO_SLOT) ||
             LOAD(&w->tx_pending) || CORE->radio->auto_state() > 1))
            return;
        if (!(ui->keyboard == FT8_KEYBOARD_GRID ? set_grid(ui->typing) : CORE->edit(ui, 0x85)))
            return;
    } else
#endif
    if (ui->typing_length < sizeof(ui->free_text)) {
        for (size_t i = 0; i <= ui->typing_length; ++i)
            field[i] = ui->typing[i];
        if (ui->keyboard == FT8_KEYBOARD_DX) {
            ui->tx_report = 0;
            ui->dx_row = 0;
        }
    }
    ui->keyboard = FT8_KEYBOARD_CLOSED;
    ui_changed(w);
}

/* Returns 1 when the BACK key only closed the keyboard. */
int ft8_live_back(void)
{
    struct workspace *w = LOAD(&workspace);
    if (!w)
        return 0;
    if (w->ui.keyboard)
        w->ui.keyboard = FT8_KEYBOARD_CLOSED;
#ifdef FT8_RADIO
    else if (w->ui.settings)
        w->ui.settings = 0;
#endif
    else
        return 0;
    ui_changed(w);
    return 1;
}

void ft8_live_touch(uint32_t pressed, uint32_t event, const struct ft8_live_view *view)
{
    struct workspace *w = LOAD(&workspace);
    if (pressed || !w)
        return;
    if (event == FT8_EVENT_STOP) {
#ifdef FT8_RADIO
        CORE->radio->auto_event(FT8_AUTO_STOP, NULL, NULL, 0);
#endif
        STORE(&w->tx_cancel, LOAD(&w->tx_cancel) + 1);
        ui_changed(w);
        return;
    }
    struct ft8_ui_state *ui = &w->ui;

#ifdef FT8_RADIO
    if (event == FT8_EVENT_TX_PICK && ui->settings && !ui->keyboard &&
        !ft8_radio_full_view(NULL)) {
        if (++ui->selection >= FT8_TX_FREE)
            ui->selection = 0;
        ui_changed(w);
        return;
    }
    if (ui->keyboard) {
        if (event == FT8_EVENT_KEY + 0x85)
            close_keyboard(w);
        else if (CORE->edit(ui, event - FT8_EVENT_KEY))
            ui_changed(w);
        return;
    }
#else
    if (event >= FT8_EVENT_KEY &&
        event < FT8_EVENT_KEY + FT8_KEY_ROWS * FT8_KEY_COLS) {
        if (!ui->keyboard)
            return;
        const char key = ft8_keyboard_keys[event - FT8_EVENT_KEY];
        if (key == FT8_KEY_ENTER) {
            close_keyboard(w);
        } else if (key == FT8_KEY_BACKSPACE) {
            if (ui->typing_length)
                ui->typing[--ui->typing_length] = 0;
            ui_changed(w);
        } else if (key && ui->typing_length + 1 < sizeof(ui->free_text)) {
            ui->typing[ui->typing_length++] = key;
            ui->typing[ui->typing_length] = 0;
            ui_changed(w);
        }
        return;
    }

    if (ui->keyboard)
        return; /* taps outside the keyboard stay inert while typing */
#endif

    if (event >= FT8_EVENT_ROW && event < FT8_EVENT_ROW + FT8_LIVE_ROWS) {
        const uint32_t row = event - FT8_EVENT_ROW;
#ifdef FT8_RADIO
        const unsigned slot = row / FT8_SLOT_ROWS;
        if (view->epoch == LOAD(&epoch) && row % FT8_SLOT_ROWS < view->slot_count[slot]) {
            CORE->select_sender(ui, &view->rows[row], row);
            CORE->radio->auto_event(FT8_AUTO_SELECT, &view->rows[row], ui, view->slot_end[slot]);
#else
        if (view->epoch == LOAD(&epoch) && row < view->count) {
            select_sender(ui, &view->rows[row], row);
#endif
            ui_changed(w);
        }
    } else if (event >= FT8_EVENT_MSG && event < FT8_EVENT_MSG + FT8_TX_MESSAGES) {
        ui->selection = event - FT8_EVENT_MSG;
        if (ui->selection == FT8_TX_FREE)
            open_keyboard(w, FT8_KEYBOARD_FREE, ui->free_text);
        ui_changed(w);
    } else if (event == FT8_EVENT_TXNEXT) {
        char message[FT8_MESSAGE_CHARS];
#ifdef FT8_RADIO
        if (CORE->radio->auto_state() > 1)
            return;
#endif
        if (tx_available(w) && CORE->std_message(ui->selection, ui, current_grid(), message))
            tx_arm(message, ui->tx_offset_hz ? ui->tx_offset_hz : FT8_TX_DEFAULT_HZ);
    } else if (event == FT8_EVENT_MYFIELD) {
        open_keyboard(w, FT8_KEYBOARD_MY, ui->my_call);
        ui_changed(w);
    } else if (event == FT8_EVENT_DXFIELD) {
        open_keyboard(w, FT8_KEYBOARD_DX, ui->dx_call);
        ui_changed(w);
#ifdef FT8_RADIO
    } else if (event == FT8_EVENT_GRID || event == FT8_EVENT_OFFSET) {
        open_keyboard(w, FT8_KEYBOARD_GRID + event - FT8_EVENT_GRID, "");
        ui_changed(w);
    } else if (event == FT8_EVENT_TIME) {
        open_keyboard(w, FT8_KEYBOARD_TIME, "");
        ui_changed(w);
    } else if (event == FT8_EVENT_CLOCK) {
        char clock[15];
        ft8_radio_clock_text(clock);
        open_keyboard(w, FT8_KEYBOARD_CLOCK, clock);
        ui_changed(w);
    } else if (event == FT8_EVENT_RETRIES || event == FT8_EVENT_CQS) {
        open_keyboard(w, FT8_KEYBOARD_RETRIES + event - FT8_EVENT_RETRIES, "");
        ui_changed(w);
    } else if (event == FT8_EVENT_TX_SLOT) {
        if ((w->tx_phase == FT8_TX_IDLE || w->tx_phase >= FT8_TX_FAULT) &&
            !LOAD(&w->tx_pending) && CORE->radio->auto_state() <= 1) {
            CORE->radio->toggle_tx_slot();
            ui_changed(w);
        }
    } else if (event == FT8_EVENT_SETUP) {
        ui->settings = 1;
        ui_changed(w);
    } else if (event == FT8_EVENT_AUTO || event == FT8_EVENT_FULL) {
        CORE->radio->auto_event(event == FT8_EVENT_AUTO ? FT8_AUTO_TOGGLE : FT8_AUTO_FULL, NULL, ui, 0);
        ui_changed(w);
    } else if (event == FT8_EVENT_SORT || event == FT8_EVENT_PAGE) {
        const unsigned list = ui->list;
        const unsigned order = list & 3;
        const unsigned next = event == FT8_EVENT_SORT ?
            (order + 1 == FT8_SORT_COUNT ? 0 : order + 1) : list + 4;
        STORE(&ui->list, next);
        ui->dx_row = 0;
#endif
    }
}

int ft8_live_snapshot(struct ft8_live_view *out, uint32_t revision[4])
{
    const uint32_t session = LOAD(&epoch);
    const uint32_t grid = current_grid();
    struct workspace *w = LOAD(&workspace);
    const uint32_t before = w ? LOAD(&w->published_revision) : 0;
    if (before & 1u)
        return 0;
    if (w) {
        unsigned char *dest = (unsigned char *)out;
        for (size_t i = 0; i < sizeof(*out); ++i)
            dest[i] = __atomic_load_n(&w->published[i], __ATOMIC_RELAXED);
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        if (before != LOAD(&w->published_revision))
            return 0;
    }
    if (!w) {
        out->tx_count = 0;
#ifdef FT8_RADIO
        out->tx_current[0] = 0;
        out->rx_total = out->rx_list = 0;
        out->slot_total[0] = out->slot_total[1] = 0;
        out->slot_count[0] = out->slot_count[1] = 0;
#endif
    }
    if (!w || out->epoch != session || out->status == FT8_LIVE_UNLOADED) {
        out->epoch = session;
        out->count = 0;
#ifdef FT8_RADIO
        out->slot_count[0] = out->slot_count[1] = 0;
#endif
        out->status = w ? FT8_LIVE_WAIT_SLOT :
                      core_present() ? FT8_LIVE_UNBOUND : FT8_LIVE_UNLOADED;
    }
    if (out->grid != grid)
#ifdef FT8_RADIO
        for (uint32_t i = 0; i < FT8_LIVE_ROWS; ++i)
#else
        for (uint32_t i = 0; i < out->count; ++i)
#endif
            out->rows[i].distance_km = FT8_DISTANCE_UNKNOWN;
    if (!tx_available(w))
        out->tx_status = FT8_TX_OFFLINE;
    out->grid = grid;
    revision[0] = session;
    revision[1] = before;
    revision[2] = grid;
    revision[3] = w ? LOAD(&w->ui_revision) : 0;
#ifdef FT8_RADIO
    out->tx_wait_s = out->tx_status == FT8_TX_ARMED ? CORE->radio->tx_seconds() : 0;
    out->tx_fault = out->tx_status == FT8_TX_FAULT || out->tx_status == FT8_TX_STOPPING ?
                    CORE->radio->tx_fault() : 0;
    out->tx_pwr = CORE->radio->tx_power();
    revision[1] ^= (out->tx_wait_s | out->tx_fault) << 24 | out->tx_pwr << 8;
    revision[0] ^= CORE->radio->auto_state() << 28;
    if (w && w->ui.settings && ft8_radio_gps_clock())
        revision[0] ^= 1u << 27;
    revision[3] += CORE->radio->full_revision();
#ifdef FT8_SD_PLUGIN
    revision[3] ^= ft8_plugin_queue() ? 0x80000000u : 0;
#endif
#endif
    return 1;
}

static uint32_t next_sequence(void)
{
    struct workspace *w = LOAD(&workspace);
    return w ? LOAD(&w->capture_sequence) : 0;
}

/* Worker context only. sequence identifies the frame containing the first
   slot sample, and skip is the offset within that frame. */
static int sync(uint32_t sequence, uint32_t skip)
{
    struct workspace *w = LOAD(&workspace);
    const uint32_t session = LOAD(&epoch);
    if (!w || !(session & 1u) || skip >= FT8_FRAME_MAX_SAMPLES)
        return 0;
    if (!w->rx)
#ifdef FT8_RADIO
        w->rx = CORE->open((void *)FT8_RADIO_RX_HIGH_BASE, FT8_ARM_WORK_BYTES);
#else
        w->rx = CORE->open(w->decoder, sizeof(w->decoder));
#endif
    if (!w->rx)
        return 0;
    if (w->tx_phase != FT8_TX_IDLE
#ifdef FT8_RADIO
        && w->tx_phase != FT8_TX_FAULT && w->tx_phase != FT8_TX_NO_SLOT && w->tx_phase != FT8_TX_ARMED
#endif
       ) {
        tx_release(w, FT8_TX_IDLE, 0);
        if (w->tx_phase == FT8_TX_STOPPING)
            return 0;
    }
#ifndef FT8_RADIO
    STORE(&w->tx_pending, 0);
#endif
    w->worker_epoch = session;
    w->skip = skip;
    w->samples = 0;
    w->expect = sequence;
    w->waiting_for_frame = 1;
    w->synced = 1;
    CORE->begin_slot(w->rx);
#ifdef FT8_RADIO
    w->skip_rx = 0;
    publish(w, FT8_LIVE_RECEIVING, w->view.count);
#else
    publish(w, FT8_LIVE_RECEIVING, 0);
#endif
    return 1;
}

#ifdef FT8_RADIO
__attribute__((section(".text.ft8_page_slots"), noinline))
static unsigned page_slots(struct workspace *w)
{
    struct ft8_live_view *v = &w->view;
    const unsigned list = LOAD(&w->ui.list);
    const unsigned max = v->slot_total[0] > v->slot_total[1] ? v->slot_total[0] : v->slot_total[1];
    const unsigned pages = (max + FT8_SLOT_ROWS - 1) / FT8_SLOT_ROWS;
    const unsigned page = pages ? (list >> 2) % pages : 0;
    v->rx_total = v->slot_total[0] + v->slot_total[1];
    v->rx_list = (page << 2) | (list & 3);
    for (unsigned slot = 0; slot < 2; ++slot) {
        v->slot_count[slot] = CORE->page(v->rows + slot * FT8_SLOT_ROWS, w->results[slot],
                                        v->slot_total[slot], &w->ui, page);
    }
    return v->slot_count[0] + v->slot_count[1];
}

__attribute__((section(".text.ft8_publish_scan"), noinline))
static void publish_scan(struct workspace *w, uint32_t end)
{
    PROFILE_START(scan);
#ifdef FT8_PROFILE
    w->scan_started = 1;
#endif
    /* Result offsets are relative to the buffer start. The radio API
       expresses that origin as the end of a nominal 15-second buffer. */
    const uint32_t nominal = end + (FT8_SLOT_SAMPLES - w->samples) / 16;
    end = nominal % (UINT32_MAX / 1000 + 1);
    w->view.grid = current_grid();
    CORE->set_locator(w->rx, w->view.grid);
    const size_t count = CORE->finish(w->rx, w->decoded, FT8_LIST_RESULTS, end);
    ++w->view.rx_scans;
    if (count) {
        unsigned totals[2] = {0};
        for (unsigned i = 0; i < count; ++i) {
            unsigned slot = 0;
            ft8_radio_delta(ft8_radio_received_edge(&w->decoded[i], end), &slot);
            w->results[slot][totals[slot]++] = w->decoded[i];
        }
        for (unsigned slot = 0; slot < 2; ++slot) {
            if (!totals[slot])
                continue;
            w->view.slot_total[slot] = totals[slot];
            w->view.slot_end[slot] = end;
            w->view.slot_batch[slot] = w->view.rx_scans;
            PROFILE_MARK(PROF_BATCH, (slot << 15) | (totals[slot] << 10) |
                         (w->view.rx_scans & 1023));
            const unsigned timing = CORE->radio->rx_timing(w->results[slot], totals[slot], end);
            w->view.slot_timing[slot] = timing;
            w->view.slot_timed = (w->view.slot_timed & ~(1u << slot)) | (!!timing << slot);
        }
        /* New results and worked-first sorting are always visible on page 1. */
        STORE(&w->ui.list, LOAD(&w->ui.list) & 3);
    }
    PROFILE_START(presentation);
    publish(w, FT8_LIVE_RESULTS, count ? page_slots(w) : w->view.count);
    PROFILE_END(presentation, PROF_PUBLISH, count);
    PROFILE_END(scan, PROF_SCAN, count);
}
#endif

/* Move ownership under the IRQ lock. The previous worker slot replaces the
   newly borrowed slot, so even a producer overrun cannot overwrite it. */
#ifdef FT8_RADIO
__attribute__((noinline, section(".text.ft8_rx_dequeue")))
static const struct frame_slot *dequeue(struct workspace *w)
{
    const unsigned irq = LOCK_RX();
    const uint32_t read = w->read;
    const struct frame_slot *slot = NULL;
    if (read != LOAD(&w->write)) {
        uint8_t *index = &w->ring_index[read % RX_QUEUE_FRAMES];
        const unsigned borrowed = *index;
        *index = w->worker_slot;
        w->worker_slot = borrowed;
        slot = &w->ring[borrowed];
        STORE(&w->read, read + 1);
    }
    UNLOCK_RX(irq);
    return slot;
}
#endif

/* Worker context only, with an independent stack and FPU context. */
static int poll(void)
{
    struct workspace *w = LOAD(&workspace);
    if (!w)
        return 0;
    tx_check(w);
#ifdef FT8_RADIO
    const unsigned list = LOAD(&w->ui.list);
    if (list != w->shown_list) {
        w->shown_list = list;
        publish(w, w->view.status, page_slots(w));
    }
    if (w->skip_rx) {
        tx_pump(w);
        w->skip_rx = w->tx_phase >= FT8_TX_SENDING && w->tx_phase <= FT8_TX_STOPPING;
        if (!w->skip_rx)
            PROFILE_MARK(PROF_RX_READY, w->tx_phase);
        return 0;
    }
    const struct frame_slot *slot = dequeue(w);
    if (!slot) {
        tx_pump(w);
        return 0;
    }
#else
    const uint32_t read = w->read;
    const uint32_t queued = LOAD(&w->write) - read;
    if (!queued) {
        tx_pump(w);
        return 0;
    }
    const struct frame_slot *slot = &w->ring[read % RING_FRAMES];
#endif
    const uint32_t session = LOAD(&epoch);
#ifdef FT8_RADIO
    if (slot->epoch == session && (session & 1u)) {
        const unsigned phase = slot->rx_phase;
        if (!w->synced || (phase == 0) != (w->rx_phase == 0) ||
            (phase && phase + 1000 < w->rx_phase)) {
            PROFILE_MARK(PROF_RX_SYNC, phase);
            sync(slot->sequence, 0);
        }
        w->rx_phase = phase;
    }
#endif
    if (w->synced && w->worker_epoch == session && slot->epoch == session) {
        const uint32_t distance = slot->sequence - w->expect;
#ifdef FT8_RADIO
        /* For RX only, insert silence for up to 250 ms of known lost PCM.
           Preserve the timing of the next symbols through a short overrun. */
        uint32_t missing = distance ? slot->sample_start - w->expected_sample : 0;
        const int lost_sync = distance && (!missing || missing > 4000);
        if (distance && !w->waiting_for_frame)
            PROFILE_MARK(PROF_PCM_GAP, (missing > 32767 ? 32767 : missing) | (lost_sync ? 32768 : 0));
#else
        const int lost_sync = distance != 0;
#endif
        if (w->waiting_for_frame && distance >= 0x80000000u) {
            /* A frame queued before the requested slot boundary. */
        } else if (lost_sync || w->skip >= slot->count) {
            w->synced = 0;
#ifdef FT8_RADIO
            if (w->tx_phase != FT8_TX_ARMED)
#endif
                tx_release(w, FT8_TX_IDLE, 0);
#ifdef FT8_RADIO
            publish(w, FT8_LIVE_GAP, w->view.count);
#else
            publish(w, FT8_LIVE_GAP, 0);
#endif
        } else {
            w->waiting_for_frame = 0;
            w->expect = slot->sequence + 1;
            uint32_t pos = w->skip;
            w->skip = 0;
#ifdef FT8_RADIO
            w->expected_sample = slot->sample_start + slot->count;
            while (missing || pos < slot->count) {
                size_t n = missing ? missing : slot->count - pos;
#else
            while (pos < slot->count) {
#endif
#ifdef FT8_RADIO
                PROFILE_START(frame_time);
                n = CORE->push_pcm(w->rx, missing ? NULL : slot->pcm + pos, n);
                PROFILE_END(frame_time, PROF_FRAME, n);
#else
                const size_t n = CORE->push_pcm(w->rx, slot->pcm + pos, slot->count - pos);
#endif
                if (n == 0) {
                    w->synced = 0;
                    tx_release(w, FT8_TX_IDLE, 0);
#ifdef FT8_RADIO
                    publish(w, FT8_LIVE_GAP, w->view.count);
#else
                    publish(w, FT8_LIVE_GAP, 0);
#endif
                    break;
                }
#ifdef FT8_RADIO
                if (missing)
                    missing -= n;
                else
#endif
                pos += n;
                w->samples += n;
#ifdef FT8_RADIO
                const uint32_t lag = (missing + slot->count - pos) / 16;
                const uint32_t end = slot->end_ms - lag +
                    (slot->end_ms < lag ? UINT32_MAX / 1000 + 1 : 0);
                if (CORE->radio->scan_due(end, w->samples,
                        pos == slot->count && slot->rx_phase == FT8_CAPTURE_END_MS + 1))
                    publish_scan(w, end);
                if (w->samples == FT8_SLOT_SAMPLES)
                    w->samples = CORE->roll(w->rx, end);
#else
                if (w->samples == FT8_SLOT_SAMPLES) {
                    uint32_t boundary_ms = slot->end_ms - (slot->count - pos) / 16;
                    if (tx_start(w, boundary_ms))
                        tx_pump(w);
                    else
                    {
                        w->view.grid = current_grid();
                        CORE->set_locator(w->rx, w->view.grid);
                        const size_t count = CORE->finish(w->rx, w->view.rows, FT8_LIVE_ROWS);
                        publish(w, FT8_LIVE_RESULTS, count);
                    }
                    CORE->begin_slot(w->rx);
                    w->samples = 0;
                }
#endif
            }
        }
    }
    tx_pump(w);
#ifndef FT8_RADIO
    STORE(&w->read, read + 1);
#endif
    return 1;
}

#ifdef FT8_RADIO
#ifdef FT8_PROFILE
__attribute__((noinline, section(".ft8_clock_text")))
void ft8_live_profile_window(unsigned phase)
{
    struct workspace *w = LOAD(&workspace);
    if (!w)
        return;
    const unsigned samples = w->synced && w->rx_phase ? w->samples : 0;
    const unsigned status = w->scan_started ? 0 : w->skip_rx ? 1 :
        samples < FT8_MIN_RX_BLOCKS * 2560 ? 2 : 3;
    if (phase < FT8_CAPTURE_END_MS)
        w->scan_started = 0;
    ft8_profile_window(phase, samples, status);
}
#endif
static int sync_time(uint32_t boundary_ms)
{
    struct workspace *w = LOAD(&workspace);
    if (boundary_ms > UINT32_MAX / 1000)
        boundary_ms += UINT32_MAX / 1000 + 1;
    if (!w)
        return 0;
    tx_check(w);
    if (!tx_start(w, boundary_ms))
        return 0;
    STORE(&w->read, LOAD(&w->write));
    w->synced = 0;
    w->skip_rx = 1;
    tx_pump(w);
    return 1;
}

static int synced(void)
{
    const struct workspace *w = LOAD(&workspace);
    return w && w->synced && w->worker_epoch == LOAD(&epoch);
}

/* Called by the menu only after the radio worker has parked and DMA is idle. */
static int unbind(void)
{
    struct workspace *w = LOAD(&workspace);
    if (!w || (LOAD(&epoch) & 1u) || LOAD(&capturing) || LOAD(&w->tx_phase) != FT8_TX_IDLE)
        return 0;
    STORE(&workspace, NULL);
    return 1;
}

__attribute__((section(".text.ft8_live_fullscreen")))
int ft8_live_fullscreen(void)
{
    const struct workspace *w = LOAD(&workspace);
    return w && (w->ui.settings || w->ui.keyboard);
}

#endif

/* Fixed location at the front of the Stage 1 payload. */
const struct ft8_live_api ft8_live_api __attribute__((section(".ft8_live_api"), used)) = {
    0x4c385446u, FT8_ARM_VERSION, sizeof(struct workspace), FT8_ARM_STACK_BYTES, bind, next_sequence, sync, poll,
    set_position, set_grid, record_tx, tx_arm, attach_tx,
#ifdef FT8_RADIO
    sync_time, unbind, synced, ft8_locator_coordinates, current_grid,
#endif
};
