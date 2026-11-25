/* Behavioral tests use the real FFmpeg RPU parser and frame side data.
 * SPDX-License-Identifier: LGPL-2.1-or-later
 */
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "libavcodec/mediacodec_dovi.h"
#include "libavcodec/mediacodec_p010.h"
#include "fixtures/dovi_p5_rpu.h"
#include "fixtures/dovi_p8_rpu.h"

static AVCodecContext *context(int profile)
{
    AVCodecContext *ctx = avcodec_alloc_context3(NULL);
    AVDOVIDecoderConfigurationRecord *cfg;
    size_t size;
    AVPacketSideData *sd;
    assert(ctx);
    ctx->codec_id = AV_CODEC_ID_HEVC;
    ctx->pkt_timebase = (AVRational){1, 90000};
    cfg = av_dovi_alloc(&size);
    assert(cfg);
    cfg->dv_profile = profile;
    cfg->rpu_present_flag = cfg->bl_present_flag = 1;
    sd = av_packet_side_data_add(&ctx->coded_side_data, &ctx->nb_coded_side_data,
                                 AV_PKT_DATA_DOVI_CONF, (uint8_t *)cfg, size, 0);
    assert(sd);
    return ctx;
}

static AVPacket *packet(const unsigned char *rpu, int size, int64_t pts)
{
    /* One minimal VCL NAL, followed by a real RPU NAL. No pixel decoding needed. */
    static const uint8_t prefix[] = {0,0,0,1,2,1,0x80,0,0,0,1,0x7c,1};
    AVPacket *pkt = av_packet_alloc();
    assert(pkt && av_new_packet(pkt, sizeof(prefix) + size) == 0);
    memcpy(pkt->data, prefix, sizeof(prefix));
    memcpy(pkt->data + sizeof(prefix), rpu, size);
    pkt->pts = pts;
    return pkt;
}

static void submit(FFMediaCodecDovi *dovi, AVCodecContext *ctx,
                   const unsigned char *rpu, int size, int64_t pts)
{
    AVPacket *pkt = packet(rpu, size, pts);
    assert(ff_mediacodec_dovi_submit(dovi, ctx, pkt) == 0);
    av_packet_free(&pkt);
}

static void receive(FFMediaCodecDovi *dovi, AVCodecContext *ctx,
                    const unsigned char *rpu, int size, int64_t pts)
{
    AVFrame *frame = av_frame_alloc();
    AVFrameSideData *sd;
    frame->pts = pts;
    frame->format = AV_PIX_FMT_P010LE;
    assert(ff_mediacodec_dovi_attach(dovi, ctx, frame) == 0);
    sd = av_frame_get_side_data(frame, AV_FRAME_DATA_DOVI_RPU_BUFFER);
    assert(sd && sd->size == size && !memcmp(sd->data, rpu, size));
    assert(av_frame_get_side_data(frame, AV_FRAME_DATA_DOVI_METADATA));
    assert(ff_mediacodec_dovi_attach(dovi, ctx, frame) < 0); /* consumed once */
    av_frame_free(&frame);
}

