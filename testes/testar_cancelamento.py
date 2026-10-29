"""testar_cancelamento.py — verifica a regra da manobra cancelada depois da escalação (29/10/2026).

Uso:   python testar_cancelamento.py
Regra: manobra cancelada depois da escalação (linha verde no SPPilots) não conta como manobra. O prático
escalado nela vai para a FRENTE da fila e só pode pegar manobra que comece a partir de 1 h depois de o
cancelamento ser visto (as anteriores já estavam escaladas). O ciclo dele (A/B) não muda.

Para uma A e para uma B do conjunto de teste, simula o cancelamento visto 30 min antes do início e confere:
  1. tudo antes da manobra cancelada fica igual ao esperado;
  2. a manobra cancelada sai com status CA/CB (C + o que ela seria) e com o prático que estava escalado;
  3. logo depois dela, esse prático é o 1º da fila;
  4. ele não pega nenhuma manobra que comece antes de (visto + 1 h);
  5. a próxima manobra dele tem o mesmo status (A/B) que a cancelada teria: ela não contou.
"""
import json, os, pickle, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

AQUI = Path(__file__).resolve().parent
MOTOR = AQUI.parent / 'codigo_referencia' / 'motor_e2d'
ESPECIAIS = {'JA', 'SI', 'CH'}
tmp = Path(tempfile.mkdtemp(prefix='e2d_canc_'))

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


def rodar(cancel, nome):
    cp = tmp / f'canc_{nome}.pkl'; pickle.dump(cancel, open(cp, 'wb'))
    env = dict(os.environ, PAUTA_FILE=str(tmp / 'pauta.xlsx'), ESP_FONTE=str(tmp / 'especiais.xlsx'),
               TURNOS=str(tmp / 'turnos.pkl'), MARGEM_ENTRADA='45', MARGEM_OUTRAS='25',
               E2D_OUT=str(tmp / f'saida_{nome}.xlsx'), FB_OUT=str(tmp / f'fb_{nome}.pkl'),
               CANCEL=str(cp), PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, 'motor_e2d.py'], cwd=str(MOTOR), env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        print(r.stderr[-3000:]); sys.exit(1)
    o = pd.read_excel(tmp / f'saida_{nome}.xlsx', dtype=str)
    o = o[pd.to_numeric(o.Seq, errors='coerce').notna()].copy()
    o['Seq'] = o.Seq.astype(int); o['Status'] = o.Status.fillna('')
    o['dt'] = pd.to_datetime(o.Data + ' ' + o.Hora, dayfirst=True)
    return o


esp = pd.read_csv(AQUI / 'esperado' / 'E2D_esperado.csv', dtype=str).fillna('')
esp['Seq'] = esp.Seq.astype(int); esp['dt'] = pd.to_datetime(esp.Data + ' ' + esp.Hora, dayfirst=True)
unicas = esp[~esp.duplicated(['Data', 'Hora', 'Navio'], keep=False) & ~esp.Pratico.isin(ESPECIAIS)]
ok = True
for st, frac in (('A', 1 / 3), ('B', 2 / 3)):
    cand = unicas[unicas.Status == st]
    r = cand.iloc[int(len(cand) * frac)]
    visto = r['dt'] - pd.Timedelta(minutes=30); lim = visto + pd.Timedelta(hours=1)
    o = rodar({(r.Data, r.Hora, r.Navio.strip()): {'visto_em': visto.strftime('%Y-%m-%d %H:%M')}}, st)
    antes = esp[esp.Seq < r.Seq].merge(o[['Seq', 'Pratico', 'Status']], on='Seq', suffixes=('', '_n'))
    t1 = (antes.Pratico == antes.Pratico_n).all() and (antes.Status == antes.Status_n).all()
    c = o[o.Seq == r.Seq].iloc[0]
    t2 = c.Status == 'C' + st and c.Pratico.strip() == r.Pratico
    t3 = c.Escalacao.split('>')[0].split('(')[0].strip() == r.Pratico
    dele = o[(o.Pratico.str.strip() == r.Pratico) & (o.Seq > r.Seq)]
    t4 = dele[dele.dt < lim].empty
    prox = dele.iloc[0] if len(dele) else None
    t5 = prox is not None and prox.Status == st
    passou = all((t1, t2, t3, t4, t5)); ok &= passou
    print(f'Cancelada {st}: {r.Data} {r.Hora} {r.Navio} ({r.Pratico}), vista {visto:%H:%M} -> '
          f'antes igual: {t1} | status C+A/B e mesmo prático: {t2} | 1º da fila: {t3} | nada antes de {lim:%H:%M}: {t4} | '
          f'próxima dele ({prox.Data} {prox.Hora}, {prox.Status}) com o mesmo status: {t5} -> ' + ('PASSOU' if passou else 'FALHOU'))
sys.exit(0 if ok else 1)
