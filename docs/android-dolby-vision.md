# Android Dolby Vision P5 硬解

## 本轮本机 ARM64 制品

2026-11-26 已重新编译 default / ARM64 的 libmpv、FFmpeg 和 libplacebo，
并装入应用的 Profile 包完成 Android 实机测试，用户反馈样片均已不卡。
原生直出在应用中继续默认关闭，使用下述 P5/P8 GPU 通道。

- JAR：`build/default-arm64-v8a.jar`
- JAR SHA-256：`ade49153da0d9bae912b34dfe13a486826c04e018d7f6cc401b771dee45e6ad7`
- 内置 `libmpv.so` SHA-256：`25ee4717c018fed56118a85c12bbee15c4941c648696ee546910503bd2c2a0e6`

本次保存构建配方、全部源码补丁和回归测试；`build/` 中的生成制品不进入 Git。
尚未发布新的原生版本，也未更新应用的远端发行库锁。应用测试包通过现有
`BOTA_ANDROID_LIBMPV_ARM64_JAR` / `BOTA_ANDROID_LIBMPV_ARM64_SHA256`
覆盖使用本制品；其他 ABI 此轮未重编译，不将 ARM64 结果视为四 ABI 验证。

## 2026-11-26：P5/P8 统一使用受能力保护的 GPU 传输

应用当前暂时关闭 `mediacodec_embed`，仍由 libmpv `gpu-next` 渲染。P5、
P8.1/P8.4 的自动/性能模式统一先尝试 MediaCodec Surface → GPU 原始分量
取样，保留逐帧 RPU，不再按是否超过 4K60 决定是否复制帧。此规则依据源
Profile 和运行时 GPU 能力，不依据文件名、容器后缀或样片列表。

mpv 在选择硬解设备时要求 `gpu-next`、GLES 3 和 `GL_EXT_YUV_target`；
不满足时按候选顺序使用 P010 copy-back。FFmpeg 只在此明确 opt-in 下允许
P5/P8 的 Surface 帧携带 RPU；普通 RGB 纹理和 NV12 不能被当成杜比原始帧。
显式兼容/复制模式继续复制，显式软解继续软解。P20 保留原有 P010/基础视角
处理，P7/P10 和普通 HDR 的选择策略不变。原生直出重新启用时保持原路径。

若设备声明支持但实际纹理导入/渲染失败，应用为当前 P5/P8 文件至多进行一次
硬解复制回退，保留 libmpv/HDR 输出；并发日志合并，关闭或切换文件取消旧
请求。反交错和需要可读帧的滤镜仍由已有共享策略切换复制帧。

真实 FFmpeg RPU/PTS/seek/flush 测试通过，并验证 P5 Surface opt-in、NV12
拒绝及 P20 不被误放开。Adreno 830 真机执行离屏合成的 P010 梯度测试，
64 个相邻 10 位灰阶保持不同，原始 Y/U/V 最大误差为 0；无视频播放、
截图或图像文件。该测试验证 GPU 分量取样能力，不替代实际影片的性能与
色彩验收。工具为 `tests/android_dovi_yuv_smoke.c`，数值日志位于本机
`build/dovi-gpu-device-capability.log`。下文 copy-back 优先策略为此前阶段记录。

## 原生 Surface + mpv 字幕候选（2026-11-25 第二轮）

应用查询 Android 解码器与显示器能力后，可优先选择 `mediacodec_embed`。
同一 mpv 会话继续解封装、播放音频、同步和选择字幕；视频硬解帧直接交给
系统 Surface，`android-subtitle-wid` 指定独立透明字幕 Surface。该 VO 调用
mpv 的 `osd_render` 和 `mp_draw_sub_overlay`，保留 libass、图片字幕及双字幕。
字幕只在内容/布局改变时更新，并使用视频 PTS；离开直出时清空旧字幕层。

P5/P8 的直出通过 FFmpeg `dovi_native` 选择 `video/dolby-vision` 解码器，
由系统处理码流中的 RPU；GPU 路径继续使用现有元数据处理。仅具有字幕
Surface 的新 VO 可以绕过 P5 的原有 copy-back 保护。无原生能力、启用
滤镜/shader、SDR 映射、自定义字幕 HDR 亮度或显式软解/兼容模式时，应用
保留/切回 GPU 路径。运行时解码失败也会回退。

此候选在本机构建并通过字幕合成与元数据测试；手机操作、颜色、字幕及
高帧率流畅度由用户复测，不将编译通过视为这些项目的验收结论。

## P8 高帧率候选路径（2026-11-25）

P8 可以在 `gpu-next`、GLES 3 和 `GL_EXT_YUV_target` 同时可用时使用
MediaCodec Surface。libplacebo 使用 `__samplerExternal2DY2YEXT` 读取原始
YUV 分量，保留逐帧 RPU 后再进行 Dolby reshaping，不经过 CPU 帧复制，也不
把已转换的 RGB 误当作杜比原始分量。该能力由实际 renderer 回报后才允许
FFmpeg 的 `dovi_yuv` 选项；不支持的 renderer 继续使用 P010 copy-back。
P5 和显式 copy-back 选择保持原路径。

实现位于三个 `zz-android-dovi-yuv-surface.patch` 中，分别应用到 mpv、
FFmpeg 和 libplacebo。ARM64 候选库已本机构建，RPU/PTS/flush、P010 边界
测试通过；最终候选的真机流畅度和颜色正确性等待用户复测。

