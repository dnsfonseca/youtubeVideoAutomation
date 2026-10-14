"""Testes da tela generica somente-leitura de revisita de etapa do
pipeline (item 3 da sessao de correcoes de composicao/interface):
`GET /projetos/<id>/pipeline/<etapa>` (server.py:ver_etapa_pipeline), pra
download/transcricao/audio/geracao_clipes - as 4 etapas que ate essa
sessao nunca tinham tela dedicada de revisita (CLAUDE.md secao "pipeline
clicavel"). roteiro/montagem/thumbnail continuam cobertas por seus
proprios arquivos de teste (test_revisar_roteiro.py/test_concluido.py/
test_thumbnail_rotas.py)."""

import json

import pytest


def _criar_projeto(projetos_dir, nome, status="concluido", etapa_atual="thumbnail"):
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"projeto_id": nome, "status": status, "etapa_atual": etapa_atual}),
        encoding="utf-8",
    )
    return pasta


@pytest.fixture
def pasta_projeto(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    return _criar_projeto(projetos_dir, "caso_pipeline_etapa")


def test_etapa_invalida_404(client, pasta_projeto):
    resposta = client.get("/projetos/caso_pipeline_etapa/pipeline/roteiro")
    assert resposta.status_code == 404


def test_projeto_inexistente_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    resposta = client.get("/projetos/nao_existe/pipeline/download")
    assert resposta.status_code == 404


def test_download_mostra_links_e_fontes(client, pasta_projeto):
    # `url_original` (nao `url`) e' o campo real gravado por
    # scripts/1_baixar_videos.py no manifest - fixture anterior usava
    # "url" direto e mascarava o bug real (a tela ficava sempre com
    # tracinho na coluna "Link original" - correcao de sessao de
    # refinamento).
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(
            {
                "fontes": [
                    {
                        "id": "fonte01",
                        "arquivo": "fonte01.mp4",
                        "url_original": "https://youtube.com/watch?v=abc123",
                        "titulo": "Video de teste",
                        "duracao_s": 125,
                        "sucesso": True,
                        "origem": "youtube",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    resposta = client.get("/projetos/caso_pipeline_etapa/pipeline/download")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "https://youtube.com/watch?v=abc123" in pagina
    assert "Video de teste" in pagina
    assert "fonte01.mp4" in pagina


def test_download_mostra_tipo_de_uso_por_fonte(client, pasta_projeto):
    """CLAUDE.md secao 5.7.2 - entrada/fontes_tipo_uso.json mapeia
    fonteNN -> ambos/transcricao/visual. A tela de leitura da Etapa 1
    precisa mostrar esse dado (correcao de sessao de refinamento - antes
    a tabela nao tinha coluna nenhuma pra isso)."""
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(
            {
                "fontes": [
                    {
                        "id": "fonte01",
                        "arquivo": "fonte01.mp4",
                        "url_original": "https://youtube.com/watch?v=abc123",
                        "titulo": "Fonte so' transcricao",
                        "duracao_s": 125,
                        "sucesso": True,
                        "origem": "youtube",
                    },
                    {
                        "id": "fonte02",
                        "arquivo": "fonte02.mp4",
                        "url_original": "https://youtube.com/watch?v=def456",
                        "titulo": "Fonte so' visual",
                        "duracao_s": 60,
                        "sucesso": True,
                        "origem": "youtube",
                    },
                    {
                        "id": "fonte03",
                        "arquivo": "fonte03.mp4",
                        "url_original": "https://youtube.com/watch?v=ghi789",
                        "titulo": "Fonte ambos (default)",
                        "duracao_s": 60,
                        "sucesso": True,
                        "origem": "youtube",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (pasta_projeto / "entrada" / "fontes_tipo_uso.json").write_text(
        json.dumps({"fonte01": "transcricao", "fonte02": "visual"}),
        encoding="utf-8",
    )

    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/download").get_data(as_text=True)

    assert "Só transcrição" in pagina
    assert "Só clipes" in pagina
    assert "Transcrição + clipes" in pagina  # fonte03, ausente do mapa -> default "ambos"


def test_download_sem_fontes_tipo_uso_json_usa_default_ambos(client, pasta_projeto):
    """Projeto anterior a` feature de fontes separadas (sem
    entrada/fontes_tipo_uso.json) - retrocompatibilidade total, nunca
    quebra a tela."""
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(
            {
                "fontes": [
                    {
                        "id": "fonte01",
                        "arquivo": "fonte01.mp4",
                        "url_original": "https://youtube.com/watch?v=abc123",
                        "titulo": "Video antigo",
                        "duracao_s": 125,
                        "sucesso": True,
                        "origem": "youtube",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    resposta = client.get("/projetos/caso_pipeline_etapa/pipeline/download")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Transcrição + clipes" in pagina


def test_download_sem_fontes_mostra_mensagem(client, pasta_projeto):
    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/download").get_data(as_text=True)
    assert "Nenhum arquivo baixado ainda." in pagina


def test_transcricao_mostra_texto_concatenado(client, pasta_projeto):
    pasta_transcricoes = pasta_projeto / "transcricoes"
    pasta_transcricoes.mkdir()
    (pasta_transcricoes / "fonte01.json").write_text(
        json.dumps(
            {
                "arquivo": "fonte01.mp4",
                "idioma": "en",
                "duracao_s": 60,
                "segmentos": [{"text": "Hello"}, {"text": "world."}],
            }
        ),
        encoding="utf-8",
    )

    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/transcricao").get_data(as_text=True)
    assert "fonte01.mp4" in pagina
    assert "Hello world." in pagina


def test_transcricao_vazia_mostra_mensagem(client, pasta_projeto):
    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/transcricao").get_data(as_text=True)
    assert "Nenhuma transcrição disponível." in pagina


def test_audio_disponivel_mostra_player(client, pasta_projeto):
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake mp3")
    (pasta_projeto / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"}), encoding="utf-8"
    )

    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/audio").get_data(as_text=True)
    assert "<audio" in pagina
    assert "/narracao_audio" in pagina
    assert "Gerado por TTS" in pagina


def test_audio_indisponivel_mostra_mensagem(client, pasta_projeto):
    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/audio").get_data(as_text=True)
    assert "Nenhum áudio de narração disponível." in pagina


def test_geracao_clipes_mostra_grid(client, pasta_projeto):
    pasta_clipes = pasta_projeto / "clipes"
    pasta_clipes.mkdir()
    (pasta_clipes / "indice.json").write_text(
        json.dumps(
            {
                "clipes": [
                    {"clipe_id": "clipe001", "fonte_original": "fonte01", "duracao_s": 8.0},
                    {"clipe_id": "clipe002", "fonte_original": "fonte02", "duracao_s": 6.5},
                ]
            }
        ),
        encoding="utf-8",
    )

    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/geracao_clipes").get_data(as_text=True)
    assert "2 clipe(s)." in pagina
    assert "clipe001" in pagina
    assert "clipe002" in pagina


def test_geracao_clipes_vazia_mostra_mensagem(client, pasta_projeto):
    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/geracao_clipes").get_data(as_text=True)
    assert "Nenhum clipe disponível." in pagina


def test_projeto_concluido_mostra_dois_botoes_de_navegacao(client, pasta_projeto):
    pagina = client.get("/projetos/caso_pipeline_etapa/pipeline/download").get_data(as_text=True)
    assert "Voltar à conclusão" in pagina
    assert "Voltar aos projetos" in pagina
    assert f"/projetos/caso_pipeline_etapa/concluido" in pagina


def test_projeto_nao_concluido_mostra_so_voltar_aos_projetos(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_projeto(projetos_dir, "caso_em_andamento", status="em_andamento", etapa_atual="audio")

    pagina = client.get("/projetos/caso_em_andamento/pipeline/download").get_data(as_text=True)
    assert "Voltar à conclusão" not in pagina
    assert "Voltar aos projetos" in pagina
