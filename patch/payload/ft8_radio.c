#include "ft8_live.h"
#include "ft8_dma_tx.h"
#include "ft8_tx_link.h"
#include "ft8_adif.h"
#include "ft8_locator.h"
#include "ft8_rx.h"
#include "ft8_tx.h"
#include "ft8_profile.h"
#ifdef FT8_SD_PLUGIN
#include "ft8_plugin.h"
#endif
#ifdef FT8_CUSTOM_MODES
#include "cw_panel.h"
#endif

#include <string.h>

#define STOCK(offset, type) ((type)(0x60400000u + (offset)))
#define LIVE ((const struct ft8_live_api *)0x6052c670u)
#ifdef FT8_VFP
void ft8_fft_prepare(void);
#endif
#define REG8(addr) (*(volatile uint8_t *)(addr))
#define REG16(addr) (*(volatile uint16_t *)(addr))
#define REG32(addr) (*(volatile uint32_t *)(addr))
#define LOAD(p) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define STORE(p, v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)

_Static_assert(FT8_RADIO_RX_WATERFALL % _Alignof(struct ft8_dma_tx) == 0,
               "TX overlay must be DMA aligned");
_Static_assert(sizeof(struct ft8_dma_tx) < FT8_RADIO_RX_LOW_BYTES - FT8_RADIO_RX_HANN_BYTES,
               "TX overlay must fit within the low receiver arena");

enum {
    STOCK_SILENCE = 0x6095c500u, STOCK_DMA3_STATUS = 0xe82000e4u,
    STOCK_DMA3_ERROR = 1u << 4, STOCK_DMA3_BUSY = 1u << 2,
    RTC_POLL_US = 20000, RTC_MAX_EDGE_US = 120000,
    KEY_TIMEOUT_US = 270000, UNKEY_RETRY_US = 200000, STATUS_MAX_AGE_US = 180000,
    STATUS_BYTE_MASK = 0xff,
    CLOCK_MS_PERIOD = UINT32_MAX / 1000 + 1,
    SLOT_MS = FT8_PERIOD_MS, SCAN_PHASE_MS = FT8_CAPTURE_END_MS, DECODE_CUTOFF_MS = FT8_DECODE_END_MS,
    TX_LEAD_BLOCKS = 6,
    LEASE_IDLE = 0, LEASE_REQUEST, LEASE_KEYING, LEASE_ON, LEASE_STOPPING,
#ifdef FT8_RADIO_TX_HOOKS
    NATIVE_TX_BUILT = 1,
#else
    NATIVE_TX_BUILT = 0,
#endif
};

typedef int (*int_fn)(void);
typedef int (*delay_fn)(unsigned);
typedef uint32_t (*time_fn)(void);
typedef void (*rtc_fn)(uint8_t *);
typedef void *(*alloc_fn)(size_t);
typedef int (*free_fn)(void *, size_t);
typedef unsigned (*irq_lock_fn)(void);
typedef void (*irq_restore_fn)(unsigned);
typedef int (*start_fn)(int, unsigned);

struct task_params {
    unsigned attr, exinf;
    void (*entry)(unsigned);
    unsigned priority, stack_bytes;
    void *stack;
    const char *name;
};

typedef int (*create_fn)(unsigned, const struct task_params *);

enum { STOCK_CALL_OFFSET = 0x13e, STOCK_CALL_LEN = 10 };
static char stock_call[STOCK_CALL_LEN] __attribute__((section(".data.ft8"))) = {0};

static void station_call(char *out)
{
    const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
    memcpy(out, stock_call, sizeof(stock_call));
    STOCK(0xbfaac, irq_restore_fn)(irq);

    unsigned length = STOCK_CALL_LEN;
    while (length && (out[length - 1] == ' ' || out[length - 1] == 0))
        --length;
    unsigned flags = 0;
    for (unsigned i = 0; i < length; ++i) {
        const unsigned c = out[i];
        if (c - '0' <= 9)
            flags |= 1;
        else if ((c & ~32u) - 'A' <= 25) {
            out[i] = c & ~32u;
            flags |= 2;
        } else if (c != '/') {
            flags = 0;
            break;
        }
    }
    /* A hyphen, as in the factory name FTX-1, invalidates the whole value. */
    out[flags == 3 ? length : 0] = 0;
}

/* Only the watchdog task sends TX lease packets. The DSP worker can request and cancel a
   lease. The two DMA callbacks never call the allocator or the UART path. */
static struct {
    void *allocation;
    struct ft8_dma_tx *dma;
    const struct ft8_dma_tx_frame *borrowed;
    uint32_t active, parked, lease, stop_requested, attempted;
    uint32_t lease_start, lease_us, requested_at, retry_at, last_heartbeat;
    uint32_t status_report, token;
    uint32_t tx_frequency, frame_frequency;
    uint16_t tx_power_tenths, frame_power_tenths;
    uint32_t submitted, tx_wait_s, dma_wait;
    uint32_t audio_boundary, audio_votes, last_scan_ms;
    uint32_t decode_deadline;
    int worker_id, watchdog_id;
    unsigned worker_polling, decode_timed;
    uint32_t mode_report;
    uint8_t lease_mode;
} radio __attribute__((section(".data.ft8")
#ifdef FT8_RADIO_TX_HOOKS
    , used
#endif
)) = {0};

#pragma clang section text=".ft8_clock_text"
static struct {
    uint32_t anchor;
    unsigned second, valid, tx_slot, configured;
    int offset;
} ft8_clock __attribute__((section(".ft8_clock_data"), used)) = {0};

static int phase30(uint32_t ms)
{
    int age = (int)ms - (int)ft8_clock.anchor;
    if (age > CLOCK_MS_PERIOD / 2)
        age -= CLOCK_MS_PERIOD;
    else if (age < -(int)(CLOCK_MS_PERIOD / 2))
        age += CLOCK_MS_PERIOD;
    int phase = ((int)(ft8_clock.second % 30) * 1000 + age - LOAD(&ft8_clock.offset)) % 30000;
    return phase < 0 ? phase + 30000 : phase;
}

int ft8_radio_delta(uint32_t edge, unsigned *slot)
{
    if (!LOAD(&ft8_clock.valid))
        return 10000;
    const int phase = phase30(edge);
    const int nearest = (phase + 7500) / 15000;
    *slot = nearest & 1;
    return phase - nearest * 15000;
}

unsigned ft8_radio_tx_slot(void) { return LOAD(&ft8_clock.tx_slot); }
int ft8_radio_time_offset(void) { return LOAD(&ft8_clock.offset); }
int ft8_radio_offset_set(void) { return LOAD(&ft8_clock.configured); }

__attribute__((noinline, section(".text.ft8_manual_clock")))
static int manual_clock(void)
{
    return ft8_radio_offset_set() && LOAD(&ft8_clock.valid);
}

unsigned ft8_radio_rx_phase(uint32_t end)
{
    return manual_clock() ? phase30(end) % SLOT_MS : SLOT_MS;
}

__attribute__((noinline, section(".text.ft8_decode_cutoff")))
static int decode_cutoff(uint32_t time)
{
    return manual_clock() && phase30(time) % SLOT_MS >= DECODE_CUTOFF_MS;
}

__attribute__((noinline, section(".text.ft8_rx_timing")))
uint32_t ft8_radio_rx_timing(const struct ft8_rx_result *rows, size_t count, uint32_t end)
{
    int sum = 0;
    unsigned n = 0, slot = 0;
    for (size_t i = 0; i < count; ++i) {
        unsigned parity = 0;
        const int delta = ft8_radio_delta(ft8_radio_received_edge(&rows[i], end), &parity);
        if (delta == 10000 || (n && slot != parity))
            continue;
        slot = parity;
        sum += delta;
        ++n;
    }
    return n ? 0x20000u | slot << 16 | (uint16_t)(sum / (int)n) : 0;
}

