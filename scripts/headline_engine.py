"""Headline Engine v2 - substitui a geracao do `headline` da thumbnail
(que ate' a v1 saia na MESMA chamada de `entregar_metadados`, junto de
titulo/descricao/tags/subject_name - CLAUDE.md, scripts/7_thumbnail.py
Grupo D). Modulo separado, importado direto (infra transversal chamada
por scripts/7_thumbnail.py, nao um script numerado do pipeline batch).

DIAGNOSTICO QUE MOTIVOU A v2 (caso real, projeto jonBenetRamsey01/Burke
Ramsey): a v1 perguntava "qual headline descreve melhor o conteudo" -
mesmo com few-shot contrastivo evitando o fato mais saliente, os 6
candidatos gerados pra' esse caso convergiram em 4 reformulacoes da MESMA
ideia ("a CBS ocultou o teste de DNA de 1999") e so' 2 angulos
genuinamente distintos. A pergunta certa e' outra: "qual elemento pode
ser PARCIALMENTE revelado pra' criar a maior curiosidade restante" - nem
sempre e' o mesmo tipo de elemento (as vezes e' consequencia, as vezes
numero, objeto, contradicao ou evidencia) e quase nunca e' a conclusao
central do video (revelar a conclusao, mesmo em parte, fecha a
curiosidade antes do clique - achado real: o usuario trocou manualmente
o vencedor automatico "WHAT $750 MILLION BOUGHT" [lacuna preservada] por
"DNA EXCLUDED BURKE RAMSEY?" [entrega a conclusao] achando que era
melhor).

GRUPO A - extracao editorial (`extrair_payload_editorial`): chamada NOVA,
antes de qualquer candidato, isola o `payload` (o elemento certo pra'
revelar em parte) da `conclusao_central` (o que o video conclui - nunca
deve ser revelado nem em parte). Prompt em
scripts/prompts/headline_engine_payload.md. Nunca bloqueia o pipeline -
falha cai em `_payload_fallback` (deriva do nucleo_editorial/pergunta-
promessa, marcado `fallback: True` pra' auditoria).

GRUPO B - candidatos por mecanismo (`gerar_candidatos_headline`): chamada
dedicada, tool forcada, 6 candidatos (headline/mechanism/withheld_fact/
emphasis_word) - recebe o `payload` da Grupo A e pede explicitamente
mecanismos DIFERENTES (10 opcoes: tempo/numero/objeto/informacao_retida/
contradicao/reversao/consequencia/institucional/evidencia/
misterio_aberto), nunca variacoes da mesma ideia. Prompt em
scripts/prompts/headline_engine_candidatos.md.

GRUPO B(filtros) - filtros deterministicos de FORMATO
(`filtrar_candidatos_deterministicos`): preservados da v1, sem alteracao
de logica - elimina em codigo, sem chamada de API, candidatos que nunca
passariam no juiz de qualquer forma (mais de 6 palavras, repete o titulo
aprovado, nao cabe na area segura medida com a fonte real, emphasis_word
que nao aparece literalmente no headline, termo da lista de risco
configuravel).

GRUPO C(rejeicao) - filtros deterministicos SEMANTICOS, NOVOS
(`filtrar_candidatos_semanticos`): rodam depois dos filtros de formato,
ainda antes do juiz - eliminam pergunta respondivel com sim/nao ("DNA
excluded him?"), candidato sem mecanismo identificavel, candidato
sustentado so' por palavra generica de risco (SHOCKING/BOMBSHELL/TRUTH/
SECRET) sem nenhum termo concreto, e candidato cujo `withheld_fact`
nao compartilha nenhum termo com o payload/fatos extraidos da Grupo A
(afirmacao nao sustentada). Cobertura deliberadamente limitada ao ingles
(mesmo espirito da CLAUDE.md secao 5.4.1 Grupo C - falso negativo
silencioso em outros idiomas, nunca falso positivo).

GRUPO C(juiz) - juiz (`julgar_candidatos`): chamada separada, so' avalia
(rubrica 0-2 por criterio) - nunca reescreve nem sugere. Rubrica cresceu
de 6 pra' 7 criterios: `answer_leak` e' NOVO e mais forte que
`not_revealing` - `not_revealing` olha so' o headline contra o segredo
PARTICULAR daquele candidato; `answer_leak` olha titulo+headline JUNTOS
contra a `conclusao_central` do caso inteiro (a v1 nao pegava isso: um
headline podia passar limpo em `not_revealing` e ainda assim, somado ao
titulo aprovado, confirmar a conclusao do video). `answer_leak` e'
PORTA de elegibilidade igual a `opens_gap`/`anchored_to_case` (zerado
desqualifica o candidato, nao e' so' desconto de nota - "penalizacao
pesada, nao nota simples").

GRUPO D - regeneracao: preservada da v1 - no maximo 1 rodada extra de
A+B+C com o feedback do juiz (ou dos filtros, se ninguem sobreviveu), se
nenhum candidato da primeira rodada passar do limiar. Grupo A (payload)
roda so' UMA vez, antes da primeira rodada - nunca repetido na
regeneracao. Se a segunda rodada tambem falhar, persiste o melhor
candidato disponivel e marca aviso de revisao humana - nunca falha o
pipeline por causa do headline (CLAUDE.md secao 18.4).

GRUPO E - persistencia: `thumbnail/headline_engine.json` grava as TRES
etapas separadamente - `payload_editorial` (Grupo A, uma vez), `rodadas[]`
com candidatos/eliminados/sobreviventes por mecanismo (Grupo B/C) e
julgamentos (Grupo C juiz) de cada rodada - pra' diagnosticar depois ONDE
um resultado ruim se originou (payload errado, mecanismos pobres, juiz
mal calibrado) sem inferir pela thumbnail final nem gastar outra geracao.

GRUPO F - modo degradado: se `nucleo_editorial_status` (gravado por
scripts/3_gerar_roteiro.py, CLAUDE.md secao 5.4.1) for "ausente" (ou o
campo nao existir - projeto antigo, upload de roteiro), o nucleo usado
como entrada da Grupo A nasce da `pergunta_promessa` (tipicamente ~40
palavras) - uma chamada extra (`extrair_nucleo_compacto`) deriva um
nucleo compacto ANTES da Grupo A rodar. Duas etapas, nunca uma so'
silenciosa.

Nenhuma chamada passa `temperature`/`top_p`/`top_k` - descontinuado na
Claude Sonnet 5 (pensamento adaptativo ligado por padrao, API devolve 400
pra' qualquer parametro de sampling explicito - bug ja corrigido na v1,
nunca reintroduzir).

FORA DE ESCOPO (v2): simulacao competitiva contra titulos/thumbnails de
concorrentes - exigiria material de terceiros como entrada, que o
pipeline nao tem.
"""

import json
import logging
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MODELO_PADRAO = "claude-sonnet-5"
MAX_TOKENS_PAYLOAD = 1280
MAX_TOKENS_CANDIDATOS = 2048
MAX_TOKENS_JULGAMENTO = 1792
MAX_TOKENS_NUCLEO_COMPACTO = 256

VERSAO_PROMPT = "2.0"

# Mesmo default de scripts/3_gerar_roteiro.py:IDIOMA_PADRAO - usado quando
# nem job_metadata.json nem IDIOMA_ROTEIRO tem o idioma do projeto (ver
# _ler_contexto).
IDIOMA_PADRAO = "en-US"

CUSTO_INPUT_POR_MILHAO_USD = 3.0
CUSTO_OUTPUT_POR_MILHAO_USD = 15.0

_PASTA_PROMPTS = Path(__file__).resolve().parent / "prompts"
_PROMPT_PAYLOAD_PATH = _PASTA_PROMPTS / "headline_engine_payload.md"
_PROMPT_CANDIDATOS_PATH = _PASTA_PROMPTS / "headline_engine_candidatos.md"
_PROMPT_JUIZ_PATH = _PASTA_PROMPTS / "headline_engine_juiz.md"
_PROMPT_NUCLEO_COMPACTO_PATH = _PASTA_PROMPTS / "headline_engine_nucleo_compacto.md"

# Grupo A - papeis validos do `payload` extraido (o elemento a revelar em
# parte - NUNCA a conclusao central).
PAYLOAD_ROLES_VALIDOS = (
    "consequencia", "numero", "objeto", "contradicao",
    "evidencia", "tempo", "institucional", "informacao_retida",
)
REVEAL_LEVELS_VALIDOS = ("partial", "none")

