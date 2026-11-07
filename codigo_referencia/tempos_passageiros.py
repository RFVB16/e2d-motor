# -*- coding: utf-8 -*-
"""
Tempos reais de navios de passageiros (regra de 06/11/2026).

1) coletar(senha, DIR): a cada rodada do ep_atualizar.py, lê a "Consulta de Serviços" do SPPilots
   (manobra.asp): a lista de cada dia e o detalhe das manobras. Grava:
     dados/navios_tipo.csv            IMO, Navio, Tipo (tipo de navio do site; serve de cache)
     dados/manobras_passageiros.csv   uma linha por manobra de navio de passageiros, com início,
                                      passagem e término reais
     dados/detalhe_estado.json        até que dia o histórico já foi lido (desde 01/10/2025)
   Só abre o detalhe de navio de passageiros ou de navio ainda desconhecido. Navio de carga
   conhecido não é aberto. Limite por rodada: DET_MAX detalhes e TEMPO_MAX segundos.

2) tabela_auto(DIR, Tmin): T automático por navio de passageiros, berço e tipo (E/S):
   mediana das manobras encerradas (as 10 mais recentes), arredondada para cima em
   múltiplos de 5 min, com pelo menos 3 manobras. Só vale quando fica 10 min ou mais acima
   ou abaixo do T padrão (linha "*" de inputs/T_passageiros.csv para aquele berço, senão o
   T do berço). Grava inputs/T_passageiros_auto.csv e registra cada mudança em
   dados/T_passageiros_mudancas.csv (aparece no painel).
   Navio de carga não entra (decisão do Rodrigo, 06/11/2026).
"""
import json, re, time
from datetime import datetime, timedelta
from pathlib import Path

BASE_URL = 'https://sts.sppilots.com.br'
LISTA = BASE_URL + '/sources/manobra/manobra.asp?act=ALL&dti={a}&dtf={b}&all=X'
DETALHE = BASE_URL + '/sources/manobra/manobra.asp?act=ONE&man={m}&dti={a}&dtf={b}&all=X'
BACKFILL_INI = datetime(2025, 10, 1)
DIAS_RECENTES = 3        # relê sempre os últimos dias (manobras que acabaram de encerrar)
DIAS_BACKFILL = 12       # dias antigos lidos por rodada, até completar o histórico
DET_MAX = 150            # detalhes abertos por rodada
TEMPO_MAX = 100          # segundos por rodada
MIN_N = 3                # manobras para o T automático valer
DIF_MIN = 10             # diferença mínima para o T padrão (min)
ULTIMAS = 10             # mediana das N manobras mais recentes

COLS_MAN = ['man', 'Navio', 'IMO', 'OP', 'Local1', 'Bordo1', 'Local2', 'Bordo2', 'POB', 'Status',
            'Inicio', 'Passagem', 'Termino', 'GT', 'LOA', 'Tipo', 'lido_em']


def _limpa(s):
    return re.sub(r'\s+', ' ', str(s).replace('\xa0', ' ')).strip()


def eh_passageiro(tipo):
    return 'PASSENGER' in str(tipo).upper()


