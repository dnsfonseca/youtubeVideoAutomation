"""Testes da funcionalidade de marca d'agua por link no formulario de Novo
projeto (CLAUDE.md secao 5.7.1):

- POST /novo com arrays links[]/marcas_dagua[] cria entrada/links.txt e
  entrada/marcas_dagua.json corretos (mapa fonteNN -> posicao, mesma
  numeracao sequencial que scripts/1_baixar_videos.py usa para nomear
  fontes/fonteNN.mp4).
- Arrays de tamanho diferente (links[] vs marcas_dagua[]) retornam erro
  sem crashar.
- Posicao de marca d'agua invalida retorna erro (protecao contra
  manipulacao de request - o <select> real so oferece opcoes validas).
- Validacao de formato de URL do YouTube.
- Retrocompatibilidade com o campo unico "links" (textarea antiga).

O subprocess da Etapa 1 e' sempre mockado (nunca chama yt-dlp de verdade -
CLAUDE.md secao 8).
"""

import json

import server
from scripts.validators import validar_marca_dagua, validar_url_youtube


def _popen_fake(linhas=None, returncode=0):
    linhas = linhas or []

    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        return _ProcessoFake()

    return _fake


# ---------------------------------------------------------------------------
# scripts/validators.py - unidades
# ---------------------------------------------------------------------------


def test_validar_marca_dagua_aceita_todas_as_posicoes_da_secao_5_7_1():
    for posicao in (
        "nenhuma",
        "superior_direito",
        "superior_esquerdo",
        "inferior_direito",
        "inferior_esquerdo",
        "banner_inferior",
    ):
        assert validar_marca_dagua(posicao) is True


def test_validar_marca_dagua_rejeita_posicao_invalida():
    assert validar_marca_dagua("centro_absoluto") is False
    assert validar_marca_dagua("") is False


def test_validar_url_youtube_aceita_formatos_comuns():
    assert validar_url_youtube("https://www.youtube.com/watch?v=abc123") is True
    assert validar_url_youtube("https://youtube.com/watch?v=abc123") is True
    assert validar_url_youtube("https://m.youtube.com/watch?v=abc123") is True
    assert validar_url_youtube("https://youtu.be/abc123") is True
    assert validar_url_youtube("http://youtube.com/watch?v=abc123") is True


def test_validar_url_youtube_rejeita_dominio_nao_youtube():
    assert validar_url_youtube("https://vimeo.com/12345") is False
    assert validar_url_youtube("https://example.com/watch?v=abc") is False
    assert validar_url_youtube("nao e uma url") is False


# ---------------------------------------------------------------------------
# POST /novo - caminho feliz com links[]/marcas_dagua[]
# ---------------------------------------------------------------------------