__attribute__((noinline, section(".text.ft8_set_offset"))) int ft8_radio_set_offset(const char *p, unsigned n)
{
    int sign = 1, value = 0, scale = 0;
    if (n && (*p == '-' || *p == '+')) {
        sign = *p++ == '-' ? -1 : 1;
        --n;
    }
    if (!n || n > 5 || (n == 1 && *p == '.'))
        return 0;
    while (n--) {
        if (*p == '.' && !scale) {
            scale = 1;
        } else {
            if ((unsigned)(*p - '0') > 9 || scale == 1000)
                return 0;
            value = value * 10 + *p - '0';
            scale *= 10;
        }
        ++p;
    }
    value *= 1000 / (scale ? scale : 1);
    if (value > 7500)
        return 0;
    STORE(&ft8_clock.offset, sign * value);
    STORE(&ft8_clock.configured, 1);
    return 1;
}

static void toggle_tx_slot(void)
{
    STORE(&ft8_clock.tx_slot, !LOAD(&ft8_clock.tx_slot));
}
#pragma clang section text=""

static uint32_t now_us(void)
{
    return STOCK(0x1669c, time_fn)();
}

static uint32_t now_ms(void)
{
    return now_us() / 1000;
}

static const char qso_path[] = "I:\\FTX-1\\FT8LOG.ADI";
static struct ft8_worked *worked __attribute__((section(".data.ft8"))) = NULL;
static void *worked_file __attribute__((section(".data.ft8"))) = NULL;
static uint32_t worked_pending __attribute__((section(".data.ft8"))) = 0;
static int full_checking(void);
static void full_log_match(const char *call);
static void full_log_done(int available);

int ft8_radio_worked(const char *call, size_t length)
{
    return ft8_adif_worked_before(worked, call, length);
}

__attribute__((noinline, section(".ft8_recent_text")))
void ft8_radio_recent_qsos(struct ft8_recent_qso out[FT8_RECENT_QSOS])
{
    const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
    if (worked)
        memcpy(out, worked->recent, sizeof(worked->recent));
    else
        memset(out, 0, sizeof(worked->recent));
    STOCK(0xbfaac, irq_restore_fn)(irq);
}

static int close_worked_file(void)
{
    if (worked_file) {
        const int result = STOCK(0x69e90, int (*)(void *))(worked_file);
        worked_file = NULL;
        return result;
    }
    return 0;
}

static void load_worked_step(void)
{
    if (worked_pending) {
        worked_pending = 0;
        worked_file = STOCK(0x6995c, void *(*)(const char *, const char *))(qso_path, "rb");
        if (!worked_file && full_checking()) {
            /* A first-use card has no ADIF yet. Probe with the normal append path. */
            worked_file = STOCK(0x6995c, void *(*)(const char *, const char *))(qso_path, "ab");
            if (worked_file) {
                close_worked_file();
                worked_file = STOCK(0x6995c, void *(*)(const char *, const char *))(qso_path, "rb");
            }
            if (!worked_file)
                full_log_done(0);
        }
    }
    if (worked_file) {
        /* Stock fread clips reads to the FILE length and returns zero on
           several I/O errors as well. Check the cursor before trusting EOF. */
        const int checking = full_checking();
        const uintptr_t handle = (uintptr_t)worked_file;
        const uint32_t before = checking ? REG32(handle + 0x28) : 0;
        char chunk[512];
        const size_t n = STOCK(0x6a8f8, size_t (*)(void *, size_t, size_t, void *))
            (chunk, 1, sizeof(chunk), worked_file);
        const uint32_t after = checking ? REG32(handle + 0x28) : 0;
        const int valid = n <= sizeof(chunk) && (!checking || after - before == n);
        if (valid)
            ft8_adif_worked_scan(worked, chunk, n, checking ? full_log_match : NULL);
        if (!valid || n != sizeof(chunk)) {
            const int eof = checking && after == REG32(handle + 0x2c);
            const int result = close_worked_file();
            if (checking)
                full_log_done(valid && eof && result == 0);
        }
    }
}

#ifdef FT8_RADIO_TX_HOOKS
enum { STOCK_GPS_ACTIVITY = 0x607c01a8u, GPS_MAX_AGE_US = 3000000 };
/* The stock RMC status hook clears this word when the receiver reports V. */
volatile uint32_t ft8_radio_gps_grid __attribute__((section(".data.ft8"))) = 0;
static uint32_t gps_last_fix __attribute__((section(".data.ft8"))) = 0;

static int32_t gps_coordinate(const uint8_t *field, unsigned limit, unsigned north_or_east)
{
    uint32_t wire;
    __builtin_memcpy(&wire, field, sizeof(wire));
    const union { uint32_t bits; float value; } coordinate = { __builtin_bswap32(wire) };
    const float nmea = coordinate.value;
    const unsigned positive = field[4] == north_or_east;
    if (!(nmea >= 0 && nmea <= 100 * limit) ||
        (!positive && field[4] != (limit == 90 ? 'S' : 'W')))
        return INT32_MIN;
    const unsigned degrees = (unsigned)nmea / 100;
    const float minutes = nmea - 100 * degrees;
    if (minutes >= 60)
        return INT32_MIN;
    const int32_t e6 = degrees * 1000000 + (uint32_t)(minutes * (1000000.0f / 60) + 0.5f);
    return positive ? e6 : -e6;
}

/* Observe the stock DISPLAY GPS task's completed E3 payload. Bit 4 is an
   accepted RMC sentence. The stock parser checks its checksum and status A.
   Latitude and longitude are big-endian NMEA ddmm.m / dddmm.m floats. */
int ft8_radio_gps_packet(uint8_t *payload)
{
    const int built = STOCK(0x11630, int (*)(uint8_t *))(payload);
    if (built && (payload[0] & 0x10)) {
        const int32_t lat = gps_coordinate(payload + 12, 90, 'N');
        const int32_t lon = gps_coordinate(payload + 17, 180, 'E');
        const uint32_t grid = LIVE->coordinates(lat, lon);
        const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
        gps_last_fix = now_us();
        ft8_radio_gps_grid = grid;
        STOCK(0xbfaac, irq_restore_fn)(irq);
    }
    return built;
}
#endif

static uint32_t station_grid(void)
{
#ifdef FT8_RADIO_TX_HOOKS
    const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
    if (ft8_radio_gps_grid && (!REG8(STOCK_GPS_ACTIVITY) ||
                              now_us() - gps_last_fix >= GPS_MAX_AGE_US))
        ft8_radio_gps_grid = 0;
    const uint32_t grid = ft8_radio_gps_grid;
    STOCK(0xbfaac, irq_restore_fn)(irq);
    return grid;
#else
    return 0;
#endif
}

int ft8_radio_gps_clock(void)
{
    /* Same AUTO selector used by the stock RMC builder before it writes RTC. */
    return REG8(0x607c01c0u) && station_grid();
}

__attribute__((noinline, section(".ft8_clock_text")))
void ft8_radio_clock_text(char out[15])
{
    uint8_t bcd[7];
    STOCK(0x135d4, void (*)(uint8_t *))(bcd);
    out[0] = 0;
    if (!ft8_valid_utc(bcd))
        return;
    out[0] = '2';
    out[1] = '0';
    for (unsigned i = 0; i < 6; ++i) {
        const unsigned value = bcd[i + (i >= 3)];
        out[2 + 2 * i] = '0' + (value >> 4);
        out[3 + 2 * i] = '0' + (value & 15);
    }
    out[14] = 0;
}

