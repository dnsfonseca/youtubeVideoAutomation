"""Geracao e cache de previews de audio das vozes TTS curadas (CLAUDE.md
secao 5.6).

Um preview e' um MP3 curto (trecho fixo por idioma) sintetizado uma unica
vez por voz e cacheado em disco:

    static/previews_vozes/<idioma>/<voz_id>.mp3

servido depois direto como estatico pelo Flask (server.py:api_preview_voz).
Reusa scripts/tts/get_provedor("google").sintetizar() em vez de chamar a
API do Google TTS de novo por conta propria - mesma validacao de
tier/catalogo/custo ja testada em scripts/tts/google.py, sem dependencia
Python nova.

Voz que falha ao gerar preview (API fora do ar, voz descontinuada pela
Google, chave invalida) fica marcada em
static/previews_vozes/_indisponiveis.json com o motivo - tentativas
futuras (nova selecao na tela de revisao) veem a marca e nao chamam a API
de novo; server.py tambem usa essa marca para BLOQUEAR a aprovacao do
roteiro com essa voz (nunca confia so' na checagem do lado do cliente)."""

import json
import logging
import shutil
from pathlib import Path

from . import get_provedor

logger = logging.getLogger(__name__)

# Mesmo trecho narrativo (neutro, sem conteudo sensivel de caso real) em
# cada idioma do catalogo curado (server.py:IDIOMAS_SUPORTADOS) - curto o
# bastante pra nunca disparar o chunking de scripts/tts/google.py
# (LIMITE_BYTES_POR_CHAMADA=4800 bytes).
TRECHOS_PREVIEW = {
    "pt-BR": (
        "Era uma noite fria de dezembro. A cidade dormia, indiferente ao "
        "que se desenrolava naquela casa aparentemente tranquila. Ninguem "
        "suspeitava do que estava por vir."
    ),
    "en-US": (
        "It was a cold December night. The city slept, unaware of what "
        "was unfolding inside that seemingly quiet house. No one "
        "suspected what was about to happen."
    ),
    "en-GB": (
        "It was a cold December night. The city slept, unaware of what "
        "was unfolding inside that seemingly quiet house. No one "
        "suspected what was about to happen."
    ),
    "es": (
        "Era una fria noche de diciembre. La ciudad dormia, ajena a lo "
        "que ocurria dentro de esa casa aparentemente tranquila. Nadie "
        "sospechaba lo que estaba por venir."
    ),
    "de": (
        "Es war eine kalte Dezembernacht. Die Stadt schlief, ahnungslos, "
        "was sich in diesem scheinbar ruhigen Haus abspielte. Niemand "
        "ahnte, was bevorstand."
    ),
}
TRECHO_PADRAO = TRECHOS_PREVIEW["en-US"]

# Idiomas do catalogo curado (mesma lista de server.py:IDIOMAS_SUPORTADOS -
# duplicada aqui de proposito pra este modulo nao depender de importar
# server.py, que por sua vez importa scripts.tts - evita import circular).
IDIOMAS_CATALOGO = ["en-US", "en-GB", "pt-BR", "es", "de"]

PASTA_PREVIEWS = Path(__file__).resolve().parent.parent.parent / "static" / "previews_vozes"
ARQUIVO_INDISPONIVEIS = PASTA_PREVIEWS / "_indisponiveis.json"


def _trecho_para_idioma(idioma: str) -> str:
    return TRECHOS_PREVIEW.get(idioma, TRECHO_PADRAO)


def caminho_preview(voz_id: str, idioma: str) -> Path:
    """Caminho em disco onde o preview MP3 de `voz_id` deve estar."""
    return PASTA_PREVIEWS / idioma / f"{voz_id}.mp3"


def listar_vozes_para_preview(provedor_nome: str = "google") -> list:
    """Todas as vozes curadas de `provedor_nome`, com idioma, achatadas
    numa lista unica de {"id", "idioma"} - usado pelo batch de regeracao
    e pelo lookup de idioma a partir so' do voz_id (api_preview_voz nao
    recebe idioma como parametro)."""
    provedor = get_provedor(provedor_nome)
    vozes = []
    for idioma in IDIOMAS_CATALOGO:
        for voz in provedor.listar_vozes(idioma):
            vozes.append({"id": voz["id"], "idioma": idioma})
    return vozes