def test_post_novo_com_links_e_marcas_dagua_cria_marcas_dagua_json(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "perfil": "truecrime",
            "links[]": [
                "https://youtube.com/watch?v=abc",
                "https://youtube.com/watch?v=def",
                "https://youtube.com/watch?v=ghi",
            ],
            "marcas_dagua[]": ["superior_direito", "nenhuma", "banner_inferior"],
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_teste"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_teste"
    links_gravados = (pasta_projeto / "entrada" / "links.txt").read_text(encoding="utf-8")
    assert "https://youtube.com/watch?v=abc" in links_gravados
    assert "https://youtube.com/watch?v=def" in links_gravados
    assert "https://youtube.com/watch?v=ghi" in links_gravados

    marcas_dagua = json.loads(
        (pasta_projeto / "entrada" / "marcas_dagua.json").read_text(encoding="utf-8")
    )
    assert marcas_dagua == {
        "fonte01": "superior_direito",
        "fonte02": "nenhuma",
        "fonte03": "banner_inferior",
    }


def test_post_novo_sem_marcas_dagua_informadas_grava_nenhuma_para_todos(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sem_marcas",
            "perfil": "truecrime",
            "links[]": ["https://youtube.com/watch?v=abc"],
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_sem_marcas"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_sem_marcas"
    marcas_dagua = json.loads(
        (pasta_projeto / "entrada" / "marcas_dagua.json").read_text(encoding="utf-8")
    )
    assert marcas_dagua == {"fonte01": "nenhuma"}


def test_post_novo_links_com_linha_vazia_no_meio_nao_desalinha_marcas(
    client, tmp_path, monkeypatch
):
    """Uma linha em branco entre duas linhas preenchidas (usuario adicionou
    uma linha e nao preencheu) e' descartada, e a marca correspondente
    tambem - fonte02 tem que continuar sendo o segundo link REAL, nao o
    terceiro."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_linha_vazia",
            "perfil": "truecrime",
            "links[]": ["https://youtube.com/watch?v=abc", "", "https://youtube.com/watch?v=def"],
            "marcas_dagua[]": ["superior_direito", "nenhuma", "banner_inferior"],
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_linha_vazia"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_linha_vazia"
    marcas_dagua = json.loads(
        (pasta_projeto / "entrada" / "marcas_dagua.json").read_text(encoding="utf-8")
    )
    assert marcas_dagua == {"fonte01": "superior_direito", "fonte02": "banner_inferior"}


# ---------------------------------------------------------------------------
# POST /novo - retrocompatibilidade com o campo unico "links" (textarea antiga)
# ---------------------------------------------------------------------------


def test_post_novo_com_campo_links_antigo_ainda_funciona_e_marca_nenhuma(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_formato_antigo",
            "perfil": "truecrime",
            "links": "https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def",
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_formato_antigo"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_formato_antigo"
    marcas_dagua = json.loads(
        (pasta_projeto / "entrada" / "marcas_dagua.json").read_text(encoding="utf-8")
    )
    assert marcas_dagua == {"fonte01": "nenhuma", "fonte02": "nenhuma"}


# ---------------------------------------------------------------------------
# POST /novo - erros
# ---------------------------------------------------------------------------


def test_post_novo_com_arrays_de_tamanho_diferente_retorna_erro(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_desalinhado",
            "perfil": "truecrime",
            "links[]": ["https://youtube.com/watch?v=abc", "https://youtube.com/watch?v=def"],
            "marcas_dagua[]": ["nenhuma"],
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 400
    assert "banner-erro-formulario" in pagina
    assert "caso_desalinhado" not in server.jobs


def test_post_novo_com_posicao_de_marca_dagua_invalida_retorna_erro(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_marca_invalida",
            "perfil": "truecrime",
            "links[]": ["https://youtube.com/watch?v=abc"],
            "marcas_dagua[]": ["centro_absoluto"],
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 400
    assert "banner-erro-formulario" in pagina
    assert "caso_marca_invalida" not in server.jobs


def test_post_novo_com_url_nao_youtube_retorna_erro_amigavel(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_url_invalida",
            "perfil": "truecrime",
            "links[]": ["https://vimeo.com/12345"],
            "marcas_dagua[]": ["nenhuma"],
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "youtube" in pagina.lower()
    assert "caso_url_invalida" not in server.jobs


def test_post_novo_com_erro_repopula_linhas_de_link_no_formulario(
    client, tmp_path, monkeypatch
):
    """Regressao: em caso de erro de validacao (ex: nome invalido), o
    formulario tem que continuar mostrando os links/marcas ja preenchidos
    pelo usuario, nao voltar vazio."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "nome invalido!",
            "perfil": "truecrime",
            "links[]": ["https://youtube.com/watch?v=abc"],
            "marcas_dagua[]": ["superior_direito"],
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert "https://youtube.com/watch?v=abc" in pagina
    assert 'value="superior_direito" selected' in pagina


# ---------------------------------------------------------------------------
# GET /novo - template renderiza a area dinamica
# ---------------------------------------------------------------------------


def test_get_novo_renderiza_area_dinamica_de_links_e_dropdown_marca_dagua(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'id="lista-links"' in pagina
    assert 'name="links[]"' in pagina
    assert 'name="marcas_dagua[]"' in pagina
    assert 'id="btn-adicionar-link"' in pagina
    assert "superior_direito" in pagina
    assert "banner_inferior" in pagina


def test_get_novo_mostra_aviso_sobre_marcas_centrais_grandes(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert "Getty" in pagina or "getty" in pagina.lower()
    assert "aviso-marca-dagua" in pagina
