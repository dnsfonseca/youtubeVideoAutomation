"""Instalacao em cascata do ffmpeg no Windows (CLAUDE.md secao 18.3).

Uso: python scripts/instalar_ffmpeg.py
Chamado por iniciar.bat --instalar-deps. Sai com codigo 0 se ffmpeg
ficou disponivel ao final (ja estava, ou foi instalado agora), 1 caso
contrario.

Motivacao (descoberta em teste real com o usuario, ver CLAUDE.md secao
18.3): "winget install Gyan.FFmpeg" instala o pacote portable do Gyan,
que registra o pacote no winget mas NAO adiciona a pasta bin ao PATH
automaticamente. Resultado sem esta correcao: "instalacao bem-sucedida"
seguida de "ffmpeg -version" continuando a falhar.

Cascata, do metodo menos invasivo pro mais invasivo:
  1. winget install (+ busca manual do executavel e ajuste de PATH se o
     pacote instalado nao se registrou sozinho)
  2. chocolatey (instala o proprio chocolatey se preciso - requer
     elevacao de administrador, com aviso explicito antes de pedir UAC)
  3. instrucao manual (ultimo recurso, nunca falha silenciosamente)

Cada tentativa e' isolada em sua propria funcao para poder ser testada
com monkeypatch (CLAUDE.md secao 8) - nenhum teste deste modulo pode
rodar winget/choco/Start-Process de verdade.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ precisa estar no sys.path para `import robustez` funcionar tanto
# rodando este arquivo direto quanto carregado nos testes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robustez  # noqa: E402

BANNER_UAC = """
=================================================================
INSTALACAO DE COMPONENTE DO SISTEMA
=================================================================
Precisamos instalar o Chocolatey (gerenciador de dependencias)
para completar o setup. O Windows vai pedir permissao de
administrador nas proximas janelas - isso e' normal e seguro.

Basta clicar "Sim" quando a janela aparecer.

Pressione ENTER para continuar ou Ctrl+C para cancelar.
================================================================="""

INSTRUCAO_MANUAL = """
=================================================================
INSTALACAO AUTOMATICA NAO CONCLUIDA
=================================================================
Nao conseguimos instalar o ffmpeg automaticamente.

Instalacao manual (5 minutos):
1. Baixe: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
2. Extraia para: C:\\ffmpeg\\
   (deve resultar em C:\\ffmpeg\\bin\\ffmpeg.exe)
3. Adicione ao PATH:
   - Pesquise "variaveis de ambiente" no menu Iniciar
   - Clique "Variaveis de ambiente..."
   - Em "Variaveis do sistema", selecione "Path" e clique "Editar"
   - Clique "Novo" e cole: C:\\ffmpeg\\bin
   - OK em todas as janelas
4. Feche e abra este terminal
5. Rode iniciar.bat novamente

Se precisar de ajuda, entre em contato com suporte.
================================================================="""


def rodar(comando: list) -> subprocess.CompletedProcess:
    """Wrapper fino sobre subprocess.run - existe so pra poder ser
    mockado em teste (nunca invocar winget/choco/powershell de verdade
    durante pytest)."""
    return subprocess.run(comando, capture_output=True, text=True)


def confirmar_continuar_com_uac() -> bool:
    """Pede confirmacao explicita do usuario antes de disparar um prompt
    de UAC (elevacao de administrador). Retorna False se o usuario
    cancelar (Ctrl+C) ou se stdin nao estiver disponivel."""
    try:
        input()
        return True
    except (EOFError, KeyboardInterrupt):
        print("\nInstalacao cancelada pelo usuario.")
        return False


def registrar_diretorio_para_sessao_atual(diretorio: Path) -> None:
    """Alem de gravar no PATH do usuario (Windows), escreve o diretorio
    num arquivo apontado por FFMPEG_PATH_HINT (se a variavel estiver
    definida) para que iniciar.bat consiga estender o PATH da propria
    sessao do .bat sem precisar reabrir o terminal."""
    arquivo_hint = os.environ.get("FFMPEG_PATH_HINT")
    if arquivo_hint:
        try:
            Path(arquivo_hint).write_text(str(diretorio), encoding="utf-8")
        except OSError:
            pass
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(diretorio)


def adicionar_ao_path_usuario(diretorio: Path) -> None:
    """Adiciona `diretorio` ao PATH do usuario (persistente entre
    sessoes, via registro do Windows) e disponibiliza para o processo
    atual e para o iniciar.bat que o chamou."""
    import winreg

    diretorio_str = str(diretorio)
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    ) as chave:
        try:
            path_atual, tipo = winreg.QueryValueEx(chave, "Path")
        except FileNotFoundError:
            path_atual, tipo = "", winreg.REG_EXPAND_SZ

        partes = [p for p in path_atual.split(";") if p]
        if diretorio_str not in partes:
            partes.append(diretorio_str)
            novo_path = ";".join(partes)
            winreg.SetValueEx(chave, "Path", 0, tipo, novo_path)

    _notificar_mudanca_de_ambiente()
    registrar_diretorio_para_sessao_atual(diretorio)


def _notificar_mudanca_de_ambiente() -> None:
    """Avisa o Windows (WM_SETTINGCHANGE) que o ambiente mudou, para que
    novos processos iniciados por outros programas eventualmente
    enxerguem o PATH novo sem logoff. Melhor esforco - se falhar, o
    fallback documentado pro usuario continua sendo "abra um novo
    terminal"."""
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x1A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            None,
        )
    except Exception:
        pass


