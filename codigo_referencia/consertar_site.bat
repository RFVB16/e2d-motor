@echo off
REM Conserta o repositorio do site (marcador da versao corrompido) e publica o painel atual.
cd /d "%USERPROFILE%\ep-santos-publico"
echo 80c9ad7b4783e14c689bedeb5d5bc05d7ee87e16> .git\refs\heads\main
git fetch origin
git reset origin/main
git add index.html
git commit -m "Painel reparo"
git push origin main
echo.
echo ===== Se apareceu "main -> main" acima, o site foi atualizado. =====
pause