def buscar_idioma_da_voz(voz_id: str, provedor_nome: str = "google") -> str:
    """Idioma da voz `voz_id` no catalogo curado, ou None se a voz nao
    existir em nenhum idioma."""
    for voz in listar_vozes_para_preview(provedor_nome):
        if voz["id"] == voz_id:
            return voz["idioma"]
    return None


def _ler_indisponiveis_bruto() -> dict:
    if not ARQUIVO_INDISPONIVEIS.exists():
        return {}
    try:
        return json.loads(ARQUIVO_INDISPONIVEIS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def carregar_indisponiveis() -> dict:
    """Mapa voz_id -> motivo, das vozes marcadas indisponiveis."""
    return dict(_ler_indisponiveis_bruto().get("motivos", {}))


def marcar_indisponivel(voz_id: str, motivo: str) -> None:
    ARQUIVO_INDISPONIVEIS.parent.mkdir(parents=True, exist_ok=True)
    dados = _ler_indisponiveis_bruto()
    motivos = dados.get("motivos", {})
    motivos[voz_id] = motivo
    dados["motivos"] = motivos
    ARQUIVO_INDISPONIVEIS.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remover_de_indisponiveis(voz_id: str) -> None:
    """Retry apos falha anterior: tira `voz_id` da lista de indisponiveis
    (chamado apos uma geracao de preview bem-sucedida)."""
    dados = _ler_indisponiveis_bruto()
    motivos = dados.get("motivos", {})
    if voz_id in motivos:
        del motivos[voz_id]
        dados["motivos"] = motivos
        ARQUIVO_INDISPONIVEIS.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def gerar_preview(voz_id: str, idioma: str, provedor_nome: str = "google") -> dict:
    """Gera (ou retorna do cache) o preview MP3 de `voz_id`/`idioma`.

    Nunca levanta excecao - qualquer falha de sintese (chave invalida,
    quota excedida, voz descontinuada) vira `marcar_indisponivel` e
    retorno com sucesso=False, mesmo espirito de robustez do resto do
    pipeline (CLAUDE.md secao 18.4).

    Retorna: {"sucesso": bool, "caminho": Path|None, "erro": str|None,
    "ja_existia": bool}."""
    caminho = caminho_preview(voz_id, idioma)
    if caminho.is_file():
        return {"sucesso": True, "caminho": caminho, "erro": None, "ja_existia": True}

    caminho.parent.mkdir(parents=True, exist_ok=True)
    trecho = _trecho_para_idioma(idioma)

    try:
        provedor = get_provedor(provedor_nome)
        provedor.sintetizar(trecho, voz_id, caminho)
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira indisponibilidade, nunca 500 pro usuario
        caminho.unlink(missing_ok=True)
        motivo = str(exc)
        logger.warning("Falha ao gerar preview da voz '%s': %s", voz_id, motivo)
        marcar_indisponivel(voz_id, motivo)
        return {"sucesso": False, "caminho": None, "erro": motivo, "ja_existia": False}

    remover_de_indisponiveis(voz_id)
    return {"sucesso": True, "caminho": caminho, "erro": None, "ja_existia": False}


def gerar_previews_batch(vozes: list, provedor_nome: str = "google") -> dict:
    """Gera previews pra uma lista de {"id", "idioma"} (ver
    listar_vozes_para_preview). Retorna sumario agregado - nunca
    interrompe no meio por uma falha isolada."""
    geradas_agora = []
    ja_existiam = []
    falha_detalhes = []

    for voz in vozes:
        resultado = gerar_preview(voz["id"], voz["idioma"], provedor_nome)
        if not resultado["sucesso"]:
            falha_detalhes.append({"id": voz["id"], "erro": resultado["erro"]})
        elif resultado["ja_existia"]:
            ja_existiam.append(voz["id"])
        else:
            geradas_agora.append(voz["id"])

    return {
        "total": len(vozes),
        "geradas_agora": len(geradas_agora),
        "ja_existiam": len(ja_existiam),
        "falharam": len(falha_detalhes),
        "falha_detalhes": falha_detalhes,
    }


def regerar_todos_previews(provedor_nome: str = "google") -> dict:
    """Apaga o cache inteiro (previews + marca de indisponiveis) e gera
    tudo de novo - botao "Regerar todos os previews" em Ajustes."""
    if PASTA_PREVIEWS.exists():
        shutil.rmtree(PASTA_PREVIEWS)

    vozes = listar_vozes_para_preview(provedor_nome)
    return gerar_previews_batch(vozes, provedor_nome)