static void metadata_tests(void)
{
    FFMediaCodecDovi dovi = {0};
    AVCodecContext *ctx = context(5);
    AVPacket *pkt;
    AVFrame *frame = av_frame_alloc();
    ff_mediacodec_dovi_init(&dovi, ctx);
    assert(dovi.enabled);
    /* Decode order differs from display order; repeated dynamic snapshots differ. */
    submit(&dovi, ctx, rpu_a, sizeof(rpu_a), 0);
    submit(&dovi, ctx, rpu_b, sizeof(rpu_b), 9000);
    submit(&dovi, ctx, rpu_a, sizeof(rpu_a), 3000);
    submit(&dovi, ctx, rpu_b, sizeof(rpu_b), 6000);
    receive(&dovi, ctx, rpu_a, sizeof(rpu_a), 0);
    receive(&dovi, ctx, rpu_a, sizeof(rpu_a), 3000);
    receive(&dovi, ctx, rpu_b, sizeof(rpu_b), 6000);
    receive(&dovi, ctx, rpu_b, sizeof(rpu_b), 9000);
    puts("PASS: B-frame timestamp matching and independent RPU snapshots");

    submit(&dovi, ctx, rpu_a, sizeof(rpu_a), 1000);
    ff_mediacodec_dovi_flush(&dovi);
    frame->pts = 1000;
    frame->format = AV_PIX_FMT_P010LE;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
    submit(&dovi, ctx, rpu_b, sizeof(rpu_b), 1000);
    receive(&dovi, ctx, rpu_b, sizeof(rpu_b), 1000);
    puts("PASS: seek/flush does not reuse metadata from an earlier timeline");

    pkt = packet(rpu_a, sizeof(rpu_a), AV_NOPTS_VALUE);
    assert(ff_mediacodec_dovi_submit(&dovi, ctx, pkt) < 0);
    av_packet_free(&pkt);
    submit(&dovi, ctx, rpu_a, sizeof(rpu_a), 1);
    pkt = packet(rpu_b, sizeof(rpu_b), 1);
    assert(ff_mediacodec_dovi_submit(&dovi, ctx, pkt) < 0);
    av_packet_free(&pkt);
    frame->pts = 1;
    frame->format = AV_PIX_FMT_NV12;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
    frame->format = AV_PIX_FMT_MEDIACODEC;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
    dovi.allow_yuv_surface = 1;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) == 0);
    AVFrameSideData *surface_rpu = av_frame_get_side_data(frame,
        AV_FRAME_DATA_DOVI_RPU_BUFFER);
    assert(surface_rpu && surface_rpu->size == sizeof(rpu_a));
    assert(!memcmp(surface_rpu->data, rpu_a, sizeof(rpu_a)));
    assert(av_frame_get_side_data(frame, AV_FRAME_DATA_DOVI_METADATA));
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
    av_frame_unref(frame);
    /* Even an opted-in renderer must never receive 8-bit pixels as Dolby. */
    submit(&dovi, ctx, rpu_b, sizeof(rpu_b), 1001);
    frame->pts = 1001;
    frame->format = AV_PIX_FMT_NV12;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
    frame->format = AV_PIX_FMT_MEDIACODEC;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) == 0);
    surface_rpu = av_frame_get_side_data(frame, AV_FRAME_DATA_DOVI_RPU_BUFFER);
    assert(surface_rpu && surface_rpu->size == sizeof(rpu_b));
    assert(!memcmp(surface_rpu->data, rpu_b, sizeof(rpu_b)));
    puts("PASS: P5 raw Surface opt-in preserves each RPU and rejects 8-bit pixels");
    ff_mediacodec_dovi_flush(&dovi);
    for (int i = 0; i < FF_MEDIACODEC_DOVI_PENDING; i++)
        submit(&dovi, ctx, rpu_a, sizeof(rpu_a), i);
    pkt = packet(rpu_a, sizeof(rpu_a), FF_MEDIACODEC_DOVI_PENDING);
    assert(ff_mediacodec_dovi_submit(&dovi, ctx, pkt) < 0);
    av_packet_free(&pkt);
    ff_mediacodec_dovi_close(&dovi);
    av_frame_free(&frame);
    avcodec_free_context(&ctx);
    puts("PASS: ambiguous/missing timestamps, unsupported output and bounded queue fail safely");

    memset(&dovi, 0, sizeof(dovi));
    ctx = context(7);
    ff_mediacodec_dovi_init(&dovi, ctx);
    assert(!dovi.enabled);
    pkt = av_packet_alloc();
    frame = av_frame_alloc();
    assert(ff_mediacodec_dovi_submit(&dovi, ctx, pkt) == 0);
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) == 0);
    av_packet_free(&pkt);
    av_frame_free(&frame);
    ff_mediacodec_dovi_close(&dovi);
    avcodec_free_context(&ctx);
    puts("PASS: other Dolby profiles and ordinary decoder output are untouched");
}

static void profile8_tests(void)
{
    const unsigned char *samples[] = {rpu_p8, rpu_p84};
    const int sizes[] = {sizeof(rpu_p8), sizeof(rpu_p84)};
    for (int sample = 0; sample < 2; sample++) {
        FFMediaCodecDovi dovi = {0};
        AVCodecContext *ctx = context(8);
        ff_mediacodec_dovi_init(&dovi, ctx);
        assert(dovi.enabled);
        submit(&dovi, ctx, samples[sample], sizes[sample], 9000);
        submit(&dovi, ctx, samples[sample], sizes[sample], 3000);
        receive(&dovi, ctx, samples[sample], sizes[sample], 3000);
        receive(&dovi, ctx, samples[sample], sizes[sample], 9000);
        submit(&dovi, ctx, samples[sample], sizes[sample], 1000);
        ff_mediacodec_dovi_flush(&dovi);
        submit(&dovi, ctx, samples[sample], sizes[sample], 1000);
        receive(&dovi, ctx, samples[sample], sizes[sample], 1000);
        /* Surface transport must be explicit and preserve the exact RPU. */
        AVFrame *frame = av_frame_alloc();
        frame->format = AV_PIX_FMT_MEDIACODEC;
        frame->pts = 2000;
        submit(&dovi, ctx, samples[sample], sizes[sample], 2000);
        assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
        dovi.allow_yuv_surface = 1;
        assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) == 0);
        AVFrameSideData *sd = av_frame_get_side_data(frame, AV_FRAME_DATA_DOVI_RPU_BUFFER);
        assert(sd && sd->size == sizes[sample]);
        assert(!memcmp(sd->data, samples[sample], sd->size));
        assert(av_frame_get_side_data(frame, AV_FRAME_DATA_DOVI_METADATA));
        assert(ff_mediacodec_dovi_attach(&dovi, ctx, frame) < 0);
        av_frame_free(&frame);
        ff_mediacodec_dovi_close(&dovi);
        avcodec_free_context(&ctx);
    }
    puts("PASS: real P8.1/P8.4 RPU survives display reordering and seek/flush");

    FFMediaCodecDovi dovi = {0};
    AVCodecContext *ctx = context(8);
    ((AVDOVIDecoderConfigurationRecord *)ctx->coded_side_data[0].data)->rpu_present_flag = 0;
    ff_mediacodec_dovi_init(&dovi, ctx);
    assert(!dovi.enabled);
    ff_mediacodec_dovi_close(&dovi);
    avcodec_free_context(&ctx);
    puts("PASS: a Dolby-tagged base layer without RPU retains ordinary decoding");
}

