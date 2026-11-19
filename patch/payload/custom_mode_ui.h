#ifndef FTX1_CUSTOM_MODE_UI_H
#define FTX1_CUSTOM_MODE_UI_H

#include <stdint.h>
#include "ft8_tx_link.h"

#define STOCK_UI ((const volatile uint8_t *)0x60935bb4u)

static inline int swr_scan_active(void)
{
    return STOCK_UI[FT8_LINK_SWR_SLOT] == FT8_LINK_SWR_EXIT;
}

static inline int custom_mode_visible(void)
{
    const unsigned type = STOCK_UI[0];
    return *(const volatile uint8_t *)0x6093994du <= 0x1fu && !swr_scan_active() &&
           (type == 0 || type == 0x20 || type == 0x60 || type == 0x62);
}

/* 1 represents stock ownership. Local ownership carries the selected revision. */
static inline unsigned custom_mode_back_route(unsigned *owner, unsigned subtype, unsigned state)
{
    const unsigned route = *owner ? *owner : state ? state : 1;
    *owner = subtype ? route : 0;
    return route == 1 ? 0 : route;
}

static inline void custom_mode_restore_stock(void)
{
    typedef void (*draw_fn)(const volatile uint8_t *, const volatile uint8_t *, unsigned, unsigned);
    typedef void (*list_fn)(const volatile uint8_t *, const volatile uint8_t *, unsigned);
    ((draw_fn)0x604410d0u)(STOCK_UI, STOCK_UI, 1, *(const volatile uint8_t *)0x60939947u);
    if (STOCK_UI[0] == 0x62)
        ((list_fn)0x6042bb54u)(STOCK_UI, STOCK_UI, 1);
}

struct custom_mode_selection {
    unsigned state, closing, retry_at;
};

/* Retry the local close at most four times while MAIN reports the old
   revision. A bounded retry cannot persist across later revision wraps. */
static inline void custom_mode_close(struct custom_mode_selection *selection)
{
    selection->closing = selection->state | (4u << 8);
    selection->retry_at = ((unsigned (*)(void))0x6041669cu)();
}

static inline int custom_mode_update(struct custom_mode_selection *selection, unsigned state)
{
    if (selection->state == state)
        return 0;
    selection->state = state;
    selection->closing = 0;
    return 1;
}

static inline void custom_mode_retry_close(struct custom_mode_selection *selection)
{
    if (selection->closing < 0x100)
        return;
    const unsigned now = ((unsigned (*)(void))0x6041669cu)();
    if ((int32_t)(now - selection->retry_at) < 0)
        return;
    const uint8_t packet[FT8_LINK_BYTES] = {
        FT8_LINK_COMMAND, FT8_LINK_SUBCOMMAND, 'F', 'T', '8',
        FT8_LINK_CLOSE_MODE, selection->closing, 0, 0,
    };
    selection->closing -= 0x100;
    selection->retry_at = now + 250000;
    ((void (*)(const uint8_t *, unsigned))0x60414a1cu)(packet, sizeof(packet));
}

#endif
