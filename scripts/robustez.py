"""Robustez contra dependencias externas volateis (CLAUDE.md secao 18).

Modulo compartilhado por excecao a convencao de "sem utils.py" da secao 9
— esta e' infra transversal (checagem de idade de lib, presenca de ffmpeg),
nao logica de pipeline duplicavel por script. Cada script que quiser usar
estas funcoes insere `scripts/` no sys.path e faz `import robustez`.

Nenhuma funcao aqui levanta excecao por falha de rede/lib ausente — uma
checagem de robustez que derruba o boot do servidor ou o pipeline seria
pior que o problema que tenta prevenir.
"""

import shutil
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _versao_pacote

import requests

JANELA_DIAS_AVISO = 90

# Timeout curto de proposito: esta checagem roda no boot do servidor e no
# inicio de scripts do pipeline — nao pode travar a experiencia do usuario
# esperando resposta da PyPI se a rede estiver lenta/indisponivel.
TIMEOUT_PYPI_S = 3


def libs_criticas() -> list:
    """Lista de dependencias volateis monitoradas (CLAUDE.md secao 18.2).

    Comeca so com yt-dlp. Reavaliar faster-whisper conforme o produto
    amadurece (CLAUDE.md secao 18.1)."""
    return ["yt-dlp"]


def versao_instalada(nome_pacote: str):
    """Versao instalada de `nome_pacote` no ambiente atual, ou None se o
    pacote nao estiver instalado."""
    try:
        return _versao_pacote(nome_pacote)
    except PackageNotFoundError:
        return None


def idade_lib(nome_pacote: str, timeout_s: float = TIMEOUT_PYPI_S):
    """Dias desde o release (upload na PyPI) da versao instalada de
    `nome_pacote`.

    Retorna None se nao for possivel determinar por qualquer motivo
    (pacote nao instalado, sem internet, resposta inesperada da PyPI) —
    nunca levanta excecao (CLAUDE.md secao 18.2: so informa, nunca
    bloqueia)."""
    versao = versao_instalada(nome_pacote)
    if versao is None:
        return None

    try:
        resposta = requests.get(
            f"https://pypi.org/pypi/{nome_pacote}/{versao}/json",
            timeout=timeout_s,
        )
        resposta.raise_for_status()
        dados = resposta.json()
    except Exception:
        return None

    urls = dados.get("urls") or []
    if not urls:
        return None

    upload_time = urls[0].get("upload_time_iso_8601") or urls[0].get("upload_time")
    if not upload_time:
        return None

    try:
        data_release = datetime.fromisoformat(upload_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if data_release.tzinfo is None:
        data_release = data_release.replace(tzinfo=timezone.utc)

    agora = datetime.now(timezone.utc)
    return (agora - data_release).days


def lib_desatualizada(nome_pacote: str, janela_dias: int = JANELA_DIAS_AVISO):
    """True se a idade da lib instalada for conhecida e maior que
    `janela_dias`. False se estiver atual OU se a idade nao puder ser
    determinada (nao alarma o usuario por falta de informacao)."""
    dias = idade_lib(nome_pacote)
    if dias is None:
        return False
    return dias > janela_dias


def ffmpeg_disponivel() -> bool:
    return shutil.which("ffmpeg") is not None


def validar_pre_condicoes_pipeline():
    """Checks universais que todo script do pipeline que depende de ffmpeg
    deve fazer antes de comecar a processar (CLAUDE.md secao 18.6).

    Retorna (True, None) se pode prosseguir, ou (False, mensagem_de_erro)
    caso contrario. Nunca levanta excecao."""
    if not ffmpeg_disponivel():
        return False, (
            "ffmpeg nao encontrado no PATH. Rode iniciar.bat --instalar-deps "
            "ou instale manualmente via 'winget install ffmpeg'."
        )
    return True, None
