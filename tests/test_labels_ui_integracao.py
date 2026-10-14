"""Testes de integracao dos labels amigaveis (Grupo A da sessao de
polimento pre-uso real): filtros Jinja registrados, templates usando os
filtros em vez de string tecnica crua, e /api/status/<id> expondo os
campos _label sem remover os originais."""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def test_filtros_de_label_registrados_no_jinja_env(app):
    for nome_filtro in (
        "label_status",
        "label_etapa",
        "label_tipo_projeto",
        "label_provedor_tts",
    ):
        assert nome_filtro in app.jinja_env.filters


def test_status_html_usa_filtro_label_etapa_e_label_status():
    conteudo = (TEMPLATES_DIR / "status.html").read_text(encoding="utf-8")
    assert "estado.etapa|label_etapa" in conteudo
    assert "estado.status|label_status" in conteudo
    # Garante que nao voltou a interpolar a chave tecnica crua sem filtro
    assert "Etapa: {{ estado.etapa or" not in conteudo
    assert "Status: {{ estado.status or" not in conteudo


def test_home_html_usa_filtro_label_status_no_badge():
    conteudo = (TEMPLATES_DIR / "home.html").read_text(encoding="utf-8")
    assert "projeto.status|label_status" in conteudo
    # O dict ad-hoc antigo de traducao (duplicava STATUS_LABEL) nao deve
    # voltar a existir.
    assert "badge_rotulos" not in conteudo


def test_home_html_badge_classes_cobre_todo_status_de_labels_ui():
    """Correcao de bug (coluna Estado vazia em video_teste_01): home.html
    mantem um dict `badge_classes` PARALELO a labels_ui.STATUS_LABEL so'
    pra' cor/estilo do badge (o texto vem do filtro label_status). Se um
    status novo (ex: "aguardando_thumbnail", "falhou") entrar em
    STATUS_LABEL sem entrar tambem em `badge_classes`, o projeto cai no
    branch `else` do template - antes desta correcao esse branch
    renderizava um <span> vazio (status-badge-vazio, sem texto nenhum),
    fazendo a coluna Estado parecer vazia mesmo com status definido. Este
    teste falha se um status novo for adicionado a STATUS_LABEL sem
    tambem entrar em badge_classes - forca lembrar de manter os dois
    dicts sincronizados."""
    from scripts.labels_ui import STATUS_LABEL

    conteudo = (TEMPLATES_DIR / "home.html").read_text(encoding="utf-8")
    inicio = conteudo.index("badge_classes = {")
    fim = conteudo.index("%}", inicio)
    bloco_badge_classes = conteudo[inicio:fim]

    for status in STATUS_LABEL:
        assert f'"{status}"' in bloco_badge_classes, (
            f"status {status!r} existe em STATUS_LABEL mas nao em badge_classes (home.html) - "
            "vai cair no fallback e precisa que o fallback tambem mostre o label."
        )


def test_home_html_fallback_de_status_desconhecido_nunca_fica_vazio():
    """Mesmo bug acima, defesa em profundidade: MESMO que um status novo
    fique fora de `badge_classes`, o branch `else` nunca pode renderizar
    um badge sem texto nenhum - tem que usar o filtro label_status (que
    cai de volta pra' chave crua se nem isso existir), nunca um <span>
    vazio."""
    conteudo = (TEMPLATES_DIR / "home.html").read_text(encoding="utf-8")
    ancora = conteudo.index("badge_classes[projeto.status]")
    inicio = conteudo.index("{% else %}", ancora)
    fim = conteudo.index("{% endif %}", inicio)
    bloco_fallback = conteudo[inicio:fim]

    assert "label_status" in bloco_fallback
    assert "status-badge-vazio" not in bloco_fallback


def test_ajustes_html_usa_filtro_label_provedor_tts():
    conteudo = (TEMPLATES_DIR / "ajustes.html").read_text(encoding="utf-8")
    assert "provedor|label_provedor_tts" in conteudo


def test_api_status_expoe_labels_preservando_chaves_originais(client, monkeypatch):
    import server

    server.jobs["caso_labels"] = {
        "etapa": "geracao_clipes",
        "status": "em_andamento",
        "pct": 10.0,
        "detalhe": "",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "proxima_etapa": None,
    }

    resposta = client.get("/api/status/caso_labels")
    corpo = resposta.get_json()

    assert resposta.status_code == 200
    # Chaves tecnicas originais preservadas (frontend usa pra logica).
    assert corpo["etapa"] == "geracao_clipes"
    assert corpo["status"] == "em_andamento"
    # Novos campos de label amigavel.
    assert corpo["etapa_label"] == "Clipes"
    assert corpo["status_label"] == "Em andamento"
