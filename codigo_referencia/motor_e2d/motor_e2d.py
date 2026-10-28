#!/usr/bin/env python3
"""
motor_e2d.py - motor oficial da E2D (copia do driver de 2026), usado pelo painel ao vivo.
Padrao do teste: margem de 45 min antes de ENTRADA e 25 min antes de SAIDA/MUDANCA.
Especiais fixos (mesmos navios da E12) via ESP_FONTE.
(texto original abaixo)
gerar_v6_corrigido.py - EP 2M 2025 com engine_e12 integrada

ESTRATEGIA:
1. Roda engine_e12 standalone -> atribuicoes fixas dos especiais (SI/JA/CH)
2. Roda o algoritmo E2D (ciclo A->B, FIFO pós-B) para os regulares
3. Forca atribuicao dos especiais via patch em ep_sim_v3

Uso:
  python gerar_v6_corrigido.py

Saidas:
  E2D_2025_v6.xlsx
  esp_atribuicoes.pkl
"""
import sys, os, pickle, time
from pathlib import Path
from collections import defaultdict, Counter, OrderedDict
from datetime import datetime, timedelta

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))  # HERE tem prioridade: modulos locais sobrescrevem os da pasta pai

import xlsxwriter
import pandas as pd
import openpyxl

import ep_algoritmo
# E2D nao tem pontuacao: cada manobra conta 1 e o ciclo fecha na 2a (A->B).
for _k in ep_algoritmo.PTS_TABLE:
    ep_algoritmo.PTS_TABLE[_k] = 1.0
ep_algoritmo.PTS_DEFAULT = 1.0

import ep_sim_v3_corrigido as sim
sim.pts_man_fn  = lambda fr, to, T_mud, is_par=False: 1.0

# ── MARGEM b45: 45 min quando a próxima manobra sai de FB (entrada), 15 min nas demais ──
import math as _math
from datetime import timedelta as _td
from ep_algoritmo import gL as _gL, gT as _gT, r15 as _r15
MARGEM_ENTRADA = int(os.environ.get('MARGEM_ENTRADA', '45'))
MARGEM_OUTRAS  = int(os.environ.get('MARGEM_OUTRAS', '25'))
_BTP_OV = __import__('pickle').load(open(os.environ['BTP_OV'],'rb')) if os.environ.get('BTP_OV') else {}
_TPLUS={(x.split(':')[0]):(int(x.split(':')[1]) if ':' in x else int(os.environ.get('TPLUS_MIN','15'))) for x in filter(None,os.environ.get('TPLUS','').split(';'))}
def _avail_b45(last, next_fr, T_min, T_mud):
    if last is None:
        return None
    m = MARGEM_ENTRADA if str(next_fr).strip() == 'FB' else MARGEM_OUTRAS
    _T = _gT(last['fr'], last['to'], T_min, T_mud)
    _k = (last['start'].strftime('%Y-%m-%d %H:%M'), str(last['fr']).strip(), str(last['to']).strip())
    if _BTP_OV and _k in _BTP_OV: _T = _BTP_OV[_k]
    _fr=str(last['fr']).strip(); _to=str(last['to']).strip(); _b=_to if _fr=='FB' else (_fr if _to=='FB' else None)
    if _b and _b in _TPLUS and not (os.environ.get('TPLUS_SO_SM')=='1' and str(next_fr).strip()=='FB'): _T += _TPLUS[_b]
    d_calc = _r15(last['start'] + _td(minutes=_T + m + _gL(last['to'], next_fr)))
    # Disponibilidade só pelo início da pauta + T + margem + lancha. O término real é apenas informativo.
    return d_calc
sim.avail_time_fn = _avail_b45

from ep_sim_v3_corrigido import norm, simular_turno
from nova_escalacao import nova_escalacao
from carregar_pauta import carregar_pauta
from ep_algoritmo import carregar_dados

ESPECIAIS = set(filter(None, __import__('os').environ.get('ESP_SET','JA,SI,CH').split(',')))


