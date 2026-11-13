/* Exercise the custom channel order sent to swresample by the pinned mpv. */
#include <math.h>
#include <stdio.h>

#include <libavutil/channel_layout.h>
#include <libswresample/swresample.h>

static int create_context(SwrContext **ctx, const AVChannelLayout *input)
{
    const AVChannelLayout stereo = AV_CHANNEL_LAYOUT_STEREO;
    int result = swr_alloc_set_opts2(ctx, &stereo, AV_SAMPLE_FMT_FLTP, 48000,
                                    input, AV_SAMPLE_FMT_FLTP, 48000, 0, NULL);
    return result < 0 ? result : swr_init(*ctx);
}

static int check_layout(const char *name, uint64_t mask,
                        const enum AVChannel *order, int count)
{
    AVChannelLayout native = {0}, custom = {0};
    SwrContext *reference = NULL, *actual = NULL;
    int failed = 1;
    if (av_channel_layout_from_mask(&native, mask) < 0 ||
        av_channel_layout_custom_init(&custom, count) < 0)
        goto done;
    for (int i = 0; i < count; i++)
        custom.u.map[i].id = order[i];

    if (create_context(&reference, &native) < 0) {
        fprintf(stderr, "%s: native reference layout failed\n", name);
        goto done;
    }
    int result = create_context(&actual, &custom);
    if (result < 0) {
        fprintf(stderr, "%s: custom layout failed (%d)\n", name, result);
        goto done;
    }

    /* An impulse in each speaker must reach the same stereo channel with
     * the same gain as the native layout, including non-native input order. */
    for (int speaker = 0; speaker < count; speaker++) {
        float native_input[8] = {0}, custom_input[8] = {0};
        float native_output[2] = {0}, custom_output[2] = {0};
        const uint8_t *native_data[8], *custom_data[8];
        uint8_t *native_out[2], *custom_out[2];
        int native_index = av_channel_layout_index_from_channel(&native, order[speaker]);
        if (native_index < 0)
            goto done;
        native_input[native_index] = custom_input[speaker] = 0.25f;
        for (int i = 0; i < count; i++) {
            native_data[i] = (const uint8_t *)&native_input[i];
            custom_data[i] = (const uint8_t *)&custom_input[i];
        }
        for (int i = 0; i < 2; i++) {
            native_out[i] = (uint8_t *)&native_output[i];
            custom_out[i] = (uint8_t *)&custom_output[i];
        }
        if (swr_convert(reference, native_out, 1, native_data, 1) != 1 ||
            swr_convert(actual, custom_out, 1, custom_data, 1) != 1)
            goto done;
        for (int i = 0; i < 2; i++) {
            if (fabsf(native_output[i] - custom_output[i]) > 1e-6f) {
                fprintf(stderr, "%s: speaker %d reached the wrong output/gain\n", name, speaker);
                goto done;
            }
        }
    }
    printf("%s: stereo downmix and channel order preserved\n", name);
    failed = 0;
done:
    swr_free(&reference);
    swr_free(&actual);
    av_channel_layout_uninit(&native);
    av_channel_layout_uninit(&custom);
    return failed;
}

int main(void)
{
    const enum AVChannel stereo[] = {AV_CHAN_FRONT_LEFT, AV_CHAN_FRONT_RIGHT};
    const enum AVChannel surround[] = {
        AV_CHAN_FRONT_LEFT, AV_CHAN_FRONT_RIGHT, AV_CHAN_FRONT_CENTER,
        AV_CHAN_LOW_FREQUENCY, AV_CHAN_BACK_LEFT, AV_CHAN_BACK_RIGHT,
    };
    const enum AVChannel side[] = {
        AV_CHAN_FRONT_CENTER, AV_CHAN_FRONT_LEFT, AV_CHAN_FRONT_RIGHT,
        AV_CHAN_SIDE_RIGHT, AV_CHAN_SIDE_LEFT, AV_CHAN_LOW_FREQUENCY,
    };
    const enum AVChannel seven[] = {
        AV_CHAN_FRONT_LEFT, AV_CHAN_FRONT_RIGHT, AV_CHAN_FRONT_CENTER,
        AV_CHAN_LOW_FREQUENCY, AV_CHAN_BACK_LEFT, AV_CHAN_BACK_RIGHT,
        AV_CHAN_SIDE_LEFT, AV_CHAN_SIDE_RIGHT,
    };
    const enum AVChannel reordered[] = {
        AV_CHAN_LOW_FREQUENCY, AV_CHAN_FRONT_CENTER, AV_CHAN_FRONT_RIGHT,
        AV_CHAN_FRONT_LEFT, AV_CHAN_SIDE_RIGHT, AV_CHAN_SIDE_LEFT,
        AV_CHAN_BACK_RIGHT, AV_CHAN_BACK_LEFT,
    };
    int failures = 0;
    failures += check_layout("stereo", AV_CH_LAYOUT_STEREO, stereo, 2);
    failures += check_layout("5.1", AV_CH_LAYOUT_5POINT1_BACK, surround, 6);
    failures += check_layout("5.1(side), reordered", AV_CH_LAYOUT_5POINT1, side, 6);
    failures += check_layout("7.1", AV_CH_LAYOUT_7POINT1, seven, 8);
    failures += check_layout("7.1, reordered", AV_CH_LAYOUT_7POINT1, reordered, 8);
    return failures ? 1 : 0;
}
