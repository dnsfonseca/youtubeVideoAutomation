"""Testes da integracao da Etapa 1 (download) no server.py:

- POST /novo cria a pasta do projeto (entrada/links.txt + job.json) e
  dispara scripts/1_baixar_videos.py como subprocess numa thread de fundo,
  redirecionando para /status/<id>.
- GET /api/status/<id> devolve o estado atual do job em memoria (polling
  usado pela tela de status - ver static/status.js).

scripts/1_baixar_videos.py em si ja tem suite propria (test_baixar_videos.py)
- aqui o subprocess e' sempre mockado (nunca chama yt-dlp de verdade, CLAUDE.md
  secao 8).
"""

import json
from pathlib import Path

import server


def _popen_fake(linhas, returncode=0, comandos_chamados=None):
    """Fabrica uma funcao para substituir server.subprocess.Popen, que
    devolve um processo fake cujo stdout emite `linhas` e cujo returncode e'
    `returncode`. Se `comandos_chamados` for passado, cada comando recebido
    e' registrado nele para inspecao pelo teste."""

    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        if comandos_chamados is not None:
            comandos_chamados.append(comando)
        return _ProcessoFake()

    return _fake


# ---------------------------------------------------------------------------
# POST /novo - validacao de entrada
# ---------------------------------------------------------------------------


def test_post_novo_sem_projetos_dir_configurado_mostra_erro(client, monkeypatch):
    # A fixture autouse `_limpar_env_das_variaveis_de_ajustes` ja garante que
    # PROJETOS_DIR nao esta setado no os.environ neste teste.
    resposta = client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "PROJETOS_DIR" in pagina
    assert "caso_teste" not in server.jobs


def test_post_novo_com_nome_invalido_mostra_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={"nome": "caso com espaço", "links": "https://youtube.com/watch?v=abc"},
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Problema 3 da Sessao 3.1: o banner de erro deixou de usar
    # `class="aviso erro"` (essa classe segue existindo so na tela de
    # ajustes, que nao foi alterada) e passou a ser um bloco dedicado com
    # icone.
    assert "banner-erro-formulario" in pagina
    assert "banner-erro-icone" in pagina


def test_post_novo_sem_links_mostra_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo", data={"nome": "caso_teste", "links": "   \n  ", "perfil": "truecrime"}
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "link" in pagina.lower()


def test_post_novo_com_projeto_ja_existente_mostra_erro(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    (projetos_dir / "caso_teste").mkdir(parents=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "ja existe" in pagina.lower() or "já existe" in pagina.lower()


def test_post_novo_marcar_gerar_thumbnail_sem_chave_openai_e_bloqueado(client, tmp_path, monkeypatch):
    """Sessao de simplificacao da Etapa 7 (CLAUDE.md secao 5.85): a
    geracao de thumbnail so' produz imagem de verdade via composicao pela
    OpenAI - sem OPENAI_API_KEY nunca haveria como gerar nada, entao a
    marcacao do checkbox e' bloqueada na validacao do formulario."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_thumb_sem_chave",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "gerar_thumbnail": "on",
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "OpenAI" in pagina
    assert not (tmp_path / "projetos" / "caso_thumb_sem_chave").exists()


def test_post_novo_marcar_gerar_thumbnail_com_chave_openai_e_aceito(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_thumb_com_chave",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "gerar_thumbnail": "on",
        },
    )

    assert resposta.status_code == 302
    configuracao = json.loads(
        (projetos_dir / "caso_thumb_com_chave" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert configuracao["gerar_thumbnail"] is True
    server._threads["caso_thumb_com_chave"].join(timeout=2)


def test_post_novo_sem_marcar_gerar_thumbnail_nunca_exige_chave_openai(client, tmp_path, monkeypatch):
    """Projeto sem a flag marcada nunca precisa de OPENAI_API_KEY - a
    checagem so' se aplica quando o usuario de fato pede a thumbnail."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    resposta = client.post(
        "/novo",
        data={"nome": "caso_sem_thumb", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )

    assert resposta.status_code == 302
    server._threads["caso_sem_thumb"].join(timeout=2)


def test_get_novo_sem_erro_nao_renderiza_banner_de_erro(client):
    """Teste novo: o formulario "limpo" (GET, sem nenhuma tentativa de POST
    ainda) nao pode mostrar o banner de erro — `erro` e' None nesse
    caminho, e o bloco `{% if erro %}` do template nao deve renderizar
    nada."""
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" not in pagina


def test_post_novo_com_erro_mantem_nome_e_links_preenchidos(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={"nome": "nome invalido!", "links": "https://youtube.com/watch?v=abc"},
    )
    pagina = resposta.get_data(as_text=True)

    assert "https://youtube.com/watch?v=abc" in pagina


# ---------------------------------------------------------------------------
# POST /novo - caminho feliz (subprocess mockado)
# ---------------------------------------------------------------------------


def test_post_novo_cria_pasta_do_projeto_e_redireciona(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def",
            "idioma": "pt-BR",
            "estrategia_corte": "aleatoria",
            "perfil": "truecrime",
        },
    )

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/status/caso_teste")

    pasta_projeto = projetos_dir / "caso_teste"
    links_gravados = (pasta_projeto / "entrada" / "links.txt").read_text(encoding="utf-8")
    assert "https://youtube.com/watch?v=abc" in links_gravados
    assert "https://youtube.com/watch?v=def" in links_gravados

    job_json = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_json["nome"] == "caso_teste"
    assert job_json["idioma"] == "pt-BR"
    assert job_json["estrategia_corte"] == "aleatoria"
    assert job_json["etapa_atual"] == "download"

    server._threads["caso_teste"].join(timeout=2)


def test_post_novo_dispara_subprocess_com_pasta_do_projeto_como_argumento(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    comandos_chamados = []
    monkeypatch.setattr(
        server.subprocess, "Popen", _popen_fake([], comandos_chamados=comandos_chamados)
    )
    # Isola este teste do auto-encadeamento para a Etapa 2 (CLAUDE.md secao
    # 4) - o foco aqui e' so o disparo do subprocess da Etapa 1; o
    # encadeamento em si tem cobertura propria mais abaixo.
    monkeypatch.setattr(server, "_encadear_etapa2", lambda *a, **k: None)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    assert len(comandos_chamados) == 1
    comando = comandos_chamados[0]
    assert str(projetos_dir / "caso_teste") in comando
    assert "1_baixar_videos.py" in " ".join(comando)


def test_etapa1_atualiza_job_com_progresso_emitido_pelo_script(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    linhas = [
        '@PROGRESSO {"pct": 0.0, "detalhe": "Processando 1/2: https://x"}\n',
        '@PROGRESSO {"pct": 50.0, "detalhe": "Baixando video 1/2", "eta_s": 30}\n',
        '@PROGRESSO {"pct": 100.0, "detalhe": "2 video(s) baixado(s) com sucesso", "sucesso": true}\n',
    ]
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(linhas, returncode=0))
    # Isola este teste do auto-encadeamento (ver comentario acima) - sem
    # isso, a Etapa 2 reseta `job` (novo pct/detalhe/log) assim que a
    # Etapa 1 termina, e as asserções abaixo (que sao sobre o estado FINAL
    # da Etapa 1) deixariam de fazer sentido.
    monkeypatch.setattr(server, "_encadear_etapa2", lambda *a, **k: None)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["status"] == "concluido"
    assert job["pct"] == 100.0
    assert job["detalhe"] == "2 video(s) baixado(s) com sucesso"
    assert job["proxima_etapa"] == "transcricao"
    assert any("Baixando video 1/2" in linha for linha in job["log"])


def test_etapa1_com_falha_no_subprocess_marca_job_como_erro(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    linhas = [
        '@PROGRESSO {"pct": 100.0, "detalhe": "ERRO: nenhum video baixado", "sucesso": false, "erros": ["falha 1"]}\n',
    ]
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(linhas, returncode=1))

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["status"] == "erro"
    assert job["erro"]
    assert job["erros"] == ["falha 1"]
    assert job["proxima_etapa"] is None


def test_etapa1_com_mensagem_usuario_amigavel_vence_detalhe_tecnico_no_job_erro(
    client, tmp_path, monkeypatch
):
    """Teste novo (Problema 4 da Sessao 3.1): quando o @PROGRESSO final
    trouxer `mensagem_usuario` (a mensagem amigavel classificada por
    scripts/1_baixar_videos.py:classificar_erro_ytdlp), o job["erro"] tem
    que usar ela, e nao o `detalhe` tecnico generico ("ERRO: nenhum video
    baixado")."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    linhas = [
        '@PROGRESSO {"pct": 100.0, "detalhe": "ERRO: nenhum video baixado", '
        '"sucesso": false, "erros": ["yt-dlp saiu com codigo 1"], '
        '"mensagem_usuario": "Este video foi removido pelo autor ou esta indisponivel."}\n',
    ]
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(linhas, returncode=1))

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    assert (
        server.jobs["caso_teste"]["erro"]
        == "Este video foi removido pelo autor ou esta indisponivel."
    )


def test_etapa1_com_falha_ao_iniciar_subprocess_marca_job_como_erro(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _popen_que_falha(*args, **kwargs):
        raise OSError("nao foi possivel iniciar o processo")

    monkeypatch.setattr(server.subprocess, "Popen", _popen_que_falha)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["status"] == "erro"
    assert "nao foi possivel iniciar o processo" in job["erro"]


# ---------------------------------------------------------------------------
# Encadeamento automatico: Etapa 1 (download) -> Etapa 2 (transcricao)
# (CLAUDE.md secao 4 - fluxo continuo sem intervencao do usuario)
# ---------------------------------------------------------------------------


def test_etapa1_com_sucesso_dispara_etapa2_automaticamente(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) baixado(s) com sucesso", "sucesso": true}\n']
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa2", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    assert chamadas == [("caso_teste", projetos_dir / "caso_teste")]


def test_etapa1_com_erro_nao_dispara_etapa2(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "ERRO: nenhum video baixado", "sucesso": false}\n'],
            returncode=1,
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa2", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    assert chamadas == []
    assert server.jobs["caso_teste"]["status"] == "erro"


def test_fluxo_completo_download_e_transcricao_automatico_ate_concluido(
    client, tmp_path, monkeypatch
):
    """Integracao ponta-a-ponta do encadeamento: dois subprocess mockados
    em sequencia (1_baixar_videos.py e 2_transcrever.py), diferenciados
    pelo comando recebido - o job final reflete o resultado da Etapa 2
    (ultima etapa do encadeamento), nao mais da Etapa 1."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _popen_por_etapa(comando, **kwargs):
        script = " ".join(comando)

        class _ProcessoFake:
            def __init__(self, linhas, returncode):
                self.stdout = iter(linhas)
                self.returncode = returncode

            def wait(self):
                return None

        if "1_baixar_videos.py" in script:
            return _ProcessoFake(
                ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) baixado(s) com sucesso", "sucesso": true}\n'],
                0,
            )
        return _ProcessoFake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) transcrito(s) com sucesso", "sucesso": true}\n'],
            0,
        )

    monkeypatch.setattr(server.subprocess, "Popen", _popen_por_etapa)
    # Isola este teste do auto-encadeamento para a Etapa 3 (CLAUDE.md secao
    # 4/5.3) - o foco aqui e' so o encadeamento etapa1 -> etapa2; o
    # encadeamento etapa2 -> etapa3 tem cobertura propria em
    # test_gerar_roteiro_integracao.py.
    monkeypatch.setattr(server, "_encadear_etapa3", lambda *a, **k: None)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["etapa"] == "transcricao"
    assert job["status"] == "concluido"
    assert job["detalhe"] == "1 video(s) transcrito(s) com sucesso"

    job_json = json.loads((projetos_dir / "caso_teste" / "job.json").read_text(encoding="utf-8"))
    assert job_json["etapa_atual"] == "transcricao"
    assert job_json["status"] == "concluido"


