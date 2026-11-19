/* RX651 MAIN V01-13 adapter. All RF switching remains in the stock TX loop. */
#include "ft8_tx_link.h"

typedef unsigned char u8;
typedef unsigned int u32;

#define B8(address) (*(volatile u8 *)(address))
#define B16(address) (*(volatile unsigned short *)(address))
#define B32(address) (*(volatile u32 *)(address))

enum {
    FT8_TICKS_PER_MS = 10,
    FT8_MAX_TICKS = 13500 * FT8_TICKS_PER_MS,
    FT8_KEY_WAIT_TICKS = 280 * FT8_TICKS_PER_MS,
    /* Stock CAT mode IDs MD02 (USB) and MD0C (DATA-U). */
    FT8_MAIN_USB = 1,
    FT8_MAIN_DATA_U = 9,
    TX_CONTROL = 0x801324,
    TX_FREQUENCY = 4,
    VOICE_PTT = 0x8013c5 - TX_CONTROL,
    VOICE_BASE = 0x21b20,
    PCM_SLOT = 0,
    VOICE_ACTIVE = 0x21d3d - VOICE_BASE,
    PCM_PLAY = 0x21d82 - VOICE_BASE,
    SWR_SCAN_OPEN = 0x84c6,
};

/* Zeroed by the stock startup table, beyond initialized data at 0x3f86c. */
struct session {
    volatile u32 ticks;
    u32 started, frequency;
    u8 phase, link, mode, ui_state;
};
enum { FT8_PHASE_IDLE, FT8_PHASE_ACTIVE, FT8_PHASE_STOPPING };
_Static_assert(__builtin_offsetof(struct session, phase) == 12, "RX hook offset");
_Static_assert(__builtin_offsetof(struct session, ui_state) == 15, "UI state offset");
_Static_assert(sizeof(struct session) == 16, "MAIN startup zero range");
static struct session *const tx = (void *)0x3f870;

extern void stock_timer_tick(void);
extern void stock_beep(u32);
extern void stock_playback_jobs(void);
extern void stock_playback_other_jobs(void);
extern void stock_e8(const u8 *);
extern void stock_swr_prepare(void);
extern u8 stock_tx_allowed(u32);
extern u8 stock_select_vfo(unsigned);
extern u8 stock_vfo_mode(unsigned);
extern unsigned ft8_main_rf_state(void);

__attribute__((noinline)) unsigned ft8_main_tx_mode(void)
{
    const unsigned mode = stock_vfo_mode(stock_select_vfo(2));
    return (mode & ~(FT8_MAIN_DATA_U ^ FT8_MAIN_USB)) == FT8_MAIN_USB ? mode : 0;
}

static __attribute__((noinline)) volatile u8 *voice_state(void)
{
    return (volatile u8 *)(B32(0x83b2c8u) + VOICE_BASE);
}

/* Keep one RX base register for the frequency and PTT register offsets. */
static inline volatile u8 *tx_control(void)
{
    volatile u8 *base = (void *)TX_CONTROL;
    __asm__("" : "+r"(base));
    return base;
}

static __attribute__((noinline)) void set_voice(volatile u8 *voice, u8 value)
{
    voice[PCM_SLOT] = value;
    voice[PCM_PLAY] = value;
    voice[VOICE_ACTIVE] = value;
}

static __attribute__((noinline)) void unkey(void)
{
    tx->phase = FT8_PHASE_STOPPING;
    B8(TX_CONTROL + VOICE_PTT) = 0;
    set_voice(voice_state(), 0);
}

void ft8_main_timer(void)
{
    stock_timer_tick();
    ++tx->ticks;
}

void ft8_main_service(void)
{
    const unsigned phase = tx->phase;
    if (phase != FT8_PHASE_ACTIVE) {
        stock_playback_jobs();
        if (phase == FT8_PHASE_STOPPING && ft8_main_rf_state() == FT8_LINK_IDLE)
            tx->phase = FT8_PHASE_IDLE;
        return;
    }
    /* The voice-file end GPIO must not release PTT owned by native PCM. */
    stock_playback_other_jobs();
    const u32 elapsed = tx->ticks - tx->started;
    const unsigned state = ft8_main_rf_state();
    volatile u8 *const control = tx_control();
    if (B8(SWR_SCAN_OPEN) || state == FT8_LINK_BUSY ||
        elapsed >= (state == FT8_LINK_KEYED ? FT8_MAX_TICKS : FT8_KEY_WAIT_TICKS) ||
        !control[VOICE_PTT] || !voice_state()[PCM_PLAY] ||
        B32(control + TX_FREQUENCY) != tx->frequency || ft8_main_tx_mode() != tx->mode)
        unkey();
}

