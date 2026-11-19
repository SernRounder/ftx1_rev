#ifndef FTX1_FT8_ARM_API_H
#define FTX1_FT8_ARM_API_H

#include <stddef.h>
#include <stdint.h>

enum {
    FT8_ARM_MAGIC = 0x52385446u,
#ifdef FT8_RADIO
#ifdef FT8_CUSTOM_MODES
#ifdef FT8_SD_PLUGIN
    FT8_ARM_VERSION = 35,
#elif defined(FT8_HOOK_VECTORS)
    FT8_ARM_VERSION = 33,
#else
    FT8_ARM_VERSION = 27,
#endif
#elif defined(FT8_SD_PLUGIN)
    FT8_ARM_VERSION = 34,
#elif defined(FT8_HOOK_VECTORS)
    FT8_ARM_VERSION = 32,
#else
    FT8_ARM_VERSION = 26,
#endif
    FT8_ARM_STACK_BYTES = 32 * 1024,
    FT8_RADIO_RX_LOW_BASE = 0x603d0880u,
    FT8_RADIO_RX_LOW_BYTES = 0x60400000u - FT8_RADIO_RX_LOW_BASE,
    FT8_RADIO_RX_HANN_BYTES = 5120 * sizeof(float),
    FT8_RADIO_RX_WATERFALL = FT8_RADIO_RX_LOW_BASE + FT8_RADIO_RX_HANN_BYTES,
    FT8_RADIO_RX_HIGH_BASE = 0x609ebe30u,
    FT8_ARM_WORK_BYTES = 0x60a00000u - FT8_RADIO_RX_HIGH_BASE,
#else
    FT8_ARM_VERSION = 6,
    FT8_ARM_STACK_BYTES = 40 * 1024,
    /* The 16 kHz receiver's aligned allocations consume 269,816 bytes. */
    FT8_ARM_WORK_BYTES = 272 * 1024,
#endif
    FT8_FRAME_MAX_SAMPLES = 2000,
    FT8_SLOT_SAMPLES = 15 * 16000,
    FT8_MESSAGE_CHARS = 35,
    FT8_DISTANCE_UNKNOWN = 0xffff,
};

struct ft8_rx;
struct ft8_tx;
struct ft8_live_view;
struct ft8_ui_state;
struct ft8_qso;
struct ft8_radio_api;
struct cw_panel_api;

struct ft8_rx_result {
    char text[FT8_MESSAGE_CHARS];
    int8_t snr_db;
    uint16_t frequency_hz;
    int16_t offset_ms;
    uint8_t recipient; /* Offset of the addressed callsign plus one, or zero. */
    uint8_t sender; /* Offset of the transmitting callsign plus one, or zero. */
    uint16_t distance_km;
};

struct ft8_arm_api {
    uint32_t magic, version, work_bytes, stack_bytes;
    struct ft8_rx *(*open)(void *, size_t);
    void (*begin_slot)(struct ft8_rx *);
    size_t (*push_pcm)(struct ft8_rx *, const int16_t *, size_t);
    size_t (*push_frame)(struct ft8_rx *, const uint16_t *, size_t);
#ifdef FT8_RADIO
    size_t (*finish)(struct ft8_rx *, struct ft8_rx_result *, size_t, uint32_t);
#else
    size_t (*finish)(struct ft8_rx *, struct ft8_rx_result *, size_t);
#endif
    void (*set_locator)(struct ft8_rx *, uint32_t);
    /* Version 3: transmit side. */
    int (*encode)(const char *, uint8_t *);
    int (*encode_free)(const char *, uint8_t *);
    struct ft8_tx *(*tx_open)(void *, size_t, const uint8_t *, unsigned);
    size_t (*tx_next)(struct ft8_tx *, int16_t *, size_t);
    /* Version 4: page renderer. */
    void (*ui_draw)(void *, const struct ft8_live_view *, const struct ft8_ui_state *);
    int (*std_message)(unsigned, const struct ft8_ui_state *, uint32_t, char *);
    /* Version 6: ADIF formatting. The caller owns confirmed metadata and storage. */
    size_t (*adif_record)(char *, size_t, const struct ft8_qso *, const uint8_t *);
#ifdef FT8_RADIO
    const struct ft8_radio_api *radio;
    unsigned (*roll)(struct ft8_rx *, uint32_t);
    unsigned (*edit)(struct ft8_ui_state *, unsigned);
    uint32_t (*hit)(const struct ft8_ui_state *, uint32_t, uint32_t);
    unsigned (*page)(struct ft8_rx_result *, const struct ft8_rx_result *, unsigned,
                     const struct ft8_ui_state *, unsigned);
    void (*select_sender)(struct ft8_ui_state *, const struct ft8_rx_result *, uint32_t);
#ifdef FT8_CUSTOM_MODES
    const struct cw_panel_api *custom;
#endif
#endif
};

#endif
