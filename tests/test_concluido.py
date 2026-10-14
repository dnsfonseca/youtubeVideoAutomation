"""Testes da tela de conclusao (CLAUDE.md secao 5.9) - GET
/projetos/<id>/concluido.

Sessao de reconstrucao (composicao por IA + tela de conclusao): a tela
passou a reunir titulos sugeridos/descricao/tags/thumbnail final/dados do
projeto (perfil/duracao/custo), tudo somente leitura. Os testes abaixo
cobrem tanto o comportamento antigo (pipeline horizontal, ja coberto antes
desta sessao) quanto os campos novos - sempre best-effort, nunca quebrando
por causa de um artefato ausente (projeto antigo sem thumbnail/tags)."""

import json

from PIL import Image


def test_get_concluido_projeto_sem_dados_retorna_200(client, tmp_path, monkeypatch):
    """Sem job.json nem video_final.mp4 no disco - a rota nao crasha,
    so' mostra os blocos vazios (video_disponivel=False)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.get("/projetos/caso_sem_dados/concluido")

    assert resposta.status_code == 200


def test_get_concluido_mostra_pipeline_horizontal(client, tmp_path, monkeypatch):
    """A tela de conclusao passa a mostrar a pipeline horizontal sticky
    (mesma macro de status.html e revisao_roteiro.html) - antes desta
    sessao, a rota nem lia job.json/estado."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.get("/projetos/caso_pipeline/concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "pipeline-horizontal" in pagina
    assert "Download" in pagina
    assert "Montagem" in pagina


def test_get_concluido_job_concluido_marca_todas_etapas_como_done(client, tmp_path, monkeypatch):
    """Com job.json status=concluido, a pipeline mostra todas as 6 etapas
    marcadas como concluidas (mesma regra de _parsear_pipeline_steps ja
    usada em status.html)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = tmp_path / "projetos" / "caso_concluido"
    pasta.mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"projeto_id": "caso_concluido", "status": "concluido", "etapa_atual": "montagem"}),
        encoding="utf-8",
    )

    resposta = client.get("/projetos/caso_concluido/concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "pipeline-step-done" in pagina
    assert "pipeline-step-pending" not in pagina


def test_get_concluido_body_tem_data_projeto_id(client, tmp_path, monkeypatch):
    """pipeline_polling.js (Sessao de correcoes UX) le o id do projeto de
    document.body.dataset.projetoId - a tela precisa expor esse atributo."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.get("/projetos/caso_body_attr/concluido")
    pagina = resposta.get_data(as_text=True)

    assert 'data-projeto-id="caso_body_attr"' in pagina


