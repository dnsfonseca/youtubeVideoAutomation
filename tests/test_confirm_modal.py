"""Testes do modal de confirmacao centralizado (correcao de sessao de
refinamento, CLAUDE.md): window.confirm()/window.alert() nativos (caixa de
dialogo do sistema operacional, fora do tema escuro) foram substituidos por
static/confirm_modal.js (window.BrollFoundryConfirm.perguntar), carregado
globalmente em base.html.

CLAUDE.md secao 8: sem runtime JS neste projeto - os testes abaixo verificam
o CODIGO FONTE (mesmo espirito de tests/test_ui_correcoes_sessao_thumbnail.py
e tests/test_iniciar_bat.py)."""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIRM_MODAL_JS = (BASE_DIR / "static" / "confirm_modal.js").read_text(encoding="utf-8")
BASE_HTML = (BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")

# Padrao de auditoria: uma chamada real a confirm()/alert() nativos - "confirm("
# ou "alert(" nao precedidos por letra/ponto (evita falso positivo em
# identificadores como "BrollFoundryConfirm.perguntar(" ou "confirmado").
PADRAO_DIALOGO_NATIVO = re.compile(r"(?<![\w.])(?:window\.)?(?:alert|confirm)\s*\(")


def _arquivos_js():
    return sorted((BASE_DIR / "static").glob("*.js"))


def _arquivos_html():
    return sorted((BASE_DIR / "templates").glob("*.html"))


def test_confirm_modal_js_define_api_global():
    assert "window.BrollFoundryConfirm" in CONFIRM_MODAL_JS
    assert "function perguntar(" in CONFIRM_MODAL_JS


def test_confirm_modal_usa_dialog_nativo_com_showmodal():
    # <dialog>.showModal() garante foco preso e backdrop - equivalente
    # semantico ao confirm() nativo, so' que estilizavel com o tema.
    assert "createElement(\"dialog\")" in CONFIRM_MODAL_JS
    assert ".showModal()" in CONFIRM_MODAL_JS


def test_confirm_modal_devolve_false_ao_cancelar_ou_fechar():
    assert 'addEventListener("cancel"' in CONFIRM_MODAL_JS
    assert "finalizar(false)" in CONFIRM_MODAL_JS


def test_base_html_inclui_confirm_modal_js_globalmente():
    assert "confirm_modal.js" in BASE_HTML


def test_confirm_modal_proprio_nao_usa_dialogo_nativo():
    assert not PADRAO_DIALOGO_NATIVO.search(CONFIRM_MODAL_JS)


def test_nenhum_js_estatico_usa_confirm_ou_alert_nativos():
    """Auditoria completa (CLAUDE.md, correcao de sessao de refinamento):
    depois desta sessao, static/confirm_modal.js e' o UNICO lugar autorizado
    a existir sem essa restricao (ele MESMO implementa o modal - nao chama
    confirm()/alert() nativos, coberto pelo teste acima). Todo outro arquivo
    JS deve usar BrollFoundryConfirm.perguntar() em vez de dialogo nativo."""
    ofensores = []
    for caminho in _arquivos_js():
        if caminho.name == "confirm_modal.js":
            continue
        conteudo = caminho.read_text(encoding="utf-8")
        if PADRAO_DIALOGO_NATIVO.search(conteudo):
            ofensores.append(caminho.name)
    assert not ofensores, f"Arquivos JS ainda usando confirm()/alert() nativo: {ofensores}"


def test_nenhum_template_usa_confirm_ou_alert_nativos_inline():
    ofensores = []
    for caminho in _arquivos_html():
        conteudo = caminho.read_text(encoding="utf-8")
        if PADRAO_DIALOGO_NATIVO.search(conteudo):
            ofensores.append(caminho.name)
    assert not ofensores, f"Templates ainda usando confirm()/alert() nativo inline: {ofensores}"


def test_thumbnail_js_usa_o_modal_do_tema_para_finalizar_projeto():
    thumbnail_js = (BASE_DIR / "static" / "thumbnail.js").read_text(encoding="utf-8")
    assert "BrollFoundryConfirm.perguntar(" in thumbnail_js
