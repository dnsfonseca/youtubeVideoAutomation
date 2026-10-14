"""Tool `youtube_top_titles` (CLAUDE.md secao 5.3) - busca titulos que
estao performando bem no YouTube para um topico, usada pela Etapa 3
(geracao de roteiro) como inspiracao de titulo. So fica disponivel para
o Claude se `YOUTUBE_API_KEY` estiver configurada - ver
scripts/3_gerar_roteiro.py.

Infra transversal (mesmo espirito de scripts/ambiente.py e
scripts/robustez.py, CLAUDE.md secao 9) - nao e' logica de pipeline de
uma etapa especifica, e' compartilhada por qualquer chamada da Etapa 3
que queira usar a tool.
"""

import re
import sys

import requests

ENDPOINT_SEARCH = "https://www.googleapis.com/youtube/v3/search"

TIMEOUT_S = 15

# idioma do roteiro (CLAUDE.md secao 7 - IDIOMA_ROTEIRO) -> codigo
# relevanceLanguage aceito pela YouTube Data API v3 (ISO 639-1).
MAPA_RELEVANCE_LANGUAGE = {
    "pt-BR": "pt",
    "en-US": "en",
    "en-GB": "en",
    "es": "es",
    "de": "de",
}

# Definicao da tool no formato esperado pela Anthropic Messages API
# (`tools=[...]` de scripts/3_gerar_roteiro.py) - centralizada aqui para
# nao duplicar o schema entre o modulo que executa a tool e o modulo que
# a declara para o Claude.
TOOL_DEFINITION = {
    "name": "youtube_top_titles",
    "description": (
        "Busca os titulos de video mais assistidos no YouTube para um "
        "topico/consulta, no idioma do roteiro. Use para se inspirar em "
        "titulos que ressoam com a audiencia atual - nao copie um titulo "
        "encontrado, use como referencia de angulo e tom."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termos de busca (ex: nome do caso, tema central do video).",
            },
            "idioma": {
                "type": "string",
                "description": "Idioma alvo do roteiro (ex: pt-BR, en-US, en-GB, es, de).",
            },
        },
        "required": ["query", "idioma"],
    },
}


_PADROES_SUFIXO_CLICKBAIT = [
    re.compile(r"\s*\|.*$"),
    re.compile(r"\s*-\s*True Crime.*$", re.IGNORECASE),
    re.compile(r"\s*-\s*Documentary.*$", re.IGNORECASE),
    re.compile(r"\s*-\s*Full Documentary.*$", re.IGNORECASE),
]

_PADRAO_ALL_CAPS = re.compile(r"\b[A-Z]{4,}\b")

# Emojis mais comuns em titulo clickbait (faixas Unicode de simbolos/
# pictogramas/emoticons) - nao e' uma lista exaustiva de todo emoji
# possivel, so' o suficiente pra limpar o caso comum sem falso positivo em
# texto normal.
_PADRAO_EMOJI = re.compile(
    "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\U00002600-\U000026FF]"
)


def sanitizar_titulo_fonte(titulo: str) -> str:
    """Remove elementos de clickbait de um titulo de video de terceiro
    antes de ele entrar no contexto que o modelo ve (CLAUDE.md secao 5.3 -
    `youtube_top_titles` e' inspiracao de titulo/angulo pra Etapa 3, nunca
    deve "contaminar" o roteiro/titulos gerados com ALL CAPS, emoji, ou
    sufixo de canal). Nunca levanta excecao - titulo vazio/None vira string
    vazia.

    - Remove sufixos comuns de canal ("| True Crime Documentary" etc)
    - Converte palavras em ALL CAPS (4+ letras) para capitalizado,
      preservando siglas curtas (CIA, FBI, DNA - 3 letras ou menos)
    - Remove emojis
    - Normaliza espacos
    """
    if not titulo:
        return ""

    for padrao in _PADROES_SUFIXO_CLICKBAIT:
        titulo = padrao.sub("", titulo)

    titulo = _PADRAO_ALL_CAPS.sub(lambda m: m.group(0).capitalize(), titulo)
    titulo = _PADRAO_EMOJI.sub("", titulo)

    titulo = re.sub(r"\s+", " ", titulo).strip()
    return titulo


def buscar_titulos_top(query: str, idioma: str, api_key: str) -> list:
    """Busca os titulos mais assistidos no YouTube para `query`, filtrados
    por `relevanceLanguage` conforme `idioma` (CLAUDE.md secao 5.3).

    Nunca levanta excecao - qualquer falha de rede/API vira lista vazia
    (a Etapa 3 nao pode ser derrubada por essa tool opcional, CLAUDE.md
    secao 5.3: "Tratamento de erro: retorna lista vazia + log se API
    falhar"). Um aviso e' impresso em stderr para diagnostico.

    Retorna lista de dicts: [{"titulo", "canal", "views", "url"}, ...].
    """
    if not query or not api_key:
        return []

    parametros = {
        "key": api_key,
        "q": query,
        "type": "video",
        "order": "viewCount",
        "maxResults": 10,
        "part": "snippet",
        "relevanceLanguage": MAPA_RELEVANCE_LANGUAGE.get(idioma, "en"),
    }

    try:
        resposta = requests.get(ENDPOINT_SEARCH, params=parametros, timeout=TIMEOUT_S)
        resposta.raise_for_status()
        dados = resposta.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"AVISO: youtube_top_titles falhou para query={query!r}: {exc}", file=sys.stderr)
        return []

    resultados = []
    for item in dados.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if not video_id:
            continue
        resultados.append(
            {
                "titulo": sanitizar_titulo_fonte(snippet.get("title")),
                "canal": snippet.get("channelTitle"),
                # search.list nao devolve contagem de views (precisaria de
                # uma chamada extra a videos.list) - deixado None por
                # enquanto, "order=viewCount" ja garante os mais vistos
                # primeiro sem precisar do numero exato.
                "views": None,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )
    return resultados
