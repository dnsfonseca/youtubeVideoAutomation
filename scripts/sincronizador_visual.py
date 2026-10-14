"""Feature A (sincronizacao inteligente com IA, opt-in por projeto via
`entrada/configuracao_video.json:sincronizacao_ia_ativa`) - sincroniza
clipes de b-roll com ancoras visuais do roteiro via Vision seletivo.

Modulo importado DIRETAMENTE por server.py (mesmo padrao de
scripts/tools/youtube.py e scripts/prompts/loader.py - infra transversal,
nao um script numerado de pipeline rodado via subprocess), porque roda
dentro da MESMA thread de background que ja executa a Etapa 5 (CLAUDE.md
secao 4) logo apos ela terminar - nao precisa do isolamento de processo
que os scripts numerados tem, e reusar a thread evita reimplementar o
parsing de `@PROGRESSO` so' para este passo opcional.

Fluxo (no maximo 2 + N/5 chamadas de API, custo baixo por desenho):

1. `extrair_ancoras_do_roteiro` - 1 chamada de texto (tool_choice forcado)
   que le o roteiro (ou o trecho inicial, conforme a duracao escolhida) e
   devolve ate 15 ancoras visuais.
2. `descrever_clipes_via_vision` - N/5 chamadas de Vision (lotes de 5
   imagens), UMA VEZ por clipe candidato - gera uma descricao curta por
   clipe e guarda em cache (`clipes/descricoes_vision.json`). Reruns
   (retry manual) reusam o cache e so descrevem clipes novos.
3. `casar_ancoras_com_clipes` - 1 UNICA chamada de texto (tool_choice
   forcado) que recebe todas as ancoras + todas as descricoes ja prontas e
   devolve o melhor clipe candidato para cada ancora. So' texto (as
   imagens ja viraram descricao na etapa 2) - e' isso que mantem o custo
   praticamente constante em relacao ao numero de ancoras, escalando so
   com o numero de clipes candidatos (proporcional a duracao escolhida).

Desvio deliberado do desenho original discutido em sessao: ancoras nao
carregam `bloco_indice` (um numero de bloco que o modelo nunca viu de
verdade, porque o roteiro em markdown nao chega numerado). A posicao de
cada ancora na timeline e' calculada aqui (`localizar_posicao_ancoras`),
localizando `texto_original` dentro do roteiro aprovado e projetando a
fracao de caracteres sobre `narracao_alinhamento.json` (que ja existe
neste ponto do pipeline - a Etapa 4/audio roda antes da Etapa 5/clipes).
Mais preciso que pedir ao modelo para adivinhar um indice de bloco sem
numeracao visivel, e evita erro de fence-post na correspondencia
bloco->clipe. Aproximacao aceita: assume velocidade de fala aprox.
constante ao longo do roteiro (nao validado empiricamente contra desvio
real de cadencia).

Toda funcao que chama a API captura QUALQUER excecao e devolve um valor
"vazio" em vez de propagar - Feature A e' sempre opcional e nunca pode
derrubar o pipeline principal (mesmo espirito do tratamento de falha do
Veo3, CLAUDE.md secao 5.75: "nunca falhar o video inteiro por causa de
uma cena").
"""

import base64
import difflib
import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger(__name__)

MODELO_PADRAO = "claude-sonnet-5"
MAX_TOKENS_RESPOSTA = 4096
MAX_ANCORAS = 15
TAMANHO_LOTE_VISION = 5

# Limiares do fallback tolerante de localizacao (`_localizar_por_similaridade`,
# usado quando o casamento literal `str.find` falha - achado real de producao,
# projeto teste_srt_darkplanner: a extracao respondeu ancoras validas [custo
# cobrado] mas 0 bateram caractere-por-caractere com o roteiro, porque a IA
# raramente cita um trecho longo 100% literal mesmo quando instruida a
# copiar). As DUAS condicoes sao exigidas juntas - so' ratio alto sozinho
# deixaria passar falso positivo tipo "bicicleta" ~ "biscoito" (strings
# curtas, ratio enganosamente alto, nenhuma sequencia real de palavras em
# comum).
LIMIAR_SIMILARIDADE_RATIO = 0.85
MIN_PALAVRAS_CONSECUTIVAS_MATCH = 3
DIMENSAO_FRAME_THUMB = "160:90"

# Precos por milhao de tokens do Sonnet - duplicado de
# scripts/3_gerar_roteiro.py:CUSTO_INPUT_POR_MILHAO_USD/
# CUSTO_OUTPUT_POR_MILHAO_USD de proposito (CLAUDE.md secao 9 - scripts
# autocontidos, sem utils compartilhado entre scripts/server.py). Usado para
# estimar o custo real da Feature A (sincronizacao com IA) a partir de
# `usage` das respostas da API - o modulo nao rastreava custo nenhum antes
# desta sessao de correcoes UX.
CUSTO_INPUT_POR_MILHAO_USD = 3.0
CUSTO_OUTPUT_POR_MILHAO_USD = 15.0
TIMEOUT_FFMPEG_S = 20

