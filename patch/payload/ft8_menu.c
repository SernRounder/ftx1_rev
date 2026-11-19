#include <stdint.h>
#include "custom_mode_ui.h"
#ifdef FT8_LIVE
#include "ft8_live.h"
#include "ft8_locator.h"
#include "ft8_ui_layout.h"
#endif
#ifdef FT8_CUSTOM_MODES
#include "cw_panel.h"
#endif

#define STOCK_BASE 0x60400000u
#define STOCK(offset, type) ((type)(STOCK_BASE + (offset)))

typedef unsigned u32;
typedef uint8_t u8;
typedef uint16_t u16;

void ft8_touch(u32 pressed, u32 event); /* ft8_touch.S trampoline */

typedef void (*void_fn)(void);
typedef void *(*frame_fn)(u32);
typedef void (*fill_fn)(void *, u32, u32, u32, u32, u32);
typedef void (*text_fn)(void *, const u16 *, u32, u32, u32, u32, u32,
                        u32, u32, u32, u32, u32);

enum {
    EVENT_BACK = 0x1134,
    EVENT_LOCAL_NOOP = 0x1135,
    DRAW_NONE = 0,
    DRAW_FT8_DOCK = 1,
    DRAW_FT8_FULL = 2,
    DRAW_CW_DOCK = 3,
    SCREEN_W = 800,
    SCREEN_H = 480,
    CW_DOCK_H = 42,
    CW_DOCK_Y = 420 - CW_DOCK_H,
};

#define LAYER (*(const volatile u32 *)0x607c4bb0u)

#ifndef FT8_RADIO
struct rect {
    u16 x, y, w, h;
};
static const struct rect back = {580, 113, 110, 34};
#ifdef FT8_LIVE
static const struct rect page = {50, 108, 700, 304};
#else
static const struct rect page = {101, 108, 599, 304};
#endif
#endif

/* The linker includes this initialized state in the image, inside the loaded hole. */
static volatile u32 requested __attribute__((section(".data.ft8"))) = 0;
static volatile u32 pending_back __attribute__((section(".data.ft8"))) = 0;
static u32 displayed __attribute__((section(".data.ft8"))) = DRAW_NONE;
static u32 repaint __attribute__((section(".data.ft8"))) = 1;
#ifdef FT8_RADIO
static u32 swallow_back_release __attribute__((section(".data.ft8"))) = 0;
static u32 pending_touch_close __attribute__((section(".data.ft8"))) = 0;
static u32 back_owner __attribute__((section(".data.ft8"))) = 0;
static struct custom_mode_selection selection __attribute__((section(".data.ft8"))) = {0};
#endif
static const void *last_frame __attribute__((section(".data.ft8"))) = 0;

#ifdef FT8_LIVE
#ifdef FT8_RADIO
static struct ft8_live_view *live_view __attribute__((section(".data.ft8"))) = NULL;
#define SCREEN_VIEW live_view
#else
static struct ft8_live_view live_view __attribute__((section(".data.ft8"))) = {0};
#define SCREEN_VIEW (&live_view)
#endif
static u32 live_revision[4] __attribute__((section(".data.ft8"))) = {0, 0, 0, 0};
#endif

#ifdef FT8_RX_PROBE
static volatile u32 rx_frames __attribute__((section(".data.ft8"))) = 0;
static volatile u32 rx_count __attribute__((section(".data.ft8"))) = 0;
static u32 drawn_frames __attribute__((section(".data.ft8"))) = 0;

#define TAIL_PROBE (*(const volatile u32 *)0x606c2fc0u)

/* Called at the stock DMA completion path. Count headers only, without consuming
   stock messages, changing the producer flags or copying from the DMA buffer. */
u32 ft8_audio_probe(const volatile u16 *frame)
{
    typedef u32 (*set_frame_fn)(const volatile u16 *);
    const u32 metadata = STOCK(0x450b4, set_frame_fn)(frame);
    if (requested) {
        rx_count = frame[0];
        rx_frames++;
    }
    return metadata;
}
#endif

#ifdef FT8_RADIO
static int ft8_touch_eligible(void)
{
    return requested && custom_mode_visible();
}

