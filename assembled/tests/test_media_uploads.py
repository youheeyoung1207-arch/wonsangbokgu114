import io, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import app as appmod, db

FAKE_ANALYSIS={
 'site_type':'office','space':{'room_count':1,'fragmentation':'low','confidence':.8},
 'ceiling':{'type':'tex','scope_status':'demolish','coverage':'full','area_pyeong':10,'layers':[],'height_m':2.5,'confidence':.8},
 'walls':[],'flooring':{'type':'deco_deluxe','scope_status':'demolish','coverage':'full','area_pyeong':10,'sanding':False,'hidden_layers':[],'mortar_or_concrete':False,'raised_floor':False,'confidence':.8},
 'fixtures':{'volume':'low','fixed_vs_movable':'mixed','confidence':.8},'electrical_cleanup':{'level':'low','confidence':.8},
 'ventilation_duct':{'level':'none','confidence':.8},'signage':{'present':False,'scope_status':'preserve','length_m':None,'height_m':None,'sky_likely':False,'confidence':.8},
 'exterior_metal':{'present':False,'scope':'none','confidence':.8},'equipment':{'mini_likely':False,'mini_count':None,'mini_accessible':None,'ladder_possible':None,'ladder_for_haul_likely':False,'sky_likely':False,'scaffold_likely':False,'confidence':.8},
 'logistics':{'difficulty':'normal','vehicle_access':True,'elevator':False,'elevator_type':'none','haul_method':'normal','route_length':'short','common_area_protection':False,'onsite_stockpile':'good','confidence':.8},
 'operational_constraints':{'adjacent_occupied_units':False,'work_window_restricted':False,'haul_window_restricted':False,'equipment_window_restricted':False,'night_work':False,'confidence':.8},
 'special_review':False,'needs_more_video':[],'overall_confidence':.8}
FAKE_RESULT={'total_low':1000000,'total_high':1200000,'confidence':.8,'breakdown':[]}

class MediaUploadTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
  self.old_db,self.old_up=db.DB_PATH,appmod.UPLOAD_DIR
  db.DB_PATH=root/'test.db'; appmod.UPLOAD_DIR=root/'uploads'; appmod.UPLOAD_DIR.mkdir()
  db.init_db(); appmod.app.config.update(TESTING=True)
  self.client=appmod.app.test_client()
 def tearDown(self):
  db.DB_PATH,self.tmpdb=db.DB_PATH,self.old_db
  db.DB_PATH=self.old_db; appmod.UPLOAD_DIR=self.old_up; self.tmp.cleanup()
 def base(self): return {'customer_name':'홍길동','customer_phone':'010-1234-5678','privacy_agreed':'yes','construction_type':'demolition','area_pyeong':'10','floor_no':'1','elevator':'no','time_restriction':'day'}
 def post(self,data):
  with patch.object(appmod,'analyze_media',return_value=dict(FAKE_ANALYSIS)) as a, patch.object(appmod,'estimate',return_value=FAKE_RESULT), patch.object(appmod,'_notify_new_lead',return_value=True):
   r=self.client.post('/estimate',data=data,content_type='multipart/form-data')
   return r,a
 def test_photo_only(self):
  d=self.base(); d['photos']=[(io.BytesIO(b'jpg1'),'a.jpg'),(io.BytesIO(b'png2'),'b.png')]
  r,a=self.post(d); self.assertEqual(r.status_code,200); self.assertIsNone(a.call_args.args[0]); self.assertEqual(len(a.call_args.args[1]),2)
  row=db.get_project(1); self.assertIsNone(row['video_path']); self.assertEqual(len(json.loads(row['photo_paths_json'])),2)
 def test_video_only(self):
  d=self.base(); d['video']=(io.BytesIO(b'video'),'a.mp4')
  r,a=self.post(d); self.assertEqual(r.status_code,200); self.assertTrue(a.call_args.args[0]); self.assertEqual(a.call_args.args[1],[])
 def test_video_and_photos(self):
  d=self.base(); d['video']=(io.BytesIO(b'video'),'a.mp4'); d['photos']=[(io.BytesIO(b'x'),'a.jpg')]
  r,a=self.post(d); self.assertEqual(r.status_code,200); self.assertTrue(a.call_args.args[0]); self.assertEqual(len(a.call_args.args[1]),1)
 def test_none_rejected(self):
  r=self.client.post('/estimate',data=self.base(),content_type='multipart/form-data'); self.assertEqual(r.status_code,302); self.assertEqual(len(db.list_projects()),0)

if __name__=='__main__': unittest.main()
