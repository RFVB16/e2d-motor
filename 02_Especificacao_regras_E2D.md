# Especificação funcional do motor de escalação E2D (Escala 2 e Desce)

Praticagem do Porto de Santos (ZP-16)
Documento técnico para reimplementação em produção

| Item | Valor |
|---|---|
| Versão do documento | 1.1 (28/10/2026): regra da draga, giro sem atracar, escala gráfica |
| Referência oficial | O código-fonte. Este documento descreve o código; onde houver divergência, vale o código. |
| Código de referência | `motor_e2d/motor_e2d.py`, `motor_e2d/ep_sim_v3_corrigido.py`, `motor_e2d/nova_escalacao.py`, `motor_e2d/ep_algoritmo.py`, `motor_e2d/carregar_pauta.py`, `motor_e2d/grupo_a_data.py`, `gerar_2026.py`, `escala_grafica.py` (provisório) |
| Convenção | Tudo o que está aqui foi lido no código. Trechos marcados **[Inferência]** são interpretação minha, não regra escrita. Trechos marcados **[Ponto de atenção]** são comportamentos não óbvios, frágeis ou aparentemente inconsistentes, listados também na seção 9. |

---

## 1. Objetivo e escopo do motor

O motor E2D recebe:

1. a **pauta de manobras** (lista de manobras com data, hora de início, navio, berço de origem e berço de destino);
2. a **escala de turnos** (quais práticos trabalham em cada dia, D1 e D2 de cada grupo, já corrigida pelo que aconteceu de fato);
3. a **tabela de tempos T** (tempo de manobra por berço e por mudança);
4. a **atribuição fixa dos práticos especiais** (JA, SI, CH), que fazem os mesmos navios que fariam na E12.

Ele devolve, para cada manobra, **qual prático regular faz a manobra**, se ela é a **A** (1ª do ciclo) ou a **B** (2ª do ciclo) daquele prático, e a **escalação** (a fila) resultante logo após a manobra.

Regra central da E2D: cada prático regular faz ciclos de **2 manobras (A → B)**. Depois da A ele fica com uma hora prevista de disponibilidade (HH:MM) e permanece na frente da fila. Assim que fica disponível, faz a B. Depois da B, "desce", ou seja, vai para o fim da fila. Toda manobra vale 1 e o ciclo fecha na 2ª manobra.

Escopo deste documento:

- **Dentro**: o motor (`motor_e2d.py` com `ep_sim_v3_corrigido.simular_turno` e `nova_escalacao`) e o orquestrador ao vivo (`gerar_2026.py`), que monta as entradas do motor (pauta, turnos, especiais).
- **Fora**: a coleta do SPPILOTS, o `ep_atualizar.py` (montagem da página/painel), a publicação. São citados apenas onde fornecem formato de entrada.

### 1.1 Fluxo geral (produção ao vivo)

```
historico_2026.csv  (SPPILOTS, com prático real)  ┐
pauta_rt.csv        (SPPILOTS, pauta atual)        ├─> gerar_2026.py
inputs/bigramas_2026.xlsx (aba RESUMO)             ┘     1. monta a pauta
                                                          2. lê o prático real por navio
                                                          3. monta a escala do dia e corrige por quem trabalhou
                                                          4. monta os turnos (D1+D2)
                                                          5. define os especiais (real do SPPILOTS; resto simulado pela E12)
                                                          6. grava _pauta_live.xlsx, _turnos_live.pkl, _especiais_live.xlsx
                                                          7. executa motor_e2d.py (subprocesso, cwd = motor_e2d/)
                                                          8. converte a saída para ao_vivo/E2D_2026_v6.xlsx
```

O motor é **recalculado do zero a cada execução**, desde o primeiro turno da escala (01/01/2026) até a última manobra da pauta. Não existe estado persistido entre execuções. **[Inferência]** Por isso, uma correção de escala ou de pauta no passado pode alterar a atribuição de manobras posteriores.

---

## 2. Entradas

### 2.1 Entradas do orquestrador `gerar_2026.py`

Todas as entradas têm caminho padrão relativo à pasta do `gerar_2026.py` e podem ser substituídas por variável de ambiente.

| Entrada | Caminho padrão | Variável | Uso |
|---|---|---|---|
| Histórico SPPILOTS | `historico_2026.csv` | `HIST_IN` | Manobras já executadas, com prático real |
| Pauta atual SPPILOTS | `pauta_rt.csv` | `RT_IN` | Manobras a partir do fim do histórico |
| Pauta de reserva | `inputs/Pauta_de_Manobra_2026.xlsx` | `PAUTA_IN` | Usada só se o histórico não existir |
| Escala | `inputs/bigramas_2026.xlsx` | `ESCALA_IN` | Aba `RESUMO` |
| Tabela T | `motor_e2d/inputs/Tempo_T__2025_.xlsx` | (fixo) | Só para a simulação E12 dos especiais |
| Saída | `ao_vivo/E2D_2026_v6.xlsx` | `SAIDA` | Planilha final |
| Margens | 45 / 25 | `MARGEM_ENTRADA` / `MARGEM_OUTRAS` | Repassadas ao motor |

#### 2.1.1 CSV do SPPILOTS (`historico_2026.csv` e `pauta_rt.csv`)

Codificação `utf-8-sig`, separador vírgula. Cabeçalho observado:

`datetime,Data,Hora,Vessel,ES,Berco,Berco2,From,To,Calado,Bordo,Agente,Obs,Status,dois_prat,Pratico`

Colunas usadas pelo código (`gerar_2026._ler_csv`, `_completar_dois_praticos` e bloco 1):

| Coluna | Formato | Uso |
|---|---|---|
| `datetime` | `AAAA-MM-DD HH:MM:SS` | Início da manobra (`DT`). Linhas com data inválida são descartadas. |
| `Vessel` | texto | Nome do navio (com `strip`) |
| `From` / `To` | código de berço (ex.: `FB`, `TC 1.1`, `BTP-1`) | Origem e destino (com `strip`) |
| `ES` | `E` (entrada), `S` (saída), `M` (mudança) | Só para agrupar a duplicação de 2 práticos |
| `dois_prat` | `True`/`False` (ou `1`) | Navio de 2 práticos |
| `Pratico` | sigla do prático (ex.: `BD`), vazio se ainda não escalado | Prático real |
| `Termino` | `HH:MM` (opcional; **não existe no CSV atual**) | Só informativo |

#### 2.1.2 Escala `bigramas_2026.xlsx`, aba `RESUMO`

Colunas: `MÊS, DIA, TIPO, P1 … P12`.

- A **data de cada linha é a posição da linha**: linha de índice *i* (0 = primeira linha de dados) corresponde a `01/01/2026 + i dias` (`gerar_2026`, bloco 3). As colunas `MÊS` e `DIA` **não são lidas**. **[Ponto de atenção]**
- `TIPO`: `D1` ou `D2` (com `strip`). Outros valores são ignorados na montagem dos turnos.
- `P1..P12`: siglas dos 12 práticos do dia, na ordem dos "slots" (posições). Inclui especiais. Célula que não é texto vira vazio (`None`). As siglas passam por `J()`: `strip`, maiúsculas, e `JÁ` → `JA`.

### 2.2 Entradas do motor `motor_e2d.py`

O motor é executado com `cwd = motor_e2d/` e recebe por variável de ambiente:

| Variável | Conteúdo (gerado por `gerar_2026.py`) |
|---|---|
| `PAUTA_FILE` | `_pauta_live.xlsx`: colunas `Data` (`DD/MM/AAAA`), `Hora` (`HH:MM`), `Termino` (`HH:MM` ou vazio), `Vessel`, `From`, `To`. Uma linha por prático (navio de 2 práticos = 2 linhas). |
| `TURNOS` | `_turnos_live.pkl`: lista de dicionários de turno (ver 2.2.2) |
| `ESP_FONTE` | `_especiais_live.xlsx`: colunas `Seq, Navio, Pratico`; `Seq` = índice da linha da pauta + 1 |
| `MARGEM_ENTRADA`, `MARGEM_OUTRAS` | margens em minutos (padrão 45 e 25) |
| `E2D_OUT` | nome da planilha de saída do motor (`_E2D_live.xlsx`) |
| `FB_OUT` | pickle com o log de "ninguém disponível" (`_fallback.pkl`) |

#### 2.2.1 Leitura da pauta (`carregar_pauta.carregar_pauta`)

Para cada linha:

1. `datetime = strptime(Data + ' ' + Hora, '%d/%m/%Y %H:%M')`. Linha que não converte é **descartada**.
2. `Termino`: se preenchido e válido (`HH:MM`), `dt_fim` = mesmo dia com a hora do término; se `dt_fim <= datetime`, soma 1 dia. Só informativo (não entra na disponibilidade).
3. `Vessel`, `From`, `To` com `strip`. `Data` e `Hora` são mantidos como texto.

Depois: ordenação **estável** por `datetime` (a ordem original do arquivo é preservada entre manobras do mesmo minuto).

`pares2` = conjunto de `(datetime, Vessel)` que aparecem **exatamente 2 vezes** (navio de 2 práticos).

#### 2.2.2 Turno (estrutura de `_turnos_live.pkl`)

| Campo | Tipo | Significado |
|---|---|---|
| `dt_ini` | Timestamp | Data do D1 às 07:30 |
| `dt_d2` | Timestamp | Data do D1 + 1 dia, às 07:30 (início do D2) |
| `dt_fim` | Timestamp | Próximo D1 às 07:30. **O motor sobrescreve** com o `dt_ini` do turno seguinte (`motor_e2d.py`, linhas 256-258). |
| `dia1` | lista[12] | Siglas do D1 na ordem dos slots P1..P12 (pode conter `None`; inclui especiais) |
| `dia2` | lista[12] | Siglas do D2 (se não houver a linha do dia seguinte, repete `dia1`) |
| `Y` | lista[12] | Fila inicial. Igual a `dia1`, exceto no 1º turno (ver 3.9). |

#### 2.2.3 Tabela de tempos `Tempo_T__2025_.xlsx`

Lida por `ep_algoritmo.carregar_dados()`:

- Aba **`T Entrada ou saída`**: colunas `Berço`, `T - TEMPO (min)`, `T - TEMPO (h)`. Gera `T_min[berço] = int(T - TEMPO (min))`. Linhas com `Berço` ou T vazio são ignoradas (a última linha da aba é uma nota de texto e cai aqui). O `int()` **trunca** valores fracionários: 83,5 → 83; 127,5 → 127; 157,5 → 157; 76,5 → 76. **[Ponto de atenção]**
- Aba **`Mudanças de entre berços`**: colunas `Mudança`, `De`, `Para`, `Tm (min)`, `Tm (h)`. Gera `T_mud[(De, Para)] = int(Tm (min))`. A chave é **direcional**: (A, B) e (B, A) são entradas distintas. Linhas sem `De`, `Para` ou `Tm` são ignoradas. Hoje são 207 pares e todos os valores são inteiros.
- A função `carregar_dados()` também abre um arquivo de manobras de 2025 (`Manobras_2025__original_.xlsx`, procurado em `inputs/`, `.`, `..` etc.). O conteúdo é descartado pelo motor, mas **o arquivo precisa existir**, senão o motor para com erro. **[Ponto de atenção]**

