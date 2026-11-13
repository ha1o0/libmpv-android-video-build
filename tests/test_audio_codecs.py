from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_audio_codecs as codecs
from test_mobile_release import jar


class AudioCodecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for abi in codecs.ABIS:
            jar(self.directory, abi)

    def nm_result(self, missing=(), undefined=()):
        defined = codecs.REQUIRED_SYMBOLS - set(missing) - set(undefined)
        output = "\n".join(f"{symbol} D 100 10" for symbol in sorted(defined))
        output += "\n" + "\n".join(f"{symbol} U 0 0" for symbol in undefined)
        return subprocess.CompletedProcess([], 0, output, "")

    def test_every_abi_must_have_the_linked_decoders_and_parsers(self):
        results = [self.nm_result() for _ in codecs.ABIS]
        with patch("check_audio_codecs.subprocess.run", side_effect=results) as nm:
            self.assertEqual(codecs.check_audio_codecs(self.directory, "llvm-nm"), list(codecs.ABIS))
            self.assertEqual(nm.call_count, 4)
            for call in nm.call_args_list:
                self.assertIn("--dynamic", call.args[0])
                self.assertIn("--defined-only", call.args[0])

    def test_rejects_the_previous_truehd_and_mlp_omission(self):
        result = self.nm_result(missing=("ff_truehd_decoder", "ff_mlp_decoder"))
        with patch("check_audio_codecs.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ValueError, "ff_truehd_decoder"):
                codecs.check_audio_codecs(self.directory, "llvm-nm")

    def test_decoder_without_the_shared_mlp_parser_is_rejected(self):
        with patch("check_audio_codecs.subprocess.run", return_value=self.nm_result(missing=("ff_mlp_parser",))):
            with self.assertRaisesRegex(ValueError, "ff_mlp_parser"):
                codecs.check_audio_codecs(self.directory, "llvm-nm")

    def test_dts_core_alone_is_not_enough_for_dts_hd(self):
        results = [self.nm_result(), self.nm_result(missing=("ff_dca_xll_parse",))]
        with patch("check_audio_codecs.subprocess.run", side_effect=results):
            with self.assertRaisesRegex(ValueError, "armeabi-v7a.*ff_dca_xll_parse"):
                codecs.check_audio_codecs(self.directory, "llvm-nm")

    def test_an_undefined_symbol_does_not_prove_decoder_availability(self):
        result = self.nm_result(undefined=("ff_truehd_decoder",))
        with patch("check_audio_codecs.subprocess.run", return_value=result):
            with self.assertRaisesRegex(ValueError, "ff_truehd_decoder"):
                codecs.check_audio_codecs(self.directory, "llvm-nm")


if __name__ == "__main__":
    unittest.main()
