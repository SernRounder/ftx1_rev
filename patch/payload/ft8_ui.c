/* WSJT-X style page renderer. Loaded with the tail core; draws through the
   stock text/fill primitives exactly like the Stage 1 code does. */
#include "ft8_live.h"
#include "ft8_adif.h"
#include "ft8_locator.h"
#include "ft8_rx.h"
#include "ft8_profile.h"
#include "ft8_tx.h"
#include "ft8_ui_layout.h"
#ifdef FT8_SD_PLUGIN
#include "ft8_plugin.h"
#endif
#include <ft8/message.h>

typedef unsigned u32;
typedef uint8_t u8;
typedef uint16_t u16;

#define STOCK_BASE 0x60400000u
#define STOCK(offset, type) ((type)(STOCK_BASE + (offset)))

typedef void (*text_fn)(void *, const u16 *, u32, u32, u32, u32, u32,
                        u32, u32, u32, u32, u32);
typedef void (*fill_fn)(void *, u32, u32, u32, u32, u32);
typedef u32 (*rtc_fn)(u8 *);

enum { PAGE_BG = 0x3186, PANE_BG = 0x18e3, HEADER_BG = 0x290a,
       ACCENT = 0x07ff, BUTTON_BG = 0x1082 };

struct rect { u16 x, y, w, h; };

#ifndef FT8_RADIO
static const struct rect band_pane = {60, 148, 486, 258};
static const struct rect activity_pane = {554, 148, 186, 76};
static const struct rect next_pane = {554, 230, 186, 178};
enum { ROW_FONT = 15, TX_FONT = 13 };
#endif
#ifndef FT8_RADIO
static const struct rect keyboard_area = {
    FT8_KEYBOARD_X, FT8_KEYBOARD_Y, FT8_KEYBOARD_W, FT8_KEYBOARD_H,
};
#endif

static void sized_text(void *frame, const char *label, u32 x, u32 y,
                       u32 bg, u32 align, u32 size)
{
    u16 glyphs[56];
    u32 n = 0;
    while (n < sizeof(glyphs) / sizeof(glyphs[0]) && label[n]) {
        glyphs[n] = (u8)label[n];
        n++;
    }
    STOCK(0x23d64, text_fn)(frame, glyphs, n, size, size, 0xffff, bg, x, y, align, 0, 1);
}

static void fill(void *frame, u32 x, u32 y, u32 w, u32 h, u32 color)
{
    STOCK(0x625a0, fill_fn)(frame, color, y, x, w, h);
}

static void pane(void *frame, const struct rect *area, const char *title)
{
    fill(frame, area->x, area->y, area->w, area->h, PANE_BG);
    fill(frame, area->x, area->y, area->w, 24, HEADER_BG);
    sized_text(frame, title, area->x + 8, area->y + 4, HEADER_BG, 1, 16);
}

static char *append(char *dest, const char *source)
{
    while (*source)
        *dest++ = *source++;
    return dest;
}

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
    return dest;
}

static char *append_report(char *dest, int db)
{
    *dest++ = db < 0 ? '-' : '+';
    if (db < 0)
        db = -db;
    *dest++ = '0' + db / 10;
    *dest++ = '0' + db % 10;
    return dest;
}


/* Keep the preview and transmission on the same template. Missing values
   appear in brackets, and the return value gates transmission. */
static int build_message(unsigned index, const struct ft8_ui_state *ui, uint32_t grid, char *out)
{
    char grid4[7];
    ft8_locator_format(grid, grid4);
    grid4[4] = 0;
    if (index == FT8_TX_FREE) {
        *append(out, ui->free_text[0] ? ui->free_text : "[EDIT]") = 0;
        return ui->free_text[0] != 0;
    }
    const int cq = index == FT8_TX_CQ;
    const char *to = cq ? "CQ" : ui->dx_call;
    const char *my = ui->my_call;
    int ready = to[0] && my[0];
    char *p = append(out, to[0] ? to : "[DX]");
    *p++ = ' ';
    p = append(p, my[0] ? my : "[MY]");
    *p++ = ' ';
    if (cq || index == 0) {
        ready &= grid4[0] != 0;
        p = append(p, grid4[0] ? grid4 : "[GRID]");
    } else if (index <= 2) {
        if (index == 2)
            *p++ = 'R';
        if (!ui->tx_report) {
            p = append(p, "[dB]");
            ready = 0;
        } else {
            p = append_report(p, ui->tx_report - FT8_REPORT_BIAS);
        }
    } else {
        p = append(p, index == 3 ? "RRR" : "73");
    }
    *p = 0;
    return ready;
}

int ft8_ui_std_message(unsigned index, const struct ft8_ui_state *ui, uint32_t grid, char *out)
{
    if (index >= FT8_TX_MESSAGES || !build_message(index, ui, grid, out))
        return 0;
    ftx_message_t message;
    if (index == FT8_TX_FREE)
        return ftx_message_encode_free(&message, out) == FTX_MESSAGE_RC_OK;
    if (ftx_message_encode(&message, NULL, out) != FTX_MESSAGE_RC_OK)
        return 0;
    const unsigned type = ftx_message_get_i3(&message);
    return type == 1 || type == 2;
}

#ifndef FT8_RADIO
static void draw_clock(void *frame)
{
    u8 bcd[7];
    char label[16] = "LOC --:--:--";
    if (STOCK(0x135d4, rtc_fn)(bcd) == 0 && (bcd[4] | bcd[5] | bcd[6]) != 0xff) {
        char *p = label + 4;
        for (unsigned i = 4; i < 7; ++i) {
            if (i > 4)
                *p++ = ':';
            *p++ = (char)('0' + (bcd[i] >> 4 & 0xf));
            *p++ = (char)('0' + (bcd[i] & 0xf));
        }
    }
    sized_text(frame, label, 554, 123, PAGE_BG, 4, 18);
}
#endif

