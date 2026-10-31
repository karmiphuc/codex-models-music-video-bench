# Music video task

Work only inside this run folder. Read TASK.txt, spec.json, audio-map.json and
TOOLS.md. Build an original video; the starter scene is only a diagnostic.
Keep audio.wav, audio-map.json, spec.json, TASK.txt and these instructions unchanged.
Do not inspect other runs or change the experiment harness.

Work autonomously. Do not start subagents, nested Codex sessions, external paid
services or image/video generation APIs. Use code to create the visuals. Choose
2D, 3D or a hybrid. Use the installed tools; do not install dependencies during a
benchmark run. No filmed or downloaded stock footage.

Write a concept and timecoded shot plan to storyboard.json. Make a short proof,
inspect frames, then render the complete piece. Make at most two repair passes.
Stop after delivering output/final.mp4, output/contact-sheet.png and output/qa.md.
Preserve source code and mention limitations in qa.md. A playable video plus a
candid report is preferable to an endless improvement loop. Avoid full-frame
strobing. Technical validation does not certify accessibility or visual quality.

Use `python render.py --seconds 5` for a proof and `python render.py` for final
encoding, unless you intentionally implement another renderer. Use the shared
postprocess.py for contact sheets and mechanical validation. Do not claim to
have heard or transcribed lyrics that are absent from the verified cue sheet.