def gerar_atribuicoes_especiais(pauta_df):
    """Roda engine_e12 sobre a pauta -> {idx_pauta: especial}"""
    print('Etapa 1: rodando engine_e12...', end=' ', flush=True)
    from engine_e12 import EngineE12
    
    esc_path = None
    for p in [HERE/'Escalacao_365_dias.xlsx', HERE.parent/'Escalacao_365_dias.xlsx']:
        if p.exists():
            esc_path = p; break
    if not esc_path:
        for p in HERE.rglob('Escalacao_365_dias.xlsx'):
            esc_path = p; break
    if not esc_path:
        for p in HERE.parent.rglob('Escalacao_365_dias.xlsx'):
            esc_path = p; break
    if not esc_path:
        raise FileNotFoundError("Escalacao_365_dias.xlsx nao encontrado")
    
    wb = openpyxl.load_workbook(esc_path, data_only=True)
    ws = wb.active
    dados = []
    for r in range(3, ws.max_row+1):
        dv = ws.cell(r,1).value
        if not dv: continue
        if isinstance(dv, str): d = datetime.strptime(dv.strip(),'%d/%m/%Y').date()
        else: d = dv.date() if hasattr(dv,'date') else dv
        d12 = ws.cell(r,2).value
        d12 = str(d12).strip() if d12 else None
        pra = [str(ws.cell(r,3+i).value).strip() if ws.cell(r,3+i).value else None for i in range(12)]
        g = ws.cell(r,15).value
        g = str(g).strip() if g else None
        inic = ws.cell(r,16).value
        inic = str(inic).strip() if inic else None
        dados.append({'data':d, 'd1d2':d12, 'praticos':pra, 'grupo':g, 'iniciador':inic})
    
    gs = ['G1','G2','G3','G4','G5','G6']
    for i, dd in enumerate(dados):
        if dd['grupo']: continue
        if dd['d1d2'] == 'D1':
            ant = None
            for j in range(i-1, -1, -1):
                if dados[j]['d1d2'] == 'D1' and dados[j]['grupo']:
                    ant = j; break
            if ant is not None:
                n = sum(1 for k in range(ant+1, i+1) if dados[k]['d1d2'] == 'D1')
                dd['grupo'] = gs[(gs.index(dados[ant]['grupo']) + n) % 6]
        elif dd['d1d2'] == 'D2' and i > 0 and dados[i-1]['grupo']:
            dd['grupo'] = dados[i-1]['grupo']
    
    esc365 = {dd['data']: {'grupo':dd['grupo'], 'praticos':dd['praticos']} for dd in dados}
    
    p2 = pauta_df.copy()
    if 'Data' in p2.columns and not pd.api.types.is_datetime64_any_dtype(p2['Data']):
        p2['Data'] = pd.to_datetime(p2['Data'], format='%d/%m/%Y', errors='coerce').dt.date
    
    key = (p2['Data'].astype(str)+'|'+p2['Hora'].astype(str)+'|'+p2['Vessel'].astype(str))
    grupos_idx = defaultdict(list)
    for i, k in enumerate(key):
        grupos_idx[k].append(i)
    par_info = {}
    for k, idxs in grupos_idx.items():
        if len(idxs) == 1: par_info[idxs[0]] = None
        elif len(idxs) == 2:
            par_info[idxs[0]] = idxs[1]
            par_info[idxs[1]] = idxs[0]
    
    # Calcular ponteiros iniciais a partir da coluna 16 (iniciador) da Escalacao_365_dias
    ponteiros = {}
    for dd in dados:
        g = dd.get('grupo')
        inic = dd.get('iniciador')
        if g and inic and dd.get('d1d2')=='D1' and g not in ponteiros:
            pra = dd['praticos']
            if inic in pra:
                ponteiros[g] = pra.index(inic)
    # Fallback para grupos sem iniciador definido
    for g_fb, p_fb in {'G1':6,'G2':7,'G3':4,'G4':8,'G5':6,'G6':4}.items():
        if g_fb not in ponteiros:
            ponteiros[g_fb] = p_fb
    engine = EngineE12(ponteiros)
    
    esp_atrib = {}
    processado = set()
    for i in range(len(p2)):
        if i in processado: continue
        m = p2.iloc[i]
        h_str = str(m['Hora'])
        try:
            h, mn = int(h_str[:2]), int(h_str[3:5])
        except:
            continue
        data = m['Data'] - timedelta(days=1) if (h, mn) < (7, 30) else m['Data']
        if data not in esc365: continue
        info = dict(esc365[data]); info['data'] = data
        if info['grupo'] is None: continue
        if any(p is None for p in info['praticos']): continue
        parc = par_info.get(i)
        tipo = 'par' if parc is not None else 'solo'
        
        decisao = engine.decidir_manobra({'tipo':tipo, 'idx':i}, info)
        cat, prats = decisao
        
        if cat == 'especial':
            esp_atrib[i] = prats[0]
            processado.add(i)
        elif cat == 'regular':
            processado.add(i)
        elif cat == 'especial_par':
            esp_atrib[i] = prats[0]
            esp_atrib[parc] = prats[1]
            processado.add(i); processado.add(parc)
        elif cat == 'regular_par':
            processado.add(i); processado.add(parc)
    
    cnt = Counter(esp_atrib.values())
    print(f'OK ({len(esp_atrib)} atribuicoes: SI={cnt.get("SI",0)} JA={cnt.get("JA",0)} CH={cnt.get("CH",0)})')
    return esp_atrib


