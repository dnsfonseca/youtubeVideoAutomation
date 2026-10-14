"""Testes das rotas do server.py para a marca d'agua do CANAL (sessao
"Marca d'agua do canal aplicada ao video final"):

- GRUPO A: upload/remocao/preview da marca GLOBAL em /ajustes.
- GRUPO B: sobrescrita por projeto no formulario de Novo projeto (POST /novo
  e o caminho "videos_pre_gerados").

scripts/6_montar_video.py (resolucao/aplicacao real via ffmpeg) tem suite
propria em tests/test_montar_video.py - aqui so' as rotas Flask (upload,
validacao de formulario, persistencia em disco).
"""

import io
import json

import pytest
from PIL import Image

import server


def _png_bytes(com_alfa=True):
    buffer = io.BytesIO()
    modo = "RGBA" if com_alfa else "RGB"
    Image.new(modo, (100, 60), (10, 20, 30, 128) if com_alfa else (10, 20, 30)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


@pytest.fixture(autouse=True)
def _marca_dagua_global_isolada(tmp_path, monkeypatch):
    """Mesma isolacao de tests/test_montar_video.py - nunca deixar um teste
    tocar em config/marca_dagua_canal.png do repo real."""
    monkeypatch.setattr(server, "PASTA_CONFIG_GLOBAL", tmp_path / "_config_isolado")
    monkeypatch.setattr(
        server, "ARQUIVO_MARCA_DAGUA_GLOBAL", tmp_path / "_config_isolado" / "marca_dagua_canal.png"
    )
    monkeypatch.setattr(
        server, "ARQUIVO_MARCA_DAGUA_GLOBAL_META", tmp_path / "_config_isolado" / "marca_dagua_canal.json"
    )


def _popen_fake(linhas=(), returncode=0):
    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    return lambda comando, **kwargs: _ProcessoFake()


# ---------------------------------------------------------------------------
# GRUPO A - Ajustes: upload/remocao/preview da marca GLOBAL
# ---------------------------------------------------------------------------


def test_ajustes_get_sem_marca_configurada_nao_quebra(client):
    resposta = client.get("/ajustes")

    assert resposta.status_code == 200


def test_upload_marca_dagua_sem_arquivo_retorna_400(client):
    resposta = client.post("/ajustes/marca_dagua/upload", data={}, content_type="multipart/form-data")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "arquivo_ausente"


def test_upload_marca_dagua_extensao_invalida_retorna_400(client):
    resposta = client.post(
        "/ajustes/marca_dagua/upload",
        data={"arquivo": (io.BytesIO(b"nao e' png"), "logo.jpg")},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "extensao_invalida"


def test_upload_marca_dagua_conteudo_corrompido_retorna_400(client):
    resposta = client.post(
        "/ajustes/marca_dagua/upload",
        data={"arquivo": (io.BytesIO(b"isto tem extensao .png mas nao e' um png de verdade"), "logo.png")},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "png_invalido"


def test_upload_marca_dagua_sucesso_com_alfa_persiste_arquivo_e_metadata(client, tmp_path):
    resposta = client.post(
        "/ajustes/marca_dagua/upload",
        data={"arquivo": (_png_bytes(com_alfa=True), "logo_canal.png")},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["tem_alfa"] is True
    assert dados["aviso"] is None

    assert server.ARQUIVO_MARCA_DAGUA_GLOBAL.exists()
    metadata = json.loads(server.ARQUIVO_MARCA_DAGUA_GLOBAL_META.read_text(encoding="utf-8"))
    assert metadata["tem_alfa"] is True
    assert metadata["nome_original"] == "logo_canal.png"


def test_upload_marca_dagua_sem_alfa_avisa_mas_nao_bloqueia(client):
    resposta = client.post(
        "/ajustes/marca_dagua/upload",
        data={"arquivo": (_png_bytes(com_alfa=False), "logo_opaco.png")},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["tem_alfa"] is False
    assert dados["aviso"] is not None
    assert server.ARQUIVO_MARCA_DAGUA_GLOBAL.exists()


def test_ajustes_marca_dagua_arquivo_404_sem_marca_configurada(client):
    resposta = client.get("/ajustes/marca_dagua/arquivo")

    assert resposta.status_code == 404


def test_ajustes_marca_dagua_arquivo_200_apos_upload(client):
    client.post(
        "/ajustes/marca_dagua/upload",
        data={"arquivo": (_png_bytes(), "logo.png")},
        content_type="multipart/form-data",
    )

    resposta = client.get("/ajustes/marca_dagua/arquivo")

    assert resposta.status_code == 200


def test_remover_marca_dagua_apaga_arquivo_e_metadata(client):
    client.post(
        "/ajustes/marca_dagua/upload",
        data={"arquivo": (_png_bytes(), "logo.png")},
        content_type="multipart/form-data",
    )
    assert server.ARQUIVO_MARCA_DAGUA_GLOBAL.exists()

    resposta = client.post("/ajustes/marca_dagua/remover")

    assert resposta.status_code == 200
    assert resposta.get_json()["sucesso"] is True
    assert not server.ARQUIVO_MARCA_DAGUA_GLOBAL.exists()
    assert not server.ARQUIVO_MARCA_DAGUA_GLOBAL_META.exists()


def test_remover_marca_dagua_sem_marca_e_idempotente(client):
    resposta = client.post("/ajustes/marca_dagua/remover")

    assert resposta.status_code == 200
    assert resposta.get_json()["sucesso"] is True


# ---------------------------------------------------------------------------
# GRUPO B - sobrescrita por projeto (POST /novo, pipeline_completa)
# ---------------------------------------------------------------------------


def test_novo_projeto_marca_dagua_projeto_invalida_retorna_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_marca_invalida",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "marca_dagua_projeto": "valor_bagunçado",
        },
    )

    assert resposta.status_code == 400
    assert "caso_marca_invalida" not in server.jobs


def test_novo_projeto_marca_outra_sem_arquivo_retorna_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_marca_sem_arquivo",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "marca_dagua_projeto": "outra",
        },
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina


def test_novo_projeto_marca_outra_com_png_valido_persiste_arquivo_e_config(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_marca_propria",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "marca_dagua_projeto": "outra",
            "marca_dagua_arquivo": (_png_bytes(), "minha_marca.png"),
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_marca_propria"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_marca_propria"
    assert (pasta_projeto / "entrada" / "marca_dagua_canal.png").exists()
    config_video = json.loads((pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    assert config_video["marca_dagua_projeto"] == "outra"


def test_novo_projeto_default_marca_dagua_projeto_e_canal(client, tmp_path, monkeypatch):
    """Sem o radio marcado explicitamente (ou form antigo sem o campo),
    cai em "canal" - retrocompatibilidade."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_marca_default",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_marca_default"].join(timeout=2)

    config_video = json.loads(
        (projetos_dir / "caso_marca_default" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["marca_dagua_projeto"] == "canal"


def test_novo_projeto_marca_nenhuma_persiste_config(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_marca_nenhuma",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "marca_dagua_projeto": "nenhuma",
        },
    )

    assert resposta.status_code == 302
    server._threads["caso_marca_nenhuma"].join(timeout=2)

    config_video = json.loads(
        (projetos_dir / "caso_marca_nenhuma" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["marca_dagua_projeto"] == "nenhuma"
    assert not (projetos_dir / "caso_marca_nenhuma" / "entrada" / "marca_dagua_canal.png").exists()


# ---------------------------------------------------------------------------
# GRUPO B/D - "videos_pre_gerados" tambem aceita a sobrescrita
# ---------------------------------------------------------------------------


def test_novo_projeto_videos_pre_gerados_marca_outra_persiste_arquivo(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "5.0"})())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_vpg_marca",
            "perfil": "truecrime",
            "tipo_projeto": "videos_pre_gerados",
            "videos_pre_gerados[]": [(io.BytesIO(b"fake video bytes"), "1_clipe.mp4")],
            "marca_dagua_projeto": "outra",
            "marca_dagua_arquivo": (_png_bytes(), "minha_marca.png"),
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_vpg_marca"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_vpg_marca"
    assert (pasta_projeto / "entrada" / "marca_dagua_canal.png").exists()
    config_video = json.loads((pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    assert config_video["marca_dagua_projeto"] == "outra"
