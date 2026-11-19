#include <fft/kiss_fftr.h>

#pragma clang section text=".ft8_vfp_text" data=".ft8_vfp_data"

static unsigned backend __attribute__((section(".ft8_vfp_data"))) = 0;

int ft8_vfp_probe(void);
void ft8_vfp_fft(kiss_fftr_cfg, const kiss_fft_cpx *, kiss_fft_cpx *);

void ft8_fft_prepare(void)
{
    if (!backend)
        backend = ft8_vfp_probe() ? 2 : 1;
}

unsigned ft8_fft_backend(void) { return backend; }

#ifndef FT8_VFP_ONLY
void ft8_rx_fft(kiss_fftr_cfg config, const kiss_fft_cpx *input, kiss_fft_cpx *output)
{
    if (backend == 2)
        ft8_vfp_fft(config, input, output);
    else
        kiss_fftr_packed(config, input, output);
}
#endif
