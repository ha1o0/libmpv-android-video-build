#!/usr/bin/env bash
set -euo pipefail

dovi_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dovi_scratch="$(mktemp -d)"
trap 'rm -rf "$dovi_scratch"' EXIT
dovi_cc="${CC:-cc}"

# Use precisely the source archive used by the Android producer.
python3 - "$dovi_root" "$dovi_scratch" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from fetch_mobile_sources import fetch
source = json.loads((Path(sys.argv[1]) / 'mobile-sources.json').read_text())['ffmpeg']
if os.environ.get('DOVI_SMOKE_ARCHIVE'):
    source['url'] = Path(os.environ['DOVI_SMOKE_ARCHIVE']).resolve().as_uri()
fetch(source, Path(sys.argv[2]) / 'ffmpeg')
PY
cd "$dovi_scratch/ffmpeg"
patch --batch --forward -p1 < "$dovi_root/buildscripts/patches/ffmpeg/mediacodec_dovi_p010.patch"
mkdir "$dovi_scratch/host"
cd "$dovi_scratch/host"
../ffmpeg/configure --cc="$dovi_cc" \
  --disable-everything --disable-autodetect --disable-programs --disable-doc \
  --disable-asm --disable-avformat --disable-avfilter --disable-avdevice \
  --disable-swscale --disable-swresample --enable-avcodec --enable-avutil \
  --enable-decoder=hevc
make -j"${DOVI_SMOKE_JOBS:-2}" libavcodec/libavcodec.a libavutil/libavutil.a
"$dovi_cc" -std=c11 -I. -I"$dovi_scratch/ffmpeg" \
  "$dovi_root/tests/mediacodec_dovi_smoke.c" \
  "$dovi_scratch/ffmpeg/libavcodec/mediacodec_dovi.c" \
  libavcodec/libavcodec.a libavutil/libavutil.a -lm -pthread -o mediacodec-dovi-smoke
./mediacodec-dovi-smoke