As tabelas completas estão no Apêndice A.

#### 2.2.4 Especiais (`ESP_FONTE`)

`motor_e2d.py`, linhas 199-217: para cada linha de `_especiais_live.xlsx` cuja coluna `Seq` seja inteira e cuja `Pratico` esteja em `ESPECIAIS`:

- `idx = Seq − 1` é o índice da manobra na pauta já ordenada;
- o motor **exige** (`assert`) que o `Vessel` dessa linha da pauta seja igual ao `Navio` da planilha. Se não for, o motor para.
- grava `esp_atrib[idx] = especial`.

Depois converte para a chave `(Data, Hora, Vessel)` → **lista** de especiais (um navio de 2 práticos pode ter 2 especiais). Essa estrutura é `sim._ESP_ATRIB_FORCADAS_KEY` (o "mapa de forçamento").

Se `ESP_FONTE` não for informado, o motor tenta `from engine_e12 import EngineE12`, módulo **que não está no pacote**, e falha. Em produção `ESP_FONTE` é obrigatório. **[Ponto de atenção]**

---

## 3. Conceitos e definições

### 3.1 Práticos regulares e especiais

- **Especiais**: `ESPECIAIS = {'JA','SI','CH'}` (configurável por `ESP_SET`, separado por vírgula). No `gerar_2026.py` o conjunto é fixo `{'JA','SI','CH'}`.
- **Regulares**: todos os demais.
- Especiais **não** participam da lógica E2D: não entram na busca da fila, não têm ciclo A/B, não contam no limite Z5 e não recebem status A/B. Fazem apenas as manobras fixadas pelo mapa de forçamento.

### 3.2 Normalização de siglas (`ep_sim_v3_corrigido.norm`)

`strip` → decomposição Unicode NFD → remoção de acentos → maiúsculas. Aplicada às listas `dia1`, `dia2` e `Y` dos turnos.

### 3.3 Dia operacional

Vai das **07:30 às 07:29** do dia seguinte. Uma manobra às `hh:mm` pertence ao dia operacional `D` se `(hh, mm) >= (7, 30)` na data `D`; senão, pertence a `D − 1` (`_calc_dia_op`; no orquestrador, `dia_op(t) = (t − 7h30).date()`).

### 3.4 Turno

Um turno = D1 + D2 de um grupo = de `dt_ini` (D1 07:30) até `dt_fim` (próximo D1 07:30). A virada D1 → D2 é em `dt_d2` (D1 + 1 dia, 07:30). As manobras do turno são as que têm `dt_ini <= datetime < dt_fim`.

### 3.5 Zonas (`ep_algoritmo.zona`)

`zona(berço) = BERCO_ZONE.get(berço.strip(), 2)`. **Berço não cadastrado cai na Zona 2.** Tabela completa na seção 8.1.

| Zona | Região |
|---|---|
| Z1 | FB (Fora da Barra) |
| Z2 | Canal principal (29-39, TC, SAIPEM, TERMG, TEV, DOW...) |
| Z3 | Porto interno (12-25, EMB, OUT, CS, IB, AGEO, VAL...) |
| Z4 | Alemoa / BTP (AL 1-4, BTP-1..3, TRSP) |
| Z5 | Cosipa / TIP / Ultrafértil (COS, TIP, ULT) |

Manobra **Z5** = origem **ou** destino em Z5 (`is_z5`).

### 3.6 Tipos de manobra

- **Entrada**: `From == 'FB'`.
- **Saída**: `To == 'FB'`.
- **Mudança**: nem `From` nem `To` é `FB`.

### 3.7 Tempo T da manobra (`ep_algoritmo.gT(fr, to, T_min, T_mud)`)

| Caso | T |
|---|---|
| Entrada (`fr == 'FB'`) | `T_min[to]`; se o berço não estiver na tabela, **60** |
| Saída (`to == 'FB'`) | `T_min[fr]`; se não estiver, **60** |
| Mudança | 1) `T_mud[(fr, to)]` se o par existir (direcional); 2) senão `TM_ZONA[(min(zona), max(zona))]`; 3) senão **60** |

Observação: a ordem dos testes faz `FB → FB` cair no 1º caso (`T_min['FB']` não existe → 60). Desde 27/10/2026 o giro sem atracar (FB → FB) recebe o T das linhas `GIRO …` da tabela (5.14), passado ao motor por `BTP_OV`.

### 3.8 Tempo de lancha L (`ep_algoritmo.gL(a, b)`)

`L = ZONE_MATRIX[(min(zona(a), zona(b)), max(zona(a), zona(b)))]` (simétrica). Berços diferentes na mesma zona → L = 0. Tabela na seção 8.2.

Na disponibilidade, `a` = **destino da última manobra** do prático e `b` = **origem da manobra candidata**.

### 3.9 Arredondamento r15 (`ep_algoritmo.r15`)

```
m  = hora*60 + minuto          (segundos são descartados)
rv = round(m / 15) * 15
resultado = mesmo dia, rv minutos (passa para o dia seguinte se rv >= 1440)
```

**É arredondamento para o quarto de hora MAIS PRÓXIMO, não para cima.** Resto de 0 a 7 min arredonda para baixo; de 8 a 14 min, para cima. Exemplos verificados: 10:07 → 10:00; 10:08 → 10:15; 10:22 → 10:15; 10:23 → 10:30; 23:53 → 00:00 do dia seguinte. Com minutos inteiros não existe empate exato (x,5), então o `round` "bancário" do Python não interfere. A docstring diz "para cima se ímpar", o que não corresponde ao comportamento. **[Ponto de atenção]**

### 3.10 Margem

Valor somado ao T antes do arredondamento (`motor_e2d._avail_b45`):

| Manobra candidata | Margem |
|---|---|
| Sai de FB (`From == 'FB'`, entrada) | `MARGEM_ENTRADA` = **45 min** |
| Qualquer outra (saída ou mudança) | `MARGEM_OUTRAS` = **25 min** |

A margem depende da **manobra candidata** (a próxima), não da manobra anterior. O comentário na linha 43 do `motor_e2d.py` diz "15 min nas demais", mas o valor em vigor é 25. **[Ponto de atenção]**

### 3.11 Disponibilidade (HH:MM)

Para um prático `p` com última manobra `last = (start, fr, to)` e uma manobra candidata `m` com origem `m.From` e início `m.datetime`:

```
avail(p, m) = r15( last.start + gT(last.fr, last.to) + margem(m.From) + gL(last.to, m.From) )
p está disponível para m  <=>  p nunca manobrou (last = None)  OU  avail(p, m) <= m.datetime
```

- `last` é a **última manobra do prático, qualquer que seja** (A ou B), em todo o histórico simulado, inclusive em turnos anteriores.
- Usa o **início programado** da última manobra. O término real não entra no cálculo.
- A disponibilidade **depende da manobra candidata** (pela margem e pelo L). O mesmo prático pode estar disponível para uma mudança e não para uma entrada no mesmo horário.
- Exemplo real (01/01/2026): BD fez A às 07:30 FB → TC 1.1 (T = 60, Z2). Para uma entrada (sai de FB): 07:30 + 60 + 45 + L(Z2→Z1 = 20) = 09:35 → r15 = **09:30**. Para uma saída de 20/21 (Z3): 07:30 + 60 + 25 + L(Z2→Z3 = 5) = **09:00**. BD fez a B às 09:00 saindo de 20/21.

### 3.12 Ciclo A → B (estado do prático regular)

Cada regular tem um contador `pts_g[p]`, que vale 0 (ciclo fechado) ou 1 (ciclo aberto). Cada manobra soma 1 (`pts_man_fn` fixo em 1,0; `THRESHOLD = 2.0`; `CARRY = False`).

- Manobra com `pts_g` = 0 antes → **A** (fica com 1; ciclo aberto).
- Manobra com `pts_g` = 1 antes → **B** (chega a 2 ≥ THRESHOLD; volta a 0; ciclo fechado; "desce").

O contador é **global**: persiste entre dias e entre turnos. Se o prático fez a A no fim do seu D2, a próxima manobra dele, no turno seguinte (depois da folga), é a B. Ele volta da folga com a **B pendente**.

### 3.13 Fila (`fila_display`)

Uma única lista ordenada de siglas, que pode conter especiais (são ignorados na busca e na exibição como regulares). **A mesma lista serve para escolher o prático e para exibir a escalação.** A variável `fila` também existe no código, mas não é usada na decisão.

Regras de movimentação:

| Evento | Efeito na fila |
|---|---|
| Regular faz **A** | **Não se move.** Fica na mesma posição; só passa a exibir `(HH:MM)` (`atualizar_nao_esp`: "Após A: piloto FICA NA MESMA POSIÇÃO") |
| Regular faz **B** | Sai da posição e vai para o **fim** da fila (`inserir_apos_B`) |
| Especial manobra | Fila de regulares não muda |
| Virada de dia operacional / D1→D2 / entre turnos | Ver seção 5 |

Consequência **[Inferência, confirmada na saída]**: como o escolhido é sempre o primeiro disponível na ordem da fila, todos os que estão à frente dele estão indisponíveis (em geral, com ciclo aberto). Ele fica parado ali após a A. A frente da fila acumula os práticos com A feita, **na ordem em que fizeram a A** (não na ordem do HH:MM). Quando um deles fica disponível, é o primeiro disponível da fila e faz a B. A função `inserir_apos_A` (que reordenaria por horário) existe, mas **nunca é chamada**.

---

## 4. Algoritmo passo a passo

### 4.1 Estado global (mantido entre turnos, durante a execução)

| Estado | Conteúdo |
|---|---|
| `last_g[p]` | Última manobra de cada prático: `{start, fr, to, fim}` |
| `pts_g[p]` | 0 ou 1 (ciclo) |
| `pend_b_carry` | Conjunto de regulares com ciclo aberto (A sem B), passado de um turno ao seguinte |
| `ultima_esc` | Texto da escalação após a última manobra do turno anterior |
| `prev_dia2` | Lista `dia2` normalizada do turno anterior |
| `man_count` | Contador absoluto de manobras (usado só para exibir os especiais) |
| `ns_carry` | Posição relativa da próxima manobra de cada especial (só para exibição) |

### 4.2 Laço de turnos (`motor_e2d.py`, linhas 280-338)

```
turnos ← ordenar por dt_ini; dt_fim[i] ← dt_ini[i+1]
para cada turno ti:
    Y_d1 ← norm(dia1) sem vazios/'?'
    se ti == 0:
        fila_ini ← norm(Y) sem vazios                       (inclui especiais)
    senão:
        se ultima_esc ≠ '' e conjunto(prev_dia2) ≠ conjunto(Y_d1):
            fila_ini ← nomes de nova_escalacao(ultima_esc, prev_dia2, Y_d1)   (seção 5.6)
            se vazio: fila_ini ← Y_d1
        senão:
            fila_ini ← Y_d1                                  (ordem dos slots do D1)
        ── B pendente entre turnos ──
        R ← [p em fila_ini | p não especial, p ∈ pend_b_carry, p ∉ prev_dia2]
        se R: remove R e reinsere, na ordem em que estavam,
              na posição do primeiro não especial (na prática, o início da fila)
    executar simular_turno(turno, fila_ini, …)  →  histórico, ultima_esc, ns_carry, man_count, pend_b_carry
    prev_dia2 ← norm(dia2)
    numerar Seq sequencialmente (1, 2, 3, … na ordem de processamento)
```

