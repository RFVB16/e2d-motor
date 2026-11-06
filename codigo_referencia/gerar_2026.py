#!/usr/bin/env python3
"""
gerar_2026.py — painel ao vivo da E2D (substitui a versão antiga com pontos/créditos).

Padrão do teste:
  * margem de 45 min antes de ENTRADA e 25 min antes de SAÍDA/MUDANÇA (tabela de T igual);
  * especiais (JA/SI/CH) fazem exatamente os navios da E12: usa o prático REAL do
    SPPILOTS quando a manobra já tem prático; para as manobras ainda sem prático,
    continua a vez da E12 por simulação;
  * sem pontos nem créditos; restrição Z5 (máx. 1 Z5 por prático regular por dia operacional).

Entradas (mesma pasta deste arquivo):
  inputs/Pauta_de_Manobra_2026.xlsx  — montada pelo ep_atualizar.py (histórico + pauta do SPPILOTS)
  historico_2026.csv                 — histórico do SPPILOTS (com o prático real)
  pauta_rt.csv                       — pauta atual do SPPILOTS (favorito "EP Salvar Pauta")
  inputs/bigramas_2026.xlsx          — escala 2026 (aba RESUMO: dia, D1/D2, P1..P12)
Saída:
  ao_vivo/E2D_2026_v6.xlsx             — lida pelo ep_atualizar.py para montar a página
"""
import sys, os, pickle, subprocess, itertools, time, datetime as dt
from pathlib import Path
from collections import defaultdict
import pandas as pd
import openpyxl, xlsxwriter

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
DIR   = Path(__file__).resolve().parent
MOTOR = DIR / 'motor_e2d'
sys.path.insert(0, str(MOTOR))
ESP = {'JA', 'SI', 'CH'}
MARGEM_ENTRADA = int(os.environ.get('MARGEM_ENTRADA', '45'))
MARGEM_OUTRAS  = int(os.environ.get('MARGEM_OUTRAS', '25'))
PAUTA_IN = Path(os.environ.get('PAUTA_IN', DIR / 'inputs' / 'Pauta_de_Manobra_2026.xlsx'))
HIST     = Path(os.environ.get('HIST_IN', DIR / 'historico_2026.csv'))
RT       = Path(os.environ.get('RT_IN', DIR / 'pauta_rt.csv'))
ESCALA   = Path(os.environ.get('ESCALA_IN', DIR / 'inputs' / 'bigramas_2026.xlsx'))
SAIDA    = Path(os.environ.get('SAIDA', DIR / 'ao_vivo' / 'E2D_2026_v6.xlsx'))
t0 = time.time()
J = lambda x: 'JA' if str(x).strip().upper() in ('JÁ', 'JA') else str(x).strip().upper()


def dia_op(t):
    return (t - pd.Timedelta(hours=7, minutes=30)).date()


# ── 1. Pauta: histórico do SPPILOTS (já executado) + pauta atual (daqui para frente) ──
def _ler_csv(path):
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, encoding='utf-8-sig')
    d['DT'] = pd.to_datetime(d['datetime'], errors='coerce')
    d = d.dropna(subset=['DT']).copy()
    d['Vessel'] = d['Vessel'].astype(str).str.strip()
    d['Pratico'] = d['Pratico'].fillna('').astype(str) if 'Pratico' in d else ''
    return d
h = _ler_csv(HIST); rt = _ler_csv(RT)


# 06/11/2026 (Rodrigo): manobras no MESMO horário seguem a ordem da pauta ao vivo do SPPilots (a numeração
# põe a mais curta primeiro: quem está na frente da fila vai nela). O histórico não respeita essa ordem.
# Guardamos a ordem da pauta ao vivo enquanto o navio aparece nela (vale a última vista) e usamos ela também
# depois que a manobra sai da pauta ao vivo. O vermelho tem que bater com a pauta real (06/11/2026).
ORDEM = DIR / 'dados' / 'ordem_ao_vivo.csv'
try:
    _ord = pd.read_csv(ORDEM, encoding='utf-8-sig', dtype=str) if ORDEM.exists() else pd.DataFrame(columns=['DT', 'Vessel', 'pos'])
except Exception as _e:
    print(f'[ordem] ordem_ao_vivo.csv não lido: {_e}'); _ord = pd.DataFrame(columns=['DT', 'Vessel', 'pos'])
if not rt.empty:
    _agora_o = pd.Timestamp(dt.datetime.now())
    _rt_o = rt
    _n_o = _rt_o.groupby('DT')['Vessel'].transform('nunique')
    _rt_o = _rt_o[_n_o >= 2]
    if len(_rt_o):
        _novo = []
        for _d, _g in _rt_o.groupby('DT', sort=False):
            _vs = list(dict.fromkeys(_g['Vessel']))
            _novo += [{'DT': _d.strftime('%Y-%m-%d %H:%M'), 'Vessel': _v, 'pos': str(_i)} for _i, _v in enumerate(_vs, 1)]
        _novo = pd.DataFrame(_novo)
        _ord = pd.concat([_ord[~_ord['DT'].isin(set(_novo['DT']))], _novo], ignore_index=True)
        _ord = _ord[pd.to_datetime(_ord['DT'], errors='coerce') >= _agora_o - pd.Timedelta(days=60)]
        try:
            _ord.sort_values(['DT', 'pos']).to_csv(ORDEM, index=False, encoding='utf-8-sig')
        except Exception as _e:
            print(f'[ordem] ordem_ao_vivo.csv não gravado: {_e}')
_ORD_POS = {(pd.Timestamp(a), str(b).strip()): int(c) for a, b, c in zip(_ord['DT'], _ord['Vessel'], _ord['pos'])}


