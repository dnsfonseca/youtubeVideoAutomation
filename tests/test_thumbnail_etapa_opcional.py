"""Testes do Grupo C (sessao de fundo por IA/5o template) - Etapa 7
(thumbnail) opcional por projeto: `entrada/configuracao_video.json`
`gerar_thumbnail` (default True, retrocompat total com projetos sem o
campo). Desligada, o projeto pula direto de "montagem" pra "concluido"
sem passar por "aguardando_thumbnail" - `scripts/7_thumbnail.py` nunca e'
disparado. `_parsear_pipeline_steps` filtra o circulo "thumbnail" da
barra horizontal nesse caso, sem alterar PIPELINE_ETAPAS (constante
global inalterada).

Nenhum destes testes chama subprocess de verdade (CLAUDE.md secao 8) -
`server.subprocess.Popen` e' sempre mockado."""

import json

import server


def _popen_fake(returncode=0, linhas=()):
    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        return _ProcessoFake()

    return _fake


def _projeto(tmp_path, nome, gerar_thumbnail=None):
    pasta = tmp_path / nome
    (pasta / "entrada").mkdir(parents=True)
    if gerar_thumbnail is not None:
        (pasta / "entrada" / "configuracao_video.json").write_text(
            json.dumps({"legendas_queimadas": False, "com_musica_fundo": False, "gerar_thumbnail": gerar_thumbnail}),
            encoding="utf-8",
        )
    (pasta / "job.json").write_text(
        json.dumps({"nome": nome, "status": "em_andamento", "etapa_atual": "geracao_clipes"}), encoding="utf-8"
    )
    return pasta


# ---------------------------------------------------------------------------
# _ler_configuracao_video - default e leitura do campo
# ---------------------------------------------------------------------------


def test_ler_configuracao_video_sem_arquivo_gerar_thumbnail_default_true(tmp_path):
    """Projeto criado ANTES desta feature (configuracao_video.json sem o
    campo, ou ausente) tem que continuar gerando thumbnail - comportamento
    historico preservado."""
    pasta = tmp_path / "projeto_antigo"
    (pasta / "entrada").mkdir(parents=True)
    assert server._ler_configuracao_video(pasta)["gerar_thumbnail"] is True


def test_ler_configuracao_video_campo_ausente_no_json_default_true(tmp_path):
    pasta = tmp_path / "projeto_sem_campo"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"legendas_queimadas": False}), encoding="utf-8"
    )
    assert server._ler_configuracao_video(pasta)["gerar_thumbnail"] is True


def test_ler_configuracao_video_gerar_thumbnail_false_e_lido(tmp_path):
    pasta = _projeto(tmp_path, "projeto_sem_thumb", gerar_thumbnail=False)
    assert server._ler_configuracao_video(pasta)["gerar_thumbnail"] is False


# ---------------------------------------------------------------------------
# _executar_etapa6 - encadeamento condicional
# ---------------------------------------------------------------------------


def test_executar_etapa6_com_thumbnail_ligada_encadeia_etapa7(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path, "com_thumb", gerar_thumbnail=True)
    server.jobs["com_thumb"] = server._job_inicial_etapa6()
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(returncode=0))

    chamadas_etapa7 = []
    chamadas_pular = []
    monkeypatch.setattr(server, "_encadear_etapa7", lambda pid, p: chamadas_etapa7.append(pid))
    monkeypatch.setattr(server, "_pular_etapa7_e_concluir", lambda pid, p: chamadas_pular.append(pid))

    server._executar_etapa6("com_thumb", pasta)

    assert chamadas_etapa7 == ["com_thumb"]
    assert chamadas_pular == []


