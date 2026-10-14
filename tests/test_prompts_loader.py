"""Testes de scripts/prompts/loader.py — montagem dinamica do prompt de
sistema por perfil + idioma (CLAUDE.md secao 3.1).

Os testes de caminho feliz usam os perfis reais em
scripts/prompts/perfis/ (truecrime completo, atualidades_narrativas e
historia como stubs minimos - CLAUDE.md secao 3.1: "cada perfil obriga
ter todos os arquivos requeridos"). Os testes de arquivo ausente
monkeypatcham loader.PERFIS_DIR para um diretorio temporario com um
perfil incompleto, sem tocar nos perfis reais do projeto.
"""

import pytest

from scripts.prompts import loader
from scripts.prompts.erros import (
    ArquivoObrigatorioAusenteError,
    IdiomaNaoSuportadoError,
    PerfilNaoEncontradoError,
)


# ---------------------------------------------------------------------------
# Caminho feliz - perfil truecrime
# ---------------------------------------------------------------------------


def test_montar_prompt_truecrime_en_us_retorna_string_com_bloco_juridico():
    prompt = loader.montar_prompt("truecrime", "en-US")

    assert isinstance(prompt, str)
    assert prompt.strip() != ""
    assert "{BLOCO_JURIDICO}" not in prompt
    assert "suspect" in prompt.lower()
    assert "indicted" in prompt.lower()


def test_montar_prompt_truecrime_en_us_contem_fontes_preferidas():
    prompt = loader.montar_prompt("truecrime", "en-US")

    assert "{FONTES_PREFERIDAS}" not in prompt
    assert "cnn.com" in prompt.lower()
    assert "nytimes.com" in prompt.lower()


def test_montar_prompt_truecrime_pt_br_contem_indiciado_e_denunciado():
    prompt = loader.montar_prompt("truecrime", "pt-BR")

    assert "indiciado" in prompt.lower()
    assert "denunciado" in prompt.lower()


# ---------------------------------------------------------------------------
# Interpolacao de {WEB_SEARCH_MAX} (otimizacao de custo pos-Sessao 6)
# ---------------------------------------------------------------------------


def test_montar_prompt_interpola_web_search_max_quando_placeholder_presente():
    prompt = loader.montar_prompt("truecrime", "en-US", web_search_max=6)

    assert "{WEB_SEARCH_MAX}" not in prompt
    assert "limite: 6 buscas" in prompt.lower()


def test_montar_prompt_sem_web_search_max_usa_fallback():
    prompt = loader.montar_prompt("truecrime", "en-US")

    assert "{WEB_SEARCH_MAX}" not in prompt
    assert f"limite: {loader._WEB_SEARCH_MAX_FALLBACK} buscas" in prompt.lower()


def test_montar_prompt_web_search_max_sem_placeholder_no_perfil_nao_quebra(tmp_path, monkeypatch):
    """Perfil sem {WEB_SEARCH_MAX} em sistema.md (ex: atualidades_narrativas,
    historia) nao pode levantar erro so por receber o argumento."""
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US", web_search_max=6)

    assert "{WEB_SEARCH_MAX}" not in prompt


# ---------------------------------------------------------------------------
# Caminho feliz - perfis sem bloco juridico (stubs)
# ---------------------------------------------------------------------------


def test_montar_prompt_atualidades_narrativas_nao_contem_placeholder_juridico():
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US")

    assert "{BLOCO_JURIDICO}" not in prompt


def test_montar_prompt_historia_de_nao_contem_placeholder_juridico():
    prompt = loader.montar_prompt("historia", "de")

    assert "{BLOCO_JURIDICO}" not in prompt


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------


def test_montar_prompt_perfil_inexistente_levanta_erro():
    with pytest.raises(PerfilNaoEncontradoError):
        loader.montar_prompt("perfil_inexistente", "en-US")


def test_montar_prompt_idioma_nao_suportado_levanta_erro():
    with pytest.raises(IdiomaNaoSuportadoError):
        loader.montar_prompt("truecrime", "japones")


def test_montar_prompt_perfil_sem_config_levanta_erro(tmp_path, monkeypatch):
    pasta_perfil = tmp_path / "perfil_incompleto"
    pasta_perfil.mkdir()
    monkeypatch.setattr(loader, "PERFIS_DIR", tmp_path)

    with pytest.raises(ArquivoObrigatorioAusenteError) as excinfo:
        loader.montar_prompt("perfil_incompleto", "en-US")
    assert excinfo.value.arquivo == "config.py"


def test_montar_prompt_perfil_sem_sistema_md_levanta_erro(tmp_path, monkeypatch):
    pasta_perfil = tmp_path / "perfil_sem_sistema"
    pasta_perfil.mkdir()
    (pasta_perfil / "config.py").write_text(
        "CONFIG = {'usa_juridico': False}\n", encoding="utf-8"
    )
    monkeypatch.setattr(loader, "PERFIS_DIR", tmp_path)

    with pytest.raises(ArquivoObrigatorioAusenteError) as excinfo:
        loader.montar_prompt("perfil_sem_sistema", "en-US")
    assert excinfo.value.arquivo == "sistema.md"


def test_montar_prompt_perfil_sem_fontes_preferidas_levanta_erro(tmp_path, monkeypatch):
    pasta_perfil = tmp_path / "perfil_sem_fontes"
    pasta_perfil.mkdir()
    (pasta_perfil / "config.py").write_text(
        "CONFIG = {'usa_juridico': False}\n", encoding="utf-8"
    )
    (pasta_perfil / "sistema.md").write_text(
        "Sistema {BLOCO_JURIDICO} {FONTES_PREFERIDAS}", encoding="utf-8"
    )
    monkeypatch.setattr(loader, "PERFIS_DIR", tmp_path)

    with pytest.raises(ArquivoObrigatorioAusenteError) as excinfo:
        loader.montar_prompt("perfil_sem_fontes", "en-US")
    assert excinfo.value.arquivo == "fontes_preferidas.py"


def test_perfil_nao_encontrado_error_lista_perfis_disponiveis_na_mensagem():
    with pytest.raises(PerfilNaoEncontradoError) as excinfo:
        loader.montar_prompt("perfil_inexistente", "en-US")

    mensagem = str(excinfo.value)
    assert "truecrime" in mensagem
    assert "atualidades_narrativas" in mensagem
    assert "historia" in mensagem
