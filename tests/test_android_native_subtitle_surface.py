"""Exercise the production direct-output subtitle compositor without a device."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeSubtitleSurfaceTests(unittest.TestCase):
    def test_timestamp_changes_clear_and_rgba_composition(self):
        patch = ROOT / 'buildscripts/patches/mpv/zzz-android-native-subtitle-surface.patch'
        added = '\n'.join(line[1:] for line in patch.read_text().splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        start = added.index('static void draw_subtitles(')
        # This function is added as a complete block in the production patch.
        depth, end = 0, start
        for i in range(added.index('{', start), len(added)):
            depth += (added[i] == '{') - (added[i] == '}')
            if depth == 0:
                end = i + 1
                break
        function = added[start:end]
        stub = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define MP_DBG(...) ((void)0)
#define MP_ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct mp_rect {int x0,y0,x1,y1;};
#define MPMIN(a,b) ((a)<(b)?(a):(b))
#define MPMAX(a,b) ((a)>(b)?(a):(b))
#define WINDOW_FORMAT_RGBA_8888 1
typedef int ANativeWindow;
typedef struct {int width,height,stride;void *bits;} ANativeWindow_Buffer;
struct mp_image {uint8_t *planes[4];int stride[4];};
struct mp_osd_res {int w,h;double display_par;};
struct sub_bitmap_list {int64_t change_id;};
struct priv {ANativeWindow *subtitle_window;void *subtitle_cache;
int64_t subtitle_change_id;int subtitle_width,subtitle_height;bool have_subtitle_frame;};
struct opts {struct {int w,h;} android_surface_size;};
struct vo {struct priv *priv;struct opts *opts;void *osd;};
static uint8_t input[32], output[32];
static struct mp_image image={.planes={input},.stride={16}};
static int writes,geometry,fail_lock;
static double observed_pts;
static struct sub_bitmap_list list={1};
static const bool mp_draw_sub_formats[]={true};
static struct sub_bitmap_list *osd_render(void *o,struct mp_osd_res r,double t,int f,const bool *fmt){observed_pts=t;return &list;}
static struct mp_image *mp_draw_sub_overlay(void *c,struct sub_bitmap_list *l,void *a,int ma,int *na,void *m,int mm,int *nm){assert(a && ma > 0 && m && mm > 0);return &image;}
static void talloc_free(void *p){}
static int ANativeWindow_setBuffersGeometry(ANativeWindow *w,int x,int y,int f){geometry++;return 0;}
static int ANativeWindow_lock(ANativeWindow *w,ANativeWindow_Buffer *b,void *r){if(fail_lock)return -1;*b=(ANativeWindow_Buffer){4,2,4,output};return 0;}
static int ANativeWindow_unlockAndPost(ANativeWindow *w){writes++;return 0;}
'''
        cases = r'''
int main(void){
 ANativeWindow window=1;struct priv p={.subtitle_window=&window,.subtitle_cache=&window};
 struct opts opts={.android_surface_size={4,2}};struct vo vo={&p,&opts};
 input[0]=10;input[1]=20;input[2]=30;input[3]=128;
 draw_subtitles(&vo,2.75);
 assert(observed_pts==2.75 && writes==1 && geometry==1);
 assert(output[0]==30 && output[1]==20 && output[2]==10 && output[3]==128);
 draw_subtitles(&vo,3);assert(writes==1 && observed_pts==3);
 memset(input,0,sizeof input);list.change_id++;
 draw_subtitles(&vo,4);assert(writes==2);
 for(int i=0;i<32;i++)assert(output[i]==0);
 fail_lock=1;list.change_id++;draw_subtitles(&vo,5);assert(writes==2);
 fail_lock=0;draw_subtitles(&vo,5);assert(writes==3);
 p.subtitle_window=NULL;draw_subtitles(&vo,6);assert(writes==3);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            c = Path(temp) / 'test.c'
            c.write_text(stub + function + cases)
            exe = Path(temp) / 'test'
            subprocess.run(['cc', '-std=c11', str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
