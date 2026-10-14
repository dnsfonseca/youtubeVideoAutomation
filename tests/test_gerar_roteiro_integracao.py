"""Testes da integracao da Etapa 3 (geracao de roteiro) no server.py
(CLAUDE.md secoes 5.3, 5.5):

- Encadeamento automatico transcricao -> roteiro (Etapa 2 concluida com
  sucesso dispara a Etapa 3 na mesma thread).
- POST /projetos/<id>/gerar_roteiro - disparo manual/retry.
- Tela de status mostra o link "Revisar roteiro" quando o job fica
  "aguardando_revisao".

scripts/3_gerar_roteiro.py em si ja tem suite propria
(test_gerar_roteiro.py) - aqui o subprocess e' sempre mockado (nunca
chama a API Anthropic de verdade, CLAUDE.md secao 8).
"""

import json

import server


def _popen_fake(linhas, returncode=0, comandos_chamados=None):
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


def _popen_por_script(respostas_por_script):
    """`respostas_por_script`: dict {trecho_do_nome_do_script: (linhas, returncode)}.
    Devolve uma funcao substituta de subprocess.Popen que escolhe a
    resposta certa conforme qual script foi invocado."""

    class _ProcessoFake:
        def __init__(self, linhas, returncode):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        script = " ".join(comando)
        for trecho, (linhas, returncode) in respostas_por_script.items():
            if trecho in script:
                return _ProcessoFake(linhas, returncode)
        raise AssertionError(f"Nenhuma resposta mockada para o comando: {script}")

    return _fake


def _criar_projeto_com_fontes_e_transcricoes(projetos_dir, nome="caso_teste"):
    pasta_projeto = projetos_dir / nome
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps({"fontes": [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]}),
        encoding="utf-8",
    )
    (pasta_projeto / "transcricoes").mkdir()
    (pasta_projeto / "transcricoes" / "fonte01.json").write_text(
        json.dumps({"arquivo": "fonte01.mp4", "segmentos": []}), encoding="utf-8"
    )
    return pasta_projeto


# ---------------------------------------------------------------------------
# POST /projetos/<id>/gerar_roteiro
# ---------------------------------------------------------------------------


def test_post_gerar_roteiro_sem_anthropic_api_key_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_fontes_e_transcricoes(projetos_dir)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    # ANTHROPIC_API_KEY deliberadamente nao configurada (fixture autouse
    # _limpar_env_das_variaveis_de_ajustes ja garante isso).

    resposta = client.post("/projetos/caso_teste/gerar_roteiro")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "chave_ausente"


def test_post_gerar_roteiro_sem_etapa2_concluida_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    resposta = client.post("/projetos/caso_sem_transcricao/gerar_roteiro")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "etapa2_nao_concluida"


def test_post_gerar_roteiro_fluxo_feliz_dispara_etapa3(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_fontes_e_transcricoes(projetos_dir)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

    comandos_chamados = []
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "Roteiro gerado com sucesso", "sucesso": true}\n'],
            comandos_chamados=comandos_chamados,
        ),
    )

    resposta = client.post("/projetos/caso_teste/gerar_roteiro")

    assert resposta.status_code == 202
    server._threads["caso_teste"].join(timeout=2)

    assert len(comandos_chamados) == 1
    assert "3_gerar_roteiro.py" in " ".join(comandos_chamados[0])

    job = server.jobs["caso_teste"]
    assert job["status"] == "aguardando_revisao"
    assert job["etapa"] == "roteiro"


def test_post_gerar_roteiro_com_falha_marca_job_como_erro(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_fontes_e_transcricoes(projetos_dir)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-invalida")

    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            [
                '@PROGRESSO {"pct": 0.0, "detalhe": "ERRO: Chave da API Anthropic invalida.", '
                '"sucesso": false, "tipo_erro": "chave_invalida", '
                '"mensagem_usuario": "Chave da API Anthropic invalida. Verifique em console.anthropic.com."}\n'
            ],
            returncode=1,
        ),
    )

    client.post("/projetos/caso_teste/gerar_roteiro")
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["status"] == "erro"
    assert job["erro"] == "Chave da API Anthropic invalida. Verifique em console.anthropic.com."

    job_json = json.loads((projetos_dir / "caso_teste" / "job.json").read_text(encoding="utf-8"))
    assert job_json["status"] == "erro"
    assert job_json["tipo_erro"] == "chave_invalida"


# ---------------------------------------------------------------------------
# Encadeamento automatico: transcricao -> roteiro
# ---------------------------------------------------------------------------


