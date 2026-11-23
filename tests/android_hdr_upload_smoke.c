// Native GLES regression for the actual gpu-next libmpv render API.
// Arguments: SDR H.264 file, PQ Main10 HEVC file, optional "p010" conversion.
// Prepare /data/local/tmp/floe-native-20261122 before running. The directory is
// private to this standalone verification process; no app preferences are used.
// This tool asserts real output formats and UINT16 texture calls, not just
// decoded dimensions or matching black buffers.
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <mpv/client.h>
#include <mpv/render.h>
#include <mpv/render_gl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
static int force_p010;
static int uint16_uploads, norm16_uploads, has_norm16;
static void record_format(GLenum format) {
 if(format==GL_R16UI||format==GL_RG16UI)uint16_uploads++;
 if(format==GL_R16_EXT||format==GL_RG16_EXT)norm16_uploads++;
}
static void store2d(GLenum target,GLsizei levels,GLenum format,GLsizei w,GLsizei h) {
 record_format(format);glTexStorage2D(target,levels,format,w,h);
}
static void image2d(GLenum target,GLint level,GLint internal,GLsizei w,GLsizei h,GLint border,GLenum format,GLenum type,const void*pixels) {
 record_format(internal);glTexImage2D(target,level,internal,w,h,border,format,type,pixels);
}
static void updated(void *ctx) {}
static void *proc(void *ctx,const char *name){
 if(!strcmp(name,"glTexStorage2D"))return (void*)store2d;
 if(!strcmp(name,"glTexImage2D"))return (void*)image2d;
 return (void*)eglGetProcAddress(name);
}
static int capture(const char *file,int hdr,int policy,uint8_t*out){
 mpv_handle*h=mpv_create();mpv_render_context*ctx=NULL;
 const char*opts[][2]={{"config","no"},{"vo","libmpv"},{"ao","null"},{"hwdec","no"},{"pause","yes"},{"keep-open","yes"},{"hdr-compute-peak","auto"},{"hdr-peak-percentile","100"}};
 for(int i=0;i<8;i++)if(mpv_set_option_string(h,opts[i][0],opts[i][1])<0){printf("bad option %s=%s\n",opts[i][0],opts[i][1]);return 1;}
 if(hdr&&mpv_set_option_string(h,"vf",force_p010?"format=fmt=p010:colormatrix=bt.2020-ncl:primaries=bt.2020:gamma=pq:max-luma=4000":"format=colormatrix=bt.2020-ncl:primaries=bt.2020:gamma=pq:max-luma=4000")<0)return 1;
 if(!hdr&&force_p010&&mpv_set_option_string(h,"vf","format=fmt=p010")<0)return 1;
 if(policy){const char*o[][2]={{"target-colorspace-hint","no"},{"target-prim","bt.709"},{"target-trc","srgb"},{"target-peak","203"}};for(int i=0;i<4;i++)if(mpv_set_option_string(h,o[i][0],o[i][1])<0)return 1;}
 mpv_request_log_messages(h,"warn");int init_status=mpv_initialize(h);if(init_status<0){printf("init status=%d\n",init_status);return 2;}
 mpv_opengl_init_params init={.get_proc_address=proc};
 int advanced=1;int status=mpv_render_context_create(&ctx,h,(mpv_render_param[]){{MPV_RENDER_PARAM_API_TYPE,MPV_RENDER_API_TYPE_OPENGL},{MPV_RENDER_PARAM_BACKEND,"gpu-next"},{MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,&init},{MPV_RENDER_PARAM_ADVANCED_CONTROL,&advanced},{0}});
 if(status<0){printf("render create=%d\n",status);return 3;}mpv_render_context_set_update_callback(ctx,updated,NULL);
 GLuint tex,fbo;glGenTextures(1,&tex);glBindTexture(GL_TEXTURE_2D,tex);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,64,32,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,tex,0);
 mpv_opengl_fbo target={.fbo=fbo,.w=64,.h=32};int block=0;
 uint16_uploads=norm16_uploads=0;
 if(mpv_command(h,(const char*[]){"loadfile",file,NULL})<0)return 4;
 int loaded=0;for(int i=0;i<180;i++){usleep(10000);mpv_event*e=mpv_wait_event(h,.01);if(e->event_id==MPV_EVENT_LOG_MESSAGE){mpv_event_log_message*l=e->data;fprintf(stderr,"%s: %s",l->prefix,l->text);}loaded|=e->event_id==MPV_EVENT_FILE_LOADED;mpv_render_context_update(ctx);status=mpv_render_context_render(ctx,(mpv_render_param[]){{MPV_RENDER_PARAM_OPENGL_FBO,&target},{MPV_RENDER_PARAM_BLOCK_FOR_TARGET_TIME,&block},{0}});if(loaded&&i>140&&status>=0)break;}
 glBindFramebuffer(GL_FRAMEBUFFER,fbo);glReadPixels(0,0,64,32,GL_RGBA,GL_UNSIGNED_BYTE,out);glFinish();
 char path[256];snprintf(path,sizeof(path),"/data/local/tmp/floe-native-20261122/hdr-target-%d-%d.ppm",hdr,policy);FILE*fileout=fopen(path,"wb");if(fileout){fprintf(fileout,"P6\n64 32\n255\n");for(int p=0;p<64*32;p++)fwrite(out+p*4,1,3,fileout);fclose(fileout);}
 char shot[256];snprintf(shot,sizeof(shot),"/data/local/tmp/floe-native-20261122/hdr-shot-%d-%d.png",hdr,policy);unlink(shot);
 int shot_status=mpv_command_async(h,73,(const char*[]){"screenshot-to-file",shot,"video",NULL});
 int shot_ready=0;struct stat st;
 for(int n=0;shot_status>=0&&n<160;n++){usleep(10000);mpv_event*e=mpv_wait_event(h,.01);if(e->event_id==MPV_EVENT_COMMAND_REPLY&&e->reply_userdata==73)shot_status=e->error;mpv_render_context_update(ctx);mpv_render_context_render(ctx,(mpv_render_param[]){{MPV_RENDER_PARAM_OPENGL_FBO,&target},{MPV_RENDER_PARAM_BLOCK_FOR_TARGET_TIME,&block},{0}});if(!stat(shot,&st)&&st.st_size>64){shot_ready=1;break;}}
 printf("ANDROID_GPU_SCREENSHOT hdr=%d policy=%d status=%d saved=%d\n",hdr,policy,shot_status,shot_ready);
 char*format=mpv_get_property_string(h,"video-out-params/pixelformat");
 printf("loaded=%d render=%d format=%s uint16_textures=%d norm16_textures=%d\n",loaded,status,format?format:"unknown",uint16_uploads,norm16_uploads);
 int format_ok=!force_p010||(format&&!strncmp(format,"p010",4));
 int upload_ok=((!hdr&&!force_p010)||has_norm16) ? uint16_uploads==0 : uint16_uploads>0;
 mpv_free(format);mpv_render_context_free(ctx);mpv_terminate_destroy(h);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&tex);return loaded&&status>=0&&format_ok&&upload_ok&&shot_ready?0:5;
}
int main(int argc,char**argv){
 if(argc!=3&&argc!=4)return 1;force_p010=argc==4&&!strcmp(argv[3],"p010");EGLDisplay d=eglGetDisplay(EGL_DEFAULT_DISPLAY);EGLint major,minor;if(!eglInitialize(d,&major,&minor))return 2;
 EGLConfig cfg;EGLint n;EGLint attrs[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES2_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};if(!eglChooseConfig(d,attrs,&cfg,1,&n)||!n)return 3;
 EGLint s[]={EGL_WIDTH,64,EGL_HEIGHT,32,EGL_NONE};EGLSurface surf=eglCreatePbufferSurface(d,cfg,s);EGLint a[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};EGLContext ctx=eglCreateContext(d,cfg,EGL_NO_CONTEXT,a);if(!eglMakeCurrent(d,surf,surf,ctx))return 4;
 GLint extension_count=0;glGetIntegerv(GL_NUM_EXTENSIONS,&extension_count);
 for(int i=0;i<extension_count;i++){const char*name=(const char*)glGetStringi(GL_EXTENSIONS,i);if(name&&!strcmp(name,"GL_EXT_texture_norm16"))has_norm16=1;}
 printf("GLES %s force_p010=%d norm16_extension=%d\n",glGetString(GL_VERSION),force_p010,has_norm16);
 for(int hdr=0;hdr<2;hdr++){uint8_t b[8192],p[8192];int a=capture(argv[hdr+1],hdr,0,b),z=a?0:capture(argv[hdr+1],hdr,1,p);if(a||z){printf("capture status %d/%d\n",a,z);return 5;}int max=0,color=0;for(int i=0;i<8192;i++){if(i%4==3)continue;int diff=abs((int)b[i]-p[i]);if(diff>max)max=diff;color|=b[i]>32;}printf("ANDROID_TARGET hdr=%d max_channel_delta=%d\n",hdr,max);if(!color||max>2)return 6;}
 puts("LIBMPV_ANDROID_SDR_TARGET_OK real GLES HDR/SDR pixels preserve default output");eglTerminate(d);return 0;
}
