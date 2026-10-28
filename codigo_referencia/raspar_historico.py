"""
raspar_historico.py — Raspa histórico de manobras do SPPILOTS.

Colunas confirmadas via DevTools (01/01→07/01/2026):
  tds[2]  – NOME DO NAVIO
  tds[3]  – E/S/M
  tds[4]  – LOC#1 (berco)
  tds[5]  – LOC#2 (destino para M)
  tds[6]  – HORÁRIO (DD/MM HH:MM)
  tds[11] – PRA (práticos)
  tds[12] – CAL  tds[13] – BRD  tds[15] – AGENTE  tds[16] – OBS

Tabela identificada pelo <tr style="...#cccccc..."> com "NOME DO NAVIO".
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import re, getpass, time

BASE_URL   = 'https://sts.sppilots.com.br'
LOGIN_URL  = f'{BASE_URL}/default.asp'
HIST_URL   = f'{BASE_URL}/sources/manobra/psh.asp'
USUARIO    = 'villasboas'

DATA_INICIO = datetime(2026, 1, 1)
DATA_FIM    = datetime.now()
BLOCO_DIAS  = 7
PAUSA_S     = 2
OUTPUT      = 'historico_2026.csv'

STATUS_MAP = {
    '#ff4a4a': 'EXECUTADO',
    '#33ccff': 'EXECUTADO',
    '#b7b7ff': 'CONFIRMADO',
    '#ffffff': 'AGENDADO',
    '#ff0099': 'ESPECIAL',
    '#66cc66': 'CANCELADA',    # verde = manobra cancelada (nao entra no pipeline)
    '#ffff00': 'SEM_PRATICO',  # amarelo = nao usa pratico (nao entra no pipeline)
    '#000000': 'ESPECIAL',
}

# Cores cuja manobra NAO deve entrar na pauta nem no historico do EP:
#   verde  (#66cc66): manobra cancelada
#   amarelo (#ffff00): manobra sem pratico (ex.: "OPERACIONAL", "LADO BARRA")
CORES_IGNORAR = {'#66cc66', '#ffff00'}


def fazer_login(senha):
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'})
    r = s.post(LOGIN_URL, data={'userid': USUARIO, 'password': senha,
                                'cmd': 'LOG', 'act': ''}, timeout=15)
    if 'SAIR' not in r.text:
        raise RuntimeError('Login falhou.')
    print('[OK] Login')
    return s


def extrair_cor(style):
    m = re.search(r'background\s*:\s*(#[0-9a-fA-F]{6})', style or '')
    return m.group(1).lower() if m else '#ffffff'


def buscar_tabela_manobras(soup):
    """
    Localiza as tabelas cujo cabecalho tem background #cccccc e 'NOME DO NAVIO'.
    O SPPILOTS gera uma tabela separada por dia quando ha multiplos dias no range.
    Retorna um pseudo-container com .find_all('tr') juntando as linhas de todas.
    """
    tabelas = []
    for tr in soup.find_all('tr'):
        if '#cccccc' in tr.get('style', '') and 'NOME DO NAVIO' in tr.get_text():
            tabela = tr.find_parent('table')
            if tabela is not None and tabela not in tabelas:
                tabelas.append(tabela)

    if not tabelas:
        return None

    # Wrapper que responde a .find_all('tr') agregando todas as tabelas
    class _MultiTabela:
        def __init__(self, tabs): self._tabs = tabs
        def find_all(self, name):
            out = []
            for t in self._tabs:
                out.extend(t.find_all(name))
            return out

    return _MultiTabela(tabelas)


def raspar_bloco(sessao, dt_ini, dt_fim, ano=2026):
    dti = dt_ini.strftime('%d/%m/%Y')
    dtf = dt_fim.strftime('%d/%m/%Y')
    url = f'{HIST_URL}?cmd=&act=ALL&dti={dti}&dtf={dtf}&x=4&y=4'

    for tentativa in range(3):
        try:
            r = sessao.get(url, timeout=60)
            break
        except Exception as e:
            print(f'  [ERRO tentativa {tentativa+1}/3] {dti}>{dtf}: {e}')
            if tentativa < 2: time.sleep(5)
            else: return []

    soup   = BeautifulSoup(r.text, 'html.parser')
    tabela = buscar_tabela_manobras(soup)

    if tabela is None:
        print(f'  [AVISO] {dti}>{dtf}: tabela nao encontrada')
        return []

    registros = []
    for tr in tabela.find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 7:
            continue

        es = tds[3].get_text(strip=True).upper() if len(tds) > 3 else ''
        if es not in ('E', 'S', 'M'):
            continue

        # Filtra manobras que NAO entram no pipeline EP:
        #   verde  (#66cc66): cancelada
        #   amarelo (#ffff00): sem pratico
        cor = extrair_cor(tr.get('style', ''))
        if cor in CORES_IGNORAR:
            continue

        vessel_td = tds[2].get_text(separator=' ', strip=True)
        vessel    = re.sub(r'\(2\s*PR[AaÁá]TICOS?\)', '', vessel_td, flags=re.I).strip()

        berco  = re.sub(r'\s+', ' ', tds[4].get_text(strip=True)).strip()
        berco2 = tds[5].get_text(strip=True) if len(tds) > 5 else ''

        try:
            dt = datetime.strptime(
                f'{tds[6].get_text(strip=True)}/{ano}', '%d/%m %H:%M/%Y')
        except Exception:
            continue

        pra_raw  = tds[11].get_text(strip=True) if len(tds) > 11 else ''
        praticos = pra_raw.split()
        calado   = tds[12].get_text(strip=True) if len(tds) > 12 else ''
        bordo    = tds[13].get_text(strip=True) if len(tds) > 13 else ''
        agente   = tds[15].get_text(strip=True) if len(tds) > 15 else ''
        obs      = tds[16].get_text(separator=' ', strip=True) if len(tds) > 16 else ''

        # Detecta 2 práticos: 2 bigramas (2 letras maiúsculas) em tds[11] OU "2PLT" no OBS
        # Fix do bug: antes procurava "2 PRAT" em vessel_td (nunca casava)
        bigramas  = [p for p in praticos if re.fullmatch(r'[A-Z]{2}', p)]
        dois_prat = len(bigramas) >= 2 or bool(re.search(r'2\s*PLT', obs, re.I))

        status = STATUS_MAP.get(cor, 'AGENDADO')

        if es == 'E':
            fr, to = 'FB', berco
        elif es == 'S':
            fr, to = berco, 'FB'
        else:
            fr, to = berco, (berco2 if berco2 else berco)

        base = dict(datetime=pd.Timestamp(dt), Data=dt.strftime('%d/%m/%Y'),
                    Hora=dt.strftime('%H:%M'), Vessel=vessel, ES=es,
                    Berco=berco, Berco2=berco2, From=fr, To=to,
                    Calado=calado, Bordo=bordo, Agente=agente,
                    Obs=obs, Status=status, dois_prat=dois_prat)

        if dois_prat and len(praticos) >= 2:
            for pra in praticos[:2]:
                rec = dict(base); rec['Pratico'] = pra
                registros.append(rec)
        else:
            base['Pratico'] = praticos[0] if praticos else ''
            registros.append(base)

    return registros


def raspar_tudo(senha, output=None):
    if output is None: output = OUTPUT
    # Incremental: só raspa a partir da última data do CSV existente
    import os, pathlib
    data_inicio = DATA_INICIO
    todos_existentes = []
    if os.path.exists(output):
        df_ex = pd.read_csv(output)
        if len(df_ex) > 0:
            df_ex['datetime'] = pd.to_datetime(df_ex['datetime'])
            ultima = df_ex['datetime'].max()
            data_inicio = ultima.to_pydatetime() - timedelta(days=1)  # sobreposição 1 dia
            todos_existentes = df_ex.to_dict('records')
            print(f'[Incremental] Histórico existente até {ultima:%d/%m %H:%M} ({len(df_ex)} manobras)')

    sessao = fazer_login(senha)
    todos, dt = [], data_inicio
    total_blocos = ((DATA_FIM - DATA_INICIO).days // BLOCO_DIAS) + 1
    print(f'Raspando {DATA_INICIO:%d/%m} > {DATA_FIM:%d/%m} '
          f'em blocos de {BLOCO_DIAS} dias ({total_blocos} blocos)...\n')

    bloco = 0
    while dt <= DATA_FIM:
        fim = min(dt + timedelta(days=BLOCO_DIAS - 1), DATA_FIM)
        bloco += 1
        regs = raspar_bloco(sessao, dt, fim)
        todos.extend(regs)
        print(f'  [{bloco}/{total_blocos}] {dt:%d/%m}>{fim:%d/%m}: '
              f'{len(regs)} manobras (total: {len(todos)})')
        dt += timedelta(days=BLOCO_DIAS)
        time.sleep(PAUSA_S)

    if not todos:
        print('Nenhuma manobra encontrada.')
        return

    # Merge com existentes
    if todos_existentes:
        df_ex = pd.DataFrame(todos_existentes)
        df_new = pd.DataFrame(todos)
        if len(df_new) > 0:
            df_ex['datetime'] = pd.to_datetime(df_ex['datetime'])
            df_new['datetime'] = pd.to_datetime(df_new['datetime'])
            cutoff = df_new['datetime'].min()
            df_ex = df_ex[df_ex['datetime'] < cutoff]
            todos_final = pd.concat([df_ex, df_new], ignore_index=True)
        else:
            todos_final = df_ex
    else:
        todos_final = pd.DataFrame(todos)

    df = todos_final.sort_values('datetime', kind='stable').reset_index(drop=True)
    df.to_csv(output, index=False, encoding='utf-8-sig')
    print(f'\n>>> {len(df)} manobras salvas em {OUTPUT}')
    print(f'    Periodo: {df["datetime"].min()} > {df["datetime"].max()}')
    print(f'    Praticos unicos: {df["Pratico"].nunique()}')
    print(df[['datetime','Vessel','ES','Berco','Pratico','Status']].head(10).to_string())


if __name__ == '__main__':
    senha = getpass.getpass('Senha SPPILOTS: ')
    raspar_tudo(senha)
