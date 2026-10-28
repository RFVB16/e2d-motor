"""
=============================================================================
EP — ESCALA POR PONTOS | Algoritmo de Alocação | Porto de Santos
=============================================================================
Versão: 1.0  |  Referência: ep_laranjas_v2.pkl (38,9% laranjas / GL 11,46h)

PARÂMETROS AJUSTÁVEIS (seção CONFIG abaixo):
  - BUFFER       : minutos de folga após manobra antes de ficar disponível
  - THRESHOLD    : pontuação acumulada para virar laranja
  - PTS_TABLE    : pontuação por par de zonas (From, To)
  - BERCO_ZONE   : mapeamento berço → zona geográfica
  - ZONE_MATRIX  : tempo de deslocamento de lancha entre zonas (min)
  - ATALAIA      : tempo fixo Atalaia ↔ FB (min)
  - BASE_DT      : datetime do início do primeiro turno
  - CICLO_H      : duração do ciclo (5 turnos × 48h = 240h)
  - N_GRUPOS     : número de grupos
  - N_POR_GRUPO  : práticos por grupo

ARQUIVOS DE ENTRADA NECESSÁRIOS:
  - man_df       : DataFrame com colunas Hora, Termino, Data, From, To (Vessel opcional)
  - T_min        : dict berço→minutos (lido de Tempo_T__2025_.xlsx)

SAÍDA:
  - DataFrame com: prat, grupo, bateu, idx, dt, prat_str, zona_to, pts_man, pts_apos
  - PKL salvo em /home/claude/ep_resultado.pkl com gl, gc, pl, man_pp
=============================================================================
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pickle

# ─────────────────────────────────────────────────────────────────────────────
# SEÇÃO CONFIG — TODOS OS PARÂMETROS AJUSTÁVEIS AQUI
# ─────────────────────────────────────────────────────────────────────────────

# ── Tempo de buffer após manobra (antes de ficar disponível) ─────────────────
BUFFER = 30          # minutos  ← ALTERE AQUI para testar buffer=15, 20, etc.

# ── Threshold de pontuação para virar laranja ────────────────────────────────
THRESHOLD = 3.0      # pontos   ← ALTERE para 2.5, 3.5, etc.

# ── Pontuação por par de zonas (mínimo, máximo) ──────────────────────────────
# Formato: (min(Z_from, Z_to), max(Z_from, Z_to)) → pontos
# Z1=FB  Z2=TERMG/TC/SAIPEM/…  Z3=EMB/OUT/CS/…  Z4=AL/BTP/…  Z5=COS/TIP/ULT
PTS_TABLE = {
    # ── Entradas / saídas (sempre com FB = Z1) ──────────────────────────────
    (1, 1): 0.0,   # FB ↔ FB       — não ocorre
    (1, 2): 1.0,   # FB ↔ Z2       — entrada/saída Z2  (3 manobras p/ laranja)
    (1, 3): 1.0,   # FB ↔ Z3       — entrada/saída Z3  (3 manobras p/ laranja)
    (1, 4): 1.5,   # FB ↔ Z4       — entrada/saída Z4  (2 manobras p/ laranja)
    (1, 5): 2.0,   # FB ↔ Z5       — entrada/saída Z5  (2 manobras p/ laranja)
    # ── Mudanças entre berços (sem FB) ──────────────────────────────────────
    (2, 2): 1.0,   # Z2 ↔ Z2       — mudança interna Z2
    (2, 3): 1.0,   # Z2 ↔ Z3       — mudança Z2–Z3
    (2, 4): 1.5,   # Z2 ↔ Z4       — mudança Z2–Z4
    (2, 5): 2.0,   # Z2 ↔ Z5       — mudança Z2–Z5
    (3, 3): 1.0,   # Z3 ↔ Z3       — mudança interna Z3
    (3, 4): 1.0,   # Z3 ↔ Z4       — mudança Z3–Z4
    (3, 5): 1.5,   # Z3 ↔ Z5       — mudança Z3–Z5
    (4, 4): 1.0,   # Z4 ↔ Z4       — mudança interna Z4
    (4, 5): 1.5,   # Z4 ↔ Z5       — mudança Z4–Z5
    (5, 5): 1.5,   # Z5 ↔ Z5       — mudança interna Z5
}
# Valor padrão para pares não mapeados:
PTS_DEFAULT = 1.0

# ── Mapeamento berço → zona geográfica ───────────────────────────────────────
BERCO_ZONE = {
    # Zona 1 — Fora da Barra (ponto de partida/chegada)
    'FB': 1,
    # Zona 2 — Canal principal (berços próximos à entrada)
    '29': 2, '29/30': 2, '29A': 2, '30': 2, '31': 2, '31/32': 2,
    '32': 2, '32/33': 2, '33': 2, '34': 2, '35.1': 2, '35.2': 2,
    '37.1': 2, '38': 2, '39': 2, 'CTRLE': 2, 'DOW': 2,
    'SAIPEM 1': 2, 'SAIPEM 1/2': 2, 'SAIPEM 2': 2, 'SAIPEM 3': 2,
    'TC 1.1': 2, 'TC 1.2': 2, 'TC 2': 2, 'TC 3': 2,
    'TEAG': 2, 'TEG': 2, 'TERMG': 2, 'TEV': 2, 'TGG': 2,
    # Zona 3 — Porto de Santos (berços internos)
    '12-A': 3, '12-P': 3, '13/14': 3, '16/17': 3, '19': 3,
    '20/21': 3, '23': 3, '25': 3, 'AGEO': 3, 'CORTE': 3,
    'CS 1': 3, 'CS 2': 3, 'CS 3': 3, 'CS 4': 3,
    'EMB-1': 3, 'EMB-2': 3, 'EMB-3': 3, 'EMB-4': 3, 'EMBR.': 3,
    'IB BC': 3, 'IB SP': 3, 'IB-OE': 3, 'OUT 2/3': 3,
    'OUT-1': 3, 'OUT-2': 3, 'OUT-3': 3, 'VAL': 3,
    # Zona 4 — Alemoa / BTP
    'AL 1': 4, 'AL 2': 4, 'AL 3': 4, 'AL 4': 4,
    'BTP-1': 4, 'BTP-2': 4, 'BTP-3': 4, 'TRSP': 4,
    # Zona 5 — Cosipa / TIP / Ultrafértil
    'COS 2': 5, 'COS 3': 5, 'COS 4': 5,
    'TIP-2': 5, 'TIP-3': 5, 'TIP-4': 5, 'ULT': 5,
}
BERCO_ZONE_DEFAULT = 2   # zona padrão para berços não mapeados

# ── Matriz de deslocamento de lancha entre zonas (minutos) ───────────────────
# Simétrica: usa (min(Za,Zb), max(Za,Zb))
ZONE_MATRIX = {
    (1, 1):  0,  (1, 2): 20,  (1, 3): 25,  (1, 4): 30,  (1, 5): 40,
    (2, 2):  0,  (2, 3):  5,  (2, 4): 10,  (2, 5): 20,
    (3, 3):  0,  (3, 4):  5,  (3, 5): 15,
    (4, 4):  0,  (4, 5): 10,
    (5, 5):  0,
}

# ── Tempo fixo Atalaia ↔ FB ───────────────────────────────────────────────────
ATALAIA = 12   # minutos

# ── Estrutura de turnos ───────────────────────────────────────────────────────
BASE_DT    = datetime(2025, 1, 2, 7, 30)  # início do turno 0 / grupo 1
CICLO_H    = 240   # horas por ciclo (5 grupos × 48h)
TURNO_H    = 48    # duração de cada turno em horas
N_GRUPOS   = 5
N_POR_GRUPO = 12   # práticos por grupo

# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES AUXILIARES (não alterar)
# ─────────────────────────────────────────────────────────────────────────────

def zona(berco: str) -> int:
    """Retorna a zona geográfica de um berço."""
    return BERCO_ZONE.get(str(berco).strip(), BERCO_ZONE_DEFAULT)

def gL(berco_a: str, berco_b: str) -> int:
    """Tempo de deslocamento de lancha entre dois berços (via zonas)."""
    za, zb = zona(berco_a), zona(berco_b)
    return ZONE_MATRIX.get((min(za, zb), max(za, zb)), 0)

# ── Tm padrão por par de zonas (mudanças sem histórico do par) ──────────────
# Mediana das 437 mudanças de 2025 com término (pauta original), agrupadas pelo
# par de zonas sem sentido, arredondada para cima em múltiplos de 5 min.
# Substitui o antigo padrão fixo de 60 min (out/2026). Z4↔Z5 não ocorre
# (petróleo/contêiner × granel) e cai no padrão final de 60 min.
TM_ZONA = {
    (2, 2): 60, (3, 3): 60, (3, 4): 60, (5, 5): 60,
    (2, 3): 65,
    (4, 4): 80,
    (2, 4): 90,
    (3, 5): 105,
    (2, 5): 130,
}
TM_ZONA_DEFAULT = 60

def tm_zona(fr: str, to: str) -> int:
    """Tm padrão para mudança cujo par de berços não está na tabela."""
    za, zb = zona(fr), zona(to)
    return TM_ZONA.get((min(za, zb), max(za, zb)), TM_ZONA_DEFAULT)

def gT(fr: str, to: str, T_min: dict, T_mud: dict | None = None) -> int:
    """
    Tempo estimado de manobra no berço.
    Para entradas (FB→berço): T do berço de destino.
    Para saídas (berço→FB):   T do berço de origem.
    Para mudanças (sem FB):   1) Tm do par na tabela de mudanças (histórico);
                              2) senão, Tm padrão do par de zonas (TM_ZONA);
                              3) senão, 60 min.
    """
    if fr == 'FB':
        return T_min.get(str(to).strip(), 60)
    if to == 'FB':
        return T_min.get(str(fr).strip(), 60)
    # Mudança berço→berço
    if T_mud:
        key = (str(fr).strip(), str(to).strip())
        if key in T_mud:
            return T_mud[key]
    return tm_zona(fr, to)  # par sem histórico: padrão por par de zonas

def r15(dt: datetime) -> datetime:
    """Arredonda datetime para o múltiplo de 15 min mais próximo (para cima se ímpar)."""
    m = dt.hour * 60 + dt.minute
    rv = round(m / 15) * 15
    d, rem = divmod(rv, 1440)
    return dt.replace(hour=rem // 60, minute=rem % 60,
                      second=0, microsecond=0) + timedelta(days=d)

def get_pts(fr: str, to: str) -> float:
    """Pontuação de uma manobra pelo par de zonas."""
    z1, z2 = zona(fr), zona(to)
    return PTS_TABLE.get((min(z1, z2), max(z1, z2)), PTS_DEFAULT)

def avail_time(last: dict | None, next_fr: str, T_min: dict,
               buf: int = BUFFER, T_mud: dict | None = None) -> datetime | None:
    """
    Calcula quando o prático fica disponível após uma manobra.
    Fórmula: r15( dt_start + gT(fr,to) + buf + gL(last_to, next_fr) )
    L é dinâmico: depende de onde o prático terminou (last_to) e onde
    começa a próxima manobra (next_fr). Ex: last_to=FB, next_fr=FB → L=0.
    """
    if last is None:
        return None
    L = gL(last['to'], next_fr)
    return r15(last['start'] + timedelta(
        minutes=gT(last['fr'], last['to'], T_min, T_mud) + buf + L))

def grp_turno(dt: datetime):
    """Retorna (grupo, turno_id) para um datetime."""
    h = (dt - BASE_DT).total_seconds() / 3600
    if h < 0:
        return None, None
    ciclo = int(h // CICLO_H)
    turno = int((h % CICLO_H) // TURNO_H)
    return turno + 1, ciclo * N_GRUPOS + turno

# ─────────────────────────────────────────────────────────────────────────────
# ALGORITMO PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def simular_ep(man_df: pd.DataFrame, T_min: dict,
               buffer: int | None = None,
               threshold: float | None = None,
               pts_table: dict | None = None,
               T_mud: dict | None = None,
               verbose: bool = True) -> pd.DataFrame:
    """
    Simula a Escala por Pontos (EP) para um conjunto de manobras.

    Parâmetros
    ----------
    man_df    : DataFrame com colunas obrigatórias:
                  - 'datetime' (pd.Timestamp) : hora de início (PoB)
                  - 'From' (str)              : berço de origem
                  - 'To'   (str)              : berço de destino
    T_min     : dict berço→int com o tempo estimado de manobra por berço
    buffer    : sobrescreve BUFFER global (None = usa CONFIG)
    threshold : sobrescreve THRESHOLD global (None = usa CONFIG)
    pts_table : sobrescreve PTS_TABLE global (None = usa CONFIG)
    verbose   : imprime progresso

    Retorna
    -------
    DataFrame com uma linha por manobra:
      prat      : ID numérico do prático (1–60)
      grupo     : grupo (1–5)
      turno_id  : índice sequencial do turno
      bateu     : bool — atingiu threshold (virou laranja)
      idx       : índice original no man_df
      dt        : datetime da manobra
      prat_str  : 'P01'…'P60'
      zona_to   : zona de destino (1–5)
      pts_man   : pontos desta manobra
      pts_apos  : acumulado após esta manobra (0 se bateu, else acumulado)

    Algoritmo de Fila (detalhado)
    -----------------------------
    Para cada grupo independente (G1–G5), mantém estado contínuo ao longo do ano:

      Estado por prático:
        pts[p]        : pontuação acumulada (preservada entre turnos)
        last[p]       : dict {'start', 'fr', 'to'} da última manobra
        thresh_seq[p] : número de sequência do último laranja (0 se não-laranja)

      Estado global do grupo:
        thresh_ctr    : contador global de laranjas (para ordenação por ordem de entrada)

      Seleção do prático para cada manobra:
        1. Calcula avail_time(last[p], m_fr) para todos os práticos
        2. Ordena pelo sort_key:

           Prioridade 0 — disponível, não-laranja, avail ≤ m_dt:
             (0, avail.timestamp(), p)  → quem ficou disponível primeiro

           Prioridade 1 — nunca trabalhou (avail=None), não-laranja:
             (1, 0, p)                  → ordem de ID (P01 < P02 < ...)

           Prioridade 2 — disponível, laranja (thresh_seq > 0):
             (2, thresh_seq, p)         → quem virou laranja primeiro retorna primeiro

           Prioridade 3 — não disponível ainda:
             (3, avail.timestamp(), p)  → fallback: quem fica disponível mais cedo

        3. O prático selecionado é sempre sorted(all, key=sort_key)[0]
           (não há pop/insert explícito — a fila é reordenada a cada manobra)

      Após a manobra:
        pts_novo = pts[p] + pts_man
        se pts_novo >= threshold:
          bateu = True
          pts[p] = round(pts_novo - threshold, 2)  ← resíduo preservado
          thresh_ctr += 1
          thresh_seq[p] = thresh_ctr               ← entra na fila laranja
        senão:
          thresh_seq[p] = 0                        ← volta para fila normal

      Estado é preservado entre turnos (não há reinicialização a cada 48h).
    """
    # Parâmetros da execução (sobrescreve globals se fornecido)
    BUF = buffer    if buffer    is not None else BUFFER
    THR = threshold if threshold is not None else THRESHOLD
    PTS = pts_table if pts_table is not None else PTS_TABLE

    # Pontuação por tempo (mudanças berço→berço)
    def _pts_por_tm(tm_min: int) -> float:
        if tm_min < 90:   return 1.0   # Tm < 1,5h
        if tm_min < 120:  return 1.5   # 1,5h ≤ Tm < 2h
        return 2.0                      # Tm ≥ 2h

    # Função de pontuação local
    def _pts(fr, to):
        # Mudança berço→berço: usar Tm da tabela se disponível
        if fr != 'FB' and to != 'FB' and T_mud:
            tm = T_mud.get((str(fr).strip(), str(to).strip()))
            if tm is not None:
                return _pts_por_tm(tm)
            # Mudança não listada: Tm padrão do par de zonas
            return _pts_por_tm(tm_zona(fr, to))
        # Entrada ou saída: pontuação por par de zonas
        z1, z2 = zona(fr), zona(to)
        return PTS.get((min(z1, z2), max(z1, z2)), PTS_DEFAULT)

    # Garantir que man_df está ordenado por datetime
    man_df = man_df.sort_values('datetime', kind='stable').reset_index(drop=True)

    # Inicialização dos estados por grupo
    def _init_grupo(g):
        base = (g - 1) * N_POR_GRUPO + 1
        praticos = list(range(base, base + N_POR_GRUPO))
        return {
            'praticos': praticos,
            'pts':       {p: 0.0 for p in praticos},
            'last':      {p: None for p in praticos},
            'thresh_seq': {p: 0 for p in praticos},
            'thresh_ctr': 0,
        }

    estados = {g: _init_grupo(g) for g in range(1, N_GRUPOS + 1)}
    rows = []

    for idx, row in man_df.iterrows():
        m_dt = row['datetime']
        m_fr = str(row['From']).strip()
        m_to = str(row['To']).strip()

        g, turno_id = grp_turno(m_dt)
        if g is None:
            continue

        e = estados[g]
        praticos = e['praticos']

        # Calcular disponibilidade de cada prático para ESTA manobra (L dinâmico)
        avails = {p: avail_time(e['last'][p], m_fr, T_min, BUF, T_mud) for p in praticos}

        # Função de ordenação — define a fila EP
        def sort_key(p):
            at = avails[p]
            ts = e['thresh_seq'][p]
            disponivel = (at is None) or (at <= m_dt)
            nunca_trab = (at is None)

            if disponivel and not nunca_trab and ts == 0:
                # Normal, disponível: prioriza quem ficou livre mais cedo
                return (0, at.timestamp(), p)
            elif nunca_trab and ts == 0:
                # Nunca trabalhou: antes de todos os disponíveis (ordem de ID)
                return (1, 0, p)
            elif disponivel and ts > 0:
                # Laranja disponível: quem virou laranja primeiro sai primeiro
                return (2, ts, p)
            else:
                # Não disponível: quem ficará disponível mais cedo
                return (3, at.timestamp() if at else 0, p)

        # Selecionar prático
        prat = sorted(praticos, key=sort_key)[0]

        # Calcular pontuação
        pts_man = _pts(m_fr, m_to)
        pts_antes = e['pts'][prat]
        pts_novo = pts_antes + pts_man
        bateu = pts_novo >= THR

        # Atualizar estado
        e['pts'][prat]  = round(pts_novo - THR, 2) if bateu else round(pts_novo, 2)
        e['last'][prat] = {'start': m_dt, 'fr': m_fr, 'to': m_to}

        if bateu:
            e['thresh_ctr'] += 1
            e['thresh_seq'][prat] = e['thresh_ctr']
        else:
            e['thresh_seq'][prat] = 0

        rows.append({
            'prat':      prat,
            'grupo':     g,
            'turno_id':  turno_id,
            'bateu':     bateu,
            'idx':       idx,
            'dt':        m_dt,
            'prat_str':  f'P{prat:02d}',
            'zona_to':   zona(m_to),
            'pts_man':   pts_man,
            'pts_apos':  round(pts_novo, 2),
        })

    df = pd.DataFrame(rows)

    if verbose:
        n_lar = df['bateu'].sum()
        print(f"  EP simulada: {len(df):,} manobras | {n_lar:,} laranjas ({n_lar/len(df)*100:.1f}%)")
        print(f"  Parâmetros: buffer={BUF}min | threshold={THR} | PTS default={PTS_DEFAULT}")

    return df

# ─────────────────────────────────────────────────────────────────────────────
# ANÁLISE — GL / GC / PL e métricas padrão
# ─────────────────────────────────────────────────────────────────────────────

def calcular_metricas(df: pd.DataFrame, man_df: pd.DataFrame,
                      sg: float = 50.0) -> dict:
    """
    Calcula as métricas principais de descanso a partir do resultado da simulação.

    Parâmetros
    ----------
    df     : resultado de simular_ep()
    man_df : DataFrame original com coluna 'dt_fim' (término real)
    sg     : limite superior de gap para considerar (horas); default 50h

    Retorna dict com:
      gl     : array de descansos longos (pós-laranja), horas
      gc     : array de descansos curtos (entre laranja), horas
      pl     : array de posições na fila quando cada laranja retornou
      man_pp : Series prat_str → n_manobras
      stats  : dict com resumo
    """
    gl, gc, pl = [], [], []

    for (p, g), gd in df.groupby(['prat', 'grupo']):
        gd = gd.sort_values('dt').reset_index(drop=True)
        pos = 0
        for i in range(len(gd) - 1):
            pos += 1
            # Descanso = do término real da manobra i ao início da manobra i+1
            orig_i = man_df.iloc[int(gd.iloc[i]['idx'])]
            dt_fim_i = orig_i.get('dt_fim', gd.iloc[i]['dt'])
            gh = (gd.iloc[i + 1]['dt'] - dt_fim_i).total_seconds() / 3600
            if 0 < gh < sg:
                if gd.iloc[i]['bateu']:
                    gl.append(gh)
                    pl.append(pos)
                    pos = 0
                else:
                    gc.append(gh)

    gl = np.array(gl)
    gc = np.array(gc)
    pl = np.array(pl)
    man_pp = df.groupby('prat_str').size()

    stats = {
        'n_laranjas':    df['bateu'].sum(),
        'pct_laranjas':  df['bateu'].mean() * 100,
        'gl_media':      gl.mean() if len(gl) else 0,
        'gl_mediana':    float(np.median(gl)) if len(gl) else 0,
        'gl_gt8_pct':    (gl > 8).mean() * 100 if len(gl) else 0,
        'gl_lt6_pct':    (gl < 6).mean() * 100 if len(gl) else 0,
        'gc_media':      gc.mean() if len(gc) else 0,
        'contraste_lc':  (gl.mean() - gc.mean()) if len(gl) and len(gc) else 0,
        'pl_media':      pl.mean() if len(pl) else 0,
        'pl_gt18_pct':   (pl > 18).mean() * 100 if len(pl) else 0,
        'man_std':       man_pp.std(),
        'man_amp':       int(man_pp.max() - man_pp.min()),
        'man_cv_pct':    man_pp.std() / man_pp.mean() * 100,
    }
    return {'gl': gl, 'gc': gc, 'pl': pl, 'man_pp': man_pp, 'stats': stats}

def imprimir_relatorio(metricas: dict):
    """Imprime tabela resumo das métricas EP."""
    s = metricas['stats']
    print("\n" + "=" * 55)
    print(f"  {'MÉTRICA':<35} {'VALOR':>12}")
    print("-" * 55)
    print(f"  {'Laranjas (n / %)':<35} {s['n_laranjas']:>8,}  ({s['pct_laranjas']:.1f}%)")
    print(f"  {'GL média (h)':<35} {s['gl_media']:>12.2f}")
    print(f"  {'GL mediana (h)':<35} {s['gl_mediana']:>12.2f}")
    print(f"  {'GL > 8h (%)':<35} {s['gl_gt8_pct']:>12.1f}")
    print(f"  {'GL < 6h (%)':<35} {s['gl_lt6_pct']:>12.1f}")
    print(f"  {'GC média (h)':<35} {s['gc_media']:>12.2f}")
    print(f"  {'Contraste longo–curto (h)':<35} {s['contraste_lc']:>12.2f}")
    print(f"  {'Posições médias (longo)':<35} {s['pl_media']:>12.1f}")
    print(f"  {'Posições > 18 (%)':<35} {s['pl_gt18_pct']:>12.1f}")
    print(f"  {'Std manobras/prático':<35} {s['man_std']:>12.1f}")
    print(f"  {'Amplitude manobras':<35} {s['man_amp']:>12}")
    print(f"  {'CV manobras (%)':<35} {s['man_cv_pct']:>12.1f}")
    print("=" * 55)

# ─────────────────────────────────────────────────────────────────────────────
# EXECUÇÃO DIRETA — carrega dados e roda a simulação
# ─────────────────────────────────────────────────────────────────────────────

def _achar_arquivo(nomes_possiveis):
    """Procura um arquivo em locais comuns. Retorna o primeiro encontrado."""
    import os
    locais = ['inputs', '.', '..', '../inputs', '../01_dados_entrada']
    for nome in nomes_possiveis:
        for loc in locais:
            caminho = os.path.join(loc, nome)
            if os.path.exists(caminho):
                return caminho
    raise FileNotFoundError(
        f"Nenhum dos arquivos {nomes_possiveis} foi encontrado em {locais}. "
        f"Coloque o arquivo em uma dessas pastas."
    )


def carregar_dados():
    """Carrega man_df e T_min dos arquivos originais."""
    arq_manobras = _achar_arquivo([
        'Manobras_2025__original_.xlsx',
        'Manobras_2025_original.xlsx',
        'Pauta_de_Manobra_2025.xlsx',
    ])
    arq_tempo = _achar_arquivo([
        'Tempo_T__2025_.xlsx',
        'Tempo_T_2025.xlsx',
    ])
    
    man_df = pd.read_excel(arq_manobras)
    
    # Normalizar nomes de colunas (alguns arquivos usam De/Para, outros From/To)
    rename_map = {}
    if 'De' in man_df.columns and 'From' not in man_df.columns:
        rename_map['De'] = 'From'
    if 'Para' in man_df.columns and 'To' not in man_df.columns:
        rename_map['Para'] = 'To'
    if rename_map:
        man_df = man_df.rename(columns=rename_map)
    
    # Validar que temos as colunas essenciais
    obrigatorias = ['Data', 'Hora', 'From', 'To']
    faltando = [c for c in obrigatorias if c not in man_df.columns]
    if faltando:
        raise ValueError(
            f"Arquivo {arq_manobras} nao tem as colunas: {faltando}. "
            f"Colunas presentes: {list(man_df.columns)}"
        )
    
    man_df['datetime'] = pd.to_datetime(
        man_df['Data'] + ' ' + man_df['Hora'], format='%d/%m/%Y %H:%M')
    # Termino pode estar ausente ou NaN — usa Hora como fallback
    if 'Termino' in man_df.columns:
        man_df['Termino'] = man_df['Termino'].fillna(man_df['Hora'])
        man_df['dt_fim'] = pd.to_datetime(
            man_df['Data'] + ' ' + man_df['Termino'].astype(str), format='%d/%m/%Y %H:%M', errors='coerce')
        man_df['dt_fim'] = man_df['dt_fim'].fillna(man_df['datetime'])
        man_df.loc[man_df['dt_fim'] < man_df['datetime'], 'dt_fim'] += timedelta(days=1)
    else:
        man_df['dt_fim'] = man_df['datetime']
    man_df['From'] = man_df['From'].astype(str).str.strip()
    man_df['To']   = man_df['To'].astype(str).str.strip()
    man_df = man_df.sort_values('datetime', kind='stable').reset_index(drop=True)

    T_df = pd.read_excel(arq_tempo, sheet_name='T Entrada ou saída')
    T_min = {
        str(r['Berço']).strip(): int(r['T - TEMPO (min)'])
        for _, r in T_df.iterrows()
        if pd.notna(r['Berço']) and pd.notna(r['T - TEMPO (min)'])
    }

    # Tabela de mudanças berço→berço
    T_mud_df = pd.read_excel(arq_tempo, sheet_name='Mudanças de entre berços')
    T_mud_df = T_mud_df.dropna(subset=['De', 'Para', 'Tm (min)'])
    T_mud = {
        (str(r['De']).strip(), str(r['Para']).strip()): int(r['Tm (min)'])
        for _, r in T_mud_df.iterrows()
    }

    return man_df, T_min, T_mud


def salvar_resultado(df: pd.DataFrame, metricas: dict,
                     out_path: str = '/home/claude/ep_resultado.pkl'):
    """Salva resultado em PKL para uso posterior."""
    payload = {
        'df':      df,
        'gl':      metricas['gl'],
        'gc':      metricas['gc'],
        'pl':      metricas['pl'],
        'man_pp':  metricas['man_pp'],
        'stats':   metricas['stats'],
        # Registra os parâmetros usados
        'params':  {
            'BUFFER':    BUFFER,
            'THRESHOLD': THRESHOLD,
            'PTS_TABLE': PTS_TABLE,
        },
    }
    with open(out_path, 'wb') as f:
        pickle.dump(payload, f)
    print(f"  Salvo em {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("Carregando dados...")
    man_df, T_min = carregar_dados()
    print(f"  {len(man_df):,} manobras | {len(T_min)} berços com T")

    print(f"\nSimulando EP (buffer={BUFFER}min, threshold={THRESHOLD})...")
    df_ep = simular_ep(man_df, T_min)

    print("\nCalculando métricas...")
    met = calcular_metricas(df_ep, man_df)
    imprimir_relatorio(met)

    salvar_resultado(df_ep, met)
    print("\nConcluído.")
