"""Provedor de imagem "openai" (Etapa 7 - thumbnail) - composicao COMPLETA
da thumbnail (sujeito(s) + fundo, tudo numa imagem so') via `gerar_composicao`,
usando o endpoint `/v1/images/edits` do gpt-image-2. Unico caminho de
renderizacao real do produto - o modo antigo de gerar SO' o fundo (`gerar()`,
`/v1/images/generations`) foi removido na sessao de simplificacao da Etapa
7 (ver HISTORICO_BUGS.md), junto dos 5 templates de composicao via Pillow
que ele alimentava.

MODEL_ID e' a UNICA referencia ao nome do modelo neste arquivo - se a
OpenAI trocar o nome/versao do modelo de imagem, so' esta constante muda."""

import base64
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MODEL_ID = "gpt-image-2"

TIMEOUT_REQUEST_S = 90

# Estimativa de referencia pra exibir custo ao usuario (mesmo espirito de
# CUSTO_INPUT_POR_MILHAO_USD em scripts/7_thumbnail.py) - NAO e' usada
# pra cobranca real, so' pra log/visibilidade.
CUSTO_USD_ESTIMADO_POR_QUALIDADE = {"low": 0.02, "medium": 0.07, "high": 0.19}


# ---------------------------------------------------------------------------
# Composicao completa por IA - `gerar_composicao` manda o briefing
# exportavel (scripts/thumbnail_briefing.py) + as fotos ORIGINAIS dos
# sujeitos (sem recorte nenhum) pro endpoint /v1/images/edits, que edita as
# imagens de referencia em vez de gerar do zero - e' isso que preserva o
# rosto da pessoa real anexada.
# ---------------------------------------------------------------------------

BASE_URL_EDITS = "https://api.openai.com/v1/images/edits"

# 16:9 exato (1536/16=96, 864/16=54, ambas as dimensoes multiplas de 16 -
# requisito da API pra' size customizado; proporcao 16:9 esta' dentro da
# faixa 1:3-3:1 aceita; 1536x864=1.327.104 pixels, dentro da faixa
# 655.360-8.294.400 aceita).
#
# CORRECAO (achado real): a API de imagens da OpenAI aceita `size`
# customizado no gpt-image-2 (a limitacao a 1024x1024/1024x1536/1536x1024
# vale so' pro gpt-image-1). Pedir 1536x864 direto elimina a necessidade de
# qualquer crop depois - uma sessao anterior recortava 1536x1024 (3:2) pro
# centro em 16:9 e cortava texto perto das bordas; a correcao de verdade
# foi pedir a proporcao certa da API, nao ajustar o crop.
TAMANHO_API_COMPOSICAO = "1536x864"

# input_fidelity NAO e' parametro ajustavel no gpt-image-2 especificamente
# (embora exista no SDK generico da OpenAI pra' outros modelos da familia
# GPT Image) - a API processa toda imagem de entrada em alta fidelidade
# automatica, sem essa opcao. E' isso que preserva o rosto da foto anexada,
# e tambem o que mais aciona a recusa por moderacao de deepfake (gpt-image-2
# tem sistema de seguranca reforcado contra imagens fotorrealistas de
# pessoa real identificavel) - CLAUDE.md secao 5.85. Por isso nunca
# passamos esse parametro na chamada abaixo.

QUALIDADE_COMPOSICAO_PADRAO = "low"

MIME_POR_EXTENSAO = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

NOME_ARQUIVO_STATUS_COMPOSICAO = "composicao_status.json"

# HISTORICO: esta instrucao nasceu pra proteger texto de um crop de centro
# 3:2 -> 16:9 que `gerar_composicao` aplicava depois de receber a imagem -
# confirmado em teste real (nancyGuthrieProject03) que o modelo posiciona
# texto encostado nas bordas superior/inferior (como nas referencias
# visuais que ele imita), entao o corte cortava letras ("NANCY GUTHRIE
# UPDATE"/"THE MARK ON HIS WRIST" cortados). O crop foi REMOVIDO numa
# sessao seguinte (gerar_composicao passou a gravar exatamente os bytes
# que a API devolve, sem crop/resize/conversao de proporcao), mas o
# `size` pedido continuava sendo TAMANHO_API (1536x1024, 3:2) - ou seja,
# a imagem final saia em 3:2, nao 16:9, e o corte que sumiu era a unica
# coisa que alguma vez a tornava 16:9. Correcao desta sessao: a premissa
# de que gpt-image-2 so' aceita 1024x1024/1024x1536/1536x1024 estava
# ERRADA (valia pra' gpt-image-1) - a API aceita `size` customizado, entao
# `gerar_composicao` agora pede TAMANHO_API_COMPOSICAO (1536x864, 16:9
# exato) direto, sem crop nenhum em lugar nenhum do caminho. Esta
# instrucao deixa de ser defesa contra corte (nao ha' mais corte) mas
# continua sendo enviada de proposito: pedir margem generosa nas bordas
# ainda ajuda o modelo a deixar espaco pro headline/texto sem empurrar
# nada pra fora do frame. So' e' anexada ao prompt enviado pra API (nunca
# ao `briefing_completo` persistido em thumbnail/metadados.json/
# briefing.json - esse continua identico pro uso manual, onde o usuario
# controla o enquadramento por fora).
INSTRUCAO_AREA_SEGURA_16_9 = (
    "SAFE MARGIN GUIDANCE: this image is generated at 1536x864, already "
    "exactly 16:9, and will be used as-is afterward with NO cropping, "
    "resizing or reframing of any kind. Even so, keep every letter, glyph, "
    "arrow tip, badge or callout comfortably inside a margin of roughly 8% "
    "of the height from the top edge and 8% from the bottom edge (about 70 "
    "pixels on each side) - a headline, subject cutout and other graphic "
    "elements will be layered on top of this photo afterwards, so nothing "
    "textual should sit flush against the top or bottom edge. This margin "
    "must hold even if a headline wraps onto two lines: budget vertical "
    "space for the FULL wrapped text block (all lines plus normal line "
    "spacing) inside that safe area - if it would not fit, use a smaller "
    "font size rather than letting any line touch the edge. Faces and "
    "subject cutouts may extend closer to the edges, but no text or "
    "graphic element should."
)

