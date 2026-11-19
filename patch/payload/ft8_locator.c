#include "ft8_locator.h"

enum { SQUARES = 180, SUBSQUARES = 4320 };

static unsigned letter(char c, unsigned limit)
{
    unsigned index = ((unsigned char)c & ~32u) - 'A';
    return index < limit ? index : limit;
}

uint32_t ft8_locator_parse(const char *text)
{
    unsigned n = 0;
    while (n < 7 && text[n])
        ++n;
    if (n != 4 && n != 6)
        return 0;
    const unsigned lon_field = letter(text[0], 18);
    const unsigned lat_field = letter(text[1], 18);
    const unsigned lon_square = (unsigned)text[2] - '0';
    const unsigned lat_square = (unsigned)text[3] - '0';
    if (lon_field >= 18 || lat_field >= 18 || lon_square >= 10 || lat_square >= 10)
        return 0;
    unsigned lon = lon_field * 10 + lon_square;
    unsigned lat = lat_field * 10 + lat_square;
    if (n == 4)
        return FT8_GRID4_FLAG | (lat * SQUARES + lon + 1u);
    const unsigned lon_sub = letter(text[4], 24);
    const unsigned lat_sub = letter(text[5], 24);
    if (lon_sub >= 24 || lat_sub >= 24)
        return 0;
    lon = lon * 24 + lon_sub;
    lat = lat * 24 + lat_sub;
    return lat * SUBSQUARES + lon + 1u;
}

static unsigned coordinate_cell(unsigned shifted_e6, unsigned per_degree)
{
    return shifted_e6 / 1000000u * per_degree +
           shifted_e6 % 1000000u * per_degree / 1000000u;
}

uint32_t ft8_locator_coordinates(int32_t latitude_e6, int32_t longitude_e6)
{
    if (latitude_e6 < -90000000 || latitude_e6 > 90000000 ||
        longitude_e6 < -180000000 || longitude_e6 > 180000000)
        return 0;
    const unsigned lon = longitude_e6 == 180000000 ? 0 :
                         coordinate_cell((unsigned)(longitude_e6 + 180000000), 12);
    const unsigned lat = latitude_e6 == 90000000 ? SUBSQUARES - 1 :
                         coordinate_cell((unsigned)(latitude_e6 + 90000000), 24);
    return lat * SUBSQUARES + lon + 1u;
}

int ft8_locator_cells(uint32_t grid, unsigned *lon, unsigned *lat, unsigned *axis)
{
    const unsigned cells = grid & ~FT8_GRID4_FLAG;
    if (cells == 0)
        return 0;
    if (grid & FT8_GRID4_FLAG) {
        if (cells > SQUARES * SQUARES)
            return 0;
        *axis = SQUARES;
        *lon = (cells - 1) % SQUARES;
        *lat = (cells - 1) / SQUARES;
    } else {
        if (cells > SUBSQUARES * SUBSQUARES)
            return 0;
        *axis = SUBSQUARES;
        *lon = (cells - 1) % SUBSQUARES;
        *lat = (cells - 1) / SUBSQUARES;
    }
    return 1;
}

void ft8_locator_format(uint32_t grid, char text[7])
{
    unsigned lon, lat, axis;
    text[0] = 0;
    if (!ft8_locator_cells(grid, &lon, &lat, &axis))
        return;
    if (axis == SUBSQUARES) {
        text[4] = (char)('a' + lon % 24);
        text[5] = (char)('a' + lat % 24);
        text[6] = 0;
        lon /= 24;
        lat /= 24;
    } else {
        text[4] = 0;
    }
    text[0] = (char)('A' + lon / 10);
    text[1] = (char)('A' + lat / 10);
    text[2] = (char)('0' + lon % 10);
    text[3] = (char)('0' + lat % 10);
}
