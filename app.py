from __future__ import annotations
import json, os, uuid, re, smtplib, ssl
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, send_file
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from db import init_db, load_rates, create_project, save_analysis, save_estimate, list_projects, get_project, mark_follow_up_requested, purge_expired_videos
from analyzer import analyze_media, MODEL_VERSION
from estimator import estimate

BASE_DIR=Path(__file__).resolve().parent
load_dotenv(BASE_DIR/'.env')
app=Flask(__name__)
app.secret_key=os.getenv('FLASK_SECRET_KEY','dev-key-change-me')
app.config['MAX_CONTENT_LENGTH']=int(os.getenv('MAX_UPLOAD_MB','300'))*1024*1024
UPLOAD_DIR=BASE_DIR/'uploads'; UPLOAD_DIR.mkdir(exist_ok=True)
VIDEO_ALLOWED={'.mp4','.mov','.m4v','.avi','.webm'}
PHOTO_ALLOWED={'.jpg','.jpeg','.png'}
MAX_PHOTOS=10

VIDEO_RETENTION_DAYS=int(os.getenv('UPLOAD_RETENTION_DAYS','30'))
CONTACT_PHONE=os.getenv('CONTACT_PHONE','01077472773')
CONTACT_PHONE_TEL=re.sub(r'[^0-9+]', '', CONTACT_PHONE)

# Visible build marker: helps distinguish the exact code running on Render.
BUILD_VERSION=os.getenv('BUILD_VERSION','v2.7.0-follow-up-request')
BUILD_TIME_KST=os.getenv('BUILD_TIME_KST','2026-09-09 23:20 KST')
RENDER_GIT_COMMIT=(os.getenv('RENDER_GIT_COMMIT') or '').strip()
BUILD_COMMIT=RENDER_GIT_COMMIT[:7] if RENDER_GIT_COMMIT else 'local'

@app.context_processor
def _build_marker():
    return dict(build_version=BUILD_VERSION, build_time_kst=BUILD_TIME_KST, build_commit=BUILD_COMMIT)

@app.before_request
def _cleanup_expired_uploads():
    # V2 scale: lightweight lazy cleanup. Default policy = 30 days.
    try:
        purge_expired_videos(VIDEO_RETENTION_DAYS)
    except Exception:
        app.logger.exception('expired upload cleanup failed')



def _format_phone(v):
    digits=re.sub(r'[^0-9]', '', v or '')
    if len(digits)==11:
        return f'{digits[:3]}-{digits[3:7]}-{digits[7:]}'
    if len(digits)==10:
        return f'{digits[:3]}-{digits[3:6]}-{digits[6:]}'
    return (v or '').strip()

def _valid_phone(v):
    return bool(re.fullmatch(r"[0-9\-+ ]{9,20}", (v or '').strip()))

def _notify_new_lead(project_id, name, phone, result):
    """SMTP email notification. Works with any SMTP provider once env vars are set."""
    host=os.getenv('SMTP_HOST'); user=os.getenv('SMTP_USER'); password=os.getenv('SMTP_PASSWORD')
    to=os.getenv('LEAD_NOTIFY_EMAIL'); sender=os.getenv('SMTP_FROM') or user
    if not all([host,to,sender]):
        app.logger.warning('lead email notification skipped: SMTP_HOST/LEAD_NOTIFY_EMAIL/SMTP_FROM missing')
        return False
    msg=EmailMessage(); msg['Subject']=f'[새 견적 접수] {name} / {phone}'; msg['From']=sender; msg['To']=to
    msg.set_content(f"새 무료견적이 접수되었습니다.\n접수번호: {project_id}\n고객: {name}\n전화: {phone}\n예상견적: {result['total_low']:,} ~ {result['total_high']:,}원\n관리자 페이지에서 확인하세요.")
    port=int(os.getenv('SMTP_PORT','587'))
    if os.getenv('SMTP_SSL','false').lower() in ('1','true','yes'):
        with smtplib.SMTP_SSL(host,port,context=ssl.create_default_context()) as smtp:
            if user: smtp.login(user,password or '')
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host,port,timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if user: smtp.login(user,password or '')
            smtp.send_message(msg)
    return True

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        if not session.get('admin_ok'): return redirect(url_for('admin_login',next=request.path))
        return fn(*args,**kwargs)
    return wrapper

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        expected=os.getenv('ADMIN_PASSWORD')
        if expected and request.form.get('password')==expected:
            session['admin_ok']=True; return redirect(request.args.get('next') or url_for('admin'))
        flash('관리자 비밀번호가 올바르지 않습니다.')
    return render_template('admin_login.html')