static void extended_profile_tests(void)
{
    FFMediaCodecDovi dovi = {0};
    AVCodecContext *ctx = context(10);
    ctx->codec_id = AV_CODEC_ID_AV1;
    ff_mediacodec_dovi_init(&dovi, ctx);
    assert(dovi.parser.cfg.dv_profile == 10 && !dovi.enabled);
    ff_mediacodec_dovi_close(&dovi);
    avcodec_free_context(&ctx);
    puts("PASS: AV1 P10 configuration reaches native selection without HEVC RPU parsing");

    memset(&dovi, 0, sizeof(dovi));
    ctx = context(20);
    ff_mediacodec_dovi_init(&dovi, ctx);
    assert(dovi.enabled);
    AVPacket *pkt = packet(rpu_p8, sizeof(rpu_p8), 9000);
    const int base_size = pkt->size;
    /* A second-view VCL NAL has nuh_layer_id=1. Keep only the base view
     * without losing its RPU, timing, flags or packet side data. */
    const uint8_t extra[] = {0,0,1,2,9,0x80};
    assert(av_grow_packet(pkt, sizeof(extra)) == 0);
    memcpy(pkt->data + base_size, extra, sizeof(extra));
    pkt->dts = 6000;
    pkt->flags = AV_PKT_FLAG_KEY;
    assert(ff_mediacodec_dovi_submit(&dovi, ctx, pkt) == 0);
    assert(pkt->size < base_size + sizeof(extra));
    assert(pkt->pts == 9000 && pkt->dts == 6000);
    H2645Packet filtered = {0};
    assert(ff_h2645_packet_split(&filtered, pkt->data, pkt->size, ctx, 0,
                                AV_CODEC_ID_HEVC, H2645_FLAG_SMALL_PADDING) == 0);
    assert(filtered.nb_nals == 2);
    assert(filtered.nals[0].nuh_layer_id == 0 && filtered.nals[0].type == 1);
    assert(filtered.nals[1].nuh_layer_id == 0 && filtered.nals[1].type == 62);
    ff_h2645_packet_uninit(&filtered);
    assert(pkt->flags & AV_PKT_FLAG_KEY);
    AVFrame *surface = av_frame_alloc();
    surface->format = AV_PIX_FMT_MEDIACODEC;
    surface->pts = 9000;
    dovi.allow_yuv_surface = 1;
    assert(ff_mediacodec_dovi_attach(&dovi, ctx, surface) < 0);
    av_frame_free(&surface);
    receive(&dovi, ctx, rpu_p8, sizeof(rpu_p8), 9000);
    av_packet_free(&pkt);
    ff_mediacodec_dovi_close(&dovi);
    avcodec_free_context(&ctx);
    puts("PASS: P20 base-view transport preserves timestamps and Dolby metadata");
}

static void p010_tests(void)
{
    uint8_t src[256], y[32], uv[16];
    for (int i = 0; i < sizeof(src); i++) src[i] = i;
    memset(y, 0xa5, sizeof(y)); memset(uv, 0xa5, sizeof(uv));
    /* Nonzero buffer offset, row padding, slice padding, and aligned crop. */
    assert(ff_mediacodec_copy_p010(y, 8, uv, 8, src, sizeof(src), 8, 144,
                                  16, 6, 2, 2, 4, 4) == 0);
    for (int row = 0; row < 4; row++)
        assert(!memcmp(y + row * 8, src + 8 + (row + 2) * 16 + 4, 8));
    for (int row = 0; row < 2; row++)
        assert(!memcmp(uv + row * 8, src + 8 + 96 + (row + 1) * 16 + 4, 8));
    puts("PASS: P010 byte stride, padding, crop and ten-bit payload preservation");
    assert(ff_mediacodec_copy_p010(y,8,uv,8,src,sizeof(src),8,139,16,6,2,2,4,4)<0);
    assert(ff_mediacodec_copy_p010(y,8,uv,8,src,sizeof(src),8,144,16,6,1,2,4,4)<0);
    assert(ff_mediacodec_copy_p010(y,8,uv,8,src,sizeof(src),8,144,16,6,2,1,4,4)<0);
    assert(ff_mediacodec_copy_p010(y,-8,uv,8,src,sizeof(src),8,144,16,6,2,2,4,4)<0);
    assert(ff_mediacodec_copy_p010(y,8,uv,8,src,sizeof(src),8,144,8,6,2,2,4,4)<0);
    assert(ff_mediacodec_copy_p010(y,8,uv,8,src,sizeof(src),INT_MAX,INT_MAX,INT_MAX,INT_MAX,2,2,4,4)<0);
    puts("PASS: invalid P010 layouts and arithmetic boundaries are rejected");
}

int main(void) { metadata_tests(); profile8_tests(); extended_profile_tests(); p010_tests(); return 0; }