### 4.3 Dentro do turno (`ep_sim_v3_corrigido.simular_turno`)

```
man_t ← manobras com dt_ini <= datetime < dt_fim, ordenação estável por datetime
se man_t vazio: devolve histórico vazio, ultima_esc = '', mantém pend_b_carry
fila_display ← fila_ini
z5_count ← {}                ; dia_op_atual ← nulo
pend ← cópia de pend_b_carry
i ← 0
enquanto i < len(man_t):
    dt ← man_t[i].datetime

    (1) VIRADA DE DIA OPERACIONAL  (seção 5.4)
        se dia_op(dt) ≠ dia_op_atual:
            z5_count ← {}  ; dia_op_atual ← dia_op(dt)
            aplicar_pendentes(dia_op_atual)

    (2) VIRADA D1 → D2  (seção 5.5)
        se ainda no D1 e dt >= dt_d2: …

    (3) GRUPO DO MESMO MINUTO
        G ← todas as manobras seguintes com datetime == dt
        agrupar G por Vessel, na ordem da primeira aparição de cada navio
        G ← reordenado: linhas do 1º navio, depois as do 2º, …
        atrib ← {}                         (quem já foi atribuído neste minuto)

    (4) para cada manobra m em G, nesta ordem:
          prat ← ESCOLHER(m)               (4.4)
          atrib[m] ← prat
          ATUALIZAR(prat, m)               (4.5)
          escalacao ← MONTAR_ESCALACAO(m, prat)   (seção 6.2)
          man_count += 1 ; ultima_esc ← escalacao
          registrar linha de saída

    (5) ajuste ("catch-up") das posições dos especiais (só exibição, 6.2.3)
    i ← primeira manobra após o grupo
```

### 4.4 ESCOLHER(m): escolha do prático (modo produção, com mapa de forçamento ativo)

```
chave ← (m.Data, m.Hora, m.Vessel)
E ← mapa_forcamento.get(chave, [])
para cada especial e em E (na ordem):
    se e ∉ valores(atrib):  devolve e                    (especial fixo)

# regulares
z5 ← is_z5(m.From, m.To)
C ← [p em fila_display, na ordem | p ∉ ESPECIAIS, p ∉ valores(atrib), disponível(p, m)]
se z5: C ← [p ∈ C | z5_count[p] < 1]
se C não vazio: devolve C[0]                             (primeiro disponível da fila)

# ninguém disponível (fallback)
R  ← [p em fila_display | p ∉ ESPECIAIS, p ∉ valores(atrib)]
RZ ← R filtrado pela regra Z5 (se z5) ; se RZ vazio: RZ ← R
p* ← elemento de RZ com menor chave (avail ≠ nulo, avail, posição em RZ)
se p* não existe: p* ← fila_display[0]
registrar no log de fallback: (dt, p*, avail(p*, m), Vessel, From, To)
devolve p*
```

Desempates e detalhes:

1. **Ordem de prioridade**: especial fixo → primeiro regular disponível na fila (respeitando Z5) → fallback.
2. Entre regulares disponíveis, vale **somente a posição na fila** (não o HH:MM nem a hora em que ficou livre).
3. A **regra Z5 vem antes da disponibilidade**: se todos os disponíveis já fizeram Z5 no dia, o motor vai ao fallback e escolhe, entre os que ainda **não** fizeram Z5, quem fica livre mais cedo, **mesmo que ainda não esteja livre**. Só se **todos** os regulares já tiverem feito Z5 é que a regra é ignorada (e aí ganha quem fica livre mais cedo, o que, havendo alguém disponível, recai num disponível).
4. No fallback, o empate em `avail` é resolvido pela posição na fila.
5. "Já atribuído neste minuto" (`atrib`) vale para **todas** as manobras com o mesmo `datetime`, de qualquer navio.
6. Se o mapa de forçamento estiver **vazio** (nenhum especial na pauta toda, ou `SEM_FORCA=1`), entra o "comportamento original" (rodízio interno dos especiais por contador). Ver 9, item P3. Esse modo não é o de produção.

### 4.5 ATUALIZAR(prat, m)

**Se `prat` é especial** (`atualizar_esp`):

- `pts_g[prat] = 0`; `last_g[prat] = {start: m.datetime, fr, to, fim}`.
- Atualiza o contador de exibição: `next_slot[prat] = (_rr_orig.pop(prat) ou next_slot[prat]) + 12`. Não afeta a escolha.

**Se `prat` é regular** (`atualizar_nao_esp`):

```
novo ← pts_g[prat] + 1
last_g[prat] ← {start: m.datetime, fr: m.From, to: m.To, fim: m.dt_fim}
se novo >= 2:                       # B
    pts_g[prat] ← 0
    pend.remove(prat)
    mover prat para o FIM de fila_display ; marcar prat em _no_hhmm
    status ← 'B'
senão:                              # A
    pts_g[prat] ← 1
    pend.add(prat) ; desmarcar prat de _no_hhmm
    (posição na fila não muda)
    status ← 'A'
se is_z5(m): z5_count[prat] += 1    # conta A e B
```

---

## 5. Regras especiais

### 5.1 Navios de 2 práticos

- Na pauta, o navio de 2 práticos aparece em **2 linhas** iguais (mesmo `datetime` e `Vessel`).
- `gerar_2026._completar_dois_praticos`: se `dois_prat` for verdadeiro (`'true'` ou `'1'`, sem diferenciar maiúsculas) e o grupo `(DT, Vessel, ES)` (ou `(DT, Vessel)` sem a coluna `ES`) tiver **uma só linha**, a linha é **duplicada**. A cópia é anexada ao fim e depois a pauta é reordenada (estável) por DT. Por isso a cópia fica **por último entre as manobras daquele minuto**, e não necessariamente colada na original. **[Ponto de atenção]** No motor isso não importa, porque as linhas de um mesmo navio no mesmo minuto são reagrupadas (4.3, passo 3). Na simulação E12 dos especiais, importa (5.3.3).
- No motor, cada linha é **uma manobra independente**: cada um dos 2 práticos tem a sua A ou B, a sua contagem Z5 e a sua disponibilidade. Os dois não podem ser a mesma pessoa (exclusão por `atrib`).
- Combinações possíveis: especial + especial, especial + regular, regular + regular.
- `pares2` (exatamente 2 linhas) não muda a escolha no modo produção. Só é usado no ajuste de exibição dos especiais. Um grupo de 3 ou mais linhas do mesmo navio no mesmo minuto é tratado como 3 manobras com práticos distintos.

### 5.2 Restrição Z5

- `Z5_LIMITE_DIA = 1`: no máximo 1 manobra Z5 por prático **regular** por **dia operacional**.
- Conta **qualquer** manobra Z5 (A ou B; origem ou destino em Z5).
- Zera a cada virada de dia operacional e no início de cada turno.
- Especiais não entram na contagem nem no filtro.
- É uma restrição **forte, com relaxamento só em último caso** (4.4, desempate 3). Na execução de 01/01 a 20/10/2026, nenhum regular fez mais de 1 Z5 no mesmo dia operacional.

### 5.3 Especiais (JA/SI/CH)

#### 5.3.1 Princípio

Os especiais fazem **exatamente os navios que fariam na E12**. O motor não decide nada sobre eles: só aplica o mapa de forçamento (4.4). As manobras dos especiais não mudam o estado E2D dos regulares, a não ser pelo fato de um regular não pegar aquela linha.

#### 5.3.2 Origem da atribuição (`gerar_2026.py`, bloco 4)

Para cada manobra da pauta, o prático "E12" (`pred`) é definido assim:

1. **Prático real conhecido** (SPPILOTS): `real[(DT, Vessel)]` = lista de siglas obtida da coluna `Pratico` de todas as linhas do grupo, quebrando por `/` e espaço e descartando `NAN`/`NONE`, com `J()`. A pauta atual (`pauta_rt.csv`) sobrescreve o histórico na mesma chave. Se conhecido, usa-se o real.
2. **Desconhecido** (manobra ainda não escalada no SPPILOTS): **simula-se a vez da E12** (5.3.3).

Só as linhas com `pred` especial viram forçamento no motor. **As escolhas de regulares da E12 (reais ou simuladas) são ignoradas**: a E2D recalcula todos os regulares.

#### 5.3.3 Simulação da vez da E12 (só para manobras sem prático real)

Por dia operacional, em ordem cronológica:

```
P ← escala corrigida do dia (12 slots)       ; se o dia não existir: ('D2', 12 vazios)
se o dia é D1 e há prático real no dia: bold ← 1º prático real do dia que está em P
se ptr é nulo ou bold existe: ptr ← índice de bold em P (ou 0) ; buf ← []
para cada manobra do dia (n = 2 se a linha seguinte for do mesmo navio e do mesmo DT, senão 1):
    se a manobra tem prático real (lista R):
        para cada uma das n linhas: nm ← R[q] (ou R[0] se faltar)
            livre[nm] ← FIM(linha) ; se Z5: z5c[(dia, nm)] += 1
            se nm ∈ P: k ← slot de nm
                se k ∈ buf: remove k de buf (vez "pulada" sendo paga)
                senão: avança ptr até k, colocando os slots pulados em buf ; ptr ← k+1
    senão:
        ok(q) ← P[q] existe  e  livre[P[q]] <= DT  e  não (Z5 e P[q] regular e z5c[(dia, P[q])] >= 1)
        percorre buf (e vai estendendo buf com ptr, ptr+1, … em módulo 12) procurando slots ok;
        a 1ª escolha fixa a "classe" (especial ou regular); a 2ª linha de um navio de 2 práticos
        precisa ser da mesma classe;
        se todos os 12 slots já estão em buf/escolhidos: pega o 1º ok entre os da mesma classe,
        senão o que fica livre mais cedo (empate: ordem em buf)
        atribui pred às n linhas ; atualiza livre e z5c
```

- `FIM(linha)` = término informado (`Termino` `HH:MM`, ajustado para o dia seguinte se for anterior ao início) ou, sem término, `início + gT` (com T **não truncado**, em ponto flutuante). Na E12 simulada **não há margem nem lancha**.
- `N = 12` slots.
- Limite de segurança: 200 iterações por manobra.

#### 5.3.4 Aplicação no motor

- Chave do forçamento: `(Data, Hora, Vessel)`. Uma chave pode ter 2 especiais (navio de 2 práticos).
- Em cada linha, usa-se o **primeiro especial da lista ainda não atribuído no mesmo minuto**. Numa chave com `[JA]` e 2 linhas, a 1ª linha (na ordem de processamento) recebe JA e a 2ª vai para um regular.
- O especial forçado é aplicado **mesmo que, pelo modelo E2D, ele não estivesse "disponível"**. A disponibilidade não é verificada para especiais.
- Na execução de 2026 até 20/10: 423 manobras de especiais (JA 193, SI 190, CH 40), todas com prático real do SPPILOTS.

### 5.4 Virada de dia operacional (07:30): B pendente (`_aplicar_pendentes`)