# Grupo A (conceito visual, camada nova) - tipos validos de
# `elemento_principal`. `camera_filmagem` existe deliberadamente separado
# de `objeto` - achado real (caso da camera de campainha/tatuagem no
# pulso): sem essa categoria explicita, uma camera especifica que capturou
# o momento do caso colapsava em "objeto" generico e a composicao final
# perdia a cena inteira em cima dela.
TIPOS_ELEMENTO_VALIDOS = ("pessoa", "objeto", "documento", "camera_filmagem", "local", "outro")
PAPEIS_COMPOSICAO_VALIDOS = ("dominante", "apoio")

# Grupo B - mecanismos validos de apresentacao do payload como headline.
# Pelo menos 4 destes tem que aparecer distintos entre os 6 candidatos de
# uma rodada (exigido no prompt - scripts/prompts/headline_engine_
# candidatos.md - nao e' um gate de codigo que bloqueia geracao, ver
# contar_mecanismos_distintos abaixo, que so' audita).
MECANISMOS_VALIDOS = (
    "tempo", "numero", "objeto", "informacao_retida", "contradicao",
    "reversao", "consequencia", "institucional", "evidencia", "misterio_aberto",
)

MAX_PALAVRAS_HEADLINE = 6
LIMIAR_SOBREPOSICAO_TITULO = 0.6  # fracao de tokens do headline tambem presentes no titulo

# Area segura de encaixe tipografico (Grupo B) - medida com a fonte REAL
# (Anton-Regular.ttf) no menor tamanho de headline que a composicao por
# IA (scripts/thumbnail_briefing.py) ainda trata como "grande" (36px - o
# mesmo piso usado pelos templates Pillow ja removidos, preservado aqui
# so' como referencia de calibracao, nao porque algum renderizador local
# ainda dependa dele), aceitando quebra em ate' 2 linhas. Candidato que
# nao cabe nem quebrado em 2 linhas de 320px nesse tamanho e' descartado
# aqui - antes de gastar uma chamada de juiz nele.
FONTE_HEADLINE_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Anton-Regular.ttf"
LARGURA_SEGURA_PX = 320
TAMANHO_FONTE_CHECK_PX = 36
# Exigir 1 linha so' a 36px reprovaria ate' os exemplos de FORMA do
# proprio prompt ("WHAT ABDUCTOR WANTED" mede 334px a 36px, mais largo
# que 320). O filtro aqui aceita ate' 2 linhas quebradas em 320px -
# elimina so' headline realmente longo/verboso demais, nao qualquer
# headline de 3-6 palavras normal.
MAX_LINHAS_AREA_SEGURA = 2

# Lista de termos de risco: DELIBERADAMENTE configuravel, nao derivada do
# roteiro nem de nenhuma lista publicada pelo YouTube (a plataforma nao
# publica lista estavel de termos que afetam monetizacao). O efeito desta
# lista e' so' eliminar o CANDIDATO de headline que contem um termo dela
# (nunca aplica censura tipografica aqui - isso ja existe em outro lugar,
# scripts/thumbnail_briefing.py, via `censor`) - e' um aviso/protecao editorial, NUNCA garantia de
# monetizacao ou de aprovacao do YouTube. Ajustavel via env var
# HEADLINE_TERMOS_RISCO (lista separada por virgula) - ver .env.example.
TERMOS_RISCO_PADRAO = (
    "kill", "killed", "killer", "murder", "murdered", "rape", "raped",
    "suicide", "molest", "molested", "pedophile", "child abuse",
)

# Grupo C(rejeicao) - palavras iniciais tipicas de pergunta ABERTA (WH-
# question) - headline que comeca com uma delas NUNCA e' tratado como
# "pergunta respondivel com sim/nao", mesmo terminando em "?".
_PALAVRAS_WH = ("who", "what", "why", "how", "where", "when", "which", "whose")

# Grupo C(rejeicao) - palavras genericas de risco: sozinhas (sem nenhum
# termo concreto do caso junto), abrem lacuna mas com ancoragem zero -
# exatamente o antipadrao "THE TRUTH REVEALED" que a rubrica do juiz ja'
# pune (anchored_to_case=0), mas vale eliminar ANTES de gastar uma
# chamada de juiz num candidato que nunca teria chance. Cobertura
# deliberadamente em ingles - candidato em outro idioma nunca casa
# nenhuma destas palavras, entao esta regra nunca dispara pra' ele (falso
# negativo silencioso, nunca falso positivo - mesmo espirito da CLAUDE.md
# secao 5.4.1 Grupo C).
_PALAVRAS_GENERICAS_RISCO = frozenset({
    "shocking", "bombshell", "truth", "secret", "secrets", "revealed",
    "mystery", "unbelievable", "insane", "chilling", "exposed", "revelation",
})
# Palavras funcionais em ingles que nunca contam como "conteudo" pra' essa
# regra (artigos, preposicoes, pronomes curtos) - sem essa lista, "THE
# SHOCKING TRUTH" teria "the" como token de conteudo e escaparia da
# eliminacao por nao ser 100% generico.
_STOPWORDS_INGLES = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or",
    "that", "this", "what", "who", "why", "how", "was", "is", "are",
    "were", "did", "does", "he", "she", "they", "it", "his", "her",
    "their", "its", "never", "really", "never",
})
# Tamanho minimo de token pra' entrar na checagem de "afirmacao sustentada"
# (Grupo C, `_afirmacao_sustentada`) - evita falso-positivo de overlap por
# palavra curta/comum ("was", "the") coincidir por acaso.
_TAMANHO_MINIMO_TOKEN_SUPORTE = 4

# Tamanho minimo (caracteres) pra' um item de `supporting_facts` (Grupo A)
# ser aceito como frase de verdade - ver comentario em
# `extrair_payload_editorial` sobre o achado real que motivou este filtro
# (resposta real devolveu caracteres isolados em vez de frases).
_TAMANHO_MINIMO_SUPPORTING_FACT = 8

# Rubrica do juiz (Grupo C) - 7 criterios, 0-2 cada, maximo 14. Limiar de
# aprovacao deliberadamente nao e' so' "soma alta": um candidato so' e'
# ELEGIVEL se opens_gap, anchored_to_case E answer_leak (os tres
# criterios-PORTA, ver docstring do modulo) forem >= 1 cada - soma alta
# com qualquer um dos tres zerado nunca vence.
CRITERIOS_JULGAMENTO = (
    "opens_gap", "anchored_to_case", "not_title_repeat",
    "not_revealing", "answer_leak", "concise_impact", "visualizable",
)
MAX_TOTAL_JULGAMENTO = len(CRITERIOS_JULGAMENTO) * 2  # 14
LIMIAR_TOTAL_APROVACAO = 9  # de 14 possiveis (~64%, mesma faixa da v1: 8/12)
MAX_RODADAS_CANDIDATOS = 2


# ---------------------------------------------------------------------------
# Helpers duplicados de proposito (CLAUDE.md secao 9 - scripts
# autocontidos) - mesmo padrao ja usado em scripts/7_thumbnail.py e
# scripts/sincronizador_visual.py.
# ---------------------------------------------------------------------------


def _valor(obj, chave, default=None):
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
    usage = _valor(resposta, "usage")
    if usage is None:
        return 0.0
    tokens_input = _valor(usage, "input_tokens") or 0
    tokens_output = _valor(usage, "output_tokens") or 0
    return (
        (tokens_input / 1_000_000) * CUSTO_INPUT_POR_MILHAO_USD
        + (tokens_output / 1_000_000) * CUSTO_OUTPUT_POR_MILHAO_USD
    )


def _detalhar_excecao(exc: Exception) -> dict:
    """Detalhe real de uma excecao de chamada a API - bug corrigido pos-
    Sessao 24 (v1): o codigo generico "chamada_api_falhou" (string fixa,
    sem NENHUM detalhe da excecao real) escondia a causa raiz. `status_code`
    vem de `anthropic.APIStatusError` e subclasses (BadRequestError etc) -
    None pra excecao sem resposta HTTP (erro de rede, timeout)."""
    return {
        "codigo": "chamada_api_falhou",
        "tipo": type(exc).__name__,
        "mensagem": str(exc),
        "status_code": getattr(exc, "status_code", None),
    }


def _obter_cliente(api_key, cliente):
    if cliente is not None:
        return cliente
    try:
        import anthropic
    except ImportError:
        return None
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _ler_dict_json_ou_none(caminho: Path):
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return dados if isinstance(dados, dict) else None


_RE_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(texto: str) -> set:
    if not texto:
        return set()
    return {t.lower() for t in _RE_TOKEN.findall(texto)}


def _contar_palavras(texto: str) -> int:
    return len((texto or "").split())