/* The stock touch task calls this for every calibrated coordinate. */
u32 ft8_panel_hit(u32 x, u32 y, u16 *detail)
{
    if (ft8_touch_eligible()) {
        u32 event = ft8_live_hit(x, y);
        if (!event)
            event = EVENT_LOCAL_NOOP;
        *detail = 0;
        return event;
    }
#ifdef FT8_CUSTOM_MODES
    return cw_panel_hit(x, y, detail);
#else
    return STOCK(0xc61e0, u32 (*)(u32, u32, u16 *))(x, y, detail);
#endif
}
#endif

int ft8_local_touch(u32 pressed, u32 event)
{
#ifdef FT8_RADIO
    if (event == EVENT_BACK && !pressed && swallow_back_release) {
        swallow_back_release = 0;
        return 1;
    }
    if (requested) {
        if (!ft8_touch_eligible())
            return 0;
        if (event - 0x1200u < 0x200) {
            ft8_live_touch(pressed, event, SCREEN_VIEW);
            return 1;
        }
        if (event == EVENT_BACK) {
            if (pressed && !ft8_live_back()) {
                requested = 0;
                __atomic_store_n(&pending_touch_close, 1u, __ATOMIC_RELEASE);
                swallow_back_release = 1;
            }
            return 1;
        }
        if (event == EVENT_LOCAL_NOOP)
            return 1;
        return 0;
    }
#ifdef FT8_CUSTOM_MODES
    const int consumed = cw_local_touch(pressed, event);
    if (consumed && pressed)
        __atomic_store_n(&pending_touch_close, 1u, __ATOMIC_RELEASE);
    return consumed;
#else
    return 0;
#endif
#else
    if (!requested || !custom_mode_visible())
        return 0;
#ifdef FT8_LIVE
    if (event - 0x1200u < 0x100) {
        ft8_live_touch(pressed, event, SCREEN_VIEW);
        return 1;
    }
#endif
    if (event == EVENT_BACK || event == EVENT_LOCAL_NOOP) {
        if (pressed && event == EVENT_BACK) {
#ifdef FT8_LIVE
            if (ft8_live_back())
                return 1;
#endif
            requested = 0;
        }
        return 1;
    }
    return 0;
#endif
}

void ft8_key_send_hook(const u8 *pkt, u32 len)
{
    if (len == 5 && pkt[0] == 0xe0 && pkt[2] == 0x03 && pkt[3] == 0x0a) {
#ifdef FT8_RADIO
        const int ft8_ok = ft8_touch_eligible();
#ifdef FT8_CUSTOM_MODES
        const int cw_ok = !ft8_ok && cw_visible();
#else
        const int cw_ok = 0;
#endif
        const unsigned route = custom_mode_back_route(&back_owner, pkt[1],
                                                     ft8_ok || cw_ok ? selection.state : 0);
        if (route) {
            if (pkt[1] == 0)
                __atomic_store_n(&pending_back, route, __ATOMIC_RELEASE);
            return;
        }
#else
        if (requested && custom_mode_visible()) {
            if (pkt[1] == 0)
                __atomic_store_n(&pending_back, 1u, __ATOMIC_RELEASE);
            return;
        }
#endif
    }
    STOCK(0x14a1c, void (*)(const u8 *, u32))(pkt, len);
}

static void sized_text(void *frame, const char *label, u32 x, u32 y,
                       u32 bg, u32 align, u32 size)
{
#ifdef FT8_LIVE
    u16 glyphs[48];
#else
    u16 glyphs[32];
#endif
    u32 n = 0;
    while (n < sizeof(glyphs) / sizeof(glyphs[0]) && label[n]) {
        glyphs[n] = (u8)label[n];
        n++;
    }
    STOCK(0x23d64, text_fn)(frame, glyphs, n, size, size, 0xffff, bg, x, y, align, 0, 1);
}

static void text(void *frame, const char *label, u32 x, u32 y, u32 bg, u32 align)
{
    sized_text(frame, label, x, y, bg, align, 25);
}

#ifndef FT8_RADIO
static void fill(void *frame, const struct rect *r, u32 color)
{
    STOCK(0x625a0, fill_fn)(frame, color, r->y, r->x, r->w, r->h);
}
#endif

#ifdef FT8_RX_PROBE
static char *append_u32(char *dest, u32 value)
{
    char reverse[10];
    unsigned n = 0;
    do {
        reverse[n++] = (char)('0' + value % 10);
        value /= 10;
    } while (value);
    while (n)
        *dest++ = reverse[--n];
    *dest = 0;
    return dest;
}
#endif

