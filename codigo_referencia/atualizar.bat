@echo off
REM ============================================================
REM atualizar.bat - Atualiza o painel local E publica no GitHub.
REM Faz tudo: roda ep_atualizar.py + copia + git push.
REM
REM USO: duplo clique neste arquivo (depois de clicar no favorito
REM      "EP Salvar Pauta" no Chrome com SPPILOTS aberto).
REM ============================================================
setlocal
REM Saida em UTF-8 (sem isso, rodando escondido pelo agendador, o Python falha ao imprimir acentos/simbolos)
set "PYTHONIOENCODING=utf-8"
REM O painel so e aberto pelo proprio .bat (modo manual); o Python nao abre aba
set "E2D_NAO_ABRIR=1"
REM Pasta do projeto = a propria pasta deste .bat (funciona em qualquer computador)
set "PROJETO=%~dp0"
set "PROJETO=%PROJETO:~0,-1%"
REM Copia local do repositorio do site (git clone de github.com/rfvb16/ep-santos)
set "PUBLICO=%USERPROFILE%\ep-santos-publico"

cd /d "%PROJETO%"

echo.
echo ====================================================
echo  ATUALIZAR PAINEL EP - Local + Online
echo ====================================================
echo.

REM 1. Roda ep_atualizar.py
echo [1/4] Rodando ep_atualizar.py...
echo.
python ep_atualizar.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha em ep_atualizar.py. Abortando.
    timeout /t 5 /nobreak >nul
    exit /b 1
)

echo.
echo ====================================================
echo  Painel local atualizado. Publicando online...
echo ====================================================
echo.

REM 2. Verifica se ep_painel.html existe
if not exist "%PROJETO%\ep_painel.html" (
    echo [ERRO] ep_painel.html nao foi gerado.
    timeout /t 5 /nobreak >nul
    exit /b 1
)

REM 3. Copia para pasta publica
echo [2/4] Copiando painel para pasta publica...
copy /Y "%PROJETO%\ep_painel.html" "%PUBLICO%\index.html" >nul

REM 4. Commit + push
cd /d "%PUBLICO%"

echo [3/4] Commitando alteracoes...
REM Se o indice do git corrompeu (ex.: computador desligou no meio), reconstroi
git status >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Indice do git corrompido - reconstruindo...
    del /f /q ".git\index" >nul 2>&1
    git reset >nul 2>&1
)
git add index.html >nul
REM Data/hora pelo PowerShell (o wmic foi removido nas versoes novas do Windows)
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH:mm"') do set "_TS=%%a"
git commit --allow-empty -m "Painel %_TS%" >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Falha no commit. Veja: cd "%PUBLICO%" e rode git status
    exit /b 1
)

echo [4/4] Enviando pro GitHub...
git push origin main
if errorlevel 1 (
    echo.
    echo [ERRO] Falha no push. Verifique sua conexao.
    timeout /t 5 /nobreak >nul
    exit /b 1
)

echo.
echo ====================================================
echo  Sucesso! Tudo atualizado.
echo.
echo  Local:  ep_painel.html
echo  Online: https://rfvb16.github.io/ep-santos/
echo          ^(aguarde 30s pra propagar^)
echo ====================================================
echo.

REM Modo automatico (agendador): nao abre o navegador nem espera
if /i "%~1"=="auto" exit /b 0

REM Abre o painel local no browser
start "" "%PROJETO%\ep_painel.html"

timeout /t 3 /nobreak >nul