# ---------------------------------------------------------------------------
# GRUPO B(filtros) - filtros deterministicos de FORMATO (preservados da v1)
# ---------------------------------------------------------------------------


def _e_substring_do_titulo(headline: str, titulo: str) -> bool:
    if not headline or not titulo:
        return False
    return headline.strip().lower() in titulo.strip().lower()


def _sobreposicao_com_titulo(headline: str, titulo: str) -> float:
    tokens_headline = _tokens(headline)
    if not tokens_headline or not titulo:
        return 0.0
    tokens_titulo = _tokens(titulo)
    comuns = tokens_headline & tokens_titulo
    return len(comuns) / len(tokens_headline)


_IMAGEM_DUMMY = Image.new("RGB", (10, 10))
_DRAW_DUMMY = ImageDraw.Draw(_IMAGEM_DUMMY)

# Helpers de fonte duplicados de proposito (CLAUDE.md secao 9 - scripts
# autocontidos) - viviam em scripts/thumbnail_templates.py (removido na
# sessao de simplificacao da Etapa 7, ver HISTORICO_BUGS.md) junto dos 5
# templates Pillow que este modulo nunca usou. So' o essencial pro
# filtro de encaixe tipografico (Grupo B) migrou pra' ca'.
_CACHE_FONTES: dict = {}


def _carregar_fonte(caminho: Path, tamanho: int):
    tamanho = max(1, int(tamanho))
    chave = (str(caminho), tamanho)
    fonte = _CACHE_FONTES.get(chave)
    if fonte is None:
        fonte = ImageFont.truetype(str(caminho), tamanho)
        _CACHE_FONTES[chave] = fonte
    return fonte


def _medir_texto(draw, texto: str, fonte, stroke_width: int = 0):
    if not texto:
        return 0, 0
    bbox = draw.textbbox((0, 0), texto, font=fonte, stroke_width=stroke_width)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _quebrar_texto_em_linhas(draw, texto: str, fonte, largura_max: float) -> list:
    """Quebra `texto` em linhas que cabem em `largura_max` com `fonte`,
    quebrando por PALAVRA (nunca no meio de uma palavra)."""
    palavras = texto.split()
    if not palavras:
        return [""]
    linhas = []
    linha_atual = palavras[0]
    for palavra in palavras[1:]:
        candidata = f"{linha_atual} {palavra}"
        largura, _ = _medir_texto(draw, candidata, fonte)
        if largura <= largura_max:
            linha_atual = candidata
        else:
            linhas.append(linha_atual)
            linha_atual = palavra
    linhas.append(linha_atual)
    return linhas


def _cabe_na_area_segura(headline: str) -> bool:
    """Quebra `headline` em linhas de ate' LARGURA_SEGURA_PX (320px) com a
    fonte REAL (Anton-Regular.ttf, 36px), textbbox real, nunca estimativa
    por contagem de caracteres. Cabe se quebrar em no maximo
    MAX_LINHAS_AREA_SEGURA (2) linhas, cada uma dentro da largura.
    Headline vazio sempre cabe (outra validacao cuida de headline
    vazio)."""
    if not headline:
        return True
    fonte = _carregar_fonte(FONTE_HEADLINE_PATH, TAMANHO_FONTE_CHECK_PX)
    linhas = _quebrar_texto_em_linhas(_DRAW_DUMMY, headline, fonte, LARGURA_SEGURA_PX)
    if len(linhas) > MAX_LINHAS_AREA_SEGURA:
        return False
    return all(_medir_texto(_DRAW_DUMMY, linha, fonte)[0] <= LARGURA_SEGURA_PX for linha in linhas)


def _emphasis_valida(headline: str, emphasis_word: str) -> bool:
    if not emphasis_word or not emphasis_word.strip():
        return True
    return emphasis_word in (headline or "")


def _termos_risco() -> tuple:
    import os

    bruto = os.environ.get("HEADLINE_TERMOS_RISCO")
    if not bruto or not bruto.strip():
        return TERMOS_RISCO_PADRAO
    return tuple(t.strip().lower() for t in bruto.split(",") if t.strip())


def _contem_termo_de_risco(headline: str) -> str | None:
    """Devolve o termo de risco encontrado (primeira ocorrencia), ou None
    se nenhum. Comparacao por substring simples, case-insensitive -
    deliberadamente simples, sem stemming/normalizacao (lista curta e
    configuravel, nao precisa de sofisticacao)."""
    headline_lower = (headline or "").lower()
    for termo in _termos_risco():
        if termo and termo in headline_lower:
            return termo
    return None


def filtrar_candidatos_deterministicos(candidatos: list, titulo_aprovado: str) -> tuple:
    """GRUPO B(filtros) - de FORMATO, preservado sem alteracao de logica
    desde a v1. Roda em codigo, sem chamada de API. Devolve
    `(sobreviventes, eliminados)` - `eliminados` e' uma lista de
    `{"candidato": {...}, "motivo": str}` pra' auditoria (Grupo E),
    nunca descartada em silencio. Ordem dos sobreviventes preservada
    (mesma ordem em que vieram da Grupo B) - importante porque o Grupo
    C (rejeicao semantica + juiz) recebe e responde por indice dentro
    dessa lista."""
    sobreviventes = []
    eliminados = []

    for candidato in candidatos:
        headline = (candidato.get("headline") or "").strip()
        emphasis_word = candidato.get("emphasis_word") or ""

        motivo = None
        if not headline:
            motivo = "headline_vazio"
        elif _contar_palavras(headline) > MAX_PALAVRAS_HEADLINE:
            motivo = "mais_de_6_palavras"
        elif _e_substring_do_titulo(headline, titulo_aprovado):
            motivo = "substring_do_titulo"
        elif _sobreposicao_com_titulo(headline, titulo_aprovado) > LIMIAR_SOBREPOSICAO_TITULO:
            motivo = "alta_sobreposicao_com_titulo"
        elif not _cabe_na_area_segura(headline):
            motivo = "nao_cabe_area_segura"
        elif not _emphasis_valida(headline, emphasis_word):
            motivo = "emphasis_word_ausente_no_headline"
        else:
            termo_risco = _contem_termo_de_risco(headline)
            if termo_risco:
                motivo = f"termo_de_risco:{termo_risco}"

        if motivo is None:
            sobreviventes.append(candidato)
        else:
            eliminados.append({"candidato": candidato, "motivo": motivo})

    return sobreviventes, eliminados


# ---------------------------------------------------------------------------
# GRUPO C(rejeicao) - filtros deterministicos SEMANTICOS (novos na v2)
# ---------------------------------------------------------------------------


def _e_pergunta_sim_nao(headline: str) -> bool:
    """Detecta headline no formato de pergunta FECHADA (respondivel com
    sim/nao) - "DID SHE DO IT?", "DNA EXCLUDED HIM?". Achado real (caso
    Burke Ramsey): esse formato tende a soar como se a resposta ja'
    estivesse implicita ao lado do titulo, mesmo sem revelar o
    `withheld_fact` sozinho (e' exatamente o que `answer_leak` no juiz
    tambem cobre - esta regra elimina o caso obvio ANTES de gastar uma
    chamada de juiz nele).

    So' rejeita headline que TERMINA em "?" (senao nao e' pergunta
    nenhuma) E cuja primeira palavra NAO e' uma palavra de pergunta
    ABERTA (who/what/why/how/where/when/which/whose) - pergunta aberta
    continua sendo o formato desejado, nunca eliminada aqui."""
    texto = (headline or "").strip()
    if not texto.endswith("?"):
        return False
    sem_interrogacao = texto[:-1].strip()
    if not sem_interrogacao:
        return False
    primeira_palavra = re.split(r"\s+", sem_interrogacao)[0].strip(".,!\"'").lower()
    return primeira_palavra not in _PALAVRAS_WH


def _mecanismo_valido(candidato: dict) -> bool:
    """GRUPO C(rejeicao) - "sem curiosity_payload identificavel": o
    candidato precisa declarar um mecanismo reconhecido E um
    withheld_fact nao-vazio. Um `mechanism` fora do enum (a API devolveu
    algo estranho) ou um `withheld_fact` vazio significa que o modelo nao
    conseguiu ancorar o candidato em nada especifico - eliminado aqui em
    vez de silenciosamente aceito com um mecanismo inventado."""
    return candidato.get("mechanism") in MECANISMOS_VALIDOS and bool((candidato.get("withheld_fact") or "").strip())


