"""Testes da auditoria/limpeza de dead code (Grupo B da sessao de
polimento pre-uso real)."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def test_scripts_erros_nao_existe_mais():
    assert not (BASE_DIR / "scripts" / "erros.py").exists()


def test_nenhum_import_de_scripts_erros_no_codigo():
    padroes = ("from scripts.erros", "from scripts import erros")
    for caminho in BASE_DIR.rglob("*.py"):
        if caminho == Path(__file__):
            continue
        if "site-packages" in caminho.parts or ".venv" in caminho.parts or "venv" in caminho.parts:
            continue
        conteudo = caminho.read_text(encoding="utf-8", errors="ignore")
        for padrao in padroes:
            assert padrao not in conteudo, f"import residual de scripts.erros em {caminho}"


def test_melhorias_pendentes_nao_lista_mais_erros_py_como_pendente():
    conteudo = (BASE_DIR / "MELHORIAS_PENDENTES.md").read_text(encoding="utf-8")
    assert "Dead code em scripts/erros.py" not in conteudo
