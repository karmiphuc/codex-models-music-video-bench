"""Replace this diagnostic scene with an original music video.

Contract: frame(t, width, height, audio_map) -> RGB PIL.Image, deterministic at t.
Use a fixed random seed; never depend on wall-clock time or previous frames.
You may replace the renderer too, including with Blender or another installed tool,
provided the delivery paths and output format in spec.json stay the same.
"""
import math
from PIL import Image, ImageDraw


def frame(t, width, height, audio_map):
    image = Image.new("RGB", (width, height), "#101624")
    draw = ImageDraw.Draw(image)
    bpm = audio_map.get("bpm") or 100
    phase = t * bpm / 60
    pulse = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
    radius = int(min(width, height) * (0.10 + pulse * 0.025))
    for sign, color in [(-1, "#61dfc2"), (1, "#dca9f8")]:
        x = width / 2 + sign * width * 0.22
        y = height * 0.5 + math.sin(phase * math.pi + sign) * height * 0.1
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
    draw.text((width * 0.05, height * 0.08), "RENDER TEST / replace scene.py", fill="white")
    draw.text((width * 0.05, height * 0.88), f"{t:05.2f}s", fill="#9ba9c4")
    return image
