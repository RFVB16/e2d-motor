"""
ep_sim_v3.py — EP 2M 2025 (versao corrigida com integracao engine_e12)

PATCH: aceita atribuicoes forcadas dos especiais via _ESP_ATRIB_FORCADAS_KEY
       (dict {(data_str, hora_str, vessel_str): especial})

FILA (2 seções em ordem):
  [HH:MM ord. por horário] → [disponíveis FIFO]

CICLO:
  disponível → faz A → HH:MM (ordenado por horário)
  HH:MM zera → disponível → faz B (frente da seção disponível)
  faz B → vai pro final da fila (FIFO)

Fila pós-B: FIFO puro.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import unicodedata
import pandas as pd
from collections import defaultdict, OrderedDict
from datetime import timedelta, datetime

from ep_algoritmo import gL, gT, r15, zona
from nova_escalacao import nova_escalacao
from grupo_a_data import GRUPO_A_DATA

ESPECIAIS = set(filter(None, __import__('os').environ.get('ESP_SET','JA,SI,CH').split(',')))
THRESHOLD = 2.0
BUFFER    = 15
_FALLBACK_LOG = []
import os as _os
_ATRASO = {}
for _x in filter(None, _os.environ.get('ATRASO','').split(';')):
    _p, _t, _m = _x.split('|'); _ATRASO[(_p, _t)] = int(_m)
_ATRASO_MAN = __import__('pickle').load(open(_os.environ['ATRASO_MAN'],'rb')) if _os.environ.get('ATRASO_MAN') else {}
CARRY     = False
Z5_LIMITE_DIA = 1   # max manobras Z5 por pratico por dia operacional

def is_z5(m_fr, m_to):
    """True se a manobra toca Z5 (origem ou destino)."""
    return zona(str(m_fr).strip()) == 5 or zona(str(m_to).strip()) == 5

pts_man_fn  = lambda fr, to, T_mud, is_par=False: 1.0
pts_real_fn = lambda fr, to: 1.0


def norm(s):
    s = str(s).strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.upper()


def avail_time_fn(last, next_fr, T_min, T_mud):
    if last is None:
        return None
    d_calc = r15(last['start'] + timedelta(
        minutes=gT(last['fr'], last['to'], T_min, T_mud) + BUFFER + gL(last['to'], next_fr)
    ))
    # Término real não entra na disponibilidade (apenas informativo).
    return d_calc


# ── GESTÃO DA FILA ────────────────────────────────────────────────────
# A fila é mantida como lista ordenada.
# Seções: [HH:MM] [disponíveis]
# Operações:
#   inserir_apos_A(p)  → coloca na seção HH:MM (reordenada por horário na hora da chamada)
#   inserir_apos_B(p) → coloca no final da fila

def simular_turno(turno, fila_ini, man_df, T_min, T_mud, pares2,
                  pts_g, last_g, tctr,
                  next_slot_carry=None,
                  man_count_prev=0,
                  real_cycle_ref=None,
                  pend_b_carry=None,
                  no_hhmm_carry=None):  # alias para pend_b_carry
    if no_hhmm_carry is not None and pend_b_carry is None:
        pend_b_carry = no_hhmm_carry
    """
    Simula turno EP completo.
    Retorna: (historico, ultima_esc, ns_carry_out, man_count, pend_b)
    """
    dt_d2  = turno['dt_d2']
    dt_fim = turno['dt_fim']

    man_t = man_df[
        (man_df['datetime'] >= turno['dt_ini']) &
        (man_df['datetime'] <  dt_fim)
    ].sort_values('datetime', kind='stable').reset_index(drop=True)

    if len(man_t) == 0:
        return [], '', next_slot_carry or {}, man_count_prev, pend_b_carry or set()

    # DRAGA (regras de 27/10/2026): num navio com 4 ou mais manobras em 36 h (draga indo e voltando),
    # duas manobras seguidas dele EM SEQUÊNCIA (a 2ª começa onde a 1ª terminou e até 30 min depois do
    # fim previsto da 1ª) são feitas pelo MESMO prático, como A e B do mesmo ciclo. Vale qualquer
    # combinação: entrada+saída, saída+entrada, com mudança etc. Se não for em sequência, segue normal.
    # Os pares não se encadeiam.
    _draga_par, _draga_prat = {}, {}
    try:
        _vv = man_t['Vessel'].astype(str).str.strip().values
        _ff = man_t['From'].astype(str).str.strip().values
        _tt = man_t['To'].astype(str).str.strip().values
        _dd = man_t['datetime'].values
        _md = man_df[['datetime']].assign(_v=man_df['Vessel'].astype(str).str.strip())
        _links = []   # (prioridade, i, j): 0 = a 2ª começa antes do fim previsto da 1ª (prático ainda a bordo)
        # navio de 2 práticos (duas linhas no mesmo horário) nunca entra como draga
        _dois = {(v, d) for v, d, n in zip(_vv, _dd, pd.Series(list(zip(_vv, _dd))).map(
            pd.Series(list(zip(_vv, _dd))).value_counts())) if n > 1}
        for _i in range(len(man_t)):
            if (_vv[_i], _dd[_i]) in _dois:
                continue
            # 4 ou mais MANOBRAS (horários distintos) do navio em 36 h
            _n36 = _md.loc[(_md['_v'] == _vv[_i]) & ((_md['datetime'] - _dd[_i]).abs() <= pd.Timedelta(hours=36)),
                           'datetime'].nunique()
            if _n36 < 4:
                continue
            _j = next((j for j in range(_i + 1, len(man_t)) if _vv[j] == _vv[_i] and _dd[j] > _dd[_i]), None)   # próxima manobra do navio
            if _j is None or _ff[_j] != _tt[_i] or (_vv[_j], _dd[_j]) in _dois:
                continue
            # em sequência = a 2ª começa até 30 min depois do fim previsto da 1ª (início + T)
            _fim_i = pd.Timestamp(_dd[_i]) + pd.Timedelta(minutes=gT(_ff[_i], _tt[_i], T_min, T_mud))
            _ini_j = pd.Timestamp(_dd[_j])
            if _ini_j < _fim_i:
                _links.append((0, _i, _j))
            elif _ini_j <= _fim_i + pd.Timedelta(minutes=30):
                _links.append((1, _i, _j))
        _usado = set()
        for _pr, _i, _j in sorted(_links):
            if _i in _usado or _j in _usado:
                continue
            _draga_par[_j] = _i
            _usado.update((_i, _j))
    except Exception:
        _draga_par = {}
    _draga_ent = set(_draga_par.values())
    _draga_reserva = {}   # prático da entrada da draga -> índice da saída que ele vai fazer

    fila         = list(fila_ini)
    fila_display = list(fila_ini)

    _dt_d1  = turno['dt_ini'].date()
    _esc_d1 = GRUPO_A_DATA.get(_dt_d1, {}).get('escala', turno.get('Y', []))
    _esp_sorted = sorted([p for p in ESPECIAIS if p in _esc_d1],
                         key=lambda p: _esc_d1.index(p))
    # next_slot em valores ABSOLUTOS (relativo ao início do ano)
    next_slot = {p: man_count_prev + _esc_d1.index(p) for p in _esp_sorted}
    if next_slot_carry:
        for p in list(ESPECIAIS):
            if p in next_slot_carry and p in _esc_d1:
                # ns_carry é relativo (delta), converter para absoluto
                next_slot[p] = man_count_prev + next_slot_carry[p]

    # FIX DISPLAY: quando ha forcamento via engine_e12, calcular next_slot
    # baseado nas atribuicoes reais que virao - assim o display reflete a
    # manobra exata em que cada especial fara, nao o indice na escala D1.
    _force_map_init = globals().get('_ESP_ATRIB_FORCADAS_KEY', {})
    # _esp_all_pos: todas as posições absolutas de cada especial no turno
    # usado apenas para corrigir o display (não afeta escalação)
    _esp_all_pos = {p: [] for p in ESPECIAIS}
    if _force_map_init:
        _mc_scan = man_count_prev
        for _i in range(len(man_t)):
            _r = man_t.iloc[_i]
            _key = (str(_r['Data']), str(_r['Hora']), str(_r['Vessel']).strip())
            _cands = _force_map_init.get(_key, [])
            if isinstance(_cands, str):
                _cands = [_cands]
            for _c in _cands:
                if _c in ESPECIAIS:
                    _esp_all_pos[_c].append(_mc_scan)
            _mc_scan += 1
        # Inicializar next_slot com PRIMEIRA posição (comportamento original)
        _seen_esp = {}
        _mc_scan2 = man_count_prev
        for _i in range(len(man_t)):
            _r = man_t.iloc[_i]
            _key = (str(_r['Data']), str(_r['Hora']), str(_r['Vessel']).strip())
            _cands = _force_map_init.get(_key, [])
            if isinstance(_cands, str):
                _cands = [_cands]
            for _c in _cands:
                if _c in ESPECIAIS and _c not in _seen_esp:
                    _seen_esp[_c] = _mc_scan2
            _mc_scan2 += 1
        for _esp, _pos in _seen_esp.items():
            if _esp in _esc_d1:
                next_slot[_esp] = _pos

    man_count  = man_count_prev
    dia_atual  = 1
    ultima_esc = ''
    _rr_orig   = {}
    historico  = []
    _no_hhmm   = set()  # pilotos que foram pro final após B: não mostra HH:MM

    # Contador de Z5 por (pratico, dia_op). Reseta a cada virada 07:30.
    z5_count = defaultdict(int)
    _dia_op_atual = None
    _pend_b_cross = set(pend_b_carry) if pend_b_carry else set()

    from datetime import datetime as _dt_, timedelta as _td_

    def _aplicar_pendentes(do_):
        """Aplica regras de pendente B na fila_display após virada de dia op.
        Camada 1: permanentes com ciclo aberto (fez A no dia op anterior)
        Camada 2: entrantes com ciclo aberto (_pend_b_cross, vêm da folga)
        """
        _ini_ = _dt_.combine(do_ - _td_(days=1), _dt_.min.time()) + _td_(hours=7, minutes=30)
        _fim_ = _dt_.combine(do_, _dt_.min.time()) + _td_(hours=7, minutes=30)

        if _os.environ.get('PEND_OFF') == '1': return
        def _eh_perm_(p):
            lg = last_g.get(p)
            if not lg: return False
            s = lg.get('start')
            return s is not None and _ini_ <= s < _fim_

        # Camada 1: permanentes com ciclo aberto
        _pm_ = [p for p in fila_display
                 if p not in ESPECIAIS and _eh_perm_(p) and pts_g.get(p, 0.0) > 0.0]
        if _pm_:
            _pos_ = {p: i for i, p in enumerate(fila_display)}
            _pm_.sort(key=lambda p: _pos_.get(p, 999))
            for _p in _pm_: fila_display.remove(_p)
            _pi_ = 0
            for _i, _q in enumerate(fila_display):
                if _q not in ESPECIAIS: _pi_ = _i; break
            for _p in reversed(_pm_): fila_display.insert(_pi_, _p)

        # Camada 2: entrantes com ciclo aberto (_pend_b_cross)
        _pm_set_ = set(_pm_)
        _ep_ = [p for p in fila_display
                 if p not in ESPECIAIS
                 and p not in _pm_set_
                 and not _eh_perm_(p)
                 and norm(p) in _pend_b_cross]
        if _ep_:
            _pei_ = 0
            for _i, _q in enumerate(fila_display):
                if _q not in ESPECIAIS:
                    if _q in _pm_: _pei_ = _i + 1
                    elif _q not in _ep_: break
            _pos2_ = {p: i for i, p in enumerate(fila_display)}
            _ep_.sort(key=lambda p: _pos2_.get(p, 999))
            for _p in _ep_: fila_display.remove(_p)
            for _p in reversed(_ep_): fila_display.insert(_pei_, _p)

    def _calc_dia_op(dt_):
        """Dia operacional: 07:30 -> 07:29 do dia seguinte."""
        d = dt_.date() if hasattr(dt_, 'date') else dt_
        if (dt_.hour, dt_.minute) < (7, 30):
            d = d - timedelta(days=1)
        return d

    def avail(p, m_fr):
        _at = avail_time_fn(last_g.get(p), m_fr, T_min, T_mud)
        if _ATRASO_MAN and _at is not None and last_g.get(p):
            _lg = last_g.get(p)
            _km = (_lg['start'].strftime('%Y-%m-%d %H:%M'), str(_lg['fr']).strip(), str(_lg['to']).strip())
            if _km in _ATRASO_MAN:
                _at = _at + timedelta(minutes=_ATRASO_MAN[_km])
        if _ATRASO and _at is not None:
            _lg = last_g.get(p)
            _k = (p, _lg['start'].strftime('%Y-%m-%d %H:%M'))
            if _k in _ATRASO:
                _at = _at + timedelta(minutes=_ATRASO[_k])
        return _at

    def is_avail(p, dt, m_fr):
        if p in _draga_reserva:      # reservado para a saída da draga que ele entrou
            return False
        at = avail(p, m_fr)
        try:
            return (at is None) or (at <= dt)
        except:
            return True

    def make_esc(dt, m_fr, _exec_prat=None, _disp=None):
        """Percorre fila_display em ordem (FIFO).
        bigrama = disponível sem crédito
        bigrama(HH:MM) = indisponível
        bigrama(+N) = disponível com crédito
        """
        def hms(a):
            if a is None: return '?'
            try: return a.strftime('%H:%M')
            except: return '?'

        parts = []
        _ddt, _dfr = _disp if _disp else (dt, m_fr)
        for p in fila_display:
            if p in ESPECIAIS:
                continue
            at = avail(p, _dfr)
            try:
                d = (at is None) or (at <= _ddt)
            except:
                d = True
            if not d and (_disp is not None or p not in _no_hhmm):
                parts.append(f'{p}({hms(at)})')
            else:
                parts.append(f'{p}')

        # Especiais: sempre {esp}(N), N = manobra que vai fazer (1-based, contando esta).
        # Posicao = N (1-based) -> idx N-1.
        # Quando ja fez no dia (rem >= 12): mostra (12) no final da fila.
        for p in sorted(next_slot.keys(), key=lambda p: next_slot.get(p, 999)):
            if p not in ESPECIAIS: continue
            # Especial que ACABOU de manobrar nesta linha -> vai para o FIM da fila.
            # Número = 12 + puxada própria desta manobra:
            #   - se foi adiantado em k, a próxima volta à grade em 12+k (gap > 12) -> usa o gap
            #   - se não foi adiantado, gap natural é 12 (ou < 12 se a PRÓXIMA foi puxada) -> usa 12
            # Logo: número = max(12, gap_até_a_próxima). Se não há próxima no turno -> 12.
            if p == _exec_prat:
                # Especial que ACABOU de manobrar. Se a PRÓXIMA manobra dele cai a
                # menos de 12 (gap<12), foi a próxima que foi puxada — ele próprio
                # manobrou natural e deve voltar ao FIM do ciclo com (12). Sem isso,
                # o código original o colocaria no meio (ex.: JA(8)).
                # Se gap>=12 (ele foi puxado: 12+k) ou não há próxima no turno,
                # mantém a renderização original abaixo (que já fica correta no fim).
                _nd = None
                if p in _esp_all_pos:
                    _prox_p = [pos for pos in _esp_all_pos[p] if pos > man_count]
                    if _prox_p:
                        _nd = _prox_p[0] - man_count
                if _nd is not None and _nd < 12:
                    parts.append(f'{p}(12)')
                    continue
            _rem = max(0, next_slot[p] - man_count)
            _tem_proxima = False
            if p in _esp_all_pos:
                _proximas = [pos for pos in _esp_all_pos[p] if pos > man_count]
                if _proximas:
                    _rem = _proximas[0] - man_count
                    _tem_proxima = True
            _label_n = max(1, _rem)
            if _tem_proxima:
                # próxima manobra conhecida no turno (inclui PUXADA): EXATO, sem cap
                _pos = min(_label_n - 1, len(parts))
            else:
                # borda de turno (próxima manobra cai no turno seguinte): o
                # fallback next_slot-man_count vale SE o especial continua
                # trabalhando (gap plausível). Se for grande, foi PUXADO e vai
                # pra FOLGA -> número seria fantasma (ex. SI(21)); limita em 12.
                if _label_n > 14:
                    _label_n = 12
                    _pos = len(parts)
                else:
                    _pos = min(_label_n - 1, len(parts))
            parts.insert(_pos, f'{p}({_label_n})')

        return ' > '.join(parts)

    def _mais_cedo(lst, _mf):
        """Ninguém disponível: escolhe quem fica livre primeiro (empate: ordem da fila)."""
        if not lst: return None
        def _k(i_p):
            i, p = i_p
            at = avail(p, _mf)
            return (at is not None, at if at is not None else 0, i)
        return min(enumerate(lst), key=_k)[1]

    def ep_next(dt, m_fr):
        """Primeiro disponível na fila — scan FIFO."""
        for p in fila_display:
            if p in ESPECIAIS: continue
            if is_avail(p, dt, m_fr):
                return p
        return next((p for p in fila_display if p not in ESPECIAIS), fila_display[0])


    def inserir_apos_A(p, dt, m_fr):
        """Após A: vai para o FIM da seção HH:MM (antes do primeiro disponível)."""
        if p in fila_display:
            fila_display.remove(p)
        # Encontrar o primeiro piloto disponível na fila
        insert_pos = len(fila_display)
        for i, q in enumerate(fila_display):
            if q in ESPECIAIS: continue
            if is_avail(q, dt, m_fr):
                insert_pos = i
                break
        fila_display.insert(insert_pos, p)

    def inserir_apos_B(p):
        """Após B: vai pro final da fila (FIFO). Modelo sem créditos."""
        _no_hhmm.add(p)  # não mostra HH:MM enquanto estiver no final
        if p in fila_display:
            fila_display.remove(p)
        fila_display.append(p)

    def atualizar_esp(prat, dt, m_fr, m_to, foi_puxado, dt_fim_man=None):
        pts_g[prat]  = 0.0
        last_g[prat] = {'start': dt.to_pydatetime(), 'fr': m_fr, 'to': m_to, 'fim': dt_fim_man}
        if not foi_puxado:
            base = _rr_orig.pop(prat, next_slot[prat])
            next_slot[prat] = base + 12

    def atualizar_nao_esp(prat, dt, m_fr, m_to, dt_fim_man=None, is_par=False):
        pm  = pts_man_fn(m_fr, m_to, T_mud, is_par=is_par)
        pa  = pts_g.get(prat, 0.0)
        pd_ = pa + pm
        lar = pd_ >= THRESHOLD

        if real_cycle_ref is not None:
            pr = pts_real_fn(m_fr, m_to)
            real_cycle_ref[prat] = (pr if pa == 0
                                    else real_cycle_ref.get(prat, 0) + pr)

        pts_g[prat]  = round(pd_ - THRESHOLD, 2) if (lar and CARRY) else \
                       (0.0 if lar else round(pd_, 2))
        last_g[prat] = {'start': dt.to_pydatetime(), 'fr': m_fr, 'to': m_to, 'fim': dt_fim_man}
        if not lar:
            _no_hhmm.discard(prat)  # fez A: volta a mostrar HH:MM normalmente
            _pend_b_cross.add(prat)  # ciclo A aberto

        if lar:
            _pend_b_cross.discard(prat)  # ciclo completo
            # Ciclo completo (B): vai pro final da fila (FIFO)
            tctr[0] += 1
            inserir_apos_B(prat)
            if real_cycle_ref is not None:
                real_cycle_ref[prat] = 0
        # Para manobra A (não lar): fila_display NÃO é alterada aqui
        # O piloto fica onde está (seção HH:MM será resolvida na próxima reordenação)

        return pm, pd_, lar

    # ── LOOP PRINCIPAL ────────────────────────────────────────────────
    man_idx = 0

    while man_idx < len(man_t):
        dt = man_t.iloc[man_idx]['datetime']

        # ── VIRADA DO DIA OPERACIONAL (07:30) ───────────────────────
        _do = _calc_dia_op(dt)
        if _dia_op_atual is None or _do != _dia_op_atual:
            z5_count.clear()
            _dia_op_atual = _do
            _aplicar_pendentes(_do)
            _vdump_new = True

        # ── VIRADA D1 → D2 ──────────────────────────────────────────
        if dia_atual == 1 and dt >= dt_d2:
            dia_atual = 2
            if real_cycle_ref is not None:
                real_cycle_ref.clear()

            Y_d2 = [norm(p) for p in turno['dia2'] if p and p != '?']
            Y_d1 = [norm(p) for p in turno['dia1'] if p and p != '?']

            if Y_d2 and set(Y_d2) != set(Y_d1) and ultima_esc:
                nova_str = nova_escalacao(ultima_esc, Y_d1, Y_d2)
                nova_fila = [p.split('(')[0] for p in nova_str.split(' > ') if '(' in p]
                if nova_fila:
                    fila[:] = nova_fila
                    fila_display[:] = list(nova_fila)
                    # Reaplicar após nova_escalacao (sobrescreve fila_display)
                    _aplicar_pendentes(_do)

            _dt_d2_date = turno['dt_d2'].date() if hasattr(turno['dt_d2'], 'date') else turno['dt_d2']
            _map = {Y_d1[i]: Y_d2[i] for i in range(min(len(Y_d1), len(Y_d2)))}
            new_ns = {_map.get(p, p): slot for p, slot in next_slot.items()}
            next_slot.clear()
            next_slot.update(new_ns)

        if _os.environ.get('VIRADA_DUMP') and locals().get('_vdump_new'):
            _vdump_new = False
            _mfr0 = str(man_t.iloc[man_idx]['From']).strip()
            with open(_os.environ['VIRADA_DUMP'], 'a') as _vf:
                _vf.write(f"{dt:%Y-%m-%d %H:%M}\t{make_esc(dt, _mfr0, None, (dt, _mfr0))}\n")
        # ── GRUPO DO MESMO DATETIME ──────────────────────────────────
        grupo = []
        j = man_idx
        while j < len(man_t) and man_t.iloc[j]['datetime'] == dt:
            grupo.append(j)
            j += 1

        vessel_to_idxs = OrderedDict()
        for k in grupo:
            v = man_t.iloc[k]['Vessel']
            if v not in vessel_to_idxs:
                vessel_to_idxs[v] = []
            vessel_to_idxs[v].append(k)

        # FIX: preservar ordem original da pauta. NAO reordenar pares antes de solos.
        # vessel_to_idxs eh OrderedDict populado na ordem em que os navios aparecem
        # no grupo (que segue a sequencia da pauta). Mantemos essa ordem.
        n_navios = list(vessel_to_idxs.keys())
        grupo = [k for v in n_navios for k in vessel_to_idxs[v]]

        mc_por_navio = {}
        mc_cur = man_count
        for v in n_navios:
            idxs = vessel_to_idxs[v]
            mc_por_navio[v] = (mc_cur, mc_cur + 1 if len(idxs) == 2 else None)
            mc_cur += len(idxs)

        mc_range    = range(man_count, mc_cur)
        esp_no_grp  = [p for p, sl in next_slot.items() if sl in mc_range]
        par_mc2_pos = {mc2 for v, (mc1, mc2) in mc_por_navio.items()
                       if mc2 is not None and (dt, str(v).strip()) in pares2}

        # ── PRÉ-ATRIBUIÇÃO ESPECIAIS ──────────────────────────────────
        atrib   = {}
        puxados = set()

        # Se ha atribuicoes forcadas (engine_e12), desativar pre-atribuicao
        # interna - sera tratada manobra a manobra no loop principal
        _force_active = bool(globals().get('_ESP_ATRIB_FORCADAS_KEY'))
        
        if esp_no_grp and not _force_active:
            navios_esp = (
                [v for v in n_navios if any(
                    next_slot.get(p) in (mc_por_navio[v][0], mc_por_navio[v][1])
                    for p in ESPECIAIS)] +
                [v for v in n_navios if not any(
                    next_slot.get(p) in (mc_por_navio[v][0], mc_por_navio[v][1])
                    for p in ESPECIAIS)]
            )
            for vessel in navios_esp:
                idxs   = vessel_to_idxs[vessel]
                n_prt  = len(idxs)
                is_par = (dt, vessel) in pares2
                mc1, mc2 = mc_por_navio[vessel]

                esp_mc1 = [p for p, sl in next_slot.items()
                           if sl == mc1 and p not in atrib.values()]
                esp_trig = esp_mc1[0] if esp_mc1 else None

                if esp_trig:
                    atrib[idxs[0]] = esp_trig
                    if n_prt == 2 and is_par:
                        ja_atrib = set(atrib.values())
                        _esc_ref = GRUPO_A_DATA.get(_dt_d1, {}).get('escala', turno.get('Y', []))
                        # Ordenar pelo next_slot atual: quem vem logo após esp_trig
                        esp_Z = sorted([p for p in ESPECIAIS if p in next_slot],
                                       key=lambda p: next_slot.get(p, 999999))
                        prat2 = None
                        if esp_trig in esp_Z:
                            idx_e = esp_Z.index(esp_trig)
                            c_ = esp_Z[(idx_e + 1) % len(esp_Z)]
                            if c_ not in ja_atrib: prat2 = c_
                        if not prat2:
                            outros = [p for p in ESPECIAIS if p != esp_trig
                                      and p in next_slot and p not in ja_atrib]
                            prat2 = outros[0] if outros else None
                        if not prat2:
                            m_fr2 = str(man_t.iloc[idxs[1]]['From']).strip()
                            cands = [p for p in fila_display
                                     if p not in ESPECIAIS and p not in ja_atrib
                                     and is_avail(p, dt, m_fr2)]
                            prat2 = cands[0] if cands else esp_trig
                        atrib[idxs[1]] = prat2
                        if prat2 in ESPECIAIS:
                            puxados.add(prat2)
                else:
                    ja_atrib = set(atrib.values())
                    m_fr1 = str(man_t.iloc[idxs[0]]['From']).strip()
                    cands = [p for p in fila_display
                             if p not in ESPECIAIS and p not in ja_atrib
                             and is_avail(p, dt, m_fr1)]
                    p1 = cands[0] if cands else next(
                        (p for p in fila_display if p not in ja_atrib), fila_display[0])
                    atrib[idxs[0]] = p1
                    if n_prt == 2 and is_par:
                        ja_atrib2 = set(atrib.values())
                        m_fr2 = str(man_t.iloc[idxs[1]]['From']).strip()
                        cands2 = [p for p in fila_display
                                  if p not in ESPECIAIS and p not in ja_atrib2
                                  and is_avail(p, dt, m_fr2)]
                        p2 = cands2[0] if cands2 else next(
                            (p for p in fila_display if p not in ja_atrib2), p1)
                        atrib[idxs[1]] = p2
                        if mc2 is not None:
                            for p_esp in list(next_slot):
                                if next_slot[p_esp] == mc2 and p_esp in ESPECIAIS:
                                    _rr_orig[p_esp] = mc2
                                    next_slot[p_esp] = mc2 + 1

        # ── PROCESSAR MANOBRAS ────────────────────────────────────────
        for k in grupo:
            man  = man_t.iloc[k]
            m_fr = str(man['From']).strip()
            m_to = str(man['To']).strip()

            # ESCALAÇÃO CONGELADA: a partir de 1 h antes da manobra o prático escalado não muda mais
            # (gravado pelo gerar_2026.py em dados/escalacao_congelada.csv; só regulares)
            # Manobra de especial (mapa da E12) NUNCA é congelada: os especiais ficam sempre como na E12
            # (correção de 29/10/2026: GOLDEN THETIS 29/10 10:30 foi congelada com AG antes de o JA entrar na pauta).
            _kfz = (str(man['Data']), str(man['Hora']), str(man['Vessel']).strip())
            _esp_k = globals().get('_ESP_ATRIB_FORCADAS_KEY', {}).get(_kfz, [])
            if isinstance(_esp_k, str):
                _esp_k = [_esp_k]
            _fz = [] if any(c in ESPECIAIS for c in _esp_k) else \
                  [c for c in globals().get('_FROZEN_KEY', {}).get(_kfz, []) if c not in set(atrib.values())]
            _p_draga = _draga_prat.get(_draga_par[k]) if k in _draga_par else None
            if _fz and k not in atrib:
                atrib[k] = _fz[0]
            if not (_p_draga and _p_draga not in ESPECIAIS) and k in _draga_ent and k not in atrib:
                # 1ª manobra do par da draga: vai para quem está livre e SEM ciclo aberto, para que
                # as duas manobras formem a A e a B do mesmo ciclo
                _ja_d = set(atrib.values())
                _cd = [p for p in fila_display if p not in ESPECIAIS and p not in _ja_d
                       and pts_g.get(p, 0) <= 0 and is_avail(p, dt, m_fr)
                       and not (is_z5(m_fr, m_to) and z5_count.get(p, 0) >= Z5_LIMITE_DIA)]
                _p_draga = _cd[0] if _cd else None
            if _p_draga and _p_draga not in ESPECIAIS and k not in atrib:
                prat = _p_draga
            elif k in atrib:
                prat = atrib[k]
            else:
                # Verificar se ha atribuicao forcada (via engine_e12)
                _key_force = (str(man['Data']), str(man['Hora']), str(man['Vessel']).strip())
                _force_map = globals().get('_ESP_ATRIB_FORCADAS_KEY', {})
                _ja_atrib_v = set(atrib.values())
                _esp_forcado = None
                if _force_map:
                    _candidatos = _force_map.get(_key_force, [])
                    if isinstance(_candidatos, str):
                        _candidatos = [_candidatos]
                    for _c in _candidatos:
                        if _c not in _ja_atrib_v:
                            _esp_forcado = _c
                            break
                
                if _esp_forcado:
                    prat = _esp_forcado
                else:
                    # FILTRO Z5: se manobra toca Z5, exclui praticos que ja
                    # bateram o limite no dia operacional. Especiais nao entram
                    # nesse filtro (rotacao propria).
                    _is_z5_manobra = is_z5(m_fr, m_to)
                    def _filtra_z5(lst):
                        if not _is_z5_manobra:
                            return lst
                        return [p for p in lst if z5_count.get(p, 0) < Z5_LIMITE_DIA]

                    if _force_map:
                        # Forçamento ativo: pegar regular pelo fila_display
                        ja_atrib = set(atrib.values())
                        cands = [p for p in fila_display
                                 if p not in ESPECIAIS and p not in ja_atrib
                                 and is_avail(p, dt, m_fr)]
                        cands = _filtra_z5(cands)
                        if cands:
                            prat = cands[0]
                        else:
                            _resto = [p for p in fila_display
                                      if p not in ESPECIAIS and p not in ja_atrib]
                            _resto_z5 = _filtra_z5(_resto)
                            prat = _mais_cedo(_resto_z5 or _resto, m_fr) or fila_display[0]
                            _FALLBACK_LOG.append((dt, prat, avail(prat, m_fr), str(man['Vessel']).strip(), m_fr, m_to))
                    else:
                        # Comportamento original (sem forcamento)
                        esp_due = sorted([p for p, sl in next_slot.items() if sl == man_count],
                                          key=lambda p: _esc_d1.index(p) if p in _esc_d1 else 999)
                        if esp_due:
                            prat = esp_due[0]
                        else:
                            ja_atrib = set(atrib.values())
                            cands = [p for p in fila_display
                                     if p not in ESPECIAIS and p not in ja_atrib
                                     and is_avail(p, dt, m_fr)]
                            cands = _filtra_z5(cands)
                            if cands:
                                prat = cands[0]
                            else:
                                _resto = [p for p in fila_display
                                          if p not in ESPECIAIS and p not in ja_atrib]
                                _resto_z5 = _filtra_z5(_resto)
                                prat = _mais_cedo(_resto_z5 or _resto, m_fr) or fila_display[0]
                                _FALLBACK_LOG.append((dt, prat, avail(prat, m_fr), str(man['Vessel']).strip(), m_fr, m_to))

            _vf = man_t['dt_fim'].iat[k] if 'dt_fim' in man_t.columns else None
            dt_fim_man = None if (_vf is None or (hasattr(_vf, 'item') and
                                   pd.isna(_vf))) else _vf.to_pydatetime()

            is_par_man = (dt, str(man['Vessel']).strip()) in pares2

            # FIX: registrar atribuicao para que a proxima linha do mesmo par
            # (mesma chave Data/Hora/Vessel) nao reutilize o mesmo especial
            # via _ESP_ATRIB_FORCADAS_KEY. Sem isso, _ja_atrib_v fica vazio na
            # 2a linha do par e o force_map pega o mesmo especial duas vezes.
            atrib[k] = prat
            _draga_prat[k] = prat
            if k in _draga_ent and prat not in ESPECIAIS:
                _draga_reserva[prat] = next(j for j, i in _draga_par.items() if i == k)
            if k in _draga_par and _draga_reserva.get(prat) == k:
                del _draga_reserva[prat]

            # Processar manobra
            pm = 0.0; pd_ = 0.0; lar = False
            if prat in ESPECIAIS:
                atualizar_esp(prat, dt, m_fr, m_to, prat in puxados, dt_fim_man)
            else:
                pm, pd_, lar = atualizar_nao_esp(
                    prat, dt, m_fr, m_to, dt_fim_man, is_par=is_par_man)
                # Após A: piloto FICA NA MESMA POSIÇÃO (só o label HH:MM muda)
                # Após B: inserir_apos_B é chamado dentro de atualizar_nao_esp
                # Contar Z5 para o regular (especiais ficam fora do limite)
                # Conta tanto A quanto B — cada manobra Z5 é independente
                if is_z5(m_fr, m_to) and prat not in ESPECIAIS:
                    z5_count[prat] += 1

            # Escalação pós-manobra
            _dp = None
            if _os.environ.get('DISP_PROX') == '1':
                if k + 1 < len(man_t):
                    _nx = man_t.iloc[k + 1]
                    _dp = (_nx['datetime'], str(_nx['From']).strip())
                else:
                    _dp = (dt, m_fr)
            esc_disp = make_esc(dt, m_fr, prat, _dp)

            man_count += 1
            ultima_esc = esc_disp

            historico.append({
                'seq'           : 0,
                'data'          : man['Data'],
                'hora'          : man['Hora'],
                'termino'       : str(man.get('Termino', '')),
                'vessel'        : str(man['Vessel']),
                'pratico'       : prat,
                'de'            : m_fr,
                'para'          : m_to,
                'pts_man'       : pm if prat not in ESPECIAIS else 0,
                'pts_apos'      : round(pd_, 2),
                'laranja'       : 'verde' if lar else None,
                'escalacao_disp': esc_disp,
                'escalacao'     : esc_disp,
            })

        man_idx = j

        # Catch-up especiais
        for p in list(next_slot):
            if next_slot[p] < man_count and p not in puxados:
                if next_slot[p] in par_mc2_pos:
                    next_slot[p] = man_count
                else:
                    while next_slot[p] < man_count:
                        next_slot[p] += 12
                    # Se pulou demais (além do ciclo atual), ajustar para
                    # a posição correta mais próxima dentro do ciclo de 12
                    while next_slot[p] > man_count + 11:
                        next_slot[p] -= 12
                    if next_slot[p] < man_count:
                        next_slot[p] = man_count

    ns_out = {p: next_slot[p] - man_count for p in next_slot}
    return historico, ultima_esc, ns_out, man_count, _pend_b_cross
