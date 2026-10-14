"""Provedor de TTS DarkPlanner - vozes ElevenLabs via plano PRO ja pago
pelo usuario (CLAUDE.md secao 5.6, integracao pos-Sessao 25).

Diferenca arquitetural em relacao ao Google TTS: a API do DarkPlanner e'
assincrona (POST /generate -> job_id -> polling GET /status/{job_id} ate
"completed" -> GET /download/{job_id} -> baixa o MP3). Essa diferenca fica
inteiramente encapsulada dentro de `sintetizar()` - scripts/4_obter_audio.py
so conhece a interface sincrona `ProvedorTTS` (CLAUDE.md secao 5.6), nao
sabe (nem precisa saber) que por baixo rolou polling.

Nao ha catalogo curado estatico como o Google (scripts/tts/vozes_catalogo.json)
- as vozes vem dinamicamente de GET /voices, cacheadas em memoria por
CACHE_TTL_S (a API tem rate limit de 10 requests/minuto, entao nao pode ser
chamada a cada abertura do formulario de revisao).

A API NAO devolve idioma por voz - `listar_vozes()` ignora o parametro
`idioma` e devolve todas as vozes do plano (vozes ElevenLabs sao
tipicamente multilingues, e tentar inferir idioma a partir do nome da voz
seria uma heuristica fragil sem base real na resposta da API).

A API PODE devolver alinhamento por palavra: GET /download/{job_id} tem um
objeto aninhado "urls" com "audio"/"srt"/"srt_padrao"/"srt_palavra" (doc
oficial confirmada). Quando "srt_palavra" esta presente, `sintetizar()`
baixa e converte esse SRT para o formato interno de alinhamento
(`_obter_alinhamento_srt_palavra`/`_srt_para_palavras`) e retorna direto em
`alinhamento` - evita rodar faster-whisper (Etapa 4, CLAUDE.md secao 5.6)
inteiro pra um audio que ja tem timestamp por palavra. Qualquer falha nesse
caminho (SRT ausente no plano contratado, erro de download, parsing sem
nenhuma palavra valida, ffprobe falhando ao medir a duracao real do mp3)
faz `alinhamento` voltar `None` - scripts/4_obter_audio.py ja sabe cair
para faster-whisper quando isso acontece (mesmo caminho usado pelo Google
TTS), entao o fallback e' automatico, sem nenhum codigo especial la.

Fallback duplo de compatibilidade: `_obter_urls_download` le
`urls.audio`/`urls.srt_palavra` (formato aninhado, documentado) mas cai
para `audio_url`/`srt_palavra_url` na RAIZ da resposta se o aninhado nao
existir - protege contra a resposta real da API ter um formato mais antigo
(achatado) do que a doc mais recente descreve.
"""

import logging
import os
import re
import subprocess
import time
from pathlib import Path

import requests

from .base import ProvedorTTS
from .erros import ChaveTTSAusenteError, ChaveTTSInvalidaError, QuotaExcedidaError

logger = logging.getLogger(__name__)

BASE_URL = "https://app.darkplanner.com.br/api/v1/audio"

TIMEOUT_REQUEST_S = 30
TIMEOUT_DOWNLOAD_S = 120
TIMEOUT_POLLING_S = 300  # 5 min max esperando o job completar
INTERVALO_POLLING_S = 3  # verifica status a cada 3s

STATUS_TERMINAIS_SUCESSO = {"completed"}
STATUS_TERMINAIS_ERRO = {"failed", "error"}

TIMEOUT_FFPROBE_S = 30

# Aceita "," (padrao SRT) e "." (visto em variantes de gerador) como
# separador de milissegundos - mesma tolerancia usada em parsers de SRT
# em outras partes do projeto.
_REGEX_TIMESTAMP_SRT = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
)

# Cache em memoria da lista de vozes (protege o rate limit de 10 req/min da
# API - nao pode ser chamada a cada abertura do formulario de revisao).
CACHE_TTL_S = 300  # 5 minutos
_cache_vozes = {"vozes": None, "obtido_em": 0.0}


