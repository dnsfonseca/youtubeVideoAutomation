"""Testes de scripts/tools/youtube.py - tool `youtube_top_titles`
(CLAUDE.md secao 5.3). Nunca chama a YouTube Data API v3 real - toda
chamada de rede e' mockada via monkeypatch em `requests.get`.
"""

import requests

from scripts.tools import youtube


class _RespostaFake:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _payload_com_dois_videos():
    return {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {"title": "O caso que chocou a cidade", "channelTitle": "Canal A"},
            },
            {
                "id": {"videoId": "def456"},
                "snippet": {"title": "A verdade nunca contada", "channelTitle": "Canal B"},
            },
        ]
    }


# ---------------------------------------------------------------------------
# Caminho feliz
# ---------------------------------------------------------------------------


def test_buscar_titulos_top_retorna_lista_de_dicts_no_formato_esperado(monkeypatch):
    monkeypatch.setattr(
        youtube.requests, "get", lambda *a, **k: _RespostaFake(_payload_com_dois_videos())
    )

    resultados = youtube.buscar_titulos_top("caso joao", "pt-BR", "chave-fake")

    assert len(resultados) == 2
    assert resultados[0] == {
        "titulo": "O caso que chocou a cidade",
        "canal": "Canal A",
        "views": None,
        "url": "https://www.youtube.com/watch?v=abc123",
    }


def test_buscar_titulos_top_usa_relevance_language_correto_por_idioma(monkeypatch):
    parametros_capturados = {}

    def _get_fake(url, params=None, timeout=None):
        parametros_capturados.update(params or {})
        return _RespostaFake({"items": []})

    monkeypatch.setattr(youtube.requests, "get", _get_fake)

    youtube.buscar_titulos_top("query", "pt-BR", "chave-fake")
    assert parametros_capturados["relevanceLanguage"] == "pt"

    youtube.buscar_titulos_top("query", "en-GB", "chave-fake")
    assert parametros_capturados["relevanceLanguage"] == "en"

    youtube.buscar_titulos_top("query", "de", "chave-fake")
    assert parametros_capturados["relevanceLanguage"] == "de"


def test_buscar_titulos_top_envia_order_view_count_e_type_video(monkeypatch):
    parametros_capturados = {}

    def _get_fake(url, params=None, timeout=None):
        parametros_capturados.update(params or {})
        return _RespostaFake({"items": []})

    monkeypatch.setattr(youtube.requests, "get", _get_fake)

    youtube.buscar_titulos_top("query", "en-US", "chave-fake")

    assert parametros_capturados["order"] == "viewCount"
    assert parametros_capturados["type"] == "video"
    assert parametros_capturados["q"] == "query"


# ---------------------------------------------------------------------------
# Casos de borda / erro
# ---------------------------------------------------------------------------


def test_buscar_titulos_top_sem_query_retorna_lista_vazia_sem_chamar_rede(monkeypatch):
    chamou = []
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **k: chamou.append(1))

    resultado = youtube.buscar_titulos_top("", "pt-BR", "chave-fake")

    assert resultado == []
    assert chamou == []


def test_buscar_titulos_top_sem_api_key_retorna_lista_vazia_sem_chamar_rede(monkeypatch):
    chamou = []
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **k: chamou.append(1))

    resultado = youtube.buscar_titulos_top("query", "pt-BR", "")

    assert resultado == []
    assert chamou == []


def test_buscar_titulos_top_com_erro_http_retorna_lista_vazia_nao_levanta(monkeypatch):
    monkeypatch.setattr(
        youtube.requests, "get", lambda *a, **k: _RespostaFake({}, status_code=403)
    )

    resultado = youtube.buscar_titulos_top("query", "pt-BR", "chave-invalida")

    assert resultado == []


def test_buscar_titulos_top_com_falha_de_rede_retorna_lista_vazia_nao_levanta(monkeypatch):
    def _get_que_falha(*a, **k):
        raise requests.ConnectionError("sem rede")

    monkeypatch.setattr(youtube.requests, "get", _get_que_falha)

    resultado = youtube.buscar_titulos_top("query", "pt-BR", "chave-fake")

    assert resultado == []


def test_buscar_titulos_top_com_json_invalido_retorna_lista_vazia_nao_levanta(monkeypatch):
    class _RespostaJsonQuebrado(_RespostaFake):
        def json(self):
            raise ValueError("json invalido")

    monkeypatch.setattr(
        youtube.requests, "get", lambda *a, **k: _RespostaJsonQuebrado({})
    )

    resultado = youtube.buscar_titulos_top("query", "pt-BR", "chave-fake")

    assert resultado == []


def test_buscar_titulos_top_com_items_vazio_retorna_lista_vazia(monkeypatch):
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **k: _RespostaFake({"items": []}))

    resultado = youtube.buscar_titulos_top("query", "pt-BR", "chave-fake")

    assert resultado == []


