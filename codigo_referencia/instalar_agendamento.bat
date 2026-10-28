@echo off
REM Cria a tarefa "E2D Atualizar" no Agendador do Windows (a cada 10 min). Rodar uma vez, de dentro da pasta do projeto.
set "P=%~dp0"
set "P=%P:~0,-1%"
schtasks /Create /F /TN "E2D Atualizar" /SC MINUTE /MO 10 /TR "wscript.exe \"%P%\atualizar_oculto.vbs\""
echo.
echo Tarefa criada para a pasta: %P%
echo Para remover: schtasks /Delete /TN "E2D Atualizar" /F
pause