int ft8_radio_set_clock(const char *text, unsigned length)
{
    if (length != 14 || text[0] != '2' || text[1] != '0' || ft8_radio_gps_clock())
        return 0;
    uint8_t fields[7] = {0};
    for (unsigned i = 0; i < 6; ++i) {
        const unsigned hi = text[2 + 2 * i] - '0', lo = text[3 + 2 * i] - '0';
        if (hi > 9 || lo > 9)
            return 0;
        fields[i + (i >= 3)] = (hi << 4) | lo;
    }
    if (!ft8_valid_utc(fields))
        return 0;
    /* Use the stock full date/time setter with its binary local-time layout. */
    for (unsigned i = 0; i < 6; ++i) {
        const unsigned value = fields[i + (i >= 3)];
        fields[i] = 10 * (value >> 4) + (value & 15);
    }
    memmove(fields + 1, fields, 6);
    STOCK(0x43b20, void (*)(const uint8_t *))(fields);
    STORE(&ft8_clock.valid, 0);
    return 1;
}

static void delay(void)
{
    STOCK(0x797c8, delay_fn)(1);
}

/* Only the real worker may block on the RTOS. The DMA IRQ continues to
   queue PCM, and the watchdog and display can run between decode batches. */
int ft8_radio_decode_expired(void)
{
    return radio.worker_polling && radio.decode_timed &&
           (int32_t)(now_us() - radio.decode_deadline) >= 0;
}


int ft8_radio_decode_pause(unsigned sleep)
{
    if (radio.worker_polling) {
        if (!LOAD(&radio.active) || ft8_radio_decode_expired())
            return 1;
        STORE(&radio.last_heartbeat, now_us());
        if (!sleep)
            return 0;
        PROFILE_START(wait);
        delay();
        PROFILE_END(wait, PROF_YIELD, 0);
        return !LOAD(&radio.active) || ft8_radio_decode_expired();
    }
    return 0;
}

static int stock_audio_busy(void)
{
    return REG8(0x607c0091u) || REG8(0x607c0092u) ||
           REG8(0x607c07c2u) || REG8(0x607c07c3u) || REG8(0x607c07c4u);
}

void ft8_radio_report_packet(uint8_t *packet, size_t length)
{
#ifdef FT8_RADIO_TX_HOOKS
    if (!length || !ft8_link_status_frame(packet[0], length))
        return;
    /* The 0x60 setup frame has MY CALL after the common status header. */
    if (packet[0] == 0x60) {
        const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
        memcpy(stock_call, packet + STOCK_CALL_OFFSET, sizeof(stock_call));
        STOCK(0xbfaac, irq_restore_fn)(irq);
    }
    const unsigned status = packet[FT8_LINK_STATUS_OFFSET];
    if (!(status & FT8_LINK_STATUS_MASK))
        return;
    /* MAIN's second big-endian frequency in the common status is TX dial Hz. */
    uint32_t frequency;
    __builtin_memcpy(&frequency, packet + 14, sizeof(frequency));
    STORE(&radio.tx_frequency, __builtin_bswap32(frequency));
    const unsigned power = packet[FT8_LINK_POWER_OFFSET];
    const unsigned flags = packet[FT8_LINK_MODE_FLAGS_OFFSET];
    STORE(&radio.tx_power_tenths, (flags & FT8_LINK_SPA) ? power * 10 : power);
    if (flags & FT8_LINK_MODE_TAG)
        STORE(&radio.mode_report, flags & ~FT8_LINK_SPA);
    ft8_link_restore_status(packet, length);
    /* Publish the status and receive time together, to 256 us precision. */
    STORE(&radio.status_report, (now_us() & ~STATUS_BYTE_MASK) | status);
#else
    (void)packet;
    (void)length;
#endif
}

unsigned ft8_radio_mode(void)
{
#ifdef FT8_RADIO_TX_HOOKS
    return LOAD(&radio.mode_report);
#else
    return 0;
#endif
}

static uint32_t report_time(uint32_t report)
{
    return report & ~STATUS_BYTE_MASK;
}

static int status_fresh(uint32_t report, uint32_t now)
{
    return report && now - report_time(report) < STATUS_MAX_AGE_US;
}

static int native_tx_route_available(void)
{
#ifdef FT8_RADIO_TX_HOOKS
    return LOAD(&radio.status_report) != 0;
#else
    return 0;
#endif
}

static void send_lease(unsigned start)
{
    const uint8_t packet[FT8_LINK_BYTES] = {
        FT8_LINK_COMMAND, FT8_LINK_SUBCOMMAND, 'F', 'T', '8',
        start, radio.token, start ? radio.lease_mode : 0, 0,
    };
    STOCK(0x14a1c, void (*)(const uint8_t *, unsigned))(packet, sizeof(packet));
}

