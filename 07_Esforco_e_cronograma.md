# 7. Esforço e cronograma (estimativa)

Estimativa para **um desenvolvedor experiente**, partindo deste pacote (regras especificadas, código de referência e conjunto de teste com resultado esperado). Não inclui o tempo de resposta do mantenedor do SPPILOTS.

| Etapa | Conteúdo | Esforço |
|---|---|---|
| 1. Motor | Reimplementar (ou empacotar) o motor; passar 100% no conjunto de teste; testes unitários dos casos de borda | 1–2 semanas |
| 2. Integração SPPILOTS | Coleta automática de pauta, histórico e escala (API/exportação; ou navegador sem interface em servidor) | 1–2 semanas (depende do SPPILOTS) |
| 3. Orquestração e dados | Montagem da pauta e da escala efetiva, banco com versões, reprocessamento, agendamento | ~1 semana |
| 4. Painel | Tela com os requisitos de `06`, login, celular | ~1 semana (há um protótipo funcional como modelo) |
| 5. Validação | Reprocessamento de 2026, conferência com o protótipo, ajustes | ~1 semana |
| 6. Implantação | Servidor, monitoramento, documentação de operação | 2–3 dias |
| **Total** | | **cerca de 1 a 2 meses** de um desenvolvedor |

Depois: **teste em paralelo de 2 a 3 meses**, com suporte sob demanda (correções e relatórios).

## Riscos principais
1. **Acesso aos dados do SPPILOTS** — sem uma forma oficial de leitura da pauta completa, a coleta fica frágil. Resolver antes de começar a etapa 2.
2. **Escala efetiva e trocas** — a escala planejada precisa ser corrigida pelo que aconteceu de fato; definir a fonte oficial das trocas.
3. **Pontos de atenção do código** — a seção 9 de `02_Especificacao_regras_E2D.md` lista comportamentos não óbvios ou frágeis do motor de referência (ex.: especial forçado num turno em que não está no D1, berços sem cadastro na tabela de zonas/T). Revisar com a Praticagem no início do projeto e decidir, para cada um, se a produção mantém o comportamento ou corrige.
4. **Interpretação de regras** — qualquer dúvida é resolvida pelo código de referência e, persistindo, pela Praticagem. Registrar as decisões.

## Entregáveis esperados
- Código-fonte e instruções de implantação.
- Relatório de validação (resultado do `comparar.py` = 100%).
- Painel em produção com login.
- Rotina de registro e relatórios do teste em paralelo.
