typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* Bulk-saved EEPROM/NVM shadow region (0x1451 + 0x3542 .. 0x70D6).
 * 0x4A2F..0x4A45 (RAM 0x5E80..0x5E96) is unreferenced in stock MAIN V0113. */
#define NVM_MAGIC     ((volatile u8 *)0x5e80u)
#define NVM_CUR_PAGE  ((volatile u8 *)0x5e81u)
#define NVM_PAGES     ((volatile u8 (*)[5])0x5e82u)
#define NVM_EDIT_PAGE ((volatile u8 *)0x5e96u)
#define NVM_MAGIC_VAL 0xa5u

#define ACTIVE_SLOTS  ((volatile u8 *)0x1b8ddu)
#define KEY_LOCK_FLAG (*(volatile u8 *)0x318a4u)
#define MENU_VAL_FLAG (*(volatile u8 *)0x30827u)
#define UI_CTX_PTR    (*(volatile u32 *)0x83b1d4u)
#define DIAL_DIR_OFF  0x21fd6u

#define SLOT_PAGE_ID  0x3fu /* DISPLAY 0x607c1938[0x3f] = "PAGE" */
#define SLOT_FUNC_ID  0xbdu /* DISPLAY 0x607c1938[0xbd] = "SETTING" */
#define SLOT_BLANK_ID 0xffu

#define STOCK_REG_ITEM   ((void (*)(const void *))0xfff06ca6u)
#define STOCK_STEP_U8    ((void (*)(u32, u32, volatile u8 *))0xfff08039u)
#define STOCK_BEEP       ((void (*)(u32))0xffea65fdu)
#define STOCK_FMT_VAL    ((u32 (*)(u32, char *, u8 *))0xffeeb137u)
#define STOCK_LOOKUP_ID  ((const void *(*)(u32))0xfff01906u)
#define STOCK_FUNC_KEY   ((void (*)(u32))0xffefdf89u)
#define STOCK_EMPTY_CB   0xfff159f4u

#define NUM_CANDS 38u

void softkey_cb28_key0(u8 *row);
void softkey_cb28_key1(u8 *row);
void softkey_cb28_key2(u8 *row);
void softkey_cb28_key3(u8 *row);
void softkey_cb28_key4(u8 *row);
void softkey_cb32_key0(void);
void softkey_cb32_key1(void);
void softkey_cb32_key2(void);
void softkey_cb32_key3(void);
void softkey_cb32_key4(void);

struct key_table_entry {
    u16 code;
    u8 flag;
    u8 page;
    u8 id;
    u8 pad[3];
    void (*fn)(u32);
};

static const u8 default_pages[4][5] = {
    /* Page 1: stock keys 2..5 + FUNC MENU button on key 6 */
    { 0x53u, 0x55u, 0x5du, 0x59u, SLOT_FUNC_ID },
    /* Page 2: CW / Keying */
    { 0x11u, 0x10u, 0x12u, 0x13u, 0x4cu },
    /* Page 3: TX / ANT / DSP */
    { 0x0eu, 0x2bu, 0x48u, 0x49u, 0x4au },
    /* Page 4: Scope / RX / Display Setting */
    { 0x81u, 0x5au, 0x42u, 0x43u, 0x33u },
};

static const u8 cand_ids[NUM_CANDS] = {
    SLOT_BLANK_ID, SLOT_FUNC_ID,
    0x81u, 0x53u, 0x55u, 0x5du, 0x59u, 0x5au,
    0x00u, 0x05u, 0x07u, 0x09u, 0x0au, 0x0eu, 0x0fu,
    0x10u, 0x11u, 0x12u, 0x13u, 0x14u, 0x4bu, 0x4cu,
    0x2bu, 0x82u, 0x48u, 0x2du,
    0x42u, 0x43u, 0x44u, 0x45u, 0x47u, 0x49u, 0x4au, 0x36u,
    0x30u, 0x31u, 0x32u, 0x33u,
};

