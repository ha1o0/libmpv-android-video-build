#!/usr/bin/env bash
set -euo pipefail

# Host regression for the FFmpeg primitive used by the native subtitle overlay.
# The same C test can also link against the Android prefix for device checks.
alpha_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
alpha_scratch="$(mktemp -d)"
trap 'rm -rf "$alpha_scratch"' EXIT
python3 - "$alpha_root" "$alpha_scratch" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from fetch_mobile_sources import fetch
source = json.loads((Path(sys.argv[1]) / 'mobile-sources.json').read_text())['ffmpeg']
if os.environ.get('SUBTITLE_SMOKE_ARCHIVE'):
    source['url'] = Path(os.environ['SUBTITLE_SMOKE_ARCHIVE']).resolve().as_uri()
fetch(source, Path(sys.argv[2]) / 'ffmpeg')
PY
mkdir "$alpha_scratch/host"
cd "$alpha_scratch/host"
../ffmpeg/configure --cc="${CC:-cc}" \
  --disable-everything --disable-autodetect --disable-programs --disable-doc \
  --disable-asm --disable-avcodec --disable-avformat --disable-avfilter \
  --disable-avdevice --disable-swresample --enable-avutil --enable-swscale \
  --enable-swscale-alpha
make -j"${SUBTITLE_SMOKE_JOBS:-2}" libswscale/libswscale.a libavutil/libavutil.a
"${CC:-cc}" -std=c11 -I. -I"$alpha_scratch/ffmpeg" \
  "$alpha_root/tests/swscale_subtitle_alpha_smoke.c" \
  libswscale/libswscale.a libavutil/libavutil.a -lm -pthread -o subtitle-alpha-smoke
./subtitle-alpha-smoke