def _completar_dois_praticos(d):
    """Navio de 2 práticos que veio com uma linha só (ainda sem práticos definidos na
    pauta): duplica a linha para que entrem as duas manobras."""
    if d.empty or 'dois_prat' not in d:
        return d
    dois = d['dois_prat'].astype(str).str.strip().str.lower().isin(['true', '1'])
    chave = ['DT', 'Vessel', 'ES'] if 'ES' in d else ['DT', 'Vessel']
    n = d.groupby(chave)['DT'].transform('size')
    falta = d[dois & (n == 1)]
    if len(falta):
        print(f'[pauta] {len(falta)} navio(s) de 2 práticos com uma linha só: duplicados')
        d = pd.concat([d, falta], ignore_index=True).sort_values('DT', kind='stable').reset_index(drop=True)
    return d
h = _completar_dois_praticos(h); rt = _completar_dois_praticos(rt)

# Manobras CANCELADAS depois da escalação (linha verde no SPPilots, status CANCELADA; regra de 29/10/2026):
# saem da pauta normal e vão ao motor marcadas; o prático escalado nelas vai para a frente da fila.
# Ficam registradas em dados/manobras_canceladas.csv (com o prático e a hora em que o cancelamento foi visto),
# para valerem mesmo depois que a linha some da pauta do SPPilots.
CANC = DIR / 'dados' / 'manobras_canceladas.csv'
_canc = pd.read_csv(CANC, dtype=str).fillna('') if CANC.exists() else pd.DataFrame(columns=['DT', 'Vessel', 'From', 'To', 'Pratico', 'visto_em'])
_canc_mudou = False
if not rt.empty and 'Status' in rt:
    _cm = rt['Status'].astype(str).str.strip().str.upper() == 'CANCELADA'
    _cv_rt = rt[_cm]
    rt = rt[~_cm].reset_index(drop=True)
    if len(_cv_rt):
        _agora_c = pd.Timestamp(dt.datetime.now()).floor('min').strftime('%Y-%m-%d %H:%M')
        _kc = lambda a, b, c, d: (pd.Timestamp(a).floor('min'), str(b).strip(), str(c).strip(), str(d).strip())
        _tem = defaultdict(int)
        for _r in _canc.itertuples():
            _tem[_kc(_r.DT, _r.Vessel, _r.From, _r.To)] += 1
        _vist = defaultdict(int); _add = []
        for _r in _cv_rt.itertuples():
            _k = _kc(_r.DT, _r.Vessel, _r.From, _r.To); _vist[_k] += 1
            if _vist[_k] > _tem[_k]:        # navio de 2 práticos: uma linha por prático
                _add.append({'DT': _k[0].strftime('%Y-%m-%d %H:%M'), 'Vessel': _k[1], 'From': _k[2], 'To': _k[3],
                             'Pratico': '', 'visto_em': _agora_c})
        if _add:
            _canc = pd.concat([_canc, pd.DataFrame(_add)], ignore_index=True); _canc_mudou = True
            print(f'[cancelada] {len(_add)} manobra(s) cancelada(s) depois da escalação: prático escalado vai para a frente')
if not h.empty:
    # histórico vale até a última manobra raspada; a pauta atual só entra depois disso
    # (se o pauta_rt.csv estiver velho, ele simplesmente não acrescenta nada)
    corte = h.DT.max() + pd.Timedelta(minutes=1)
    if rt.empty or rt.DT.max() < corte:
        print('[AVISO] pauta_rt.csv sem manobras futuras: clique no favorito "EP Salvar Pauta" com o ep_server.py aberto')
    # manobras já passadas que estão na pauta atual mas ainda não entraram no histórico raspado
    # (antes ficavam de fora até a próxima raspagem): entram pela pauta atual
    # inclui as brancas (FUTURO) atrasadas: continuam na pauta com prático escalado (ex.: KACEY 29/10 11:30, SI);
    # sem elas a vez da E12 não andava e o especial era previsto na manobra seguinte (29/10/2026)
    _orf = rt[rt.DT < corte] if not rt.empty else rt.iloc[0:0]
    if len(_orf):
        _hk = {}
        for _r in h.itertuples():
            _hk.setdefault((_r.Vessel, str(_r.From).strip(), str(_r.To).strip()), []).append(_r.DT)
        _ok = [not any(abs((_r.DT - _t).total_seconds()) <= 6 * 3600
                       for _t in _hk.get((_r.Vessel, str(_r.From).strip(), str(_r.To).strip()), []))
               for _r in _orf.itertuples()]
        _orf = _orf[_ok]
        if len(_orf):
            print(f'[pauta] {len(_orf)} manobra(s) já passadas (ou atrasadas) ainda fora do histórico: mantidas pela pauta atual')
    partes = [h[h.DT < corte]] + ([_orf] if len(_orf) else []) + ([rt[rt.DT >= corte]] if not rt.empty else [])
    p = pd.concat(partes, ignore_index=True)
    p['De'] = p['From']; p['Para'] = p['To']
    p['Termino'] = p['Termino'] if 'Termino' in p else ''
else:   # sem histórico: usa a pauta montada pelo ep_atualizar.py
    p = pd.read_excel(PAUTA_IN).rename(columns={'From': 'De', 'To': 'Para'})
    p['DT'] = pd.to_datetime(p['Data'].astype(str).str.strip() + ' ' + p['Hora'].astype(str).str.strip(),
                             format='%d/%m/%Y %H:%M', errors='coerce')
    p['Vessel'] = p['Vessel'].astype(str).str.strip()