static void draw_page(void *frame)
{
#ifdef FT8_RADIO
    /* The frequency readout and meters on the main layer remain visible. */
    STOCK(0xbdd61, void (*)(void *, u32))(frame, FT8_SCREEN_W * FT8_SCREEN_H * sizeof(u16));
    if (live_view) {
        ft8_live_draw(frame, live_view);
    } else {
        STOCK(0x625a0, fill_fn)(frame, 0x3186, FT8_SOFT_Y, 0, FT8_SCREEN_W, FT8_SOFT_H);
        text(frame, "FT8 OFFLINE", 12, FT8_SOFT_Y + 12, 0x3186, 1);
    }
#else
    fill(frame, &page, 0x3186);
    fill(frame, &back, 0x1f);
    text(frame, "FT8 RX", page.x + 20, page.y + 11, 0x3186, 1);
    text(frame, "BACK", back.x + back.w / 2, back.y + (back.h - 24) / 2, 0x1f, 0);
#ifdef FT8_LIVE
    if (!ft8_live_draw(frame, SCREEN_VIEW))
        text(frame, "DECODER NOT LOADED", page.x + 20, page.y + 68, 0x3186, 1);
#else
    text(frame, "RECEIVE SCREEN", page.x + 20, page.y + 68, 0x3186, 1);
#ifdef FT8_RX_PROBE
    char frames[22] = "FRAMES: ";
    char count[24] = "HEADER COUNT: ";
    drawn_frames = rx_frames;
    append_u32(frames + 8, drawn_frames);
    append_u32(count + 14, rx_count);
    text(frame, frames, page.x + 20, page.y + 105, 0x3186, 1);
    text(frame, count, page.x + 20, page.y + 142, 0x3186, 1);
    text(frame, TAIL_PROBE == 0x50385446u ? "TAIL: PRESENT" : "TAIL: MISSING",
         page.x + 20, page.y + 179, 0x3186, 1);
#else
    text(frame, "DECODER OFFLINE", page.x + 20, page.y + 107, 0x3186, 1);
#endif
#endif
#endif
}

static void clear_overlay_buffers(u32 y, u32 h)
{
    typedef void (*zero_fn)(void *, u32);
    for (u32 idx = 3; idx <= 4; ++idx) {
        u16 *const buf = STOCK(0x448b8, frame_fn)(idx);
        if (buf)
            STOCK(0xbdd61, zero_fn)(buf + y * SCREEN_W, h * SCREEN_W * sizeof(u16));
    }
}

/* Apply MAIN's selection against the newly committed stock UI state. */
void ft8_ui_worker(void)
{
    STOCK(0x41ff8, void_fn)();
#ifdef FT8_RADIO
    const unsigned state = ft8_radio_mode();
    const unsigned mode = state & FT8_LINK_MODE_MASK;
    const unsigned back_req = __atomic_exchange_n(&pending_back, 0u, __ATOMIC_ACQ_REL);
    const unsigned touch_close = __atomic_exchange_n(&pending_touch_close, 0u, __ATOMIC_ACQ_REL);
    const int swr = swr_scan_active();
    /* UART readback can lead the UI queue when leaving SWR. Apply the new
       active selection once the stock EXIT key has left the bottom bar. */
    if ((!swr || mode == FT8_LINK_MODE_NONE) && custom_mode_update(&selection, state)) {
        requested = !swr && mode == FT8_LINK_MODE_FT8;
#ifdef FT8_CUSTOM_MODES
        if (!requested)
            ft8_live_set_active(0);
        cw_set_active(!swr && mode == FT8_LINK_MODE_CW);
#endif
        repaint = 1;
    } else if (touch_close) {
        custom_mode_close(&selection);
    } else if (back_req && back_req == selection.state && !swr) {
        if (requested) {
            if (!ft8_live_back()) {
                requested = 0;
                custom_mode_close(&selection);
            }
            repaint = 1;
        }
#ifdef FT8_CUSTOM_MODES
        else if (mode == FT8_LINK_MODE_CW && !selection.closing) {
            cw_set_active(0);
            custom_mode_close(&selection);
        }
#endif
    }
    if (swr)
        requested = 0;
    const u32 ft8_on = requested;
    ft8_live_set_active(ft8_on != 0);
    live_view = ft8_on ? ft8_live_screen() : 0;
#ifdef FT8_CUSTOM_MODES
    cw_sync(ft8_on != 0 || swr);
#endif
    custom_mode_retry_close(&selection);
#else
    const unsigned back_req = __atomic_exchange_n(&pending_back, 0u, __ATOMIC_ACQ_REL);
    if (back_req && requested) {
#ifdef FT8_LIVE
        if (!ft8_live_back())
#endif
            requested = 0;
        repaint = 1;
    }
#ifdef FT8_LIVE
    ft8_live_set_active(requested != 0);
#endif
#endif
}