def _apenas_palavra_generica(headline: str) -> bool:
    """GRUPO C(rejeicao) - headline cujo UNICO conteudo (descontadas
    stopwords) sao palavras genericas de risco (SHOCKING/BOMBSHELL/TRUTH/
    SECRET/...) - lacuna total, ancoragem zero (o erro OPOSTO ao de
    revelar demais, e' igualmente ruim). Headline sem nenhuma palavra de
    conteudo (so' stopwords) nao e' eliminado por ESTA regra - outra
    validacao (headline_vazio) ja cobre esse caso degenerado.

    Cobertura deliberadamente em ingles - ver comentario da constante
    _PALAVRAS_GENERICAS_RISCO."""
    tokens = [t for t in _RE_TOKEN.findall((headline or "").lower())]
    conteudo = [t for t in tokens if t not in _STOPWORDS_INGLES]
    if not conteudo:
        return False
    return all(t in _PALAVRAS_GENERICAS_RISCO for t in conteudo)


def _afirmacao_sustentada(candidato: dict, payload_editorial: dict) -> bool:
    """GRUPO C(rejeicao) - "afirmacao nao sustentada pelo roteiro":
    verificacao heuristica (nunca uma auditoria documental real - mesmo
    espirito da CLAUDE.md secao 5.4.1 Grupo A) de que o `withheld_fact`
    do candidato compartilha pelo menos um termo substantivo (>=4
    caracteres) com o material que a Grupo A extraiu do roteiro
    (`payload`/`concrete_anchor`/`hidden_question`/`supporting_facts`).
    Zero sobreposicao sugere que o candidato inventou um angulo sem
    lastro no que foi extraido - eliminado aqui, registrado com motivo
    pra' auditoria (aceitavel com falso positivo, nunca com falso
    negativo escondido)."""
    fato = (candidato.get("withheld_fact") or "").strip()
    if not fato:
        return False
    payload_editorial = payload_editorial or {}
    partes_contexto = [
        str(payload_editorial.get("payload") or ""),
        str(payload_editorial.get("concrete_anchor") or ""),
        str(payload_editorial.get("hidden_question") or ""),
        str(payload_editorial.get("tension_source") or ""),
        " ".join(str(f) for f in (payload_editorial.get("supporting_facts") or [])),
    ]
    tokens_contexto = _tokens(" ".join(partes_contexto))
    tokens_fato = {t for t in _tokens(fato) if len(t) >= _TAMANHO_MINIMO_TOKEN_SUPORTE}
    if not tokens_fato or not tokens_contexto:
        # Sem material da Grupo A pra' comparar (payload_editorial vazio,
        # ex: fallback sem supporting_facts nenhum) - nao ha' base pra'
        # rejeitar por falta de lastro, entao deixa passar (esta regra
        # nunca vira o unico motivo de reprovacao quando a propria Grupo
        # A nao tinha material nenhum pra' oferecer).
        return True
    return bool(tokens_fato & tokens_contexto)


def filtrar_candidatos_semanticos(candidatos: list, payload_editorial: dict) -> tuple:
    """GRUPO C(rejeicao) - roda sobre os SOBREVIVENTES de
    `filtrar_candidatos_deterministicos` (formato), ainda antes do juiz.
    Devolve `(sobreviventes, eliminados)` no mesmo formato de
    `filtrar_candidatos_deterministicos`. Ordem preservada (o juiz
    responde por indice dentro dos sobreviventes finais)."""
    sobreviventes = []
    eliminados = []

    for candidato in candidatos:
        headline = (candidato.get("headline") or "").strip()

        motivo = None
        if _e_pergunta_sim_nao(headline):
            motivo = "pergunta_sim_nao"
        elif not _mecanismo_valido(candidato):
            motivo = "sem_mecanismo_identificavel"
        elif _apenas_palavra_generica(headline):
            motivo = "apenas_palavra_generica"
        elif not _afirmacao_sustentada(candidato, payload_editorial):
            motivo = "afirmacao_nao_sustentada"

        if motivo is None:
            sobreviventes.append(candidato)
        else:
            eliminados.append({"candidato": candidato, "motivo": motivo})

    return sobreviventes, eliminados


def contar_mecanismos_distintos(candidatos: list) -> int:
    """Metrica de auditoria (Grupo D/E) - NUNCA um gate que bloqueia
    geracao (o prompt de Grupo B ja' pede >=4 mecanismos distintos; forcar
    isso em codigo gastaria uma rodada extra sem garantia nenhuma de
    melhora, e o produto ja' evita regeneracao por motivo que a rodada
    extra nao tem como corrigir - mesmo principio da correcao pos-Sessao
    24 sobre falha de infraestrutura do juiz). So' conta quantos
    `mechanism` distintos apareceram, pra' quem olhar `headline_engine.json`
    depois conseguir distinguir "a Grupo B gerou variacao pobre" de "os
    mecanismos eram bons mas o juiz/filtros descartaram os melhores"."""
    return len({c.get("mechanism") for c in candidatos if c.get("mechanism")})


# ---------------------------------------------------------------------------
# GRUPO A - extracao editorial (payload)
# ---------------------------------------------------------------------------

NOME_TOOL_PAYLOAD = "entregar_payload_editorial"
SCHEMA_PAYLOAD = {
    "name": NOME_TOOL_PAYLOAD,
    "description": (
        "Entrega o payload editorial deste caso (o elemento certo pra' revelar "
        "parcialmente num headline de thumbnail), distinto da conclusao central "
        "do video."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "conclusao_central": {"type": "string"},
            "payload": {"type": "string"},
            "payload_role": {"type": "string", "enum": list(PAYLOAD_ROLES_VALIDOS)},
            "hidden_question": {"type": "string"},
            "tension_source": {"type": "string"},
            "concrete_anchor": {"type": "string"},
            "information_gap": {"type": "string"},
            "supporting_facts": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 6,
            },
            "reveal_level": {"type": "string", "enum": list(REVEAL_LEVELS_VALIDOS)},
            # Conceito visual (camada nova, mesma chamada - zero custo de
            # API extra) - ver docstring de `extrair_payload_editorial` e
            # scripts/prompts/headline_engine_payload.md.
            "elemento_principal": {"type": "string"},
            "tipo_elemento": {"type": "string", "enum": list(TIPOS_ELEMENTO_VALIDOS)},
            "acao_ou_momento": {"type": ["string", "null"]},
            "revelacao": {"type": ["string", "null"]},
            "papel_na_composicao": {"type": "string", "enum": list(PAPEIS_COMPOSICAO_VALIDOS)},
        },
        "required": [
            "conclusao_central", "payload", "payload_role", "hidden_question",
            "tension_source", "concrete_anchor", "information_gap",
            "supporting_facts", "reveal_level",
            "elemento_principal", "tipo_elemento", "acao_ou_momento",
            "revelacao", "papel_na_composicao",
        ],
    },
}


def extrair_payload_editorial(
    cliente_api,
    modelo: str,
    nucleo_editorial: str,
    pergunta_promessa: str,
    titulo_aprovado: str,
    roteiro_texto: str,
    idioma: str = IDIOMA_PADRAO,
    _custos: list | None = None,
) -> tuple:
    """GRUPO A. Chamada dedicada (tool forcada), roda UMA vez por
    `gerar_headline` - antes de qualquer rodada de candidatos, nunca
    repetida na regeneracao (Grupo D). Devolve `(payload_editorial, None)`
    em sucesso ou `(None, codigo_erro)` em falha - nunca levanta excecao.
    Chamador (`gerar_headline`) trata falha com `_payload_fallback`,
    nunca bloqueia o pipeline (CLAUDE.md secao 18.4)."""
    prompt_sistema = _PROMPT_PAYLOAD_PATH.read_text(encoding="utf-8")
    entrada = (
        f"Idioma exigido para TODOS os campos de texto: {idioma}\n\n"
        f"Nucleo editorial: {nucleo_editorial or '(nao disponivel)'}\n\n"
        f"Pergunta-promessa: {pergunta_promessa or '(nao disponivel)'}\n\n"
        f"Titulo aprovado do video: {titulo_aprovado or '(nao disponivel)'}\n\n"
        f"Roteiro aprovado:\n\n{roteiro_texto}"
    )
    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_PAYLOAD,
            system=prompt_sistema,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": entrada, "cache_control": {"type": "ephemeral"}}],
                }
            ],
            tools=[SCHEMA_PAYLOAD],
            tool_choice={"type": "tool", "name": NOME_TOOL_PAYLOAD},
        )
    except Exception as exc:
        logger.warning("extrair_payload_editorial: chamada a API falhou: %s", exc, exc_info=True)
        return None, _detalhar_excecao(exc)

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_PAYLOAD)
    if not isinstance(dados, dict):
        return None, "resposta_invalida"

    payload = str(dados.get("payload") or "").strip()
    conclusao_central = str(dados.get("conclusao_central") or "").strip()
    if not payload or not conclusao_central:
        return None, "payload_invalido"

    payload_role = dados.get("payload_role") if dados.get("payload_role") in PAYLOAD_ROLES_VALIDOS else ""
    reveal_level = dados.get("reveal_level") if dados.get("reveal_level") in REVEAL_LEVELS_VALIDOS else "partial"
    # Achado real (validacao Grupo G contra API real, projeto Burke
    # Ramsey): uma resposta real devolveu `supporting_facts` como uma
    # lista de CARACTERES ISOLADOS (37 entradas de 1 letra cada,
    # coincidentemente soletrando um fragmento de tag XML de outro
    # formato de tool-call) em vez de frases curtas - lixo de formato que
    # nunca deveria virar "fato de suporte". Descarta qualquer item
    # menor que _TAMANHO_MINIMO_SUPPORTING_FACT (uma frase curta de
    # verdade, mesmo minima, tem bem mais que isso) - filtro simples,
    # nunca uma correcao inteligente do conteudo.
    supporting_facts = [
        f for f in (str(x).strip() for x in (dados.get("supporting_facts") or []))
        if len(f) >= _TAMANHO_MINIMO_SUPPORTING_FACT
    ]

    conceito_visual = _normalizar_conceito_visual(dados)

    payload_editorial = {
        "conclusao_central": conclusao_central,
        "payload": payload,
        "payload_role": payload_role,
        "hidden_question": str(dados.get("hidden_question") or "").strip(),
        "tension_source": str(dados.get("tension_source") or "").strip(),
        "concrete_anchor": str(dados.get("concrete_anchor") or "").strip(),
        "information_gap": str(dados.get("information_gap") or "").strip(),
        "supporting_facts": supporting_facts,
        "reveal_level": reveal_level,
        "conceito_visual": conceito_visual,
        "fallback": False,
    }
    return payload_editorial, None


