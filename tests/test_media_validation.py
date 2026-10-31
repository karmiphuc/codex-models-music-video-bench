"""Real encoders and synthetic fixtures; no model or creative generation calls."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave

import numpy as np

from lab.media import demo_audio, validate_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class SoundtrackValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "audio.wav"
        demo_audio(cls.source, duration=1.5)
        cls.spec = {"width": 160, "height": 90, "fps": 12, "duration_seconds": 1.5}
        cls.output = cls.root / "output"
        cls.output.mkdir()
        replacement = cls.root / "replacement.wav"
        with wave.open(str(replacement), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22050)
            times = np.arange(33075) / 22050
            audio.writeframes((np.sin(2 * np.pi * 880 * times) * 5000).astype("<i2").tobytes())
        for name, source, audio_filter in [
            ("matched", cls.source, None),
            ("silent", cls.source, "volume=0"),
            ("shifted", cls.source, "adelay=150:all=1"),
            ("replaced", replacement, None),
        ]:
            command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                       "color=c=black:s=160x90:r=12", "-i", str(source), "-t", "1.5",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                       "-movflags", "+faststart"]
            if audio_filter:
                command.extend(["-af", audio_filter])
            command.append(str(cls.output / (name + ".mp4")))
            subprocess.run(command, check=True, capture_output=True)
        # Move only the existing AAC timestamps; no waveform re-encoding/filter.
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-i", str(cls.output / "matched.mp4"), "-itsoffset", "0.2",
                        "-i", str(cls.output / "matched.mp4"), "-map", "0:v:0", "-map", "1:a:0",
                        "-c", "copy", str(cls.output / "timestamp-delay.mp4")],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_matched_aac_soundtrack_and_full_decode_pass(self):
        result = validate_video(self.output / "matched.mp4", self.spec)
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["checks"]["full_decode"])
        self.assertEqual(result["audio_comparison"]["comparison_offset_samples"], 0)

    def test_valid_metadata_does_not_accept_silent_replaced_or_shifted_audio(self):
        for name in ["silent", "shifted", "replaced"]:
            with self.subTest(name=name):
                result = validate_video(self.output / (name + ".mp4"), self.spec)
                self.assertFalse(result["passed"], result)
                self.assertTrue(result["checks"]["audio_duration"])
                self.assertTrue(result["checks"]["full_decode"])
                self.assertFalse(result["checks"]["soundtrack_matches_at_zero_offset"])

    def test_expected_source_is_required(self):
        result = validate_video(self.output / "matched.mp4", self.spec, self.root / "missing.wav")
        self.assertFalse(result["passed"])
        self.assertIn("missing", result["audio_comparison"]["error"])

    def test_mux_only_audio_timestamp_delay_is_rejected(self):
        result = validate_video(self.output / "timestamp-delay.mp4", self.spec)
        self.assertFalse(result["passed"])
        self.assertTrue(result["checks"]["full_decode"])
        self.assertTrue(result["checks"]["duration"])
        self.assertTrue(result["checks"]["audio_duration"])
        self.assertFalse(result["checks"]["stream_start_alignment"])
        self.assertGreater(result["stream_start_times"]["audio_seconds"], 0.1)

    def test_truncated_media_cannot_pass_on_container_metadata(self):
        payload = (self.output / "matched.mp4").read_bytes()
        corrupted = self.output / "truncated.mp4"
        corrupted.write_bytes(payload[:len(payload) * 3 // 4])
        result = validate_video(corrupted, self.spec)
        self.assertFalse(result["passed"])
        if "full_decode" in result["checks"]:
            self.assertFalse(result["checks"]["full_decode"], result)


if __name__ == "__main__":
    unittest.main()