Executada na **primeira manobra** de cada novo dia operacional (inclusive a primeira do turno), antes da escolha. Pode ser desligada com `PEND_OFF=1` (não usar em produção). Seja `do` o novo dia operacional e `[do−1 07:30, do 07:30)` o dia anterior.

1. **Camada 1, "permanentes com ciclo aberto"**: regulares que estão na fila, cuja **última manobra começou no dia operacional anterior** e que estão com ciclo aberto (`pts_g > 0`). São retirados e reinseridos, **na ordem relativa que tinham**, na posição do primeiro não especial (o início da fila).
2. **Camada 2, "entrantes com ciclo aberto"**: regulares que estão na fila e em `pend` (ciclo aberto), que não estão na Camada 1 e cuja última manobra **não** foi no dia operacional anterior (tipicamente, os que voltam da folga com B pendente). São reinseridos, na ordem relativa que tinham, **logo após o bloco da Camada 1**.
   - Cálculo exato da posição: percorre a fila ignorando especiais; ao achar um da Camada 1, a posição passa a ser índice + 1; ao achar alguém que não é nem da Camada 1 nem da Camada 2, para. Depois retira os da Camada 2 e insere todos nessa posição.

Também na virada: `z5_count` zera.

### 5.5 Virada D1 → D2 (dentro do turno)

Ocorre na **primeira manobra com `dt >= dt_d2`**, logo depois da virada de dia operacional (5.4).

```
Y_d1 ← norm(dia1) ; Y_d2 ← norm(dia2)
se Y_d2 não vazio e conjunto(Y_d2) ≠ conjunto(Y_d1) e ultima_esc ≠ '':
    nova ← nomes de nova_escalacao(ultima_esc, Y_d1, Y_d2)
    se nova não vazio:
        fila_display ← nova
        aplicar_pendentes(dia atual)            (reaplica 5.4 sobre a nova fila)
remapear contadores de exibição dos especiais: chave Y_d1[i] → Y_d2[i]
```

Se o conjunto de práticos de D1 e D2 for igual (mesmas pessoas, mesmo que em outra ordem de slots), **a fila continua como estava**. `ultima_esc` aqui é a escalação depois da última manobra do D1.

### 5.6 Nova escalação (`nova_escalacao.nova_escalacao(ultima_esc, saindo, entrando)`) — TROCA DIRETA

**Regra em vigor desde 23/10/2026.** É usada na troca de pessoas entre D1 e D2 (5.5) e entre turnos (4.2). Os parâmetros `saindo` e `entrando` são as listas de 12 slots, com especiais.

**Critério (definido pela Praticagem):** quem continua trabalhando deve ter a **menor mudança possível de posição** (e, portanto, de descanso).

```
remover vazios/'?' ; n ← min(len(saindo), len(entrando)) ; truncar as duas em n
slot_sai[p] ← índice de p em saindo
permanece ← entrando ∩ saindo ; novos ← (entrando − saindo) − ESPECIAIS
função entra_no_lugar(L):            (L = sainte)
    j ← slot_sai[L] ; visto ← {}
    repetir:
        q ← entrando[j]
        se q é vazio ou já visto: devolver nada
        se q ∈ novos: devolver q
        se q estava em saindo (remanescente que mudou de slot): j ← slot_sai[q]   (segue a cadeia)
        senão (especial): devolver nada
esc ← parse(ultima_esc) ; final ← [] ; usados ← {}
para cada (p, estado) em esc, na ordem:
    se p ∈ ESPECIAIS: pular
    se p ∈ saindo e p ∉ entrando:                  (sainte)
        q ← entra_no_lugar(p)
        se q existe e q ∉ usados: inserir q (na posição de p)
        (se não existe: a posição do sainte é descartada)
    senão se p ∉ usados: inserir p                 (remanescente: mantém a posição)
anexar ao fim os novos ainda não inseridos, na ordem de entrando
manter só os 12 primeiros
```

Resumo prático:

- **Remanescentes não mudam de posição** (salvo pelo efeito de saídas sem substituto à frente deles).
- Cada sainte é substituído, **na mesma posição da fila**, pelo entrante do seu slot. Se o slot do sainte passou a um remanescente que mudou de slot, segue-se a cadeia até chegar a um entrante (substituição indireta resolvida na posição do sainte).
- **Sainte com B pendente:** o entrante herda a posição dele (mesmo que na frente); o sainte, quando voltar, entra como entrante pendente (5.4, Camada 2).
- **Slot do sainte passou a um especial:** a posição do sainte é **descartada** e os de trás sobem.
- **Entrante em slot que era de especial** (ou sem posição herdada): vai para o **fim**.
- Exemplos verificados:
  - `ultima_esc = "B(09:30) > C > JA(3) > A > D"`, saindo `[A,B,JA,C,D]`, entrando `[E,F,SI,G,H]` → `F > G > E > H`.
  - Mesma `ultima_esc`, entrando `[A,B,JA,X,D]` → `B > X > A > D`.
  - 08/10 (slide 3): fim do dia `SP > LZ > FX > FS > LE > HI > LB > LT > LG > ZI > AG > CM`; saem FX e AG; LB muda do slot 5 para o 11 (slot de FX); NI entra no slot 5; LC no slot 12 → `SP > LZ > NI > FS > LE > HI > LB > LT > LG > ZI > LC > CM` (FS, LE e HI **não mudam**; na regra antiga subiam uma posição).
- Os estados `(…)` são descartados pelo motor; só a **ordem** importa. O resultado nunca contém especiais.
- **Regra antiga** (substituição indireta: o entrante entra antes do remanescente que ocupou o slot do sainte) disponível com `REORD=indireta`, só para comparação. Em 2026 ela fazia remanescentes perderem 1–2 posições em 171 casos (81 viradas); com a troca direta, isso deixa de ocorrer. Indicadores agregados (descanso longo, dias de pico, manobras por dia trabalhado) praticamente iguais.

### 5.7 B pendente na virada de turno (entre turnos)

Combina duas regras:

1. No laço de turnos (4.2): entrantes que voltam da folga (não estavam no `dia2` anterior) e estão em `pend_b_carry` vão para o início de `fila_ini`.
2. Na primeira manobra do turno, `_aplicar_pendentes` (5.4) roda de novo: esses entrantes caem na Camada 2 e ficam logo após eventuais permanentes da Camada 1.

Efeito: quem voltou da folga com a A feita é o primeiro da fila e tende a fazer a B logo na abertura do turno.

### 5.8 Ninguém disponível (fallback)

Ver 4.4. Comportamento a reproduzir:

- O escolhido é quem **fica livre mais cedo** (respeitando Z5, se possível).
- A manobra é atribuída **no horário da pauta**. O motor não simula atraso: a `last_g` do prático passa a ser o início programado dessa manobra.
- O evento é registrado em `_FALLBACK_LOG` / `FB_OUT` como `(datetime, prático, hora em que ficaria livre, navio, de, para)`. Na execução de 2026 até 20/10: 6 casos (ex.: 25/02 17:45 NI, livre às 18:15, BETTY FB→23).

### 5.9 Práticos que entram ou saem e trocas

- A **escala do dia** vem da aba RESUMO, já com as trocas planejadas.
- **Escala real do SPPILOTS (desde 25/10/2026):** se existe `inputs/escala_grafica.json` (gerado por `escala_grafica.py`, 5.15), ele substitui a escala planejada slot a slot, nos dias em que pelo menos 10 dos 12 slots foram lidos; slot sem leitura mantém o planejado. A correção abaixo é aplicada depois.
- **Correção pelo que aconteceu de fato** (`gerar_2026.corrigir(plan, seq)`), aplicada a cada dia que tem manobras com prático real:
  - `seq` = práticos que manobraram naquele dia operacional, na ordem da primeira manobra (pelo SPPILOTS; com o mesmo minuto, na ordem de leitura).
  - `outs` = slots de regulares planejados que **não** manobraram no dia (slots vazios também contam).
  - `ins` = regulares que manobraram **sem** estar na escala, na ordem de `seq`, limitados a `len(outs)`.
  - Testam-se **todas** as formas de colocar `ins` nos `outs` (permutações). Escolhe-se a de **menor custo**; no empate, a primeira encontrada.
  - Custo (`_custo`): considerando só os regulares da escala resultante, é o menor número, entre as 12 rotações possíveis, de inversões da ordem real `seq` em relação à ordem dos slots. Ou seja, escolhe a colocação que deixa a vez real da E12 "mais em ordem".
  - Se não há `ins` ou não há `outs`, a escala planejada fica como está. Planejado que não manobrou e não foi substituído **continua na escala**.
  - Especiais nunca são movidos por essa correção.
- Troca de pessoas entre D1 e D2 → 5.5. Entre turnos → 4.2 e 5.6.
- A disponibilidade é sempre calculada a partir da última manobra real do prático no histórico simulado. Por isso, quem emenda dias por troca continua sujeito ao seu HH:MM.

### 5.10 Montagem dos turnos (`gerar_2026.py`, bloco 3)

```
para cada dia d com TIPO == 'D1' (em ordem):
    d2  ← d + 1
    nxt ← próximo dia com TIPO == 'D1' (ou d + 2)
    dia1 ← escala[d] ; dia2 ← escala[d2] (ou dia1, se d2 não existir)
    turno ← {dt_ini: d 07:30, dt_d2: d2 07:30, dt_fim: nxt 07:30, dia1, dia2, Y: dia1}
manter só os turnos com dt_ini <= última manobra da pauta
1º turno: se o 1º prático real do dia está em dia1, Y ← dia1 girado para começar por ele
```

Manobras anteriores ao primeiro `dt_ini` ou fora de qualquer turno **não são processadas**.

### 5.11 Montagem da pauta (`gerar_2026.py`, bloco 1)

1. Lê os CSVs e duplica as linhas de 2 práticos que vieram com uma só linha (5.1).
2. `corte = maior DT do histórico + 1 min`. Pauta = **todas** as linhas do histórico (com `DT < corte`) + linhas de `pauta_rt.csv` com `DT >= corte`.
3. Ordenação estável por `DT`. **A ordem das manobras do mesmo minuto é a ordem de leitura**: histórico (ordem do CSV) antes da pauta atual, e cópias de 2 práticos por último no minuto.
4. Sem histórico: lê `inputs/Pauta_de_Manobra_2026.xlsx` (`Data`, `Hora`, `Vessel`, `From`/`To` ou `De`/`Para`).
5. Grava `_pauta_live.xlsx` com `Data = DT em DD/MM/AAAA`, `Hora = DT em HH:MM`, `Termino`, `Vessel`, `From`, `To`.

### 5.12 Ordem de processamento das manobras do mesmo horário

1. Ordem da pauta (5.11), preservada pela ordenação estável do motor.
2. No motor, as manobras com o **mesmo `datetime`** formam um grupo. Os navios do grupo são processados **na ordem da primeira aparição de cada um**, e as linhas de um mesmo navio ficam juntas (4.3, passo 3). Não há prioridade de "par antes de solo" nem por tipo de manobra.
3. Cada linha escolhe o prático depois de a linha anterior ter atualizado a fila. Exemplo: se a 1ª linha foi uma B, aquele prático já foi para o fim da fila antes da 2ª linha.

