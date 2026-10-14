"""Etapa 7 (simplificada) do pipeline - geracao de thumbnail para YouTube.
Roda DEPOIS da Etapa 6 (montagem), com o processo do ffmpeg ja encerrado -
nao concorre por CPU com nenhum outro subprocess do pipeline.

Uso: python "scripts/7_thumbnail.py" <caminho_da_pasta_do_projeto>

SIMPLIFICACAO DESTA SESSAO (ver HISTORICO_BUGS.md): os 5 templates de
composicao via Pillow (`scripts/thumbnail_templates.py`) foram REMOVIDOS
por inteiro - resultado muito abaixo das referencias reais do nicho em
teste real. O caminho validado e': o Claude gera o briefing exportavel
(Grupo C), o usuario edita se quiser, e a OpenAI (`scripts/imagem/
openai.gerar_composicao`) compoe a thumbnail final a partir do briefing +
fotos dos sujeitos - acao explicita do usuario na tela, quantas vezes
quiser, comparando as composicoes acumuladas.

Foram junto: o scan de frames de CENARIO (`thumbnail/candidatos_cena/`,
existia so' pra alimentar o fundo dos templates Pillow) e o recorte de
sujeito via `rembg` (existia so' pra' produzir o PNG com fundo removido
que os templates Pillow colavam - a composicao por IA manda a foto
ORIGINAL, sem recorte, direto pro modelo).

RECONSTRUCAO ANTERIOR (sessao pos-Sessao 26, preservada nesta
simplificacao): a arquitetura de identificacao automatica (grid de
candidatos extraidos dos CLIPES via Haar cascade + Vision decidindo qual
rosto era o sujeito) foi REMOVIDA - resultado ruim em teste real (achado
documentado, projeto NancyGuthrieProject01: Vision escolhia a
apresentadora de telejornal em vez da vitima, porque a decisao de
identidade rodava sobre frames de b-roll, nao sobre uma foto que o usuario
ja sabia de quem era). A substituicao, que continua valendo: o usuario faz
upload de ate 2 fotos (`thumbnail/sujeitos/`) DECLARANDO o papel de cada
uma (vitima/suspeito/condenado/investigador/testemunha/outro) - Vision
nunca decide "quem e' quem", so' opcionalmente extrai atributos visuais
(Grupo C, scripts/thumbnail_briefing.py) de uma foto cujo papel ja' e'
conhecido.

GRUPO B - upload de sujeitos com papel declarado: `atualizar_sujeito_slot`/
`remover_sujeito_slot` abaixo - cascata de 2 slots (hero/secondary), cada
um com papel obrigatorio, persistidos em thumbnail/sujeitos/sujeitos.json.
Sem recorte nenhum - a foto ORIGINAL enviada e' o que a composicao por IA
usa direto.

GRUPO C - briefing exportavel: scripts/thumbnail_briefing.py monta
`thumbnail.briefing_completo` - um prompt em ingles pronto pra colar em
qualquer gerador de imagem, combinando o headline vencedor (Headline
Engine), os papeis/atributos dos sujeitos enviados, e um dos 5 templates de
composicao (ARROW_TRIO/PROFILE_ISOLATION/EVIDENCE_SCENE/DUOTONE_DOSSIER/
INVESTIGATOR_UPDATE - escolhido por chamada dedicada com enum fechado ao
subconjunto elegivel pras fotos disponiveis, ou forcado explicitamente
pelo usuario na tela). Funciona 100% sem nenhuma API de imagem configurada
- e' a entrega que sempre funciona pra uso externo.

GRUPO D - metadados: chamada UNICA (nao-streaming, tool_choice forcado -
sem precedente de streaming real em NENHUMA chamada Claude do projeto,
achado confirmado por grep em sessao anterior) usando roteiro_aprovado.md
como input (marcado com cache_control), produz descricao/tags do video +
o briefing de composicao da thumbnail. Persiste thumbnail/metadados.json
com um hash do roteiro usado - `metadados_desatualizados()` detecta
edicao posterior do roteiro sem regerar sozinho (decisao sempre do
usuario).

**Titulo do video: FONTE UNICA DE VERDADE (sessao "titulo canonico -
Burke Ramsey").** Ate esta correcao, o Grupo D pedia a' IA 3 titulos
NOVOS e independentes (mesmo schema que o roteiro/Etapa 3 ja usa),
persistidos em `metadados.json["title"]` e exibidos na tela de conclusao
ao lado do titulo realmente escolhido pelo usuario na revisao do roteiro
(`titulo.txt`) - dois conjuntos concorrentes representando o mesmo
conceito editorial (achado real, projeto jonBenetRamsey01/Burke Ramsey:
usuario escolheu "What the 1999 DNA Test Really Proved..." na revisao, a
Etapa 7 gerou "The DNA Evidence CBS Never Told You About" e mais dois,
titulo escolhido nunca aparecia na conclusao). O Grupo D NAO gera mais
titulo nenhum - `titulo_escolhido` (lido de `titulo.txt`, Etapa 3/5.5) e'
persistido tal como esta' no disco, nunca gerado/reescrito aqui;
`titulos_alternativos` (as outras 2 opcoes de `titulos_sugeridos.json`,
Etapa 3) fica so' como referencia editorial, nunca tratado como titulo
candidato a substituir a escolha do usuario.

GRUPO H (composicao completa por IA): scripts/imagem/openai.gerar_composicao
- unico caminho de renderizacao real hoje. Acao explicita do usuario
(botao na tela de thumbnail, cada clique custa uma chamada real), exige
OPENAI_API_KEY. Composicoes acumulam em thumbnail/previews/ (nunca se
sobrescrevem) ate' o usuario escolher uma como thumbnail final.

RECONCILIACAO TITULO<->HEADLINE (sessao "coordenacao entre titulo e
headline", ajustada na sessao "titulo canonico"): `reconciliar_titulos_com_headline`
roda logo depois de `_mesclar_headline_em_thumbnail` (tanto em `gerar_metadados`
quanto em `regenerar_thumbnail_briefing`) - reavalia `titulo_escolhido`
(unico, nunca mais os 3 gerados pelo Grupo D) contra o headline FINAL e
devolve uma AUDITORIA (`titulo_headline_reconciliacao`, persistida pra'
avisar o usuario se o titulo aprovado colide com o que o headline
esconde). A auditoria NUNCA sobrescreve `titulo_escolhido` - o titulo
aprovado pelo usuario e' soberano, nenhuma etapa posterior pode trocá-lo
em silencio. Implementado inteiramente aqui, nunca em
scripts/headline_engine.py (restricao explicita da sessao) - o Headline
Engine continua responsavel so' por nunca repetir titulo.txt no
headline, sem saber nada sobre esta auditoria.
"""

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import anthropic
except ImportError:
    anthropic = None

# scripts/7_thumbnail.py precisa da RAIZ do projeto no sys.path (nao so
# scripts/) porque scripts/thumbnail_briefing.py importa `from scripts
# import ...` - mesma convencao que scripts/3_gerar_roteiro.py e
# scripts/4_obter_audio.py ja usam. Quando este script roda standalone
# (`python scripts/7_thumbnail.py <pasta>`, como server.py faz via
# subprocess), a raiz nao entra no sys.path sozinha - sem isso, `from
# scripts import ...` falha com ModuleNotFoundError antes de qualquer linha
# do pipeline rodar. Quando carregado via importlib nos testes, a raiz ja
# esta' no sys.path por causa de tests/conftest.py, e o insert aqui e'
# inofensivo (sys.path aceita duplicatas sem efeito colateral).
_RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ_PROJETO))

from scripts import headline_engine, thumbnail_briefing  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MODELO_PADRAO = "claude-sonnet-5"
MAX_TOKENS_RESPOSTA = 1024

# Precos por milhao de tokens do Sonnet - duplicado de
# scripts/sincronizador_visual.py / scripts/3_gerar_roteiro.py de proposito
# (CLAUDE.md secao 9 - scripts autocontidos, sem utils compartilhado).
CUSTO_INPUT_POR_MILHAO_USD = 3.0
CUSTO_OUTPUT_POR_MILHAO_USD = 15.0

PAPEIS_SUJEITO_VALIDOS = ("vitima", "suspeito", "condenado", "investigador", "testemunha", "outro")


