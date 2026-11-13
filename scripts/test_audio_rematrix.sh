#!/usr/bin/env bash
set -euo pipefail

audio_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
audio_scratch="$(mktemp -d)"
trap 'rm -rf "$audio_scratch"' EXIT
audio_cc="${CC:-cc}"
audio_jobs="${AUDIO_SMOKE_JOBS:-2}"

# Fetch the same verified FFmpeg archive as the Android build, independently
# of its platform dependencies. A local archive may be reused after SHA256
# verification; CI fetches the pinned release directly.
python3 - "$audio_root" "$audio_scratch" <<'PY'
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from fetch_mobile_sources import fetch
source = json.loads((Path(sys.argv[1]) / 'mobile-sources.json').read_text())['ffmpeg']
if os.environ.get('AUDIO_SMOKE_ARCHIVE'):
    source['url'] = Path(os.environ['AUDIO_SMOKE_ARCHIVE']).resolve().as_uri()
fetch(source, Path(sys.argv[2]) / 'ffmpeg')
PY

mkdir "$audio_scratch/host"
cd "$audio_scratch/host"
../ffmpeg/configure --cc="$audio_cc" \
  --disable-everything --disable-autodetect --disable-programs --disable-doc \
  --disable-asm --disable-avcodec --disable-avformat --disable-avfilter \
  --disable-avdevice --disable-swscale \
  --enable-avutil --enable-swresample
make -j"$audio_jobs" libswresample/libswresample.a libavutil/libavutil.a

compile_smoke() {
  "$audio_cc" -std=c11 -I. -I"$audio_scratch/ffmpeg" \
    "$audio_root/tests/audio_rematrix_smoke.c" \
    libswresample/libswresample.a libavutil/libavutil.a \
    -lm -pthread -o audio-rematrix-smoke
}
compile_smoke
./audio-rematrix-smoke