Consequência: o **Seq da saída é a ordem de processamento**, que pode diferir do índice da linha na pauta (ex.: 27/01/2026 07:30 AGILITY DIVA, linhas 912 e 915 na pauta, sai com Seq 912 e 913). **[Ponto de atenção]**

### 5.13 Draga: manobras em sequência ficam com o mesmo prático (27/10/2026)

Caso típico: draga que entra, vai até um ponto e volta, várias vezes por dia. Regra da Praticagem: **duas manobras seguidas da draga, em sequência, são feitas pelo mesmo prático, como A e B do mesmo ciclo**, em qualquer combinação (entrada + saída, saída + entrada, com mudança). Se não for em sequência, segue a regra normal.

Implementação (`ep_sim_v3_corrigido.simular_turno`, bloco "DRAGA", antes do laço de manobras):

1. **Candidato a draga:** navio com **4 ou mais manobras (horários distintos)** em ±36 h da manobra. Navio de 2 práticos (duas linhas no mesmo horário) **nunca** entra.
2. **Em sequência:** a próxima manobra do mesmo navio (horário posterior) começa **onde a anterior terminou** (`De` da 2ª = `Para` da 1ª) e **até 30 min depois do fim previsto** da 1ª (início + T).
3. **Prioridade:** primeiro os pares em que a 2ª começa antes do fim previsto da 1ª (o prático ainda está a bordo); depois os demais. Cada manobra entra em no máximo um par (**pares não se encadeiam**).
4. **1ª manobra do par:** vai para o primeiro prático **livre e sem ciclo aberto** da fila (respeitando Z5); ele fica **reservado** (não pode ser escolhido para outra manobra) até a 2ª.
5. **2ª manobra do par:** vai para o mesmo prático, que fecha o ciclo (B) e vai para o fim da fila.
6. Se a 1ª foi para um especial, a regra não se aplica (segue normal).

Exemplos no conjunto de teste: HAM 316 (28–29/09/2026, 4 pares, reproduz a E12 real), UTRECHT (26–27/07, 5 pares), HANG JUN 6009 (25/04, 3 pares). Correção de 28/10/2026: a primeira versão contava linhas (e não horários) e juntava as duas linhas de um navio de 2 práticos (MSC AINO, 15/02); corrigido nos itens 1 e 2.

### 5.14 Giro sem atracar (FB → FB) (27/10/2026)

Manobra em que o navio entra, gira numa bacia e sai sem atracar (ex.: "entrada, giro e saída do TECON"). T pela linha `GIRO <área>` da tabela de T:

| Linha | T (min) |
|---|---|
| GIRO TECON | 90 |
| GIRO EMBRAPORT | 135 |
| GIRO BTP | 155 |
| GIRO ALEMOA | 160 |

Base: T ≈ 33 + 13,3 × d (d = distância da estação de praticagem à bacia de giro, em milhas; velocidade 9 nós, 1 milha para reduzir e 1 para retomar, giro de 20 min). Distâncias informadas pela Praticagem: Embraport 7,5 nm; bacia do BTP 9 nm.

Área: `gerar_2026.py` procura no texto da pauta (colunas OBS/Agente/Celulas) as palavras EMBRAPORT/DP WORLD, BTP, ALEMOA, TECON/SANTOS BRASIL; sem área identificada, GIRO TECON. Resultado em `motor_e2d/_giro_T.pkl` (chave `(AAAA-MM-DD HH:MM, 'FB', 'FB')`), passado ao motor pela variável `BTP_OV`. **[Ponto de atenção]** o painel ainda usa 60 min para o giro no cálculo do DL e da coluna lateral.

### 5.15 Escala real pela escala gráfica do SPPILOTS (provisório, 25/10/2026)

Hoje o único lugar onde se vê quem realmente trabalha em cada dia (com as trocas) é a **escala gráfica** do SPPILOTS (`escalas_anuais.asp`, POST `mes`/`ano`), que vem como **imagem**. `escala_grafica.py` lê essa imagem:

- 6 blocos de 12 colunas; bloco = grupo. Bloco do D1 = `((dias desde 01/01)/2 + 2) mod 6`.
- Linha do D1/D2 = dono do slot; dono riscado = não trabalha. Substitutos acima da linha do D1 (para o D1) e abaixo da linha do D2 (para o D2), empilhados; quem trabalha = o primeiro não riscado, do dono para fora.
- Siglas reconhecidas por comparação com o banco de modelos `escala_grafica_modelos.npz` (numpy + Pillow, sem OCR externo); aprende com as siglas confirmadas pelo histórico.
- Grava `inputs/escala_grafica.json` (`{"AAAA-MM-DD": [12 siglas ou null]}`).

**Em produção isso não deve existir:** a escala e as trocas estão no banco do SPPILOTS, de onde a imagem é gerada. Basta ler de lá e montar os turnos (5.10) no mesmo formato.

---

## 6. Saída

### 6.1 Planilha do motor (`E2D_OUT`, aba `E2D 2025`)

Linha 1: cabeçalho. Colunas:

| Col. | Nome | Conteúdo |
|---|---|---|
| A | `Seq` | Número sequencial (1..N) na ordem de processamento |
| B | `Data` | `DD/MM/AAAA` (texto da pauta) |
| C | `Hora` | `HH:MM` (início) |
| D | `Termino` | `HH:MM` ou vazio (informativo) |
| E | `Pratico` | Sigla |
| F | `Navio` | `Vessel` |
| G | `De` | Berço de origem |
| H | `Para` | Berço de destino |
| I | `Status` | `A`, `B` ou vazio (especiais) |
| J | `Escalacao` | Fila após a manobra (6.2) |

- `Status = 'B'` se a manobra fechou o ciclo. `Status = 'A'` se não fechou, o acumulado ficou em 1,0 e o prático não é especial. Vazio para especiais.
- **Divisória de dia**: antes da 1ª manobra de cada novo dia operacional (exceto o primeiro), uma linha com `"<n> Manobras"` na coluna A, em que *n* é o total de manobras do dia operacional **anterior**. As demais células ficam vazias. O último dia não tem divisória final.
- Formatação (informativa): especial verde-claro `#D5E8D4`; B verde `#D5F5E3`; A vermelho-claro `#FADBD8`; linhas alternadas `#EBF5FB`; divisória `#2C3E50` com texto amarelo.

### 6.2 Formato da escalação (`make_esc`)

Texto com os elementos separados por `" > "` (espaço, `>`, espaço). Representa a fila **depois** de aplicada a manobra da linha, avaliada no **horário e na origem dessa manobra**.

Exemplo real (01/01/2026, Seq 2):
`BD(09:30) > RG(10:30) > RO > LB > GU > GO > GE > BA > JA(9) > PI > FO > SI(15)`

#### 6.2.1 Regulares

Na ordem de `fila_display`, ignorando especiais:

- `XX(HH:MM)`: indisponível para uma manobra hipotética **com a mesma origem e o mesmo horário da linha atual**. HH:MM = `avail(p, From da linha)`. Por isso o HH:MM exibido muda conforme a origem da linha (margem 45 se a linha sai de FB, 25 nos demais casos, e L até essa origem).
- `XX`: disponível, nunca manobrou, ou **acabou de fazer a B** (marcado em `_no_hhmm`: depois da B, o prático aparece sem HH:MM até fazer a próxima A, mesmo que ainda não esteja livre). Atenção: isso é só exibição. Na escolha, a disponibilidade é sempre verificada.

#### 6.2.2 Especiais: `XX(N)`

`N` = quantas manobras faltam até a próxima manobra **forçada** desse especial (1 = a próxima linha). O especial é inserido na posição `N − 1` da lista (contando regulares e especiais já inseridos), limitada ao fim. Regras exatas (só exibição):

1. Os especiais são processados em ordem crescente de `next_slot`.
2. Se o especial **acabou de manobrar nesta linha** e a próxima manobra forçada dele no turno está a menos de 12 linhas, ele é exibido como `XX(12)` no **fim**.
3. Se existe próxima manobra forçada no turno: `N = posição absoluta dela − man_count` (exato, sem teto).
4. Se não existe: `N = max(1, next_slot − man_count)`. Se `N > 14`, exibe `XX(12)` no fim.

#### 6.2.3 Contadores de exibição dos especiais (`next_slot`)

Usados só no item 4 acima e no `ns_carry`:

- No início do turno: para cada especial presente em `Y`, `next_slot = man_count_prev + índice em Y` ou `man_count_prev + ns_carry`. Com forçamento, passa a ser a posição absoluta da 1ª manobra forçada dele no turno.
- Depois de manobrar: `+12`.
- Depois de cada grupo de mesmo minuto, ajuste ("catch-up"): se `next_slot < man_count`, soma 12 até alcançar `man_count`, depois subtrai 12 enquanto for maior que `man_count + 11` e, por fim, garante que não fique abaixo de `man_count` (com uma regra especial para a 2ª linha de pares).
- Na virada D1→D2: chave remapeada por slot (`Y_d1[i] → Y_d2[i]`).

**[Inferência]** Uma reimplementação pode simplificar a exibição dos especiais para "N = linhas até a próxima manobra forçada no turno; senão, 12 no fim", desde que se aceite a diferença em casos de borda de turno.

### 6.3 Planilha final do painel (`ao_vivo/E2D_2026_v6.xlsx`, aba `E2D 2026`)

Gerada por `gerar_2026.py` (bloco 6) a partir da saída do motor:

- Linha 1: título `E2D 2026 — margem 45 min antes de entrada / 25 min antes de saída e mudança — gerado DD/MM/AAAA HH:MM`.
- Linha 2: cabeçalho `Seq, Data, Hora, Termino, Pratico, Navio, De, Para, Pts(cont), Pts(real), Total, Status, #Pos, Escalacao`.
- Linhas 3 em diante: só as linhas com `Seq` inteiro (as divisórias de dia são removidas). `Pts(cont)`, `Pts(real)`, `Total` e `#Pos` ficam **vazias** (só existem por compatibilidade com o `ep_atualizar.py`).

### 6.4 Log de fallback

`FB_OUT` (pickle): lista de tuplas `(Timestamp início, prático, datetime em que ficaria livre, navio, de, para)`.

---

## 7. Parâmetros configuráveis e valores atuais

### 7.1 Parâmetros em vigor

| Parâmetro | Valor | Onde | Observação |
|---|---|---|---|
| `MARGEM_ENTRADA` | 45 min | env, `motor_e2d.py` | Próxima manobra sai de FB |
| `MARGEM_OUTRAS` | 25 min | env, `motor_e2d.py` | Saída e mudança |
| `ESP_SET` | `JA,SI,CH` | env, motor e `nova_escalacao` | Em `gerar_2026.py` é fixo |
| `Z5_LIMITE_DIA` | 1 | constante, `ep_sim_v3_corrigido.py` | |
| `THRESHOLD` | 2.0 | constante, `ep_sim_v3_corrigido.py` | Com 1 ponto por manobra = ciclo de 2 |
| Pontos por manobra | 1.0 | `pts_man_fn` (patch em `motor_e2d.py`) | `PTS_TABLE` também é zerada para 1,0 |
| `CARRY` | False | `ep_sim_v3_corrigido.py` | |
| Dia operacional | 07:30 | código | Fixo |
| T padrão (berço sem T) | 60 min | `gT` | |
| Tm padrão por par de zonas | `TM_ZONA`, padrão 60 | `ep_algoritmo.py` | |
| Zona padrão (berço sem zona) | 2 | `BERCO_ZONE_DEFAULT` | |
| Arredondamento | r15, ao mais próximo | `ep_algoritmo.r15` | |
| Slots E12 (simulação dos especiais) | 12 | `gerar_2026.py` | |
| Draga: manobras do navio em ±36 h | ≥ 4 (horários distintos) | `ep_sim_v3_corrigido.py`, bloco DRAGA | 5.13 |
| Draga: tolerância após o fim previsto da 1ª | 30 min | idem | 5.13 |
| T do giro sem atracar | linhas `GIRO …` da tabela T | `gerar_2026.py` → `BTP_OV` | 5.14 |