def _normalizar_conceito_visual(dados: dict) -> dict:
    """Conceito visual (camada nova) - normaliza os 5 campos extras da
    mesma resposta de `extrair_payload_editorial`. `tipo_elemento` fora do
    enum cai em "outro" (mesmo espirito de `payload_role`/`accent` -
    nunca descarta o conceito inteiro por causa de um enum invalido).
    `revelacao` so' faz sentido com `acao_ou_momento` preenchido - vazio
    um dos dois zera os dois juntos, pra' nunca persistir uma revelacao
    orfa sem a acao que a causou."""
    elemento_principal = str(dados.get("elemento_principal") or "").strip()
    tipo_elemento = dados.get("tipo_elemento") if dados.get("tipo_elemento") in TIPOS_ELEMENTO_VALIDOS else "outro"
    acao_ou_momento = dados.get("acao_ou_momento")
    acao_ou_momento = acao_ou_momento.strip() if isinstance(acao_ou_momento, str) and acao_ou_momento.strip() else None
    revelacao = dados.get("revelacao")
    revelacao = revelacao.strip() if isinstance(revelacao, str) and revelacao.strip() else None
    if acao_ou_momento is None:
        revelacao = None
    papel_na_composicao = (
        dados.get("papel_na_composicao")
        if dados.get("papel_na_composicao") in PAPEIS_COMPOSICAO_VALIDOS
        else "apoio"
    )
    return {
        "elemento_principal": elemento_principal,
        "tipo_elemento": tipo_elemento,
        "acao_ou_momento": acao_ou_momento,
        "revelacao": revelacao,
        "papel_na_composicao": papel_na_composicao,
    }


def _payload_fallback(nucleo_editorial: str, pergunta_promessa: str) -> dict:
    """Usado quando `extrair_payload_editorial` falha (API fora do ar,
    resposta invalida) - GRUPO A nunca bloqueia o pipeline. Deriva um
    payload minimo do que ja' existia antes desta feature (nucleo
    editorial/pergunta-promessa), marcado `fallback: True` pra' a
    auditoria e pro chamador saberem que a Grupo A degradou. Sem
    `supporting_facts` (nada foi extraido de verdade) - `_afirmacao_
    sustentada` trata ausencia de material com gracaa, nunca reprovando
    por essa razao especifica quando a Grupo A nao tinha nada a oferecer."""
    return {
        "conclusao_central": pergunta_promessa or "",
        "payload": nucleo_editorial or "",
        "payload_role": "informacao_retida",
        "hidden_question": pergunta_promessa or "",
        "tension_source": "",
        "concrete_anchor": "",
        "information_gap": "",
        "supporting_facts": [],
        "reveal_level": "none",
        "conceito_visual": _conceito_visual_fallback(nucleo_editorial),
        "fallback": True,
    }


def _conceito_visual_fallback(nucleo_editorial: str) -> dict:
    """Fallback deterministico do conceito visual - usado quando a Grupo
    A inteira falhou (`_payload_fallback` acima). Sem chamada de API pra'
    inferir um elemento concreto, o unico material seguro e' o nucleo
    editorial em si como `elemento_principal` generico, `tipo_elemento`
    "outro" (nunca inventa uma categoria especifica sem base) e
    `papel_na_composicao` "apoio" (nunca forca dominancia de um elemento
    que ninguem confirmou)."""
    return {
        "elemento_principal": nucleo_editorial or "",
        "tipo_elemento": "outro",
        "acao_ou_momento": None,
        "revelacao": None,
        "papel_na_composicao": "apoio",
    }


# ---------------------------------------------------------------------------
# GRUPO B - candidatos por mecanismo
# ---------------------------------------------------------------------------

NOME_TOOL_CANDIDATOS = "entregar_candidatos_headline"
SCHEMA_CANDIDATOS = {
    "name": NOME_TOOL_CANDIDATOS,
    "description": "Entrega 6 candidatos de headline pra thumbnail, cada um com mechanism, withheld_fact e emphasis_word.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 6,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "mechanism": {"type": "string", "enum": list(MECANISMOS_VALIDOS)},
                        "withheld_fact": {"type": "string"},
                        "emphasis_word": {"type": "string"},
                    },
                    "required": ["headline", "mechanism", "withheld_fact", "emphasis_word"],
                },
            }
        },
        "required": ["candidates"],
    },
}


def _montar_prompt_candidatos(feedback_regeneracao: str | None) -> str:
    prompt_base = _PROMPT_CANDIDATOS_PATH.read_text(encoding="utf-8")
    bloco_feedback = ""
    if feedback_regeneracao:
        bloco_feedback = (
            "## Rodada anterior nao aprovada - feedback do juiz\n\n"
            f"{feedback_regeneracao}\n\n"
            "Gere candidatos NOVOS que corrijam esses pontos - nao repita os "
            "mesmos headlines."
        )
    return prompt_base.format(feedback_regeneracao=bloco_feedback)


