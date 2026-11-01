@echo off
REM Cria a tarefa "E2D Atualizar" no Agendador do Windows (a cada 10 min). Rodar uma vez, de dentro da pasta do projeto.
set "P=%~dp0"
set "P=%P:~0,-1%"
schtasks /Create /F /TN "E2D Atualizar" /SC MINUTE /MO 10 /TR "wscript.exe \"%P%\atualizar_oculto.vbs\""
REM roda tambem na bateria e nao para se tirar da tomada (01/11/2026)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = Get-ScheduledTask -TaskName 'E2D Atualizar'; $t.Settings.DisallowStartIfOnBatteries = $false; $t.Settings.StopIfGoingOnBatteries = $false; $t.Settings.StartWhenAvailable = $true; Set-ScheduledTask -InputObject $t | Out-Null"
echo.
echo Tarefa criada para a pasta: %P%
echo Para remover: schtasks /Delete /TN "E2D Atualizar" /F
pause