# ---------------------------------------------------------------------------
# Progresso (CLAUDE.md secao 9 - convencao @PROGRESSO)
# ---------------------------------------------------------------------------


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


# ---------------------------------------------------------------------------
# Leitura de entrada
# ---------------------------------------------------------------------------


def _ler_lista_json(caminho: Path) -> list:
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return dados if isinstance(dados, list) else []


def _ler_lista_clipes(caminho: Path) -> list:
    """Le clipes/indice.json tolerando os dois formatos existentes:
    lista pura (formato de fixture antigo) ou dict com envelope
    `{"clipes": [...], "metadata": {...}}` - o formato REAL gravado por
    5_gerar_clipes.py (CLAUDE.md secao 5.7). Nao alterar o formato
    gravado pela Etapa 5 (6_montar_video.py e a tela de reorganizacao
    ja consomem o dict) - so' tolerar os dois na leitura aqui."""
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(dados, list):
        return dados
    if isinstance(dados, dict):
        clipes = dados.get("clipes")
        if isinstance(clipes, list):
            return clipes
    return []


def _ler_dict_json_ou_none(caminho: Path):
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return dados if isinstance(dados, dict) else None


# ---------------------------------------------------------------------------
# Pre-condicoes (CLAUDE.md secao 18.6)
# ---------------------------------------------------------------------------


def _validar_pre_condicoes(pasta_projeto: Path):
    if not pasta_projeto.exists():
        return False, "Pasta do projeto nao encontrada.", "pasta_ausente"

    clipes = _ler_lista_clipes(pasta_projeto / "clipes" / "indice.json")
    if not clipes:
        return (
            False,
            "clipes/indice.json nao encontrado ou vazio. Rode a Etapa 5 (geracao de clipes) antes desta etapa.",
            "clipes_ausentes",
        )

    if not (pasta_projeto / "saida" / "video_final.mp4").exists():
        return (
            False,
            "saida/video_final.mp4 nao encontrado. Rode a Etapa 6 (montagem) antes desta etapa.",
            "video_final_ausente",
        )

    return True, None, None


# ---------------------------------------------------------------------------
# Helpers de chamada de API
# ---------------------------------------------------------------------------


def _valor(obj, chave, default=None):
    """Le `chave` de `obj` seja ele um dict (fakes de teste) ou um objeto
    com atributos (respostas reais do SDK anthropic) - duplicado de
    scripts/sincronizador_visual.py de proposito (CLAUDE.md secao 9)."""
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
    """Duplicado de scripts/sincronizador_visual.py de proposito. Nunca
    levanta excecao."""
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
# GRUPO B - upload de sujeitos (hero/secondary) com papel declarado
# ---------------------------------------------------------------------------

SLOTS_SUJEITO = ("hero", "secondary")


def _ler_sujeitos_json(pasta_thumbnail: Path) -> dict:
    dados = _ler_dict_json_ou_none(pasta_thumbnail / "sujeitos" / "sujeitos.json") or {}
    return {"hero": dados.get("hero"), "secondary": dados.get("secondary")}


