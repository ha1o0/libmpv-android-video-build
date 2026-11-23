"""Run the production header fallback with controlled libavcodec responses."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AndroidHdrMetadataTest(unittest.TestCase):
    def test_missing_headers_sdr_and_explicit_container_colors(self):
        patch = ROOT / 'buildscripts/patches/mpv/android_hdr_surface.patch'
        added = '\n'.join(line[1:] for line in patch.read_text().splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        start = added.index('struct pl_color_space mp_get_codec_color_hint(')
        function = added[start:added.index('\n}', start) + 2]
        stub = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#define STREAM_VIDEO 1
#define AV_CODEC_ID_HEVC 173
struct pl_color_space {int transfer,primaries;};
struct mp_codec_params {int type;struct pl_color_space color;};
typedef struct {int codec_id,color_trc,color_primaries,extradata_size;void *extradata;} AVCodecParameters;
typedef struct {int color_trc,color_primaries,thread_count;} AVCodecContext;
typedef struct {int unused;} AVCodec;
static AVCodecParameters params;
static int opens,allocated,freed,open_result,context_result;
static int header_transfer,header_primaries;
static bool decoder_available=true;
static int pl_transfer_from_av(int v){return v==2?0:v;}
static int pl_primaries_from_av(int v){return v==2?0:v;}
static AVCodecParameters *mp_codec_params_to_av(const struct mp_codec_params *c){allocated++;return &params;}
static void avcodec_parameters_free(AVCodecParameters **p){freed++;*p=NULL;}
static const AVCodec *avcodec_find_decoder(int id){static AVCodec codec;return decoder_available?&codec:NULL;}
static AVCodecContext *avcodec_alloc_context3(const AVCodec *c){return calloc(1,sizeof(AVCodecContext));}
static int avcodec_parameters_to_context(AVCodecContext *c,const AVCodecParameters *p){return context_result;}
static int avcodec_open2(AVCodecContext *c,const AVCodec *d,void *o){assert(c->thread_count==1);opens++;c->color_trc=header_transfer;c->color_primaries=header_primaries;return open_result;}
static void avcodec_free_context(AVCodecContext **c){free(*c);*c=NULL;}
'''
        cases = r'''
int main(void) {
 struct mp_codec_params c={.type=STREAM_VIDEO};
 params=(AVCodecParameters){AV_CODEC_ID_HEVC,2,2,100,(void *)1};
 header_transfer=16;header_primaries=9;
 struct pl_color_space result=mp_get_codec_color_hint(&c);
 assert(result.transfer==16&&result.primaries==9&&opens==1);
 assert(c.color.transfer==0&&c.color.primaries==0);
 assert(allocated==freed);

 c.color=(struct pl_color_space){1,1};
 result=mp_get_codec_color_hint(&c);
 assert(result.transfer==1&&result.primaries==1&&opens==1);
 c.type=2;c.color=(struct pl_color_space){0};
 result=mp_get_codec_color_hint(&c);assert(result.transfer==0&&opens==1);

 c.type=STREAM_VIDEO;
 params.color_trc=18;params.color_primaries=9;
 result=mp_get_codec_color_hint(&c);
 assert(result.transfer==18&&result.primaries==9&&opens==1);

 params.color_trc=params.color_primaries=2;
 header_transfer=1;header_primaries=1;
 result=mp_get_codec_color_hint(&c);
 assert(result.transfer==1&&result.primaries==1&&opens==2);
 c.color.transfer=1;header_transfer=16;header_primaries=9;
 result=mp_get_codec_color_hint(&c);
 assert(result.transfer==1&&result.primaries==9&&opens==3);

 c.color=(struct pl_color_space){0};open_result=-1;
 result=mp_get_codec_color_hint(&c);
 assert(result.transfer==0&&result.primaries==0&&opens==4);
 context_result=-1;
 result=mp_get_codec_color_hint(&c);assert(result.transfer==0&&opens==4);
 context_result=0;decoder_available=false;
 result=mp_get_codec_color_hint(&c);assert(result.transfer==0&&opens==4);
 decoder_available=true;open_result=0;
 params.extradata_size=0;
 result=mp_get_codec_color_hint(&c);assert(result.transfer==0&&opens==4);
 params.extradata_size=0x1000001;
 result=mp_get_codec_color_hint(&c);assert(result.transfer==0&&opens==4);
 params.extradata_size=100;params.codec_id=1;
 result=mp_get_codec_color_hint(&c);assert(result.transfer==0&&opens==4);
 assert(allocated==freed);
 puts("HDR header fallback, SDR, container precedence and invalid input passed");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'metadata.c'
            binary = Path(directory) / 'metadata'
            source.write_text(stub + function + cases)
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11',
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
