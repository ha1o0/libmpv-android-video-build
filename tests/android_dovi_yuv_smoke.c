/* Check raw 10-bit external sampling on a real Android GPU without a window,
 * media playback, screenshots or image files. The input is a synthetic P010
 * gradient; only numeric error statistics leave the device.
 * SPDX-License-Identifier: LGPL-2.1-or-later
 */
#include <android/hardware_buffer.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <GLES2/gl2ext.h>
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WIDTH 64
#define HEIGHT 32

static GLuint shader(GLenum type, const char *source)
{
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &source, NULL);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "Shader: %s\n", log);
        exit(1);
    }
    return s;
}

int main(void)
{
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    assert(eglInitialize(display, NULL, NULL));
    const EGLint attrs[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8, EGL_NONE};
    EGLConfig config;
    EGLint count;
    assert(eglChooseConfig(display, attrs, &config, 1, &count) && count);
    const EGLint context_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attrs);
    const EGLint surface_attrs[] = {EGL_WIDTH, WIDTH, EGL_HEIGHT, HEIGHT, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, surface_attrs);
    assert(eglMakeCurrent(display, surface, surface, context));
    const char *exts = (const char *)glGetString(GL_EXTENSIONS);
    assert(exts && strstr(exts, "GL_EXT_YUV_target"));
    assert(strstr(exts, "GL_EXT_color_buffer_float"));

    AHardwareBuffer_Desc desc = {.width = WIDTH, .height = HEIGHT, .layers = 1,
        .format = AHARDWAREBUFFER_FORMAT_YCbCr_P010,
        .usage = AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN |
                 AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE};
    AHardwareBuffer *buffer = NULL;
    assert(AHardwareBuffer_allocate(&desc, &buffer) == 0);
    AHardwareBuffer_Planes planes;
    assert(AHardwareBuffer_lockPlanes(buffer, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN,
                                     -1, NULL, &planes) == 0);
    assert(planes.planeCount == 3);
    for (int plane = 0; plane < 3; plane++) {
        int w = plane ? WIDTH / 2 : WIDTH, h = plane ? HEIGHT / 2 : HEIGHT;
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                uint16_t value = (plane == 0 ? 64 + x : plane == 1 ? 256 : 768) << 6;
                uint8_t *at = (uint8_t *)planes.planes[plane].data +
                    y * planes.planes[plane].rowStride + x * planes.planes[plane].pixelStride;
                memcpy(at, &value, sizeof(value));
            }
        }
    }
    assert(AHardwareBuffer_unlock(buffer, NULL) == 0);

    PFNEGLGETNATIVECLIENTBUFFERANDROIDPROC client_buffer =
        (void *)eglGetProcAddress("eglGetNativeClientBufferANDROID");
    PFNEGLCREATEIMAGEKHRPROC create_image = (void *)eglGetProcAddress("eglCreateImageKHR");
    PFNEGLDESTROYIMAGEKHRPROC destroy_image = (void *)eglGetProcAddress("eglDestroyImageKHR");
    PFNGLEGLIMAGETARGETTEXTURE2DOESPROC bind_image =
        (void *)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    assert(client_buffer && create_image && destroy_image && bind_image);
    EGLImageKHR image = create_image(display, EGL_NO_CONTEXT, EGL_NATIVE_BUFFER_ANDROID,
                                    client_buffer(buffer), NULL);
    assert(image != EGL_NO_IMAGE_KHR);
    GLuint input, output, fbo;
    glGenTextures(1, &input);
    glBindTexture(GL_TEXTURE_EXTERNAL_OES, input);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    bind_image(GL_TEXTURE_EXTERNAL_OES, image);
    assert(glGetError() == GL_NO_ERROR);

    glGenTextures(1, &output);
    glBindTexture(GL_TEXTURE_2D, output);
    glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA32F, WIDTH, HEIGHT);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, output, 0);
    assert(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
    const char *vs = "#version 300 es\n"
        "void main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);"
        "gl_Position=vec4(p*2.0-1.0,0,1);}";
    const char *fs = "#version 300 es\n#extension GL_EXT_YUV_target : require\n"
        "precision highp float; precision highp __samplerExternal2DY2YEXT;\n"
        "uniform __samplerExternal2DY2YEXT source; out vec4 color;\n"
        "void main(){color=texture(source,gl_FragCoord.xy/vec2(64,32));}";
    GLuint v = shader(GL_VERTEX_SHADER, vs), f = shader(GL_FRAGMENT_SHADER, fs);
    GLuint program = glCreateProgram();
    glAttachShader(program, v);
    glAttachShader(program, f);
    glLinkProgram(program);
    GLint linked;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    assert(linked);
    glUseProgram(program);
    glUniform1i(glGetUniformLocation(program, "source"), 0);
    glViewport(0, 0, WIDTH, HEIGHT);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    float pixels[WIDTH * HEIGHT * 4];
    glReadPixels(0, 0, WIDTH, HEIGHT, GL_RGBA, GL_FLOAT, pixels);
    assert(glGetError() == GL_NO_ERROR);
    float max_error = 0;
    for (int y = 0; y < HEIGHT; y++) {
        for (int x = 0; x < WIDTH; x++) {
            const float expected[] = {(64 + x) / 1023.0f, 256 / 1023.0f, 768 / 1023.0f};
            for (int c = 0; c < 3; c++) {
                float err = fabsf(pixels[(y * WIDTH + x) * 4 + c] - expected[c]);
                max_error = fmaxf(max_error, err);
            }
            if (x) assert(pixels[(y * WIDTH + x) * 4] > pixels[(y * WIDTH + x - 1) * 4]);
        }
    }
    printf("GPU: %s\nraw P010 sampling max_error=%.8f; adjacent 10-bit levels remain distinct\n",
           glGetString(GL_RENDERER), max_error);
    assert(max_error < 0.0005f);
    glDeleteProgram(program);
    glDeleteShader(v);
    glDeleteShader(f);
    glDeleteFramebuffers(1, &fbo);
    glDeleteTextures(1, &input);
    glDeleteTextures(1, &output);
    destroy_image(display, image);
    AHardwareBuffer_release(buffer);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroySurface(display, surface);
    eglDestroyContext(display, context);
    eglTerminate(display);
    puts("PASS: raw ten-bit YUV is preserved without RGB conversion");
    return 0;
}
