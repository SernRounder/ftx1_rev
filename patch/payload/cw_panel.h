#ifndef FTX1_CW_PANEL_H
#define FTX1_CW_PANEL_H

#include <stdint.h>

struct cw_panel_api {
    int (*capture)(const volatile uint16_t *, unsigned *);
};

extern const struct cw_panel_api cw_panel_api;
unsigned cw_panel_hit(unsigned, unsigned, uint16_t *);
int cw_local_touch(unsigned, unsigned);
void cw_sync(int);
void cw_set_active(int);
int cw_visible(void);
int cw_draw(void *, int);
void cw_worker_step(void);
int ft8_radio_start_worker(void);
int ft8_radio_cw_available(void);

#endif