本构建继续使用 libmpv / FFmpeg / libplacebo。P5 在允许硬解时选择 MediaCodec copy-back：硬件解码 HEVC，取出 P010 原始分量，由 gpu-next 根据逐帧 Dolby RPU 做颜色处理。CPU 负责元数据解析与帧拷贝，不执行 HEVC 像素解码。

## 为什么使用 copy-back

现有 Android AImageReader 外部 OES 纹理按 RGB 取样；在杜比 reshaping 之前发生平台 YUV→RGB 转换，不能简单给这类帧追加 RPU。本实现要求 P010（Android color-format 54），保留 10-bit 分量，继续使用 mpv 的字幕、滤镜及 gpu-next 渲染。

在 K80 Pro（24122RKC7C，Android API 37）上，`c2.qti.hevc.decoder` 明确报告 P010 支持。独立 MediaCodec 探针解码测试片的 259 帧至 EOS，实际输出 color-format=54；256 像素宽的帧报告 stride=512 字节。此探针只证明硬件和 P010 输出能力，真实影片的最终验证另记录在应用交付审查中。

## 实现边界

- 仅 HEVC 且容器声明 Dolby Vision profile 5 时请求 P010 并启用 RPU 传递。
- 在进入 MediaCodec 前解析 RPU，按输入 PTS 保存独立元数据快照；按实际输出 PTS 取回，处理 B 帧乱序。时间戳转换与 MediaCodec 微秒转换保持一致。
- 元数据最多保留 128 帧；重复/缺失 PTS、找不到对应元数据、非 P010 输出均报告解码错误，由 mpv 的现有错误回退处理，避免静默输出错误颜色。
- seek/flush 和关闭解码器时释放队列并清理 RPU 状态，避免跨时间线复用。
- P010 复制检查 buffer offset/size、byte stride、slice-height、crop、目标步长和容量，保留 16-bit 存储中的全部分量位。无法安全解释的布局拒绝处理。
- 非 P5 的 MediaCodec 解码保持原选择策略；用户显式关闭硬解仍使用软件解码。P5 硬解依赖设备提供 P010，并不能保证所有 Android 设备都支持。
- `mediacodec-copy` 包含帧拷贝/上传成本，不代表零拷贝，也不代表系统 Dolby Vision 显示模式直出。

## 验证

`DOVI_SMOKE_ARCHIVE=/path/to/ffmpeg-8.1.3.tar.xz scripts/test_mediacodec_dovi.sh` 使用已锁定且经过 SHA-256 校验的 FFmpeg 源码运行真实 RPU 解析、时间戳、flush 和 P010 边界测试；不提供本地 archive 时下载同一锁定版本。发布工作流运行此检查，并要求所有 ABI 的实际 libmpv 链接 MediaCodec HEVC 解码器及新增 RPU 传递函数。


## 2026-11-25 sample-library follow-up

The native subtitle VO now supplies real active/modified rectangle arrays to
`mp_draw_sub_overlay`. The device initially exposed an assertion that the stub
alone missed; debug logs now confirm nonempty primary/secondary ASS composition
and clearing with the real library. No screenshots are required for these probes.

During `on_loaded`, changes to VO must be stored without reinitializing the video
chain. Track selection already exists but normal decoder initialization has not
run yet; eagerly rebuilding here creates the chain twice. The loaded-output patch
keeps ordinary runtime VO replacement intact.

P20 uses the existing P010/RPU transport. For the app's 2D output, non-base-view
MV-HEVC NALs are excluded before submitting packets to MediaCodec; their presence
caused the device HEVC decoder to fail after initially producing frames. Base-view
RPU and packet timing survive this filtering. This is not stereoscopic playback.
P10 has an optional native AV1/Dolby selection (`video/dolby-vision`, Android
profile 1024), guarded by the Java codec/display check. A source-profile badge is
not proof that every device processes all Dolby profiles or enhancement layers.

Verification: complete patch application from the locked source archives matched
all changed compiled files (mpv 21, FFmpeg 11, libplacebo 6). The real FFmpeg parser
smoke covers metadata ordering, flush, P010 bounds, P20 view filtering and P10
configuration. Device results and delivery manifest are recorded in the app's
`docs/reviews/2026-11-25-android-p8-120fps-hdr-glass.md`.


## Container-only HDR colorimetry

`The World in HDR.mkv` carries VP9 BT.2020/PQ in Matroska Colour. The original
MediaCodec wrapper did not receive those fields and returned BT.709/SDR buffers.
The Android-only mpv initialization now fills missing AVCodecContext color fields
and HDR side data from the container before opening MediaCodec. FFmpeg forwards
explicit input range/standard/transfer and PQ static HDR metadata during configure.
Unknown fields stay unset, and the output is still read from MediaCodec rather
than relabeled after decoding. The device now reports standard=6/transfer=6,
BT.2020/PQ limited, with hardware Surface output and no sampled frame drops.

`tests/test_android_codec_color.py` checks the production packing function for
SDR, HLG, PQ, absent fields, byte ordering, luminance units and invalid extremes.
The patch sources were checked against the compiled Android source tree.


## PGS transparency in the separate subtitle plane

Enable `--enable-swscale-alpha` for all Android flavors. The previous disabled
setting discarded transparent/semitransparent BGRA alpha on resized PGS bitmaps,
turning the rectangular canvas opaque. `scripts/test_subtitle_alpha.sh` tests the
real scaler at 1x/0.5x/2x with bilinear/Lanczos, and the same C probe was run against
both production Android libraries on the handset: before 0/128 -> 255/255, after
0/128 -> 0/129 (rounding), with opaque pixels unchanged. No screenshot is needed.