def gerar_candidatos_headline(
    cliente_api,
    modelo: str,
    payload_editorial: dict,
    titulo_aprovado: str,
    roteiro_texto: str,
    feedback_regeneracao: str | None = None,
    idioma: str = IDIOMA_PADRAO,
    _custos: list | None = None,
) -> tuple:
    """GRUPO B. Chamada dedicada (tool forcada), NUNCA na mesma chamada
    que titulo/descricao/subject_name - e' o que evita o vies de
    sumarizacao do diagnostico (ver docstring do modulo). Recebe o
    `payload_editorial` inteiro da Grupo A (payload/payload_role/
    hidden_question/tension_source/concrete_anchor/conclusao_central) em
    vez de so' nucleo_editorial/pergunta_promessa (mudanca de assinatura
    da v1 pra' v2). Devolve `(candidatos, None)` em sucesso ou `(None,
    codigo_erro)` em falha - nunca levanta excecao.

    `idioma`: passado EXPLICITAMENTE no corpo da mensagem, nao inferido
    implicitamente do roteiro pelo modelo - achado real da v1
    (nancyGuthrieProject03, en-US): a instrucao implicita saiu
    inconsistente entre rodadas. Mesmo padrao de {IDIOMA} ja usado nos
    prompts de roteiro (scripts/prompts/perfis/*/sistema.md)."""
    prompt_sistema = _montar_prompt_candidatos(feedback_regeneracao)
    payload_editorial = payload_editorial or {}
    entrada = (
        f"Idioma exigido para TODOS os campos de texto (headline, withheld_fact): {idioma}\n\n"
        f"Payload (elemento a revelar em parte): {payload_editorial.get('payload') or '(nao disponivel)'}\n"
        f"payload_role: {payload_editorial.get('payload_role') or '(nao disponivel)'}\n"
        f"hidden_question: {payload_editorial.get('hidden_question') or '(nao disponivel)'}\n"
        f"tension_source: {payload_editorial.get('tension_source') or '(nao disponivel)'}\n"
        f"concrete_anchor: {payload_editorial.get('concrete_anchor') or '(nao disponivel)'}\n\n"
        f"Conclusao central do caso (NUNCA revelar, nem em parte): "
        f"{payload_editorial.get('conclusao_central') or '(nao disponivel)'}\n\n"
        f"Titulo aprovado do video (NUNCA repita): {titulo_aprovado or '(nao disponivel)'}\n\n"
        f"Roteiro aprovado:\n\n{roteiro_texto}"
    )
    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_CANDIDATOS,
            system=prompt_sistema,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": entrada, "cache_control": {"type": "ephemeral"}}],
                }
            ],
            tools=[SCHEMA_CANDIDATOS],
            tool_choice={"type": "tool", "name": NOME_TOOL_CANDIDATOS},
        )
    except Exception as exc:
        logger.warning("gerar_candidatos_headline: chamada a API falhou: %s", exc, exc_info=True)
        return None, _detalhar_excecao(exc)

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_CANDIDATOS)
    if not isinstance(dados, dict):
        return None, "resposta_invalida"

    candidatos = dados.get("candidates")
    if not isinstance(candidatos, list) or not candidatos:
        return None, "resposta_sem_candidatos"

    candidatos_normalizados = []
    for c in candidatos:
        if not isinstance(c, dict):
            continue
        mechanism_bruto = c.get("mechanism")
        # Mecanismo fora do enum NAO e' silenciosamente coagido pra' um
        # default valido (a v1 fazia isso com gap_type -> "secret") -
        # preservado como veio, pra' `_mecanismo_valido` (Grupo C) captar
        # e eliminar de forma auditavel em vez de aceitar de graca.
        mechanism = mechanism_bruto if mechanism_bruto in MECANISMOS_VALIDOS else str(mechanism_bruto or "")
        candidatos_normalizados.append(
            {
                "headline": str(c.get("headline") or "").strip(),
                "mechanism": mechanism,
                "withheld_fact": str(c.get("withheld_fact") or "").strip(),
                "emphasis_word": str(c.get("emphasis_word") or "").strip(),
            }
        )

    if not candidatos_normalizados:
        return None, "resposta_sem_candidatos"

    return candidatos_normalizados, None


# ---------------------------------------------------------------------------
# GRUPO C(juiz)
# ---------------------------------------------------------------------------

NOME_TOOL_JULGAMENTO = "entregar_julgamento_headline"
_PROPRIEDADES_CRITERIOS = {
    criterio: {"type": "integer", "enum": [0, 1, 2]} for criterio in CRITERIOS_JULGAMENTO
}
SCHEMA_JULGAMENTO = {
    "name": NOME_TOOL_JULGAMENTO,
    "description": "Entrega a nota (0-2) por criterio da rubrica para cada candidato de headline, na ordem recebida.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_index": {"type": "integer"},
                        **_PROPRIEDADES_CRITERIOS,
                    },
                    "required": ["candidate_index", *CRITERIOS_JULGAMENTO],
                },
            }
        },
        "required": ["judgments"],
    },
}


def julgar_candidatos(
    cliente_api,
    modelo: str,
    candidatos: list,
    titulo_aprovado: str,
    conclusao_central: str = "",
    _custos: list | None = None,
) -> tuple:
    """GRUPO C(juiz). Chamada separada - o juiz so' avalia, nunca reescreve
    (reforcado tambem no prompt de sistema). Devolve `(julgamentos,
    None)` em sucesso - `julgamentos` e' uma lista alinhada por INDICE
    com `candidatos` (nunca confia em `candidate_index` da resposta
    pra' reordenar, so' usa pra' validar que a contagem bate) - ou
    `(None, codigo_erro)` em falha. Nunca levanta excecao.

    `conclusao_central` (novo na v2): passado pro juiz avaliar o criterio
    `answer_leak` - titulo+headline juntos nao podem permitir deduzir a
    conclusao do video, mesmo quando o headline sozinho passa limpo em
    `not_revealing` (que so' olha o segredo PARTICULAR do candidato).

    NAO passa `temperature` (bug corrigido na v1, pos-Sessao 24): a
    Claude Sonnet 5 tem pensamento adaptativo ligado por padrao e
    REMOVEU o parametro de sampling explicito - qualquer `temperature`/
    `top_p`/`top_k` na chamada devolve 400."""
    prompt_sistema = _PROMPT_JUIZ_PATH.read_text(encoding="utf-8")

    linhas_candidatos = []
    for i, c in enumerate(candidatos):
        linhas_candidatos.append(
            f"Candidato {i}:\nheadline: {c['headline']}\nmechanism: {c['mechanism']}\nwithheld_fact: {c['withheld_fact']}"
        )
    entrada = (
        f"Titulo aprovado do video: {titulo_aprovado or '(nao disponivel)'}\n\n"
        f"Conclusao central do caso (para avaliar answer_leak): {conclusao_central or '(nao disponivel)'}\n\n"
        + "\n\n".join(linhas_candidatos)
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_JULGAMENTO,
            system=prompt_sistema,
            messages=[{"role": "user", "content": entrada}],
            tools=[SCHEMA_JULGAMENTO],
            tool_choice={"type": "tool", "name": NOME_TOOL_JULGAMENTO},
        )
    except Exception as exc:
        logger.warning("julgar_candidatos: chamada a API falhou: %s", exc, exc_info=True)
        return None, _detalhar_excecao(exc)

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_JULGAMENTO)
    if not isinstance(dados, dict):
        return None, "resposta_invalida"

    julgamentos_brutos = dados.get("judgments")
    if not isinstance(julgamentos_brutos, list):
        return None, "resposta_invalida"

    por_indice = {}
    for j in julgamentos_brutos:
        if not isinstance(j, dict):
            continue
        indice = j.get("candidate_index")
        if not isinstance(indice, int):
            continue
        por_indice[indice] = j

    julgamentos = []
    for i in range(len(candidatos)):
        j = por_indice.get(i, {})
        notas = {}
        for criterio in CRITERIOS_JULGAMENTO:
            valor = j.get(criterio)
            notas[criterio] = valor if valor in (0, 1, 2) else 0
        notas["total"] = sum(notas[c] for c in CRITERIOS_JULGAMENTO)
        julgamentos.append(notas)

    return julgamentos, None


def _elegivel(julgamento: dict) -> bool:
    """Tres criterios-PORTA (v2 - a v1 tinha dois): `opens_gap`,
    `anchored_to_case` E `answer_leak` precisam ser >=1 cada. Qualquer um
    zerado desqualifica o candidato, mesmo com soma total alta nos
    outros quatro - "penalizacao pesada, nao nota simples" (pedido
    explicito pro answer_leak)."""
    return (
        julgamento["opens_gap"] >= 1
        and julgamento["anchored_to_case"] >= 1
        and julgamento["answer_leak"] >= 1
    )


def selecionar_vencedor(candidatos: list, julgamentos: list):
    """Aplica a regra de selecao: entre os candidatos ELEGIVEIS (peso
    igual de opens_gap/anchored_to_case/answer_leak, nenhum dos tres
    zerado) com nota total >= LIMIAR_TOTAL_APROVACAO, vence o maior
    total; empate, o headline mais curto (palavras, depois caracteres).
    Devolve `(indice_vencedor_ou_None, aprovado_bool)` - `aprovado=False`
    sinaliza pro chamador que nenhum candidato passou do limiar (dispara
    regeneracao ou modo degradado)."""
    elegiveis = [
        i for i, j in enumerate(julgamentos)
        if _elegivel(j) and j["total"] >= LIMIAR_TOTAL_APROVACAO
    ]
    if not elegiveis:
        return None, False

    def _chave_desempate(i):
        headline = candidatos[i]["headline"]
        return (-julgamentos[i]["total"], _contar_palavras(headline), len(headline))

    vencedor = min(elegiveis, key=_chave_desempate)
    return vencedor, True


def _melhor_candidato_sem_aprovacao(candidatos: list, julgamentos: list | None):
    """GRUPO D (fallback final) - quando nenhuma rodada aprova nenhum
    candidato, escolhe o melhor disponivel pra' persistir mesmo assim
    (nunca falha o pipeline por causa do headline). Prefere o de maior
    nota total julgada; sem julgamento nenhum disponivel (juiz falhou
    nas duas rodadas), pega o primeiro sobrevivente dos filtros
    deterministicos."""
    if not candidatos:
        return None, None
    if julgamentos and len(julgamentos) == len(candidatos):
        indice = max(range(len(candidatos)), key=lambda i: julgamentos[i]["total"])
        return candidatos[indice], julgamentos[indice]
    return candidatos[0], None


