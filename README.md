# E2D — Escala 2 e Desce · motor e especificação

Praticagem do Porto de Santos (ZP-16). **Repositório privado e confidencial**: contém a escala e horários reais dos práticos.

Comece por [`00_LEIA-ME.md`](00_LEIA-ME.md).

## Teste rápido

```
cd testes
python rodar_referencia.py
python comparar.py saida_referencia.csv     # tem de dar 100% em Pratico, Status e Escalacao
```

## Regras de trabalho neste repositório

- **Quem define as regras é a Praticagem** (responsável: Rodrigo de Freitas Villas Bôas). Dúvida de regra não se resolve no código: pergunte.
- Toda mudança de regra atualiza, no mesmo commit: o código (`codigo_referencia/`), a especificação (`02_Especificacao_regras_E2D.md`), o resultado esperado (`testes/esperado/`) e o `CHANGELOG.md`.
- Mudança que não é de regra (integração, tela, desempenho) **não pode alterar** o resultado do teste: `comparar.py` tem de continuar 100%.
- **Nunca** versionar senhas, `config.json` ou credenciais.