/* Hooked at 0x043AE8 inside the UI loop immediately before 0x604B0BAC -> 0x60460B44.
   All FT8/CW_DEC drawing and wipe recovery happen here before VDC5 buffer swap. */
void ft8_pre_swap(void)
{
    const int swr = swr_scan_active();
    const int clear = !swr && custom_mode_visible();
    if (swr || clear) {
        u32 next = DRAW_NONE;
        if (requested && clear) {
#ifdef FT8_RADIO
            next = ft8_live_fullscreen() ? DRAW_FT8_FULL : DRAW_FT8_DOCK;
#else
            next = DRAW_FT8_FULL;
#endif
        }
#ifdef FT8_CUSTOM_MODES
        else if (!requested && cw_visible()) {
            next = DRAW_CW_DOCK;
        }
#endif
        const u32 previous = displayed;
        if ((previous == DRAW_FT8_FULL || previous == DRAW_FT8_DOCK) &&
            next != DRAW_FT8_FULL && next != DRAW_FT8_DOCK) {
            clear_overlay_buffers(0, SCREEN_H);
            displayed = DRAW_NONE;
            last_frame = 0;
        } else if (previous == DRAW_CW_DOCK && next != DRAW_CW_DOCK) {
            clear_overlay_buffers(CW_DOCK_Y, CW_DOCK_H);
            displayed = DRAW_NONE;
            last_frame = 0;
        }
        if (previous && !displayed && !swr &&
            next != DRAW_FT8_FULL && next != DRAW_FT8_DOCK)
            custom_mode_restore_stock();

        if (next == DRAW_FT8_FULL || next == DRAW_FT8_DOCK) {
            u16 *const frame = STOCK(0x448b8, frame_fn)(LAYER);
            if (frame) {
                int ready = 1;
#ifdef FT8_LIVE
                u32 revision[4];
#ifdef FT8_RADIO
                if (!live_view)
                    repaint = 1;
                else
#endif
                if (!ft8_live_snapshot(SCREEN_VIEW, revision))
                    ready = 0;
                else
                    for (u32 i = 0; i < 4; ++i)
                        if (revision[i] != live_revision[i]) {
                            live_revision[i] = revision[i];
                            repaint = 1;
                        }
#endif
#ifdef FT8_RX_PROBE
                if (rx_frames - drawn_frames >= 8)
                    repaint = 1;
#endif
                const u32 sentinel_y =
#ifdef FT8_RADIO
                    479;
#else
                    page.y + page.h - 1;
#endif
                if (ready && (repaint || displayed != next || frame != last_frame ||
                              frame[sentinel_y * SCREEN_W] == 0)) {
                    draw_page(frame);
                    displayed = next;
                    last_frame = frame;
                    repaint = 0;
                }
            }
        }
#ifdef FT8_CUSTOM_MODES
        else if (next == DRAW_CW_DOCK) {
            u16 *const frame = STOCK(0x448b8, frame_fn)(LAYER);
            if (frame) {
                const int wiped = frame[(CW_DOCK_Y + CW_DOCK_H - 1) * SCREEN_W] == 0;
                if (cw_draw(frame, displayed != DRAW_CW_DOCK || frame != last_frame ||
                            wiped || repaint)) {
                    displayed = DRAW_CW_DOCK;
                    last_frame = frame;
                    repaint = 0;
                }
            }
        }
#endif
    } else {
        /* Stock popups own Layer 5 while visible. Repaint when they dismiss. */
        repaint = 1;
    }
    ((void (*)(void))0x604b0bad)();
}

#ifndef FT8_HOOK_VECTORS
/* Hook entries are branched to by patched stock code with no in-image
   references; this kept table roots them against --gc-sections. */
const void *const ft8_hook_roots[] __attribute__((section(".ft8_hooks"), used)) = {
    (const void *)ft8_touch,     (const void *)ft8_ui_worker,
    (const void *)ft8_pre_swap,  (const void *)ft8_key_send_hook,
#ifdef FT8_RX_PROBE
    (const void *)ft8_audio_probe,
#endif
#ifdef FT8_LIVE
    (const void *)ft8_live_capture,
#endif
};
#endif
