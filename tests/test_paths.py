"""Cache accounting and LRU eviction tests (app/paths.py)."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from app import paths


class CachePruneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "lut").mkdir()
        (self.root / "full").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, relative: str, size: int, age_seconds: float) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_usage_counts_nested_files(self) -> None:
        self._write("lut/a.cube", 1000, 7200)
        self._write("full/b.rgba", 2000, 7200)
        total, count = paths.cache_usage(self.root)
        self.assertEqual(count, 2)
        self.assertEqual(total, 3000)

    def test_prune_is_a_noop_under_the_limit(self) -> None:
        self._write("lut/a.cube", 1000, 7200)
        removed, freed = paths.prune_cache(max_bytes=10_000, root=self.root)
        self.assertEqual((removed, freed), (0, 0))
        self.assertTrue((self.root / "lut" / "a.cube").is_file())

    def test_prune_evicts_oldest_first_until_under_the_cap(self) -> None:
        oldest = self._write("lut/old.cube", 4000, 9000)
        middle = self._write("full/mid.rgba", 4000, 5000)
        newest = self._write("lut/new.cube", 4000, 3000)
        removed, freed = paths.prune_cache(max_bytes=8000, root=self.root)
        self.assertEqual(removed, 1)
        self.assertEqual(freed, 4000)
        self.assertFalse(oldest.exists())
        self.assertTrue(middle.is_file())
        self.assertTrue(newest.is_file())

    def test_prune_never_touches_recent_files(self) -> None:
        # A render in flight resolves its cache paths at process start; deleting
        # a file written seconds ago would break it.
        self._write("lut/running.cube", 5000, 10)
        self._write("lut/stale.cube", 5000, 7200)
        removed, _freed = paths.prune_cache(
            max_bytes=1000, min_age_seconds=600, root=self.root
        )
        self.assertEqual(removed, 1)
        self.assertTrue((self.root / "lut" / "running.cube").is_file())
        self.assertFalse((self.root / "lut" / "stale.cube").exists())

    def test_prune_keeps_evicting_when_recent_files_alone_exceed_the_cap(self) -> None:
        self._write("lut/a.cube", 5000, 5)
        self._write("lut/b.cube", 5000, 5)
        removed, freed = paths.prune_cache(max_bytes=1000, root=self.root)
        self.assertEqual((removed, freed), (0, 0))
        total, _count = paths.cache_usage(self.root)
        self.assertEqual(total, 10_000)

    def test_missing_cache_directory_is_tolerated(self) -> None:
        missing = self.root / "nope"
        self.assertEqual(paths.cache_usage(missing), (0, 0))
        self.assertEqual(paths.prune_cache(root=missing), (0, 0))


if __name__ == "__main__":
    unittest.main()
