"""Link checking must fail on broken local content without requesting the web."""
import tempfile
import unittest
from pathlib import Path
from scripts.check_docs import REQUIRED, anchors, check


class DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in REQUIRED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# Example\n')

    def test_valid_links_anchors_and_external_urls(self):
        (self.root / 'README.md').write_text('[Guide](docs/API.md#example) [Web](https://example.invalid/)')
        self.assertEqual(check(self.root), [])
        self.assertEqual(anchors('# Same\n# Same\n'), {'same', 'same-1'})

    def test_broken_local_targets_anchors_and_source_references(self):
        (self.root / 'README.md').write_text('[Absent](missing.md) [Anchor](docs/API.md#wrong) `apps/absent.py`')
        failures = check(self.root)
        self.assertEqual(len(failures), 3)

    def test_fenced_examples_and_missing_required_guides(self):
        (self.root / 'README.md').write_text('```md\n[Example](not-a-real-file.md)\n```\n')
        self.assertEqual(check(self.root), [])
        (self.root / 'docs/API.md').unlink()
        self.assertTrue(any('Missing canonical guide' in x for x in check(self.root)))