def test_buscar_titulos_top_item_sem_video_id_e_ignorado(monkeypatch):
    payload = {
        "items": [
            {"id": {}, "snippet": {"title": "Sem id", "channelTitle": "Canal X"}},
            {
                "id": {"videoId": "valido123"},
                "snippet": {"title": "Com id", "channelTitle": "Canal Y"},
            },
        ]
    }
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **k: _RespostaFake(payload))

    resultado = youtube.buscar_titulos_top("query", "pt-BR", "chave-fake")

    assert len(resultado) == 1
    assert resultado[0]["titulo"] == "Com id"


def test_buscar_titulos_top_idioma_desconhecido_cai_para_ingles(monkeypatch):
    parametros_capturados = {}

    def _get_fake(url, params=None, timeout=None):
        parametros_capturados.update(params or {})
        return _RespostaFake({"items": []})

    monkeypatch.setattr(youtube.requests, "get", _get_fake)

    youtube.buscar_titulos_top("query", "fr-FR", "chave-fake")

    assert parametros_capturados["relevanceLanguage"] == "en"


# ---------------------------------------------------------------------------
# Definicao da tool (schema Anthropic)
# ---------------------------------------------------------------------------


def test_tool_definition_tem_nome_e_schema_esperados():
    assert youtube.TOOL_DEFINITION["name"] == "youtube_top_titles"
    propriedades = youtube.TOOL_DEFINITION["input_schema"]["properties"]
    assert "query" in propriedades
    assert "idioma" in propriedades
    assert youtube.TOOL_DEFINITION["input_schema"]["required"] == ["query", "idioma"]


# ---------------------------------------------------------------------------
# sanitizar_titulo_fonte (Sessao de correcoes UX - qualidade de roteiro,
# D.3): titulos de video concorrentes retornados por youtube_top_titles sao
# a inspiracao de angulo/titulo pra Etapa 3 - clickbait cru (ALL CAPS,
# emoji, sufixo de canal) nao pode vazar pro contexto do modelo.
# ---------------------------------------------------------------------------


def test_sanitizar_titulo_remove_all_caps():
    resultado = youtube.sanitizar_titulo_fonte(
        "After 30 Years, The TRUTH About Ramsey's Killer Finally Comes Out"
    )
    assert "TRUTH" not in resultado
    assert "Truth" in resultado


def test_sanitizar_titulo_preserva_siglas_curtas():
    resultado = youtube.sanitizar_titulo_fonte("The CIA, the FBI, and the DNA that broke the case")
    assert "CIA" in resultado
    assert "FBI" in resultado
    assert "DNA" in resultado


def test_sanitizar_titulo_remove_sufixo_documentary():
    resultado = youtube.sanitizar_titulo_fonte("The Sullivan Case - True Crime Documentary")
    assert resultado == "The Sullivan Case"


def test_sanitizar_titulo_remove_pipe_e_apos():
    resultado = youtube.sanitizar_titulo_fonte(
        "After 30 Years, The Truth Finally Comes Out | True Crime Documentary"
    )
    assert resultado == "After 30 Years, The Truth Finally Comes Out"


def test_sanitizar_titulo_remove_emojis():
    resultado = youtube.sanitizar_titulo_fonte("The case that shocked everyone \U0001F631\U0001F6A8")
    assert "\U0001F631" not in resultado
    assert "\U0001F6A8" not in resultado
    assert resultado == "The case that shocked everyone"


def test_sanitizar_titulo_vazio_ou_none_retorna_string_vazia():
    assert youtube.sanitizar_titulo_fonte("") == ""
    assert youtube.sanitizar_titulo_fonte(None) == ""


def test_sanitizar_titulo_exemplo_completo_da_documentacao():
    """Exemplo literal usado na especificacao desta feature."""
    original = (
        "After 30 Years, The TRUTH About JonBenét Ramsey's Killer Finally "
        "Comes Out | True Crime Documentary"
    )
    esperado = (
        "After 30 Years, The Truth About JonBenét Ramsey's Killer Finally "
        "Comes Out"
    )
    assert youtube.sanitizar_titulo_fonte(original) == esperado


def test_buscar_titulos_top_sanitiza_titulos_antes_de_retornar(monkeypatch):
    """Integracao: o titulo que chega no resultado de buscar_titulos_top (o
    que a Etapa 3 ve como tool_result) ja sai sanitizado, nunca o titulo
    cru da YouTube Data API."""
    payload = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "The SHOCKING Truth | True Crime Documentary",
                    "channelTitle": "Canal A",
                },
            }
        ]
    }
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **k: _RespostaFake(payload))

    resultados = youtube.buscar_titulos_top("caso joao", "en-US", "chave-fake")

    assert resultados[0]["titulo"] == "The Shocking Truth"