print('=== gerar_v6_corrigido ===')
t0 = time.time()
_, T_min, T_mud = carregar_dados()
man_df, pares2 = carregar_pauta()
print(f'Pauta: {len(man_df)} manobras')

_esp_fonte = os.environ.get('ESP_FONTE')
if _esp_fonte:
    # Especiais FIXOS lidos de uma planilha de referência (ex.: E12 v5), linha a linha (Seq = idx+1)
    _wb = openpyxl.load_workbook(_esp_fonte, read_only=True)
    _ws = _wb.worksheets[0]
    esp_atrib = {}
    _hdr = None
    for _r in _ws.iter_rows(values_only=True):
        if _hdr is None:
            if _r and 'Seq' in _r: _hdr = list(_r)
            continue
        if isinstance(_r[0], int):
            _p = str(_r[_hdr.index('Pratico')]).strip()
            if _p in ESPECIAIS:
                _i = _r[0] - 1
                _m = man_df.iloc[_i]
                assert str(_m['Vessel']).strip() == str(_r[_hdr.index('Navio')]).strip(), _r
                esp_atrib[_i] = _p
    print(f'Especiais fixos de {_esp_fonte}: {len(esp_atrib)} ({Counter(esp_atrib.values())})')
else:
    esp_atrib = gerar_atribuicoes_especiais(man_df)
with open(HERE/'esp_atribuicoes.pkl', 'wb') as f:
    pickle.dump(esp_atrib, f)

# Converter idx -> chave (Data, Hora, Vessel) para o patch no ep_sim
# Para pares (mesma chave 2x), agrega lista de especiais
esp_atrib_key = defaultdict(list)
for idx, especial in esp_atrib.items():
    m = man_df.iloc[idx]
    data_str = m['Data'] if isinstance(m['Data'], str) else m['Data'].strftime('%d/%m/%Y') if hasattr(m['Data'], 'strftime') else str(m['Data'])
    key = (data_str, str(m['Hora']), str(m['Vessel']).strip())
    esp_atrib_key[key].append(especial)

# Patch no modulo sim
sim._ESP_ATRIB_FORCADAS_KEY = dict(esp_atrib_key)
if os.environ.get('SEM_FORCA') == '1':   # especiais pelo contador interno do motor (como a b45 OFICIAL)
    sim._ESP_ATRIB_FORCADAS_KEY = {}
print(f'Atribuicoes forcadas (chave): {len(esp_atrib_key)} chaves')
# Escalações congeladas (regulares escalados a partir de 1 h antes): {(Data, Hora, Navio): [práticos]}
_fzp = os.environ.get('FROZEN')
sim._FROZEN_KEY = pickle.load(open(_fzp, 'rb')) if _fzp and os.path.exists(_fzp) else {}
print(f'Escalacoes congeladas: {len(sim._FROZEN_KEY)} chaves')


# Carregar turnos
tpkl = Path(os.environ['TURNOS']) if os.environ.get('TURNOS') else None
for p in ([] if tpkl else [HERE/'turnos_v4.pkl', HERE/'2025'/'turnos_v5.pkl', HERE.parent/'turnos_v4.pkl', HERE.parent/'2025'/'turnos_v5.pkl']):
    if p.exists():
        tpkl = p; break
