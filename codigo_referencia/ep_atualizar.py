"""
ep_atualizar.py — Script ao vivo EP Porto de Santos

Fluxo:
1. Login SPPILOTS (senha salva em config.json)
2. Raspa histórico 2026 (incremental)
3. Coleta pauta dos próximos 7 dias do SPPILOTS
4. Faz merge da pauta RT com Pauta_de_Manobra_2026.xlsx
5. Roda gerar_2026.py → gera E2D_2026_v6.xlsx
6. Lê planilha e gera ep_painel.html
"""
import sys, os, json, time, pathlib, getpass, subprocess
import pandas as pd
from datetime import datetime, timedelta

_DIR = pathlib.Path(__file__).parent
sys.path.insert(0, str(_DIR))
try:
    from ep_algoritmo import gT as _gT
    _ep_algo_ok = True
except Exception:
    _ep_algo_ok = False

# Carregar T_min/T_mud uma vez no nível do módulo
_T_min, _T_mud = {}, {}
try:
    if _ep_algo_ok:
        import pandas as _pd_tm
        _tempo_t = _DIR / 'inputs' / 'Tempo_T__2025_.xlsx'
        if _tempo_t.exists():
            _tdf = _pd_tm.read_excel(_tempo_t, sheet_name='T Entrada ou saída')
            _T_min = {
                str(r['Berço']).strip(): int(r['T - TEMPO (min)'])
                for _, r in _tdf.iterrows()
                if _pd_tm.notna(r['Berço']) and _pd_tm.notna(r['T - TEMPO (min)'])
            }
            _mud = _pd_tm.read_excel(_tempo_t, sheet_name='Mudanças de entre berços')
            _mud = _mud.dropna(subset=['De', 'Para', 'Tm (min)'])
            _T_mud = {
                (str(r['De']).strip(), str(r['Para']).strip()): int(r['Tm (min)'])
                for _, r in _mud.iterrows()
            }
except Exception:
    pass

# Carregar tabela Tm uma vez no nível do módulo
_T_min: dict = {}
_T_mud: dict = {}
try:
    import pandas as _pd_tm
    _tempo_t = _DIR / 'inputs' / 'Tempo_T__2025_.xlsx'
    if _tempo_t.exists():
        _tdf = _pd_tm.read_excel(_tempo_t, sheet_name='T Entrada ou saída')
        _T_min = {
            str(r['Berço']).strip(): int(r['T - TEMPO (min)'])
            for _, r in _tdf.iterrows()
            if _pd_tm.notna(r['Berço']) and _pd_tm.notna(r['T - TEMPO (min)'])
        }
        _mud = _pd_tm.read_excel(_tempo_t, sheet_name='Mudanças de entre berços')
        _mud = _mud.dropna(subset=['De', 'Para', 'Tm (min)'])
        _T_mud = {
            (str(r['De']).strip(), str(r['Para']).strip()): int(r['Tm (min)'])
            for _, r in _mud.iterrows()
        }
        print(f'[Tm] {len(_T_min)} berços, {len(_T_mud)} mudanças carregados.')
    else:
        print(f'[Tm] AVISO: {_tempo_t} não encontrado — DL usará dt_ini_B como fallback.')
except Exception as _e:
    print(f'[Tm] ERRO ao carregar T_min: {_e}')

# ── Detecção de Z5 ────────────────────────────────────────────────────────────
Z5_BERCOS = {'COS 2', 'COS 3', 'COS 4', 'TIP-2', 'TIP-3', 'TIP-4', 'ULT'}
# Giro sem atracar (FB -> FB): o gT() da tabela devolve 60 min para qualquer FB->FB. O T certo (linhas GIRO da
# tabela de T) o gerar_2026.py grava em motor_e2d/_giro_T.pkl a cada rodada, por (data hora, 'FB', 'FB').
# _gT_m() usa esse T quando a manobra e um giro conhecido; nos demais casos e igual ao gT() de sempre.
_giro_cache = {'mt': None, 'd': {}}
def _giro_T_dict():
    try:
        f = _DIR / 'motor_e2d' / '_giro_T.pkl'
        mt = f.stat().st_mtime
        if _giro_cache['mt'] != mt:
            import pickle as _pk
            _giro_cache['d'] = _pk.load(open(f, 'rb')) or {}
            _giro_cache['mt'] = mt
    except Exception:
        pass
    return _giro_cache['d']

def _gT_m(de, para, dt):
    de = str(de).strip(); para = str(para).strip()
    if de == 'FB' and para == 'FB':
        g = _giro_T_dict().get((pd.Timestamp(dt).strftime('%Y-%m-%d %H:%M'), 'FB', 'FB'))
        if g is not None:
            return g
    return _gT(de, para, _T_min, _T_mud)


def is_z5(de, para):
    return str(de).strip() in Z5_BERCOS or str(para).strip() in Z5_BERCOS

# ── Paths ─────────────────────────────────────────────────────────────────────
CONFIG_PATH = _DIR / 'config.json'
HIST_PATH   = _DIR / 'historico_2026.csv'
# Pauta RT: sempre usa o CSV da pasta do projeto
PAUTA_RT = _DIR / 'pauta_rt.csv'


def _sem_canceladas(d):
    """Linhas CANCELADAS (verde no SPPilots, enviadas pelo userscript v1.4) só servem ao motor
    (gerar_2026.py); o painel continua lendo a pauta como antes, sem elas."""
    try:
        if 'Status' in d.columns:
            return d[d['Status'].astype(str).str.strip().str.upper() != 'CANCELADA'].copy()
    except Exception:
        pass
    return d
PAUTA_XLSX  = _DIR / 'inputs' / 'Pauta_de_Manobra_2026.xlsx'
XLSX_OUT    = _DIR / 'ao_vivo' / 'E2D_2026_v6.xlsx'   # simulação ao vivo (refeita a cada rodada)
PAINEL_PATH = _DIR / 'ep_painel.html'
ESPECIAIS   = {'JA', 'SI', 'CH'}


def _lancha_atalaia_mod(berco_fim):
    """Lancha do fim da B até a Atalaia (min): FB = 12; berço = lancha FB→berço − 12."""
    try:
        from ep_algoritmo import gL as _gL, ATALAIA as _AT
    except Exception:
        return 12
    b = str(berco_fim).strip()
    if b == 'FB':
        return _AT
    return max(_gL('FB', b) - _AT, 0)


def _local_sp(es, de, para):
    """Local no formato do SPPILOTS: entrada E 39, saída S 39, mudança M 34 → 35.2."""
    es = str(es).strip().upper()[:1]
    de, para = str(de).strip(), str(para).strip()
    if es == 'E' or (not es and de == 'FB'):
        return f'E {para}'
    if es == 'S' or (not es and para == 'FB'):
        return f'S {de}'
    return f'M {de} → {para}'


def _fim_b_efetivo(dt, de, para):
    """Fim efetivo da B = início + T de tabela + lancha até a Atalaia."""
    dt = pd.Timestamp(dt)
    try:
        if _ep_algo_ok and _T_min:
            dt = dt + pd.Timedelta(minutes=_gT_m(de, para, dt))
    except Exception:
        pass
    return dt + pd.Timedelta(minutes=_lancha_atalaia_mod(para))


# ── Config ────────────────────────────────────────────────────────────────────
def obter_senha():
    cfg = json.load(open(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
    if cfg.get('senha_sppilots'):
        print('[Config] Usando senha salva.')
        return cfg['senha_sppilots']
    senha = getpass.getpass('Senha SPPILOTS: ')
    cfg['senha_sppilots'] = senha
    json.dump(cfg, open(CONFIG_PATH, 'w'))
    print('[Config] Senha salva.')
    return senha


# ── Coleta SPPILOTS ───────────────────────────────────────────────────────────
def coletar_sppilots(senha):
    print('\n[SPPILOTS] Raspando histórico...')
    try:
        from raspar_historico import raspar_tudo
        raspar_tudo(senha)
    except Exception as e:
        print(f'  [ERRO histórico] {e}')

    # Escala gráfica do SPPilots: quem está realmente de serviço em cada dia (D1/D2)
    try:
        import escala_grafica
        escala_grafica.atualizar(senha, _DIR)
    except Exception as e:
        print(f'  [ERRO escala gráfica] {e}')

    # pauta futura: atualizada pelo botao "Atualizar Pauta SPPILOTS" do painel HTML
    # (requer a aba do SPPILOTS aberta no navegador, na pagina da Pauta)
    avisar_pauta_rt_velha()


def avisar_pauta_rt_velha():
    """Alerta se pauta_rt.csv estiver desatualizada (>2h) ou inexistente."""
    if not PAUTA_RT.exists():
        print('\n' + '!'*60)
        print('! pauta_rt.csv NAO encontrada.')
        print('! Abra o SPPILOTS no navegador (pagina da Pauta) e clique')
        print('! no botao "Atualizar Pauta SPPILOTS" no painel HTML.')
        print('!'*60)
        return

    from datetime import datetime as _dt
    idade_s = (_dt.now().timestamp() - PAUTA_RT.stat().st_mtime)
    idade_h = idade_s / 3600
    if idade_h > 2:
        print('\n' + '!'*60)
        print(f'! ATENCAO: pauta_rt.csv tem {idade_h:.1f}h de idade.')
        print('! Abra o SPPILOTS no navegador (pagina da Pauta) e clique')
        print('! no botao "Atualizar Pauta SPPILOTS" no painel HTML')
        print('! para atualizar antes de usar o painel.')
        print('!'*60)
    else:
        print(f'[pauta_rt.csv] atualizada ha {idade_h*60:.0f} min')


# ── Merge pauta RT na histórica ───────────────────────────────────────────────
def merge_pauta():
    """
    Adiciona manobras da pauta_rt.csv na Pauta_de_Manobra_2026.xlsx.
    Estrategia: tudo a partir do inicio de HOJE vem da pauta_rt (SPPILOTS e a
    fonte de verdade do dia); tudo antes de hoje fica do arquivo original.

    BACKUP AUTOMATICO: antes de sobrescrever, salva o arquivo atual como
    Pauta_de_Manobra_2026_BACKUP.xlsx (reescrito a cada rodada).
    """
    if not PAUTA_XLSX.exists() or not PAUTA_RT.exists():
        print('[Merge] Arquivos não encontrados')
        return

    # Backup antes de qualquer modificacao
    import shutil
    backup_path = PAUTA_XLSX.with_name(PAUTA_XLSX.stem + '_BACKUP' + PAUTA_XLSX.suffix)
    try:
        shutil.copy2(PAUTA_XLSX, backup_path)
        print(f'[Merge] Backup salvo: {backup_path.name}')
    except Exception as e:
        print(f'[Merge] AVISO: falha ao criar backup ({e}). Abortando merge por seguranca.')
        return

    try:
        df_hist = pd.read_excel(PAUTA_XLSX)
        df_hist['datetime'] = pd.to_datetime(
            df_hist['Data'].astype(str) + ' ' + df_hist['Hora'].astype(str),
            dayfirst=True)

        rt = _sem_canceladas(pd.read_csv(PAUTA_RT))
        rt['datetime'] = pd.to_datetime(rt['datetime'])

        rt_fmt = pd.DataFrame({
            'Data':     rt['datetime'].dt.strftime('%d/%m/%Y'),
            'Hora':     rt['datetime'].dt.strftime('%H:%M'),
            'Termino':  '',
            'Vessel':   rt['Vessel'],
            'De':       rt['From'],
            'Para':     rt['To'],
            'datetime': rt['datetime'],
        })
        # NAO fazer drop_duplicates aqui: navios de 2 praticos viram 2 linhas
        # iguais legitimamente e precisam permanecer duplicadas.

        # Corte: primeiro horário da pauta_rt (o que o SPPILOTS está mostrando agora).
        # Tudo ANTES disso vem do xlsx anterior. Tudo A PARTIR disso vem do RT.
        # Isso evita duplicatas de manobras entre 00:00 e o início do RT
        # (ex: manobras de madrugada que já saíram do SPPILOTS mas estão no historico).
        if len(rt) > 0:
            hoje_inicio = pd.Timestamp(rt['datetime'].min()).floor('min')
        else:
            now_merge = datetime.now()
            if now_merge.hour > 7 or (now_merge.hour == 7 and now_merge.minute >= 30):
                hoje_inicio = pd.Timestamp(now_merge.replace(
                    hour=7, minute=30, second=0, microsecond=0))
            else:
                hoje_inicio = pd.Timestamp((now_merge - timedelta(days=1)).replace(
                    hour=7, minute=30, second=0, microsecond=0))

        df_hist_antes = df_hist[df_hist['datetime'] < hoje_inicio]
        rt_hoje_futuro = rt_fmt[rt_fmt['datetime'] >= hoje_inicio].drop(columns=['datetime'])

        # Complementa com manobras do historico_2026.csv que sao de hoje mas
        # nao estao na pauta_rt. Isso pega manobras matinais ja executadas que
        # SPPILOTS nao mostra mais (sairam da pauta visivel apos completar).
        hist_csv_path = _DIR / 'historico_2026.csv'
        complementares = pd.DataFrame()
        if hist_csv_path.exists():
            try:
                hcsv = pd.read_csv(hist_csv_path)
                hcsv['datetime'] = pd.to_datetime(hcsv['datetime'])
                # Deduplicar historico: manter só a primeira ocorrência de (datetime, Vessel)
                hcsv = hcsv.drop_duplicates(
                    subset=['datetime', 'Vessel'],
                    keep='first'
                ).reset_index(drop=True)
                # So pega de hoje
                hcsv_hoje = hcsv[hcsv['datetime'] >= hoje_inicio].copy()
                if len(hcsv_hoje) > 0:
                    # Quais (datetime, vessel) ja estao na rt_hoje_futuro?
                    rt_keys = set(zip(
                        pd.to_datetime(rt_fmt[rt_fmt['datetime'] >= hoje_inicio]['datetime']).dt.floor('min'),
                        rt_fmt[rt_fmt['datetime'] >= hoje_inicio]['Vessel'].astype(str).str.strip().str.upper()
                    ))
                    hcsv_hoje['_key'] = list(zip(
                        pd.to_datetime(hcsv_hoje['datetime']).dt.floor('min'),
                        hcsv_hoje['Vessel'].astype(str).str.strip().str.upper()
                    ))
                    # Pega so as que NAO estao na pauta_rt (complementares)
                    nao_na_rt = hcsv_hoje[~hcsv_hoje['_key'].isin(rt_keys)]
                    if len(nao_na_rt) > 0:
                        complementares = pd.DataFrame({
                            'Data':    nao_na_rt['datetime'].dt.strftime('%d/%m/%Y'),
                            'Hora':    nao_na_rt['datetime'].dt.strftime('%H:%M'),
                            'Termino': '',
                            'Vessel':  nao_na_rt['Vessel'],
                            'De':      nao_na_rt['From'],
                            'Para':    nao_na_rt['To'],
                        })
                        print(f'[Merge] +{len(complementares)} manobras matinais do historico_2026.csv (ja executadas)')
            except Exception as e:
                print(f'[Merge] AVISO: nao deu pra complementar do historico ({e})')

        # Deduplicar df_hist_antes: mesma manobra pode ter sido adicionada
        # em rodadas anteriores com horários diferentes (planejado vs real).
        # Manter a entrada mais recente (maior datetime) para cada
        # (Vessel, De, Para, dia_operacional).
        df_hist_antes['_dt2'] = pd.to_datetime(
            df_hist_antes['Data'].astype(str) + ' ' + df_hist_antes['Hora'].astype(str),
            dayfirst=True, errors='coerce')
        df_hist_antes['_dia_op2'] = (df_hist_antes['_dt2'] - pd.Timedelta(hours=7, minutes=30)).dt.date
        n_antes = len(df_hist_antes)
        df_hist_antes = df_hist_antes.sort_values('_dt2').drop_duplicates(
            subset=['Vessel', 'De', 'Para', '_dia_op2'], keep='last'
        )
        n_depois = len(df_hist_antes)
        if n_antes != n_depois:
            print(f'[Merge] Deduplicadas {n_antes - n_depois} entradas repetidas no xlsx anterior')
        df_hist_antes = df_hist_antes.drop(columns=['_dt2', '_dia_op2'])

        df_hist_antes = df_hist_antes.drop(columns=['datetime'])
        if len(complementares) > 0:
            # Remover de df_hist_antes entradas planejadas do mesmo navio
            # que aparecem nos complementares (execução real em horário diferente).
            # Critério: mesmo Vessel no mesmo dia operacional (07:30→07:30).
            comp_vessels = set(complementares['Vessel'].astype(str).str.strip().str.upper())
            if comp_vessels:
                # Calcular dia operacional de cada entrada do hist_antes
                df_hist_antes['_dt_h'] = pd.to_datetime(
                    df_hist_antes['Data'].astype(str) + ' ' + df_hist_antes['Hora'].astype(str),
                    dayfirst=True, errors='coerce')
                df_hist_antes['_dia_op'] = (df_hist_antes['_dt_h'] - pd.Timedelta(hours=7, minutes=30)).dt.date
                # Calcular dia operacional de cada complementar
                complementares['_dt_c'] = pd.to_datetime(
                    complementares['Data'].astype(str) + ' ' + complementares['Hora'].astype(str),
                    dayfirst=True, errors='coerce')
                complementares['_dia_op'] = (complementares['_dt_c'] - pd.Timedelta(hours=7, minutes=30)).dt.date
                # Pares (vessel, dia_op) que estão nos complementares
                comp_keys = set(zip(
                    complementares['Vessel'].astype(str).str.strip().str.upper(),
                    complementares['_dia_op']
                ))
                # Remover do hist_antes entradas cujo (vessel, dia_op) já está nos complementares
                mask_remover = df_hist_antes.apply(
                    lambda r: (str(r['Vessel']).strip().upper(), r['_dia_op']) in comp_keys, axis=1
                )
                n_rem = mask_remover.sum()
                if n_rem > 0:
                    df_hist_antes = df_hist_antes[~mask_remover]
                    print(f'[Merge] Removidas {n_rem} entradas planejadas substituídas por execução real')
                df_hist_antes = df_hist_antes.drop(columns=['_dt_h', '_dia_op'])
                complementares = complementares.drop(columns=['_dt_c', '_dia_op'])

            df_merged = pd.concat([df_hist_antes, complementares, rt_hoje_futuro], ignore_index=True)
        else:
            df_merged = pd.concat([df_hist_antes, rt_hoje_futuro], ignore_index=True)

        # Deduplicar: se mesmo (Data, Hora, Vessel) aparecer 2x mas NÃO for navio de 2 práticos,
        # manter apenas a primeira ocorrência. Navios de 2 práticos têm duplicata legítima.
        df_merged['_dt'] = pd.to_datetime(df_merged['Data'].astype(str) + ' ' + df_merged['Hora'].astype(str), dayfirst=True, errors='coerce')
        df_merged['_key2'] = df_merged['_dt'].dt.floor('min').astype(str) + '|' + df_merged['Vessel'].astype(str).str.strip().str.upper()
        ct2 = df_merged['_key2'].value_counts()
        keys_duplos = set(ct2[ct2 >= 2].index)
        # Para cada chave com >=2 ocorrências, verificar se veio de fontes diferentes (complementar + rt)
        # Manter apenas os que vêm de rt (mais recente) quando a mesma manobra existe nas duas fontes
        if keys_duplos:
            # Marcamos a origem: complementares vêm antes de rt_hoje_futuro no concat
            n_hist = len(df_hist_antes)
            n_comp = len(complementares) if len(complementares) > 0 else 0
            df_merged['_src'] = 'rt'
            if n_comp > 0:
                df_merged.iloc[n_hist:n_hist+n_comp, df_merged.columns.get_loc('_src')] = 'comp'
            # Se uma chave tem tanto 'comp' quanto 'rt', remove o 'comp'
            mask_remove = (df_merged['_key2'].isin(keys_duplos)) & (df_merged['_src'] == 'comp')
            n_rem = mask_remove.sum()
            if n_rem > 0:
                df_merged = df_merged[~mask_remove]
                print(f'[Merge] Removidas {n_rem} duplicatas complementar/rt')
            df_merged = df_merged.drop(columns=['_src'])
        df_merged = df_merged.drop(columns=['_dt','_key2'])
        df_merged.to_excel(PAUTA_XLSX, index=False)
        print(f'[Merge] Pauta: {len(df_hist_antes)} antes de hoje + '
              f'{len(complementares)} matinais + '
              f'{len(rt_hoje_futuro)} (hoje em diante, via SPPILOTS)')
    except Exception as e:
        print(f'[Merge] ERRO: {e}')


# ── Pauta lida de outra página (29/10/2026) ──────────────────────────────────
PAUTA_BOA = _DIR / 'dados' / 'pauta_rt_ultima_boa.csv'


def validar_pauta_rt():
    """Recusa uma pauta_rt.csv que não é a pauta de serviço atual (ex.: 29/10 15:03, lida quando a aba do
    SPPilots mostrava outra consulta: 73 manobras passadas que não existem no histórico). Critério: entre as
    linhas anteriores à última manobra do histórico, menos da metade acha o mesmo navio no histórico (±6 h),
    com pelo menos 5 linhas assim. Recusada: guarda em dados/pauta_rejeitada_<data hora>.csv e volta a
    última pauta boa; aceita: vira a nova 'última boa'."""
    import shutil
    try:
        if not PAUTA_RT.exists() or not HIST_PATH.exists():
            return
        rt = pd.read_csv(PAUTA_RT, dtype=str)
        h = pd.read_csv(HIST_PATH, dtype=str, usecols=['datetime', 'Vessel'])
        h['dt'] = pd.to_datetime(h['datetime'], errors='coerce'); rt['dt'] = pd.to_datetime(rt['datetime'], errors='coerce')
        corte = h['dt'].max()
        ant = rt[rt['dt'] < corte - pd.Timedelta(hours=1)]
        hv = {}
        for v, t in zip(h['Vessel'].astype(str).str.strip(), h['dt']):
            if pd.notna(t) and t >= corte - pd.Timedelta(days=4):
                hv.setdefault(v, []).append(t)
        ach = sum(1 for v, t in zip(ant['Vessel'].astype(str).str.strip(), ant['dt'])
                  if any(abs((t - x).total_seconds()) <= 6 * 3600 for x in hv.get(v, [])))
        if len(ant) >= 5 and ach < 0.5 * len(ant):
            PAUTA_BOA.parent.mkdir(parents=True, exist_ok=True)
            dest = PAUTA_BOA.parent / f'pauta_rejeitada_{datetime.now():%Y-%m-%d_%H%M}.csv'
            shutil.copy(PAUTA_RT, dest)
            print(f'[AVISO] pauta_rt.csv recusada: {len(ant) - ach} de {len(ant)} manobras passadas não estão no histórico '
                  f'(a aba do SPPilots devia estar em outra página). Guardada em {dest.name}.')
            if PAUTA_BOA.exists():
                shutil.copy(PAUTA_BOA, PAUTA_RT)
                print('[AVISO] usando a última pauta boa.')
            return False
        PAUTA_BOA.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PAUTA_RT, PAUTA_BOA)
        return True
    except Exception as e:
        print(f'[pauta] validação não feita: {e}')


# ── Rodar gerar_2026.py ───────────────────────────────────────────────────────
def rodar_simulacao():
    print('\n[Simulação] Rodando gerar_2026_corrigido.py...')
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, str(_DIR / 'gerar_2026.py')],
        capture_output=True, text=True, cwd=str(_DIR),
        encoding='utf-8', errors='replace',
    )
    if r.returncode != 0:
        print(f'[Simulação] ERRO:\n{r.stderr[-600:]}')
        return False
    print(f'[Simulação] Concluído em {time.time()-t0:.1f}s')
    return True


