#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
size_t g_peak, g_cur;
void *__real_malloc(size_t);
void __real_free(void *);
static void report(void) { fprintf(stderr, "PEAK_CONCURRENT_MALLOC %zu bytes\n", g_peak); }
void *__wrap_malloc(size_t n) {
    static int once;
    if (!once) { atexit(report); once = 1; }
    void *p = __real_malloc(n + 8);
    if (p) { *(size_t *)p = n; g_cur += n; if (g_cur > g_peak) g_peak = g_cur; }
    return p ? (char *)p + 8 : NULL;
}
void __wrap_free(void *p) {
    if (p) { g_cur -= ((size_t *)p)[-1]; __real_free((char *)p - 8); }
}
void *__wrap_calloc(size_t a, size_t b) {
    void *p = __wrap_malloc(a * b);
    if (p) memset(p, 0, a * b);
    return p;
}