@app.get('/admin')
@admin_required
def admin():
    return render_template('admin.html',projects=list_projects())

@app.get('/admin/video/<int:project_id>')
@admin_required
def admin_video(project_id):
    row=get_project(project_id)
    if not row or not row['video_path']: abort(404)
    path=Path(row['video_path'])
    if not path.exists(): abort(404)
    return send_file(path,conditional=True)

@app.get('/admin/photo/<int:project_id>/<int:photo_index>')
@admin_required
def admin_photo(project_id, photo_index):
    row=get_project(project_id)
    if not row: abort(404)
    try:
        photos=json.loads(row['photo_paths_json'] or '[]')
    except (TypeError, json.JSONDecodeError):
        photos=[]
    if photo_index < 0 or photo_index >= len(photos): abort(404)
    path=Path(photos[photo_index])
    if not path.exists(): abort(404)
    return send_file(path,conditional=True)


@app.post('/request-follow-up/<int:project_id>')
def request_follow_up(project_id):
    row=get_project(project_id)
    if not row:
        abort(404)
    requested_at=mark_follow_up_requested(project_id)
    return {'ok': True, 'message': '요청이 접수되었습니다.', 'requested_at': requested_at}

@app.get('/privacy')
def privacy():
    return render_template('privacy.html')

@app.get('/')
def index():
    return render_template('index.html')