# Mensagens amigaveis por tipo de erro - o `erro_mensagem` real devolvido
# pela API (quando existe) sempre acompanha, nunca substitui.
MENSAGENS_ERRO_COMPOSICAO = {
    "sem_chave": "OPENAI_API_KEY não configurada.",
    "sem_fotos": "Nenhuma foto de sujeito disponível para enviar à API.",
    "briefing_ausente": "O briefing exportável está vazio — gere-o antes de tentar a composição por IA.",
    "erro_rede": "Falha de rede ao chamar a API da OpenAI.",
    "resposta_sem_imagem": "A API não devolveu nenhuma imagem — possível recusa de moderação (deepfake/pessoa real identificável).",
    "falha_pos_processamento": "A imagem foi recebida mas não pôde ser salva em disco.",
}


def _persistir_status_composicao(output_path: Path, resultado: dict) -> None:
    """Grava um JSON sidecar (`composicao_status.json`, ao lado de
    `output_path`) com o resultado da ULTIMA tentativa de composicao
    completa por IA - sobrevive a um recarregamento de pagina. Nunca
    levanta excecao - falha ao gravar o status nao pode derrubar uma
    geracao que ja' deu certo (ou mascarar uma que falhou)."""
    corpo = dict(resultado)
    corpo["gerado_em"] = datetime.now().isoformat()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        (output_path.parent / NOME_ARQUIVO_STATUS_COMPOSICAO).write_text(
            json.dumps(corpo, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        logger.warning("imagem/openai._persistir_status_composicao: falha ao gravar status.", exc_info=True)


def ler_status_composicao(pasta_saida: Path) -> dict | None:
    """Le composicao_status.json de dentro de `pasta_saida` (o
    `output_path.parent` passado a `gerar_composicao`). None se o arquivo
    nao existe ou esta corrompido - nunca levanta excecao."""
    caminho = pasta_saida / NOME_ARQUIVO_STATUS_COMPOSICAO
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return dados if isinstance(dados, dict) else None


def _falha_composicao(output_path: Path, erro_tipo: str, erro_mensagem: str | None = None, status_http=None) -> dict:
    resultado = {
        "sucesso": False,
        "erro_tipo": erro_tipo,
        "erro_mensagem": erro_mensagem or MENSAGENS_ERRO_COMPOSICAO.get(erro_tipo, "Falha desconhecida."),
        "status_http": status_http,
    }
    _persistir_status_composicao(output_path, resultado)
    return resultado


def gerar_composicao(
    briefing_completo: str,
    caminhos_fotos,
    output_path,
    qualidade: str = QUALIDADE_COMPOSICAO_PADRAO,
) -> dict:
    """Composicao COMPLETA da thumbnail (sujeito(s) + fundo, tudo numa
    imagem so') via /v1/images/edits do gpt-image-2. Envia
    `briefing_completo` (scripts/thumbnail_briefing.py, ja' pronto em
    ingles) como prompt e `caminhos_fotos` (as fotos ORIGINAIS dos
    sujeitos, sem recorte nenhum) como imagens de referencia, NA ORDEM
    recebida (chamador manda hero primeiro, secondary depois - esta funcao
    nao reordena).

    **Nunca mexe na imagem devolvida pela API**: os bytes recebidos sao
    gravados exatamente como vieram, na resolucao pedida por
    TAMANHO_API_COMPOSICAO (1536x864, 16:9 exato) - sem crop, sem resize,
    sem padding, sem conversao de proporcao. Uma sessao anterior chegou a
    aplicar um crop de centro 3:2->16:9 aqui (pra' compensar pedir
    1536x1024/TAMANHO_API, o `size` do modo de FUNDO) - esse crop foi
    removido, mas o `size` pedido continuava 3:2, entao a imagem final
    saia em 3:2 mesmo sem nenhum crop. Correcao desta sessao: pedir
    TAMANHO_API_COMPOSICAO (16:9) direto da API elimina a necessidade de
    qualquer crop - a premissa de que gpt-image-2 so' aceita
    1024x1024/1024x1536/1536x1024 estava errada (valia pra' gpt-image-1);
    a API aceita `size` customizado. `INSTRUCAO_AREA_SEGURA_16_9` continua
    anexada ao prompt (ainda ajuda a composicao a deixar espaco pro
    texto), mas o nome ficou desatualizado - nao existe corte 16:9 nenhum,
    o canvas ja' nasce 16:9 - consumido direto pela tela de thumbnail/
    pagina de conclusao, que exibem a imagem na proporcao que ela vier.

    Nunca levanta excecao - toda falha (sem chave, sem fotos, rede, recusa
    de moderacao, resposta sem imagem, falha ao salvar) devolve
    um dict `{"sucesso": False, "erro_tipo", "erro_mensagem", "status_http"}`
    com o motivo REAL (nunca string generica) e persiste esse resultado em
    `composicao_status.json` ao lado de `output_path`, pra' sobreviver a um
    recarregamento de pagina. Sucesso devolve
    `{"sucesso": True, "caminho": str(output_path), "custo_usd_estimado", "modelo", "qualidade"}`."""
    caminhos_fotos = [Path(c) for c in (caminhos_fotos or []) if c]

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _falha_composicao(Path(output_path), "sem_chave")

    if not caminhos_fotos:
        return _falha_composicao(Path(output_path), "sem_fotos")

    briefing_completo = (briefing_completo or "").strip()
    if not briefing_completo:
        return _falha_composicao(Path(output_path), "briefing_ausente")

    # Anexado so' aqui, na chamada de API - nunca no briefing persistido
    # (thumbnail/metadados.json), que continua servindo intacto pro uso
    # manual (copiar/colar em outro gerador de imagem, onde o usuario
    # controla o enquadramento por fora e o corte 16:9 desta funcao nao
    # se aplica).
    prompt_api = f"{briefing_completo}\n\n{INSTRUCAO_AREA_SEGURA_16_9}"

    arquivos_multipart = []
    try:
        for caminho_foto in caminhos_fotos:
            mime = MIME_POR_EXTENSAO.get(caminho_foto.suffix.lower(), "application/octet-stream")
            arquivos_multipart.append(("image[]", (caminho_foto.name, caminho_foto.read_bytes(), mime)))
    except OSError as exc:
        return _falha_composicao(Path(output_path), "sem_fotos", erro_mensagem=f"Falha ao ler foto do sujeito: {exc}")

    try:
        resposta = requests.post(
            BASE_URL_EDITS,
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": MODEL_ID,
                "prompt": prompt_api,
                "size": TAMANHO_API_COMPOSICAO,
                "quality": qualidade,
                "n": 1,
            },
            files=arquivos_multipart,
            timeout=TIMEOUT_REQUEST_S,
        )
    except requests.RequestException as exc:
        logger.warning("imagem/openai.gerar_composicao: falha de rede.", exc_info=True)
        return _falha_composicao(Path(output_path), "erro_rede", erro_mensagem=str(exc))

    if resposta.status_code != 200:
        erro_api = {}
        try:
            erro_api = (resposta.json() or {}).get("error") or {}
        except ValueError:
            erro_api = {}
        erro_tipo = erro_api.get("code") or erro_api.get("type") or "erro_api"
        erro_mensagem = erro_api.get("message") or (resposta.text[:500] if hasattr(resposta, "text") else "")
        logger.warning(
            "imagem/openai.gerar_composicao: API recusou a composicao (status %s, tipo %s): %s",
            resposta.status_code, erro_tipo, erro_mensagem,
        )
        return _falha_composicao(Path(output_path), erro_tipo, erro_mensagem=erro_mensagem, status_http=resposta.status_code)

    try:
        dados = resposta.json() or {}
        item = (dados.get("data") or [None])[0]
        b64 = (item or {}).get("b64_json")
    except (ValueError, AttributeError, IndexError, TypeError):
        b64 = None

    if not b64:
        return _falha_composicao(Path(output_path), "resposta_sem_imagem", status_http=resposta.status_code)

    output_path = Path(output_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(b64))
    except Exception as exc:
        logger.warning("imagem/openai.gerar_composicao: falha ao salvar a imagem gerada.", exc_info=True)
        return _falha_composicao(output_path, "falha_pos_processamento", erro_mensagem=str(exc), status_http=resposta.status_code)

    custo = CUSTO_USD_ESTIMADO_POR_QUALIDADE.get(qualidade, 0.0)
    resultado = {
        "sucesso": True,
        "caminho": str(output_path),
        "custo_usd_estimado": custo,
        "modelo": MODEL_ID,
        "qualidade": qualidade,
        "num_fotos_enviadas": len(caminhos_fotos),
    }
    _persistir_status_composicao(output_path, resultado)
    caminho_custo = output_path.parent / f"{output_path.name}.custo.json"
    try:
        caminho_custo.write_text(
            json.dumps(
                {"modelo": MODEL_ID, "qualidade": qualidade, "modo": "composicao", "custo_usd_estimado": custo},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("imagem/openai.gerar_composicao: falha ao gravar log de custo.", exc_info=True)

    return resultado
