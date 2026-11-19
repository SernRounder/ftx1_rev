#include "ft8_dma_tx.h"

#define LOAD(p) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define STORE(p, v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)

_Static_assert(sizeof(struct ft8_dma_tx_frame) == FT8_DMA_TX_BYTES, "DMA transfer span");

enum { ENABLED = 1, IN_FLIGHT = 2 };

int ft8_dma_tx_begin(struct ft8_dma_tx *tx)
{
    if (LOAD(&tx->state))
        return 0;
    /* The IRQ cannot select an old source while the queue is disabled. */
    STORE(&tx->read, 0);
    STORE(&tx->write, 0);
    STORE(&tx->state, ENABLED);
    return 1;
}

void ft8_dma_tx_inhibit(struct ft8_dma_tx *tx)
{
    __atomic_fetch_and(&tx->state, ~(uint32_t)ENABLED, __ATOMIC_ACQ_REL);
}

int ft8_dma_tx_submit(struct ft8_dma_tx *tx, const int16_t *pcm, size_t samples,
                      void (*clean)(const void *, size_t))
{
    const uint32_t write = tx->write;
    if ((samples != FT8_DMA_TX_SAMPLES && samples != 2 * FT8_DMA_TX_SAMPLES) ||
        !(LOAD(&tx->state) & ENABLED) || write - LOAD(&tx->read) == FT8_DMA_TX_SLOTS)
        return 0;
    struct ft8_dma_tx_frame *frame = &tx->frames[write % FT8_DMA_TX_SLOTS];
    frame->words[0] = (uint16_t)samples;
    frame->words[1] = 0x1234;
    for (size_t i = 0; i < samples; ++i)
        frame->words[2 + i] = (uint16_t)pcm[
#ifndef FT8_RADIO
            2 *
#endif
            i];
    for (size_t i = 2 + samples; i < FT8_DMA_TX_BYTES / sizeof(uint16_t); ++i)
        frame->words[i] = 0;
    clean(frame, sizeof(*frame));
    if (!(LOAD(&tx->state) & ENABLED))
        return 0;
    STORE(&tx->write, write + 1);
    return 1;
}

const struct ft8_dma_tx_frame *ft8_dma_tx_select(struct ft8_dma_tx *tx)
{
    const uint32_t read = LOAD(&tx->read);
    uint32_t expected = ENABLED;
    if (read == LOAD(&tx->write) ||
        !__atomic_compare_exchange_n(&tx->state, &expected, ENABLED | IN_FLIGHT, 0,
                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return NULL;
    return &tx->frames[read % FT8_DMA_TX_SLOTS];
}

int ft8_dma_tx_complete(struct ft8_dma_tx *tx, const struct ft8_dma_tx_frame *source)
{
    const uint32_t read = LOAD(&tx->read);
    if (!(LOAD(&tx->state) & IN_FLIGHT) || source != &tx->frames[read % FT8_DMA_TX_SLOTS])
        return 0;
    STORE(&tx->read, read + 1);
    __atomic_fetch_and(&tx->state, ~(uint32_t)IN_FLIGHT, __ATOMIC_ACQ_REL);
    return 1;
}

int ft8_dma_tx_drained(const struct ft8_dma_tx *tx)
{
    return !(LOAD(&tx->state) & IN_FLIGHT) && LOAD(&tx->read) == LOAD(&tx->write);
}

int ft8_dma_tx_busy(const struct ft8_dma_tx *tx)
{
    return (LOAD(&tx->state) & IN_FLIGHT) != 0;
}
