import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import db


class VideoRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.old_db_path = db.DB_PATH
        db.DB_PATH = self.base / 'estimator.db'
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def _insert_project(self, created_at, video_path):
        with db.connect() as conn:
            cur = conn.execute(
                '''INSERT INTO projects(
                    created_at, video_path, area_pyeong, floor_no, elevator, status
                ) VALUES(?,?,?,?,?,?)''',
                (created_at, video_path, 10, 1, 1, 'uploaded'),
            )
            return cur.lastrowid

    def test_purge_deletes_only_videos_older_than_30_days(self):
        old_file = self.base / 'old.mp4'
        recent_file = self.base / 'recent.mp4'
        old_file.write_bytes(b'old')
        recent_file.write_bytes(b'recent')

        now = datetime.now(timezone.utc)
        old_id = self._insert_project((now - timedelta(days=31)).isoformat(), str(old_file))
        recent_id = self._insert_project((now - timedelta(days=29)).isoformat(), str(recent_file))
        empty_id = self._insert_project((now - timedelta(days=40)).isoformat(), '')
        null_id = self._insert_project((now - timedelta(days=40)).isoformat(), None)

        deleted = db.purge_expired_videos(30)

        self.assertEqual(deleted, 1)
        self.assertFalse(old_file.exists())
        self.assertTrue(recent_file.exists())

        with db.connect() as conn:
            old_path = conn.execute('SELECT video_path FROM projects WHERE id=?', (old_id,)).fetchone()['video_path']
            recent_path = conn.execute('SELECT video_path FROM projects WHERE id=?', (recent_id,)).fetchone()['video_path']
            empty_path = conn.execute('SELECT video_path FROM projects WHERE id=?', (empty_id,)).fetchone()['video_path']
            null_path = conn.execute('SELECT video_path FROM projects WHERE id=?', (null_id,)).fetchone()['video_path']

        self.assertIsNone(old_path)
        self.assertEqual(recent_path, str(recent_file))
        self.assertEqual(empty_path, '')
        self.assertIsNone(null_path)


if __name__ == '__main__':
    unittest.main()
