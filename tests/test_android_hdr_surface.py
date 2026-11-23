"""Compile the production EGL negotiation functions with a deterministic driver.

The real device smoke probe separately verifies its EGL extensions/configs. This
suite covers driver rejection and metadata/capability combinations without a GPU.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'buildscripts/patches/mpv/android_hdr_surface.patch'


def production_functions():
    additions = '\n'.join(line[1:] for line in PATCH.read_text().splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
    return additions[additions.index('static int android_refine_config'):
                     additions.index('static pl_color_space_t android_preferred_csp')]


class AndroidHdrSurfaceTest(unittest.TestCase):
    def test_source_display_depth_and_driver_must_agree(self):
        stub = r'''
#include <assert.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef int EGLint;
typedef int EGLConfig;
typedef int EGLSurface;
typedef int EGLNativeWindowType;
typedef int ANativeWindow;
#define EGL_NO_SURFACE 0
#define EGL_NO_CONTEXT 0
#define EGL_NONE 0
#define EGL_GL_COLORSPACE_KHR 1
#define EGL_RED_SIZE 2
#define EGL_GREEN_SIZE 3
#define EGL_BLUE_SIZE 4
#define EGL_ALPHA_SIZE 5
#define EGL_EXTENSIONS 6
#define EGL_GL_COLORSPACE_BT2020_PQ_EXT 10
#define EGL_GL_COLORSPACE_BT2020_HLG_EXT 11
#define EGL_SMPTE2086_DISPLAY_PRIMARY_RX_EXT 20
#define EGL_SMPTE2086_DISPLAY_PRIMARY_RY_EXT 21
#define EGL_SMPTE2086_DISPLAY_PRIMARY_GX_EXT 22
#define EGL_SMPTE2086_DISPLAY_PRIMARY_GY_EXT 23
#define EGL_SMPTE2086_DISPLAY_PRIMARY_BX_EXT 24
#define EGL_SMPTE2086_DISPLAY_PRIMARY_BY_EXT 25
#define EGL_SMPTE2086_WHITE_POINT_X_EXT 26
#define EGL_SMPTE2086_WHITE_POINT_Y_EXT 27
#define EGL_SMPTE2086_MAX_LUMINANCE_EXT 28
#define EGL_SMPTE2086_MIN_LUMINANCE_EXT 29
#define EGL_CTA861_3_MAX_CONTENT_LIGHT_LEVEL_EXT 30
#define EGL_CTA861_3_MAX_FRAME_AVERAGE_LEVEL_EXT 31
#define EGL_METADATA_SCALING_EXT 50000
#define MP_ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MP_WARN(...) ((void)0)
#define MP_ERR(...) ((void)0)
#define MP_INFO(...) ((void)0)
#define PL_COLOR_TRC_PQ 1
#define PL_COLOR_TRC_HLG 2
#define PL_COLOR_TRC_SRGB 3
#define PL_COLOR_PRIM_BT_2020 1
struct xy {float x,y;};
struct pl_raw_primaries {struct xy red,green,blue,white;};
struct pl_hdr_metadata {struct pl_raw_primaries prim;float max_luma,min_luma,max_cll,max_fall;};
struct pl_color_space {int transfer,primaries;struct pl_hdr_metadata hdr;};
struct pl_bit_encoding {int sample_depth,color_depth;};
struct mp_image_params {struct pl_color_space color;struct {struct pl_bit_encoding bits;} repr;};
static const struct pl_color_space pl_color_space_srgb={.transfer=PL_COLOR_TRC_SRGB,.primaries=2};
struct opts {int android_hdr_capabilities;};
struct vo {struct opts *opts;};
struct priv {int egl_display,egl_config,egl_context,egl_surface,colorspace,logged_colorspace,depth;bool hdr_failed;};
struct ra_ctx {struct priv *priv;struct vo *vo;};
static int creates,destroys,reject_hdr,fail_make_current,metadata[32];
static const char *extensions;
static ANativeWindow native_window;
static bool gl_check_extension(const char *ext,const char *name){return strstr(ext,name)!=NULL;}
static ANativeWindow *vo_android_native_window(struct vo *v){return &native_window;}
static const char *eglQueryString(int d,int k){return extensions;}
static bool eglGetConfigAttrib(int d,int config,int key,int *value){*value=key==EGL_ALPHA_SIZE?(config==10?2:8):config;return true;}
static int eglCreateWindowSurface(int d,int c,int w,const int *attr){creates++;return attr&&reject_hdr?0:creates;}
static bool eglMakeCurrent(int d,int r,int w,int c){return !r||!fail_make_current;}
static bool eglDestroySurface(int d,int s){destroys++;return true;}
static bool eglSurfaceAttrib(int d,int s,int key,int value){metadata[key]=value;return true;}
static bool pl_primaries_valid(const struct pl_raw_primaries *p){return p->red.x>0;}
static const struct pl_raw_primaries *pl_raw_primaries_get(int p){static const struct pl_raw_primaries v={{.708,.292},{.170,.797},{.131,.046},{.3127,.329}};return &v;}
'''
        cases = r'''
int main(void) {
 const char *all="EGL_EXT_gl_colorspace_bt2020_pq EGL_EXT_gl_colorspace_bt2020_hlg EGL_EXT_surface_SMPTE2086_metadata EGL_EXT_surface_CTA861_3_metadata";
 for(int mask=0;mask<4;mask++)for(int depth=8;depth<=10;depth+=2)
 for(int transfer=1;transfer<=3;transfer++)for(int prim=1;prim<=2;prim++)
 for(int ext=0;ext<2;ext++)for(int reject=0;reject<2;reject++) {
  struct opts opts={mask};struct vo vo={&opts};
  struct priv p={.depth=depth,.egl_surface=1,.egl_context=1};struct ra_ctx ctx={&p,&vo};
  struct mp_image_params params={.color={.transfer=transfer,.primaries=prim,.hdr={.max_luma=1000,.min_luma=.005,.max_cll=900,.max_fall=400}}};
  extensions=ext?all:"";reject_hdr=reject;creates=destroys=0;memset(metadata,0,sizeof(metadata));
  bool handled=android_set_color(&ctx,&params);
  if(!mask){assert(!handled);assert(creates==0);continue;}
  bool hdr=depth==10&&prim==1&&ext&&!reject&&((transfer==1&&(mask&1))||(transfer==2&&(mask&2)));
  assert(handled);assert(params.color.transfer==(hdr?transfer:PL_COLOR_TRC_SRGB));
  assert(p.egl_surface!=0);assert(p.egl_context==1);
  assert(params.repr.bits.color_depth==depth);
  if(hdr&&transfer==1){assert(metadata[28]==50000000);assert(metadata[30]==45000000);}
  int initialCreates=creates;
  android_set_color(&ctx,&params);assert(creates==initialCreates);
  android_set_color(&ctx,NULL);assert(p.colorspace==0);assert(p.egl_surface!=0);
 }
 struct opts opts={3};struct vo vo={&opts};struct priv p={.depth=10,.egl_surface=1,.egl_context=1};struct ra_ctx ctx={&p,&vo};
 EGLConfig configs[]={8,10};assert(android_refine_config(&ctx,configs,2)==1);opts.android_hdr_capabilities=0;assert(android_refine_config(&ctx,configs,2)==0);
 opts.android_hdr_capabilities=3;extensions=all;reject_hdr=0;
 struct mp_image_params params={.color={.transfer=PL_COLOR_TRC_PQ,.primaries=1}};
 assert(android_set_color(&ctx,&params));assert(p.colorspace==10);
 params.color.transfer=PL_COLOR_TRC_HLG;assert(android_set_color(&ctx,&params));assert(p.colorspace==11);
 params.color=pl_color_space_srgb;assert(android_set_color(&ctx,&params));assert(p.colorspace==0);
 puts("Android HDR negotiation, SDR restoration, metadata and EGL context retention passed");
}
'''
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'probe.c'
            exe = Path(td) / 'probe'
            src.write_text(stub + production_functions() + cases)
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wno-pointer-to-int-cast',
                            str(src), '-lm', '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
