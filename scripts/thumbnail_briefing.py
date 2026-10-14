"""Grupo C da Etapa 7 (thumbnail) - briefing exportavel. Modulo novo desta
sessao de reconstrucao (ver docstring de scripts/7_thumbnail.py pro
contexto completo da mudanca de arquitetura).

Monta `thumbnail.briefing_completo` - um prompt em INGLES pronto pra colar
em qualquer gerador de imagem (Grupo D/Parte 2, ainda nao implementada,
vai mandar esse texto + as fotos pro endpoint /v1/images/edits do
gpt-image-2) - combinando:

1. O headline vencedor (Headline Engine, ja rodou antes desta chamada) e
   os demais campos ja gerados por `scripts/7_thumbnail.py:gerar_metadados`
   (accent/censor/subject_name/secondary/background_prompt).
2. Os papeis e atributos visuais dos sujeitos enviados (Grupo B da Etapa 7
   - thumbnail/sujeitos/sujeitos.json). Atributos vem de UMA chamada Vision
   leve por foto (framing/expressao/genero/faixa etaria) SE
   `ANTHROPIC_API_KEY` estiver configurada - Vision aqui NUNCA decide
   identidade (o papel ja' foi declarado pelo usuario no upload), so'
   descreve o que ve. Sem chave, cai num fallback deterministico por
   papel (nunca bloqueia a geracao do briefing - CLAUDE.md secao 18.4).
3. Um dos 5 TEMPLATES de composicao (ARROW_TRIO/PROFILE_ISOLATION/
   EVIDENCE_SCENE/DUOTONE_DOSSIER/INVESTIGATOR_UPDATE) - escolhido por uma
   chamada dedicada (tool_choice forcado, enum FECHADO ao subconjunto que
   os papeis disponiveis permitem - nunca deixa o modelo escolher um
   template que exige um sujeito ausente). Sem chave/API indisponivel cai
   no fallback deterministico universal: EVIDENCE_SCENE (unico template
   elegivel em TODA combinacao de fotos disponiveis).

Funciona 100% sem NENHUMA API de imagem configurada - e' a entrega que
sempre funciona (Fase 2 - Parte 1 desta sessao). A composicao de verdade
via gpt-image-2 (`/v1/images/edits`, enviando as fotos + este texto) e' a
Parte 2, sessao separada - ver MELHORIAS_PENDENTES.md.
"""

import base64
import hashlib
import json
import logging
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger(__name__)

MODELO_PADRAO = "claude-sonnet-5"
MAX_TOKENS_ATRIBUTOS = 512
MAX_TOKENS_SELECAO_TEMPLATE = 512

# Duplicado de scripts/7_thumbnail.py / scripts/headline_engine.py de
# proposito (CLAUDE.md secao 9 - scripts autocontidos, sem utils
# compartilhado).
CUSTO_INPUT_POR_MILHAO_USD = 3.0
CUSTO_OUTPUT_POR_MILHAO_USD = 15.0

# Duplicado de scripts/7_thumbnail.py:PAPEIS_SUJEITO_VALIDOS de proposito
# (mesmo motivo acima) - manter os dois em sincronia se a lista mudar.
PAPEIS_VALIDOS = ("vitima", "suspeito", "condenado", "investigador", "testemunha", "outro")

ACCENT_PADRAO = "red"

# Tamanho maximo do trecho do roteiro enviado pra' selecao de template e
# pra' background_prompt implicito - roteiro completo pode passar de 25k
# caracteres (CLAUDE.md secao 5.4.1), e a selecao de template so' precisa
# do TOM/ASSUNTO geral do caso, nao de cada detalhe - poupa tokens.
LIMITE_CARACTERES_ROTEIRO_PARA_SELECAO = 6000

TEMPLATES_VALIDOS = (
    "ARROW_TRIO",
    "PROFILE_ISOLATION",
    "EVIDENCE_SCENE",
    "DUOTONE_DOSSIER",
    "INVESTIGATOR_UPDATE",
    "DUAL_PORTRAIT",
)


# ---------------------------------------------------------------------------
# Helpers genericos (duplicados de proposito - CLAUDE.md secao 9)
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


def _obter_cliente(api_key, cliente):
    if cliente is not None:
        return cliente
    if anthropic is None or not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _ler_json_dict(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return dados if isinstance(dados, dict) else {}


# ---------------------------------------------------------------------------
# Fingerprint deterministico do estado de sujeitos.json (Fase 1 - correcao
# do estado do briefing)
#
# Substitui a dependencia da flag booleana `briefing_desatualizado`
# (server.py, setada so' explicitamente por `thumbnail_atualizar_papel_
# sujeito`) por uma comparacao determinística do estado REAL de
# thumbnail/sujeitos/sujeitos.json - unica fonte de verdade dos sujeitos.
# Achado real que motivou isso (caso Nancy Guthrie): upload de um sujeito
# novo (`thumbnail_upload_sujeito`) nunca setava a flag - so' a troca de
# PAPEL de um slot ja preenchido setava - entao um briefing gerado ANTES
# de qualquer sujeito existir (EVIDENCE_SCENE, automatico apos a Etapa 7)
# continuava sendo enviado pra' composicao por IA depois do usuario
# enviar 2 fotos, porque nenhum caminho de codigo jamais marcou a flag.
# ---------------------------------------------------------------------------


def calcular_fingerprint_sujeitos(sujeitos: dict) -> str:
    """Fingerprint deterministico do estado RELEVANTE de sujeitos.json -
    hero.arquivo/hero.papel/secondary.arquivo/secondary.papel, com o
    estado null de cada slot tratado explicitamente (nunca omitido do
    hash). Mesmo estado sempre produz o MESMO fingerprint (chaves
    ordenadas via `sort_keys=True` - nunca depende da ordem de insercao
    do dict de entrada); qualquer mudanca num desses 4 campos produz um
    fingerprint diferente. Nunca usa timestamp, ordem de upload ou
    qualquer outro dado nao-deterministico.

    `sujeitos` e' o dict no MESMO formato que `_ler_sujeitos_json`
    (scripts/7_thumbnail.py) devolve - `{"hero": {...}|None,
    "secondary": {...}|None}` - aceita tambem o dict cru lido direto de
    sujeitos.json (mesma forma). Nunca levanta excecao - entrada
    None/invalida e' tratada como "os dois slots vazios"."""
    sujeitos = sujeitos if isinstance(sujeitos, dict) else {}

    def _estado_slot(nome: str):
        info = sujeitos.get(nome)
        if not isinstance(info, dict):
            return None
        return {"arquivo": info.get("arquivo"), "papel": info.get("papel")}

    estado = {"hero": _estado_slot("hero"), "secondary": _estado_slot("secondary")}
    bruto = json.dumps(estado, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Descricao de pessoa SEM NOME (Correcao 4 aprovada pelo usuario)
# ---------------------------------------------------------------------------
#
# REGRA DE SEGURANCA (nao remover/afrouxar sem decisao explicita do
# usuario): {HERO_DESC}/{SECONDARY_DESC} (e o equivalente curto usado nos
# grids de foto) NUNCA podem conter nome proprio de pessoa real - so' papel
# declarado + atributos visuais genericos (ex: "person established as the
# case's victim, with a warm expression", nunca "Nancy Guthrie"). O nome
# real do caso so' entra no texto TIPOGRAFICO do prompt (subject_name/
# headline - dado do caso pro texto que aparece escrito na thumbnail, nunca
# instrucao de geracao de rosto). Duas razoes concretas: (1) reduz a chance
# de recusa por moderacao - gpt-image-2 tem sistema de seguranca reforcado
# contra deepfake, pedir put um nome real associado a um rosto gerado e' o
# gatilho mais comum de recusa; (2) o rosto do sujeito SEMPRE vem da foto
# anexada (Parte 2, /v1/images/edits) - pedir ao modelo pra' "inventar" o
# rosto de uma pessoa nomeada e' logicamente errado quando ja' existe uma
# foto real sendo enviada junto.

_SUBSTANTIVO_POR_PAPEL = {
    "vitima": "the case's victim",
    "suspeito": "the case's suspect",
    "condenado": "a convicted individual in the case",
    "investigador": "the case's investigator",
    "testemunha": "a witness in the case",
    "outro": "a person connected to the case",
}

_SUBSTANTIVO_CURTO_POR_PAPEL = {
    "vitima": "victim",
    "suspeito": "suspect",
    "condenado": "convicted individual",
    "investigador": "investigator",
    "testemunha": "witness",
    "outro": "person connected to the case",
}

_EXPRESSAO_PADRAO_POR_PAPEL = {
    "vitima": "a warm, approachable expression",
    "suspeito": "a serious, unsettling expression",
    "condenado": "a cold, hardened expression",
    "investigador": "a focused, determined expression",
    "testemunha": "a nervous, guarded expression",
    "outro": "a serious expression",
}


def _papel_ou_outro(papel: str) -> str:
    return papel if papel in PAPEIS_VALIDOS else "outro"


def _papel_em_ingles(papel: str) -> str:
    """Traducao de UMA palavra do papel declarado (PT-BR, vindo cru de
    thumbnail/sujeitos/sujeitos.json) pro' INGLES - usada em toda frase de
    prompt que menciona o papel diretamente (ex: "pointing toward the
    {papel}"), nunca o valor cru do formulario. GRUPO C (correcao desta
    sessao): antes, `caso['hero_papel']`/`caso['secondary_papel']`
    entravam direto em texto de prompt em ingles (achado real: "pointing
    from the photographs toward the vitima" no briefing colado no pedido).
    Reusa `_SUBSTANTIVO_CURTO_POR_PAPEL` (mesma tabela ja usada por
    `descrever_papel_curto`) - nunca uma segunda tabela de traducao
    duplicada."""
    return _SUBSTANTIVO_CURTO_POR_PAPEL[_papel_ou_outro(papel)]


# Achado real (caso Burke Ramsey/JonBenét): SCHEMA_ATRIBUTOS_FOTO so'
# permite `genero` "man"/"woman"/"unknown" (nao ha' opcao de crianca), mas
# `faixa_etaria` e' texto livre - uma foto de uma vitima crianca voltou com
# genero "woman" e faixa_etaria "young child", que
# `descrever_pessoa_para_prompt` concatenava sem checar em
# "young child woman" - substantivo contraditorio (crianca E mulher adulta
# ao mesmo tempo) que ja existia antes desta correcao. Lista curta de
# sinais que `faixa_etaria` pode conter indicando crianca - usada so' pra'
# decidir a troca de substantivo, nunca reclassifica o papel declarado.
_SINALIZADORES_CRIANCA = ("child", "kid", "toddler", "infant", "baby", "preteen", "tween")


def _ajustar_genero_e_prefixo_para_crianca(genero: str, faixa_etaria: "str | None") -> tuple:
    """Corrige a contradicao "young child woman"/"young child man": quando
    `faixa_etaria` sinaliza uma crianca, troca o substantivo por
    "girl"/"boy"/"child" (nunca "man"/"woman") e descarta o prefixo de
    idade original (o substantivo novo ja carrega a nocao de crianca -
    manter um prefixo como "young child " na frente seria redundante e
    arriscaria reintroduzir uma contradicao com um texto de Vision
    imprevisivel). Sem sinal de crianca em `faixa_etaria`, devolve
    `(genero, faixa_etaria)` inalterados - comportamento de sempre pra'
    adultos."""
    faixa_lower = (faixa_etaria or "").lower()
    if not any(sinal in faixa_lower for sinal in _SINALIZADORES_CRIANCA):
        return genero, faixa_etaria
    if genero == "woman":
        return "girl", None
    if genero == "man":
        return "boy", None
    return "child", None


def descrever_pessoa_para_prompt(papel: str, atributos: dict | None = None) -> str:
    """Descricao SEM NOME de uma pessoa pra' uso em prompt de geracao de
    imagem - ver bloco de comentario acima (Correcao 4). Sempre comeca com
    "person"/"man"/"woman"/"girl"/"boy"/"child" (nunca com artigo - quem
    monta o prompt final prefixa "a "/"a large " conforme o template) pra'
    nunca colidir com "an" (nenhuma das opcoes comeca com vogal).

    `atributos`: dict opcional vindo de `extrair_atributos_foto` (Vision)
    ou None/vazio (fallback deterministico so' com o papel). Chaves usadas,
    todas opcionais: `genero` ("man"|"woman"), `faixa_etaria` (string
    curta, ex: "middle-aged"), `expressao` (frase curta, ex: "a warm
    smile"). Qualquer chave ausente ou fora do esperado cai no fallback -
    nunca levanta excecao.

    REGRA DE COERENCIA (achado real, ver `_ajustar_genero_e_prefixo_para_
    crianca` acima): a descricao final nunca pode ser crianca E mulher/
    homem adulto ao mesmo tempo - `faixa_etaria` que sinaliza crianca
    sempre substitui o substantivo, nunca so' se soma a ele."""
    papel = _papel_ou_outro(papel)
    atributos = atributos or {}

    genero = atributos.get("genero")
    genero = genero if genero in ("man", "woman") else "person"

    faixa_etaria = atributos.get("faixa_etaria")
    genero, faixa_etaria = _ajustar_genero_e_prefixo_para_crianca(genero, faixa_etaria)
    prefixo_idade = f"{faixa_etaria} " if isinstance(faixa_etaria, str) and faixa_etaria.strip() else ""

    expressao = atributos.get("expressao")
    if not isinstance(expressao, str) or not expressao.strip():
        expressao = _EXPRESSAO_PADRAO_POR_PAPEL[papel]

    substantivo = _SUBSTANTIVO_POR_PAPEL[papel]
    return f"{prefixo_idade}{genero} established as {substantivo}, with {expressao}"


def descrever_papel_curto(papel: str, atributos: dict | None = None) -> str:
    """Versao curta (adjetivo+substantivo, sem "established as...") usada
    em contextos coletivos/plurais - ex: legenda de um grid de fotos
    ("black-and-white {isto} photographs"), onde a frase longa de
    `descrever_pessoa_para_prompt` nao encaixa gramaticalmente. Mesma regra
    de seguranca (nunca nome proprio)."""
    papel = _papel_ou_outro(papel)
    atributos = atributos or {}
    genero = atributos.get("genero")
    prefixo_genero = {"man": "male ", "woman": "female "}.get(genero, "")
    return f"{prefixo_genero}{_SUBSTANTIVO_CURTO_POR_PAPEL[papel]}"


# ---------------------------------------------------------------------------
# Atributos por foto (Vision LEVE - nunca decide identidade)
# ---------------------------------------------------------------------------

NOME_TOOL_ATRIBUTOS = "entregar_atributos_visuais"
SCHEMA_ATRIBUTOS_FOTO = {
    "name": NOME_TOOL_ATRIBUTOS,
    "description": (
        "Descreve atributos VISUAIS genericos da pessoa na foto - nunca a identifica, nunca "
        "presume nome. Usado so' pra enriquecer um prompt de geracao de imagem."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "genero": {
                "type": "string",
                "enum": ["man", "woman", "unknown"],
                "description": "Genero aparente da pessoa na foto, ou 'unknown' se nao for claro.",
            },
            "faixa_etaria": {
                "type": "string",
                "description": (
                    "Faixa etaria aparente em 1-3 palavras em ingles (ex: 'young adult', "
                    "'middle-aged', 'elderly'). Vazio se nao for claro."
                ),
            },
            "expressao": {
                "type": "string",
                "description": (
                    "Expressao facial/emocional em ingles, frase curta comecando com 'a'/'an' "
                    "(ex: 'a warm, confident smile'). Nunca mencione nome, roupa com logo "
                    "identificavel ou qualquer coisa que revele IDENTIDADE - so' expressao."
                ),
            },
            "enquadramento": {
                "type": "string",
                "enum": ["close_up", "medium_shot", "unknown"],
                "description": "Enquadramento da foto original.",
            },
        },
        "required": ["genero", "faixa_etaria", "expressao", "enquadramento"],
    },
}

_EXTENSAO_PARA_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def extrair_atributos_foto(
    caminho_foto: Path,
    papel: str,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> dict:
    """Chamada Vision UNICA e leve por foto - pede so' atributos visuais
    genericos (genero/faixa etaria/expressao/enquadramento), NUNCA pede
    identificacao (o papel ja' foi declarado pelo usuario no upload - Grupo
    B). Diferente da identificacao por Vision REMOVIDA nesta sessao
    (rodava sobre frames de clipe e tentava decidir "quem e' essa pessoa"),
    esta chamada nunca decide identidade - so' descreve o que ve numa foto
    cujo papel ja' e' conhecido.

    Sem `api_key`/cliente indisponivel/qualquer falha: devolve fallback
    deterministico `{"genero": None, "faixa_etaria": None, "expressao":
    None, "enquadramento": None, "fonte": "fallback_sem_vision"}` -
    `descrever_pessoa_para_prompt` ja sabe usar defaults por papel nesse
    caso. Nunca levanta excecao, nunca bloqueia o briefing (CLAUDE.md
    secao 18.4)."""
    fallback = {
        "genero": None,
        "faixa_etaria": None,
        "expressao": None,
        "enquadramento": None,
        "fonte": "fallback_sem_vision",
    }

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None or not caminho_foto.exists():
        return fallback

    media_type = _EXTENSAO_PARA_MEDIA_TYPE.get(caminho_foto.suffix.lower())
    if media_type is None:
        return fallback

    try:
        foto_b64 = base64.b64encode(caminho_foto.read_bytes()).decode("ascii")
    except OSError:
        return fallback

    substantivo_papel = _SUBSTANTIVO_CURTO_POR_PAPEL[_papel_ou_outro(papel)]
    blocos_conteudo = [
        {
            "type": "text",
            "text": (
                f"Esta foto foi enviada como '{substantivo_papel}' de um video de true crime/atualidades. "
                "Descreva SO' atributos visuais genericos uteis pra' compor um prompt de geracao de "
                "imagem (genero aparente, faixa etaria aparente, expressao facial, enquadramento). "
                "NAO tente identificar quem e' a pessoa, NAO mencione nome nenhum - a identidade ja' "
                "e' conhecida por fora, so' os atributos visuais interessam aqui."
            ),
        },
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": foto_b64}},
    ]

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_ATRIBUTOS,
            messages=[{"role": "user", "content": blocos_conteudo}],
            tools=[SCHEMA_ATRIBUTOS_FOTO],
            tool_choice={"type": "tool", "name": NOME_TOOL_ATRIBUTOS},
        )
    except Exception:
        logger.warning("extrair_atributos_foto: chamada a API falhou.", exc_info=True)
        return fallback

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_ATRIBUTOS)
    if not isinstance(dados, dict):
        return fallback

    genero = dados.get("genero")
    genero = genero if genero in ("man", "woman") else None
    enquadramento = dados.get("enquadramento")
    enquadramento = enquadramento if enquadramento in ("close_up", "medium_shot") else None
    faixa_etaria = dados.get("faixa_etaria")
    faixa_etaria = faixa_etaria.strip() if isinstance(faixa_etaria, str) and faixa_etaria.strip() else None
    expressao = dados.get("expressao")
    expressao = expressao.strip() if isinstance(expressao, str) and expressao.strip() else None

    return {
        "genero": genero,
        "faixa_etaria": faixa_etaria,
        "expressao": expressao,
        "enquadramento": enquadramento,
        "fonte": "vision",
    }