p = p.dropna(subset=['DT']).sort_values('DT', kind='stable').reset_index(drop=True)
# mesmo horário: ordem guardada da pauta ao vivo; sem registro, mantém a ordem que veio
p['_ord'] = [_ORD_POS.get((d, str(v).strip()), 1000 + i) for i, (d, v) in enumerate(zip(p['DT'], p['Vessel']))]
_n_reord = int(sum(1 for (d, v) in zip(p['DT'], p['Vessel']) if (d, str(v).strip()) in _ORD_POS))
p = p.sort_values(['DT', '_ord'], kind='stable').drop(columns='_ord').reset_index(drop=True)
if _n_reord:
    print(f'[ordem] {_n_reord} manobra(s) no mesmo horário na ordem da pauta ao vivo')
p['De'] = p['De'].astype(str).str.strip(); p['Para'] = p['Para'].astype(str).str.strip()
p['Termino'] = p['Termino'].where(p['Termino'].notna(), '').astype(str).replace('nan', '')
print(f'[pauta] {len(p)} manobras, {p.DT.min():%d/%m/%Y} a {p.DT.max():%d/%m/%Y %H:%M}')

# ── 2. Prático real (SPPILOTS): histórico + pauta atual ─────────────────────────
real = {}          # (DT, navio) -> [práticos]
seq_dia = defaultdict(list)   # dia operacional -> ordem real de chamada (E12)
for src in (h, rt):          # pauta atual sobrescreve o histórico
    if src.empty:
        continue
    for k, g in src.groupby(['DT', 'Vessel'], sort=False):
        ps = [J(x) for s in g.Pratico for x in str(s).replace('/', ' ').split() if x and x.upper() not in ('NAN', 'NONE')]
        if ps:
            real[k] = ps
for (t, v), ps in sorted(real.items(), key=lambda kv: kv[0][0]):
    for x in ps:
        if x not in seq_dia[dia_op(t)]:
            seq_dia[dia_op(t)].append(x)
print(f'[sppilots] prático real conhecido em {len(real)} navios')

# ── 3. Escala por dia (planejada + correção pelo que aconteceu de fato) ─────────
R = pd.read_excel(ESCALA, sheet_name='RESUMO')
d0 = dt.date(2026, 1, 1)
PP = ['P%d' % i for i in range(1, 13)]
plano = {}
for i, r in R.iterrows():
    plano[d0 + dt.timedelta(days=i)] = (str(r['TIPO']).strip(), [J(r[c]) if isinstance(r[c], str) else None for c in PP])

# Escala gráfica do SPPilots (lida pelo ep_atualizar.py): quem está realmente de serviço.
# Substitui a escala planejada slot a slot; slot sem leitura mantém o planejado.
_EG = DIR / 'inputs' / 'escala_grafica.json'
if _EG.exists():
    import json as _json
    _n = 0
    for _k, _w in _json.loads(_EG.read_text(encoding='utf-8')).items():
        _d = dt.date.fromisoformat(_k)
        if _d in plano and _w and len(_w) == 12 and sum(1 for x in _w if x) >= 10:
            _tipo, _plan = plano[_d]
            plano[_d] = (_tipo, [J(x) if x else _plan[i] for i, x in enumerate(_w)])
            _n += 1
    print(f'[escala] escala gráfica do SPPilots aplicada em {_n} dias')

# Correção manual da escala (dados/escala_manual.json: {"AAAA-MM-DD": [12 bigramas na ordem dos slots]}).
# Vale acima da escala gráfica: usada quando a leitura da imagem do SPPilots erra (ex.: 31/10/2026).
_EM = DIR / 'dados' / 'escala_manual.json'
if _EM.exists():
    import json as _json
    _n = 0
    for _k, _w in _json.loads(_EM.read_text(encoding='utf-8')).items():
        _d = dt.date.fromisoformat(_k)
        if _d in plano and _w and len(_w) == 12:
            plano[_d] = (plano[_d][0], [J(x) if x else plano[_d][1][i] for i, x in enumerate(_w)])
            _n += 1
    print(f'[escala] correção manual aplicada em {_n} dias')


def _custo(esc, seq):
    reg = [x for x in esc if x not in ESP and x is not None]
    s = [x for x in seq if x in reg]
    best = None
    for k in range(len(reg)):
        rot = reg[k:] + reg[:k]; ix = {x: i for i, x in enumerate(rot)}
        v = [ix[x] for x in s]
        inv = sum(1 for a in range(len(v)) for b in range(a + 1, len(v)) if v[a] > v[b])
        best = inv if best is None or inv < best else best
    return best or 0


def corrigir(plan, seq):
    """Quem manobrou e não estava na escala entra no lugar de quem não manobrou,
    na posição que deixa a vez real da E12 em ordem (mesma regra validada em 17/10)."""
    W = set(seq)
    # Sigla repetida na escala (erro de leitura da escala gráfica, ex.: 03/11/2026 leu NI duas vezes no lugar do LC):
    # todas as posições da sigla repetida viram candidatas a troca; no fim ela fica uma vez só.
    _cnt = {x: plan.count(x) for x in plan if x is not None and x not in ESP}
    dups = {x for x, c in _cnt.items() if c > 1}
    outs = [i for i, x in enumerate(plan) if (x not in W or x in dups) and x not in ESP]
    ins = [x for x in seq if x not in plan and x not in ESP]
    if not ins or not outs:
        return plan
    ins = ins[:len(outs)]
    melhor = None
    for slots in itertools.permutations(outs, len(ins)):
        e = list(plan)
        for x, s in zip(ins, slots):
            e[s] = x
        _r = [x for x in e if x is not None and x not in ESP]
        if len(_r) != len(set(_r)) and len(set(_r)) < len(set(x for x in plan if x is not None and x not in ESP)) + len(ins):
            continue      # ainda sobrou sigla repetida: troca inválida
        c = _custo(e, seq)
        if melhor is None or c < melhor[0]:
            melhor = (c, e)
    return melhor[1] if melhor else plan


