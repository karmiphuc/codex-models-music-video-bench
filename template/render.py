"""Deterministic CPU renderer. Run from this folder: python render.py."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time

from scene import frame


def render(seconds=None):
    root = Path(__file__).resolve().parent
    spec = json.loads((root / "spec.json").read_text())
    audio = json.loads((root / "audio-map.json").read_text())
    duration = spec["duration_seconds"] if seconds is None else min(seconds, spec["duration_seconds"])
    if duration <= 0:
        raise ValueError("Render duration must be positive.")
    width, height, fps = spec["width"], spec["height"], spec["fps"]
    output = root / "output"
    output.mkdir(exist_ok=True)
    destination = output / ("final.mp4" if seconds is None else "preview.mp4")
    command = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
               "-i", str(root / "audio.wav"), "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-t", str(duration),
               "-movflags", "+faststart", str(destination)]
    started = time.monotonic()
    # Inherit stderr to avoid a full stderr pipe blocking a long encode.
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for i in range(math.ceil(duration * fps)):
            image = frame(i / fps, width, height, audio)
            if image.size != (width, height):
                raise ValueError("frame() returned the wrong dimensions")
            process.stdin.write(image.convert("RGB").tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("FFmpeg failed")
    except BaseException:
        process.terminate()
        process.wait()
        raise
    (output / "render-metrics.json").write_text(json.dumps({
        "seconds": time.monotonic() - started, "frames": math.ceil(duration * fps),
        "file": destination.name}, indent=2) + "\n")
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, help="Short diagnostic preview")
    args = parser.parse_args()
    render(args.seconds)
