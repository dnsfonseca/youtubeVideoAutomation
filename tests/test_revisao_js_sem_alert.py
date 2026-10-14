"""Teste estatico (Sessao de correcoes UX, Grupo B): static/revisao.js nao
pode mais usar alert() do navegador pra avisar que a origem do audio nao foi
selecionada - isso virou erro inline (#erro-inline-aprovar) na tela de
revisao de roteiro. So le o arquivo como texto, nao executa JS."""

from pathlib import Path

CAMINHO_REVISAO_JS = (
    Path(__file__).resolve().parent.parent / "static" / "revisao.js"
)


def _ler_revisao_js() -> str:
    return CAMINHO_REVISAO_JS.read_text(encoding="utf-8")


def test_revisao_js_nao_usa_alert():
    texto = _ler_revisao_js()
    assert "alert(" not in texto


def test_revisao_js_usa_erro_inline_aprovar():
    texto = _ler_revisao_js()
    assert "erro-inline-aprovar" in texto
    assert "erro-inline-aprovar-msg" in texto
