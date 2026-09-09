from __future__ import annotations
import json, math
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / 'data' / 'historical_matches.json'


def load_history():
    return json.loads(DATA_PATH.read_text(encoding='utf-8'))


def _analysis_features(analysis: dict, context: dict) -> set[str]:
    f=set()
    site=(analysis.get('site_type') or '').strip()
    if site: f.add(site)
    fixtures=(analysis.get('fixtures') or {}).get('volume')
    if fixtures=='high': f.add('fixtures_high')
    elec=(analysis.get('electrical_cleanup') or {}).get('level')
    if elec=='high': f.add('electrical_high')
    log=analysis.get('logistics') or {}
    if log.get('common_area_protection'): f.add('common_area_protection')
    if log.get('haul_method')=='ladder': f.add('ladder_haul')
    if log.get('difficulty')=='hard': f.add('hard_logistics')
    ops=analysis.get('operational_constraints') or {}
    if ops.get('adjacent_occupied_units'): f.add('adjacent_occupied_units')
    if ops.get('work_window_restricted'): f.add('time_restricted')
    eq=analysis.get('equipment') or {}
    if eq.get('mini_likely'): f.add('mini_equipment')
    if (eq.get('mini_count') or 0) >= 2: f.add('mini_equipment_multiple')
    space=analysis.get('space') or {}
    if (space.get('room_count') or 0) >= 8: f.add('many_rooms')
    if space.get('fragmentation')=='high': f.add('many_rooms')
    if analysis.get('special_review'): f.add('special_review')
    if int(context.get('floor_no') or 1) < 0: f.add('basement')
    return f


def find_comparables(analysis: dict, context: dict, limit: int=3):
    data=load_history()
    target_features=_analysis_features(analysis, context)
    target_site=(analysis.get('site_type') or '').strip()
    target_floor=int(context.get('floor_no') or 1)
    area=float(context.get('area_pyeong') or 0)
    scored=[]
    for c in data.get('matches', []):
        score=0.0
        reasons=[]
        if target_site and c.get('site_type')==target_site:
            score += 5.0; reasons.append('동일 업종')
        cfloor=c.get('floor_no')
        if cfloor is not None:
            d=abs(int(cfloor)-target_floor)
            if d==0: score += 1.5; reasons.append('동일 층')
            elif d<=1: score += 0.5
        carea=c.get('area_pyeong')
        if area and carea:
            ratio=max(area, float(carea))/max(1.0,min(area,float(carea)))
            if ratio <= 1.25: score += 2.0; reasons.append('면적 유사')
            elif ratio <= 1.7: score += 0.8
        overlap=target_features.intersection(set(c.get('features') or []))
        score += min(4.0, len(overlap)*0.8)
        if overlap: reasons.append('조건 '+','.join(sorted(overlap)[:3]))
        if c.get('match_confidence')=='high': score += 0.7
        if score>0:
            scored.append({**c, 'similarity_score':round(score,2), 'similarity_reason':' / '.join(reasons)})
    scored.sort(key=lambda x:x['similarity_score'], reverse=True)
    return scored[:limit]


def evidence_summary(analysis: dict, context: dict):
    comps=find_comparables(analysis, context)
    strong=[c for c in comps if c['similarity_score']>=5.0 and c.get('match_confidence')=='high']
    eligible=[c for c in strong if c.get('calibration_eligible') and c.get('financial_verified') and c.get('financials_usable_for_pricing')]
    return {
        'comparables': comps,
        'strong_count': len(strong),
        'eligible_count': len(eligible),
        # Current matched finance rows are mostly project totals, not normalized item unit costs.
        # Therefore V2 does not bend the estimate amount to fit historic contract totals.
        'price_adjustment_applied': False,
        'note': '과거 현장 데이터는 현장 특성의 유사성 참고에만 사용합니다. 매출·지출·손익은 현장 동일성과 정산범위가 원본으로 검증된 경우에만 가격 보정 대상이 되며, 현재 후보 매칭 재무값은 가격 계산에 사용하지 않습니다.'
    }
