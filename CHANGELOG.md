# Histórico de versões

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
