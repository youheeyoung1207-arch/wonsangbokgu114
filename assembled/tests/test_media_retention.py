import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
import db
class Retention(unittest.TestCase):
 def test_expired_video_and_photos_deleted(self):
  t=tempfile.TemporaryDirectory(); root=Path(t.name); old=db.DB_PATH; db.DB_PATH=root/'x.db'; db.init_db()
  v=root/'v.mp4'; p1=root/'1.jpg'; p2=root/'2.png'
  for x in (v,p1,p2): x.write_bytes(b'x')
  pid=db.create_project(10,1,False,'day',str(v),photo_paths=[str(p1),str(p2)])
  cutoff=(datetime.now(timezone.utc)-timedelta(days=31)).isoformat()
  with db.connect() as c:c.execute('UPDATE projects SET created_at=? WHERE id=?',(cutoff,pid))
  self.assertEqual(db.purge_expired_videos(30),3)
  row=db.get_project(pid); self.assertIsNone(row['video_path']); self.assertIsNone(row['photo_paths_json']); self.assertFalse(v.exists()); self.assertFalse(p1.exists()); self.assertFalse(p2.exists())
  db.DB_PATH=old;t.cleanup()
if __name__=='__main__':unittest.main()
