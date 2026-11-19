#ifndef FT8_PLUGIN_H
#define FT8_PLUGIN_H

#include "ft8_live.h"

enum { FT8_PLUGIN_MAGIC = 0x50385446, FT8_PLUGIN_ABI = 1,
       FT8_PLUGIN_MAX = 16 * 1024, FT8_PLUGIN_LINE = 40 };

struct ft8_plugin_header {
    uint32_t magic, abi, size, entry, crc;
};

/* Only these imports and the read-only queue snapshot cross the module ABI. */
struct ft8_plugin_host {
    char *(*append)(char *, const char *);
    char *(*number)(char *, uint32_t);
    char *(*report)(char *, int);
};

/* Changing this shared layout requires a plugin ABI version bump. */
_Static_assert(sizeof(struct ft8_full_peer) == 20 &&
               offsetof(struct ft8_full_peer, call) == 0 &&
               offsetof(struct ft8_full_peer, hz) == 14 &&
               offsetof(struct ft8_full_peer, km) == 16 &&
               offsetof(struct ft8_full_peer, db) == 18, "FT8 plugin peer ABI changed");

typedef void (*ft8_plugin_queue_fn)(const struct ft8_plugin_host *,
                                    const struct ft8_full_peer *, char *);

void ft8_plugin_request(void);
void ft8_plugin_load(void);
ft8_plugin_queue_fn ft8_plugin_queue(void);

#endif
