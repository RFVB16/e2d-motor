@echo off
REM Conserta o repositorio do site (marcador da versao corrompido quando o PC desliga no meio do commit)
REM e publica o painel atual. Desde 31/10/2026 usa a ultima versao enviada (origin/main), sem numero fixo.
cd /d "%USERPROFILE%\ep-santos-publico"
for /f "usebackq delims=" %%a in (".git\refs\remotes\origin\main") do echo %%a> .git\refs\heads\main
git fetch origin
git reset origin/main
git add index.html
git commit -m "Painel reparo"
git push origin main
echo.
echo ===== Se apareceu "main -> main" acima, o site foi atualizado. =====
pause
