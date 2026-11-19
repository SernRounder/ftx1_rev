/* ADIF record formatter and session-scoped worked-callsign set. */
#include "ft8_adif.h"

#include <string.h>

typedef unsigned u32;

static char *append(char *dest, const char *source)
{
    while (*source)
        *dest++ = *source++;
    return dest;
}

/* Write "<name:length>" and leave the value to the caller. */
static char *field_open(char *dest, const char *name, size_t length)
{
    *dest++ = '<';
    dest = append(dest, name);
    *dest++ = ':';
    if (length >= 10) {
        *dest++ = (char)('0' + length / 10);
        *dest++ = (char)('0' + length % 10);
    } else {
        *dest++ = (char)('0' + length);
    }
    *dest++ = '>';
    return dest;
}

static char *field(char *dest, const char *name, const char *value)
{
    size_t n = 0;
    while (value[n])
        ++n;
    dest = field_open(dest, name, n);
    for (size_t i = 0; i < n; ++i)
        *dest++ = value[i];
    return dest;
}

static char *append_bcd2(char *dest, uint8_t bcd)
{
    *dest++ = (char)('0' + (bcd >> 4 & 0xf));
    *dest++ = (char)('0' + (bcd & 0xf));
    return dest;
}

static int valid_field(const char *value, size_t size)
{
    for (size_t i = 0; i < size; ++i) {
        const unsigned char ch = value[i];
        if (!ch)
            return 1;
        if (ch < 0x20 || ch > 0x7e || ch == '<' || ch == '>')
            return 0;
    }
    return 0;
}

static __attribute__((noinline)) int bcd_value(uint8_t bcd)
{
    const int high = bcd >> 4, low = bcd & 15;
    return high <= 9 && low <= 9 ? 10 * high + low : -1;
}

static int month_days(int year, int month)
{
    static const uint8_t days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return days[month - 1] + (month == 2 && year % 4 == 0);
}

int ft8_valid_utc(const uint8_t bcd[7])
{
    if (!bcd)
        return 0;
    const int year = bcd_value(bcd[0]), month = bcd_value(bcd[1]), day = bcd_value(bcd[2]);
    const int hour = bcd_value(bcd[4]), minute = bcd_value(bcd[5]), second = bcd_value(bcd[6]);
    return year >= 0 && month >= 1 && month <= 12 && day >= 1 &&
           day <= month_days(year, month) &&
           hour >= 0 && hour < 24 && minute >= 0 && minute < 60 && second >= 0 && second < 60;
}

static uint8_t to_bcd(unsigned value)
{
    return (value / 10 << 4) | (value % 10);
}

int ft8_local_to_utc(uint8_t bcd[7], int utc_offset_minutes)
{
    if (!ft8_valid_utc(bcd))
        return 0;
    int year = bcd_value(bcd[0]), month = bcd_value(bcd[1]), day = bcd_value(bcd[2]);
    int minute = 60 * bcd_value(bcd[4]) + bcd_value(bcd[5]) - utc_offset_minutes;
    const int step = minute < 0 ? -1 : minute >= 1440;
    if (step) {
        minute -= step * 1440;
        day += step;
        if (day < 1 || day > month_days(year, month)) {
            month += step;
            if (month < 1 || month > 12) {
                month -= step * 12;
                year += step;
            }
            day = step < 0 ? month_days(year, month) : 1;
        }
    }
    if ((unsigned)year > 99)
        return 0;
    bcd[0] = to_bcd(year);
    bcd[1] = to_bcd(month);
    bcd[2] = to_bcd(day);
    bcd[4] = to_bcd(minute / 60);
    bcd[5] = to_bcd(minute % 60);
    return 1;
}

/* Stock years are 00..99 and represent 2000..2099. */
static const struct {
    const char *tag;
    uint8_t offset, capacity;
} qso_fields[] = {
#define QSO_FIELD(member, tag) {tag, offsetof(struct ft8_qso, member), sizeof(((struct ft8_qso *)0)->member)}
    QSO_FIELD(call, "CALL"),
    QSO_FIELD(band, "BAND"),
    QSO_FIELD(freq, "FREQ"),
    QSO_FIELD(power, "TX_PWR"),
    QSO_FIELD(report_sent, "RST_SENT"),
    QSO_FIELD(report_received, "RST_RCVD"),
    QSO_FIELD(grid, "GRIDSQUARE"),
    QSO_FIELD(my_call, "STATION_CALLSIGN"),
    QSO_FIELD(my_grid, "MY_GRIDSQUARE"),
#undef QSO_FIELD
};

