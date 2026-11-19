#ifndef FTX1_FT8_UI_LAYOUT_H
#define FTX1_FT8_UI_LAYOUT_H

/* Shared drawing and touch geometry for the native overlay and lab page. */

enum {
    FT8_KEY_COLS = 10, FT8_KEY_ROWS = 4, FT8_TX_FREE = 6,
    FT8_KEY_BACKSPACE = '<', FT8_KEY_ENTER = '>',

    FT8_EVENT_ROW = 0x1200,     /* + band-activity row index */
    FT8_EVENT_MSG = 0x1210,     /* + Tx selection index (0..6) */
    FT8_EVENT_TXNEXT = 0x1220,
    FT8_EVENT_STOP = 0x1221,
    FT8_EVENT_MYFIELD = 0x1222, /* MY GRID label doubles as the MY CALL editor */
    FT8_EVENT_DXFIELD = 0x1223, /* RX FREQUENCY pane body */
    FT8_EVENT_GRID = 0x1224,
    FT8_EVENT_OFFSET = 0x1225,
    FT8_EVENT_SORT = 0x1226,
    FT8_EVENT_PAGE = 0x1227,
    FT8_EVENT_TIME = 0x1228,
    FT8_EVENT_AUTO = 0x1229,
    FT8_EVENT_FULL = 0x122a,
    FT8_EVENT_TX_SLOT = 0x122b,
    FT8_EVENT_SETUP = 0x122c,
    FT8_EVENT_TX_PICK = 0x122d,
    FT8_EVENT_CLOCK = 0x122e,
    FT8_EVENT_RETRIES = 0x1240,
    FT8_EVENT_CQS = 0x1241,
    FT8_EVENT_BACK = 0x1134,
#ifdef FT8_RADIO
    FT8_EVENT_KEY = 0x1300,     /* stock keyboard code's low byte */
#else
    FT8_EVENT_KEY = 0x1230,     /* + keyboard key index (0..39) */
#endif

#ifdef FT8_RADIO
    FT8_SCREEN_W = 800, FT8_SCREEN_H = 480,
    FT8_DOCK_Y = 235, FT8_SOFT_Y = 420, FT8_SOFT_H = 60,
    FT8_SOFT_W = 133, FT8_STOP_KEY_X = 5 * FT8_SOFT_W,
    FT8_COL_W = 400, FT8_COL_ROWS = 3, FT8_DOCK_ROW_Y = 270,
    FT8_DOCK_ROW_H = 32, FT8_SESSION_Y = 368,
    FT8_BACK_X = 672, FT8_BACK_Y = 8, FT8_BACK_W = 112, FT8_BACK_H = 40,
    FT8_CONFIG_X = 20, FT8_CONFIG_Y = 96, FT8_CONFIG_W = 350, FT8_CONFIG_STEP = 32,
    FT8_MSG_X = 396, FT8_MSG_Y = FT8_CONFIG_Y, FT8_MSG_STEP = 44, FT8_MSG_W = 384,
    FT8_FREE_W = 70, FT8_QSO_TOOLS_Y = FT8_MSG_Y + FT8_TX_FREE * FT8_MSG_STEP,
    FT8_TXNEXT_X = 525, FT8_BUTTON_Y = 429, FT8_BUTTON_W = 126, FT8_BUTTON_H = 42,
#else
    FT8_KEY_W = 46, FT8_KEY_H = 34, FT8_KEY_X0 = 68, FT8_KEY_Y0 = 200,
    FT8_BAND_X = 60, FT8_BAND_Y = 200, FT8_BAND_STEP = 25, FT8_BAND_W = 486,
    FT8_MSG_X = 554, FT8_MSG_Y = 262, FT8_MSG_STEP = 17, FT8_MSG_W = 186,
    FT8_TXNEXT_X = 560, FT8_BUTTON_Y = 384, FT8_BUTTON_W = 82, FT8_BUTTON_H = 20,
    FT8_STOP_X = 650,
    FT8_MYFIELD_X = 300, FT8_MYFIELD_Y = 118, FT8_MYFIELD_W = 120, FT8_MYFIELD_H = 18,
    FT8_DXFIELD_X = 554, FT8_DXFIELD_Y = 148, FT8_DXFIELD_W = 186, FT8_DXFIELD_H = 76,
    FT8_KEYBOARD_X = 60, FT8_KEYBOARD_Y = 148, FT8_KEYBOARD_W = 486, FT8_KEYBOARD_H = 258,
#endif
};

#ifdef FT8_RADIO
enum { FT8_STOCK_KEYS = 49 };
static inline const uint16_t *ft8_stock_key_table(unsigned layout)
{
    return (const uint16_t *)(0x605373a0u + layout * 500);
}
#else
/* 40 keys: 26 letters, 10 digits, space, backspace, enter, unused. */
static const char ft8_keyboard_keys[FT8_KEY_ROWS * FT8_KEY_COLS] = {
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J',
    'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T',
    'U', 'V', 'W', 'X', 'Y', 'Z', '0', '1', '2', '3',
    '4', '5', '6', '7', '8', '9', ' ', FT8_KEY_BACKSPACE, FT8_KEY_ENTER, 0,
};
#endif

#endif
