"""
carregar_pauta.py — Carrega Pauta_de_Manobra_2025.xlsx como fonte master de manobras.

Estrutura: #, Data, Hora, Termino, Vessel, De, Para

Retorna:
  man_df  — DataFrame com colunas: datetime, Data, Hora, Termino, dt_fim, Vessel, From, To
  pares2  — set de (datetime, Vessel) com 2 práticos
"""

import pandas as pd
from datetime import datetime, timedelta

import os
def _find_pauta():
    cands = ['Manobras_2025__original_completa.xlsx',
             os.path.join('inputs','Manobras_2025__original_completa.xlsx'),
             os.path.join('..','inputs','Manobras_2025__original_completa.xlsx'),
             os.path.join('..','01_dados_entrada','Manobras_2025__original_completa.xlsx'),
             '/mnt/user-data/uploads/Manobras_2025__original_completa.xlsx']
    for c in cands:
        if os.path.exists(c): return c
    return cands[0]
PAUTA_PATH = __import__('os').environ.get('PAUTA_FILE') or _find_pauta()


def carregar_pauta(path=PAUTA_PATH):
    df = pd.read_excel(path)
    # Mapear colunas From/To -> De/Para (pauta-mestra usa From/To), sem reordenar
    df = df.rename(columns={'From': 'De', 'To': 'Para'})

    linhas = []
    for _, r in df.iterrows():
        data_s = str(r['Data']).strip()
        hora_s = str(r['Hora']).strip()
        vessel  = str(r['Vessel']).strip()
        fr      = str(r['De']).strip()
        to      = str(r['Para']).strip()
        term    = r['Termino']

        # Parse datetime — dayfirst=True para formato DD/MM/YYYY
        try:
            dt = datetime.strptime(f'{data_s} {hora_s}', '%d/%m/%Y %H:%M')
            dt = pd.Timestamp(dt)
        except Exception:
            continue

        # Termino como string HH:MM e como datetime dt_fim
        term_str = ''
        dt_fim   = None
        if pd.notna(term):
            try:
                t = datetime.strptime(str(term).strip(), '%H:%M')
                dt_fim = dt.replace(hour=t.hour, minute=t.minute)
                if dt_fim <= dt:
                    dt_fim += timedelta(days=1)
                term_str = t.strftime('%H:%M')
            except Exception:
                pass

        linhas.append({
            'datetime': dt,
            'Data':     data_s,        # mantém DD/MM/YYYY original
            'Hora':     hora_s,
            'Termino':  term_str,
            'dt_fim':   dt_fim,
            'Vessel':   vessel,
            'From':     fr,
            'To':       to,
        })

    man_df = pd.DataFrame(linhas)
    man_df = man_df.sort_values('datetime', kind='stable').reset_index(drop=True)

    g = man_df.groupby(['datetime', 'Vessel']).size()
    pares2 = set((dt, v) for (dt, v), n in g.items() if n == 2)

    print(f'Pauta: {len(man_df)} manobras | {len(pares2)} navios de 2 práticos')
    return man_df, pares2