escala = {}
for d, (tipo, plan) in plano.items():
    escala[d] = (tipo, corrigir(plan, seq_dia[d]) if seq_dia.get(d) else plan)

# ── CONFERÊNCIA DA ESCALA (05/11/2026): cada dia tem que ter 12 siglas diferentes e incluir todos que manobraram ──
# Erro aqui não pode passar despercebido: vai para ao_vivo/alertas_escala.json e aparece em vermelho no painel.
_ALERTAS = []
_hoje = dt.date.today()
for _d in sorted(escala):
    if not (_hoje - dt.timedelta(days=4) <= _d <= _hoje + dt.timedelta(days=3)):
        continue
    _w = [x for x in escala[_d][1] if x]
    _rep = sorted({x for x in _w if _w.count(x) > 1})
    _fora = [x for x in seq_dia.get(_d, []) if x not in _w and x not in ESP]
    if _rep:
        _ALERTAS.append(f'{_d:%d/%m}: escala com sigla repetida ({", ".join(_rep)}) — confira a escala gráfica')
    if len(_w) != 12:
        _ALERTAS.append(f'{_d:%d/%m}: escala com {len(_w)} siglas (deveriam ser 12)')
    if _fora:
        _ALERTAS.append(f'{_d:%d/%m}: manobrou e não está na escala: {", ".join(_fora)}')
for _a in _ALERTAS:
    print(f'[ALERTA ESCALA] {_a}')
try:
    (DIR / 'ao_vivo').mkdir(exist_ok=True)
    import json as _json
    (DIR / 'ao_vivo' / 'alertas_escala.json').write_text(_json.dumps(_ALERTAS, ensure_ascii=False), encoding='utf-8')
except Exception as _e:
    print(f'[ALERTA ESCALA] não gravado: {_e}')

# turnos D1+D2
dias = sorted(escala)
turnos = []
for i, d in enumerate(dias):
    if escala[d][0] != 'D1':
        continue
    d2 = d + dt.timedelta(days=1)
    nxt = next((x for x in dias[i + 1:] if escala[x][0] == 'D1'), d + dt.timedelta(days=2))
    dia1 = escala[d][1]; dia2 = escala.get(d2, escala[d])[1]
    turnos.append(dict(dt_ini=pd.Timestamp(d) + pd.Timedelta(hours=7.5), dt_d2=pd.Timestamp(d2) + pd.Timedelta(hours=7.5),
                       dt_fim=pd.Timestamp(nxt) + pd.Timedelta(hours=7.5), dia1=dia1, dia2=dia2, Y=list(dia1)))
fim_pauta = p.DT.max()
turnos = [t for t in turnos if t['dt_ini'] <= fim_pauta]
# 1º turno: a fila começa por quem fez a 1ª manobra real do dia
s0 = seq_dia.get(turnos[0]['dt_ini'].date(), [])
if s0 and s0[0] in turnos[0]['dia1']:
    k = turnos[0]['dia1'].index(s0[0]); turnos[0]['Y'] = turnos[0]['dia1'][k:] + turnos[0]['dia1'][:k]
TURNOS = MOTOR / '_turnos_live.pkl'
pickle.dump(turnos, open(TURNOS, 'wb'))
print(f'[escala] {len(turnos)} turnos')

# ── 4. Especiais: E12 real onde há prático; vez da E12 simulada no resto ────────
from ep_algoritmo import gT, BERCO_ZONE
import ep_algoritmo
_Tf = ep_algoritmo._achar_arquivo.__globals__  # só para garantir import
T_df = pd.read_excel(MOTOR / 'inputs' / 'Tempo_T__2025_.xlsx', sheet_name='T Entrada ou saída')
Tmin = {str(r['Berço']).strip(): float(r['T - TEMPO (min)']) for _, r in T_df.iterrows()
        if pd.notna(r['Berço']) and pd.notna(r['T - TEMPO (min)'])}
M_df = pd.read_excel(MOTOR / 'inputs' / 'Tempo_T__2025_.xlsx', sheet_name='Mudanças de entre berços').dropna(subset=['De', 'Para', 'Tm (min)'])
Tmud = {(str(r['De']).strip(), str(r['Para']).strip()): float(r['Tm (min)']) for _, r in M_df.iterrows()}
z5 = lambda a, b: BERCO_ZONE.get(a) == 5 or BERCO_ZONE.get(b) == 5


def fim_de(i):
    t = str(p.Termino.iat[i])
    if ':' in t:
        hh, mm = map(int, t.split(':')[:2]); f = p.DT.iat[i].normalize() + pd.Timedelta(hours=hh, minutes=mm)
        return f if f >= p.DT.iat[i] else f + pd.Timedelta(days=1)
    return p.DT.iat[i] + pd.Timedelta(minutes=gT(p.De.iat[i], p.Para.iat[i], Tmin, Tmud))


