# Histórico de versões

## 31/10/2026
- **Painel, ⚠ "Escalado ainda em manobra":** aparece sempre que, na escalação (1 h antes), a manobra anterior do mesmo prático ainda não terminou pelo T, em A ou B (antes: "Escalado ainda a bordo", só na B e com mais de 30 min pela frente) (06).

## 29/10/2026
- **Painel recusa pauta de outra página:** se a maioria das manobras já passadas da `pauta_rt.csv` não existe no histórico (mín. 5), ela é guardada em `dados/pauta_rejeitada_<data hora>.csv` e o painel usa a última pauta boa (`dados/pauta_rt_ultima_boa.csv`). Caso: 29/10 15:03, 73 manobras de outra consulta congeladas por engano (removidas).
- **Painel, relatório por prático:** o trecho das 07:30 até o 1º acionamento aparece como "07:30 → 1º acionamento" e não conta mais como descanso longo; a manobra cancelada entra no relatório (o descanso vai até o acionamento dela; não conta como manobra).
- **Painel:** a manobra cancelada depois da escalação aparece em verde, com o prático escalado e, na coluna A/B, o que ela seria (A ou B); o Δt (descanso) vai até o horário da cancelada, e a manobra seguinte conta a partir dela (06; 02, 5.17).
- **Correção:** manobra branca (`FUTURO`) atrasada, já passada do horário e ainda na pauta, continua no painel e no motor (antes sumia). Caso KACEY 29/10 11:30 (SI): sem ela a previsão da E12 punha o SI na manobra seguinte (SUPER TOMIYASU 15:00) (02, 5.16).
- **Manobra cancelada depois da escalação** (linha verde; decisão da Praticagem): não conta como manobra, o prático vai para a frente de todos e vale para a próxima manobra ainda não escalada (início a partir de 1 h depois de o cancelamento ser visto). Novo `dados/manobras_canceladas.csv`, variável `CANCEL` no motor, script do navegador v1.4 (envia a linha verde como `CANCELADA`) (02, 5.17). Novo `testes/testar_cancelamento.py`. Resultado do teste de 2026 não muda (100%).
- **Painel:** na coluna Δt, o valor da manobra A (descanso longo) aparece em negrito amarelo com contorno preto (06).
- **Painel:** em navio de 2 práticos a coluna A/B mostra sempre os dois status (A/A e B/B, além de A/B) (06).
- **Painel refeito do zero** com as regras corretas; o congelamento anterior (gerado com a troca direta) foi descartado e o congelamento recomeça a partir daí (02, 5.16).
- **Congelamento pela cor da linha** (decisão da Praticagem): a manobra fica fixa quando começa (azul) ou termina (vermelha), e não mais 1 h antes. Branca e lilás ainda podem mudar, inclusive com atraso. Novo arquivo `dados/escalacao_finalizada.csv` (02, 5.16).
- **Correção do congelamento:** manobra de especial (mapa da E12) nunca é congelada; o especial prevalece (02, 5.16). Caso: GOLDEN THETIS 29/10 10:30 (AG congelado no lugar do JA). Novo teste 3 em `testes/testar_congelamento.py`. Resultado do teste de 2026 não muda (100%).
- **Nova escalação volta ao modelo original (substituição indireta)**, o da apresentação e da planilha de 2025 (decisão da Praticagem). A troca direta, adotada em 24/10, fica disponível só com `REORD=direto`, para comparação (02, 5.6). Conferido: o código da regra indireta dá o mesmo resultado que a versão de 21/04/2026 em 30.000 casos aleatórios.
- `testes/esperado` regerado com a regra indireta. O esperado da troca direta foi mantido em `testes/esperado_alternativo/` e continua reproduzível (100% com `REORD=direto`).

## 28/10/2026
- **Escalação congelada** (decidida em 28/10): a partir de 1 h antes da manobra, o prático regular escalado fica fixo (`dados/escalacao_congelada.csv`, variável `FROZEN` no motor) (02, 5.16). Congelamento inicial 28/10 11:40; o passado anterior não foi reconstruído. Novo `testes/testar_congelamento.py`.
- **Manobras já iniciadas fora do histórico ("órfãs")** continuam no painel (02, 5.16).
- **Painel:** o ⚠ substitui o asterisco (passar o mouse ou tocar mostra "Risco de atraso" / "Escalado ainda a bordo"); especial escalado e não confirmado aparece em linha cinza (06).
- **Painel:** o giro sem atracar (FB → FB) passa a usar o T das linhas `GIRO …` no fim efetivo, na coluna lateral, no "⚠ livre hh:mm" e no ⚠ de observação (antes, 60 min) (02, 5.14).
- `testes/esperado` **não mudou**: o conjunto de teste não usa congelamento e continua 100% igual (11.320 manobras).
- **Regra da draga** (decidida em 27/10): manobras em sequência da draga ficam com o mesmo prático, como A e B (02, 5.13). Corrigido o caso de navio de 2 práticos ser tomado por draga.
- **Giro sem atracar** (FB → FB): linhas GIRO TECON 90, EMBRAPORT 135, BTP 155, ALEMOA 160 na tabela de T (02, 5.14).
- **Escala real** lida da escala gráfica do SPPILOTS (provisório; em produção, ler do banco) (02, 5.15).
- **Painel:** coluna Δt entre inícios (substitui "DL (efetivo)"); coluna Escalação oculta com botão; asterisco de observação (06).
- **Créditos removidos** de todo o código (já não tinham efeito). Resultado do motor idêntico.
- Arquitetura: integração direta com o banco do SPPILOTS, contingência com motor reserva, controle de versões (03, 3.3).
- `testes/esperado` regerado com o motor atual.

## 24/10/2026
- Nova escalação por troca direta (02, 5.6).

## 21/10/2026
- Primeira versão do pacote.
