"""Testes do item 4 da sessao de correcoes de composicao/interface:
job.json ausente/corrompido com artefatos reais em disco mostrava
"Projeto sem dados persistidos" e pipeline vazia, sem nenhuma forma de
recuperar pela propria tela - mesmo com saida/video_final.mp4 de 1.3GB +
roteiro_aprovado.md + narracao.mp3 presentes. Cobre
`_detectar_estagio_por_artefatos` (server.py) e a rota
`POST /projetos/<id>/reconstruir_estado`."""

import json

import server


def test_detectar_estagio_sem_artefato_nenhum_devolve_none(tmp_path):
    pasta = tmp_path / "vazio"
    pasta.mkdir()
    assert server._detectar_estagio_por_artefatos(pasta) is None


def test_detectar_estagio_pasta_inexistente_devolve_none(tmp_path):
    assert server._detectar_estagio_por_artefatos(tmp_path / "nao_existe") is None


def test_detectar_estagio_roteiro_md_aponta_aguardando_revisao(tmp_path):
    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "roteiro.md").write_text("Roteiro gerado.", encoding="utf-8")
    assert server._detectar_estagio_por_artefatos(pasta) == "aguardando_revisao"


def test_detectar_estagio_roteiro_aprovado_aponta_aguardando_audio(tmp_path):
    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "roteiro.md").write_text("Roteiro gerado.", encoding="utf-8")
    (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")
    assert server._detectar_estagio_por_artefatos(pasta) == "aguardando_audio"


def test_detectar_estagio_clipes_gerados_aponta_aguardando_reorganizacao(tmp_path):
    pasta = tmp_path / "projeto"
    (pasta / "clipes").mkdir(parents=True)
    (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")
    (pasta / "clipes" / "indice.json").write_text(
        json.dumps({"clipes": [{"clipe_id": "clipe001"}]}), encoding="utf-8"
    )
    assert server._detectar_estagio_por_artefatos(pasta) == "aguardando_reorganizacao"


def test_detectar_estagio_video_final_aponta_aguardando_thumbnail(tmp_path):
    pasta = tmp_path / "projeto"
    (pasta / "saida").mkdir(parents=True)
    (pasta / "saida" / "video_final.mp4").write_bytes(b"fake video")
    assert server._detectar_estagio_por_artefatos(pasta) == "aguardando_thumbnail"


def test_detectar_estagio_thumbnail_final_aponta_concluido(tmp_path):
    pasta = tmp_path / "projeto"
    (pasta / "thumbnail").mkdir(parents=True)
    (pasta / "thumbnail" / "final.jpg").write_bytes(b"fake jpg")
    assert server._detectar_estagio_por_artefatos(pasta) == "concluido"


def test_reconstruir_estado_projeto_inexistente_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    resposta = client.post("/projetos/nao_existe/reconstruir_estado")
    assert resposta.status_code == 404


def test_reconstruir_estado_job_json_valido_recusa(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta = projetos_dir / "caso_job_valido"
    pasta.mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"status": "em_andamento", "etapa_atual": "download"}), encoding="utf-8"
    )

    resposta = client.post("/projetos/caso_job_valido/reconstruir_estado")
    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "job_json_valido"


def test_reconstruir_estado_sem_artefato_nenhum_recusa(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta = projetos_dir / "caso_sem_artefato"
    pasta.mkdir(parents=True)

    resposta = client.post("/projetos/caso_sem_artefato/reconstruir_estado")
    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "nada_para_reconstruir"


def test_reconstruir_estado_video_final_grava_aguardando_thumbnail(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta = projetos_dir / "caso_video_final"
    (pasta / "saida").mkdir(parents=True)
    (pasta / "saida" / "video_final.mp4").write_bytes(b"fake video" * 1000)
    (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")
    (pasta / "narracao.mp3").write_bytes(b"fake mp3")

    resposta = client.post("/projetos/caso_video_final/reconstruir_estado")
    dados = resposta.get_json()

    assert resposta.status_code == 200
    assert dados["sucesso"] is True
    assert dados["estagio"] == "aguardando_thumbnail"
    assert dados["redirect"] == "/status/caso_video_final"

    job_reconstruido = json.loads((pasta / "job.json").read_text(encoding="utf-8"))
    assert job_reconstruido["status"] == "aguardando_thumbnail"
    assert job_reconstruido["etapa_atual"] == "thumbnail"


def test_reconstruir_estado_thumbnail_final_grava_concluido_e_redireciona(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta = projetos_dir / "caso_concluido"
    (pasta / "thumbnail").mkdir(parents=True)
    (pasta / "thumbnail" / "final.jpg").write_bytes(b"fake jpg")

    resposta = client.post("/projetos/caso_concluido/reconstruir_estado")
    dados = resposta.get_json()

    assert resposta.status_code == 200
    assert dados["estagio"] == "concluido"
    assert dados["redirect"] == "/projetos/caso_concluido/concluido"

    job_reconstruido = json.loads((pasta / "job.json").read_text(encoding="utf-8"))
    assert job_reconstruido["status"] == "concluido"
    assert job_reconstruido["data_fim"]
