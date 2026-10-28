' Inicia o ep_server.py (porta 7373) sem janela - usado ao entrar no Windows
Set sh = CreateObject("WScript.Shell")
pasta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)  ' pasta deste arquivo
sh.CurrentDirectory = pasta
sh.Run "cmd /c python ep_server.py > """ & pasta & "\servidor.log"" 2>&1", 0, False