FIM = [fim_de(i) for i in range(len(p))]
p['dop'] = [dia_op(t) for t in p.DT]
N = 12
livre = {}; z5c = {}; pred = [None] * len(p); ptr = None; buf = []
for dop, ix in p.groupby('dop', sort=False).indices.items():
    tipo, P = escala.get(dop, ('D2', [None] * 12))
    bold = [x for x in seq_dia.get(dop, []) if x in P][:1] if tipo == 'D1' else []
    if ptr is None or bold:
        ptr = P.index(bold[0]) if bold else 0; buf = []
    ix = list(ix); j = 0
    while j < len(ix):
        n = 2 if j + 1 < len(ix) and p.Vessel.iat[ix[j + 1]] == p.Vessel.iat[ix[j]] and p.DT.iat[ix[j + 1]] == p.DT.iat[ix[j]] else 1
        i0 = ix[j]; t_ = p.DT.iat[i0]; zz = z5(p.De.iat[i0], p.Para.iat[i0])
        conhecido = real.get((t_, p.Vessel.iat[i0]))
        if conhecido:     # E12 real: segue o SPPILOTS e atualiza a vez
            for q, nm in zip(range(n), conhecido + conhecido[:1]):
                pred[ix[j + q]] = nm; livre[nm] = FIM[ix[j + q]]
                if zz: z5c[(dop, nm)] = z5c.get((dop, nm), 0) + 1
                if nm in P:
                    k_ = P.index(nm)
                    if k_ in buf: buf.remove(k_)
                    else:
                        while ptr != k_:
                            buf.append(ptr); ptr = (ptr + 1) % N
                        ptr = (ptr + 1) % N
            j += n; continue
        ok = lambda q: P[q] is not None and livre.get(P[q], pd.Timestamp.min) <= t_ and not (zz and P[q] not in ESP and z5c.get((dop, P[q]), 0) >= 1)
        took = []; k = 0; cls = None; guard = 0
        while len(took) < n and guard < 200:
            guard += 1
            if k >= len(buf):
                if len(buf) + len(took) >= N:
                    cand = [x for x in buf if cls is None or (P[x] in ESP) == cls] or buf
                    livres = [x for x in cand if ok(x)]
                    q = livres[0] if livres else min(cand, key=lambda x: (livre.get(P[x], pd.Timestamp.min), buf.index(x)))
                    took.append(q); buf.remove(q)
                    if cls is None: cls = P[q] in ESP
                    continue
                buf.append(ptr); ptr = (ptr + 1) % N
            q = buf[k]
            if ok(q) and (cls is None or (P[q] in ESP) == cls):
                if cls is None: cls = P[q] in ESP
                took.append(buf.pop(k))
            else:
                k += 1
        for q in took:
            nm = P[q]; pred[ix[j]] = nm; livre[nm] = FIM[ix[j]]
            if zz: z5c[(dop, nm)] = z5c.get((dop, nm), 0) + 1
            j += 1
        if not took:
            j += 1
n_esp = sum(1 for x in pred if x in ESP)
print(f'[especiais] {n_esp} manobras de especiais ({sum(1 for i,x in enumerate(pred) if x in ESP and (p.DT.iat[i],p.Vessel.iat[i]) in real)} pelo SPPILOTS)')

# Giro sem atracar (FB → FB, ex.: "ENTRADA GIRO E SAÍDA DO TECON"): T pela linha "GIRO <área>" da tabela
# de T, conforme a área citada na pauta; sem área identificada, usa GIRO TECON. (Regra de 27/10/2026.)
_GIRO_T = {}
try:
    _tt = pd.read_excel(DIR / 'inputs' / 'Tempo_T__2025_.xlsx', sheet_name='T Entrada ou saída')
    _gt = {str(b).strip().upper(): float(t) for b, t in zip(_tt['Berço'], _tt['T - TEMPO (min)'])
           if str(b).strip().upper().startswith('GIRO') and pd.notna(t)}
    _areas = [('GIRO EMBRAPORT', ('EMBRAPORT', 'DP WORLD', 'DPW')), ('GIRO BTP', ('BTP',)),
              ('GIRO ALEMOA', ('ALEMOA', 'LEMOA')), ('GIRO TECON', ('TECON', 'TCOM', 'SANTOS BRASIL'))]
    _cols = [c for c in ('OBS', 'Obs', 'Agente', 'Celulas') if c in p.columns]
    for _i in range(len(p)):
        if p.De.iat[_i] != 'FB' or p.Para.iat[_i] != 'FB':
            continue
        _txt = ' '.join(str(p[c].iat[_i]) for c in _cols).upper()
        _area = next((a for a, kws in _areas if any(k in _txt for k in kws)), 'GIRO TECON')
        if _area in _gt:
            _GIRO_T[(p.DT.iat[_i].strftime('%Y-%m-%d %H:%M'), 'FB', 'FB')] = _gt[_area]
    if _GIRO_T:
        print(f'[giro] {len(_GIRO_T)} manobra(s) de giro com T da tabela')
except Exception as _e:
    print(f'[giro] não aplicado: {_e}')
# Navio de passageiros: T próprio por berço (regra de 06/11/2026). Tabelas em inputs\navios_passageiros.csv
# (lista de navios) e inputs\T_passageiros.csv (Navio, Berco, Tipo E/S, T_min; Navio "*" = qualquer navio
# de passageiros). Prioridade: linha do navio > linha "*" > T do berço. Vai para o mesmo arquivo de exceções
# de T dos giros (_giro_T.pkl), por (data hora, De, Para), que o motor e o painel já usam.
_PAX_T = 0
try:
    _nav_pax = {str(v).strip().upper() for v in pd.read_csv(DIR / 'inputs' / 'navios_passageiros.csv', encoding='utf-8-sig').Navio.dropna()}
    _tp = pd.read_csv(DIR / 'inputs' / 'T_passageiros.csv', encoding='utf-8-sig', dtype=str).dropna(subset=['Navio', 'Berco', 'Tipo', 'T_min'])
    _tpx = {(str(n).strip().upper(), str(b).strip(), str(t).strip().upper()): float(m)
            for n, b, t, m in zip(_tp.Navio, _tp.Berco, _tp.Tipo, _tp.T_min)}
    for _i in range(len(p)):
        _v = str(p.Vessel.iat[_i]).strip().upper(); _de = str(p.De.iat[_i]).strip(); _pa = str(p.Para.iat[_i]).strip()
        if _v not in _nav_pax or (_de == 'FB') == (_pa == 'FB'):
            continue
        _tipo, _b = ('E', _pa) if _de == 'FB' else ('S', _de)
        _t = _tpx.get((_v, _b, _tipo), _tpx.get(('*', _b, _tipo)))
        if _t is not None:
            _GIRO_T[(p.DT.iat[_i].strftime('%Y-%m-%d %H:%M'), _de, _pa)] = _t; _PAX_T += 1
    print(f'[passageiros] {_PAX_T} manobra(s) de navio de passageiros com T próprio')