size_t ft8_adif_record(char *out, size_t capacity, const struct ft8_qso *qso,
                       const uint8_t bcd[7])
{
    if (!out || !qso || capacity < FT8_ADIF_RECORD_MAX || !ft8_valid_utc(bcd) ||
        !qso->call[0] || !qso->my_call[0] || (!qso->band[0] && !qso->freq[0]))
        return 0;
    const char *fields = (const char *)qso;
    const size_t field_count = sizeof(qso_fields) / sizeof(qso_fields[0]);
    for (size_t i = 0; i < field_count; ++i)
        if (!valid_field(fields + qso_fields[i].offset, qso_fields[i].capacity))
            return 0;
    /* The validated field sizes and their tags fit within FT8_ADIF_RECORD_MAX. */
    char *p = field(out, qso_fields[0].tag, qso->call);
    p = append(field_open(p, "QSO_DATE", 8), "20");
    for (unsigned i = 0; i < 3; ++i)
        p = append_bcd2(p, bcd[i]);
    p = field_open(p, "TIME_ON", 6);
    for (unsigned i = 4; i < 7; ++i)
        p = append_bcd2(p, bcd[i]);
    p = field(p, "MODE", "FT8");
    for (size_t i = 1; i < field_count; ++i) {
        const char *value = fields + qso_fields[i].offset;
        if (*value)
            p = field(p, qso_fields[i].tag, value);
    }
    p = append(p, "<eor>\n");
    *p = 0;
    return (size_t)(p - out);
}

int ft8_adif_worked_before(const struct ft8_worked *index, const char *call, size_t n)
{
    if (!index || !n || n >= sizeof(index->calls[0]))
        return 0;
    for (unsigned i = 0; i < index->count; ++i)
        if (!index->calls[i][n] && !memcmp(index->calls[i], call, n))
            return 1;
    return 0;
}

void ft8_adif_worked_add(struct ft8_worked *index, const char *call)
{
    const size_t n = strlen(call);
    if (!index || n >= sizeof(index->calls[0]) || !n ||
        ft8_adif_worked_before(index, call, n))
        return;
    memcpy(index->calls[index->next], call, n + 1);
    if (++index->next == FT8_WORKED_MAX)
        index->next = 0;
    if (index->count < FT8_WORKED_MAX)
        ++index->count;
}

void ft8_adif_recent_add(struct ft8_worked *index, const char *call, const char *fields, size_t n)
{
    /* The on-radio log writes these two fields immediately after CALL. */
    if (!index || n < 36 || memcmp(fields, "QSO_DATE:8>", 11) ||
        memcmp(fields + 19, "<TIME_ON:6>", 11))
        return;
    const char *digit = fields + 11;
    struct ft8_recent_qso row;
    for (unsigned j = 0; j < sizeof(row.utc); ++j) {
        const char separator = "0000-00-00 00:00:00"[j];
        if (separator != '0') {
            row.utc[j] = separator;
            if (separator == ' ')
                digit += 11;
        } else {
            if ((unsigned)(*digit - '0') > 9)
                return;
            row.utc[j] = *digit++;
        }
    }
    /* The reader has already terminated the call in its record buffer. */
    __builtin_memcpy(row.call, call, sizeof(row.call));
    unsigned i = 0;
    for (; i < FT8_RECENT_QSOS; ++i) {
        const int order = strcmp(row.utc, index->recent[i].utc);
        if (order > 0)
            break;
        if (!order && !strcmp(row.call, index->recent[i].call))
            return;
    }
    if (i == FT8_RECENT_QSOS)
        return;
    memmove(index->recent + i + 1, index->recent + i,
            (FT8_RECENT_QSOS - i - 1) * sizeof(row));
    index->recent[i] = row;
    __atomic_add_fetch(&index->recent_revision, 1, __ATOMIC_RELEASE);
}

void ft8_adif_worked_scan(struct ft8_worked *index, const char *chunk, size_t count,
                          void (*match)(const char *))
{
    /* FT8LOG.ADI writes one complete record per line. Ignore a damaged,
       overlong or interrupted line rather than marking an incomplete QSO. */
    for (size_t i = 0; i < count; ++i) {
        if (chunk[i] != '\n') {
            if (index->fill < sizeof(index->line))
                index->line[index->fill++] = chunk[i];
            continue;
        }
        unsigned n = index->fill;
        index->fill = 0;
        if (n && n < sizeof(index->line) && index->line[n - 1] == '\r')
            --n;
        if (n < 15 || n >= sizeof(index->line) ||
            memcmp(index->line, "<CALL:", 6) || memcmp(index->line + n - 5, "<eor>", 5))
            continue;
        unsigned length = 0, p = 6;
        while ((unsigned)(index->line[p] - '0') < 10 && p < 8)
            length = 10 * length + index->line[p++] - '0';
        if (!length || length > 13 || index->line[p++] != '>' || p + length >= n ||
            index->line[p + length] != '<')
            continue;
        index->line[p + length] = 0;
        ft8_adif_recent_add(index, index->line + p, index->line + p + length + 1,
                           n - p - length - 1);
        if (match)
            match(index->line + p);
        else
            ft8_adif_worked_add(index, index->line + p);
    }
}

void ft8_adif_worked_read(struct ft8_worked *index, const char *chunk, size_t count)
{
    ft8_adif_worked_scan(index, chunk, count, NULL);
}
