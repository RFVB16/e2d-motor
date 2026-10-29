# Pacote de implementação — E2D (Escala 2 e Desce)

Praticagem do Porto de Santos (ZP-16) · versão de 28/10/2026

Este pacote reúne o que uma equipe de TI precisa para implementar a E2D em produção e operá-la num **período de teste em paralelo com a escala atual (E12)**. A E2D já existe como protótipo funcionando (simulação em Python + painel web publicado), validado contra os dados reais de 2025 e 2026. O trabalho de implementação é transformar esse protótipo num sistema robusto, integrado ao SPPILOTS e operado pela Praticagem.

## Ordem de leitura

| Arquivo | Para quê |
|---|---|
| `01_Visao_geral_e_escopo.md` | O que é a E2D, o que precisa ser entregue, como será o teste em paralelo |
| `02_Especificacao_regras_E2D.md` | **Regras completas do motor de escalação** — o coração do sistema |
| `03_Arquitetura_e_integracao.md` | Como o protótipo funciona hoje e a arquitetura recomendada para produção (integração SPPILOTS, hospedagem, segurança) |
| `04_Dados_e_formatos.md` | Formato de todas as entradas e saídas |
| `05_Validacao_e_teste_paralelo.md` | Como provar que a implementação está correta e como conduzir o teste em paralelo com a E12 |
| `06_Painel_requisitos.md` | O que a tela (painel ao vivo) mostra e como cada número é calculado |
| `07_Esforco_e_cronograma.md` | Estimativa de esforço e etapas |

## Pastas

| Pasta | Conteúdo |
|---|---|
| `codigo_referencia/` | Código do protótipo atual (Python). É a **referência oficial** das regras: em caso de dúvida entre um texto e o código, vale o código. Mesma estrutura de pastas do protótipo em uso. |
| `codigo_referencia/motor_e2d/` | Motor da E2D (simulação da fila) |
| `testes/` | Conjunto de teste com entrada e resultado esperado (01/01 a 13/11/2026, 11.320 manobras; esperado regerado em 29/10/2026 com a nova escalação indireta, o modelo original; o esperado da troca direta fica em `esperado_alternativo/`) e os scripts `rodar_referencia.py`, `comparar.py` e `testar_congelamento.py` (teste da escalação congelada, 02 5.16) |
| `dados/` | Dados reais de 2026 para estudo: pauta consolidada com início/fim reais e histórico do SPPILOTS com o prático de cada manobra |

## Teste rápido (5 minutos)

```
cd testes
python rodar_referencia.py          # roda o motor de referência
python comparar.py saida_referencia.csv
```
Resultado esperado: 100% em Prático, Status e Escalação. Uma nova implementação é considerada correta quando produz o mesmo resultado (`python comparar.py <saida_da_nova_implementacao.csv>`).

Requisitos: Python 3.10+ com `pandas`, `openpyxl`, `xlsxwriter` (o painel também usa `requests` e `beautifulsoup4`).

## O que NÃO está no pacote

- **Senha do SPPILOTS.** O protótipo usa o usuário de um prático e a senha fica num `config.json` local, que não foi incluído. A produção deve usar uma credencial de serviço própria (ver `03_Arquitetura_e_integracao.md`).
- **Dados pessoais além do necessário.** Os arquivos de `dados/` e `testes/` identificam práticos por bigrama (2 letras) e contêm horários de trabalho reais: tratar como confidenciais e não publicar.

## Contato

Responsável técnico pela especificação: Rodrigo de Freitas Villas Bôas (prático, Praticagem de Santos).
