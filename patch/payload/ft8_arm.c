/* Receiver payload ABI. Work RAM and the worker stack are provisioned by the caller. */
#include "ft8_rx.h"
#include "ft8_profile.h"
#include "ft8_tx.h"
#include "ft8_live.h"
#include "ft8_adif.h"
#ifdef FT8_CUSTOM_MODES
#include "cw_panel.h"
#endif

#include <stdio.h>
#include <string.h>


struct receiver {
    struct ft8_rx rx;
    size_t used;
};

static struct receiver *owner __attribute__((section(".data.ft8"))) = NULL;
#ifdef FT8_RADIO
static size_t low_used __attribute__((section(".data.ft8"))) = 0;
#endif

void *ft8_arm_malloc(size_t size)
{
    if (size > SIZE_MAX - 7u)
        return NULL;
    const size_t aligned = (size + 7u) & ~7u;
#ifdef FT8_RADIO
    /* monitor_init allocates Hann first and the waterfall last. Place those
       two tables below the image and keep the receiver, overlap and FFT high. */
    if (!low_used || aligned > FT8_ARM_WORK_BYTES) {
        if ((!low_used && aligned != FT8_RADIO_RX_HANN_BYTES) ||
            (low_used && low_used != FT8_RADIO_RX_HANN_BYTES))
            return NULL;
        if (aligned > FT8_RADIO_RX_LOW_BYTES - low_used)
            return NULL;
        void *ptr = (void *)(FT8_RADIO_RX_LOW_BASE + low_used);
        low_used += aligned;
        return ptr;
    }
#endif
    if (aligned > FT8_ARM_WORK_BYTES - owner->used)
        return NULL;
    void *ptr = (unsigned char *)owner + owner->used;
    owner->used += aligned;
    return ptr;
}

void *ft8_arm_calloc(size_t count, size_t size)
{
    if (size != 0 && count > SIZE_MAX / size)
        return NULL;
    size *= count;
    void *ptr = ft8_arm_malloc(size);
    return ptr ? memset(ptr, 0, size) : NULL;
}

void ft8_arm_free(void *ptr)
{
    /* Both supported FFT sizes use only radix 2/3/4/5. The arena resets on open. */
    (void)ptr;
}

FILE *const stderr = NULL;

int ft8_arm_fprintf(FILE *stream, const char *format, ...)
{
    (void)stream;
    (void)format;
    return 0;
}

_Noreturn void ft8_arm_exit(int status)
{
    (void)status;
    __builtin_trap();
}

static struct ft8_rx *open_receiver(void *work, size_t length)
{
#ifdef FT8_VFP_ONLY
    extern unsigned ft8_fft_backend(void);
    if (ft8_fft_backend() != 2)
        return NULL;
#endif
    if (!work || length < FT8_ARM_WORK_BYTES || (uintptr_t)work % 8)
        return NULL;
#ifdef FT8_RADIO
    if ((uintptr_t)work != FT8_RADIO_RX_HIGH_BASE)
        return NULL;
    low_used = 0;
#endif
    owner = work;
    owner->used = (sizeof(*owner) + 7u) & ~7u;
    if (!ft8_rx_init(&owner->rx, 16000))
        return NULL;
#ifdef FT8_RADIO
    /* Keep the candidate heap after the waterfall in the existing low arena.
       The high arena holds the FFT tables and has little spare capacity. */
    if (sizeof(ftx_candidate_t) * FT8_RX_CANDIDATES > FT8_RADIO_RX_LOW_BYTES - low_used)
        return NULL;
    owner->rx.candidates = (void *)(FT8_RADIO_RX_LOW_BASE + low_used);
#endif
    return &owner->rx;
}

/* Stock recording observes a sample count, one metadata halfword, then PCM lane 0.
   The caller must supply a stable copy of a type-1 RX frame. */
static size_t push_frame(struct ft8_rx *rx, const uint16_t *frame, size_t bytes)
{
    if (bytes < 4)
        return 0;
    const size_t samples = frame[0];
    if (samples == 0 || samples > FT8_FRAME_MAX_SAMPLES || samples > (bytes - 4) / 2)
        return 0;
    return ft8_rx_push(rx, (const int16_t *)(frame + 2), samples);
}

#ifdef FT8_RADIO
static size_t push_native_pcm(struct ft8_rx *rx, const int16_t *pcm, size_t count)
{
    if (pcm)
        return ft8_rx_push(rx, pcm, count);
    const int16_t silence[256] = {0};
    if (count > sizeof(silence) / sizeof(silence[0]))
        count = sizeof(silence) / sizeof(silence[0]);
    return ft8_rx_push(rx, silence, count);
}

void ft8_radio_audio_slot(const struct ft8_rx_result *, size_t, uint32_t);
void ft8_radio_auto_rx(const struct ft8_rx_result *, size_t, uint32_t);

static size_t finish_native(struct ft8_rx *rx, struct ft8_rx_result *out, size_t capacity,
                            uint32_t end_ms)
{
    const size_t count = ft8_rx_finish(rx, out, capacity);
    PROFILE_START(results);
    ft8_radio_audio_slot(out, count, end_ms);
    for (size_t i = 0; i < count; ++i)
        ft8_radio_api.qso_event(out[i].text, rx->locator, 1, 0);
    ft8_radio_auto_rx(out, count, end_ms);
    PROFILE_END(results, PROF_RESULTS, count);
    return count;
}
#endif

/* Transmit state is provisioned by the caller; open validates the storage. */
static struct ft8_tx *open_transmitter(void *memory, size_t length,
                                       const uint8_t *tones, unsigned frequency_hz)
{
    if (!memory || length < sizeof(struct ft8_tx) || (uintptr_t)memory % 4)
        return NULL;
    if (!ft8_tx_start(memory, tones, frequency_hz))
        return NULL;
    return memory;
}

const struct ft8_arm_api ft8_arm_api __attribute__((section(".ft8_api"), used)) = {
    FT8_ARM_MAGIC, FT8_ARM_VERSION, FT8_ARM_WORK_BYTES, FT8_ARM_STACK_BYTES,
#ifdef FT8_RADIO
    open_receiver, ft8_rx_begin_slot, push_native_pcm, push_frame, finish_native, ft8_rx_set_locator,
#else
    open_receiver, ft8_rx_begin_slot, ft8_rx_push, push_frame, ft8_rx_finish, ft8_rx_set_locator,
#endif
    ft8_tx_encode, ft8_tx_encode_free, open_transmitter, ft8_tx_next,
    ft8_ui_draw, ft8_ui_std_message,
    ft8_adif_record,
#ifdef FT8_RADIO
    &ft8_radio_api,
    ft8_rx_roll,
    ft8_ui_edit,
    ft8_ui_hit,
    ft8_ui_page,
    ft8_ui_select_sender,
#ifdef FT8_CUSTOM_MODES
    &cw_panel_api,
#endif
#endif
};
