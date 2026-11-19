#include "ft8_plugin.h"

#define STOCK(offset, type) ((type)(0x60400000u + (offset)))
#define LIVE_DATA __attribute__((section(".ft8_plugin_data")))
#pragma clang section text=".ft8_plugin_text" rodata=".ft8_plugin_rodata"

static unsigned requested LIVE_DATA = 0;
static ft8_plugin_queue_fn queue LIVE_DATA = 0;

__attribute__((noinline)) ft8_plugin_queue_fn ft8_plugin_queue(void)
{
    return __atomic_load_n(&queue, __ATOMIC_ACQUIRE);
}

__attribute__((noinline)) void ft8_plugin_request(void)
{
    if (!ft8_plugin_queue())
        __atomic_store_n(&requested, 1, __ATOMIC_RELEASE);
}

static uint32_t crc32(uint32_t crc, const void *buffer, size_t size)
{
    const unsigned char *bytes = buffer;
    while (size--) {
        crc ^= *bytes++;
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return crc;
}

static void sync_code(void *code, size_t size)
{
    /* Stock cache helpers clean data and invalidate instructions and the
       branch predictor before the entry point becomes visible. */
    STOCK(0x2fa8, void (*)(void *, size_t))(code, size);
    STOCK(0x2efc, void (*)(void *, size_t))(code, size);
}

__attribute__((noinline)) void ft8_plugin_load(void)
{
    if (!__atomic_exchange_n(&requested, 0, __ATOMIC_ACQ_REL) || ft8_plugin_queue())
        return;
    void *file = STOCK(0x6995c, void *(*)(const char *, const char *))("I:\\FTX-1\\FT8QUEUE.BIN", "rb");
    if (!file)
        return;
    const volatile uint32_t *const state = file;
    const size_t length = state[0x2c / 4];
    typedef size_t (*read_fn)(void *, size_t, size_t, void *);
    typedef unsigned (*lock_fn)(void);
    typedef void (*unlock_fn)(unsigned);
    const read_fn read = STOCK(0x6a8f8, read_fn);
    const lock_fn lock = STOCK(0xbfa8c, lock_fn);
    const unlock_fn unlock = STOCK(0xbfaac, unlock_fn);
    struct ft8_plugin_header header;
    void *allocation = 0;
    unsigned char *code = 0;
    int valid = 0;
    if (length > sizeof(header) && length <= sizeof(header) + FT8_PLUGIN_MAX &&
        read(&header, 1, sizeof(header), file) == sizeof(header) &&
        header.magic == FT8_PLUGIN_MAGIC && header.abi == FT8_PLUGIN_ABI &&
        header.size == length - sizeof(header) && (header.entry & 1u) &&
        header.size >= 2 && (header.entry & ~1u) <= header.size - 2) {
        const unsigned irq = lock();
        allocation = STOCK(0x7d9e0, void *(*)(size_t))(header.size + 31u);
        unlock(irq);
        if (allocation) {
            code = (void *)(((uintptr_t)allocation + 31u) & ~(uintptr_t)31u);
            const uint32_t prefix = crc32(~0u, &header, offsetof(struct ft8_plugin_header, crc));
            valid = read(code, 1, header.size, file) == header.size &&
                    state[0x28 / 4] == length && ~crc32(prefix, code, header.size) == header.crc;
        }
    }
    const int closed = STOCK(0x69e90, int (*)(void *))(file);
    if (valid && closed == 0) {
        sync_code(code, header.size);
        __atomic_store_n(&queue, (ft8_plugin_queue_fn)(code + header.entry), __ATOMIC_RELEASE);
    } else if (allocation) {
        const unsigned irq = lock();
        STOCK(0x7d9ec, int (*)(void *, size_t))(allocation, header.size + 31u);
        unlock(irq);
    }
}
