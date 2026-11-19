#include "ft8_profile.h"
#include "ft8_live.h"
#include <stddef.h>

#define STOCK(offset, type) ((type)(0x60400000u + (offset)))
#define DATA __attribute__((section(".data.ft8")))

struct profile_record {
    uint32_t start_us, elapsed_us;
    uint16_t event, detail;
};
_Static_assert(sizeof(struct profile_record) == 12, "profile record format");
static struct profile_record *records DATA = NULL;
static unsigned used DATA = 0, lost DATA = 0;
static unsigned pending DATA = 0, sealed DATA = 0;

#define LOCK() STOCK(0xbfa8c, unsigned (*)(void))()
#define UNLOCK(irq) STOCK(0xbfaac, void (*)(unsigned))(irq)

void ft8_profile_bind(void *buffer)
{
    records = buffer;
    used = lost = pending = sealed = 0;
}

PROFILE_CODE(log)
void ft8_profile_event(unsigned event, unsigned detail, uint32_t started)
{
    const uint32_t elapsed = ft8_profile_now() - started;
    const unsigned irq = LOCK();
    if (records) {
        if (used >= PROF_BUFFER_BYTES / sizeof(*records) - 1)
            ++lost;
        else
            records[used++] = (struct profile_record) { started, elapsed, event, detail };
    }
    UNLOCK(irq);
}

PROFILE_CODE(log)
void ft8_profile_mark(unsigned event, unsigned detail)
{
    ft8_profile_event(event, detail, ft8_profile_now());
}

__attribute__((noinline, section(".ft8_profile_text")))
void ft8_profile_stop(unsigned reason, uint32_t now)
{
    __atomic_store_n(&pending, 3, __ATOMIC_RELEASE);
    ft8_profile_event(PROF_STOP, reason, now);
}

__attribute__((noinline)) void ft8_profile_capture(unsigned event, unsigned detail)
{
    const unsigned bit = event == PROF_DMA_FIRST ? 1 : 2;
    if ((__atomic_load_n(&pending, __ATOMIC_ACQUIRE) & bit) &&
        (__atomic_fetch_and(&pending, ~bit, __ATOMIC_ACQ_REL) & bit))
        PROFILE_MARK(event, detail);
}

__attribute__((noinline, section(".ft8_profile_text")))
void ft8_profile_window(unsigned phase, unsigned samples, unsigned status)
{
    if (phase < FT8_CAPTURE_END_MS) {
        sealed = 0;
    } else if (phase < FT8_PERIOD_MS && !sealed && (!status || phase >= FT8_DECODE_END_MS)) {
        sealed = 1;
        PROFILE_MARK(PROF_SLOT_SAMPLES, ((samples / 16) & 0x3fff) | (status << 14));
    }
}

PROFILE_CODE(log)
void ft8_profile_flush(int final)
{
    /* Batch the SD operations so acquisition does not open and close
       the file after every DMA frame. BACK always flushes the remainder. */
    if (!used || (!final && used < 128))
        return;
    PROFILE_START(start);
    void *file = STOCK(0x6995c, void *(*)(const char *, const char *))
        ("I:\\FTX-1\\FT8TIME.BIN", "ab");
    if (!file)
        return;
    unsigned irq = LOCK();
    if (lost) {
        records[used++] = (struct profile_record) {
            start, 0, PROF_LOST, lost > 65535 ? 65535 : lost
        };
        lost = 0;
    }
    const unsigned count = used;
    UNLOCK(irq);
    const size_t n = STOCK(0x6b51c, size_t (*)(const void *, size_t, size_t, void *))
        (records, sizeof(*records), count, file);
    const int closed = STOCK(0x69e90, int (*)(void *))(file);
    irq = LOCK();
    if (n <= count) {
        used -= n;
        __builtin_memmove(records, records + n, used * sizeof(*records));
    }
    UNLOCK(irq);
    PROFILE_END(start, PROF_SD, closed ? 0 : n);
}
