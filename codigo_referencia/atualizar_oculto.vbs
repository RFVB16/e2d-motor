' Roda o atualizar.bat em modo automatico, sem abrir janela (usado pelo Agendador de Tarefas)
Set sh = CreateObject("WScript.Shell")
pasta = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)  ' pasta deste arquivo
sh.CurrentDirectory = pasta
' aspas externas extras: o cmd /c remove o primeiro e o ultimo par
sh.Run "cmd /c """"" & pasta & "\atualizar.bat"" auto > """ & pasta & "\ultima_atualizacao.log"" 2>&1""", 0, False