def _montar_feedback_regeneracao(candidatos: list, julgamentos: list) -> str:
    linhas = []
    for c, j in zip(candidatos, julgamentos):
        fracos = [criterio for criterio in CRITERIOS_JULGAMENTO if j[criterio] <= 1]
        linhas.append(
            f'- "{c["headline"]}" (mecanismo {c.get("mechanism") or "?"}, '
            f'total {j["total"]}/{MAX_TOTAL_JULGAMENTO}) - fraco em: {", ".join(fracos) or "nenhum"}'
        )
    return (
        "Nenhum candidato da rodada anterior passou do limiar de aprovacao. "
        "Pontos fracos observados pelo juiz:\n" + "\n".join(linhas) +
        "\n\nGere candidatos com mecanismos diferentes dos usados acima - nao repita o mesmo angulo."
    )


def _montar_feedback_filtros(eliminados: list) -> str:
    """Feedback de regeneracao quando NENHUM candidato sobreviveu aos
    filtros deterministicos (formato ou semantico) - o juiz nunca chegou
    a rodar nesta rodada. Resume os motivos de eliminacao (contagem por
    motivo) pra' o modelo evitar repetir o mesmo problema."""
    motivos = Counter(e["motivo"] for e in eliminados)
    resumo_motivos = ", ".join(f"{motivo} ({n})" for motivo, n in motivos.items()) or "nao disponivel"
    return (
        "Todos os candidatos da rodada anterior foram eliminados antes do juiz. "
        f"Motivos: {resumo_motivos}. Gere candidatos mais curtos, com mecanismo "
        "claramente identificavel, angulo diferente do titulo aprovado, e "
        "sustentados pelos fatos do roteiro - evite perguntas respondiveis com "
        "sim/nao e palavras genericas isoladas (SHOCKING/BOMBSHELL/TRUTH/SECRET)."
    )


# ---------------------------------------------------------------------------
# GRUPO F - modo degradado (nucleo compacto a partir da pergunta-promessa)
# ---------------------------------------------------------------------------

NOME_TOOL_NUCLEO_COMPACTO = "entregar_nucleo_compacto"
SCHEMA_NUCLEO_COMPACTO = {
    "name": NOME_TOOL_NUCLEO_COMPACTO,
    "description": "Entrega um nucleo editorial compacto (2 a 8 palavras) derivado da pergunta-promessa.",
    "input_schema": {
        "type": "object",
        "properties": {"nucleo_compacto": {"type": "string"}},
        "required": ["nucleo_compacto"],
    },
}


def extrair_nucleo_compacto(
    cliente_api, modelo: str, pergunta_promessa: str, idioma: str = IDIOMA_PADRAO, _custos: list | None = None
) -> tuple:
    """GRUPO F, primeira das duas etapas do modo degradado. Devolve
    `(nucleo_compacto, None)` ou `(None, codigo_erro)` - nunca levanta
    excecao. Chamada so' acontece quando `nucleo_editorial_status ==
    "ausente"` (ou campo nao existe) - projeto sem nucleo valido nunca
    usa a pergunta-promessa longa direto na Grupo A em silencio.

    `idioma`: passado EXPLICITAMENTE, nao inferido - achado real da v1
    (nancyGuthrieProject03, pergunta_promessa em ingles): mesmo com a
    instrucao implicita, o `nucleo_compacto` saiu em portugues."""
    if not pergunta_promessa or not pergunta_promessa.strip():
        return None, "pergunta_promessa_ausente"

    prompt_sistema = _PROMPT_NUCLEO_COMPACTO_PATH.read_text(encoding="utf-8")
    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_NUCLEO_COMPACTO,
            system=prompt_sistema,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Idioma exigido para a resposta: {idioma}\n\n"
                        f"Pergunta-promessa: {pergunta_promessa}"
                    ),
                }
            ],
            tools=[SCHEMA_NUCLEO_COMPACTO],
            tool_choice={"type": "tool", "name": NOME_TOOL_NUCLEO_COMPACTO},
        )
    except Exception as exc:
        logger.warning("extrair_nucleo_compacto: chamada a API falhou: %s", exc, exc_info=True)
        return None, _detalhar_excecao(exc)

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_NUCLEO_COMPACTO)
    if not isinstance(dados, dict):
        return None, "resposta_invalida"

    nucleo = dados.get("nucleo_compacto")
    if not isinstance(nucleo, str) or not (2 <= _contar_palavras(nucleo) <= 8):
        return None, "nucleo_invalido"

    return nucleo.strip(), None


# ---------------------------------------------------------------------------
# Orquestracao (Grupos A-F) + persistencia (Grupo E)
# ---------------------------------------------------------------------------


def _ler_contexto(pasta_projeto: Path) -> dict:
    """Le job_metadata.json (nucleo_editorial/status/pergunta_promessa/
    idioma) e titulo.txt. Ausencia de qualquer um deles e' tratada com
    graca - projeto antigo ou fluxo incompleto nao derruba o Headline
    Engine (CLAUDE.md secao 18.6/18.4), so' faz o modo degradado
    (Grupo F) entrar em acao.

    `idioma`: mesma cascata que server.py ja usa em outro lugar pra
    resolver o idioma de um projeto (job_metadata.get("idioma") or
    IDIOMA_ROTEIRO or default)."""
    job_metadata = _ler_dict_json_ou_none(pasta_projeto / "job_metadata.json") or {}
    caminho_titulo = pasta_projeto / "titulo.txt"
    titulo_aprovado = ""
    if caminho_titulo.exists():
        try:
            titulo_aprovado = caminho_titulo.read_text(encoding="utf-8").strip()
        except OSError:
            titulo_aprovado = ""
    import os

    return {
        "nucleo_editorial": job_metadata.get("nucleo_editorial"),
        "nucleo_editorial_status": job_metadata.get("nucleo_editorial_status") or "ausente",
        "pergunta_promessa": job_metadata.get("pergunta_promessa") or "",
        "titulo_aprovado": titulo_aprovado,
        "idioma": job_metadata.get("idioma") or os.environ.get("IDIOMA_ROTEIRO") or IDIOMA_PADRAO,
    }