#ifdef FT8_RADIO
__attribute__((noinline, section(".text.ft8_my_call")))
static int row_has_my_call(const struct ft8_rx_result *row, const struct ft8_ui_state *ui)
{
    for (unsigned i = 0; row->text[i]; ++i)
        if ((!i || row->text[i - 1] == ' ') &&
            ft8_radio_same_call(row->text, i + 1, ui->my_call))
            return 1;
    return 0;
}

#pragma clang section text=".ft8_clock_text" rodata=".ft8_clock_rodata"
static char *append_delta(char *p, int value)
{
    *p++ = value < 0 ? '-' : '+';
    unsigned magnitude = (value < 0 ? -value : value) + 50;
    p = append_u32(p, magnitude / 1000);
    *p++ = '.';
    *p++ = '0' + magnitude / 100 % 10;
    *p = 0;
    return p;
}

static const char *slot_label(unsigned slot) { return slot ? "15/45" : "00/30"; }

__attribute__((noinline, section(".text.ft8_draw_batch")))
static void draw_batch(void *frame, const struct ft8_live_view *view, unsigned slot)
{
    char text[16];
    *append_u32(append(text, "RX #"), view->slot_batch[slot]) = 0;
    sized_text(frame, text, slot * FT8_COL_W + 9, FT8_DOCK_Y + 23, PANE_BG, 1, 11);
}

static void draw_rx_row(void *frame, const struct ft8_rx_result *row, u32 x, u32 y,
                        uint32_t end_ms, u32 bg)
{
    char value[10];
    char message[28];
    unsigned n = 0;
    while (n < sizeof(message) - 1 && row->text[n]) {
        message[n] = row->text[n];
        ++n;
    }
    if (row->text[n])
        message[n - 1] = '~';
    message[n] = 0;
    *append_u32(value, row->frequency_hz) = 0;
    sized_text(frame, value, x + 390, y + 16, bg, 4, 12);
    sized_text(frame, message, x + 9, y, bg, 1, 14);
    char *end = value;
    if (row->distance_km == FT8_DISTANCE_UNKNOWN) {
        end = append(end, "--");
    } else {
        *end++ = '~';
        end = append_u32(end, row->distance_km);
    }
    *end = 0;
    sized_text(frame, value, x + 287, y + 16, bg, 4, 12);
    *append_report(value, row->snr_db) = 0;
    sized_text(frame, value, x + 326, y + 16, bg, 4, 12);
    unsigned slot;
    const int delta = ft8_radio_delta(ft8_radio_received_edge(row, end_ms), &slot);
    char *p = append(value, "D ");
    if (delta == 10000)
        *append(p, "--") = 0;
    else
        append_delta(p, delta);
    sized_text(frame, value, x + 9, y + 16, bg, 1, 12);
}
#pragma clang section text="" rodata=""
#endif