except Exception as _e:
    print(f'[passageiros] não aplicado: {_e}')
pickle.dump(_GIRO_T, open(MOTOR / '_giro_T.pkl', 'wb'))

# arquivos de entrada do motor
PAUTA_M = MOTOR / '_pauta_live.xlsx'
# as canceladas entram na pauta do motor no seu horário (depois das demais do mesmo horário), sem especial
_pm = pd.DataFrame({'DT': p.DT, 'Vessel': p.Vessel, 'De': p.De, 'Para': p.Para, 'Termino': p.Termino.astype(str),
                    '_pred': [x or '' for x in pred]})
if len(_canc):
    _cx = pd.DataFrame({'DT': pd.to_datetime(_canc.DT), 'Vessel': _canc.Vessel.astype(str).str.strip(),
                        'De': _canc.From.astype(str).str.strip(), 'Para': _canc.To.astype(str).str.strip(), 'Termino': '', '_pred': ''})
    _cx = _cx[(_cx.DT >= p.DT.min()) & (_cx.DT <= p.DT.max())]
    _pm = pd.concat([_pm, _cx], ignore_index=True).sort_values('DT', kind='stable').reset_index(drop=True)
_CANC_KEY = {(d.strftime('%d/%m/%Y'), d.strftime('%H:%M'), str(v).strip()): {'visto_em': str(ve)}
             for d, v, ve in zip(pd.to_datetime(_canc.DT), _canc.Vessel, _canc.visto_em)} if len(_canc) else {}
pickle.dump(_CANC_KEY, open(MOTOR / '_canceladas.pkl', 'wb'))
pd.DataFrame({'Data': _pm.DT.dt.strftime('%d/%m/%Y'), 'Hora': _pm.DT.dt.strftime('%H:%M'), 'Termino': _pm.Termino.astype(str),
              'Vessel': _pm.Vessel, 'From': _pm.De, 'To': _pm.Para}).to_excel(PAUTA_M, index=False)
ESP_F = MOTOR / '_especiais_live.xlsx'
wb = xlsxwriter.Workbook(str(ESP_F)); ws = wb.add_worksheet()
ws.write_row(0, 0, ['Seq', 'Navio', 'Pratico'])
for i in range(len(_pm)):
    ws.write_row(i + 1, 0, [i + 1, _pm.Vessel.iat[i], _pm._pred.iat[i] or ''])
wb.close()

# ── 5. Motor E2D ────────────────────────────────────────────────────────────────
# Escalação congelada (regra de 29/10/2026): manobra que já COMEÇOU (linha azul na pauta do SPPilots:
# PROXIMO/CONFIRMADO) ou TERMINOU (linha vermelha: AGENDADO/EXECUTADO, ou já no histórico) não muda mais.
# O prático que a E2D tinha nessa hora fica fixo. Linhas brancas e lilases ainda podem mudar (inclusive com atraso).
# Só regulares; manobra de especial nunca é congelada (o motor ignora, ep_sim_v3_corrigido).
STATUS_FIXO = {'PROXIMO', 'CONFIRMADO', 'AGENDADO', 'EXECUTADO'}
_mn = lambda t: pd.Timestamp(t).floor('min')
_fixas = set()
if not h.empty:
    _fixas |= {(_mn(t), str(v).strip()) for t, v in zip(h.DT, h.Vessel)}
if not rt.empty and 'Status' in rt:
    _fixas |= {(_mn(t), str(v).strip()) for t, v, s_ in zip(rt.DT, rt.Vessel, rt.Status)
               if str(s_).strip().upper() in STATUS_FIXO}
CONG = DIR / 'dados' / 'escalacao_finalizada.csv'
# (29/10/2026) O congelamento anterior (1 h antes, gerado com a troca direta) foi DESCARTADO a pedido da Praticagem:
# não se congela o que foi gerado errado. O painel foi refeito do zero com as regras corretas e o congelamento
# vale daí em diante. dados/escalacao_congelada.csv fica guardado, sem uso.
_cg = pd.read_csv(CONG, dtype=str) if CONG.exists() else pd.DataFrame(columns=['DT', 'Vessel', 'Pratico', 'registrado_em'])
# Períodos descongelados (dados/descongelar.json): escalações congeladas que foram geradas com dado errado
# (ex.: escala lida errada) e por isso não valem. Cada item: {"de", "registradas_antes_de", "motivo"}.
_DESC = DIR / 'dados' / 'descongelar.json'
if _DESC.exists() and len(_cg):
    import json as _json
    _n0 = len(_cg)
    _dtc = pd.to_datetime(_cg['DT'], errors='coerce'); _rgc = pd.to_datetime(_cg['registrado_em'], errors='coerce')
    _drop = pd.Series(False, index=_cg.index)
    for _it in _json.loads(_DESC.read_text(encoding='utf-8')):
        _drop |= (_dtc >= pd.Timestamp(_it['de'])) & (_rgc < pd.Timestamp(_it['registradas_antes_de']))
    _cg = _cg[~_drop]
    print(f'[congelada] {_n0 - len(_cg)} escalação(ões) congelada(s) desconsiderada(s) por dados/descongelar.json')
_fz = defaultdict(list)
for _r in _cg.itertuples():
    _d = pd.Timestamp(_r.DT)
    _fz[(_d.strftime('%d/%m/%Y'), _d.strftime('%H:%M'), str(_r.Vessel).strip())].append(str(_r.Pratico).strip())