def parse_lista(html, dia):
    """Linhas da lista de um dia: (man, pob 'dd/mm HH:MM', imo, navio, op, local1, local2)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    for a in soup.find_all('a', href=re.compile(r'act=ONE&man=\d+')):
        tr = a.find_parent('tr')
        tds = [_limpa(td.get_text(' ')) for td in tr.find_all('td', recursive=False)] if tr else []
        if len(tds) < 7:
            continue
        m = re.search(r'man=(\d+)', a['href']).group(1)
        mi = re.match(r'(\d+)\s*-\s*(.+)', tds[3])
        imo, navio = (mi.group(1), mi.group(2).strip()) if mi else ('', tds[3])
        out.append(dict(man=m, pob=tds[2], imo=imo, navio=navio, op=tds[4], l1=tds[5], l2=tds[6]))
    return out


def parse_detalhe(html):
    """Campos do detalhe: cada linha de títulos (negrito, fundo azul) é seguida da linha de valores."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    d = {}
    for tr in soup.find_all('tr'):
        st = (tr.get('style') or '').lower()
        if 'font-weight: bold' not in st or '87ab' not in st:
            continue
        labs = [_limpa(td.get_text(' ')) for td in tr.find_all('td', recursive=False)]
        if not labs or labs[0].upper().startswith('MANOBRAS DA ESTADIA'):
            continue
        nxt = tr.find_next('tr')
        if nxt is None:
            continue
        vals = [_limpa(td.get_text(' ')) for td in nxt.find_all('td', recursive=False)]
        for l, v in zip(labs, vals):
            d.setdefault(l.upper(), v)
    return d


def _dt(s):
    s = _limpa(s)
    for f in ('%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S'):
        try:
            return datetime.strptime(s, f)
        except Exception:
            pass
    return None


def coletar(senha, DIR):
    import pandas as pd
    from raspar_historico import fazer_login
    DIR = Path(DIR); D = DIR / 'dados'
    f_tipo, f_man, f_est = D / 'navios_tipo.csv', D / 'manobras_passageiros.csv', D / 'detalhe_estado.json'
    tipos = {}
    if f_tipo.exists():
        t = pd.read_csv(f_tipo, dtype=str, encoding='utf-8-sig').fillna('')
        tipos = {r.IMO: (r.Navio, r.Tipo) for r in t.itertuples() if r.IMO}
    man = pd.read_csv(f_man, dtype=str, encoding='utf-8-sig').fillna('') if f_man.exists() else pd.DataFrame(columns=COLS_MAN)
    feitas = set(man.loc[man.Status.str.upper() == 'ENCERRADA', 'man'])
    est = json.load(open(f_est, encoding='utf-8')) if f_est.exists() else {}
    cursor = datetime.strptime(est.get('backfill_ate', (BACKFILL_INI - timedelta(days=1)).strftime('%Y-%m-%d')), '%Y-%m-%d')

    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    recentes = [hoje - timedelta(days=i) for i in range(DIAS_RECENTES - 1, -1, -1)]
    # histórico: anda para trás a partir dos dias recentes (temporada atual primeiro) até encontrar o
    # trecho já lido para frente desde 01/10/2025 (backfill_ate)
    desde = datetime.strptime(est.get('lido_desde', recentes[0].strftime('%Y-%m-%d')), '%Y-%m-%d')
    antigos = []
    d = desde - timedelta(days=1)
    while d > cursor and len(antigos) < DIAS_BACKFILL:
        antigos.append(d); d -= timedelta(days=1)

    s = fazer_login(senha)
    s.get(BASE_URL + '/default.asp?ctx=OPR', timeout=30)
    t0 = time.time(); n_det = 0; novos = []; parou = False

    def get(url):
        r = s.get(url, timeout=30); r.encoding = 'iso-8859-1'
        return r.text

    for dia in recentes + antigos:      # dias recentes primeiro; depois o histórico antigo
        a = dia.strftime('%d/%m/%Y'); b = (dia + timedelta(days=1)).strftime('%d/%m/%Y')
        if time.time() - t0 > TEMPO_MAX or n_det >= DET_MAX:
            parou = True; break
        try:
            linhas = parse_lista(get(LISTA.format(a=a, b=b)), dia)
        except Exception as e:
            print(f'[Passageiros] lista {a}: {e}'); parou = True; break
        completo = True
        for l in linhas:
            if l['man'] in feitas:
                continue
            tp = tipos.get(l['imo'])
            if tp is not None and not eh_passageiro(tp[1]):
                continue                                  # navio de carga já conhecido
            if time.time() - t0 > TEMPO_MAX or n_det >= DET_MAX:
                completo = False; parou = True; break
            try:
                det = parse_detalhe(get(DETALHE.format(m=l['man'], a=a, b=b))); n_det += 1
            except Exception as e:
                print(f'[Passageiros] detalhe {l["man"]}: {e}'); completo = False; continue
            tipo = det.get('TIPO DE NAVIO', '')
            if not tipo and 'NOME' not in det:            # página sem dados (sessão caiu?)
                completo = False; parou = True; break
            tipos[l['imo']] = (det.get('NOME', l['navio']), tipo)
            if eh_passageiro(tipo):
                novos.append({'man': l['man'], 'Navio': det.get('NOME', l['navio']), 'IMO': l['imo'],
                              'OP': det.get('TIPO', l['op']), 'Local1': det.get('LOCAL #1', l['l1']),
                              'Bordo1': det.get('BORDO #1', ''), 'Local2': det.get('LOCAL #2', l['l2']),
                              'Bordo2': det.get('BORDO #2', ''), 'POB': det.get('POB', ''),
                              'Status': det.get('STATUS', ''), 'Inicio': det.get('INÍCIO', ''),
                              'Passagem': det.get('PASSAGEM', ''), 'Termino': det.get('TÉRMINO', ''),
                              'GT': det.get('GT', ''), 'LOA': det.get('LOA', ''), 'Tipo': tipo,
                              'lido_em': datetime.now().strftime('%Y-%m-%d %H:%M')})
                if det.get('STATUS', '').upper() == 'ENCERRADA':
                    feitas.add(l['man'])
        if completo and dia in antigos:
            desde = dia
        if parou or (dia in antigos and not completo):
            break

    if novos:
        nv = pd.DataFrame(novos, columns=COLS_MAN)
        man = pd.concat([man[~man.man.isin(nv.man)], nv], ignore_index=True)
        tmp = f_man.with_suffix('.tmp'); man.to_csv(tmp, index=False, encoding='utf-8-sig'); tmp.replace(f_man)
    tt = pd.DataFrame([{'IMO': k, 'Navio': v[0], 'Tipo': v[1]} for k, v in tipos.items()])
    tmp = f_tipo.with_suffix('.tmp'); tt.to_csv(tmp, index=False, encoding='utf-8-sig'); tmp.replace(f_tipo)
    est['backfill_ate'] = cursor.strftime('%Y-%m-%d'); est['lido_desde'] = desde.strftime('%Y-%m-%d')
    json.dump(est, open(f_est, 'w', encoding='utf-8'))
    print(f'[Passageiros] {n_det} detalhe(s) lido(s), {len(novos)} manobra(s) de passageiros gravada(s); '
          f'histórico lido de 01/10/2025 a {cursor:%d/%m/%Y} e de {desde:%d/%m/%Y} até hoje; {time.time() - t0:.0f}s')