# ---------------------------------------------------------------------------
# Selecao de template (Mudanca 2 aprovada pelo usuario)
# ---------------------------------------------------------------------------


# GRUPO A (correcao desta sessao): categorias de papel usadas so' pra'
# decidir ELEGIBILIDADE/relacao entre hero e secondary - nunca pra' texto
# de prompt (isso e' `_papel_em_ingles`/`descrever_pessoa_para_prompt`).
# Achado real que motivou esta secao: com a tabela antiga (so' presenca/
# ausencia de foto, cega ao papel), um par vitima+investigador deixava
# DUOTONE_DOSSIER elegivel e o modelo escolhia ele, gerando um grid de
# "12-15 fotos" repetindo o UNICO investigador enviado - "quinze copias do
# mesmo agente" (briefing real colado no pedido desta sessao).
_CATEGORIA_ALVO = frozenset({"vitima"})
_CATEGORIA_ACUSADO = frozenset({"suspeito", "condenado"})
_CATEGORIA_AUTORIDADE = frozenset({"investigador"})


def _relacao_acusatoria(papel_a: str, papel_b: str) -> bool:
    """True quando o par (em qualquer ordem) combina um alvo (vitima) com
    um acusado (suspeito/condenado) - relacao que justifica uma seta de
    acusacao entre os dois retratos."""
    papeis = {papel_a, papel_b}
    return bool(papeis & _CATEGORIA_ALVO) and bool(papeis & _CATEGORIA_ACUSADO)


def templates_elegiveis(hero_papel: "str | None", secondary_papel: "str | None") -> tuple:
    """Tabela de selecao por PAPEL declarado. Caso so' o slot "secondary"
    esteja preenchido (sem hero - upload fora de ordem, nunca reordenamos
    os slots por conta propria), trata como "zero sujeitos utilizaveis
    pros templates de retrato".

    Regras, na ordem em que sao checadas:
    1. Sem hero: so' EVIDENCE_SCENE (nao exige papel nenhum - unico caso em
       que nao ha' foto nenhuma pra' aproveitar).
    2. So' hero (sem secondary): PROFILE_ISOLATION/DUOTONE_DOSSIER (sem
       grid - so' 1 sujeito existe).
    3. Par com um "alvo/acusado" (vitima/suspeito/condenado) E um
       "autoridade" (investigador): INVESTIGATOR_UPDATE - a referencia real
       que motivou este template (CLAUDE.md secao 5.86). Unico elegivel de
       proposito - nao ha' ambiguidade genuina a resolver nesta combinacao,
       entao `selecionar_template` nem chama a API (economia).
    4. Par vitima + suspeito/condenado (sem investigador): ARROW_TRIO ou
       DUOTONE_DOSSIER (com seta de acusacao, sem grid - papeis diferentes,
       nao ha' "12-15 fotos" de uma unica pessoa) - real ambiguidade
       estetica, o Claude escolhe.
    5. hero e secondary com o MESMO papel (ex: duas vitimas do mesmo autor):
       so' DUOTONE_DOSSIER, com grid ativado (representa MULTIPLOS
       sujeitos do mesmo papel) - unico elegivel, sem ambiguidade.
    6. Qualquer outra combinacao de DOIS sujeitos sem relacao de acusacao,
       sem autoridade envolvida e sem o mesmo papel (ex: vitima + outro,
       testemunha + outro): DUAL_PORTRAIT - unico elegivel, sem
       ambiguidade. CORRECAO (caso real Burke Ramsey/JonBenét - vitima +
       "outro", sem relacao de acusacao): antes desta correcao, esta
       combinacao caia nas opcoes de retrato SOLO (regra 2), o que
       DESCARTAVA a segunda foto enviada sem nenhuma composicao
       apropriada pra' duas pessoas sem culpa presumida entre elas.
       `outro` continua sendo `outro` - nunca reclassificado pra' habilitar
       um template (o papel declarado pelo usuario e' sempre a fonte de
       verdade, so' a ELEGIBILIDADE de template muda).

    REGRA DE SEGURANCA (achado real, nao afrouxar sem decisao explicita do
    usuario): EVIDENCE_SCENE NUNCA e' elegivel quando ha' pelo menos uma
    foto de sujeito enviada (`hero_papel` presente) - em teste real, um par
    vitima+investigador chegou a ter EVIDENCE_SCENE elegivel e escolhido, e
    a thumbnail saiu sem nenhum dos dois rostos apesar das fotos
    disponiveis. So' a regra 1 (sem hero nenhum) oferece EVIDENCE_SCENE.

    NAO afrouxar a regra do ARROW_TRIO (regra 4, `_relacao_acusatoria`) -
    DUAL_PORTRAIT so' se torna elegivel quando NENHUMA relacao mais
    especifica (autoridade, acusacao, mesmo papel) se aplica, nunca no
    lugar delas."""
    if not hero_papel:
        return ("EVIDENCE_SCENE",)

    _RETRATO_SOLO = ("PROFILE_ISOLATION", "DUOTONE_DOSSIER")

    if not secondary_papel:
        return _RETRATO_SOLO

    papeis = {hero_papel, secondary_papel}
    tem_autoridade = bool(papeis & _CATEGORIA_AUTORIDADE)
    tem_alvo_ou_acusado = bool(papeis & (_CATEGORIA_ALVO | _CATEGORIA_ACUSADO))

    if tem_autoridade and tem_alvo_ou_acusado:
        return ("INVESTIGATOR_UPDATE",)
    if _relacao_acusatoria(hero_papel, secondary_papel):
        return ("ARROW_TRIO", "DUOTONE_DOSSIER")
    if hero_papel == secondary_papel:
        return ("DUOTONE_DOSSIER",)
    return ("DUAL_PORTRAIT",)