_PROMPT_ANCORAS_PATH = Path(__file__).resolve().parent / "prompts" / "extrair_ancoras.md"

NOME_TOOL_ANCORAS = "entregar_ancoras"
SCHEMA_ANCORAS = {
    "name": NOME_TOOL_ANCORAS,
    "description": "Entrega a lista de ancoras visuais extraidas do roteiro.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ancoras": {
                "type": "array",
                "maxItems": MAX_ANCORAS,
                "items": {
                    "type": "object",
                    "properties": {
                        "texto_original": {
                            "type": "string",
                            "description": "Trecho EXATO (copiado literalmente) do roteiro onde a ancora aparece.",
                        },
                        "termo_ancora": {
                            "type": "string",
                            "description": "Descricao visual curta e concreta (em ingles) do b-roll ideal.",
                        },
                        "prioridade": {"type": "string", "enum": ["alta", "media"]},
                    },
                    "required": ["texto_original", "termo_ancora", "prioridade"],
                },
            }
        },
        "required": ["ancoras"],
    },
}

NOME_TOOL_DESCRICOES = "entregar_descricoes"
SCHEMA_DESCRICOES = {
    "name": NOME_TOOL_DESCRICOES,
    "description": "Entrega uma descricao visual curta para cada clipe (imagem) do lote.",
    "input_schema": {
        "type": "object",
        "properties": {
            "descricoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "clipe_id": {"type": "string"},
                        "descricao_visual": {
                            "type": "string",
                            "description": "Poucas palavras, em ingles (ex: 'person riding bicycle on dirt path').",
                        },
                    },
                    "required": ["clipe_id", "descricao_visual"],
                },
            }
        },
        "required": ["descricoes"],
    },
}

NOME_TOOL_MATCHES = "entregar_matches"
SCHEMA_MATCHES = {
    "name": NOME_TOOL_MATCHES,
    "description": (
        "Para cada ancora, entrega o clipe candidato do banco que melhor a representa "
        "(ou vazio, se nada combinar bem)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ancora_termo": {"type": "string"},
                        "clipe_id_candidato": {
                            "type": "string",
                            "description": "clipe_id do banco, ou string vazia se nenhum combina bem.",
                        },
                        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                    },
                    "required": ["ancora_termo", "clipe_id_candidato", "confianca"],
                },
            }
        },
        "required": ["matches"],
    },
}


