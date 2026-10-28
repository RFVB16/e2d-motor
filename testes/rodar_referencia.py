"""rodar_referencia.py — roda o motor E2D de REFERÊNCIA (Python) sobre o conjunto de teste.

Uso:   python rodar_referencia.py
Lê:    entrada/pauta.csv, entrada/especiais.csv, entrada/turnos.json
Gera:  saida_referencia.csv  (mesmas colunas de esperado/E2D_esperado.csv)
Depois: python comparar.py saida_referencia.csv   -> deve dar 100%

Requisitos: Python 3.10+, pandas, openpyxl, xlsxwriter.
"""
import json, os, pickle, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

AQUI = Path(__file__).resolve().parent
MOTOR = AQUI.parent / 'codigo_referencia' / 'motor_e2d'
tmp = Path(tempfile.mkdtemp(prefix='e2d_'))

# 1. pauta no formato do motor (Data, Hora, Termino, Vessel, From, To), na ordem do arquivo
p = pd.read_csv(AQUI / 'entrada' / 'pauta.csv', dtype=str).sort_values('Seq', key=lambda s: s.astype(int))
pd.DataFrame({'Data': p.Data, 'Hora': p.Hora, 'Termino': '', 'Vessel': p.Navio, 'From': p.De, 'To': p.Para}) \
  .to_excel(tmp / 'pauta.xlsx', index=False)
# 2. especiais fixos (Seq, Navio, Pratico)
e = pd.read_csv(AQUI / 'entrada' / 'especiais.csv', dtype=str)
pd.DataFrame({'Seq': e.Seq.astype(int), 'Navio': e.Navio, 'Pratico': e.Especial}).to_excel(tmp / 'especiais.xlsx', index=False)
# 3. turnos
T = json.load(open(AQUI / 'entrada' / 'turnos.json', encoding='utf-8'))
for t in T:
    for k in ('dt_ini', 'dt_d2', 'dt_fim'):
        t[k] = pd.Timestamp(t[k])
pickle.dump(T, open(tmp / 'turnos.pkl', 'wb'))

env = dict(os.environ, PAUTA_FILE=str(tmp / 'pauta.xlsx'), ESP_FONTE=str(tmp / 'especiais.xlsx'),
           TURNOS=str(tmp / 'turnos.pkl'), MARGEM_ENTRADA='45', MARGEM_OUTRAS='25',
           E2D_OUT=str(tmp / 'saida.xlsx'), FB_OUT=str(tmp / 'fallback.pkl'), PYTHONIOENCODING='utf-8')
r = subprocess.run([sys.executable, 'motor_e2d.py'], cwd=str(MOTOR), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout[-800:]);
if r.returncode:
    print(r.stderr[-3000:]); sys.exit(1)
o = pd.read_excel(tmp / 'saida.xlsx')
o = o[pd.to_numeric(o.Seq, errors='coerce').notna()][['Seq', 'Data', 'Hora', 'Pratico', 'Navio', 'De', 'Para', 'Status', 'Escalacao']]
o['Seq'] = o.Seq.astype(int)
o.to_csv(AQUI / 'saida_referencia.csv', index=False, encoding='utf-8')
print(f'OK -> {AQUI / "saida_referencia.csv"} ({len(o)} manobras)')