# GRUPO (correcao do seletor - bug real de UI, nao de elegibilidade):
# ordem de desempate EXPLICITA entre templates elegiveis, usada por
# `template_preferido` pra' decidir qual pre-selecionar no dropdown
# (Grupo F) quando mais de um template estiver elegivel e nao houver
# preferencia persistida (ou a persistida nao for mais elegivel - ver
# `template_preferido`). Documentada aqui, nunca implicita na ordem de um
# dict ou na ordem em que `templates_elegiveis` monta cada tupla de
# retorno - a MESMA combinacao de papeis sempre sugere o MESMO template.
# INVESTIGATOR_UPDATE primeiro (unico template de "atualizacao de caso");
# ARROW_TRIO antes de DUOTONE_DOSSIER quando ambos empatam (par
# vitima+suspeito/condenado) porque a seta de acusacao com os dois rostos
# comunica a relacao mais diretamente que o dossie de um so' sujeito;
# DUOTONE_DOSSIER antes de PROFILE_ISOLATION quando ambos empatam (so' 1
# sujeito disponivel, ou combinacao sem relacao clara - regras 2 e 6 de
# `templates_elegiveis`) porque o tom sombrio/grunge do dossie e' mais
# chamativo como sugestao padrao que o retrato mais contido de
# PROFILE_ISOLATION - o usuario continua livre pra trocar no dropdown;
# EVIDENCE_SCENE por ultimo (na pratica e' sempre o UNICO elegivel quando
# aparece - ver regra de seguranca em `templates_elegiveis` - entao a
# posicao aqui so' importa como fallback se a lista vier vazia).
ORDEM_PREFERENCIA_TEMPLATE = (
    "INVESTIGATOR_UPDATE",
    "ARROW_TRIO",
    "DUOTONE_DOSSIER",
    "DUAL_PORTRAIT",
    "PROFILE_ISOLATION",
    "EVIDENCE_SCENE",
)


def template_preferido(elegiveis: "tuple | list") -> "str | None":
    """Desempate deterministico e explicito entre os templates elegiveis
    pro estado atual de sujeitos - usado pra' PRE-SELECIONAR o dropdown
    manual (Grupo F) na tela, nunca pra' decidir elegibilidade (isso e'
    so' `templates_elegiveis`) nem pra' composicao (mapeamento de papel
    pra' posicao visual, que continua acontecendo dentro de cada
    `montar_prompt_*`).

    Nao confundir com `selecionar_template`: quando ha' AMBIGUIDADE
    estetica real entre elegiveis (ex: ARROW_TRIO x DUOTONE_DOSSIER pro
    mesmo par vitima+suspeito), quem decide de fato pro briefing gerado
    e' a chamada de IA de `selecionar_template` (ou o usuario, via
    `template_forcado`) - esta funcao so' da' um palpite de exibicao
    ANTES de qualquer chamada de API, pra' pre-selecionar o dropdown de
    forma previsivel. Devolve None se `elegiveis` estiver vazio (nunca
    deveria acontecer - `templates_elegiveis` sempre devolve pelo menos
    um item - mas o chamador trata esse caso com fallback proprio)."""
    for candidato in ORDEM_PREFERENCIA_TEMPLATE:
        if candidato in elegiveis:
            return candidato
    return None


NOME_TOOL_SELECAO_TEMPLATE = "escolher_template_thumbnail"

_DESCRICAO_TEMPLATE = {
    "ARROW_TRIO": "dois sujeitos + seta conectando-os, ideal quando ha' uma relacao clara de acusacao/conexao (ex: suspeito -> vitima).",
    "PROFILE_ISOLATION": "um unico sujeito em perfil, ancorado num local/cenario especifico do caso - tom mais contido/reflexivo.",
    "EVIDENCE_SCENE": "sem sujeito humano em destaque - cena de evidencias/investigacao. So' elegivel quando nenhuma foto de sujeito foi enviada.",
    "DUOTONE_DOSSIER": "retrato grande de um sujeito central (perpetrador), com grid opcional de fotos-evidencia - tom sombrio/grunge.",
    "INVESTIGATOR_UPDATE": "vitima/sujeito principal + investigador/autoridade - bom pra' casos de atualizacao/desenvolvimento em andamento.",
    "DUAL_PORTRAIT": "dois sujeitos lado a lado, sem seta ENTRE os dois e sem pressupor culpa entre eles (tensao visual permitida, mas so' mirando objeto/documento/evidencia do caso) - fallback pra' qualquer combinacao de dois sujeitos sem relacao de acusacao, autoridade ou mesmo papel.",
}

# Descricao AMIGAVEL (portugues, pra' leigo) de cada template - usada no
# seletor manual da tela (Grupo F, `title` de cada opcao + linha de status
# abaixo do dropdown). Diferente de `_DESCRICAO_TEMPLATE` acima (que e'
# pro MODELO decidir, injetada no schema da chamada de selecao) - esta
# aqui e' pro USUARIO final entender o que a composicao MOSTRA e quando
# escolher, sem precisar conhecer a especificacao interna. Escrita a
# partir da composicao REAL de cada `montar_prompt_*`, nao e' so' um
# resumo do nome.
DESCRICAO_AMIGAVEL_TEMPLATE = {
    "ARROW_TRIO": (
        "Dois rostos grandes lado a lado com uma seta ligando os dois — mostra a relação de "
        "acusação entre a vítima e o suspeito/condenado. Ideal quando há foto de ambos os lados do caso."
    ),
    "PROFILE_ISOLATION": (
        "Um único rosto em close, de perfil, ancorado no local do caso ao fundo — composição mais "
        "contida e reflexiva. Ideal quando só há foto de um sujeito, ou pra dar um tom mais sóbrio."
    ),
    "EVIDENCE_SCENE": (
        "Cena de investigação sem nenhum rosto em destaque — viatura, fita policial, lupa, evidências "
        "espalhadas. Ideal quando não há foto utilizável de nenhum sujeito."
    ),
    "DUOTONE_DOSSIER": (
        "Retrato grande em preto-e-branco de um sujeito central, em tom sombrio de dossiê policial — com "
        "um painel de várias fotos da mesma pessoa (bom pra casos com múltiplas vítimas do mesmo autor) "
        "ou um retrato menor conectado por seta quando há um segundo sujeito acusado. Ideal pra dar peso "
        "dramático a um único sujeito central."
    ),
    "INVESTIGATOR_UPDATE": (
        "Estilo 'breaking news': o investigador/autoridade e a pessoa do caso lado a lado, cenário ao "
        "fundo e uma faixa de atualização no topo. Ideal pra vídeos sobre desdobramentos recentes de uma "
        "investigação em andamento."
    ),
    "DUAL_PORTRAIT": (
        "Dois rostos grandes em composição assimétrica (um domina, definido pelo eixo editorial do caso) "
        "— sem seta nem qualquer elemento ligando os dois, nunca pressupondo culpa entre eles, mas com "
        "contraste, sombra e expressão real permitidos, e tensão visual (seta/recorte) livre pra apontar "
        "pra um objeto, documento ou elemento institucional do caso. Ideal quando há foto de dois sujeitos "
        "que não têm uma relação de acusação clara entre si (ex: vítima e um familiar, duas testemunhas, "
        "vítima e uma pessoa apenas citada no caso)."
    ),
}

# Requisito de cada template em portugues, pra' tela de thumbnail (Grupo F,
# `templates/thumbnail.html`) explicar por que uma opcao esta' desabilitada
# no seletor manual - "com o motivo visivel, nao escondido". Descreve o
# REQUISITO do template (nao um diagnostico do que falta agora), pra' ficar
# correto em qualquer combinacao de papeis - ver `templates_elegiveis`. Os
# valores de ARROW_TRIO/INVESTIGATOR_UPDATE sao montados a partir das
# MESMAS constantes de categoria (`_CATEGORIA_*`) que `templates_elegiveis`
# usa pra' decidir a elegibilidade de verdade - se a lista de papeis de uma
# categoria mudar, o texto muda junto, sem editar duas vezes.
REQUISITO_TEMPLATE = {
    "ARROW_TRIO": (
        f"Requer 2 sujeitos com relação de acusação: um {'/'.join(sorted(_CATEGORIA_ALVO))} e um "
        f"{'/'.join(sorted(_CATEGORIA_ACUSADO))}."
    ),
    "PROFILE_ISOLATION": "Requer pelo menos 1 sujeito com foto enviada (sujeito principal).",
    "EVIDENCE_SCENE": "So' disponivel quando nenhuma foto de sujeito foi enviada (requer 0 sujeitos).",
    "DUOTONE_DOSSIER": "Requer pelo menos 1 sujeito com foto enviada (sujeito principal).",
    "INVESTIGATOR_UPDATE": (
        f"Requer 2 sujeitos: um {'/'.join(sorted(_CATEGORIA_AUTORIDADE))} e um "
        f"{'/'.join(sorted(_CATEGORIA_ALVO | _CATEGORIA_ACUSADO))}."
    ),
    "DUAL_PORTRAIT": "Requer 2 sujeitos com foto enviada, sem relacao de acusacao, autoridade ou mesmo papel entre eles.",
}

# Motivo CURTO de indisponibilidade - versao compacta de REQUISITO_TEMPLATE
# pra' caber inline na propria opcao do <select> (Grupo F), nao so' no
# tooltip. Mesma fonte de dados (`_CATEGORIA_*`) pros papeis envolvidos.
MOTIVO_CURTO_INDISPONIVEL = {
    "ARROW_TRIO": f"requer {'/'.join(sorted(_CATEGORIA_ALVO))} + {'/'.join(sorted(_CATEGORIA_ACUSADO))}",
    "PROFILE_ISOLATION": "requer sujeito principal",
    "EVIDENCE_SCENE": "requer 0 sujeitos",
    "DUOTONE_DOSSIER": "requer sujeito principal",
    "INVESTIGATOR_UPDATE": (
        f"requer {'/'.join(sorted(_CATEGORIA_AUTORIDADE))} + {'/'.join(sorted(_CATEGORIA_ALVO | _CATEGORIA_ACUSADO))}"
    ),
    "DUAL_PORTRAIT": "requer 2 sujeitos",
}

# Mensagem GENERICA (Fase 1 - correcao da mensagem de indisponibilidade):
# usada quando um template esta' inelegivel nao porque falta um
# REQUISITO estrutural (isso e' `MOTIVO_CURTO_INDISPONIVEL`/
# `REQUISITO_TEMPLATE` acima), e sim porque outra regra de EXCLUSIVIDADE
# de `templates_elegiveis` ja' venceu pra' este par de papeis especifico
# (ex: hero=vitima + secondary=investigador faz INVESTIGATOR_UPDATE
# vencer com exclusividade - PROFILE_ISOLATION/DUOTONE_DOSSIER/
# DUAL_PORTRAIT ficam inelegiveis mesmo com sujeito principal E 2
# sujeitos presentes). Achado real que motivou esta correcao: o texto
# fixo "requer sujeito principal"/"requer 2 sujeitos" mentia nesse
# cenario - o requisito ESTAVA atendido, so' nao era o template
# escolhido pela regra de exclusividade.
MOTIVO_GENERICO_INDISPONIVEL = "Não elegível para esta combinação de sujeitos."


