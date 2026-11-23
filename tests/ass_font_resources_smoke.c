// Headless native font resource regression. Run with: font-directory output-directory [secondary].
// Place the black H.264 font-pixels.mp4 fixture in output-directory first.
// No application database or saved font preferences are read or changed.
#include <mpv/client.h>
#include <mpv/render.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#define mpv_create p_mpv_create
#define mpv_set_option_string p_mpv_set_option_string
#define mpv_request_log_messages p_mpv_request_log_messages
#define mpv_initialize p_mpv_initialize
#define mpv_render_context_create p_mpv_render_context_create
#define mpv_render_context_render p_mpv_render_context_render
#define mpv_command p_mpv_command
#define mpv_wait_event p_mpv_wait_event
#define mpv_get_property_string p_mpv_get_property_string
#define mpv_set_property_string p_mpv_set_property_string
#define mpv_error_string p_mpv_error_string
#define mpv_free p_mpv_free
#define mpv_render_context_free p_mpv_render_context_free
#define mpv_terminate_destroy p_mpv_terminate_destroy
static mpv_handle*(*p_mpv_create)(void);
static int(*p_mpv_set_option_string)(mpv_handle*,const char*,const char*);
static int(*p_mpv_request_log_messages)(mpv_handle*,const char*);
static int(*p_mpv_initialize)(mpv_handle*);
static int(*p_mpv_render_context_create)(mpv_render_context**,mpv_handle*,mpv_render_param*);
static int(*p_mpv_render_context_render)(mpv_render_context*,mpv_render_param*);
static int(*p_mpv_command)(mpv_handle*,const char**);
static mpv_event*(*p_mpv_wait_event)(mpv_handle*,double);
static char*(*p_mpv_get_property_string)(mpv_handle*,const char*);
static int(*p_mpv_set_property_string)(mpv_handle*,const char*,const char*);
static const char*(*p_mpv_error_string)(int);
static void(*p_mpv_free)(void*);
static void(*p_mpv_render_context_free)(mpv_render_context*);
static void(*p_mpv_terminate_destroy)(mpv_handle*);
static int bind_mpv(void){
 #ifdef __ANDROID__
 const char*library="libmpv.so";
#else
 const char*library="@rpath/libmpv.2.dylib";
#endif
 void*lib=dlopen(library,RTLD_NOW|RTLD_LOCAL);
 if(!lib){fprintf(stderr,"dlopen: %s\n",dlerror());return 0;}
#define BIND(name) p_##name=dlsym(lib,#name);if(!p_##name){fprintf(stderr,"missing %s\n",#name);return 0;}
 BIND(mpv_create);BIND(mpv_set_option_string);BIND(mpv_request_log_messages);BIND(mpv_initialize);BIND(mpv_render_context_create);BIND(mpv_render_context_render);BIND(mpv_command);BIND(mpv_wait_event);BIND(mpv_get_property_string);BIND(mpv_set_property_string);BIND(mpv_error_string);BIND(mpv_free);BIND(mpv_render_context_free);BIND(mpv_terminate_destroy);
#undef BIND
 return 1;
}
#define W 640
#define H 360
static int capture(const char* family,const char* fonts,const char* root,int n,int secondary) {
 char video[1024],sub[1024],output[1024];
 snprintf(video,sizeof(video),"%s/font-pixels.mp4",root);
 snprintf(sub,sizeof(sub),"%s/font-pixels.srt",root);
 snprintf(output,sizeof(output),"%s/font-pixels-%s-%d.ppm",root,secondary?"secondary":"primary",n);
 mpv_handle* h=mpv_create();mpv_render_context*ctx=NULL;
 if(!h)return 1;
 const char*opts[][2]={{"config","no"},{"vo","libmpv"},{"ao","null"},{"hwdec","no"},{"pause","yes"},{"keep-open","yes"},{"cache","no"},{"sub-auto","no"},{"sub-fonts-dir",fonts},{"sub-font-provider","none"},{"sub-font",family},{"sub-font-size","52"},{"sub-bold","no"},{"sub-border-size","0"},{"sub-shadow-offset","0"},{"sub-ass-override","force"},{"start","0"}};
 for(int i=0;i<(int)(sizeof(opts)/sizeof(opts[0]));i++)if(mpv_set_option_string(h,opts[i][0],opts[i][1])<0)return 2;
 if(secondary){const char*o[][2]={{"secondary-sub-style","independent"},{"secondary-sub-font",family},{"secondary-sub-font-size","52"},{"secondary-sub-bold","no"},{"secondary-sub-border-size","0"},{"secondary-sub-shadow-offset","0"},{"secondary-sub-ass-override","force"},{"sub-font","Roboto"},{"sub-visibility","no"}};for(int i=0;i<9;i++)if(mpv_set_option_string(h,o[i][0],o[i][1])<0)return 13;}
 mpv_request_log_messages(h,"debug");if(mpv_initialize(h)<0)return 3;
 if(mpv_render_context_create(&ctx,h,(mpv_render_param[]){{MPV_RENDER_PARAM_API_TYPE,MPV_RENDER_API_TYPE_SW},{0}})<0)return 4;
 uint8_t *pixels=calloc(W*H,4);int size[2]={W,H};size_t stride=W*4;
 mpv_render_param draw[]={{MPV_RENDER_PARAM_SW_SIZE,size},{MPV_RENDER_PARAM_SW_FORMAT,"rgb0"},{MPV_RENDER_PARAM_SW_STRIDE,&stride},{MPV_RENDER_PARAM_SW_POINTER,pixels},{0}};
 if(mpv_command(h,(const char*[]){"loadfile",video,NULL})<0)return 5;
 int loaded=0,added=0,white=0;uint64_t hash=1469598103934665603ULL;
 for(int i=0;i<300;i++){
  mpv_event*e=mpv_wait_event(h,.025);
  if(e->event_id==MPV_EVENT_LOG_MESSAGE){mpv_event_log_message*l=e->data;if(strstr(l->text,"fontselect")||strstr(l->text,"font provider")||strstr(l->text,"Failed"))fprintf(stderr,"%s: %s",l->prefix,l->text);}
  if(e->event_id==MPV_EVENT_FILE_LOADED)loaded=1;
  if(loaded&&!added){mpv_set_property_string(h,"demuxer-lavf-format","");int result=mpv_command(h,(const char*[]){"sub-add",sub,"select",NULL});if(result<0){fprintf(stderr,"sub-add error=%s\n",mpv_error_string(result));return 6;}if(secondary){char second[1024];snprintf(second,sizeof(second),"%s/font-pixels-secondary.srt",root);int e=mpv_command(h,(const char*[]){"sub-add",second,"auto",NULL});if(e<0)return 14;if(mpv_set_property_string(h,"secondary-sid","2")<0)return 15;}added=1;}
  if(mpv_render_context_render(ctx,draw)<0)return 7;
  white=0;for(int j=0;j<W*H;j++)white+=pixels[j*4]>64&&pixels[j*4+1]>64&&pixels[j*4+2]>64;
  if(white>100&&i>50)break;
 }
 for(int n=0;n<10000;n++){mpv_event*e=mpv_wait_event(h,0);if(e->event_id==MPV_EVENT_NONE)break;if(e->event_id==MPV_EVENT_LOG_MESSAGE){mpv_event_log_message*l=e->data;if(strstr(l->text,"fontselect")||strstr(l->text,"font provider")||strstr(l->text,"Failed"))fprintf(stderr,"%s: %s",l->prefix,l->text);}}
 char*selected=mpv_get_property_string(h,secondary?"secondary-sub-font":"sub-font");char*text=mpv_get_property_string(h,secondary?"secondary-sub-text":"sub-text");
 FILE*f=fopen(output,"wb");if(!f)return 8;fprintf(f,"P6\n%d %d\n255\n",W,H);
 for(int j=0;j<W*H;j++){fwrite(pixels+j*4,1,3,f);for(int c=0;c<3;c++){hash^=pixels[j*4+c];hash*=1099511628211ULL;}}fclose(f);
 printf("LIBMPV_ASS_PIXELS slot=%s family=%s selected=%s active_text=%s visible_pixels=%d hash=%llu path=%s\n",secondary?"secondary":"primary",family,selected?selected:"missing",text?text:"missing",white,(unsigned long long)hash,output);
 int good=loaded&&added&&white>100&&selected&&!strcmp(selected,family)&&text&&strstr(text,"iiii");
 mpv_free(selected);mpv_free(text);free(pixels);mpv_render_context_free(ctx);mpv_terminate_destroy(h);
 return good?0:9;
}
int main(int argc,char**argv){
 if(!bind_mpv())return 99;if(argc!=3&&argc!=4)return 10;int secondary=argc==4&&!strcmp(argv[3],"secondary");char name[1024];FILE*f;
 snprintf(name,sizeof(name),"%s/font-pixels.srt",argv[2]);f=fopen(name,"wb");if(!f)return 12;fputs("1\n00:00:00,000 --> 00:00:10,000\niiiiiiii WWWWWWWW 字幕弹幕\n",f);fclose(f);
 snprintf(name,sizeof(name),"%s/font-pixels-secondary.srt",argv[2]);f=fopen(name,"wb");if(!f)return 12;fputs("1\n00:00:00,000 --> 00:00:10,000\niiiiiiii WWWWWWWW 字幕弹幕\n",f);fclose(f);
 const char*families[]={"Roboto","Noto Serif CJK SC","Droid Sans Mono"};for(int i=0;i<3;i++){int result=capture(families[i],argv[1],argv[2],i,secondary);if(result)return 20+result;}
 puts("LIBMPV_ASS_PIXELS_OK three system families rendered visible subtitles");return 0;
}
