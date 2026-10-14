"""Testes de GET /: como a Home resolve o destino do clique em cada linha
de projeto (home.html:64) - CLAUDE.md secao 5.9 (Grupo D da sessao de
composicao por IA/tela de conclusao). Projeto com status "concluido" abre
direto em /concluido; qualquer outro status continua abrindo em /status."""

import json


def _criar_projeto(tmp_path, nome, status):
    pasta = tmp_path / "projetos" / nome
    pasta.mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"projeto_id": nome, "nome": nome, "status": status, "etapa_atual": "montagem"}),
        encoding="utf-8",
    )
    return pasta


def test_home_projeto_concluido_linka_para_tela_de_conclusao(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _criar_projeto(tmp_path, "caso_home_concluido", status="concluido")

    pagina = client.get("/").get_data(as_text=True)

    assert "/projetos/caso_home_concluido/concluido" in pagina
    assert "/projetos/caso_home_concluido/status" not in pagina


def test_home_projeto_em_andamento_continua_linkando_para_status(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _criar_projeto(tmp_path, "caso_home_status", status="aguardando_thumbnail")

    pagina = client.get("/").get_data(as_text=True)

    assert "/status/caso_home_status" in pagina
    assert "/projetos/caso_home_status/concluido" not in pagina


def test_home_projeto_aguardando_revisao_linka_para_revisar_roteiro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _criar_projeto(tmp_path, "caso_home_revisao", status="aguardando_revisao")

    pagina = client.get("/").get_data(as_text=True)

    assert "/projetos/caso_home_revisao/revisar_roteiro" in pagina


def test_home_projeto_aguardando_thumbnail_mostra_badge_com_texto_visivel(client, tmp_path, monkeypatch):
    """Correcao de bug (video_teste_01): a coluna Estado ficava vazia pra'
    projetos com status "aguardando_thumbnail" - o dict `badge_classes`
    de home.html nao tinha entrada pra' esse status (existe em
    labels_ui.STATUS_LABEL desde a Etapa 7, mas nunca foi adicionado ao
    dict paralelo do template), e o branch de fallback renderizava um
    <span> vazio. Confere que o LABEL amigavel aparece de verdade na
    pagina renderizada, nao so' que o dict foi corrigido em isolamento."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _criar_projeto(tmp_path, "caso_home_thumbnail", status="aguardando_thumbnail")

    pagina = client.get("/").get_data(as_text=True)

    assert "Aguardando thumbnail" in pagina
    assert 'status-badge-vazio"' not in pagina


def test_home_projeto_status_desconhecido_nunca_mostra_badge_vazio(client, tmp_path, monkeypatch):
    """Defesa em profundidade do mesmo bug: um status que NEM existe em
    labels_ui.STATUS_LABEL (job.json corrompido/versao futura ainda nao
    suportada) tem que cair no badge de fallback visivel (com a propria
    chave tecnica como texto), nunca num <span> sem conteudo nenhum."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    _criar_projeto(tmp_path, "caso_home_status_novo", status="status_futuro_inexistente")

    pagina = client.get("/").get_data(as_text=True)

    assert "status_futuro_inexistente" in pagina
    assert 'status-badge-vazio"' not in pagina
