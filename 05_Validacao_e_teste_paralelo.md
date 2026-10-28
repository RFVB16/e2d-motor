# 5. Validação e teste em paralelo

## 5.1 Validação em bancada (obrigatória antes de qualquer uso)

**Conjunto de teste:** `testes/entrada/` (pauta de 01/01 a 13/11/2026, 11.320 manobras-prático, 159 turnos, 424 manobras de especiais) e `testes/esperado/E2D_esperado.csv` (resultado do motor de referência).

**Critério de aceite:** a nova implementação, com as mesmas entradas, produz
- **Prático: 100%** igual;
- **Status (A/B): 100%** igual;
- **Escalação (fila após cada manobra): 100%** igual (desejável; divergência só de formatação é aceitável se documentada).

Como conferir:
```
cd testes
python rodar_referencia.py                 # opcional: mostra que a referência reproduz 100%
python comparar.py <saida_da_implementacao.csv>
```
O `comparar.py` lista as primeiras divergências. Como a fila é sequencial, **a primeira divergência é a que importa**: as seguintes costumam ser consequência dela.

Testes adicionais recomendados (unitários), cada um com um caso pequeno montado à mão:
1. Ciclo simples A → B → fim da fila.
2. Disponibilidade com margem 45 (próxima é entrada) × 25 (saída/mudança), lancha entre zonas e arredondamento r15.
3. Várias manobras no mesmo horário (ordem de processamento).
4. Navio de 2 práticos.
5. Ninguém disponível (escolhe quem fica livre primeiro).
6. Restrição Z5 (no máximo 1 manobra Z5 por prático por dia operacional).
7. Virada das 07:30: D1 → D2 e troca de turno, prático com B pendente.
8. Especiais fixos (não afetam a ordem dos regulares além do que a especificação prevê).
9. Trocas: prático que entra no lugar de outro.

## 5.2 Reprocessamento histórico

Rodar a implementação sobre todo 2026 a partir dos dados reais (histórico SPPILOTS + escala efetiva) e comparar com o protótipo. Diferenças só são aceitas se explicadas por diferença de entrada (ex.: pauta mais nova).

## 5.3 Teste em paralelo com a E12 (operação real)

**Duração sugerida:** 2 a 3 meses (cada grupo passa várias vezes, inclui dias de pico e viradas de turno com trocas).

**Durante o teste:**
- A E2D roda ao vivo sobre a pauta real, atualizando a cada poucos minutos.
- A E12 continua sendo a escala oficial (ou, se decidido, a E2D escala e a E12 fica de contingência).
- Todo dado recebido e toda escalação calculada ficam registrados com data/hora.

**Registro de alterações e casos (diário):**
- mudanças de horário de manobras já distribuídas;
- manobras canceladas/incluídas;
- casos em que a E2D indicaria um prático indisponível ou em horário inviável (o painel marca "⚠ livre hh:mm");
- trocas de última hora, faltas, especiais;
- divergências apontadas pelos práticos.

**Relatório periódico (semanal) E2D × E12:**
- manobras por prático;
- descanso longo (fim da B → início da próxima A; fim = início + T + lancha até a Atalaia);
- maior descanso por prático e por dia, em especial nos dias de pico (≥ 44 manobras);
- manobras entre 00h e 07h por prático;
- frequência de estouro de margem e de atraso real (usando o término real, quando disponível);
- casos "ninguém disponível".

**Critérios para encerrar o teste com sucesso** (a definir pela Praticagem; sugestão):
- nenhuma divergência de regra não explicada;
- disponibilidade de dados ≥ 99% do tempo;
- indicadores de descanso e atraso compatíveis com os da simulação.