def test_executar_etapa6_com_thumbnail_desligada_pula_pro_concluido(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path, "sem_thumb", gerar_thumbnail=False)
    server.jobs["sem_thumb"] = server._job_inicial_etapa6()
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(returncode=0))

    chamadas_etapa7 = []
    monkeypatch.setattr(server, "_encadear_etapa7", lambda pid, p: chamadas_etapa7.append(pid))

    server._executar_etapa6("sem_thumb", pasta)

    assert chamadas_etapa7 == []
    assert server.jobs["sem_thumb"]["status"] == "concluido"

    job_disco = json.loads((pasta / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "concluido"
    assert job_disco["etapa_atual"] == "concluido"


def test_executar_etapa6_falha_no_subprocess_nunca_pula_pro_concluido(tmp_path, monkeypatch):
    """Mesmo com gerar_thumbnail=False, uma FALHA na montagem (Etapa 6)
    tem que continuar virando status="erro" - a etapa opcional so' se
    aplica no caminho de SUCESSO."""
    pasta = _projeto(tmp_path, "falha_sem_thumb", gerar_thumbnail=False)
    server.jobs["falha_sem_thumb"] = server._job_inicial_etapa6()
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(returncode=1))

    server._executar_etapa6("falha_sem_thumb", pasta)

    assert server.jobs["falha_sem_thumb"]["status"] == "erro"


# ---------------------------------------------------------------------------
# _executar_etapa7 - bug corrigido pos-Sessao 23: o subprocess podia sair
# com returncode != 0 (caso real: ModuleNotFoundError do import quebrado em
# scripts/7_thumbnail.py rodando como subprocess) e o status virava
# "aguardando_thumbnail" incondicionalmente, escondendo que a etapa nao
# rodou. "Nunca falhar o job" continua valendo (status NUNCA vira "erro"
# aqui - o video final ja esta pronto), mas job["etapa7_falhou"] agora
# distingue os dois casos.
# ---------------------------------------------------------------------------


def test_executar_etapa7_sucesso_marca_etapa7_falhou_false(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path, "thumb_sucesso")
    server.jobs["thumb_sucesso"] = server._job_inicial_etapa7()
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake(returncode=0))

    server._executar_etapa7("thumb_sucesso", pasta)

    job = server.jobs["thumb_sucesso"]
    assert job["status"] == "aguardando_thumbnail"
    assert job["etapa7_falhou"] is False
    assert job.get("mensagem_usuario") is None

    job_disco = json.loads((pasta / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "aguardando_thumbnail"
    assert job_disco["etapa7_falhou"] is False
    assert job_disco["mensagem_usuario"] is None


def test_executar_etapa7_subprocess_falha_marca_etapa7_falhou_true_mas_nao_vira_erro(tmp_path, monkeypatch):
    """Status NUNCA pode virar "erro" aqui (travaria o pipeline com o
    video final ja pronto) - mas a falha nao pode mais ficar escondida."""
    pasta = _projeto(tmp_path, "thumb_falha")
    server.jobs["thumb_falha"] = server._job_inicial_etapa7()
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        _popen_fake(returncode=1, linhas=["ModuleNotFoundError: No module named 'scripts'\n"]),
    )

    server._executar_etapa7("thumb_falha", pasta)

    job = server.jobs["thumb_falha"]
    assert job["status"] == "aguardando_thumbnail"
    assert job["etapa7_falhou"] is True
    assert job["mensagem_usuario"]
    assert job["tipo_erro"]
    assert "ModuleNotFoundError" in "\n".join(job["log"])

    job_disco = json.loads((pasta / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "aguardando_thumbnail"
    assert job_disco["etapa7_falhou"] is True
    assert job_disco["mensagem_usuario"]
    assert job_disco["log_erro"]


def test_executar_etapa7_falha_ao_iniciar_subprocess_marca_etapa7_falhou_true(tmp_path, monkeypatch):
    pasta = _projeto(tmp_path, "thumb_falha_iniciar")
    server.jobs["thumb_falha_iniciar"] = server._job_inicial_etapa7()

    def _popen_levanta(comando, **kwargs):
        raise OSError("arquivo nao encontrado")

    monkeypatch.setattr(server.subprocess, "Popen", _popen_levanta)

    server._executar_etapa7("thumb_falha_iniciar", pasta)

    job = server.jobs["thumb_falha_iniciar"]
    assert job["status"] == "aguardando_thumbnail"
    assert job["etapa7_falhou"] is True
    assert "arquivo nao encontrado" in job["mensagem_usuario"]


# ---------------------------------------------------------------------------
# POST /projetos/<id>/gerar_thumbnail - retry manual da Etapa 7 (bug 1/3
# pos-Sessao 23). Ao contrario de montar_video_rota/transcrever, aceita
# rodar mesmo com o projeto ja em "aguardando_thumbnail" - e' exatamente
# esse status que uma falha de etapa 7 deixa o projeto.
# ---------------------------------------------------------------------------


def test_post_gerar_thumbnail_sem_video_final_retorna_400(client, tmp_path, monkeypatch):
    pasta = _projeto(tmp_path, "sem_video_final")
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path))

    resposta = client.post("/projetos/sem_video_final/gerar_thumbnail")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "etapa6_nao_concluida"


def test_post_gerar_thumbnail_com_video_final_dispara_etapa7(client, tmp_path, monkeypatch):
    pasta = _projeto(tmp_path, "com_video_final", gerar_thumbnail=True)
    (pasta / "saida").mkdir()
    (pasta / "saida" / "video_final.mp4").write_bytes(b"fake")
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path))

    chamadas = []
    monkeypatch.setattr(server, "_disparar_etapa7", lambda pid, p: chamadas.append(pid))

    resposta = client.post("/projetos/com_video_final/gerar_thumbnail")

    assert resposta.status_code == 202
    assert chamadas == ["com_video_final"]


