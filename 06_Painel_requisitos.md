# 6. Painel ao vivo — requisitos

Modelo: o painel do protótipo (`codigo_referencia/ep_atualizar.py`, função `gerar_painel`), publicado hoje como página estática. A produção pode reconstruir com outra tecnologia, mantendo o conteúdo e os cálculos abaixo.

## 6.1 Cabeçalho
- Título "E2D — Escala 2 e Desce | Porto de Santos".
- **"Atualizado às hh:mm (dd/mm) · há X min"**, calculado no navegador do leitor; vira etiqueta vermelha "⚠ desatualizado há …" acima de 30 min sem atualização.
- Hora em que a pauta do SPPILOTS foi lida.
- Manobras de ontem e de hoje, média do ano por dia (contando cada prático de navio de 2 práticos).
- Navios de 2 práticos hoje.
- **Descanso médio efetivo (Δt)** e **Posições médias após B** (definições em 6.5).
- Faixa: "Dados atualizados a cada 15 min · próxima verificação em m:ss" (a página se recarrega sozinha).

## 6.2 Tabela principal — pauta simulada pela E2D
Uma linha por manobra (navio de 2 práticos em uma linha, práticos separados por "/"), em ordem de horário; **empate de horário na ordem de processamento do motor** (Seq), para a coluna Escalação de cada linha seguir a anterior.

| Coluna | Conteúdo |
|---|---|
| Navio | nome |
| Local | `E 39` (entrada), `S 39` (saída), `M 34 → 35.2` (mudança) |
| Horário | dd/mm hh:mm; se a manobra não é confirmada e o prático escalado só fica livre depois, mostra abaixo "⚠ livre hh:mm" (horário previsto inviável) |
| PRT | prático(s) escalado(s) pela E2D; especiais destacados; **⚠ de observação** (6.5) |
| A/B | status no ciclo; em navio de 2 práticos mostra os dois, na ordem dos práticos (A/B, B/A, e também A/A e B/B) |
| Δt | **Na A** (descanso longo, em **negrito amarelo com contorno preto**): do **fim** da manobra anterior do mesmo prático (início + T + lancha até a Atalaia) até o **início** da A — o mesmo número do relatório por prático (desde 31/10/2026; antes era entre inícios). **Na B**: do início da A até o início da B. Em branco se a anterior foi em outro turno, em especiais e em manobras não confirmadas; em navio de 2 práticos, "ON 3h00 / BR 1h30", com o amarelo só na parte de quem está em A |
| Escalação | fila logo após a manobra (`XX(hh:mm)` = indisponível até hh:mm). **Oculta por padrão**; botão "Mostrar/Ocultar escalação" no título (escolha salva no navegador) |

Cor da linha pelo status do SPPILOTS: executada (rosa), confirmada/próxima (azul), em breve (lilás), não confirmada (branca). **Especial já escalado em manobra não confirmada:** linha cinza com texto branco, como no SPPILOTS.

Quando a manobra **começa** (linha azul) ou **termina** (linha vermelha), o nome do prático fica **congelado** e não muda mais (02, 5.16). Linhas brancas e lilases ainda podem mudar. Manobras já iniciadas que ainda não estão no histórico continuam aparecendo (02, 5.16). Manobra cancelada depois da escalação aparece em **verde**, como no SPPilots, com o prático que estava escalado e, na coluna A/B, o que ela seria (A ou B); o Δt vai até o horário da cancelada, e a manobra seguinte do prático conta a partir dela; o prático vai para a frente da fila (02, 5.17).

## 6.3 Coluna lateral
- **Z5 hoje**: manobras Z5 do dia operacional e quem fez.
- **Disponíveis · hh:mm (E) ou (S/M)**: fila na ordem da escalação após a **última manobra confirmada**, considerando quem estará livre na hora prevista da próxima manobra não confirmada (e do tipo dela). Se alguém está livre para a próxima mas não para o outro tipo no mesmo horário, mostra ao lado "E hh:mm" ou "S hh:mm". Se ninguém estiver livre: "⚠ ninguém livre às hh:mm · primeiro às hh:mm".
- **Indisponíveis · livre p/ E / S**: quem ainda está ocupado, com a hora em que fica livre para uma entrada (margem 45 + lancha até FB) e para uma saída/mudança (margem 25 + lancha até o berço da próxima saída/mudança da pauta).

## 6.4 Histórico semanal
Tabela por semana: período, manobras (média/dia), Δt médio efetivo, posições médias após B.

## 6.5 Definições dos cálculos
- **Fim efetivo de uma manobra** = início (horário da pauta) + T de tabela (giro sem atracar: T da linha `GIRO …`, 02 5.14) + lancha até a Atalaia. Lancha até a Atalaia: 12 min se termina em FB; se termina num berço, lancha de FB até o berço menos 12 (Z2 8, Z3 13, Z4 18, Z5 28 min).
- **DL efetivo** = início da A − fim efetivo da B anterior do mesmo prático, se não houve folga entre elas (o prático esteve escalado em todos os dias operacionais entre as duas).
- **Disponibilidade** (igual ao motor) = arredonda ao quarto de hora mais próximo (início da última manobra + T + margem + lancha do destino dela até a origem da próxima); margem 45 min se a próxima é entrada (sai de FB), 25 min nas demais.
- **Posições após B**: quantas manobras ocorrem entre a B de um prático e a A seguinte dele.
- **⚠ de observação (PRT)**: só em manobras confirmadas, a partir da escalação (1 h antes) e nos últimos 2 dias. Passando o mouse (ou tocando) no ⚠ aparece o motivo: **"Risco de atraso (XX)"** = fim previsto da A (início + T) + lancha a menos de 15 min do início da B; **"Escalado ainda em manobra (XX)"** = na escalação (início − 60 min), em A ou B, a manobra anterior do mesmo prático ainda não tinha terminado pelo T (início + T). Até 31/10/2026 só valia na B e com mais de 30 min pela frente. Registro em `dados/observacao_log.csv`.

## 6.6 Requisitos não funcionais
- Atualização a cada 1–5 min (protótipo: 15 min).
- Funciona em celular.
- Acesso com login (práticos e administração).
- Indicação clara de dados desatualizados ou com falha de coleta.