def atualizar_sujeito_slot(pasta_projeto: Path, slot: str, arquivo: str, papel: str) -> dict:
    """GRUPO B: grava/atualiza um slot (hero|secondary) em
    thumbnail/sujeitos/sujeitos.json - `arquivo` e' o nome (sem caminho) do
    arquivo ja salvo em thumbnail/sujeitos/ (server.py salva o upload ANTES
    de chamar esta funcao) e `papel` tem que estar em
    PAPEIS_SUJEITO_VALIDOS. Nunca levanta excecao - `slot`/`papel`
    invalidos devolvem `{"sucesso": False, "erro": ...}` sem tocar no
    arquivo em disco."""
    if slot not in SLOTS_SUJEITO:
        return {"sucesso": False, "erro": "slot_invalido"}
    if papel not in PAPEIS_SUJEITO_VALIDOS:
        return {"sucesso": False, "erro": "papel_invalido"}

    pasta_sujeitos = pasta_projeto / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True, exist_ok=True)
    dados = _ler_sujeitos_json(pasta_projeto / "thumbnail")
    dados[slot] = {"arquivo": arquivo, "papel": papel}
    (pasta_sujeitos / "sujeitos.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"sucesso": True, "sujeitos": dados}


def remover_sujeito_slot(pasta_projeto: Path, slot: str) -> dict:
    """GRUPO B: esvazia um slot (o arquivo original em thumbnail/sujeitos/
    fica orfao em disco de proposito - nunca deletamos arquivo enviado pelo
    usuario sem pedido explicito - so' para de aparecer em sujeitos.json).
    Nunca levanta excecao."""
    if slot not in SLOTS_SUJEITO:
        return {"sucesso": False, "erro": "slot_invalido"}

    pasta_thumbnail = pasta_projeto / "thumbnail"
    dados = _ler_sujeitos_json(pasta_thumbnail)
    dados[slot] = None
    pasta_sujeitos = pasta_thumbnail / "sujeitos"
    pasta_sujeitos.mkdir(parents=True, exist_ok=True)
    (pasta_sujeitos / "sujeitos.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"sucesso": True, "sujeitos": dados}


# ---------------------------------------------------------------------------
# GRUPO D - metadados (titulo/descricao/tags + briefing da thumbnail)
# ---------------------------------------------------------------------------

_PROMPT_METADADOS_PATH = Path(__file__).resolve().parent / "prompts" / "metadados_thumbnail.md"

MAX_TOKENS_RESPOSTA_METADADOS = 2048

ACCENTS_VALIDOS = ("red", "amber", "blue")

ACCENT_PADRAO = "red"

# Criterio OBJETIVO (nunca subjetivo) pra' considerar um background_prompt
# utilizavel: apos strip(), precisa ter pelo menos este tanto de
# caracteres. Escolhido pra' descartar so' o caso degenerado (string
# vazia/so' espaco) sem rejeitar uma descricao curta mas valida. Duplicado
# de scripts/thumbnail_briefing.py de proposito (CLAUDE.md secao 9 -
# scripts autocontidos) - vivia em scripts/thumbnail_templates.py antes da
# remocao dos templates Pillow (ver HISTORICO_BUGS.md).
BACKGROUND_PROMPT_MIN_CHARS = 20


def background_prompt_valido(texto: str) -> bool:
    """True se `texto` tem conteudo real o suficiente pra' servir de
    briefing de fundo (ver BACKGROUND_PROMPT_MIN_CHARS). Nunca levanta
    excecao - `texto` None vira False."""
    return bool(texto) and len((texto or "").strip()) >= BACKGROUND_PROMPT_MIN_CHARS


NOME_TOOL_METADADOS = "entregar_metadados"
SCHEMA_METADADOS = {
    "name": NOME_TOOL_METADADOS,
    "description": (
        "Entrega descricao/tags do video e o briefing de composicao da thumbnail. "
        "O titulo do video ja foi escolhido pelo usuario na revisao do roteiro "
        "(Etapa 3/5.5) - nao e' pedido aqui."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "thumbnail": {
                "type": "object",
                "properties": {
                    "subject_name": {"type": "string"},
                    "headline": {"type": "string"},
                    "emphasis_word": {"type": "string"},
                    "secondary": {"type": "string"},
                    "accent": {"type": "string", "enum": list(ACCENTS_VALIDOS)},
                    "censor": {"type": "boolean"},
                    "background_prompt": {"type": "string"},
                },
                "required": [
                    "subject_name",
                    "headline",
                    "emphasis_word",
                    "secondary",
                    "accent",
                    "censor",
                    "background_prompt",
                ],
            },
        },
        "required": ["description", "tags", "thumbnail"],
    },
}


def _normalizar_thumbnail_metadados(dados: dict) -> dict:
    """Aplica os fallbacks de enum/consistencia do briefing de thumbnail:
    accent fora da lista cai no padrao; emphasis_word que nao aparece
    LITERALMENTE dentro de headline e' ignorada (vira ""). Funcao pura,
    sem I/O - reusada tanto na geracao via IA (`gerar_metadados`) quanto
    (Grupo G, tela) na edicao manual do usuario, que precisa respeitar os
    mesmos fallbacks."""
    dados = dict(dados or {})

    accent = dados.get("accent")
    dados["accent"] = accent if accent in ACCENTS_VALIDOS else ACCENT_PADRAO

    headline = dados.get("headline") or ""
    emphasis_word = dados.get("emphasis_word") or ""
    if not emphasis_word.strip() or emphasis_word not in headline:
        emphasis_word = ""

    dados["headline"] = headline
    dados["emphasis_word"] = emphasis_word
    dados["secondary"] = dados.get("secondary") or ""
    dados["subject_name"] = dados.get("subject_name") or ""
    dados["censor"] = bool(dados.get("censor"))
    dados["background_prompt"] = dados.get("background_prompt") or ""

    return dados


def _hash_roteiro(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def validar_consistencia_headline_conceito(thumbnail_normalizado: dict) -> dict:
    """Validacao de consistencia headline<->conceito (codigo puro, sessao
    "conceito visual") - roda entre o Grupo D (metadados/background_
    prompt) e o Grupo C (briefing), nunca bloqueia o pipeline. Substitui
    `_eixo_editorial_vazio` (mecanismo antigo, removido - ver
    HISTORICO_BUGS.md): em vez de checar 3 campos derivados de um
    cabecalho injetado de volta no roteiro, confere que o
    `elemento_principal` do conceito visual (extraido pela Grupo A do
    Headline Engine, ja mesclado em `thumbnail_normalizado` nesse ponto -
    ver `_mesclar_headline_em_thumbnail`) nao veio vazio. Vazio significa
    que o briefing (Grupo C) nao tem ancora nenhuma pra' montar a cena em
    cima, mesmo com headline/background_prompt presentes - persistido
    honestamente (`conceito_visual_ausente`), nunca escondido (CLAUDE.md
    secao 18.4), pra' a tela de thumbnail avisar o usuario."""
    conceito_visual = thumbnail_normalizado.get("conceito_visual") or {}
    elemento_principal = (conceito_visual.get("elemento_principal") or "").strip()
    return {"conceito_visual_ausente": not elemento_principal}


def _reparar_thumbnail_normalizado(
    cliente_api,
    modelo: str,
    roteiro_texto: str,
    eixo_base: dict,
    thumbnail_normalizado: dict,
    _custos: list | None,
    elemento_principal: str = "",
) -> dict:
    """Tenta UMA chamada extra de `_chamar_claude_metadados` quando
    `background_prompt` veio trivial (`background_prompt_valido`).

    Sessao "conceito visual": o reparo do EIXO EDITORIAL vazio
    (evidencia_central/conflito/data_chave) foi removido junto da remocao
    desses 3 campos (ver HISTORICO_BUGS.md) - o `elemento_principal`, que
    agora chega aqui como parametro (extraido ANTES desta chamada pela
    Grupo A do Headline Engine), ja' e' a ancora obrigatoria do
    `background_prompt` na propria chamada original (scripts/prompts/
    metadados_thumbnail.md), entao nao ha' mais um campo "vazio apesar de
    ancora disponivel" pra' reparar separadamente.

    So' adota do reparo o `background_prompt` se ele efetivamente
    melhorou - nunca substitui o dict inteiro pelo da segunda chamada,
    preservando o que a primeira ja' acertou. Nenhuma tentativa (nem a
    original nem o reparo) bloqueia o pipeline - se continuar trivial,
    `thumbnail_normalizado` volta como veio, e o chamador persiste esse
    estado honestamente (nunca finge que deu certo)."""
    bg_invalido = not background_prompt_valido(thumbnail_normalizado.get("background_prompt", ""))
    if not bg_invalido:
        return thumbnail_normalizado

    logger.info("_reparar_thumbnail_normalizado: background_prompt trivial na primeira geracao - tentando reparo unico.")

    dados_reparo, _erro_reparo = _chamar_claude_metadados(
        cliente_api, modelo, roteiro_texto, _custos,
        titulo_aprovado=eixo_base.get("titulo_aprovado", ""), nucleo_editorial=eixo_base.get("nucleo_editorial", ""),
        elemento_principal=elemento_principal,
    )
    if dados_reparo is None:
        return thumbnail_normalizado

    thumbnail_reparado = _normalizar_thumbnail_metadados(dados_reparo.get("thumbnail") or {})
    if background_prompt_valido(thumbnail_reparado.get("background_prompt", "")):
        thumbnail_normalizado["background_prompt"] = thumbnail_reparado["background_prompt"]
    return thumbnail_normalizado


def _mesclar_headline_em_thumbnail(thumbnail_normalizado: dict, resultado_headline: dict) -> dict:
    """Mescla o resultado do Headline Engine (`headline_engine.gerar_
    headline`, ja' executado ANTES desta chamada - ver `gerar_metadados`/
    `regenerar_thumbnail_briefing`) no dict de thumbnail ja' normalizado
    pela chamada de metadados (Grupo D). Substitui `_aplicar_headline_
    engine` (removido - ver HISTORICO_BUGS.md): a MESMA logica de merge,
    so' que sem rodar `gerar_headline` aqui dentro (agora roda antes, sem
    depender de `thumbnail_normalizado` - ver sessao "conceito visual").

    Headline Engine indisponivel (sem chave/cliente) ou com falha na
    PRIMEIRA chamada (`sucesso: False`) mantem o `headline`/
    `emphasis_word` que ja' vieram da chamada unica de metadados - nunca
    apaga um headline utilizavel so' porque o motor novo nao rodou
    (CLAUDE.md secao 18.4). Falha so' depois da primeira chamada (juiz
    fora do ar, por exemplo) ja' e' tratada dentro do proprio
    `headline_engine.gerar_headline` (persiste o melhor candidato
    disponivel com aviso de revisao humana, sempre com `sucesso: True`)."""
    if not resultado_headline.get("sucesso"):
        logger.info(
            "_mesclar_headline_em_thumbnail: Headline Engine nao rodou (%s) - mantendo headline da chamada de metadados.",
            resultado_headline.get("erro"),
        )
        thumbnail_normalizado.setdefault("mechanism", None)
        thumbnail_normalizado.setdefault("withheld_fact", None)
        thumbnail_normalizado.setdefault("judge_score", None)
        thumbnail_normalizado.setdefault("nucleo_editorial_status", None)
        thumbnail_normalizado.setdefault("fallback_usado", False)
        thumbnail_normalizado.setdefault("fallback_sem_julgamento", False)
        thumbnail_normalizado.setdefault("conceito_visual", None)
        return thumbnail_normalizado

    headline = resultado_headline["headline"]
    emphasis_word = resultado_headline["emphasis_word"] or ""
    # Defesa (ultimo recurso): o vencedor pode vir de um candidato bruto
    # nunca filtrado (todos eliminados nas duas rodadas) - reaplica a
    # MESMA regra de _normalizar_thumbnail_metadados antes de persistir,
    # nunca confia que emphasis_word ja' e' substring valida.
    if not emphasis_word.strip() or emphasis_word not in headline:
        emphasis_word = ""

    thumbnail_normalizado["headline"] = headline
    thumbnail_normalizado["emphasis_word"] = emphasis_word
    thumbnail_normalizado["mechanism"] = resultado_headline["mechanism"]
    thumbnail_normalizado["withheld_fact"] = resultado_headline["withheld_fact"]
    thumbnail_normalizado["judge_score"] = resultado_headline["judge_score"]
    thumbnail_normalizado["nucleo_editorial_status"] = resultado_headline["nucleo_editorial_status"]
    thumbnail_normalizado["fallback_usado"] = resultado_headline["fallback_usado"]
    thumbnail_normalizado["aviso_revisao_humana"] = resultado_headline["aviso_revisao_humana"]
    thumbnail_normalizado["fallback_sem_julgamento"] = resultado_headline.get("fallback_sem_julgamento", False)
    thumbnail_normalizado["conceito_visual"] = resultado_headline.get("conceito_visual")
    return thumbnail_normalizado


# ---------------------------------------------------------------------------
# Reconciliacao titulo <-> headline (sessao "coordenacao entre titulo e
# headline", ajustada na sessao "titulo canonico") - NUNCA implementada
# dentro de scripts/headline_engine.py de proposito (restricao explicita
# da sessao): o Headline Engine ja evita repetir titulo.txt (o titulo
# escolhido na revisao do roteiro, Etapa 3 - ver
# headline_engine._ler_contexto/gerar_candidatos_headline). Este bloco
# fecha a lacuna inversa - o titulo aprovado pode, por si so', revelar o
# que o headline deliberadamente esconde (achado real: titulo "What the
# Wrist Tattoo Actually Reveals" ao lado do headline "THE MARK ON HIS
# WRIST" - titulo entregando o proprio elemento visual que o headline usa
# como lacuna) - SEM tocar em headline_engine.py.
#
# Ate a sessao "titulo canonico", esta funcao reescrevia os 3 titulos
# GERADOS PELO GRUPO D (thumbnail/metadados.json["title"]) - um conjunto
# concorrente independente do titulo que o usuario de fato escolheu na
# revisao (ver docstring do modulo, achado Burke Ramsey). O Grupo D nao
# gera titulo nenhum mais - esta funcao roda agora sobre uma lista de UM
# item so' (`[titulo_escolhido]`, lido de titulo.txt) e o resultado e'
# tratado como AUDITORIA apenas: o chamador NUNCA persiste `titulos_finais`
# como o titulo do projeto, so' guarda a auditoria (`titulo_headline_
# reconciliacao`) pra' eventualmente avisar o usuario. `titulo_escolhido`
# em si e' soberano e nunca e' sobrescrito por este bloco.
# ---------------------------------------------------------------------------

_PROMPT_TITULOS_HEADLINE_PATH = Path(__file__).resolve().parent / "prompts" / "titulos_headline_reconciliacao.md"
MAX_TOKENS_TITULOS_HEADLINE = 1024

NOME_TOOL_TITULOS_HEADLINE = "entregar_titulos_reconciliados"
SCHEMA_TITULOS_HEADLINE = {
    "name": NOME_TOOL_TITULOS_HEADLINE,
    "description": (
        "Devolve os titulos (reescrevendo so' os que colidem com o headline "
        "final da thumbnail) e uma nota de complementaridade (0-2) por titulo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "titles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "complementarity_score": {"type": "integer", "enum": [0, 1, 2]},
                        "motivo": {"type": "string"},
                    },
                    "required": ["title", "complementarity_score", "motivo"],
                },
            }
        },
        "required": ["titles"],
    },
}