def test_get_concluido_inclui_scripts_de_polling_do_pipeline(client, tmp_path, monkeypatch):
    """A tela de conclusao antes so recebia o pipeline renderizado uma vez
    no carregamento (macro Jinja) - agora tambem faz polling via
    pipeline_polling.js (Sessao de correcoes UX, Grupo A)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.get("/projetos/caso_polling/concluido")
    pagina = resposta.get_data(as_text=True)

    assert "pipeline_render.js" in pagina
    assert "pipeline_polling.js" in pagina


# ---------------------------------------------------------------------------
# Campos novos: thumbnail final, titulos/descricao/tags, dados do projeto
# ---------------------------------------------------------------------------


def _montar_projeto_completo(tmp_path, nome):
    pasta = tmp_path / "projetos" / nome
    (pasta / "saida").mkdir(parents=True)
    (pasta / "thumbnail").mkdir()
    (pasta / "thumbnail" / "final.jpg").write_bytes(b"")
    Image.new("RGB", (1280, 720), (10, 20, 30)).save(pasta / "thumbnail" / "final.jpg")
    (pasta / "saida" / "video_final.mp4").write_bytes(b"fake")
    (pasta / "titulo.txt").write_text("Titulo Escolhido", encoding="utf-8")
    # titulos_sugeridos.json (Etapa 3, CLAUDE.md secao 5.3): as 3 opcoes
    # editoriais originais - a tela de conclusao (sessao "titulo canonico")
    # nunca gera titulo nenhum sozinha, so' consome titulo.txt (canonico) +
    # as outras 2 opcoes daqui como referencia.
    (pasta / "titulos_sugeridos.json").write_text(
        json.dumps({"titulos": ["Titulo Escolhido", "Titulo B", "Titulo C"], "descricoes": ["", "", ""]}),
        encoding="utf-8",
    )
    (pasta / "job.json").write_text(
        json.dumps({"projeto_id": nome, "status": "concluido", "etapa_atual": "thumbnail", "perfil": "truecrime"}),
        encoding="utf-8",
    )
    (pasta / "thumbnail" / "metadados.json").write_text(
        json.dumps(
            {
                "titulo_escolhido": "Titulo Escolhido",
                "titulos_alternativos": ["Titulo B", "Titulo C"],
                "description": "Uma descricao completa do video.",
                "tags": ["tag1", "tag2", "tag3"],
                "thumbnail": {},
            }
        ),
        encoding="utf-8",
    )
    (pasta / "saida" / "montagem_metadata.json").write_text(
        json.dumps({"tempo_total_s": 185.0, "duracao_video_s": 1500.0}), encoding="utf-8"
    )
    (pasta / "job_metadata.json").write_text(json.dumps({"custo_estimado_usd": 1.5}), encoding="utf-8")
    return pasta


def test_get_concluido_renderiza_com_todos_os_campos_presentes(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _montar_projeto_completo(tmp_path, "caso_completo")

    resposta = client.get("/projetos/caso_completo/concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Titulo Escolhido" in pagina
    assert "Titulo B" in pagina and "Titulo C" in pagina  # alternativas nao escolhidas, so' referencia
    assert "Uma descricao completa do video." in pagina
    assert "tag1" in pagina and "tag2" in pagina and "tag3" in pagina
    assert "truecrime" in pagina
    assert "25:00" in pagina  # duracao_video_s=1500.0 -> duracao do VIDEO (nao processamento)
    assert "3:05" in pagina  # tempo_total_s=185s -> tempo de processamento, campo separado
    assert "Duração do vídeo" in pagina
    assert "1.50" in pagina  # custo total estimado
    assert "Baixar thumbnail" in pagina


def test_get_concluido_thumbnail_ausente_nao_quebra(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = _montar_projeto_completo(tmp_path, "caso_sem_thumb")
    (pasta / "thumbnail" / "final.jpg").unlink()

    resposta = client.get("/projetos/caso_sem_thumb/concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Baixar thumbnail" not in pagina


def test_get_concluido_tags_e_descricao_ausentes_nao_quebra(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = _montar_projeto_completo(tmp_path, "caso_sem_texto")
    (pasta / "thumbnail" / "metadados.json").write_text(
        json.dumps(
            {"titulo_escolhido": "Titulo Escolhido", "titulos_alternativos": [], "description": "", "tags": [], "thumbnail": {}}
        ),
        encoding="utf-8",
    )

    resposta = client.get("/projetos/caso_sem_texto/concluido")

    assert resposta.status_code == 200


def test_get_concluido_projeto_antigo_sem_duracao_video_s_usa_narracao_como_fallback(client, tmp_path, monkeypatch):
    """Projeto montado ANTES da correcao que passou a persistir
    duracao_video_s (scripts/6_montar_video.py) - montagem_metadata.json so'
    tem tempo_total_s (processamento). video_final.mp4 fake nao e' um video
    de verdade (ffprobe falha nele), entao a cascata cai no ultimo recurso:
    narracao_alinhamento.json.duracao_s."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = _montar_projeto_completo(tmp_path, "caso_projeto_antigo")
    (pasta / "saida" / "montagem_metadata.json").write_text(
        json.dumps({"tempo_total_s": 185.0}), encoding="utf-8"
    )
    (pasta / "narracao_alinhamento.json").write_text(
        json.dumps({"duracao_s": 900.0}), encoding="utf-8"
    )

    resposta = client.get("/projetos/caso_projeto_antigo/concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "15:00" in pagina  # 900s (narracao) usado como fallback de duracao do video
    assert "Duração do vídeo" in pagina


def test_get_concluido_projeto_totalmente_vazio_nao_quebra(client, tmp_path, monkeypatch):
    """Projeto sem thumbnail/metadados/job_metadata algum (nunca chegou a'
    Etapa 7, ou e' de antes dela existir) - a tela so' mostra os blocos
    disponiveis, sem erro 500."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.get("/projetos/caso_totalmente_vazio/concluido")

    assert resposta.status_code == 200


# ---------------------------------------------------------------------------
# Sessao "titulo canonico" (achado real, projeto Burke Ramsey/JonBenét): a
# tela de conclusao NUNCA gera/exibe um conjunto de titulos concorrente -
# titulo.txt (Etapa 3/5.5, escolhido pelo usuario) e' sempre o titulo
# canonico da pagina; o que a Etapa 7 (thumbnail/metadados.json) grava so'
# entra como descricao/tags/thumbnail, nunca como titulo.
# ---------------------------------------------------------------------------


def test_get_concluido_nunca_le_title_do_grupo_d_para_o_titulo_canonico(client, tmp_path, monkeypatch):
    """Reproduz o bug original: mesmo que thumbnail/metadados.json ainda
    tenha uma chave antiga "title" (de uma geracao anterior a' correcao,
    ou escrita por engano), a pagina de conclusao NUNCA usa esse valor
    como titulo - so' titulo.txt."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = _montar_projeto_completo(tmp_path, "caso_title_antigo_ignorado")
    (pasta / "thumbnail" / "metadados.json").write_text(
        json.dumps(
            {
                # Chave antiga (formato pre-correcao) - nunca mais deveria
                # ser gerada, mas se sobrar de um projeto antigo no disco,
                # a tela tem que ignora-la para o titulo canonico.
                "title": ["Titulo Gerado Pela Etapa 7 - NUNCA deveria aparecer como titulo"],
                "description": "Descricao.",
                "tags": [],
                "thumbnail": {},
            }
        ),
        encoding="utf-8",
    )

    pagina = client.get("/projetos/caso_title_antigo_ignorado/concluido").get_data(as_text=True)

    assert "Titulo Escolhido" in pagina  # de titulo.txt, sempre
    assert "Titulo Gerado Pela Etapa 7" not in pagina


def test_get_concluido_marca_titulo_escolhido_e_lista_alternativas_da_revisao(client, tmp_path, monkeypatch):
    """As outras 2 opcoes da revisao (titulos_sugeridos.json, Etapa 3)
    aparecem como referencia - nunca como um segundo conjunto gerado pela
    Etapa 7 (Opcao A do pedido "titulo canonico")."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _montar_projeto_completo(tmp_path, "caso_alternativas")

    pagina = client.get("/projetos/caso_alternativas/concluido").get_data(as_text=True)

    assert "Título (escolhido na revisão)" in pagina
    assert "Titulo Escolhido" in pagina
    assert "Outras opções da revisão (não utilizadas)" in pagina
    assert "Titulo B" in pagina and "Titulo C" in pagina


def test_get_concluido_projeto_antigo_sem_titulos_sugeridos_nao_quebra(client, tmp_path, monkeypatch):
    """Validacao 10 do pedido "titulo canonico": projeto gerado antes de
    titulos_sugeridos.json existir (ou roteiro importado por upload) nao
    tem esse arquivo no disco - a tela nao quebra, so' nao mostra nenhuma
    alternativa."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = _montar_projeto_completo(tmp_path, "caso_sem_titulos_sugeridos")
    (pasta / "titulos_sugeridos.json").unlink()

    resposta = client.get("/projetos/caso_sem_titulos_sugeridos/concluido")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Titulo Escolhido" in pagina
    assert "Outras opções da revisão" not in pagina


def test_get_concluido_projeto_antigo_sem_titulo_txt_nao_quebra(client, tmp_path, monkeypatch):
    """Projeto sem titulo.txt algum (nunca passou pela revisao, ou e' de
    antes da Etapa 3 existir) - a tela cai no fallback ja existente
    (projeto_id como titulo de header) sem erro 500."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    pasta = _montar_projeto_completo(tmp_path, "caso_sem_titulo_txt")
    (pasta / "titulo.txt").unlink()

    resposta = client.get("/projetos/caso_sem_titulo_txt/concluido")

    assert resposta.status_code == 200


def test_get_concluido_nao_expoe_nenhuma_acao_de_mutacao(client, tmp_path, monkeypatch):
    """A tela de conclusao e' somente leitura (CLAUDE.md secao 5.9) -
    trocar thumbnail/regerar briefing/editar textos e' so' na Etapa 7. As
    unicas acoes com efeito colateral aqui sao download (link puro, sem
    POST) e "abrir pasta" (nao muda dado nenhum do projeto)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _montar_projeto_completo(tmp_path, "caso_somente_leitura")

    pagina = client.get("/projetos/caso_somente_leitura/concluido").get_data(as_text=True)

    for rota_de_mutacao in (
        "escolher_template", "salvar_textos", "upload_sujeito", "remover_sujeito",
        "gerar_briefing", "renderizar", "gerar_composicao_ia", "aprovar_roteiro",
    ):
        assert rota_de_mutacao not in pagina
