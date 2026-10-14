"""Etapa 2 do pipeline (CLAUDE.md secao 5.2) - transcreve cada video-fonte
baixado na Etapa 1 usando faster-whisper em GPU CUDA local.

Uso: python "scripts/2_transcrever.py" <caminho_da_pasta_do_projeto>

Saida:
- transcricoes/<id_da_fonte>.json - segmentos com timestamps por palavra,
  um arquivo por video-fonte transcrito com sucesso (schema CLAUDE.md
  secao 5.2).

Requisitos minimos oficiais do produto (CLAUDE.md secao 13): GPU NVIDIA
Compute Capability 6.0+, 4GB+ VRAM, driver CUDA 12+. CPU-only e GPUs
AMD/Intel nao sao suportadas - a pre-condicao abaixo refusa duro nesses
casos, antes de tentar carregar o modelo.

Este script e' autocontido (CLAUDE.md secao 9) - exceto por
scripts/robustez.py, scripts/ambiente.py e scripts/whisper_setup.py, infra
transversal de robustez (CLAUDE.md secao 18), nao logica de pipeline.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ precisa estar no sys.path para `import ambiente`/`import robustez`
# funcionarem tanto rodando este arquivo direto quanto carregado via
# importlib nos testes (mesma convencao de 1_baixar_videos.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ambiente  # noqa: E402
import robustez  # noqa: E402
import whisper_setup  # noqa: E402

whisper_setup.registrar_dlls_cuda()

# Import no nivel de modulo (nao lazy dentro de funcao) para que os testes
# possam substituir `WhisperModel` via monkeypatch (CLAUDE.md secao 8: nunca
# chamar faster-whisper real em teste). Se a lib nao estiver instalada,
# WhisperModel fica None e transcrever_todos() reporta erro claro em vez de
# derrubar o script com ImportError na carga do modulo.
try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

MODELO_PADRAO = "medium"
DISPOSITIVO_PADRAO = "cuda"
COMPUTE_TYPE_PADRAO = "float16"

# Config duro (CLAUDE.md secao 5.2) - nao editavel via .env de proposito.
TIMEOUT_POR_VIDEO_S = 60 * 60

TIMEOUT_FFPROBE_S = 30

# ---------------------------------------------------------------------------
# Categorizacao de erros da transcricao (CLAUDE.md secao 5.2) - mesmo
# espirito de classificar_erro_ytdlp em 1_baixar_videos.py: stderr/mensagem
# tecnica de excecao vira categoria conhecida + mensagem amigavel. Ordem
# importa - "vram_insuficiente" (OOM) tem que ser checada antes do
# "gpu_indisponivel" generico, ja que ambas podem conter "cuda failed" no
# texto.
# ---------------------------------------------------------------------------

_CATEGORIAS_ERRO_TRANSCRICAO = [
    (
        "vram_insuficiente",
        lambda s: "out of memory" in s
        or "cuda_error_out_of_memory" in s
        or "cudaerroroutofmemory" in s,
    ),
    (
        "gpu_indisponivel",
        lambda s: "cuda driver version is insufficient" in s
        or "no cuda-capable device" in s
        or "cuda_error_no_device" in s
        or "libcudnn" in s
        or "cudnn" in s
        or "could not select cuda device" in s
        or "cuda failed" in s
        # Bibliotecas de runtime CUDA (cuBLAS/cuDNN) ausentes/nao
        # carregaveis - confirmado num teste real numa RTX 3070 Ti (Sessao
        # 17): mensagem exata do ctranslate2 e' algo como "Library
        # cublas64_12.dll is not found or cannot be loaded".
        # whisper_setup.registrar_dlls_cuda() corrige a causa mais comum
        # disso (pastas nvidia-cublas-cu12/nvidia-cudnn-cu12 fora do PATH),
        # mas este check continua util como defesa em profundidade.
        or "cublas" in s
        or "is not found or cannot be loaded" in s,
    ),
    (
        "modelo_nao_encontrado",
        lambda s: "huggingface" in s
        or "max retries exceeded" in s
        or "name or service not known" in s
        or "failed to download" in s
        or "urlopen error" in s
        or "connection aborted" in s
        or "connection refused" in s,
    ),
    (
        "arquivo_corrompido",
        lambda s: "invalid data found when processing input" in s
        or "moov atom not found" in s
        or "could not open file" in s
        or "ffprobe" in s,
    ),
    (
        "timeout",
        lambda s: "timeout" in s or "tempo limite" in s,
    ),
]


def classificar_erro_transcricao(stderr: str, modelo: str = None, arquivo: str = None) -> tuple:
    """Classifica uma mensagem de erro (stderr do ffprobe ou texto de uma
    excecao do faster-whisper/ctranslate2) numa categoria conhecida, com
    mensagem amigavel pro usuario final.

    Retorna (categoria, mensagem_amigavel). Cai em "erro_desconhecido" com
    um trecho tecnico se nada bater com nenhuma categoria conhecida."""
    texto = (stderr or "").lower()
    for categoria, condicao in _CATEGORIAS_ERRO_TRANSCRICAO:
        if not condicao(texto):
            continue
        if categoria == "vram_insuficiente":
            nome_modelo = modelo or "atual"
            return categoria, (
                f"Memoria de video insuficiente para o modelo {nome_modelo}. "
                "Nos Ajustes, troque para um modelo menor."
            )
        if categoria == "gpu_indisponivel":
            return categoria, "GPU NVIDIA nao detectada. Verifique drivers."
        if categoria == "modelo_nao_encontrado":
            return categoria, "Modelo Whisper nao disponivel. Verifique conexao com internet."
        if categoria == "arquivo_corrompido":
            nome_arquivo = arquivo or "video-fonte"
            return categoria, f"Arquivo de video corrompido: {nome_arquivo}"
        if categoria == "timeout":
            return categoria, "Transcricao excedeu tempo limite (60min)."
    trecho = (stderr or "").strip()[:200]
    return "erro_desconhecido", f"Erro inesperado na transcricao. Detalhe tecnico: {trecho}"


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _formatar_duracao_amigavel(segundos: float) -> str:
    """Formata segundos como "5min 23s" ou "45s" (script autocontido -
    CLAUDE.md secao 9 - duplica server.py:_formatar_duracao_s de proposito
    em vez de importar de um utils.py compartilhado)."""
    segundos = int(segundos)
    if segundos < 60:
        return f"{segundos}s"
    minutos, s = divmod(segundos, 60)
    if s == 0:
        return f"{minutos}min"
    return f"{minutos}min {s}s"


def _validar_arquivo_com_ffprobe(caminho_mp4: Path):
    """Confere que o mp4 nao esta corrompido ANTES de gastar tempo de GPU
    tentando transcrever ele (CLAUDE.md secao 5.2, categoria
    "arquivo_corrompido"). Retorna (True, None) se o arquivo parece valido,
    ou (False, mensagem_tecnica) caso contrario. Nunca levanta excecao."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(caminho_mp4),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_FFPROBE_S,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"Falha ao executar ffprobe: {exc}"

    if resultado.returncode != 0 or not (resultado.stdout or "").strip():
        return False, (resultado.stderr or "ffprobe nao conseguiu ler o arquivo.").strip()
    return True, None


