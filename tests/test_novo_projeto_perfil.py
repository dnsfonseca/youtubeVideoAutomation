"""Testes da integracao do sistema de perfis (CLAUDE.md secao 3.1) no
formulario de Novo projeto:

- GET /novo lista os perfis disponiveis (lidos de
  scripts/prompts/perfis/ via scripts/prompts/loader.py:listar_perfis())
  no dropdown "Tipo de conteudo".
- POST /novo exige o campo perfil, valida que ele corresponde a um
  perfil real (protecao contra manipulacao de request), e grava
  entrada/perfil.txt na pasta do projeto quando tudo esta ok.

O subprocess da Etapa 1 e' sempre mockado (nunca chama yt-dlp de
verdade - CLAUDE.md secao 8), igual test_novo_e_status.py.
"""

import server


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
# GET /novo - dropdown de perfis
# ---------------------------------------------------------------------------


def test_get_novo_lista_os_3_perfis_disponiveis(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'name="perfil"' in pagina
    assert 'value="truecrime"' in pagina
    assert 'value="atualidades_narrativas"' in pagina
    assert 'value="historia"' in pagina
    assert "True Crime" in pagina


def test_get_novo_dropdown_perfil_tem_opcao_vazia_inicial(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert "Selecione o tipo de conteudo" in pagina


# ---------------------------------------------------------------------------
# POST /novo - validacao do campo perfil
# ---------------------------------------------------------------------------


def test_post_novo_sem_perfil_mostra_erro_de_validacao(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc"},
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "tipo de conteudo" in pagina.lower()
    assert "caso_teste" not in server.jobs


def test_post_novo_com_perfil_inexistente_retorna_400_sem_crashar(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "perfil_que_nao_existe",
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 400
    assert "banner-erro-formulario" in pagina
    assert "caso_teste" not in server.jobs


def test_post_novo_com_perfil_valido_cria_entrada_perfil_txt(
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
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_teste"
    conteudo_perfil = (pasta_projeto / "entrada" / "perfil.txt").read_text(encoding="utf-8")
    assert conteudo_perfil == "truecrime"

    server._threads["caso_teste"].join(timeout=2)


def test_post_novo_com_perfil_valido_grava_perfil_no_job_json(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "historia",
        },
    )
    server._threads["caso_teste"].join(timeout=2)

    import json

    pasta_projeto = projetos_dir / "caso_teste"
    job_json = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_json["perfil"] == "historia"
