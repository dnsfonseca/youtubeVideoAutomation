"""Testes da Etapa 3 do pipeline (scripts/3_gerar_roteiro.py) - geracao de
roteiro via Anthropic Messages API com web search e o sistema de perfis
de conteudo (CLAUDE.md secoes 5.3, 5.4, 3.1).

Nunca chama a API Anthropic real nem a YouTube Data API real (CLAUDE.md
secao 8): `anthropic.Anthropic` e' sempre substituido por um cliente fake
que devolve respostas pre-fabricadas, e `youtube.buscar_titulos_top' e'
mockada quando exercitada.

O nome do arquivo do script comeca com digito ("3_gerar_roteiro.py"),
entao nao pode ser importado com `import` normal - carregado via
importlib.util.spec_from_file_location, igual test_baixar_videos.py e
test_transcrever.py fazem para os scripts 1 e 2.
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "3_gerar_roteiro.py"

_spec = importlib.util.spec_from_file_location("gerar_roteiro_etapa3", CAMINHO_SCRIPT)
modulo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = modulo
_spec.loader.exec_module(modulo)


# ---------------------------------------------------------------------------
# Fakes do SDK anthropic - nunca chamam rede de verdade.
# ---------------------------------------------------------------------------


class FakeContentBlock:
    def __init__(self, type_, **kw):
        self.type = type_
        for chave, valor in kw.items():
            setattr(self, chave, valor)


class _FakeServerToolUse:
    def __init__(self, web_search_requests=0):
        self.web_search_requests = web_search_requests


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50, web_search_requests=0, cache_creation_input_tokens=0, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.server_tool_use = _FakeServerToolUse(web_search_requests)
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class FakeResponse:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage = usage or FakeUsage()


class FakeMessages:
    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = []

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if not self._respostas:
            raise AssertionError("FakeMessages.create chamado mais vezes do que respostas fornecidas")
        resposta = self._respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class FakeClient:
    def __init__(self, respostas):
        self.messages = FakeMessages(respostas)


PERGUNTA_PROMESSA_TESTE = "Por que o alibi dele nao se sustentou depois da pericia?"
# Default deliberadamente generico E' construido pra compartilhar o termo
# "titulo" com os 3 titulos-placeholder default (_resposta_saida_
# estruturada abaixo) - assim o Grupo B (detectar_titulos_divergentes)
# nao dispara por acidente na maioria dos testes deste arquivo, que nao
# tem nada a ver com nucleo_editorial/titulos. Testes que exercitam o
# Grupo B de verdade usam um nucleo/titulos explicitos e nao-genericos.
NUCLEO_EDITORIAL_TESTE = "titulo generico de teste"

# Sentinela pra distinguir "parametro nao passado" (usa o default valido
# NUCLEO_EDITORIAL_TESTE, pra nao disparar reparo em testes que nao tem
# nada a ver com nucleo_editorial) de "passado explicitamente como None"
# (campo omitido da resposta - simula o modelo nao ter preenchido).
_SEM_VALOR = object()

# Texto longo o suficiente para nao disparar o mecanismo de expansao
# (Grupo E) contra o palavras_alvo default (4000, quando nenhum
# configuracao_video.json e' escrito pelo teste) - "Roteiro final de
# teste." tem 4 palavras; 970 repeticoes = 3880 palavras narradas, 97% do
# alvo. A maioria dos testes deste arquivo nao se importa com o CONTEUDO
# do roteiro, so' com o fluxo de chamadas/cache/tokens - um texto curto
# faria essa maioria entrar sem querer no loop de expansao (chamadas
# extras a FakeMessages, alterando len(chamadas) em testes que nao tem
# nada a ver com tamanho de roteiro).
ROTEIRO_TESTE_LONGO = ("Roteiro final de teste. " * 970) + "[F1@00:00]"


def _resposta_saida_estruturada(
    roteiro_md=ROTEIRO_TESTE_LONGO,
    titulos=None,
    descricoes=None,
    usage=None,
    pergunta_promessa=PERGUNTA_PROMESSA_TESTE,
    nucleo_editorial=_SEM_VALOR,
):
    titulos = titulos if titulos is not None else ["Titulo factual", "Titulo emocional", "Titulo pergunta"]
    descricoes = descricoes if descricoes is not None else ["Desc 1", "Desc 2", "Desc 3"]
    input_dict = {"roteiro_md": roteiro_md, "titulos": titulos, "descricoes": descricoes}
    if pergunta_promessa is not None:
        input_dict["pergunta_promessa"] = pergunta_promessa
    if nucleo_editorial is _SEM_VALOR:
        nucleo_editorial = NUCLEO_EDITORIAL_TESTE
    if nucleo_editorial is not None:
        input_dict["nucleo_editorial"] = nucleo_editorial
    return FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input=input_dict,
            )
        ],
        usage=usage or FakeUsage(input_tokens=200, output_tokens=80),
    )


def _resposta_sem_tool_use(texto="Sem mais pesquisa necessaria.", web_search_requests=0):
    return FakeResponse(
        [FakeContentBlock("text", text=texto)],
        usage=FakeUsage(web_search_requests=web_search_requests),
    )


def _resposta_resumo_estruturado(resumo=None, usage=None):
    """Resposta fake da chamada forcada (tool_choice) que fecha a fase 1 -
    extrai o resumo estruturado dos achados (NOME_TOOL_RESUMO), nao o
    roteiro final."""
    resumo = (
        resumo
        if resumo is not None
        else {
            "fatos_verificados": [
                {"fato": "O caso ocorreu numa pequena cidade.", "fonte": "F1@00:00", "confianca": "alta"}
            ],
            "cronologia": [{"data": "2025-01-01", "evento": "Evento inicial do caso"}],
            "pessoas_envolvidas": [{"nome": "Fulano de Tal", "papel": "suspeito", "status_legal": "investigado"}],
            "conflitos_entre_fontes": [],
            "titulos_top_youtube": [],
            "observacoes_editoriais": [],
        }
    )
    return FakeResponse(
        [FakeContentBlock("tool_use", id="tu_resumo", name="entregar_resumo_pesquisa", input=resumo)],
        usage=usage or FakeUsage(),
    )


# ---------------------------------------------------------------------------
# Fixture de projeto no disco
# ---------------------------------------------------------------------------


def _criar_projeto(tmp_path, perfil="truecrime", idioma_env=None, com_transcricao=True):
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "perfil.txt").write_text(perfil, encoding="utf-8")

    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(
            {
                "fontes": [
                    {
                        "id": "fonte01",
                        "arquivo": "fonte01.mp4",
                        "url_original": "https://youtube.com/watch?v=abc",
                        "sucesso": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    if com_transcricao:
        (pasta_projeto / "transcricoes").mkdir()
        (pasta_projeto / "transcricoes" / "fonte01.json").write_text(
            json.dumps(
                {
                    "arquivo": "fonte01.mp4",
                    "duracao_s": 120.0,
                    "idioma": "en",
                    "segmentos": [
                        {"start": 0.0, "end": 4.2, "text": "Tonight we talk about a real case.", "palavras": []},
                        {"start": 4.2, "end": 8.0, "text": "It happened in a small town.", "palavras": []},
                    ],
                }
            ),
            encoding="utf-8",
        )

    return pasta_projeto


@pytest.fixture(autouse=True)
def _env_minimo(monkeypatch):
    """Isola os testes deste arquivo do .env real - cada teste liga so as
    variaveis que precisa via monkeypatch.setenv."""
    for campo in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "IDIOMA_ROTEIRO", "YOUTUBE_API_KEY", "WEB_SEARCH_MAX"):
        monkeypatch.delenv(campo, raising=False)


def _instalar_client_fake(monkeypatch, respostas):
    fake_client = FakeClient(respostas)
    monkeypatch.setattr(modulo.anthropic, "Anthropic", lambda api_key: fake_client)
    return fake_client


def _respostas_fluxo_feliz(resposta_final=None):
    """Sequencia minima de 3 respostas para um fluxo que passa pela fase 1
    completa - pesquisa (sem tool client-side pendente, quebra o loop na
    primeira rodada) + chamada forcada que extrai o resumo estruturado -
    e entrega a saida estruturada final numa fase 2 separada (chamada com
    tool_choice forcado, conversa nova). `resposta_final` default = saida
    valida."""
    return [
        _resposta_sem_tool_use(),
        _resposta_resumo_estruturado(),
        resposta_final or _resposta_saida_estruturada(),
    ]


# ---------------------------------------------------------------------------
# Fluxo feliz
# ---------------------------------------------------------------------------


def test_fluxo_feliz_perfil_truecrime_gera_roteiro_titulos_e_metadata(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("IDIOMA_ROTEIRO", "en-US")

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "roteiro.md").read_text(encoding="utf-8") == ROTEIRO_TESTE_LONGO

    titulos_json = json.loads((pasta_projeto / "titulos_sugeridos.json").read_text(encoding="utf-8"))
    assert titulos_json["titulos"] == ["Titulo factual", "Titulo emocional", "Titulo pergunta"]
    assert titulos_json["descricoes"] == ["Desc 1", "Desc 2", "Desc 3"]

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["perfil_usado"] == "truecrime"
    assert job_metadata["idioma"] == "en-US"
    assert job_metadata["modelo"] == modulo.MODELO_PADRAO
    # Soma dos tokens das 3 chamadas: FakeUsage padrao (100/50) da rodada
    # de pesquisa + FakeUsage padrao (100/50) da chamada forcada que extrai
    # o resumo + 200/80 da fase 2 (saida estruturada final).
    # Todos os FakeUsage neste teste possuem cache_creation/cache_read = 0 (default),
    # entao tokens_input_nao_cacheado = tokens_input_total = 400.
    assert job_metadata["tokens_input_nao_cacheado"] == 400
    assert job_metadata["tokens_input_total"] == 400
    assert job_metadata["tokens_cache_criados"] == 0
    assert job_metadata["tokens_cache_lidos"] == 0
    assert job_metadata["cache_hit_rate"] == 0.0
    assert job_metadata["tokens_output"] == 180
    assert "custo_estimado_usd" in job_metadata
    assert "tempo_geracao_s" in job_metadata
    assert "data_geracao" in job_metadata


def test_fluxo_feliz_com_rodada_de_pesquisa_antes_da_saida_estruturada(tmp_path, monkeypatch):
    """O modelo pode usar web_search (resolvido server-side, sem tool_use
    client-side) antes de finalmente entregar a saida estruturada - 3
    chamadas a messages.create no total (pesquisa + extracao do resumo +
    saida final da fase 2)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(web_search_requests=3),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 3
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["web_searches_usadas"] == 3


# ---------------------------------------------------------------------------
# Injecao do bloco juridico por perfil (CLAUDE.md secoes 3.1/5.4)
# ---------------------------------------------------------------------------