def buscar_ffmpeg_em_winget_packages():
    """Procura ffmpeg.exe dentro da pasta onde o winget instala pacotes
    portable (LOCALAPPDATA\\Microsoft\\WinGet\\Packages). Retorna o
    primeiro Path encontrado, ou None."""
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not base.exists():
        return None
    encontrados = sorted(base.rglob("ffmpeg.exe"))
    return encontrados[0] if encontrados else None


def winget_disponivel() -> bool:
    return shutil.which("winget") is not None


def instalar_via_winget() -> bool:
    resultado = rodar(
        [
            "winget",
            "install",
            "--id",
            "Gyan.FFmpeg",
            "-e",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]
    )
    return resultado.returncode == 0


def tentativa_winget() -> bool:
    """Tentativa 1: winget install + deteccao/correcao de PATH pro caso
    do pacote portable do Gyan.FFmpeg nao se registrar sozinho."""
    if not winget_disponivel():
        print("winget nao esta disponivel neste sistema.")
        return False

    print("Tentando instalar ffmpeg via winget...")
    if not instalar_via_winget():
        print("winget nao conseguiu instalar o ffmpeg.")
        return False

    if robustez.ffmpeg_disponivel():
        print("ffmpeg instalado via winget e disponivel no PATH.")
        return True

    print(
        "winget instalou o pacote, mas o ffmpeg nao apareceu no PATH "
        "(pacote portable do Gyan.FFmpeg nao registra PATH sozinho). "
        "Procurando o executavel..."
    )
    encontrado = buscar_ffmpeg_em_winget_packages()
    if encontrado is None:
        print("Nao encontrei ffmpeg.exe nos pacotes instalados pelo winget.")
        return False

    adicionar_ao_path_usuario(encontrado.parent)
    if robustez.ffmpeg_disponivel():
        print(f"ffmpeg encontrado em {encontrado.parent} e adicionado ao PATH.")
        return True

    print("ffmpeg foi encontrado, mas ainda nao ficou acessivel nesta sessao.")
    return False


def chocolatey_disponivel() -> bool:
    return shutil.which("choco") is not None


def instalar_chocolatey_e_ffmpeg_elevado() -> bool:
    """Dispara UM prompt de UAC (elevacao) que instala o chocolatey (se
    ainda nao estiver instalado) e em seguida `choco install ffmpeg -y`,
    tudo na mesma sessao elevada - evita pedir UAC duas vezes."""
    comando_ps = (
        "Set-ExecutionPolicy Bypass -Scope Process -Force; "
        "if (-not (Get-Command choco -ErrorAction SilentlyContinue)) { "
        "iex ((New-Object System.Net.WebClient).DownloadString("
        "'https://community.chocolatey.org/install.ps1')) }; "
        "choco install ffmpeg -y"
    )
    resultado = rodar(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Start-Process powershell -Verb RunAs -Wait -ArgumentList "
            f"'-NoProfile -ExecutionPolicy Bypass -Command \"{comando_ps}\"'",
        ]
    )
    return resultado.returncode == 0


def tentativa_chocolatey() -> bool:
    """Tentativa 2: chocolatey. Pede confirmacao explicita antes de
    disparar UAC se o chocolatey ainda nao estiver instalado."""
    if not chocolatey_disponivel():
        print(BANNER_UAC)
        if not confirmar_continuar_com_uac():
            return False

    print("Instalando ffmpeg via chocolatey (pode pedir permissao de administrador)...")
    if not instalar_chocolatey_e_ffmpeg_elevado():
        print("Instalacao via chocolatey nao foi concluida (UAC negado ou falha do choco).")
        return False

    if robustez.ffmpeg_disponivel():
        print("ffmpeg instalado via chocolatey e disponivel no PATH.")
        return True

    # choco adiciona a propria pasta de shims ao PATH de Machine durante a
    # instalacao dele mesmo - so nao propaga pro processo ja em execucao.
    caminho_choco_bin = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin"
    if caminho_choco_bin.exists():
        registrar_diretorio_para_sessao_atual(caminho_choco_bin)

    if robustez.ffmpeg_disponivel():
        print("ffmpeg instalado via chocolatey e disponivel nesta sessao.")
        return True

    print("chocolatey rodou, mas o ffmpeg ainda nao ficou acessivel nesta sessao.")
    return False


def mostrar_instrucao_manual() -> None:
    print(INSTRUCAO_MANUAL)


def instalar_ffmpeg_cascata() -> bool:
    """Fluxo completo (CLAUDE.md secao 18.3): winget -> chocolatey ->
    instrucao manual. Retorna True assim que ffmpeg ficar disponivel em
    qualquer etapa."""
    if robustez.ffmpeg_disponivel():
        print("ffmpeg ja esta no PATH. Nada a fazer.")
        return True

    if tentativa_winget():
        return True

    if tentativa_chocolatey():
        return True

    mostrar_instrucao_manual()
    return False


if __name__ == "__main__":
    sucesso = instalar_ffmpeg_cascata()
    sys.exit(0 if sucesso else 1)
