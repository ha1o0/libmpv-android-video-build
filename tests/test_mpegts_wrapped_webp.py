#!/usr/bin/env python3
"""Exercise the production MPEG-TS wrapper detector across pinned FFmpeg sources."""

import argparse
import ctypes
import os
import random
import subprocess
import tempfile
from pathlib import Path


def extract_function(source, name):
    start = source.index('static int ' + name + '(')
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg-source', type=Path, required=True)
    parser.add_argument('--patch', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'buildscripts' /
                        'patches' / 'ffmpeg' / 'mpegts_wrapped_webp.patch')
    parser.add_argument('--sample', type=Path, action='append', default=[])
    args = parser.parse_args()
    source = (args.ffmpeg_source / 'libavformat/mpegts.c').read_text()

    with tempfile.TemporaryDirectory(prefix='mpegts-webp-probe-') as folder:
        root = Path(folder)
        (root / 'libavformat').mkdir()
        target = root / 'libavformat/mpegts.c'
        target.write_text(source)
        subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i',
                        str(args.patch.resolve())], cwd=root, check=True,
                       stdout=subprocess.DEVNULL)
        source = target.read_text()
        function = extract_function(source, 'mpegts_wrapped_webp_probe')
        harness = root / 'probe.c'
        harness.write_text('''#include <stdint.h>
#include <string.h>
#define TS_PACKET_SIZE 188
#define AVPROBE_SCORE_MAX 100
#define FFMIN(a,b) ((a) < (b) ? (a) : (b))
typedef struct { const uint8_t *buf; int buf_size; } AVProbeData;
''' + function + '''
int detect(const uint8_t *bytes, int size) {
    AVProbeData data = {bytes, size};
    return mpegts_wrapped_webp_probe(&data);
}
''')
        library = root / 'probe.so'
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-shared',
                        '-fPIC', '-Wall', '-Wextra', '-Werror', str(harness),
                        '-o', str(library)], check=True)
        native = ctypes.CDLL(str(library)).detect
        native.argtypes = [ctypes.c_void_p, ctypes.c_int]
        native.restype = ctypes.c_int

        def detect(data):
            buffer = ctypes.create_string_buffer(data, max(1, len(data)))
            return native(buffer, len(data))

        packet = b'\x47\x40\x11\x10' + bytes(184)

        def wrapped(offset=33, packets=8):
            return b'RIFF' + bytes(4) + b'WEBP' + bytes(offset - 12) + packet * packets

        for offset in (12, 33, 188, 511, 512):
            assert detect(wrapped(offset)) == 100, ('valid offset', offset)
        assert detect(wrapped(513)) == 0, 'bounded prefix scan'
        assert detect(wrapped(packets=7)) == 0, 'requires eight complete packets'
        valid = wrapped()
        for length in range(len(valid)):
            assert detect(valid[:length]) == 0, ('truncated', length)
        for index, value in ((0, 0), (1, 0x80), (3, 0), (3, 0x20)):
            broken = bytearray(valid)
            broken[33 + 3 * 188 + index] = value
            if index == 3 and value == 0x20:
                broken[33 + 3 * 188 + 4] = 184
            assert detect(bytes(broken)) == 0, ('invalid TS header', index, value)
        assert detect(packet * 12) == 0, 'normal MPEG-TS keeps existing probe'
        for signature in (b'AVI ', b'WAVE', b'WEBX'):
            assert detect(valid[:8] + signature + valid[12:]) == 0
        rng = random.Random(122)
        for size in (0, 1, 8, 11, 12, 33, 100, 1024, 2048, 8192):
            for _ in range(50):
                noise = bytes(rng.randrange(256) for _ in range(size))
                assert detect(noise) == 0, ('random input', size)
                if size >= 12:
                    noise = b'RIFF' + noise[4:8] + b'WEBP' + noise[12:]
                    assert detect(noise) == 0, ('realistic WebP without TS', size)
        for sample in args.sample:
            assert detect(sample.read_bytes()[:8192]) == 100, sample
    print('MPEG-TS WebP-wrapper probe checks passed:', args.ffmpeg_source)


if __name__ == '__main__':
    main()