def _valor(obj, chave, default=None):
    """Le `chave` de `obj` seja ele um dict (fakes de teste) ou um objeto
    com atributos (respostas reais do SDK anthropic) - duplicado de
    scripts/3_gerar_roteiro.py de proposito (CLAUDE.md secao 9)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(chave, default)
    return getattr(obj, chave, default)


def _extrair_tool_use(resposta, nome_tool):
    for bloco in _valor(resposta, "content", []) or []:
        if _valor(bloco, "type") == "tool_use" and _valor(bloco, "name") == nome_tool:
            return _valor(bloco, "input")
    return None


def _custo_usd_da_resposta(resposta) -> float:
    """Estima o custo em USD de uma chamada `messages.create` a partir do
    `usage` da resposta (`input_tokens`/`output_tokens`) - devolve 0.0 se a
    resposta nao tiver `usage` (fakes de teste, que so' tem `content`) ou o
    `usage` vier incompleto. Nunca levanta excecao."""
    usage = _valor(resposta, "usage")
    if usage is None:
        return 0.0
    tokens_input = _valor(usage, "input_tokens") or 0
    tokens_output = _valor(usage, "output_tokens") or 0
    return (
        (tokens_input / 1_000_000) * CUSTO_INPUT_POR_MILHAO_USD
        + (tokens_output / 1_000_000) * CUSTO_OUTPUT_POR_MILHAO_USD
    )


def _obter_cliente(api_key, cliente):
    if cliente is not None:
        return cliente
    if anthropic is None or not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# 1. Extracao de ancoras
# ---------------------------------------------------------------------------


def _recortar_roteiro_por_duracao(roteiro_texto: str, duracao_alvo_s: float, duracao_total_s: float) -> str:
    """Recorta `roteiro_texto` proporcionalmente a fracao de narracao que
    `duracao_alvo_s` representa sobre `duracao_total_s` (0/None ou >= total
    = roteiro inteiro). Corta no proximo espaco apos o ponto proporcional,
    nunca no meio de uma palavra."""
    if not duracao_alvo_s or duracao_alvo_s <= 0 or not duracao_total_s or duracao_alvo_s >= duracao_total_s:
        return roteiro_texto
    fracao = min(1.0, duracao_alvo_s / duracao_total_s)
    corte_aproximado = int(len(roteiro_texto) * fracao)
    proximo_espaco = roteiro_texto.find(" ", corte_aproximado)
    corte = proximo_espaco if proximo_espaco != -1 else len(roteiro_texto)
    return roteiro_texto[:corte]


def extrair_ancoras_do_roteiro(
    roteiro_texto: str,
    duracao_alvo_s: float,
    duracao_total_s: float,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> list:
    """Extrai ancoras visuais dos primeiros `duracao_alvo_s` segundos de
    narracao do roteiro (0/None = roteiro inteiro). Retorna lista de dicts
    `{"texto_original", "termo_ancora", "prioridade"}` - lista vazia se o
    roteiro estiver vazio, a lib `anthropic` nao estiver instalada, ou a
    chamada falhar/devolver algo inesperado (nunca levanta excecao).

    `cliente`: injecao de dependencia para teste (fake com
    `.messages.create`) - None (default) instancia um `anthropic.Anthropic`
    real com `api_key`.

    `_custos`: lista mutavel opcional onde o custo USD desta chamada e'
    acumulado (side-channel usado por `sincronizar_projeto` para somar o
    custo total da Feature A sem mudar o tipo de retorno desta funcao -
    parametro interno, prefixo `_` de proposito)."""
    if not roteiro_texto or not roteiro_texto.strip():
        return []

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return []

    trecho = _recortar_roteiro_por_duracao(roteiro_texto, duracao_alvo_s, duracao_total_s)
    prompt_sistema = _PROMPT_ANCORAS_PATH.read_text(encoding="utf-8")
    janela_descricao = "o roteiro inteiro" if not duracao_alvo_s or duracao_alvo_s <= 0 else f"~{int(duracao_alvo_s)}s iniciais de narracao"
    prompt_usuario = f"Roteiro analisado ({janela_descricao}):\n\n{trecho}"
    logger.info(
        "Extrator de ancoras: texto enviado ao Claude tem %d chars, cobre %s.",
        len(trecho),
        janela_descricao,
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_RESPOSTA,
            system=prompt_sistema,
            messages=[{"role": "user", "content": prompt_usuario}],
            tools=[SCHEMA_ANCORAS],
            tool_choice={"type": "tool", "name": NOME_TOOL_ANCORAS},
        )
    except Exception:
        logger.warning("Extrator de ancoras: chamada a API falhou.", exc_info=True)
        return []

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_ANCORAS)
    if not isinstance(dados, dict):
        logger.info("Extrator de ancoras: resposta da API nao trouxe tool_use valido.")
        return []
    ancoras = dados.get("ancoras")
    if isinstance(ancoras, str):
        # Achado real de producao (projeto teste_srt_darkplanner): o modelo,
        # apesar do `tool_choice` forcado com schema tipado (`ancoras` como
        # array), ocasionalmente devolve o campo como uma STRING contendo o
        # JSON inteiro serializado de novo por dentro - as vezes so' o array
        # (`"[...]"`), as vezes o objeto todo re-aninhado
        # (`"{\"ancoras\": [...]}"`). Sem esse fallback, o `isinstance(...,
        # list)` abaixo falha e a extracao inteira e' descartada mesmo com a
        # IA tendo retornado ancoras validas (silencioso: nenhuma excecao,
        # nenhum erro, so' 0 ancoras - e' exatamente o que gerou o achado de
        # "custo cobrado, 0 ancoras" que abriu esta correcao).
        try:
            ancoras_reparsed = json.loads(ancoras)
        except (json.JSONDecodeError, TypeError):
            ancoras_reparsed = None
        if isinstance(ancoras_reparsed, dict):
            ancoras = ancoras_reparsed.get("ancoras")
        elif isinstance(ancoras_reparsed, list):
            ancoras = ancoras_reparsed
        else:
            ancoras = None
        if ancoras is not None:
            logger.info("Extrator de ancoras: campo 'ancoras' veio como string JSON aninhada - reparseado.")
    if not isinstance(ancoras, list):
        logger.info("Extrator de ancoras: campo 'ancoras' ausente ou nao e' lista (mesmo apos tentar reparsear).")
        return []
    logger.info("Extrator de ancoras: Claude retornou %d ancora(s) raw.", len(ancoras))

    validas = []
    for ancora in ancoras[:MAX_ANCORAS]:
        if not isinstance(ancora, dict):
            continue
        texto_original = (ancora.get("texto_original") or "").strip()
        termo_ancora = (ancora.get("termo_ancora") or "").strip()
        if not texto_original or not termo_ancora:
            continue
        prioridade = ancora.get("prioridade") if ancora.get("prioridade") in ("alta", "media") else "media"
        validas.append({"texto_original": texto_original, "termo_ancora": termo_ancora, "prioridade": prioridade})
    logger.info("Extrator de ancoras: %d ancora(s) validas apos filtro de campos obrigatorios.", len(validas))
    return validas


_PADRAO_TOKEN = re.compile(r"\S+")


def _tokenizar_com_offsets(texto: str) -> list:
    """Lista de `(token_minusculo, offset_char_inicio)` para cada sequencia
    de nao-espaco em `texto` - a mesma nocao de "palavra" que o fallback de
    6-palavras ja usava (split por espaco), so' guardando o offset de cada
    token para `_localizar_por_similaridade` poder devolver uma posicao de
    caractere igual ao `str.find` literal."""
    return [(m.group(0).lower(), m.start()) for m in _PADRAO_TOKEN.finditer(texto)]


def _localizar_por_similaridade(texto_original: str, tokens_roteiro: list) -> int | None:
    """Fallback tolerante para quando o casamento literal (`str.find`, com ou
    sem o corte nas 6 primeiras palavras) falha - achado real de producao
    (projeto teste_srt_darkplanner): a IA raramente cita um trecho longo
    100% literal mesmo instruida a "copiar caractere por caractere"
    (paráfrase leve, pontuação, espaçamento), então exigir bit-a-bit descarta
    ancoras validas em silencio.

    Usa `difflib.SequenceMatcher` em nivel de PALAVRA (nao de caractere)
    entre todos os tokens do roteiro e os tokens da ancora, pega o maior
    bloco CONTIGUO de tokens iguais, e so aceita como match se as DUAS
    condicoes valerem:
    1. Esse bloco tem pelo menos `MIN_PALAVRAS_CONSECUTIVAS_MATCH` palavras
       consecutivas iguais.
    2. A similaridade (`ratio()`) entre os tokens da ancora e a janela do
       roteiro de mesmo tamanho a partir do inicio do bloco e' >=
       `LIMIAR_SIMILARIDADE_RATIO`.

    As duas juntas evitam falso positivo tipo "bicicleta" casando com
    "biscoito" (ratio enganosamente alto em strings curtas isoladas, mas
    nenhuma sequencia real de palavras em comum) sem exigir match perfeito
    (que e' exatamente o que falha na pratica). Retorna o offset de
    caractere onde o bloco comeca no roteiro, ou None se nada bateu o
    suficiente."""
    tokens_ancora = [tok for tok, _offset in _tokenizar_com_offsets(texto_original)]
    if len(tokens_ancora) < MIN_PALAVRAS_CONSECUTIVAS_MATCH:
        return None

    tokens_roteiro_texto = [tok for tok, _offset in tokens_roteiro]
    matcher = difflib.SequenceMatcher(None, tokens_roteiro_texto, tokens_ancora, autojunk=False)
    bloco = matcher.find_longest_match(0, len(tokens_roteiro_texto), 0, len(tokens_ancora))
    if bloco.size < MIN_PALAVRAS_CONSECUTIVAS_MATCH:
        return None

    # `bloco.a` e' onde o bloco casado COMECA no roteiro, mas `bloco.b` pode
    # ser > 0 se os primeiros tokens da ancora nao fizeram parte do bloco
    # contiguo (ex: erro de digitacao no 1o token) - sem corrigir por esse
    # deslocamento, a janela de comparacao fica desalinhada (comeca tarde
    # demais e "vaza" pra dentro do texto seguinte no roteiro), inflando
    # diferenca artificial e derrubando o ratio de matches legitimos.
    inicio_janela = max(0, bloco.a - bloco.b)
    fim_janela = min(len(tokens_roteiro_texto), inicio_janela + len(tokens_ancora))
    janela_roteiro = " ".join(tokens_roteiro_texto[inicio_janela:fim_janela])
    ratio = difflib.SequenceMatcher(None, janela_roteiro, " ".join(tokens_ancora)).ratio()
    if ratio < LIMIAR_SIMILARIDADE_RATIO:
        return None

    return tokens_roteiro[inicio_janela][1]


def localizar_posicao_ancoras(ancoras: list, roteiro_texto: str, palavras_alinhadas: list) -> list:
    """Para cada ancora, localiza `texto_original` dentro de `roteiro_texto`
    - busca literal primeiro (texto inteiro, depois so as 6 primeiras
    palavras), e se as duas falharem, cai para `_localizar_por_similaridade`
    (casamento tolerante por palavra, ver docstring la) - e projeta a fracao
    de caracteres sobre `palavras_alinhadas` (schema de
    narracao_alinhamento.json: lista de `{"palavra","inicio_s","fim_s"}`)
    para estimar `posicao_s`, o instante da narracao em que a ancora
    deveria aparecer.

    Ancoras nao localizadas (nem por match literal nem por similaridade) sao
    descartadas - logadas em vez de silenciosas (achado real de producao:
    custo de API pago sem nenhuma ancora aproveitada, sem nenhum log
    explicando o motivo). Retorna lista de `{**ancora, "posicao_s": float}`."""
    if not ancoras or not palavras_alinhadas or not roteiro_texto:
        return []
    total_chars = len(roteiro_texto)
    if total_chars == 0:
        return []

    tokens_roteiro = _tokenizar_com_offsets(roteiro_texto)

    localizadas = []
    descartadas = 0
    for ancora in ancoras:
        texto_original = ancora.get("texto_original", "")
        offset = roteiro_texto.find(texto_original)
        if offset == -1:
            primeiras_palavras = " ".join(texto_original.split()[:6])
            offset = roteiro_texto.find(primeiras_palavras) if primeiras_palavras else -1
        if offset == -1:
            offset_similaridade = _localizar_por_similaridade(texto_original, tokens_roteiro)
            offset = offset_similaridade if offset_similaridade is not None else -1
        if offset == -1:
            descartadas += 1
            continue

        fracao = offset / total_chars
        indice_palavra = min(int(fracao * len(palavras_alinhadas)), len(palavras_alinhadas) - 1)
        posicao_s = palavras_alinhadas[indice_palavra].get("inicio_s", 0.0) or 0.0
        localizadas.append({**ancora, "posicao_s": float(posicao_s)})
    logger.info(
        "Extrator de ancoras: apos localizacao (literal + similaridade), restaram %d de %d ancora(s) (%d descartada(s)).",
        len(localizadas),
        len(ancoras),
        descartadas,
    )
    return localizadas


# ---------------------------------------------------------------------------
# 2. Selecao de candidatos e descricao via Vision
# ---------------------------------------------------------------------------


def selecionar_clipes_candidatos(clipes: list, duracao_alvo_s: float) -> list:
    """Subconjunto de `clipes` (lista do indice.json, na ordem da timeline)
    cuja posicao cai dentro da janela analisada (primeiros `duracao_alvo_s`
    segundos de narracao) - e' o unico trecho onde ancoras podem existir,
    entao e' o unico trecho que vale a pena descrever via Vision (mantem o
    custo proporcional a janela escolhida, nao ao video inteiro). 0/None =
    video inteiro (todos os clipes sao candidatos)."""
    if not duracao_alvo_s or duracao_alvo_s <= 0:
        return list(clipes)
    candidatos = []
    acumulado = 0.0
    for clipe in clipes:
        if acumulado >= duracao_alvo_s:
            break
        candidatos.append(clipe)
        acumulado += clipe.get("duracao_s", 0.0) or 0.0
    return candidatos


def _ler_cache_descricoes(pasta_projeto: Path) -> dict:
    caminho = pasta_projeto / "clipes" / "descricoes_vision.json"
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _salvar_cache_descricoes(pasta_projeto: Path, descricoes: dict) -> None:
    caminho = pasta_projeto / "clipes" / "descricoes_vision.json"
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(descricoes, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def extrair_frame_clipe(caminho_clipe: Path, caminho_saida_jpg: Path) -> bool:
    """Extrai um frame do meio-inicio do clipe, reduzido, como JPG - usado
    tanto pela descricao via Vision quanto (mesmo arquivo, reaproveitado)
    como thumbnail da tela de reorganizacao manual (Feature B). Nunca
    levanta excecao."""
    try:
        caminho_saida_jpg.parent.mkdir(parents=True, exist_ok=True)
        resultado = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-y",
                "-i", str(caminho_clipe),
                "-ss", "0.5",
                "-vframes", "1",
                "-vf", f"scale={DIMENSAO_FRAME_THUMB}",
                str(caminho_saida_jpg),
            ],
            capture_output=True,
            timeout=TIMEOUT_FFMPEG_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return resultado.returncode == 0 and caminho_saida_jpg.exists()


def descrever_clipes_via_vision(
    clipes_candidatos: list,
    pasta_projeto: Path,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> dict:
    """Gera (ou reusa do cache) uma descricao visual curta por clipe
    candidato. Extrai um frame de cada clipe ainda nao descrito, agrupa em
    lotes de `TAMANHO_LOTE_VISION` e faz uma chamada Vision por lote.

    Cache em `clipes/descricoes_vision.json` (chave `clipe_id`) - reruns
    (retry manual da sincronizacao) NUNCA re-descrevem um clipe ja
    descrito, mesmo que a janela de duracao mude entre tentativas (CLAUDE.md
    - "preservar cache Vision"). Retorna `{clipe_id: descricao}` - inclui o
    cache previo mesmo se nenhum clipe novo puder ser descrito agora."""
    descricoes = _ler_cache_descricoes(pasta_projeto)
    pendentes = [c for c in clipes_candidatos if c.get("clipe_id") not in descricoes]
    if not pendentes:
        return descricoes

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return descricoes

    pasta_thumbs = pasta_projeto / "clipes" / "thumbs"
    pasta_clipes = pasta_projeto / "clipes"

    for inicio in range(0, len(pendentes), TAMANHO_LOTE_VISION):
        lote = pendentes[inicio:inicio + TAMANHO_LOTE_VISION]
        blocos_conteudo = []
        clipe_ids_lote = []
        for clipe in lote:
            clipe_id = clipe.get("clipe_id")
            if not clipe_id:
                continue
            caminho_frame = pasta_thumbs / f"{clipe_id}.jpg"
            if not caminho_frame.exists():
                caminho_clipe = pasta_clipes / clipe.get("arquivo", "")
                if not extrair_frame_clipe(caminho_clipe, caminho_frame):
                    continue
            try:
                frame_b64 = base64.b64encode(caminho_frame.read_bytes()).decode("ascii")
            except OSError:
                continue
            clipe_ids_lote.append(clipe_id)
            blocos_conteudo.append({"type": "text", "text": f"Clipe {clipe_id}:"})
            blocos_conteudo.append(
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": frame_b64}}
            )

        if not blocos_conteudo:
            continue

        blocos_conteudo.append(
            {
                "type": "text",
                "text": "Descreva o conteudo visual de cada clipe acima em poucas palavras (em ingles).",
            }
        )

        try:
            resposta = cliente_api.messages.create(
                model=modelo,
                max_tokens=MAX_TOKENS_RESPOSTA,
                messages=[{"role": "user", "content": blocos_conteudo}],
                tools=[SCHEMA_DESCRICOES],
                tool_choice={"type": "tool", "name": NOME_TOOL_DESCRICOES},
            )
        except Exception:
            continue

        if _custos is not None:
            _custos.append(_custo_usd_da_resposta(resposta))

        dados = _extrair_tool_use(resposta, NOME_TOOL_DESCRICOES)
        if not isinstance(dados, dict):
            continue
        for item in dados.get("descricoes") or []:
            if not isinstance(item, dict):
                continue
            clipe_id = item.get("clipe_id")
            descricao = (item.get("descricao_visual") or "").strip()
            if clipe_id in clipe_ids_lote and descricao:
                descricoes[clipe_id] = descricao

        _salvar_cache_descricoes(pasta_projeto, descricoes)

    return descricoes


# ---------------------------------------------------------------------------
# 3. Casamento ancora <-> clipe e aplicacao dos swaps
# ---------------------------------------------------------------------------


def casar_ancoras_com_clipes(
    ancoras_localizadas: list,
    descricoes: dict,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> list:
    """Uma UNICA chamada de texto (tool_choice forcado) que recebe todas as
    ancoras + todas as descricoes de clipe ja prontas e devolve o melhor
    candidato para cada ancora - so texto (as imagens ja viraram descricao
    em `descrever_clipes_via_vision`), o que mantem o custo praticamente
    constante em relacao ao numero de ancoras.

    Retorna lista de `{"ancora_termo", "clipe_id_candidato", "confianca"}` -
    so os matches com `confianca` "alta"/"media" e `clipe_id_candidato`
    presente no dict `descricoes` (defesa contra alucinacao de id
    inexistente); lista vazia se nao houver ancoras/descricoes ou a
    chamada falhar."""
    if not ancoras_localizadas or not descricoes:
        return []

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return []

    prompt_usuario = (
        "Ancoras visuais extraidas do roteiro (cada uma precisa do melhor "
        "clipe candidato do banco abaixo):\n"
        + json.dumps(
            [{"termo_ancora": a["termo_ancora"], "prioridade": a["prioridade"]} for a in ancoras_localizadas],
            ensure_ascii=False,
        )
        + "\n\nBanco de clipes disponiveis (clipe_id: descricao visual):\n"
        + json.dumps(descricoes, ensure_ascii=False)
        + "\n\nPara cada ancora, escolha o clipe_id do banco que melhor a "
        "representa. Se nenhum clipe combinar razoavelmente, deixe "
        "clipe_id_candidato vazio e confianca 'baixa'. Nunca repita o mesmo "
        "clipe_id para ancoras diferentes - escolha o segundo melhor se o "
        "melhor ja foi usado por uma ancora de prioridade mais alta."
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_RESPOSTA,
            messages=[{"role": "user", "content": prompt_usuario}],
            tools=[SCHEMA_MATCHES],
            tool_choice={"type": "tool", "name": NOME_TOOL_MATCHES},
        )
    except Exception:
        return []

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_MATCHES)
    if not isinstance(dados, dict):
        return []
    matches = dados.get("matches")
    if not isinstance(matches, list):
        return []

    validos = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        ancora_termo = (item.get("ancora_termo") or "").strip()
        clipe_id = (item.get("clipe_id_candidato") or "").strip()
        confianca = item.get("confianca") if item.get("confianca") in ("alta", "media", "baixa") else "baixa"
        if not ancora_termo or not clipe_id or confianca == "baixa":
            continue
        if clipe_id not in descricoes:
            continue
        validos.append({"ancora_termo": ancora_termo, "clipe_id_candidato": clipe_id, "confianca": confianca})
    return validos


def _posicao_para_indice_clipe(posicao_s: float, clipes: list):
    """Indice (na lista `clipes`, na ordem da timeline) do clipe que cobre
    o instante `posicao_s` da narracao - soma cumulativa de `duracao_s`.
    Clampa no ultimo clipe se `posicao_s` exceder a duracao total. Lista
    vazia -> None."""
    if not clipes:
        return None
    acumulado = 0.0
    for indice, clipe in enumerate(clipes):
        acumulado += clipe.get("duracao_s", 0.0) or 0.0
        if posicao_s < acumulado:
            return indice
    return len(clipes) - 1


def aplicar_swaps_automaticos(matches: list, ancoras_localizadas: list, indice_clipes: list) -> list:
    """Aplica os swaps de posicao (bloco_destino <-> posicao_atual_do_
    candidato) para as ancoras com match aceito, MUTANDO `indice_clipes`
    (lista de dicts do indice.json, na ordem da timeline) in-place.
    Preserva o total de clipes - so' reordena.

    Prioriza ancoras "alta" antes de "media" quando dois matches disputam o
    mesmo bloco de destino ou o mesmo clipe candidato - o de prioridade
    mais alta vence, o outro e' descartado silenciosamente.

    Retorna o log de swaps aplicados: lista de
    `{"ancora_termo", "clipe_id", "bloco_origem", "bloco_destino", "confianca"}`."""
    if not matches or not ancoras_localizadas or not indice_clipes:
        return []

    posicao_por_ancora = {a["termo_ancora"]: a["posicao_s"] for a in ancoras_localizadas}
    prioridade_por_ancora = {a["termo_ancora"]: a["prioridade"] for a in ancoras_localizadas}
    confianca_por_ancora = {m["ancora_termo"]: m.get("confianca") for m in matches}

    matches_ordenados = sorted(
        matches, key=lambda m: 0 if prioridade_por_ancora.get(m["ancora_termo"]) == "alta" else 1
    )

    indice_por_clipe_id = {clipe.get("clipe_id"): i for i, clipe in enumerate(indice_clipes)}

    blocos_destino_usados = set()
    clipes_ja_movidos = set()
    log_swaps = []

    for match in matches_ordenados:
        ancora_termo = match["ancora_termo"]
        clipe_id = match["clipe_id_candidato"]
        posicao_s = posicao_por_ancora.get(ancora_termo)
        if posicao_s is None:
            continue

        bloco_destino = _posicao_para_indice_clipe(posicao_s, indice_clipes)
        if bloco_destino is None or bloco_destino in blocos_destino_usados:
            continue

        bloco_origem = indice_por_clipe_id.get(clipe_id)
        if bloco_origem is None or clipe_id in clipes_ja_movidos:
            continue
        if bloco_origem == bloco_destino:
            continue

        indice_clipes[bloco_origem], indice_clipes[bloco_destino] = (
            indice_clipes[bloco_destino],
            indice_clipes[bloco_origem],
        )
        # O clipe que ANTES estava em bloco_destino agora esta em
        # bloco_origem - o mapa precisa refletir os DOIS lados da troca.
        indice_por_clipe_id[clipe_id] = bloco_destino
        indice_por_clipe_id[indice_clipes[bloco_origem].get("clipe_id")] = bloco_origem

        blocos_destino_usados.add(bloco_destino)
        clipes_ja_movidos.add(clipe_id)
        log_swaps.append(
            {
                "ancora_termo": ancora_termo,
                "clipe_id": clipe_id,
                "bloco_origem": bloco_origem,
                "bloco_destino": bloco_destino,
                "confianca": confianca_por_ancora.get(ancora_termo),
            }
        )

    return log_swaps


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------


def _enriquecer_log_swaps(log_swaps: list, ancoras_localizadas: list, descricoes: dict) -> list:
    """Junta `log_swaps` (so' ids/indices) com os dados que a UI de
    reorganizacao manual precisa mostrar (GRUPO B da sessao de correcoes UX
    - antes desta sessao, o resultado da Feature A nunca aparecia em lugar
    nenhum alem de uma linha de resumo no log efemero do job): texto_original
    e prioridade da ancora (via `termo_ancora`), descricao visual do clipe
    escolhido (via `clipe_id`). Nunca levanta excecao - swap sem
    correspondencia (nao deveria acontecer, mas os dicts de entrada nao tem
    garantia de integridade referencial) fica com os campos extras em
    branco."""
    ancora_por_termo = {a["termo_ancora"]: a for a in ancoras_localizadas}
    enriquecidos = []
    for swap in log_swaps:
        ancora = ancora_por_termo.get(swap["ancora_termo"], {})
        enriquecidos.append(
            {
                **swap,
                "texto_original": ancora.get("texto_original", ""),
                "prioridade": ancora.get("prioridade", ""),
                "posicao_s": ancora.get("posicao_s"),
                "descricao_visual": descricoes.get(swap["clipe_id"], ""),
            }
        )
    return enriquecidos


def _salvar_log_sincronizacao(pasta_projeto: Path, log: dict) -> None:
    """Persiste o resultado da Feature A em clipes/sincronizacao_vision_log.json
    para a tela de reorganizacao manual (Feature B) poder mostrar o que a IA
    fez - antes desta sessao o resultado so' existia em `job["log"]` (em
    memoria, some no restart do servidor) como uma linha de resumo. Nunca
    levanta excecao (mesmo espirito de `_salvar_cache_descricoes`)."""
    caminho = pasta_projeto / "clipes" / "sincronizacao_vision_log.json"
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def sincronizar_projeto(
    pasta_projeto: Path,
    api_key: str,
    duracao_alvo_s: float,
    modelo: str = MODELO_PADRAO,
    cliente=None,
) -> dict:
    """Orquestra o fluxo completo da Feature A para um projeto: extrai
    ancoras, localiza suas posicoes na narracao, descreve os clipes
    candidatos via Vision, casa ancoras com clipes e aplica os swaps
    resultantes em `clipes/indice.json` (gravado de volta so' se algum
    swap foi aplicado). Tambem grava `clipes/sincronizacao_vision_log.json`
    (GRUPO B - custo real e detalhe dos swaps, para a tela de reorganizacao
    manual exibir) sempre que a sincronizacao chegou a rodar pelo menos uma
    chamada de API.

    Nunca levanta excecao - qualquer falha (arquivo de entrada ausente,
    chamada de API com erro) e' capturada e devolvida em `erro`, sem
    interromper o chamador (server.py sempre segue para a Etapa 6 ou para
    a pausa de reorganizacao manual, independente do resultado desta
    funcao - Feature A e' estritamente aditiva).

    Retorna `{"sucesso", "swaps_aplicados", "ancoras_encontradas",
    "clipes_descritos", "log_swaps", "custo_usd_total", "erro"}`."""
    resultado = {
        "sucesso": False,
        "swaps_aplicados": 0,
        "ancoras_encontradas": 0,
        "clipes_descritos": 0,
        "log_swaps": [],
        "custo_usd_total": 0.0,
        "erro": None,
    }

    caminho_roteiro = pasta_projeto / "roteiro_aprovado.md"
    caminho_alinhamento = pasta_projeto / "narracao_alinhamento.json"
    caminho_indice = pasta_projeto / "clipes" / "indice.json"

    if not caminho_roteiro.exists() or not caminho_alinhamento.exists() or not caminho_indice.exists():
        resultado["erro"] = "Arquivos de entrada da sincronizacao ausentes (roteiro/alinhamento/indice)."
        return resultado

    try:
        roteiro_texto = caminho_roteiro.read_text(encoding="utf-8")
        alinhamento = json.loads(caminho_alinhamento.read_text(encoding="utf-8"))
        indice_json = json.loads(caminho_indice.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        resultado["erro"] = f"Falha ao ler arquivos de entrada: {exc}"
        return resultado

    palavras_alinhadas = alinhamento.get("palavras") or []
    clipes = indice_json.get("clipes") or []
    if not palavras_alinhadas or not clipes:
        resultado["erro"] = "Alinhamento ou indice de clipes vazio."
        return resultado

    duracao_total_s = palavras_alinhadas[-1].get("fim_s", 0.0) or 0.0
    custos = []

    ancoras = extrair_ancoras_do_roteiro(
        roteiro_texto, duracao_alvo_s, duracao_total_s, api_key, modelo, cliente, _custos=custos
    )
    ancoras_localizadas = localizar_posicao_ancoras(ancoras, roteiro_texto, palavras_alinhadas)
    resultado["ancoras_encontradas"] = len(ancoras_localizadas)
    if not ancoras_localizadas:
        resultado["sucesso"] = True
        resultado["custo_usd_total"] = round(sum(custos), 6)
        _salvar_log_sincronizacao(pasta_projeto, _montar_log_sincronizacao(resultado, duracao_alvo_s))
        return resultado

    candidatos = selecionar_clipes_candidatos(clipes, duracao_alvo_s)
    descricoes = descrever_clipes_via_vision(candidatos, pasta_projeto, api_key, modelo, cliente, _custos=custos)
    resultado["clipes_descritos"] = len(descricoes)
    if not descricoes:
        resultado["sucesso"] = True
        resultado["custo_usd_total"] = round(sum(custos), 6)
        _salvar_log_sincronizacao(pasta_projeto, _montar_log_sincronizacao(resultado, duracao_alvo_s))
        return resultado

    matches = casar_ancoras_com_clipes(ancoras_localizadas, descricoes, api_key, modelo, cliente, _custos=custos)
    log_swaps = aplicar_swaps_automaticos(matches, ancoras_localizadas, clipes)

    if log_swaps:
        indice_json["clipes"] = clipes
        metadata = indice_json.setdefault("metadata", {})
        metadata["sincronizacao_ia"] = {
            "ancoras_encontradas": len(ancoras_localizadas),
            "clipes_descritos": len(descricoes),
            "swaps_aplicados": len(log_swaps),
        }
        try:
            caminho_indice.write_text(json.dumps(indice_json, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            resultado["erro"] = f"Swaps calculados mas falha ao gravar indice.json: {exc}"
            return resultado

    resultado["sucesso"] = True
    resultado["swaps_aplicados"] = len(log_swaps)
    resultado["log_swaps"] = _enriquecer_log_swaps(log_swaps, ancoras_localizadas, descricoes)
    resultado["custo_usd_total"] = round(sum(custos), 6)
    _salvar_log_sincronizacao(pasta_projeto, _montar_log_sincronizacao(resultado, duracao_alvo_s))
    return resultado


def _montar_log_sincronizacao(resultado: dict, duracao_alvo_s: float) -> dict:
    """Formato gravado em clipes/sincronizacao_vision_log.json - subconjunto
    de `resultado` (sem `erro`, que so' importa para quem chamou
    diretamente) mais timestamp e a duracao_alvo_s configurada."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duracao_alvo_s": duracao_alvo_s,
        "ancoras_encontradas": resultado["ancoras_encontradas"],
        "clipes_descritos": resultado["clipes_descritos"],
        "swaps_aplicados": resultado["log_swaps"],
        "custo_usd_total": resultado["custo_usd_total"],
    }
