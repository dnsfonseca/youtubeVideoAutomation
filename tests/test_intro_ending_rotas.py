"""Testes das rotas do server.py para intro/ending anexados ao video final
(secao "Intro e ending anexados ao video final"):

- GRUPO A: upload/validacao no formulario de Novo projeto (pipeline completa
  e "videos_pre_gerados").
- GRUPO F: blocos fixos (posicao travada) na tela de reorganizacao de
  clipes.

scripts/6_montar_video.py (normalizacao/concatenacao real via ffmpeg) tem
suite propria em tests/test_montar_video.py - aqui so' as rotas Flask
(upload, validacao de formulario, persistencia em disco, renderizacao de
template). CLAUDE.md secao 8 - nenhuma chamada real a ffmpeg/ffprobe
(sempre monkeypatch em server.subprocess.run/Popen)."""

import io
import json

import server


def _popen_fake(linhas=(), returncode=0):
    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    return lambda comando, **kwargs: _ProcessoFake()


def _ffprobe_video_legivel_fake(duracao_s=5.0):
    """Mock de `subprocess.run` que responde como um ffprobe real pra um
    video legivel de `duracao_s` segundos - cobre tanto
    `validar_video_legivel_ffprobe` (formato `default=noprint_wrappers=1`)
    quanto `_obter_duracao_video_ffprobe` (formato `nokey=1`, usado em
    outros pontos do formulario)."""

    def _run(cmd, *args, **kwargs):
        resultado = type("R", (), {})()
        resultado.returncode = 0
        if "-of" in cmd and cmd[cmd.index("-of") + 1].startswith("default=noprint_wrappers=1"):
            resultado.stdout = f"codec_type=video\nduration={duracao_s}\n"
        else:
            resultado.stdout = str(duracao_s)
        return resultado

    return _run


# ---------------------------------------------------------------------------
# GRUPO A - upload no formulario de Novo projeto (pipeline_completa)
# ---------------------------------------------------------------------------


def test_novo_projeto_intro_extensao_invalida_retorna_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_intro_extensao_invalida",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "intro_arquivo": (io.BytesIO(b"nao e' video"), "intro.avi"),
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "caso_intro_extensao_invalida" not in server.jobs


def test_novo_projeto_intro_ilegivel_ffprobe_retorna_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    def _run_falha(cmd, *args, **kwargs):
        resultado = type("R", (), {})()
        resultado.returncode = 1
        resultado.stdout = ""
        return resultado

    monkeypatch.setattr(server.subprocess, "run", _run_falha)

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_intro_ilegivel",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "intro_arquivo": (io.BytesIO(b"lixo, nao e' um mp4 de verdade"), "intro.mp4"),
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "caso_intro_ilegivel" not in server.jobs


def test_novo_projeto_intro_e_ending_validos_persistem_arquivos(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())
    monkeypatch.setattr(server.subprocess, "run", _ffprobe_video_legivel_fake(duracao_s=4.0))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_intro_ending_ok",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "intro_arquivo": (io.BytesIO(b"fake mp4 bytes"), "minha_intro.mp4"),
            "ending_arquivo": (io.BytesIO(b"fake mov bytes"), "meu_ending.mov"),
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_intro_ending_ok"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_intro_ending_ok"
    assert (pasta_projeto / "entrada" / "intro.mp4").exists()
    assert (pasta_projeto / "entrada" / "ending.mov").exists()


