"""Host-owned deliverable checks. These do not judge creative quality."""
import json
import math
from pathlib import Path
from PIL import Image


def validate_artifacts(work, duration):
    work = Path(work)
    checks = {}
    try:
        data = json.loads((work / "storyboard.json").read_text())
        shots = data.get("shots", []) if isinstance(data, dict) else data
        valid = isinstance(shots, list) and bool(shots)
        last_end = 0
        for shot in shots if valid else []:
            start, end = shot["start"], shot["end"]
            valid = valid and all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in [start, end])
            valid = valid and 0 <= start < end <= duration + 0.15 and start >= last_end - 0.15
            valid = valid and bool(str(shot.get("description", "")).strip())
            last_end = end
        checks["timecoded_storyboard"] = bool(valid and shots[0]["start"] <= 0.15 and last_end >= duration - 0.15)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        checks["timecoded_storyboard"] = False
    try:
        with Image.open(work / "output/contact-sheet.png") as image:
            image.verify()
        checks["decodable_contact_sheet"] = True
    except (OSError, ValueError, SyntaxError):
        checks["decodable_contact_sheet"] = False
    try:
        checks["nonempty_qa"] = len((work / "output/qa.md").read_text().strip()) >= 32
    except (OSError, ValueError):
        checks["nonempty_qa"] = False
    return {"passed": all(checks.values()), "checks": checks,
            "limitations": "Checks file formats and time coverage; story quality, truth of QA and originality require human review."}
