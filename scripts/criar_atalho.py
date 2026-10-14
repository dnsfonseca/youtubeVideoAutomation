"""Cria atalho na area de trabalho apontando pra iniciar.bat.

Chamado por "iniciar.bat --instalar-deps" (CLAUDE.md secao 18.3). Nunca
trava a instalacao se falhar - so' avisa e sai com codigo != 0.
"""
import os
import sys
from pathlib import Path


def criar_atalho_windows() -> bool:
    try:
        import win32com.client
    except ImportError:
        print("Modulo pywin32 nao disponivel. Instale: pip install pywin32")
        return False

    projeto_raiz = Path(__file__).parent.parent.resolve()
    iniciar_bat = projeto_raiz / "iniciar.bat"

    if not iniciar_bat.exists():
        print(f"iniciar.bat nao encontrado em {projeto_raiz}")
        return False

    desktop = Path(os.path.expanduser("~/Desktop"))
    atalho = desktop / "Broll Foundry.lnk"

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(atalho))
    shortcut.Targetpath = str(iniciar_bat)
    shortcut.WorkingDirectory = str(projeto_raiz)
    shortcut.IconLocation = str(iniciar_bat)
    shortcut.Description = "Broll Foundry - Automacao de videos YouTube"
    shortcut.save()

    print(f"Atalho criado: {atalho}")
    return True


if __name__ == "__main__":
    sucesso = criar_atalho_windows()
    sys.exit(0 if sucesso else 1)
