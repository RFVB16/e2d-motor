# Histórico de versões

## 28/10/2026 (3)
- **Painel:** relatório por prático (clicar no nome ou no A/B): E12 real × E2D no turno, descanso útil com o mesmo critério nas duas (fim + lancha até a Atalaia → 1 h antes da próxima); na E2D separa descanso longo e intervalo entre A e B (06).
- Especial: linha cinza até a manobra começar, preta depois. Símbolo ⚠ em amarelo.
- Atualização a cada 10 min (`instalar_agendamento.bat`).

## 28/10/2026 (2)
- **Escalação congelada** (02, 5.16): a partir de 1 h antes da manobra o prático regular escalado fica fixo. Uma vez que a linha fica vermelha, não muda mais. Registro em `dados/escalacao_congelada.csv`; o motor lê via `sim._FROZEN_KEY`. Congelamento de 28/10 11:40 vale para o passado.
- **Manobras órfãs**: manobra já iniciada que sumiu da pauta é mantida no painel (não desaparece).
- **Painel:** símbolo ⚠ (com explicação ao passar o mouse ou clicar) no lugar do texto "dentro do T"; linha cinza para especial escalado.

## 28/10/2026
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
