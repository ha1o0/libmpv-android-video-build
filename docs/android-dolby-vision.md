# Android Dolby Vision P5 硬解

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
