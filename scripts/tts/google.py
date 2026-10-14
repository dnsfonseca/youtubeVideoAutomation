"""Provedor de TTS Google Cloud Text-to-Speech (CLAUDE.md secao 5.6) - o
unico provedor implementado de verdade no MVP (ElevenLabs/OpenAI/Azure sao
stubs, ver scripts/tts/elevenlabs.py etc).

Chama o endpoint REST `texttospeech.googleapis.com/v1/text:synthesize`
diretamente via `requests` (sem SDK `google-cloud-texttospeech` - evita
puxar a dependencia pesada `google-cloud-*` so pra uma chamada HTTP
simples com autenticacao por API key).

Restricao de custo (CLAUDE.md): so o tier Wavenet ($4/1M chars) e'
permitido. Neural2 ($16), Chirp3-HD ($30) e Studio ($160) custam
significativamente mais - qualquer voz fora do catalogo curado
(scripts/tts/vozes_catalogo.json, que so lista vozes Wavenet) e' recusada
antes de chamar a API.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

from .base import ProvedorTTS
from .erros import (
    ChaveTTSAusenteError,
    ChaveTTSInvalidaError,
    QuotaExcedidaError,
    TierNaoPermitidoError,
    VozInvalidaError,
)

# NAO ALTERAR sem validacao de custo (CLAUDE.md) - Neural2=$16/1M,
# Chirp3-HD=$30/1M, Studio=$160/1M. Wavenet e' o unico tier presente em
# vozes_catalogo.json de proposito.
GOOGLE_TTS_TIER_PERMITIDO = "Wavenet"

# Custo por milhao de caracteres, por tier (referencia - CLAUDE.md secao 11).
CUSTOS_POR_TIER = {
    "Standard": 4.00,
    "Wavenet": 4.00,
    "Neural2": 16.00,
    "Chirp3-HD": 30.00,
    "Studio": 160.00,
}

ENDPOINT_SYNTHESIZE = "https://texttospeech.googleapis.com/v1/text:synthesize"

# Google TTS API tem limite de 5000 BYTES por request (nao caracteres).
# UTF-8 multibyte (em-dashes, aspas curvas, reticencias) faz um chunk de
# ~4900 chars facilmente ultrapassar 5000 bytes e a API rejeita com HTTP
# 400 (bug real, sessao de correcao pos-Sessao 8). Margem de seguranca de
# 200 bytes pra evitar esses edge cases.
LIMITE_BYTES_POR_CHAMADA = 4800

TIMEOUT_REQUEST_S = 60
TIMEOUT_FFMPEG_S = 120
TIMEOUT_FFPROBE_S = 30

# Transicao entre chunks concatenados (sessao pos-8.2 - feedback de uso real:
# "as pausas entre os paragrafos ficaram meio secas", roteiro Lily & Jack,
# corte reto do concat demuxer). Constantes isoladas aqui pra ajuste fino
# futuro sem tocar na logica de _construir_filtro_transicao.
FADE_OUT_S = 0.15
SILENCIO_ENTRE_CHUNKS_S = 0.5
FADE_IN_S = 0.15

_CATALOGO_PATH = Path(__file__).resolve().parent / "vozes_catalogo.json"
_catalogo_cache = None


def _carregar_catalogo() -> dict:
    """Cacheado no nivel de modulo - o catalogo e' um arquivo estatico
    versionado com o codigo, nao muda durante a execucao do processo."""
    global _catalogo_cache
    if _catalogo_cache is None:
        _catalogo_cache = json.loads(_CATALOGO_PATH.read_text(encoding="utf-8"))
    return _catalogo_cache


def _todas_vozes_google() -> dict:
    """Mapa id -> entrada de voz, de TODOS os idiomas do provedor google -
    usado para validar que uma voz pedida existe no catalogo curado
    independente do idioma (protecao contra origem_audio.json manipulado
    apontando pra uma voz fora do catalogo)."""
    catalogo = _carregar_catalogo().get("google", {})
    vozes = {}
    for lista in catalogo.values():
        for voz in lista:
            vozes[voz["id"]] = voz
    return vozes


def _dividir_em_chunks(texto: str, limite: int = LIMITE_BYTES_POR_CHAMADA) -> list:
    """Divide `texto` em pedacos de ate `limite` BYTES (UTF-8), preservando
    fronteiras de frase (fim de frase = '.' ou quebra de linha) - nunca
    corta uma frase ao meio, o que produziria uma pausa antinatural na
    narracao entre dois chunks sintetizados separadamente. Google TTS mede
    o limite em bytes, nao caracteres - caracteres UTF-8 multibyte
    (em-dashes, aspas curvas, etc) precisam ser contados corretamente pra
    nao estourar o limite da API (ver LIMITE_BYTES_POR_CHAMADA)."""
    texto = texto.strip()
    if len(texto.encode("utf-8")) <= limite:
        return [texto] if texto else []

    frases = [f for f in re.split(r"(?<=[.\n])\s+", texto) if f.strip()]
    chunks = []
    atual = ""
    for frase in frases:
        candidato = f"{atual} {frase}".strip() if atual else frase
        if len(candidato.encode("utf-8")) > limite and atual:
            chunks.append(atual)
            atual = frase
        else:
            atual = candidato
    if atual:
        chunks.append(atual)

    # Salvaguarda: se alguma frase individual excede o limite sozinha,
    # sub-dividir por palavras pra evitar payload rejeitado pela API.
    chunks_finais = []
    for chunk in chunks:
        if len(chunk.encode("utf-8")) <= limite:
            chunks_finais.append(chunk)
        else:
            chunks_finais.extend(_sub_dividir_por_palavras(chunk, limite))
    return chunks_finais


def _sub_dividir_por_palavras(texto: str, limite: int) -> list:
    """Fallback: divide texto por palavras quando uma frase individual
    excede o limite de bytes. Ultima linha de defesa contra payload
    rejeitado pela API Google TTS."""
    palavras = texto.split()
    chunks = []
    atual = ""
    for palavra in palavras:
        candidato = f"{atual} {palavra}".strip() if atual else palavra
        if len(candidato.encode("utf-8")) > limite and atual:
            chunks.append(atual)
            atual = palavra
        else:
            atual = candidato
    if atual:
        chunks.append(atual)
    return chunks


def _language_code_de_voz(voz: str) -> str:
    """"en-US-Wavenet-D" -> "en-US" (o languageCode exigido pela API vem
    sempre do prefixo antes de "-Wavenet-")."""
    return voz.split(f"-{GOOGLE_TTS_TIER_PERMITIDO}-")[0]


def _construir_filtro_transicao(duracoes: list) -> str:
    """Monta o filter_complex do ffmpeg com fade in/out entre chunks e
    silencio de SILENCIO_ENTRE_CHUNKS_S entre cada par - evita o corte seco
    audivel do concat demuxer simples (feedback de uso real, roteiro Lily &
    Jack). Primeiro chunk nao tem fade in (comeca normal), ultimo nao tem
    fade out (termina normal); intermediarios tem os dois."""
    n = len(duracoes)
    labels = []
    partes_filtro = []
    for i, duracao in enumerate(duracoes):
        filtros_chunk = []
        if i != 0:
            filtros_chunk.append(f"afade=t=in:st=0:d={FADE_IN_S}")
        if i != n - 1:
            inicio_fade_out = max(0.0, duracao - FADE_OUT_S)
            filtros_chunk.append(f"afade=t=out:st={inicio_fade_out}:d={FADE_OUT_S}")

        label = f"a{i}"
        labels.append(label)
        if filtros_chunk:
            partes_filtro.append(f"[{i}:a]{','.join(filtros_chunk)}[{label}]")
        else:
            partes_filtro.append(f"[{i}:a]anull[{label}]")

    partes_filtro.append(f"aevalsrc=0:d={SILENCIO_ENTRE_CHUNKS_S}[silencio]")

    entradas_concat = []
    for i, label in enumerate(labels):
        entradas_concat.append(f"[{label}]")
        if i != n - 1:
            entradas_concat.append("[silencio]")
    partes_filtro.append(
        f"{''.join(entradas_concat)}concat=n={len(entradas_concat)}:v=0:a=1[out]"
    )

    return ";".join(partes_filtro)


def _concatenar_audios_ffmpeg(caminhos_chunks: list, saida: Path):
    """Concatena os chunks com fade out/in e silencio entre eles (ver
    FADE_OUT_S/SILENCIO_ENTRE_CHUNKS_S/FADE_IN_S). Chunk unico e' so copiado
    - sem fade nem silencio, nada a suavizar."""
    if len(caminhos_chunks) <= 1:
        if caminhos_chunks:
            shutil.copyfile(caminhos_chunks[0], saida)
        return

    duracoes = [_duracao_audio_s(caminho) for caminho in caminhos_chunks]
    filtro = _construir_filtro_transicao(duracoes)

    comando = ["ffmpeg", "-y"]
    for caminho in caminhos_chunks:
        comando += ["-i", str(caminho)]
    comando += ["-filter_complex", filtro, "-map", "[out]", str(saida)]

    subprocess.run(
        comando,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_FFMPEG_S,
    )


def _duracao_audio_s(caminho: Path) -> float:
    """Duracao do MP3 gerado, via ffprobe - a API Google TTS nao devolve
    duracao na resposta. Nunca levanta excecao (best-effort, so metadado
    informativo); retorna 0.0 se nao conseguir determinar."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(caminho),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_FFPROBE_S,
        )
        return round(float((resultado.stdout or "0").strip()), 2)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