def test_post_gerar_thumbnail_permite_retry_mesmo_ja_aguardando_thumbnail(client, tmp_path, monkeypatch):
    """Diferente das outras rotas de retry manual (montar_video_rota etc) -
    esta rota nao pode exigir um status diferente do atual, porque
    "aguardando_thumbnail" com etapa7_falhou=True e' exatamente o estado
    que precisa poder disparar o retry."""
    pasta = _projeto(tmp_path, "retry_ja_aguardando", gerar_thumbnail=True)
    (pasta / "saida").mkdir()
    (pasta / "saida" / "video_final.mp4").write_bytes(b"fake")
    (pasta / "job.json").write_text(
        json.dumps({"nome": "retry_ja_aguardando", "status": "aguardando_thumbnail", "etapa7_falhou": True}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path))

    chamadas = []
    monkeypatch.setattr(server, "_disparar_etapa7", lambda pid, p: chamadas.append(pid))

    resposta = client.post("/projetos/retry_ja_aguardando/gerar_thumbnail")

    assert resposta.status_code == 202
    assert chamadas == ["retry_ja_aguardando"]


# ---------------------------------------------------------------------------
# _parsear_pipeline_steps - filtra o circulo "thumbnail"
# ---------------------------------------------------------------------------


def test_pipeline_steps_thumbnail_desligada_remove_o_passo(app, tmp_path):
    pasta = _projeto(tmp_path, "proj_sem_thumb_steps", gerar_thumbnail=False)
    estado = {"etapa": "montagem", "status": "concluido"}

    with app.test_request_context():
        passos = server._parsear_pipeline_steps(estado, pasta, "proj_sem_thumb_steps")

    nomes = [p["nome"] for p in passos]
    assert "thumbnail" not in nomes
    assert len(passos) == len(server.PIPELINE_ETAPAS) - 1
    # numeracao dos passos restantes continua sequencial 1..N (thumbnail e'
    # sempre o ultimo item de PIPELINE_ETAPAS - filtra-lo nunca abre buraco).
    assert [p["numero"] for p in passos] == list(range(1, len(passos) + 1))


def test_pipeline_steps_thumbnail_ligada_mantem_o_passo(app, tmp_path):
    pasta = _projeto(tmp_path, "proj_com_thumb_steps", gerar_thumbnail=True)
    estado = {"etapa": "montagem", "status": "concluido"}

    with app.test_request_context():
        passos = server._parsear_pipeline_steps(estado, pasta, "proj_com_thumb_steps")

    assert "thumbnail" in [p["nome"] for p in passos]
    assert len(passos) == len(server.PIPELINE_ETAPAS)


def test_pipeline_steps_projeto_antigo_sem_configuracao_mantem_thumbnail(app, tmp_path):
    """Retrocompat: projeto sem entrada/configuracao_video.json (criado
    antes desta feature) continua mostrando o circulo thumbnail."""
    pasta = tmp_path / "projeto_bem_antigo"
    (pasta / "entrada").mkdir(parents=True)
    estado = {"etapa": "thumbnail", "status": "aguardando_thumbnail"}

    with app.test_request_context():
        passos = server._parsear_pipeline_steps(estado, pasta, "projeto_bem_antigo")

    assert "thumbnail" in [p["nome"] for p in passos]


def test_pipeline_steps_sem_pasta_projeto_mantem_thumbnail():
    """pasta_projeto=None (nenhum chamador real omite hoje, mas mantem
    retrocompatibilidade) nunca filtra - sem como saber a configuracao do
    projeto, cai no comportamento historico."""
    estado = {"etapa": "montagem", "status": "concluido"}
    passos = server._parsear_pipeline_steps(estado, pasta_projeto=None, projeto_id=None)
    assert "thumbnail" in [p["nome"] for p in passos]


# ---------------------------------------------------------------------------
# Projeto antigo em aguardando_thumbnail continua funcionando (nao existe
# migracao que regrida esse estado - CLAUDE.md, mesmo espirito do teste
# ja existente test_ler_job_json_concluido_nunca_regride_para_aguardando_thumbnail
# em test_novo_e_status.py).
# ---------------------------------------------------------------------------


def test_projeto_antigo_aguardando_thumbnail_le_normalmente(tmp_path):
    pasta = tmp_path / "projeto_pausado_thumb"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"nome": "projeto_pausado_thumb", "status": "aguardando_thumbnail", "etapa_atual": "thumbnail"}),
        encoding="utf-8",
    )

    job_disco = server._ler_job_json(pasta)

    assert job_disco["status"] == "aguardando_thumbnail"
    assert job_disco["etapa_atual"] == "thumbnail"
    # config ausente = gerar_thumbnail True (nao ha conflito: este projeto
    # ja passou pela Etapa 7 e esta esperando revisao manual dela).
    assert server._ler_configuracao_video(pasta)["gerar_thumbnail"] is True