static const char cand_names[] =
    "BLANK\0"
    "FUNC MENU\0"
    "D-MODE\0"
    "3DSS\0"
    "MULTI\0"
    "SCOPE\0"
    "SPAN\0"
    "SPEED\0"
    "D-LEVEL\0"
    "DIMMER\0"
    "MIC GAIN\0"
    "PROC LEVEL\0"
    "AMC LEVEL\0"
    "RF POWER\0"
    "MONI LEVEL\0"
    "KEYER\0"
    "BK-IN\0"
    "CW SPEED\0"
    "CW PITCH\0"
    "BK-DELAY\0"
    "ZIN\0"
    "CW SPOT\0"
    "TUNER\0"
    "ANT TUNE\0"
    "MOX\0"
    "TXW\0"
    "ATT\0"
    "IPO\0"
    "AGC\0"
    "AMP\0"
    "VOX\0"
    "NB\0"
    "DNR\0"
    "DNF\0"
    "RADIO\0"
    "CW\0"
    "OPERATION\0"
    "DISPLAY\0";

static void softkey_open_func_menu(u32 arg)
{
    if (arg == 0) {
        STOCK_FUNC_KEY(1u);
    }
}

static const struct key_table_entry func_btn_entry = {
    0x0530u, 0u, 3u, SLOT_FUNC_ID, { 0, 0, 0 }, softkey_open_func_menu,
};

static void softkey_nvm_init(void)
{
    if (*NVM_MAGIC == NVM_MAGIC_VAL) {
        *NVM_CUR_PAGE &= 3u;
        *NVM_EDIT_PAGE &= 3u;
        return;
    }
    for (u32 p = 0; p < 4u; p++) {
        for (u32 s = 0; s < 5u; s++) {
            NVM_PAGES[p][s] = default_pages[p][s];
        }
    }
    *NVM_CUR_PAGE = 0u;
    *NVM_EDIT_PAGE = 0u;
    *NVM_MAGIC = NVM_MAGIC_VAL;
}

void softkey_load_slots(void)
{
    softkey_nvm_init();
    u32 page = *NVM_CUR_PAGE & 3u;
    ACTIVE_SLOTS[0] = SLOT_PAGE_ID;
    for (u32 s = 0; s < 5u; s++) {
        ACTIVE_SLOTS[s + 1u] = NVM_PAGES[page][s];
    }
}

u32 softkey_get_slot(u32 slot)
{
    softkey_nvm_init();
    if (slot == 0u || slot >= 6u) {
        return SLOT_PAGE_ID;
    }
    return NVM_PAGES[*NVM_CUR_PAGE & 3u][slot - 1u];
}

u32 softkey_format_val(u32 id, char *val_out, u8 *en_out)
{
    if (id == SLOT_PAGE_ID) {
        if (val_out != 0) {
            val_out[0] = (char)('1' + (*NVM_CUR_PAGE & 3u));
            val_out[1] = '/';
            val_out[2] = '4';
            for (u32 i = 3u; i < 12u; i++) {
                val_out[i] = ' ';
            }
        }
        *en_out = 1u;
        return 1u;
    }
    if (id == SLOT_FUNC_ID || id == 0x4cu || id == 0x82u ||
        (id >= 0x30u && id <= 0x34u)) {
        if (val_out != 0) {
            for (u32 i = 0; i < 12u; i++) {
                val_out[i] = '\0';
            }
        }
        *en_out = 1u;
        return 0u;
    }
    return STOCK_FMT_VAL(id, val_out, en_out);
}

const void *softkey_lookup_id(u32 id)
{
    u8 target = (u8)id;
    if (target == SLOT_FUNC_ID) {
        return &func_btn_entry;
    }
    const struct key_table_entry *p = (const struct key_table_entry *)0xffe96a00u;
    while (p->code != 0x05ffu) {
        if (p->id == target) {
            return p;
        }
        p++;
    }
    return 0;
}

void softkey_next_page(void)
{
    softkey_nvm_init();
    *NVM_CUR_PAGE = (u8)((*NVM_CUR_PAGE + 1u) & 3u);
    STOCK_BEEP(1u);
}

static void write_row(u8 *row, u32 is_def, const char *text)
{
    row[0] = (u8)((is_def ? 0x80u : 0u) | (MENU_VAL_FLAG == 1u ? 0x40u : 0u));
    row[1] = 12u;
    row[2] = 0u;
    for (u32 i = 0; i < 21u; i++) {
        char c = *text;
        if (c != '\0') {
            row[24u + i] = (u8)c;
            text++;
        } else {
            row[24u + i] = ' ';
        }
    }
}

