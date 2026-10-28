@echo off
REM Faz o ep_server.py iniciar sozinho ao entrar no Windows (sem administrador). Rodar uma vez, de dentro da pasta do projeto.
set "P=%~dp0"
set "P=%P:~0,-1%"
set "D=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\E2D_servidor.vbs"
> "%D%" echo Set sh = CreateObject("WScript.Shell")
>> "%D%" echo sh.CurrentDirectory = "%P%"
>> "%D%" echo sh.Run "cmd /c python ep_server.py", 0, False
echo.
echo Pronto: o servidor vai iniciar sozinho a cada entrada no Windows (pasta: %P%).
echo Para desfazer, apague E2D_servidor.vbs da pasta de Inicializar (Win+R, shell:startup).
pause
