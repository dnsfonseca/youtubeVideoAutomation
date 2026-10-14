"""Testes de scripts/tts/preview_vozes.py (CLAUDE.md secao 5.6 - previews
de voz).

Nunca chama scripts/tts/get_provedor("google").sintetizar() de verdade
(que por sua vez chamaria a API Google TTS real) - sempre monkeypatch em
scripts.tts.preview_vozes.get_provedor com um provedor fake.

Todo teste isola PASTA_PREVIEWS/ARQUIVO_INDISPONIVEIS em tmp_path via
monkeypatch.setattr - nunca escreve em static/previews_vozes/ real."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.tts import preview_vozes


@pytest.fixture(autouse=True)
def _isolar_pasta_previews(tmp_path, monkeypatch):
    pasta = tmp_path / "previews_vozes"
    monkeypatch.setattr(preview_vozes, "PASTA_PREVIEWS", pasta)
    monkeypatch.setattr(preview_vozes, "ARQUIVO_INDISPONIVEIS", pasta / "_indisponiveis.json")
    return pasta


def _provedor_fake(vozes_por_idioma=None, sintetizar_mock=None):
    """Fake ProvedorTTS minimo: listar_vozes(idioma) e sintetizar(...)."""
    fake = MagicMock()
    vozes_por_idioma = vozes_por_idioma or {}
    fake.listar_vozes.side_effect = lambda idioma: vozes_por_idioma.get(idioma, [])
    if sintetizar_mock is not None:
        fake.sintetizar.side_effect = sintetizar_mock
    return fake


# ---------------------------------------------------------------------------
# caminho_preview / _trecho_para_idioma
# ---------------------------------------------------------------------------


def test_caminho_preview_monta_caminho_por_idioma_e_voz(_isolar_pasta_previews):
    caminho = preview_vozes.caminho_preview("en-US-Wavenet-D", "en-US")
    assert caminho == _isolar_pasta_previews / "en-US" / "en-US-Wavenet-D.mp3"


def test_trecho_para_idioma_conhecido_retorna_trecho_especifico():
    assert preview_vozes._trecho_para_idioma("pt-BR") == preview_vozes.TRECHOS_PREVIEW["pt-BR"]


def test_trecho_para_idioma_desconhecido_cai_no_padrao():
    assert preview_vozes._trecho_para_idioma("xx-XX") == preview_vozes.TRECHO_PADRAO


# ---------------------------------------------------------------------------
# listar_vozes_para_preview / buscar_idioma_da_voz
# ---------------------------------------------------------------------------


def test_listar_vozes_para_preview_achata_todos_os_idiomas(monkeypatch):
    vozes_por_idioma = {
        "en-US": [{"id": "en-US-Wavenet-A"}, {"id": "en-US-Wavenet-B"}],
        "pt-BR": [{"id": "pt-BR-Wavenet-B"}],
    }
    fake = _provedor_fake(vozes_por_idioma)
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    resultado = preview_vozes.listar_vozes_para_preview()

    assert {"id": "en-US-Wavenet-A", "idioma": "en-US"} in resultado
    assert {"id": "en-US-Wavenet-B", "idioma": "en-US"} in resultado
    assert {"id": "pt-BR-Wavenet-B", "idioma": "pt-BR"} in resultado
    assert len(resultado) == 3


def test_buscar_idioma_da_voz_encontra_no_catalogo(monkeypatch):
    fake = _provedor_fake({"pt-BR": [{"id": "pt-BR-Wavenet-B"}]})
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    assert preview_vozes.buscar_idioma_da_voz("pt-BR-Wavenet-B") == "pt-BR"


def test_buscar_idioma_da_voz_retorna_none_se_nao_encontrada(monkeypatch):
    fake = _provedor_fake({"pt-BR": [{"id": "pt-BR-Wavenet-B"}]})
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    assert preview_vozes.buscar_idioma_da_voz("voz-fantasma") is None


# ---------------------------------------------------------------------------
# marcar_indisponivel / remover_de_indisponiveis / carregar_indisponiveis
# ---------------------------------------------------------------------------


def test_carregar_indisponiveis_sem_arquivo_retorna_vazio():
    assert preview_vozes.carregar_indisponiveis() == {}


def test_marcar_indisponivel_persiste_motivo():
    preview_vozes.marcar_indisponivel("pt-BR-Wavenet-B", "Chave invalida")

    assert preview_vozes.carregar_indisponiveis() == {"pt-BR-Wavenet-B": "Chave invalida"}


def test_marcar_indisponivel_preserva_outras_entradas():
    preview_vozes.marcar_indisponivel("voz-a", "erro a")
    preview_vozes.marcar_indisponivel("voz-b", "erro b")

    indisponiveis = preview_vozes.carregar_indisponiveis()
    assert indisponiveis == {"voz-a": "erro a", "voz-b": "erro b"}


def test_remover_de_indisponiveis_tira_a_voz(_isolar_pasta_previews):
    preview_vozes.marcar_indisponivel("voz-a", "erro a")
    preview_vozes.marcar_indisponivel("voz-b", "erro b")

    preview_vozes.remover_de_indisponiveis("voz-a")

    assert preview_vozes.carregar_indisponiveis() == {"voz-b": "erro b"}


def test_remover_de_indisponiveis_voz_ausente_nao_da_erro():
    preview_vozes.remover_de_indisponiveis("voz-que-nao-existe")
    assert preview_vozes.carregar_indisponiveis() == {}


def test_carregar_indisponiveis_arquivo_corrompido_retorna_vazio(_isolar_pasta_previews):
    _isolar_pasta_previews.mkdir(parents=True)
    (_isolar_pasta_previews / "_indisponiveis.json").write_text("{nao e json valido", encoding="utf-8")

    assert preview_vozes.carregar_indisponiveis() == {}


# ---------------------------------------------------------------------------
# gerar_preview
# ---------------------------------------------------------------------------


def test_gerar_preview_cache_hit_nao_chama_provedor(_isolar_pasta_previews, monkeypatch):
    caminho = preview_vozes.caminho_preview("pt-BR-Wavenet-B", "pt-BR")
    caminho.parent.mkdir(parents=True)
    caminho.write_bytes(b"audio falso ja em cache")

    fake_get_provedor = MagicMock()
    monkeypatch.setattr(preview_vozes, "get_provedor", fake_get_provedor)

    resultado = preview_vozes.gerar_preview("pt-BR-Wavenet-B", "pt-BR")

    assert resultado == {"sucesso": True, "caminho": caminho, "erro": None, "ja_existia": True}
    fake_get_provedor.assert_not_called()


def test_gerar_preview_sucesso_grava_arquivo_e_retorna_sucesso(monkeypatch):
    def _sintetizar(texto, voz, saida):
        Path(saida).write_bytes(b"audio sintetizado")
        return {"audio_path": saida}

    fake = _provedor_fake(sintetizar_mock=_sintetizar)
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    resultado = preview_vozes.gerar_preview("pt-BR-Wavenet-B", "pt-BR")

    assert resultado["sucesso"] is True
    assert resultado["ja_existia"] is False
    assert resultado["caminho"].read_bytes() == b"audio sintetizado"
    fake.sintetizar.assert_called_once()
    texto_enviado = fake.sintetizar.call_args[0][0]
    assert texto_enviado == preview_vozes.TRECHOS_PREVIEW["pt-BR"]


def test_gerar_preview_falha_marca_indisponivel_e_nao_deixa_arquivo(monkeypatch):
    def _sintetizar(texto, voz, saida):
        raise RuntimeError("Chave Google TTS invalida ou sem permissao.")

    fake = _provedor_fake(sintetizar_mock=_sintetizar)
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    resultado = preview_vozes.gerar_preview("pt-BR-Wavenet-B", "pt-BR")

    assert resultado["sucesso"] is False
    assert resultado["caminho"] is None
    assert "Chave Google TTS invalida" in resultado["erro"]
    assert not preview_vozes.caminho_preview("pt-BR-Wavenet-B", "pt-BR").exists()
    assert preview_vozes.carregar_indisponiveis() == {
        "pt-BR-Wavenet-B": "Chave Google TTS invalida ou sem permissao."
    }


def test_gerar_preview_sucesso_apos_falha_anterior_remove_de_indisponiveis(monkeypatch):
    preview_vozes.marcar_indisponivel("pt-BR-Wavenet-B", "falha antiga")

    def _sintetizar(texto, voz, saida):
        Path(saida).write_bytes(b"audio ok agora")

    fake = _provedor_fake(sintetizar_mock=_sintetizar)
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    resultado = preview_vozes.gerar_preview("pt-BR-Wavenet-B", "pt-BR")

    assert resultado["sucesso"] is True
    assert preview_vozes.carregar_indisponiveis() == {}


# ---------------------------------------------------------------------------
# gerar_previews_batch
# ---------------------------------------------------------------------------


def test_gerar_previews_batch_agrega_sucesso_falha_e_cache(monkeypatch):
    # "voz-cache" ja existe em disco; "voz-ok" sintetiza com sucesso;
    # "voz-falha" sempre falha.
    caminho_cache = preview_vozes.caminho_preview("voz-cache", "en-US")
    caminho_cache.parent.mkdir(parents=True)
    caminho_cache.write_bytes(b"ja em cache")

    def _sintetizar(texto, voz, saida):
        if voz == "voz-falha":
            raise RuntimeError("Quota excedida")
        Path(saida).write_bytes(b"audio novo")

    fake = _provedor_fake(sintetizar_mock=_sintetizar)
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    vozes = [
        {"id": "voz-cache", "idioma": "en-US"},
        {"id": "voz-ok", "idioma": "en-US"},
        {"id": "voz-falha", "idioma": "en-US"},
    ]
    resultado = preview_vozes.gerar_previews_batch(vozes)

    assert resultado["total"] == 3
    assert resultado["geradas_agora"] == 1
    assert resultado["ja_existiam"] == 1
    assert resultado["falharam"] == 1
    assert resultado["falha_detalhes"] == [{"id": "voz-falha", "erro": "Quota excedida"}]


def test_gerar_previews_batch_lista_vazia_retorna_sumario_zerado():
    resultado = preview_vozes.gerar_previews_batch([])
    assert resultado == {
        "total": 0,
        "geradas_agora": 0,
        "ja_existiam": 0,
        "falharam": 0,
        "falha_detalhes": [],
    }


# ---------------------------------------------------------------------------
# regerar_todos_previews
# ---------------------------------------------------------------------------


def test_regerar_todos_previews_apaga_cache_antigo_e_gera_tudo(_isolar_pasta_previews, monkeypatch):
    lixo = preview_vozes.caminho_preview("voz-antiga", "en-US")
    lixo.parent.mkdir(parents=True)
    lixo.write_bytes(b"preview velho de uma voz que nem existe mais no catalogo")
    preview_vozes.marcar_indisponivel("voz-antiga-indisponivel", "erro velho")

    fake = _provedor_fake(
        vozes_por_idioma={"en-US": [{"id": "en-US-Wavenet-A"}]},
        sintetizar_mock=lambda texto, voz, saida: Path(saida).write_bytes(b"novo"),
    )
    monkeypatch.setattr(preview_vozes, "get_provedor", lambda nome: fake)

    resultado = preview_vozes.regerar_todos_previews()

    assert not lixo.exists()
    assert preview_vozes.carregar_indisponiveis() == {}
    assert resultado["total"] == 1
    assert resultado["geradas_agora"] == 1
    assert preview_vozes.caminho_preview("en-US-Wavenet-A", "en-US").exists()
