"""Setup necessario pra faster-whisper funcionar no Windows (CLAUDE.md
secao 18.9/4).

O driver NVIDIA (verificado por scripts/ambiente.py) NAO inclui as
bibliotecas de runtime CUDA (cuBLAS/cuDNN) que o ctranslate2 (usado pelo
faster-whisper) precisa carregar em tempo de execucao - isso e' instalado
separadamente via os pacotes pip `nvidia-cublas-cu12` e `nvidia-cudnn-cu12`
(requirements.txt).

No Windows, ter essas DLLs instaladas no venv nao e' suficiente: elas ficam
dentro de site-packages/nvidia/*/bin/, uma pasta que NAO esta no PATH do
processo por padrao, entao `ctranslate2` falha ao carregar a DLL nativa
(ex: "Library cublas64_12.dll is not found or cannot be loaded") mesmo com
o pacote pip instalado corretamente - confirmado rodando scripts/2_transcrever.py
de verdade numa RTX 3070 Ti (Sessao 4), e depois de novo em
scripts/4_obter_audio.py com o mesmo sintoma (Sessao 8.1/pos-8.1).

Extraido pra modulo compartilhado pra que todo script que importe
faster-whisper (transcricao E alinhamento de audio) resolva o mesmo
problema da mesma forma, em vez de duplicar a logica inline.

Deve ser importado e `registrar_dlls_cuda()` chamado ANTES de importar
faster_whisper em qualquer script que use transcricao/alinhamento.
"""

import os
import sys
from pathlib import Path


def registrar_dlls_cuda():
    """Registra diretorios cuBLAS/cuDNN no PATH do processo.

    `os.add_dll_directory` sozinho NAO resolveu na pratica (confirmado em
    teste real): o carregamento de cublas64_12.dll pelo ctranslate2 e'
    lazy (so acontece dentro de `model.transcribe(...)`, nao na construcao
    do `WhisperModel`), e nao respeitou os diretorios registrados via
    `AddDllDirectory`. Prepender ao PATH do processo (`os.environ["PATH"]`)
    e' o workaround que efetivamente funcionou - LoadLibrary do Windows
    sempre pesquisa PATH, independente de flags de busca estendida. Faz as
    duas coisas por seguranca.

    Idempotente - pode ser chamado multiplas vezes sem efeito colateral
    (so prepende de novo ao PATH). Nunca levanta excecao - se os pacotes
    nao estiverem instalados (Linux, ou driver que ja resolve isso
    sozinho), simplesmente nao ha nada a registrar.
    """
    if sys.platform != "win32":
        return
    try:
        import importlib.util

        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return
    if spec is None or not spec.submodule_search_locations:
        return

    for pasta_nvidia in spec.submodule_search_locations:
        base = Path(pasta_nvidia)
        if not base.is_dir():
            continue
        for pasta_bin in base.glob("*/bin"):
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(pasta_bin))
                except OSError:
                    pass
            os.environ["PATH"] = str(pasta_bin) + os.pathsep + os.environ.get("PATH", "")