class DarkPlannerTTS(ProvedorTTS):
    def validar_configuracao(self) -> tuple:
        if not os.environ.get("DARKPLANNER_API_KEY"):
            return False, "Configure DARKPLANNER_API_KEY em Ajustes antes de usar o provedor DarkPlanner."
        return True, "Chave DarkPlanner configurada."

    def listar_vozes(self, idioma: str) -> list:
        """Retorna todas as vozes do plano DarkPlanner, do cache em memoria
        se ainda valido (CACHE_TTL_S) ou buscando de novo em GET /voices.

        `idioma` e' ignorado de proposito (ver docstring do modulo). Nunca
        levanta excecao - falha ao consultar a API vira lista vazia (mesmo
        espirito de scripts/tts/google.py:listar_vozes, que tambem nunca
        propaga excecao pra nao quebrar o formulario de revisao)."""
        api_key = os.environ.get("DARKPLANNER_API_KEY")
        if not api_key:
            return []

        vozes = _vozes_do_cache(api_key)
        return vozes

    def sintetizar(self, texto: str, voz: str, saida: Path) -> dict:
        api_key = os.environ.get("DARKPLANNER_API_KEY")
        if not api_key:
            raise ChaveTTSAusenteError("DARKPLANNER_API_KEY")

        saida = Path(saida)
        job_id = _submeter_job(api_key, texto, voz)
        _aguardar_conclusao(api_key, job_id)
        urls = _obter_urls_download(api_key, job_id)
        _baixar_arquivo(urls["audio_url"], saida)

        alinhamento = _obter_alinhamento_srt_palavra(urls.get("srt_palavra_url"), saida)

        return {
            "audio_path": saida,
            "alinhamento": alinhamento,
            "duracao_s": (alinhamento or {}).get("duracao_s") or 0.0,
            "provedor": "darkplanner",
            "voz_usada": voz,
            "custo_estimado_usd": 0.0,
        }


def _headers(api_key: str) -> dict:
    return {"X-API-Key": api_key}


def _submeter_job(api_key: str, texto: str, voz: str) -> str:
    try:
        resposta = requests.post(
            f"{BASE_URL}/generate",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json={"text": texto, "voice_id": voz},
            timeout=TIMEOUT_REQUEST_S,
        )
    except requests.RequestException as exc:
        raise ChaveTTSInvalidaError(f"Falha de rede ao submeter job DarkPlanner: {exc}") from exc

    if resposta.status_code in (401, 403):
        raise ChaveTTSInvalidaError("Chave DarkPlanner invalida ou sem permissao.")
    if resposta.status_code == 429:
        raise QuotaExcedidaError("Limite de uso da API DarkPlanner excedido (10 requests/minuto).")
    resposta.raise_for_status()

    job_id = (resposta.json() or {}).get("job_id")
    if not job_id:
        raise ChaveTTSInvalidaError("Resposta do DarkPlanner sem job_id.")
    return job_id


def _aguardar_conclusao(api_key: str, job_id: str) -> None:
    inicio = time.monotonic()
    while True:
        if time.monotonic() - inicio > TIMEOUT_POLLING_S:
            raise ChaveTTSInvalidaError(
                f"Timeout aguardando job DarkPlanner '{job_id}' concluir (>{TIMEOUT_POLLING_S}s)."
            )

        try:
            resposta = requests.get(
                f"{BASE_URL}/status/{job_id}",
                headers=_headers(api_key),
                timeout=TIMEOUT_REQUEST_S,
            )
        except requests.RequestException as exc:
            raise ChaveTTSInvalidaError(f"Falha de rede ao verificar status do job DarkPlanner: {exc}") from exc

        resposta.raise_for_status()
        dados = resposta.json() or {}
        status = str(dados.get("status", "")).lower()

        if status in STATUS_TERMINAIS_SUCESSO:
            return
        if status in STATUS_TERMINAIS_ERRO:
            raise ChaveTTSInvalidaError(
                f"Job DarkPlanner '{job_id}' falhou: {dados.get('message', status)}"
            )

        time.sleep(INTERVALO_POLLING_S)


def _obter_urls_download(api_key: str, job_id: str) -> dict:
    """Le GET /download/{job_id} e devolve {"audio_url", "srt_palavra_url"}.

    Formato documentado (aninhado): {"urls": {"audio": "...", "srt_palavra":
    "..."}}. Fallback de compatibilidade (achatado, campos na raiz):
    {"audio_url": "...", "srt_palavra_url": "..."} - protege contra a API
    real ainda usar (ou voltar a usar) o formato antigo. `srt_palavra_url`
    e' sempre opcional (None se ausente nos dois formatos); `audio_url` e'
    obrigatorio nos dois."""
    resposta = requests.get(
        f"{BASE_URL}/download/{job_id}",
        headers=_headers(api_key),
        timeout=TIMEOUT_REQUEST_S,
    )
    resposta.raise_for_status()
    dados = resposta.json() or {}
    urls_aninhadas = dados.get("urls") or {}

    audio_url = urls_aninhadas.get("audio") or dados.get("audio_url")
    srt_palavra_url = urls_aninhadas.get("srt_palavra") or dados.get("srt_palavra_url")

    if not audio_url:
        raise ChaveTTSInvalidaError(f"Resposta do DarkPlanner sem audio_url para o job '{job_id}'.")
    return {"audio_url": audio_url, "srt_palavra_url": srt_palavra_url}