def _ler_eixo_editorial_base(pasta_projeto: Path) -> dict:
    """Le `nucleo_editorial` (job_metadata.json, gerado na Etapa 3 -
    CLAUDE.md secao 5.4.1) e o titulo aprovado (titulo.txt, Etapa 3/5.5) -
    contexto de ANCORAGEM geral injetado na chamada de Grupo D
    (`_chamar_claude_metadados`) pra' o modelo derivar `background_prompt`/
    `secondary` do eixo editorial do video, nunca de qualquer detalhe
    chamativo solto no meio do roteiro inteiro (achado real que motivou
    esta correcao: briefing usando "the bowl nobody explains"/"the 2008
    exoneration letter" - detalhes tangenciais - em vez do teste de DNA de
    1999 que sustenta a promessa do titulo). Desde a sessao "conceito
    visual", a ancora MAIS forte do `background_prompt` e' o
    `elemento_principal` extraido pelo Headline Engine (ver
    `_chamar_claude_metadados`) - este eixo (titulo/nucleo) continua como
    contexto secundario, nunca removido.

    Duplicado do padrao ja usado por
    scripts/headline_engine.py:_ler_contexto (CLAUDE.md secao 9 - scripts
    autocontidos, sem utils compartilhado). Projeto antigo sem
    job_metadata.json/titulo.txt (validacao 9 do pedido) devolve strings
    vazias - nunca levanta excecao, nunca bloqueia a chamada de Grupo D."""
    job_metadata = _ler_dict_json_ou_none(pasta_projeto / "job_metadata.json") or {}
    caminho_titulo = pasta_projeto / "titulo.txt"
    titulo_aprovado = ""
    if caminho_titulo.exists():
        try:
            titulo_aprovado = caminho_titulo.read_text(encoding="utf-8").strip()
        except OSError:
            titulo_aprovado = ""
    return {
        "nucleo_editorial": job_metadata.get("nucleo_editorial") or "",
        "titulo_aprovado": titulo_aprovado,
    }


def _ler_titulos_alternativos(pasta_projeto: Path, titulo_escolhido: str) -> list:
    """Sessao "titulo canonico": le `titulos_sugeridos.json` (as 3 opcoes
    editoriais geradas na Etapa 3, CLAUDE.md secao 5.3) e devolve as que
    NAO foram escolhidas pelo usuario na revisao - nunca gera titulo novo
    aqui (Opcao A do pedido: a Etapa 7 nao compete com a Etapa 3). Projeto
    sem `titulos_sugeridos.json` (antigo, ou roteiro importado por upload)
    devolve lista vazia; titulo customizado digitado pelo usuario (nao
    bate com nenhuma das 3 opcoes) simplesmente nao exclui nada. Nunca
    levanta excecao."""
    dados = _ler_dict_json_ou_none(pasta_projeto / "titulos_sugeridos.json") or {}
    titulos = dados.get("titulos")
    if not isinstance(titulos, list):
        return []
    titulo_escolhido_norm = (titulo_escolhido or "").strip()
    return [
        str(t).strip()
        for t in titulos
        if str(t).strip() and str(t).strip() != titulo_escolhido_norm
    ]


def _idioma_do_projeto(pasta_projeto: Path) -> str:
    """Mesma cascata ja usada por scripts/headline_engine.py:_ler_contexto
    (job_metadata.json.idioma -> IDIOMA_ROTEIRO -> default) - duplicada de
    proposito (CLAUDE.md secao 9, scripts autocontidos)."""
    job_metadata = _ler_dict_json_ou_none(pasta_projeto / "job_metadata.json") or {}
    return job_metadata.get("idioma") or os.environ.get("IDIOMA_ROTEIRO") or "en-US"


