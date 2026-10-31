# Requested run status

The selected track is 黃小琥 Tiger Huang — 現在那邊是幾點？,
from https://www.youtube.com/watch?v=VDzkjosrJO4. Use the full supplied audio
unless an excerpt is requested.

The exact conditions are Sol 6.1 medium/high/max/ultra and Astra high/max,
all using fresh, filesystem-isolated, persistent native goals. Each condition
receives identical inputs and the same 500,000-token / two-hour limits.

The 2026-10-31 readiness check successfully created a separate paused native
goal for each of the six exact model/effort combinations and verified their
effective configuration. Native shell execution was also checked inside the
namespace: it sees `/workspace/run`, not the host workspace or sibling runs.
This readiness check requested no model turns and generated no music videos.

**The actual music-video benchmark is blocked on the song's audio file.** The
cloud environment rejects direct YouTube requests with HTTP 403, and no source
audio for the selected track has been supplied. The synthetic test fixture has
not been substituted for the selected music.

Once an MP3, WAV or M4A of that track is supplied, follow the exact commands in
README.md under "Requested isolated goal run". Execution of these six conditions
has already been authorized; no additional permission question is needed.
