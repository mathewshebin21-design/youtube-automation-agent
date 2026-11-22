import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from qa import validate

class QATests(unittest.TestCase):
    def test_missing_media_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            result=validate(pathlib.Path(d)/"missing.mp4")
            self.assertEqual(result["status"],"FAIL")
            self.assertFalse(result.get("publish_allowed",False))
    def test_empty_media_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"empty.mp4"
            p.touch()
            self.assertEqual(validate(p)["status"],"FAIL")

if __name__=="__main__":
    unittest.main()