static void draw_band_activity(void *frame, const struct ft8_live_view *view
#ifdef FT8_RADIO
                               , const char *peer, const struct ft8_ui_state *ui
#endif
)
{
    static const char *const status[] = {
#ifdef FT8_RADIO
        "DECODER NOT LOADED", "RX PLATFORM NOT READY", "WAITING FOR AUDIO",
        "COLLECTING AUDIO", "NO MESSAGES THIS SCAN", "AUDIO GAP - RESUMING",
#else
        "DECODER NOT LOADED", "RX PLATFORM NOT READY", "WAITING FOR SLOT",
        "RECEIVING FT8 SLOT", "DECODE COMPLETE", "AUDIO GAP - WAITING FOR SLOT",
#endif
    };
#ifdef FT8_RADIO
    fill(frame, 0, FT8_DOCK_Y, FT8_SCREEN_W, FT8_SOFT_Y - FT8_DOCK_Y, PANE_BG);
    fill(frame, 0, FT8_DOCK_Y, FT8_SCREEN_W, 22, HEADER_BG);
    sized_text(frame, "FT8 DECODE", 9, FT8_DOCK_Y + 4, HEADER_BG, 1, 15);
    for (unsigned slot = 0; slot < 2; ++slot) {
        const unsigned x = slot * FT8_COL_W;
        char timing[19];
        char *p = append(timing, "AVG D ");
        if (view->slot_timed & (1u << slot))
            append_delta(p, (int16_t)view->slot_timing[slot]);
        else
            *append(p, "--") = 0;
        sized_text(frame, slot_label(slot), x + 140, FT8_DOCK_Y + 4, HEADER_BG, 1, 15);
        if (ft8_radio_tx_slot() == slot)
            sized_text(frame, "TX", x + 206, FT8_DOCK_Y + 4, HEADER_BG, 1, 15);
        sized_text(frame, timing, x + 390, FT8_DOCK_Y + 4, HEADER_BG, 4, 13);
        draw_batch(frame, view, slot);
        sized_text(frame, "km   dB    Hz", x + 390, FT8_DOCK_Y + 23, PANE_BG, 4, 11);
    }
#else
    char head[8];
    pane(frame, &band_pane, "BAND ACTIVITY");
    if (view->status == FT8_LIVE_RESULTS) {
        *append_u32(head, view->count) = 0;
        sized_text(frame, head, band_pane.x + band_pane.w - 12, band_pane.y + 4, HEADER_BG, 4, 16);
    }
#endif
#ifndef FT8_RADIO
    if (view->tx_count) { /* most recent confirmed transmission */
        sized_text(frame, "TX", 68, 178, ACCENT, 1, 14);
        sized_text(frame, view->tx[0], 92, 178, ACCENT, 1, 14);
    }
#endif
#ifdef FT8_RADIO
    if (!view->count) {
#else
    if (view->status != FT8_LIVE_RESULTS) {
#endif
        sized_text(frame, status[view->status], 28,
#ifdef FT8_RADIO
                   FT8_DOCK_ROW_Y,
#else
                   FT8_BAND_Y,
#endif
                   PANE_BG, 1, 16);
        return;
    }
#ifdef FT8_RADIO
    for (u32 i = 0; i < FT8_LIVE_ROWS; ++i) {
        if (i % FT8_SLOT_ROWS >= view->slot_count[i / FT8_SLOT_ROWS])
            continue;
#else
    for (u32 i = 0; i < view->count; ++i) {
#endif
        const struct ft8_rx_result *row = &view->rows[i];
#ifdef FT8_RADIO
        const u32 x = i / FT8_COL_ROWS * FT8_COL_W;
        const u32 y = FT8_DOCK_ROW_Y + i % FT8_COL_ROWS * FT8_DOCK_ROW_H;
        const u32 bg = row_has_my_call(row, ui) ? 0xa000 :
                       ft8_radio_same_call(row->text, row->sender, peer) ? HEADER_BG : PANE_BG;
        if (bg != PANE_BG)
            fill(frame, x + 1, y, FT8_COL_W - 2, FT8_DOCK_ROW_H, bg);
        draw_rx_row(frame, row, x, y, view->slot_end[i / FT8_SLOT_ROWS], bg);
#else
        const u32 y = FT8_BAND_Y + i * FT8_BAND_STEP;
        *append_u32(head, row->frequency_hz) = 0;
        sized_text(frame, head, 68, y, PANE_BG, 1, 15);
        const u32 message_x = 112;
        char message[27];
        u32 n = 0;
        while (n < sizeof(message) - 1 && row->text[n]) {
            message[n] = row->text[n];
            ++n;
        }
        message[n] = 0;
        sized_text(frame, message, message_x, y, PANE_BG, 1, ROW_FONT);
        if (row->distance_km != FT8_DISTANCE_UNKNOWN) {
            char km[12];
            char *p = km;
            *p++ = '~';
            p = append_u32(p, row->distance_km);
            p = append(p, " km");
            *p = 0;
            sized_text(frame, km, band_pane.x + band_pane.w - 10, y, PANE_BG, 4, TX_FONT);
        }
#endif
    }
}

#ifndef FT8_RADIO
static void draw_rx_frequency(void *frame, const struct ft8_live_view *view,
                              const struct ft8_ui_state *ui)
{
    pane(frame, &activity_pane, "RX FREQUENCY");
    if (ui->dx_call[0]) {
        sized_text(frame, ui->dx_call, 566, 180, PANE_BG, 1, 22);
        char line[20];
        char *p = append(line, "FREQ ");
        p = append_u32(p, ui->tx_offset_hz ? ui->tx_offset_hz
                                    : (view->count ? view->rows[0].frequency_hz : 1000));
        p = append(p, " Hz");
        *p = 0;
        sized_text(frame, line, 566, 204, PANE_BG, 1, 13);
    } else {
        sized_text(frame, "TAP A ROW", 566, 182, PANE_BG, 1, 16);
        sized_text(frame, "TO SELECT", 566, 200, PANE_BG, 1, 16);
    }
}
#endif

#ifndef FT8_RADIO
static void draw_next_tx(void *frame, const struct ft8_live_view *view,
                         const struct ft8_ui_state *ui, uint32_t grid)
{
    static const char *const names[] = {
        "Tx1", "Tx2", "Tx3", "Tx4", "Tx5", "Tx6", "FREE",
    };
    static const char *const phase[] = {
        "", " ARMED", " TX", " DRAIN", " STOPPING", " TX FAULT", " TX OFFLINE", " NO SLOT",
    };
    char message[FT8_MESSAGE_CHARS];

#ifdef FT8_RADIO
    struct ft8_full_view queue;
    const int full_auto = ft8_radio_full_view(&queue);
    pane(frame, &next_pane, full_auto ? "QUEUE" : "NEXT TX");
#else
    pane(frame, &next_pane, "NEXT TX");
#endif
    const char *label = phase[view->tx_status];
#ifdef FT8_RADIO
    static const char *const fault[] = {
        "FAULT", "LINK LOST", "KEY TIME", "KEY LOST", "AUDIO BUSY",
        "WORKER", "TX LIMIT", "NO SPI", "NO CREDIT", "DMA BUSY",
        "DMA PEND", "DMA ERR", "DMA DONE?", "PCM FULL", "M PTT", "M RF",
    };
    if ((view->tx_status == FT8_TX_FAULT ||
         (view->tx_status == FT8_TX_STOPPING && view->tx_fault)) &&
        view->tx_fault < sizeof(fault) / sizeof(fault[0]))
        label = fault[view->tx_fault];
    char waiting[] = "ARMED 00s";
    if (view->tx_status == FT8_TX_ARMED && view->tx_wait_s) {
        waiting[6] += view->tx_wait_s / 10;
        waiting[7] += view->tx_wait_s % 10;
        label = waiting;
    }
#endif
    sized_text(frame, label, next_pane.x + next_pane.w - 8, next_pane.y + 4, HEADER_BG, 4, 14);
#ifdef FT8_RADIO
    if (full_auto) {
#ifdef FT8_SD_PLUGIN
        char line[FT8_PLUGIN_LINE];
        static const struct ft8_plugin_host host = {append, append_u32, append_report};
        const ft8_plugin_queue_fn format = ft8_plugin_queue();
#else
        char line[40];
#endif
        char *p = append_u32(append(line, "QSO "), queue.done);
        p = append_u32(append(p, "  Q "), queue.count);
        *append_u32(append(p, "  CQ "), queue.cq_left) = 0;
        sized_text(frame, line, FT8_MSG_X + 8, FT8_MSG_Y, PANE_BG, 1, TX_FONT);
        for (unsigned i = 0; i < queue.count && i < FT8_FULL_PREVIEW; ++i) {
            const struct ft8_full_peer *peer = &queue.next[i];
#ifdef FT8_SD_PLUGIN
            if (format)
                format(&host, peer, line);
            else
                *append(line, peer->call) = 0;
#else
            p = append(append(line, peer->call), " ");
            p = append_report(p, peer->db);
            *p++ = ' ';
            p = append_u32(p, peer->hz);
            p = append(p, "Hz");
            if (peer->km != FT8_DISTANCE_UNKNOWN)
                p = append(append_u32(append(p, " "), peer->km), "km");
            *p = 0;
#endif
            sized_text(frame, line, FT8_MSG_X + 8, FT8_MSG_Y + (i + 1) * FT8_MSG_STEP,
                       PANE_BG, 1, TX_FONT);
        }
    } else
#endif
    for (unsigned i = 0; i < FT8_TX_MESSAGES; ++i) {
        char line[FT8_MESSAGE_CHARS + 6];
        char *p = append(line, names[i]);
        *p++ = ' ';
        build_message(i, ui, grid, message);
#ifdef FT8_RADIO
        const unsigned limit = 26;
#else
        const unsigned limit = 22;
#endif
        for (u32 n = 0; n < limit && message[n]; ++n)
            *p++ = message[n];
        *p = 0;
        sized_text(frame, line, FT8_MSG_X + 8, FT8_MSG_Y + i * FT8_MSG_STEP,
                   i == ui->selection ? ACCENT : PANE_BG, 1, TX_FONT);
    }
    const u32 armed = view->tx_status == FT8_TX_ARMED;
    fill(frame, FT8_TXNEXT_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H,
         armed ? ACCENT : BUTTON_BG);
    const char *next_label = "TX NEXT";
#ifdef FT8_RADIO
    if (full_auto)
        next_label = queue.checking ? "CHECK SD" : queue.current[0] ? queue.current : "CQ";
#endif
    sized_text(frame, next_label, FT8_TXNEXT_X + FT8_BUTTON_W / 2, FT8_BUTTON_Y + (FT8_BUTTON_H - TX_FONT) / 2,
               armed ? ACCENT : BUTTON_BG, 0, TX_FONT);
#ifndef FT8_RADIO
    fill(frame, FT8_STOP_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H, BUTTON_BG);
    sized_text(frame, "STOP", FT8_STOP_X + FT8_BUTTON_W / 2, FT8_BUTTON_Y + (FT8_BUTTON_H - TX_FONT) / 2,
               BUTTON_BG, 0, TX_FONT);
#endif
}

#endif

#ifdef FT8_RADIO
static const uint16_t config_events[] = {
    FT8_EVENT_MYFIELD, FT8_EVENT_DXFIELD, FT8_EVENT_GRID, FT8_EVENT_OFFSET,
    FT8_EVENT_TIME, FT8_EVENT_TX_SLOT, FT8_EVENT_AUTO, FT8_EVENT_FULL,
    FT8_EVENT_RETRIES, FT8_EVENT_CQS,
};

static void draw_config(void *frame, const struct ft8_live_view *view, const struct ft8_ui_state *ui)
{
    char grid[7], hz[8], offset[12], retries[4], rounds[4], text[FT8_MESSAGE_CHARS];
    ft8_locator_format(view->grid, grid);
    *append_u32(hz, ui->tx_offset_hz ? ui->tx_offset_hz : FT8_TX_DEFAULT_HZ) = 0;
    append_delta(offset, ft8_radio_time_offset());
    *append_u32(retries, ft8_auto_options.retries) = 0;
    const unsigned cq_rounds = ft8_auto_options.cq_rounds;
    *append_u32(rounds, cq_rounds) = 0;
    const char *const labels[] = {
        "MY CALL", "DX CALL", "GRID", "TX Hz", "TIME OFFSET", "TX SLOT", "AUTO QSO", "FULL AUTO",
        "QSO RETRIES", "CQ ROUNDS",
    };
    const int full = ft8_radio_full_view(NULL);
    const char *const values[] = {
        ui->my_call, ui->dx_call, grid, hz, ft8_radio_offset_set() ? offset : "SET TO ENABLE TX",
        slot_label(ft8_radio_tx_slot()), ft8_auto_options.enabled ? "ON" : "OFF", full ? "END" : "START",
        retries, cq_rounds == FT8_CQ_UNLIMITED ? "-1 (CONTINUOUS)" : rounds,
    };
    sized_text(frame, "FT8 CONFIG", 20, 18, PAGE_BG, 1, 21);
#ifdef FT8_VFP
    extern unsigned ft8_fft_backend(void);
    const unsigned backend = ft8_fft_backend();
    sized_text(frame, backend == 2 ? "VFP FFT" : backend ? "VFP UNAVAILABLE" : "FFT WAIT",
               450, 20, PAGE_BG, 1, 14);
#endif
    sized_text(frame, "STATION AND TIMING", 20, 68, PAGE_BG, 1, 16);
    sized_text(frame, "RECENT QSOs (UTC)", FT8_MSG_X, 68, PAGE_BG, 1, 16);
    for (unsigned i = 0; i < sizeof(config_events) / sizeof(config_events[0]); ++i) {
        const unsigned y = FT8_CONFIG_Y + i * FT8_CONFIG_STEP;
        fill(frame, FT8_CONFIG_X, y, FT8_CONFIG_W, FT8_CONFIG_STEP - 3, BUTTON_BG);
        sized_text(frame, labels[i], 30, y + 7, BUTTON_BG, 1, 15);
        sized_text(frame, values[i][0] ? values[i] : "--", 359, y + 7, BUTTON_BG, 4, 15);
    }
    struct ft8_recent_qso recent[FT8_RECENT_QSOS];
    ft8_radio_recent_qsos(recent);
    fill(frame, FT8_MSG_X, FT8_MSG_Y, FT8_MSG_W, FT8_RECENT_QSOS * FT8_MSG_STEP - 4, PANE_BG);
    for (unsigned i = 0; i < FT8_RECENT_QSOS && recent[i].call[0]; ++i) {
        const unsigned y = FT8_MSG_Y + i * FT8_MSG_STEP;
        sized_text(frame, recent[i].call, FT8_MSG_X + 10, y + 12, PANE_BG, 1, 15);
        sized_text(frame, recent[i].utc, FT8_MSG_X + FT8_MSG_W - 10, y + 12, PANE_BG, 4, 15);
    }
    if (!recent[0].call[0])
        sized_text(frame, "NO LOGGED QSOs", FT8_MSG_X + 10, FT8_MSG_Y + 12, PANE_BG, 1, 15);
    const unsigned pick_x = FT8_MSG_X + FT8_FREE_W;
    fill(frame, FT8_MSG_X, FT8_QSO_TOOLS_Y, FT8_FREE_W - 4, FT8_MSG_STEP - 4, BUTTON_BG);
    sized_text(frame, "FREE", FT8_MSG_X + 10, FT8_QSO_TOOLS_Y + 12, BUTTON_BG, 1, 14);
    fill(frame, pick_x, FT8_QSO_TOOLS_Y, FT8_MSG_W - FT8_FREE_W, FT8_MSG_STEP - 4, BUTTON_BG);
    char key[] = "TX1";
    key[2] += ui->selection;
    sized_text(frame, ui->selection == FT8_TX_FREE ? "TX" : key, pick_x + 10,
               FT8_QSO_TOOLS_Y + 12, BUTTON_BG, 1, 14);
    build_message(ui->selection, ui, view->grid, text);
    text[25] = 0;
    sized_text(frame, text, pick_x + 54, FT8_QSO_TOOLS_Y + 12, BUTTON_BG, 1, 13);
    fill(frame, FT8_TXNEXT_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H, BUTTON_BG);
    char *p = append(text, "SET ");
    if (view->tx_pwr) {
        p = append_u32(p, view->tx_pwr / 10);
        *p++ = '.';
        *p++ = '0' + view->tx_pwr % 10;
        *p++ = 'W';
    } else
        p = append(p, "--");
    *p = 0;
    sized_text(frame, text, 20, 443, PAGE_BG, 1, 15);
    fill(frame, FT8_MSG_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H, BUTTON_BG);
    sized_text(frame, ft8_radio_gps_clock() ? "GPS TIME" : "DATE/TIME",
               FT8_MSG_X + FT8_BUTTON_W / 2, 442, BUTTON_BG, 0, 16);
    sized_text(frame, "TX NEXT", 588, 442, BUTTON_BG, 0, 16);
    fill(frame, FT8_STOP_KEY_X, FT8_SOFT_Y, FT8_SCREEN_W - FT8_STOP_KEY_X, FT8_SOFT_H, 0x8000);
    sized_text(frame, "STOP", 733, 442, 0x8000, 0, 16);
}

static void draw_dock(void *frame, const struct ft8_live_view *view, const struct ft8_ui_state *ui)
{
    struct ft8_full_view full;
    const int running = ft8_radio_full_view(&full);
    const unsigned automatic = ft8_radio_api.auto_state();
    const char *peer = running ? full.current : ui->dx_call;
    draw_band_activity(frame, view, peer, ui);
    PROFILE_MARK(PROF_DRAW, (view->rx_list >> 2) << 8 |
                 view->slot_count[1] << 4 | view->slot_count[0]);

    static const char *const phases[] = {
        "RX", "ARMED", "TX", "TX DRAIN", "STOPPING", "TX FAULT", "TX OFFLINE", "NO SLOT",
    };
    const unsigned status = view->tx_status;
    char line[56];
    char *p = append(line, running ? "FULL AUTO  " : automatic ? "AUTO QSO  " : "MANUAL  ");
    p = append(p, !ft8_radio_offset_set() ? "SET TIME OFFSET" :
                     status == FT8_TX_IDLE && automatic == 3 ? "WAIT REPLY" : phases[status]);
    if (status == FT8_TX_ARMED)
        p = append(append_u32(append(p, " "), view->tx_wait_s), "s");
    if (*peer)
        p = append(append(p, "  "), peer);
    *p = 0;
    fill(frame, 0, FT8_SESSION_Y, FT8_SCREEN_W, FT8_SOFT_Y - FT8_SESSION_Y, HEADER_BG);
    sized_text(frame, line, 9, FT8_SESSION_Y + 3, HEADER_BG, 1, 15);
    if (running) {
        p = append_u32(append(line, "QSO "), full.done);
        p = append_u32(append(p, "  Q "), full.count);
        p = append(p, "  CQ ");
        *(full.cq_left == FT8_CQ_UNLIMITED ? append(p, "INF") : append_u32(p, full.cq_left)) = 0;
        sized_text(frame, line, 790, FT8_SESSION_Y + 4, HEADER_BG, 4, 14);
    }

    const char *message = view->tx_current;
    const char *prefix = status == FT8_TX_ARMED ? "PEND " : status == FT8_TX_STOPPING ? "CANCEL " : "TX ";
    char pending[FT8_MESSAGE_CHARS];
    if (!*message && view->tx_count) {
        prefix = "SENT ";
        message = view->tx[0];
    } else if (!*message && !running) {
        prefix = "NEXT ";
        build_message(ui->selection, ui, view->grid, pending);
        message = pending;
    }
    if (*message) {
        char *end = append(append(line, prefix), message);
        *end = 0;
        if (running && end > line + 32) {
            line[31] = '~';
            line[32] = 0;
        }
        sized_text(frame, line, 9, FT8_SESSION_Y + 28, HEADER_BG, 1, 12);
    }
    if (running) {
        const struct ft8_full_peer *next = &full.next[0];
        p = append(line, full.checking ? "CHECK SD" : full.count ? "NEXT " : full.cq_left ? "NEXT CQ" : "QUEUE EMPTY");
        if (full.count) {
            p = append_report(append(append(p, next->call), " "), next->db);
            p = append(append_u32(append(p, " "), next->hz), "Hz");
        }
        *p = 0;
        sized_text(frame, line, 790, FT8_SESSION_Y + 28, HEADER_BG, 4, 12);
    }

    static const char *const order[] = {"RARE", "dB", "km"};
    const unsigned max = view->slot_total[0] > view->slot_total[1] ? view->slot_total[0] : view->slot_total[1];
    const unsigned pages = (max + FT8_SLOT_ROWS - 1) / FT8_SLOT_ROWS;
    *append_u32(append(append_u32(append(line, "PAGE "), (view->rx_list >> 2) + 1), "/"),
                pages ? pages : 1) = 0;
    const char *const keys[] = {"BACK", running ? "END AUTO" : "TX NEXT", order[view->rx_list & 3],
                                line, "SETUP", "STOP"};
    for (unsigned i = 0; i < 6; ++i) {
        const unsigned x = i * FT8_SOFT_W;
        const unsigned w = i == 5 ? FT8_SCREEN_W - x : FT8_SOFT_W;
        const unsigned bg = i == 5 ? 0x8000 : (i & 1) ? PAGE_BG : BUTTON_BG;
        fill(frame, x, FT8_SOFT_Y, w, FT8_SOFT_H, bg);
        sized_text(frame, keys[i], x + w / 2, FT8_SOFT_Y + 22, bg, 0, 16);
    }
}

int ft8_radio_worked(const char *, size_t);

static unsigned token_length(const char *token)
{
    unsigned n = 0;
    while (token[n] && token[n] != ' ')
        ++n;
    return n;
}

static unsigned prefix(const struct ft8_rx_result *row)
{
    if (!row->sender)
        return 0;
    const char *call = row->text + row->sender - 1;
    unsigned value = 0;
    for (unsigned i = 0; i < 4 && call[i] && call[i] != ' '; ++i) {
        value = value * 256 + (unsigned char)call[i];
        if ((unsigned)(call[i] - '0') <= 9)
            return value;
    }
    return 0;
}

unsigned ft8_ui_page(struct ft8_rx_result *out, const struct ft8_rx_result *rows,
                     unsigned count, const struct ft8_ui_state *ui, unsigned page)
{
    const unsigned order = __atomic_load_n(&ui->list, __ATOMIC_ACQUIRE) & 3;
    const unsigned first = page * FT8_SLOT_ROWS;
    if (first >= count)
        return 0;
    uint32_t ranks[FT8_LIST_RESULTS];
    uint8_t indices[FT8_LIST_RESULTS];
    unsigned prefixes[FT8_LIST_RESULTS];
    for (unsigned i = 0; i < count; ++i)
        prefixes[i] = prefix(&rows[i]);
    for (unsigned i = 0; i < count; ++i) {
        const struct ft8_rx_result *row = &rows[i];
        unsigned group = !row_has_my_call(row, ui);
        if (group && row->sender) {
            const char *call = row->text + row->sender - 1;
            if (ft8_radio_worked(call, token_length(call)))
                group = 2;
        }
        const unsigned signal = (unsigned)(row->snr_db + FT8_REPORT_BIAS);
        const unsigned distance = row->distance_km == FT8_DISTANCE_UNKNOWN ? 0 : row->distance_km;
        unsigned score = signal;
        if (order == FT8_SORT_DISTANCE) {
            score |= distance << 7;
        } else if (order == FT8_SORT_RARE) {
            unsigned common = count + 1;
            if (prefixes[i]) {
                common = 0;
                for (unsigned j = 0; j < count; ++j)
                    common += prefixes[j] == prefixes[i];
            }
            score |= distance << 7 | (FT8_LIST_RESULTS + 1 - common) << 22;
        }
        ranks[i] = ((2 - group) << 28) | score;
        unsigned j = i;
        while (j && ranks[indices[j - 1]] < ranks[i]) {
            indices[j] = indices[j - 1];
            --j;
        }
        indices[j] = i;
    }
    unsigned shown = count - first;
    if (shown > FT8_SLOT_ROWS)
        shown = FT8_SLOT_ROWS;
    for (unsigned i = 0; i < shown; ++i)
        out[i] = rows[indices[first + i]];
    return shown;
}

void ft8_ui_select_sender(struct ft8_ui_state *ui, const struct ft8_rx_result *result, uint32_t row)
{
    if (!result->sender)
        return;
    const char *call = result->text + result->sender - 1;
    size_t length = 0, same = 0;
    while (call[length] && call[length] != ' ') {
        if (length == sizeof(ui->dx_call) - 1 || call[length] == '<')
            return;
        same += ui->my_call[length] == call[length];
        ++length;
    }
    if (!length || (same == length && !ui->my_call[length]))
        return;
    for (size_t i = 0; i < length; ++i)
        ui->dx_call[i] = call[i];
    ui->dx_call[length] = 0;
    ui->dx_row = row + 1;
    ui->tx_report = result->snr_db + FT8_REPORT_BIAS;
    if (ui->selection == FT8_TX_CQ)
        ui->selection = 0;
}

static int hit_zone(uint32_t x, uint32_t y, uint32_t zx, uint32_t zy, uint32_t zw, uint32_t zh)
{
    return x - zx < zw && y - zy < zh;
}

/* Map a touch to an FT8_EVENT_* id, or 0 for a passive page area. */
uint32_t ft8_ui_hit(const struct ft8_ui_state *ui, uint32_t x, uint32_t y)
{
    if (ui->keyboard) {
        if (hit_zone(x, y, FT8_BACK_X, FT8_BACK_Y, FT8_BACK_W, FT8_BACK_H))
            return FT8_EVENT_BACK;
        const uint16_t *key = ft8_stock_key_table(ui->keyboard_layout);
        for (unsigned i = 0; i < FT8_STOCK_KEYS; ++i, key += 5)
            if ((unsigned)(key[4] - 0x1200) < 256 &&
                hit_zone(x, y, key[0], key[1], key[2], key[3]))
                return FT8_EVENT_KEY + (key[4] & 255);
        return 0;
    }
    if (hit_zone(x, y, FT8_STOP_KEY_X, FT8_SOFT_Y, FT8_SCREEN_W - FT8_STOP_KEY_X, FT8_SOFT_H))
        return FT8_EVENT_STOP;
    if (!ui->settings) {
        if (x < FT8_SCREEN_W && y >= FT8_SOFT_Y && y < FT8_SCREEN_H) {
            static const uint16_t keys[] = {FT8_EVENT_BACK, FT8_EVENT_TXNEXT, FT8_EVENT_SORT,
                                           FT8_EVENT_PAGE, FT8_EVENT_SETUP};
            const unsigned key = x / FT8_SOFT_W;
            return key == 1 && ft8_radio_full_view(NULL) ? FT8_EVENT_FULL : keys[key];
        }
        if (x < FT8_SCREEN_W && y - FT8_DOCK_ROW_Y < FT8_COL_ROWS * FT8_DOCK_ROW_H)
            return FT8_EVENT_ROW + x / FT8_COL_W * FT8_COL_ROWS + (y - FT8_DOCK_ROW_Y) / FT8_DOCK_ROW_H;
        return 0;
    }
    if (hit_zone(x, y, FT8_BACK_X, FT8_BACK_Y, FT8_BACK_W, FT8_BACK_H))
        return FT8_EVENT_BACK;
    if (hit_zone(x, y, FT8_MSG_X, FT8_QSO_TOOLS_Y, FT8_MSG_W, FT8_MSG_STEP - 4))
        return ft8_radio_full_view(NULL) ? 0 :
               x < FT8_MSG_X + FT8_FREE_W ? FT8_EVENT_MSG + FT8_TX_FREE : FT8_EVENT_TX_PICK;
    if (hit_zone(x, y, FT8_TXNEXT_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H))
        return FT8_EVENT_TXNEXT;
    if (hit_zone(x, y, FT8_MSG_X, FT8_BUTTON_Y, FT8_BUTTON_W, FT8_BUTTON_H))
        return ft8_radio_gps_clock() ? 0 : FT8_EVENT_CLOCK;
    if (hit_zone(x, y, FT8_CONFIG_X, FT8_CONFIG_Y, FT8_CONFIG_W,
                 FT8_CONFIG_STEP * sizeof(config_events) / sizeof(config_events[0])))
        return config_events[(y - FT8_CONFIG_Y) / FT8_CONFIG_STEP];
    return 0;
}

unsigned ft8_ui_edit(struct ft8_ui_state *ui, unsigned key)
{
    unsigned cursor = ui->typing_cursor, length = ui->typing_length;
    if (key == 0x85 && ui->keyboard == FT8_KEYBOARD_TIME)
        return ft8_radio_set_offset(ui->typing, length);
    if (key == 0x85 && ui->keyboard == FT8_KEYBOARD_CLOCK)
        return ft8_radio_set_clock(ui->typing, length);
    if (key == 0x85 && (ui->keyboard == FT8_KEYBOARD_OFFSET || ui->keyboard >= FT8_KEYBOARD_RETRIES)) {
        if (ui->keyboard == FT8_KEYBOARD_CQS && length == 2 &&
            ui->typing[0] == '-' && ui->typing[1] == '1') {
            __atomic_store_n(&ft8_auto_options.cq_rounds, FT8_CQ_UNLIMITED, __ATOMIC_RELEASE);
            return 1;
        }
        unsigned hz = 0;
        for (unsigned i = 0; i < length; ++i) {
            const unsigned digit = (unsigned)ui->typing[i] - '0';
            if (digit > 9 || i == 4)
                return 0;
            hz = hz * 10 + digit;
        }
        if (ui->keyboard >= FT8_KEYBOARD_RETRIES) {
            if (!length || hz > 99 || (!hz && ui->keyboard == FT8_KEYBOARD_CQS))
                return 0;
            uint8_t *value = ui->keyboard == FT8_KEYBOARD_CQS ?
                &ft8_auto_options.cq_rounds : &ft8_auto_options.retries;
            __atomic_store_n(value, hz, __ATOMIC_RELEASE);
            return 1;
        }
        if (length && (hz < FT8_TX_MIN_HZ || hz > FT8_TX_MAX_HZ))
            return 0;
        ui->tx_offset_hz = hz;
        return 1;
    }
    if (key == 0x81 && ui->keyboard_layout < 2)
        ui->keyboard_layout ^= 1;
    else if (key == 0x83)
        ui->keyboard_layout = 2;
    else if (key == 0x82 || key == 0x8a)
        ui->keyboard_layout = 0;
    else if (key == 0x86 && cursor)
        --cursor;
    else if (key == 0x87 && cursor < length)
        ++cursor;
    else if (key == 8 && cursor) {
        --cursor;
        --length;
        for (unsigned i = cursor; i <= length; ++i)
            ui->typing[i] = ui->typing[i + 1];
    } else if (key - ' ' <= '~' - ' ' && length < 13 + (ui->keyboard == FT8_KEYBOARD_CLOCK)) {
        for (unsigned i = ++length; i > cursor; --i)
            ui->typing[i] = ui->typing[i - 1];
        ui->typing[cursor++] = key - 'a' <= 'z' - 'a' ? key - 32 : key;
        ui->typing[length] = 0;
    } else
        return 0;
    ui->typing_cursor = cursor;
    ui->typing_length = length;
    return 1;
}
#endif

static void draw_keyboard(void *frame, const struct ft8_ui_state *ui)
{
    static const char *const target[] = { "", "MY CALL", "DX CALL", "FREE TEXT", "MY GRID",
                                         "TX Hz", "TIME OFFSET", "YYYYMMDDHHMMSS",
                                         "QSO RETRIES 0-99", "CQ ROUNDS 1-99 / -1" };
#ifdef FT8_RADIO
    /* The stock renderer takes its layout rectangles from the UI task's
       scratch table. Restore both scratch fields before returning to stock. */
    uint16_t saved[FT8_STOCK_KEYS * 5];
    uint16_t *const table = (void *)0x607c1f8cu;
    uint8_t *const layout = (void *)0x607c07a1u;
    const unsigned previous = *layout;
    typedef void (*copy_fn)(void *, const void *, unsigned);
    const copy_fn copy = STOCK(0xbdc20, copy_fn);
    copy(saved, table, sizeof(saved));
    copy(table, ft8_stock_key_table(ui->keyboard_layout), sizeof(saved));
    STOCK(0x29614, void (*)(unsigned, unsigned, unsigned))(ui->keyboard_layout, 0, 0);
    copy(table, saved, sizeof(saved));
    *layout = previous;
    char line[37];
    char *p = append(append(line, target[ui->keyboard]), "  ");
    for (unsigned i = 0; i <= ui->typing_length; ++i) {
        if (i == ui->typing_cursor)
            *p++ = '|';
        if (ui->typing[i])
            *p++ = ui->typing[i];
    }
    *p = 0;
    sized_text(frame, line, 20, 23, PAGE_BG, 1, 19);
#else
    fill(frame, keyboard_area.x, keyboard_area.y, keyboard_area.w, keyboard_area.h,
         HEADER_BG);
    char line[30];
    char *p = append(line, target[ui->keyboard]);
    p = append(p, ": ");
    p = append(p, ui->typing);
    if (!ui->typing_length)
        *p++ = '_';
    *p = 0;
    sized_text(frame, line, keyboard_area.x + 8, keyboard_area.y + 14, HEADER_BG, 1, ROW_FONT);
    for (u32 r = 0; r < FT8_KEY_ROWS; ++r) {
        for (u32 c = 0; c < FT8_KEY_COLS; ++c) {
            const char key = ft8_keyboard_keys[r * FT8_KEY_COLS + c];
            const char *label;
            char single[5];
            if (!key)
                continue;
            if (key == FT8_KEY_BACKSPACE)
                label = "BKSP";
            else if (key == FT8_KEY_ENTER)
                label = "ENT";
            else if (key == ' ')
                label = "SPC";
            else {
                single[0] = key;
                single[1] = 0;
                label = single;
            }
            const u32 x = FT8_KEY_X0 + c * FT8_KEY_W;
            const u32 y = FT8_KEY_Y0 + r * FT8_KEY_H;
            fill(frame, x, y, FT8_KEY_W - 2, FT8_KEY_H - 2, PANE_BG);
            sized_text(frame, label, x + FT8_KEY_W / 2 - 1, y + (FT8_KEY_H - TX_FONT) / 2,
                       PANE_BG, 0, TX_FONT);
        }
    }
#endif
}

void ft8_ui_draw(void *frame, const struct ft8_live_view *view,
                 const struct ft8_ui_state *ui)
{
#ifdef FT8_RADIO
    if (!ui->settings && !ui->keyboard) {
        draw_dock(frame, view, ui);
        return;
    }
    fill(frame, 0, 0, FT8_SCREEN_W, FT8_SCREEN_H, PAGE_BG);
    fill(frame, FT8_BACK_X, FT8_BACK_Y, FT8_BACK_W, FT8_BACK_H, 0x1f);
    sized_text(frame, "BACK", FT8_BACK_X + FT8_BACK_W / 2, 20, 0x1f, 0, 18);
    if (ui->keyboard)
        draw_keyboard(frame, ui);
    else
        draw_config(frame, view, ui);
#else
    char grid[7];
    char label[20] = "MY GRID ";
    ft8_locator_format(view->grid, grid);
    append(label + 8, grid[0] ? grid : "--");
    sized_text(frame, label, 328, 123, PAGE_BG, 1, 18);
    draw_clock(frame);
    if (ui->keyboard)
        draw_keyboard(frame, ui);
    else
        draw_band_activity(frame, view);
    draw_rx_frequency(frame, view, ui);
    draw_next_tx(frame, view, ui, view->grid);
#endif
}