static void softkey_cb28_page(u8 *row)
{
    softkey_nvm_init();
    u32 p = *NVM_EDIT_PAGE & 3u;
    char buf[6];
    buf[0] = (char)('1' + p);
    buf[1] = ' ';
    buf[2] = '/';
    buf[3] = ' ';
    buf[4] = '4';
    buf[5] = '\0';
    write_row(row, p == 0u, buf);
}

static void softkey_cb32_page(void)
{
    softkey_nvm_init();
    STOCK_STEP_U8(0u, 3u, NVM_EDIT_PAGE);
}

static u32 find_cand_idx(u8 id)
{
    for (u32 i = 0; i < NUM_CANDS; i++) {
        if (cand_ids[i] == id) {
            return i;
        }
    }
    return 0u;
}

static const char *nth_cand_name(u32 idx)
{
    const char *p = cand_names;
    while (idx > 0u) {
        while (*p != '\0') {
            p++;
        }
        p++;
        idx--;
    }
    return p;
}

void softkey_cb28_key(u8 *row, u32 slot_idx)
{
    softkey_nvm_init();
    u32 p = *NVM_EDIT_PAGE & 3u;
    u8 id = NVM_PAGES[p][slot_idx];
    u32 cidx = find_cand_idx(id);
    write_row(row, id == default_pages[p][slot_idx], nth_cand_name(cidx));
}

void softkey_cb32_key(u32 slot_idx)
{
    softkey_nvm_init();
    if (KEY_LOCK_FLAG == 1u) {
        return;
    }
    u32 p = *NVM_EDIT_PAGE & 3u;
    u32 idx = find_cand_idx(NVM_PAGES[p][slot_idx]);
    u8 dir = *(volatile u8 *)(UI_CTX_PTR + DIAL_DIR_OFF);
    if (dir == 0u) {
        idx = (idx + 1u < NUM_CANDS) ? (idx + 1u) : 0u;
    } else {
        idx = (idx > 0u) ? (idx - 1u) : (NUM_CANDS - 1u);
    }
    NVM_PAGES[p][slot_idx] = cand_ids[idx];
}

static void fill_title(u8 *dst, u32 idx)
{
    static const char tpl_page[21] = "SOFTKEY EDIT PAGE    ";
    static const char tpl_key[21]  = "SOFTKEY KEY 2        ";
    const char *src = (idx == 0u) ? tpl_page : tpl_key;
    for (u32 i = 0; i < 21u; i++) {
        dst[i] = (u8)src[i];
    }
    if (idx != 0u) {
        dst[12] = (u8)('1' + idx);
    }
}

void softkey_register_items(void)
{
    static void (*const cb28_tbl[5])(u8 *) = {
        softkey_cb28_key0, softkey_cb28_key1, softkey_cb28_key2,
        softkey_cb28_key3, softkey_cb28_key4,
    };
    static void (*const cb32_tbl[5])(void) = {
        softkey_cb32_key0, softkey_cb32_key1, softkey_cb32_key2,
        softkey_cb32_key3, softkey_cb32_key4,
    };
    u8 desc[60];
    for (u32 i = 0; i < 60u; i++) {
        desc[i] = 0u;
    }
    desc[0] = 1u;
    desc[3] = 3u;   /* Group 3: DISPLAY SETTING */
    desc[4] = 16u;  /* Subgroup 16: DISPLAY */
    desc[52] = 1u;
    desc[55] = 10u;
    *(u32 *)&desc[36] = STOCK_EMPTY_CB;

    for (u32 i = 0; i < 6u; i++) {
        desc[5] = (u8)(8u + i); /* items 8..13 after LED DIMMER (7) */
        fill_title(&desc[6], i);
        if (i == 0u) {
            *(u32 *)&desc[28] = (u32)softkey_cb28_page;
            *(u32 *)&desc[32] = (u32)softkey_cb32_page;
        } else {
            *(u32 *)&desc[28] = (u32)cb28_tbl[i - 1u];
            *(u32 *)&desc[32] = (u32)cb32_tbl[i - 1u];
        }
        STOCK_REG_ITEM(desc);
    }
}
