from __future__ import annotations
import base64, json, os, re
from pathlib import Path
import cv2
import requests

MODEL_VERSION = 'vision-v2-history-grounded-keyframes'

PROMPT = '''
당신은 철거 현장을 보는 분석기다. 가격을 계산하지 마라.
업로드된 현장 영상의 키프레임과/또는 현장 사진을 보고 아래 JSON 구조로만 답하라.
확실하지 않은 것은 null, unknown, confirm_needed 또는 낮은 confidence로 표시하라.
현장 면적/층수 등 사용자 입력값을 존중하되, 보이지 않는 물량을 임의로 전체 면적에 채우지 마라.

핵심 원칙:
- 보이는 물체와 철거범위는 다르다. scope_status를 demolish / preserve / restoration / partial / confirm_needed로 구분한다.
- 바닥은 visible finish와 hidden lower layer/mortar/concrete/raised floor를 분리한다.
- 천장은 tex-only, mytone, tex+gypsum, gypsum, wood frame, light-gauge metal 등 층구성을 구분한다. 마이톤 흡음텍스가 확인되면 ceiling.type="mytone"으로 반환한다.
- 벽은 gypsum_partition, wood, masonry, glass, alc_block, steel_plate, soundproof_multilayer 등으로 구분한다.
- 업종명만으로 폐기물/가격을 결정하지 말고 실제 방수, 가벽량, 집기량, 전기·환기 밀도를 본다.
- 층수만으로 반출 난이도를 정하지 말고 사다리차 가능 여부, 엘리베이터 종류, 운반거리, 공용부, 차량 접근을 본다.
- 작업시간 제한, 주변 영업장, 폐기물 반출 가능시간, 장비 사용 가능시간을 별도 조건으로 찾는다.
- 1층 간판도 사다리 작업을 기본으로 보지 말고 일반 간판 철거는 안전상 스카이 가능성을 높게 평가한다.
- 특수 공장설비, 화학오염 의심, 고층고/비계, 구조에 가까운 철거는 special_review=true로 한다.

JSON schema:
{
  "site_type": "office|restaurant|cafe|academy|clinic|animal_hospital|hair_salon|karaoke|retail|factory|sauna|daycare|auditorium|gosiwon|other|unknown",
  "space": {"room_count": null, "fragmentation":"low|medium|high|unknown", "confidence":0.0},
  "ceiling": {"type":"tex|mytone|gypsum|smc|open|wood_frame|unknown", "scope_status":"demolish|preserve|restoration|partial|confirm_needed", "coverage":"full|partial|unknown", "area_pyeong":null, "layers":[], "height_m":null, "confidence":0.0},
  "walls": [{"type":"gypsum_partition|wood|masonry|glass|alc_block|steel_plate|soundproof_multilayer|unknown", "scope_status":"demolish|preserve|partial|confirm_needed", "length_m":null, "height_m":null, "sides":2, "layers_per_side":2, "hidden_infill":null, "confidence":0.0}],
  "flooring": {"type":"deco_deluxe|carpet_tile|wood_floor|epoxy|polished_tile|porcelain_tile|vinyl_sheet|unknown", "scope_status":"demolish|preserve|partial|confirm_needed", "coverage":"full|partial|unknown", "area_pyeong":null, "sanding":false, "hidden_layers":[], "mortar_or_concrete":false, "raised_floor":false, "confidence":0.0},
  "fixtures": {"volume":"low|medium|high", "fixed_vs_movable":"mostly_fixed|mixed|mostly_movable|unknown", "confidence":0.0},
  "electrical_cleanup": {"level":"low|medium|high", "confidence":0.0},
  "ventilation_duct": {"level":"none|low|medium|high", "confidence":0.0},
  "signage": {"present":false, "scope_status":"demolish|preserve|confirm_needed", "length_m":null, "height_m":null, "sky_likely":true, "confidence":0.0},
  "exterior_metal": {"present":false, "scope":"none|small|large", "confidence":0.0},
  "equipment": {"mini_likely":false, "mini_count":null, "mini_accessible":null, "ladder_possible":null, "ladder_for_haul_likely":false, "sky_likely":false, "scaffold_likely":false, "confidence":0.0},
  "logistics": {"difficulty":"easy|normal|hard", "vehicle_access":true, "elevator":null, "elevator_type":"freight|passenger|none|unknown", "haul_method":"normal|ladder|external_window|unknown", "route_length":"short|medium|long|unknown", "common_area_protection":false, "onsite_stockpile":"good|limited|none|unknown", "confidence":0.0},
  "operational_constraints": {"adjacent_occupied_units":false, "work_window_restricted":false, "haul_window_restricted":false, "equipment_window_restricted":false, "night_work":false, "confidence":0.0},
  "special_review": false,
  "needs_more_video": [],
  "overall_confidence": 0.0
}
'''

