#ifndef FTX1_FT8_PROFILE_H
#define FTX1_FT8_PROFILE_H

enum {
    PROF_FRAME = 0x8101, PROF_FFT, PROF_SEARCH, PROF_SORT, PROF_CANDIDATE,
    PROF_LLR, PROF_NORMALIZE, PROF_LDPC, PROF_CRC, PROF_UNPACK, PROF_METRICS,
    PROF_RESULTS, PROF_PUBLISH, PROF_YIELD, PROF_SCAN, PROF_SD, PROF_LOST,
    PROF_STOP, PROF_MAIN_RX, PROF_RX_TIMEOUT, PROF_DMA_FIRST, PROF_QUEUED_FIRST,
    PROF_PCM_DROP, PROF_PCM_GAP, PROF_SLOT_SAMPLES, PROF_SLOT_STATUS, PROF_RX_READY,
    PROF_SEALED, PROF_BATCH, PROF_DRAW,
    PROF_TX_FAULT, PROF_TX_REQUEST, PROF_TX_KEYED, PROF_SCAN_REJECT, PROF_RX_SYNC,
    PROF_BUFFER_BYTES = 11520,
};
#ifdef FT8_PROFILE
#include <stdint.h>
static inline uint32_t ft8_profile_now(void)
{
    return ((uint32_t (*)(void))0x6041669cu)();
}
void ft8_profile_event(unsigned event, unsigned detail, uint32_t started);
void ft8_profile_mark(unsigned event, unsigned detail);
void ft8_profile_bind(void *buffer);
void ft8_profile_flush(int final);
void ft8_profile_stop(unsigned reason, uint32_t now);
void ft8_profile_capture(unsigned event, unsigned detail);
void ft8_profile_window(unsigned phase, unsigned samples, unsigned status);
void ft8_live_profile_window(unsigned phase);
#define PROFILE_START(name) uint32_t name = ft8_profile_now()
#define PROFILE_END(name, event, detail) ft8_profile_event(event, detail, name)
#define PROFILE_MARK(event, detail) ft8_profile_mark(event, detail)
#define PROFILE_CODE(region) __attribute__((noinline, section(".trace_" #region)))
#else
#define PROFILE_START(name) ((void)0)
#define PROFILE_END(name, event, detail) ((void)0)
#define PROFILE_MARK(event, detail) ((void)0)
#define PROFILE_CODE(region)
#endif
#endif