def test_fluxo_completo_download_ok_mas_transcricao_falha_marca_erro_na_etapa_transcricao(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _popen_por_etapa(comando, **kwargs):
        script = " ".join(comando)

        class _ProcessoFake:
            def __init__(self, linhas, returncode):
                self.stdout = iter(linhas)
                self.returncode = returncode

            def wait(self):
                return None

        if "1_baixar_videos.py" in script:
            return _ProcessoFake(
                ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) baixado(s) com sucesso", "sucesso": true}\n'],
                0,
            )
        return _ProcessoFake(
            [
                '@PROGRESSO {"pct": 0.0, "detalhe": "ERRO: GPU NVIDIA nao detectada.", '
                '"sucesso": false, "tipo_erro": "gpu_indisponivel", '
                '"mensagem_usuario": "GPU NVIDIA nao detectada. Verifique drivers."}\n'
            ],
            1,
        )

    monkeypatch.setattr(server.subprocess, "Popen", _popen_por_etapa)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["etapa"] == "transcricao"
    assert job["status"] == "erro"
    assert job["erro"] == "GPU NVIDIA nao detectada. Verifique drivers."

    job_json = json.loads((projetos_dir / "caso_teste" / "job.json").read_text(encoding="utf-8"))
    assert job_json["etapa_atual"] == "transcricao"
    assert job_json["status"] == "erro"
    assert job_json["tipo_erro"] == "gpu_indisponivel"


# ---------------------------------------------------------------------------
# POST /projetos/<id>/transcrever - disparo manual da Etapa 2
# ---------------------------------------------------------------------------


def test_post_transcrever_com_ambiente_incompativel_retorna_400(criar_app, tmp_path, monkeypatch):
    monkeypatch.setattr(
        server.ambiente,
        "detectar_gpu",
        lambda: {
            "presente": False,
            "modelo": None,
            "vram_mb": None,
            "driver_version": None,
            "compute_capability": None,
            "cuda_umd_version": None,
            "erro": "nvidia-smi nao encontrado.",
        },
    )
    app = criar_app(PROJETOS_DIR=str(tmp_path / "projetos"))
    client = app.test_client()

    resposta = client.post("/projetos/caso_teste/transcrever")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "ambiente_incompativel"


def test_post_transcrever_sem_etapa1_concluida_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_sem_download/transcrever")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "etapa1_nao_concluida"