def motivo_indisponibilidade(template: str, hero_papel: "str | None", secondary_papel: "str | None") -> str:
    """Motivo de indisponibilidade CONTEXTUAL de `template`, dado o estado
    ATUAL de hero_papel/secondary_papel - nunca so' o texto estatico de
    `MOTIVO_CURTO_INDISPONIVEL`, que descreve o REQUISITO do template sem
    saber se ele ja' foi atendido.

    Distingue os dois casos do pedido:
    (A) requisito estrutural nao atendido - o texto de
        `MOTIVO_CURTO_INDISPONIVEL` continua correto e e' usado como esta;
    (B) requisito atendido, mas outra regra de exclusividade de
        `templates_elegiveis` venceu pra' este par - `MOTIVO_GENERICO_
        INDISPONIVEL` e' usado no lugar, nunca afirmando que falta um
        sujeito que na verdade existe.

    So' PROFILE_ISOLATION/DUOTONE_DOSSIER (requisito: sujeito principal)
    e DUAL_PORTRAIT (requisito: 2 sujeitos) podem cair no caso (B) - os
    demais (ARROW_TRIO/INVESTIGATOR_UPDATE/EVIDENCE_SCENE) tem requisito
    que, uma vez atendido, SEMPRE ganha a regra de `templates_elegiveis`
    (nunca perde por exclusividade - ver docstring de `templates_
    elegiveis`), entao o texto estatico deles nunca fica enganoso."""
    if template in ("PROFILE_ISOLATION", "DUOTONE_DOSSIER"):
        if not hero_papel:
            return MOTIVO_CURTO_INDISPONIVEL[template]
        return MOTIVO_GENERICO_INDISPONIVEL
    if template == "DUAL_PORTRAIT":
        if not (hero_papel and secondary_papel):
            return MOTIVO_CURTO_INDISPONIVEL[template]
        return MOTIVO_GENERICO_INDISPONIVEL
    return MOTIVO_CURTO_INDISPONIVEL.get(template, "")


def motivos_indisponibilidade(hero_papel: "str | None", secondary_papel: "str | None") -> dict:
    """Atalho: monta o dict {template: motivo} pra' TODOS os templates de
    `TEMPLATES_VALIDOS`, contextualizado pro par hero_papel/secondary_papel
    atual - o que as rotas de `server.py` (tela de thumbnail e troca de
    papel) precisam pra' renderizar/atualizar o seletor manual (Grupo F)
    sem inventar mensagem enganosa."""
    return {codigo: motivo_indisponibilidade(codigo, hero_papel, secondary_papel) for codigo in TEMPLATES_VALIDOS}


# Nome de exibicao (portugues, curto) de cada template - so' pra' rotulo do
# seletor manual na tela (Grupo F). `TEMPLATES_VALIDOS` (codigo em ingles)
# continua sendo o valor real enviado/persistido. Nomes pensados pra'
# alguem que NAO conhece a especificacao interna dos templates - o
# detalhe tecnico (quantos sujeitos, qual composicao exata) fica na
# descricao (`DESCRICAO_AMIGAVEL_TEMPLATE`), nao no nome.
NOME_EXIBICAO_TEMPLATE = {
    "ARROW_TRIO": "Seta de acusação",
    "PROFILE_ISOLATION": "Perfil em destaque",
    "EVIDENCE_SCENE": "Cena de evidências",
    "DUOTONE_DOSSIER": "Retrato dossiê",
    "INVESTIGATOR_UPDATE": "Atualização de investigação",
    "DUAL_PORTRAIT": "Retrato duplo sem acusação",
}


def _schema_selecao_template(elegiveis: tuple) -> dict:
    linhas_descricao = "\n".join(f"- {nome}: {_DESCRICAO_TEMPLATE[nome]}" for nome in elegiveis)
    return {
        "name": NOME_TOOL_SELECAO_TEMPLATE,
        "description": f"Escolhe qual template de composicao de thumbnail combina melhor com o caso.\n\n{linhas_descricao}",
        "input_schema": {
            "type": "object",
            "properties": {
                "template": {"type": "string", "enum": list(elegiveis)},
                "motivo": {
                    "type": "string",
                    "description": "Frase curta explicando a escolha - fica so' na auditoria, nunca aparece pro usuario final.",
                },
            },
            "required": ["template", "motivo"],
        },
    }


def selecionar_template(
    roteiro_texto: str,
    headline: str,
    elegiveis: tuple,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
    hero_papel: "str | None" = None,
    secondary_papel: "str | None" = None,
    template_forcado: "str | None" = None,
    conceito_visual: "dict | None" = None,
) -> dict:
    """Escolhe 1 template dentro de `elegiveis` (enum FECHADO no schema -
    o modelo NUNCA pode escolher um template fora do que os papeis
    disponiveis permitem, porque a opcao nem existe no schema). Se so'
    houver 1 elegivel, nem chama a API (economia - nao ha' ambiguidade pra'
    resolver). Fallback deterministico em qualquer falha (sem chave, API
    fora do ar, resposta invalida): "EVIDENCE_SCENE" - e' o UNICO template
    elegivel quando nenhuma foto foi enviada (ver `templates_elegiveis`),
    portanto sempre seguro de usar sem julgamento nenhum. Nunca levanta
    excecao.

    `hero_papel`/`secondary_papel`: so' informam o PROMPT da chamada, pra'
    o modelo julgar com o mesmo contexto de papel que `templates_elegiveis`
    ja usou pra' montar `elegiveis`.

    `conceito_visual` (GRUPO H, sessao "conceito visual", Parte 2): resumo
    textual do conceito (elemento_principal/tipo_elemento/acao_ou_momento)
    injetado como contexto ADICIONAL no MESMO prompt que ja existe - ZERO
    chamadas novas de API. `templates_elegiveis` continua decidindo por
    CATEGORIA de papel (questao de layout, nunca de conteudo); o conceito
    visual so' ajuda o modelo a escolher, dentro do enum ja fechado, qual
    ESTETICA narra melhor esse elemento especifico (ex: um documento/
    camera sugere EVIDENCE_SCENE ou DUOTONE_DOSSIER; um confronto entre
    pessoas sugere ARROW_TRIO) - nenhum template novo, a diferenca deixa
    de estar em QUAL template e passa a estar em QUE CONTEUDO aquele
    template narra (isso e' Grupo E/G, resolvido nos `montar_prompt_*`).

    `template_forcado` (Grupo F - escolha manual do usuario na tela): se
    preenchido E presente em `elegiveis`, usa direto sem chamar a API -
    escolha explicita do usuario tem prioridade sobre a sugestao
    automatica. Fora de `elegiveis` (o usuario nao deveria conseguir
    escolher isso pela tela - templates que exigem papel ausente ficam
    desabilitados - mas a funcao nao confia so' no frontend) e' ignorado
    silenciosamente, caindo de volta na selecao automatica normal."""
    if template_forcado and template_forcado in elegiveis:
        return {"template": template_forcado, "motivo": "escolhido manualmente pelo usuario.", "fonte": "usuario", "erro": None}

    if len(elegiveis) == 1:
        return {"template": elegiveis[0], "motivo": "unico template elegivel para os papeis disponiveis.", "fonte": "unico_elegivel", "erro": None}

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return {
            "template": "EVIDENCE_SCENE",
            "motivo": "fallback deterministico - sem cliente Anthropic disponivel.",
            "fonte": "fallback_deterministico",
            "erro": "cliente_indisponivel",
        }

    trecho_roteiro = (roteiro_texto or "")[:LIMITE_CARACTERES_ROTEIRO_PARA_SELECAO]
    bloco_conceito = ""
    elemento_principal_selecao = (conceito_visual or {}).get("elemento_principal") or ""
    if elemento_principal_selecao:
        tipo_elemento_selecao = (conceito_visual or {}).get("tipo_elemento") or "outro"
        acao_selecao = (conceito_visual or {}).get("acao_ou_momento") or ""
        bloco_acao_selecao = f" durante o momento: {acao_selecao}" if acao_selecao else ""
        bloco_conceito = (
            f"Conceito visual que a thumbnail precisa mostrar ({tipo_elemento_selecao}): "
            f"{elemento_principal_selecao}{bloco_acao_selecao}. Considere qual template narra melhor "
            "ESSE elemento especifico, dentro das opcoes elegiveis abaixo.\n\n"
        )
    texto_pedido = (
        "Escolha qual template de composicao de thumbnail combina melhor com este caso de true crime/"
        f"atualidades, considerando o headline aprovado (\"{headline}\"), os papeis declarados dos sujeitos "
        f"enviados (sujeito principal: {hero_papel or 'nenhum'}; sujeito secundario: {secondary_papel or 'nenhum'}), "
        f"{bloco_conceito}"
        "e o resumo do roteiro abaixo.\n\n"
        f"Roteiro (trecho):\n{trecho_roteiro}"
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_SELECAO_TEMPLATE,
            messages=[{"role": "user", "content": texto_pedido}],
            tools=[_schema_selecao_template(elegiveis)],
            tool_choice={"type": "tool", "name": NOME_TOOL_SELECAO_TEMPLATE},
        )
    except Exception:
        logger.warning("selecionar_template: chamada a API falhou.", exc_info=True)
        return {
            "template": "EVIDENCE_SCENE",
            "motivo": "fallback deterministico - chamada de selecao falhou.",
            "fonte": "fallback_deterministico",
            "erro": "chamada_api_falhou",
        }

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_SELECAO_TEMPLATE)
    template = (dados or {}).get("template") if isinstance(dados, dict) else None
    if template not in elegiveis:
        return {
            "template": "EVIDENCE_SCENE",
            "motivo": "fallback deterministico - resposta invalida ou fora do enum elegivel.",
            "fonte": "fallback_deterministico",
            "erro": "resposta_invalida",
        }

    motivo = (dados or {}).get("motivo")
    motivo = motivo.strip() if isinstance(motivo, str) and motivo.strip() else ""
    return {"template": template, "motivo": motivo, "fonte": "ia", "erro": None}


# ---------------------------------------------------------------------------
# Selecao de PROTAGONISTA VISUAL do DUAL_PORTRAIT (Problema 1, validacao 11
# do pedido - caso real Burke Ramsey/JonBenét)
#
# DUAL_PORTRAIT nao tem seta nem grid, mas ainda precisa decidir qual dos
# dois sujeitos ocupa a posicao DOMINANTE (maior, mais central) na
# composicao - decisao de COMPOSICAO VISUAL, nunca de papel. Achado real:
# no caso "Burke Ramsey: What the 1999 DNA Test Really Proved About
# JonBenét's Brother", o titulo e' sobre BURKE, mas ele foi enviado como
# sujeito SECONDARY (JonBenét, a vitima, foi enviada primeiro, como hero) -
# sem esta decisao, o slot hero venceria so' por ordem de upload, deixando
# a pessoa errada em destaque. NUNCA reclassifica papel declarado - "outro"
# continua "outro" em `descrever_pessoa_para_prompt`, so' a POSICAO/TAMANHO
# na composicao muda.
#
# CORRECAO (achado real na VALIDACAO CONTRA A API REAL desta correcao - a
# primeira versao so' foi validada com cliente FAKE, que nao reflete o
# modelo de verdade): pedir ao modelo pra' responder com o rotulo abstrato
# "hero"/"secondary" causa erro de LIGACAO (binding) - na chamada real do
# caso Burke Ramsey, o modelo respondeu "hero" com um `motivo` que dizia
# EXPLICITAMENTE "hero (papel declarado = vitima, referente a Burke)" -
# uma contradicao factual (Burke NAO e' a vitima do caso, JonBenét e'), o
# modelo se confundiu tentando manter dois pares hero/secondary <->
# vitima/outro sincronizados na cabeca ao mesmo tempo. A correcao faz o
# modelo responder com o proprio PAPEL (o rotulo que ele ja' recebeu e' o
# rotulo que ele devolve, enum FECHADO aos dois papeis reais deste par -
# nunca "hero"/"secondary") - o codigo, nao o modelo, faz a traducao
# papel -> slot depois, eliminando esse ponto de erro. Tambem esclarece
# que "vitima" significa estritamente a vitima do CRIME (nunca uma leitura
# figurada tipo "vitima de uma suspeita injusta"), e injeta `subject_name`
# (quando disponivel) como ancora factual extra pro modelo aplicar
# conhecimento do caso real.
# ---------------------------------------------------------------------------

NOME_TOOL_PROTAGONISTA_DUAL = "escolher_protagonista_dual_portrait"