def reconciliar_titulos_com_headline(
    cliente_api,
    modelo: str,
    titulos: list,
    headline: str,
    withheld_fact: str,
    emphasis_word: str,
    idioma: str,
    _custos: list | None = None,
) -> tuple:
    """Reavalia `titulos` contra o `headline` final (ja decidido pelo
    Headline Engine, nunca alterado aqui) e devolve, alem dos titulos
    reescritos, uma auditoria de complementaridade.

    Desde a sessao "titulo canonico", o chamador passa uma lista de UM
    item so' (`[titulo_escolhido]`) e usa o retorno SOMENTE como
    auditoria - `titulos_finais` (que pode vir reescrito pela IA) nunca e'
    persistido como o titulo do projeto; quem decide o titulo e' sempre o
    usuario, na revisao do roteiro. A funcao continua generica (aceita
    lista de qualquer tamanho) de proposito, pra' nao acoplar a assinatura
    a essa decisao de uso.

    Devolve `(titulos_finais, auditoria)` - NUNCA levanta excecao e NUNCA
    bloqueia o pipeline: sem titulo, sem headline, sem cliente, ou qualquer
    falha de API/resposta preserva `titulos` exatamente como vieram, so'
    registrando o motivo em `auditoria["erro"]` (mesmo espirito de
    `_mesclar_headline_em_thumbnail` - CLAUDE.md secao 18.4). `auditoria` e'
    persistida em thumbnail/metadados.json (Grupo F da sessao - nunca em
    headline_engine.json, que pertence so' ao Headline Engine)."""
    titulos_validos = [str(t).strip() for t in (titulos or []) if str(t).strip()]
    headline = (headline or "").strip()

    if not titulos_validos or not headline or cliente_api is None:
        return titulos_validos, {
            "executado": False,
            "motivo": "titulos_ou_headline_ou_cliente_ausente",
            "titulos_originais": titulos_validos,
        }

    prompt_sistema = _PROMPT_TITULOS_HEADLINE_PATH.read_text(encoding="utf-8")
    entrada = (
        f"Idioma exigido para os titulos: {idioma}\n\n"
        f"Headline final da thumbnail (NAO pode ser alterado): {headline}\n"
        f"Fato retido pelo headline (withheld_fact, NUNCA revelar em nenhum titulo): "
        f"{withheld_fact or '(nao informado)'}\n"
        f"Palavra de destaque do headline (emphasis_word): {emphasis_word or '(nenhuma)'}\n\n"
        "Titulos atuais (candidatos, na ordem factual/autoridade/obstaculo):\n"
        + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titulos_validos))
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_TITULOS_HEADLINE,
            system=prompt_sistema,
            messages=[{"role": "user", "content": entrada}],
            tools=[SCHEMA_TITULOS_HEADLINE],
            tool_choice={"type": "tool", "name": NOME_TOOL_TITULOS_HEADLINE},
        )
    except Exception as exc:
        logger.warning("reconciliar_titulos_com_headline: chamada a API falhou: %s", exc, exc_info=True)
        return titulos_validos, {
            "executado": False,
            "erro": str(exc),
            "titulos_originais": titulos_validos,
        }

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_TITULOS_HEADLINE)
    if not isinstance(dados, dict):
        return titulos_validos, {
            "executado": True,
            "erro": "resposta_invalida",
            "titulos_originais": titulos_validos,
        }

    itens = dados.get("titles")
    if not isinstance(itens, list) or not itens:
        return titulos_validos, {
            "executado": True,
            "erro": "resposta_sem_titulos",
            "titulos_originais": titulos_validos,
        }

    titulos_finais = []
    scores = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        titulo = str(item.get("title") or "").strip()
        if not titulo:
            continue
        score = item.get("complementarity_score")
        score = score if score in (0, 1, 2) else None
        titulos_finais.append(titulo)
        scores.append({"title": titulo, "complementarity_score": score, "motivo": str(item.get("motivo") or "")})

    if not titulos_finais:
        return titulos_validos, {
            "executado": True,
            "erro": "resposta_sem_titulos_validos",
            "titulos_originais": titulos_validos,
        }

    # Resposta incompleta (menos titulos do que o pedido) - preenche o
    # restante com os originais em vez de descartar titulos bons (nunca
    # deixa o video com menos de 3 opcoes so' porque a reconciliacao veio
    # truncada).
    while len(titulos_finais) < len(titulos_validos):
        idx = len(titulos_finais)
        titulos_finais.append(titulos_validos[idx])
        scores.append(
            {"title": titulos_validos[idx], "complementarity_score": None, "motivo": "preservado_resposta_incompleta"}
        )
    titulos_finais = titulos_finais[: len(titulos_validos)] if titulos_validos else titulos_finais

    auditoria = {
        "executado": True,
        "alterado": titulos_finais != titulos_validos,
        "titulos_originais": titulos_validos,
        "titulos_finais": titulos_finais,
        "scores": scores,
    }
    return titulos_finais, auditoria


def _ler_roteiro_aprovado(pasta_projeto: Path):
    """Le roteiro_aprovado.md com as mesmas 3 pre-condicoes de sempre
    (existe / legivel / nao-vazio) - extraido pra' ser compartilhado por
    `gerar_metadados` e `regenerar_thumbnail_briefing`. Devolve
    `(texto, None)` em sucesso ou `(None, codigo_erro)` em falha."""
    caminho_roteiro = pasta_projeto / "roteiro_aprovado.md"
    if not caminho_roteiro.exists():
        return None, "roteiro_ausente"
    try:
        roteiro_texto = caminho_roteiro.read_text(encoding="utf-8")
    except OSError:
        return None, "roteiro_ilegivel"
    if not roteiro_texto.strip():
        return None, "roteiro_vazio"
    return roteiro_texto, None


def _chamar_claude_metadados(
    cliente_api,
    modelo: str,
    roteiro_texto: str,
    _custos: list | None = None,
    titulo_aprovado: str = "",
    nucleo_editorial: str = "",
    elemento_principal: str = "",
):
    """Faz a chamada de API (tool_choice forcado, nao-streaming - CLAUDE.md
    secao 9) pedindo o schema completo de metadados/thumbnail. Devolve
    `(dados, None)` em sucesso ou `(None, codigo_erro)` em falha -
    `codigo_erro` distingue "chamada_api_falhou" (excecao de rede) de
    "resposta_invalida" (resposta sem tool_use), preservando o contrato de
    erro que `gerar_metadados`/`regenerar_thumbnail_briefing` ja expunham
    antes desta funcao ser extraida. Compartilhada por `gerar_metadados`
    (primeira geracao, e' tambem quem tenta o reparo unico de
    background_prompt trivial chamando isto de novo) e
    `regenerar_thumbnail_briefing` (regeneracao parcial pedida pelo
    usuario) - a UNICA diferenca entre os tres usos e' o que cada chamador
    faz com o resultado, nunca a chamada em si.

    `titulo_aprovado`/`nucleo_editorial`: contexto de ANCORAGEM geral
    opcional, injetado ANTES do roteiro na mesma mensagem (ver
    `_ler_eixo_editorial_base`).

    `elemento_principal` (sessao "conceito visual"): o `elemento_
    principal` do conceito visual ja extraido pelo Headline Engine (Grupo
    A, roda ANTES desta chamada agora - `gerar_metadados`/`regenerar_
    thumbnail_briefing`) - ancora OBRIGATORIA do `background_prompt`
    (scripts/prompts/metadados_thumbnail.md instrui o modelo nesse
    sentido). Substitui o mecanismo antigo de `evidencia_central`/
    `conflito`/`data_chave` (removido - ver HISTORICO_BUGS.md), que
    injetava um cabecalho derivado desta MESMA chamada de volta pro
    Headline Engine - dependencia circular que a reordenacao desta sessao
    eliminou. Default "" (Grupo A do Headline Engine falhou, ou projeto
    antigo) - o prompt trata ausencia com graca, cai no titulo/nucleo
    como ancora, nunca bloqueia a chamada."""
    prompt_sistema = _PROMPT_METADADOS_PATH.read_text(encoding="utf-8")
    bloco_eixo = ""
    if titulo_aprovado or nucleo_editorial or elemento_principal:
        bloco_eixo = (
            f"Titulo aprovado do video: {titulo_aprovado or '(nao disponivel)'}\n"
            f"Nucleo editorial (Etapa 3, se disponivel): {nucleo_editorial or '(nao disponivel)'}\n"
            f"Elemento principal do conceito visual (Headline Engine, se disponivel): "
            f"{elemento_principal or '(nao disponivel)'}\n\n"
        )
    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_RESPOSTA_METADADOS,
            system=prompt_sistema,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{bloco_eixo}Roteiro aprovado:\n\n{roteiro_texto}",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
            tools=[SCHEMA_METADADOS],
            tool_choice={"type": "tool", "name": NOME_TOOL_METADADOS},
        )
    except Exception:
        logger.warning("_chamar_claude_metadados: chamada a API falhou.", exc_info=True)
        return None, "chamada_api_falhou"

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_METADADOS)
    if not isinstance(dados, dict):
        return None, "resposta_invalida"
    return dados, None


