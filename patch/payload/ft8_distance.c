#include "ft8_locator.h"
#include "ft8_arm_api.h"

#include <math.h>

#ifdef FT8_RADIO
/* The native FFT, waveform and locator use angles within one turn. Fold to
   +/- pi/2 before evaluating the degree-11 sine polynomial. */
__attribute__((noinline)) float sinf(float angle)
{
    const float pi = 3.14159265358979323846f;
    if (angle > pi)
        angle -= 2 * pi;
    else if (angle < -pi)
        angle += 2 * pi;
    if (angle > pi / 2)
        angle = pi - angle;
    else if (angle < -pi / 2)
        angle = -pi - angle;
    const float x2 = angle * angle;
    return angle * (1.0f + x2 * (-1.0f / 6 + x2 * (1.0f / 120 + x2 *
           (-1.0f / 5040 + x2 * (1.0f / 362880 - x2 / 39916800)))));
}

float cosf(float angle)
{
    return sinf(1.57079632679489661923f - fabsf(angle));
}
#endif

static int center_radians(uint32_t grid, float *lat, float *lon)
{
    const float pi = 3.14159265358979323846f;
    unsigned x, y, axis;
    if (!ft8_locator_cells(grid, &x, &y, &axis))
        return 0;
    *lat = pi * (((float)y + 0.5f) / (float)axis - 0.5f);
    *lon = 2.0f * pi * (((float)x + 0.5f) / (float)axis - 0.5f);
    return 1;
}

uint16_t ft8_locator_distance(uint32_t local, uint32_t remote)
{
    float lat1, lon1, lat2, lon2;
    if (!center_radians(local, &lat1, &lon1) || !center_radians(remote, &lat2, &lon2))
        return FT8_DISTANCE_UNKNOWN;
    const float dy = sinf((lat2 - lat1) * 0.5f);
    const float dx = sinf((lon2 - lon1) * 0.5f);
    float hav = dy * dy + cosf(lat1) * cosf(lat2) * dx * dx;
    if (hav > 1.0f)
        hav = 1.0f;
#if defined(FT8_PROFILE) || defined(FT8_VFP_ONLY)
    /* Reduce atan to |t| <= tan(pi/8). The approximation's maximum
       truncation error is below 11 m over the entire globe. */
    const int far = hav > 0.5f;
    const float low = far ? 1.0f - hav : hav;
#if defined(__arm__) && defined(FT8_VFP_ONLY)
    extern float ft8_vfp_sqrt(float value);
    float t = ft8_vfp_sqrt(low / (1.0f - low));
#else
    float t = sqrtf(low / (1.0f - low));
#endif
    const float quarter = 0.7853981633974483f;
    float bias = 0.0f;
    if (t > 0.4142135623730950f) {
        t = (t - 1.0f) / (t + 1.0f);
        bias = quarter;
    }
    const float x = t * t;
    const float angle = bias + t * (1.0f + x * (-1.0f/3 + x * (1.0f/5 +
        x * (-1.0f/7 + x * (1.0f/9 - x/11)))));
    return (uint16_t)(12742.0f * (far ? 2.0f * quarter - angle : angle) + 0.5f);
#else
    return (uint16_t)(12742.0f * atan2f(sqrtf(hav), sqrtf(1.0f - hav)) + 0.5f);
#endif
}