# prático já registrado numa manobra cancelada: fica o mesmo (é quem estava escalado)
for _r in _canc.itertuples():
    if str(_r.Pratico).strip():
        _d = pd.Timestamp(_r.DT)
        _fz[(_d.strftime('%d/%m/%Y'), _d.strftime('%H:%M'), str(_r.Vessel).strip())].append(str(_r.Pratico).strip())
# Não se congela o que foi gerado errado (05/11/2026): prático congelado numa manobra de um dia em que ele
# não está na escala (ex.: AB e LC em 03-05/11/2026, por erro de leitura da escala gráfica) é descartado e avisado.
_desc = []
for _k in list(_fz):
    _dop = dia_op(pd.Timestamp(dt.datetime.strptime(_k[0] + ' ' + _k[1], '%d/%m/%Y %H:%M')))
    _esc_d = set(x for x in escala.get(_dop, ('', []))[1] if x)
    if not _esc_d:
        continue
    _ok = [x for x in _fz[_k] if x in ESP or x in _esc_d]
    _ruim = [x for x in _fz[_k] if x not in _ok]
    if _ruim:
        _desc.append(f'{_k[0][:5]} {_k[1]} {_k[2]}: {", ".join(_ruim)}')
        if _ok: _fz[_k] = _ok
        else: del _fz[_k]
if _desc:
    print(f'[congelada] {len(_desc)} escalação(ões) congelada(s) descartada(s): prático fora da escala do dia')
    for _x in _desc[-10:]:
        print(f'   {_x}')
pickle.dump(dict(_fz), open(MOTOR / '_congeladas.pkl', 'wb'))
OUT_M = '_E2D_live.xlsx'
env = dict(os.environ, PAUTA_FILE=str(PAUTA_M), ESP_FONTE=str(ESP_F), TURNOS=str(TURNOS),
           MARGEM_ENTRADA=str(MARGEM_ENTRADA), MARGEM_OUTRAS=str(MARGEM_OUTRAS), E2D_OUT=OUT_M,
           FB_OUT=str(MOTOR / '_fallback.pkl'), PYTHONIOENCODING='utf-8', BTP_OV=str(MOTOR / '_giro_T.pkl'), FROZEN=str(MOTOR / '_congeladas.pkl'),
           CANCEL=str(MOTOR / '_canceladas.pkl'))
CONG_FORA = MOTOR / '_cong_fora.pkl'
env['CONG_FORA_OUT'] = str(CONG_FORA)


def _rodar_motor():
    r_ = subprocess.run([sys.executable, 'motor_e2d.py'], cwd=str(MOTOR), env=env, capture_output=True,
                        text=True, encoding='utf-8', errors='replace')
    if r_.returncode != 0:
        print(r_.stdout[-1500:]); print(r_.stderr[-3000:]); sys.exit(1)
    return r_


# Última mudança de regra do motor (05/11/2026: lancha por distância a 20 nós, desembarque 8 min,
# tabela nova de T das mudanças). A conferência do congelamento só olha manobras a partir daqui.
REGRA_DESDE = pd.Timestamp(os.environ.get('REGRA_DESDE', '2026-11-05 21:00'))


def _inconsistencia():
    """Conferência interna (05/11/2026). O motor registra cada manobra congelada que NÃO era a vez do prático
    (havia outro disponível antes dele na fila). Em operação normal isso é raro e leve (pauta mudou depois de
    congelar). Indica congelamento gerado com dado errado quando: o congelado nem estava disponível pela regra,
    ou havia 4+ disponíveis antes dele, ou há 3+ casos no mesmo período de 48 h. Devolve o 1º horário afetado."""
    try:
        L = pickle.load(open(CONG_FORA, 'rb'))
    except Exception:
        return None, []
    L = [x for x in L if x[0] >= pd.Timestamp(dt.date.today() - dt.timedelta(days=10))]
    # Manobras anteriores à última mudança de regra foram escaladas pela regra antiga: não contam aqui
    # (senão a regra nova acusaria o passado de 'fora da vez' e refaria escalações já cumpridas).
    L = [x for x in L if x[0] >= REGRA_DESDE]
    graves = [x for x in L if (not x[6]) or x[5] >= 4]
    ini = min([x[0] for x in graves], default=None)
    for x in L:      # 3 ou mais no mesmo período de 48 h
        n48 = [y for y in L if x[0] <= y[0] < x[0] + pd.Timedelta(hours=48)]
        if len(n48) >= 3:
            ini = x[0] if ini is None else min(ini, x[0])
            break
    return ini, L


r = _rodar_motor()
_ini, _casos = _inconsistencia()
if _ini is not None:
    _agora_c = pd.Timestamp(dt.datetime.now())
    _rg = pd.to_datetime(_cg['registrado_em'], errors='coerce'); _dc = pd.to_datetime(_cg['DT'], errors='coerce')
    _sai = (_dc >= _ini) & (_rg < _agora_c)
    _n = int(_sai.sum())
    _cg = _cg[~_sai]
    for _k in list(_fz):
        if pd.Timestamp(dt.datetime.strptime(_k[0] + ' ' + _k[1], '%d/%m/%Y %H:%M')) >= _ini:
            del _fz[_k]
    pickle.dump(dict(_fz), open(MOTOR / '_congeladas.pkl', 'wb'))
    _msg = (f'congelamento inconsistente a partir de {_ini:%d/%m %H:%M} ({len(_casos)} manobra(s) congelada(s) fora da vez): '
            f'{_n} escalação(ões) congelada(s) refeita(s) automaticamente')
    print(f'[conferência] {_msg}')
    _ALERTAS.append('AVISO: ' + _msg)
    r = _rodar_motor()
    _ini2, _ = _inconsistencia()
    if _ini2 is not None:
        _ALERTAS.append(f'congelamento continua inconsistente a partir de {_ini2:%d/%m %H:%M} — conferir')
        print(f'[conferência] AINDA inconsistente a partir de {_ini2:%d/%m %H:%M}')
    try:
        (DIR / 'ao_vivo' / 'alertas_escala.json').write_text(_json.dumps(_ALERTAS, ensure_ascii=False), encoding='utf-8')
    except Exception:
        import json as _json
        (DIR / 'ao_vivo' / 'alertas_escala.json').write_text(_json.dumps(_ALERTAS, ensure_ascii=False), encoding='utf-8')
