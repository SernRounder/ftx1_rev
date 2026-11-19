#ifndef STPCPY_SHIM_H
#define STPCPY_SHIM_H
#include <string.h>
static inline char *stpcpy_shim(char *dest, const char *src) {
    const size_t size = strlen(src);
    memcpy(dest, src, size + 1);
    return dest + size;
}
#define stpcpy stpcpy_shim
#endif