if not tpkl:
    for p in HERE.rglob('turnos_v*.pkl'):
        tpkl = p; break
if not tpkl:
    for p in HERE.parent.rglob('turnos_v*.pkl'):
        tpkl = p; break
if not tpkl:
    raise FileNotFoundError("turnos_*.pkl nao encontrado")

print(f'Turnos: {tpkl}')
with open(tpkl, 'rb') as f:
    turnos = pickle.load(f)
turnos = sorted(turnos, key=lambda x: x['dt_ini'])
for i, t in enumerate(turnos):
    t['dt_fim'] = turnos[i+1]['dt_ini'] if i+1 < len(turnos) else t['dt_fim']

print(f'{len(turnos)} turnos | {time.time()-t0:.1f}s')

pts_g = defaultdict(float)
last_g = {}
tctr = [0]
real_cyc = defaultdict(float)

all_hist = []
seq = [0]
ultima_esc = ''
prev_dia2 = []
ns_carry = None
mc_prev = 0
pend_b_carry = set()

print('Etapa 2: simulando EP...', end=' ', flush=True)

# As atribuicoes forcadas ja foram patcheadas via sim._ESP_ATRIB_FORCADAS_KEY acima

for ti, turno in enumerate(turnos):
    Y_d1 = [norm(p) for p in turno['dia1'] if p and p != '?']
    
    if ti == 0:
        fila_ini = [norm(p) for p in turno['Y'] if p]
    else:
        if ultima_esc and set(prev_dia2) != set(Y_d1):
            nova_str = nova_escalacao(ultima_esc, prev_dia2, Y_d1)
            fila_ini = [p.split('(')[0] for p in nova_str.split(' > ') if '(' in p]
            if not fila_ini:
                fila_ini = Y_d1
        else:
            fila_ini = Y_d1
        real_cyc.clear()

        # ── REGRA PENDENTE B ESTENDIDA (entre turnos) ──────────────
        # Entrantes que voltam da folga com B pendente (em pend_b_carry)
        # são promovidos para antes dos entrantes regulares na fila_ini.
        if pend_b_carry and fila_ini:
            _pend_ret = [p for p in fila_ini
                         if p not in ESPECIAIS
                         and norm(p) in {norm(q) for q in pend_b_carry}
                         and norm(p) not in {norm(q) for q in prev_dia2}]
            if _pend_ret:
                # Posição de inserção: início da fila (P1) por ora,
                # depois os pendentes do dia ant serão promovidos pelo simulador
                _fila = [p for p in fila_ini if p not in _pend_ret]
                _pos = 0
                for _i, _q in enumerate(_fila):
                    if _q not in ESPECIAIS:
                        _pos = _i
                        break
                for _p in reversed(_pend_ret):
                    _fila.insert(_pos, _p)
                fila_ini = _fila
    
    res = simular_turno(
        turno, fila_ini, man_df, T_min, T_mud, pares2,
        pts_g, last_g, tctr,
        next_slot_carry=ns_carry,
        man_count_prev=mc_prev,
        real_cycle_ref=real_cyc,
        pend_b_carry=pend_b_carry,
    )
    hist, ultima_esc, ns_carry, mc_prev, pend_b_carry = res
    

    
    prev_dia2 = [norm(p) for p in turno['dia2'] if p and p != '?']
    
    for h in hist:
        seq[0] += 1
        h['seq'] = seq[0]
    
    all_hist.extend(hist)

print(f'{time.time()-t0:.0f}s | {seq[0]} manobras')

cnt = Counter(h['pratico'] for h in all_hist if h['pratico'] in ESPECIAIS)
print(f'Especiais: JA={cnt.get("JA",0)} SI={cnt.get("SI",0)} CH={cnt.get("CH",0)}')

def pdt(h):
    try: return datetime.strptime(f"{h['data']} {h['hora']}", '%d/%m/%Y %H:%M')
    except: return None

# Gerar planilha
print('Etapa 3: gerando planilha...', end=' ', flush=True)
V = 6
out = HERE / os.environ.get('E2D_OUT', 'E2D_2025_b45_gerado.xlsx')

