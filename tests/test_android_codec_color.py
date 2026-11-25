"""Exercise the production MediaCodec input color packet without a device."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def added_function(patch, name):
    added = '\n'.join(line[1:] for line in patch.read_text().splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    start = added.index(name)
    start = added.rfind('\n', 0, start) + 1
    depth = 0
    for i in range(added.index('{', start), len(added)):
        depth += (added[i] == '{') - (added[i] == '}')
        if depth == 0:
            return added[start:i+1]
    raise AssertionError(name)


class CodecColorTest(unittest.TestCase):
    def test_hdr_sdr_unspecified_and_static_metadata(self):
        function = added_function(ROOT / 'buildscripts/patches/ffmpeg/zzzzzzz-android-codec-color.patch',
                                  'mediacodec_set_input_color(')
        stub = r'''
#include <assert.h>
#include <stdint.h>
#include <math.h>
#include <string.h>
#define COLOR_RANGE_UNSPECIFIED 0
#define COLOR_STANDARD_UNSPECIFIED 0
#define COLOR_TRANSFER_UNSPECIFIED 0
#define COLOR_TRANSFER_ST2084 6
#define AV_PKT_DATA_MASTERING_DISPLAY_METADATA 1
#define AV_PKT_DATA_CONTENT_LIGHT_LEVEL 2
#define AV_WL16(p,v) do{(p)[0]=(v)&255;(p)[1]=(v)>>8;}while(0)
typedef struct {int num,den;} AVRational;
static double av_q2d(AVRational q){return (double)q.num/q.den;}
typedef struct {AVRational display_primaries[3][2],white_point[2],min_luminance,max_luminance;int has_primaries,has_luminance;} AVMasteringDisplayMetadata;
typedef struct {unsigned MaxCLL,MaxFALL;} AVContentLightMetadata;
typedef struct {void *data;size_t size;} AVPacketSideData;
typedef struct {int color_range,colorspace,color_trc;AVPacketSideData md,cl;} AVCodecContext;
typedef struct {int range,standard,transfer,sets;uint8_t hdr[25];int hdr_size;} FFAMediaFormat;
static int ff_AMediaFormatColorRange_from_AVColorRange(int v){return v==1?2:v==2?1:0;}
static int ff_AMediaFormatColorStandard_from_AVColorSpace(int v){return v==9?6:v==1?1:0;}
static int ff_AMediaFormatColorTransfer_from_AVColorTransfer(int v){return v==16?6:v==18?7:v==6?3:0;}
static const AVPacketSideData *ff_get_coded_side_data(AVCodecContext *c,int t){return t==1?&c->md:&c->cl;}
static void ff_AMediaFormat_setInt32(FFAMediaFormat *f,const char *k,int v){f->sets++;if(!strcmp(k,"color-range"))f->range=v;else if(!strcmp(k,"color-standard"))f->standard=v;else if(!strcmp(k,"color-transfer"))f->transfer=v;else assert(0);}
static void ff_AMediaFormat_setBuffer(FFAMediaFormat *f,const char *k,void *v,size_t n){assert(!strcmp(k,"hdr-static-info")&&n==25);memcpy(f->hdr,v,n);f->hdr_size=n;}
static unsigned field(FFAMediaFormat *f,int i){return f->hdr[1+2*i]|f->hdr[2+2*i]<<8;}
'''
        cases = r'''
int main(void){
 AVCodecContext c={0};FFAMediaFormat f={0};
 mediacodec_set_input_color(&c,&f);assert(f.sets==0&&!f.hdr_size);
 c=(AVCodecContext){.color_range=1,.colorspace=1,.color_trc=6};
 mediacodec_set_input_color(&c,&f);assert(f.range==2&&f.standard==1&&f.transfer==3&&!f.hdr_size);
 c=(AVCodecContext){.color_range=1,.colorspace=9,.color_trc=18};f=(FFAMediaFormat){0};
 mediacodec_set_input_color(&c,&f);assert(f.standard==6&&f.transfer==7&&!f.hdr_size);
 AVMasteringDisplayMetadata md={.display_primaries={{{68,100},{32,100}},{{265,1000},{69,100}},{{15,100},{6,100}}},.white_point={{3127,10000},{3290,10000}},.min_luminance={1,1000},.max_luminance={1000,1},.has_primaries=1,.has_luminance=1};
 AVContentLightMetadata cl={1200,400};
 c.color_trc=16;c.md=(AVPacketSideData){&md,sizeof(md)};c.cl=(AVPacketSideData){&cl,sizeof(cl)};f=(FFAMediaFormat){0};
 mediacodec_set_input_color(&c,&f);
 assert(f.range==2&&f.standard==6&&f.transfer==6&&f.hdr_size==25&&f.hdr[0]==0);
 assert(field(&f,0)==34000&&field(&f,1)==16000&&field(&f,6)==15635&&field(&f,7)==16450);
 assert(field(&f,8)==1000&&field(&f,9)==10&&field(&f,10)==1200&&field(&f,11)==400);
 md.max_luminance=(AVRational){100000,1};md.min_luminance=(AVRational){0,0};cl.MaxCLL=100000;
 f=(FFAMediaFormat){0};mediacodec_set_input_color(&c,&f);assert(field(&f,8)==65535&&field(&f,9)==0&&field(&f,10)==65535);
 c.md.size=1;c.cl.size=1;f=(FFAMediaFormat){0};mediacodec_set_input_color(&c,&f);assert(!f.hdr_size);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'color.c';source.write_text(stub+function+cases)
            exe = Path(tmp)/'color'
            subprocess.run(['cc','-std=c11','-Wall',str(source),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    unittest.main()
