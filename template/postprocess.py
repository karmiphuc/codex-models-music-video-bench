from pathlib import Path
import json
from lab.media import contact_sheet, validate_video

root = Path(__file__).resolve().parent
video = root / "output/final.mp4"
result = validate_video(video, json.loads((root / "spec.json").read_text()))
(root / "output/validation.json").write_text(json.dumps(result, indent=2) + "\n")
if result.get("checks", {}).get("video_stream"):
    contact_sheet(video, root / "output/contact-sheet.png")
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