def logical_day(h):
    try:
        dt = datetime.strptime(f"{h['data']} {h['hora']}", '%d/%m/%Y %H:%M')
        return (dt - timedelta(days=1)).date() if dt.hour < 7 or (dt.hour == 7 and dt.minute < 30) else dt.date()
    except: return None

man_por_ld = Counter(logical_day(h) for h in all_hist if logical_day(h))

final_hist = []; prev_ld = None
for h in all_hist:
    ld = logical_day(h)
    if ld and prev_ld and ld != prev_ld:
        final_hist.append({'_day_div': True, 'data': h['data'], 'n_man': man_por_ld.get(prev_ld, 0)})
    prev_ld = ld or prev_ld
    final_hist.append(h)

wb = xlsxwriter.Workbook(str(out), {'constant_memory': False})
ws = wb.add_worksheet('E2D 2025')
ws.freeze_panes(3, 0); ws.set_zoom(80)

def fmt(bg='#FFFFFF', fc='#1B2631', bold=False):
    return wb.add_format({'bg_color':bg, 'font_color':fc, 'bold':bold, 'font_name':'Arial',
                          'font_size':9, 'border':1, 'align':'center', 'valign':'vcenter'})

fh = fmt('#1B4F72', '#FFFFFF', True); fn = fmt(); fa = fmt('#EBF5FB')
fverde = fmt('#D5F5E3', '#1E8449', True); fverm = fmt('#FADBD8', '#922B21', True)
fesp = fmt('#D5E8D4', bold=True); fdiv = wb.add_format({'bg_color':'#2C3E50'})

cols = ['Seq','Data','Hora','Termino','Pratico','Navio','De','Para','Status','Escalacao']
for ci, lbl in enumerate(cols):
    ws.write(0, ci, lbl, fh)
ws.set_row(0, 20)

ws.set_column(0,0,5); ws.set_column(1,1,10); ws.set_column(2,2,6); ws.set_column(3,3,6)
ws.set_column(4,4,5); ws.set_column(5,5,26); ws.set_column(6,6,7); ws.set_column(7,7,7)
ws.set_column(8,8,5)
ws.set_column(9,9,95)

ri = 1
for h in final_hist:
    if h.get('_day_div'):
        ws.set_row(ri, 14)
        n = h.get('n_man', 0)
        fdt = wb.add_format({'bg_color':'#2C3E50', 'font_color':'#F1C40F', 'bold':True,
                              'font_name':'Arial', 'font_size':8, 'align':'center', 'valign':'vcenter'})
        ws.write(ri, 0, f'{n} Manobras', fdt)
        for ci in range(1, 10): ws.write(ri, ci, '', fdiv)
        ri += 1; continue
    p = h['pratico']
    is_v = h.get('laranja') == 'verde'
    is_esp = p in ESPECIAIS
    is_A = (not is_v) and (round(h.get('pts_apos', 0), 1) == 1.0) and (p not in ESPECIAIS)
    if is_esp:    f = fesp
    elif is_v:    f = fverde
    elif is_A:    f = fverm
    elif ri % 2 == 0: f = fa
    else:         f = fn
    
    ws.set_row(ri, 20)
    ws.write(ri, 0, h['seq'], f)
    ws.write(ri, 1, h['data'], f)
    ws.write(ri, 2, h['hora'], f)
    ws.write(ri, 3, str(h.get('termino','')), f)
    ws.write(ri, 4, p, f)
    ws.write(ri, 5, str(h.get('vessel','')), f)
    ws.write(ri, 6, str(h.get('de','')), f)
    ws.write(ri, 7, str(h.get('para','')), f)
    ws.write(ri, 8, 'B' if is_v else ('A' if is_A else ''), f)
    ws.write_string(ri, 9, str(h.get('escalacao_disp', '')), f)
    ri += 1

wb.close()
print(f'{out.stat().st_size//1024}KB | {time.time()-t0:.0f}s')
print(f'OK -> {out}')

print(f'Fallback (ninguém disponível): {len(sim._FALLBACK_LOG)} manobras')
import pickle as _pk; _pk.dump(sim._FALLBACK_LOG, open(os.environ.get("FB_OUT","fb.pkl"),"wb"))
