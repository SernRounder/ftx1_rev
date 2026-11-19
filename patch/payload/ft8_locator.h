#ifndef FTX1_FT8_LOCATOR_H
#define FTX1_FT8_LOCATOR_H

#include <stdint.h>

#define FT8_GRID4_FLAG (1u << 31)

/* Opaque numeric grid. Zero means no valid position. */
uint32_t ft8_locator_parse(const char *text);
uint32_t ft8_locator_coordinates(int32_t latitude_e6, int32_t longitude_e6);
int ft8_locator_cells(uint32_t grid, unsigned *lon, unsigned *lat, unsigned *axis);
void ft8_locator_format(uint32_t grid, char text[7]);
uint16_t ft8_locator_distance(uint32_t local, uint32_t remote);

#endif