def _persistir_auditoria(pasta_thumbnail: Path, auditoria: dict) -> None:
    pasta_thumbnail.mkdir(parents=True, exist_ok=True)
    (pasta_thumbnail / "headline_engine.json").write_text(
        json.dumps(auditoria, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def gerar_headline(
    pasta_projeto: Path,
    roteiro_texto: str,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> dict:
    """Ponto de entrada do Headline Engine. Roda Grupos A-F, persiste
    `thumbnail/headline_engine.json` (Grupo E) sempre que ao menos uma
    Grupo B (candidatos) foi tentada, e devolve o bloco a ser mesclado no
    `thumbnail` de metadados.json:
    `{"headline": str, "mechanism": str, "withheld_fact": str,
    "emphasis_word": str, "judge_score": int|None, "conclusao_central":
    str, "payload": str, "payload_role": str, "hidden_question": str,
    "nucleo_editorial_status": str, "fallback_usado": bool,
    "aviso_revisao_humana": bool, "fallback_sem_julgamento": bool,
    "payload_extracao_fallback": bool}`.

    Nunca levanta excecao nem falha o pipeline por causa do headline -
    `{"sucesso": False, "erro": ...}` so' acontece se nem uma rodada
    completa de Grupo B (candidatos) conseguir rodar (sem cliente, ou API
    fora do ar) - caso em que o chamador (scripts/7_thumbnail.py) mantem
    qualquer headline anterior/fallback simples, igual ja fazia antes
    desta feature existir. A Grupo A (payload) NUNCA causa essa falha
    sozinha - se ela falhar, `_payload_fallback` degrada com gracaa e o
    pipeline segue pra' Grupo B normalmente.

    Falha do JUIZ (Grupo C) e' tratada separado de "nenhum candidato
    passou do limiar" (correcao da v1, preservada): falha do juiz e'
    erro de INFRAESTRUTURA (API fora do ar, parametro invalido) - gastar
    uma segunda rodada inteira de Grupo B (geracao de candidatos novos)
    nao tem chance nenhuma de resolver um problema que esta' na chamada
    do juiz, so' desperdica uma chamada. Por isso, falha do juiz
    interrompe o loop imediatamente (sem regeneracao) e cai direto no
    fallback abaixo. `fallback_sem_julgamento=True` no resultado
    distingue esse caso de `aviso_revisao_humana=True` sozinho (que
    tambem cobre "foi avaliado mas nenhum candidato passou do limiar de
    aprovacao")."""
    contexto = _ler_contexto(pasta_projeto)
    pasta_thumbnail = pasta_projeto / "thumbnail"

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return {"sucesso": False, "erro": "cliente_indisponivel"}

    custos_locais: list = []

    fallback_usado = False
    nucleo_editorial = contexto["nucleo_editorial"]
    if contexto["nucleo_editorial_status"] == "ausente" or not nucleo_editorial:
        fallback_usado = True
        nucleo_compacto, erro_nucleo = extrair_nucleo_compacto(
            cliente_api, modelo, contexto["pergunta_promessa"], contexto["idioma"], custos_locais
        )
        nucleo_editorial = nucleo_compacto or (contexto["pergunta_promessa"] or "")[:80]
    else:
        erro_nucleo = None

    # GRUPO A - roda UMA vez, antes de qualquer rodada de candidatos.
    # Falha nunca bloqueia - degrada com _payload_fallback.
    payload_editorial, erro_payload = extrair_payload_editorial(
        cliente_api, modelo, nucleo_editorial, contexto["pergunta_promessa"],
        contexto["titulo_aprovado"], roteiro_texto, contexto["idioma"], custos_locais,
    )
    payload_extracao_fallback = payload_editorial is None
    if payload_editorial is None:
        payload_editorial = _payload_fallback(nucleo_editorial, contexto["pergunta_promessa"])

    rodadas_auditoria = []
    feedback = None
    vencedor_final = None
    julgamento_vencedor = None
    aprovado = False
    erro_geral = None
    juiz_falhou_com_sobreviventes = False

    for numero_rodada in range(1, MAX_RODADAS_CANDIDATOS + 1):
        candidatos, erro_candidatos = gerar_candidatos_headline(
            cliente_api,
            modelo,
            payload_editorial,
            contexto["titulo_aprovado"],
            roteiro_texto,
            feedback_regeneracao=feedback,
            idioma=contexto["idioma"],
            _custos=custos_locais,
        )
        if candidatos is None:
            erro_geral = erro_candidatos
            rodadas_auditoria.append({"rodada": numero_rodada, "erro": erro_candidatos})
            break

        sobreviventes_formato, eliminados_formato = filtrar_candidatos_deterministicos(
            candidatos, contexto["titulo_aprovado"]
        )
        sobreviventes, eliminados_semanticos = filtrar_candidatos_semanticos(
            sobreviventes_formato, payload_editorial
        )
        eliminados = eliminados_formato + eliminados_semanticos

        julgamentos = None
        erro_julgamento = None
        if sobreviventes:
            julgamentos, erro_julgamento = julgar_candidatos(
                cliente_api, modelo, sobreviventes, contexto["titulo_aprovado"],
                payload_editorial.get("conclusao_central", ""), custos_locais,
            )

        rodada_info = {
            "rodada": numero_rodada,
            "candidatos_gerados": candidatos,
            "mecanismos_distintos_gerados": contar_mecanismos_distintos(candidatos),
            "eliminados": eliminados,
            "eliminados_formato": eliminados_formato,
            "eliminados_semanticos": eliminados_semanticos,
            "sobreviventes": sobreviventes,
            "julgamentos": julgamentos,
            "erro_julgamento": erro_julgamento,
        }
        rodadas_auditoria.append(rodada_info)

        if sobreviventes and julgamentos:
            indice_vencedor, aprovado = selecionar_vencedor(sobreviventes, julgamentos)
            if aprovado:
                vencedor_final = sobreviventes[indice_vencedor]
                julgamento_vencedor = julgamentos[indice_vencedor]
                break
            feedback = _montar_feedback_regeneracao(sobreviventes, julgamentos)
        elif sobreviventes:
            # Juiz falhou (erro de infraestrutura, ver julgar_candidatos) -
            # NUNCA dispara uma rodada extra de geracao (bug corrigido
            # na v1, pos-Sessao 24). Para o loop aqui mesmo e cai no
            # fallback logo abaixo.
            juiz_falhou_com_sobreviventes = True
            break
        else:
            feedback = _montar_feedback_filtros(eliminados)

    aviso_revisao_humana = False
    if vencedor_final is None:
        todos_candidatos_vistos = []
        todos_julgamentos_vistos = []
        houve_alguma_geracao = False
        for r in rodadas_auditoria:
            if r.get("candidatos_gerados"):
                houve_alguma_geracao = True
            for c in r.get("sobreviventes") or []:
                todos_candidatos_vistos.append(c)
            for j in r.get("julgamentos") or []:
                todos_julgamentos_vistos.append(j)
            if not r.get("sobreviventes") and r.get("candidatos_gerados"):
                # Nenhum sobrevivente nesta rodada - ainda assim guarda os
                # brutos como ultimo recurso (rede de seguranca final).
                todos_candidatos_vistos.extend(r["candidatos_gerados"])

        if not houve_alguma_geracao:
            # Nenhuma rodada conseguiu sequer gerar candidatos (Grupo B
            # falhou logo de cara, ou falhou de novo numa retentativa sem
            # nunca ter produzido nada antes) - nao ha' nada pra persistir,
            # devolve o erro real em vez de mascarar como "sem candidato".
            return {"sucesso": False, "erro": erro_geral or "nenhum_candidato_disponivel"}

        vencedor_final, julgamento_vencedor = _melhor_candidato_sem_aprovacao(
            todos_candidatos_vistos,
            todos_julgamentos_vistos if len(todos_julgamentos_vistos) == len(todos_candidatos_vistos) else None,
        )
        aviso_revisao_humana = True

    if vencedor_final is None:
        return {"sucesso": False, "erro": "nenhum_candidato_disponivel"}

    if _custos is not None:
        _custos.extend(custos_locais)

    # Bug corrigido na v1 (pos-Sessao 24, item 3): distingue "vencedor
    # nunca foi avaliado por ninguem" (juiz falhou, ou nao rodou) de
    # aviso_revisao_humana sozinho (que tambem cobre "foi avaliado mas
    # ficou abaixo do limiar de aprovacao") - a tela de thumbnail precisa
    # saber qual dos dois pra nao mostrar so' um aviso generico.
    fallback_sem_julgamento = julgamento_vencedor is None

    resultado = {
        "sucesso": True,
        "headline": vencedor_final["headline"],
        "mechanism": vencedor_final["mechanism"],
        "withheld_fact": vencedor_final["withheld_fact"],
        "emphasis_word": vencedor_final["emphasis_word"],
        "judge_score": julgamento_vencedor["total"] if julgamento_vencedor else None,
        "conclusao_central": payload_editorial.get("conclusao_central", ""),
        "payload": payload_editorial.get("payload", ""),
        "payload_role": payload_editorial.get("payload_role", ""),
        "hidden_question": payload_editorial.get("hidden_question", ""),
        "conceito_visual": payload_editorial.get("conceito_visual") or _conceito_visual_fallback(nucleo_editorial),
        "nucleo_editorial_status": contexto["nucleo_editorial_status"],
        "fallback_usado": fallback_usado,
        "aviso_revisao_humana": aviso_revisao_humana,
        "fallback_sem_julgamento": fallback_sem_julgamento,
        "payload_extracao_fallback": payload_extracao_fallback,
    }

    auditoria = {
        "versao_prompt": VERSAO_PROMPT,
        "nucleo_editorial_status": contexto["nucleo_editorial_status"],
        "nucleo_editorial_usado": nucleo_editorial,
        "idioma_usado": contexto["idioma"],
        "fallback_usado": fallback_usado,
        "erro_nucleo_compacto": erro_nucleo,
        "titulo_aprovado": contexto["titulo_aprovado"],
        # GRUPO D (auditoria por etapa) - as tres etapas separadas: payload
        # extraido (Grupo A, uma vez), candidatos por mecanismo + juiz por
        # rodada (rodadas[] ja carrega candidatos_gerados/eliminados_*/
        # sobreviventes = Grupo B/C rejeicao, e julgamentos = Grupo C juiz).
        "payload_editorial": payload_editorial,
        "payload_extracao_fallback": payload_extracao_fallback,
        "erro_payload_editorial": erro_payload,
        "rodadas": rodadas_auditoria,
        "numero_rodadas": len(rodadas_auditoria),
        "juiz_falhou_com_sobreviventes": juiz_falhou_com_sobreviventes,
        "vencedor": resultado,
        "aviso_revisao_humana": aviso_revisao_humana,
        "fallback_sem_julgamento": fallback_sem_julgamento,
        "custo_usd": round(sum(custos_locais), 6),
    }
    _persistir_auditoria(pasta_thumbnail, auditoria)

    return resultado
