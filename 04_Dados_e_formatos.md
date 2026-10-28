# 4. Dados e formatos

Convenções gerais: horários em hora local de Brasília; **dia operacional** de 07:30 a 07:29 do dia seguinte; práticos identificados por **bigrama** (2 letras maiúsculas, ex.: `RD`); especiais: `JA`, `SI`, `CH`. Berços com os nomes do SPPILOTS (ex.: `TC 1.1`, `BTP-3`, `35.2`, `IB-OE`); `FB` = fora da barra.

Tipos de manobra: **E** (entrada: FB → berço), **S** (saída: berço → FB), **M** (mudança: berço → berço).

## 4.1 Entradas do motor (conjunto de teste em `testes/entrada/`)

### `pauta.csv` — manobras, uma linha por prático
| Coluna | Exemplo | Observação |
|---|---|---|
| Seq | 1 | Ordem de processamento (1..N). **A ordem importa**: manobras do mesmo horário são processadas na ordem desta coluna (ver 02) |
| Data | 01/01/2026 | dd/mm/aaaa |
| Hora | 07:30 | hh:mm (horário da pauta / POB) |
| Navio | MSC ADELE | |
| De | FB | origem |
| Para | BTP-1 | destino |

Navio de 2 práticos = **duas linhas** idênticas consecutivas (mesmo Data/Hora/Navio).

### `turnos.json` — escala efetiva por turno (lista em ordem cronológica)
```json
{"dt_ini": "2026-01-01 07:30", "dt_d2": "2026-01-02 07:30", "dt_fim": "2026-01-03 07:30",
 "dia1": ["RG","RO","LB",...12 bigramas],   // quem está escalado no D1, na ordem da escala
 "dia2": ["RG","AC","PI",...12 bigramas],   // quem está escalado no D2
 "Y":    ["BD","RG","RO",...]}               // fila inicial do 1º turno
```
`dia1`/`dia2` são a escala **efetiva** (já com trocas): no protótipo vêm da aba RESUMO de `bigramas_2026.xlsx`, corrigida por quem de fato manobrou no dia (`gerar_2026.py`, função `corrigir`).

### `especiais.csv` — manobras dos especiais (fixas)
| Coluna | Observação |
|---|---|
| Seq | mesma numeração da pauta |
| Navio | conferência |
| Especial | JA, SI ou CH |

Os especiais fazem exatamente as mesmas manobras que fariam na E12: no passado, as que fizeram de fato (histórico SPPILOTS); no futuro, as que a E12 lhes daria (`gerar_2026.py`, simulação E12 de continuidade).

### `Tempo_T__2025_.xlsx` — tempo de manobra (T)
- Aba **`T Entrada ou saída`**: colunas `Berço`, `T - TEMPO (min)`, `T - TEMPO (h)`. Para entrada usa o T do berço de destino; para saída, o do berço de origem.
- Aba **`Mudanças de entre berços`**: colunas `De`, `Para`, `Tm (min)`. Para mudança sem par na tabela, usa o padrão por par de zonas (`TM_ZONA`, ver 02).

## 4.2 Saída do motor (`testes/esperado/E2D_esperado.csv`)

| Coluna | Exemplo | Observação |
|---|---|---|
| Seq | 3 | igual à entrada |
| Data, Hora, Navio, De, Para | | iguais à entrada |
| Pratico | RO | bigrama escalado pela E2D |
| Status | A | `A` (1ª manobra do ciclo) ou `B` (2ª); vazio nas manobras dos especiais |
| Escalacao | `BD(09:30) > RG(10:30) > RO(11:00) > LB > GU > ... > JA(8) > SI(14)` | Fila **logo após** esta manobra. `XX(hh:mm)` = prático que fez A e só fica disponível a partir de hh:mm; `XX` = disponível; especial com número = contador de posição (ver 02) |

## 4.3 Dados vindos do SPPILOTS (protótipo)

### Pauta de serviço (`pauta_rt.csv`, gerada pelo script do navegador a partir de `psh.asp`)
`datetime, Data, Hora, Termino, Vessel, From, To, ES, Berco, Calado, Bordo, Agente, OBS, Status, dois_prat, Pratico`

Status pela cor da linha na página do SPPILOTS:

| Cor (fundo da linha) | Status | Significado |
|---|---|---|
| `#ff4a4a` | AGENDADO | confirmada |
| `#33ccff` | PROXIMO | próxima a acontecer |
| `#b7b7ff` | BREVE | confirmada, em breve (lilás) |
| `#ffffff` | FUTURO | **não confirmada** (branca, horário previsto) |
| `#ff0099`, `#000000` | ESPECIAL | marcação dos especiais |
| `#66cc66` | — | cancelada (ignorar) |
| `#ffff00` | — | sem prático (ignorar) |

Navio de 2 práticos: texto "(2 PRÁTICOS)" no nome, dois bigramas na coluna de prático ou "2PLT" na observação. Se ainda não há práticos definidos, o protótipo **duplica a linha** para que entrem as duas manobras.

### Histórico (`historico_2026.csv`, via `raspar_historico.py`)
`datetime, Data, Hora, Vessel, ES, Berco, Berco2, From, To, Calado, Bordo, Agente, Obs, Status, dois_prat, Pratico` — uma linha por prático. Colunas da tabela HTML do SPPILOTS: navio `td[2]`, E/S/M `td[3]`, berço `td[4]`, berço destino `td[5]`, horário `td[6]` (dd/mm hh:mm), práticos `td[11]`, calado `td[12]`, bordo `td[13]`, agente `td[15]`, obs `td[16]`.

### Escala (`bigramas_2026.xlsx`, aba `RESUMO`)
`MÊS, DIA, TIPO (D1/D2), P1..P12` — escala planejada com trocas registradas. O protótipo corrige pela realidade (quem manobrou de fato).

## 4.4 Dados de estudo (`dados/`)

- `Pauta_2026_consolidada.xlsx` — pauta real 01/01 a 01/10/2026 com POB, início real, fim, duração, LOA, calado, bordo, 2 práticos (abas `Pauta 2026`, `Excluídas`, `Notas`).
- `historico_2026.csv` — histórico SPPILOTS com o prático real (E12) de cada manobra.

Usos: reprocessamento, comparação E2D × E12, estudo de durações reais × T.
