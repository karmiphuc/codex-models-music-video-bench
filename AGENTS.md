# Codex music video lab

This repository prepares a reusable version of the motion-graphics experiment
at https://youtu.be/3S4vuHxGh7c for all available Codex coding models. Users can
choose any song later. No soundtrack is selected or required at setup.

Read README.md. This repository is the experiment harness, not one generated music
video. Keep creative work inside experiments/<id>/runs/<run>/attempt-<n>/work.
Keep the prompt, audio, tool versions and output specification identical across
the matrix. Discover current model IDs and supported efforts; never replace the
catalog with guessed marketing names. Record exclusions and failed/unsupported
runs. Do not silently fall back to another model or effort.

Preparation does not require launching the full model matrix. `run` prints
commands by default; `--execute` starts sessions that consume the user's Codex
allowance. Start with a single selected condition for operational checks before
the full experiment. No subagents or nested model sessions during a condition.

Accept any future user-supplied song via `prepare --audio`, with optional title,
artist, song ID and excerpt settings. Keep each prepared song in its own folder
and select it with `plan --song ID`. Default to the full supplied track; do not
hardcode the reference video's song or 79-second duration. Never present synthetic
fixture audio as the chosen song. Never invent lyrics or pretend to transcribe audio.

Run `python -m unittest discover -s tests -v` for harness changes and
`python lab.py smoke` for the real encoder path. These do not invoke a model.
Do not edit frozen experiment seeds; create a new plan after input changes.