class GoogleTTS(ProvedorTTS):
    def validar_configuracao(self) -> tuple:
        if not os.environ.get("GOOGLE_TTS_API_KEY"):
            return False, "Configure GOOGLE_TTS_API_KEY em Ajustes antes de usar o provedor Google TTS."
        return True, "Chave Google TTS configurada."

    def listar_vozes(self, idioma: str) -> list:
        catalogo = _carregar_catalogo().get("google", {})
        vozes = catalogo.get(idioma)
        if not vozes:
            print(
                f"[WARN] Nenhuma voz Google TTS curada para o idioma '{idioma}'.",
                flush=True,
            )
            return []
        return vozes

    def _chamar_api(self, texto: str, voz: str, api_key: str) -> bytes:
        payload = {
            "input": {"text": texto},
            "voice": {"languageCode": _language_code_de_voz(voz), "name": voz},
            "audioConfig": {"audioEncoding": "MP3"},
        }
        resposta = requests.post(
            ENDPOINT_SYNTHESIZE,
            params={"key": api_key},
            json=payload,
            timeout=TIMEOUT_REQUEST_S,
        )
        if resposta.status_code in (401, 403):
            raise ChaveTTSInvalidaError("Chave Google TTS invalida ou sem permissao.")
        if resposta.status_code == 429:
            raise QuotaExcedidaError("Cota da API Google TTS excedida.")
        resposta.raise_for_status()

        dados = resposta.json()
        audio_base64 = dados.get("audioContent")
        if not audio_base64:
            raise ChaveTTSInvalidaError("Resposta da API Google TTS sem audioContent.")
        return base64.b64decode(audio_base64)

    def sintetizar(self, texto: str, voz: str, saida: Path) -> dict:
        api_key = os.environ.get("GOOGLE_TTS_API_KEY")
        if not api_key:
            raise ChaveTTSAusenteError("GOOGLE_TTS_API_KEY")

        if GOOGLE_TTS_TIER_PERMITIDO not in voz:
            raise TierNaoPermitidoError(voz, GOOGLE_TTS_TIER_PERMITIDO)

        if voz not in _todas_vozes_google():
            raise VozInvalidaError(voz)

        saida = Path(saida)
        custo_por_milhao = CUSTOS_POR_TIER[GOOGLE_TTS_TIER_PERMITIDO]
        chunks = _dividir_em_chunks(texto)
        custo_total = 0.0

        if len(chunks) <= 1:
            chunk_unico = chunks[0] if chunks else ""
            audio_bytes = self._chamar_api(chunk_unico, voz, api_key)
            saida.write_bytes(audio_bytes)
            custo_total = (len(chunk_unico) / 1_000_000) * custo_por_milhao
        else:
            with tempfile.TemporaryDirectory() as pasta_temp_str:
                pasta_temp = Path(pasta_temp_str)
                caminhos_chunks = []
                for indice, chunk in enumerate(chunks):
                    audio_bytes = self._chamar_api(chunk, voz, api_key)
                    caminho_chunk = pasta_temp / f"chunk_{indice:03d}.mp3"
                    caminho_chunk.write_bytes(audio_bytes)
                    caminhos_chunks.append(caminho_chunk)
                    custo_total += (len(chunk) / 1_000_000) * custo_por_milhao
                _concatenar_audios_ffmpeg(caminhos_chunks, saida)

        return {
            "audio_path": saida,
            "alinhamento": None,
            "duracao_s": _duracao_audio_s(saida),
            "provedor": "google",
            "voz_usada": voz,
            "custo_estimado_usd": round(custo_total, 6),
            "chunks_processados": len(chunks) or 1,
        }
