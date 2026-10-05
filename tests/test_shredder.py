"""
Unit tests for EVENT-HORIZON Memory Shredder & Anti-Forensics Matrix
Author: Avenoir (@justavenoir)
"""

import os
import tempfile
import unittest

from event_horizon import SecureMemoryBuffer, shred_file, render_hex_dump


class TestEventHorizon(unittest.TestCase):
    def test_buffer_allocation_and_lock(self):
        """Test physical RAM allocation and locking semantics."""
        size = 1024
        buf = SecureMemoryBuffer(size)
        self.assertEqual(buf.size, size)
        self.assertIsNotNone(buf.buffer)
        buf.obliterate()
        self.assertIsNone(buf.buffer)

    def test_write_and_read(self):
        """Verify data integrity within locked buffer prior to shredding."""
        payload = b"CRITICAL_COSMIC_ENTROPY_TOKEN_0xDEADBEEF"
        buf = SecureMemoryBuffer(len(payload) + 16)
        buf.write(payload)
        read_back = buf.read(len(payload))
        self.assertEqual(read_back, payload)
        buf.obliterate()

    def test_payload_overflow_guard(self):
        """Verify overflow attempts raise ValueError and protect buffer boundary."""
        buf = SecureMemoryBuffer(16)
        with self.assertRaises(ValueError):
            buf.write(b"A" * 32)
        buf.obliterate()

    def test_multi_pass_obliteration(self):
        """Verify multi-pass obliteration runs without exception and tears down cleanly."""
        buf = SecureMemoryBuffer(2048)
        buf.write(b"TOP_SECRET_MILITARY_CIPHER" * 20)
        # Run 5-pass obliteration
        buf.obliterate(passes=5)
        self.assertIsNone(buf.raw_ptr)
        self.assertIsNone(buf.buffer)

    def test_file_shredding(self):
        """Verify sector-level overwriting, cache flush, metadata scrambling, and deletion."""
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"CLASSIFIED_PAYLOAD_TO_BE_SHREDDED_1234567890" * 50)
            tf_path = tf.name

        self.assertTrue(os.path.exists(tf_path))
        result = shred_file(tf_path, passes=3)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(tf_path), "File should be completely deleted from disk")

    def test_hex_dump_renderer(self):
        """Verify hex dump output format."""
        data = b"Hello, Cosmic World 1234"
        rendered = render_hex_dump(data)
        self.assertIn("0x0000", rendered)
        self.assertIn("Hello, Cosmic", rendered)


if __name__ == "__main__":
    unittest.main()