@app.post('/estimate')
def make_estimate():
    customer_name=(request.form.get('customer_name') or '').strip()
    customer_phone=(request.form.get('customer_phone') or '').strip()
    privacy_agreed=request.form.get('privacy_agreed')=='yes'
    if len(customer_name)<2:
        flash('이름을 입력해주세요.'); return redirect(url_for('index'))
    if not _valid_phone(customer_phone):
        flash('전화번호를 정확히 입력해주세요.'); return redirect(url_for('index'))
    if not privacy_agreed:
        flash('개인정보 수집·이용 및 영상 분석 외부전송에 동의해주세요.'); return redirect(url_for('index'))
    video=request.files.get('video')
    video = video if video and video.filename else None
    photos=[x for x in request.files.getlist('photos') if x and x.filename]
    if not video and not photos:
        flash('현장 동영상 또는 사진을 최소 1개 올려주세요.')
        return redirect(url_for('index'))
    if len(photos) > MAX_PHOTOS:
        flash('사진은 최대 10장까지 올릴 수 있습니다.')
        return redirect(url_for('index'))
    if video and Path(video.filename).suffix.lower() not in VIDEO_ALLOWED:
        flash('동영상은 MP4, MOV, M4V, AVI, WEBM 형식만 지원합니다.')
        return redirect(url_for('index'))
    if any(Path(x.filename).suffix.lower() not in PHOTO_ALLOWED for x in photos):
        flash('사진은 JPG 또는 PNG 형식만 지원합니다.')
        return redirect(url_for('index'))
    try:
        area=float(request.form.get('area_pyeong') or 0)
        floor_no=int(request.form.get('floor_no') or 1)
    except ValueError:
        flash('평수와 층수를 숫자로 입력해주세요.')
        return redirect(url_for('index'))
    elevator=request.form.get('elevator')=='yes'
    time_restriction=request.form.get('time_restriction') or 'day'
    construction_type=request.form.get('construction_type') or 'demolition'
    if construction_type not in ('demolition','demolition_restoration','restoration'):
        construction_type='demolition'
    restoration_scopes=request.form.getlist('restoration_scope')
    valid_restoration_scopes={
        'ceiling','floor','wall_partition','paint','electrical','fire','hvac','duct',
        'plumbing','door_glass_sash','sign_exterior','waxing','cleaning','other'
    }
    restoration_scopes=[x for x in restoration_scopes if x in valid_restoration_scopes]
    if construction_type!='demolition' and not restoration_scopes:
        flash('원상복구 항목을 하나 이상 선택해주세요.')
        return redirect(url_for('index'))
    video_path=None
    if video:
        name=secure_filename(video.filename)
        path=UPLOAD_DIR/f'{uuid.uuid4().hex}_{name}'
        video.save(path)
        video_path=str(path)
    photo_paths=[]
    for photo in photos:
        name=secure_filename(photo.filename)
        photo_path=UPLOAD_DIR/f'{uuid.uuid4().hex}_{name}'
        photo.save(photo_path)
        photo_paths.append(str(photo_path))
    project_id=create_project(area, floor_no, elevator, time_restriction, video_path, customer_name, customer_phone, privacy_agreed, construction_type, restoration_scopes, photo_paths)
    context={
        'area_pyeong':area,
        'floor_no':floor_no,
        'elevator':elevator,
        'time_restriction':time_restriction,
        'construction_type':construction_type,
        'restoration_scopes':restoration_scopes,
    }
    try:
        analysis=analyze_media(video_path, photo_paths, context)
        analysis['request_scope']={
            'construction_type':construction_type,
            'restoration_scopes':restoration_scopes,
        }
        save_analysis(project_id, MODEL_VERSION, analysis)
        result=estimate(analysis, context, load_rates())
        save_estimate(project_id, result)
        try:
            _notify_new_lead(project_id, customer_name, customer_phone, result)
        except Exception:
            app.logger.exception('lead notification failed')
    except Exception:
        app.logger.exception('analysis failed')
        flash('영상·사진 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.')
        return redirect(url_for('index'))
    finally:
        if os.getenv('KEEP_UPLOADS','true').lower() not in ('1','true','yes'):
            for raw in ([video_path] if video_path else []) + photo_paths:
                try:
                    Path(raw).unlink(missing_ok=True)
                except Exception:
                    app.logger.warning('temporary upload cleanup failed: %s', raw)
    return render_template('result.html', result=result, analysis=analysis, project_id=project_id, context=context, recalculated=False, contact_phone=CONTACT_PHONE, contact_phone_tel=CONTACT_PHONE_TEL, customer_phone_display=_format_phone(customer_phone), follow_up_requested=False)


def _bool_field(name: str) -> bool:
    return request.form.get(name) == 'yes'


def _float_or_none(value):
    try:
        if value is None or str(value).strip() == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@app.post('/recalculate')