def _schema_protagonista_dual(hero_papel: str, secondary_papel: str) -> dict:
    """Schema com enum FECHADO aos dois papeis reais deste par - o modelo
    devolve o PAPEL do sujeito que fica em destaque, nunca o rotulo
    abstrato "hero"/"secondary" (ver bloco de comentario acima - correcao
    de um erro de ligacao achado na validacao contra a API real)."""
    return {
        "name": NOME_TOOL_PROTAGONISTA_DUAL,
        "description": (
            "Decide qual dos dois PAPEIS abaixo ocupa a posicao visual DOMINANTE numa composicao "
            "DUAL_PORTRAIT - decisao de COMPOSICAO, nunca de papel (o papel declarado de cada sujeito "
            "nunca muda)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "protagonista_papel": {
                    "type": "string",
                    "enum": [hero_papel, secondary_papel],
                    "description": "O PAPEL (exatamente como fornecido, nunca 'hero'/'secondary') do sujeito que deve ficar em destaque visual.",
                },
                "motivo": {
                    "type": "string",
                    "description": "Frase curta explicando a escolha - fica so' na auditoria, nunca aparece pro usuario final.",
                },
            },
            "required": ["protagonista_papel", "motivo"],
        },
    }


def selecionar_protagonista_dual_portrait(
    titulo_aprovado: str,
    headline: str,
    hero_papel: "str | None",
    secondary_papel: "str | None",
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
    subject_name: "str | None" = None,
) -> dict:
    """Decide qual SLOT (hero|secondary) fica visualmente dominante no
    DUAL_PORTRAIT, olhando pro TITULO/headline (eixo editorial) em vez de
    so' pela ordem de upload - ver bloco de comentario acima. Fallback
    deterministico em qualquer caso sem informacao suficiente pra decidir
    (sem cliente, sem titulo/headline, papeis ausentes/identicos, resposta
    invalida, excecao de API): "hero" - preserva o comportamento de sempre
    (slot hero em destaque) quando nao ha' como decidir com mais contexto.
    Nunca levanta excecao.

    `subject_name` (opcional - Grupo D, `thumbnail.subject_name`): nome do
    sujeito CENTRAL do video segundo os metadados, injetado so' como ancora
    factual extra pro modelo (nunca usado pra' mapear diretamente qual slot
    e' quem - nao ha' vinculo de upload entre nome e slot, so' entre slot e
    papel)."""
    fallback = {
        "protagonista": "hero",
        "motivo": "fallback deterministico - sem informacao suficiente pra decidir.",
        "fonte": "fallback_deterministico",
        "erro": None,
    }

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return {**fallback, "erro": "cliente_indisponivel"}

    if not (titulo_aprovado or "").strip() and not (headline or "").strip():
        return {**fallback, "erro": "contexto_insuficiente"}

    hero_papel = (hero_papel or "").strip()
    secondary_papel = (secondary_papel or "").strip()
    if not hero_papel or not secondary_papel or hero_papel == secondary_papel:
        return {**fallback, "erro": "papeis_insuficientes_ou_identicos"}

    bloco_subject_name = f"Sujeito central do video (segundo os metadados, se disponivel): {subject_name}\n" if (subject_name or "").strip() else ""

    texto_pedido = (
        "Duas fotos de sujeitos foram enviadas para uma thumbnail de composicao dupla (DUAL_PORTRAIT) - "
        "sem relacao de acusacao, autoridade ou culpa presumida entre eles. Decida qual dos dois PAPEIS "
        "abaixo deve ocupar a posicao visual DOMINANTE (maior, mais central) considerando de quem a "
        "HISTORIA do video e' realmente sobre - nunca so' pela ordem de envio.\n\n"
        "IMPORTANTE sobre os papeis: sao a categoria FIXA de cada sujeito NO CRIME/CASO que motiva o "
        "video, no vocabulario controlado do sistema - 'vitima' significa ESTRITAMENTE a vitima do "
        "crime (nunca uma leitura figurada, como 'vitima de uma suspeita injusta' ou 'vitima da midia'); "
        "'outro' significa qualquer pessoa conectada ao caso que nao se encaixa nas demais categorias "
        "(suspeito/condenado/investigador/testemunha/vitima). Use conhecimento factual do caso (se for "
        "um caso real conhecido) pra' identificar corretamente qual dos dois papeis abaixo corresponde a' "
        "pessoa que o titulo/headline realmente centraliza - nao presuma que o papel mais grave (ex: "
        "vitima) e' automaticamente o protagonista do video.\n\n"
        f"Titulo aprovado do video: {titulo_aprovado or '(nao disponivel)'}\n"
        f"Headline da thumbnail: {headline or '(nao disponivel)'}\n"
        f"{bloco_subject_name}"
        f"Papel do primeiro sujeito (foto enviada no slot principal): {hero_papel}\n"
        f"Papel do segundo sujeito (foto enviada no slot secundario): {secondary_papel}\n\n"
        "Responda com EXATAMENTE um dos dois papeis acima (copie o texto exato) - nunca 'hero'/"
        "'secondary', esses rotulos sao so' de uso interno do sistema."
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=256,
            messages=[{"role": "user", "content": texto_pedido}],
            tools=[_schema_protagonista_dual(hero_papel, secondary_papel)],
            tool_choice={"type": "tool", "name": NOME_TOOL_PROTAGONISTA_DUAL},
        )
    except Exception:
        logger.warning("selecionar_protagonista_dual_portrait: chamada a API falhou.", exc_info=True)
        return {**fallback, "erro": "chamada_api_falhou"}

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_PROTAGONISTA_DUAL)
    papel_escolhido = (dados or {}).get("protagonista_papel") if isinstance(dados, dict) else None
    if papel_escolhido == hero_papel:
        protagonista = "hero"
    elif papel_escolhido == secondary_papel:
        protagonista = "secondary"
    else:
        return {**fallback, "erro": "resposta_invalida"}

    motivo = (dados or {}).get("motivo")
    motivo = motivo.strip() if isinstance(motivo, str) and motivo.strip() else ""
    return {"protagonista": protagonista, "motivo": motivo, "fonte": "ia", "erro": None}


# ---------------------------------------------------------------------------
# Sessao "conceito visual", Grupo D - relacao entre o elemento_principal e
# os sujeitos (parte SUBJECT-DEPENDENT, por isso vive aqui e nao no
# Headline Engine - scripts/headline_engine.py:extrair_payload_editorial
# roda ANTES de qualquer sujeito existir, nunca pode saber a quem um
# elemento pertence). Unica chamada de API NOVA desta sessao.
# ---------------------------------------------------------------------------

NOME_TOOL_RELACAO_CONCEITO = "resolver_relacao_conceito_sujeitos"
_PAPEL_INDETERMINADO = "indeterminado"


def _schema_relacao_conceito(hero_papel: str, secondary_papel: str) -> dict:
    """Enum FECHADO aos dois papeis reais deste par + o sentinela
    "indeterminado" (mesmo padrao de `_schema_protagonista_dual` -
    correcao ja validada contra API real: o modelo responde com o PAPEL,
    nunca com o rotulo abstrato "hero"/"secondary", o codigo faz essa
    traducao depois)."""
    return {
        "name": NOME_TOOL_RELACAO_CONCEITO,
        "description": (
            "Decide a qual dos dois PAPEIS abaixo (ou nenhum, se indeterminado) o elemento visual do "
            "conceito principal do video pertence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pertence_a_papel": {
                    "type": "string",
                    "enum": [hero_papel, secondary_papel, _PAPEL_INDETERMINADO],
                    "description": "O PAPEL (exatamente como fornecido) do sujeito a quem o elemento pertence, ou 'indeterminado'.",
                },
                "motivo": {
                    "type": "string",
                    "description": "Frase curta explicando a escolha - fica so' na auditoria, nunca aparece pro usuario final.",
                },
            },
            "required": ["pertence_a_papel", "motivo"],
        },
    }


def resolver_relacao_com_sujeitos(
    conceito_visual: "dict | None",
    hero_papel: "str | None",
    secondary_papel: "str | None",
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
) -> "str | None":
    """Resolve a QUEM (hero ou secondary) o `elemento_principal` do
    conceito visual (extraido pelo Headline Engine, scripts/
    headline_engine.py Grupo A) pertence - decisao subject-dependent que o
    motor nao pode tomar sozinho, porque roda ANTES de qualquer sujeito
    existir.

    So' dispara a chamada quando ha' AMBIGUIDADE REAL: os DOIS slots
    (hero E secondary) precisam estar preenchidos com papeis distintos -
    com zero ou um sujeito so', nao ha' o que desambiguar (devolve None
    sem gastar chamada nenhuma - o unico candidato, se houver, ja' e' obvio
    pelo contexto, nao precisa de uma decisao explicita aqui). Qualquer
    falha (sem elemento_principal, sem cliente, excecao de API, resposta
    invalida, ou o proprio modelo respondendo "indeterminado") devolve
    `None` - fallback SEGURO, nunca bloqueia o briefing nem inventa uma
    relacao que a chamada nao confirmou (CLAUDE.md secao 18.4). Consumo
    do valor devolvido (pelos templates de composicao) e' Grupo E/G desta
    mesma sessao - aqui so' resolve e devolve."""
    elemento_principal = (conceito_visual or {}).get("elemento_principal") or ""
    hero_papel = (hero_papel or "").strip()
    secondary_papel = (secondary_papel or "").strip()

    if not elemento_principal:
        return None
    if not hero_papel or not secondary_papel or hero_papel == secondary_papel:
        return None

    cliente_api = _obter_cliente(api_key, cliente)
    if cliente_api is None:
        return None

    tipo_elemento = (conceito_visual or {}).get("tipo_elemento") or "outro"
    acao_ou_momento = (conceito_visual or {}).get("acao_ou_momento") or ""
    bloco_acao = f"Acao/momento associado: {acao_ou_momento}\n" if acao_ou_momento else ""

    texto_pedido = (
        "Um elemento visual concreto foi identificado como o CONCEITO VISUAL deste video - a thumbnail "
        "precisa mostra-lo. Dois sujeitos (com fotos reais enviadas) estao disponiveis para esta "
        "composicao. Decida a qual dos dois PAPEIS abaixo esse elemento pertence - ou responda "
        f"'{_PAPEL_INDETERMINADO}' se genuinamente nao for possivel decidir com confianca a partir da "
        "informacao fornecida (nunca adivinhe).\n\n"
        f"Elemento principal: {elemento_principal}\n"
        f"Tipo do elemento: {tipo_elemento}\n"
        f"{bloco_acao}\n"
        f"Papel do primeiro sujeito: {hero_papel}\n"
        f"Papel do segundo sujeito: {secondary_papel}\n\n"
        "Responda com EXATAMENTE um dos dois papeis acima (copie o texto exato), ou "
        f"'{_PAPEL_INDETERMINADO}'."
    )

    try:
        resposta = cliente_api.messages.create(
            model=modelo,
            max_tokens=256,
            messages=[{"role": "user", "content": texto_pedido}],
            tools=[_schema_relacao_conceito(hero_papel, secondary_papel)],
            tool_choice={"type": "tool", "name": NOME_TOOL_RELACAO_CONCEITO},
        )
    except Exception:
        logger.warning("resolver_relacao_com_sujeitos: chamada a API falhou.", exc_info=True)
        return None

    if _custos is not None:
        _custos.append(_custo_usd_da_resposta(resposta))

    dados = _extrair_tool_use(resposta, NOME_TOOL_RELACAO_CONCEITO)
    papel_escolhido = (dados or {}).get("pertence_a_papel") if isinstance(dados, dict) else None
    if papel_escolhido == hero_papel:
        return "hero"
    if papel_escolhido == secondary_papel:
        return "secondary"
    return None


# ---------------------------------------------------------------------------
# Montagem do prompt final = template (codigo) + caso (dados)
# ---------------------------------------------------------------------------