print('[motor]', ' | '.join(l for l in r.stdout.splitlines() if 'Etapa' in l or 'Especiais' in l or 'Fallback' in l or 'congeladas' in l))

# grava as manobras que já começaram ou terminaram (azul/vermelha) e ainda não estavam congeladas
try:
    _agora = pd.Timestamp(dt.datetime.now())
    _ja = {(_mn(a), str(b).strip()) for a, b in zip(_cg.DT, _cg.Vessel)}
    _novos = defaultdict(list)
    for _row in openpyxl.load_workbook(MOTOR / OUT_M, read_only=True).worksheets[0].iter_rows(min_row=2, values_only=True):
        if not isinstance(_row[0], int):
            continue
        _d = pd.to_datetime(f'{_row[1]} {_row[2]}', dayfirst=True)
        _pr, _nv = str(_row[4] or '').strip(), str(_row[5] or '').strip()
        if (_mn(_d), _nv) in _fixas and (_mn(_d), _nv) not in _ja and _pr and _pr not in ESP:
            _novos[(_d, _nv)].append(_pr)
    if _novos:
        _add = pd.DataFrame([{'DT': k[0].strftime('%Y-%m-%d %H:%M'), 'Vessel': k[1], 'Pratico': p_,
                              'registrado_em': _agora.strftime('%Y-%m-%d %H:%M')}
                             for k, v in _novos.items() for p_ in v])
        CONG.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([_cg, _add], ignore_index=True).to_csv(CONG, index=False, encoding='utf-8')
        print(f'[congela] {len(_novos)} manobra(s) começada(s)/terminada(s) agora: prático fixo')
except Exception as _e:
    print(f'[congela] não gravado: {_e}')

# registra o prático de cada manobra cancelada (é quem estava escalado nela)
try:
    if len(_canc):
        _cpr = defaultdict(list)
        for _row in openpyxl.load_workbook(MOTOR / OUT_M, read_only=True).worksheets[0].iter_rows(min_row=2, values_only=True):
            if isinstance(_row[0], int) and str(_row[8] or '').startswith('C'):
                _cpr[(pd.to_datetime(f'{_row[1]} {_row[2]}', dayfirst=True), str(_row[5]).strip())].append(str(_row[4]).strip())
        for _i in _canc.index:
            if not str(_canc.at[_i, 'Pratico']).strip():
                _l = _cpr.get((pd.Timestamp(_canc.at[_i, 'DT']), str(_canc.at[_i, 'Vessel']).strip()), [])
                _usados = [x for x in _canc.loc[(_canc.DT == _canc.at[_i, 'DT']) & (_canc.Vessel == _canc.at[_i, 'Vessel']), 'Pratico'] if x]
                _l = [x for x in _l if x not in _usados]
                if _l:
                    _canc.at[_i, 'Pratico'] = _l[0]; _canc_mudou = True
    if _canc_mudou:
        CANC.parent.mkdir(parents=True, exist_ok=True)
        _canc.to_csv(CANC, index=False, encoding='utf-8')
except Exception as _e:
    print(f'[cancelada] não registrado: {_e}')

# ── 6. Planilha no formato que o ep_atualizar.py lê ─────────────────────────────
src = openpyxl.load_workbook(MOTOR / OUT_M, read_only=True).worksheets[0]
SAIDA.parent.mkdir(parents=True, exist_ok=True)
wb = xlsxwriter.Workbook(str(SAIDA)); ws = wb.add_worksheet('E2D 2026')
ws.write(0, 0, f'E2D 2026 — margem {MARGEM_ENTRADA} min antes de entrada / {MARGEM_OUTRAS} min antes de saída e mudança — gerado {dt.datetime.now():%d/%m/%Y %H:%M}')
ws.write_row(1, 0, ['Seq', 'Data', 'Hora', 'Termino', 'Pratico', 'Navio', 'De', 'Para', 'Pts(cont)', 'Pts(real)', 'Total', 'Status', '#Pos', 'Escalacao'])
ri = 2; n = 0; _cpain = []
for row in src.iter_rows(min_row=2, values_only=True):
    if not isinstance(row[0], int):
        continue
    seq, data, hora, term, prat, nav, de, para, st, esc = row[:10]
    if str(st or '').startswith('C'):   # cancelada: fora da planilha; o painel a mostra em verde (canceladas_painel.csv)
        _cpain.append({'DT': pd.to_datetime(f'{data} {hora}', dayfirst=True).strftime('%Y-%m-%d %H:%M'), 'Vessel': str(nav).strip(),
                       'Pratico': str(prat).strip(), 'AB': str(st)[1:]})   # AB = o que ela seria (A ou B)
        continue
    ws.write_row(ri, 0, [seq, data, hora, term or '', prat, nav, de, para, '', '', '', st or '', '', esc or ''])
    ri += 1; n += 1
wb.close()
pd.DataFrame(_cpain, columns=['DT', 'Vessel', 'Pratico', 'AB']).to_csv(SAIDA.parent / 'canceladas_painel.csv', index=False, encoding='utf-8')
print(f'[ok] {SAIDA} — {n} manobras — {time.time()-t0:.0f}s')
