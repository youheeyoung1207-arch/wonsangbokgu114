from __future__ import annotations
import math
from historical import evidence_summary

PYEONG_M2 = 3.305785

def _ceil(x):
    return int(math.ceil(max(0, x)))

def _scope_is_demo(obj: dict) -> bool:
    status=obj.get('scope_status')
    # backward compatibility: old analyzer used flooring.remove
    if status is None and 'remove' in obj:
        return bool(obj.get('remove'))
    return status in ('demolish','partial')

def _resolved_area(obj: dict, total_area: float):
    if obj.get('area_pyeong') is not None:
        try: return float(obj.get('area_pyeong'))
        except (TypeError,ValueError): return None
    if obj.get('coverage')=='full' and total_area:
        return float(total_area)
    return None

def estimate(analysis: dict, context: dict, rates: dict):
    items=[]
    low=high=0
    confidence=float(analysis.get('overall_confidence') or 0.0)
    area=float(context.get('area_pyeong') or 0)

    # 1) Flooring. Never assume partial/unknown floor means whole site area.
    floor=analysis.get('flooring') or {}
    floor_area=_resolved_area(floor, area)
    ftype=floor.get('type')
    if _scope_is_demo(floor):
        if not floor_area:
            items.append({'name':'바닥 철거','qty':'면적 확인 필요','low':0,'high':0,'note':'부분/전체 범위가 확인되지 않아 가격에 넣지 않음'})
            confidence*=0.88
        else:
            fr=rates['flooring_per_pyeong']
            unit_low=unit_high=None; label=None; note=None
            if ftype=='deco_deluxe':
                unit_low,unit_high,label=fr['deco_deluxe_1p_low'],fr['deco_deluxe_1p_high'],'데코/디럭스타일 1P 철거'; note='폐기물 포함 기준'
            elif ftype=='carpet_tile':
                unit_low=unit_high=fr['carpet_tile']; label='카펫타일 철거'; note='샌딩·폐기물 포함 기준'
            elif ftype=='wood_floor':
                unit_low=unit_high=fr['wood_floor']; label='마루 철거'; note='샌딩·폐기물 포함 기준'
            elif ftype=='epoxy':
                unit_low,unit_high,label=fr['epoxy_1mm'],fr['epoxy_3mm'],'에폭시 철거(두께 미확정)'; note='샌딩·폐기물 포함, 두께 확인 필요'
            elif ftype=='polished_tile':
                unit_low=unit_high=fr['polished_tile']; label='폴리싱타일 철거'; note='폐기물 포함 기준'
            if unit_low:
                vlow,vhigh=int(floor_area*unit_low),int(floor_area*unit_high)
                low+=vlow; high+=vhigh
                items.append({'name':label,'qty':f'{floor_area:.1f}평','low':vlow,'high':vhigh,'note':note})
            elif ftype=='porcelain_tile':
                pr=rates['demolition_provisional']; vlow=int(floor_area*pr['porcelain_tile_per_pyeong_low']); vhigh=int(floor_area*pr['porcelain_tile_per_pyeong_high'])
                low+=vlow; high+=vhigh
                items.append({'name':'자기타일 철거+샌딩','qty':f'{floor_area:.1f}평','low':vlow,'high':vhigh,'note':'외부조사 가견적단가 · 실적 검증 전'})
                confidence*=0.82
            elif ftype=='vinyl_sheet':
                pr=rates['demolition_provisional']; vlow=int(floor_area*pr['vinyl_sheet_per_pyeong_low']); vhigh=int(floor_area*pr['vinyl_sheet_per_pyeong_high'])
                low+=vlow; high+=vhigh
                items.append({'name':'장판/비닐시트 철거','qty':f'{floor_area:.1f}평','low':vlow,'high':vhigh,'note':'외부조사 가견적단가 · 실적 검증 전'})
            elif ftype not in (None,'unknown'):
                items.append({'name':'바닥 철거','qty':f'{floor_area:.1f}평','low':0,'high':0,'note':f'{ftype} 단가 미확정'})
                confidence*=0.9

        # Hidden floor build-up is a risk flag, not an invented percentage surcharge.
        if floor.get('hidden_layers') or floor.get('mortar_or_concrete') or floor.get('raised_floor'):
            items.append({'name':'바닥 하부층/몰탈·콘크리트 확인','qty':'추가 구조 감지','low':0,'high':0,'note':'과거 현장에서 숨은 데코타일·몰탈로 물량이 크게 늘어난 사례가 있어 별도 확인'})
            confidence*=0.9

    # 2) Ceiling.
    ceiling=analysis.get('ceiling') or {}
    ctype=ceiling.get('type'); c_area=_resolved_area(ceiling,area)
    if _scope_is_demo(ceiling):
        if not c_area:
            items.append({'name':'천장 철거','qty':'면적 확인 필요','low':0,'high':0,'note':'철거 범위가 부분/불명확하여 전체 평수를 자동 적용하지 않음'})
            confidence*=0.9
        elif ctype=='tex':
            people_days=max(1.0,4.0*(c_area/100.0))
            wage_mid=(rates['labor']['korean_skilled_day']+rates['labor']['korean_helper_day'])/2
            labor=int(people_days*(wage_mid+rates['labor']['meal_drink_per_person_day']))
            loads=_ceil(c_area/rates['waste']['ceiling_tex_pyeong_per_mixed_load'])
            waste=loads*rates['waste']['mixed_2_5t_load']
            vlow,vhigh=int(labor*0.85)+waste,int(labor*1.15)+waste
            low+=vlow; high+=vhigh
            items.append({'name':'천장 텍스 철거','qty':f'{c_area:.1f}평','low':vlow,'high':vhigh,'note':f'혼합폐기물 약 {loads}대, 경량철골은 고철로 분리'})
        elif ctype=='gypsum':
            loads=_ceil(c_area/rates['waste']['ceiling_gypsum_pyeong_per_load']); waste=loads*rates['waste']['mixed_2_5t_load']; pr=rates['demolition_provisional']
            labor_low=int(c_area*pr['gypsum_ceiling_labor_per_pyeong_low']); labor_high=int(c_area*pr['gypsum_ceiling_labor_per_pyeong_high'])
            vlow,vhigh=waste+labor_low,waste+labor_high; low+=vlow; high+=vhigh
            items.append({'name':'천장 석고보드 철거','qty':f'{c_area:.1f}평','low':vlow,'high':vhigh,'note':f'혼합폐기물 약 {loads}대 + 외부조사 가견적 인건비'})
            confidence*=0.88
        elif ctype=='wood_frame':
            pr=rates['demolition_provisional']; vlow=int(c_area*pr['wood_frame_ceiling_per_pyeong_low']); vhigh=int(c_area*pr['wood_frame_ceiling_per_pyeong_high']); low+=vlow; high+=vhigh
            items.append({'name':'목상 천장 철거','qty':f'{c_area:.1f}평','low':vlow,'high':vhigh,'note':'외부조사 가견적단가 · 폐기물 물량은 추가 확인'})
            confidence*=0.84

    # 3) Gypsum partition geometry.
    wall_man_days=0.0; wall_board_m2=0.0
    for wall in analysis.get('walls') or []:
        if not _scope_is_demo(wall):
            continue
        if wall.get('type')=='gypsum_partition' and wall.get('length_m') and wall.get('height_m'):
            sides=wall.get('sides') or rates['gypsum_defaults']['partition_default_sides']
            layers=wall.get('layers_per_side') or rates['gypsum_defaults']['partition_default_layers_per_side']
            length=float(wall['length_m']); height=float(wall['height_m'])
            wall_board_m2 += length*height*sides*layers
            physical_wall_pyeong=(length*height)/PYEONG_M2
            this_md=8.0*(physical_wall_pyeong/100.0)
            if height>3.2: this_md*=1.15
            wall_man_days+=this_md
        elif wall.get('type') in ('alc_block','masonry','steel_plate','soundproof_multilayer'):
            items.append({'name':f"특수 벽체 철거 ({wall.get('type')})",'qty':'실측 필요','low':0,'high':0,'note':'일반 석고칸막이 생산성을 적용하지 않고 별도 확인'})
            confidence*=0.88
    if wall_board_m2>0:
        board_area=(rates['gypsum_defaults']['board_width_mm']/1000)*(rates['gypsum_defaults']['board_height_mm']/1000)
        boards=_ceil(wall_board_m2/board_area)
        wage_mid=(rates['labor']['korean_skilled_day']+rates['labor']['korean_helper_day'])/2
        labor=int(wall_man_days*(wage_mid+rates['labor']['meal_drink_per_person_day']))
        vlow,vhigh=int(labor*0.85),int(labor*1.2)
        low+=vlow; high+=vhigh
        items.append({'name':'석고 경량칸막이 철거','qty':f'석고 환산 {boards}장(900×1800)','low':vlow,'high':vhigh,'note':f'기본 일반석고 9.5T·양면2P 가정, 작업량 환산 {wall_man_days:.1f}명×1일 상당'})

    # 4) Fixtures/electrical. Movable-owner items are not automatically demolition waste.
    fixtures=analysis.get('fixtures') or {}
    if fixtures.get('fixed_vs_movable')!='mostly_movable' and fixtures.get('volume') in ('medium','high'):
        man_days=1.5 if fixtures['volume']=='medium' else 3.0
        wage=rates['labor']['korean_helper_day']+rates['labor']['meal_drink_per_person_day']
        cost=int(man_days*wage); vlow,vhigh=int(cost*0.8),int(cost*1.3)
        low+=vlow; high+=vhigh
        items.append({'name':'고정 집기/선반/카운터 철거','qty':fixtures['volume'],'low':vlow,'high':vhigh,'note':'목재 폐기물 차량수는 체적 환산계수 확정 후 분리'})
    elif fixtures.get('fixed_vs_movable')=='mixed':
        confidence*=0.94

    elec=analysis.get('electrical_cleanup') or {}
    if elec.get('level') in ('medium','high'):
        man_days=0.75 if elec['level']=='medium' else 1.5
        wage=rates['labor']['korean_skilled_day']+rates['labor']['meal_drink_per_person_day']
        cost=int(man_days*wage); vlow,vhigh=int(cost*0.85),int(cost*1.2)
        low+=vlow; high+=vhigh
        items.append({'name':'조명/전기 선정리','qty':elec['level'],'low':vlow,'high':vhigh,'note':'분전반·통신·숨은 배선은 추가 확인'})

    # 5) Equipment based on explicit evidence.
    signage=analysis.get('signage') or {}
    if signage.get('present') and signage.get('scope_status') in ('demolish','partial',None):
        exterior=analysis.get('exterior_metal') or {}
        if exterior.get('present') and exterior.get('scope')=='large':
            days=2 if (signage.get('length_m') or 0)>12 else 1
            sky=days*rates['equipment']['sky_full_day']; label=f'스카이 {days}일'
        else:
            sky=rates['equipment']['sky_1h']; label='스카이 1시간'
        low+=sky; high+=sky
        items.append({'name':'간판/고소작업 장비','qty':label,'low':sky,'high':sky,'note':'일반 간판은 1층도 안전상 스카이 기본 검토'})

    eq=analysis.get('equipment') or {}
    floor_heavy=bool(floor.get('mortar_or_concrete') or floor.get('raised_floor'))
    if eq.get('mini_likely') and eq.get('mini_accessible') is not False and floor_heavy:
        count=max(1,int(eq.get('mini_count') or 1))
        # Duration is not inferred from floor area alone. Use half-day as explicit provisional bucket only if analysis cannot determine duration.
        mini=count*rates['equipment']['mini_excavator_half_day']
        low+=mini; high+=mini
        items.append({'name':'미니장비','qty':f'{count}대 · 반일 임시기준','low':mini,'high':mini,'note':'실제 사용시간/대수 확인 시 재계산; 평수만으로 하루 수를 결정하지 않음'})
        confidence*=0.96
    elif eq.get('mini_likely') and eq.get('mini_accessible') is False:
        items.append({'name':'장비 반입 불가','qty':'인력철거 재산정 필요','low':0,'high':0,'note':'과거 고시원처럼 미니장비 반입 불가 시 생산성이 크게 달라질 수 있음'})
        confidence*=0.82

    log=analysis.get('logistics') or {}
    if log.get('haul_method')=='ladder' or eq.get('ladder_for_haul_likely'):
        ladder=rates['equipment']['ladder_half_day']
        low+=ladder; high+=ladder
        items.append({'name':'사다리차 폐기물 반출','qty':'반일 임시기준','low':ladder,'high':ladder,'note':'실제 반출량/창 위치/사용시간 확인 시 1시간·반일·1일로 재선택'})
    elif log.get('difficulty')=='hard':
        items.append({'name':'반출/접근 조건','qty':'어려움','low':0,'high':0,'note':'임의 15% 할증을 쓰지 않고 운반거리·엘리베이터·사다리차·보양을 개별 산정'})
        confidence*=0.9

    ops=analysis.get('operational_constraints') or {}
    if any([ops.get('work_window_restricted'),ops.get('haul_window_restricted'),ops.get('equipment_window_restricted'),ops.get('night_work')]):
        items.append({'name':'작업시간/민원 조건','qty':'제한 있음','low':0,'high':0,'note':'고정 야간할증을 임의 적용하지 않고 실제 작업가능시간을 확인해 생산성으로 반영'})
        confidence*=0.9

    if analysis.get('special_review'):
        items.append({'name':'특수현장 검토','qty':'수동 확인 필요','low':0,'high':0,'note':'공장설비·고층고·비계·오염·구조성 철거는 표준 내부철거 자동견적에서 분리'})
        confidence*=0.8

    # 6) Restoration scope selected by the customer. These items MUST affect price.
    construction_type=context.get('construction_type') or 'demolition'
    scopes=set(context.get('restoration_scopes') or [])
    if construction_type in ('demolition_restoration','restoration') and scopes:
        rr=rates.get('restoration', {})
        def add_rest(name, qty, vlow, vhigh=None, note=''):
            nonlocal low, high
            vhigh=vlow if vhigh is None else vhigh
            low+=int(vlow); high+=int(vhigh)
            items.append({'name':name,'qty':qty,'low':int(vlow),'high':int(vhigh),'note':note})

        if 'ceiling' in scopes:
            ctype=(analysis.get('ceiling') or {}).get('type')
            unit=rr['ceiling']['mytone_install_per_pyeong'] if ctype=='mytone' else rr['ceiling']['tex_install_per_pyeong'] if ctype=='tex' else rr['ceiling']['unknown_ceiling_provisional_per_pyeong']
            note='사용자 확정 단가' if ctype in ('tex','mytone') else '천장 종류 미확정 · 석고텍스 단가를 임시 가견적으로 적용'
            add_rest('천장 원상복구',f'{area:.1f}평',area*unit,note=note)
            if ctype not in ('tex','mytone'): confidence*=0.9
        if 'floor' in scopes:
            unit=rr['floor']['deluxe_tile_install_per_pyeong']; add_rest('바닥 원상복구',f'{area:.1f}평',area*unit,note='디럭스타일 기준 외부조사 가견적 · 자재 확인 필요'); confidence*=0.92
        if 'wall_partition' in scopes:
            unit=rr['wall_partition']['allowance_per_pyeong']; add_rest('벽체·칸막이 복구',f'{area:.1f}평 기준',area*unit,note='범위 미확정 외부조사 가견적'); confidence*=0.9
        if 'paint' in scopes:
            x=rr['paint']; add_rest('페인트·도장',f'{area:.1f}평 기준',area*x['per_floor_pyeong_low'],area*x['per_floor_pyeong_high'],note='벽·기둥 일반 수성 2회 외부조사 가견적'); confidence*=0.92
        if 'electrical' in scopes:
            x=rr['electrical']; count=max(1,round(area*x['fixture_count_ratio'])); add_rest('전기·조명',f'LED 약 {count}개',count*x['led_slim_each'],note='LED 자재 기준 · 배선/회로 변경 인건비는 현장 확인 후 추가'); confidence*=0.9
        if 'fire' in scopes:
            x=rr['fire']; count=max(1,round(area*x['head_count_ratio'])); add_rest('소방',f'스프링클러 약 {count}개',count*x['sprinkler_fix_each'],note='텍스 타공·헤드고정 사용자 확정 단가')
        if 'hvac' in scopes:
            x=rr['hvac']; add_rest('냉난방·에어컨','1대 임시',x['unit_relocation_each'],note='수량/배관거리 미확정 외부조사 가견적'); confidence*=0.86
        if 'duct' in scopes:
            x=rr['duct']; add_rest('환기·덕트',f"{x['default_count']}개소 임시",x['fix_each']*x['default_count'],note='규격/수량 미확정 외부조사 가견적'); confidence*=0.86
        if 'plumbing' in scopes:
            x=rr['plumbing']; add_rest('설비',f'{area:.1f}평 기준',area*x['allowance_per_pyeong'],note='급배수 범위 미확정 외부조사 가견적'); confidence*=0.84
        if 'door_glass_sash' in scopes:
            x=rr['door_glass_sash']; add_rest('출입문·유리·샷시','1개소 임시',x['allowance_each'],note='규격/재질 미확정 외부조사 가견적'); confidence*=0.84
        if 'sign_exterior' in scopes:
            x=rr['sign_exterior']; add_rest('간판·외부마감','범위 확인 전',x['allowance'],note='외부조사 가견적'); confidence*=0.84
        if 'waxing' in scopes:
            x=rr['waxing']; add_rest('바닥 왁싱',f'{area:.1f}평',area*x['per_pyeong'],note='외부조사 가견적')
        if 'cleaning' in scopes:
            x=rr['cleaning']; add_rest('준공청소',f'{area:.1f}평',area*x['per_pyeong'],note='외부조사 가견적')
        if 'other' in scopes:
            items.append({'name':'기타 원상복구','qty':'내용 확인 필요','low':0,'high':0,'note':'요구사항 확인 후 산정'})
            confidence*=0.9

    # 7) Historical actual-job evidence. Used as a guardrail, not price forcing.
    hist=evidence_summary(analysis,context)
    if hist['strong_count']>=2:
        confidence=min(0.95, confidence+0.03)

    if confidence<0.7:
        low=int(low*0.95); high=int(high*1.15)

    return {
        'total_low':max(0,int(low//10000*10000)),
        'total_high':max(0,int(math.ceil(high/10000)*10000)),
        'confidence':round(max(0.05,min(0.95,confidence)),2),
        'breakdown':items,
        'needs_more_video':analysis.get('needs_more_video') or [],
        'history':{
            'reference_count':len(hist['comparables']),
            'strong_count':hist['strong_count'],
            'eligible_count':hist['eligible_count'],
            'price_adjustment_applied':hist['price_adjustment_applied'],
            'note':hist['note']
        }
    }
