from __future__ import annotations
import sqlite3, json
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'data' / 'estimator.db'
RATES_PATH = BASE_DIR / 'data' / 'default_rates.json'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  customer_name TEXT,
  customer_phone TEXT,
  privacy_agreed INTEGER NOT NULL DEFAULT 0,
  privacy_agreed_at TEXT,
  construction_type TEXT,
  restoration_scopes_json TEXT,
  area_pyeong REAL,
  floor_no INTEGER,
  elevator INTEGER,
  time_restriction TEXT,
  video_path TEXT,
  photo_paths_json TEXT,
  status TEXT NOT NULL DEFAULT 'uploaded',
  requested_at TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  model_version TEXT,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS estimates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  total_low INTEGER NOT NULL,
  total_high INTEGER NOT NULL,
  confidence REAL NOT NULL,
  breakdown_json TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  actual_contract_amount INTEGER,
  actual_cost INTEGER,
  actual_people INTEGER,
  actual_days REAL,
  actual_waste_json TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(id)
);
'''

PROJECT_MIGRATIONS={
 'customer_name':'TEXT','customer_phone':'TEXT','privacy_agreed':'INTEGER NOT NULL DEFAULT 0',
 'privacy_agreed_at':'TEXT','construction_type':'TEXT','restoration_scopes_json':'TEXT',
 'photo_paths_json':'TEXT','requested_at':'TEXT'
}

def _now(): return datetime.now(timezone.utc).isoformat()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; return conn

def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols={r['name'] for r in conn.execute('PRAGMA table_info(projects)').fetchall()}
        for name, ddl in PROJECT_MIGRATIONS.items():
            if name not in cols:
                conn.execute(f'ALTER TABLE projects ADD COLUMN {name} {ddl}')

def load_rates(): return json.loads(RATES_PATH.read_text(encoding='utf-8'))

def create_project(area_pyeong, floor_no, elevator, time_restriction, video_path,
                   customer_name='', customer_phone='', privacy_agreed=False,
                   construction_type='demolition', restoration_scopes=None, photo_paths=None):
    with connect() as conn:
        cur=conn.execute('''INSERT INTO projects(
          created_at,customer_name,customer_phone,privacy_agreed,privacy_agreed_at,
          construction_type,restoration_scopes_json,area_pyeong,floor_no,elevator,time_restriction,video_path,photo_paths_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
          _now(),customer_name,customer_phone,int(bool(privacy_agreed)),_now() if privacy_agreed else None,
          construction_type,json.dumps(restoration_scopes or [],ensure_ascii=False),area_pyeong,floor_no,int(bool(elevator)),time_restriction,video_path,
          json.dumps(photo_paths or [],ensure_ascii=False)))
        return cur.lastrowid

def save_analysis(project_id, model_version, data):
    with connect() as conn:
        conn.execute('INSERT INTO analyses(project_id,created_at,model_version,raw_json) VALUES(?,?,?,?)',
                     (project_id,_now(),model_version,json.dumps(data,ensure_ascii=False)))

def save_estimate(project_id, result):
    with connect() as conn:
        conn.execute('INSERT INTO estimates(project_id,created_at,total_low,total_high,confidence,breakdown_json) VALUES(?,?,?,?,?,?)',
                     (project_id,_now(),result['total_low'],result['total_high'],result['confidence'],json.dumps(result['breakdown'],ensure_ascii=False)))

def list_projects(limit=200):
    with connect() as conn:
        return conn.execute('''SELECT p.*, e.total_low,e.total_high,e.confidence,e.breakdown_json,
          a.raw_json AS analysis_json FROM projects p
          LEFT JOIN estimates e ON e.id=(SELECT id FROM estimates WHERE project_id=p.id ORDER BY id DESC LIMIT 1)
          LEFT JOIN analyses a ON a.id=(SELECT id FROM analyses WHERE project_id=p.id ORDER BY id DESC LIMIT 1)
          ORDER BY p.id DESC LIMIT ?''',(limit,)).fetchall()

def get_project(project_id):
    with connect() as conn:
        return conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()



def mark_follow_up_requested(project_id):
    """Mark a quote as explicitly requested by the customer. Idempotent."""
    with connect() as conn:
        row=conn.execute('SELECT requested_at FROM projects WHERE id=?',(project_id,)).fetchone()
        if not row:
            return None
        requested_at=row['requested_at'] or _now()
        if not row['requested_at']:
            conn.execute("UPDATE projects SET requested_at=?, status='requested' WHERE id=?",(requested_at,project_id))
        return requested_at

def purge_expired_videos(retention_days=30):
    """Delete expired video/photo files and clear stale DB paths. Returns deleted file count."""
    from datetime import timedelta
    cutoff=(datetime.now(timezone.utc)-timedelta(days=max(1,int(retention_days)))).isoformat()
    deleted=0
    with connect() as conn:
        rows=conn.execute(
            'SELECT id,video_path,photo_paths_json FROM projects WHERE created_at < ? AND '
            '((video_path IS NOT NULL AND video_path != ?) OR '
            '(photo_paths_json IS NOT NULL AND photo_paths_json != ? AND photo_paths_json != ?))',
            (cutoff, '', '', '[]'),
        ).fetchall()
        for row in rows:
            paths=[]
            if row['video_path']:
                paths.append(row['video_path'])
            try:
                paths.extend(json.loads(row['photo_paths_json'] or '[]'))
            except (TypeError, json.JSONDecodeError):
                pass
            for raw in paths:
                if not raw:
                    continue
                try:
                    Path(raw).unlink(missing_ok=True)
                except Exception:
                    pass
                deleted += 1
            conn.execute('UPDATE projects SET video_path=NULL, photo_paths_json=NULL WHERE id=?',(row['id'],))
    return deleted
