"""Etapa 4 do pipeline (CLAUDE.md secao 5.6) - obtem o audio da narracao do
video, seja gerando via TTS (Google Cloud TTS no MVP - ver scripts/tts/) ou
usando um audio enviado pelo usuario, e produz o alinhamento por palavra
que as etapas seguintes (divisao de cenas, montagem, renderizacao,
legendas) precisam.

Uso: python "scripts/4_obter_audio.py" <caminho_da_pasta_do_projeto>

Entrada: origem_audio.json (gravado por POST /projetos/<id>/aprovar_roteiro -
CLAUDE.md secao 5.5), com o formato:
{"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-D"}
ou
{"origem": "upload", "upload_arquivo": "narracao_upload.mp3"}

Saida:
- narracao.mp3 - audio final da narracao (sempre MP3, mesmo quando a
  origem foi upload em outro formato).
- narracao_alinhamento.json - schema (CLAUDE.md secao 5.6):
  {"duracao_s": ..., "idioma_detectado": "...", "texto_transcrito": "...",
   "palavras": [{"palavra": "...", "inicio_s": ..., "fim_s": ...}, ...]}
- narracao_metadata.json - origem, provedor/voz (se TTS), custo, tempo de
  geracao, etc (CLAUDE.md secao 5.6).

Caminho A (TTS): le roteiro_aprovado.md (ja vem SEM notas de rodape de
origem - filtro implementado na Sessao 7.1) e remove cabecalhos markdown
ATX ("## Titulo de secao") de novo por seguranca (_remover_cabecalhos_
markdown - rede defensiva, ja deveriam ter sido removidos na aprovacao,
mas um roteiro real chegou aqui com 17 intactos numa sessao de
verificacao - ver docstring da funcao) antes de chamar
scripts/tts/get_provedor(provedor).sintetizar().
Se o provedor nao devolver alinhamento nativo (caso do Google - a API REST
nao fornece timestamps por palavra), roda faster-whisper em cima do
narracao.mp3 recem-gerado para produzir o alinhamento (transcricao forcada).

Caminho B (upload): converte o arquivo enviado (mp3/wav/m4a/ogg) para MP3
padrao via ffmpeg, depois roda faster-whisper para gerar alinhamento E
transcricao - a transcricao real (nao o roteiro escrito) e' o que a Etapa
de legendas usa quando a origem e' upload (CLAUDE.md secao 5.9), porque um
humano pode improvisar/trocar palavras ao gravar.

Origem "depois" nunca deveria chegar aqui (server.py so dispara esta etapa
quando a origem ja foi decidida) - tratado como erro de pre-condicao
(CLAUDE.md secao 18.6), nunca crasha.

Este script e' autocontido (CLAUDE.md secao 9) - exceto por scripts/tts/
(arquitetura pluggable de provedores, infra transversal, nao logica de
pipeline duplicavel), scripts/robustez.py (checagem de ffmpeg no PATH) e
scripts/whisper_setup.py (registro de DLLs cuBLAS/cuDNN, infra transversal
de robustez compartilhada com scripts/2_transcrever.py - CLAUDE.md
secao 4/18.9).
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Precisa da RAIZ do projeto no sys.path (nao so scripts/) porque
# scripts/tts/ e scripts/robustez.py sao importados via caminho absoluto de
# pacote (`scripts.tts...`, `scripts.robustez`) - mesma convencao de
# scripts/3_gerar_roteiro.py.
_RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ_PROJETO))

from scripts import robustez  # noqa: E402
from scripts import whisper_setup  # noqa: E402
from scripts.tts import (  # noqa: E402
    ChaveTTSAusenteError,
    ChaveTTSInvalidaError,
    ProvedorTTSInvalidoError,
    QuotaExcedidaError,
    TierNaoPermitidoError,
    TTSErro,
    VozInvalidaError,
    get_provedor,
)

# Mesmo problema documentado em scripts/2_transcrever.py (CLAUDE.md secao
# 4/18.9): sem isso, a Etapa 4 falha com "Library cublas64_12.dll is not
# found or cannot be loaded" ao rodar faster-whisper para o alinhamento
# (Sessao 8.1-fix - confirmado em teste real com o projeto Lily & Jack).
whisper_setup.registrar_dlls_cuda()

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

MODELO_WHISPER_PADRAO = "medium"
DISPOSITIVO_WHISPER_PADRAO = "cuda"
COMPUTE_TYPE_PADRAO = "float16"

# Config duro (mesmo espirito dos timeouts das etapas 2/3) - nao editavel
# via .env de proposito.
TIMEOUT_TOTAL_S = 20 * 60
TIMEOUT_FFMPEG_S = 5 * 60
TIMEOUT_WHISPER_S = 10 * 60

COTACAO_USD_BRL_PADRAO = 5.20

EXTENSOES_AUDIO_VALIDAS = frozenset({".mp3", ".wav", ".m4a", ".ogg"})


class ErroConversaoFFmpeg(Exception):
    """Falha ao converter o audio enviado (upload) para MP3 via ffmpeg."""


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


def classificar_erro_tts(exc: Exception) -> tuple:
    """Classifica uma excecao de scripts/tts/ (CLAUDE.md secao 5.6) numa
    categoria conhecida, com mensagem amigavel pro usuario final."""
    if isinstance(exc, ChaveTTSAusenteError):
        return "chave_ausente", str(exc)
    if isinstance(exc, ChaveTTSInvalidaError):
        return "chave_invalida", str(exc)
    if isinstance(exc, QuotaExcedidaError):
        return "quota_excedida", str(exc)
    if isinstance(exc, (VozInvalidaError, ProvedorTTSInvalidoError)):
        return "voz_invalida", str(exc)
    if isinstance(exc, TierNaoPermitidoError):
        return "tier_nao_permitido", str(exc)
    return "erro_desconhecido", str(exc)


def _checar_timeout(inicio: float):
    if time.monotonic() - inicio > TIMEOUT_TOTAL_S:
        raise TimeoutError("Etapa de audio excedeu tempo limite.")


def _ler_cotacao_usd_brl() -> float:
    valor = os.environ.get("COTACAO_USD_BRL")
    if not valor:
        return COTACAO_USD_BRL_PADRAO
    try:
        return float(valor)
    except ValueError:
        return COTACAO_USD_BRL_PADRAO


def _ler_origem_audio(pasta_projeto: Path):
    caminho = pasta_projeto / "origem_audio.json"
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _validar_pre_condicoes(pasta_projeto: Path, origem_audio):
    """Valida tudo que este script precisa ANTES de comecar a processar
    (CLAUDE.md secao 18.6). Retorna (True, None, None) se pode prosseguir,
    ou (False, mensagem_de_erro, tipo_erro) caso contrario."""
    if origem_audio is None:
        return (
            False,
            "origem_audio.json nao encontrado. Aprove o roteiro na tela de "
            "revisao antes desta etapa.",
            "erro_desconhecido",
        )

    origem = origem_audio.get("origem")
    if origem == "depois":
        return (
            False,
            "A origem do audio ainda nao foi decidida (\"decidir depois\"). "
            "Volte a tela de revisao para escolher TTS ou upload.",
            "erro_desconhecido",
        )

    if origem == "tts":
        if not (pasta_projeto / "roteiro_aprovado.md").exists():
            return (
                False,
                "roteiro_aprovado.md nao encontrado. Aprove o roteiro antes desta etapa.",
                "erro_desconhecido",
            )
    elif origem == "upload":
        upload_arquivo = origem_audio.get("upload_arquivo")
        if not upload_arquivo:
            return False, "Nenhum arquivo de upload registrado em origem_audio.json.", "arquivo_upload_invalido"
        if not (pasta_projeto / upload_arquivo).exists():
            return (
                False,
                f"Arquivo de audio enviado nao encontrado: {upload_arquivo}",
                "arquivo_upload_invalido",
            )
    else:
        return False, f"origem_audio invalida: '{origem}'.", "erro_desconhecido"

    ok_ffmpeg, mensagem_ffmpeg = robustez.validar_pre_condicoes_pipeline()
    if not ok_ffmpeg:
        return False, mensagem_ffmpeg, "erro_desconhecido"

    return True, None, None


def _carregar_modelo_whisper() -> "WhisperModel":
    if WhisperModel is None:
        raise RuntimeError("faster-whisper nao esta instalado no ambiente Python atual.")
    modelo_nome = os.environ.get("WHISPER_MODEL") or MODELO_WHISPER_PADRAO
    dispositivo = os.environ.get("WHISPER_DEVICE") or DISPOSITIVO_WHISPER_PADRAO
    return WhisperModel(modelo_nome, device=dispositivo, compute_type=COMPUTE_TYPE_PADRAO)


def _gerar_alinhamento_whisper(caminho_audio: Path, inicio: float) -> dict:
    """Roda faster-whisper com word_timestamps=True sobre `caminho_audio`,
    numa thread daemon separada com timeout (mesmo padrao de
    scripts/2_transcrever.py:_transcrever_com_timeout). Usado tanto para o
    caminho TTS (quando o provedor nao devolve alinhamento nativo) quanto
    para o caminho de upload (alinhamento + transcricao real da fala)."""
    _checar_timeout(inicio)
    modelo = _carregar_modelo_whisper()

    estado = {"resultado": None, "erro": None}

    def _trabalho():
        try:
            segments, info = modelo.transcribe(str(caminho_audio), word_timestamps=True)
            palavras = []
            trechos_texto = []
            for seg in segments:
                texto_seg = (seg.text or "").strip()
                if texto_seg:
                    trechos_texto.append(texto_seg)
                for palavra in seg.words or []:
                    palavras.append(
                        {
                            "palavra": palavra.word.strip(),
                            "inicio_s": palavra.start,
                            "fim_s": palavra.end,
                        }
                    )
            estado["resultado"] = {
                "duracao_s": info.duration,
                "idioma_detectado": info.language,
                "texto_transcrito": " ".join(trechos_texto),
                "palavras": palavras,
            }
        except Exception as exc:  # repassado para a thread principal abaixo
            estado["erro"] = exc

    thread = threading.Thread(target=_trabalho, daemon=True)
    thread.start()
    thread.join(timeout=TIMEOUT_WHISPER_S)

    if thread.is_alive():
        raise TimeoutError(f"Geracao de alinhamento excedeu o tempo limite de {TIMEOUT_WHISPER_S:.0f}s.")
    if estado["erro"] is not None:
        raise estado["erro"]
    return estado["resultado"]


def _converter_para_mp3(origem: Path, destino: Path):
    """Converte qualquer formato de audio suportado (mp3/wav/m4a/ogg) para
    MP3 padrao via ffmpeg. Retorna (True, None) em sucesso, ou
    (False, mensagem_tecnica) caso contrario - nunca levanta excecao aqui
    (o chamador decide o que fazer com a falha, CLAUDE.md secao 18.5)."""
    try:
        resultado = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(origem),
                "-vn", "-acodec", "libmp3lame", "-qscale:a", "2",
                str(destino),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_FFMPEG_S,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"Falha ao executar ffmpeg: {exc}"

    if resultado.returncode != 0 or not destino.exists():
        trecho_stderr = "\n".join((resultado.stderr or "").strip().splitlines()[-15:])
        return False, trecho_stderr or "ffmpeg falhou ao converter o audio enviado."
    return True, None


def _registrar_log_tts(pasta_projeto: Path, metadata: dict):
    """Log de auditoria de chamadas de TTS (CLAUDE.md secao 5.6) -
    best-effort, nunca falha a etapa por causa deste log."""
    try:
        pasta_logs = pasta_projeto / "logs"
        pasta_logs.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        linha = (
            f"[{timestamp}] projeto={pasta_projeto.name} provedor={metadata.get('provedor')} "
            f"voz={metadata.get('voz_usada')} chars={metadata.get('chars_processados')} "
            f"custo=${metadata.get('custo_estimado_usd')} duracao={metadata.get('tempo_geracao_s')}s\n"
        )
        with (pasta_logs / "tts_calls.log").open("a", encoding="utf-8") as arquivo_log:
            arquivo_log.write(linha)
    except OSError:
        pass


# Duplicado de proposito de server.py:PADRAO_CABECALHO_MARKDOWN/
# remover_cabecalhos_markdown (CLAUDE.md secao 9 - script autocontido,
# server.py e' quem importa scripts/, nunca o contrario). Rede de
# seguranca defensiva (CLAUDE.md secao 18.6/18.7): esta etapa "confia" no
# contrato de que roteiro_aprovado.md ja' chega sem cabecalhos markdown
# (a tela de revisao/aprovar_roteiro e' quem deveria garantir isso), mas
# um roteiro REAL aprovado em producao (nancyGuthrieProject03, sessao de
# verificacao pos-correcoes de composicao/interface) chegou a esta etapa
# com 17 cabecalhos "## Titulo de secao" intactos - o TTS teria narrado
# cada titulo literalmente. Raiz provavel: processo do servidor rodando
# codigo anterior ao fix da Sessao 21 sem reiniciar, nao um bug na propria
# funcao de remocao (validada isoladamente contra o arquivo real). Ainda
# assim, esta etapa NUNCA deveria confiar cegamente num contrato entre
# telas - remove de novo aqui, custando nada quando o arquivo ja chega
# limpo.
_PADRAO_CABECALHO_MARKDOWN = re.compile(r"^#{1,6}[ \t]+.*$", re.MULTILINE)


def _remover_cabecalhos_markdown(texto: str) -> str:
    if not texto:
        return texto
    sem_cabecalhos = _PADRAO_CABECALHO_MARKDOWN.sub("", texto)
    sem_cabecalhos = re.sub(r"\n{3,}", "\n\n", sem_cabecalhos)
    return sem_cabecalhos.strip()


def _calcular_metrica_fechamento(texto: str | None, duracao_s) -> dict:
    """Metrica de fechamento (CLAUDE.md - reestruturacao do roteiro,
    Grupo E): registra quantas palavras por minuto a voz efetivamente
    produziu. Todo o calculo de presets de duracao na tela de Novo
    projeto assume ~160 palavras/minuto sem nunca medir contra a voz
    real - esta metrica fecha esse loop. Puramente informativa: nunca
    falha a etapa, nunca bloqueia nada, nunca dispara aviso."""
    if not texto or not duracao_s:
        return {}
    palavras = len(texto.split())
    minutos = duracao_s / 60
    if minutos <= 0:
        return {}
    return {
        "palavras_narradas": palavras,
        "palavras_por_minuto_efetivas": round(palavras / minutos, 1),
    }


def _obter_audio_tts(pasta_projeto: Path, origem_audio: dict, inicio: float) -> dict:
    provedor_nome = origem_audio.get("provedor")
    voz = origem_audio.get("voz")
    texto = (pasta_projeto / "roteiro_aprovado.md").read_text(encoding="utf-8")
    texto = _remover_cabecalhos_markdown(texto)
    caminho_audio = pasta_projeto / "narracao.mp3"

    emitir_progresso(5.0, f"Sintetizando narracao com {provedor_nome} ({voz})...")

    provedor = get_provedor(provedor_nome)
    ok_config, mensagem_config = provedor.validar_configuracao()
    if not ok_config:
        raise ChaveTTSAusenteError(mensagem_config)

    _checar_timeout(inicio)
    inicio_sintese = time.monotonic()
    resultado_sintese = provedor.sintetizar(texto, voz, caminho_audio)
    tempo_geracao_s = round(time.monotonic() - inicio_sintese, 1)

    emitir_progresso(60.0, "Narracao sintetizada. Gerando alinhamento por palavra...")

    alinhamento_nativo = resultado_sintese.get("alinhamento")
    if alinhamento_nativo is not None:
        alinhamento_dados = alinhamento_nativo
    else:
        # Provedores sem alinhamento nativo (caso do Google - a API REST
        # nao fornece timestamps por palavra) - faster-whisper roda em cima
        # do proprio audio recem-sintetizado para gerar o alinhamento.
        alinhamento_dados = _gerar_alinhamento_whisper(caminho_audio, inicio)

    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento_dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    custo_usd = resultado_sintese.get("custo_estimado_usd", 0.0) or 0.0
    cotacao_usd_brl = _ler_cotacao_usd_brl()
    metadata = {
        "origem": "tts",
        "provedor": provedor_nome,
        "voz_usada": resultado_sintese.get("voz_usada", voz),
        "duracao_s": alinhamento_dados.get("duracao_s") or resultado_sintese.get("duracao_s"),
        "custo_estimado_usd": custo_usd,
        "custo_estimado_brl": round(custo_usd * cotacao_usd_brl, 4),
        "chars_processados": len(texto),
        "tempo_geracao_s": tempo_geracao_s,
        "chunks_processados": resultado_sintese.get("chunks_processados", 1),
        "data_geracao": datetime.now(timezone.utc).isoformat(),
    }
    metadata.update(_calcular_metrica_fechamento(texto, metadata["duracao_s"]))
    _registrar_log_tts(pasta_projeto, metadata)
    return metadata


def _obter_audio_upload(pasta_projeto: Path, origem_audio: dict, inicio: float) -> dict:
    caminho_upload = pasta_projeto / origem_audio["upload_arquivo"]
    caminho_audio = pasta_projeto / "narracao.mp3"

    emitir_progresso(5.0, "Convertendo audio enviado para MP3...")
    ok, mensagem_erro = _converter_para_mp3(caminho_upload, caminho_audio)
    if not ok:
        raise ErroConversaoFFmpeg(mensagem_erro)

    emitir_progresso(40.0, "Transcrevendo audio para gerar alinhamento e legenda...")
    alinhamento_dados = _gerar_alinhamento_whisper(caminho_audio, inicio)

    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento_dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadata = {
        "origem": "upload",
        "provedor": None,
        "voz_usada": None,
        "duracao_s": alinhamento_dados.get("duracao_s"),
        "custo_estimado_usd": 0.0,
        "custo_estimado_brl": 0.0,
        "chars_processados": None,
        "tempo_geracao_s": None,
        "chunks_processados": None,
        "data_geracao": datetime.now(timezone.utc).isoformat(),
    }
    metadata.update(
        _calcular_metrica_fechamento(alinhamento_dados.get("texto_transcrito"), metadata["duracao_s"])
    )
    return metadata


def obter_audio(pasta_projeto: Path) -> dict:
    inicio = time.monotonic()

    origem_audio = _ler_origem_audio(pasta_projeto)
    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes(pasta_projeto, origem_audio)
    if not ok_precondicoes:
        emitir_progresso(
            0.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro
        )
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    origem = origem_audio["origem"]
    emitir_progresso(0.0, f"Iniciando obtencao de audio da narracao (origem: {origem})...")

    try:
        if origem == "tts":
            metadata = _obter_audio_tts(pasta_projeto, origem_audio, inicio)
        else:
            metadata = _obter_audio_upload(pasta_projeto, origem_audio, inicio)
    except TTSErro as exc:
        tipo_erro, mensagem_usuario = classificar_erro_tts(exc)
        emitir_progresso(
            0.0, f"ERRO: {mensagem_usuario}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_usuario
        )
        return {"sucesso": False, "erro_fatal": mensagem_usuario, "tipo_erro": tipo_erro}
    except ErroConversaoFFmpeg as exc:
        mensagem_usuario = f"Falha ao converter o audio enviado: {exc}"
        emitir_progresso(
            0.0,
            f"ERRO: {mensagem_usuario}",
            sucesso=False,
            tipo_erro="conversao_ffmpeg_falhou",
            mensagem_usuario=mensagem_usuario,
        )
        return {"sucesso": False, "erro_fatal": mensagem_usuario, "tipo_erro": "conversao_ffmpeg_falhou"}
    except TimeoutError as exc:
        mensagem_usuario = str(exc) or "Etapa de audio excedeu tempo limite."
        emitir_progresso(
            0.0, f"ERRO: {mensagem_usuario}", sucesso=False, tipo_erro="timeout", mensagem_usuario=mensagem_usuario
        )
        return {"sucesso": False, "erro_fatal": mensagem_usuario, "tipo_erro": "timeout"}
    except RuntimeError as exc:
        # faster-whisper nao instalado no ambiente atual.
        mensagem_usuario = str(exc)
        emitir_progresso(
            0.0,
            f"ERRO: {mensagem_usuario}",
            sucesso=False,
            tipo_erro="erro_desconhecido",
            mensagem_usuario=mensagem_usuario,
        )
        return {"sucesso": False, "erro_fatal": mensagem_usuario, "tipo_erro": "erro_desconhecido"}
    except requests.exceptions.HTTPError as exc:
        # Erro na chamada HTTP a API de sintese TTS (provedor.sintetizar())
        # - distinto de falha na geracao de alinhamento (faster-whisper),
        # que cai no handler generico abaixo. Log tecnico completo aqui;
        # mensagem_usuario fica amigavel.
        status_code = exc.response.status_code if exc.response is not None else None
        print(f"[SINTESE TTS] Falha na chamada a API (HTTP {status_code}): {exc}", flush=True)
        if status_code == 400:
            mensagem_usuario = (
                "API Google TTS rejeitou payload (HTTP 400). Provavel tamanho do "
                "chunk excedeu limite. Detalhes tecnicos no log."
            )
            tipo_erro = "payload_invalido"
        else:
            mensagem_usuario = f"Erro na chamada a API de sintese TTS (HTTP {status_code}): {exc}"
            tipo_erro = "erro_desconhecido"
        emitir_progresso(
            0.0, f"ERRO: {mensagem_usuario}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_usuario
        )
        return {"sucesso": False, "erro_fatal": mensagem_usuario, "tipo_erro": tipo_erro}
    except Exception as exc:
        # Chega aqui apenas se a falha veio da geracao de alinhamento
        # (faster-whisper) - falhas de sintese TTS via HTTP sao capturadas
        # pelo handler especifico acima, antes deste.
        mensagem_usuario = f"Erro na geracao de alinhamento: {exc}"
        print(f"[ALINHAMENTO] {mensagem_usuario}", flush=True)
        emitir_progresso(
            0.0,
            f"ERRO: {mensagem_usuario}",
            sucesso=False,
            tipo_erro="alinhamento_falhou",
            mensagem_usuario=mensagem_usuario,
        )
        return {"sucesso": False, "erro_fatal": mensagem_usuario, "tipo_erro": "alinhamento_falhou"}

    (pasta_projeto / "narracao_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    emitir_progresso(100.0, f"Audio da narracao obtido com sucesso (origem: {origem})", sucesso=True)
    return {"sucesso": True, "metadata": metadata}


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/4_obter_audio.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    resultado = obter_audio(pasta_projeto)

    if not resultado.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