# ── Ler planilha ──────────────────────────────────────────────────────────────
def ler_planilha():
    """Lê E2D_2026_v6.xlsx e retorna todas as manobras."""
    if not XLSX_OUT.exists():
        print('[Planilha] Não encontrada')
        return []

    import openpyxl
    wb = openpyxl.load_workbook(XLSX_OUT, read_only=True, data_only=True)
    ws = wb.active

    manobras = []
    for r in ws.iter_rows(min_row=3, values_only=True):
        if not r[0] or not str(r[0]).strip().isdigit():
            continue
        try:
            seq, data, hora, term, prat, vessel, de, para, \
                ptsc, ptsr, total, status_ep, pos, esc = r
            dt = pd.to_datetime(f"{data} {hora}", dayfirst=True)
            manobras.append({
                'seq':       seq,
                'datetime':  dt,
                'termino':   str(term) if term else '',
                'pratico':   str(prat),
                'vessel':    str(vessel),
                'de':        str(de),
                'para':      str(para),
                'pts_real':  ptsr,
                'ab':        'B' if status_ep == 'B' else ('A' if status_ep == 'A' else ''),
                'escalacao': str(esc) if esc else '',
            })
        except Exception:
            continue
    return manobras


# ── Relatório por prático: E12 real × E2D no turno (descanso útil, mesmo critério nas duas) ──
_REL = {'d': {}, 'i': {}, 'dia': {}}