def gerar_metadados(
    pasta_projeto: Path,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> dict:
    """GRUPO D. Chamada UNICA (tool_choice forcado, NAO-streaming) usando
    roteiro_aprovado.md como input, marcado com cache_control (ajuda um
    retry dentro da janela do cache efemero - mesmo espirito do "Refazer
    roteiro com instrucoes" que ja existe pro roteiro em si). Persiste
    thumbnail/metadados.json com um hash do roteiro usado, pra
    `metadados_desatualizados` detectar edicao posterior sem regerar
    sozinho (decisao sempre do usuario, nunca automatica).

    ORDEM (sessao "conceito visual" - mudou nesta sessao, ver
    HISTORICO_BUGS.md): o HEADLINE ENGINE roda PRIMEIRO agora, antes desta
    chamada - `headline_engine.gerar_headline` produz `headline` e o
    CONCEITO VISUAL (Grupo A estendido, `elemento_principal`/
    `tipo_elemento`/etc). O `elemento_principal` extraido vira a ancora
    OBRIGATORIA do `background_prompt` nesta chamada (ver
    `_chamar_claude_metadados`) - antes, era o inverso: esta chamada rodava
    primeiro e produzia `evidencia_central`/`conflito`/`data_chave`, que
    eram injetados de volta como cabecalho no roteiro entregue ao Headline
    Engine (`_montar_roteiro_com_eixo_editorial`, mecanismo circular
    removido nesta sessao - os 3 campos foram subsumidos pelo conceito
    visual). `headline`/`emphasis_word` que vem desta chamada unica
    continuam servindo de FALLBACK - `_mesclar_headline_em_thumbnail`
    sobrescreve com o resultado do Headline Engine quando ele teve
    sucesso, senao preserva o que veio daqui (chamada dedicada e separada
    de sempre, nunca no mesmo turno que subject_name/descricao - evita o
    vies de sumarizacao documentado em scripts/headline_engine.py).
    subject_name/secondary/accent/censor/background_prompt sempre vem
    desta chamada unica.

    GRUPO C (validacao semantica): se o `background_prompt` que voltou for
    trivial (`background_prompt_valido` - string vazia ou abaixo do minimo
    objetivo de caracteres, NUNCA um julgamento subjetivo de qualidade),
    `_reparar_thumbnail_normalizado` tenta UMA reparacao automatica - uma
    segunda chamada completa a' API, adotando so' o que efetivamente
    melhorou. Se persistir trivial mesmo apos a tentativa, segue e persiste
    mesmo assim - nunca bloqueia esta chamada. Validacao adicional
    (`validar_consistencia_headline_conceito`, codigo puro) confere se o
    conceito visual (agora ja' mesclado) veio vazio - `thumbnail
    ["conceito_visual_ausente"]` fica `True` nesse caso (nunca um vazio
    silencioso - CLAUDE.md secao 18.4) pra' a tela de thumbnail avisar o
    usuario.

    Nunca levanta excecao - falha vira `{"sucesso": False, "erro": ...}`.

    CUSTO (correcao de sessao de refinamento - CLAUDE.md): a chamada de
    metadados (e o reparo, se acontecer) e o briefing do Grupo C (fotos de
    sujeito via Vision + selecao de template) gastavam dinheiro de API real
    sem NUNCA persistir esse custo em lugar nenhum - `_calcular_custo_total_projeto`
    (server.py) nao tinha de onde somar. `_custos_proprios` (lista local,
    NUNCA repassada pra `headline_engine.gerar_headline`) acumula so' essas
    duas chamadas e persiste em `metadados["custo_usd_estimado"]` - o
    Headline Engine continua de fora de proposito, seu custo ja e'
    persistido a parte em thumbnail/headline_engine.json e somado la'
    (evita contar duas vezes)."""
    roteiro_texto, erro = _ler_roteiro_aprovado(pasta_projeto)
    if erro is not None:
        return {"sucesso": False, "erro": erro}

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return {"sucesso": False, "erro": "cliente_indisponivel"}

    _custos_proprios = []

    resultado_headline = headline_engine.gerar_headline(
        pasta_projeto, roteiro_texto, api_key=None, modelo=modelo, cliente=cliente_api, _custos=_custos
    )
    conceito_visual_baseline = (
        (resultado_headline.get("conceito_visual") or {}) if resultado_headline.get("sucesso") else {}
    )
    elemento_principal = conceito_visual_baseline.get("elemento_principal") or ""

    eixo_base = _ler_eixo_editorial_base(pasta_projeto)
    dados, erro_chamada = _chamar_claude_metadados(
        cliente_api, modelo, roteiro_texto, _custos_proprios,
        titulo_aprovado=eixo_base["titulo_aprovado"], nucleo_editorial=eixo_base["nucleo_editorial"],
        elemento_principal=elemento_principal,
    )
    if dados is None:
        return {"sucesso": False, "erro": erro_chamada}

    thumbnail_normalizado = _normalizar_thumbnail_metadados(dados.get("thumbnail") or {})
    thumbnail_normalizado = _reparar_thumbnail_normalizado(
        cliente_api, modelo, roteiro_texto, eixo_base, thumbnail_normalizado, _custos_proprios,
        elemento_principal=elemento_principal,
    )

    thumbnail_normalizado = _mesclar_headline_em_thumbnail(thumbnail_normalizado, resultado_headline)
    thumbnail_normalizado.update(validar_consistencia_headline_conceito(thumbnail_normalizado))

    # Titulo canonico: NUNCA gerado aqui. titulo_escolhido vem de
    # titulo.txt (Etapa 3/5.5, ja lido em eixo_base) - a reconciliacao
    # contra o headline final e' so' auditoria (ver comentario acima da
    # funcao), nunca substitui `titulo_escolhido`.
    titulo_escolhido = eixo_base["titulo_aprovado"]
    _, titulo_headline_reconciliacao = reconciliar_titulos_com_headline(
        cliente_api,
        modelo,
        [titulo_escolhido] if titulo_escolhido else [],
        thumbnail_normalizado.get("headline"),
        thumbnail_normalizado.get("withheld_fact"),
        thumbnail_normalizado.get("emphasis_word"),
        _idioma_do_projeto(pasta_projeto),
        _custos_proprios,
    )

    metadados = {
        "titulo_escolhido": titulo_escolhido,
        "titulos_alternativos": _ler_titulos_alternativos(pasta_projeto, titulo_escolhido),
        "description": str(dados.get("description") or ""),
        "tags": [str(t) for t in (dados.get("tags") or [])],
        "thumbnail": thumbnail_normalizado,
        "roteiro_hash": _hash_roteiro(roteiro_texto),
        "titulo_headline_reconciliacao": titulo_headline_reconciliacao,
    }

    pasta_thumbnail = pasta_projeto / "thumbnail"
    pasta_thumbnail.mkdir(parents=True, exist_ok=True)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadados, _resultado_briefing = _aplicar_briefing_grupo_c(
        pasta_projeto, api_key, modelo, metadados, cliente_api, _custos_proprios
    )

    metadados["custo_usd_estimado"] = round(sum(_custos_proprios), 6)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if _custos is not None:
        _custos.extend(_custos_proprios)

    return {"sucesso": True, "metadados": metadados}


def _aplicar_briefing_grupo_c(
    pasta_projeto: Path,
    api_key: str,
    modelo: str,
    metadados: dict,
    cliente_api=None,
    _custos: list | None = None,
    template_forcado: "str | None" = None,
) -> tuple:
    """GRUPO C: gera `thumbnail.briefing_completo` (scripts/
    thumbnail_briefing.py) logo apos persistir metadados.json com o
    headline final (Headline Engine ja aplicado nesse ponto). A funcao de
    briefing LE o proprio metadados.json do disco (por isso so' e' chamada
    aqui DEPOIS do primeiro write) - assim ela pode ser reusada tambem pela
    rota dedicada `/projetos/<id>/thumbnail/gerar_briefing` (server.py),
    chamavel a qualquer momento na tela (ex: depois que o usuario troca um
    upload de sujeito).

    `cliente_api`: reaproveita o MESMO cliente ja obtido pelo chamador
    (`gerar_metadados`/`regenerar_thumbnail_briefing` ja chamaram
    `_obter_cliente` uma vez) - nunca reconstroi um cliente novo a partir
    so' de `api_key`. Critico pra' teste: sem isso, um teste que injeta um
    cliente FAKE via `cliente=` em `gerar_metadados` ainda acabaria
    chamando a API Anthropic DE VERDADE aqui dentro (CLAUDE.md secao 8 -
    "nunca chamar API real do Claude em teste"), porque `api_key` sozinha
    e' o suficiente pra' `anthropic.Anthropic(api_key=...)` construir um
    cliente real. `gerar_briefing_thumbnail` (rota dedicada, sem cliente
    de chamador nenhum pra' reaproveitar) passa None de proposito - ai' sim
    constroi um cliente novo a partir de `api_key`, comportamento correto
    em producao.

    Devolve `(metadados, resultado_briefing)` - `resultado_briefing` e' o
    dict cru de `thumbnail_briefing.gerar_briefing_completo` (inclui
    `sucesso`/`erro`). GRUPO B (correcao desta sessao): esse `gerar_
    briefing_completo` agora FALHA de proposito quando o headline esta'
    ausente/vazio (sem cascata de fallback silencioso pro subject_name -
    ver docstring dele) - `_aplicar_briefing_grupo_c` nunca apaga o
    `metadados` ja' bom que chegou aqui quando isso acontece (CLAUDE.md
    secao 18.4: `gerar_metadados`/`regenerar_thumbnail_briefing` ignoram o
    segundo valor de proposito, nunca bloqueiam a geracao principal por
    causa do briefing) - mas o CHAMADOR que expoe isso like uma acao
    explicita do usuario (`gerar_briefing_thumbnail`, rota dedicada)
    repassa `resultado_briefing` pra' reportar o erro de verdade em vez de
    fingir sucesso com um briefing vazio.

    `template_forcado` (Grupo F - escolha manual do usuario na tela):
    repassado direto pra' `thumbnail_briefing.gerar_briefing_completo` -
    ver docstring dele."""
    resultado_briefing = thumbnail_briefing.gerar_briefing_completo(
        pasta_projeto, api_key, modelo, cliente=cliente_api, _custos=_custos,
        template_forcado=template_forcado,
    )
    if not resultado_briefing.get("sucesso"):
        logger.info(
            "_aplicar_briefing_grupo_c: geracao do briefing nao concluiu (%s).", resultado_briefing.get("erro")
        )
        return metadados, resultado_briefing

    metadados.setdefault("thumbnail", {})
    metadados["thumbnail"]["briefing_completo"] = resultado_briefing["briefing_completo"]
    metadados["thumbnail"]["briefing_template"] = resultado_briefing["template_escolhido"]
    # Fingerprint do estado de sujeitos QUE PRODUZIU este briefing (Fase 1
    # - correcao do estado do briefing) - fonte de verdade pra' decidir se
    # o briefing persistido ainda vale, comparado contra o fingerprint
    # ATUAL de sujeitos.json no momento do uso (server.py:_briefing_stale).
    # Nunca depende de alguem lembrar de chamar uma funcao de invalidacao
    # em cada rota que mexe em sujeitos.json - qualquer rota futura fica
    # protegida automaticamente so' por essa comparacao.
    metadados["thumbnail"]["briefing_subjects_fingerprint"] = resultado_briefing.get("subjects_fingerprint")
    # Briefing novo de verdade acabou de ser gerado - qualquer marca de
    # "desatualizado" de uma troca de papel anterior (server.py:
    # thumbnail_atualizar_papel_sujeito) deixou de valer. A flag continua
    # existindo (consumida pelo banner da tela) mas NUNCA e' mais a unica
    # defesa - ver fingerprint acima.
    metadados["thumbnail"].pop("briefing_desatualizado", None)

    pasta_thumbnail = pasta_projeto / "thumbnail"
    pasta_thumbnail.mkdir(parents=True, exist_ok=True)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadados, resultado_briefing


def gerar_briefing_thumbnail(
    pasta_projeto: Path,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
    template_forcado: "str | None" = None,
) -> dict:
    """GRUPO C: ponto de entrada da rota dedicada `/projetos/<id>/thumbnail/
    gerar_briefing` (server.py) - regera SO' `thumbnail.briefing_completo`
    a partir do que ja esta' em disco (thumbnail/metadados.json +
    thumbnail/sujeitos/sujeitos.json), sem gastar uma chamada nova de
    Grupo D/Headline Engine. Chamavel a qualquer momento na tela, em
    particular depois que o usuario troca um upload de sujeito (o briefing
    anterior ficaria referenciando papeis/fotos que nao existem mais) ou
    troca o template escolhido (Grupo F - `template_forcado`, repassado
    direto pra' `thumbnail_briefing.gerar_briefing_completo`).

    `cliente`: override opcional pra' teste (mesmo padrao de
    `gerar_metadados`/`regenerar_thumbnail_briefing`) - repassado direto
    pra' `_aplicar_briefing_grupo_c`, nunca reconstroi um cliente a partir
    so' de `api_key` quando um fake foi injetado.

    Precondicao: thumbnail/metadados.json precisa existir (Grupo D ja
    rodou pelo menos uma vez) - sem ele nao ha' headline pra' usar.

    GRUPO B (correcao desta sessao): diferente de `gerar_metadados`/
    `regenerar_thumbnail_briefing` (que ignoram falha do Grupo C - nunca
    bloqueiam a geracao principal), esta rota dedicada e' a ACAO EXPLICITA
    do usuario ("Gerar / regenerar briefing" na tela) - se o Grupo C falhar
    (ex: headline ausente), devolve `sucesso: False` de verdade em vez de
    fingir sucesso com um briefing vazio, pro JS mostrar o erro real.

    CUSTO (correcao de sessao de refinamento): `_custos_proprios` acumula
    o gasto desta chamada (fotos de sujeito via Vision + selecao de
    template) e SOMA em `metadados["custo_usd_estimado"]` - persistido
    mesmo se `resultado_briefing` falhar no final (uma chamada pode ter
    custado dinheiro real antes de outra falhar)."""
    caminho_metadados = pasta_projeto / "thumbnail" / "metadados.json"
    metadados = _ler_dict_json_ou_none(caminho_metadados)
    if metadados is None:
        return {"sucesso": False, "erro": "metadados_ausentes"}

    custo_acumulado = metadados.get("custo_usd_estimado") or 0.0
    _custos_proprios = []

    metadados, resultado_briefing = _aplicar_briefing_grupo_c(
        pasta_projeto, api_key, modelo, metadados, cliente, _custos_proprios,
        template_forcado=template_forcado,
    )

    if _custos_proprios:
        metadados["custo_usd_estimado"] = round(custo_acumulado + sum(_custos_proprios), 6)
        pasta_thumbnail = pasta_projeto / "thumbnail"
        pasta_thumbnail.mkdir(parents=True, exist_ok=True)
        (pasta_thumbnail / "metadados.json").write_text(
            json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if _custos is not None:
        _custos.extend(_custos_proprios)

    if not resultado_briefing.get("sucesso"):
        return {
            "sucesso": False,
            "erro": resultado_briefing.get("erro") or "briefing_falhou",
            "mensagem": "Nao foi possivel gerar o briefing - confirme que ha' um headline aprovado (Grupo D/Headline Engine) antes de tentar de novo.",
        }
    return {"sucesso": True, "thumbnail": metadados.get("thumbnail", {}), "metadados": metadados}


def regenerar_thumbnail_briefing(
    pasta_projeto: Path,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> dict:
    """GRUPO C (regeneracao parcial). Regera SOMENTE o bloco `thumbnail`
    (subject_name/headline/emphasis_word/secondary/accent/censor/
    background_prompt) via uma nova chamada a' IA - preserva
    description/tags e qualquer edicao humana anterior desses campos, ja
    gravados em thumbnail/metadados.json. `titulo_escolhido` NUNCA e'
    tocado aqui - sempre relido de titulo.txt (fonte unica de verdade, ver
    docstring do modulo). E' o caminho real por tras do botao "Regenerar
    dados automaticos" da tela (Grupo G/F).

    Mesma ORDEM de `gerar_metadados` (sessao "conceito visual"): o
    Headline Engine roda PRIMEIRO, produzindo `headline`/conceito visual;
    `elemento_principal` extraido vira ancora do `background_prompt` desta
    chamada. Mesmo reparo unico de `_reparar_thumbnail_normalizado` usado
    por `gerar_metadados` (so' background_prompt trivial agora - o reparo
    de eixo editorial foi removido junto dos campos, ver HISTORICO_BUGS.md).
    Persiste `thumbnail["conceito_visual_ausente"]` honestamente em
    qualquer caso (nunca um vazio silencioso).

    Reusa o MESMO prompt de sistema e schema de `gerar_metadados` (pedir
    so' o bloco thumbnail exigiria manter um segundo schema so' pra essa
    diferenca - nao vale a pena) - so' o que e' PERSISTIDO difere:
    description/tags da resposta sao descartados, so' o `thumbnail`
    normalizado substitui o anterior. Assim como em `gerar_metadados`, o
    `headline`/`emphasis_word` desta chamada serve so' de fallback,
    substituido pelo resultado do Headline Engine
    (`_mesclar_headline_em_thumbnail`) quando ele teve sucesso -
    "Regenerar briefing do fundo" tambem regera o headline, nunca deixa o
    projeto com um headline da geracao antiga do single-pass.

    Nunca levanta excecao - falha vira `{"sucesso": False, "erro": ...}`.

    CUSTO (correcao de sessao de refinamento): mesma logica de
    `gerar_metadados` - `_custos_proprios` acumula so' a chamada de
    metadados e o briefing do Grupo C (nunca o Headline Engine, que
    persiste seu proprio custo em headline_engine.json). Regeneracao
    parcial gasta dinheiro NOVO em cima do que a geracao original ja
    custou - `metadados["custo_usd_estimado"]` acumula (soma) em vez de
    substituir, pra' `_calcular_custo_total_projeto` (server.py) refletir
    TODO gasto real do projeto, nao so' da ultima chamada."""
    roteiro_texto, erro = _ler_roteiro_aprovado(pasta_projeto)
    if erro is not None:
        return {"sucesso": False, "erro": erro}

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return {"sucesso": False, "erro": "cliente_indisponivel"}

    _custos_proprios = []

    resultado_headline = headline_engine.gerar_headline(
        pasta_projeto, roteiro_texto, api_key=None, modelo=modelo, cliente=cliente_api, _custos=_custos
    )
    conceito_visual_baseline = (
        (resultado_headline.get("conceito_visual") or {}) if resultado_headline.get("sucesso") else {}
    )
    elemento_principal = conceito_visual_baseline.get("elemento_principal") or ""

    eixo_base = _ler_eixo_editorial_base(pasta_projeto)
    dados, erro_chamada = _chamar_claude_metadados(
        cliente_api, modelo, roteiro_texto, _custos_proprios,
        titulo_aprovado=eixo_base["titulo_aprovado"], nucleo_editorial=eixo_base["nucleo_editorial"],
        elemento_principal=elemento_principal,
    )
    if dados is None:
        return {"sucesso": False, "erro": erro_chamada}

    thumbnail_normalizado = _normalizar_thumbnail_metadados(dados.get("thumbnail") or {})
    thumbnail_normalizado = _reparar_thumbnail_normalizado(
        cliente_api, modelo, roteiro_texto, eixo_base, thumbnail_normalizado, _custos_proprios,
        elemento_principal=elemento_principal,
    )

    thumbnail_normalizado = _mesclar_headline_em_thumbnail(thumbnail_normalizado, resultado_headline)
    thumbnail_normalizado.update(validar_consistencia_headline_conceito(thumbnail_normalizado))

    metadados_existentes = _ler_dict_json_ou_none(pasta_projeto / "thumbnail" / "metadados.json") or {}
    custo_acumulado = metadados_existentes.get("custo_usd_estimado") or 0.0
    metadados_existentes["thumbnail"] = thumbnail_normalizado
    metadados_existentes.setdefault("description", "")
    metadados_existentes.setdefault("tags", [])
    metadados_existentes["roteiro_hash"] = _hash_roteiro(roteiro_texto)
    # Compatibilidade: metadados.json de uma geracao anterior a' sessao
    # "titulo canonico" ainda pode ter a chave antiga "title" (3 titulos
    # gerados pelo Grupo D) - nunca mais persistida, removida aqui se
    # sobrar de uma regeneracao parcial sobre um metadados.json antigo.
    metadados_existentes.pop("title", None)

    # titulo_escolhido NUNCA vem desta chamada - sempre relido de
    # titulo.txt (eixo_base, fonte unica de verdade). A reconciliacao
    # contra o headline NOVO (que acabou de mudar em _aplicar_headline_
    # engine acima) e' so' auditoria - nunca substitui titulo_escolhido
    # (mesmo bug que motivou a sessao "titulo canonico", so' que no
    # caminho de regeneracao em vez do de primeira geracao).
    titulo_escolhido = eixo_base["titulo_aprovado"] or metadados_existentes.get("titulo_escolhido") or ""
    _, titulo_headline_reconciliacao = reconciliar_titulos_com_headline(
        cliente_api,
        modelo,
        [titulo_escolhido] if titulo_escolhido else [],
        thumbnail_normalizado.get("headline"),
        thumbnail_normalizado.get("withheld_fact"),
        thumbnail_normalizado.get("emphasis_word"),
        _idioma_do_projeto(pasta_projeto),
        _custos_proprios,
    )
    metadados_existentes["titulo_escolhido"] = titulo_escolhido
    metadados_existentes["titulos_alternativos"] = _ler_titulos_alternativos(pasta_projeto, titulo_escolhido)
    metadados_existentes["titulo_headline_reconciliacao"] = titulo_headline_reconciliacao

    pasta_thumbnail = pasta_projeto / "thumbnail"
    pasta_thumbnail.mkdir(parents=True, exist_ok=True)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(metadados_existentes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadados_existentes, _resultado_briefing = _aplicar_briefing_grupo_c(
        pasta_projeto, api_key, modelo, metadados_existentes, cliente_api, _custos_proprios
    )
    thumbnail_normalizado = metadados_existentes.get("thumbnail", thumbnail_normalizado)

    metadados_existentes["custo_usd_estimado"] = round(custo_acumulado + sum(_custos_proprios), 6)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(metadados_existentes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if _custos is not None:
        _custos.extend(_custos_proprios)

    return {"sucesso": True, "thumbnail": thumbnail_normalizado, "metadados": metadados_existentes}


def metadados_desatualizados(pasta_projeto: Path) -> bool:
    """True se roteiro_aprovado.md mudou desde a ultima geracao de
    thumbnail/metadados.json, OU se um dos dois arquivos nao existe (nesse
    caso nao ha' propriamente "desatualizacao", mas tambem nao ha'
    metadados validos pra usar - trata como True, precisa gerar). Nunca
    regera sozinho - so' informa; quem decide regerar e' o Grupo G."""
    caminho_roteiro = pasta_projeto / "roteiro_aprovado.md"
    caminho_metadados = pasta_projeto / "thumbnail" / "metadados.json"
    if not caminho_roteiro.exists() or not caminho_metadados.exists():
        return True

    metadados = _ler_dict_json_ou_none(caminho_metadados)
    if not metadados or "roteiro_hash" not in metadados:
        return True

    try:
        roteiro_texto = caminho_roteiro.read_text(encoding="utf-8")
    except OSError:
        return True

    return _hash_roteiro(roteiro_texto) != metadados["roteiro_hash"]


# ---------------------------------------------------------------------------
# Orquestracao principal (Grupo D dispara o briefing do Grupo C
# automaticamente apos gerar metadados - ver gerar_metadados/
# regenerar_thumbnail_briefing. Upload de sujeitos, Grupo B, so' acontece
# depois, pela tela - nada aqui depende dele.)
# ---------------------------------------------------------------------------


def gerar_thumbnail_candidatos(pasta_projeto: Path) -> dict:
    """Ponto de entrada do `python scripts/7_thumbnail.py <pasta>`: gera
    metadados (Grupo D, se `ANTHROPIC_API_KEY` configurada - isso ja'
    dispara o briefing do Grupo C automaticamente, ver `gerar_metadados`).
    Sem chave, segue sem briefing - o projeto pausa em
    `aguardando_thumbnail` mesmo assim, esperando a tela (Grupo G).

    Nunca levanta excecao - falha de pre-condicao vira
    `{"sucesso": False, "erro_fatal": ..., "tipo_erro": ...}`
    (CLAUDE.md secao 18.4)."""
    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes(pasta_projeto)
    if not ok_precondicoes:
        emitir_progresso(0.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    modelo = os.environ.get("ANTHROPIC_MODEL") or MODELO_PADRAO

    if api_key and metadados_desatualizados(pasta_projeto):
        emitir_progresso(20.0, "Gerando metadados (titulo/descricao/thumbnail/briefing)...")
        resultado_metadados = gerar_metadados(pasta_projeto, api_key, modelo)
        if not resultado_metadados.get("sucesso"):
            logger.info(
                "gerar_thumbnail_candidatos: Grupo D nao gerou metadados (%s) - segue sem briefing.",
                resultado_metadados.get("erro"),
            )

    emitir_progresso(100.0, "Concluido: metadados/briefing da thumbnail preparados", sucesso=True)
    return {"sucesso": True}


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/7_thumbnail.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    resultado = gerar_thumbnail_candidatos(pasta_projeto)

    if not resultado.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