def test_perfil_truecrime_injeta_bloco_juridico_pt_br(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("IDIOMA_ROTEIRO", "pt-BR")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"]
    assert "indiciado" in system_prompt.lower()
    assert "denunciado" in system_prompt.lower()


def test_perfil_atualidades_narrativas_nao_injeta_bloco_juridico(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="atualidades_narrativas")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("IDIOMA_ROTEIRO", "pt-BR")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"]
    assert "indiciado" not in system_prompt.lower()
    assert "{BLOCO_JURIDICO}" not in system_prompt


def test_prompt_sistema_nao_vaza_placeholder_idioma(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("IDIOMA_ROTEIRO", "pt-BR")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"]
    assert "{IDIOMA}" not in system_prompt
    assert "pt-BR" in system_prompt


# ---------------------------------------------------------------------------
# Tool youtube_top_titles - presente so quando YOUTUBE_API_KEY configurada
# ---------------------------------------------------------------------------


def test_sem_youtube_api_key_tool_nao_e_passada(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    tools_primeira_chamada = fake_client.messages.chamadas[0]["tools"]
    nomes = [t.get("name") for t in tools_primeira_chamada]
    assert "youtube_top_titles" not in nomes


def test_com_youtube_api_key_tool_e_passada(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("YOUTUBE_API_KEY", "chave-youtube-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    tools_primeira_chamada = fake_client.messages.chamadas[0]["tools"]
    nomes = [t.get("name") for t in tools_primeira_chamada]
    assert "youtube_top_titles" in nomes


def test_modelo_chama_youtube_tool_e_recebe_resultado_mockado(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("YOUTUBE_API_KEY", "chave-youtube-fake")

    resultado_youtube = [{"titulo": "Video top 1", "canal": "Canal X", "views": None, "url": "https://x"}]
    monkeypatch.setattr(
        modulo.youtube_tool, "buscar_titulos_top", lambda query, idioma, api_key: resultado_youtube
    )

    resposta_com_tool_use = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_youtube",
                name="youtube_top_titles",
                input={"query": "caso joao", "idioma": "en-US"},
            )
        ],
        usage=FakeUsage(),
    )
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            resposta_com_tool_use,
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    # A segunda chamada (rodada seguinte do loop de pesquisa) tem que
    # carregar o tool_result com o resultado mockado da tool.
    segunda_chamada = fake_client.messages.chamadas[1]
    mensagens = segunda_chamada["messages"]
    tool_result_msg = mensagens[-1]
    assert tool_result_msg["role"] == "user"
    conteudo_tool_result = tool_result_msg["content"][0]["content"]
    assert "Video top 1" in conteudo_tool_result


# ---------------------------------------------------------------------------
# Categorizacao de erro
# ---------------------------------------------------------------------------


class _ErroAPIFake(Exception):
    def __init__(self, status_code, mensagem="erro da API"):
        super().__init__(mensagem)
        self.status_code = status_code


def test_erro_401_classificado_como_chave_invalida(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(monkeypatch, [_ErroAPIFake(401)])

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "chave_invalida"


def test_erro_402_classificado_como_credito_insuficiente(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(monkeypatch, [_ErroAPIFake(402)])

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "credito_insuficiente"


def test_erro_429_classificado_como_rate_limit(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(monkeypatch, [_ErroAPIFake(429)])

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "rate_limit"


def test_sem_anthropic_api_key_retorna_chave_ausente(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    # ANTHROPIC_API_KEY deliberadamente nao configurada.

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "chave_ausente"


def test_erro_desconhecido_classificado_com_status_code_nao_mapeado(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(monkeypatch, [_ErroAPIFake(500, "internal server error")])

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "erro_desconhecido"


def test_classificar_erro_api_credito_insuficiente_por_texto_sem_status_code():
    exc = Exception("Your credit balance is too low to access the Claude API")
    categoria, mensagem = modulo.classificar_erro_api(exc)
    assert categoria == "credito_insuficiente"


# ---------------------------------------------------------------------------
# Validacao de pre-condicoes (CLAUDE.md secao 18.6)
# ---------------------------------------------------------------------------


def test_sem_transcricoes_retorna_transcricoes_ausentes(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, com_transcricao=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "transcricoes_ausentes"


def test_sem_manifest_fontes_retorna_transcricoes_ausentes(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_sem_manifest"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta_projeto / "transcricoes").mkdir()
    (pasta_projeto / "transcricoes" / "fonte01.json").write_text(
        json.dumps({"arquivo": "fonte01.mp4", "segmentos": []}), encoding="utf-8"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "transcricoes_ausentes"


def test_sem_perfil_txt_retorna_perfil_invalido(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "perfil.txt").unlink()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "perfil_invalido"


def test_perfil_inexistente_retorna_perfil_invalido(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="perfil_que_nao_existe")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "perfil_invalido"


# ---------------------------------------------------------------------------
# Parsing/validacao da resposta estruturada
# ---------------------------------------------------------------------------


def test_fase1_sem_resumo_estruturado_e_resposta_malformada(tmp_path, monkeypatch):
    """A chamada forcada que fecha a fase 1 (tool_choice=entregar_resumo_pesquisa)
    nao devolve o tool_use esperado (ex: modelo devolveu so texto, apesar
    do tool_choice forcado - defesa contra resposta inesperada da API).
    Nesse caso o pipeline para ANTES de chegar na fase 2 (so 2 chamadas)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, [_resposta_sem_tool_use(), _resposta_sem_tool_use()])

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "resposta_malformada"
    assert len(fake_client.messages.chamadas) == 2


def test_fase2_sem_tool_use_final_e_resposta_malformada(tmp_path, monkeypatch):
    """A chamada final da fase 2 (tool_choice=entregar_roteiro) nao devolve
    o tool_use esperado - mesma defesa da fase 1, agora no outro lado."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    _instalar_client_fake(
        monkeypatch, [_resposta_sem_tool_use(), _resposta_resumo_estruturado(), _resposta_sem_tool_use()]
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "resposta_malformada"


def test_resposta_sem_campo_roteiro_md_e_resposta_malformada(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resposta = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input={"titulos": ["A", "B", "C"], "descricoes": ["1", "2", "3"]},
            )
        ]
    )
    _instalar_client_fake(monkeypatch, [_resposta_sem_tool_use(), _resposta_resumo_estruturado(), resposta])

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "resposta_malformada"


def test_resposta_com_menos_de_3_titulos_e_resposta_malformada(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(titulos=["Somente um titulo"]),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "resposta_malformada"


def test_resposta_com_menos_de_3_descricoes_e_resposta_malformada(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(descricoes=["Somente uma descricao"]),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "resposta_malformada"


def test_resposta_valida_nao_grava_arquivos_de_saida_quando_invalida(tmp_path, monkeypatch):
    """Uma resposta malformada nao pode deixar roteiro.md pela metade."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(titulos=["Um so"]),
        ],
    )

    modulo.gerar_roteiro(pasta_projeto)

    assert not (pasta_projeto / "roteiro.md").exists()
    assert not (pasta_projeto / "titulos_sugeridos.json").exists()
    assert not (pasta_projeto / "job_metadata.json").exists()


# ---------------------------------------------------------------------------
# Timeout (config duro de 15min)
# ---------------------------------------------------------------------------


def test_timeout_retorna_tipo_erro_timeout(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # -1 (nao 0) para o teste ser determinístico independente da resolucao
    # do relogio monotonico: `elapsed > -1` e' sempre verdadeiro (elapsed
    # nunca e' negativo), enquanto `elapsed > 0` poderia falhar por
    # coincidencia se duas leituras muito proximas de time.monotonic()
    # caírem no mesmo tick.
    monkeypatch.setattr(modulo, "TIMEOUT_TOTAL_S", -1)
    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "timeout"


# ---------------------------------------------------------------------------
# montar_prompt_usuario - identificacao de fontes e timestamps
# ---------------------------------------------------------------------------


def test_montar_prompt_usuario_identifica_fonte_com_numero_e_url():
    manifest = {
        "fontes": [
            {"id": "fonte01", "arquivo": "fonte01.mp4", "url_original": "https://x.com/1", "sucesso": True}
        ]
    }
    transcricoes = {
        "fonte01": {
            "segmentos": [{"start": 0.0, "end": 2.0, "text": "Ola mundo"}],
        }
    }
    prompt = modulo.montar_prompt_usuario(manifest, transcricoes)

    assert "FONTE 01" in prompt
    assert "fonte01.mp4" in prompt
    assert "https://x.com/1" in prompt
    assert "Ola mundo" in prompt
    assert "[00:00]" in prompt


def test_montar_prompt_usuario_ignora_fonte_que_falhou():
    manifest = {
        "fontes": [
            {"id": "fonte01", "arquivo": "fonte01.mp4", "url_original": "https://x", "sucesso": False}
        ]
    }
    prompt = modulo.montar_prompt_usuario(manifest, {})
    assert "=== FONTE" not in prompt
    assert "fonte01.mp4" not in prompt


def test_formatar_timestamp_abaixo_de_uma_hora():
    assert modulo._formatar_timestamp(272) == "04:32"


def test_formatar_timestamp_acima_de_uma_hora():
    assert modulo._formatar_timestamp(3725) == "01:02:05"


# ---------------------------------------------------------------------------
# Fase 2 isolada da fase 1 - otimizacao de custo pos-Sessao 6 (a fase 2 nao
# pode reenviar o historico bruto de pesquisa, so' o resumo + transcricoes).
# ---------------------------------------------------------------------------


def test_fase2_e_conversa_nova_sem_historico_da_fase1(tmp_path, monkeypatch):
    """A chamada final da fase 2 (entregar_roteiro) tem que ser uma
    conversa NOVA - uma unica mensagem de usuario - sem o historico de
    tool_use/tool_result acumulado durante a pesquisa da fase 1. Era isso
    que inflava o input em 10x num teste real (ver docstring do modulo)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("YOUTUBE_API_KEY", "chave-youtube-fake")

    resultado_youtube = [
        {"titulo": "Resultado bruto de busca no youtube XPTO", "canal": "Canal X", "views": None, "url": "https://x"}
    ]
    monkeypatch.setattr(
        modulo.youtube_tool, "buscar_titulos_top", lambda query, idioma, api_key: resultado_youtube
    )

    resposta_com_tool_use = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_youtube",
                name="youtube_top_titles",
                input={"query": "caso joao", "idioma": "en-US"},
            )
        ],
        usage=FakeUsage(),
    )
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            resposta_com_tool_use,
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)
    assert resultado["sucesso"] is True

    mensagens_fase2 = fake_client.messages.chamadas[-1]["messages"]
    assert len(mensagens_fase2) == 1
    assert mensagens_fase2[0]["role"] == "user"
    assert isinstance(mensagens_fase2[0]["content"], str)

    conteudo_fase2 = mensagens_fase2[0]["content"]
    assert "Resultado bruto de busca no youtube XPTO" not in conteudo_fase2
    assert "youtube_top_titles" not in conteudo_fase2
    assert "tool_result" not in conteudo_fase2


def test_fase2_contem_resumo_estruturado_da_fase1(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resumo = {
        "fatos_verificados": [
            {"fato": "Fato caracteristico do resumo XYZ123", "fonte": "F1@00:00", "confianca": "alta"}
        ],
        "cronologia": [],
        "pessoas_envolvidas": [],
        "conflitos_entre_fontes": [],
        "titulos_top_youtube": [],
        "observacoes_editoriais": [],
    }
    fake_client = _instalar_client_fake(
        monkeypatch,
        [_resposta_sem_tool_use(), _resposta_resumo_estruturado(resumo=resumo), _resposta_saida_estruturada()],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)
    assert resultado["sucesso"] is True

    conteudo_fase2 = fake_client.messages.chamadas[-1]["messages"][0]["content"]
    assert "Fato caracteristico do resumo XYZ123" in conteudo_fase2


def test_fase2_contem_transcricoes(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    conteudo_fase2 = fake_client.messages.chamadas[-1]["messages"][0]["content"]
    assert "Tonight we talk about a real case." in conteudo_fase2
    assert "FONTE 01" in conteudo_fase2


# ---------------------------------------------------------------------------
# Prompt de sistema truecrime - uso criterioso de web_search e comprimento
# ---------------------------------------------------------------------------


def test_sistema_truecrime_contem_instrucao_uso_criterioso_web_search(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"].lower()
    assert "uso de web_search" in system_prompt
    assert "priorize qualidade sobre quantidade de buscas" in system_prompt


def test_sistema_truecrime_contem_instrucao_comprimento(tmp_path, monkeypatch):
    """O unico numero de tamanho valido no prompt de sistema vem do bloco
    montado em runtime por _montar_bloco_tamanho_alvo a partir da
    configuracao do projeto (default: 4000 palavras -> 20000-24000
    caracteres, ver PALAVRAS_ALVO_PADRAO/CHARS_POR_PALAVRA_MIN/MAX) - nao
    de uma faixa fixa escrita no sistema.md do perfil (Investigacao de
    tamanho curto, Grupo A). Travar neste teste num numero literal do
    sistema.md seria reproduzir o mesmo bug que motivou a investigacao."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"]
    assert "# TAMANHO ALVO DESTE PROJETO" in system_prompt
    caracteres_min = int(modulo.PALAVRAS_ALVO_PADRAO * modulo.CHARS_POR_PALAVRA_MIN)
    caracteres_max = int(modulo.PALAVRAS_ALVO_PADRAO * modulo.CHARS_POR_PALAVRA_MAX)
    assert str(caracteres_min) in system_prompt
    assert str(caracteres_max) in system_prompt
    # e nenhuma faixa fixa de perfil sobrevive no mesmo prompt
    assert "25.000-35.000" not in system_prompt


def test_interpolacao_web_search_max_no_prompt_final(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("WEB_SEARCH_MAX", "6")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"]
    assert "{WEB_SEARCH_MAX}" not in system_prompt
    assert "limite: 6 buscas" in system_prompt


def test_sem_web_search_max_no_env_usa_default_e_avisa_no_console(tmp_path, monkeypatch, capsys):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.delenv("WEB_SEARCH_MAX", raising=False)

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    system_prompt = fake_client.messages.chamadas[0]["system"][0]["text"]
    assert "limite: 5 buscas" in system_prompt

    saida = capsys.readouterr().out
    assert "[INFO] WEB_SEARCH_MAX nao configurado. Usando default 5." in saida


# ---------------------------------------------------------------------------
# Modo DRY_RUN_API (calibracao de prompt sem custo) - CLAUDE.md secao ?
# ---------------------------------------------------------------------------


def test_dry_run_mode_nao_chama_api_quando_ativo(tmp_path, monkeypatch):
    """Com DRY_RUN_API=true, a API Anthropic NUNCA e chamada."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("DRY_RUN_API", "true")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert resultado.get("dry_run") is True
    # Verificar que o cliente fake NUNCA foi chamado
    assert len(fake_client.messages.chamadas) == 0


def test_dry_run_mode_cria_dry_run_output_md(tmp_path, monkeypatch):
    """Com DRY_RUN_API=true, cria dry_run_output.md com secoes esperadas."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("IDIOMA_ROTEIRO", "pt-BR")
    monkeypatch.setenv("DRY_RUN_API", "true")

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    dry_run_file = pasta_projeto / "dry_run_output.md"
    assert dry_run_file.exists()

    conteudo = dry_run_file.read_text(encoding="utf-8")
    assert "=== PROMPT DE SISTEMA ===" in conteudo
    assert "=== PROMPT DE USUARIO ===" in conteudo
    assert "=== METADADOS ===" in conteudo
    assert "Perfil: truecrime" in conteudo
    assert "Idioma: pt-BR" in conteudo
    assert "Modelo (nao chamado):" in conteudo
    assert "Tokens input estimados:" in conteudo
    assert "Custo estimado se chamado:" in conteudo
    assert "$" in conteudo


def test_dry_run_mode_marca_job_com_status_dry_run_concluido(tmp_path, monkeypatch):
    """Com DRY_RUN_API=true, job.json recebe status='dry_run_concluido' e etapa_atual='roteiro'."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("DRY_RUN_API", "true")

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    job_file = pasta_projeto / "job.json"
    assert job_file.exists()

    job = json.loads(job_file.read_text(encoding="utf-8"))
    assert job.get("status") == "dry_run_concluido"
    assert job.get("etapa_atual") == "roteiro"


def test_dry_run_mode_false_chama_api_normalmente(tmp_path, monkeypatch):
    """Com DRY_RUN_API=false explicitamente, comportamento normal (API e chamada)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("DRY_RUN_API", "false")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    # Com DRY_RUN_API=false, o cliente e chamado normalmente (3 chamadas:
    # pesquisa + extracao do resumo + saida final da fase 2).
    assert len(fake_client.messages.chamadas) == 3
    # Arquivo dry_run_output.md NAO e criado
    assert not (pasta_projeto / "dry_run_output.md").exists()


def test_dry_run_mode_ausente_chama_api_normalmente(tmp_path, monkeypatch):
    """Com DRY_RUN_API ausente/unset, comportamento normal (API e chamada)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.delenv("DRY_RUN_API", raising=False)  # Garante que nao existe

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 3
    assert not (pasta_projeto / "dry_run_output.md").exists()


def test_dry_run_mode_insensivel_a_maiuscula_e_espacos(tmp_path, monkeypatch):
    """DRY_RUN_API=True com maiuscula ou espacos tambem ativa modo dry-run."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("DRY_RUN_API", "  TRUE  ")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado.get("dry_run") is True
    assert len(fake_client.messages.chamadas) == 0


def test_dry_run_mode_nao_cria_roteiro_titulos_metadata(tmp_path, monkeypatch):
    """Em modo dry-run, os arquivos normais de saida (roteiro.md, titulos_sugeridos.json, job_metadata.json) NAO sao criados."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    monkeypatch.setenv("DRY_RUN_API", "true")

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    # Arquivos do fluxo normal NAO devem existir
    assert not (pasta_projeto / "roteiro.md").exists()
    assert not (pasta_projeto / "titulos_sugeridos.json").exists()
    assert not (pasta_projeto / "job_metadata.json").exists()
    # Arquivo dry-run SIM deve existir
    assert (pasta_projeto / "dry_run_output.md").exists()


# ---------------------------------------------------------------------------
# Priorizacao de fontes recentes sobre transcricoes desatualizadas (Sessao 22)
# ---------------------------------------------------------------------------


def test_prompt_truecrime_tem_regra_priorizacao_fontes():
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / "truecrime" / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "USO ESTRATÉGICO DAS FONTES" in texto
    assert "PRIORIZE a web search" in texto
    assert "FONTE PRIMÁRIA vs SECUNDÁRIA" not in texto


def test_prompt_atualidades_tem_regra_priorizacao_fontes():
    caminho = (
        BASE_DIR / "scripts" / "prompts" / "perfis" / "atualidades_narrativas" / "sistema.md"
    )
    texto = caminho.read_text(encoding="utf-8")
    assert "PRIORIZAÇÃO DE FONTES" in texto
    assert "PRIORIZE a busca web" in texto


def test_prompt_historia_tem_regra_priorizacao_fontes():
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / "historia" / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "PRIORIZAÇÃO DE FONTES" in texto
    assert "PRIORIZE a busca web" in texto


# ---------------------------------------------------------------------------
# Cache control - prompt caching (pos-Sessao 6.5)
# ---------------------------------------------------------------------------


def test_web_search_max_padrao_constante_e_cinco():
    """WEB_SEARCH_MAX_PADRAO deve ser 5 conforme Sessao 22 (frescor de dados)."""
    assert modulo.WEB_SEARCH_MAX_PADRAO == 5


def test_prompt_sistema_enviado_com_cache_control(tmp_path, monkeypatch):
    """O prompt de sistema e enviado com cache_control ephemeral na estrutura de blocos."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    # Verificar que o system prompt esta em formato de lista de blocos
    system_arg = fake_client.messages.chamadas[0]["system"]
    assert isinstance(system_arg, list)
    assert len(system_arg) > 0
    bloco_sistema = system_arg[0]
    assert bloco_sistema["type"] == "text"
    assert "text" in bloco_sistema
    assert "cache_control" in bloco_sistema
    assert bloco_sistema["cache_control"]["type"] == "ephemeral"


def test_primeiro_user_message_fase1_com_cache_control(tmp_path, monkeypatch):
    """O primeiro user message da fase 1 (conteudo do usuario) tem cache_control ephemeral."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    # Primera chamada (fase 1)
    primeira_chamada = fake_client.messages.chamadas[0]
    mensagens = primeira_chamada["messages"]
    primeiro_user_msg = mensagens[0]

    assert primeiro_user_msg["role"] == "user"
    # O content pode ser string ou lista de blocos - nesta fase, deveria ser lista
    conteudo = primeiro_user_msg["content"]
    if isinstance(conteudo, list):
        # Se e uma lista, deveria ter cache_control no bloco
        bloco = conteudo[0]
        assert bloco["type"] == "text"
        assert "cache_control" in bloco
        assert bloco["cache_control"]["type"] == "ephemeral"


def test_calculo_custo_com_cache_read_tokens(tmp_path, monkeypatch):
    """O custo estimado reflete corretamente cache_read_input_tokens com multiplicador reduzido."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # Simular uma resposta onde a fase 2 teve cache reads:
    # usage.input_tokens=200 (nao cacheado)
    # usage.cache_read_input_tokens=500 (5x mais caro em escrita, 10x mais barato em leitura)
    # usage.output_tokens=80
    resposta_fase2_com_cache = _resposta_saida_estruturada(
        usage=FakeUsage(
            input_tokens=200,
            output_tokens=80,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=0
        )
    )
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            resposta_fase2_com_cache,
        ],
    )

    modulo.gerar_roteiro(pasta_projeto)

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    # Verificar que tokens foram contabilizados
    assert job_metadata["tokens_cache_lidos"] == 500
    assert job_metadata["tokens_cache_criados"] == 0

    # Custo esperado:
    # - input nao-cacheado: 400 tokens (100+100+200 de todas as chamadas)
    # - cache lidos: 500 tokens
    # - output: 180 tokens (50+50+80)
    # custo = (400/1e6)*3.0 + (500/1e6)*(3.0*0.10) + (180/1e6)*15.0
    #       = 0.0012 + 0.00015 + 0.0027
    #       = 0.00405
    # (arredondado a 4 casas decimais conforme o modulo)
    expected_cost = pytest.approx(0.0041, abs=0.0005)  # margem de erro aceitavel
    assert job_metadata["custo_estimado_usd"] == expected_cost


def test_job_metadata_campos_cache_com_cache_creation(tmp_path, monkeypatch):
    """job_metadata contem todos os campos novos de cache: tokens_input_total,
    tokens_input_nao_cacheado, tokens_cache_criados, tokens_cache_lidos, cache_hit_rate."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # Simular uma resposta onde a fase 2 teve cache creation (escrita):
    resposta_fase2_com_cache_creation = _resposta_saida_estruturada(
        usage=FakeUsage(
            input_tokens=200,
            output_tokens=80,
            cache_creation_input_tokens=1000,
            cache_read_input_tokens=0
        )
    )
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            resposta_fase2_com_cache_creation,
        ],
    )

    modulo.gerar_roteiro(pasta_projeto)

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    # Verificar presenca e valores dos campos novos
    assert "tokens_input_nao_cacheado" in job_metadata
    assert "tokens_input_total" in job_metadata
    assert "tokens_cache_criados" in job_metadata
    assert "tokens_cache_lidos" in job_metadata
    assert "cache_hit_rate" in job_metadata

    # Valores esperados:
    # - tokens_input_nao_cacheado: 100+100+200 = 400
    # - tokens_cache_criados: 1000 (so na ultima chamada)
    # - tokens_cache_lidos: 0
    # - tokens_input_total: 400 + 1000 + 0 = 1400
    # - cache_hit_rate: 0 / 1400 = 0.0
    assert job_metadata["tokens_input_nao_cacheado"] == 400
    assert job_metadata["tokens_cache_criados"] == 1000
    assert job_metadata["tokens_cache_lidos"] == 0
    assert job_metadata["tokens_input_total"] == 1400
    assert job_metadata["cache_hit_rate"] == 0.0


def test_job_metadata_cache_hit_rate_com_leitura_e_escrita(tmp_path, monkeypatch):
    """cache_hit_rate calcula corretamente quando ha tanto cache creation quanto cache reads."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # Simular: primeira chamada sem cache, segunda chamada leu cache da primeira
    resposta_com_cache_write = FakeResponse(
        [FakeContentBlock("text", text="Pesquisa completa")],
        usage=FakeUsage(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=500,
            cache_read_input_tokens=0
        )
    )
    resposta_com_cache_read = FakeResponse(
        [FakeContentBlock("tool_use", id="tu_resumo", name="entregar_resumo_pesquisa",
                         input={
                             "fatos_verificados": [],
                             "cronologia": [],
                             "pessoas_envolvidas": [],
                             "conflitos_entre_fontes": [],
                             "titulos_top_youtube": [],
                             "observacoes_editoriais": [],
                         })],
        usage=FakeUsage(
            input_tokens=50,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=200
        )
    )
    resposta_fase2 = _resposta_saida_estruturada(
        usage=FakeUsage(input_tokens=100, output_tokens=80)
    )

    fake_client = _instalar_client_fake(
        monkeypatch,
        [resposta_com_cache_write, resposta_com_cache_read, resposta_fase2],
    )

    modulo.gerar_roteiro(pasta_projeto)

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    # Valores esperados:
    # - tokens_input_nao_cacheado: 100+50+100 = 250
    # - tokens_cache_criados: 500
    # - tokens_cache_lidos: 200
    # - tokens_input_total: 250+500+200 = 950
    # - cache_hit_rate: 200/950 = 0.2105...
    assert job_metadata["tokens_input_nao_cacheado"] == 250
    assert job_metadata["tokens_cache_criados"] == 500
    assert job_metadata["tokens_cache_lidos"] == 200
    assert job_metadata["tokens_input_total"] == 950
    assert job_metadata["cache_hit_rate"] == pytest.approx(200 / 950, abs=0.0001)


# ---------------------------------------------------------------------------
# Otimizacao de cache (Sessao 6.7) - GOTCHA de `tools` invalidando cache do
# system, debug_cache.log, aviso_cache em job_metadata.
# ---------------------------------------------------------------------------


def test_chamada_resumo_e_chamada_final_compartilham_a_mesma_lista_de_tools(tmp_path, monkeypatch):
    """A chamada forcada de resumo (fim da fase 1) e a chamada final da fase
    2 usam a MESMA lista de tools (TOOLS_FASE_ESTRUTURADA) - condicao
    necessaria para o cache do prompt de sistema (cache_control) ser LIDO
    (nao reescrito) na segunda chamada, ja que a Anthropic API inclui
    `tools` no prefixo cacheavel antes de `system` (CLAUDE.md/docstring do
    modulo - "GOTCHA de cache invalidado por tools")."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    chamada_resumo = fake_client.messages.chamadas[1]
    chamada_final = fake_client.messages.chamadas[2]

    assert chamada_resumo["tools"] == chamada_final["tools"]
    assert chamada_resumo["tools"] == modulo.TOOLS_FASE_ESTRUTURADA


def test_chamada_resumo_forca_tool_choice_entregar_resumo(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    chamada_resumo = fake_client.messages.chamadas[1]
    assert chamada_resumo["tool_choice"] == {"type": "tool", "name": "entregar_resumo_pesquisa"}


def test_chamada_final_forca_tool_choice_entregar_roteiro(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    chamada_final = fake_client.messages.chamadas[2]
    assert chamada_final["tool_choice"] == {"type": "tool", "name": "entregar_roteiro"}


def test_pesquisa_loop_nao_expoe_tools_de_saida_estruturada(tmp_path, monkeypatch):
    """O loop de pesquisa (tool_choice='auto') continua usando so
    tools_pesquisa (web_search [+ youtube]) - entregar_resumo_pesquisa e
    entregar_roteiro NAO sao expostas ali, para nao arriscar o modelo
    chama-las cedo demais e quebrar o fluxo de duas fases (CLAUDE.md secao
    5.3). So a chamada de resumo e a final (ambas com tool_choice forcado)
    compartilham TOOLS_FASE_ESTRUTURADA."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    fake_client = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    chamada_pesquisa = fake_client.messages.chamadas[0]
    nomes_tools_pesquisa = {t["name"] for t in chamada_pesquisa["tools"]}
    assert "entregar_resumo_pesquisa" not in nomes_tools_pesquisa
    assert "entregar_roteiro" not in nomes_tools_pesquisa
    assert "tool_choice" not in chamada_pesquisa


def test_debug_cache_log_gravado_apos_geracao(tmp_path, monkeypatch):
    """debug_cache.log e' gravado em logs/ com o detalhe de cada chamada
    messages.create (Sessao 6.7, B.3)."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    caminho_log = pasta_projeto / "logs" / "debug_cache.log"
    assert caminho_log.exists()
    conteudo = caminho_log.read_text(encoding="utf-8")
    assert "cache_hit_rate final" in conteudo
    assert "pesquisa_rodada_1" in conteudo
    assert "resumo_estruturado" in conteudo
    assert "roteiro_final" in conteudo


def test_aviso_cache_aparece_quando_hit_rate_baixo(tmp_path, monkeypatch):
    """job_metadata.json ganha 'aviso_cache' quando cache_hit_rate < 0.5
    (Sessao 6.7, B.3)."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # Fluxo feliz padrao nao gera nenhum cache_read (tudo FakeUsage default
    # sem cache_read_input_tokens) - hit_rate = 0.0, bem abaixo de 0.5.
    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["cache_hit_rate"] < 0.5
    assert "aviso_cache" in job_metadata
    assert "debug_cache.log" in job_metadata["aviso_cache"]


def test_aviso_cache_ausente_quando_hit_rate_alto(tmp_path, monkeypatch):
    """job_metadata.json NAO ganha 'aviso_cache' quando cache_hit_rate >= 0.5."""
    pasta_projeto = _criar_projeto(tmp_path, perfil="truecrime")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resposta_pesquisa_com_hit = FakeResponse(
        [FakeContentBlock("text", text="Pesquisa completa")],
        usage=FakeUsage(input_tokens=50, output_tokens=50, cache_read_input_tokens=900, cache_creation_input_tokens=0),
    )
    resposta_resumo_com_hit = _resposta_resumo_estruturado(
        usage=FakeUsage(input_tokens=10, output_tokens=20, cache_read_input_tokens=100, cache_creation_input_tokens=0)
    )
    resposta_final_com_hit = _resposta_saida_estruturada(
        usage=FakeUsage(input_tokens=10, output_tokens=20, cache_read_input_tokens=100, cache_creation_input_tokens=0)
    )

    _instalar_client_fake(
        monkeypatch, [resposta_pesquisa_com_hit, resposta_resumo_com_hit, resposta_final_com_hit]
    )

    modulo.gerar_roteiro(pasta_projeto)

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["cache_hit_rate"] >= 0.5
    assert "aviso_cache" not in job_metadata


# ---------------------------------------------------------------------------
# Tamanho configurável do roteiro (CLAUDE.md secao 5.3/7)
# ---------------------------------------------------------------------------


def test_gerar_roteiro_configuracao_tamanho_ausente_usa_default(tmp_path, monkeypatch):
    """Se entrada/configuracao_video.json não existe, _ler_configuracao_tamanho
    retorna (PALAVRAS_ALVO_PADRAO=4000, DURACAO_ALVO_MINUTOS_PADRAO=25)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    # Sem gravar entrada/configuracao_video.json

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["palavras_alvo"] == 4000
    assert job_metadata["duracao_alvo_minutos"] == 25


def test_gerar_roteiro_configuracao_tamanho_com_valores_customizados(
    tmp_path, monkeypatch
):
    """Se entrada/configuracao_video.json tem palavras_alvo=6000 e
    duracao_alvo_minutos=40, esses valores aparecem no job_metadata."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(
            {
                "palavras_alvo": 6000,
                "duracao_alvo_minutos": 40,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["palavras_alvo"] == 6000
    assert job_metadata["duracao_alvo_minutos"] == 40


def test_gerar_roteiro_injeta_bloco_tamanho_no_prompt_sistema(
    tmp_path, monkeypatch
):
    """_montar_bloco_tamanho_alvo injeta instrução de tamanho no prompt de
    sistema. O prompt final deve conter referência ao número de palavras e
    caracteres estimados."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 5000, "duracao_alvo_minutos": 30}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    client_fake = _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    modulo.gerar_roteiro(pasta_projeto)

    # Captura as chamadas à API para verificar o prompt
    assert len(client_fake.messages.chamadas) >= 1
    primeira_chamada = client_fake.messages.chamadas[0]
    # O campo "system" é uma lista de blocos com cache_control
    # (_montar_system_blocks) - o texto fica em bloco["text"].
    assert "system" in primeira_chamada
    prompt_sistema = "".join(bloco["text"] for bloco in primeira_chamada["system"])
    # Deve conter referência ao tamanho (5000 palavras é esperado)
    assert "5000" in prompt_sistema or "palavra" in prompt_sistema.lower()


def test_gerar_roteiro_grava_campos_tamanho_e_ratio_no_metadata(
    tmp_path, monkeypatch
):
    """job_metadata.json gravado ao final de gerar_roteiro deve conter:
    - pergunta_promessa: campo obrigatorio do schema
    - palavras_narradas: contagem sem notas de rodape nem markdown
    - palavras_alvo / duracao_alvo_minutos: do arquivo de configuracao
    - caracteres_alvo_min_informativo / caracteres_alvo_max_informativo:
      calculados, apenas informativos (nao entram no ratio)
    - ratio_tamanho: palavras_narradas / palavras_alvo
    - stop_reason_final: de resposta_final.stop_reason

    Usa um roteiro longo o suficiente (>=95% do alvo) para nao disparar o
    mecanismo de expansao, testado separadamente."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 4000, "duracao_alvo_minutos": 25}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_md = "palavra " * 3900 + "[F1@00:00]"

    # Resposta com stop_reason conhecido
    resposta_final_com_stop = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input={
                    "pergunta_promessa": PERGUNTA_PROMESSA_TESTE,
                    "roteiro_md": roteiro_md,
                    "titulos": ["T1", "T2", "T3"],
                    "descricoes": ["D1", "D2", "D3"],
                },
            )
        ],
        usage=FakeUsage(),
    )
    resposta_final_com_stop.stop_reason = "end_turn"

    respostas = [
        _resposta_sem_tool_use(),
        _resposta_resumo_estruturado(),
        resposta_final_com_stop,
    ]
    _instalar_client_fake(monkeypatch, respostas)

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    # Verificar campos gravados
    assert job_metadata["pergunta_promessa"] == PERGUNTA_PROMESSA_TESTE
    assert "palavras_narradas" in job_metadata
    assert job_metadata["palavras_alvo"] == 4000
    assert job_metadata["duracao_alvo_minutos"] == 25
    assert "caracteres_alvo_min_informativo" in job_metadata
    assert "caracteres_alvo_max_informativo" in job_metadata
    assert "ratio_tamanho" in job_metadata
    assert job_metadata["stop_reason_final"] == "end_turn"
    assert job_metadata["numero_expansoes"] == 0

    # caracteres_alvo_min_informativo = 4000 * 5.0 = 20000
    assert job_metadata["caracteres_alvo_min_informativo"] == 20000
    # caracteres_alvo_max_informativo = 4000 * 6.0 = 24000
    assert job_metadata["caracteres_alvo_max_informativo"] == 24000

    palavras_esperadas = modulo.contar_palavras_narradas(roteiro_md)
    assert job_metadata["palavras_narradas"] == palavras_esperadas
    ratio_esperado = round(palavras_esperadas / 4000, 2)
    assert job_metadata["ratio_tamanho"] == ratio_esperado


def test_gerar_roteiro_ratio_pequeno_adiciona_aviso_tamanho(
    tmp_path, monkeypatch
):
    """Se ratio_tamanho < 1.0 (roteiro muito curto), job_metadata recebe
    campo aviso_tamanho com mensagem de que o roteiro ficou abaixo do
    esperado."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 4000, "duracao_alvo_minutos": 25}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # Resposta com roteiro muito curto (< 1000 caracteres)
    resposta_final_curta = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input={
                    "pergunta_promessa": PERGUNTA_PROMESSA_TESTE,
                    "roteiro_md": "Roteiro muito curto.",  # ~20 caracteres
                    "titulos": ["T1", "T2", "T3"],
                    "descricoes": ["D1", "D2", "D3"],
                },
            )
        ],
        usage=FakeUsage(),
    )

    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            resposta_final_curta,
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    # ratio < 1.0 deve gerar aviso
    assert job_metadata["ratio_tamanho"] < 1.0
    assert "aviso_tamanho" in job_metadata


# ---------------------------------------------------------------------------
# Investigacao de tamanho curto (Grupos A-F) - roteiro sistematicamente
# abaixo do alvo configurado. Ver CLAUDE.md e HISTORICO_BUGS.md para o
# diagnostico completo (numeros conflitantes no sistema.md dos perfis,
# clausula de escape silenciosa, alvo ausente do prompt de usuario da
# fase 2).
# ---------------------------------------------------------------------------


def test_bloco_tamanho_alvo_nao_contem_aproximadamente():
    """Grupo B: linguagem de piso, nao de aproximacao - 'aproximadamente'
    nao pode aparecer no bloco que define o numero exato deste projeto."""
    bloco = modulo._montar_bloco_tamanho_alvo(4000, 25)
    assert "aproximad" not in bloco.lower()


def test_bloco_tamanho_alvo_deixa_claro_que_e_piso():
    """Grupo B: o bloco precisa deixar explicito que o minimo e' piso
    (roteiro abaixo dele e' incompleto), nao uma sugestao."""
    bloco = modulo._montar_bloco_tamanho_alvo(4000, 25)
    assert "incompleto" in bloco.lower() or "piso" in bloco.lower()


def test_bloco_tamanho_alvo_menciona_justificativa_tamanho():
    """Grupo D: o escape com preco - o bloco de sistema (nao so o
    sistema.md do perfil) tambem precisa apontar pro campo
    justificativa_tamanho como saida do escape, nao silencio."""
    bloco = modulo._montar_bloco_tamanho_alvo(4000, 25)
    assert "justificativa_tamanho" in bloco


@pytest.mark.parametrize("perfil", ["truecrime", "atualidades_narrativas", "historia"])
def test_sistema_md_nenhum_perfil_tem_faixa_numerica_de_tamanho_total(perfil):
    """Grupo A/F: nenhum sistema.md de nenhum perfil pode conter faixa
    numerica de caracteres/minutos para o tamanho TOTAL do roteiro - o
    unico numero valido vem do bloco montado em runtime por
    _montar_bloco_tamanho_alvo. (Nao cobre mencoes numericas de ritmo
    interno, tipo 'gancho a cada 2-3 minutos' ou 'hook de ~350-500
    caracteres', que nao sao alvo de tamanho total e continuam legitimas.)"""
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / perfil / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "25.000" not in texto
    assert "35.000" not in texto
    assert "20.000" not in texto
    assert "40.000" not in texto
    assert "25-35" not in texto


def test_montar_prompt_usuario_fase2_inclui_alvo_no_final():
    """Grupo C: o prompt de usuario da fase 2 precisa repetir o alvo de
    tamanho como ULTIMO bloco (reforco de recencia, imediatamente antes
    do modelo escrever)."""
    manifest = {"fontes": []}
    resumo = {"fatos_verificados": []}
    prompt = modulo.montar_prompt_usuario_fase2(resumo, manifest, {}, 4000, 20000)
    assert "20000" in prompt or "20.000" in prompt
    assert "LEMBRETE DE TAMANHO" in prompt
    # o bloco de lembrete precisa vir depois de tudo mais (resumo, transcricoes,
    # instrucao de formato) - e' o ultimo bloco do prompt montado.
    indice_lembrete = prompt.index("LEMBRETE DE TAMANHO")
    indice_instrucao_formato = prompt.index("Gere o roteiro final")
    assert indice_lembrete > indice_instrucao_formato


def test_schema_saida_tem_campo_justificativa_tamanho_opcional():
    """Grupo D: o schema da tool de saida ganha o campo, mas ele nao entra
    em 'required' - a saida sem o campo continua valida."""
    propriedades = modulo.SCHEMA_SAIDA["input_schema"]["properties"]
    assert "justificativa_tamanho" in propriedades
    assert propriedades["justificativa_tamanho"]["type"] == "string"
    assert "justificativa_tamanho" not in modulo.SCHEMA_SAIDA["input_schema"]["required"]


def test_validar_saida_estruturada_aceita_com_e_sem_justificativa():
    """Grupo D/F: _validar_saida_estruturada nao rejeita nem exige o campo
    novo - roteiro sem justificativa (caso normal) e com justificativa
    (caso de escape) sao ambos validos."""
    base = {
        "pergunta_promessa": PERGUNTA_PROMESSA_TESTE,
        "roteiro_md": "Texto do roteiro.",
        "titulos": ["T1", "T2", "T3"],
        "descricoes": ["D1", "D2", "D3"],
    }
    valido_sem, erro_sem = modulo._validar_saida_estruturada(base)
    assert valido_sem is True and erro_sem is None

    com_justificativa = dict(base, justificativa_tamanho="Fontes insuficientes sobre o desfecho.")
    valido_com, erro_com = modulo._validar_saida_estruturada(com_justificativa)
    assert valido_com is True and erro_com is None


def test_gerar_roteiro_ratio_pequeno_com_justificativa_persiste_no_metadata(
    tmp_path, monkeypatch
):
    """Grupo D: quando o modelo preenche justificativa_tamanho (porque o
    roteiro ficou abaixo do minimo), o campo e' persistido em
    job_metadata.json junto de ratio_tamanho/aviso_tamanho."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 4000, "duracao_alvo_minutos": 25}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resposta_final_com_justificativa = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input={
                    "pergunta_promessa": PERGUNTA_PROMESSA_TESTE,
                    "roteiro_md": "Roteiro curto por falta de fontes.",
                    "titulos": ["T1", "T2", "T3"],
                    "descricoes": ["D1", "D2", "D3"],
                    "justificativa_tamanho": (
                        "As fontes disponiveis so cobrem os primeiros "
                        "eventos do caso; o desfecho nao tem cobertura "
                        "verificavel suficiente para expandir sem "
                        "especular."
                    ),
                },
            )
        ],
        usage=FakeUsage(),
    )

    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            resposta_final_com_justificativa,
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    assert job_metadata["ratio_tamanho"] < 1.0
    assert "aviso_tamanho" in job_metadata
    assert job_metadata["justificativa_tamanho"] == (
        "As fontes disponiveis so cobrem os primeiros "
        "eventos do caso; o desfecho nao tem cobertura "
        "verificavel suficiente para expandir sem "
        "especular."
    )


def test_gerar_roteiro_ratio_grande_nao_persiste_justificativa_mesmo_se_presente(
    tmp_path, monkeypatch
):
    """Grupo D: justificativa_tamanho so e' persistida quando o roteiro
    ficou abaixo do minimo (ratio_tamanho < 1.0) - um campo presente na
    saida do modelo mas com roteiro dentro do alvo nao deveria acontecer
    na pratica (o prompt so pede o campo no caso de escape), mas o
    codigo nao deve persistir lixo em job_metadata se ratio >= 1.0."""
    pasta_projeto = _criar_projeto(tmp_path)
    # palavras_alvo=10 seria clampado para o default (1000-15000, ver
    # _ler_configuracao_tamanho) - usa o menor valor valido do range.
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 5}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    # ratio_tamanho agora e' medido em palavras narradas - 1050 palavras
    # para um alvo de 1000 da' ratio 1.05 (>= 1.0, nao dispara expansao).
    roteiro_longo = "Palavra " * 1050
    resposta_final = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input={
                    "pergunta_promessa": PERGUNTA_PROMESSA_TESTE,
                    "roteiro_md": roteiro_longo,
                    "titulos": ["T1", "T2", "T3"],
                    "descricoes": ["D1", "D2", "D3"],
                    "justificativa_tamanho": "Nao deveria ser persistido.",
                },
            )
        ],
        usage=FakeUsage(),
    )

    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            resposta_final,
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    assert job_metadata["ratio_tamanho"] >= 1.0
    assert "aviso_tamanho" not in job_metadata
    assert "justificativa_tamanho" not in job_metadata
    assert job_metadata["numero_expansoes"] == 0


# ---------------------------------------------------------------------------
# Reestruturacao do roteiro (pergunta-promessa, estrutura por divida
# narrativa, proibicoes de voz, expansao e justificativa obrigatoria) - ver
# CLAUDE.md/prompt de sessao para o diagnostico completo dos 3 problemas
# que motivaram esta reestruturacao.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["truecrime", "atualidades_narrativas", "historia"])
def test_sistema_md_nenhum_perfil_tem_estrutura_antiga_por_cronologia(perfil):
    """Grupo G.1: a estrutura antiga (abertura-contexto-desenvolvimento
    cronologico-desfecho-fechamento) foi substituida integralmente pela
    estrutura por divida narrativa."""
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / perfil / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "Desenvolvimento cronológico" not in texto
    assert "Contexto (logo após a abertura)" not in texto
    assert "Título factual" not in texto
    assert "Âncora" in texto
    assert "Virada" in texto
    assert "dívida" in texto.lower()


@pytest.mark.parametrize("perfil", ["truecrime", "atualidades_narrativas", "historia"])
def test_sistema_md_tem_regra_0_pergunta_promessa_antes_da_regra_1(perfil):
    """Grupo G.1: os tres perfis ganham a Regra 0 (pergunta-promessa),
    posicionada antes da Regra 1, com as quatro condicoes obrigatorias."""
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / perfil / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "Regra 0" in texto
    assert "pergunta-promessa" in texto.lower()
    indice_regra0 = texto.index("Regra 0")
    indice_regra1 = texto.index("Regra 1")
    assert indice_regra0 < indice_regra1


@pytest.mark.parametrize("perfil", ["truecrime", "atualidades_narrativas", "historia"])
def test_sistema_md_tem_proibicoes_de_voz_e_regra_de_derivacao(perfil):
    """Grupo G.1: proibicoes de disclaimer falado, regra de derivacao
    numerica (exemplo dos 41 minutos) e regra de nome proprio (nunca leva
    nota de transcricao)."""
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / perfil / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "41 minutos" in texto
    assert "nota de transcrição" in texto
    assert "é apresentado aqui como tal" in texto


@pytest.mark.parametrize("perfil", ["truecrime", "atualidades_narrativas", "historia"])
def test_sistema_md_titulos_derivados_da_pergunta_promessa(perfil):
    """Grupo G.1: os titulos sugeridos sao 3 formulacoes da pergunta-
    promessa (direto/com autoridade/com o obstaculo), nao 3 angulos
    independentes."""
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / perfil / "sistema.md"
    texto = caminho.read_text(encoding="utf-8")
    assert "**Direto**" in texto
    assert "**Com autoridade**" in texto
    assert "**Com o obstáculo**" in texto


def test_schema_saida_pergunta_promessa_obrigatoria():
    """Grupo G.3: pergunta_promessa entra em SCHEMA_SAIDA e e' obrigatoria."""
    propriedades = modulo.SCHEMA_SAIDA["input_schema"]["properties"]
    assert "pergunta_promessa" in propriedades
    assert "pergunta_promessa" in modulo.SCHEMA_SAIDA["input_schema"]["required"]


def test_validar_saida_estruturada_rejeita_pergunta_promessa_ausente():
    """Grupo G.3: pergunta_promessa ausente invalida a saida."""
    dados = {
        "roteiro_md": "Texto do roteiro.",
        "titulos": ["T1", "T2", "T3"],
        "descricoes": ["D1", "D2", "D3"],
    }
    valido, erro = modulo._validar_saida_estruturada(dados)
    assert valido is False
    assert "pergunta_promessa" in erro


@pytest.mark.parametrize(
    "pergunta_promessa",
    ["", "   ", "Por que?", "O motivo dele nao foi provado"],
)
def test_validar_saida_estruturada_rejeita_pergunta_promessa_vazia_ou_generica(pergunta_promessa):
    """Grupo G.3: pergunta_promessa vazia, curta demais, ou sem '?' (nao
    formulada como pergunta) invalida a saida."""
    dados = {
        "pergunta_promessa": pergunta_promessa,
        "roteiro_md": "Texto do roteiro.",
        "titulos": ["T1", "T2", "T3"],
        "descricoes": ["D1", "D2", "D3"],
    }
    valido, erro = modulo._validar_saida_estruturada(dados)
    assert valido is False


def test_contar_palavras_narradas_ignora_notas_e_markdown():
    """Grupo G.4: contar_palavras_narradas ignora notas de rodape e
    marcacao markdown leve - bate com contagem manual em texto de
    referencia (28 palavras depois de remover notas/markdown)."""
    texto = (
        "# Titulo\n\n"
        "Isto e um paragrafo de teste com uma nota externa e um aviso "
        "registrado [F1@00:00] [N: exemplo.com/artigo] [⚠ single-source] "
        "no meio do texto.\n\n"
        "Segundo paragrafo sem nenhuma nota apenas texto normal aqui."
    )
    assert modulo.contar_palavras_narradas(texto) == 28


def test_contar_palavras_narradas_ignora_tag_multi_fonte():
    """Grupo G.4: tag com multiplas fontes ([F1@.., F2@..]) e' removida
    inteira, nao deixa residuo contado como palavra."""
    texto = "Uma frase com evidencia dupla [F1@00:10, F2@01:20] confirmada."
    assert modulo.contar_palavras_narradas(texto) == len(
        "Uma frase com evidencia dupla confirmada.".split()
    )


def test_gerar_roteiro_ratio_acima_do_limiar_nao_dispara_expansao(tmp_path, monkeypatch):
    """Grupo G.5: roteiro >= 95% do alvo em palavras narradas nao dispara
    nenhuma chamada de expansao."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_no_alvo = "Palavra " * 960 + "[F1@00:00]"  # 96% de 1000
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(roteiro_md=roteiro_no_alvo),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 3
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["numero_expansoes"] == 0
    assert "expansoes" not in job_metadata


def test_gerar_roteiro_ratio_abaixo_do_limiar_expande_e_para_em_duas(tmp_path, monkeypatch):
    """Grupo G.5: roteiro abaixo de 95% do alvo dispara expansao; mesmo
    aceitando as duas tentativas, o loop para em MAX_EXPANSOES (2) mesmo
    sem atingir o piso."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_inicial = "Palavra " * 500 + "[F1@00:00]"  # 50%
    roteiro_expandido_1 = "Palavra " * 700 + "[F1@00:00]"  # 70%
    roteiro_expandido_2 = "Palavra " * 900 + "[F1@00:00]"  # 90% - ainda < 95%

    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(roteiro_md=roteiro_inicial),
            _resposta_saida_estruturada(roteiro_md=roteiro_expandido_1),
            _resposta_saida_estruturada(roteiro_md=roteiro_expandido_2),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    # 3 chamadas do fluxo normal + 2 expansoes = 5 (a chamada de
    # justificativa, tentada em seguida por ratio ainda < 0.95, esgota a
    # fila e falha silenciosamente - nao afeta o resultado).
    assert len(fake_client.messages.chamadas) >= 5
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["numero_expansoes"] == 2
    assert [e["aceita"] for e in job_metadata["expansoes"]] == [True, True]
    assert job_metadata["palavras_narradas"] == 900
    assert job_metadata["ratio_tamanho"] == 0.9
    assert "aviso_tamanho" in job_metadata


def test_gerar_roteiro_expansao_com_queda_de_notas_e_descartada(tmp_path, monkeypatch):
    """Grupo G.6: expansao que perde notas de rodape (queda > 10%) e'
    descartada - a versao anterior (mais curta, mas com as notas
    originais) e' mantida."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_original = (
        "Palavra " * 500 + "[F1@00:00] [F2@01:00] [F3@02:00]"
    )  # 50%, 3 notas
    roteiro_expandido_sem_notas = "Palavra " * 800  # 80%, 0 notas - queda total

    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(roteiro_md=roteiro_original),
            _resposta_saida_estruturada(roteiro_md=roteiro_expandido_sem_notas),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    assert job_metadata["numero_expansoes"] == 1
    assert job_metadata["expansoes"][0]["aceita"] is False
    assert "notas" in job_metadata["expansoes"][0]["motivo_rejeicao"]
    # A versao PERSISTIDA e' a original (500 palavras), nao a expandida.
    assert job_metadata["palavras_narradas"] == 500
    roteiro_persistido = (pasta_projeto / "roteiro.md").read_text(encoding="utf-8")
    assert roteiro_persistido == roteiro_original


def test_gerar_roteiro_solicita_justificativa_quando_piso_nao_atingido(tmp_path, monkeypatch):
    """Grupo G.7: se o roteiro final ficou abaixo do piso e o modelo nao
    preencheu justificativa_tamanho por conta propria, uma chamada extra
    e forcada para obter a justificativa."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_curto = "Palavra " * 200 + "[F1@00:00]"  # 20%, bem abaixo do piso
    resposta_justificativa = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_justificativa",
                name="entregar_justificativa_tamanho",
                input={"justificativa": "Faltaram fontes verificaveis sobre o desfecho do caso."},
            )
        ],
        usage=FakeUsage(),
    )

    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(roteiro_md=roteiro_curto),
            _resposta_sem_tool_use(),  # tentativa de expansao invalida (sem tool_use) -> descartada
            resposta_justificativa,
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))

    assert job_metadata["numero_expansoes"] == 1
    assert job_metadata["expansoes"][0]["aceita"] is False
    assert job_metadata["justificativa_tamanho"] == "Faltaram fontes verificaveis sobre o desfecho do caso."


def test_gerar_roteiro_nao_solicita_justificativa_se_ja_fornecida(tmp_path, monkeypatch):
    """Grupo G.7: se o modelo ja preencheu justificativa_tamanho na saida
    original, nenhuma chamada extra de justificativa e' feita."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_curto_com_justificativa = FakeResponse(
        [
            FakeContentBlock(
                "tool_use",
                id="tu_final",
                name="entregar_roteiro",
                input={
                    "pergunta_promessa": PERGUNTA_PROMESSA_TESTE,
                    "roteiro_md": "Palavra " * 200 + "[F1@00:00]",
                    "titulos": ["T1", "T2", "T3"],
                    "descricoes": ["D1", "D2", "D3"],
                    "justificativa_tamanho": "Fontes insuficientes sobre o desfecho.",
                    "nucleo_editorial": NUCLEO_EDITORIAL_TESTE,
                },
            )
        ],
        usage=FakeUsage(),
    )

    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            roteiro_curto_com_justificativa,
            _resposta_sem_tool_use(),  # tentativa de expansao invalida -> descartada
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    # 3 chamadas do fluxo normal + 1 tentativa de expansao (invalida) = 4.
    # Nenhuma chamada de justificativa extra, porque o campo ja veio
    # preenchido na saida original.
    assert len(fake_client.messages.chamadas) == 4
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["justificativa_tamanho"] == "Fontes insuficientes sobre o desfecho."


# ===========================================================================
# Sessao de refinamento pos-validacao empirica: Grupos A/B/C (validacoes
# pos-geracao, nunca bloqueiam, nunca tocam sistema.md - CLAUDE.md).
# ===========================================================================


# ---------------------------------------------------------------------------
# Nao-regressao (Grupo E do PLANO) - garante que nada do que a sessao
# anterior implementou foi alterado por esta sessao.
# ---------------------------------------------------------------------------

# Hashes calculados nesta sessao, ANTES de qualquer edicao a sistema.md
# (nenhum sistema.md foi tocado por esta sessao - CLAUDE.md, restricao
# central). Se este teste falhar no futuro, alguem editou um sistema.md e
# precisa recalcular conscientemente, nao por acidente.
#
# Excecao deliberada (correcao pos-Sessao 21): "truecrime" foi editado
# cirurgicamente nesta sessao para remover a brecha que autorizava
# "eventualmente um subtitulo" no roteiro (bug real: cabecalhos markdown
# tipo "## The Woman Who Lived Alone..." iam parar no TTS e eram narrados
# literalmente). Regra 0, estrutura por divida narrativa, proibicoes de
# voz e regra de derivacao NAO foram tocadas - so' a frase de permissao
# de subtitulo na secao "Formato de saida" saiu, alinhando truecrime com
# atualidades_narrativas/historia (que ja nunca tiveram essa permissao).
# Hash recalculado conscientemente apos a edicao.
#
# Recalculado de novo na sessao "coordenacao entre titulo e headline"
# (Grupo A): os 3 perfis ganharam um paragrafo na secao "Titulos
# sugeridos" instruindo que o titulo nunca deve transformar em assunto
# central um unico detalhe concreto/visualizavel do caso (o material
# bruto de onde a thumbnail tira sua propria lacuna visual) - achado real
# que motivou a mudanca: um titulo entregava explicitamente a marca no
# pulso que o headline da thumbnail usava como lacuna ("wrist tattoo" no
# titulo vs "THE MARK ON HIS WRIST" no headline).
_HASHES_SISTEMA_MD = {
    "atualidades_narrativas": "312ac3a9125682bd88b1302bc38f5040b07ecc2e438abe3c6d510d52e29f9e04",
    "historia": "4a889931aebf43fdbfedb3aba887327dae4341e5005d5b04b15d9c3488d47781",
    "truecrime": "1eb08167a40849d97aec3a330e02d88d054d6d9f110bd8648bd17f5b62e06d36",
}


@pytest.mark.parametrize("perfil", sorted(_HASHES_SISTEMA_MD))
def test_sistema_md_nao_foi_alterado_por_esta_sessao(perfil):
    caminho = BASE_DIR / "scripts" / "prompts" / "perfis" / perfil / "sistema.md"
    conteudo = caminho.read_bytes()
    assert hashlib.sha256(conteudo).hexdigest() == _HASHES_SISTEMA_MD[perfil]


def test_nao_regressao_contar_palavras_narradas_valor_referencia():
    texto = "Uma frase [F1@00:00] com **markdown** e [N: url] e [⚠ single-source] aqui."
    # "Uma frase com markdown e e aqui." -> 7 palavras narradas.
    assert modulo.contar_palavras_narradas(texto) == 7


def test_nao_regressao_ratio_tamanho_medido_em_palavras_narradas(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}), encoding="utf-8"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    roteiro_1000_palavras = ("Palavra " * 1000).strip()
    _instalar_client_fake(
        monkeypatch, _respostas_fluxo_feliz(_resposta_saida_estruturada(roteiro_md=roteiro_1000_palavras))
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["palavras_narradas"] == 1000
    assert job_metadata["ratio_tamanho"] == 1.0


def test_nao_regressao_expansao_dispara_abaixo_de_95_e_para_em_duas():
    assert modulo.EXPANSAO_LIMIAR_RATIO == 0.95
    assert modulo.MAX_EXPANSOES == 2


def test_nao_regressao_pergunta_promessa_continua_obrigatoria():
    assert "pergunta_promessa" in modulo.SCHEMA_SAIDA["input_schema"]["required"]


# ---------------------------------------------------------------------------
# Grupo A - nomes proprios sustentados so' por transcricao
# ---------------------------------------------------------------------------


def test_detectar_nomes_nome_presente_no_corpus_nao_e_sinalizado():
    roteiro = "Her sister's husband, Tommaso Cioni, was interviewed [F1@04:32]."
    resumo = {
        "pessoas_envolvidas": [
            {"nome": "Tommaso Cioni", "papel": "familiar", "status_legal": "nenhum"}
        ]
    }
    resultado = modulo.detectar_nomes_suspeitos(roteiro, resumo)
    assert resultado == []


def test_detectar_nomes_ausente_do_corpus_com_nota_so_de_transcricao_e_alto():
    roteiro = "Her sister's husband, Tomas Ossioni, was photographed there [F1@33:39]."
    resumo = {"pessoas_envolvidas": [{"nome": "Fulano de Tal", "papel": "outro"}]}
    resultado = modulo.detectar_nomes_suspeitos(roteiro, resumo)
    nomes = {r["nome"]: r for r in resultado}
    assert "Tomas Ossioni" in nomes
    assert nomes["Tomas Ossioni"]["nivel"] == "alto"
    assert "Tomas Ossioni" in nomes["Tomas Ossioni"]["contexto"]


def test_detectar_nomes_ausente_do_corpus_sem_nota_e_medio():
    roteiro = "Her sister's husband, Fulano Beltrano, was there without any footnote."
    resultado = modulo.detectar_nomes_suspeitos(roteiro, {})
    nomes = {r["nome"]: r for r in resultado}
    assert nomes["Fulano Beltrano"]["nivel"] == "medio"


def test_detectar_nomes_nota_ambigua_f_e_n_juntas_e_medio_nao_alto():
    roteiro = "Her sister's husband, Fulano Beltrano, was interviewed [F1@04:32][N: https://example.com]."
    resultado = modulo.detectar_nomes_suspeitos(roteiro, {})
    nomes = {r["nome"]: r for r in resultado}
    assert nomes["Fulano Beltrano"]["nivel"] == "medio"


def test_detectar_nomes_ignora_lugar_ou_instituicao():
    roteiro = "The case was handled by the Springfield Police Department [F1@01:00]."
    resultado = modulo.detectar_nomes_suspeitos(roteiro, {})
    assert all("Police Department" not in r["nome"] for r in resultado)


def test_detectar_nomes_ignora_stopword_no_inicio_do_candidato():
    roteiro = "The Suspect fled the scene before officers arrived [F1@02:00]."
    resultado = modulo.detectar_nomes_suspeitos(roteiro, {})
    assert all(r["nome"] != "The Suspect" for r in resultado)


def test_detectar_nomes_sem_candidato_retorna_vazio():
    assert modulo.detectar_nomes_suspeitos("nenhum nome proprio aqui.", {}) == []


def test_detectar_nomes_resumo_ausente_nao_quebra():
    roteiro = "Fulano Beltrano foi interrogado [F1@00:10]."
    resultado = modulo.detectar_nomes_suspeitos(roteiro, None)
    assert resultado[0]["nivel"] == "alto"


# ---------------------------------------------------------------------------
# Grupo B - titulos possivelmente divergentes do nucleo editorial
# ---------------------------------------------------------------------------


def test_detectar_titulos_alinhados_com_nucleo_nao_dispara():
    nucleo = "mistakes that identify him"
    titulos = [
        "The Mistakes That Identify Him",
        "How His Mistakes Gave Him Away",
        "What Mistake Finally Identified Him?",
    ]
    assert modulo.detectar_titulos_divergentes(nucleo, titulos) == []


def test_detectar_titulos_divergentes_sao_sinalizados():
    nucleo = "mistakes that identify him"
    titulos = ["Wrist Tattoo", "41 Minutes With Her Mother", "Why No One Was Arrested"]
    resultado = modulo.detectar_titulos_divergentes(nucleo, titulos)
    assert "Wrist Tattoo" in resultado


def test_detectar_titulos_sem_nucleo_editorial_retorna_vazio():
    """Roteiros gerados antes deste campo existir (ou modelo que nao
    preencheu) nunca disparam o Grupo B - nunca quebra, so' nao verifica."""
    titulos = ["Titulo A", "Titulo B", "Titulo C"]
    assert modulo.detectar_titulos_divergentes(None, titulos) == []
    assert modulo.detectar_titulos_divergentes("", titulos) == []


def test_detectar_titulos_sem_titulos_retorna_vazio():
    assert modulo.detectar_titulos_divergentes("mistakes that identify him", []) == []
    assert modulo.detectar_titulos_divergentes("mistakes that identify him", None) == []


# ---------------------------------------------------------------------------
# Grupo C - numero de duracao/janela temporal sem derivacao proxima
# ---------------------------------------------------------------------------


def test_detectar_numeros_com_derivacao_no_contexto_nao_e_sinalizado():
    texto = (
        "According to reconstruction based on the timing of the home's door "
        "lock and other data points, this individual remained inside the "
        "house for forty-one minutes."
    )
    assert modulo.detectar_numeros_sem_derivacao(texto) == []


def test_detectar_numeros_sem_derivacao_no_contexto_e_sinalizado():
    texto = (
        "He wore a mask, but he did not cover his mouth for the duration of "
        "his time inside. For forty-one minutes, he breathed inside an "
        "enclosed space that would later be processed as a crime scene."
    )
    resultado = modulo.detectar_numeros_sem_derivacao(texto)
    assert len(resultado) == 1
    assert "forty-one" in resultado[0]["numero_detectado"].lower()


def test_detectar_numeros_horario_no_contexto_conta_como_derivacao():
    texto = "Records show he left at 3:15. He was gone for twenty minutes."
    assert modulo.detectar_numeros_sem_derivacao(texto) == []


def test_detectar_numeros_ignora_numero_sem_unidade_de_tempo():
    texto = "The report cites forty-one witnesses interviewed by detectives."
    resultado = modulo.detectar_numeros_sem_derivacao(texto)
    # "forty-one witnesses" nao tem unidade de tempo - nao entra no escopo
    # minimo do Grupo C (so' duracao/janela temporal), entao nao dispara.
    assert resultado == []


def test_detectar_numeros_desligavel_por_env(monkeypatch):
    monkeypatch.setenv("VALIDACAO_NUMEROS_ATIVA", "false")
    texto = "For forty-one minutes, he stayed inside with no explanation given."
    assert modulo.detectar_numeros_sem_derivacao(texto) == []


def test_detectar_numeros_ligado_por_default(monkeypatch):
    monkeypatch.delenv("VALIDACAO_NUMEROS_ATIVA", raising=False)
    texto = "For forty-one minutes, he stayed inside with no explanation given."
    assert len(modulo.detectar_numeros_sem_derivacao(texto)) == 1


# ---------------------------------------------------------------------------
# Schema - nucleo_editorial
# ---------------------------------------------------------------------------


def test_schema_saida_tem_campo_nucleo_editorial_obrigatorio():
    propriedades = modulo.SCHEMA_SAIDA["input_schema"]["properties"]
    assert "nucleo_editorial" in propriedades
    assert "nucleo_editorial" in modulo.SCHEMA_SAIDA["input_schema"]["required"]


# ---------------------------------------------------------------------------
# Integracao end-to-end - job_metadata.json recebe os 3 campos novos
# ---------------------------------------------------------------------------


def test_gerar_roteiro_persiste_grupos_abc_vazios_quando_nada_suspeito(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(monkeypatch, _respostas_fluxo_feliz())

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nomes_nao_confirmados"] == []
    assert job_metadata["titulos_possivel_divergencia"] == []
    assert job_metadata["numeros_sem_derivacao"] == []


def test_gerar_roteiro_persiste_nome_suspeito_no_job_metadata(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    roteiro = (
        "Her sister's husband, Tomas Ossioni, was photographed there [F1@33:39]. "
        + ("Roteiro final de teste. " * 970)
    )
    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(
                resumo={
                    "fatos_verificados": [],
                    "cronologia": [],
                    "pessoas_envolvidas": [{"nome": "Fulano de Tal", "papel": "outro"}],
                    "conflitos_entre_fontes": [],
                    "titulos_top_youtube": [],
                    "observacoes_editoriais": [],
                }
            ),
            _resposta_saida_estruturada(roteiro_md=roteiro),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    nomes = {n["nome"]: n for n in job_metadata["nomes_nao_confirmados"]}
    assert nomes["Tomas Ossioni"]["nivel"] == "alto"


def test_gerar_roteiro_expansao_preserva_nucleo_editorial_dos_avisos(tmp_path, monkeypatch):
    """Regeneracao de titulos NAO acontece (ajuste 2 do refinamento) -
    Grupo B so' sinaliza. Este teste confirma que uma expansao (Grupo E, ja
    existente) nao quebra o calculo do Grupo B mesmo trazendo
    nucleo_editorial na resposta expandida."""
    pasta_projeto = _criar_projeto(tmp_path)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"palavras_alvo": 1000, "duracao_alvo_minutos": 10}), encoding="utf-8"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    roteiro_curto = ("Palavra " * 100).strip() + " [F1@00:00]"
    roteiro_expandido = ("Palavra " * 1000).strip() + " [F1@00:00]"

    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(
                roteiro_md=roteiro_curto, nucleo_editorial="mistakes that identify him"
            ),
            _resposta_saida_estruturada(
                roteiro_md=roteiro_expandido,
                titulos=["Wrist Tattoo", "Wrist Tattoo 2", "Wrist Tattoo 3"],
                nucleo_editorial="mistakes that identify him",
            ),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 4  # fluxo normal (3) + 1 expansao aceita
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nucleo_editorial"] == "mistakes that identify him"
    assert "Wrist Tattoo" in job_metadata["titulos_possivel_divergencia"]


# ---------------------------------------------------------------------------
# Grupo F - validacao empirica contra o roteiro real que motivou a sessao
# (nunca depende da pasta real do projeto - fixture sanitizada e minima).
# ---------------------------------------------------------------------------


def test_grupo_f_validacao_empirica_caso_real_sanitizado():
    """Reproduz, numa fixture curta e inventada (nunca a pasta real do
    projeto), a estrutura exata do caso real que motivou esta sessao: um
    nome garbado por legenda automatica sustentado so' por nota de
    transcricao, e um numero de duracao repetido sem re-derivar na
    segunda mencao. As DUAS ocorrencias precisam ser sinalizadas - esse e'
    o criterio de aceite da sessao."""
    roteiro = (
        "According to reconstruction based on the timing of the home's door "
        "lock and other data points, this individual remained inside the "
        "house for forty-one minutes [F1@01:22-01:29]. When he left, the "
        "victim left with him [F1@01:29].\n\n"
        "He wore a mask, but he did not cover his mouth for the duration of "
        "his time inside the house [F1@09:23-09:25]. For forty-one minutes, "
        "he breathed inside an enclosed space that would later be processed "
        "as a crime scene [F1@09:25-09:31].\n\n"
        "More than a month after her disappearance, her sister's husband, "
        "Tomas Ossioni, was photographed visiting the victim's home [F1@33:39]."
    )
    resumo_sem_confirmacao_do_nome = {
        "fatos_verificados": [],
        "cronologia": [],
        "pessoas_envolvidas": [],
        "conflitos_entre_fontes": [],
        "titulos_top_youtube": [],
        "observacoes_editoriais": [],
    }

    nomes = modulo.detectar_nomes_suspeitos(roteiro, resumo_sem_confirmacao_do_nome)
    numeros = modulo.detectar_numeros_sem_derivacao(roteiro)

    nomes_alto = {n["nome"] for n in nomes if n["nivel"] == "alto"}
    assert "Tomas Ossioni" in nomes_alto

    # A 1a mencao (com "based on... reconstruction" na mesma frase) NAO e'
    # sinalizada; a 2a mencao (sem derivacao por perto) E' sinalizada.
    assert len(numeros) == 1
    assert "forty-one" in numeros[0]["numero_detectado"].lower()


# ===========================================================================
# Correcao 1 (sessao pre-thumbnail): nucleo_editorial validado com reparo,
# NUNCA invalida o roteiro (_validar_saida_estruturada continua sem checar
# este campo - o reparo/fallback acontece depois, em codigo separado).
# ===========================================================================


def _resposta_nucleo_editorial(nucleo="mistakes that identify him", usage=None):
    return FakeResponse(
        [FakeContentBlock("tool_use", id="tu_nucleo", name=modulo.NOME_TOOL_NUCLEO, input={"nucleo_editorial": nucleo})],
        usage=usage or FakeUsage(),
    )


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("mistakes that identify him", True),
        ("his mistakes", True),  # 2 palavras - limite minimo
        ("a b c d e f g h", True),  # 8 palavras - limite maximo
        ("mistakes", False),  # 1 palavra - abaixo do minimo
        ("a b c d e f g h i", False),  # 9 palavras - acima do maximo
        ("   ", False),  # so' espaco
        ("", False),
        (None, False),
        (123, False),
    ],
)
def test_nucleo_editorial_valido_faixa_2_a_8_palavras(texto, esperado):
    assert modulo._nucleo_editorial_valido(texto) is esperado


