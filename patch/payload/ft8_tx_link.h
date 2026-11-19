#ifndef FTX1_FT8_TX_LINK_H
#define FTX1_FT8_TX_LINK_H

enum {
    FT8_LINK_COMMAND = 0xe8,
    FT8_LINK_SUBCOMMAND = 0xf8,
    FT8_LINK_BYTES = 9,
    FT8_LINK_START = 1,
    FT8_LINK_STOP = 0,
    FT8_LINK_STATUS_OFFSET = 9,
    FT8_LINK_POWER_OFFSET = 32,
    FT8_LINK_MODE_FLAGS_OFFSET = FT8_LINK_POWER_OFFSET + 1,
    FT8_LINK_SPA = 1,
    FT8_LINK_MODE_TAG = 0x80,
    FT8_LINK_MODE_REVISION = 0x78,
    FT8_LINK_MODE_STEP = 8,
    FT8_LINK_MODE_SHIFT = 1,
    FT8_LINK_MODE_MASK = 3 << FT8_LINK_MODE_SHIFT,
    FT8_LINK_MODE_NONE = 0,
    FT8_LINK_MODE_FT8 = 1 << FT8_LINK_MODE_SHIFT,
    FT8_LINK_MODE_CW = 2 << FT8_LINK_MODE_SHIFT,
    FT8_LINK_CLOSE_MODE = 2,
    FT8_LINK_SWR_SLOT = 0x6c,
    FT8_LINK_SWR_EXIT = 0xed,
    FT8_LINK_STATUS_MASK = 0xc0,
    FT8_LINK_STATUS_TAG = 0x80,
    FT8_LINK_DIAG_PTT = 0x40,
    FT8_LINK_DIAG_RF = 0xc0,
    FT8_LINK_HEARTBEAT = 0x20,
    FT8_LINK_TOKEN_MASK = 7,
    FT8_LINK_IDLE = 0,
    FT8_LINK_KEYED = 1,
    FT8_LINK_PENDING = 2,
    FT8_LINK_BUSY = 3,
};

static inline int ft8_link_status_frame(unsigned type, unsigned length)
{
    return (type == 0x20 && length == 0x13c) ||
           (type == 0x60 && length == 0x14d) ||
           (type == 0x62 && length == 0x23b);
}

static inline void ft8_link_restore_status(unsigned char *packet, unsigned length)
{
    packet[length - 1] -= packet[FT8_LINK_STATUS_OFFSET] +
                          packet[FT8_LINK_POWER_OFFSET] + packet[FT8_LINK_MODE_FLAGS_OFFSET];
    packet[FT8_LINK_STATUS_OFFSET] = packet[FT8_LINK_POWER_OFFSET] =
        packet[FT8_LINK_MODE_FLAGS_OFFSET] = 0;
}

#endif
