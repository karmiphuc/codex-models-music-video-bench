# Identical tools for every run

Python 3.11+, NumPy, Pillow and FFmpeg/FFprobe are required. scene.py receives
absolute song time in seconds and returns a PIL image. All frames can be rendered
independently. The default encoder muxes audio.wav from time zero, with no music
replacement. spec.json specifies duration, dimensions and fps.

The energy envelope and amplitude-rise candidates in audio-map.json are measured
from the audio, but are not verified beats. An optional BPM grid starts at zero,
which may not be a downbeat. Empty lyrics/sections mean unavailable, not silence.

Blender is optional. If installed before planning, all runs can use the same
version for procedural 3D. Node and other tools can be used only if prepared on
the host before planning. Do not fetch packages during the run.

Preview: `python render.py --seconds 5`
Final: `python render.py`
Contact sheet and metadata QA: `python postprocess.py`

Deliver a coherent narrative or choreography and a purposeful ending. Retain the
original synchronized soundtrack. Save output/qa.md with inspected timestamps,
remaining issues and whether you viewed the final export. Do not label the
starter diagnostic or a static waveform as a completed creative music video.
