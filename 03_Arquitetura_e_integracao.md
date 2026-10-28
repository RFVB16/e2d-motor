# 3. Arquitetura e integração

## 3.1 Como o protótipo funciona hoje

O protótipo roda no computador de um prático (Windows) e publica uma página estática no GitHub Pages.

```
 Chrome (aba do SPPILOTS logada)                 Computador (Windows)
 ┌───────────────────────────────┐   POST CSV    ┌─────────────────────────────────────────┐
 │ psh.asp (pauta de serviço)    │──────────────▶│ ep_server.py  (localhost:7373)          │
 │ script Tampermonkey: lê a     │  a cada 5 min │   grava pauta_rt.csv                    │
 │ tabela e envia (5 em 5 min)   │               │                                         │
 └───────────────────────────────┘               │ Agendador do Windows (15 em 15 min):    │
                                                 │ atualizar.bat → ep_atualizar.py         │
 SPPILOTS (login usuário/senha)  ◀── requests ───│   1. raspar_historico.py (histórico)    │
                                                 │   2. gerar_2026.py → motor_e2d.py       │
                                                 │      (pauta + escala + turnos + motor)  │
                                                 │   3. monta ep_painel.html               │
                                                 │   4. git push → GitHub Pages            │
                                                 └─────────────────────────────────────────┘
```

Arquivos (em `codigo_referencia/`):

| Arquivo | Função |
|---|---|
| `E2D_pauta_automatica.user.js` | Script de navegador: lê a tabela da pauta na página `psh.asp` do SPPILOTS e envia ao `ep_server.py`; refaz o login se a sessão cair |
| `ep_server.py` | Servidor local que recebe a pauta e grava `pauta_rt.csv` |
| `raspar_historico.py` | Baixa o histórico de manobras executadas (com o prático real) do SPPILOTS via HTTP (login + `psh.asp?act=ALL&dti=..&dtf=..`) |
| `gerar_2026.py` | Orquestrador: monta a pauta (histórico até a última manobra executada + pauta atual daí em diante), monta a escala efetiva e os turnos, define os especiais e chama o motor |
| `motor_e2d/` | Motor E2D (regras) |
| `ep_atualizar.py` | Executa tudo, calcula os indicadores e gera a página `ep_painel.html` |
| `ep_algoritmo.py` | Tabelas de zonas, lancha e T usadas pelo painel |
| `escala_grafica.py` + `escala_grafica_modelos.npz` | Lê a escala gráfica (imagem) do SPPILOTS para saber quem realmente está de serviço (provisório; ver 02, 5.15) |
| `atualizar.bat`, `*.vbs`, `instalar_*.bat` | Automação no Windows (agendador, início do servidor, publicação) |

### Limitações do protótipo (o que a produção precisa resolver)

1. **A pauta futura só sai pelo navegador.** O SPPILOTS só mostra as manobras programadas (inclusive as não confirmadas, linhas brancas) numa sessão de navegador; o acesso por HTTP direto devolve apenas as executadas. Por isso o protótipo depende de uma aba de Chrome aberta e logada.
2. **Depende de um computador ligado** e da credencial pessoal de um prático.
3. **Sessão única (suspeita):** o login do script Python a cada 15 min pode derrubar a sessão do navegador.
4. **Término real das manobras** não vem do SPPILOTS na pauta; usa-se o T de tabela.
5. Publicação via GitHub Pages: página pública (qualquer um com o link vê).

## 3.2 Arquitetura recomendada para produção

```
 SPPILOTS ──(API/exportação de leitura, credencial de serviço)──▶ Coletor (a cada 1–5 min)
                                                                     │  grava pauta + histórico + escala
                                                                     ▼
                                                               Banco de dados (histórico versionado)
                                                                     │
                                                                     ▼
                                                    Motor E2D (determinístico, reprocessa o turno)
                                                                     │  escalação + fila + disponibilidades
                                                                     ▼
                                                  API / Painel web (login dos práticos) + relatórios
```

Recomendações:

- **Integração SPPILOTS (prioridade 1).** Solicitar ao mantenedor do SPPILOTS um meio oficial de leitura: API (JSON) ou exportação agendada (CSV) com: pauta de serviço completa (todas as cores/status, inclusive não confirmadas), histórico com prático executante e, se possível, término real; escala diária com trocas. Se não houver API, a alternativa é um navegador sem interface (headless) num servidor, com credencial de serviço — mais frágil.
- **Motor determinístico e reprocessável.** O motor deve ser uma função pura: (pauta ordenada, escala/turnos, tabela T, especiais, parâmetros) → escalação. A cada atualização, reprocessar a partir do início do turno vigente (ou do ano) garante coerência. O protótipo reprocessa o ano inteiro em ~60 s; em produção, basta a partir de um "estado salvo" no início de cada turno.
- **Ordem das manobras no mesmo horário** é parte das regras (afeta quem pega o quê): seguir exatamente a especificação.
- **Banco de dados com versões.** Guardar cada pauta recebida (com horário de coleta) e cada escalação calculada, para auditoria e para o relatório do teste.
- **Hospedagem:** servidor da Praticagem ou nuvem (VM pequena basta). Agendador (cron) a cada 1–5 min.
- **Painel com login** (práticos da ZP-16), em vez de página pública.
- **Parâmetros configuráveis:** margens (45/25 min), tabela T, tabela de lancha, zonas, restrição Z5, conjunto de especiais.
- **Monitoramento:** alerta se a coleta falhar ou se os dados ficarem desatualizados (o protótipo mostra "desatualizado há X" quando passa de 30 min).

## 3.3 Integração direta (técnico de TI que opera o SPPILOTS)

Como o SPPILOTS é operado pela própria Praticagem, a integração pode ser feita **direto no banco de dados**, sem raspagem de página nem leitura de imagem:

1. **Entrada.** Uma função lê do banco, no formato de `04_Dados_e_formatos.md`: a pauta (inserida pelos operadores à medida que chegam as informações dos navios), quem fez cada manobra já executada, e a escala do dia com as trocas (os mesmos dados que geram a escala gráfica). Substitui `raspar_historico.py`, o userscript, `ep_server.py` e `escala_grafica.py`.
2. **Motor.** O núcleo (`motor_e2d/`) é usado **sem alteração de regra**. Pode continuar em Python, rodando no servidor ao lado do SPPILOTS. Reescrever em outra linguagem é possível, mas é a parte mais cara e mais sujeita a erro; se for feito, o critério é passar 100% no conjunto de teste.
3. **Disparo.** Rodar o motor sempre que a pauta mudar (inclusão ou alteração de manobra) ou a cada 1–5 min. A escalação de cada manobra **congela 1 h antes** do início; o que está mais distante é previsão e pode mudar.
4. **Saída.** Gravar o prático de cada manobra numa tabela própria (ex.: `escalacao_e2d`). O SPPILOTS mostra essa tabela: primeiro como **sugestão** para quem escala conferir (teste em paralelo), depois, se aprovado, como escalação oficial.

### 3.3.1 Contingência
- **Alerta** se o motor não atualizar em X minutos.
- **Motor reserva:** segunda instalação, mesma versão (pelo Git), com cópia da pauta, da escala e das manobras executadas a cada poucos minutos. Assume se o principal parar; se o SPPILOTS ou a rede caírem, trabalha offline com a última cópia (o operador digita os navios novos e depois eles são lançados de volta). Não recalcula o passado: usa quem de fato fez cada manobra. Testar a troca periodicamente.
- **Escalação manual** seguindo a última fila calculada (sempre salva), ou **volta para a E12** com a posição da seta de cada grupo.

### 3.3.2 Controle de versões
O código, as regras e os testes ficam num repositório Git privado. Cada mudança é registrada (quem, quando, o quê), revisada e só entra depois de passar no conjunto de teste. Servidor principal e reserva usam sempre a mesma versão. Margens, tabela de T e limite Z5 devem ficar em configuração (tabela), não no código.

## 3.4 Segurança

- Nenhuma senha em código ou em arquivos versionados; usar cofre de segredos/variáveis de ambiente.
- Credencial de serviço própria para o SPPILOTS (não a de um prático).
- Acesso de leitura apenas.
- Dados de escala e horários de trabalho são pessoais: painel com autenticação e registros com acesso restrito.