def extract_keyframes(video_path: str, max_frames: int = 12):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frames / fps if fps else 0
    if duration <= 0:
        times = [0]
    else:
        step = max(duration / max_frames, 1.0)
        times = [i * step for i in range(max_frames) if i * step < duration]
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        if max(h, w) > 1280:
            scale = 1280 / max(h, w)
            frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if ok:
            out.append(base64.b64encode(buf.tobytes()).decode('ascii'))
    cap.release()
    return out

def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r'^```json\s*|^```\s*|```$', '', text, flags=re.I|re.M).strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError('JSON 응답을 찾지 못했습니다.')
    return json.loads(text[start:end+1])

def _photo_inline_data(photo_path: str):
    path=Path(photo_path)
    mime='image/png' if path.suffix.lower()=='.png' else 'image/jpeg'
    return {'inline_data': {'mime_type': mime, 'data': base64.b64encode(path.read_bytes()).decode('ascii')}}

def analyze_media(video_path: str | None, photo_paths: list[str] | None, context: dict):
    api_key = os.getenv('GEMINI_API_KEY', '').strip()
    if not api_key:
        return {
            'analysis_mode': 'demo_no_api_key',
            'site_type':'unknown',
            'space': {'room_count':None,'fragmentation':'unknown','confidence':0.0},
            'ceiling': {'type':'unknown','scope_status':'confirm_needed','coverage':'unknown','area_pyeong':None,'layers':[],'height_m':None,'confidence':0.0},
            'walls': [],
            'flooring': {'type':'unknown','scope_status':'confirm_needed','coverage':'unknown','area_pyeong':None,'sanding':False,'hidden_layers':[],'mortar_or_concrete':False,'raised_floor':False,'confidence':0.0},
            'fixtures': {'volume':'medium','fixed_vs_movable':'unknown','confidence':0.0},
            'electrical_cleanup': {'level':'medium','confidence':0.0},
            'ventilation_duct': {'level':'none','confidence':0.0},
            'signage': {'present':False,'scope_status':'confirm_needed','length_m':None,'height_m':None,'sky_likely':True,'confidence':0.0},
            'exterior_metal': {'present':False,'scope':'none','confidence':0.0},
            'equipment': {'mini_likely':False,'mini_count':None,'mini_accessible':None,'ladder_possible':None,'ladder_for_haul_likely':False,'sky_likely':False,'scaffold_likely':False,'confidence':0.0},
            'logistics': {'difficulty':'normal','vehicle_access':True,'elevator':context.get('elevator'),'elevator_type':'unknown','haul_method':'unknown','route_length':'unknown','common_area_protection':False,'onsite_stockpile':'unknown','confidence':0.0},
            'operational_constraints': {'adjacent_occupied_units':False,'work_window_restricted':context.get('time_restriction')=='restricted','haul_window_restricted':False,'equipment_window_restricted':False,'night_work':context.get('time_restriction')=='night','confidence':0.0},
            'special_review': False,
            'needs_more_video':['GEMINI_API_KEY를 설정하면 영상·사진 자동분석이 작동합니다.'],
            'overall_confidence': 0.05
        }

    frames = extract_keyframes(video_path) if video_path else []
    parts = [{'text': PROMPT + '\n사용자 입력: ' + json.dumps(context, ensure_ascii=False)}]
    for img in frames:
        parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': img}})
    for photo_path in (photo_paths or []):
        parts.append(_photo_inline_data(photo_path))
    model = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    payload = {'contents':[{'parts':parts}], 'generationConfig': {'temperature':0.1, 'responseMimeType':'application/json'}}
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    text = data['candidates'][0]['content']['parts'][0]['text']
    parsed = _extract_json(text)
    parsed['analysis_mode'] = 'gemini_video_photos' if video_path and photo_paths else ('gemini_keyframes' if video_path else 'gemini_photos')
    return parsed

def analyze_video(video_path: str, context: dict):
    return analyze_media(video_path, [], context)