def _linha_pequena_e_grande(caso: dict, pequena_padrao: str) -> tuple:
    """Deriva (linha pequena, linha grande) pros templates 1-4, que usam
    DUAS linhas de hierarquia de texto (ao contrario do INVESTIGATOR_
    UPDATE - unico que usa headline+emphasis_word de UMA linha so' com
    duas cores, Correcao 1).

    GRUPO B (correcao desta sessao - Headline Engine): a linha GRANDE e'
    SEMPRE o headline vencedor do Headline Engine - a peca com lacuna de
    curiosidade (CLAUDE.md secao 5.86), maior elemento textual, exatamente
    como nas referencias reais medidas na Fase 1. ANTES desta correcao a
    cascata era `subject_name -> emphasis_word -> headline`, o que fazia o
    NOME DO CASO (ex: "NANCY GUTHRIE") virar a linha grande no lugar do
    headline com lacuna - achado real, briefing colado no pedido desta
    sessao. subject_name nunca ocupa a linha grande aqui - nome proprio
    informa, nao abre lacuna de curiosidade; onde faz sentido como rotulo
    de caso (ex: label pequeno de PROFILE_ISOLATION, ou o topo de
    INVESTIGATOR_UPDATE) ele entra separado, nunca substituindo o
    headline. Sem cascata de fallback silencioso: quem chama esta funcao
    ja' recebeu um `headline` garantido nao-vazio (checado antes, em
    `gerar_briefing_completo`).

    - linha pequena: thumbnail.secondary (contexto curto ja gerado pelo
      Grupo D) se preenchido, senao `pequena_padrao` (fallback fixo por
      template, ex: "THE CASE OF")."""
    pequena = (caso.get("secondary_texto") or pequena_padrao).strip().upper()
    grande = (caso.get("headline") or "").strip().upper()
    return pequena, grande


def montar_prompt_arrow_trio(caso: dict) -> tuple:
    hero_desc = descrever_pessoa_para_prompt(caso["hero_papel"], caso.get("hero_atributos"))
    secondary_desc = descrever_pessoa_para_prompt(caso["secondary_papel"], caso.get("secondary_atributos"))
    accent = caso.get("accent") or ACCENT_PADRAO
    conceito_visual = caso.get("conceito_visual")
    clausula_conceito = montar_clausula_conceito_visual(conceito_visual)
    background_desc = _frase_dominancia_conceito(
        clausula_conceito,
        (conceito_visual or {}).get("papel_na_composicao"),
        caso.get("background_prompt") or "a dark, atmospheric crime-scene backdrop",
    )
    headline_pequena, headline_grande = _linha_pequena_e_grande(caso, "THE CASE OF")

    # CORRECAO 2 (regra de seguranca aprovada pelo usuario): a tarja de
    # censura SO' pode cobrir os olhos do secondary quando (a) o usuario
    # pediu explicitamente (thumbnail.censor == True) E (b) o papel
    # declarado do secondary e' "suspeito" ou "condenado". Qualquer outro
    # papel (vitima/investigador/testemunha/outro) NUNCA e' censurado, m
    # esmo com censor=True - cobrir os olhos de uma vitima e' erro
    # editorial grave, nao uma escolha estetica. Guarda de codigo, nao
    # texto opcional bonito - a condicao (b) e' checada aqui SEMPRE, o
    # campo `censor` sozinho nunca decide.
    papel_secondary_censuravel = caso["secondary_papel"] in ("suspeito", "condenado")
    aplicar_censura = bool(caso.get("censor")) and papel_secondary_censuravel

    tertiary_clause = ""
    if caso.get("tertiary_atributos") is not None or caso.get("tertiary_papel"):
        tertiary_desc = descrever_pessoa_para_prompt(caso.get("tertiary_papel", "outro"), caso.get("tertiary_atributos"))
        tertiary_clause = f", and a {tertiary_desc} on the far right"

    censor_clause = ""
    if aplicar_censura:
        texto_censura = (caso.get("subject_name") or _SUBSTANTIVO_CURTO_POR_PAPEL[caso["secondary_papel"]]).upper()
        censor_clause = f' Cover the {_papel_em_ingles(caso["secondary_papel"])}\'s eyes with a red censorship bar containing white text "{texto_censura}".'

    prompt = (
        "Create a 16:9 professional true-crime YouTube thumbnail. Three-part composition: "
        f"a large {secondary_desc} on the left, a large {hero_desc} as the main subject in the center-right"
        f"{tertiary_clause}. Behind them, {background_desc}. Add a large curved {accent} arrow pointing from "
        f"the {_papel_em_ingles(caso['secondary_papel'])} toward the {_papel_em_ingles(caso['hero_papel'])}. "
        "Add yellow crime-scene tape across "
        f"the lower-right.{censor_clause} Bottom-left typography: \"{headline_pequena}\" in bold white "
        f"uppercase, followed by \"{headline_grande}\" in huge bold {accent} uppercase. Strong white rim "
        "lighting around people, high contrast, dark cinematic background, realistic photography, dramatic "
        "true-crime aesthetic, clean professional compositing."
    )
    return prompt, {"censura_aplicada": aplicar_censura, "censura_papel_secondary": caso["secondary_papel"]}


def montar_prompt_profile_isolation(caso: dict) -> tuple:
    hero_desc = descrever_pessoa_para_prompt(caso["hero_papel"], caso.get("hero_atributos"))
    accent = caso.get("accent") or ACCENT_PADRAO
    conceito_visual = caso.get("conceito_visual")
    clausula_conceito = montar_clausula_conceito_visual(conceito_visual)
    background_desc = _frase_dominancia_conceito(
        clausula_conceito,
        (conceito_visual or {}).get("papel_na_composicao"),
        caso.get("background_prompt") or "the location central to the case",
    )
    headline_pequena, headline_grande = _linha_pequena_e_grande(caso, "WHAT HAPPENED")

    # GRUPO B (correcao desta sessao): antes, este label repetia o proprio
    # `headline` (ja' virou headline_grande acima) - texto duplicado na
    # imagem. subject_name (nome do caso) e' o unico uso legitimo que sobra
    # pra' este label pequeno agora que ele nao ocupa mais a linha grande -
    # omitido por inteiro quando nao ha' subject_name, nunca cai de volta
    # pro headline.
    subject_name = (caso.get("subject_name") or "").strip().upper()[:40]
    label_clause = f', and "{subject_name}" inside a small off-white label below it' if subject_name else ""

    prompt = (
        f"Create a 16:9 cinematic true-crime YouTube thumbnail. Show {background_desc} as the main "
        "background, with subtle atmospheric lighting and a mysterious atmosphere. Place a large "
        f"{hero_desc} in side-profile close-up on the left, looking toward the background. On the "
        f"center-right, add the text \"{headline_pequena}\" in small white uppercase letters, "
        f"\"{headline_grande}\" in huge bold {accent} uppercase letters{label_clause}. Dark blue-black "
        "color palette, cinematic lighting, subtle fog, realistic photography, strong contrast, minimal "
        "clutter, professional documentary thumbnail composition."
    )
    return prompt, {"censura_aplicada": False}


# ---------------------------------------------------------------------------
# GRUPO E/G (sessao "conceito visual", Parte 2) - clausula compartilhada do
# conceito visual + prioridade semantica sobre o background_prompt.
#
# Substitui por inteiro `_descricao_evidencia_central`/o campo
# `evidencia_central` (removidos do Grupo D - scripts/7_thumbnail.py - na
# Parte 1, ver HISTORICO_BUGS.md): o conceito visual (elemento_principal/
# tipo_elemento/acao_ou_momento/revelacao/papel_na_composicao, extraido
# pela Grupo A do Headline Engine) e' a fonte unica de ancoragem visual
# concreta agora.
# ---------------------------------------------------------------------------

def montar_clausula_conceito_visual(conceito: "dict | None") -> str:
    """GRUPO E. Funcao PURA (mesmo padrao de `_linha_pequena_e_grande`) -
    a clausula do conceito visual e' montada em CODIGO, nunca pedida a' IA
    como texto livre. Mesma classe de bug ja' conhecida neste modulo
    (`_ajustar_genero_e_prefixo_para_crianca`): concatenar campos soltos
    sem checar a RELACAO entre eles produz texto incoerente ou fraco - aqui
    o risco analogo e' mencionar "doorbell camera" e "tattoo" como dois
    fragmentos soltos em vez da cadeia causal entre eles (validado contra
    a API real no caso Nancy Guthrie - Grupo K).

    Correcao (sessao "relacao causal do conceito visual"): a versao
    anterior prefixava `elemento_principal` com uma traducao generica de
    `tipo_elemento` (ex: "a piece of recording/camera equipment, the
    doorbell camera...") - redundante quando `elemento_principal` ja'
    nomeia a coisa concreta, entao esse prefixo saiu. E o conector entre
    `acao_ou_momento` e `revelacao` era "- a moment that directly leads
    to {revelacao}", que produz frase quebrada sempre que `revelacao` ja'
    vem como oracao completa (sujeito+verbo) da IA - caso real: "a moment
    that directly leads to the blocking motion rotates his wrist...".
    `revelacao` e' tipicamente uma oracao (nao um substantivo), entao o
    conector "as" (causal/temporal) encaixa gramaticalmente nos dois
    formatos sem forcar `revelacao` a completar a frase de `acao_ou_
    momento`.

    Sem `elemento_principal`: devolve "" (nada pra' compor - os
    montadores tratam clausula vazia como ausencia total, nunca quebram -
    cobre tanto falha do Grupo A quanto projeto antigo sem conceito_visual
    nenhum).
    So' `elemento_principal`: descreve so' o elemento.
    + `acao_ou_momento` (sem `revelacao`): liga elemento -> acao/momento.
    + `revelacao` sem `acao_ou_momento` (defensivo - `_normalizar_
    conceito_visual` no Headline Engine ja' zera os dois juntos se um
    faltar, entao esse ramo nao deveria disparar em producao, mas a
    funcao nunca inventa uma acao pra' preencher o vazio): descreve so' a
    revelacao, ligada ao elemento.
    + `acao_ou_momento` + `revelacao`: cadeia causal COMPLETA elemento ->
    acao -> revelacao numa unica oracao, motivo desta funcao existir em
    vez de so' concatenar os 3 campos lado a lado."""
    conceito = conceito or {}
    elemento_principal = (conceito.get("elemento_principal") or "").strip()
    if not elemento_principal:
        return ""

    acao_ou_momento = (conceito.get("acao_ou_momento") or "").strip()
    revelacao = (conceito.get("revelacao") or "").strip()

    if not acao_ou_momento and not revelacao:
        return f"The image must prominently feature {elemento_principal}."

    if acao_ou_momento and not revelacao:
        return (
            f"The image must prominently feature {elemento_principal}, captured in the exact "
            f"moment of {acao_ou_momento}."
        )

    if revelacao and not acao_ou_momento:
        return (
            f"The image must prominently feature {elemento_principal}, with {revelacao} clearly "
            "visible in the same shot."
        )

    return (
        f"The image must prominently feature {elemento_principal}, captured in the exact moment of "
        f"{acao_ou_momento}, as {revelacao}. Render this cause-and-effect chain visually (the action "
        "and what it reveals), never the elements in isolation."
    )


def _frase_dominancia_conceito(clausula_conceito: str, papel_composicao: "str | None", background_desc: str) -> str:
    """GRUPO G. Combina `background_desc` com `clausula_conceito` sem que
    um jamais SUBSTITUA o outro - perderia contexto visual (os dois
    coexistem: o conceito define o que a imagem PRECISA mostrar, o fundo
    define o ambiente ao redor dele). `clausula_conceito` vazia (Grupo A
    falhou, ou projeto antigo sem conceito_visual) devolve so'
    `background_desc` - comportamento identico ao de antes desta sessao.

    'dominante': o conceito ocupa o CENTRO da composicao - vem PRIMEIRO no
    texto, com uma frase explicita de precedencia, e o fundo fica
    textualmente subordinado (mencionado depois, como pano de fundo
    secundario). 'apoio' (default, inclusive `papel_na_composicao`
    ausente/invalido): o fundo continua a ancora visual primaria, o
    conceito entra como detalhe concreto DENTRO da cena."""
    if not clausula_conceito:
        return background_desc
    if papel_composicao == "dominante":
        return (
            f"{clausula_conceito} This is the dominant, central focal point of the composition - more "
            f"prominent than any background detail. As a secondary backdrop behind it, {background_desc}"
        )
    return f"{background_desc}, with this concrete detail from the case visible in the scene: {clausula_conceito}"