### 7.2 Parâmetros presentes no código, mas desligados ou sem efeito em produção

| Item | Situação |
|---|---|
| `BTP_OV` (pickle `{(início 'AAAA-MM-DD HH:MM', fr, to): T}`) | Opcional, desligado. Substitui o T de manobras específicas. |
| `TPLUS` (`"BERÇO:min;BERÇO2"`), `TPLUS_MIN` (padrão 15), `TPLUS_SO_SM` | Opcional, desligado. Soma minutos ao T de entradas e saídas naquele berço. Com `TPLUS_SO_SM=1`, não soma quando a próxima manobra sai de FB. |
| `ATRASO` (`"PR|AAAA-MM-DD HH:MM|min;…"`), `ATRASO_MAN` (pickle) | Opcional, desligado. Soma minutos à disponibilidade. |
| `PEND_OFF=1` | Desliga a regra de B pendente na virada. Não usar. |
| `DISP_PROX=1` | Exibição avaliada pela próxima manobra. Não usar. |
| `VIRADA_DUMP` | Grava em arquivo a escalação de cada virada. Diagnóstico. |
| `SEM_FORCA=1` | Ignora o mapa de especiais e volta ao rodízio interno. Não usar. |
| `REORD=direto/slot` | Modos alternativos de nova escalação. Não usar. |
| `BUFFER = 15` (`ep_sim_v3_corrigido`) | Só usado pela `avail_time_fn` original, que é **substituída** por `_avail_b45`. Sem efeito. |
| `ep_algoritmo.BUFFER = 30`, `THRESHOLD = 3.0`, `PTS_TABLE`, `simular_ep`, `BASE_DT`, `CICLO_H`, `grp_turno` | Legado da EP por pontos. Não usado pelo motor E2D. |
| `ATALAIA = 12` | Definido, **não usado** em lugar nenhum. |
| `GRUPO_A_DATA` | Dicionário vazio. Em todos os casos usa-se `turno['Y']`. |
| `real_cycle_ref`, `tctr` | Contadores sem efeito na escolha. |

### 7.3 Fila após a B

- `inserir_apos_B` é FIFO puro: depois da B o prático vai para o fim da fila.
- Não há nenhum outro critério de ordenação após a B.

---

## 8. Tabelas completas

### 8.1 `BERCO_ZONE` (berço → zona)

| Zona | Berços |
|---|---|
| 1 | `FB` |
| 2 | `29`, `29/30`, `29A`, `30`, `31`, `31/32`, `32`, `32/33`, `33`, `34`, `35.1`, `35.2`, `37.1`, `38`, `39`, `CTRLE`, `DOW`, `SAIPEM 1`, `SAIPEM 1/2`, `SAIPEM 2`, `SAIPEM 3`, `TC 1.1`, `TC 1.2`, `TC 2`, `TC 3`, `TEAG`, `TEG`, `TERMG`, `TEV`, `TGG` |
| 3 | `12-A`, `12-P`, `13/14`, `16/17`, `19`, `20/21`, `23`, `25`, `AGEO`, `CORTE`, `CS 1`, `CS 2`, `CS 3`, `CS 4`, `EMB-1`, `EMB-2`, `EMB-3`, `EMB-4`, `EMBR.`, `IB BC`, `IB SP`, `IB-OE`, `OUT 2/3`, `OUT-1`, `OUT-2`, `OUT-3`, `VAL` |
| 4 | `AL 1`, `AL 2`, `AL 3`, `AL 4`, `BTP-1`, `BTP-2`, `BTP-3`, `TRSP` |
| 5 | `COS 2`, `COS 3`, `COS 4`, `TIP-2`, `TIP-3`, `TIP-4`, `ULT` |
| padrão | qualquer outro código → **2** |

A comparação é exata (sensível a maiúsculas, espaços internos, ponto e hífen), após `strip`.

Berços que aparecem na pauta de 2026 e **não estão cadastrados** (caem na Z2 e, em entrada ou saída, em T = 60): `37.2` (10 manobras), `ALA` (4), `CS 1/2` (2), `EMB-1/2` (17), `LARGO` (2), `MORT` (4), `TC` (8). **[Ponto de atenção]**

### 8.2 `ZONE_MATRIX` (lancha, minutos, simétrica)

| | Z1 | Z2 | Z3 | Z4 | Z5 |
|---|---|---|---|---|---|
| **Z1** | 0 | 20 | 25 | 30 | 40 |
| **Z2** | 20 | 0 | 5 | 10 | 20 |
| **Z3** | 25 | 5 | 0 | 5 | 15 |
| **Z4** | 30 | 10 | 5 | 0 | 10 |
| **Z5** | 40 | 20 | 15 | 10 | 0 |

Par ausente → 0 (não ocorre, pois a matriz está completa).

### 8.3 `TM_ZONA` (Tm padrão de mudança sem histórico do par, minutos, simétrica)

| Par de zonas | Tm |
|---|---|
| Z2↔Z2 | 60 |
| Z3↔Z3 | 60 |
| Z3↔Z4 | 60 |
| Z5↔Z5 | 60 |
| Z2↔Z3 | 65 |
| Z4↔Z4 | 80 |
| Z2↔Z4 | 90 |
| Z3↔Z5 | 105 |
| Z2↔Z5 | 130 |
| demais (inclui Z4↔Z5 e pares com Z1) | 60 (`TM_ZONA_DEFAULT`) |

Na pauta de 2026, 131 das 312 mudanças não têm o par na tabela de mudanças e usam `TM_ZONA`.

### 8.4 `ATALAIA`

`ATALAIA = 12` minutos (Atalaia ↔ FB). **Não é usado** em nenhum cálculo do motor nem do orquestrador.

### 8.5 Tabela T de entrada e saída e tabela de mudanças

Ver Apêndice A (valores atuais do arquivo `Tempo_T__2025_.xlsx`).

---

## 9. Casos de borda e pontos de atenção

| # | Ponto | Onde | Impacto / recomendação |
|---|---|---|---|
| P1 | **r15 arredonda ao mais próximo**, não para cima. A docstring está errada. | `ep_algoritmo.r15` | Reproduzir exatamente. Até 7 min de "folga negativa". |
| P2 | Após a **A o prático não muda de posição**. A ordem da frente da fila é a ordem em que os práticos fizeram a A, não o HH:MM. `inserir_apos_A` nunca é chamada. O cabeçalho do arquivo ("HH:MM ord. por horário") não corresponde ao comportamento. | `atualizar_nao_esp`, `ep_next` | Implementar como posição fixa, não como seção ordenada. |
| P3 | Se o mapa de especiais estiver **vazio**, o motor muda de modo: passa a escalar especiais por contador interno (pré-atribuição e `esp_due`). | `simular_turno` | Em produção, garantir sempre o forçamento. A reimplementação pode tratar "mapa vazio" como "sem especiais". |
| P4 | **Possível erro de execução**: `atualizar_esp` lê `next_slot[prat]` mesmo com `_rr_orig.pop` (o argumento padrão é avaliado antes). Um especial forçado num turno em que **não consta do `dia1`** (só no D2, ou fora da escala) gera `KeyError` e o motor para. Não aconteceu em 2026 até 20/10 (nenhum turno com especial só no D2), mas o caso é possível com trocas de especiais. | `atualizar_esp`, `_esc_d1` | Na reimplementação, desacoplar a exibição dos especiais da escolha. |
| P5 | Na virada D1→D2, os contadores de exibição dos especiais são remapeados **por índice de slot**. Se um especial mudar de slot entre D1 e D2, o contador passa a outra sigla e o especial pode sumir da exibição (e cair no P4). | `simular_turno`, D1→D2 | Só exibição, mais o risco do P4. |
| P6 | **Seq da saída ≠ índice da pauta.** O motor reagrupa as linhas do mesmo navio no mesmo minuto. Já o `ESP_FONTE` usa o índice da pauta (`Seq − 1`) e confere o navio com `assert`. | `motor_e2d.py`, `simular_turno` | A integração deve usar a chave (Data, Hora, Navio), não o Seq. |
| P7 | A cópia criada para o navio de 2 práticos com uma só linha fica **por último no minuto**, não colada na original. Na simulação E12 dos especiais (que exige linhas adjacentes), o par vira 2 manobras "solo". Com prático real conhecido, as duas linhas recebem o **1º** nome da lista. Em 2026: 2 casos (AGILITY DIVA 27/01 07:30; GEORGE H 01/02 09:00). | `_completar_dois_praticos`, bloco 4 | Duplicar a linha logo após a original. |
| P8 | **Z5 tem prioridade sobre a disponibilidade**: se os disponíveis já fizeram Z5, é escolhido um indisponível sem Z5 (com registro de fallback). | `ESCOLHER` | Confirmar com a operação se é a regra desejada. |
| P9 | **Fallback não simula atraso**: o prático "atrasado" fica com a manobra no horário da pauta e a próxima disponibilidade dele é calculada a partir desse horário. | `ESCOLHER`, `atualizar_nao_esp` | Reproduzir e registrar. |
| P10 | O **HH:MM exibido depende da origem da linha atual** (margem 45/25 e L), então o mesmo prático pode aparecer com horários diferentes em linhas seguidas. Depois da B, o prático aparece **sem** HH:MM mesmo indisponível. | `make_esc` | Documentar para os usuários do painel. |
| P11 | **T truncado** pelo `int()` no motor (83,5 → 83 etc.), mas usado sem truncar (float) na simulação E12 dos especiais. | `carregar_dados`, `gerar_2026` bloco 4 | Reproduzir a truncagem no motor. |
| P12 | **Berços não cadastrados** caem na Z2 com T = 60 (lista em 8.1). `EMB-1/2` e `CS 1/2` são, fisicamente, Z3 **[Inferência]**. | `BERCO_ZONE`, `gT` | Cadastrar os berços, ou manter o padrão para fidelidade ao motor atual. |
| P13 | A data da escala é a **posição da linha** na aba RESUMO (`01/01/2026 + i`). As colunas MÊS e DIA são ignoradas. Uma linha inserida ou removida desloca o ano inteiro. | `gerar_2026` bloco 3 | Validar a integridade (365 linhas contíguas). |
| P14 | `corrigir` usa **permutações** (custo fatorial) e, num dia em andamento, quem ainda não manobrou conta como "não manobrou". Pode atribuir slots de forma provisória, que mudam ao longo do dia. **[Inferência]** | `corrigir` | Aceitável com poucos `ins`. Em produção, limitar ou otimizar. |
| P15 | Na simulação E12, o ponteiro (`ptr`) só é reposicionado em **D1 com prático real**. Em dias futuros (sem dado real), o ponteiro e o `buf` do dia anterior continuam valendo para a nova lista P. **[Inferência]** Pode não refletir a abertura real da E12. | `gerar_2026` bloco 4 | Conferir com a regra da E12. |
| P16 | Na simulação E12, as 2 linhas de um navio de 2 práticos precisam ser da **mesma classe** (2 especiais ou 2 regulares). | `gerar_2026` bloco 4 | Confirmar com a regra da E12. |
| P17 | Quando D1 e D2 têm **o mesmo conjunto** de pessoas (mesmo em slots diferentes), a fila não é refeita. Entre turnos com o mesmo conjunto, a fila volta para a **ordem dos slots** do D1 (perde a ordem anterior). | `motor_e2d.py`, D1→D2 | Raro, mas reproduzir. |
| P18 | A virada D1→D2 e a virada de dia operacional ocorrem **na primeira manobra** após 07:30, não às 07:30 em si. Sem manobras, nada muda. | `simular_turno` | Equivalente na prática. |
| P19 | `nova_escalacao` corta em **12** regulares e trunca `saindo`/`entrando` ao menor tamanho. | `nova_escalacao` | Sem efeito com 12 slots. |
| P20 | Sem `Termino` no CSV atual, a coluna Termino da saída fica vazia e a simulação E12 usa `início + T` como fim. | `gerar_2026` | Informativo. |
| P21 | Sem histórico, o ramo da pauta de reserva (`Pauta_de_Manobra_2026.xlsx`) exige a coluna `Termino` (senão dá `KeyError` na linha 93). | `gerar_2026` bloco 1 | Ramo de reserva. |
| P22 | `carregar_dados()` exige o arquivo `Manobras_2025__original_.xlsx`, embora o motor descarte o conteúdo. | `ep_algoritmo.carregar_dados` | Na reimplementação, ler só a tabela T. |
| P23 | Sem `ESP_FONTE`, o motor importa `engine_e12`, que **não está no pacote**. | `motor_e2d.py` | `ESP_FONTE` é obrigatório. |
| P24 | Comentários desatualizados: "15 min nas demais" (o valor é 25); a nota da aba T fala em "1.1×T + L + 0.5h" (não é usada). | `motor_e2d.py` l.43; xlsx | Ignorar. Vale o código. |
| P25 | Um turno sem manobras devolve `ultima_esc` vazio. O turno seguinte começa então pela ordem dos slots do D1 (não aplica `nova_escalacao`). | `simular_turno`, laço de turnos | Reproduzir. |
| P26 | Manobra cujo **mesmo navio aparece 2 vezes no mesmo minuto** é sempre tratada como 2 práticos. A chave de forçamento não usa De/Para. | `carregar_pauta`, forçamento | Garantir que a pauta não tenha duplicatas espúrias. |
| P27 | Quando o fallback não acha nenhum regular livre de atribuição no minuto, usa `fila_display[0]`, que pode ser especial ou alguém já atribuído. Extremamente improvável. | `ESCOLHER` | Tratar como erro na reimplementação. |
| P28 | O motor é recalculado do zero a cada execução. Mudanças no passado (escala corrigida, pauta) propagam para frente. **[Inferência]** | arquitetura | Definir com a operação se a produção "congela" o passado. |