def _obter_alinhamento_srt_palavra(srt_palavra_url, caminho_audio: Path):
    """Baixa e converte o SRT por palavra do DarkPlanner (se a URL foi
    fornecida) para o formato interno de alinhamento (CLAUDE.md secao 5.6).
    Nunca levanta excecao: qualquer falha (URL ausente, download com erro,
    parsing sem nenhuma palavra valida, ffprobe falhando ao medir a duracao
    real do mp3) retorna None - scripts/4_obter_audio.py ja sabe cair para
    faster-whisper quando `alinhamento` vem None (mesmo caminho usado pelo
    Google TTS)."""
    if not srt_palavra_url:
        return None

    caminho_srt = caminho_audio.with_name(f"{caminho_audio.stem}_palavra.srt")
    try:
        _baixar_arquivo(srt_palavra_url, caminho_srt)
        palavras = _srt_para_palavras(caminho_srt)
        if not palavras:
            logger.warning("SRT palavra do DarkPlanner sem nenhuma palavra valida - fallback Whisper.")
            return None
        duracao_s = _duracao_audio_ffprobe(caminho_audio)
    except (requests.RequestException, OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Falha obtendo alinhamento via SRT palavra do DarkPlanner: %s", exc)
        return None

    return {
        "duracao_s": duracao_s,
        "idioma_detectado": None,
        "texto_transcrito": " ".join(palavra["palavra"] for palavra in palavras),
        "palavras": palavras,
    }


def _srt_para_palavras(caminho_srt: Path) -> list:
    """Converte um SRT por palavra (1-3 palavras curtas por bloco,
    timestamp `HH:MM:SS,mmm --> HH:MM:SS,mmm`) para
    `[{"palavra", "inicio_s", "fim_s"}, ...]`. Tolera bloco com ou sem linha
    de indice numerico antes do timestamp, e bloco vazio no final do
    arquivo (comum em SRT) - blocos que nao casam o padrao esperado sao
    simplesmente ignorados, nunca levantam excecao."""
    conteudo = caminho_srt.read_text(encoding="utf-8-sig")

    palavras = []
    for bloco in re.split(r"\n\s*\n", conteudo.strip()):
        linhas = [linha for linha in bloco.strip().splitlines() if linha.strip()]
        if len(linhas) < 2:
            continue

        indice_timestamp = 1 if linhas[0].strip().isdigit() else 0
        if indice_timestamp >= len(linhas):
            continue

        match = _REGEX_TIMESTAMP_SRT.match(linhas[indice_timestamp].strip())
        if not match:
            continue

        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(grupo) for grupo in match.groups())
        inicio_s = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        fim_s = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000

        texto = " ".join(linhas[indice_timestamp + 1 :]).strip()
        if texto:
            palavras.append({"palavra": texto, "inicio_s": round(inicio_s, 3), "fim_s": round(fim_s, 3)})

    return palavras


def _duracao_audio_ffprobe(caminho_audio: Path) -> float:
    """Duracao real do mp3 via ffprobe - NUNCA o ultimo `fim_s` do SRT
    palavra. O SRT pode terminar antes do fim real do audio (silencio final
    da narracao); a Etapa 5 planeja slots de clipe com base em `duracao_s`,
    entao usar o fim do SRT deixaria os ultimos segundos do audio sem clipe
    planejado. Levanta excecao em qualquer falha (comando, parsing) - o
    chamador (`_obter_alinhamento_srt_palavra`) trata isso como falha do
    caminho SRT inteiro e cai para o fallback Whisper."""
    resultado = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(caminho_audio),
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_FFPROBE_S,
        check=True,
    )
    return float(resultado.stdout.strip())


def _baixar_arquivo(url: str, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    resposta = requests.get(url, stream=True, timeout=TIMEOUT_DOWNLOAD_S)
    resposta.raise_for_status()
    with open(caminho, "wb") as arquivo:
        for chunk in resposta.iter_content(chunk_size=8192):
            if chunk:
                arquivo.write(chunk)


def _vozes_do_cache(api_key: str) -> list:
    agora = time.monotonic()
    if _cache_vozes["vozes"] is not None and (agora - _cache_vozes["obtido_em"]) < CACHE_TTL_S:
        return _cache_vozes["vozes"]

    try:
        resposta = requests.get(
            f"{BASE_URL}/voices",
            headers=_headers(api_key),
            timeout=TIMEOUT_REQUEST_S,
        )
        resposta.raise_for_status()
        vozes_brutas = (resposta.json() or {}).get("voices", [])
    except requests.RequestException as exc:
        logger.warning("Falha ao listar vozes DarkPlanner: %s", exc)
        return _cache_vozes["vozes"] or []

    vozes = [
        {
            "id": voz.get("id"),
            "genero": voz.get("gender", "desconhecido"),
            "descricao": voz.get("name", "Sem nome"),
            "recomendada_para": [],
            "amostra_url": voz.get("preview_url"),
        }
        for voz in vozes_brutas
        if voz.get("id")
    ]
    _cache_vozes["vozes"] = vozes
    _cache_vozes["obtido_em"] = agora
    return vozes


def limpar_cache_vozes() -> None:
    """Reseta o cache em memoria (usado pelos testes, e util pra forcar
    releitura apos o usuario trocar a chave em Ajustes)."""
    _cache_vozes["vozes"] = None
    _cache_vozes["obtido_em"] = 0.0
