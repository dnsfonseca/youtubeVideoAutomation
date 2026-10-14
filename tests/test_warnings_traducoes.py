"""Testes de scripts/warnings_traducoes.py (Sessao 7.2 - CLAUDE.md secao
5.4/5.5): dicionario de categorias de aviso [⚠ ...] acionaveis na tela de
revisao, com fallback para categorias nao mapeadas."""

from scripts.warnings_traducoes import (
    WARNING_FALLBACK,
    WARNINGS_ACIONAVEIS,
    categoria_do_aviso,
    traduzir_aviso,
)


def test_warnings_acionaveis_contem_categorias_descobertas_na_investigacao():
    """Investigacao (sistema.md dos 3 perfis + roteiros reais gerados)
    encontrou so duas categorias de aviso em uso: single-source e
    conflict."""
    assert "single-source" in WARNINGS_ACIONAVEIS
    assert "conflict" in WARNINGS_ACIONAVEIS
    for categoria, dados in WARNINGS_ACIONAVEIS.items():
        assert dados["titulo"], f"categoria {categoria} sem titulo"
        assert dados["descricao"], f"categoria {categoria} sem descricao"


def test_warning_fallback_tem_titulo_e_descricao():
    assert WARNING_FALLBACK["titulo"]
    assert WARNING_FALLBACK["descricao"]


def test_categoria_do_aviso_extrai_categoria_simples():
    assert categoria_do_aviso("single-source") == "single-source"
    assert categoria_do_aviso("conflict") == "conflict"


def test_categoria_do_aviso_extrai_so_ate_a_virgula():
    """Aviso real observado em producao traz texto livre apos a categoria."""
    texto = "single-source, for the mine shaft and underhome search specifics"
    assert categoria_do_aviso(texto) == "single-source"


def test_categoria_do_aviso_string_vazia():
    assert categoria_do_aviso("") == ""
    assert categoria_do_aviso(None) == ""


def test_traduzir_aviso_categoria_conhecida():
    resultado = traduzir_aviso("single-source")
    assert resultado["titulo"] == "Apenas uma fonte"


def test_traduzir_aviso_categoria_desconhecida_cai_no_fallback():
    resultado = traduzir_aviso("categoria-inexistente")
    assert resultado == WARNING_FALLBACK


def test_traduzir_aviso_com_texto_livre_ainda_reconhece_categoria():
    resultado = traduzir_aviso("conflict, sobre a hora da ligacao")
    assert resultado["titulo"] == "Fontes divergem"