Validações feitas na execução de 01/01 a 20/10/2026 (cópia isolada, sem alterar arquivos): 11.249 manobras; status A 5.417, B 5.409, especiais 423; nenhum regular com 2 manobras de mesmo status em sequência (alternância A/B perfeita); nenhum regular com mais de 1 Z5 por dia operacional; 6 fallbacks.

---

## 10. Referência cruzada: regra → arquivo/função

| Regra | Arquivo | Função / trecho |
|---|---|---|
| Fórmula de disponibilidade (margem 45/25, T, L, r15) | `motor_e2d/motor_e2d.py` | `_avail_b45` (l.51-63), substitui `sim.avail_time_fn` |
| Opcionais BTP_OV / TPLUS | `motor_e2d/motor_e2d.py` | l.49-50, 56-59 |
| Opcionais ATRASO / ATRASO_MAN | `motor_e2d/ep_sim_v3_corrigido.py` | l.36-39, `avail` |
| Disponível = nunca manobrou ou avail ≤ início | `ep_sim_v3_corrigido.py` | `is_avail` |
| T por tipo de manobra | `motor_e2d/ep_algoritmo.py` | `gT`, `tm_zona`, `TM_ZONA` |
| Lancha L | `ep_algoritmo.py` | `gL`, `ZONE_MATRIX`, `zona`, `BERCO_ZONE` |
| r15 | `ep_algoritmo.py` | `r15` |
| Leitura da tabela T (int) | `ep_algoritmo.py` | `carregar_dados` |
| Leitura da pauta e pares2 | `motor_e2d/carregar_pauta.py` | `carregar_pauta` |
| 1 ponto por manobra; ciclo de 2 | `motor_e2d.py` l.36-41; `ep_sim_v3_corrigido.py` | `pts_man_fn`, `THRESHOLD`, `atualizar_nao_esp` |
| A não move; B vai ao fim | `ep_sim_v3_corrigido.py` | `atualizar_nao_esp`, `inserir_apos_B` |
| Escolha: 1º disponível da fila | `ep_sim_v3_corrigido.py` | laço "PROCESSAR MANOBRAS" (l.543-611) |
| Restrição Z5 | `ep_sim_v3_corrigido.py` | `Z5_LIMITE_DIA`, `is_z5`, `_filtra_z5`, `z5_count` |
| Fallback "ninguém disponível" | `ep_sim_v3_corrigido.py` | `_mais_cedo`, `_FALLBACK_LOG`; gravação em `motor_e2d.py` l.429-430 |
| Grupo do mesmo minuto e ordem dos navios | `ep_sim_v3_corrigido.py` | l.433-451 |
| Especiais forçados | `motor_e2d.py` l.199-236; `ep_sim_v3_corrigido.py` l.551-566 | `_ESP_ATRIB_FORCADAS_KEY` |
| Pré-atribuição e rodízio de especiais (desativados) | `ep_sim_v3_corrigido.py` | l.465-540, 593-597 |
| Exibição dos especiais | `ep_sim_v3_corrigido.py` | `make_esc`, `atualizar_esp`, catch-up (l.670-683) |
| Virada de dia operacional e B pendente | `ep_sim_v3_corrigido.py` | `_calc_dia_op`, `_aplicar_pendentes` |
| Virada D1→D2 | `ep_sim_v3_corrigido.py` | l.404-426 |
| Virada entre turnos e B pendente entre turnos | `motor_e2d.py` | l.280-314 |
| Nova escalação | `motor_e2d/nova_escalacao.py` | `nova_escalacao`, `status_valido`, `parse_esc`, `fmt_esc` |
| Grupo A (vazio) | `motor_e2d/grupo_a_data.py` | `GRUPO_A_DATA = {}` |
| Saída do motor e divisórias | `motor_e2d.py` | l.345-427 (`logical_day`, `cols`) |
| Montagem da pauta ao vivo | `gerar_2026.py` | `_ler_csv`, `_completar_dois_praticos`, bloco 1 |
| Prático real e ordem do dia | `gerar_2026.py` | bloco 2 (`real`, `seq_dia`, `J`) |
| Escala do dia e correção | `gerar_2026.py` | bloco 3 (`plano`, `corrigir`, `_custo`) |
| Montagem dos turnos | `gerar_2026.py` | bloco 3 (`turnos`, rotação do 1º turno) |
| Simulação E12 dos especiais | `gerar_2026.py` | bloco 4 (`fim_de`, laço por `dop`) |
| Chamada do motor e planilha final | `gerar_2026.py` | blocos 5 e 6 |
| Draga (mesmo prático em manobras em sequência) | `ep_sim_v3_corrigido.py` | bloco DRAGA (`_draga_par`, `_draga_reserva`), `is_avail`, prefixo da escolha |
| Giro sem atracar | `gerar_2026.py` | bloco "Giro sem atracar" (`_GIRO_T`) |
| Escala real (imagem do SPPILOTS) | `escala_grafica.py`; `gerar_2026.py` | `atualizar`; bloco `_EG` |

---

## Apêndice A. Tabela de tempos (`motor_e2d/inputs/Tempo_T__2025_.xlsx`)

Valores atuais do arquivo. "T usado" = valor após o `int()` do motor.

### A.1 Aba `T Entrada ou saída` (T de entrada e de saída por berço)

| Berço | Zona | T no arquivo (min) | T usado (min) |
|---|---|---|---|
| `12-A` | 3 | 80 | 80 |
| `12-P` | 3 | 83.5 | 83 |
| `13/14` | 3 | 75 | 75 |
| `16/17` | 3 | 85 | 85 |
| `19` | 3 | 75 | 75 |
| `20/21` | 3 | 75 | 75 |
| `23` | 3 | 65 | 65 |
| `25` | 3 | 60 | 60 |
| `29` | 2 | 60 | 60 |
| `29/30` | 2 | 60 | 60 |
| `29A` | 2 | 70 | 70 |
| `30` | 2 | 60 | 60 |
| `31` | 2 | 60 | 60 |
| `31/32` | 2 | 60 | 60 |
| `32` | 2 | 60 | 60 |
| `32/33` | 2 | 60 | 60 |
| `33` | 2 | 60 | 60 |
| `34` | 2 | 60 | 60 |
| `35.1` | 2 | 60 | 60 |
| `35.2` | 2 | 60 | 60 |
| `37.1` | 2 | 60 | 60 |
| `38` | 2 | 60 | 60 |
| `39` | 2 | 60 | 60 |
| `AGEO` | 3 | 90 | 90 |
| `AL 1` | 4 | 109 | 109 |
| `AL 2` | 4 | 105 | 105 |
| `AL 3` | 4 | 95 | 95 |
| `AL 4` | 4 | 100 | 100 |
| `BTP-1` | 4 | 105 | 105 |
| `BTP-2` | 4 | 105 | 105 |
| `BTP-3` | 4 | 100 | 100 |
| `CORTE` | 3 | 75 | 75 |
| `COS 2` | 5 | 130 | 130 |
| `COS 3` | 5 | 120 | 120 |
| `COS 4` | 5 | 120 | 120 |
| `CS 1` | 3 | 85 | 85 |
| `CS 2` | 3 | 85 | 85 |
| `CS 3` | 3 | 90 | 90 |
| `CS 4` | 3 | 75 | 75 |
| `CTRLE` | 2 | 60 | 60 |
| `DOW` | 2 | 60 | 60 |
| `EMB-1` | 3 | 90 | 90 |
| `EMB-2` | 3 | 85 | 85 |
| `EMB-3` | 3 | 80 | 80 |
| `EMB-4` | 3 | 90 | 90 |
| `EMBR.` | 3 | 60 | 60 |
| `IB BC` | 3 | 75 | 75 |
| `IB SP` | 3 | 76.5 | 76 |
| `IB-OE` | 3 | 85 | 85 |
| `OUT 2/3` | 3 | 60 | 60 |
| `OUT-1` | 3 | 60 | 60 |
| `OUT-2` | 3 | 80 | 80 |
| `OUT-3` | 3 | 70 | 70 |
| `SAIPEM 1` | 2 | 45 | 45 |
| `SAIPEM 1/2` | 2 | 45 | 45 |
| `SAIPEM 2` | 2 | 45 | 45 |
| `SAIPEM 3` | 2 | 50 | 50 |
| `TC 1.1` | 2 | 60 | 60 |
| `TC 1.2` | 2 | 60 | 60 |
| `TC 2` | 2 | 65 | 65 |
| `TC 3` | 2 | 65 | 65 |
| `TEAG` | 2 | 60 | 60 |
| `TEG` | 2 | 60 | 60 |
| `TERMG` | 2 | 60 | 60 |
| `TEV` | 2 | 60 | 60 |
| `TGG` | 2 | 60 | 60 |
| `TIP-2` | 5 | 127.5 | 127 |
| `TIP-3` | 5 | 120 | 120 |
| `TIP-4` | 5 | 125 | 125 |
| `TRSP` | 4 | 157.5 | 157 |
| `ULT` | 5 | 125 | 125 |
| `VAL` | 3 | 85 | 85 |

