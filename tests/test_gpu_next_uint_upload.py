#!/usr/bin/env python3
"""Compile real MPV/FFmpeg descriptors and ra.c upload helpers with mock GPU I/O."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def braced(source, start):
    opening = source.index('{', start)
    depth, position, quote = 0, opening, None
    while position < len(source):
        if quote:
            if source[position] == '\\':
                position += 2
                continue
            if source[position] == quote:
                quote = None
        elif source.startswith('//', position):
            position = source.index('\n', position)
            continue
        elif source.startswith('/*', position):
            position = source.index('*/', position) + 2
            continue
        elif source[position] in ('"', "'"):
            quote = source[position]
        elif source[position] == '{':
            depth += 1
        elif source[position] == '}':
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
        position += 1
    raise AssertionError('Unclosed source body')


def function(source, name):
    match = re.search(r'(?m)^(?:static\s+)?[A-Za-z_][\w\s*]*\b' + re.escape(name) + r'\s*\(', source)
    assert match, name
    return braced(source, match.start())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', type=Path, default=Path(__file__).resolve().parents[1] / 'build/local-20261122/buildscripts')
    parser.add_argument('--cc', default='/usr/bin/clang')
    args = parser.parse_args()
    mpv, ffmpeg = args.staged / 'deps/mpv', args.staged / 'deps/ffmpeg'
    prefix = args.staged / 'prefix/arm64-v8a/include'
    ra = (mpv / 'video/out/gpu_next/ra.c').read_text()
    image = (mpv / 'video/img_format.c').read_text()
    image_ops = (mpv / 'video/mp_image.c').read_text()
    common = (mpv / 'common/common.c').read_text()
    conversion = (mpv / 'video/fmt-conversion.c').read_text()
    pixdesc = (ffmpeg / 'libavutil/pixdesc.c').read_text()
    imgutils = (ffmpeg / 'libavutil/imgutils.c').read_text()
    placebo = (args.staged / 'deps/libplacebo/src/colorspace.c').read_text()
    video = (mpv / 'video/out/gpu_next/video.c').read_text()
    pix_table_start = pixdesc.index('static const AVPixFmtDescriptor av_pix_fmt_descriptors')
    conversion_start = conversion.index('static const struct {')
    image_prefix = image[image.index('struct mp_imgfmt_entry {'):image.index('char **mp_imgfmt_name_list')]
    fragments = [function(common, 'mp_log2'), function(common, 'mp_round_next_power_of_2'),
                 function(image_ops, 'mp_chroma_div_up'),
                 function(image_ops, 'mp_image_plane_w'), function(image_ops, 'mp_image_plane_h'),
                 braced(pixdesc, pix_table_start) + ';', function(pixdesc, 'av_pix_fmt_desc_get'),
                 function(pixdesc, 'av_pix_fmt_count_planes'), function(imgutils, 'av_image_fill_max_pixsteps'),
                 function(imgutils, 'image_get_linesize'), function(imgutils, 'av_image_get_linesize'),
                 braced(conversion, conversion_start) + ';']
    # Include the anonymous conversion table's variable name after its struct.
    fragments[-1] = conversion[conversion_start:conversion.index('enum AVPixelFormat imgfmt2pixfmt')]
    fragments += [function(conversion, 'imgfmt2pixfmt'), function(conversion, 'pixfmt2imgfmt'), image_prefix,
                  function(image, 'fill_pixdesc_layout'), function(image, 'mp_imgfmt_get_desc_from_pixdesc'),
                  function(image, 'get_native_desc'), function(image, 'mp_imgfmt_desc_get_num_comps'),
                  function(image, 'mp_imgfmt_get_desc'), function(image, 'mp_imgfmt_to_name_buf'),
                  function(placebo, 'pl_bit_encoding_equal')]
    for name in ('ra_pl_cleanup_frame', 'plane_data_from_imgfmt', 'gpu_plane_data',
                 'ra_next_check_imgfmt', 'upload_mp_image_to_pl_frame'):
        fragments.append(function(ra, name))
    fragments += [function(placebo, 'pl_color_transfer_nominal_peak'),
                  function(image_ops, 'mp_image_params_restore_dovi_mapping'),
                  function(video, 'get_side_data'), function(video, 'dovi_requires_base_layer_fallback'),
                  function(video, 'restore_dovi_base_layer_params'), function(video, 'resolve_frame_color_params'),
                  function(video, 'apply_uploaded_frame_color')]
    preamble = r'''
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <libavutil/pixdesc.h>
#include <libavutil/common.h>
#include <libavutil/error.h>
#include <libavutil/dovi_meta.h>
#include <libavutil/imgutils.h>
#include "video/img_format.h"
#include "video/fmt-conversion.h"
#include "video/mp_image.h"
#include <libplacebo/renderer.h>
#include <libplacebo/utils/upload.h>
#include <libplacebo/utils/libav.h>
#define pl_unreachable() abort()
struct ra_next { pl_gpu gpu; struct mp_log *log; };
#define MSGL_ERR 1
void mp_msg(struct mp_log *log, int level, const char *format, ...) {}
void mp_assert_fail(const char *file, int line, const char *function, const char *expression) { abort(); }
// This unit covers the actual RPU/base-layer policy and upload merge; the
// source's unrelated color-space inference is covered by real GLES pixels.
void mp_image_params_guess_csp(struct mp_image_params *params) {}
static bool have_norm16, have_uint16, have_float;
static int norm_queries, uint_queries, float_queries, upload_count, fail_upload, live_tex, destroyed;
static struct pl_fmt_t fmt;
static enum pl_fmt_type uploaded_type[4];
pl_fmt pl_plane_find_fmt(pl_gpu gpu, int out_map[4], const struct pl_plane_data *data) {
    if (out_map) for (int n = 0; n < 4; n++) out_map[n] = data->component_size[n] ? data->component_map[n] : -1;
    int depth = data->component_size[0];
    if (data->type == PL_FMT_UNORM) { norm_queries++; if (depth == 16 && !have_norm16) return NULL; }
    if (data->type == PL_FMT_UINT) { uint_queries++; if (!have_uint16) return NULL; }
    if (data->type == PL_FMT_FLOAT) { float_queries++; if (!have_float) return NULL; }
    fmt = (struct pl_fmt_t){.type=data->type, .component_depth={depth,depth,depth,depth}};
    return &fmt;
}
void ra_next_tex_destroy(struct ra_next *ra, pl_tex *tex) {
    if (*tex) { free((void *)*tex); *tex=NULL; live_tex--; destroyed++; }
}
bool pl_upload_plane(pl_gpu gpu, struct pl_plane *plane, pl_tex *tex, const struct pl_plane_data *data) {
    assert(pl_plane_find_fmt(gpu, NULL, data));
    struct pl_tex_t *storage = calloc(1, sizeof(*storage));
    *tex = storage; plane->texture = storage; live_tex++;
    uploaded_type[upload_count++] = data->type;
    return upload_count != fail_upload;
}
static void reset(bool norm, bool uints, bool floats) {
    assert(live_tex == 0);
    have_norm16=norm; have_uint16=uints; have_float=floats;
    norm_queries=uint_queries=float_queries=upload_count=destroyed=0; fail_upload=-1;
}
'''
    assertions = r'''
static struct mp_image image_for(enum AVPixelFormat format) {
    static uint8_t data[4][4096];
    int id = pixfmt2imgfmt(format);
    struct mp_image image = {.imgfmt=id, .fmt=mp_imgfmt_get_desc(id), .w=16, .h=8};
    for (int n=0;n<image.fmt.num_planes;n++) { image.planes[n]=data[n]; image.stride[n]=128; }
    image.params.color = (struct pl_color_space){.primaries=PL_COLOR_PRIM_BT_2020, .transfer=PL_COLOR_TRC_PQ,
        .hdr={.max_luma=1000.0f, .min_luma=0.01f}};
    image.params.repr = (struct pl_color_repr){.sys=PL_COLOR_SYSTEM_DOLBYVISION, .levels=PL_COLOR_LEVELS_LIMITED,
        .dovi=(const struct pl_dovi_metadata *)(uintptr_t)0x12345678};
    return image;
}
static void bits(const struct pl_frame *frame,int sample,int color,int shift) {
    assert(frame->repr.bits.sample_depth==sample && frame->repr.bits.color_depth==color && frame->repr.bits.bit_shift==shift);
}
int main(void) {
    struct ra_next ra = {0}; struct pl_frame frame={0};
    struct mp_image yuv=image_for(AV_PIX_FMT_YUV420P10LE), p010=image_for(AV_PIX_FMT_P010LE);
    reset(true,true,true);
    assert(ra_next_check_imgfmt(&ra,yuv.imgfmt)); assert(uint_queries==0);
    assert(upload_mp_image_to_pl_frame(&ra,&frame,&yuv)); bits(&frame,16,10,0);
    assert(upload_count==3 && uint_queries==0);
    for (int n=0;n<3;n++) assert(uploaded_type[n]==PL_FMT_UNORM);
    assert(frame.color.primaries==PL_COLOR_PRIM_BT_2020 && frame.color.transfer==PL_COLOR_TRC_PQ && frame.color.hdr.max_luma==1000);
    assert(frame.repr.dovi==yuv.params.repr.dovi && frame.repr.sys==PL_COLOR_SYSTEM_DOLBYVISION && frame.repr.levels==PL_COLOR_LEVELS_LIMITED);
    ra_pl_cleanup_frame(&ra,&frame); assert(destroyed==3 && !live_tex);
    reset(false,true,true); assert(ra_next_check_imgfmt(&ra,yuv.imgfmt));
    assert(upload_mp_image_to_pl_frame(&ra,&frame,&yuv)); bits(&frame,16,10,0);
    for (int n=0;n<3;n++) assert(uploaded_type[n]==PL_FMT_UINT);
    ra_pl_cleanup_frame(&ra,&frame);
    reset(false,true,true); assert(upload_mp_image_to_pl_frame(&ra,&frame,&p010)); bits(&frame,16,10,6);
    assert(upload_count==2); for (int n=0;n<2;n++) assert(uploaded_type[n]==PL_FMT_UINT);
    assert(frame.repr.dovi==p010.params.repr.dovi); ra_pl_cleanup_frame(&ra,&frame);
    struct mp_image floats=image_for(AV_PIX_FMT_GBRPF32LE);
    reset(false,true,true); assert(upload_mp_image_to_pl_frame(&ra,&frame,&floats));
    for (int n=0;n<3;n++) assert(uploaded_type[n]==PL_FMT_FLOAT);
    assert(uint_queries==0); ra_pl_cleanup_frame(&ra,&frame);
    reset(false,true,false); assert(!ra_next_check_imgfmt(&ra,floats.imgfmt)); assert(uint_queries==0);
    reset(false,false,true); assert(!ra_next_check_imgfmt(&ra,yuv.imgfmt));
    assert(!upload_mp_image_to_pl_frame(&ra,&frame,&yuv) && upload_count==0 && !live_tex);
    reset(false,true,true); fail_upload=2;
    assert(!upload_mp_image_to_pl_frame(&ra,&frame,&yuv)); assert(upload_count==2 && destroyed==2 && !live_tex);
    // Real AVDOVIMetadata offsets/header layout; residual/enhancement layers
    // must remove RPU metadata, while supported RPU-only profiles retain it.
    struct { AVDOVIMetadata metadata; AVDOVIRpuDataHeader header; } dovi={0};
    dovi.metadata.header_offset=offsetof(typeof(dovi),header);
    AVBufferRef buffer={.data=(uint8_t *)&dovi, .size=sizeof(dovi)};
    struct mp_ff_side_data side={.type=AV_FRAME_DATA_DOVI_METADATA,.buf=&buffer};
    yuv.ff_side_data=&side; yuv.num_ff_side_data=1;
    yuv.params.primaries_orig=PL_COLOR_PRIM_BT_2020;
    yuv.params.transfer_orig=PL_COLOR_TRC_PQ;
    yuv.params.sys_orig=PL_COLOR_SYSTEM_BT_2020_NC;
    struct mp_image_params params=yuv.params;
    assert(dovi_requires_base_layer_fallback(&yuv));
    resolve_frame_color_params(&yuv,&params);
    assert(!params.repr.dovi && params.repr.sys==PL_COLOR_SYSTEM_BT_2020_NC && params.color.hdr.max_luma==0);
    frame.repr.bits=(struct pl_bit_encoding){.sample_depth=16,.color_depth=10,.bit_shift=6};
    apply_uploaded_frame_color(&frame,&params); bits(&frame,16,10,6);
    assert(!frame.repr.dovi && frame.repr.sys==PL_COLOR_SYSTEM_BT_2020_NC);
    AVMasteringDisplayMetadata static_hdr={.has_luminance=1,.max_luminance={1000,1},.min_luminance={1,10000}};
    AVBufferRef static_buffer={.data=(uint8_t *)&static_hdr,.size=sizeof(static_hdr)};
    struct mp_ff_side_data sides[2]={side,{.type=AV_FRAME_DATA_MASTERING_DISPLAY_METADATA,.buf=&static_buffer}};
    yuv.ff_side_data=sides; yuv.num_ff_side_data=2;
    yuv.params.color.hdr.max_luma=4000; yuv.params.color.hdr.max_pq_y=0.9f;
    params=yuv.params; resolve_frame_color_params(&yuv,&params);
    assert(!params.repr.dovi && params.color.hdr.max_luma==1000 && fabsf(params.color.hdr.min_luma-0.0001f)<0.000001f);
    assert(params.color.hdr.max_pq_y==0);
    dovi.header.disable_residual_flag=1;
    for (int profile=5;profile<=8;profile+=3) {
        dovi.header.vdr_rpu_profile=profile;
        params=yuv.params; assert(!dovi_requires_base_layer_fallback(&yuv));
        resolve_frame_color_params(&yuv,&params);
        assert(params.repr.dovi==yuv.params.repr.dovi && params.color.hdr.max_luma==4000 && params.color.hdr.max_pq_y==0.9f);
        frame.repr.bits=(struct pl_bit_encoding){.sample_depth=16,.color_depth=10,.bit_shift=6};
        apply_uploaded_frame_color(&frame,&params); bits(&frame,16,10,6);
        assert(frame.repr.dovi==yuv.params.repr.dovi && frame.repr.sys==PL_COLOR_SYSTEM_DOLBYVISION);
    }
    puts("PASS actual gpu_next upload: UNORM16, UINT16, YUV10/P010 bits, FLOAT, metadata, rejection, partial cleanup, RPU/base-layer/screenshot merge");
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='floe-gpu-upload-unit-') as temporary:
        directory = Path(temporary)
        unit = directory / 'test.c'
        hlg = re.search(r'(?m)^#define HLG_75[^\n]*', placebo)
        assert hlg
        unit.write_text(preamble + hlg[0] + '\n' + '\n'.join(fragments) + assertions)
        executable = directory / 'test'
        command = [args.cc, '-std=gnu11', '-O1', '-ffunction-sections', '-fdata-sections', '-Wno-deprecated-declarations',
                   '-I' + str(mpv / '_build'), '-I' + str(prefix), '-I' + str(mpv), str(unit), '-o', str(executable)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    main()