def recalculate():
    """사용자가 자동인식 결과를 확인/수정한 뒤 같은 견적엔진으로 다시 계산."""
    try:
        analysis=json.loads(request.form.get('analysis_json') or '{}')
        context=json.loads(request.form.get('context_json') or '{}')
        project_id=int(request.form.get('project_id') or 0)
    except (json.JSONDecodeError, ValueError, TypeError):
        flash('수정값을 읽지 못했습니다. 다시 영상 분석부터 진행해주세요.')
        return redirect(url_for('index'))

    area=_float_or_none(request.form.get('area_pyeong'))
    if area is not None and area > 0:
        context['area_pyeong']=area
    try:
        context['floor_no']=int(request.form.get('floor_no') or context.get('floor_no') or 1)
    except ValueError:
        pass
    context['elevator']=_bool_field('elevator')
    context['time_restriction']=request.form.get('time_restriction') or context.get('time_restriction') or 'day'

    floor=analysis.setdefault('flooring', {})
    floor['type']=request.form.get('floor_type') or floor.get('type') or 'unknown'
    floor['scope_status']=request.form.get('floor_scope') or floor.get('scope_status') or 'confirm_needed'
    floor['coverage']=request.form.get('floor_coverage') or floor.get('coverage') or 'unknown'
    floor_area=_float_or_none(request.form.get('floor_area'))
    floor['area_pyeong']=floor_area
    floor['mortar_or_concrete']=_bool_field('floor_mortar')
    floor['raised_floor']=_bool_field('raised_floor')

    ceiling=analysis.setdefault('ceiling', {})
    ceiling['type']=request.form.get('ceiling_type') or ceiling.get('type') or 'unknown'
    ceiling['scope_status']=request.form.get('ceiling_scope') or ceiling.get('scope_status') or 'confirm_needed'
    ceiling['coverage']=request.form.get('ceiling_coverage') or ceiling.get('coverage') or 'unknown'
    ceiling['area_pyeong']=_float_or_none(request.form.get('ceiling_area'))

    fixtures=analysis.setdefault('fixtures', {})
    fixtures['volume']=request.form.get('fixtures_volume') or fixtures.get('volume') or 'low'
    fixtures['fixed_vs_movable']=request.form.get('fixtures_type') or fixtures.get('fixed_vs_movable') or 'unknown'

    elec=analysis.setdefault('electrical_cleanup', {})
    elec['level']=request.form.get('electrical_level') or elec.get('level') or 'low'

    signage=analysis.setdefault('signage', {})
    signage['present']=_bool_field('signage_present')
    signage['scope_status']=request.form.get('signage_scope') or signage.get('scope_status') or 'confirm_needed'
    signage['length_m']=_float_or_none(request.form.get('signage_length'))

    eq=analysis.setdefault('equipment', {})
    eq['mini_likely']=_bool_field('mini_likely')
    try:
        eq['mini_count']=max(1, int(request.form.get('mini_count') or 1)) if eq['mini_likely'] else None
    except ValueError:
        eq['mini_count']=1 if eq['mini_likely'] else None
    mini_access=request.form.get('mini_accessible')
    eq['mini_accessible']=True if mini_access=='yes' else False if mini_access=='no' else None
    eq['ladder_for_haul_likely']=_bool_field('ladder_for_haul')

    log=analysis.setdefault('logistics', {})
    log['difficulty']=request.form.get('logistics_difficulty') or log.get('difficulty') or 'normal'
    log['haul_method']=request.form.get('haul_method') or log.get('haul_method') or 'unknown'
    log['elevator']=context.get('elevator')

    ops=analysis.setdefault('operational_constraints', {})
    ops['night_work']=context.get('time_restriction')=='night'
    ops['work_window_restricted']=context.get('time_restriction')=='restricted'

    # 사용자가 직접 검토한 입력임을 기록. 모델 confidence를 임의로 올리지는 않음.
    analysis['user_reviewed']=True
    result=estimate(analysis, context, load_rates())
    if project_id:
        try:
            save_analysis(project_id, MODEL_VERSION + '+user-reviewed', analysis)
            save_estimate(project_id, result)
        except Exception:
            app.logger.exception('recalculation save failed')
    project_row=get_project(project_id) if project_id else None
    return render_template('result.html', result=result, analysis=analysis, project_id=project_id, context=context, recalculated=True, contact_phone=CONTACT_PHONE, contact_phone_tel=CONTACT_PHONE_TEL, customer_phone_display=_format_phone(project_row['customer_phone'] if project_row else ''), follow_up_requested=bool(project_row and project_row['requested_at']))

if __name__=='__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5000')), debug=os.getenv('FLASK_DEBUG')=='1')
else:
    init_db()