static void request_stop(unsigned reason)
{
    struct ft8_dma_tx *dma = LOAD(&radio.dma);
    uint32_t expected = 0;
    __atomic_compare_exchange_n(&radio.stop_requested, &expected, reason + 1, 0,
                                __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    if (dma && LOAD(&radio.lease) != LEASE_IDLE)
        ft8_dma_tx_inhibit(dma);
}

PROFILE_CODE(start) static int radio_start(uint32_t lease_ms)
{
    const uint32_t report = LOAD(&radio.status_report);
    const uint32_t now = now_us();
    struct ft8_dma_tx *dma = LOAD(&radio.dma);
    if (LOAD(&radio.lease) != LEASE_IDLE || LOAD(&radio.borrowed))
        return 0;
    STORE(&radio.stop_requested, 0);
    if (!dma || !LOAD(&radio.active))
        return 0;
    if (!status_fresh(report, now) || (report & 3) != FT8_LINK_IDLE) {
        request_stop(FT8_RADIO_LINK_LOST);
        return 0;
    }
    if (stock_audio_busy()) {
        request_stop(FT8_RADIO_AUDIO_BUSY);
        return 0;
    }
    /* The worker lends the waterfall after leaving the decoder. The RX
       magnitudes previously occupied these bytes, including the metadata. */
    dma->state = 0;
    if (!ft8_dma_tx_begin(dma))
        return 0;
    radio.submitted = 0;
    radio.token = ((report >> 2) + 1) & FT8_LINK_TOKEN_MASK;
    radio.lease_mode = LOAD(&radio.mode_report);
    radio.lease_start = now;
    radio.lease_us = lease_ms * 1000;
    STORE(&radio.dma_wait, FT8_RADIO_SPI_MISSING);
    STORE(&radio.lease, LEASE_REQUEST);
    return 1;
}

static int radio_submit(const int16_t *pcm, size_t samples)
{
    struct ft8_dma_tx *dma = LOAD(&radio.dma);
    if (!dma || LOAD(&radio.stop_requested))
        return 0;
    /* The stock source emits silence while the MAIN processes key-on. */
    if (radio.submitted++ < TX_LEAD_BLOCKS)
        return 1;
    if (LOAD(&radio.lease) != LEASE_ON) {
        request_stop(FT8_RADIO_KEY_TIMEOUT);
        return 0;
    }
    if (ft8_dma_tx_submit(dma, pcm, samples, STOCK(0x2fa8, void (*)(const void *, size_t))))
        return 1;
    request_stop(LOAD(&radio.dma_wait));
    return 0;
}

static int radio_drained(void)
{
    struct ft8_dma_tx *dma = LOAD(&radio.dma);
    if (!dma || LOAD(&radio.lease) != LEASE_ON || LOAD(&radio.stop_requested))
        return -1;
    return ft8_dma_tx_drained(dma);
}

static int radio_stop(void)
{
    request_stop(FT8_RADIO_NO_FAULT);
    return LOAD(&radio.lease) == LEASE_IDLE && !LOAD(&radio.borrowed);
}

static const struct ft8_tx_io io
#ifdef FT8_RADIO_TX_HOOKS
    __attribute__((used))
#endif
    = {now_ms, radio_start, radio_submit, radio_drained, radio_stop};

__attribute__((noinline)) PROFILE_CODE(watchdog) static void watchdog_step(void)
{
    const uint32_t lease = LOAD(&radio.lease);
    if (lease == LEASE_IDLE)
        return;
    const uint32_t report = LOAD(&radio.status_report);
    const uint32_t worker_at = LOAD(&radio.last_heartbeat);
    const uint32_t now = now_us();
    const unsigned state = report & 3;
    const unsigned token = (report >> 2) & FT8_LINK_TOKEN_MASK;
    const int fresh = status_fresh(report, now);
    if (lease == LEASE_STOPPING) {
        const int confirmed = fresh && state == FT8_LINK_IDLE &&
            now - radio.retry_at >= 50000 &&
            report_time(report) - report_time(radio.retry_at) < STATUS_MAX_AGE_US;
        if (confirmed || now - radio.lease_start >= 14000000) {
#ifdef FT8_PROFILE
            ft8_profile_event(confirmed ? PROF_MAIN_RX : PROF_RX_TIMEOUT, report & 255,
                              confirmed ? report_time(report) : now);
#endif
            STORE(&radio.lease, LEASE_IDLE);
        } else if (now - radio.retry_at >= UNKEY_RETRY_US) {
            radio.retry_at = now;
            send_lease(FT8_LINK_STOP);
        }
        return;
    }
    if (!LOAD(&radio.active))
        request_stop(FT8_RADIO_NO_FAULT);
    else if (!fresh)
        request_stop(FT8_RADIO_LINK_LOST);
    else if (stock_audio_busy())
        request_stop(FT8_RADIO_AUDIO_BUSY);
    else if (now - radio.lease_start >= radio.lease_us)
        request_stop(FT8_RADIO_LEASE_EXPIRED);
    else if (now - worker_at >= 150000)
        request_stop(FT8_RADIO_WORKER_TIMEOUT);
    if (LOAD(&radio.stop_requested)) {
        if (lease == LEASE_REQUEST) {
            STORE(&radio.lease, LEASE_IDLE);
        } else {
            radio.retry_at = now;
            STORE(&radio.lease, LEASE_STOPPING);
#ifdef FT8_PROFILE
            ft8_profile_stop(LOAD(&radio.stop_requested) - 1, now);
#endif
            send_lease(FT8_LINK_STOP);
        }
        return;
    }
    if (lease == LEASE_REQUEST) {
        if (state != FT8_LINK_IDLE) {
            request_stop(FT8_RADIO_KEY_LOST);
            STORE(&radio.lease, LEASE_IDLE);
            return;
        }
        radio.requested_at = now;
        STORE(&radio.lease, LEASE_KEYING);
        PROFILE_MARK(PROF_TX_REQUEST, (radio.token << 8) | (report & 255));
        send_lease(FT8_LINK_START);
    } else if (lease == LEASE_KEYING) {
        if (token == radio.token && state == FT8_LINK_KEYED &&
            report_time(report) - report_time(radio.requested_at) < KEY_TIMEOUT_US) {
            radio.frame_frequency = LOAD(&radio.tx_frequency);
            radio.frame_power_tenths = LOAD(&radio.tx_power_tenths);
            STORE(&radio.lease, LEASE_ON);
            PROFILE_MARK(PROF_TX_KEYED, report & 255);
        } else if (now - radio.requested_at >= KEY_TIMEOUT_US) {
            request_stop(FT8_RADIO_KEY_TIMEOUT);
        }
    } else if (token != radio.token || state != FT8_LINK_KEYED) {
        request_stop(FT8_RADIO_KEY_LOST);
    }
}

__attribute__((target("arm"))) void ft8_radio_watchdog(unsigned unused)
{
    (void)unused;
    for (;;) {
        watchdog_step();
        delay();
    }
}

static int read_second(void)
{
    uint8_t bcd[7] = {[6] = 0xff};
    STOCK(0x135d4, rtc_fn)(bcd);
    const unsigned sec = bcd[6];
    if ((sec & 15) > 9 || sec > 0x59)
        return -1;
    return (int)((sec >> 4) * 10 + (sec & 15));
}

static unsigned tx_seconds(void)
{
    return LOAD(&radio.tx_wait_s);
}

static unsigned tx_power(void)
{
    return status_fresh(LOAD(&radio.status_report), now_us()) ?
        LOAD(&radio.tx_power_tenths) : 0;
}

static unsigned tx_fault(void)
{
    const unsigned report = LOAD(&radio.status_report);
    if ((report & FT8_LINK_DIAG_PTT) &&
        ((report >> 2) & FT8_LINK_TOKEN_MASK) == radio.token)
        return FT8_RADIO_MAIN_PTT + ((report >> 7) & 1);
    const unsigned stop = LOAD(&radio.stop_requested);
    return stop ? stop - 1 : FT8_RADIO_NO_FAULT;
}

static struct ft8_qso pending_qso __attribute__((section(".data.ft8"))) = {0};
static uint32_t pending_since __attribute__((section(".data.ft8"))) = 0;
static char last_logged[14] __attribute__((section(".data.ft8"))) = {0};
static void auto_sent(void);

static const char *qso_call(const char *text, char *call)
{
    unsigned n = 0;
    while (text[n] && text[n] != ' ') {
        if (n == 13 || text[n] == '<')
            return NULL;
        call[n] = text[n];
        ++n;
    }
    call[n] = 0;
    return n && text[n] == ' ' ? text + n + 1 : NULL;
}

/* Worker context. The actual completed TX message supplies both calls.
   A received closing message must reverse the calls from a completed RRR. */
static void qso_event(const char *text, uint32_t grid, unsigned received, unsigned offset_hz)
{
    if (!received)
        auto_sent();
    if (received) {
        if (!pending_qso.call[0])
            return;
        if (now_us() - pending_since > 90000000u) {
            pending_qso.call[0] = 0;
            return;
        }
    }
    struct ft8_qso qso = {0};
    const char *second = qso_call(text, received ? qso.my_call : qso.call);
    if (!second)
        return;
    const char *ending = qso_call(second, received ? qso.call : qso.my_call);
    if (!ending || !strcmp(qso.call, "CQ"))
        return;
    if (received) {
        if ((strcmp(ending, "73") && strcmp(ending, "RR73")) ||
            strcmp(qso.call, pending_qso.call) || strcmp(qso.my_call, pending_qso.my_call))
            return;
        qso = pending_qso;
    } else {
        if (strcmp(ending, "73") && strcmp(ending, "RRR") && strcmp(ending, "RR73"))
            return;
        const uint32_t dial_hz = radio.frame_frequency;
        if (!dial_hz)
            return;
        const uint32_t frequency = dial_hz + offset_hz;
        typedef void (*format_fn)(char *, size_t, const char *, ...);
        STOCK(0xbd4d1, format_fn)(qso.freq, sizeof(qso.freq), "%u.%06u",
                                  frequency / 1000000u, frequency % 1000000u);
        const unsigned power = radio.frame_power_tenths;
        if (power)
            STOCK(0xbd4d1, format_fn)(qso.power, sizeof(qso.power), "%u.%u",
                                      power / 10, power % 10);
        char locator[7];
        ft8_locator_format(grid, locator);
        memcpy(qso.my_grid, locator, 4);
        if (!strcmp(ending, "RRR")) {
            pending_qso = qso;
            pending_since = now_us();
            return;
        }
    }
    if (!strcmp(qso.call, last_logged))
        return;

    char record[FT8_ADIF_RECORD_MAX];
    uint8_t utc[7];
    STOCK(0x135d4, rtc_fn)(utc);
    /* Stock TIME ZONE is a half-hour index, with UTC at entry 24. */
    const unsigned zone = REG8(0x607c01c4u);
    if (zone <= 52 && zone != 24 && !ft8_local_to_utc(utc, ((int)zone - 24) * 30))
        return;
    const size_t length = ft8_adif_record(record, sizeof(record), &qso, utc);
    if (!length)
        return;
    void *file = STOCK(0x6995c, void *(*)(const char *, const char *))(qso_path, "ab");
    if (!file)
        return;
    const size_t written =
        STOCK(0x6b51c, size_t (*)(const void *, size_t, size_t, void *))(record, 1, length, file);
    const int result = STOCK(0x69e90, int (*)(void *))(file);
    if (written == length && !result) {
        memcpy(last_logged, qso.call, sizeof(last_logged));
        ft8_adif_worked_add(worked, qso.call);
        const size_t call_length = strlen(qso.call);
        const char *fields = record + call_length + sizeof("<CALL:1><") - 1 + (call_length >= 10);
        ft8_adif_recent_add(worked, qso.call, fields, record + length - fields);
        pending_qso.call[0] = 0;
    }
}


static uint32_t clock_age(uint32_t now, uint32_t then)
{
    return now - then + (now < then ? CLOCK_MS_PERIOD : 0);
}

enum { AUTO_OFF, AUTO_READY, AUTO_TX, AUTO_RX, AUTO_POSTED, AUTO_CANCEL_OFF, AUTO_CANCEL_READY };
enum { RX_GRID, RX_REPORT, RX_RREPORT, RX_RRR, RX_RR73, RX_73, RX_OTHER };

struct ft8_auto_options ft8_auto_options = {1, 5, FT8_FULL_CQS};
enum { FULL_RECENT_CALLS = FT8_FULL_CQS * FT8_LIST_RESULTS };

static struct {
    struct ft8_ui_state station;
    uint32_t state, step, key_edge, activity;
    unsigned retries;
} automatic __attribute__((section(".data.ft8"))) = {0};

struct full_auto {
    struct ft8_full_peer queue[FT8_LIST_RESULTS];
    char completed[FULL_RECENT_CALLS][14];
    unsigned enabled, count, done, cq_left, checking;
    unsigned revision;
    struct ft8_full_view view;
};

static struct full_auto *full __attribute__((section(".data.ft8"))) = NULL;

static int full_enabled(void)
{
    return full && LOAD(&full->enabled);
}

static int full_checking(void)
{
    return full_enabled() && full->checking;
}

static void full_publish(void)
{
    const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
    full->view.count = full->checking ? 0 : full->count;
    full->view.done = full->done;
    full->view.cq_left = full->cq_left;
    full->view.checking = full->checking;
    memcpy(full->view.current, automatic.station.dx_call, sizeof(full->view.current));
    memcpy(full->view.next, full->queue, sizeof(full->view.next));
    STORE(&full->revision, full->revision + 1);
    STOCK(0xbfaac, irq_restore_fn)(irq);
}

static unsigned full_revision(void)
{
    return (full ? LOAD(&full->revision) : 0) +
           (worked ? LOAD(&worked->recent_revision) : 0);
}

__attribute__((noinline)) int ft8_radio_full_view(struct ft8_full_view *out)
{
    if (!full_enabled())
        return 0;
    if (out) {
        const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
        memcpy(out, &full->view, sizeof(*out));
        STOCK(0xbfaac, irq_restore_fn)(irq);
    }
    return 1;
}

static unsigned auto_state(void)
{
    const unsigned state = LOAD(&automatic.state);
    if (state >= AUTO_CANCEL_OFF)
        return state - AUTO_CANCEL_OFF;
    return state == AUTO_POSTED ? AUTO_TX : state;
}

__attribute__((noinline)) static int auto_transition(unsigned old, unsigned next)
{
    return __atomic_compare_exchange_n(&automatic.state, &old, next, 0,
                                        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}

__attribute__((noinline)) int ft8_radio_same_call(const char *text, unsigned offset, const char *call)
{
    if (!offset || !*call)
        return 0;
    const char *p = text + offset - 1;
    while (*call && *p == *call) {
        ++p;
        ++call;
    }
    return !*call && (*p == ' ' || !*p);
}

static int auto_recipient(const struct ft8_rx_result *row)
{
    return ft8_radio_same_call(row->text, row->recipient, automatic.station.my_call);
}

static __attribute__((noinline)) int auto_peer_matches(const struct ft8_rx_result *row)
{
    return ft8_radio_same_call(row->text, row->sender, automatic.station.dx_call) &&
           auto_recipient(row);
}

static unsigned auto_message(const struct ft8_rx_result *row)
{
    const char *p = row->text + row->sender - 1;
    while (*p && *p != ' ')
        ++p;
    if (!*p++)
        return RX_OTHER;
    if (!strcmp(p, "RRR"))
        return RX_RRR;
    if (!strcmp(p, "RR73"))
        return RX_RR73;
    if (!strcmp(p, "73"))
        return RX_73;
    const unsigned reply = *p == 'R';
    const char *report = p + reply;
    if ((*report == '+' || *report == '-') &&
        (unsigned)(report[1] - '0') <= 9 && (unsigned)(report[2] - '0') <= 9 && !report[3])
        return reply ? RX_RREPORT : RX_REPORT;
    return ft8_locator_parse(p) ? RX_GRID : RX_OTHER;
}

unsigned ft8_radio_received_edge(const struct ft8_rx_result *row, uint32_t end)
{
    const unsigned back = SLOT_MS + 500 - row->offset_ms;
    return end - back + (end < back ? CLOCK_MS_PERIOD : 0);
}

static void full_remove(unsigned index)
{
    --full->count;
    memmove(&full->queue[index], &full->queue[index + 1],
            (full->count - index) * sizeof(full->queue[0]));
}

static void full_log_match(const char *call)
{
    for (unsigned i = 0; i < full->count; ++i)
        if (!strcmp(full->queue[i].call, call)) {
            full_remove(i);
            return;
        }
}

static void full_stop(unsigned state)
{
    if (auto_transition(state, AUTO_CANCEL_OFF + LOAD(&ft8_auto_options.enabled)))
        STORE(&full->enabled, 0);
}

static void full_post(void)
{
    automatic.activity = now_ms();
    full_publish();
    auto_transition(AUTO_RX, AUTO_POSTED);
}

static void full_next(void)
{
    automatic.station.dx_call[0] = 0;
    automatic.step = FT8_TX_CQ;
    automatic.retries = 0;
    if (full->count) {
        const struct ft8_full_peer *peer = &full->queue[0];
        memcpy(automatic.station.dx_call, peer->call, sizeof(peer->call));
        automatic.station.tx_report = peer->db + FT8_REPORT_BIAS;
        automatic.step = peer->step;
        full_remove(0);
    } else if (!full->cq_left) {
        full_stop(AUTO_RX);
        return;
    }
    full_post();
}

static void full_log_done(int available)
{
    full->checking = 0;
    if (available && LOAD(&automatic.state) == AUTO_RX)
        full_next();
    else
        full_stop(AUTO_RX);
}

static void full_queue(const struct ft8_rx_result *row)
{
    struct ft8_full_peer peer = {0};
    if (!row->sender || !auto_recipient(row) ||
        !qso_call(row->text + row->sender - 1, peer.call))
        return;
    const unsigned kind = auto_message(row);
    if (kind > RX_REPORT)
        return;
    for (unsigned i = 0; i < FULL_RECENT_CALLS && i < full->done; ++i)
        if (!strcmp(full->completed[i], peer.call))
            return;
    peer.hz = row->frequency_hz;
    peer.km = row->distance_km;
    peer.db = row->snr_db;
    peer.step = kind + 1;
    for (unsigned i = 0; i < full->count; ++i)
        if (!strcmp(full->queue[i].call, peer.call)) {
            const struct ft8_full_peer old = full->queue[i];
            if (peer.db <= old.db) {
                if (peer.km == FT8_DISTANCE_UNKNOWN || old.km != FT8_DISTANCE_UNKNOWN)
                    return;
                const uint16_t km = peer.km;
                peer = old;
                peer.km = km;
            } else if (peer.km == FT8_DISTANCE_UNKNOWN) {
                peer.km = old.km;
            }
            full_remove(i);
            break;
        }
    if (full->count == FT8_LIST_RESULTS)
        return;
    unsigned index = full->count;
    while (index && (peer.km < full->queue[index - 1].km ||
                     (peer.km == full->queue[index - 1].km && peer.db > full->queue[index - 1].db)))
        --index;
    memmove(&full->queue[index + 1], &full->queue[index],
            (full->count - index) * sizeof(peer));
    full->queue[index] = peer;
    ++full->count;
}

static void full_rx(const struct ft8_rx_result *rows, size_t count, uint32_t end)
{
    const unsigned age = clock_age(end, automatic.key_edge);
    if (full->checking || age < 25500 || age > 33500)
        return;
    for (size_t i = 0; i < count; ++i) {
        const struct ft8_rx_result *row = &rows[i];
        const unsigned phase = clock_age(ft8_radio_received_edge(row, end), automatic.key_edge);
        if (phase < 12000 || phase > 18000)
            continue;
        if (automatic.step == FT8_TX_CQ) {
            full_queue(row);
        } else if (auto_peer_matches(row)) {
            const unsigned kind = auto_message(row);
            if ((automatic.step == 1 && kind == RX_RREPORT) ||
                (automatic.step == 2 && (kind == RX_RRR || kind == RX_RR73))) {
                automatic.step += 2;
                automatic.retries = 0;
                full_post();
                return;
            }
        }
    }
    if (automatic.step == FT8_TX_CQ && full->count) {
        close_worked_file();
        worked->fill = 0;
        worked_pending = full->checking = 1;
        full_publish();
    }
}

static int auto_event(unsigned event, const struct ft8_rx_result *row,
                      const struct ft8_ui_state *ui, uint32_t end)
{
    const unsigned state = LOAD(&automatic.state);
    if (event == FT8_AUTO_STOP) {
        if (state >= AUTO_TX && state <= AUTO_POSTED)
            STORE(&automatic.state, AUTO_CANCEL_OFF + LOAD(&ft8_auto_options.enabled));
        return 0;
    }
    if (event == FT8_AUTO_FULL) {
        if (full_enabled()) {
            STORE(&automatic.state, AUTO_CANCEL_OFF + LOAD(&ft8_auto_options.enabled));
            return 0;
        }
        if (!ft8_radio_offset_set() || !full || state > AUTO_READY || !ui->my_call[0] || !LIVE->grid() ||
            !native_tx_route_available())
            return 0;
        full->count = full->done = full->checking = 0;
        automatic.retries = 0;
        full->cq_left = LOAD(&ft8_auto_options.cq_rounds);
        automatic.station = *ui;
        automatic.station.dx_call[0] = 0;
        automatic.step = FT8_TX_CQ;
        automatic.activity = now_ms();
        full_publish();
        STORE(&full->enabled, 1);
        return auto_transition(state, AUTO_POSTED);
    }
    if (event == FT8_AUTO_TOGGLE) {
        if (full_enabled())
            return 0;
        const unsigned enabling = !LOAD(&ft8_auto_options.enabled);
        STORE(&ft8_auto_options.enabled, enabling);
        STORE(&automatic.state, (state >= AUTO_TX ? AUTO_CANCEL_OFF : AUTO_OFF) + enabling);
        return enabling;
    }
    if (!ft8_radio_offset_set() || state != AUTO_READY || !ft8_radio_same_call(row->text, row->sender, ui->dx_call) ||
        !ui->my_call[0] || clock_age(now_ms(), end) >= 30000)
        return 0;
    unsigned step = 0;
    if (ft8_radio_same_call(row->text, row->recipient, ui->my_call)) {
        const unsigned kind = auto_message(row);
        if (kind > RX_RR73)
            return 0;
        step = kind < RX_RRR ? kind + 1 : 4;
    } else if (memcmp(row->text, "CQ ", 3)) {
        return 0;
    }
    automatic.station = *ui;
    automatic.step = step;
    automatic.retries = 0;
    automatic.activity = now_ms();
    return auto_transition(AUTO_READY, AUTO_POSTED);
}

static int auto_key(uint32_t boundary)
{
    if (LOAD(&automatic.state) != AUTO_TX)
        return 0;
    automatic.key_edge = boundary;
    return 1;
}

static void auto_service(void)
{
    unsigned state = LOAD(&automatic.state);
    if (state >= AUTO_CANCEL_OFF) {
        if (full_enabled())
            STORE(&full->enabled, 0);
        auto_transition(state, state - AUTO_CANCEL_OFF);
        return;
    }
    if (state <= AUTO_READY)
        return;
    const int unattended = full_enabled();
    if (state == AUTO_RX) {
        if (full_checking() || clock_age(now_ms(), automatic.key_edge) < SLOT_MS + DECODE_CUTOFF_MS)
            return;
        if (automatic.step != FT8_TX_CQ && automatic.retries < LOAD(&ft8_auto_options.retries)) {
            ++automatic.retries;
            automatic.activity = now_ms();
            auto_transition(AUTO_RX, AUTO_POSTED);
        } else if (unattended) {
            full_next();
        } else {
            auto_transition(AUTO_RX, AUTO_READY);
        }
        state = LOAD(&automatic.state);
    }
    if (clock_age(now_ms(), automatic.activity) >= 45000) {
        if (unattended)
            full_stop(state);
        else
            auto_transition(state, AUTO_READY);
        return;
    }
    if (state != AUTO_POSTED)
        return;
    char message[FT8_MESSAGE_CHARS];
    const uint32_t local = LIVE->grid();
    unsigned step = automatic.step;
    if (step == 0 && !local)
        step = 1;
    const unsigned hz = automatic.station.tx_offset_hz;
    automatic.step = step;
    if (!ft8_ui_std_message(step, &automatic.station, local, message)) {
        if (unattended)
            full_stop(AUTO_POSTED);
        else
            auto_transition(AUTO_POSTED, AUTO_READY);
        return;
    }
    if (unattended && step == 3)
        memcpy(message + strlen(message) - 3, "RR73", 5);
    if (auto_transition(AUTO_POSTED, AUTO_TX) &&
        !LIVE->tx_arm(message, FT8_TX_AUTO_FLAG | (hz ? hz : FT8_TX_DEFAULT_HZ))) {
        if (unattended)
            full_stop(AUTO_TX);
        else
            auto_transition(AUTO_TX, AUTO_READY);
    }
}

static void auto_sent(void)
{
    if (full_enabled()) {
        if (!auto_transition(AUTO_TX, AUTO_RX))
            return;
        if (automatic.step == FT8_TX_CQ) {
            if (full->cq_left != FT8_CQ_UNLIMITED)
                --full->cq_left;
            full_publish();
        } else if (automatic.step >= 3) {
            memcpy(full->completed[full->done % FULL_RECENT_CALLS], automatic.station.dx_call,
                   sizeof(full->completed[0]));
            ++full->done;
            full_next();
        }
        return;
    }
    if (auto_transition(AUTO_TX, automatic.step == 4 ? AUTO_READY : AUTO_RX))
        automatic.activity = now_ms();
}

__attribute__((noinline)) void ft8_radio_auto_rx(const struct ft8_rx_result *rows,
                                                 size_t count, uint32_t end)
{
    if (LOAD(&automatic.state) != AUTO_RX)
        return;
    if (full_enabled()) {
        full_rx(rows, count, end);
        return;
    }
    const unsigned step = automatic.step;
    for (size_t i = 0; i < count; ++i) {
        const struct ft8_rx_result *row = &rows[i];
        if (!auto_peer_matches(row))
            continue;
        const uint32_t edge = ft8_radio_received_edge(row, end);
        const unsigned age = clock_age(edge, automatic.key_edge);
        if (age < 12000 || age > 18000)
            continue;
        const unsigned kind = auto_message(row);
        if (step == 3 && (kind == RX_73 || kind == RX_RR73)) {
            auto_transition(AUTO_RX, AUTO_READY);
            return;
        }
        if (!((step == 0 && kind == RX_REPORT) ||
              (step == 1 && kind == RX_RREPORT) ||
              (step == 2 && (kind == RX_RRR || kind == RX_RR73))))
            continue;
        automatic.step = step < 2 ? step + 2 : 4;
        automatic.retries = 0;
        automatic.activity = now_ms();
        automatic.station.tx_report = row->snr_db + FT8_REPORT_BIAS;
        auto_transition(AUTO_RX, AUTO_POSTED);
        return;
    }
}

__attribute__((noinline)) void ft8_radio_audio_slot(const struct ft8_rx_result *rows,
                                                    size_t count, uint32_t end)
{
    if (ft8_radio_offset_set())
        return;
    /* A miss restores rolling acquisition. Only full-band CRC-verified
       decodes steer RX phase. TX continues to use the RTC and user offset. */
    unsigned best = 0;
    int offset = 0;
    for (size_t i = 0; i < count; ++i) {
        unsigned votes = 0;
        const int first = rows[i].offset_ms;
        for (size_t j = 0; j < count; ++j)
            votes += (unsigned)(rows[j].offset_ms - first + 160) <= 320;
        if (votes > best) {
            best = votes;
            offset = first;
        }
    }
    radio.audio_votes = best;
    if (best) {
        const unsigned back = SLOT_MS + 500 - offset;
        radio.audio_boundary = end - back + (end < back ? CLOCK_MS_PERIOD : 0);
        radio.last_scan_ms = end;
    }
}

static unsigned audio_phase(uint32_t age)
{
    if (age > CLOCK_MS_PERIOD / 2)
        age += SLOT_MS - CLOCK_MS_PERIOD % SLOT_MS;
    return age % SLOT_MS;
}

static unsigned locked_phase(uint32_t time)
{
    const unsigned age = clock_age(time, radio.audio_boundary);
    const unsigned phase = audio_phase(age);
    if (age >= SLOT_MS && age < CLOCK_MS_PERIOD / 2)
        radio.audio_boundary = time - phase + (time < phase ? CLOCK_MS_PERIOD : 0);
    return phase;
}

unsigned ft8_radio_roll_blocks(uint32_t end)
{
    if (ft8_radio_offset_set())
        return 12;
    if (full_enabled() && LOAD(&automatic.state) == AUTO_RX && !full->checking)
        return 12;
    if (!radio.audio_votes)
        return 12;
    unsigned until = (SCAN_PHASE_MS + SLOT_MS - locked_phase(end)) % SLOT_MS;
    if (!until)
        until = SLOT_MS;
    const unsigned blocks = (until + 159) / 160;
    return blocks < 93 ? blocks : 93;
}

PROFILE_CODE(scan) static int scan_due(uint32_t end, unsigned samples, unsigned sealed)
{
    if (ft8_radio_offset_set()) {
        if (!manual_clock())
            return samples == FT8_SLOT_SAMPLES;
        const uint32_t now = now_ms();
        const unsigned current = phase30(now) % SLOT_MS;
        const unsigned age = clock_age(end, radio.last_scan_ms);
        if (!sealed)
            return 0;
        const unsigned reason = samples < FT8_MIN_RX_BLOCKS * 2560 ? 1 : age < 12000 ? 2 :
            current >= DECODE_CUTOFF_MS ? 3 : clock_age(now, end) > current ? 4 : 0;
        if (reason) {
            PROFILE_MARK(PROF_SCAN_REJECT, (reason << 13) | (current / 2));
            return 0;
        }
        radio.last_scan_ms = end;
        return 1;
    }
    if (samples != FT8_SLOT_SAMPLES)
        return 0;
    if (full_enabled() && LOAD(&automatic.state) == AUTO_RX) {
        const unsigned age = clock_age(end, automatic.key_edge);
        return !full->checking && age >= 25500 && age <= 33500;
    }
    if (!radio.audio_votes)
        return 1;
    const unsigned phase = locked_phase(end);
    if ((phase < SCAN_PHASE_MS && phase >= 900) ||
        clock_age(end, radio.last_scan_ms) < 12000)
        return 0;
    radio.last_scan_ms = end;
    return 1;
}

#pragma clang section text=".ft8_clock_text"
__attribute__((noinline)) static void poll_slot(uint32_t now, uint32_t *last_read, int *previous)
{
    if (now - *last_read < RTC_POLL_US)
        return;
    const int second = read_second();
    const uint32_t seen = now_us();
    const uint32_t gap = seen - *last_read;
    const unsigned ms = seen / 1000;
    if (second >= 0 && *previous >= 0 && second == (*previous + 1) % 60 && gap <= RTC_MAX_EDGE_US) {
        const unsigned midpoint = seen - gap / 2;
        ft8_clock.anchor = midpoint / 1000;
        ft8_clock.second = second;
        STORE(&ft8_clock.valid, 1);
    }
    if (second < 0 || (LOAD(&ft8_clock.valid) && clock_age(ms, ft8_clock.anchor) > 2000))
        STORE(&ft8_clock.valid, 0);
    if (manual_clock()) {
        const unsigned phase = (phase30(ms) + 30000 - SLOT_MS * ft8_radio_tx_slot()) % 30000;
        STORE(&radio.tx_wait_s, 30 - phase / 1000);
        if (phase <= 100)
            LIVE->sync_time(ms - phase);
    } else {
        STORE(&radio.tx_wait_s, 0);
    }
    *last_read = seen;
    *previous = second;
}
#pragma clang section text=""

__attribute__((target("arm"))) void ft8_radio_worker(unsigned unused)
{
    (void)unused;
    uint32_t last_read = 0;
    int previous = -1;
    for (;;) {
        if (LOAD(&radio.active)) {
#ifdef FT8_VFP
            ft8_fft_prepare();
#endif
            STORE(&radio.parked, 0);
            const uint32_t now = now_us();
            STORE(&radio.last_heartbeat, now);
            auto_service();
            poll_slot(now, &last_read, &previous);
            /* Yield even when multiple frames are queued. No IRQ or UART wait
               runs from inside the decoder and watchdog priority is higher. */
            radio.worker_polling = 1;
            for (unsigned i = 0; i < 3; ++i) {
                const uint32_t tick = now_us();
                radio.decode_timed = manual_clock();
                if (radio.decode_timed) {
                    const unsigned phase = phase30(tick / 1000) % SLOT_MS;
                    radio.decode_deadline = tick - tick % 1000 +
                        (DECODE_CUTOFF_MS - phase) * 1000;
                }
                if (!LIVE->poll() || ft8_radio_decode_expired())
                    break;
                STORE(&radio.last_heartbeat, now_us());
            }
            radio.worker_polling = 0;
#ifdef FT8_PROFILE
            ft8_live_profile_window(ft8_radio_rx_phase(now_ms()));
            /* Stay off the card during TX and near decode or keying. */
            if (LOAD(&radio.lease) == LEASE_IDLE &&
                (!manual_clock() || phase30(now_ms()) % SLOT_MS < 11000))
                ft8_profile_flush(0);
#endif
            if (LOAD(&radio.lease) == LEASE_IDLE && !decode_cutoff(now_ms())) {
                load_worked_step();
#ifdef FT8_SD_PLUGIN
                if (auto_state() <= AUTO_READY)
                    ft8_plugin_load();
#endif
            }
        } else if (!LOAD(&radio.parked)) {
            previous = -1;
            STORE(&radio.tx_wait_s, 0);
            LIVE->poll();
            close_worked_file();
            if (LOAD(&radio.lease) == LEASE_IDLE) {
#ifdef FT8_PROFILE
                ft8_profile_flush(1);
                ft8_profile_bind(NULL);
#endif
                STORE(&radio.parked, 1);
            }
        }
#ifdef FT8_CUSTOM_MODES
        else if (ft8_radio_cw_available()) {
            cw_worker_step();
            cw_worker_step();
        }
#endif
        delay();
    }
}

/* The stock flash copy ends at 0x606d0000. The stock boot stack descends
   from 0x606dc000, above these two disjoint task stacks. */
extern void ft8_radio_worker_entry(unsigned);
extern void ft8_radio_watchdog_entry(unsigned);
static const struct task_params worker_params = {
    /* SPI/audio and touch use priorities 4–5, UART background uses 7,
       and the root display task uses 8. Smaller numbers run first. */
    0, 0, ft8_radio_worker_entry, 6, FT8_ARM_STACK_BYTES, (void *)0x606d0000u, "ft8-rx"
};
static const struct task_params watchdog_params = {
    0, 0, ft8_radio_watchdog_entry, 5, 4096, (void *)0x606d8000u, "ft8-wd"
};

static int start_task(int *id, const struct task_params *params)
{
    if (*id > 0)
        return 1;
    if (*id == 0) {
        const int created = STOCK(0x78fb0, create_fn)(0, params);
        if (created <= 0)
            return 0;
        *id = -created;
    }
    if (STOCK(0x7a830, start_fn)(-*id, 0) != 0)
        return 0;
    *id = -*id;
    return 1;
}

#ifdef FT8_CUSTOM_MODES
int ft8_radio_start_worker(void)
{
    return start_task(&radio.worker_id, &worker_params);
}

int ft8_radio_cw_available(void)
{
    /* No decoder or borrowed TX descriptor may still own the shared arena. */
    return !LOAD(&radio.allocation) && !LOAD(&radio.active) &&
           LOAD(&radio.lease) == LEASE_IDLE && !LOAD(&radio.borrowed);
}
#endif

static size_t runtime_bytes(void)
{
    return LIVE->work_bytes + sizeof(struct ft8_worked) + sizeof(struct full_auto) + 31
#ifdef FT8_PROFILE
        + PROF_BUFFER_BYTES
#endif
        ;
}

static void release_workspace(void *memory)
{
    const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
    STOCK(0x7d9ec, free_fn)(memory, runtime_bytes());
    STOCK(0xbfaac, irq_restore_fn)(irq);
}

static void *allocate_workspace(void)
{
    /* Leave the whole stock ctMalloc pool for the graphics and filesystems. */
    if (!(int32_t)REG32(0x607c50bcu) && STOCK(0x7703c, int_fn)() != 0)
        return NULL;
    const unsigned irq = STOCK(0xbfa8c, irq_lock_fn)();
    void *memory = STOCK(0x7d9e0, alloc_fn)(runtime_bytes());
    STOCK(0xbfaac, irq_restore_fn)(irq);
    return memory;
}

static int release_if_idle(void)
{
    void *allocation = LOAD(&radio.allocation);
    if (!allocation)
        return 1;
    if (!LOAD(&radio.parked) || LOAD(&radio.borrowed) || !LIVE->unbind())
        return 0;
    STORE(&radio.dma, NULL);
    worked = NULL;
    full = NULL;
    release_workspace(allocation);
    STORE(&radio.allocation, NULL);
    return 1;
}

static int menu(int open)
{
    if (!open) {
        STORE(&radio.active, 0);
        STORE(&automatic.state, AUTO_OFF);
        if (full)
            STORE(&full->enabled, 0);
        radio.attempted = 0;
        release_if_idle();
        return 0;
    }
    if (LOAD(&radio.active))
        return 1;
    if (radio.attempted || !release_if_idle())
        return 0;
    radio.attempted = 1;
    radio.audio_votes = 0;
    STORE(&ft8_clock.valid, 0);
    STORE(&radio.parked, 1);
    void *allocation = allocate_workspace();
    if (!allocation)
        return 0;
    if ((NATIVE_TX_BUILT && !start_task(&radio.watchdog_id, &watchdog_params)) ||
        !start_task(&radio.worker_id, &worker_params)) {
        release_workspace(allocation);
        return 0;
    }
    void *workspace = (void *)(((uintptr_t)allocation + 31u) & ~31u);
    if (!LIVE->bind(workspace, LIVE->work_bytes)) {
        release_workspace(allocation);
        return 0;
    }
    STORE(&radio.allocation, allocation);
    STORE(&radio.dma, NATIVE_TX_BUILT ? (void *)FT8_RADIO_RX_WATERFALL : NULL);
    if (!LIVE->attach_tx(&io))
        return 0;
    worked = (void *)((char *)workspace + LIVE->work_bytes);
    worked->count = worked->next = worked->fill = 0;
    worked->recent_revision = 0;
    memset(worked->recent, 0, sizeof(worked->recent));
    full = (void *)(worked + 1);
#ifdef FT8_PROFILE
    ft8_profile_bind(full + 1);
#endif
    full->enabled = full->revision = 0;
    worked_pending = 1;
#ifdef FT8_SD_PLUGIN
    ft8_plugin_request();
#endif
    STORE(&automatic.state, LOAD(&ft8_auto_options.enabled) ? AUTO_READY : AUTO_OFF);
    STORE(&radio.active, 1);
    return 1;
}

uintptr_t ft8_radio_dma_source(uintptr_t stock)
{
    if (LOAD(&radio.lease) != LEASE_ON || LOAD(&radio.stop_requested))
        return stock;
    const uint32_t dma_status = REG32(STOCK_DMA3_STATUS);
    unsigned wait = FT8_RADIO_PCM_FULL;
    if (stock != STOCK_SILENCE || stock_audio_busy())
        wait = FT8_RADIO_AUDIO_BUSY;
    else if (dma_status & STOCK_DMA3_ERROR)
        wait = FT8_RADIO_DMA_ERROR;
    else if (LOAD(&radio.borrowed))
        wait = FT8_RADIO_DMA_NO_DONE;
    else if (REG16(0x607c4012u) <= 0xff)
        wait = FT8_RADIO_NO_CREDIT;
    else if (dma_status & STOCK_DMA3_BUSY)
        wait = FT8_RADIO_DMA_BUSY;
    /* CHSTAT.END and CHSTAT.TC can remain set after a completed stock
       transfer. They do not block N0SA replacement at this stock handoff. */
    STORE(&radio.dma_wait, wait);
    if (wait != FT8_RADIO_PCM_FULL)
        return stock;
    struct ft8_dma_tx *dma = LOAD(&radio.dma);
    const struct ft8_dma_tx_frame *frame = dma ? ft8_dma_tx_select(dma) : NULL;
    if (!frame)
        return stock;
    STORE(&radio.borrowed, frame);
    STORE(&radio.dma_wait, FT8_RADIO_DMA_NO_DONE);
    return (uintptr_t)frame;
}

void ft8_radio_dma_done(void)
{
    struct ft8_dma_tx *dma = LOAD(&radio.dma);
    const struct ft8_dma_tx_frame *borrowed = LOAD(&radio.borrowed);
    if (!dma || !borrowed)
        return;
    if (REG32(STOCK_DMA3_STATUS) & STOCK_DMA3_BUSY)
        return;
    if (REG32(STOCK_DMA3_STATUS) & STOCK_DMA3_ERROR)
        request_stop(FT8_RADIO_DMA_ERROR);
    if (ft8_dma_tx_complete(dma, borrowed)) {
        STORE(&radio.borrowed, NULL);
        STORE(&radio.dma_wait, FT8_RADIO_PCM_FULL);
    }
}

const struct ft8_radio_api ft8_radio_api = {
    menu, ft8_radio_dma_source, ft8_radio_dma_done, ft8_radio_report_packet,
    native_tx_route_available, tx_seconds, tx_fault, tx_power,
    station_call, station_grid, qso_event, scan_due,
    auto_state, auto_event, auto_key, full_revision, toggle_tx_slot, ft8_radio_rx_timing,
};
