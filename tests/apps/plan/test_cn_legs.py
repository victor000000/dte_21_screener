"""Public source cannot silently preload a private broker book."""
import unittest
from apps.plan.cn_legs import CN

class PublicBook(unittest.TestCase):
    def test_private_transcription_is_not_distributed(self):
        self.assertEqual(CN, [])