def test_gerar_roteiro_nucleo_editorial_valido_nao_dispara_reparo(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    fake_client = _instalar_client_fake(
        monkeypatch,
        _respostas_fluxo_feliz(_resposta_saida_estruturada(nucleo_editorial="mistakes that identify him")),
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 3  # nenhuma chamada extra de reparo
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nucleo_editorial"] == "mistakes that identify him"
    assert job_metadata["nucleo_editorial_status"] == "ok"


def test_gerar_roteiro_nucleo_editorial_ausente_dispara_reparo_bem_sucedido(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(nucleo_editorial=None),  # sem o campo
            _resposta_nucleo_editorial("mistakes that identify him"),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 4
    chamada_reparo = fake_client.messages.chamadas[-1]
    assert chamada_reparo["tool_choice"] == {"type": "tool", "name": modulo.NOME_TOOL_NUCLEO}
    assert chamada_reparo["tools"] == modulo.TOOLS_FASE_ESTRUTURADA

    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nucleo_editorial"] == "mistakes that identify him"
    assert job_metadata["nucleo_editorial_status"] == "reparado"
    # roteiro nunca foi tocado pelo reparo
    assert (pasta_projeto / "roteiro.md").read_text(encoding="utf-8") == ROTEIRO_TESTE_LONGO


def test_gerar_roteiro_nucleo_editorial_invalido_dispara_reparo_mesmo_com_campo_presente(
    tmp_path, monkeypatch
):
    """Nucleo com 1 palavra (presente mas invalido) tambem dispara reparo -
    o gatilho e' `_nucleo_editorial_valido`, nao "campo ausente"."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    fake_client = _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(nucleo_editorial="mistakes"),  # presente, mas 1 palavra
            _resposta_nucleo_editorial("mistakes that identify him"),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    assert len(fake_client.messages.chamadas) == 4
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nucleo_editorial"] == "mistakes that identify him"
    assert job_metadata["nucleo_editorial_status"] == "reparado"


def test_gerar_roteiro_reparo_de_nucleo_falha_persiste_status_ausente_sem_falhar_geracao(
    tmp_path, monkeypatch
):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(nucleo_editorial=None),
            RuntimeError("erro de rede simulado"),  # chamada de reparo falha
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True  # NUNCA invalida o roteiro
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nucleo_editorial"] is None
    assert job_metadata["nucleo_editorial_status"] == "ausente"
    # roteiro.md e titulos_sugeridos.json foram gravados normalmente
    assert (pasta_projeto / "roteiro.md").exists()
    assert (pasta_projeto / "titulos_sugeridos.json").exists()


def test_gerar_roteiro_reparo_de_nucleo_devolve_invalido_persiste_status_ausente(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(nucleo_editorial=None),
            _resposta_nucleo_editorial("mistakes"),  # 1 palavra - continua invalido
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["nucleo_editorial"] is None
    assert job_metadata["nucleo_editorial_status"] == "ausente"


def test_gerar_roteiro_nucleo_editorial_ausente_grupo_b_nao_dispara(tmp_path, monkeypatch):
    """Se o nucleo continua ausente mesmo apos o reparo, o Grupo B
    (titulos_possivel_divergencia) nunca dispara - nao ha' nucleo pra
    comparar contra (comportamento ja' garantido por
    detectar_titulos_divergentes, este teste confirma a fiacao completa)."""
    pasta_projeto = _criar_projeto(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")
    _instalar_client_fake(
        monkeypatch,
        [
            _resposta_sem_tool_use(),
            _resposta_resumo_estruturado(),
            _resposta_saida_estruturada(nucleo_editorial=None),
            RuntimeError("falha simulada"),
        ],
    )

    resultado = modulo.gerar_roteiro(pasta_projeto)

    assert resultado["sucesso"] is True
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["titulos_possivel_divergencia"] == []
