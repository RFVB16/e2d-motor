"""comparar.py — compara a saída de uma implementação com o resultado esperado da E2D.

Uso:   python comparar.py <saida.csv> [esperado/E2D_esperado.csv]
Formato da saída (CSV UTF-8, uma linha por manobra-prático, mesma ordem/Seq da pauta de entrada):
       Seq, Data, Hora, Pratico, Navio, De, Para, Status, Escalacao
Critério de aceite: 100% de igualdade em Pratico e Status; Escalacao idealmente 100%.
"""
import sys
import pandas as pd

cand = pd.read_csv(sys.argv[1], dtype=str).fillna('')
esp = pd.read_csv(sys.argv[2] if len(sys.argv) > 2 else 'esperado/E2D_esperado.csv', dtype=str).fillna('')
m = esp.merge(cand, on='Seq', how='left', suffixes=('_esp', '_cand'))
print(f'Manobras esperadas: {len(esp)} | na saída: {len(cand)} | faltando: {m.Pratico_cand.isna().sum()}')
for col in ('Navio', 'Pratico', 'Status', 'Escalacao'):
    ok = (m[f'{col}_esp'].str.strip() == m[f'{col}_cand'].fillna('').str.strip())
    print(f'  {col:10s}: {ok.mean()*100:7.3f}% iguais ({(~ok).sum()} diferenças)')
d = m[m.Pratico_esp.str.strip() != m.Pratico_cand.fillna('').str.strip()]
if len(d):
    print('\nPrimeiras divergências de prático (a 1ª costuma ser a causa das seguintes):')
    print(d[['Seq', 'Data_esp', 'Hora_esp', 'Navio_esp', 'Pratico_esp', 'Pratico_cand', 'Escalacao_esp']].head(10).to_string(index=False))
sys.exit(0 if len(d) == 0 else 1)
