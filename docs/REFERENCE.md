# Reference and replication limits

Primary reference: [Devarf — I Had Opus 5.5 Make the Same Music Video at Every Effort](https://www.youtube.com/watch?v=3S4vuHxGh7c).
The accessible video description identifies a fixed song/prompt comparison in
Claude Code and the soundtrack Mirror Mirror by Anno Domini Beats. The creator's
[portfolio](https://devarf.dev/) also lists music videos using that track.

[This secondary walkthrough](https://visions.joaoqueiros.com/blog/opus-5-5-music-video-effort-low-medium-high-xhigh-max-ultracode/)
reports a 79-second excerpt and shared audio analysis/rendering tools. We could
read public metadata and this walkthrough, not inspect every frame or verify the
full original transcript. This repository is an independently implemented Codex
adaptation, with an original prompt, not the creator's private toolkit or a
byte-for-byte reproduction. The exact excerpt offset is unverified. It preserves
the fixed-input experiment while substituting the model/effort matrix.

Local integration evidence: codex-cli 0.163.0 `exec --help` and generated
app-server JSON schemas for InitializeParams, ModelListParams and
ModelListResponse. The [official Codex app-server documentation](https://developers.openai.com/codex/app-server/)
describes the supported protocol. Discovery uses initialize/initialized followed
by paginated model/list, with includeHidden=true. Plan selection records hidden
entries as exclusions unless explicitly included.

Use your own [YouTube Audio Library download](https://support.google.com/youtube/answer/3376882)
and retain its attribution details. The song and the original creator's video are
not redistributed with this project.

Experiments change both model identity and effort. Compare efforts within one
model or compare models at a stated effort/default; do not treat named efforts
as equal compute across model families. Render hardware and generation randomness
also affect results. Multiple repeats strengthen any quality conclusions.
