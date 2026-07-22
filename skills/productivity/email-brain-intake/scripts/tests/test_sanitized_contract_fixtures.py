import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from email_brain_contract import validate_payload, validate_receipt


class SanitizedFixturesTests(unittest.TestCase):
    def test_every_published_receipt_fixture_validates(self):
        path = SCRIPTS.parent / "references" / "sanitized-contract-fixtures.v1.json"
        fixture = json.loads(path.read_text())
        self.assertTrue(fixture["sanitized"])
        validate_payload(fixture["request"]["payload"])
        for receipt in fixture["receipts"].values():
            validate_receipt(receipt)

    def test_schema_hash_manifest_matches_exact_files(self):
        references = SCRIPTS.parent / "references"
        manifest = json.loads((references / "schema-hashes.v1.json").read_text())
        for name, expected in manifest["artifacts"].items():
            actual = "sha256:" + hashlib.sha256((references / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
