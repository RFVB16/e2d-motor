@echo off
REM Envia para o GitHub privado (RFVB16/e2d-motor) o codigo atual da pasta E2D NOVA.
REM Chamado no fim do atualizar.bat. So envia se algum arquivo de codigo mudou. Nunca envia senha nem dados da escala.
REM Desde 29/10/2026 envia tambem os textos e os testes do PACOTE_IMPLEMENTACAO (nunca config.json nem dados).
setlocal
set "SRC=%~dp0"
set "REPO=%USERPROFILE%\e2d-motor"
if not exist "%REPO%\.git" (
  echo [Repositorio] copia local nao encontrada em %REPO% - pulando.
  exit /b 0
)
set "DST=%REPO%\codigo_referencia"
for %%F in (E2D_pauta_automatica.user.js atualizar.bat atualizar_oculto.vbs consertar_site.bat ep_algoritmo.py ep_atualizar.py ep_server.py escala_grafica.py escala_grafica_modelos.npz gerar_2026.py instalar_servidor_inicio.bat raspar_historico.py servidor_oculto.vbs sincronizar_repo.bat) do (
  if exist "%SRC%%%F" copy /Y "%SRC%%%F" "%DST%\%%F" >nul
)
if exist "%SRC%instalar_agendamento_10min.bat" copy /Y "%SRC%instalar_agendamento_10min.bat" "%DST%\instalar_agendamento.bat" >nul
for %%F in (carregar_pauta.py ep_algoritmo.py ep_sim_v3_corrigido.py grupo_a_data.py motor_e2d.py nova_escalacao.py) do (
  if exist "%SRC%motor_e2d\%%F" copy /Y "%SRC%motor_e2d\%%F" "%DST%\motor_e2d\%%F" >nul
)
if exist "%SRC%inputs\Tempo_T__2025_.xlsx" copy /Y "%SRC%inputs\Tempo_T__2025_.xlsx" "%DST%\inputs\Tempo_T__2025_.xlsx" >nul
if exist "%SRC%motor_e2d\inputs\Tempo_T__2025_.xlsx" copy /Y "%SRC%motor_e2d\inputs\Tempo_T__2025_.xlsx" "%DST%\motor_e2d\inputs\Tempo_T__2025_.xlsx" >nul

REM Textos e testes do PACOTE (especificacao, CHANGELOG, LEIA-ME, resultado esperado) - 29/10/2026
set "PAC=%SRC%PACOTE_IMPLEMENTACAO"
if exist "%PAC%" (
  for %%F in ("%PAC%\*.md") do copy /Y "%%~F" "%REPO%" >nul
  if exist "%PAC%\.gitignore" copy /Y "%PAC%\.gitignore" "%REPO%\.gitignore" >nul
  if not exist "%REPO%\testes" mkdir "%REPO%\testes"
  for %%F in (rodar_referencia.py comparar.py testar_congelamento.py testar_cancelamento.py) do (
    if exist "%PAC%\testes\%%F" copy /Y "%PAC%\testes\%%F" "%REPO%\testes\%%F" >nul
  )
  for %%D in (entrada esperado esperado_alternativo) do (
    if exist "%PAC%\testes\%%D" (
      if not exist "%REPO%\testes\%%D" mkdir "%REPO%\testes\%%D"
      copy /Y "%PAC%\testes\%%D\*" "%REPO%\testes\%%D" >nul
    )
  )
)

cd /d "%REPO%"
git add -A codigo_referencia testes .gitignore ":(glob)*.md" >nul 2>&1
git diff --cached --quiet
if not errorlevel 1 (
  echo [Repositorio] codigo sem mudancas.
  exit /b 0
)
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH:mm"') do set "_TS=%%a"
git commit -m "Atualizacao automatica do codigo %_TS%" >nul 2>&1
git push -q origin main
if errorlevel 1 (
  echo [Repositorio] AVISO: falha ao enviar para o GitHub. Tenta de novo na proxima rodada.
  exit /b 0
)
echo [Repositorio] codigo enviado para github.com/RFVB16/e2d-motor
exit /b 0