static __attribute__((section(".c2_text"), noinline)) void key(u8 token)
{
    tx->link = token << 2;
    if (B8(SWR_SCAN_OPEN) != 0)
        return;
    volatile u8 *const control = tx_control();
    const u32 frequency = B32(control + TX_FREQUENCY);
    volatile u8 *const voice = voice_state();
    if (ft8_main_rf_state() != FT8_LINK_IDLE)
        return;
    const unsigned mode = ft8_main_tx_mode();
    tx->mode = mode;
    if (!mode ||
        control[VOICE_PTT] || B16(voice + PCM_PLAY) || voice[VOICE_ACTIVE] || voice[PCM_SLOT] ||
        !stock_tx_allowed(frequency))
        return;
    tx->started = tx->ticks;
    tx->frequency = frequency;
    tx->phase = FT8_PHASE_ACTIVE;
    set_voice(voice, 1);
    control[VOICE_PTT] = 1;
}

static __attribute__((section(".c2_text"), noinline)) void set_ui_mode(u8 mode)
{
    const unsigned previous = tx->ui_state;
    if (mode != FT8_LINK_MODE_FT8 && (previous & FT8_LINK_MODE_MASK) == FT8_LINK_MODE_FT8 &&
        tx->phase == FT8_PHASE_ACTIVE)
        unkey();
    const u8 revision = (previous + FT8_LINK_MODE_STEP) & FT8_LINK_MODE_REVISION;
    tx->ui_state = FT8_LINK_MODE_TAG | revision | mode;
}

__attribute__((section(".c2_text"))) void ft8_main_swr_open_hook(void)
{
    stock_swr_prepare();
    set_ui_mode(FT8_LINK_MODE_NONE);
}

__attribute__((section(".c2_text"))) void ft8_main_command(const u8 *packet)
{
    struct __attribute__((packed)) signature { u32 value; };
    const struct signature *words = (const void *)packet;
    const u32 fields = words[1].value;
    const u32 expected = FT8_LINK_COMMAND | (FT8_LINK_SUBCOMMAND << 8) | ('F' << 16) | ('T' << 24);
    if (words[0].value != expected || (u8)fields != '8' || packet[8] != 0) {
        stock_e8(packet);
        return;
    }
    const u8 token = fields >> 16;
    const unsigned revision = fields >> 24;
    const u8 command = fields >> 8;
    if (command == FT8_LINK_CLOSE_MODE) {
        if (!revision && token == tx->ui_state && (token & FT8_LINK_MODE_MASK))
            set_ui_mode(FT8_LINK_MODE_NONE);
        return;
    }
    if (token > FT8_LINK_TOKEN_MASK)
        return;
    const unsigned phase = tx->phase;
    if (command == FT8_LINK_START && phase == FT8_PHASE_IDLE &&
        revision == tx->ui_state && (revision & FT8_LINK_MODE_MASK) == FT8_LINK_MODE_FT8)
        key(token);
    else if (command == FT8_LINK_STOP && !revision && phase == FT8_PHASE_ACTIVE && tx->link == token << 2)
        unkey();
}

/* 72 assignable custom button IDs: sq9pd's 70 IDs + FT8 (0xEE) + CW_DEC (0xEF). */
__attribute__((section(".c2_rodata"), used))
const u8 ft8_custom_btn_table[72] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x48, 0x42, 0x45, 0x36, 0x44, 0x08,
    0x09, 0x82, 0x2b, 0x49, 0x4a, 0x41, 0x2d, 0x0e, 0x07, 0x0a, 0x47, 0x0b,
    0x0c, 0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x4b, 0x4c, 0x16, 0x18, 0x17,
    0x7f, 0x6c, 0x62, 0x63, 0x6d, 0x6e, 0x5e, 0x65, 0x66, 0x83, 0x84, 0x80,
    0x68, 0x67, 0x69, 0x6a, 0x88, 0x81, 0x55, 0x5d, 0x59, 0x5a, 0x53, 0xe0,
    0xe1, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0x64, 0xe9, 0xee, 0xef,
};

struct custom_key_entry {
    unsigned short code;
    u8 flag;
    u8 page;
    u32 id;
    void (*fn)(unsigned);
};
_Static_assert(sizeof(struct custom_key_entry) == 12, "MAIN key_table_entry size");

__attribute__((section(".c2_text")))
static void select_ui_mode(u8 target)
{
    if (B8(SWR_SCAN_OPEN) != 0) {
        stock_beep(3);
        return;
    }
    set_ui_mode((tx->ui_state & FT8_LINK_MODE_MASK) == target ? FT8_LINK_MODE_NONE : target);
    stock_beep(1);
}

__attribute__((section(".c2_text"), used))
void ft8_custom_ft8_click(unsigned arg)
{
    if (arg == 0)
        select_ui_mode(FT8_LINK_MODE_FT8);
}

__attribute__((section(".c2_text"), used))
void ft8_custom_cw_click(unsigned arg)
{
    if (arg == 0)
        select_ui_mode(FT8_LINK_MODE_CW);
}

__attribute__((section(".c2_rodata"), aligned(4), used))
const struct custom_key_entry ft8_custom_key_ft8 = {
    0x0596, 0, 0, 0xee, ft8_custom_ft8_click,
};

__attribute__((section(".c2_rodata"), aligned(4), used))
const struct custom_key_entry ft8_custom_key_cw = {
    0x0597, 0, 0, 0xef, ft8_custom_cw_click,
};
