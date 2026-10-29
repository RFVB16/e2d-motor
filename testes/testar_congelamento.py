"""testar_congelamento.py — verifica a escalação congelada do motor E2D de referência.

Uso:   python testar_congelamento.py
Requer: rodar_referencia.py já funcionando (mesmos requisitos).

O que testa (resultado impresso: PASSOU / FALHOU):
  1. Congelar 300 manobras de regulares NO PRÁTICO QUE O ESPERADO JÁ TEM não pode mudar nada:
     a saída continua 100% igual a esperado/E2D_esperado.csv.
  2. Congelar UMA manobra num prático DIFERENTE (outro regular da escalação daquele horário):
     o motor tem que obedecer, ou seja, essa manobra sai com o prático forçado.
  3. Congelar um REGULAR numa manobra que a E12 dá a um ESPECIAL: o especial tem que continuar
     (especiais ficam sempre como na E12; correção de 29/10/2026).
"""
import json, os, pickle, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

AQUI = Path(__file__).resolve().parent
MOTOR = AQUI.parent / 'codigo_referencia' / 'motor_e2d'
ESPECIAIS = {'JA', 'SI', 'CH'}


def preparar(tmp):
    p = pd.read_csv(AQUI / 'entrada' / 'pauta.csv', dtype=str).sort_values('Seq', key=lambda s: s.astype(int))
    pd.DataFrame({'Data': p.Data, 'Hora': p.Hora, 'Termino': '', 'Vessel': p.Navio, 'From': p.De, 'To': p.Para}) \
      .to_excel(tmp / 'pauta.xlsx', index=False)
    e = pd.read_csv(AQUI / 'entrada' / 'especiais.csv', dtype=str)
    pd.DataFrame({'Seq': e.Seq.astype(int), 'Navio': e.Navio, 'Pratico': e.Especial}).to_excel(tmp / 'especiais.xlsx', index=False)
    T = json.load(open(AQUI / 'entrada' / 'turnos.json', encoding='utf-8'))
    for t in T:
        for k in ('dt_ini', 'dt_d2', 'dt_fim'):
            t[k] = pd.Timestamp(t[k])
    pickle.dump(T, open(tmp / 'turnos.pkl', 'wb'))


def rodar(tmp, congeladas, nome):
    fz = tmp / f'cong_{nome}.pkl'
    pickle.dump(congeladas, open(fz, 'wb'))
    env = dict(os.environ, PAUTA_FILE=str(tmp / 'pauta.xlsx'), ESP_FONTE=str(tmp / 'especiais.xlsx'),
               TURNOS=str(tmp / 'turnos.pkl'), MARGEM_ENTRADA='45', MARGEM_OUTRAS='25',
               E2D_OUT=str(tmp / f'saida_{nome}.xlsx'), FB_OUT=str(tmp / f'fb_{nome}.pkl'),
               FROZEN=str(fz), PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, 'motor_e2d.py'], cwd=str(MOTOR), env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        print(r.stderr[-3000:]); sys.exit(1)
    o = pd.read_excel(tmp / f'saida_{nome}.xlsx', dtype=str)
    o = o[pd.to_numeric(o.Seq, errors='coerce').notna()].copy()
    o['Seq'] = o.Seq.astype(int)
    return o


tmp = Path(tempfile.mkdtemp(prefix='e2d_cong_'))
preparar(tmp)
esp = pd.read_csv(AQUI / 'esperado' / 'E2D_esperado.csv', dtype=str).fillna('')
esp['Seq'] = esp.Seq.astype(int)

# só linhas de regulares cujo (Data, Hora, Navio) é único: sem ambiguidade de chave
chave = ['Data', 'Hora', 'Navio']
unicas = esp[~esp.duplicated(chave, keep=False) & ~esp.Pratico.isin(ESPECIAIS)]
amostra = unicas.iloc[::max(1, len(unicas) // 300)].head(300)
c1 = {(r.Data, r.Hora, r.Navio.strip()): [r.Pratico] for r in amostra.itertuples()}

ok = True
# teste 1
o1 = rodar(tmp, c1, 't1')
m = esp.merge(o1[['Seq', 'Pratico']], on='Seq', suffixes=('_esp', '_novo'))
dif = (m.Pratico_esp.str.strip() != m.Pratico_novo.fillna('').str.strip()).sum()
print(f'Teste 1: {len(c1)} manobras congeladas no prático esperado -> {dif} diferenças em {len(m)} manobras: '
      + ('PASSOU' if dif == 0 else 'FALHOU'))
ok &= dif == 0

# teste 2: força um outro regular da escalação daquele horário numa manobra do meio do ano
cand = unicas[unicas.Data.str.endswith('/2026') & unicas.Data.str.startswith('1')].iloc[200:]
forcado = None
for r in cand.itertuples():
    nomes = [x.split('(')[0].strip() for x in r.Escalacao.split('>')]
    outros = [n for n in nomes if n and n not in ESPECIAIS and n != r.Pratico and len(n) == 2]
    if outros:
        forcado = (r, outros[0])
        break
r, novo = forcado
o2 = rodar(tmp, {(r.Data, r.Hora, r.Navio.strip()): [novo]}, 't2')
got = o2[o2.Seq == r.Seq].Pratico.iloc[0].strip()
print(f'Teste 2: {r.Data} {r.Hora} {r.Navio}: esperado {r.Pratico}, forçado {novo}, motor deu {got}: '
      + ('PASSOU' if got == novo else 'FALHOU'))
ok &= got == novo

# teste 3: regular congelado em manobra de especial -> o especial prevalece
esp_rows = esp[esp.Pratico.isin(ESPECIAIS) & ~esp.duplicated(chave, keep=False)].iloc[100:]
r3 = esp_rows.iloc[0]
reg = next(x.split('(')[0].strip() for x in r3.Escalacao.split('>') if x.split('(')[0].strip() not in ESPECIAIS)
o3 = rodar(tmp, {(r3.Data, r3.Hora, r3.Navio.strip()): [reg]}, 't3')
got3 = o3[o3.Seq == r3.Seq].Pratico.iloc[0].strip()
m3 = esp.merge(o3[['Seq', 'Pratico']], on='Seq', suffixes=('_esp', '_novo'))
dif3 = (m3.Pratico_esp.str.strip() != m3.Pratico_novo.fillna('').str.strip()).sum()
print(f'Teste 3: {r3.Data} {r3.Hora} {r3.Navio}: especial {r3.Pratico}, congelado o regular {reg}, motor deu {got3} '
      f'({dif3} diferenças no ano): ' + ('PASSOU' if got3 == r3.Pratico and dif3 == 0 else 'FALHOU'))
ok &= got3 == r3.Pratico and dif3 == 0
sys.exit(0 if ok else 1)
