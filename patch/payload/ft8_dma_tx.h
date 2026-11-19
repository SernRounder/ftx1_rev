#ifndef FTX1_FT8_DMA_TX_H
#define FTX1_FT8_DMA_TX_H

#include <stddef.h>
#include <stdint.h>

#ifndef FT8_DMA_TX_SLOTS
#define FT8_DMA_TX_SLOTS 4
#endif

enum {
    FT8_DMA_TX_SAMPLES = 800,
    FT8_DMA_TX_BYTES = 0x2260,
};

struct ft8_dma_tx_frame {
    _Alignas(32) uint16_t words[FT8_DMA_TX_BYTES / sizeof(uint16_t)];
};

struct ft8_dma_tx {
    struct ft8_dma_tx_frame frames[FT8_DMA_TX_SLOTS];
    uint32_t write, read, state;
};

/* Zero-initialize before first use. Only the worker begins and submits frames.
   The watchdog may inhibit at any time. IRQ selection and retirement are serialized
   by the platform. A borrowed DMA frame is retained across inhibit and drain. */
int ft8_dma_tx_begin(struct ft8_dma_tx *tx);
void ft8_dma_tx_inhibit(struct ft8_dma_tx *tx);
int ft8_dma_tx_submit(struct ft8_dma_tx *tx, const int16_t *stereo, size_t samples,
                      void (*clean)(const void *, size_t));
/* The caller verifies the stock silence fallback, TX credit and that CH3 is idle
   with no unhandled completion. NULL means retain the stock DMA source. */
const struct ft8_dma_tx_frame *ft8_dma_tx_select(struct ft8_dma_tx *tx);
/* Call only on verified CH3 completion of this exact source. */
int ft8_dma_tx_complete(struct ft8_dma_tx *tx, const struct ft8_dma_tx_frame *source);
int ft8_dma_tx_drained(const struct ft8_dma_tx *tx);
int ft8_dma_tx_busy(const struct ft8_dma_tx *tx);

#endif