def montar_relatorio(manobras):
    """Para cada prático regular em serviço perto de hoje: manobras e descanso útil no turno, E12 real × E2D.
    Descanso útil = do fim da manobra (início + T + lancha até a Atalaia) até 1 h antes do início da seguinte.
    Conta também das 07:30 até o 1º acionamento (tipo 'inicio', fora do descanso longo) e do fim da última até o fim do serviço."""
    import pickle as _pk
    H = pd.Timedelta(hours=1); D0 = pd.Timedelta(hours=7, minutes=30)
    od = lambda t: (pd.Timestamp(t) - D0).date()
    try:
        TT = _pk.load(open(_DIR / 'motor_e2d' / '_turnos_live.pkl', 'rb'))
    except Exception as e:
        print(f'[Relatório] escala indisponível: {e}'); return
    # E12 real: histórico + pauta atual (sem ESPECIAL administrativo)
    try:
        h = pd.read_csv(HIST_PATH, dtype=str); h['dt'] = pd.to_datetime(h['datetime'])
        h = h[['dt', 'Vessel', 'From', 'To', 'Pratico', 'Status']]
    except Exception:
        h = pd.DataFrame(columns=['dt', 'Vessel', 'From', 'To', 'Pratico', 'Status'])
    try:
        rt = _sem_canceladas(pd.read_csv(PAUTA_RT, dtype=str)); rt['dt'] = pd.to_datetime(rt['datetime'])
        rt = rt[rt['dt'] > (h['dt'].max() if len(h) else pd.Timestamp(0))][['dt', 'Vessel', 'From', 'To', 'Pratico', 'Status']]
    except Exception:
        rt = h.iloc[0:0]
    r12 = pd.concat([h, rt]); r12 = r12[r12['Pratico'].notna() & (r12['Status'].fillna('') != 'ESPECIAL')]
    r12 = r12.assign(P=r12['Pratico'].astype(str).str.split('/')).explode('P'); r12['P'] = r12['P'].str.strip()
    r12 = r12[r12['P'] != '']
    reg = r12[~r12['P'].isin(ESPECIAIS)]
    corte = reg['dt'].max() if len(reg) else pd.Timestamp(datetime.now())   # até onde a E12 já tem nome
    e2 = [(pd.Timestamp(m['datetime']), x.strip(), m) for m in manobras for x in str(m.get('pratico', '')).split('/') if x.strip()]

    def fim(dt, de, para): return _fim_b_efetivo(dt, de, para)
    _ler_canceladas()
    def calc(lst, ini, fimw):
        lst = sorted(lst, key=lambda z: z[0]); use = [z for z in lst if z[0] <= corte]
        gaps = []; prev = ini; prevlab = f'{ini:%H:%M}'; prevab = ''; prim = True
        for dt, end, lab, ab in use:
            lab = lab[:11] + (' (cancelada)' if ab == 'X' else '')   # descansos: só data e hora (sem navio e berço)
            g = (dt - H - prev).total_seconds() / 60
            if prim:   # das 07:30 até o 1º acionamento (1 h antes da 1ª manobra): não é descanso longo (29/10/2026)
                if g > 0:
                    gaps.append((prevlab, f'1º acionamento {dt - H:%d/%m %H:%M}', g, 'inicio', prev, dt - H, False))
            else:
                gaps.append((prevlab, lab, g, 'canc' if prevab == 'X' else ('ciclo' if prevab == 'A' else 'longo'), prev, dt - H, True))
            prev = end; prevlab = lab; prevab = ab; prim = False
        fechado = fimw <= corte
        prox = [z[0] for z in lst if z[0] > corte]
        lim = min([fimw, corte] + [prox[0] - H] if prox else [fimw, corte])
        g = (lim - prev).total_seconds() / 60
        if g > 0:
            _acn = bool(prox) and lim == prox[0] - H   # termina no acionamento da próxima: intervalo completo
            gaps.append((prevlab, 'fim do serviço' if lim == fimw else ('acionamento ' + f'{prox[0]:%d/%m %H:%M}' if _acn else f'{corte:%d/%m %H:%M} (em andamento)'), g,
                         'inicio' if prim else ('canc' if prevab == 'X' else ('ciclo' if (prevab == 'A' and lim != fimw) else 'longo')),
                         prev, lim, (not prim) and _acn, (not prim) and lim != fimw and not _acn))
        # madrugada (0h–5h): da saída à volta da Atalaia, unindo se < 2 h em terra
        per = []
        for dt, end, _, _ in use:
            if per and dt - per[-1][1] < pd.Timedelta(hours=2): per[-1][1] = max(per[-1][1], end)
            else: per.append([dt, end])
        mad = 0.0
        for a, b in per:
            d = a.normalize() - pd.Timedelta(days=1)
            while d <= b:
                lo, hi = max(a, d), min(b, d + pd.Timedelta(hours=5))
                if hi > lo: mad += (hi - lo).total_seconds() / 60
                d += pd.Timedelta(days=1)
        gaps = [tuple(g) + (False,) * (8 - len(g)) for g in gaps]   # (de, até, min, tipo, início, fim, entre duas manobras, em andamento)
        vals = [max(g[2], 0) for g in gaps]
        lon = [max(g[2], 0) for g in gaps if g[3] == 'longo']; cic = [max(g[2], 0) for g in gaps if g[3] == 'ciclo']
        return gaps, dict(n=sum(1 for z in use if z[3] != 'X'), maior=max(vals) if vals else 0, total=sum(vals), mad=mad, fechado=fechado,
                          maior_longo=max(lon) if lon else 0, total_longo=sum(lon), total_ciclo=sum(cic), n_ciclo=len(cic))

    hoje = od(datetime.now()); D = {}; I = {}
    _INT = {'e2d': [], 'e12': []}   # (dia operacional, minutos) de todos os práticos, para a linha do dia
    for t in TT:
        if not (pd.Timestamp(hoje) - pd.Timedelta(days=4) <= t['dt_ini'] <= pd.Timestamp(hoje) + pd.Timedelta(days=2)): continue
        for p in set(t['dia1']) | set(t['dia2']):
            if p in ESPECIAIS: continue
            dias = ([t['dt_ini']] if p in t['dia1'] else []) + ([t['dt_d2']] if p in t['dia2'] else [])
            key = f'{p}|{od(dias[0])}'
            for dd in dias: I[f'{p}|{od(dd)}'] = key
            if key in D: continue
            ini = dias[0]; fimw = dias[-1] + pd.Timedelta(days=1)
            l12 = []
            for _, r in reg[(reg['P'] == p) & (reg['dt'] >= ini) & (reg['dt'] < fimw)].drop_duplicates(['dt', 'Vessel']).iterrows():
                l12.append((r['dt'], fim(r['dt'], r['From'], r['To']), f"{r['dt']:%d/%m %H:%M} {str(r['Vessel'])[:18]} ({_local_sp('', r['From'], r['To'])})", ''))
            l2 = []
            for dt, x, m in e2:
                if x == p and ini <= dt < fimw:
                    l2.append((dt, fim(dt, m['de'], m['para']), f"{dt:%d/%m %H:%M} {str(m['vessel'])[:18]} ({_local_sp('', m['de'], m['para'])})", str(m.get('ab', '')).strip().upper()[:1]))
            # cancelada depois da escalação: o descanso vai até o acionamento dela e recomeça no horário dela
            for (cd, cv), cl in _CANC_LIN.items():
                for cp, cab in cl:
                    if cp == p and ini <= cd < fimw:
                        l2.append((cd, cd, f"{cd:%d/%m %H:%M} {cv[:18]} (cancelada)", 'X'))   # X = cancelada: não conta como manobra
            g12, s12 = calc(l12, ini, fimw); g2, s2 = calc(l2, ini, fimw)
            # comparação (31/10/2026): descansos longos da E2D (da B até a A) × TODOS os intervalos da E12
            # (na E12 todo intervalo é descanso: a vez volta a cada 12). Só intervalos completos entre duas manobras.
            _l2 = [g[2] for g in g2 if g[3] == 'longo' and g[6]]
            _l12 = [g[2] for g in g12 if g[6]]
            _med = lambda v: float(pd.Series(v).median()) if v else None
            for _g, _lst in ((g2, _INT['e2d']), (g12, _INT['e12'])):
                for g in _g:
                    if g[6] and (_g is g12 or g[3] == 'longo'):
                        _lst.append((od(g[5] + H), g[2]))
            lim_b = min(fimw, corte)
            def _seg(L, gaps):
                ms = [[int(pd.Timestamp(max(ini, dt - H)).value // 10**6), int(pd.Timestamp(min(end, lim_b)).value // 10**6), ab, lab]
                      for dt, end, lab, ab in sorted(L, key=lambda z: z[0]) if dt <= corte and ab != 'X']
                gs = [[int(pd.Timestamp(g[4]).value // 10**6), int(pd.Timestamp(min(g[5], lim_b)).value // 10**6), round(g[2]),
                       'andamento' if g[7] else ('emendado' if g[3] == 'ciclo' and g[2] < 0 else g[3])] for g in gaps if g[4] < lim_b]
                return ms, gs
            sb2 = _seg(l2, g2); sb12 = _seg(l12, g12)
            fmt = lambda L: [dict(t=lab, f='' if ab == 'X' else f'{end:%H:%M}', fut=bool(dt > corte), ab='' if ab == 'X' else ab) for dt, end, lab, ab in sorted(L, key=lambda z: z[0])]
            D[key] = dict(p=p, ini=f'{ini:%d/%m %H:%M}', fim=f'{fimw:%d/%m %H:%M}', corte=f'{corte:%d/%m %H:%M}',
                          m12=fmt(l12), m2=fmt(l2),
                          g12=[[g[0], g[1], round(g[2]), 'andamento' if g[7] else (g[3] if g[3] in ('inicio', 'canc') else '')] for g in g12],
                          g2=[[g[0], g[1], round(g[2]), 'andamento' if g[7] else ('emendado' if g[3] == 'ciclo' and g[2] < 0 else g[3])] for g in g2],
                          s12=s12, s2=s2,
                          c2=dict(med=_med(_l2), n=len(_l2), lt5=sum(1 for v in _l2 if v < 300)),
                          c12=dict(med=_med(_l12), n=len(_l12), lt5=sum(1 for v in _l12 if v < 300)),
                          b0=int(pd.Timestamp(ini).value // 10**6), b1=int(pd.Timestamp(lim_b).value // 10**6),
                          b2=sb2, b12=sb12, d1=f'{od(ini)}', d2=f'{od(dias[-1])}')
    # linha do dia (todos os práticos): descanso longo típico da E2D × intervalo típico da E12, e % abaixo de 5 h
    DIA = {}
    for k in ('e2d', 'e12'):
        for d_, v in _INT[k]:
            DIA.setdefault(str(d_), {}).setdefault(k, []).append(v)
    _REL['dia'] = {d_: {k: dict(med=float(pd.Series(v).median()), n=len(v), lt5=round(100 * sum(1 for x in v if x < 300) / len(v)))
                        for k, v in x.items()} for d_, x in DIA.items()}
    _REL['d'], _REL['i'] = D, I
    print(f'[Relatório] {len(D)} turnos de práticos preparados (E12 com nome até {corte:%d/%m %H:%M})')

# ── Info pauta RT ─────────────────────────────────────────────────────────────
import re as _re_cb
_CB_HIST = {}   # (datetime, navio) -> (calado, bordo) vindos do histórico (manobras já executadas)


def _norm_cb(*vals):
    """Calado e bordo pelo conteúdo, qualquer que seja a coluna (o SPPILOTS mudou a ordem
    das colunas): calado = '12,75' ou '12,75 | 12,95'; bordo = BB ou BE."""
    cal = brd = ''
    for v in vals:
        v = '' if v is None else str(v).strip()
        if v.lower() == 'nan':
            continue
        if not cal and _re_cb.fullmatch(r'\d{1,2}[,.]\d{1,2}(\s*\|\s*\d{1,2}[,.]\d{1,2})?', v):
            # dois valores ("12,75 | 12,95"): mostra o maior
            _nums = [float(x.replace(',', '.')) for x in _re_cb.findall(r'\d{1,2}[,.]\d{1,2}', v)]
            cal = f'{max(_nums):.2f}'.replace('.', ',') if _nums else v
        elif not brd and v.upper() in ('BB', 'BE'):
            brd = v.upper()
    return cal, brd


def info_pauta_rt():
    """Retorna dict {(datetime, vessel): info} da pauta RT."""
    global _CB_HIST
    try:
        _h = pd.read_csv(HIST_PATH, dtype=str)
        _h['datetime'] = pd.to_datetime(_h['datetime'], errors='coerce')
        _h = _h[_h['datetime'] >= pd.Timestamp(datetime.now()) - pd.Timedelta(days=4)]
        _CB_HIST = {(r['datetime'], str(r['Vessel']).strip()): _norm_cb(r.get('Calado'), r.get('Bordo'))
                    for _, r in _h.iterrows()}
    except Exception as _e:
        print(f'[calado/bordo] histórico não lido: {_e}')
    idx = {}
    if not PAUTA_RT.exists():
        return idx
    rt = _sem_canceladas(pd.read_csv(PAUTA_RT))
    rt['datetime'] = pd.to_datetime(rt['datetime'])
    for seq_rt, row in rt.iterrows():  # seq_rt = índice linha = ordem SPPILOTS
        key = (row['datetime'], str(row['Vessel']).strip())
        if key in idx:
            # 2 entradas pra mesma (datetime, vessel) = navio de 2 praticos
            idx[key]['pratico'] += '/' + str(row.get('Pratico', ''))
            idx[key]['dois_prat'] = True
        else:
            # dois_prat tambem eh marcado se a coluna explicita dizer
            dois = bool(row.get('dois_prat', False))
            if isinstance(dois, str):
                dois = dois.lower() in ('true', '1', 'sim', 's')
            idx[key] = {
                'status':    row.get('Status', ''),
                'pratico':   str(row.get('Pratico', '')),
                'calado':    _norm_cb(row.get('Calado'), row.get('Bordo'), *str(row.get('Celulas', '') or '').split(' ¦ '))[0],
                'bordo':     _norm_cb(row.get('Calado'), row.get('Bordo'), *str(row.get('Celulas', '') or '').split(' ¦ '))[1],
                'es':        str(row.get('ES', '')),
                'dois_prat': dois,
                'seq_rt':    int(seq_rt),  # ordem da linha no SPPILOTS
            }
    return idx



# ── Manobras em observação (atraso / escalação alterada) ─────────────────────
OBS_FOLGA_MIN = 15      # B com menos que isso entre o fim previsto da A (+ lancha) e o início: "apertada"
OBS_JANELA_MIN = 60     # a escalação acontece 1 h antes da manobra
OBS_DENTRO_T_MIN = 0    # na escalação, a manobra anterior ainda não terminou pelo T (31/10/2026; antes: mais de 30 min, só na B)

def marcar_observacao(manobras):
    """Marca m['obs_e2d'] (lista de motivos) nas manobras que merecem observação:
       1) B apertada (risco de atraso): pouca folga entre o fim previsto da A do mesmo prático e a B;
       2) escalado ainda em manobra: na escalação (1 h antes), A ou B, a manobra anterior do mesmo prático
          ainda não terminou pelo T (desde 31/10/2026; antes só na B e com mais de 30 min pela frente).
    Só manobras confirmadas e já escaladas (<= 1 h antes) são marcadas.
    O registro fica em dados/escalacao_registro.json e os casos em dados/observacao_log.csv."""
    import json, csv
    try:
        from ep_algoritmo import gL as _gLo
    except Exception:
        _gLo = lambda a, b: 0
    now = pd.Timestamp(datetime.now())
    pasta = _DIR / 'dados'; pasta.mkdir(exist_ok=True)
    reg_p = pasta / 'escalacao_registro.json'; log_p = pasta / 'observacao_log.csv'
    try:
        reg = json.loads(reg_p.read_text(encoding='utf-8')) if reg_p.exists() else {}
    except Exception:
        reg = {}
    pr = lambda m: [x.strip() for x in str(m.get('pratico', '')).split('/') if x.strip() and x.strip().upper() not in ('NAN', 'NONE')]
    for m in manobras:
        m['obs_e2d'] = []
    def conf(m):   # mesma regra do painel: confirmada = status diferente de FUTURO (sem status: já passou)
        st = str(m.get('status', '')).upper()
        if st == 'FUTURO': return False
        if st == '': return pd.Timestamp(m['datetime']) <= now
        return True
    ordem = sorted(manobras, key=lambda x: (pd.Timestamp(x['datetime']), int(x.get('seq') or 0)))
    # 1) B apertada
    ult = {}
    for m in ordem:
        dt = pd.Timestamp(m['datetime'])
        for p in pr(m):
            if p in ESPECIAIS:
                continue
            ant = ult.get(p)
            # só para manobra confirmada: antes disso a pauta ainda se ajusta
            if (m.get('ab') == 'B' and ant is not None and conf(m) and dt - now <= pd.Timedelta(minutes=OBS_JANELA_MIN)
                    and dt >= now - pd.Timedelta(days=2)
                    and dt - pd.Timestamp(ant['datetime']) < pd.Timedelta(hours=16)):
                try:
                    T = _gT_m(ant.get('de', ''), ant.get('para', ''), ant['datetime'])
                    L = _gLo(str(ant.get('para', '')).strip(), str(m.get('de', '')).strip())
                    folga = (dt - (pd.Timestamp(ant['datetime']) + pd.Timedelta(minutes=T + L))).total_seconds() / 60
                    if folga < OBS_FOLGA_MIN:
                        m['obs_e2d'].append(f'B apertada ({p}): {folga:.0f} min entre o fim previsto da A '
                                            f'({str(ant["vessel"]).strip()} {pd.Timestamp(ant["datetime"]):%H:%M}) + lancha e esta B')
                except Exception:
                    pass
            ult[p] = m
    # 2) risco de manipulação (critério do estudo "escalados dentro do T"): na escalação da B
    #    (1 h antes), o prático ainda está na A com mais de 30 min pela frente (fim da A pelo T).
    ult = {}
    for m in ordem:
        dt = pd.Timestamp(m['datetime'])
        for p in pr(m):
            if p in ESPECIAIS:
                continue
            ant = ult.get(p)
            if (m.get('ab') in ('A', 'B') and ant is not None and conf(m) and dt - now <= pd.Timedelta(minutes=OBS_JANELA_MIN)
                    and dt >= now - pd.Timedelta(days=2)
                    and dt - pd.Timestamp(ant['datetime']) < pd.Timedelta(hours=16)):
                try:
                    T = _gT_m(ant.get('de', ''), ant.get('para', ''), ant['datetime'])
                    fimA = pd.Timestamp(ant['datetime']) + pd.Timedelta(minutes=T)
                    resta = (fimA - (dt - pd.Timedelta(minutes=OBS_JANELA_MIN))).total_seconds() / 60
                    if resta > OBS_DENTRO_T_MIN:
                        m['obs_e2d'].append(f'dentro do T ({p}): na escalação (1 h antes) ainda faltavam {resta:.0f} min '
                                            f'para o fim previsto da manobra anterior ({str(ant["vessel"]).strip()} {pd.Timestamp(ant["datetime"]):%H:%M})')
                except Exception:
                    pass
            ult[p] = m
    # limpa registros antigos e grava
    reg = {k: r for k, r in reg.items() if pd.Timestamp(r['dt']) > now - pd.Timedelta(days=3)}
    reg_p.write_text(json.dumps(reg, ensure_ascii=False, indent=0), encoding='utf-8')
    # log (sem repetir)
    vistos = set()
    if log_p.exists():
        with open(log_p, encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) >= 5: vistos.add((row[1], row[2], row[4]))
    novos = []
    for m in manobras:
        for mot in dict.fromkeys(m['obs_e2d']):
            k = (f'{pd.Timestamp(m["datetime"]):%Y-%m-%d %H:%M}', str(m['vessel']).strip(), mot)
            if k not in vistos:
                vistos.add(k); novos.append([f'{now:%Y-%m-%d %H:%M}', k[0], k[1], str(m.get('pratico', '')), mot])
    if novos:
        novo = not log_p.exists()
        with open(log_p, 'a', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            if novo: w.writerow(['registrado_em', 'manobra', 'navio', 'pratico', 'motivo'])
            w.writerows(novos)
    n = sum(1 for m in manobras if m['obs_e2d'])
    print(f'[Observação] {n} manobras marcadas ({len(novos)} novos casos no log)')

_DL_TEMPOS = []   # horário da B de cada valor de deltas_min_dia (para a semana atual)

# ── Montar dados do painel ────────────────────────────────────────────────────
_CANC_INI = {}   # prático -> inícios das manobras canceladas depois da escalação
_CANC_LIN = {}   # (início, navio) -> [(prático, A/B que seria)]
_CANC_DT = {}    # (início, navio) -> Δt da linha verde


def _ler_canceladas():
    """ao_vivo/canceladas_painel.csv (gerado pelo gerar_2026.py): prático e o que a cancelada seria (A/B)."""
    _CANC_INI.clear(); _CANC_LIN.clear()
    try:
        f = _DIR / 'ao_vivo' / 'canceladas_painel.csv'
        if f.exists():
            for r in pd.read_csv(f, dtype=str).fillna('').itertuples():
                d = pd.Timestamp(r.DT).floor('min'); v = str(r.Vessel).strip(); p = str(r.Pratico).strip()
                if p:
                    _CANC_INI.setdefault(p, []).append(d)
                    _CANC_LIN.setdefault((d, v), []).append((p, str(r.AB).strip()))
    except Exception as e:
        print(f'[cancelada] não lida: {e}')


def montar_dados(manobras, rt_idx):
    """Separa manobras em: passadas (últimas 20), futuras e histórico."""
    now = pd.Timestamp(datetime.now())
    _ler_canceladas()

    # Inicio do dia operacional vigente (07:30 hoje, ou 07:30 ontem se ainda < 07:30)
    if now.hour > 7 or (now.hour == 7 and now.minute >= 30):
        ini_hoje = now.replace(hour=7, minute=30, second=0, microsecond=0)
    else:
        ini_hoje = now.replace(hour=7, minute=30, second=0, microsecond=0) - timedelta(days=1)

    # HISTORICO comeca 1 dia operacional ANTES (07:30 ontem do dia operacional vigente)
    ini_hist = ini_hoje - timedelta(days=1)

    # Inicio da pauta RT (primeira manobra que o SPPILOTS esta mostrando).
    inicio_rt = None
    if rt_idx:
        inicio_rt = pd.Timestamp(min(k[0] for k in rt_idx.keys()))

    # Detectar navios de 2 praticos: aparecem 2x na planilha (mesmo dt+vessel)
    from collections import Counter
    ct = Counter((m['datetime'], m['vessel'].strip()) for m in manobras)
    dois_prat_set = {k for k, v in ct.items() if v >= 2}

    passadas_recentes = []
    futuras = []
    historico_dia = []
    ultima_esc = ''

    for m in manobras:
        dt = m['datetime']
        # Especiais participam normalmente do display (JA/SI/CH fazem manobras)
        # Apenas Δt e DL são calculados só para regulares (linhas abaixo protegidas)

        rt_info = rt_idx.get((dt, m['vessel'].strip()), {})
        m['status']   = rt_info.get('status', '')
        m['pra_real'] = rt_info.get('pratico', '')
        m['calado']   = rt_info.get('calado', '')
        m['bordo']    = rt_info.get('bordo', '')
        if not m['calado'] or not m['bordo']:      # manobra já fora da pauta atual: usa o histórico
            _hc, _hb = _CB_HIST.get((dt, m['vessel'].strip()), ('', ''))
            m['calado'] = m['calado'] or _hc
            m['bordo'] = m['bordo'] or _hb
        m['agente']   = rt_info.get('agente', '')
        m['obs']      = rt_info.get('obs', '')
        m['es']       = rt_info.get('es', '')
        m['dois_prat']= (dt, m['vessel'].strip()) in dois_prat_set
        # seq_rt: ordem da linha no SPPILOTS (desempate para mesmo horário)
        if 'seq_rt' in rt_info:
            m['seq_rt'] = rt_info['seq_rt']

        # Classificação
        if dt < now - timedelta(minutes=30):
            # HISTORICO: do inicio do dia anterior (07:30 ontem) ate a primeira da pauta atual
            #            ou ate "agora" (se nao tiver pauta carregada).
            if dt >= ini_hist and (inicio_rt is None or dt < inicio_rt):
                historico_dia.append(m)
            # PASSADAS: manobras da pauta atual ja executadas (>= inicio_rt)
            elif inicio_rt is not None and dt >= inicio_rt:
                passadas_recentes.append(m)
            # Mais antigo que isso, nao mostra
        elif dt <= now + timedelta(hours=36):
            futuras.append(m)

    # Pre-computar PRÓXIMA manobra de cada prático (so olhamos manobras a partir
    # de "agora" - 36h pra capturar o ciclo atual em andamento).
    # Pra cada manobra, "proxima" = primeira manobra POSTERIOR onde o mesmo
    # bigrama aparece. Usado pra mostrar quando o prático vai pegar a proxima.
    todas_ord = sorted(
        [m for m in manobras if str(m.get('pratico', '')).strip() and str(m['pratico']).strip() not in ESPECIAIS],
        key=lambda x: pd.Timestamp(x['datetime'])
    )
    # Agrupa indices por prático
    from collections import defaultdict
    idx_por_prat = defaultdict(list)
    for i, m in enumerate(todas_ord):
        p = str(m['pratico']).strip()
        # Em caso de 2 práticos, pode vir "AB/CD" - pega cada um
        for pi in p.split('/'):
            pi = pi.strip()
            if pi:
                idx_por_prat[pi].append(i)

    def parse_termino(termino_str, dt_inicio):
        """Converte 'HH:MM' (termino) em pd.Timestamp.
        Se termino for tipo '23:45', combina com a data do inicio.
        Se ja for um timestamp, retorna direto."""
        if not termino_str or termino_str in ('None', 'nan', ''):
            return None
        s = str(termino_str).strip()
        # Tenta extrair HH:MM
        import re
        mm = re.match(r'(\d{1,2}):(\d{2})', s)
        if not mm:
            return None
        h, m = int(mm.group(1)), int(mm.group(2))
        # Combina com data do inicio
        fim = dt_inicio.replace(hour=h, minute=m, second=0, microsecond=0)
        # Se passou da meia-noite, adiciona 1 dia
        if fim < dt_inicio:
            fim = fim + pd.Timedelta(days=1)
        return fim

    def contar_bigramas_ate_proximo(m):
        """Para uma manobra B do prático X, conta quantos bigramas (linhas da pauta)
        aconteceram entre essa B (exclusiva) e a proxima A do mesmo pratico (inclusiva).
        SO conta se a proxima manobra do pratico for A (ciclo B->A completo).
        Cada linha em todas_ord = 1 bigrama (pares ja vem em 2 linhas separadas).
        Retorna inteiro ou None."""
        if str(m.get('ab', '')).upper() != 'B':
            return None
        p = str(m.get('pratico', '')).strip()
        if not p or p in ESPECIAIS:
            return None
        # Acha indice da manobra na lista cronologica (todas_ord)
        idx_b = None
        for i, m2 in enumerate(todas_ord):
            if (m2.get('datetime') == m.get('datetime') and
                m2.get('vessel', '') == m.get('vessel', '') and
                str(m2.get('pratico', '')).strip() == p and
                str(m2.get('ab', '')).upper() == 'B'):
                idx_b = i
                break
        if idx_b is None:
            return None
        # Acha proxima manobra do mesmo pratico (indice posicional > idx_b)
        idx_prox = None
        proxima_ab = None
        praticos_dono = set(pi.strip() for pi in p.split('/') if pi.strip())
        for j in range(idx_b + 1, len(todas_ord)):
            mj = todas_ord[j]
            pj = str(mj.get('pratico', '')).strip()
            # Match se o pratico da linha for um dos donos da B (caso par)
            if any(pi in praticos_dono for pi in pj.split('/')):
                idx_prox = j
                proxima_ab = str(mj.get('ab', '')).upper()
                break
        if idx_prox is None:
            return None
        # So conta se a proxima for A (ciclo B->A completo)
        if 'A' not in proxima_ab:
            return None
        # Conta bigramas (linhas da pauta) entre B (exclusivo) e próximo A (inclusivo)
        return idx_prox - idx_b

    def buscar_proxima(m):
        """Dada uma manobra B, calcula DELTA de tempo do FIM da manobra B
        ate o INICIO da proxima manobra do mesmo pratico.
        SO MOSTRA pra B (quem completou ciclo e voltou pra fila).
        Retorna tupla (str_formatada, minutos_int_ou_None)."""
        if str(m.get('ab', '')).upper() != 'B':
            return ('', None)
        p = str(m.get('pratico', '')).strip()
        if not p or p in ESPECIAIS:
            return ('', None)
        dt = pd.Timestamp(m['datetime'])
        # Calcula FIM da manobra B (inicio + termino)
        fim_b = None
        # Sempre usa Tm tabelado: fim_B = dt_ini_B + gT(de, para)
        try:
            if _ep_algo_ok and _T_min:
                _tm = _gT_m(m.get('de', ''), m.get('para', ''), dt)
                fim_b = dt + pd.Timedelta(minutes=_tm)
        except Exception:
            pass
        if fim_b is None:
            fim_b = dt  # último recurso se gT falhar
        vessel = m.get('vessel', '')
        proxima_dt = None
        # Para cada bigrama (lida com "AB/CD" de 2 práticos)
        for pi in p.split('/'):
            pi = pi.strip()
            if not pi:
                continue
            for i in idx_por_prat.get(pi, []):
                m2 = todas_ord[i]
                dt2 = pd.Timestamp(m2['datetime'])
                # Mesma manobra? pula
                if dt2 == dt and m2.get('vessel', '') == vessel:
                    continue
                if dt2 > dt:
                    if proxima_dt is None or dt2 < proxima_dt:
                        proxima_dt = dt2
                    break
        if proxima_dt is None:
            return ('', None)

        # Calcular delta a partir do FIM da B
        delta = proxima_dt - fim_b
        total_min = int(delta.total_seconds() // 60)
        if total_min < 0:
            return ('', None)
        # Acima de 24h, mostra so '>24h' (descanso muito longo)
        if total_min > 24 * 60:
            return ('>24h', total_min)
        if total_min < 60:
            return (f'{total_min}min', total_min)
        horas = total_min // 60
        mins = total_min % 60
        s = f'{horas}h{mins:02d}' if mins else f'{horas}h'
        return (s, total_min)

    # Escala efetiva por dia operacional (07:30→07:29), da simulação ao vivo
    _esc_dia = {}
    try:
        import pickle as _pk
        for _t in _pk.load(open(_DIR / 'motor_e2d' / '_turnos_live.pkl', 'rb')):
            _esc_dia[(_t['dt_ini'] - pd.Timedelta(hours=7, minutes=30)).date()] = set(_t['dia1'])
            _esc_dia[(_t['dt_d2'] - pd.Timedelta(hours=7, minutes=30)).date()] = set(_t['dia2'])
    except Exception as _e:
        print(f'[DL] escala por dia indisponível ({_e}); usando só o limite de 48 h')

    def _saiu_do_servico(p, t0, t1):
        """True se em algum dia operacional entre t0 e t1 o prático não estava escalado."""
        if not _esc_dia:
            return False
        d = (pd.Timestamp(t0) - pd.Timedelta(hours=7, minutes=30)).date()
        d1 = (pd.Timestamp(t1) - pd.Timedelta(hours=7, minutes=30)).date()
        while d <= d1:
            if d in _esc_dia and p not in _esc_dia[d]:
                return True
            d += __import__('datetime').timedelta(days=1)
        return False

    def _lancha_atalaia(berco_fim):
        """Lancha do fim da B até a Atalaia (min)."""
        try:
            from ep_algoritmo import gL as _gL, ATALAIA as _AT
        except Exception:
            _gL, _AT = None, 12
        b = str(berco_fim).strip()
        if b == 'FB' or _gL is None:
            return _AT
        return max(_gL('FB', b) - _AT, 0)

    def dl_antes_da_a(m):
        """DL mostrado na linha da A: tempo do FIM da B anterior do mesmo prático
        (início da B + T de tabela + lancha até a Atalaia) até o INÍCIO desta A. Se a manobra anterior
        foi em outro turno (mais de 48 h antes), fica em branco."""
        if 'A' not in str(m.get('ab', '')).upper():
            return ''
        p = str(m.get('pratico', '')).strip()
        if not p or p in ESPECIAIS:
            return ''
        dt = pd.Timestamp(m['datetime'])
        vessel = m.get('vessel', '')
        saidas = []
        for pi in [x.strip() for x in p.split('/') if x.strip()]:
            ant = None
            for i in idx_por_prat.get(pi, []):
                m2 = todas_ord[i]
                dt2 = pd.Timestamp(m2['datetime'])
                if dt2 == dt and m2.get('vessel', '') == vessel:
                    continue
                if dt2 < dt:
                    ant = m2
                else:
                    break
            if ant is None:
                saidas.append(''); continue
            fim_ant = pd.Timestamp(ant['datetime'])
            try:
                if _ep_algo_ok and _T_min:
                    fim_ant = fim_ant + pd.Timedelta(minutes=_gT_m(ant.get('de', ''), ant.get('para', ''), ant['datetime']))
                # + lancha até a Atalaia: saída (termina em FB) = 12 min;
                #   entrada/mudança (termina no berço) = lancha FB→berço − 12 min
                fim_ant = fim_ant + pd.Timedelta(minutes=_lancha_atalaia(str(ant.get('para', ''))))
            except Exception:
                pass
            tot = int((dt - fim_ant).total_seconds() // 60)
            if _saiu_do_servico(pi, fim_ant, dt) or tot > 48 * 60:
                saidas.append(''); continue   # entre a B e a A ele saiu do serviço (folga): sem DL
            if tot < 0 or 'B' not in str(ant.get('ab', '')).upper():
                saidas.append(''); continue
            tot = int(10 * round(tot / 10))   # arredonda para os 10 min mais próximos
            h_, mn_ = divmod(tot, 60)
            saidas.append(f'{h_}h{mn_:02d}' if h_ and mn_ else (f'{h_}h' if h_ else f'{mn_}min'))
        return '/'.join(x for x in saidas if x) if any(saidas) else ''

    def dt_inicios(m):
        """Δt mostrado em cada linha (A e B): do INÍCIO da manobra anterior do mesmo prático
        até o INÍCIO desta (A→B na linha da B; B→A na linha da A). Em branco se a anterior
        foi em outro turno (folga no meio ou mais de 48 h)."""
        p = str(m.get('pratico', '')).strip()
        if not p or p in ESPECIAIS:
            return ''
        dt = pd.Timestamp(m['datetime'])
        vessel = m.get('vessel', '')
        saidas = []
        for pi in [x.strip() for x in p.split('/') if x.strip()]:
            if pi in ESPECIAIS:
                saidas.append(''); continue
            ant = None
            for i in idx_por_prat.get(pi, []):
                m2 = todas_ord[i]
                dt2 = pd.Timestamp(m2['datetime'])
                if dt2 == dt and m2.get('vessel', '') == vessel:
                    continue
                if dt2 < dt:
                    ant = m2
                else:
                    break
            # manobra cancelada depois da escalação conta como a anterior (o descanso vai até o horário dela)
            _ca = [t for t in _CANC_INI.get(pi, []) if t < dt]
            if _ca and (ant is None or max(_ca) > pd.Timestamp(ant['datetime'])):
                ant = {'datetime': max(_ca)}
            if ant is None:
                saidas.append(''); continue
            ini_ant = pd.Timestamp(ant['datetime'])
            tot = int((dt - ini_ant).total_seconds() // 60)
            if tot <= 0 or tot > 48 * 60 or _saiu_do_servico(pi, ini_ant, dt):
                saidas.append(''); continue
            h_, mn_ = divmod(tot, 60)
            saidas.append(f'{h_}h{mn_:02d}' if h_ else f'{mn_}min')
        return '/'.join(x for x in saidas if x) if any(saidas) else ''

    # Δt da própria linha verde (cancelada): do início da anterior do prático até o horário da cancelada
    _CANC_DT.clear()
    for (_cd, _cv), _cl in _CANC_LIN.items():
        _CANC_DT[(_cd, _cv)] = '/'.join(x for x in (dt_inicios({'pratico': p_, 'datetime': _cd, 'vessel': _cv}) for p_, _ in _cl) if x)

    # Aplica PROX em TODAS as listas — para qualquer manobra B,
    # mostra o tempo ate a proxima manobra do mesmo pratico.
    #
    # Coleta de minutos para Δt MEDIO:
    # - Dia anterior INTEIRO (07:30 ontem -> 07:30 hoje): todas as B's com delta valido
    # - Dia atual: SO as B's encerradas (cujo proximo A do mesmo pratico ja aconteceu
    #   antes de "agora") - garante que o descanso ja se concretizou
    if now.hour > 7 or (now.hour == 7 and now.minute >= 30):
        _ini_op = pd.Timestamp(now.replace(hour=7, minute=30, second=0, microsecond=0))
    else:
        _ini_op = pd.Timestamp(now.replace(hour=7, minute=30, second=0, microsecond=0) - timedelta(days=1))
    _fim_op = _ini_op + timedelta(days=1)
    _ini_ant = _ini_op - timedelta(days=1)  # 07:30 dia anterior
    _now_ts  = pd.Timestamp(now)

    # Δt e POSICOES usam o MESMO escopo de B's (consistencia entre as duas):
    # - B a partir de 07:30 do dia anterior (>= _ini_ant)
    # - A proxima manobra do mesmo pratico ja aconteceu (encerrou)
    # - A proxima manobra do pratico e A (ciclo B->A completo - garantido pela
    #   funcao contar_bigramas_ate_proximo que so retorna nesse caso)
    deltas_min_dia = []
    posicoes_apos_b = []
    _DL_TEMPOS.clear()
    _processadas = set()  # evita duplicar mesma manobra entre listas

    # Constroi set de (pratico, dia_operacional) onde o pratico tem manobras.
    # Usado pra detectar folgas: se entre B e A o pratico nao aparece em algum
    # dia, foi folgar.
    def _dia_op_for_set(dt):
        if dt.hour < 7 or (dt.hour == 7 and dt.minute < 30):
            return (dt - timedelta(days=1)).date()
        return dt.date()
    _ativos_dia_op = set()
    for m_loop in todas_ord:
        try:
            dt_loop = pd.Timestamp(m_loop['datetime'])
        except Exception:
            continue
        p_loop = str(m_loop.get('pratico', '')).strip()
        if not p_loop:
            continue
        for pi in p_loop.split('/'):
            pi = pi.strip()
            if pi:
                _ativos_dia_op.add((pi, _dia_op_for_set(dt_loop)))

    # Limpa log de posicoes (recria do zero a cada execucao)
    try:
        with open(_DIR / 'log_posicoes.txt', 'w', encoding='utf-8') as f:
            f.write(f'=== Log gerado em {now} ===\n')
    except Exception:
        pass
    # Para o Δt médio: B dos últimos 7 dias (média estável, sem depender do movimento de um só dia),
    # contando só ciclos B→A dentro do MESMO turno (D1+D2). Manobras extras não são exibidas.
    _ids_vis = {id(x) for x in passadas_recentes + futuras + historico_dia}
    _extra_dl = [x for x in manobras if id(x) not in _ids_vis
                 and _ini_ant - timedelta(days=6) <= pd.Timestamp(x['datetime']) < _ini_ant]
    for lista in (passadas_recentes, futuras, historico_dia, _extra_dl):
        for m in lista:
            s, mins = buscar_proxima(m)
            # DL na linha da A (descanso desde a B anterior); em branco nas não confirmadas (brancas)
            # (também em branco se a manobra é futura e não foi achada na pauta: a pauta pode ter
            #  mudado entre a simulação e o painel, e ela aparece branca)
            _st = str(m.get('status', '')).upper()
            _fut_sem_rt = (_st == '' and pd.Timestamp(m['datetime']) > now)
            # manobra que já passou conta como feita, mesmo que a pauta lida ainda a mostre como futura
            _ja_passou = pd.Timestamp(m['datetime']) <= now
            m['proxima'] = '' if ((_st == 'FUTURO' and not _ja_passou) or _fut_sem_rt) else dt_inicios(m)
            try:
                dt_m = pd.Timestamp(m['datetime'])
            except Exception:
                continue

            # Filtro 1: B dos últimos 7 dias
            if dt_m < _ini_ant - timedelta(days=6):
                continue
            # Filtro 2: tem que ter proxima manobra do mesmo pratico
            if mins is None:
                continue
            # Filtro 3: a proxima manobra ja encerrou (inicio_proximo <= now)
            fim_b = None
            try:
                if _ep_algo_ok and _T_min:
                    _tm2 = _gT_m(m.get('de', ''), m.get('para', ''), dt_m)
                    fim_b = dt_m + pd.Timedelta(minutes=_tm2)
            except Exception:
                pass
            if fim_b is None:
                fim_b = dt_m
            inicio_proximo = fim_b + timedelta(minutes=mins)
            if inicio_proximo > _now_ts:
                continue

            # Calcula posicoes (so retorna se proxima for A)
            pos = contar_bigramas_ate_proximo(m)
            if pos is None:
                # Proxima nao e A (B->B), nao entra em NENHUMA das metricas
                continue

            # Dedup: evita processar mesma manobra de listas diferentes
            chave = (dt_m, m.get('vessel', ''), str(m.get('pratico', '')).strip())
            if chave in _processadas:
                continue

            # Mesmo turno: a B e a A seguinte têm de estar no mesmo turno (D1+D2). Ciclos que atravessam
            # a troca de turno (folga, ou prático que emenda outro turno por troca) não entram.
            def _turno(t):
                d = (pd.Timestamp(t) - pd.Timedelta(hours=7, minutes=30)).date()
                return d if (d - __import__('datetime').date(2026, 1, 1)).days % 2 == 0 else d - timedelta(days=1)
            if _turno(dt_m) != _turno(inicio_proximo):
                continue

            _processadas.add(chave)

            # Coleta as duas metricas (mesmo conjunto de B's)
            posicoes_apos_b.append(pos)
            deltas_min_dia.append(mins - _lancha_atalaia_mod(m.get('para', '')))   # DL efetivo (com lancha)
            _DL_TEMPOS.append(dt_m)

            # Log
            try:
                p_log = str(m.get('pratico', '')).strip()
                v_log = str(m.get('vessel', ''))[:25]
                with open(_DIR / 'log_posicoes.txt', 'a', encoding='utf-8') as f:
                    h = mins // 60
                    mn = mins % 60
                    dt_str = f'{h}h{mn:02d}' if h else f'{mn}min'
                    f.write(f'{dt_m} {p_log:7s} {v_log:25s} pos={pos:3d}  Δt={dt_str}\n')
            except Exception:
                pass

    # FILA ATUAL (painel lateral): escalação depois da ÚLTIMA MANOBRA CONFIRMADA
    # (não branca). A coluna Escalação de cada linha é a fila logo após aquela manobra;
    # os disponíveis são os próximos para as manobras brancas que vêm depois.
    def _confirmada(m):
        st = str(m.get('status', '')).upper()
        if st == 'FUTURO':
            return False
        if st == '':
            return pd.Timestamp(m['datetime']) <= now   # sem pauta: só conta se já passou
        return True
    # Manobras NÃO confirmadas cujo horário previsto é inviável: o prático escalado pela
    # simulação só fica livre depois (horários previstos encadeados, ainda não atualizados).
    try:
        from ep_algoritmo import gL as _gL3, r15 as _r15b
        _mg_e = int(os.environ.get('MARGEM_ENTRADA', '45')); _mg_o = int(os.environ.get('MARGEM_OUTRAS', '25'))
        for m in manobras:
            if _confirmada(m):
                continue
            dt_m = pd.Timestamp(m['datetime'])
            p = str(m.get('pratico', '')).strip()
            if not p or p in ESPECIAIS:
                continue
            ant = None
            for i in idx_por_prat.get(p, []):
                m2 = todas_ord[i]
                if pd.Timestamp(m2['datetime']) < dt_m:
                    ant = m2
                else:
                    break
            if ant is None or _saiu_do_servico(p, pd.Timestamp(ant['datetime']), dt_m):
                continue
            fr = str(m.get('de', '')).strip()
            _T = _gT_m(ant.get('de', ''), ant.get('para', ''), ant['datetime']) if _T_min else 60
            livre = pd.Timestamp(_r15b(pd.Timestamp(ant['datetime']).to_pydatetime() + timedelta(
                minutes=_T + (_mg_e if fr == 'FB' else _mg_o) + _gL3(str(ant.get('para', '')).strip(), fr))))
            if livre > dt_m:
                m['inviavel'] = livre
    except Exception as _e:
        print(f'[Inviáveis] não calculado: {_e}')

    _ja = [m for m in manobras if _confirmada(m) and m.get('escalacao')]
    if _ja:
        _ult = max(_ja, key=lambda x: (pd.Timestamp(x['datetime']), int(x.get('seq') or 0)))
        ultima_esc = {'esc': _ult['escalacao'], 'dt': pd.Timestamp(_ult['datetime'])}
        # hora prevista da próxima manobra não confirmada: a disponibilidade é avaliada nela
        _prox = sorted([m for m in manobras
                        if not _confirmada(m) and pd.Timestamp(m['datetime']) >= ultima_esc['dt']],
                       key=lambda x: pd.Timestamp(x['datetime']))
        ultima_esc['t_prox'] = pd.Timestamp(_prox[0]['datetime']) if _prox else None
        # Disponibilidade de cada prático ocupado PARA a próxima manobra (mesma conta do motor:
        # r15(início da última + T + margem + lancha até a origem da próxima); margem 45 se a
        # próxima sai de FB, senão 25). O HH:MM da coluna Escalação vale para a manobra da linha.
        ultima_esc['avail'] = {}
        if _prox:
            try:
                from ep_algoritmo import gL as _gL2, r15 as _r15
                _nfr = str(_prox[0].get('de', '')).strip()
                _marg = int(os.environ.get('MARGEM_ENTRADA', '45')) if _nfr == 'FB' else int(os.environ.get('MARGEM_OUTRAS', '25'))
                _ult_p = {}
                _kref = (ultima_esc['dt'], int(_ult.get('seq') or 0))
                for m in manobras:
                    # última manobra de cada prático até a manobra de referência (na ordem da simulação,
                    # que é a mesma da coluna Escalação), confirmada ou não
                    if (pd.Timestamp(m['datetime']), int(m.get('seq') or 0)) > _kref:
                        continue
                    for pi in str(m.get('pratico', '')).split('/'):
                        pi = pi.strip()
                        if pi:
                            _ult_p[pi] = m
                # origem da próxima saída/mudança não confirmada (para a disponibilidade "S")
                _sfr = next((str(m.get('de', '')).strip() for m in _prox if str(m.get('de', '')).strip() != 'FB'), None)
                _mE = int(os.environ.get('MARGEM_ENTRADA', '45')); _mS = int(os.environ.get('MARGEM_OUTRAS', '25'))
                ultima_esc['avail_E'] = {}; ultima_esc['avail_S'] = {}
                ultima_esc['tipo_prox'] = 'E' if _nfr == 'FB' else 'S'
                for pi, m in _ult_p.items():
                    _T = _gT_m(m.get('de', ''), m.get('para', ''), m['datetime']) if _T_min else 60
                    _ini = pd.Timestamp(m['datetime']).to_pydatetime(); _to = str(m.get('para', '')).strip()
                    ultima_esc['avail'][pi] = pd.Timestamp(_r15(_ini + timedelta(minutes=_T + _marg + _gL2(_to, _nfr))))
                    ultima_esc['avail_E'][pi] = pd.Timestamp(_r15(_ini + timedelta(minutes=_T + _mE + _gL2(_to, 'FB'))))
                    ultima_esc['avail_S'][pi] = pd.Timestamp(_r15(_ini + timedelta(minutes=_T + _mS + _gL2(_to, _sfr or _to))))
            except Exception as _e:
                print(f'[Lateral] disponibilidade não calculada: {_e}')

    return passadas_recentes, futuras, historico_dia, ultima_esc, deltas_min_dia, posicoes_apos_b


# ── Gerar painel HTML ─────────────────────────────────────────────────────────
# Cores do SPPILOTS
COR_STATUS = {   # cores da pauta do SPPilots (medidas nos prints)
    'EXECUTADO':  '#ff4a4a',
    'AGENDADO':   '#ff4a4a',
    'PROXIMO':    '#33ccff',
    'BREVE':      '#b7b7ff',
    'FUTURO':     '#ffffff',
    'CONFIRMADO': '#33ccff',
    'ESPECIAL':   '#ff0099',
    'VIRADA':     '#66cc66',
}
COR_TEXT = {
    'EXECUTADO': '#fff', 'AGENDADO': '#fff', 'PROXIMO': '#000',
    'BREVE': '#000', 'FUTURO': '#000', 'CONFIRMADO': '#000',
    'ESPECIAL': '#fff', 'VIRADA': '#fff',
}


def _dt_html(cal, ab, abp=None):
    """Coluna Δt: o Δt da manobra A é o descanso longo -> negrito amarelo com contorno preto (pedido do Rodrigo, 29/10/2026).
    Navio de 2 práticos ('ON 3h00 / BR 1h30' com A/B 'A/B'): destaca só a parte de quem está em A.
    abp = {prático: 'A'/'B'}: cada parte começa pelo bigrama, então vale mesmo quando o Δt de um deles está em branco
    e só sobra uma parte (correção de 31/10/2026)."""
    import html as _h
    cal = str(cal or ''); ab = str(ab or '').upper()
    partes = cal.split(' / '); abs_ = [x.strip() for x in ab.split('/')]
    if abp and cal.strip() and all(t.strip().split(' ')[0] in abp for t in partes):
        return ' / '.join(f'<b class="dl-a">{_h.escape(t)}</b>' if str(abp.get(t.strip().split(' ')[0], '')).upper() == 'A'
                          else _h.escape(t) for t in partes)
    if len(partes) == len(abs_) and len(partes) > 1:
        return ' / '.join(f'<b class="dl-a">{_h.escape(t)}</b>' if a == 'A' and t.strip() else _h.escape(t)
                          for t, a in zip(partes, abs_))
    if cal.strip() and abs_ and all(a == 'A' for a in abs_):
        return f'<b class="dl-a">{_h.escape(cal)}</b>'
    return _h.escape(cal)


def gerar_painel(passadas, futuras, historico, ultima_esc, estado_info, deltas_min_dia=None, posicoes_apos_b=None):
    if deltas_min_dia is None:
        deltas_min_dia = []
    if posicoes_apos_b is None:
        posicoes_apos_b = []
    now = datetime.now()
    now_str = now.strftime('%d/%m/%Y %H:%M')
    gen_hora = now.strftime('%H:%M'); gen_data = now.strftime('%d/%m')
    gen_iso = now.strftime('%Y-%m-%dT%H:%M:%S') + '-03:00'   # horário de Brasília
    try:
        _pm = datetime.fromtimestamp(PAUTA_RT.stat().st_mtime)
        pauta_str = _pm.strftime('%H:%M') + ('' if _pm.date() == now.date() else _pm.strftime(' de %d/%m'))
    except Exception:
        pauta_str = '—'
    ult_hist = estado_info.get('ultimo_dt', '—')
    mc       = estado_info.get('mc', 0)

    # T_min e T_mud carregados no nível do módulo (_T_min, _T_mud)

    # Contagem de BIGRAMAS por dia operacional (07:30 -> 07:30):
    #   Ontem  = de 07:30 ontem ate 07:30 hoje
    #   Hoje   = de 07:30 hoje ate 07:30 amanha
    # Combina pauta_rt.csv (futuras + atuais) com historico_2026.csv (passadas)
    # para cobrir tanto "hoje" quanto "ontem".
    # Cada bigrama conta 1; pares (dois_prat=true) contam como 2.
    if now.hour > 7 or (now.hour == 7 and now.minute >= 30):
        ini_hoje = pd.Timestamp(now.replace(hour=7, minute=30, second=0, microsecond=0))
    else:
        ini_hoje = pd.Timestamp(now.replace(hour=7, minute=30, second=0, microsecond=0) - timedelta(days=1))
    fim_hoje  = ini_hoje + timedelta(days=1)
    ini_ontem = ini_hoje - timedelta(days=1)
    fim_ontem = ini_hoje

    def _carregar_pauta_combinada():
        """Le pauta_rt + historico_2026 e retorna DataFrame combinado, deduplicado.
        Pares (mesmo datetime + Vessel em 2 linhas) sao detectados e marcados
        com dois_prat='true' antes de deduplicar.
        Deduplicacao usa o timestamp parseado (dt) e Vessel normalizado, evitando
        duplicacao entre fontes que escrevem datetime em formatos diferentes."""
        dfs = []
        # pauta_rt (atual + futuro) - ja vem com dois_prat correto
        if PAUTA_RT.exists():
            try:
                d = _sem_canceladas(pd.read_csv(PAUTA_RT))
                d['dt'] = pd.to_datetime(d['datetime'])
                if 'dois_prat' not in d.columns:
                    d['dois_prat'] = 'false'
                if 'Status' not in d.columns:
                    d['Status'] = 'AGENDADO'
                d['Vessel'] = d['Vessel'].astype(str).str.strip().str.upper()
                dfs.append(d[['dt', 'Vessel', 'dois_prat', 'Status']])
            except Exception:
                pass
        # historico (passado) - detectar pares por duplicacao de (dt, Vessel)
        if HIST_PATH.exists():
            try:
                d = pd.read_csv(HIST_PATH)
                d['dt'] = pd.to_datetime(d['datetime'])
                d['Vessel'] = d['Vessel'].astype(str).str.strip().str.upper()
                # Detecta pares: se (dt, Vessel) aparece >= 2 vezes, e par
                contagem = d.groupby(['dt', 'Vessel']).size()
                pares_keys = set(contagem[contagem >= 2].index)
                d['dois_prat'] = d.apply(
                    lambda r: 'true' if (r['dt'], r['Vessel']) in pares_keys else 'false',
                    axis=1
                )
                d['Status'] = 'AGENDADO'  # historico = ja realizado, sempre conta
                dfs.append(d[['dt', 'Vessel', 'dois_prat', 'Status']])
            except Exception:
                pass
        if not dfs:
            return None
        out = pd.concat(dfs, ignore_index=True)
        # Dedup pelo TIMESTAMP (dt) + Vessel normalizado, nao pela string original.
        # Pauta_rt vem antes na lista, entao tem prioridade (keep='first').
        out = out.drop_duplicates(subset=['dt', 'Vessel'], keep='first')
        return out

    def _contar_bigramas(df_pauta, ini, fim):
        """Conta bigramas no intervalo [ini, fim). Par conta 2.
        Exclui Status='FUTURO' (estimadas) e 'ESPECIAL' (marcacao administrativa).
        df_pauta ja deve estar deduplicado por (datetime, Vessel) com flag dois_prat."""
        if df_pauta is None or len(df_pauta) == 0:
            return 0
        sub = df_pauta[(df_pauta['dt'] >= ini) & (df_pauta['dt'] < fim) &
                       (~df_pauta['Status'].isin(['FUTURO', 'ESPECIAL']))]
        if len(sub) == 0:
            return 0
        n = 0
        for _, r in sub.iterrows():
            n += 2 if str(r.get('dois_prat', '')).lower() == 'true' else 1
        return n

    n_ontem = 0
    n_hoje  = 0
    media_ano = 0.0
    n_pares_hoje = 0
    try:
        df_combo = _carregar_pauta_combinada()
        n_ontem = _contar_bigramas(df_combo, ini_ontem, fim_ontem)
        n_hoje  = _contar_bigramas(df_combo, ini_hoje,  fim_hoje)

        # Media do ano: total de bigramas desde 01/jan ate inicio do dia operacional
        # de hoje, dividido pelo numero de dias operacionais ja completados.
        # (nao inclui hoje, que ainda esta em andamento)
        ini_ano = pd.Timestamp(now.year, 1, 1, 7, 30)
        n_total_ano = _contar_bigramas(df_combo, ini_ano, ini_hoje)
        # Numero de dias operacionais ja completos: do 01/jan ate ontem
        n_dias = max(1, (ini_hoje - ini_ano).days)
        media_ano = n_total_ano / n_dias

        # Numero de navios de 2 praticos (pares) HOJE
        if df_combo is not None:
            sub_hoje = df_combo[(df_combo['dt'] >= ini_hoje) &
                                (df_combo['dt'] < fim_hoje) &
                                (~df_combo['Status'].isin(['FUTURO', 'ESPECIAL']))]
            n_pares_hoje = sum(1 for _, r in sub_hoje.iterrows()
                               if str(r.get('dois_prat', '')).lower() == 'true')
    except Exception:
        pass

    # Descanso medio (Δt medio): media dos descansos das manobras B do dia.
    # Filtra so deltas dentro do dia operacional atual e <=24h.
    delta_medio_str = '—'
    if deltas_min_dia:
        media_min = sum(deltas_min_dia) / len(deltas_min_dia)
        h = int(media_min // 60)
        m = int(media_min % 60)
        delta_medio_str = f'{h}h{m:02d}' if h else f'{m}min'

    # Posicoes medias apos B: quantos bigramas em media passam entre uma B
    # e o proximo A do mesmo pratico (mesmo escopo do delta_t).
    pos_media_str = '—'
    if posicoes_apos_b:
        pos_media = sum(posicoes_apos_b) / len(posicoes_apos_b)
        pos_media_str = f'{pos_media:.1f}'

    # ── LOG SEMANAL ─────────────────────────────────────────────────────────
    # Mantem CSV com Δt medio + Pos. media de cada semana fechada
    # (semana = 7 dias a partir de 01/jan/2026 07:30).
    # Semana atual e calculada ao vivo (com os dados do escopo atual).
    INICIO_ANO_SEM = pd.Timestamp(2026, 1, 1, 7, 30)
    LOG_SEM_PATH = _DIR / 'log_semanal_efetivo.csv'   # recalculado com o DL efetivo (fim da B + T + lancha)

    def _num_semana(ts):
        if ts < INICIO_ANO_SEM:
            return 0
        return int((ts - INICIO_ANO_SEM).total_seconds() / (7 * 24 * 3600)) + 1

    def _periodo_semana(sem):
        ini = INICIO_ANO_SEM + timedelta(days=(sem - 1) * 7)
        fim = ini + timedelta(days=7) - timedelta(minutes=1)
        return ini, fim

    def _fmt_delta_min(min_total):
        h = int(min_total // 60)
        m = int(min_total % 60)
        return f'{h}h{m:02d}' if h else f'{m}min'

    sem_atual = _num_semana(pd.Timestamp(now))

    # Carrega log existente
    log_semanal = []
    if LOG_SEM_PATH.exists():
        try:
            log_df = pd.read_csv(LOG_SEM_PATH)
            log_semanal = log_df.to_dict('records')
        except Exception:
            log_semanal = []

    # Identifica TODAS as semanas faltantes (de 1 até a anterior à atual).
    # Tambem inclui semanas existentes que NAO tem n_manobras (esquema antigo)
    # pra forçar recálculo com a nova coluna.
    sem_anterior = sem_atual - 1
    semanas_no_log = {int(r['semana']) for r in log_semanal
                      if pd.notna(r.get('n_manobras'))}
    semanas_faltantes = [s for s in range(1, sem_anterior + 1) if s not in semanas_no_log]
    # Remove do log as semanas sem n_manobras (vão ser recalculadas)
    log_semanal = [r for r in log_semanal
                   if int(r['semana']) in semanas_no_log
                   or int(r['semana']) > sem_anterior]

    if semanas_faltantes:
        # Le a planilha simulada uma unica vez e calcula todas de uma vez
        try:
            plan = XLSX_OUT
            if plan.exists():
                print(f'[Log semanal] Calculando {len(semanas_faltantes)} semana(s) faltante(s)...')
                df_p = pd.read_excel(plan, sheet_name=f'E2D {now.year}', header=1)
                df_p['dt'] = pd.to_datetime(df_p['Data'].astype(str) + ' ' + df_p['Hora'].astype(str),
                                             format='%d/%m/%Y %H:%M', errors='coerce')
                df_p = df_p[df_p['dt'].notna()].reset_index(drop=True)
                df_p['Status'] = df_p['Status'].astype(str).str.upper().str.strip()
                df_p['Pratico'] = df_p['Pratico'].astype(str).str.strip()

                # Calcula dia operacional (07:30 -> 07:29 do dia seguinte)
                def _dia_op(dt):
                    if dt.hour < 7 or (dt.hour == 7 and dt.minute < 30):
                        return (dt - timedelta(days=1)).date()
                    return dt.date()
                df_p['dia_op'] = df_p['dt'].apply(_dia_op)

                # Indexa por pratico uma vez
                prat_idx_p = {}
                for i, p in enumerate(df_p['Pratico']):
                    prat_idx_p.setdefault(p, []).append(i)

                # Conjunto (pratico, dia_op) onde o pratico esta ativo
                ativo_dia = set()
                for _, row in df_p.iterrows():
                    p = row['Pratico']
                    if p and p != 'nan':
                        ativo_dia.add((p, row['dia_op']))

                ESP = {'JA', 'SI', 'CH'}

                # Pre-calcula numero da semana de cada manobra
                df_p['_sem'] = ((df_p['dt'] - INICIO_ANO_SEM).dt.total_seconds()
                                / (7 * 24 * 3600)).astype(int) + 1

                # Conta total de bigramas (linhas) por semana (excluindo nada -
                # a planilha simulada nao tem FUTURO/ESPECIAL, sao todas reais)
                manobras_por_sem = df_p.groupby('_sem').size().to_dict()

                # Acumula casos por semana
                buckets = {s: ([], []) for s in semanas_faltantes}  # sem -> (deltas, pos)
                semanas_set = set(semanas_faltantes)
                for i, row in df_p.iterrows():
                    if row['Status'] != 'B':
                        continue
                    sem_i = int(row['_sem'])
                    if sem_i not in semanas_set:
                        continue
                    p = row['Pratico']
                    if not p or p in ESP or p == 'nan':
                        continue
                    prox = None
                    for j in prat_idx_p.get(p, []):
                        if j > i:
                            prox = j
                            break
                    if prox is None:
                        continue
                    prox_row = df_p.iloc[prox]
                    if prox_row['Status'] != 'A':
                        continue

                    # Filtro folga: prático tem que estar ATIVO em todos os dias
                    # operacionais entre o B e o A. Se houver dia sem manobra
                    # dele, foi pra folga - nao conta.
                    dia_b = row['dia_op']
                    dia_a = prox_row['dia_op']
                    if dia_a > dia_b:
                        d = dia_b + timedelta(days=1)
                        teve_folga = False
                        while d < dia_a:
                            if (p, d) not in ativo_dia:
                                teve_folga = True
                                break
                            d += timedelta(days=1)
                        if teve_folga:
                            continue

                    dm = int((prox_row['dt'] - _fim_b_efetivo(row['dt'], row['De'], row['Para'])).total_seconds() / 60)   # DL efetivo
                    if dm < 0:
                        continue
                    buckets[sem_i][0].append(dm)
                    buckets[sem_i][1].append(prox - i)

                fechadas = 0
                for s in semanas_faltantes:
                    deltas_s, pos_s = buckets[s]
                    if not deltas_s:
                        continue
                    n = len(deltas_s)
                    md = sum(deltas_s) / n
                    mp = sum(pos_s) / n
                    ini_s, fim_s = _periodo_semana(s)
                    n_manobras_sem = int(manobras_por_sem.get(s, 0))
                    log_semanal.append({
                        'semana': s,
                        'periodo_ini': ini_s.strftime('%d/%m/%Y %H:%M'),
                        'periodo_fim': fim_s.strftime('%d/%m/%Y %H:%M'),
                        'n_casos': n,
                        'n_manobras': n_manobras_sem,
                        'delta_min': round(md, 1),
                        'delta_str': _fmt_delta_min(md),
                        'pos_media': round(mp, 1),
                    })
                    fechadas += 1

                if fechadas:
                    pd.DataFrame(log_semanal).sort_values('semana').to_csv(
                        LOG_SEM_PATH, index=False, encoding='utf-8')
                    print(f'[Log semanal] {fechadas} semana(s) gravada(s) em {LOG_SEM_PATH.name}')
            else:
                print(f'[Log semanal] AVISO: planilha {plan} nao encontrada')
        except Exception as e:
            print(f'[Log semanal] AVISO: erro ao calcular semanas faltantes: {e}')

    # Recarrega log final + adiciona semana atual (parcial, ao vivo)
    log_semanal_view = sorted(log_semanal, key=lambda r: int(r['semana']))
    # Semana atual: usa deltas_min_dia + posicoes_apos_b ja calculados (escopo atual)
    ini_a, fim_a = _periodo_semana(sem_atual)
    _sel = [i for i, t in enumerate(_DL_TEMPOS) if t >= ini_a] if len(_DL_TEMPOS) == len(deltas_min_dia) else list(range(len(deltas_min_dia)))
    if _sel and posicoes_apos_b:
        n_a = len(_sel)
        md_a = sum(deltas_min_dia[i] for i in _sel) / n_a
        mp_a = sum(posicoes_apos_b[i] for i in _sel) / n_a
        # Total de manobras da semana atual (ate agora) - usa pauta combinada
        n_manobras_sem_atual = 0
        try:
            df_combo_sem = _carregar_pauta_combinada()
            if df_combo_sem is not None:
                n_manobras_sem_atual = _contar_bigramas(df_combo_sem, ini_a, pd.Timestamp(now))
        except Exception:
            pass
        log_semanal_view.append({
            'semana': sem_atual,
            'periodo_ini': ini_a.strftime('%d/%m/%Y %H:%M'),
            'periodo_fim': fim_a.strftime('%d/%m/%Y %H:%M'),
            'n_casos': n_a,
            'n_manobras': n_manobras_sem_atual,
            'delta_min': round(md_a, 1),
            'delta_str': _fmt_delta_min(md_a),
            'pos_media': round(mp_a, 1),
            'parcial': True,
        })

    # Renderiza HTML da tabela semanal — mostra TODAS as 52 semanas do ano
    # (semanas futuras aparecem com traço).
    log_semanal_html = ''
    # Indexa por numero da semana
    por_semana = {int(r['semana']): r for r in log_semanal_view}
    rows_html = []
    for sem_n in range(1, 53):
        ini_s, fim_s = _periodo_semana(sem_n)
        ini_str = ini_s.strftime('%d/%m/%Y')
        fim_str = fim_s.strftime('%d/%m/%Y')
        r = por_semana.get(sem_n)
        if r:
            parcial = r.get('parcial', False)
            sem_label = (f'{sem_n} <span style="color:#aaa;font-weight:400">(parcial)</span>'
                         if parcial else str(sem_n))
            n_manobras = r.get('n_manobras', 0) or 0
            try:
                n_manobras = int(n_manobras)
            except Exception:
                n_manobras = 0
            # Media/dia: parcial usa dias decorridos, fechada usa 7
            if parcial:
                dias_decorridos = max(1, (pd.Timestamp(now) - ini_s).total_seconds() / 86400)
                media_dia = n_manobras / dias_decorridos
            else:
                media_dia = n_manobras / 7
            n_str = f'{n_manobras} ({media_dia:.1f}/dia)' if n_manobras > 0 else '—'
            dt_str = str(r['delta_str'])
            pos_str = str(r['pos_media'])
            row_style = 'background:#fff8dc' if parcial else ''
        else:
            sem_label = str(sem_n)
            n_str = '—'
            dt_str = '—'
            pos_str = '—'
            row_style = 'color:#bbb'
        rows_html.append(
            f'<tr style="{row_style}">'
            f'<td style="text-align:center;font-weight:600;padding:4px 8px">{sem_label}</td>'
            f'<td style="white-space:nowrap;padding:4px 8px">{ini_str} → {fim_str}</td>'
            f'<td style="text-align:center;padding:4px 8px">{n_str}</td>'
            f'<td style="text-align:center;font-weight:600;padding:4px 8px">{dt_str}</td>'
            f'<td style="text-align:center;font-weight:600;padding:4px 8px">{pos_str}</td>'
            f'</tr>'
        )
    log_semanal_html = f'''
<div class="panel" style="margin-top:18px">
  <div class="panel-title">📊 Histórico semanal — Δt e Posições</div>
  <div style="padding:8px 12px">
    <div style="max-height:340px;overflow-y:auto;border:1px solid #e0e0e0;border-radius:4px">
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead><tr style="background:#f0f4f8;position:sticky;top:0;z-index:1">
          <th style="padding:8px;border-bottom:1px solid #ccc">Semana</th>
          <th style="padding:8px;border-bottom:1px solid #ccc;text-align:left">Período</th>
          <th style="padding:8px;border-bottom:1px solid #ccc">Manobras (média/dia)</th>
          <th style="padding:8px;border-bottom:1px solid #ccc">Δt médio efetivo</th>
          <th style="padding:8px;border-bottom:1px solid #ccc">Pos. média após B</th>
        </tr></thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
    </div>
  </div>
</div>
'''

    # ── Fila EP ───────────────────────────────────────────────────────────────
    fila_html = ''
    fila_items = []
    _esc_str = ultima_esc.get('esc', '') if isinstance(ultima_esc, dict) else str(ultima_esc or '')
    if _esc_str:
        for i, part in enumerate(_esc_str.split(' > '), 1):
            p = part.split('(')[0].strip()
            if not p:
                continue
            inner = part[part.index('(')+1:part.index(')')] if '(' in part else ''
            fila_items.append({'pos': i, 'pratico': p, 'status': inner or 'disponível'})

    for item in fila_items:
        p = item['pratico']
        st = item['status']

        # Casos:
        #   especial sem nada:             JA, SI, CH                -> badge vazio
        #   especial com número de posição: JA(4), SI(10)         -> badge "N"
        #   especial entrando:              SI(E)                     -> badge "E"
        #   pratico normal com HH:MM:       RG(09:00), LB(10:15)     -> badge hora
        #   pratico normal disponivel:      RG (sem parenteses)      -> badge ok
        if p in ESPECIAIS:
            bg, fc = '#e8f4e8', '#2d6a2d'
            if st in ('', 'disponível'):
                badge = ''
            elif st == 'E':
                badge = '<span class="badge esp">E</span>'
            else:
                # número de posição (E12) ou outra info
                badge = f'<span class="badge esp">{st}</span>'
        elif st == 'disponível':
            bg, fc = '#ffffff', '#1a1a1a'
            badge = '<span class="badge ok">✓</span>'
        else:  # HH:MM
            bg, fc = '#f0f4ff', '#3355aa'
            badge = f'<span class="badge hhmm">{st}</span>'

        fila_html += f'''<tr style="background:{bg};color:{fc}">
          <td class="pos">P{item['pos']}</td>
          <td class="prat">{p}</td>
          <td class="st">{badge}</td>
        </tr>'''

    # ── Disponíveis (ordem da escalação) e indisponíveis (ordem de disponibilidade) ──
    disp_html, indisp_html, sit_hora, prox_hora, tipo_lbl = '', '', '', '', ''
    if isinstance(ultima_esc, dict) and ultima_esc.get('esc'):
        import re as _re
        _ref = ultima_esc['dt']
        _agora = pd.Timestamp(now)
        sit_hora = _ref.strftime('%d/%m %H:%M')
        # disponível = quem já estará livre na hora prevista da próxima manobra branca
        _t_prox = ultima_esc.get('t_prox') or _agora
        prox_hora = pd.Timestamp(_t_prox).strftime('%H:%M')
        tipo_lbl = {'E': '(E)', 'S': '(S/M)'}.get(ultima_esc.get('tipo_prox'), '')
        _disp, _indisp = [], []
        for part in ultima_esc['esc'].split(' > '):
            p = part.split('(')[0].strip()
            if not p:
                continue
            inner = part[part.index('(')+1:part.index(')')] if '(' in part and ')' in part else ''
            mh = _re.fullmatch(r'(\d{1,2}):(\d{2})', inner)
            if mh and p not in ESPECIAIS:
                t = _ref.normalize() + pd.Timedelta(hours=int(mh.group(1)), minutes=int(mh.group(2)))
                if t < _ref - pd.Timedelta(hours=6):
                    t += pd.Timedelta(days=1)
                t = ultima_esc.get('avail', {}).get(p, t)   # disponibilidade para a próxima manobra
                tE = ultima_esc.get('avail_E', {}).get(p, t); tS = ultima_esc.get('avail_S', {}).get(p, t)
                if t > _t_prox:                 # ainda ocupado na hora da próxima manobra
                    _indisp.append((min(tE, tS), p, tE, tS)); continue
                # livre para a próxima, mas talvez não para o outro tipo de manobra no mesmo horário
                outro = tS if ultima_esc.get('tipo_prox') == 'E' else tE
                inner = (('S ' if ultima_esc.get('tipo_prox') == 'E' else 'E ') + outro.strftime('%H:%M')) if outro > _t_prox else ''
            _disp.append((p, inner))
        for n, (p, inner) in enumerate(_disp, 1):
            if p in ESPECIAIS:
                cls, badge = 'esp', (f'<span class="badge esp">{inner}</span>' if inner else '')
            elif inner:
                cls, badge = '', f'<span class="so" title="Livre para a próxima manobra; para {"saída/mudança" if inner[0]=="S" else "entrada"} só a partir de {inner[2:]}">{"saída" if inner[0]=="S" else "entrada"} só {inner[2:]}</span>'
            else:
                cls, badge = '', ''
            disp_html += f'<tr class="{cls}"><td class="pos">{n}</td><td class="prat">{p}</td><td class="st">{badge}</td></tr>'
        for t, p, tE, tS in sorted(_indisp):
            indisp_html += (f'<tr><td class="prat">{p}</td><td class="st"><span class="tE">E {tE:%H:%M}</span>'
                            f'<br><span class="tS">S {tS:%H:%M}</span></td></tr>')
    if isinstance(ultima_esc, dict) and ultima_esc.get('esc') and not any(p not in ESPECIAIS for p, _ in _disp):
        _primeiro = min((x[0] for x in _indisp), default=None)
        disp_html = (f'<tr><td colspan="3" class="vazio" style="color:#c0392b;font-weight:700">⚠ ninguém livre às {prox_hora}'
                     + (f'<br>primeiro às {_primeiro:%H:%M}' if _primeiro is not None else '') + '</td></tr>')
    if not disp_html:
        disp_html = '<tr><td colspan="3" class="vazio">— nenhum —</td></tr>'
    if not indisp_html:
        indisp_html = '<tr><td colspan="2" class="vazio">— nenhum —</td></tr>'

    # ── Lista Z5 do dia operacional vigente ──────────────────────────────────
    z5_dia = []
    z5_vistos = set()
    for m in historico + passadas:
        try:
            dt  = m.get('datetime')
            de  = m.get('de', '')
            par = m.get('para', '')
            prat = str(m.get('pratico', '')).strip()
            if not prat or prat in ESPECIAIS:
                continue
            if dt < ini_hoje or dt >= fim_hoje:
                continue
            if not is_z5(de, par):
                continue
            key = (prat, dt)
            if key in z5_vistos:
                continue
            z5_vistos.add(key)
            z5_dia.append({'dt': dt, 'pratico': prat})
        except Exception:
            continue
    z5_dia.sort(key=lambda x: x['dt'])

    z5_html = ''
    if z5_dia:
        for item in z5_dia:
            hh = item['dt'].strftime('%H:%M') if hasattr(item['dt'], 'strftime') else ''
            z5_html += f'<tr><td class="z5-hh">{hh}</td><td class="z5-prat">{item["pratico"]}</td></tr>'
    else:
        z5_html = '<tr><td colspan="2" style="text-align:center;padding:8px;color:#999;font-size:10px">— sem Z5 —</td></tr>'

    # ── Projeção (histórico + passadas + futuras em ordem cronológica) ──────
    proj_html = ''
    # Junta tudo em ordem cronologica. Historico fica antes (manobras
    # finalizadas anteriores ao inicio da pauta atual, mas dentro do dia
    # operacional). Tratadas como passadas (visual rosa "EXECUTADO").
    todas_proj = (
        [(m, True) for m in historico] +
        [(m, True) for m in passadas if m not in historico] +
        [(m, False) for m in futuras]
    )
    # Ordena por datetime; desempate: seq (ordem da SIMULAÇÃO), para que a coluna Escalação
    # de cada linha siga a sequência em que a E2D distribuiu as manobras do mesmo horário.
    # (Antes desempatava pela ordem do SPPILOTS, e manobras ausentes da pauta iam para o fim do
    #  horário, fazendo parecer que alguém tinha passado na frente.)
    todas_proj.sort(key=lambda x: (
        pd.Timestamp(x[0]['datetime']),
        int(x[0].get('seq', 0) or 0)
    ))

    # JUNTAR manobras duplicadas de navios de 2 praticos em UMA linha so.
    # Quando 2 manobras tem mesma (datetime, vessel) e dois_prat=True,
    # mostra como EP1/EP2 numa linha so (mais limpo visualmente).
    juntadas = []
    vistos = {}  # (dt,vessel) -> indice em juntadas
    for m, is_past in todas_proj:
        if m.get('dois_prat'):
            key = (m['datetime'], m['vessel'].strip())
            if key in vistos:
                # Junta com a anterior: concatena praticos, A/B e proxima
                idx = vistos[key]
                m_ant, _ = juntadas[idx]
                p1 = str(m_ant.get('pratico', '')).strip()
                p2 = str(m.get('pratico', '')).strip()
                if p2 and p2 not in p1.split('/'):
                    m_ant['pratico'] = p1 + '/' + p2 if p1 else p2
                if m.get('obs_e2d'):
                    m_ant['obs_e2d'] = list(dict.fromkeys((m_ant.get('obs_e2d') or []) + m['obs_e2d']))
                if m.get('inviavel') and (not m_ant.get('inviavel') or m['inviavel'] > m_ant['inviavel']):
                    m_ant['inviavel'] = m['inviavel']
                # Concatena A/B (cada pratico pode ter status A/B diferente)
                ab1 = str(m_ant.get('ab', '')).strip()
                ab2 = str(m.get('ab', '')).strip()
                if ab2:   # navio de 2 práticos: mostra os dois status sempre (A/B, e também A/A e B/B)
                    m_ant['ab'] = f'{ab1}/{ab2}' if ab1 else ab2
                # Concatena proxima: cada pratico tem sua propria proxima manobra
                # DL de dupla: mostra cada prático com o seu valor (ex.: 'ED 19h')
                partes = m_ant.get('_dl_partes') or [(p1.split('/')[0].strip(), str(m_ant.get('proxima', '')).strip())]
                partes.append((p2, str(m.get('proxima', '')).strip()))
                m_ant['_dl_partes'] = partes
                # status de cada prático, para o amarelo do Δt da A (mesmo quando o Δt de um deles está em branco)
                _abp = m_ant.get('_abp') or {p1.split('/')[0].strip(): ab1}
                _abp[p2] = ab2; m_ant['_abp'] = _abp
                m_ant['proxima'] = ' / '.join(f'{pp} {vv}' for pp, vv in partes if vv)
                # Mantem escalacao do primeiro (geralmente igual no segundo)
                continue
            else:
                vistos[key] = len(juntadas)
                # Cria copia pra nao modificar original
                juntadas.append((dict(m), is_past))
        else:
            juntadas.append((m, is_past))

    # Manobra cancelada depois da escalação (linha verde no SPPilots): aparece em verde, com o prático que
    # estava escalado; não conta como manobra (A/B mostra o que ela seria; Δt até o horário dela, e a manobra seguinte do prático conta a partir dela) e o prático vai para a frente da fila (PACOTE 5.17)
    try:
        if juntadas:
            _t0 = min(pd.Timestamp(x['datetime']) for x, _ in juntadas); _t1 = max(pd.Timestamp(x['datetime']) for x, _ in juntadas)
            _rtc = pd.read_csv(PAUTA_RT, dtype=str)
            _rtc = _rtc[_rtc['Status'].astype(str).str.strip().str.upper() == 'CANCELADA'] if 'Status' in _rtc.columns else _rtc.iloc[0:0]
            _cpr = _CANC_LIN   # lido em montar_dados (ao_vivo/canceladas_painel.csv)
            _vc = set()
            for _r in _rtc.itertuples():
                _d = pd.Timestamp(_r.datetime).floor('min'); _v = str(_r.Vessel).strip()
                if (_d, _v) in _vc or not (_t0 <= _d <= _t1):
                    continue
                _vc.add((_d, _v))
                _pp = [x for x in _cpr.get((_d, _v), []) if x[0]]
                juntadas.append(({'datetime': _d, 'vessel': _v, 'de': str(_r.From).strip(), 'para': str(_r.To).strip(),
                                  'pratico': '/'.join(x[0] for x in _pp), 'ab': '/'.join(x[1] for x in _pp), 'status': 'CANCELADA', 'cancelada': True,
                                  'calado': '', 'bordo': '', 'proxima': _CANC_DT.get((_d, _v), ''), 'escalacao': ''}, False))
            juntadas.sort(key=lambda x: pd.Timestamp(x[0]['datetime']))
    except Exception as _e:
        print(f'[cancelada] não mostrada: {_e}')

    for m, is_past in juntadas:
        dt_s = pd.Timestamp(m['datetime']).strftime('%d/%m %H:%M')
        vessel = str(m['vessel'])
        de = str(m['de'])
        para = str(m['para'])
        es = str(m.get('es', '') or ('E' if de == 'FB' else ('S' if para == 'FB' else 'M')))
        rota = _local_sp(es, de, para)   # como no SPPILOTS: E 39, S 39, M 34 → 35.2

        ep = m['pratico']
        is_esp_man = str(ep).strip() in ESPECIAIS or any(p.strip() in ESPECIAIS for p in str(ep).split('/'))

        ab = m.get('ab', '')
        # Se tem B em qualquer parte (B, B/A, A/B), usa cor de B
        ab_cl = 'ab-b' if 'B' in ab.upper() else 'ab-a'

        status_man = m.get('status', '')
        if is_past:
            status_man = 'EXECUTADO'
        bg = COR_STATUS.get(status_man, '#ffffff')
        fc = COR_TEXT.get(status_man, '#000000')
        # Como no SPPilots: manobra de especial = linha cinza (escalada ou confirmada); preta depois de finalizada
        if is_esp_man or any(x.strip() in ESPECIAIS for x in str(m.get('pra_real', '')).split('/')):
            bg, fc = ('#000000', '#fff') if is_past else ('#a5a5a5', '#fff')
        if m.get('cancelada'):
            bg, fc = '#66cc66', '#000'
        # Especiais: NÃO altera fundo da linha — só destaca coluna PRT inline
        # Isso evita o visual "colado" quando especiais aparecem consecutivos

        cal = str(m.get('proxima', '') or '')
        brd = str(m.get('bordo', '') or '')
        agt = str(m.get('agente', '') or '')[:15]
        obs = str(m.get('obs', '') or '')[:80]
        esc_str = str(m.get('escalacao', ''))
        # Na linha da própria manobra, o HH:MM de quem a está fazendo não se aplica
        # (é calculado pela origem desta mesma manobra): mostra (n/a)
        for _p in [x.strip() for x in str(m.get('pratico', '')).split('/') if x.strip()]:
            if _p not in ESPECIAIS:
                esc_str = _re_cb.sub(r'(?<![A-Z])' + _re_cb.escape(_p) + r'\(\d{1,2}:\d{2}\)', _p + '(n/a)', esc_str)

        # Escape HTML para nao quebrar o layout caso conteudo tenha <, >, &, "
        import html as _html
        vessel_e = _html.escape(vessel)
        rota_e   = _html.escape(rota)
        ep_e     = _html.escape(ep)
        ab_e     = _html.escape(ab)
        cal_e    = _html.escape(cal)
        esc_e    = _html.escape(esc_str)

        # Célula PRT com destaque para especiais
        # (como no SPPilots, o especial aparece sem destaque na célula; a cor vem da linha)
        _relp = next((x.strip() for x in str(ep).split('/') if x.strip() and x.strip() not in ESPECIAIS), '')
        _reld = (pd.Timestamp(m['datetime']) - pd.Timedelta(hours=7, minutes=30)).date()
        _rela = f' data-p="{_html.escape(_relp)}" data-d="{_reld}"' if _relp else ''
        ep_cell = f'<td class="ep{" relx" if _relp else ""}"{_rela}>{ep_e}</td>'
        _obs = list(dict.fromkeys(m.get('obs_e2d') or []))
        if _obs:
            def _explica(o):
                cab, det = (o.split(':', 1) + [''])[:2] if ':' in o else (o, '')
                quem = cab[cab.find('(') + 1:cab.find(')')] if '(' in cab and ')' in cab else ''
                quem = f' ({quem})' if quem else ''
                if o.startswith('B apertada'):
                    return f'Risco de atraso{quem}: pouco tempo entre o fim previsto da A e esta manobra. {det.strip()}'
                return f'Escalado ainda em manobra{quem}: {det.strip()}'
            _txt = ' | '.join(_explica(o) for o in _obs)
            _tit = _html.escape(_txt)
            ep_cell = ep_cell.replace('</td>', f'<span class="obsx" tabindex="0" title="{_tit}" '
                                               f'onclick="this.classList.toggle(\'open\')">⚠'
                                               f'<span class="obsx-txt">{_tit}</span></span></td>', 1)

        _inv = m.get('inviavel')
        if _inv is not None and not is_past:
            dt_cell = (f'<td class="dt" title="Horário previsto inviável: o prático escalado só fica livre às '
                       f'{_inv:%H:%M} (provavelmente o horário ainda não foi atualizado)">{dt_s}'
                       f'<br><span class="invi">⚠ livre {_inv:%H:%M}</span></td>')
        else:
            dt_cell = f'<td class="dt">{dt_s}</td>'
        proj_html += f'''<tr style="background:{bg};color:{fc}">
          <td class="vessel">{vessel_e}{' <span class="p2">(2 PRÁTICOS)</span>' if m.get('dois_prat') else ''}</td>
          <td class="berco">{rota_e}</td>
          {dt_cell}
          {ep_cell}'''

        # ordem da pauta do SPPILOTS: ... PRT, calado, bordo; depois os campos da E2D e a escalação
        proj_html += f'''
          <td class="calado">{_html.escape(str(m.get('calado', '') or ''))}</td>
          <td class="brd">{_html.escape(str(m.get('bordo', '') or ''))}</td>
          <td class="{ab_cl}{' relx' if _relp else ''}"{_rela}>{ab_e}</td>
          <td class="cal">{_dt_html(cal, ab, m.get('_abp'))}</td>
          <td class="esc esc-col">{esc_e}</td>
        </tr>'''

    if not proj_html:
        proj_html = '<tr><td colspan="9" style="text-align:center;padding:20px;color:#999">Sem manobras</td></tr>'

    # ── Histórico do dia operacional vigente (manobras antes da pauta) ───────
    # Mesmo formato visual da Projeção EP, mas sem a coluna "Escalação"
    hist_html = ''
    # Junta duplicatas de 2 praticos igual fazemos na projecao
    hist_juntadas = []
    hist_vistos = {}
    for m in historico:
        if m.get('dois_prat'):
            key = (m['datetime'], m['vessel'].strip())
            if key in hist_vistos:
                idx = hist_vistos[key]
                m_ant = hist_juntadas[idx]
                p1 = str(m_ant.get('pratico', '')).strip()
                p2 = str(m.get('pratico', '')).strip()
                if p2 and p2 not in p1.split('/'):
                    m_ant['pratico'] = p1 + '/' + p2 if p1 else p2
                ab1 = str(m_ant.get('ab', '')).strip()
                ab2 = str(m.get('ab', '')).strip()
                if ab2:   # navio de 2 práticos: mostra os dois status sempre (A/B, e também A/A e B/B)
                    m_ant['ab'] = f'{ab1}/{ab2}' if ab1 else ab2
                # DL de dupla: mostra cada prático com o seu valor (ex.: 'ED 19h')
                partes = m_ant.get('_dl_partes') or [(p1.split('/')[0].strip(), str(m_ant.get('proxima', '')).strip())]
                partes.append((p2, str(m.get('proxima', '')).strip()))
                m_ant['_dl_partes'] = partes
                # status de cada prático, para o amarelo do Δt da A (mesmo quando o Δt de um deles está em branco)
                _abp = m_ant.get('_abp') or {p1.split('/')[0].strip(): ab1}
                _abp[p2] = ab2; m_ant['_abp'] = _abp
                m_ant['proxima'] = ' / '.join(f'{pp} {vv}' for pp, vv in partes if vv)
                continue
            else:
                hist_vistos[key] = len(hist_juntadas)
                hist_juntadas.append(dict(m))
        else:
            hist_juntadas.append(m)

    import html as _html
    for m in hist_juntadas:
        dt_s = pd.Timestamp(m['datetime']).strftime('%d/%m %H:%M')
        de = str(m.get('de', ''))
        para = str(m.get('para', ''))
        es = str(m.get('es', '') or ('E' if de == 'FB' else ('S' if para == 'FB' else 'M')))
        rota = _local_sp(es, de, para)
        ep = m.get('pratico', '')
        ab = m.get('ab', '')
        ab_cl = 'ab-b' if 'B' in ab.upper() else 'ab-a'
        cal = str(m.get('proxima', '') or '')
        vessel = str(m.get('vessel', ''))[:26]

        # Cor: manobras de historico ja foram executadas (cinza claro neutro)
        bg = '#f0f0f0'
        fc = '#555555'

        vessel_e = _html.escape(vessel)
        rota_e   = _html.escape(rota)
        ep_e     = _html.escape(str(ep))
        ab_e     = _html.escape(ab)
        cal_e    = _html.escape(cal)

        hist_html += f'''<tr style="background:{bg};color:{fc}">
          <td class="vessel">{vessel_e}{' <span class="p2">(2 PRÁTICOS)</span>' if m.get('dois_prat') else ''}</td>
          <td class="berco">{rota_e}</td>
          <td class="dt">{dt_s}</td>
          <td class="ep">{ep_e}</td>
          <td class="{ab_cl}">{ab_e}</td>
          <td class="cal">{_dt_html(cal, ab, m.get('_abp'))}</td>
        </tr>'''

    if not hist_html:
        hist_html = '<tr><td colspan="6" style="text-align:center;padding:10px;color:#999">Sem histórico</td></tr>'

    # ── Stats ─────────────────────────────────────────────────────────────────
    n_disp  = sum(1 for x in fila_items if x['status'] == 'disponível')

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>E2D — Ao Vivo</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 12px; background: #f0f2f5; color: #1a1a1a; }}

.header {{ background: #1B4F72; color: white; padding: 10px 16px;
           display: flex; align-items: center; justify-content: space-between; }}
.header h1 {{ font-size: 15px; font-weight: 700; letter-spacing: 1px; }}
.header .meta {{ font-size: 11px; opacity: .85; text-align: right; line-height: 1.5; }}

.stats {{ display: flex; gap: 16px; padding: 7px 14px; background: #eaf0fb;
         border-bottom: 1px solid #d0daf0; font-size: 11px; color: #1B4F72; }}
.stats b {{ font-weight: 700; }}

.container {{ display: flex; gap: 12px; padding: 12px; max-width: 100%; margin: 0 auto; height: calc(100vh - 100px); }}

.panel {{ background: white; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.12); overflow: hidden; }}
.panel-title {{ background: #2E86C1; color: white; padding: 7px 12px;
                font-size: 12px; font-weight: 700; letter-spacing: .5px; }}

/* Fila */
.fila {{ width: 155px; flex-shrink: 0; overflow-y: auto; }}
.fila table {{ width: 100%; border-collapse: collapse; }}
.fila td {{ padding: 3px 5px; border-bottom: 1px solid #eee; }}
.pos {{ width: 24px; font-weight: 700; color: #888; font-size: 10px; }}
.prat {{ font-weight: 700; font-size: 12px; letter-spacing: .3px; }}
.st {{ text-align: right; font-size: 10px; }}
.fila .badge {{ font-size: 9px; padding: 1px 4px; }}

/* Coluna lateral esquerda: Z5 + disponíveis + indisponíveis */
.sidecol {{ width: 128px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; min-height: 0; }}
.sidecol .panel {{ display: flex; flex-direction: column; min-height: 0; }}
.sidecol .panel-title {{ padding: 6px 8px; font-size: 11px; }}
.side {{ flex: 1 1 0; }}
.side-scroll {{ flex: 1; overflow-y: auto; }}
.side table {{ width: 100%; border-collapse: collapse; }}
.side td {{ padding: 2px 6px; border-bottom: 1px solid #eee; }}
.side .pos {{ width: 18px; color: #999; font-size: 10px; font-weight: 400; }}
.side .prat {{ font-weight: 700; font-size: 13px; letter-spacing: .3px; }}
.side .st {{ text-align: right; font-size: 10px; color: #555; white-space: nowrap; }}
.side tr.esp {{ color: #2d6a2d; background: #f1f8f1; }}
.side .tE {{ color: #1a5276; }}
.side .tS {{ color: #7d6608; }}
.side .so {{ font-size: 9px; color: #b9770e; white-space: nowrap; }}
.side .dia {{ color: #999; font-size: 9px; }}
.side .vazio {{ text-align: center; color: #999; font-size: 10px; padding: 8px; }}
.disp .panel-title {{ background: #1e8449; }}
.indisp .panel-title {{ background: #5d6d7e; }}
.z5col {{ flex: 0 1 auto; max-height: 22%; }}
.z5col .panel-title {{ background: #C0392B; }}
.z5-scroll {{ flex: 1; overflow-y: auto; }}
.z5col table {{ width: 100%; border-collapse: collapse; }}
.z5col td {{ padding: 3px 5px; border-bottom: 1px solid #eee; text-align: center; }}
.z5-hh {{ font-size: 10px; color: #888; }}
.z5-prat {{ font-weight: 700; font-size: 13px; color: #C0392B; letter-spacing: .3px; }}

/* Projeção */
.proj {{ flex: 1; min-width: 0; display: flex; flex-direction: column; }}
.proj-scroll {{ flex: 1; overflow-y: scroll; overflow-x: auto;
                scrollbar-width: thin; scrollbar-color: #2E86C1 #f0f0f0; }}
.proj-scroll::-webkit-scrollbar {{ width: 8px; height: 10px; }}
.proj-scroll::-webkit-scrollbar-thumb {{ background: #2E86C1; border-radius: 4px; }}
.proj-scroll::-webkit-scrollbar-track {{ background: #f0f0f0; }}
.proj table {{ min-width: 100%; border-collapse: collapse; table-layout: auto;
               font-family: Tahoma, Verdana, "Segoe UI", sans-serif; font-size: 11px; }}
/* visual igual à pauta do SPPilots: Tahoma 11px (medido com os dois em 100%), cabeçalho cinza, linhas separadas por traço preto */
.proj th {{ background: #cccccc; color: #000; padding: 3px 6px; border-bottom: 1px solid #000;
            font-size: 11px; font-weight: 700; text-align: left; position: sticky; top: 0; z-index: 1;
            white-space: nowrap; }}
.proj td {{ padding: 2px 6px; border-bottom: 1px solid #000; font-size: 11px; line-height: 14px; }}
.proj td.vessel, .proj td.berco, .proj td.dt, .proj td.ep, .proj td.calado, .proj td.brd,
.proj td.cal, .proj td.esc, .proj td.ab-a, .proj td.ab-b {{ color: inherit; font-size: 11px; font-weight: 400; letter-spacing: 0; }}
.proj td.esc {{ font-size: 10px; }}
#projtab.hide-esc .esc-col {{ display: none; }}
.p2 {{ background: #ffff00; color: #0000ff; }}
.es {{ width: 28px; text-align: center; font-weight: 700; white-space: nowrap; }}
.star2 {{ font-size: 9px; color: #d4a017; margin-left: 2px; }}
.vessel {{ font-weight: 600; white-space: nowrap; }}
.berco {{ font-weight: 600; font-size: 11px; white-space: nowrap; }}
.brd {{ font-size: 11px; text-align: center; width: 36px; }}
.calado {{ font-size: 11px; white-space: nowrap; color: #333; }}
.dt {{ width: 85px; white-space: nowrap; }}
.invi {{ background: #ffff00; color: #c00000; font-weight: 700; font-size: 10px; padding: 0 2px; }}
.relx {{ cursor: pointer; text-decoration: underline dotted; }}
#relbox .tg {{ font-size:10px; padding:0 4px; border-radius:3px; color:#fff; }} #relbox .tl {{ background:#2e7d32; }} #relbox .tc {{ background:#8d6e00; }}
#relbox tr.cic td {{ background:#fff8e1; color:#555; }}
#relbox .te {{ background:#555; }} #relbox .ta {{ background:#7cc47f; color:#000; }} #relbox .ti {{ background:#999; }}
#relbox .dia {{ background:#eaf3ea; border:1px solid #9cc79c; border-radius:4px; padding:5px 8px; margin:6px 0; }}
#relbox .barra {{ margin:4px 0 0; }} #relbox .barra svg {{ display:block; width:100%; height:auto; }}
#relbox .leg {{ font-size:10px; color:#333; margin:0 0 8px; line-height:1.6; }} #relbox .leg span {{ display:inline-block; width:10px; height:10px; margin:0 3px 0 7px; vertical-align:-1px; }}
#relbox .big {{ font-size:16px; font-weight:700; }} #relbox .ok {{ color:#2e7d32; }}
#relbox {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:100; }}
#relbox .in {{ background:#fff; color:#000; max-width:760px; margin:4vh auto; max-height:90vh; overflow:auto; padding:12px 14px; border-radius:6px; font-size:12px; }}
#relbox table {{ border-collapse:collapse; width:100%; margin:4px 0 8px; }}
#relbox td, #relbox th {{ border:1px solid #ccc; padding:2px 5px; text-align:left; vertical-align:top; }}
#relbox th {{ background:#1f3a5f; color:#fff; }}
#relbox .fut {{ color:#999; }} #relbox .neg {{ color:#c00000; font-weight:700; }}
#relbox .x {{ float:right; cursor:pointer; font-size:18px; font-weight:700; }}
#relbox .cols {{ display:flex; gap:10px; flex-wrap:wrap; }} #relbox .cols > div {{ flex:1 1 330px; }}
.obsx {{ position: relative; color: #ffd400; text-shadow: 0 0 1px #000, 0 0 1px #000, 0 0 1px #000; font-weight: 700; margin-left: 3px; cursor: pointer; }}
.obsx-txt {{ display: none; position: absolute; left: 0; top: 1.4em; z-index: 20; width: 240px; white-space: normal;
  background: #ffffe0; color: #000; border: 1px solid #000; padding: 4px 6px; font-weight: 400; font-size: 11px; text-align: left; }}
.obsx.open .obsx-txt {{ display: block; }}
.dl-a {{ color: #ffd400; font-weight: 800; text-shadow: 0 0 1px #000, 0 0 1px #000, 0 0 1px #000; }}
.ep {{ font-weight: 700; font-size: 14px; color: #1B4F72; letter-spacing: .5px; white-space: nowrap; }}
.cal, .brd {{ font-size: 10.5px; color: #666; white-space: nowrap; }}
.esc {{ font-size: 11px; font-family: "Consolas","Courier New",monospace; color: #333;
        white-space: nowrap;
        letter-spacing: 0px; word-spacing: 0px; }}
.agt {{ font-size: 11px; color: #666; max-width: 90px; }}
.obs {{ font-size: 10px; color: #555; max-width: 240px;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

/* Histórico */
.hist {{ max-width: 100%; margin: 0 auto; padding: 0 12px 16px; }}
.hist table {{ width: 100%; border-collapse: collapse; }}
.hist th {{ background: #1B4F72; color: white; padding: 6px 8px; font-size: 11px; text-align: left; }}
.hist td {{ padding: 4px 8px; font-size: 12px; border-right: 1px solid #e8e8e8; }}
.hdt {{ width: 110px; white-space: nowrap; font-weight: 600; }}
.hvessel {{ font-weight: 600; width: 180px; }}
.hrota {{ color: #555; width: 180px; }}
.hep {{ font-weight: 700; color: #1B4F72; width: 60px; }}
.hpts {{ width: 50px; color: #666; }}

.ab-a {{ font-weight: 700; color: #1a5276; text-align: center; width: 28px; }}
.ab-b {{ font-weight: 700; color: #1e8449; text-align: center; width: 28px; }}

.badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; }}
.badge.ok {{ background: #d5f5e3; color: #1e8449; }}
.badge.hhmm {{ background: #d6eaf8; color: #1a5276; }}
.badge.esp {{ background: #e8f4e8; color: #2d6a2d; }}
</style>
</head>
<body>

<div class="header">
  <h1>⚓ E2D — Escala 2 e Desce | Porto de Santos</h1>
  <div class="meta">
    <span style="font-size:15px">Atualizado às <b>{gen_hora}</b> ({gen_data}) · <b id="idade"></b></span>
    <span style="opacity:.8"> · pauta do SPPilots lida às {pauta_str}</span><br>
    Ontem: <b>{n_ontem}</b> manobras | Hoje: <b>{n_hoje}</b> manobras | Média do ano: <b>{media_ano:.1f}</b>/dia<br>
    Navios 2 práticos (hoje): <b>{n_pares_hoje}</b> | Descanso médio efetivo (Δt, 7 dias): <b>{delta_medio_str}</b> | Posições médias após B: <b>{pos_media_str}</b>
  </div>
</div>

<div class="stats">
  <span style="margin-left:auto;opacity:.7">Dados atualizados a cada 10 min · próxima verificação em <span id="countdown">5:00</span></span>
</div>

<script>
function togEsc(){{var t=document.getElementById('projtab'),b=document.getElementById('btn-esc');if(!t)return;
var h=t.classList.toggle('hide-esc');if(b)b.textContent=h?'Mostrar escalação':'Ocultar escalação';
try{{localStorage.setItem('e2d_esc',h?'0':'1')}}catch(e){{}}}}
document.addEventListener('DOMContentLoaded',function(){{try{{if(localStorage.getItem('e2d_esc')==='1')togEsc()}}catch(e){{}}}});
// Idade dos dados: "há X min"; fica vermelho se passar de 30 min (computador desligado / sessão caiu)
(function(){{
  const gen = new Date('{gen_iso}');
  const el = document.getElementById('idade');
  function upd() {{
    const min = Math.max(0, Math.round((Date.now() - gen.getTime()) / 60000));
    if (!el) return;
    if (min > 30) {{
      const h = Math.floor(min / 60), mm = min % 60;
      el.textContent = '⚠ desatualizado há ' + (h ? h + 'h' + String(mm).padStart(2, '0') : min + ' min');
      el.style.cssText = 'color:#fff;background:#c0392b;padding:1px 6px;border-radius:3px';
    }} else {{
      el.textContent = min < 1 ? 'agora' : 'há ' + min + ' min';
    }}
  }}
  upd(); setInterval(upd, 30000);
}})();
// Contador visual do proximo refresh (a pagina recarrega sozinha via meta http-equiv)
(function(){{
  let s = 300;
  const el = document.getElementById('countdown');
  setInterval(() => {{
    s = Math.max(0, s - 1);
    const m = Math.floor(s/60), ss = s%60;
    if (el) el.textContent = m + ':' + String(ss).padStart(2,'0');
  }}, 1000);
}})();
</script>

<div class="container">
  <div class="sidecol">
    <div class="panel z5col">
      <div class="panel-title">Z5 hoje</div>
      <div class="z5-scroll">
        <table><tbody>{z5_html}</tbody></table>
      </div>
    </div>
    <div class="panel side disp">
      <div class="panel-title" title="Ordem da escalação após a última manobra confirmada ({sit_hora}), considerando quem estará livre na hora prevista da próxima manobra não confirmada ({prox_hora})">Disponíveis · {prox_hora} {tipo_lbl}</div>
      <div class="side-scroll"><table><tbody>{disp_html}</tbody></table></div>
    </div>
    <div class="panel side indisp">
      <div class="panel-title" title="Hora em que cada um fica livre para uma entrada (E, margem 45 min, lancha até FB) e para uma saída/mudança (S, margem 25 min, lancha até o berço da próxima saída)">Indisponíveis · livre p/ E / S</div>
      <div class="side-scroll"><table><tbody>{indisp_html}</tbody></table></div>
    </div>
  </div>
  <div class="panel proj">
    <div class="panel-title">🚢 Pauta simulada pela E2D · margem 45 min antes de entrada e 25 min antes de saída/mudança · especiais pela E12 <button id="btn-esc" type="button" onclick="togEsc()" style="float:right;font-size:11px;padding:1px 8px;cursor:pointer">Mostrar escalação</button></div>
    <div class="proj-scroll">
      <table id="projtab" class="hide-esc">
        <thead><tr>
          <th>Navio</th><th>Local</th><th>Horário</th>
          <th title="⚠ = em observação (manobras confirmadas, a partir da escalação 1 h antes): risco de atraso, ou escalado ainda em manobra (a anterior ainda não terminou pelo T na escalação). Toque no ⚠ para ver o motivo.">PRT</th><th>Calado</th><th>Bordo</th><th>A/B</th><th title="Δt entre inícios: na B, do início da A até o início da B; na A, do início da B anterior até o início da A (mesmo prático, mesmo turno)">Δt</th><th class="esc-col">Escalação</th>
        </tr></thead>
        <tbody>{proj_html}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- Tabela "Historico - Dia Operacional Atual" removida.
     Manobras finalizadas (do dia operacional vigente, anteriores a primeira
     da pauta) ja estao integradas na tabela principal "Manobras - Projecao EP",
     em ordem cronologica, com visual de manobra executada (vermelho). -->

<!-- Botao "Atualizar Pauta SPPILOTS" removido (nao funcionava na pratica).
     Para atualizar a pauta: clique no favorito "EP Salvar Pauta" no Chrome
     com SPPILOTS aberto, depois rode python ep_atualizar.py no terminal. -->


<div id="relbox" onclick="if(event.target===this)this.style.display='none'"><div class="in" id="relin"></div></div>
<script>
var REL = __RELJSON__;
function _h(m){{m=Math.round(m);var s=m<0?'-':'';m=Math.abs(m);return s+Math.floor(m/60)+'h'+String(m%60).padStart(2,'0');}}
function _lista(L){{if(!L.length)return '<tr><td>nenhuma</td></tr>';return L.map(function(x){{return '<tr class="'+(x.fut?'fut':'')+'"><td>'+(x.ab?'<b>'+x.ab+'</b> ':'')+x.t+'</td><td>'+x.f+'</td></tr>';}}).join('');}}
function _gaps(G){{if(!G.length)return '<tr><td colspan=2>—</td></tr>';var nm={{longo:['tl','descanso longo'],ciclo:['tc','dentro do ciclo'],emendado:['te','emendado'],andamento:['ta','em andamento'],inicio:['ti','antes da 1ª'],canc:['ti','após cancelada']}};return G.map(function(g){{var t=g[3],z=nm[t],tg=z?'<span class="tg '+z[0]+'">'+z[1]+'</span> ':'';var fora=(t!=='longo'&&t!=='');return '<tr'+(fora?' class="cic"':'')+'><td>'+tg+g[0]+' → '+g[1]+'</td><td>'+(t==='emendado'?'—':_h(g[2]))+'</td></tr>';}}).join('');}}
function _hm(t){{var d=new Date(t);return String(d.getUTCHours()).padStart(2,'0')+':'+String(d.getUTCMinutes()).padStart(2,'0');}}
function _barra(r){{var W=700,X=function(t){{return (t-r.b0)/Math.max(1,(r.b1-r.b0))*W;}};
function rc(v){{return v>=480?'#2e7d32':(v>=300?'#ef8f00':'#c62828');}}
function linha(B,y){{var ms=B[0],gs=B[1],o='';gs.forEach(function(g){{var t=g[3],c;if(t==='emendado')return;
if(t==='inicio'||t==='canc')c='#d9d9d9';else if(t==='andamento')c='#7cc47f';else if(t==='ciclo')c='#f3d36b';else c=rc(g[2]);
var a=X(g[0]),b=X(g[1]);if(b-a<0.5)return;
o+='<rect x="'+a.toFixed(1)+'" y="'+y+'" width="'+(b-a).toFixed(1)+'" height="24" fill="'+c+'"><title>'+_hm(g[0])+' → '+_hm(g[1])+' · '+_h(g[2])+'</title></rect>';
if(b-a>38&&t!=='ciclo'&&t!=='inicio'&&t!=='canc')o+='<text x="'+((a+b)/2).toFixed(1)+'" y="'+(y+16)+'" text-anchor="middle" font-size="11" fill="'+(t==='andamento'?'#000':'#fff')+'">'+_h(g[2])+(t==='andamento'?'…':'')+'</text>';}});
var fa=null;ms.forEach(function(m){{var a=X(m[0]),b=X(m[1]),em=false;if(fa!==null&&a<fa){{a=fa;em=true;}}if(b<a+3)b=a+3;
o+='<rect x="'+a.toFixed(1)+'" y="'+y+'" width="'+(b-a).toFixed(1)+'" height="24" fill="#1f3a5f" stroke="#fff" stroke-width="1"><title>'+(m[2]?m[2]+' · ':'')+(m[3]||'')+' · acionamento '+_hm(m[0])+' · fim '+_hm(m[1])+'</title></rect>';
if(m[2]&&b-a>11)o+='<text x="'+((a+b)/2).toFixed(1)+'" y="'+(y+16)+'" text-anchor="middle" font-size="11" fill="#fff">'+m[2]+'</text>';
if(em)o+='<path d="M'+(a-3).toFixed(1)+' '+(y-5)+' l6 0 l-3 5 z" fill="#c62828"><title>emendada: acionada antes do fim da anterior</title></path>';fa=b;}});return o;}}
var tk='';for(var t=r.b0;t<=r.b1+60000;t+=3*3600000){{var x=X(t),an=x<12?'start':(x>W-12?'end':'middle');tk+='<line x1="'+x.toFixed(1)+'" y1="6" x2="'+x.toFixed(1)+'" y2="66" stroke="#bbb" stroke-dasharray="2,3"/><text x="'+x.toFixed(1)+'" y="78" font-size="10" text-anchor="'+an+'" fill="#555">'+_hm(t)+'</text>';}}
var dv='';if(r.d2!==r.d1){{var xd=X(r.b0+86400000);if(xd>0&&xd<W)dv='<line x1="'+xd.toFixed(1)+'" y1="4" x2="'+xd.toFixed(1)+'" y2="68" stroke="#000" stroke-width="1.5"/>';}}
return '<div class="barra"><svg viewBox="-40 0 '+(W+48)+' 84" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI,Arial">'+tk+
'<text x="-6" y="24" text-anchor="end" font-size="12" font-weight="600">E2D</text>'+linha(r.b2,8)+
'<text x="-6" y="56" text-anchor="end" font-size="12" font-weight="600">E12</text>'+linha(r.b12,40)+dv+'</svg></div>'+
'<div class="leg"><span style="background:#1f3a5f"></span>manobra (acionamento → fim + lancha)<span style="background:#2e7d32"></span>descanso ≥ 8 h<span style="background:#ef8f00"></span>5–8 h<span style="background:#c62828"></span>&lt; 5 h<span style="background:#f3d36b"></span>dentro do ciclo (A→B)<span style="background:#7cc47f"></span>em andamento<span style="background:#d9d9d9"></span>antes da 1ª manobra<span style="background:#c62828;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-top:6px solid #c62828;background:none"></span>emendada</div>';}}
function fecharRel(){{document.getElementById('relbox').style.display='none';}}
function abrirRel(p,d){{var k=REL.i[p+'|'+d],r=k&&REL.d[k];if(!r){{document.getElementById('relin').innerHTML='<span class="x" onclick="fecharRel()">×</span>Sem relatório para '+p+' neste dia (fora do turno atual).';document.getElementById('relbox').style.display='block';return;}}
var a=r.s12,b=r.s2,M=function(v){{return v===null||v===undefined?'—':_h(v);}};
var dias='';[r.d1,r.d2].filter(function(x,i,arr){{return arr.indexOf(x)===i;}}).forEach(function(dd){{var z=REL.dia[dd];if(z&&z.e2d&&z.e12)dias+='<div class="dia"><b>Dia '+dd.slice(8,10)+'/'+dd.slice(5,7)+', todos os práticos:</b> descanso longo típico da E2D <b>'+_h(z.e2d.med)+'</b> × intervalo típico da E12 <b>'+_h(z.e12.med)+'</b> · abaixo de 5 h: E2D '+z.e2d.lt5+'% × E12 '+z.e12.lt5+'%</div>';}});
var row=function(n,x,y){{return '<tr><td>'+n+'</td><td>'+x+'</td><td>'+y+'</td></tr>';}};
var h='<span class="x" onclick="fecharRel()">×</span>'+
'<b>'+r.p+' · turno '+r.ini+' → '+r.fim+'</b><br><small>'+(a.fechado?'':'Comparação até '+r.corte+' (depois disso a E12 ainda não tem nome). ')+'Descanso = do fim da manobra (início + T + lancha até a Atalaia) até o acionamento da seguinte (1 h antes). Na E2D vale o descanso longo (da B até a A); na E12, todos os intervalos (a vez volta a cada 12).</small>'+dias+
'<table><tr><th></th><th>E2D (descanso longo, da B até a A)</th><th>E12 real (todos os intervalos)</th></tr>'+
row('Descanso típico','<span class="big ok">'+M(r.c2.med)+'</span>','<span class="big">'+M(r.c12.med)+'</span>')+
row('Quantos',r.c2.n,r.c12.n)+row('Abaixo de 5 h',r.c2.lt5,r.c12.lt5)+row('Manobras',b.n,a.n)+row('Trabalho na madrugada (0h–5h)',_h(b.mad),_h(a.mad))+'</table>'+
'<b>Linha do tempo do turno</b>'+_barra(r)+
'<small>Passe o mouse (ou toque) num trecho da barra para ver a manobra ou o descanso. Fim da manobra = início + T da tabela + lancha até a Atalaia. Fora da comparação: dentro do ciclo, emendado, antes da 1ª manobra e em andamento.</small>';
document.getElementById('relin').innerHTML=h;document.getElementById('relbox').style.display='block';}}
document.addEventListener('click',function(e){{var t=e.target.closest('.relx');if(!t||e.target.closest('.obsx'))return;abrirRel(t.dataset.p,t.dataset.d);}});
</script>
{log_semanal_html}
</body>
</html>'''

    import json as _json
    html = html.replace('__RELJSON__', _json.dumps(_REL, ensure_ascii=False, default=str).replace('</', '<\\/'))
    PAINEL_PATH.write_text(html, encoding='utf-8')
    print(f'[Painel] ep_painel.html gerado')


# ── Estado ────────────────────────────────────────────────────────────────────
def ler_estado_info():
    """Lê info resumida do estado_ep_rt.pkl"""
    import pickle
    p = _DIR / 'estado_ep_rt.pkl'
    info = {'ultimo_dt': '—', 'mc': 0}
    if p.exists():
        try:
            e = pickle.load(open(p, 'rb'))
            dt = e.get('ultimo_dt')
            if dt:
                info['ultimo_dt'] = pd.Timestamp(dt).strftime('%d/%m %H:%M')
            info['mc'] = e.get('mc_prev', 0)
        except Exception:
            pass
    return info


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f'\n{"="*55}')
    print(f'EP ATUALIZAR — {datetime.now().strftime("%d/%m/%Y %H:%M")}')
    print('='*55)

    senha = obter_senha()
    coletar_sppilots(senha)
    validar_pauta_rt()
    merge_pauta()

    if not rodar_simulacao():
        print('\n✗ Erro na simulação. Abortando.')
        return

    manobras = ler_planilha()
    print(f'[Planilha] {len(manobras)} manobras lidas')

    rt_idx = info_pauta_rt()
    passadas, futuras, historico, ultima_esc, deltas_min_dia, posicoes_apos_b = montar_dados(manobras, rt_idx)
    try:
        marcar_observacao(manobras)
    except Exception as _e:
        print(f'[Observação] não calculado: {_e}')
    estado_info = ler_estado_info()
    try:
        montar_relatorio(manobras)
    except Exception as _e:
        print(f'[Relatório] não calculado: {_e}')

    gerar_painel(passadas, futuras, historico, ultima_esc, estado_info, deltas_min_dia, posicoes_apos_b)

    print(f'\n✓ Concluído!')
    print(f'   Passadas: {len(passadas)} | Futuras: {len(futuras)} | Histórico dia: {len(historico)}')

    # Abrir no Chrome (não abre quando chamado pelo atualizar.bat: ele mesmo abre no modo manual
    # e não abre nada no modo automático do agendador)
    import platform
    if os.environ.get('E2D_NAO_ABRIR') == '1':
        pass
    elif platform.system() == 'Windows':
        os.startfile(str(PAINEL_PATH))
    elif platform.system() == 'Darwin':
        subprocess.run(['open', str(PAINEL_PATH)])
    else:
        subprocess.run(['xdg-open', str(PAINEL_PATH)])


if __name__ == '__main__':
    import sys
    if '--loop' in sys.argv:
        print('Modo loop ativado (atualiza a cada 5 min). Ctrl+C para sair.')
        while True:
            try:
                main()
                print(f'\nPróxima atualização em 5 min... (Ctrl+C para sair)')
                time.sleep(300)
            except KeyboardInterrupt:
                print('\nEncerrado.')
                break
    else:
        main()