def montar_prompt_evidence_scene(caso: dict) -> tuple:
    accent = caso.get("accent") or ACCENT_PADRAO
    conceito_visual = caso.get("conceito_visual")
    clausula_conceito = montar_clausula_conceito_visual(conceito_visual)
    background_desc = _frase_dominancia_conceito(
        clausula_conceito,
        (conceito_visual or {}).get("papel_na_composicao"),
        caso.get("background_prompt") or "a nighttime crime scene",
    )
    headline_pequena, headline_grande = _linha_pequena_e_grande(caso, "THE CASE OF")

    # CORRECAO 3 (aprovada): este template e' elegivel mesmo COM fotos
    # disponiveis - a foto de evidencia so' entra se o papel "vitima"
    # estiver presente entre hero/secondary, nunca obrigatorio.
    papel_evidencia_disponivel = "vitima" in (caso.get("hero_papel"), caso.get("secondary_papel"))
    evidence_photo_clause = " a small victim photograph," if papel_evidencia_disponivel else ""

    prompt = (
        f"Create a 16:9 gritty true-crime YouTube thumbnail. Background: {background_desc}, with police "
        f"cars, flashing lights and atmospheric fog. Add yellow police tape,{evidence_photo_clause} "
        "magnifying glass, forensic evidence marker, abandoned gloves and old "
        "newspaper clippings layered around the scene. Center the huge headline "
        f"\"{headline_pequena}\" in distressed bold white "
        f"uppercase letters and \"{headline_grande}\" directly below in huge distressed {accent} uppercase "
        "letters. Dark gray, black, yellow and red palette, cinematic crime-scene photography, film grain, "
        "aged investigative-document aesthetic, dramatic depth and professional editorial compositing."
    )
    return prompt, {"censura_aplicada": False}


def montar_prompt_duotone_dossier(caso: dict) -> tuple:
    hero_desc = descrever_pessoa_para_prompt(caso["hero_papel"], caso.get("hero_atributos"))
    accent = caso.get("accent") or ACCENT_PADRAO
    conceito_visual = caso.get("conceito_visual")
    clausula_conceito = montar_clausula_conceito_visual(conceito_visual)
    # GRUPO G (Parte 2): este template nao usa `background_prompt` (nunca
    # usou) - o fundo generico da cena (fita/texturas, linha fixa abaixo)
    # ja' e' o "ambiente", entao a mesma prioridade dominante/apoio se
    # aplica contra ESSE fundo generico em vez de um `background_desc`
    # dedicado.
    fundo_generico = f"blurred yellow crime-scene tape, {accent}-black textures and subtle forensic graphics"
    fundo_com_conceito = _frase_dominancia_conceito(
        clausula_conceito, (conceito_visual or {}).get("papel_na_composicao"), fundo_generico
    )
    headline_pequena, headline_grande = _linha_pequena_e_grande(caso, "THE CASE OF")

    # GRUPO A (correcao desta sessao): o grid de "12-15 fotos" so' faz
    # sentido representando MULTIPLOS sujeitos do MESMO papel (ex: varias
    # vitimas do mesmo autor) - antes, qualquer secondary presente virava
    # grid, mesmo quando secondary era um UNICO investigador (achado real:
    # "quinze copias do mesmo agente", briefing colado no pedido). Papeis
    # diferentes com relacao de acusacao clara (vitima <-> suspeito/
    # condenado) usam seta com UMA foto, nunca grid. Qualquer outra
    # combinacao (ex: hero+investigador, que `templates_elegiveis` nem
    # deixa chegar aqui na pratica - vai pra' INVESTIGATOR_UPDATE) degrada
    # pro retrato solo, sem clausula nenhuma - nunca inventa uma relacao
    # visual que os papeis declarados nao sustentam.
    secondary_papel = caso.get("secondary_papel")
    secondary_clause = ""
    if secondary_papel and secondary_papel == caso["hero_papel"]:
        secondary_curto = descrever_papel_curto(secondary_papel, caso.get("secondary_atributos"))
        secondary_clause = (
            " On the left, show a tilted evidence-board panel containing approximately 12-15 "
            f"black-and-white {secondary_curto} photographs arranged in a grid. Add a large {accent} arrow "
            f"pointing from the photographs toward the {_papel_em_ingles(caso['hero_papel'])}."
        )
    elif secondary_papel and _relacao_acusatoria(caso["hero_papel"], secondary_papel):
        secondary_desc = descrever_pessoa_para_prompt(secondary_papel, caso.get("secondary_atributos"))
        secondary_clause = (
            f" On the left, add a smaller portrait of a {secondary_desc}. Add a large {accent} arrow "
            f"pointing from the {_papel_em_ingles(secondary_papel)} toward the {_papel_em_ingles(caso['hero_papel'])}."
        )

    prompt = (
        "Create a 16:9 dramatic true-crime YouTube thumbnail. On the right, place an enormous "
        f"high-contrast black-and-white portrait of a {hero_desc}, with intense expression and {accent} "
        f"atmospheric lighting behind them.{secondary_clause} Background: {fundo_com_conceito}. "
        f"Bottom-left {accent} "
        f"banner containing \"{headline_pequena}\" in white italic uppercase and \"{headline_grande}\" in "
        "extremely large white uppercase letters. Aggressive visual hierarchy, cinematic lighting, gritty "
        "investigative aesthetic, professional YouTube thumbnail."
    )
    return prompt, {"censura_aplicada": False}


def montar_prompt_investigator_update(caso: dict) -> tuple:
    hero_desc = descrever_pessoa_para_prompt(caso["hero_papel"], caso.get("hero_atributos"))
    accent = caso.get("accent") or ACCENT_PADRAO
    conceito_visual = caso.get("conceito_visual")
    clausula_conceito = montar_clausula_conceito_visual(conceito_visual)
    background_desc = _frase_dominancia_conceito(
        clausula_conceito,
        (conceito_visual or {}).get("papel_na_composicao"),
        caso.get("background_prompt") or "the location central to the case, at night",
    )
    case_name = (caso.get("subject_name") or "CASE").strip().upper()

    secondary_clause = ""
    if caso.get("secondary_papel"):
        secondary_desc = descrever_pessoa_para_prompt(caso["secondary_papel"], caso.get("secondary_atributos"))
        secondary_clause = f"a {secondary_desc}"
    else:
        secondary_clause = "a blurred, out-of-focus silhouette integrated into the background"

    tertiary_clause = ""
    rotulo_terciario = caso.get("tertiary_label")
    if rotulo_terciario and caso.get("secondary_papel"):
        tertiary_clause = (
            f' Add a red brush-stroke label near the {_papel_em_ingles(caso["secondary_papel"])} reading '
            f'"{rotulo_terciario}", with a red arrow pointing toward them.'
        )

    # CORRECAO 1 (bug corrigido - aprovada pelo usuario): a referencia real
    # ("WHAT ABDUCTOR WANTED") e' UM headline com DUAS cores, nao duas
    # linhas separadas - usa os campos REAIS ja existentes no schema
    # (headline + emphasis_word do Headline Engine) em vez de inventar
    # HEADLINE_SMALL/HEADLINE_LARGE. emphasis_word vazio (ja tratado em
    # _normalizar_thumbnail_metadados quando nao e' substring literal do
    # headline) cai numa frase sem cor de destaque - nunca quebra.
    headline = (caso.get("headline") or "").strip()
    emphasis_word = (caso.get("emphasis_word") or "").strip()
    # GRUPO G (achado da validacao empirica desta sessao, nancyGuthrieProject03):
    # o headline vem de thumbnail/metadados.json em Title Case ("The Mark
    # On His Wrist"), nao em uppercase - sem `.upper()` aqui o texto
    # inserido no prompt contradizia a propria instrucao "in white
    # uppercase" logo ao lado. A checagem de substring usa o texto
    # ORIGINAL (mesmo case que o Headline Engine garantiu), so' a
    # exibicao no prompt e' maiuscula.
    if headline and emphasis_word and emphasis_word in headline:
        bottom_clause = (
            f'Bottom: huge headline "{headline.upper()}", with "{emphasis_word.upper()}" in {accent} uppercase '
            "and the rest of the headline in white uppercase."
        )
    else:
        bottom_clause = f'Bottom: huge headline "{headline.upper()}" in white uppercase.'

    prompt = (
        f'Create a 16:9 high-impact true-crime breaking-news YouTube thumbnail. Top: huge bold yellow text '
        f'"{case_name} UPDATE". Left: {secondary_clause}. Center background: {background_desc}. Right: an '
        f"enormous close-up portrait of a {hero_desc} with realistic skin texture and an intense emotional "
        f"expression.{tertiary_clause} {bottom_clause} Dark navy/black palette with yellow, white and red "
        "accents, cinematic lighting, realistic photography, dramatic contrast, professional true-crime "
        "editorial composition."
    )
    return prompt, {"censura_aplicada": False}


def montar_prompt_dual_portrait(caso: dict) -> tuple:
    """DUAL_PORTRAIT (Problema 1 do pedido - caso real Burke Ramsey/
    JonBenét): fallback pra' qualquer combinacao de DOIS sujeitos sem
    relacao de acusacao clara (ARROW_TRIO/DUOTONE_DOSSIER), sem autoridade
    envolvida (INVESTIGATOR_UPDATE) e sem o mesmo papel (DUOTONE_DOSSIER
    com grid) - ver `templates_elegiveis` regra 6. Nunca usa
    `_relacao_acusatoria`/censura, mesmo que `caso.get("censor")` venha
    True (nao ha' "acusado" nesta composicao pra' justificar censura).

    CORRECAO (achado real, caso Burke Ramsey - ver HISTORICO_BUGS.md):
    a versao anterior traduzia "nao implicar culpa" em "sem tensao
    nenhuma" - briefing real saiu com "no visual implication of guilt or
    accusation between them" / "calm, contemplative half-smile" /
    "Neutral, balanced lighting, composed and dignified" / "portraits of
    equal visual importance", resultando numa composicao parecida com
    retrospectiva memorial, num feed onde a concorrencia usa alto
    contraste e carga emocional. Sao DUAS coisas diferentes: nao
    implicar culpa (correto e obrigatorio - Burke foi excluido por DNA e
    exonerado por carta oficial, insinuar culpa dele visualmente e'
    exatamente o ato que gerou o processo dele contra a CBS) e nao ter
    tensao (erro - a tensao pode e deve existir, apontando pra' OUTRO
    lugar). A restricao agora e' sobre o ALVO da tensao, nunca sobre a
    existencia dela:
    - PERMITIDO: alto contraste e sombras, composicao assimetrica,
      expressao emocional real (nunca um meio-sorriso neutro), setas/
      circulos/recortes apontando pra' OBJETO, DOCUMENTO, EVIDENCIA ou
      ELEMENTO INSTITUCIONAL (o conceito visual - `clausula_conceito`,
      GRUPO E/G da sessao "conceito visual" - quando disponivel),
      contraste cromatico e elementos de tensao temporal
    - PROIBIDO: qualquer seta, fita, ou elemento visual LIGANDO ou
      apontando de um sujeito PRA' o outro (isso sim implicaria
      acusacao/culpa entre os dois) - a tensao da composicao nunca mira
      numa pessoa, so' no elemento concreto do caso
    "Equal visual importance" foi removido de proposito: quando ha'
    protagonista definido pelo eixo editorial (`caso["protagonista"]`
    abaixo), ele DEVE dominar a composicao - dizer "importancia visual
    igual" no mesmo prompt que descreve um "dominante"/"complementar"
    era uma contradicao textual que confundia o gerador de imagem.

    `caso["protagonista"]` (validacao 11 do pedido - `selecionar_
    protagonista_dual_portrait`, decidido pelo EIXO EDITORIAL do caso, nao
    pelo slot em que a foto foi enviada) decide qual descricao ocupa a
    posicao DOMINANTE - "hero" (padrao, quando a decisao nao rodou ou nao
    houve informacao suficiente) preserva o comportamento de sempre. Papel
    declarado de cada sujeito nunca muda por causa dessa escolha - so' a
    POSICAO/TAMANHO na composicao."""
    hero_desc = descrever_pessoa_para_prompt(caso["hero_papel"], caso.get("hero_atributos"))
    secondary_desc = descrever_pessoa_para_prompt(caso["secondary_papel"], caso.get("secondary_atributos"))
    accent = caso.get("accent") or ACCENT_PADRAO
    # A tensao mira o elemento concreto do caso (documento/objeto/local/
    # camera), NUNCA uma das duas pessoas - o conceito visual e' exatamente
    # esse elemento (GRUPO E/G, Parte 2 - substitui o antigo
    # `_descricao_evidencia_central`/`evidencia_central`, removido do
    # Grupo D - ver HISTORICO_BUGS.md). Mesmo mecanismo de prioridade
    # dominante/apoio dos outros 5 montadores, aplicado aqui contra o
    # `background_prompt` deste template.
    conceito_visual = caso.get("conceito_visual")
    clausula_conceito = montar_clausula_conceito_visual(conceito_visual)
    background_desc = _frase_dominancia_conceito(
        clausula_conceito,
        (conceito_visual or {}).get("papel_na_composicao"),
        caso.get("background_prompt") or "a dark, atmospheric backdrop related to the case",
    )
    headline_pequena, headline_grande = _linha_pequena_e_grande(caso, "THE CASE OF")

    protagonista = caso.get("protagonista") or "hero"
    if protagonista == "secondary":
        principal_desc, complementar_desc = secondary_desc, hero_desc
    else:
        principal_desc, complementar_desc = hero_desc, secondary_desc

    prompt = (
        "Create a 16:9 true-crime YouTube thumbnail with two portraits in an asymmetric composition - no "
        "arrow, no crime-scene tape, no visual implication of guilt or accusation between them, and no "
        f"visual element connecting or pointing from one person toward the other (any visual tension points "
        f"only at a concrete object/document/location from the case, never at either person). On one side, "
        f"a large {principal_desc}, in the dominant position, closer to camera, with a genuine, weighted "
        "emotional expression (never a neutral or calm half-smile) under dramatic directional lighting with "
        f"deep shadows. On the other side, a {complementar_desc}, positioned smaller and further back, in a "
        f"deliberately unbalanced, complementary composition. Behind them, {background_desc}. "
        f"Bottom typography: \"{headline_pequena}\" in bold white uppercase, followed by \"{headline_grande}\" "
        f"in huge bold {accent} uppercase. High-contrast dramatic lighting, strong chromatic contrast, realistic "
        "photography, professional true-crime editorial compositing."
    )
    return prompt, {"censura_aplicada": False, "protagonista": protagonista}