def _transcrever_com_timeout(model, caminho_mp4: Path, callback_progresso, timeout_s: float):
    """Roda `model.transcribe(...)` numa thread daemon separada, com prazo
    maximo de `timeout_s` segundos (CLAUDE.md secao 5.2 - timeout de 60min
    por video, config duro).

    Thread daemon (nao ThreadPoolExecutor) de proposito: se o timeout
    estourar, a thread de trabalho pode continuar rodando em segundo plano
    (Python nao mata threads a forca) - mas sendo daemon, ela nao impede o
    processo de sair quando o script terminar, ao contrario de uma thread
    normal presa num `executor.shutdown(wait=True)`.

    Levanta TimeoutError se estourar o prazo, ou repropaga a excecao
    original se `model.transcribe` falhar por qualquer outro motivo.
    Retorna o dict {"duracao_s", "idioma", "segmentos"} em caso de sucesso.
    """
    estado = {"resultado": None, "erro": None}

    def _trabalho():
        try:
            segments, info = model.transcribe(str(caminho_mp4), word_timestamps=True)
            segmentos_out = []
            for seg in segments:
                palavras = [
                    {"start": w.start, "end": w.end, "word": w.word}
                    for w in (seg.words or [])
                ]
                segmentos_out.append(
                    {
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text.strip(),
                        "palavras": palavras,
                    }
                )
                callback_progresso(seg, info)
            estado["resultado"] = {
                "duracao_s": info.duration,
                "idioma": info.language,
                "segmentos": segmentos_out,
            }
        except Exception as exc:  # repassado para a thread principal abaixo
            estado["erro"] = exc

    thread = threading.Thread(target=_trabalho, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        raise TimeoutError(f"Transcricao excedeu o tempo limite de {timeout_s:.0f}s (timeout).")
    if estado["erro"] is not None:
        raise estado["erro"]
    return estado["resultado"]


def _ler_tipo_uso_fontes(pasta_projeto: Path) -> dict:
    """Mapa id_da_fonte -> tipo_uso, lido de entrada/fontes_tipo_uso.json
    (feature de fontes separadas). Arquivo ausente (modo unificado, ou
    projeto anterior a esta feature) retorna {} - toda fonte cai no default
    "ambos" em `_fontes_elegiveis_para_transcricao` (retrocompatibilidade
    total)."""
    caminho = pasta_projeto / "entrada" / "fontes_tipo_uso.json"
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _fontes_elegiveis_para_transcricao(pasta_projeto: Path, fontes: list) -> list:
    """Filtra `fontes` (entradas de manifest_fontes.json com sucesso=True)
    para as que devem ser transcritas: tipo_uso "ambos" ou "transcricao"
    (default "ambos" se ausente do mapa) E origem "youtube" - fontes
    enviadas por upload nunca sao transcritas automaticamente, mesmo que por
    algum motivo tenham tipo_uso "transcricao"/"ambos" (nao deveria
    acontecer via UI, mas a checagem de origem e' a garantia de verdade)."""
    tipo_uso_por_id = _ler_tipo_uso_fontes(pasta_projeto)
    resultado = []
    for f in fontes:
        if f.get("origem", "youtube") != "youtube":
            continue
        tipo_uso = tipo_uso_por_id.get(f.get("id"), "ambos")
        if tipo_uso in ("ambos", "transcricao"):
            resultado.append(f)
    return resultado


def _validar_pre_condicoes(pasta_projeto: Path):
    """Valida tudo que este script precisa ANTES de comecar a processar
    qualquer video (CLAUDE.md secao 18.6/18.7): existencia do manifest da
    Etapa 1 com pelo menos um video baixado com sucesso, e ambiente
    NVIDIA/CUDA atendendo aos requisitos minimos oficiais (CLAUDE.md secao
    13).

    Retorna (True, None, None) se pode prosseguir, ou
    (False, mensagem_de_erro, tipo_erro) caso contrario."""
    ok_ffmpeg, mensagem_ffmpeg = robustez.validar_pre_condicoes_pipeline()
    if not ok_ffmpeg:
        return False, mensagem_ffmpeg, "erro_desconhecido"

    manifest_path = pasta_projeto / "fontes" / "manifest_fontes.json"
    if not manifest_path.exists():
        return (
            False,
            f"fontes/manifest_fontes.json nao encontrado em {manifest_path}. "
            "Rode a Etapa 1 (download) antes desta etapa.",
            "erro_desconhecido",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"fontes/manifest_fontes.json invalido: {exc}", "erro_desconhecido"

    fontes_baixadas = [f for f in manifest.get("fontes", []) if f.get("sucesso")]
    fontes_ok = _fontes_elegiveis_para_transcricao(pasta_projeto, fontes_baixadas)
    if not fontes_ok:
        mensagem = (
            "Nenhum video-fonte elegivel para transcricao (tipo_uso "
            "'transcricao'/'ambos' e origem YouTube) obtido com sucesso na Etapa 1."
            if fontes_baixadas
            else "Nenhum video-fonte baixado com sucesso na Etapa 1."
        )
        return False, mensagem, "erro_desconhecido"

    gpu = ambiente.detectar_gpu()
    compatibilidade = ambiente.avaliar_compatibilidade(gpu)
    if not compatibilidade["atende_minimo"]:
        return False, compatibilidade["mensagem"], "gpu_indisponivel"

    return True, None, None


def transcrever_todos(pasta_projeto: Path) -> dict:
    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes(pasta_projeto)
    if not ok_precondicoes:
        emitir_progresso(
            0.0,
            f"ERRO: {mensagem_erro}",
            sucesso=False,
            tipo_erro=tipo_erro,
            mensagem_usuario=mensagem_erro,
        )
        return {"transcricoes": [], "sucesso": False, "erro_fatal": mensagem_erro}

    manifest_path = pasta_projeto / "fontes" / "manifest_fontes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fontes_baixadas = [f for f in manifest.get("fontes", []) if f.get("sucesso")]
    fontes = _fontes_elegiveis_para_transcricao(pasta_projeto, fontes_baixadas)
    total = len(fontes)

    pasta_fontes = pasta_projeto / "fontes"
    pasta_transcricoes = pasta_projeto / "transcricoes"
    pasta_transcricoes.mkdir(parents=True, exist_ok=True)

    modelo_nome = os.environ.get("WHISPER_MODEL") or MODELO_PADRAO
    dispositivo = os.environ.get("WHISPER_DEVICE") or DISPOSITIVO_PADRAO

    if WhisperModel is None:
        mensagem = "faster-whisper nao esta instalado no ambiente Python atual."
        emitir_progresso(
            0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="erro_desconhecido", mensagem_usuario=mensagem
        )
        return {"transcricoes": [], "sucesso": False, "erro_fatal": mensagem}

    emitir_progresso(0.0, f"Carregando modelo Whisper ({modelo_nome})...")
    try:
        model = WhisperModel(modelo_nome, device=dispositivo, compute_type=COMPUTE_TYPE_PADRAO)
    except Exception as exc:
        categoria, mensagem_usuario = classificar_erro_transcricao(str(exc), modelo=modelo_nome)
        emitir_progresso(
            0.0,
            f"ERRO: {mensagem_usuario}",
            sucesso=False,
            tipo_erro=categoria,
            mensagem_usuario=mensagem_usuario,
        )
        return {"transcricoes": [], "sucesso": False, "erro_fatal": mensagem_usuario}

    resultados = []
    for indice, fonte in enumerate(fontes, start=1):
        arquivo = fonte["arquivo"]
        id_fonte = fonte.get("id") or Path(arquivo).stem
        caminho_mp4 = pasta_fontes / arquivo

        emitir_progresso((indice - 1) / total * 100, f"Processando {indice}/{total}: {arquivo}")

        item = {
            "id": id_fonte,
            "arquivo": arquivo,
            "sucesso": False,
            "erro": None,
            "tipo_erro": None,
            "mensagem_usuario": None,
        }

        if not caminho_mp4.exists():
            item["erro"] = f"Arquivo nao encontrado: {caminho_mp4}"
            item["tipo_erro"] = "arquivo_corrompido"
            item["mensagem_usuario"] = f"Arquivo de video corrompido: {arquivo}"
            resultados.append(item)
            continue

        valido, mensagem_ffprobe = _validar_arquivo_com_ffprobe(caminho_mp4)
        if not valido:
            item["erro"] = mensagem_ffprobe
            item["tipo_erro"] = "arquivo_corrompido"
            item["mensagem_usuario"] = f"Arquivo de video corrompido: {arquivo}"
            resultados.append(item)
            continue

        tempo_inicio_arquivo = time.monotonic()

        def _progresso_segmento(seg, info, _indice=indice, _arquivo=arquivo, _inicio=tempo_inicio_arquivo):
            # Nao mostrar "seg.end/duracao" cru (ex: "612.3s/1247.3s") - isso
            # e' posicao no audio, nao tempo de execucao, e o usuario le como
            # se a transcricao demorasse 1:1 (achado real em teste de ponta a
            # ponta - faster-whisper em GPU roda ~10-30x mais rapido que
            # tempo real). Projeta o tempo restante pela velocidade medida de
            # verdade neste arquivo ate agora, em vez de qualquer estimativa
            # fixa.
            duracao = info.duration or 0
            pct_local = min(seg.end / duracao, 1.0) * 100 if duracao else 0.0
            pct_total = ((_indice - 1) + pct_local / 100) / total * 100
            tempo_decorrido = time.monotonic() - _inicio
            velocidade = seg.end / tempo_decorrido if tempo_decorrido > 0 and seg.end > 0 else 0
            detalhe = f"Transcrevendo {_indice}/{total} ({_arquivo})"
            if velocidade > 0:
                segundos_restantes = max(duracao - seg.end, 0) / velocidade
                detalhe += f" — {_formatar_duracao_amigavel(segundos_restantes)} restantes"
            emitir_progresso(pct_total, detalhe)

        try:
            saida = _transcrever_com_timeout(
                model, caminho_mp4, _progresso_segmento, TIMEOUT_POR_VIDEO_S
            )
        except TimeoutError as exc:
            item["erro"] = str(exc)
            item["tipo_erro"] = "timeout"
            item["mensagem_usuario"] = "Transcricao excedeu tempo limite (60min)."
            resultados.append(item)
            continue
        except Exception as exc:
            categoria, mensagem_usuario = classificar_erro_transcricao(
                str(exc), modelo=modelo_nome, arquivo=arquivo
            )
            item["erro"] = str(exc)
            item["tipo_erro"] = categoria
            item["mensagem_usuario"] = mensagem_usuario
            resultados.append(item)
            continue

        saida["arquivo"] = arquivo
        caminho_saida = pasta_transcricoes / f"{id_fonte}.json"
        caminho_saida.write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")

        item["sucesso"] = True
        item["arquivo_transcricao"] = caminho_saida.name
        resultados.append(item)

    sucessos = sum(1 for r in resultados if r["sucesso"])

    if sucessos == total:
        emitir_progresso(100.0, f"{sucessos} video(s) transcrito(s) com sucesso", sucesso=True)
    elif sucessos == 0:
        falhas = [r for r in resultados if not r["sucesso"]]
        erros = [r["erro"] for r in falhas if r["erro"]]
        mensagens_unicas = list(
            dict.fromkeys(r["mensagem_usuario"] for r in falhas if r.get("mensagem_usuario"))
        )
        mensagem_usuario = (
            " | ".join(mensagens_unicas)
            if mensagens_unicas
            else "Nao foi possivel transcrever nenhum video."
        )
        emitir_progresso(
            100.0,
            "ERRO: nenhum video transcrito",
            sucesso=False,
            erros=erros,
            mensagem_usuario=mensagem_usuario,
            tipo_erro=falhas[0]["tipo_erro"] if falhas else None,
        )
    else:
        falhas = [r for r in resultados if not r["sucesso"]]
        avisos = [f"{r['id']}: {r['mensagem_usuario'] or r['erro']}" for r in falhas]
        tipos_erro = sorted({r["tipo_erro"] for r in falhas if r.get("tipo_erro")})
        emitir_progresso(
            100.0,
            f"Concluido com {sucessos} de {total} sucessos",
            sucesso=True,
            avisos=avisos,
            tipos_erro=tipos_erro,
        )

    return {
        "transcricoes": resultados,
        "sucesso": sucessos > 0,
        "total": total,
        "sucessos": sucessos,
    }


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/2_transcrever.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    resultado = transcrever_todos(pasta_projeto)

    if not resultado.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