def test_post_transcrever_fluxo_feliz_dispara_etapa2(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    (pasta_projeto / "fontes").mkdir(parents=True)
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps({"fontes": [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))
    # Isola este teste do auto-encadeamento para a Etapa 3 (CLAUDE.md secao
    # 4/5.3) - o foco aqui e' so o disparo manual da Etapa 2.
    monkeypatch.setattr(server, "_encadear_etapa3", lambda *a, **k: None)

    resposta = client.post("/projetos/caso_teste/transcrever")

    assert resposta.status_code == 202
    server._threads["caso_teste"].join(timeout=2)
    assert server.jobs["caso_teste"]["etapa"] == "transcricao"


def test_post_transcrever_com_sucesso_apos_falha_anterior_limpa_erro_obsoleto_do_job_json(
    client, tmp_path, monkeypatch
):
    """Regressao descoberta rodando o pipeline real de ponta a ponta
    (Sessao 4): se uma tentativa anterior de transcricao falhou (gravou
    tipo_erro/mensagem_usuario/log_erro no job.json) e o usuario tenta de
    novo com sucesso (POST /projetos/<id>/transcrever), o job.json final
    nao pode continuar mostrando o erro obsoleto ao lado de
    status=concluido - _persistir_job faz merge por cima do que ja existe
    em disco, entao os campos de erro tem que ser explicitamente
    zerados no sucesso."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    (pasta_projeto / "fontes").mkdir(parents=True)
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps({"fontes": [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]}),
        encoding="utf-8",
    )
    (pasta_projeto / "job.json").write_text(
        json.dumps(
            {
                "status": "erro",
                "etapa_atual": "transcricao",
                "tipo_erro": "gpu_indisponivel",
                "mensagem_usuario": "GPU NVIDIA nao detectada. Verifique drivers.",
                "log_erro": "algum log tecnico da tentativa anterior",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) transcrito(s) com sucesso", "sucesso": true}\n']
        ),
    )
    # Isola este teste do auto-encadeamento para a Etapa 3 (CLAUDE.md secao
    # 4/5.3) - o foco aqui e' so a limpeza de erro obsoleto no job.json da
    # Etapa 2.
    monkeypatch.setattr(server, "_encadear_etapa3", lambda *a, **k: None)

    client.post("/projetos/caso_teste/transcrever")
    server._threads["caso_teste"].join(timeout=2)

    job_json = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_json["status"] == "concluido"
    assert job_json["tipo_erro"] is None
    assert job_json["mensagem_usuario"] is None
    assert job_json["log_erro"] is None


# ---------------------------------------------------------------------------
# GET /api/status/<id>
# ---------------------------------------------------------------------------


def test_api_status_retorna_job_em_andamento(client):
    server.jobs["caso_em_andamento"] = {
        "etapa": "download",
        "status": "em_andamento",
        "pct": 42.0,
        "detalhe": "Baixando video 1/2",
        "eta_s": 30,
        "log": ["Baixando video 1/2"],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/api/status/caso_em_andamento")
    corpo = resposta.get_json()

    assert resposta.status_code == 200
    assert corpo["status"] == "em_andamento"
    assert corpo["pct"] == 42.0
    assert corpo["detalhe"] == "Baixando video 1/2"


def test_api_status_de_projeto_desconhecido_retorna_404(client):
    resposta = client.get("/api/status/projeto_que_nao_existe")
    corpo = resposta.get_json()

    assert resposta.status_code == 404
    assert corpo["status"] == "nao_encontrado"


def test_api_status_apos_etapa1_concluida_reflete_sucesso(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) baixado(s) com sucesso", "sucesso": true}\n']
        ),
    )
    monkeypatch.setattr(server, "_encadear_etapa2", lambda *a, **k: None)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    resposta = client.get("/api/status/caso_teste")
    corpo = resposta.get_json()

    assert corpo["status"] == "concluido"
    assert corpo["proxima_etapa"] == "transcricao"


# ---------------------------------------------------------------------------
# GET /api/status/<id> - pipeline_steps/arquivos_baixados/artefatos no
# polling (correcao pos-Sessao 18: esses 3 blocos so eram calculados no
# render inicial de /status/<id>, nunca no JSON de polling que
# static/status.js consulta a cada 2s - a tela "congelava" nesses blocos).
# ---------------------------------------------------------------------------


def test_api_status_retorna_pipeline_steps(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_projeto_no_disco(
        projetos_dir,
        "caso_pipeline",
        job_json={"projeto_id": "caso_pipeline", "status": "em_andamento", "etapa_atual": "transcricao"},
    )
    server.jobs["caso_pipeline"] = {
        "etapa": "transcricao",
        "status": "em_andamento",
        "pct": 30.0,
        "detalhe": "Transcrevendo 1/1",
        "log": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/api/status/caso_pipeline")
    corpo = resposta.get_json()

    assert "pipeline_steps" in corpo
    nomes = [passo["nome"] for passo in corpo["pipeline_steps"]]
    assert "download" in nomes and "transcricao" in nomes
    passo_transcricao = next(p for p in corpo["pipeline_steps"] if p["nome"] == "transcricao")
    assert passo_transcricao["estado"] == "running"


def test_api_status_retorna_arquivos_baixados_com_origem(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_projeto_no_disco(
        projetos_dir,
        "caso_arquivos",
        job_json={"projeto_id": "caso_arquivos", "status": "em_andamento", "etapa_atual": "transcricao"},
        manifest_fontes={
            "fontes": [
                {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 60, "sucesso": True, "origem": "youtube"},
                {"id": "fonte02", "arquivo": "fonte02.mp4", "duracao_s": 30, "sucesso": True, "origem": "upload"},
            ],
            "sucesso": True,
        },
    )
    server.jobs["caso_arquivos"] = {
        "etapa": "transcricao",
        "status": "em_andamento",
        "pct": 10.0,
        "detalhe": "",
        "log": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/api/status/caso_arquivos")
    corpo = resposta.get_json()

    assert len(corpo["arquivos_baixados"]) == 2
    origens = {f["arquivo"]: f["origem"] for f in corpo["arquivos_baixados"]}
    assert origens["fonte01.mp4"] == "youtube"
    assert origens["fonte02.mp4"] == "upload"


def test_api_status_arquivo_sem_origem_no_manifest_assume_youtube(client, tmp_path, monkeypatch):
    """Manifests gravados antes da Sessao 18 (fontes separadas) nao tem a
    chave "origem" - retrocompatibilidade: assume "youtube" (unico jeito de
    baixar fonte antes dessa feature existir)."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_projeto_no_disco(
        projetos_dir,
        "caso_manifest_antigo",
        job_json={"projeto_id": "caso_manifest_antigo", "status": "em_andamento", "etapa_atual": "transcricao"},
        manifest_fontes={
            "fontes": [{"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 60, "sucesso": True}],
            "sucesso": True,
        },
    )
    server.jobs["caso_manifest_antigo"] = {
        "etapa": "transcricao",
        "status": "em_andamento",
        "pct": 10.0,
        "detalhe": "",
        "log": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/api/status/caso_manifest_antigo")
    corpo = resposta.get_json()

    assert corpo["arquivos_baixados"][0]["origem"] == "youtube"


def test_api_status_retorna_artefatos(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta = _criar_projeto_no_disco(
        projetos_dir,
        "caso_artefatos",
        job_json={"projeto_id": "caso_artefatos", "status": "em_andamento", "etapa_atual": "montagem"},
    )
    (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")
    server.jobs["caso_artefatos"] = {
        "etapa": "montagem",
        "status": "em_andamento",
        "pct": 50.0,
        "detalhe": "",
        "log": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/api/status/caso_artefatos")
    corpo = resposta.get_json()

    nomes_artefatos = [a["nome"] for a in corpo["artefatos"]]
    assert "roteiro_aprovado.md" in nomes_artefatos


# ---------------------------------------------------------------------------
# GET /status/<id> - pagina renderizada
# ---------------------------------------------------------------------------


def test_status_html_mostra_mensagem_de_proxima_etapa_quando_job_concluido(client):
    server.jobs["caso_concluido"] = {
        "etapa": "download",
        "status": "concluido",
        "pct": 100.0,
        "detalhe": "1 video(s) baixado(s) com sucesso",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": "transcricao",
    }

    resposta = client.get("/status/caso_concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Próxima etapa: Transcrição." in pagina
    assert "oculto" not in pagina.split('id="status-proxima-etapa"')[1].split(">")[0]


def test_status_html_sem_job_nao_mostra_proxima_etapa(client):
    resposta = client.get("/status/projeto_sem_job")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    trecho = pagina.split('id="status-proxima-etapa"')[1].split(">")[0]
    assert "oculto" in trecho


def test_status_aguardando_reorganizacao_nao_menciona_transcricao(client):
    """Bug corrigido na sessao de correcoes UX: o texto de proxima etapa era
    hardcoded no template ("Download completo, proxima etapa:
    transcricao.") e aparecia igual em QUALQUER estado com proxima_etapa
    preenchido - inclusive apos a Etapa 5, onde a proxima etapa real e'
    "montagem" (ou a pausa manual de reorganizacao)."""
    server.jobs["caso_aguardando_reorg"] = {
        "etapa": "geracao_clipes",
        "status": "aguardando_reorganizacao",
        "pct": 100.0,
        "detalhe": "Clipes prontos - aguardando reorganizacao manual.",
        "log": [],
        "erro": None,
        "proxima_etapa": "montagem",
    }

    resposta = client.get("/status/caso_aguardando_reorg")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "transcricao" not in pagina.split('id="status-proxima-etapa"')[1].split("</p>")[0].lower()
    assert "aguardando reorganização manual" in pagina.lower()
    assert "montagem" in pagina.lower()


def test_status_aguardando_legendas_mostra_proxima_etapa_montagem(client):
    server.jobs["caso_aguardando_legendas"] = {
        "etapa": "legendas",
        "status": "aguardando_legendas",
        "pct": 100.0,
        "detalhe": "Clipes prontos.",
        "log": [],
        "erro": None,
        "proxima_etapa": "montagem",
    }

    resposta = client.get("/status/caso_aguardando_legendas")
    pagina = resposta.get_data(as_text=True)

    assert "Próxima etapa: Montagem." in pagina


# ---------------------------------------------------------------------------
# status.html - aguardando_thumbnail: bug corrigido pos-Sessao 23 - esse
# status nao tinha bloco nenhum na tela (ficava so com "Preparando
# candidatos..." estatico, sem botao/link). Dois blocos mutuamente
# exclusivos por estado.etapa7_falhou (server.py:_montar_estado_status).
# ---------------------------------------------------------------------------


def test_status_aguardando_thumbnail_sucesso_mostra_link_revisar(client):
    server.jobs["caso_thumb_ok"] = {
        "etapa": "thumbnail",
        "status": "aguardando_thumbnail",
        "pct": 100.0,
        "detalhe": "Concluido: candidatos de thumbnail gerados",
        "log": [],
        "erro": None,
        "proxima_etapa": None,
        "etapa7_falhou": False,
    }

    resposta = client.get("/status/caso_thumb_ok")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    bloco_ok = pagina.split('id="status-aguardando-thumbnail-ok"')[1].split("</p>")[0]
    assert "oculto" not in bloco_ok
    assert "/projetos/caso_thumb_ok/thumbnail" in bloco_ok
    bloco_falhou = pagina.split('id="status-aguardando-thumbnail-falhou"')[1].split(">", 1)[0]
    assert "oculto" in bloco_falhou


def test_status_aguardando_thumbnail_falha_mostra_botao_tentar_novamente(client):
    server.jobs["caso_thumb_falhou"] = {
        "etapa": "thumbnail",
        "status": "aguardando_thumbnail",
        "pct": 100.0,
        "detalhe": "A preparacao automatica da thumbnail falhou. Revise manualmente ou tente novamente.",
        "log": ["ModuleNotFoundError: No module named 'scripts'"],
        "erro": "scripts/7_thumbnail.py terminou com codigo 1.",
        "mensagem_usuario": "scripts/7_thumbnail.py terminou com codigo 1.",
        "proxima_etapa": None,
        "etapa7_falhou": True,
    }

    resposta = client.get("/status/caso_thumb_falhou")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    bloco_falhou = pagina.split('id="status-aguardando-thumbnail-falhou"')[1]
    assert "oculto" not in bloco_falhou.split(">", 1)[0]
    assert "scripts/7_thumbnail.py terminou com codigo 1." in bloco_falhou
    assert "Tentar novamente" in bloco_falhou
    assert "/projetos/caso_thumb_falhou/gerar_thumbnail" in bloco_falhou
    assert "/projetos/caso_thumb_falhou/thumbnail" in bloco_falhou
    bloco_ok = pagina.split('id="status-aguardando-thumbnail-ok"')[1].split("</p>")[0]
    assert "oculto" in bloco_ok


def test_montar_estado_status_etapa7_falhou_vem_do_job_em_memoria():
    estado = server._montar_estado_status({"status": "aguardando_thumbnail", "etapa7_falhou": True}, None)
    assert estado["etapa7_falhou"] is True


def test_montar_estado_status_etapa7_falhou_default_false_quando_ausente():
    estado = server._montar_estado_status({"status": "aguardando_thumbnail"}, None)
    assert estado["etapa7_falhou"] is False


def test_montar_estado_status_etapa7_falhou_vem_do_disco_sem_job_em_memoria():
    estado = server._montar_estado_status(None, {"status": "aguardando_thumbnail", "etapa7_falhou": True})
    assert estado["etapa7_falhou"] is True


def test_mensagem_proxima_etapa_none_quando_sem_proxima_etapa():
    assert server._mensagem_proxima_etapa("concluido", None) is None


def test_mensagem_proxima_etapa_usa_rotulo_amigavel():
    assert server._mensagem_proxima_etapa("concluido", "geracao_clipes") == "Próxima etapa: Clipes."


def test_mensagem_proxima_etapa_aguardando_reorganizacao_tem_texto_proprio():
    mensagem = server._mensagem_proxima_etapa("aguardando_reorganizacao", "montagem")
    assert "aguardando reorganização manual" in mensagem.lower()
    assert "Montagem" in mensagem


def test_proxima_etapa_migration_planejamento_vira_geracao_clipes(tmp_path):
    """Bug corrigido nesta sessao: _executar_etapa4 gravava
    proxima_etapa="planejamento" (nome orfao de arquitetura abandonada).
    Projeto com esse valor legado em disco migra em memoria para
    "geracao_clipes" (nome real da etapa hoje), sem reescrever o disco."""
    pasta_projeto = tmp_path / "projeto_legado"
    pasta_projeto.mkdir()
    (pasta_projeto / "job.json").write_text(
        json.dumps({"status": "concluido", "etapa_atual": "audio", "proxima_etapa": "planejamento"}),
        encoding="utf-8",
    )

    job = server._ler_job_json(pasta_projeto)

    assert job["proxima_etapa"] == "geracao_clipes"
    conteudo_disco = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert conteudo_disco["proxima_etapa"] == "planejamento"  # nunca reescreve o disco


def test_status_html_nao_inclui_pipeline_polling_js(client):
    """status.html ja tem polling completo (status.js, a cada 2s) - nao
    deve tambem carregar pipeline_polling.js (Sessao de correcoes UX,
    Grupo A: esse arquivo e' so' pra revisar_roteiro/concluido, que nao
    tinham polling nenhum antes)."""
    resposta = client.get("/status/projeto_sem_job")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "pipeline_polling.js" not in pagina
    assert "pipeline_render.js" in pagina
    assert "status.js" in pagina


def test_status_js_continua_polling_durante_aguardando_legendas():
    """Regressao (Grupo C/G3): "aguardando_legendas" NAO e' uma pausa real
    esperando o usuario (ao contrario de aguardando_revisao/aguardando_audio/
    aguardando_reorganizacao) - server.py grava esse status e, na MESMA
    thread de fundo, segue direto para a Feature A/B (sincronizacao com IA/
    thumbnails) sem nenhuma pausa de verdade. Achado real de producao: com a
    Feature A ativa (chamadas Vision podem levar dezenas de segundos), um
    poll quase sempre pegava esse status no meio do caminho e o polling
    parava pra sempre (statusEmAndamento so' contava em_andamento/pendente),
    deixando a tela congelada ate' o usuario recarregar manualmente."""
    caminho_js = Path(__file__).resolve().parent.parent / "static" / "status.js"
    conteudo = caminho_js.read_text(encoding="utf-8")
    inicio = conteudo.index("function statusEmAndamento")
    fim = conteudo.index("}", inicio)
    corpo = conteudo[inicio:fim]

    assert '"aguardando_legendas"' in corpo
    assert '"em_andamento"' in corpo
    assert '"pendente"' in corpo


# ---------------------------------------------------------------------------
# GET /status/<id> - persistencia em disco (Sessao 4): projeto historico,
# sem job em memoria, le job.json + entrada/links.txt +
# fontes/manifest_fontes.json direto do disco.
# ---------------------------------------------------------------------------


def _criar_projeto_no_disco(
    projetos_dir,
    nome,
    job_json=None,
    links=None,
    manifest_fontes=None,
):
    """Monta a estrutura de pastas de um projeto direto no disco (sem passar
    por POST /novo nem pelo pipeline) - usado para simular projetos
    historicos que a tela de status precisa renderizar so a partir do que
    esta persistido."""
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    if links is not None:
        (pasta / "entrada" / "links.txt").write_text(
            "\n".join(links) + ("\n" if links else ""), encoding="utf-8"
        )
    if job_json is not None:
        (pasta / "job.json").write_text(
            json.dumps(job_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if manifest_fontes is not None:
        (pasta / "fontes").mkdir(parents=True, exist_ok=True)
        (pasta / "fontes" / "manifest_fontes.json").write_text(
            json.dumps(manifest_fontes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return pasta


def test_status_html_projeto_historico_concluido_renderiza_os_4_blocos(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_historico",
        job_json={
            "projeto_id": "caso_historico",
            "nome": "caso_historico",
            "status": "concluido",
            "etapa_atual": "download",
            "proxima_etapa": "transcricao",
            "data_criacao": "2026-08-28T11:39:00",
            "data_inicio_execucao": "2026-08-28T11:39:02",
            "data_fim": "2026-08-28T11:41:15",
            "resumo_fontes": {
                "total_solicitado": 1,
                "total_baixado": 1,
                "total_falhado": 0,
                "duracao_total_s": 299,
            },
        },
        links=["https://www.youtube.com/watch?v=XPyIfmiKt_w"],
        manifest_fontes={
            "fontes": [
                {
                    "id": "fonte01",
                    "arquivo": "fonte01.mp4",
                    "url_original": "https://www.youtube.com/watch?v=XPyIfmiKt_w",
                    "titulo": "Um video qualquer",
                    "duracao_s": 299,
                    "sucesso": True,
                }
            ],
            "sucesso": True,
        },
    )

    resposta = client.get("/status/caso_historico")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Bloco A - cabecalho
    assert "Criado em 28/08/2026" in pagina
    assert "Concluído em 28/08/2026" in pagina
    # Bloco B - estado
    assert "Status: Concluído" in pagina
    # Bloco C - links
    assert "https://www.youtube.com/watch?v=XPyIfmiKt_w" in pagina
    # Bloco D - arquivos
    assert "fonte01.mp4" in pagina
    assert "4min 59s" in pagina


def test_status_html_projeto_historico_com_erro_mostra_banner_e_resumo(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_erro",
        job_json={
            "projeto_id": "caso_erro",
            "nome": "caso_erro",
            "status": "erro",
            "etapa_atual": "download",
            "data_criacao": "2026-08-28T11:46:00",
            "data_fim": "2026-08-28T11:46:30",
            "tipo_erro": "video_removido",
            "mensagem_usuario": "Este video foi removido pelo autor ou esta indisponivel.",
            "resumo_fontes": {
                "total_solicitado": 1,
                "total_baixado": 0,
                "total_falhado": 1,
                "duracao_total_s": 0,
            },
        },
        links=["https://www.youtube.com/watch?v=invalido"],
        manifest_fontes={
            "fontes": [
                {
                    "id": "fonte01",
                    "arquivo": "fonte01.mp4",
                    "url_original": "https://www.youtube.com/watch?v=invalido",
                    "sucesso": False,
                    "tipo_erro": "video_removido",
                }
            ],
            "sucesso": False,
        },
    )

    resposta = client.get("/status/caso_erro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "erro-destaque" in pagina
    assert "Este video foi removido pelo autor ou esta indisponivel." in pagina
    trecho_erro = pagina.split('id="status-erro"')[1].split(">")[0]
    assert "oculto" not in trecho_erro
    # Manifest existe mas a unica fonte falhou (sucesso: false) - mensagem
    # especifica de "todas falharam", distinta de "ainda" (ver secao nova
    # de testes do bloco "Arquivos baixados" mais abaixo).
    assert "Nenhum arquivo baixado com sucesso" in pagina


def test_status_html_job_json_formato_antigo_renderiza_campos_disponiveis(
    client, tmp_path, monkeypatch
):
    """job.json no formato anterior a Sessao 4 (sem data_inicio_execucao,
    resumo_fontes, etapa_atual) nao pode crashar - so mostra os campos que
    tem, e "-"/estado neutro pros que faltam."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_antigo",
        job_json={
            "nome": "caso_antigo",
            "idioma": None,
            "estrategia_corte": None,
            "etapa": "download",
            "status": "pendente",
            "criado_em": "2026-08-28T11:39:36.387133",
        },
        links=["https://www.youtube.com/watch?v=XPyIfmiKt_w"],
    )

    resposta = client.get("/status/caso_antigo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Criado em 28/08/2026" in pagina
    assert "Status: Pendente" in pagina
    assert "Nenhum arquivo baixado ainda." in pagina


def test_status_html_sem_job_json_mostra_aviso_e_nao_crasha(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(projetos_dir, "caso_sem_job_json", job_json=None, links=None)

    resposta = client.get("/status/caso_sem_job_json")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "O estado deste projeto se perdeu" in pagina


def test_status_html_sem_job_json_com_artefatos_oferece_reconstrucao(client, tmp_path, monkeypatch):
    """Item 4 da sessao de correcoes de composicao/interface: job.json
    ausente mas com artefatos reais em disco (roteiro_aprovado.md aqui)
    oferece o botao de reconstrucao de estado, em vez de so' avisar."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(projetos_dir, "caso_sem_job_json_com_artefatos", job_json=None, links=None)
    (projetos_dir / "caso_sem_job_json_com_artefatos" / "roteiro_aprovado.md").write_text(
        "Roteiro aprovado real.", encoding="utf-8"
    )

    resposta = client.get("/status/caso_sem_job_json_com_artefatos")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Reconstruir estado a partir dos artefatos" in pagina
    assert "/projetos/caso_sem_job_json_com_artefatos/reconstruir_estado" in pagina


def test_status_html_links_txt_vazio_mostra_nenhum_link_registrado(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_links_vazio",
        job_json={"nome": "caso_links_vazio", "status": "pendente", "etapa_atual": "download"},
        links=[],
    )

    resposta = client.get("/status/caso_links_vazio")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Nenhum link registrado." in pagina


def test_status_html_sem_manifest_fontes_mostra_nenhum_arquivo_ainda(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_sem_manifest",
        job_json={
            "nome": "caso_sem_manifest",
            "status": "em_andamento",
            "etapa_atual": "download",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    resposta = client.get("/status/caso_sem_manifest")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Nenhum arquivo baixado ainda." in pagina


def test_status_html_job_em_memoria_tem_prioridade_sobre_disco(client, tmp_path, monkeypatch):
    """Enquanto o job esta ativo em memoria, a tela mostra os dados
    dinamicos dele (pct/detalhe ao vivo) em vez do ultimo estado persistido
    em disco (que so seria atualizado na proxima transicao)."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_ativo",
        job_json={
            "nome": "caso_ativo",
            "status": "em_andamento",
            "etapa_atual": "download",
            "data_criacao": "2026-08-28T11:39:00",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    server.jobs["caso_ativo"] = {
        "etapa": "download",
        "status": "em_andamento",
        "pct": 42.0,
        "detalhe": "Baixando video 1/1",
        "eta_s": 30,
        "log": ["Baixando video 1/1"],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/status/caso_ativo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Status: Em andamento" in pagina
    assert "Baixando video 1/1" in pagina


# ---------------------------------------------------------------------------
# _executar_etapa1 - persistencia do job.json nas transicoes de estado
# ---------------------------------------------------------------------------


def test_etapa1_concluida_persiste_job_json_com_resumo_de_fontes(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _popen_que_grava_manifest(comando, **kwargs):
        pasta_projeto = Path(comando[2])
        pasta_fontes = pasta_projeto / "fontes"
        pasta_fontes.mkdir(parents=True, exist_ok=True)
        (pasta_fontes / "manifest_fontes.json").write_text(
            json.dumps(
                {
                    "fontes": [
                        {
                            "id": "fonte01",
                            "arquivo": "fonte01.mp4",
                            "sucesso": True,
                            "duracao_s": 120,
                        }
                    ],
                    "sucesso": True,
                }
            ),
            encoding="utf-8",
        )

        class _ProcessoFake:
            stdout = iter(
                ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) baixado(s) com sucesso", "sucesso": true}\n']
            )
            returncode = 0

            def wait(self):
                return None

        return _ProcessoFake()

    monkeypatch.setattr(server.subprocess, "Popen", _popen_que_grava_manifest)
    monkeypatch.setattr(server, "_encadear_etapa2", lambda *a, **k: None)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job_json = json.loads((projetos_dir / "caso_teste" / "job.json").read_text(encoding="utf-8"))
    assert job_json["status"] == "concluido"
    assert job_json["proxima_etapa"] == "transcricao"
    assert job_json["resumo_fontes"] == {
        "total_solicitado": 1,
        "total_baixado": 1,
        "total_falhado": 0,
        "duracao_total_s": 120,
    }
    assert "data_fim" in job_json
    assert job_json["nome"] == "caso_teste"


def test_etapa1_com_erro_persiste_job_json_com_mensagem_e_tipo_erro(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    linhas = [
        '@PROGRESSO {"pct": 100.0, "detalhe": "ERRO: nenhum video baixado", '
        '"sucesso": false, "erros": ["yt-dlp saiu com codigo 1"], '
        '"mensagem_usuario": "Este video foi removido pelo autor ou esta indisponivel."}\n',
    ]
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(linhas, returncode=1))

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job_json = json.loads((projetos_dir / "caso_teste" / "job.json").read_text(encoding="utf-8"))
    assert job_json["status"] == "erro"
    assert job_json["mensagem_usuario"] == "Este video foi removido pelo autor ou esta indisponivel."
    assert "data_fim" in job_json
    assert job_json["resumo_fontes"]["total_solicitado"] == 1


# ---------------------------------------------------------------------------
# Bloco "Arquivos baixados" (tela de status) - correcao de bug reportado
# em uso real: o bloco mostrava "Nenhum arquivo baixado ainda" mesmo com
# fontes/manifest_fontes.json existindo em disco com fontes sucesso=true
# (MELHORIAS_PENDENTES.md). Investigacao: o codigo de server.py/status.html
# ja filtrava fontes_baixadas corretamente - o bug nao reproduziu num
# projeto real (teste_projeto_broll) nem em manifest sintetico. Estes
# testes fixam o comportamento correto e cobrem os casos que a mensagem
# generica de "ainda" nao distinguia (manifest com todas as fontes
# falhando vs. manifest ausente).
# ---------------------------------------------------------------------------


def test_formatar_duracao_s_60_segundos_sem_zero_padding():
    assert server._formatar_duracao_s(60) == "1min 0s"


def test_formatar_duracao_s_318_segundos():
    assert server._formatar_duracao_s(318) == "5min 18s"


def test_formatar_duracao_s_3600_segundos_sem_zero_padding():
    assert server._formatar_duracao_s(3600) == "60min 0s"


def test_status_html_manifest_com_uma_fonte_sucesso_exibe_arquivo_formatado(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_1_sucesso",
        job_json={"nome": "caso_1_sucesso", "status": "concluido", "etapa_atual": "download"},
        links=["https://youtube.com/watch?v=abc"],
        manifest_fontes={
            "fontes": [
                {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 318, "sucesso": True},
            ],
            "sucesso": True,
        },
    )

    resposta = client.get("/status/caso_1_sucesso")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "fonte01.mp4 — 5min 18s" in pagina


def test_status_html_manifest_com_2_sucessos_e_1_falha_exibe_so_os_sucessos(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_parcial",
        job_json={"nome": "caso_parcial", "status": "concluido", "etapa_atual": "download"},
        links=["https://youtube.com/watch?v=abc"],
        manifest_fontes={
            "fontes": [
                {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 60, "sucesso": True},
                {"id": "fonte02", "arquivo": "fonte02.mp4", "duracao_s": 120, "sucesso": True},
                {"id": "fonte03", "arquivo": "fonte03.mp4", "duracao_s": None, "sucesso": False},
            ],
            "sucesso": True,
        },
    )

    resposta = client.get("/status/caso_parcial")
    pagina = resposta.get_data(as_text=True)

    assert "fonte01.mp4" in pagina
    assert "fonte02.mp4" in pagina
    assert "fonte03.mp4" not in pagina


def test_status_html_manifest_com_todas_as_fontes_falhando_mostra_mensagem_especifica(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_todas_falham",
        job_json={"nome": "caso_todas_falham", "status": "erro", "etapa_atual": "download"},
        links=["https://youtube.com/watch?v=abc"],
        manifest_fontes={
            "fontes": [
                {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": None, "sucesso": False},
            ],
            "sucesso": False,
        },
    )

    resposta = client.get("/status/caso_todas_falham")
    pagina = resposta.get_data(as_text=True)

    assert "Nenhum arquivo baixado com sucesso" in pagina
    assert "fonte01.mp4" not in pagina


def test_status_html_sem_manifest_novo_mostra_nenhum_arquivo_ainda(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_sem_manifest_novo",
        job_json={"nome": "caso_sem_manifest_novo", "status": "pendente", "etapa_atual": "download"},
        links=["https://youtube.com/watch?v=abc"],
    )

    resposta = client.get("/status/caso_sem_manifest_novo")
    pagina = resposta.get_data(as_text=True)

    assert "Nenhum arquivo baixado ainda." in pagina


def test_status_html_manifest_com_fontes_vazias_mostra_nenhum_arquivo_ainda(
    client, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_fontes_vazias",
        job_json={"nome": "caso_fontes_vazias", "status": "pendente", "etapa_atual": "download"},
        links=["https://youtube.com/watch?v=abc"],
        manifest_fontes={"fontes": [], "sucesso": False},
    )

    resposta = client.get("/status/caso_fontes_vazias")
    pagina = resposta.get_data(as_text=True)

    assert "Nenhum arquivo baixado ainda." in pagina


# ---------------------------------------------------------------------------
# Link "Voltar aos projetos" (barra de pipeline da tela de status) -
# correcao de UX original: nao havia jeito de voltar pra lista de projetos
# sem usar o menu superior. Regressao corrigida na sessao de correcoes de UI
# (destaque de thumbnail/botao duplicado/posicao do voltar): uma sessao
# anterior tinha adicionado um SEGUNDO link "Voltar aos projetos" solto no
# corpo (classe "link-voltar"), duplicando o que ja existia na barra de
# pipeline (pipeline-acoes) - usuario validou visualmente 3 vezes que o
# duplicado continuava aparecendo antes desta correcao. So' o da barra de
# pipeline sobrevive agora.
# ---------------------------------------------------------------------------


def test_status_html_tem_link_voltar_aos_projetos(client):
    resposta = client.get("/status/projeto_qualquer")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'class="pipeline-acoes"' in pagina
    assert "Voltar aos projetos" in pagina


def test_status_html_link_voltar_aponta_para_home(client):
    resposta = client.get("/status/projeto_qualquer")
    pagina = resposta.get_data(as_text=True)

    inicio = pagina.index('class="pipeline-acoes"')
    trecho = pagina[inicio : pagina.index("</a>", inicio)]
    assert 'href="/"' in trecho


def test_status_html_nao_duplica_link_voltar_aos_projetos(client):
    """Regressao: 'link-voltar' solto no corpo (fora da barra de pipeline)
    nao pode reaparecer - so' pode existir UM 'Voltar aos projetos' na
    pagina inteira."""
    resposta = client.get("/status/projeto_qualquer")
    pagina = resposta.get_data(as_text=True)

    assert pagina.count("Voltar aos projetos") == 1
    assert "link-voltar" not in pagina


def test_status_html_mostra_pipeline_horizontal(client):
    """A antiga sidebar vertical de pipeline (coluna de 260px) foi
    substituida pela macro _pipeline_horizontal.html, sticky abaixo do
    header - a pipeline continua aparecendo, so' que horizontal agora."""
    resposta = client.get("/status/projeto_qualquer")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "pipeline-horizontal" in pagina
    assert "Download" in pagina
    assert "Montagem" in pagina


# ---------------------------------------------------------------------------
# GET /api/vozes/<provedor>/<idioma> - listagem de vozes (CLAUDE.md secao 5.6)
# ---------------------------------------------------------------------------


def test_api_vozes_google_en_us_retorna_vozes_do_catalogo(client):
    """Endpoint retorna lista de vozes curadas para Google + idioma."""
    resposta = client.get("/api/vozes/google/en-US")

    assert resposta.status_code == 200
    vozes = resposta.get_json()
    assert isinstance(vozes, list)
    assert len(vozes) > 0
    # Verifica campos obrigatorios de cada voz
    for voz in vozes:
        assert "id" in voz
        assert "genero" in voz
        assert "descricao" in voz
        assert "recomendada_para" in voz


def test_api_vozes_provedor_inexistente_retorna_404(client):
    """Endpoint retorna 404 para provedor desconhecido."""
    resposta = client.get("/api/vozes/provedor_fake/en-US")

    assert resposta.status_code == 404


def test_api_vozes_google_idioma_inexistente_retorna_lista_vazia(client):
    """Endpoint retorna [] (nunca 404) para idioma inexistente."""
    resposta = client.get("/api/vozes/google/xx-XX")

    assert resposta.status_code == 200
    vozes = resposta.get_json()
    assert vozes == []


def test_api_vozes_elevenlabs_stub_retorna_lista_vazia(client):
    """Stub de ElevenLabs retorna [] - nao implementado no MVP."""
    resposta = client.get("/api/vozes/elevenlabs/en-US")

    assert resposta.status_code == 200
    vozes = resposta.get_json()
    assert vozes == []


def test_api_vozes_openai_stub_retorna_lista_vazia(client):
    """Stub de OpenAI retorna [] - nao implementado no MVP."""
    resposta = client.get("/api/vozes/openai/en-US")

    assert resposta.status_code == 200
    vozes = resposta.get_json()
    assert vozes == []


def test_api_vozes_azure_stub_retorna_lista_vazia(client):
    """Stub de Azure retorna [] - nao implementado no MVP."""
    resposta = client.get("/api/vozes/azure/en-US")

    assert resposta.status_code == 200
    vozes = resposta.get_json()
    assert vozes == []


def test_api_vozes_darkplanner_retorna_catalogo_da_api(client, monkeypatch):
    """Endpoint retorna as vozes buscadas dinamicamente da API DarkPlanner
    (CLAUDE.md secao 5.6, integracao pos-Sessao 25) - idioma e' ignorado
    pelo provedor (scripts/tts/darkplanner.py), so' repassado adiante."""
    from scripts.tts.darkplanner import DarkPlannerTTS

    vozes_fake = [{"id": "v1", "genero": "feminina", "descricao": "Helena", "recomendada_para": [], "amostra_url": "https://cdn/v1.mp3"}]
    monkeypatch.setattr(DarkPlannerTTS, "listar_vozes", lambda self, idioma: vozes_fake)

    resposta = client.get("/api/vozes/darkplanner/pt-BR")

    assert resposta.status_code == 200
    assert resposta.get_json() == vozes_fake


# ---------------------------------------------------------------------------
# GET /api/preview_voz/<voz_id> e POST /api/regerar_previews_vozes
# (CLAUDE.md secao 5.6 - previews de voz, scripts/tts/preview_vozes.py)
# ---------------------------------------------------------------------------


def test_api_preview_voz_indisponivel_previamente_nao_chama_gerar_preview(client, monkeypatch):
    """Voz ja marcada indisponivel responde direto, sem tentar sintetizar
    de novo (protege contra chamar a API repetidamente por uma voz que ja
    se sabe que falha)."""
    monkeypatch.setattr(
        server.preview_vozes, "carregar_indisponiveis", lambda: {"pt-BR-Wavenet-B": "Chave invalida"}
    )
    chamou_gerar = []
    monkeypatch.setattr(server.preview_vozes, "gerar_preview", lambda *a, **k: chamou_gerar.append(1))

    resposta = client.get("/api/preview_voz/pt-BR-Wavenet-B")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo == {"disponivel": False, "url": None, "erro": "Chave invalida"}
    assert chamou_gerar == []


def test_api_preview_voz_desconhecida_retorna_404(client, monkeypatch):
    monkeypatch.setattr(server.preview_vozes, "carregar_indisponiveis", lambda: {})
    monkeypatch.setattr(server.preview_vozes, "buscar_idioma_da_voz", lambda voz_id: None)

    resposta = client.get("/api/preview_voz/voz-fantasma")

    assert resposta.status_code == 404
    assert resposta.get_json()["disponivel"] is False


def test_api_preview_voz_sucesso_retorna_url_do_static(client, monkeypatch):
    monkeypatch.setattr(server.preview_vozes, "carregar_indisponiveis", lambda: {})
    monkeypatch.setattr(server.preview_vozes, "buscar_idioma_da_voz", lambda voz_id: "pt-BR")
    monkeypatch.setattr(
        server.preview_vozes,
        "gerar_preview",
        lambda voz_id, idioma: {"sucesso": True, "caminho": "x", "erro": None, "ja_existia": False},
    )

    resposta = client.get("/api/preview_voz/pt-BR-Wavenet-B")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["disponivel"] is True
    assert corpo["url"] == "/static/previews_vozes/pt-BR/pt-BR-Wavenet-B.mp3"


def test_api_preview_voz_falha_de_geracao_retorna_disponivel_falso(client, monkeypatch):
    monkeypatch.setattr(server.preview_vozes, "carregar_indisponiveis", lambda: {})
    monkeypatch.setattr(server.preview_vozes, "buscar_idioma_da_voz", lambda voz_id: "pt-BR")
    monkeypatch.setattr(
        server.preview_vozes,
        "gerar_preview",
        lambda voz_id, idioma: {"sucesso": False, "caminho": None, "erro": "Quota excedida", "ja_existia": False},
    )

    resposta = client.get("/api/preview_voz/pt-BR-Wavenet-B")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo == {"disponivel": False, "url": None, "erro": "Quota excedida"}


def test_api_preview_voz_darkplanner_retorna_preview_url_direto(client, monkeypatch):
    """provedor=darkplanner devolve o preview_url ja pronto da API (campo
    amostra_url), sem sintetizar nem cachear localmente (CLAUDE.md secao
    5.6)."""
    from scripts.tts.darkplanner import DarkPlannerTTS

    vozes_fake = [{"id": "v1", "amostra_url": "https://cdn.elevenlabs/v1-preview.mp3"}]
    monkeypatch.setattr(DarkPlannerTTS, "listar_vozes", lambda self, idioma: vozes_fake)

    resposta = client.get("/api/preview_voz/v1?provedor=darkplanner")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo == {"disponivel": True, "url": "https://cdn.elevenlabs/v1-preview.mp3", "erro": None}


def test_api_preview_voz_darkplanner_voz_sem_preview_url_retorna_indisponivel(client, monkeypatch):
    """Voz existe no catalogo mas a API nao trouxe preview_url pra ela -
    responde disponivel=false SEM marcar a voz como bloqueada pra geracao
    real (diferente do caminho Google, que reflete falha de sintese de
    verdade)."""
    from scripts.tts.darkplanner import DarkPlannerTTS

    vozes_fake = [{"id": "v1", "amostra_url": None}]
    monkeypatch.setattr(DarkPlannerTTS, "listar_vozes", lambda self, idioma: vozes_fake)

    resposta = client.get("/api/preview_voz/v1?provedor=darkplanner")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert corpo["disponivel"] is False


def test_api_preview_voz_darkplanner_voz_desconhecida_retorna_indisponivel(client, monkeypatch):
    from scripts.tts.darkplanner import DarkPlannerTTS

    monkeypatch.setattr(DarkPlannerTTS, "listar_vozes", lambda self, idioma: [])

    resposta = client.get("/api/preview_voz/voz-fantasma?provedor=darkplanner")

    assert resposta.status_code == 200
    assert resposta.get_json()["disponivel"] is False


def test_api_regerar_previews_vozes_chama_regeracao_e_retorna_sumario(client, monkeypatch):
    sumario_fake = {
        "total": 2, "geradas_agora": 1, "ja_existiam": 0, "falharam": 1, "falha_detalhes": []
    }
    monkeypatch.setattr(server.preview_vozes, "regerar_todos_previews", lambda: sumario_fake)

    resposta = client.post("/api/regerar_previews_vozes")

    assert resposta.status_code == 200
    assert resposta.get_json() == sumario_fake


def test_api_regerar_previews_vozes_get_nao_permitido(client):
    resposta = client.get("/api/regerar_previews_vozes")
    assert resposta.status_code == 405


# ---------------------------------------------------------------------------
# POST /projetos/<id>/gerar_audio - disparo manual da Etapa 4
# (CLAUDE.md secao 5.6)
# ---------------------------------------------------------------------------


def test_post_gerar_audio_sem_etapa3_concluida_retorna_400(client, tmp_path, monkeypatch):
    """Sem roteiro_aprovado.md, erro 400."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/projeto_inexistente/gerar_audio")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "etapa3_nao_concluida"


def test_post_gerar_audio_sem_origem_definida_retorna_400(client, tmp_path, monkeypatch):
    """Sem origem_audio.json, erro 400."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    (pasta_projeto / "roteiro_aprovado.md").write_text("Roteiro test", encoding="utf-8")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_teste/gerar_audio")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "origem_audio_nao_definida"


def test_post_gerar_audio_tts_sem_chave_retorna_400(client, tmp_path, monkeypatch):
    """TTS sem chave configurada, erro 400."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    (pasta_projeto / "roteiro_aprovado.md").write_text("Roteiro test", encoding="utf-8")
    (pasta_projeto / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)

    resposta = client.post("/projetos/caso_teste/gerar_audio")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "chave_ausente"


def test_post_gerar_audio_upload_com_arquivo_ok_dispara_etapa4(client, tmp_path, monkeypatch):
    """Upload com arquivo existente dispara Etapa 4 (sucesso)."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    (pasta_projeto / "roteiro_aprovado.md").write_text("Roteiro test", encoding="utf-8")
    (pasta_projeto / "narracao_upload.mp3").write_bytes(b"fake audio")
    (pasta_projeto / "origem_audio.json").write_text(
        json.dumps({"origem": "upload", "upload_arquivo": "narracao_upload.mp3"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    # Mock de _disparar_etapa4
    chamadas = []
    def mock_disparar_etapa4(projeto_id, pasta):
        chamadas.append((projeto_id, pasta))

    monkeypatch.setattr(server, "_disparar_etapa4", mock_disparar_etapa4)

    resposta = client.post("/projetos/caso_teste/gerar_audio")

    assert resposta.status_code == 202
    corpo = resposta.get_json()
    assert corpo["status"] == "iniciado"
    assert len(chamadas) == 1
    assert chamadas[0][0] == "caso_teste"


def test_post_gerar_audio_tts_com_chave_dispara_etapa4(client, tmp_path, monkeypatch):
    """TTS com chave configurada dispara Etapa 4."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    (pasta_projeto / "roteiro_aprovado.md").write_text("Roteiro test", encoding="utf-8")
    (pasta_projeto / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key_123")

    # Mock de _disparar_etapa4
    chamadas = []
    def mock_disparar_etapa4(projeto_id, pasta):
        chamadas.append((projeto_id, pasta))

    monkeypatch.setattr(server, "_disparar_etapa4", mock_disparar_etapa4)

    resposta = client.post("/projetos/caso_teste/gerar_audio")

    assert resposta.status_code == 202
    assert len(chamadas) == 1


# ---------------------------------------------------------------------------
# POST /projetos/<id>/gerar_clipes - disparo manual da Etapa 5 (CLAUDE.md -
# consolidacao da antiga cadeia dividir_cenas (5) -> montar_timeline (6) ->
# renderizar_clipes (7) num unico script por selecao aleatoria de trechos)
# ---------------------------------------------------------------------------


def test_post_gerar_clipes_sem_etapa4_concluida_retorna_400(client, tmp_path, monkeypatch):
    """Sem narracao.mp3 (Etapa 4 nao concluida), erro 400."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/projeto_inexistente/gerar_clipes")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "etapa4_nao_concluida"


def test_post_gerar_clipes_fluxo_feliz_dispara_etapa5(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    (pasta_projeto / "narracao.mp3").write_bytes(b"audio")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    chamadas = []
    monkeypatch.setattr(
        server, "_disparar_etapa5", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    resposta = client.post("/projetos/caso_teste/gerar_clipes")

    assert resposta.status_code == 202
    corpo = resposta.get_json()
    assert corpo["status"] == "iniciado"
    assert chamadas == [("caso_teste", pasta_projeto)]


# ---------------------------------------------------------------------------
# POST /projetos/<id>/montar_video - disparo manual da Etapa 6 (montagem
# final: concat + mux + legendas)
# ---------------------------------------------------------------------------


def test_post_montar_video_sem_etapa5_concluida_retorna_400(client, tmp_path, monkeypatch):
    """Sem clipes/indice.json (Etapa 5 nao concluida), erro 400."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/projeto_inexistente/montar_video")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "etapa5_nao_concluida"


def test_post_montar_video_fluxo_feliz_dispara_etapa6(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "indice.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    chamadas = []
    monkeypatch.setattr(
        server, "_disparar_etapa6", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    resposta = client.post("/projetos/caso_teste/montar_video")

    assert resposta.status_code == 202
    corpo = resposta.get_json()
    assert corpo["status"] == "iniciado"
    assert chamadas == [("caso_teste", pasta_projeto)]


# ---------------------------------------------------------------------------
# Encadeamento automatico: Etapa 4 (audio) -> Etapa 5 (geracao de clipes)
# (CLAUDE.md secao 4 - fluxo continuo sem intervencao do usuario). A Etapa 5
# consolidada vai direto para "aguardando_legendas" - sem os hops
# intermediarios de montagem/renderizacao que existiam antes da consolidacao.
# ---------------------------------------------------------------------------


def test_etapa4_com_sucesso_dispara_etapa5_automaticamente(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "Audio da narracao obtido com sucesso", "sucesso": true}\n']
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa5", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    thread = server._disparar_etapa4("caso_teste", pasta_projeto)
    thread.join(timeout=2)

    assert chamadas == [("caso_teste", pasta_projeto)]


def test_etapa4_com_erro_nao_dispara_etapa5(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 0.0, "detalhe": "ERRO: falhou", "sucesso": false}\n'],
            returncode=1,
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa5", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    thread = server._disparar_etapa4("caso_teste", pasta_projeto)
    thread.join(timeout=2)

    assert chamadas == []
    assert server.jobs["caso_teste"]["status"] == "erro"


def test_etapa5_com_sucesso_marca_job_aguardando_legendas(tmp_path, monkeypatch):
    """Etapa 5 consolidada (geracao de clipes) bem-sucedida passa por
    `aguardando_legendas` antes de encadear a Etapa 6 (montagem) - aqui a
    Etapa 6 e' mockada (`_encadear_etapa6` vira no-op) para isolar so' o
    comportamento da Etapa 5, mesmo espirito de
    test_etapa4_com_sucesso_dispara_etapa5_automaticamente."""
    pasta_projeto = tmp_path / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "Concluido: 5 clipe(s) gerado(s)", "sucesso": true}\n']
        ),
    )
    monkeypatch.setattr(server, "_encadear_etapa6", lambda projeto_id, pasta: None)

    server.jobs["caso_teste"] = server._job_inicial_etapa5()
    server._executar_etapa5("caso_teste", pasta_projeto)

    job = server.jobs["caso_teste"]
    assert job["status"] == "aguardando_legendas"
    assert job["etapa"] == "legendas"

    job_disco = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "aguardando_legendas"
    assert job_disco["etapa_atual"] == "legendas"


def test_etapa5_com_sucesso_dispara_etapa6_automaticamente(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "Concluido: 5 clipe(s) gerado(s)", "sucesso": true}\n']
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa6", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    server.jobs["caso_teste"] = server._job_inicial_etapa5()
    server._executar_etapa5("caso_teste", pasta_projeto)

    assert chamadas == [("caso_teste", pasta_projeto)]


def test_etapa5_com_erro_nao_dispara_etapa6(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 0.0, "detalhe": "ERRO: fontes ausentes", "sucesso": false}\n'],
            returncode=1,
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa6", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    server.jobs["caso_teste"] = server._job_inicial_etapa5()
    server._executar_etapa5("caso_teste", pasta_projeto)

    assert chamadas == []
    assert server.jobs["caso_teste"]["status"] == "erro"


def test_etapa5_com_falha_no_subprocess_marca_job_como_erro(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 0.0, "detalhe": "ERRO: fontes ausentes", "sucesso": false, '
             '"mensagem_usuario": "fontes/manifest_fontes.json nao encontrado.", "tipo_erro": "fontes_ausentes"}\n'],
            returncode=1,
        ),
    )

    server.jobs["caso_teste"] = server._job_inicial_etapa5()
    server._executar_etapa5("caso_teste", pasta_projeto)

    job = server.jobs["caso_teste"]
    assert job["status"] == "erro"
    assert "fontes/manifest_fontes.json nao encontrado" in job["erro"]

    job_disco = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "erro"
    assert job_disco["tipo_erro"] == "fontes_ausentes"


def test_fluxo_completo_audio_ate_clipes_ate_montagem_automatico(
    client, tmp_path, monkeypatch
):
    """Integracao ponta-a-ponta do encadeamento: subprocess mockados em
    sequencia (4_obter_audio.py, 5_gerar_clipes.py, 6_montar_video.py e
    7_thumbnail.py - o fallback do fake Popen cobre qualquer script que
    nao seja audio/clipes, entao tambem responde por 7_thumbnail.py),
    diferenciados pelo comando recebido - o job final reflete o resultado
    da Etapa 7 (ultima etapa do encadeamento automatico hoje - Etapa 6
    encadeia direto nela - terminal em "aguardando_thumbnail", nao mais
    em "concluido" direto: o job so' chega em "concluido" depois que o
    usuario confirma um template na tela de thumbnail, Grupo G)."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    pasta_projeto.mkdir(parents=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _popen_por_etapa(comando, **kwargs):
        script = " ".join(comando)

        class _ProcessoFake:
            def __init__(self, linhas, returncode):
                self.stdout = iter(linhas)
                self.returncode = returncode

            def wait(self):
                return None

        if "4_obter_audio.py" in script:
            return _ProcessoFake(
                ['@PROGRESSO {"pct": 100.0, "detalhe": "Audio obtido", "sucesso": true}\n'], 0
            )
        if "5_gerar_clipes.py" in script:
            return _ProcessoFake(
                ['@PROGRESSO {"pct": 100.0, "detalhe": "Concluido: 3 clipe(s) gerado(s)", "sucesso": true}\n'],
                0,
            )
        return _ProcessoFake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "Concluido: video final montado", "sucesso": true}\n'],
            0,
        )

    monkeypatch.setattr(server.subprocess, "Popen", _popen_por_etapa)

    thread = server._disparar_etapa4("caso_teste", pasta_projeto)
    thread.join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["status"] == "aguardando_thumbnail"
    assert job["etapa"] == "thumbnail"


# ---------------------------------------------------------------------------
# Migracao de status (STATUS_MIGRATION) - projetos antigos com status
# obsoletos sao mapeados em memoria para os status novos, sem reescrever o
# disco. Inclui tanto os status obsoletos anteriores a Sessao 10 quanto os
# tres status intermediarios da cadeia dividir_cenas/montar_timeline/
# renderizar_clipes, removida na consolidacao da Etapa 5.
# ---------------------------------------------------------------------------


def test_ler_job_json_migra_aguardando_geracao_video_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_geracao_video' (obsoleto) e' mapeado para
    'aguardando_geracao_clipes' em memoria - arquivo no disco nao e'
    reescrito."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_antigo",
        job_json={
            "nome": "caso_antigo",
            "status": "aguardando_geracao_video",  # Status obsoleto
            "etapa_atual": "download",
            "data_criacao": "2026-08-28T11:39:00",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    # Ler via server._ler_job_json
    job_dict = server._ler_job_json(projetos_dir / "caso_antigo")

    # Em memoria, status foi migrado
    assert job_dict["status"] == "aguardando_geracao_clipes"

    # No disco, arquivo continua com status antigo
    job_disco = json.loads(
        (projetos_dir / "caso_antigo" / "job.json").read_text(encoding="utf-8")
    )
    assert job_disco["status"] == "aguardando_geracao_video"


def test_ler_job_json_migra_aguardando_curadoria_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_curadoria' (obsoleto) e' mapeado para
    'aguardando_geracao_clipes' em memoria."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_curadoria",
        job_json={
            "nome": "caso_curadoria",
            "status": "aguardando_curadoria",  # Status obsoleto
            "etapa_atual": "download",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_curadoria")

    assert job_dict["status"] == "aguardando_geracao_clipes"


def test_ler_job_json_migra_aguardando_cortes_v9_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_cortes_v9' (obsoleto) e' mapeado para
    'aguardando_geracao_clipes' em memoria."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_cortes_v9",
        job_json={
            "nome": "caso_cortes_v9",
            "status": "aguardando_cortes_v9",  # Status obsoleto
            "etapa_atual": "download",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_cortes_v9")

    assert job_dict["status"] == "aguardando_geracao_clipes"


def test_ler_job_json_migra_aguardando_planejamento_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_planejamento' (entrada da antiga Etapa 5, removida
    na Sessao 10) e' mapeado para 'aguardando_geracao_clipes' em memoria."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_planejamento",
        job_json={
            "nome": "caso_planejamento",
            "status": "aguardando_planejamento",  # Status obsoleto (Sessao 10)
            "etapa_atual": "audio",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_planejamento")

    assert job_dict["status"] == "aguardando_geracao_clipes"


def test_ler_job_json_migra_aguardando_cortes_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_cortes' (saida da antiga Etapa 5, removida na
    Sessao 10) e' mapeado para 'aguardando_geracao_clipes' em memoria."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_cortes",
        job_json={
            "nome": "caso_cortes",
            "status": "aguardando_cortes",  # Status obsoleto (Sessao 10)
            "etapa_atual": "planejamento",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_cortes")

    assert job_dict["status"] == "aguardando_geracao_clipes"


def test_ler_job_json_migra_aguardando_montagem_timeline_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_montagem_timeline' (etapa intermediaria removida
    na consolidacao da Etapa 5) e' mapeado para 'aguardando_geracao_clipes'
    em memoria."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_montagem",
        job_json={
            "nome": "caso_montagem",
            "status": "aguardando_montagem_timeline",  # Status obsoleto (consolidacao Etapa 5)
            "etapa_atual": "divisao_cenas",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_montagem")

    assert job_dict["status"] == "aguardando_geracao_clipes"


def test_ler_job_json_migra_aguardando_renderizacao_para_aguardando_geracao_clipes(
    client, tmp_path, monkeypatch
):
    """Status 'aguardando_renderizacao' (etapa intermediaria removida na
    consolidacao da Etapa 5) e' mapeado para 'aguardando_geracao_clipes' em
    memoria."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_renderizacao",
        job_json={
            "nome": "caso_renderizacao",
            "status": "aguardando_renderizacao",  # Status obsoleto (consolidacao Etapa 5)
            "etapa_atual": "montagem_timeline",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_renderizacao")

    assert job_dict["status"] == "aguardando_geracao_clipes"


def test_ler_job_json_nao_migra_status_que_nao_esta_no_mapa(
    client, tmp_path, monkeypatch
):
    """Status que nao esta no STATUS_MIGRATION dict passa incolume."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_concluido",
        job_json={
            "nome": "caso_concluido",
            "status": "concluido",  # Status moderno, nao no mapa
            "etapa_atual": "download",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_concluido")

    # Status nao foi alterado
    assert job_dict["status"] == "concluido"


def test_ler_job_json_concluido_nunca_regride_para_aguardando_thumbnail(
    client, tmp_path, monkeypatch
):
    """Ajuste explicito da sessao de thumbnail (Etapa 7): projetos que ja
    chegaram a status "concluido" ANTES desta feature existir (etapa_atual
    gravado como "concluido" tambem, no fluxo antigo onde a Etapa 6 era
    terminal) nao podem "regredir" pra "aguardando_thumbnail"/"thumbnail"
    so' porque agora existe uma etapa nova entre montagem e concluido.

    Por isso NAO existe (nem deve existir) uma entrada
    "concluido": "aguardando_thumbnail" em STATUS_MIGRATION nem
    "concluido": "thumbnail" em ETAPA_ATUAL_MIGRATION - STATUS_MIGRATION/
    ETAPA_ATUAL_MIGRATION so' mapeiam nomes ORFAOS (que nao existem mais
    em lugar nenhum do pipeline atual); "concluido" continua um valor
    perfeitamente valido e terminal hoje, entao nunca deveria estar la'
    como chave. Este teste fixa esse comportamento: mesmo com a etapa
    "thumbnail" agora existindo em PIPELINE_ETAPAS, um job.json antigo com
    status/etapa_atual="concluido" tem que continuar voltando exatamente
    como "concluido" - nunca "aguardando_thumbnail"/"thumbnail"."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    assert "concluido" not in server.STATUS_MIGRATION
    assert "concluido" not in server.ETAPA_ATUAL_MIGRATION

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_concluido_pre_thumbnail",
        job_json={
            "nome": "caso_concluido_pre_thumbnail",
            "status": "concluido",
            "etapa_atual": "concluido",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_concluido_pre_thumbnail")

    assert job_dict["status"] == "concluido"
    assert job_dict["etapa_atual"] == "concluido"


def test_ler_job_json_nao_migra_status_pendente(
    client, tmp_path, monkeypatch
):
    """Status 'pendente' nao esta no mapa de migracao e passa incolume."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_pendente",
        job_json={
            "nome": "caso_pendente",
            "status": "pendente",  # Status antigo mas nao no mapa
            "etapa_atual": "download",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    job_dict = server._ler_job_json(projetos_dir / "caso_pendente")

    assert job_dict["status"] == "pendente"


def test_ler_job_json_none_quando_arquivo_nao_existe(client, tmp_path, monkeypatch):
    """Se pasta nao existe ou arquivo nao existe, retorna None."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    # Pasta nao existe
    job_dict = server._ler_job_json(projetos_dir / "projeto_inexistente")

    assert job_dict is None


def test_tela_status_mostra_status_migrado_para_usuario(
    client, tmp_path, monkeypatch
):
    """Tela de status (GET /status/<id>) mostra o status migrado, nao o
    antigo do disco."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    _criar_projeto_no_disco(
        projetos_dir,
        "caso_visualizar",
        job_json={
            "nome": "caso_visualizar",
            "status": "aguardando_geracao_video",  # Status antigo
            "etapa_atual": "download",
            "data_criacao": "2026-08-28T11:39:00",
        },
        links=["https://www.youtube.com/watch?v=abc"],
    )

    resposta = client.get("/status/caso_visualizar")
    pagina = resposta.get_data(as_text=True)

    # Usuario ve o status moderno traduzido ("Gerando clipes"), nao a
    # chave tecnica antiga "aguardando_geracao_video" nem a chave crua
    # "aguardando_geracao_clipes" (agora sempre exibida via label_status).
    assert "Gerando clipes" in pagina
    assert "aguardando_geracao_video" not in pagina


# Nota (consolidacao Etapa 5/6/7 - remocao completa de PySceneDetect/pHash/
# Vision): os testes que existiam aqui
# (test_post_novo_sem_usar_vision_grava_false_em_configuracao_edicao,
# test_post_novo_com_usar_vision_grava_true_em_configuracao_edicao)
# validavam o toggle "usar analise visual avancada" do formulario de Novo
# projeto. Com a analise Vision removida do pipeline inteiro, o checkbox
# `usar_vision` e o arquivo entrada/configuracao_edicao.json deixaram de
# existir - `_criar_pasta_projeto` nao grava mais esse arquivo, e o
# template novo_projeto.html nao tem mais o campo.


# ---------------------------------------------------------------------------
# POST /novo - musica de fundo (CLAUDE.md secao 5.8) migrou pra
# POST /aprovar_roteiro (Grupo B da sessao de UX - bloco saiu do
# formulario de Novo projeto e foi pra tela de revisao, junto com a
# escolha de origem do audio). Testes equivalentes agora vivem em
# tests/test_aprovar_roteiro.py. Este teste cobre so' o que ainda importa
# aqui: /novo continua ignorando com_musica_fundo/musicas[] mesmo se
# alguem enviar esses campos por engano (URL antiga, script externo etc).
# ---------------------------------------------------------------------------


def test_novo_projeto_ignora_campos_de_musica_legado(client, tmp_path, monkeypatch):
    """POST /novo com com_musica_fundo=on e musicas[] (campos do formulario
    antigo) nao cria entrada/musica_fundo/ - o campo nao existe mais neste
    endpoint, so' na tela de revisao."""
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_musica_legado",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "com_musica_fundo": "on",
            "musicas[]": [(io.BytesIO(b"fake-audio"), "track.mp3")],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_musica_legado"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_musica_legado"
    assert not (pasta_projeto / "entrada" / "musica_fundo").exists()

    config_video = json.loads(
        (pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["com_musica_fundo"] is False


def test_novo_projeto_grayscale_marcado_grava_configuracao(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_grayscale",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "grayscale": "on",
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_grayscale"].join(timeout=2)

    config_video = json.loads(
        (projetos_dir / "caso_grayscale" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["grayscale"] is True


def test_novo_projeto_grayscale_nao_marcado_default_falso(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sem_grayscale",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_sem_grayscale"].join(timeout=2)

    config_video = json.loads(
        (projetos_dir / "caso_sem_grayscale" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["grayscale"] is False


# ---------------------------------------------------------------------------
# GET/POST /novo - preset de tamanho do roteiro (Grupo C da sessao de UX) -
# substitui os dois campos numericos livres (palavras_alvo/duracao_alvo_minutos)
# por um <select> com 8 opcoes fixas. O valor persistido continua sendo
# palavras_alvo (scripts/validators.py:normalizar_palavras_alvo nao mudou).
# ---------------------------------------------------------------------------


def test_get_novo_preset_padrao_25min_selecionado_sem_formulario_previo(client):
    """GET /novo sem nenhum `form` de redisplay usa o default 4000 palavras
    / 25 min - a opcao correspondente do <select> vem marcada selected."""
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'value="4000" data-minutos="25" selected>' in pagina


def test_post_novo_com_erro_preset_palavras_alvo_exato_continua_selecionado(
    client, tmp_path, monkeypatch
):
    """Redisplay apos erro de validacao (ex: sem links) com palavras_alvo
    batendo exatamente num preset (3200 = "20 min") mantem esse preset
    selecionado, nao o default."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "   \n  ",
            "perfil": "truecrime",
            "palavras_alvo": "3200",
            "duracao_alvo_minutos": "20",
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert 'value="3200" data-minutos="20" selected>' in pagina
    assert 'value="4000" data-minutos="25" selected>' not in pagina


def test_post_novo_com_erro_preset_palavras_alvo_legado_seleciona_mais_proximo(
    client, tmp_path, monkeypatch
):
    """Valor legado fora da lista de presets (3500, de um projeto/reload
    anterior a este preset) nao trava a tela nem e' descartado - o select
    mostra o preset mais proximo (3200, diferenca 300) em vez do default
    (4000, diferenca 500), sem escrever nada em disco (nenhum projeto e'
    criado nesta requisicao - o POST falhou por falta de links)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "   \n  ",
            "perfil": "truecrime",
            "palavras_alvo": "3500",
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert 'value="3200" data-minutos="20" selected>' in pagina
    assert 'value="4000" data-minutos="25" selected>' not in pagina
    assert "caso_teste" not in server.jobs


# ---------------------------------------------------------------------------
# POST /novo - tipo de projeto "videos_pre_gerados" (CLAUDE.md secao 3,
# "Vídeos pré-gerados"): caminho totalmente separado da pipeline completa -
# usuario ja tem os clipes finais prontos (ex: exportados do DarkPlanner
# Flow/Veo3, ja com audio embutido), so' concatena. Sem links, sem
# download/transcricao/roteiro/audio/clipes - dispara a Etapa 6 direto.
# ---------------------------------------------------------------------------


def test_novo_projeto_tipo_invalido_retorna_400(client, tmp_path, monkeypatch):
    """Protecao contra manipulacao de request - o <input type=radio> do
    formulario so oferece os dois valores validos."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={"nome": "caso_teste", "perfil": "truecrime", "tipo_projeto": "algo_manipulado"},
    )

    assert resposta.status_code == 400
    assert "tipo de projeto" in resposta.get_data(as_text=True).lower()


def test_novo_projeto_videos_pre_gerados_aceita_uploads(client, tmp_path, monkeypatch):
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "5.0"})())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_pre_gerado",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [
                (io.BytesIO(b"fake-video-1"), "1_Wide_shot.mp4"),
                (io.BytesIO(b"fake-video-2"), "2_Close_up.mp4"),
            ],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_pre_gerado"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_pre_gerado"
    assert (pasta_projeto / "entrada" / "tipo_projeto.txt").read_text(encoding="utf-8").strip() == (
        "videos_pre_gerados"
    )
    assert (pasta_projeto / "clipes" / "clipe_0000.mp4").exists()
    assert (pasta_projeto / "clipes" / "clipe_0001.mp4").exists()

    indice = json.loads((pasta_projeto / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert indice["metadata"]["tipo_projeto"] == "videos_pre_gerados"
    assert len(indice["clipes"]) == 2


def test_novo_projeto_videos_pre_gerados_valida_extensao(client, tmp_path, monkeypatch):
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_extensao_invalida",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [(io.BytesIO(b"nao e' video"), "1_arquivo.txt")],
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert not (projetos_dir / "caso_extensao_invalida").exists()


def test_novo_projeto_videos_pre_gerados_sem_arquivos_mostra_erro(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/novo",
        data={"nome": "caso_sem_arquivos", "perfil": "truecrime", "tipo_projeto": "videos_pre_gerados"},
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "video" in pagina.lower()
    assert not (projetos_dir / "caso_sem_arquivos").exists()


def test_novo_projeto_videos_pre_gerados_valida_tamanho_total_2gb(client, tmp_path, monkeypatch):
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    # Baixa o teto para o teste nao precisar de verdade de 2GB de payload.
    monkeypatch.setattr(server, "TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES", 10)

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_grande_demais",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [(io.BytesIO(b"conteudo maior que 10 bytes"), "1_a.mp4")],
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "excede" in pagina.lower()
    assert not (projetos_dir / "caso_grande_demais").exists()


def test_novo_projeto_videos_pre_gerados_sort_natural_por_prefixo(client, tmp_path, monkeypatch):
    """Envio fora de ordem (10, 2, 1) - indice.json final segue a ordem
    NUMERICA do prefixo, nao a ordem de envio nem a ordem alfabetica (que
    colocaria '10_...' antes de '2_...')."""
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "5.0"})())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sort_natural",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [
                (io.BytesIO(b"video-10"), "10_ultimo.mp4"),
                (io.BytesIO(b"video-2"), "2_segundo.mp4"),
                (io.BytesIO(b"video-1"), "1_primeiro.mp4"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert resposta.status_code == 302
    server._threads["caso_sort_natural"].join(timeout=2)

    indice = json.loads(
        (projetos_dir / "caso_sort_natural" / "clipes" / "indice.json").read_text(encoding="utf-8")
    )
    ordem = [c["arquivo_original"] for c in indice["clipes"]]
    assert ordem == ["1_primeiro.mp4", "2_segundo.mp4", "10_ultimo.mp4"]


def test_novo_projeto_videos_pre_gerados_srt_marcado_sem_arquivo_erro(client, tmp_path, monkeypatch):
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_srt_sem_arquivo",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "com_legenda_srt": "on",
            "videos_pre_gerados[]": [(io.BytesIO(b"fake-video"), "1_a.mp4")],
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert not (projetos_dir / "caso_srt_sem_arquivo").exists()


def test_novo_projeto_videos_pre_gerados_srt_opcional_salva(client, tmp_path, monkeypatch):
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "5.0"})())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_com_srt",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "com_legenda_srt": "on",
            "videos_pre_gerados[]": [(io.BytesIO(b"fake-video"), "1_a.mp4")],
            "arquivo_srt": (io.BytesIO(b"1\n00:00:00,000 --> 00:00:01,000\nOla\n"), "legenda.srt"),
        },
        content_type="multipart/form-data",
    )
    assert resposta.status_code == 302
    server._threads["caso_com_srt"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_com_srt"
    assert (pasta_projeto / "entrada" / "legenda_importada.srt").exists()
    config_video = json.loads(
        (pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["legendas_queimadas"] is True
    assert config_video["com_musica_fundo"] is False


def test_novo_projeto_videos_pre_gerados_dispara_etapa6_direto(client, tmp_path, monkeypatch):
    """Nenhum comando de 1_baixar_videos.py e' disparado - so' 6_montar_video.py,
    direto, sem passar pelas Etapas 1-5."""
    import io

    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    comandos_chamados = []
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([], comandos_chamados=comandos_chamados))
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "5.0"})())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_direto_etapa6",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [(io.BytesIO(b"fake-video"), "1_a.mp4")],
        },
        content_type="multipart/form-data",
    )
    assert resposta.status_code == 302
    server._threads["caso_direto_etapa6"].join(timeout=2)

    # 2 comandos: 6_montar_video.py e depois 7_thumbnail.py (Etapa 6
    # encadeia direto na Etapa 7 em sucesso, desde a sessao de thumbnail).
    assert len(comandos_chamados) == 2
    assert "6_montar_video.py" in comandos_chamados[0][1]
    assert "7_thumbnail.py" in comandos_chamados[1][1]

    # Mock de Popen retorna sucesso imediato (returncode=0) - o job avanca
    # ate' "aguardando_thumbnail" na mesma thread, confirmando que as
    # Etapas 6 e 7 rodaram de ponta a ponta sem esperar nenhuma das
    # Etapas 1-5. So' chega a "concluido" depois que o usuario confirma
    # um template na tela de thumbnail (Grupo G).
    job_disco = json.loads((projetos_dir / "caso_direto_etapa6" / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "aguardando_thumbnail"


def test_criar_pasta_projeto_videos_pre_gerados_job_inicial_aponta_montagem(tmp_path):
    """Confirma o estado ANTES de qualquer thread rodar - job.json ja e'
    criado apontando direto para a etapa "montagem" (index 5 de
    PIPELINE_ETAPAS - "thumbnail", index 6, e' a ultima desde a Etapa 7),
    sem nenhum estagio intermediario de download/transcricao/roteiro/
    audio/clipes."""
    pasta_projeto = tmp_path / "projeto"
    indice_clipes = [{"clipe_id": "clipe_0000", "arquivo": "clipe_0000.mp4", "duracao_s": 5.0}]

    server._criar_pasta_projeto_videos_pre_gerados(pasta_projeto, "truecrime", indice_clipes, False)

    job = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job["etapa_atual"] == "montagem"
    assert job["tipo_projeto"] == "videos_pre_gerados"
    assert server._ler_tipo_projeto(pasta_projeto) == "videos_pre_gerados"


def test_ler_tipo_projeto_ausente_retorna_pipeline_completa(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    assert server._ler_tipo_projeto(pasta_projeto) == "pipeline_completa"


def test_ler_tipo_projeto_none_retorna_pipeline_completa():
    assert server._ler_tipo_projeto(None) == "pipeline_completa"


def test_validar_uploads_videos_pre_gerados_rejeita_extensao_invalida():
    import io
    from werkzeug.datastructures import FileStorage

    arquivo = FileStorage(stream=io.BytesIO(b"x"), filename="1_a.txt")
    validados, erro = server._validar_uploads_videos_pre_gerados([arquivo])

    assert validados == []
    assert erro is not None
    assert "formato de video" in erro.lower()


def test_validar_uploads_videos_pre_gerados_ordena_por_prefixo():
    import io
    from werkzeug.datastructures import FileStorage

    arquivos = [
        FileStorage(stream=io.BytesIO(b"x" * 10), filename="10_ultimo.mp4"),
        FileStorage(stream=io.BytesIO(b"x" * 10), filename="2_segundo.mp4"),
        FileStorage(stream=io.BytesIO(b"x" * 10), filename="1_primeiro.mp4"),
    ]
    validados, erro = server._validar_uploads_videos_pre_gerados(arquivos)

    assert erro is None
    assert [item[2] for item in validados] == ["1_primeiro.mp4", "2_segundo.mp4", "10_ultimo.mp4"]


def test_validar_uploads_videos_pre_gerados_total_excede_teto(monkeypatch):
    import io
    from werkzeug.datastructures import FileStorage

    monkeypatch.setattr(server, "TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES", 5)
    arquivos = [FileStorage(stream=io.BytesIO(b"x" * 100), filename="1_a.mp4")]
    validados, erro = server._validar_uploads_videos_pre_gerados(arquivos)

    assert validados == []
    assert "excede" in erro.lower()


def test_obter_duracao_video_ffprobe_falha_retorna_zero(tmp_path, monkeypatch):
    """ffprobe ausente/falhando nunca derruba a criacao do projeto - so'
    vira 0.0 (campo informativo, o concat via demuxer nao depende dele)."""
    monkeypatch.setattr(
        server.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    assert server._obter_duracao_video_ffprobe(tmp_path / "inexistente.mp4") == 0.0


def test_novo_projeto_videos_pre_gerados_nao_duplica_nome(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    (projetos_dir / "caso_existente").mkdir(parents=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    import io

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_existente",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [(io.BytesIO(b"fake-video"), "1_a.mp4")],
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "ja existe" in pagina.lower() or "já existe" in pagina.lower()


# ---------------------------------------------------------------------------
# _fontes_baixadas_com_origem - correcao de sessao de refinamento (link
# original + tipo de uso na tela de leitura da Etapa 1). Regressao real:
# a primeira versao da correcao quebrava /status para um job que so' existe
# em memoria (server.jobs), sem pasta em disco - `_pasta_projeto_ou_none`
# devolve None nesse caso, e o codigo novo tentava `pasta_projeto / "entrada"
# / ...` sem checar None antes.
# ---------------------------------------------------------------------------


def test_fontes_baixadas_com_origem_pasta_none_nao_levanta_excecao():
    fontes_baixadas, mensagem = server._fontes_baixadas_com_origem(None)
    assert fontes_baixadas == []
    assert mensagem == "Nenhum arquivo baixado ainda."


def test_status_com_job_so_em_memoria_sem_pasta_no_disco_nao_quebra(client):
    """Regressao real (correcao de sessao de refinamento): job existe so'
    em server.jobs (nenhuma pasta em disco ainda) - GET /status/<id> nao
    pode levantar TypeError ao calcular fontes_baixadas."""
    server.jobs["caso_so_memoria"] = {
        "etapa": "download",
        "status": "processando",
        "pct": 10.0,
        "detalhe": "Baixando...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/status/caso_so_memoria")

    assert resposta.status_code == 200