Berço ausente desta tabela (inclusive os não cadastrados em `BERCO_ZONE`) → T = 60.

### A.2 Aba `Mudanças de entre berços` (Tm por par direcional De → Para; 205 pares)

| De | Para | Tm (min) |
|---|---|---|
| `12-A` | `13/14` | 55 |
| `12-A` | `16/17` | 70 |
| `12-A` | `37.1` | 70 |
| `12-A` | `EMB-3` | 70 |
| `13/14` | `12-A` | 75 |
| `13/14` | `13/14` | 50 |
| `13/14` | `30` | 60 |
| `16/17` | `20/21` | 45 |
| `16/17` | `29` | 60 |
| `16/17` | `35.2` | 60 |
| `16/17` | `AL 3` | 95 |
| `16/17` | `TIP-3` | 105 |
| `19` | `16/17` | 60 |
| `19` | `19` | 80 |
| `19` | `23` | 60 |
| `19` | `35.2` | 75 |
| `20/21` | `30` | 90 |
| `20/21` | `32` | 60 |
| `20/21` | `33` | 65 |
| `20/21` | `35.1` | 60 |
| `20/21` | `35.2` | 60 |
| `20/21` | `39` | 80 |
| `23` | `31` | 60 |
| `23` | `CS 2` | 60 |
| `23` | `TERMG` | 60 |
| `23` | `TIP-4` | 120 |
| `25` | `30` | 50 |
| `25` | `TC 1.1` | 50 |
| `29` | `31` | 60 |
| `29` | `33` | 30 |
| `29` | `BTP-3` | 80 |
| `29` | `COS 2` | 110 |
| `29` | `EMBR.` | 30 |
| `29/30` | `12-A` | 90 |
| `30` | `13/14` | 90 |
| `30` | `29/30` | 60 |
| `30` | `30` | 60 |
| `31` | `31` | 75 |
| `31` | `35.1` | 60 |
| `31` | `BTP-3` | 105 |
| `31` | `EMB-1` | 75 |
| `31` | `EMB-3` | 75 |
| `32` | `33` | 45 |
| `32` | `35.1` | 60 |
| `32` | `CS 2` | 60 |
| `32` | `EMB-3` | 80 |
| `32` | `EMB-4` | 60 |
| `33` | `33` | 110 |
| `33` | `CS 2` | 70 |
| `33` | `EMB-4` | 60 |
| `34` | `31` | 60 |
| `34` | `32` | 45 |
| `34` | `35.2` | 60 |
| `34` | `CS 4` | 90 |
| `34` | `EMB-3` | 60 |
| `34` | `EMB-4` | 60 |
| `35.1` | `33` | 35 |
| `35.1` | `35.1` | 70 |
| `35.1` | `CORTE` | 60 |
| `35.1` | `EMB-3` | 75 |
| `35.2` | `33` | 40 |
| `35.2` | `34` | 45 |
| `35.2` | `35.1` | 45 |
| `35.2` | `35.2` | 60 |
| `35.2` | `CS 4` | 75 |
| `35.2` | `EMB-3` | 80 |
| `37.1` | `23` | 60 |
| `37.1` | `35.1` | 60 |
| `37.1` | `OUT-3` | 80 |
| `37.1` | `TEG` | 30 |
| `38` | `35.2` | 90 |
| `38` | `38` | 80 |
| `AL 1` | `AL 1` | 85 |
| `AL 1` | `OUT-1` | 110 |
| `AL 2` | `DOW` | 75 |
| `AL 2` | `IB SP` | 60 |
| `AL 3` | `AGEO` | 60 |
| `AL 3` | `AL 4` | 70 |
| `AL 3` | `DOW` | 90 |
| `AL 3` | `IB BC` | 60 |
| `AL 3` | `IB SP` | 60 |
| `AL 3` | `IB-OE` | 60 |
| `AL 4` | `AGEO` | 60 |
| `AL 4` | `CS 2` | 120 |
| `AL 4` | `DOW` | 90 |
| `AL 4` | `IB BC` | 75 |
| `AL 4` | `IB SP` | 60 |
| `AL 4` | `IB-OE` | 60 |
| `BTP-1` | `EMB-1` | 80 |
| `BTP-1` | `EMB-2` | 75 |
| `BTP-2` | `EMB-2` | 65 |
| `BTP-3` | `25` | 80 |
| `BTP-3` | `EMB-1` | 70 |
| `BTP-3` | `EMB-2` | 75 |
| `CORTE` | `CORTE` | 60 |
| `CORTE` | `TEV` | 105 |
| `COS 2` | `25` | 110 |
| `COS 2` | `COS 2` | 30 |
| `COS 3` | `CS 4` | 60 |
| `CS 1` | `29` | 80 |
| `CS 1` | `CS 1` | 90 |
| `CS 1` | `TC 2` | 100 |
| `CS 2` | `CS 2` | 85 |
| `CS 3` | `CS 3` | 55 |
| `CS 3` | `TC 1.2` | 75 |
| `CS 4` | `34` | 85 |
| `CS 4` | `CS 1` | 60 |
| `CS 4` | `EMB-3` | 60 |
| `CS 4` | `EMB-4` | 90 |
| `CTRLE` | `23` | 60 |
| `DOW` | `25` | 60 |
| `DOW` | `29` | 55 |
| `DOW` | `29A` | 60 |
| `DOW` | `31` | 55 |
| `DOW` | `AL 3` | 105 |
| `DOW` | `AL 4` | 100 |
| `DOW` | `IB BC` | 80 |
| `DOW` | `IB SP` | 90 |
| `DOW` | `IB-OE` | 75 |
| `EMB-1` | `25` | 60 |
| `EMB-1` | `31` | 100 |
| `EMB-1` | `BTP-1` | 60 |
| `EMB-1` | `BTP-2` | 60 |
| `EMB-1` | `BTP-3` | 75 |
| `EMB-1` | `EMB-1` | 40 |
| `EMB-1` | `TC 1.2` | 60 |
| `EMB-2` | `31/32` | 60 |
| `EMB-2` | `BTP-1` | 80 |
| `EMB-2` | `BTP-3` | 60 |
| `EMB-2` | `EMB-2` | 45 |
| `EMB-2` | `EMB-3` | 60 |
| `EMB-2` | `TC 1.2` | 55 |
| `EMB-2` | `TEV` | 65 |
| `EMB-3` | `34` | 60 |
| `EMB-3` | `CORTE` | 60 |
| `EMB-3` | `EMB-3` | 80 |
| `EMB-3` | `TC 1.1` | 50 |
| `EMB-3` | `TC 2` | 60 |
| `EMB-4` | `35.2` | 60 |
| `EMBR.` | `29` | 30 |
| `FB` | `FB` | 80 |
| `IB BC` | `AL 2` | 70 |
| `IB BC` | `AL 3` | 60 |
| `IB BC` | `AL 4` | 60 |
| `IB BC` | `DOW` | 75 |
| `IB SP` | `AL 3` | 60 |
| `IB SP` | `AL 4` | 55 |
| `IB SP` | `DOW` | 75 |
| `IB-OE` | `AGEO` | 45 |
| `IB-OE` | `AL 3` | 60 |
| `IB-OE` | `AL 4` | 60 |
| `IB-OE` | `CS 1` | 45 |
| `IB-OE` | `DOW` | 65 |
| `OUT-1` | `25` | 40 |
| `OUT-1` | `AL 1` | 90 |
| `SAIPEM 1` | `SAIPEM 3` | 30 |
| `SAIPEM 2` | `SAIPEM 1` | 50 |
| `SAIPEM 2` | `SAIPEM 2` | 110 |
| `SAIPEM 2` | `SAIPEM 3` | 55 |
| `SAIPEM 3` | `SAIPEM 1` | 45 |
| `SAIPEM 3` | `SAIPEM 2` | 40 |
| `SAIPEM 3` | `SAIPEM 3` | 35 |
| `TC 1.1` | `25` | 70 |
| `TC 1.1` | `EMB-1` | 90 |
| `TC 1.1` | `EMB-2` | 60 |
| `TC 1.1` | `TC 1.1` | 50 |
| `TC 1.2` | `BTP-1` | 85 |
| `TC 1.2` | `TC 1.2` | 60 |
| `TC 1.2` | `TC 2` | 60 |
| `TC 1.2` | `TC 3` | 55 |
| `TC 2` | `EMB-2` | 60 |
| `TC 2` | `TC 1.1` | 65 |
| `TC 2` | `TC 2` | 60 |
| `TC 3` | `29` | 50 |
| `TC 3` | `TC 1.2` | 70 |
| `TC 3` | `TEV` | 60 |
| `TEAG` | `16/17` | 70 |
| `TEG` | `23` | 90 |
| `TERMG` | `TIP-4` | 150 |
| `TERMG` | `ULT` | 120 |
| `TEV` | `TEV` | 55 |
| `TEV` | `VAL` | 70 |
| `TGG` | `TGG` | 35 |
| `TIP-2` | `12-A` | 105 |
| `TIP-2` | `16/17` | 120 |
| `TIP-2` | `35.2` | 135 |
| `TIP-2` | `TIP-3` | 60 |
| `TIP-2` | `TIP-4` | 90 |
| `TIP-2` | `ULT` | 50 |
| `TIP-3` | `12-A` | 115 |
| `TIP-3` | `16/17` | 120 |
| `TIP-3` | `20/21` | 110 |
| `TIP-3` | `39` | 90 |
| `TIP-3` | `TIP-2` | 60 |
| `TIP-4` | `23` | 90 |
| `TIP-4` | `COS 2` | 120 |
| `TIP-4` | `TIP-2` | 80 |
| `TIP-4` | `TIP-3` | 60 |
| `ULT` | `25` | 115 |
| `ULT` | `CS 1` | 105 |
| `ULT` | `TIP-2` | 60 |
| `VAL` | `CS 4` | 60 |
| `VAL` | `EMB-3` | 60 |
| `VAL` | `TEV` | 70 |
| `VAL` | `VAL` | 45 |

Par (De, Para) ausente → `TM_ZONA` do par de zonas (8.3) → 60.