def nomes_passageiros(DIR):
    """Navios de passageiros: tipo do site (navios_tipo.csv) + lista manual (inputs/navios_passageiros.csv)."""
    import pandas as pd
    DIR = Path(DIR); nomes = set()
    f = DIR / 'dados' / 'navios_tipo.csv'
    if f.exists():
        t = pd.read_csv(f, dtype=str, encoding='utf-8-sig').fillna('')
        nomes |= {n.strip().upper() for n, tp in zip(t.Navio, t.Tipo) if eh_passageiro(tp)}
    f = DIR / 'inputs' / 'navios_passageiros.csv'
    if f.exists():
        nomes |= {str(v).strip().upper() for v in pd.read_csv(f, encoding='utf-8-sig').Navio.dropna()}
    return nomes


def tabela_auto(DIR, Tmin, Tpadrao):
    """Tpadrao: {(berço, tipo): T} das linhas "*" de T_passageiros.csv. Devolve {(navio, berço, tipo): T}."""
    import numpy as np, pandas as pd
    DIR = Path(DIR)
    f_man = DIR / 'dados' / 'manobras_passageiros.csv'
    f_auto = DIR / 'inputs' / 'T_passageiros_auto.csv'
    f_mud = DIR / 'dados' / 'T_passageiros_mudancas.csv'
    cols = ['Navio', 'Berco', 'Tipo', 'T_min', 'T_padrao', 'n', 'valores', 'desde']
    antes = pd.read_csv(f_auto, dtype=str, encoding='utf-8-sig').fillna('') if f_auto.exists() else pd.DataFrame(columns=cols)
    ant = {(r.Navio, r.Berco, r.Tipo): r for r in antes.itertuples()}
    linhas = []
    if f_man.exists():
        m = pd.read_csv(f_man, dtype=str, encoding='utf-8-sig').fillna('')
        m = m[m.Status.str.upper() == 'ENCERRADA'].copy()
        m['ini'] = m.Inicio.map(_dt); m['fim'] = m.Termino.map(_dt)
        m = m[m.ini.notna() & m.fim.notna()].copy()
        m['dur'] = (m.fim - m.ini).dt.total_seconds() / 60
        m = m[(m.dur > 0) & (m.dur < 400)]
        m['tipo'] = np.where((m.Local1 == 'FB') & (m.Local2 != 'FB'), 'E',
                             np.where((m.Local2 == 'FB') & (m.Local1 != 'FB'), 'S', ''))
        m = m[m.tipo != ''].copy()
        m['berco'] = np.where(m.tipo == 'E', m.Local2, m.Local1)
        m = m.drop_duplicates('man').sort_values('ini')
        for (nv, b, tp), g in m.groupby(['Navio', 'berco', 'tipo']):
            v = list(g.dur.tail(ULTIMAS))
            if len(v) < MIN_N:
                continue
            T = float(np.ceil(np.median(v) / 5) * 5)
            base = Tpadrao.get((b, tp), Tmin.get(b, 60))
            if abs(T - base) < DIF_MIN:
                continue
            k = (nv.upper(), b, tp)
            desde = ant[k].desde if k in ant and str(ant[k].T_min) == f'{T:g}' else datetime.now().strftime('%Y-%m-%d %H:%M')
            linhas.append({'Navio': k[0], 'Berco': b, 'Tipo': tp, 'T_min': f'{T:g}', 'T_padrao': f'{base:g}',
                           'n': str(len(v)), 'valores': ' '.join(f'{x:.0f}' for x in v), 'desde': desde})
    novo = pd.DataFrame(linhas, columns=cols)
    nov = {(r.Navio, r.Berco, r.Tipo): r for r in novo.itertuples()}
    mud = []
    agora = datetime.now().strftime('%Y-%m-%d %H:%M')
    for k in set(ant) | set(nov):
        de = ant[k].T_min if k in ant else ''
        para = nov[k].T_min if k in nov else ''
        if de != para:
            r = nov.get(k) or ant.get(k)
            mud.append({'quando': agora, 'Navio': k[0], 'Berco': k[1], 'Tipo': k[2],
                        'T_antes': de or r.T_padrao, 'T_novo': para or r.T_padrao,
                        'n': r.n, 'valores': r.valores})
    if mud:
        mm = pd.DataFrame(mud)
        mm.to_csv(f_mud, mode='a', header=not f_mud.exists(), index=False, encoding='utf-8-sig')
        for x in mud:
            print(f"[Passageiros] T automático: {x['Navio']} {x['Tipo']} {x['Berco']}: {x['T_antes']} -> {x['T_novo']} min ({x['valores']})")
    if mud or not f_auto.exists():
        tmp = f_auto.with_suffix('.tmp'); novo.to_csv(tmp, index=False, encoding='utf-8-sig'); tmp.replace(f_auto)
    return {(r.Navio, r.Berco, r.Tipo): float(r.T_min) for r in novo.itertuples()}