_MONTADORES = {
    "ARROW_TRIO": montar_prompt_arrow_trio,
    "PROFILE_ISOLATION": montar_prompt_profile_isolation,
    "EVIDENCE_SCENE": montar_prompt_evidence_scene,
    "DUOTONE_DOSSIER": montar_prompt_duotone_dossier,
    "INVESTIGATOR_UPDATE": montar_prompt_investigator_update,
    "DUAL_PORTRAIT": montar_prompt_dual_portrait,
}


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------


def gerar_briefing_completo(
    pasta_projeto: Path,
    api_key: str,
    modelo: str = MODELO_PADRAO,
    cliente=None,
    _custos: list | None = None,
    template_forcado: "str | None" = None,
) -> dict:
    """Ponto de entrada do Grupo C. Le thumbnail/metadados.json (headline/
    emphasis_word/secondary/accent/censor/subject_name/background_prompt,
    ja' gerados pelo Grupo D + Headline Engine - nunca gera headline aqui
    de novo) e thumbnail/sujeitos/sujeitos.json (papeis declarados no
    upload - Grupo B), extrai atributos visuais por foto (Vision leve ou
    fallback deterministico), escolhe 1 dos 5 templates (enum fechado ao
    que os papeis disponiveis permitem, ou `template_forcado` se o usuario
    escolheu manualmente na tela - Grupo F) e monta o prompt final em
    codigo puro (funcoes `montar_prompt_*`, testaveis e auditaveis).

    Funciona SEM `api_key` (todo passo que chamaria API cai em fallback
    deterministico) - e' a entrega que sempre funciona, mesmo com nenhuma
    chave configurada.

    GRUPO B (correcao desta sessao): `headline` e' a UNICA excecao a essa
    tolerancia - sem ele nao ha' fallback silencioso pra' subject_name/
    emphasis_word (a cascata antiga que causava esse fallback foi removida
    de `_linha_pequena_e_grande`). Headline ausente/vazio faz esta funcao
    devolver `{"sucesso": False, "erro": "headline_ausente"}` sem escrever
    briefing.json - o chamador (`_aplicar_briefing_grupo_c`,
    scripts/7_thumbnail.py) ja' trata `sucesso: False` como "nao concluiu,
    segue sem briefing" (CLAUDE.md secao 18.4), e a rota dedicada
    `/thumbnail/gerar_briefing` repassa o erro pra' tela em vez de fingir
    sucesso com um briefing incompleto.

    Persiste thumbnail/briefing.json (auditoria completa: template
    escolhido + motivo, atributos extraidos por foto, decisao de censura,
    texto final) e devolve o mesmo conteudo essencial em
    `{"sucesso": True, "briefing_completo": str, "template_escolhido": str,
    "auditoria": dict}` quando o headline existe. Nunca levanta excecao."""
    pasta_thumbnail = pasta_projeto / "thumbnail"
    metadados = _ler_json_dict(pasta_thumbnail / "metadados.json")
    thumbnail = metadados.get("thumbnail") or {}

    headline = (thumbnail.get("headline") or "").strip()
    if not headline:
        logger.info("gerar_briefing_completo: headline ausente/vazio - briefing precisa do headline do Headline Engine.")
        return {"sucesso": False, "erro": "headline_ausente"}

    sujeitos = _ler_json_dict(pasta_thumbnail / "sujeitos" / "sujeitos.json")
    hero_info = sujeitos.get("hero")
    secondary_info = sujeitos.get("secondary")
    # Fingerprint do estado de sujeitos QUE PRODUZIU este briefing - lido
    # do MESMO `sujeitos` usado pra' montar o `caso` abaixo, nunca
    # recalculado de outra leitura do disco (evita corrida entre esta
    # leitura e uma escrita concorrente em sujeitos.json).
    subjects_fingerprint = calcular_fingerprint_sujeitos(sujeitos)

    roteiro_texto = ""
    caminho_roteiro = pasta_projeto / "roteiro_aprovado.md"
    if caminho_roteiro.exists():
        try:
            roteiro_texto = caminho_roteiro.read_text(encoding="utf-8")
        except OSError:
            roteiro_texto = ""

    # Titulo aprovado (Etapa 3/5.5) - usado so' pela selecao de PROTAGONISTA
    # do DUAL_PORTRAIT abaixo (validacao 11 do pedido, caso real Burke
    # Ramsey/JonBenét). Mesmo padrao ja usado por
    # scripts/headline_engine.py:_ler_contexto (CLAUDE.md secao 9 - scripts
    # autocontidos, sem utils compartilhado).
    titulo_aprovado = ""
    caminho_titulo = pasta_projeto / "titulo.txt"
    if caminho_titulo.exists():
        try:
            titulo_aprovado = caminho_titulo.read_text(encoding="utf-8").strip()
        except OSError:
            titulo_aprovado = ""

    cliente_api = _obter_cliente(api_key, cliente)

    atributos_hero = None
    if hero_info and hero_info.get("arquivo"):
        caminho_foto_hero = pasta_thumbnail / "sujeitos" / hero_info["arquivo"]
        atributos_hero = extrair_atributos_foto(
            caminho_foto_hero, hero_info.get("papel", "outro"), api_key, modelo, cliente_api, _custos
        )

    atributos_secondary = None
    if secondary_info and secondary_info.get("arquivo"):
        caminho_foto_secondary = pasta_thumbnail / "sujeitos" / secondary_info["arquivo"]
        atributos_secondary = extrair_atributos_foto(
            caminho_foto_secondary, secondary_info.get("papel", "outro"), api_key, modelo, cliente_api, _custos
        )

    hero_papel = (hero_info or {}).get("papel")
    secondary_papel = (secondary_info or {}).get("papel")

    # Sessao "conceito visual", Grupo D - `conceito_visual` (baseline,
    # extraido pelo Headline Engine ANTES de qualquer sujeito existir - ver
    # scripts/headline_engine.py) chega aqui via thumbnail/metadados.json
    # (persistido por scripts/7_thumbnail.py:_mesclar_headline_em_thumbnail).
    # Lido ANTES de `selecionar_template` (GRUPO H, Parte 2) pra' entrar
    # como contexto adicional na MESMA chamada de selecao - zero chamadas
    # novas de API.
    conceito_visual = thumbnail.get("conceito_visual")

    elegiveis = templates_elegiveis(hero_papel, secondary_papel)
    selecao = selecionar_template(
        roteiro_texto, headline, elegiveis, api_key, modelo, cliente_api, _custos,
        hero_papel=hero_papel, secondary_papel=secondary_papel,
        template_forcado=template_forcado, conceito_visual=conceito_visual,
    )

    # `relacao_com_sujeitos` resolve a parte SUBJECT-DEPENDENT que o motor
    # nao pode decidir sozinho - None quando nao ha' ambiguidade real (0 ou
    # 1 sujeito) ou quando a chamada nao confirmou nada (fallback seguro).
    relacao_com_sujeitos = resolver_relacao_com_sujeitos(
        conceito_visual, hero_papel, secondary_papel, api_key, modelo, cliente_api, _custos
    )

    caso = {
        "hero_papel": hero_papel,
        "hero_atributos": atributos_hero,
        "secondary_papel": secondary_papel,
        "secondary_atributos": atributos_secondary,
        "headline": headline,
        "emphasis_word": thumbnail.get("emphasis_word") or "",
        "secondary_texto": thumbnail.get("secondary") or "",
        "accent": thumbnail.get("accent") or ACCENT_PADRAO,
        "censor": bool(thumbnail.get("censor")),
        "subject_name": thumbnail.get("subject_name") or "",
        "background_prompt": thumbnail.get("background_prompt") or "",
        "conceito_visual": conceito_visual,
        "relacao_com_sujeitos": relacao_com_sujeitos,
    }

    template_escolhido = selecao["template"]

    # Validacao 11 do pedido (caso real Burke Ramsey/JonBenét): DUAL_PORTRAIT
    # com os dois slots preenchidos precisa decidir qual sujeito fica
    # visualmente dominante pelo EIXO EDITORIAL (titulo/headline), nunca so'
    # pelo slot em que a foto foi enviada - ver
    # `selecionar_protagonista_dual_portrait`. Nunca reclassifica papel
    # (`hero_papel`/`secondary_papel` no `caso` continuam intocados).
    protagonista_info = None
    if template_escolhido == "DUAL_PORTRAIT" and hero_papel and secondary_papel:
        protagonista_info = selecionar_protagonista_dual_portrait(
            titulo_aprovado, headline, hero_papel, secondary_papel, api_key, modelo, cliente_api, _custos,
            subject_name=caso.get("subject_name"),
        )
        caso["protagonista"] = protagonista_info["protagonista"]

    montador = _MONTADORES[template_escolhido]
    prompt_final, decisao_composicao = montador(caso)

    auditoria = {
        "template_escolhido": template_escolhido,
        "template_motivo": selecao.get("motivo"),
        "template_fonte": selecao.get("fonte"),
        "template_erro": selecao.get("erro"),
        "templates_elegiveis": list(elegiveis),
        "hero": {"papel": caso["hero_papel"], "atributos": atributos_hero} if hero_info else None,
        "secondary": {"papel": caso["secondary_papel"], "atributos": atributos_secondary} if secondary_info else None,
        "protagonista_dual_portrait": protagonista_info,
        "decisao_composicao": decisao_composicao,
        # Sessao "conceito visual", Grupo D/I - parte SUBJECT-DEPENDENT da
        # auditoria (o conceito baseline em si e' auditado a parte, em
        # thumbnail/headline_engine.json - ver scripts/headline_engine.py).
        "conceito_visual": conceito_visual,
        "relacao_com_sujeitos": relacao_com_sujeitos,
        "briefing_completo": prompt_final,
        "roteiro_hash": hashlib.sha256(roteiro_texto.encode("utf-8")).hexdigest() if roteiro_texto else None,
        "subjects_fingerprint": subjects_fingerprint,
    }

    pasta_thumbnail.mkdir(parents=True, exist_ok=True)
    (pasta_thumbnail / "briefing.json").write_text(json.dumps(auditoria, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "sucesso": True,
        "briefing_completo": prompt_final,
        "template_escolhido": template_escolhido,
        "subjects_fingerprint": subjects_fingerprint,
        "auditoria": auditoria,
    }