def test_etapa2_com_sucesso_dispara_etapa3_automaticamente(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_fontes_e_transcricoes(projetos_dir)
    (projetos_dir / "caso_teste" / "fontes" / "manifest_fontes.json").write_text(
        json.dumps({"fontes": [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake([]))

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa3", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    client.post("/projetos/caso_teste/transcrever")
    server._threads["caso_teste"].join(timeout=2)

    assert chamadas == [("caso_teste", projetos_dir / "caso_teste")]


def test_etapa2_com_erro_nao_dispara_etapa3(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_fontes_e_transcricoes(projetos_dir)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(
            ['@PROGRESSO {"pct": 0.0, "detalhe": "ERRO: GPU indisponivel", "sucesso": false}\n'],
            returncode=1,
        ),
    )

    chamadas = []
    monkeypatch.setattr(
        server, "_encadear_etapa3", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    client.post("/projetos/caso_teste/transcrever")
    server._threads["caso_teste"].join(timeout=2)

    assert chamadas == []


def test_fluxo_completo_download_transcricao_e_roteiro_ate_aguardando_revisao(
    client, tmp_path, monkeypatch
):
    """Integracao ponta-a-ponta do encadeamento completo: tres subprocess
    mockados em sequencia (1_baixar_videos.py, 2_transcrever.py,
    3_gerar_roteiro.py) - o job final reflete o resultado da Etapa 3
    (aguardando_revisao), nao mais "concluido"."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-fake")

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
        if "2_transcrever.py" in script:
            # Como o subprocess e' totalmente mockado, o script real nunca
            # roda - grava manualmente o arquivo de transcricao que a
            # Etapa 3 (tambem mockada) espera encontrar em disco.
            pasta_projeto = tmp_path / "projetos" / "caso_teste"
            (pasta_projeto / "entrada").mkdir(parents=True, exist_ok=True)
            (pasta_projeto / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
            (pasta_projeto / "transcricoes").mkdir(exist_ok=True)
            (pasta_projeto / "transcricoes" / "fonte01.json").write_text(
                json.dumps({"arquivo": "fonte01.mp4", "segmentos": []}), encoding="utf-8"
            )
            return _ProcessoFake(
                ['@PROGRESSO {"pct": 100.0, "detalhe": "1 video(s) transcrito(s) com sucesso", "sucesso": true}\n'],
                0,
            )
        return _ProcessoFake(
            ['@PROGRESSO {"pct": 100.0, "detalhe": "Roteiro gerado com sucesso", "sucesso": true}\n'],
            0,
        )

    monkeypatch.setattr(server.subprocess, "Popen", _popen_por_etapa)

    client.post(
        "/novo",
        data={"nome": "caso_teste", "links": "https://youtube.com/watch?v=abc", "perfil": "truecrime"},
    )
    server._threads["caso_teste"].join(timeout=2)

    job = server.jobs["caso_teste"]
    assert job["etapa"] == "roteiro"
    assert job["status"] == "aguardando_revisao"

    job_json = json.loads((projetos_dir / "caso_teste" / "job.json").read_text(encoding="utf-8"))
    assert job_json["etapa_atual"] == "roteiro"
    assert job_json["status"] == "aguardando_revisao"


# ---------------------------------------------------------------------------
# Tela de status - link "Revisar roteiro"
# ---------------------------------------------------------------------------


def test_status_html_mostra_link_revisar_roteiro_quando_aguardando_revisao(client):
    server.jobs["caso_aguardando"] = {
        "etapa": "roteiro",
        "status": "aguardando_revisao",
        "pct": 100.0,
        "detalhe": "Roteiro gerado com sucesso",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/status/caso_aguardando")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "link-revisar-roteiro" in pagina
    assert "/projetos/caso_aguardando/revisar_roteiro" in pagina
    trecho = pagina.split('id="status-aguardando-revisao"')[1].split(">")[0]
    assert "oculto" not in trecho


def test_status_html_link_revisar_roteiro_fica_oculto_fora_do_estado_aguardando_revisao(client):
    server.jobs["caso_em_andamento"] = {
        "etapa": "roteiro",
        "status": "em_andamento",
        "pct": 30.0,
        "detalhe": "Gerando roteiro com IA...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/status/caso_em_andamento")
    pagina = resposta.get_data(as_text=True)

    # O bloco fica sempre no DOM (para o polling JS poder mostra-lo sem
    # esperar reload da pagina quando o status muda em tempo real - ver
    # static/status.js), so' escondido via classe "oculto" quando o job
    # nao esta aguardando revisao.
    trecho = pagina.split('id="status-aguardando-revisao"')[1].split(">")[0]
    assert "oculto" in trecho


def test_revisar_roteiro_mostra_conteudo_do_roteiro_gerado(client, tmp_path, monkeypatch):
    """A tela completa (Sessao 7 - CLAUDE.md secao 5.5) superou o stub da
    Sessao 6: so abre para projetos em aguardando_revisao/aguardando_audio
    (ver tests/test_revisar_roteiro.py para a cobertura completa da tela
    nova) - aqui so confirma que o conteudo do roteiro.md e dos titulos
    sugeridos aparece na pagina quando o status permite."""
    projetos_dir = tmp_path / "projetos"
    pasta_projeto = projetos_dir / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta_projeto / "roteiro.md").write_text("Este e o roteiro final gerado.", encoding="utf-8")
    (pasta_projeto / "titulos_sugeridos.json").write_text(
        json.dumps({"titulos": ["Titulo 1", "Titulo 2", "Titulo 3"], "descricoes": ["a", "b", "c"]}),
        encoding="utf-8",
    )
    (pasta_projeto / "job.json").write_text(
        json.dumps({"status": "aguardando_revisao", "etapa_atual": "revisao"}), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_teste/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Este e o roteiro final gerado." in pagina
    assert "Titulo 1" in pagina


def test_revisar_roteiro_status_errado_redireciona_para_status(client, tmp_path, monkeypatch):
    """Sem job.json (ou com status fora de aguardando_revisao/aguardando_audio)
    a tela completa nao abre - redireciona para /status/<id> em vez de
    mostrar uma pagina vazia/quebrada (comportamento do stub antigo)."""
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_sem_roteiro/revisar_roteiro")

    assert resposta.status_code == 302
    assert resposta.headers["Location"].startswith("/status/caso_sem_roteiro")
