/* Regression probe for scaled premultiplied PGS/BGRA subtitles. No image output. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <libavutil/imgutils.h>
#include <libavutil/mem.h>
#include <libswscale/swscale.h>

static int check(int width, int height, int flags)
{
    uint8_t *src[4] = {0}, *dst[4] = {0};
    int ss[4], ds[4];
    if (av_image_alloc(src, ss, 128, 64, AV_PIX_FMT_BGRA, 32) < 0 ||
        av_image_alloc(dst, ds, width, height, AV_PIX_FMT_BGRA, 32) < 0)
        return 1;
    for (int y = 0; y < 64; y++) {
        for (int x = 0; x < 128; x++) {
            int alpha = x >= 32 && x < 64 ? 128 : x >= 64 && x < 96 ? 255 : 0;
            memset(src[0] + y * ss[0] + 4*x, alpha, 4);
        }
    }
    struct SwsContext *s = sws_getContext(128, 64, AV_PIX_FMT_BGRA, width, height,
        AV_PIX_FMT_BGRA, flags, NULL, NULL, NULL);
    int ok = s && sws_scale(s, (const uint8_t *const *)src, ss, 0, 64, dst, ds) == height;
    int clear = dst[0][(height/2) * ds[0] + 4*(width/8) + 3];
    int half = dst[0][(height/2) * ds[0] + 4*(3*width/8) + 3];
    int solid = dst[0][(height/2) * ds[0] + 4*(5*width/8) + 3];
    ok = ok && clear == 0 && half >= 126 && half <= 130 && solid == 255;
    printf("%dx%d flags=%d transparent=%d partial=%d opaque=%d %s\n",
           width, height, flags, clear, half, solid, ok ? "PASS" : "FAIL");
    sws_freeContext(s);
    av_freep(&src[0]); av_freep(&dst[0]);
    return !ok;
}
int main(void)
{
    int failed = 0;
    for (int i = 0; i < 2; i++) {
        int flags = i ? SWS_LANCZOS | SWS_FULL_CHR_H_INT | SWS_FULL_CHR_H_INP | SWS_ACCURATE_RND : SWS_BILINEAR;
        failed |= check(64, 32, flags);
        failed |= check(256, 128, flags);
        failed |= check(128, 64, flags);
    }
    return failed;
}
