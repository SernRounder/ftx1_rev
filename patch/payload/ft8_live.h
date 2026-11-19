#ifndef FTX1_FT8_LIVE_H
#define FTX1_FT8_LIVE_H

#include "ft8_arm_api.h"

enum {
#ifdef FT8_RADIO
       FT8_PERIOD_MS = 15000, FT8_CAPTURE_END_MS = 13450, FT8_DECODE_END_MS = 14500,
       FT8_MIN_RX_BLOCKS = 79,
       FT8_SLOT_ROWS = 3, FT8_LIVE_ROWS = 2 * FT8_SLOT_ROWS,
#else
       FT8_LIVE_ROWS = 8,
#endif
       FT8_TX_ROWS = 4, FT8_LIST_RESULTS = 24,
       FT8_SORT_RARE = 0, FT8_SORT_DB = 1, FT8_SORT_DISTANCE = 2, FT8_SORT_COUNT = 3 };
enum ft8_live_status {
    FT8_LIVE_UNLOADED, FT8_LIVE_UNBOUND, FT8_LIVE_WAIT_SLOT,
    FT8_LIVE_RECEIVING, FT8_LIVE_RESULTS, FT8_LIVE_GAP,
};
enum ft8_live_tx_status {
    FT8_TX_IDLE = 0, FT8_TX_ARMED, FT8_TX_SENDING, FT8_TX_DRAINING,
    FT8_TX_STOPPING, FT8_TX_FAULT, FT8_TX_OFFLINE,
    FT8_TX_NO_SLOT,
};

/* Supplied by the platform before the menu opens. start must validate TX
   ownership, mode and the PCM route,
   and enforce the lease in a context independent of this worker. A failed
   start must leave the transmitter off. All callbacks are nonblocking.
   now_ms must also be safe to call from the RX capture interrupt.
   submit takes ownership of a copy. drained returns 1, 0 (pending), or -1.
   stop cancels queued PCM and returns 1 only after this lease is unkeyed. */
struct ft8_tx_io {
    uint32_t (*now_ms)(void);
    int (*start)(uint32_t lease_ms);
    int (*submit)(const int16_t *pcm, size_t frames);
    int (*drained)(void);
    int (*stop)(void);
};

struct ft8_live_api {
    uint32_t magic, version, work_bytes, stack_bytes;
    int (*bind)(void *, size_t);
    uint32_t (*next_sequence)(void);
    int (*sync)(uint32_t, uint32_t);
    int (*poll)(void);
    int (*set_position)(int32_t, int32_t);
    int (*set_grid)(const char *);
    int (*record_tx)(const char *);
    int (*tx_arm)(const char *, uint32_t);
    int (*attach_tx)(const struct ft8_tx_io *);
#ifdef FT8_RADIO
    int (*sync_time)(uint32_t);
    int (*unbind)(void);
    int (*synced)(void);
    uint32_t (*coordinates)(int32_t, int32_t);
    uint32_t (*grid)(void);
#endif
};

#ifdef FT8_RADIO
enum ft8_radio_fault {
    FT8_RADIO_NO_FAULT, FT8_RADIO_LINK_LOST, FT8_RADIO_KEY_TIMEOUT,
    FT8_RADIO_KEY_LOST, FT8_RADIO_AUDIO_BUSY, FT8_RADIO_WORKER_TIMEOUT,
    FT8_RADIO_LEASE_EXPIRED, FT8_RADIO_SPI_MISSING, FT8_RADIO_NO_CREDIT,
    FT8_RADIO_DMA_BUSY, FT8_RADIO_DMA_PENDING, FT8_RADIO_DMA_ERROR,
    FT8_RADIO_DMA_NO_DONE, FT8_RADIO_PCM_FULL,
    FT8_RADIO_MAIN_PTT, FT8_RADIO_MAIN_RF,
};

struct ft8_radio_api {
    int (*menu)(int);
    uintptr_t (*source)(uintptr_t);
    void (*done)(void);
    void (*report)(uint8_t *, size_t);
    int (*tx_available)(void);
    unsigned (*tx_seconds)(void);
    unsigned (*tx_fault)(void);
    unsigned (*tx_power)(void);
    void (*station_call)(char *);
    uint32_t (*station_grid)(void);
    void (*qso_event)(const char *, uint32_t, unsigned, unsigned);
    int (*scan_due)(uint32_t, unsigned samples, unsigned sealed);
    unsigned (*auto_state)(void);
    int (*auto_event)(unsigned, const struct ft8_rx_result *, const struct ft8_ui_state *, uint32_t);
    int (*auto_key)(uint32_t);
    unsigned (*full_revision)(void);
    void (*toggle_tx_slot)(void);
    uint32_t (*rx_timing)(const struct ft8_rx_result *, size_t, uint32_t);
};

extern const struct ft8_radio_api ft8_radio_api;
unsigned ft8_radio_received_edge(const struct ft8_rx_result *, uint32_t);
int ft8_radio_delta(uint32_t, unsigned *);
int ft8_radio_time_offset(void);
int ft8_radio_offset_set(void);
unsigned ft8_radio_rx_phase(uint32_t end);
int ft8_radio_decode_expired(void);
unsigned ft8_radio_tx_slot(void);
int ft8_radio_set_offset(const char *, unsigned);
int ft8_radio_gps_clock(void);
void ft8_radio_clock_text(char out[15]);
int ft8_radio_set_clock(const char *, unsigned);
#endif

