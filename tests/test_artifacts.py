import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from lab.artifacts import validate_artifacts


class ArtifactTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "output").mkdir()
        (root / "storyboard.json").write_text(json.dumps({"concept":"Fixture", "shots":[
            {"start":0,"end":1,"description":"First shot"},
            {"start":1,"end":2,"description":"Ending"}]}))
        Image.new("RGB", (320, 180)).save(root / "output/contact-sheet.png")
        (root / "output/qa.md").write_text("Offline test fixture with inspected frames and recorded limitations.")
        return root

    def test_valid_artifact_formats(self):
        self.assertTrue(validate_artifacts(self.fixture(), 2)["passed"])

    def test_empty_or_incomplete_storyboard_is_not_a_valid_delivery(self):
        root = self.fixture()
        for data in [[], {}, [{"start":0,"end":1,"description":"Only half"}],
                     [{"start":0,"end":float("nan"),"description":"Invalid time"}]]:
            (root / "storyboard.json").write_text(json.dumps(data))
            self.assertFalse(validate_artifacts(root, 2)["checks"]["timecoded_storyboard"])

    def test_invalid_contact_sheet_and_empty_qa_are_rejected(self):
        root = self.fixture()
        (root / "output/contact-sheet.png").write_text("not an image")
        (root / "output/qa.md").write_text("")
        result = validate_artifacts(root, 2)
        self.assertFalse(result["checks"]["decodable_contact_sheet"])
        self.assertFalse(result["checks"]["nonempty_qa"])


if __name__ == "__main__":
    unittest.main()
