#ifndef FTX1_FT8_ADIF_H
#define FTX1_FT8_ADIF_H

#include <stddef.h>
#include <stdint.h>

enum { FT8_WORKED_MAX = 512, FT8_ADIF_RECORD_MAX = 240, FT8_RECENT_QSOS = 6 };

struct ft8_recent_qso {
    char call[14], utc[20];
};
int ft8_valid_utc(const uint8_t bcd[7]);
int ft8_local_to_utc(uint8_t bcd[7], int utc_offset_minutes);

struct ft8_qso {
    char call[14];
    char my_call[14];
    char grid[5];    /* dx four-character grid from the decoded row */
    char my_grid[5]; /* four-character grid */
    char band[8];
    char freq[12];    /* MHz */
    char report_sent[4], report_received[4];
    char power[6];    /* watts */
};

/* Build one record from confirmed QSO data and seven caller-supplied UTC BCD bytes. */
size_t ft8_adif_record(char *out, size_t capacity, const struct ft8_qso *qso,
                       const uint8_t bcd[7]);
/* Cache the newest distinct calls from the on-radio ADIF. */
struct ft8_worked {
    char calls[FT8_WORKED_MAX][14];
    unsigned count, next, fill;
    char line[FT8_ADIF_RECORD_MAX];
    unsigned recent_revision;
    struct ft8_recent_qso recent[FT8_RECENT_QSOS];
};
void ft8_adif_recent_add(struct ft8_worked *, const char *call, const char *fields, size_t);
void ft8_radio_recent_qsos(struct ft8_recent_qso out[FT8_RECENT_QSOS]);
void ft8_adif_worked_add(struct ft8_worked *, const char *);
int ft8_adif_worked_before(const struct ft8_worked *, const char *, size_t);
void ft8_adif_worked_read(struct ft8_worked *, const char *, size_t);
void ft8_adif_worked_scan(struct ft8_worked *, const char *, size_t, void (*match)(const char *));

#endif