def test_novo_projeto_sem_intro_nem_ending_nao_cria_arquivos(client, tmp_path, monkeypatch):
    """Nao-regressao: campos opcionais ausentes - nenhum arquivo de
    intro/ending e' criado, nenhum erro."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sem_intro_ending",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_sem_intro_ending"].join(timeout=2)

    pasta_entrada = projetos_dir / "caso_sem_intro_ending" / "entrada"
    assert not (pasta_entrada / "intro.mp4").exists()
    assert not (pasta_entrada / "ending.mp4").exists()


def test_novo_projeto_erro_por_outro_motivo_nao_deixa_temp_orfao(client, tmp_path, monkeypatch):
    """Intro valida, mas o formulario falha por outro motivo (link
    invalido) - o arquivo temporario da intro (ja validado com sucesso) e'
    descartado, nunca vaza pro disco."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    monkeypatch.setattr(server.subprocess, "run", _ffprobe_video_legivel_fake(duracao_s=4.0))

    import tempfile

    arquivos_temp_antes = set(__import__("pathlib").Path(tempfile.gettempdir()).glob("broll_intro_*"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_link_invalido_com_intro",
            "links": "isto-nao-e-um-link-do-youtube",
            "perfil": "truecrime",
            "intro_arquivo": (io.BytesIO(b"fake mp4 bytes"), "intro.mp4"),
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200

    arquivos_temp_depois = set(__import__("pathlib").Path(tempfile.gettempdir()).glob("broll_intro_*"))
    assert arquivos_temp_depois - arquivos_temp_antes == set()


# ---------------------------------------------------------------------------
# GRUPO A/G - "videos_pre_gerados" tambem aceita intro/ending
# ---------------------------------------------------------------------------


def test_novo_projeto_videos_pre_gerados_intro_persiste_arquivo(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())
    monkeypatch.setattr(server.subprocess, "run", _ffprobe_video_legivel_fake(duracao_s=3.0))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_vpg_intro",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [(io.BytesIO(b"fake video bytes"), "1_clipe.mp4")],
            "intro_arquivo": (io.BytesIO(b"fake mp4 bytes"), "intro.mp4"),
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_vpg_intro"].join(timeout=2)

    assert (projetos_dir / "caso_vpg_intro" / "entrada" / "intro.mp4").exists()


# ---------------------------------------------------------------------------
# GRUPO F - blocos fixos na tela de reorganizacao de clipes
# ---------------------------------------------------------------------------


def _criar_projeto_com_clipes(tmp_path, nome, clipes, status="aguardando_reorganizacao", com_intro=False, com_ending=False):
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "clipes").mkdir(parents=True)
    (pasta / "clipes" / "indice.json").write_text(
        json.dumps({"clipes": clipes}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (pasta / "job.json").write_text(
        json.dumps({"projeto_id": nome, "status": status, "etapa_atual": "geracao_clipes"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (pasta / "entrada").mkdir(parents=True, exist_ok=True)
    if com_intro:
        (pasta / "entrada" / "intro.mp4").write_bytes(b"fake")
    if com_ending:
        (pasta / "entrada" / "ending.mp4").write_bytes(b"fake")
    return projetos_dir


def _clipe(clipe_id, duracao_s=8.0):
    return {"clipe_id": clipe_id, "arquivo": f"{clipe_id}.mp4", "duracao_s": duracao_s}


def test_reorganizar_clipes_sem_intro_ending_nao_renderiza_blocos_fixos(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_com_clipes(tmp_path, "caso_sem_fixos", [_clipe("c0")])),
    )

    resposta = client.get("/projetos/caso_sem_fixos/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'class="timeline-fixo"' not in pagina


def test_reorganizar_clipes_com_intro_e_ending_renderiza_blocos_fixos_nao_arrastaveis(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_com_clipes(
                tmp_path, "caso_com_fixos", [_clipe("c0")], com_intro=True, com_ending=True
            )
        ),
    )
    monkeypatch.setattr(server.subprocess, "run", _ffprobe_video_legivel_fake(duracao_s=4.0))

    resposta = client.get("/projetos/caso_com_fixos/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert pagina.count('class="timeline-fixo"') == 2
    assert 'draggable="false"' in pagina
    assert "Intro" in pagina
    assert "Ending" in pagina


def test_descobrir_intro_ending_info_projeto_antigo_sem_campos_nao_quebra(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)

    resultado = server._descobrir_intro_ending_info(pasta_projeto)

    assert resultado == {"intro": None, "ending": None}
