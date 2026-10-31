# Codex Models Music Video Bench

A prepared project for repeating [Devarf's music-video experiment](https://youtu.be/3S4vuHxGh7c)
across the coding models offered by your Codex installation and every supported
reasoning effort. **Choose any song later.** Setup requires no soundtrack.

Each condition receives the same audio excerpt, audio map, creative brief,
rendering toolkit and output requirements in a fresh folder. Models choose their
own visual concept. The harness saves source, MP4s, contact sheets, elapsed time,
reported token usage, failures and anonymous clips for human scoring.

**Current readiness:** rendering and harness checks are runnable. The project is
ready to accept a future audio file. Each song gets its own prepared inputs and
experiment folders. Setup and verification do not launch creative model sessions.

## Setup

Use Python 3.11+, Git, FFmpeg/FFprobe with libx264/AAC, and a signed-in Codex CLI.
The CLI integration was checked against **codex-cli 0.163.0**. Blender is optional
for 3D; install it before freezing the plan if you want every model to have it.

```bash
git clone https://github.com/karmiphuc/codex-models-music-video-bench.git
cd codex-models-music-video-bench
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
codex login status
python lab.py doctor
python lab.py smoke
python -m unittest discover -s tests -v
```

GitHub Actions runs the offline tests and the sample render on every push and pull request.

The smoke command makes a short synthetic render solely to check the encoder.
It does not call Codex or use your music. Windows users can run the Python
commands in PowerShell and activate `.venv\Scripts\Activate.ps1`.

## Add any song when you are ready

Supply an MP3, WAV, FLAC or another FFmpeg-readable audio file. Track and artist
metadata can be set for each song without changing code or prompts:

```bash
python lab.py prepare --audio "/path/to/new-song.mp3" --song new-song --title "New Song" --artist "Artist Name"
```

The full track is used by default. For an excerpt, add `--start 30 --duration 60`
to use seconds 30–90. Omit `--duration` to use all remaining audio after the start
offset. There is no fixed 79-second limit. `--title` defaults to the filename;
an omitted artist stays unknown. `--song` is a stable folder ID, automatically
derived from the title when omitted. Use a different ID for a second excerpt or
another track with the same title. The ID `demo` is reserved for diagnostics.

Preparation writes `prepared/new-song/audio.wav`, `audio-map.json` and a
provenance record. The source is hashed, converted to mono PCM at 22,050 Hz and
trimmed once for all models. This standardization is a project choice, not the
original creator's exact audio pipeline. Keep the original download separately.
Retain any license or attribution information with your source; `--license-note`
can save a note in the provenance record.

The lightweight map contains measured energy and possible amplitude accents.
It does not transcribe or identify instruments. Add `--bpm NUMBER` only after
checking the tempo; that grid starts at excerpt zero. Optional `--cues cues.json`
imports verified lyrics and sections in the format shown in
[docs/cues.example.json](docs/cues.example.json), with times relative to the excerpt.
Review and enrich the map **before** freezing a plan. Re-running preparation will
not overwrite a prepared folder; use a new song ID for a changed excerpt.
You can keep multiple songs prepared simultaneously. `python lab.py doctor`
lists their IDs. No song is required for setup, tests, discovery or smoke checks.

## Discover and freeze the comparison

```bash
python lab.py discover
python lab.py plan --song new-song --efforts all
```

`discover` reads the installed app-server's paginated `model/list` catalog without
starting a generation. It stores exact IDs and supported reasoning efforts in
`catalog.json`. No hardcoded model list or invented effort labels are used.
`MODEL_MATRIX.csv` previews the current visible-model matrix before audio is supplied.

`plan` includes all visible coding models and all advertised efforts by default.
Hidden catalog entries, such as internal review or specialist models, are recorded
as exclusions. Use `--include-hidden` to test those too, or `--models ID ...` for
explicit selection. A catalog entry does not guarantee account access: rejections
remain failed conditions. The matrix is bounded by the installed catalog, not an
assertion that every historical or API-only OpenAI model is available in Codex.

For one representative condition per model use `--efforts default`. To reduce
randomness use `--repeats 3`. For example:

```bash
python lab.py plan --song new-song --efforts all --repeats 3
```

Every plan creates `experiments/<song-id>-<timestamp>/` with a frozen seed,
SHA-256 hashes, model catalog, environment versions and complete run matrix.
Resolution is 1920×1080 at 30 fps by default; change `experiment.json` before
planning if needed. Do not edit a frozen seed. `plan --demo` explicitly creates
a synthetic test experiment; it never substitutes for the chosen soundtrack.
If exactly one real song is prepared, `--song` can be omitted. With multiple
songs, the harness requires a selection so it cannot accidentally use the wrong one.

## Run when ready

Replace `EXPERIMENT` with the folder printed by `plan`:

```bash
python lab.py run --experiment EXPERIMENT
python lab.py run --experiment EXPERIMENT --only run-001 --execute
python lab.py run --experiment EXPERIMENT --execute
python lab.py report --experiment EXPERIMENT
```

The first command prints the exact CLI commands without starting sessions.
`--execute` starts the sessions and consumes Codex allowance. Runs execute
serially. Each gets a fresh Git working folder, identical prompt on stdin and
explicit model/effort settings. User config is ignored for consistent defaults;
normal Codex authentication is retained. Custom provider configurations require
adapting the invocation before making a new plan.

Default limits are **2 hours per condition** and **8 hours per invocation**.
Adjust with `--seconds` and `--total-seconds`. A large matrix will take multiple
invocations. Completed conditions are skipped on resume; unstarted ones remain
pending. `--retry-failed` creates a new attempt from the untouched seed and
preserves the failed attempt. Ctrl-C preserves an interrupted status. POSIX
timeouts kill the session's process group, including render children. Windows
timeouts terminate the CLI but may require cleaning up remaining render children.
No token or dollar cap is enforced. Usage is collected after a turn completes;
usage can be absent for interrupted sessions. No automatic retries or guessed
dollar prices are added.

These folders are an experiment layout, not a security boundary against sibling
reads. Instructions prohibit reading other conditions, and Codex uses its
workspace-write sandbox. Use separate containers or machines for stronger
isolation. Tools/dependencies should be installed on the host before planning;
sessions are instructed not to install them or call other models.

## Review the outputs

For each attempt look in `work/output/` for `final.mp4`, `contact-sheet.png` and
`qa.md`. The harness also keeps raw JSONL events, stderr, command arguments,
metrics and its own metadata validation. A `complete` status means the CLI
finished and required files/technical checks passed. It does not mean the video
is visually good, the correct song was selected, or sync/accessibility was certified.
The harness rejects an unchanged diagnostic source and any explicitly reported
model reroute. Some CLI events do not expose server-side model identity, so the
requested model/effort is recorded without claiming independent identity attestation.

`RESULTS.md` and `results.csv` compare conditions. `review/clip-<opaque-id>.mp4`
provides neutral filenames; score with `review-scores.csv` and
[docs/RUBRIC.md](docs/RUBRIC.md). Keep `blind-key.json` and the model-labeled report
away from reviewers until scoring is complete. Visible text inside a model's own
video could still reveal its identity. Existing human scores are preserved on
report regeneration.

Input/output/cache usage comes from `turn.completed` events. Cached input is a
subset of input, not an extra amount to add. Costs stay blank because tokens
alone do not establish subscription or API billing. Wall time includes the whole
session; `output/render-metrics.json` separately measures the supplied renderer.

See [docs/REFERENCE.md](docs/REFERENCE.md) for sources and replication limits,
and [CODEX_HANDOFF.txt](CODEX_HANDOFF.txt) for a ready-to-paste Codex task.
