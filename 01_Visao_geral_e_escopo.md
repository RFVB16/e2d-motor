# 1. Visão geral e escopo

## 1.1 O problema

A Praticagem de Santos tem cerca de 60 práticos, escalados em grupos de 12 que trabalham 2 dias seguidos (D1 e D2) e folgam. O porto tem em média ~39 manobras por dia (contando cada prático de navios de 2 práticos), com dias de pico acima de 44.

Na escala atual (**E12**), as manobras do dia são distribuídas em rodízio fixo entre os 12 práticos. Na **E2D — Escala 2 e Desce**, cada prático faz um **ciclo de duas manobras próximas** (A e B) e depois vai para o fim da fila. O objetivo é concentrar o trabalho em pares e garantir descansos longos entre os ciclos, mantendo a divisão equilibrada das manobras.

Resultados da simulação (dados reais, para contexto):
- descanso longo mediano entre ciclos em torno de 9h (contra cerca de 5h na E12);
- em dias de pico, todos os práticos mantêm pelo menos um descanso de 5 h ou mais;
- as margens de disponibilidade (45 min antes de entrada, 25 min antes de saída/mudança) cobrem a variação real das manobras: atraso real na manobra seguinte em cerca de 0,4% das passagens A→B.

## 1.2 O que precisa ser entregue

1. **Motor E2D em produção** — reimplementação (ou empacotamento robusto) do motor descrito em `02_Especificacao_regras_E2D.md`, reproduzindo 100% o conjunto de teste (`05_Validacao_e_teste_paralelo.md`).
2. **Integração com o SPPILOTS** — leitura automática e confiável de:
   - pauta de serviço (manobras programadas, confirmadas e não confirmadas, com navio, tipo E/S/M, berços, horário, navios de 2 práticos);
   - histórico (manobras executadas e o prático que fez cada uma);
   - escala do dia (quem está escalado, trocas, especiais).
   Sem depender do computador ou do navegador de um prático (ver 03).
3. **Painel ao vivo** — página web com a pauta simulada pela E2D, a fila, disponíveis/indisponíveis, descanso longo e avisos (ver 06). Já existe um protótipo funcional que serve de modelo.
4. **Registro e auditoria** — guardar, a cada atualização, a pauta recebida e a escalação calculada, para comparar com a E12 e reproduzir qualquer decisão depois.
5. **Ferramentas do teste em paralelo** — relatórios diários comparando E2D × E12 e o registro de alterações (ver 05).

## 1.3 Fora do escopo (nesta fase)

- Substituir a escalação oficial: durante o teste, **a E12 continua valendo**; a E2D roda em paralelo para comparação (ou, se a Praticagem decidir, escala de fato com a E12 como contingência).
- Mudanças nas regras da E2D: as regras estão fechadas na especificação. Ajustes de parâmetros (margens) devem ser configuráveis, mas os valores iniciais são os da especificação.

## 1.4 Como será o teste em paralelo (resumo)

1. Validação em bancada: a implementação reproduz o conjunto de teste (100%).
2. Reprocessamento histórico: roda sobre todo 2026 (dados reais) e confere com o protótipo.
3. Operação paralela: a E2D roda ao vivo, sobre a pauta real, ao lado da E12, por um período definido (sugestão: 2 a 3 meses, cobrindo todos os grupos várias vezes e dias de pico).
4. Registro de todas as alterações de pauta e casos especiais, e relatório periódico.

Detalhes em `05_Validacao_e_teste_paralelo.md`.

## 1.5 Papéis

| Papel | Quem | Responsabilidade |
|---|---|---|
| Dono das regras | Praticagem (comissão / R. Villas Bôas) | Decide qualquer dúvida de regra; aprova a validação |
| Implementação | TI / empresa contratada | Motor, integração, painel, registro, hospedagem |
| SPPILOTS | Mantenedor do sistema SPPILOTS | Fornecer acesso de leitura aos dados (API, exportação ou credencial de serviço) |
| Operação do teste | Praticagem | Acompanhar o painel, registrar ocorrências |
