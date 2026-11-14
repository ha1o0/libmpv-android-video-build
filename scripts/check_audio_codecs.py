#!/usr/bin/env python3
"""Reject Android bundles missing the audio and subtitle codecs needed by mpv."""

import argparse
from pathlib import Path
import subprocess
import tempfile
import zipfile

from mobile_release import ABIS, inspect_jar


# Check the linked, stripped library rather than configure flags. DTS-HD MA
# (including the channel-based audio in DTS:X) also needs the XLL implementation.
REQUIRED_SYMBOLS = frozenset({
    "ff_aac_decoder",
    "ff_hevc_mediacodec_decoder",
    "ff_mediacodec_dovi_submit",
    "ff_mediacodec_dovi_attach",
    "ff_ass_decoder",
    "ff_ssa_decoder",
    "ff_pgssub_decoder",
    "ff_dvdsub_decoder",
    "ff_subrip_decoder",
    "ff_ac3_decoder",
    "ff_eac3_decoder",
    "ff_flac_decoder",
    "ff_opus_decoder",
    "ff_mlp_decoder",
    "ff_truehd_decoder",
    "ff_mlp_parser",
    "ff_dca_decoder",
    "ff_dca_parser",
    "ff_dca_xll_parse",
    "ff_dca_xll_filter_frame",
})


def check_audio_codecs(directory, nm):
    checked = []
    for abi in ABIS:
        jar = directory / f"default-{abi}.jar"
        inspect_jar(jar, abi)
        with tempfile.TemporaryDirectory(prefix="android-audio-codecs-") as temp:
            library = Path(temp) / "libmpv.so"
            with zipfile.ZipFile(jar) as archive:
                library.write_bytes(archive.read(f"lib/{abi}/libmpv.so"))
            result = subprocess.run(
                [str(nm), "--dynamic", "--defined-only", "--format=posix", str(library)],
                check=True, capture_output=True, text=True, timeout=60,
            )
        symbols = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].upper() != "U":
                symbols.add(parts[0])
        missing = REQUIRED_SYMBOLS - symbols
        if missing:
            raise ValueError(f"{abi} libmpv.so is missing required audio/subtitle symbols: {', '.join(sorted(missing))}")
        checked.append(abi)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--nm", required=True, help="NDK llvm-nm executable")
    args = parser.parse_args()
    try:
        checked = check_audio_codecs(args.directory, args.nm)
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error
    print(f"Validated Dolby/DTS audio and ASS/PGS subtitle codecs: {', '.join(checked)}")


if __name__ == "__main__":
    main()