struct ft8_live_view {
    uint32_t epoch, status, count, grid, tx_count, tx_status;
#ifdef FT8_RADIO
    /* The VM uses rx_scans to verify recovery after an audio overrun. */
    uint32_t rx_total, rx_list, rx_scans;
    char tx_current[FT8_MESSAGE_CHARS];
#endif
    char tx[FT8_TX_ROWS][FT8_MESSAGE_CHARS];
    struct ft8_rx_result rows[FT8_LIVE_ROWS];
#ifdef FT8_RADIO
    uint32_t tx_wait_s, tx_fault;
    uint32_t tx_pwr; /* 0.1 W from the MAIN status report; 0 = unknown */
    uint32_t slot_end[2];
    uint16_t slot_batch[2];
    uint16_t slot_timing[2];
    uint8_t slot_total[2], slot_count[2], slot_timed;
#endif
};

/* Interactive settings owned by the workspace; drawn by the tail renderer. */
enum { FT8_TX_MESSAGES = 7, FT8_TX_CQ = 5, FT8_REPORT_BIAS = 64 };
enum { FT8_AUTO_STOP, FT8_AUTO_TOGGLE, FT8_AUTO_SELECT, FT8_AUTO_FULL };
#define FT8_TX_AUTO_FLAG UINT32_C(0x80000000)
enum { FT8_KEYBOARD_CLOSED = 0, FT8_KEYBOARD_MY, FT8_KEYBOARD_DX, FT8_KEYBOARD_FREE,
       FT8_KEYBOARD_GRID, FT8_KEYBOARD_OFFSET, FT8_KEYBOARD_TIME, FT8_KEYBOARD_CLOCK,
       FT8_KEYBOARD_RETRIES, FT8_KEYBOARD_CQS };
struct ft8_ui_state {
    char my_call[14], dx_call[14], free_text[14];
    uint32_t selection; /* 0..6, index into FT8_TX_MESSAGES */
    uint32_t keyboard;  /* ft8_keyboard target */
    uint32_t typing_length;
    char typing[15];
#ifdef FT8_RADIO
    uint8_t typing_cursor, keyboard_layout;
    uint8_t settings;
    uint32_t list;
#endif
    uint8_t tx_report; /* Estimated report plus FT8_REPORT_BIAS, zero if unavailable. */
    uint32_t tx_offset_hz;
    uint32_t dx_row; /* 1 + selected band-activity row, 0 = none */
};

void ft8_live_set_active(int active);
uint32_t ft8_live_capture(const volatile uint16_t *frame);
/* On success, revision changes when the active session or displayed data changes. */
int ft8_live_snapshot(struct ft8_live_view *out, uint32_t revision[4]);
#ifdef FT8_RADIO
struct ft8_live_view *ft8_live_screen(void);
#endif
/* In-page interaction, computed by ft8_menu.c geometry dispatch. */
void ft8_live_touch(uint32_t pressed, uint32_t event, const struct ft8_live_view *view);
uint32_t ft8_live_hit(uint32_t x, uint32_t y);
int ft8_live_back(void);
int ft8_live_draw(void *frame, const struct ft8_live_view *view);
#ifdef FT8_RADIO
int ft8_live_fullscreen(void);
unsigned ft8_radio_mode(void);
#endif

/* Tail renderer entry points (ft8_ui.c, exported through ft8_arm_api v4). */
void ft8_ui_draw(void *frame, const struct ft8_live_view *view,
                 const struct ft8_ui_state *ui);
int ft8_ui_std_message(unsigned index, const struct ft8_ui_state *ui,
                       uint32_t grid, char *out);
#ifdef FT8_RADIO
enum { FT8_FULL_PREVIEW = 6, FT8_FULL_CQS = 3, FT8_CQ_UNLIMITED = 255 };
struct ft8_auto_options {
    uint8_t enabled, retries, cq_rounds;
};
extern struct ft8_auto_options ft8_auto_options;
struct ft8_full_peer {
    char call[14];
    uint16_t hz, km;
    int8_t db;
    uint8_t step;
};
struct ft8_full_view {
    unsigned count, done, cq_left, checking;
    char current[14];
    struct ft8_full_peer next[FT8_FULL_PREVIEW];
};
int ft8_radio_full_view(struct ft8_full_view *);
int ft8_radio_same_call(const char *text, unsigned offset, const char *call);
unsigned ft8_ui_edit(struct ft8_ui_state *ui, unsigned key);
uint32_t ft8_ui_hit(const struct ft8_ui_state *ui, uint32_t x, uint32_t y);
unsigned ft8_ui_page(struct ft8_rx_result *, const struct ft8_rx_result *, unsigned,
                     const struct ft8_ui_state *, unsigned page);
void ft8_ui_select_sender(struct ft8_ui_state *, const struct ft8_rx_result *, uint32_t);
#endif

#endif
