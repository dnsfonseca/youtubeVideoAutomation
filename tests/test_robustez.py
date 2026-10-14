"""Testes de scripts/robustez.py — infra transversal de robustez contra
dependencias externas volateis (CLAUDE.md secao 18).

Nenhum teste aqui bate na rede real (PyPI) — requests.get e' sempre
mockado (CLAUDE.md secao 8).
"""

from datetime import datetime, timedelta, timezone

import pytest
import requests

from scripts import robustez


# ---------------------------------------------------------------------------
# libs_criticas
# ---------------------------------------------------------------------------


def test_libs_criticas_nao_e_vazia_e_contem_yt_dlp():
    resultado = robustez.libs_criticas()

    assert resultado
    assert "yt-dlp" in resultado


# ---------------------------------------------------------------------------
# versao_instalada
# ---------------------------------------------------------------------------


def test_versao_instalada_de_pacote_real_instalado_retorna_string_nao_vazia():
    # pytest esta instalado no venv que roda este proprio teste.
    resultado = robustez.versao_instalada("pytest")

    assert isinstance(resultado, str)
    assert resultado


def test_versao_instalada_de_pacote_inexistente_retorna_none():
    resultado = robustez.versao_instalada("pacote-que-nao-existe-xyz123")

    assert resultado is None


# ---------------------------------------------------------------------------
# idade_lib
# ---------------------------------------------------------------------------


class _RespostaFake:
    def __init__(self, corpo_json):
        self._corpo_json = corpo_json

    def raise_for_status(self):
        pass

    def json(self):
        return self._corpo_json


def test_idade_lib_calcula_dias_desde_o_release_a_partir_da_resposta_da_pypi(monkeypatch):
    monkeypatch.setattr(robustez, "versao_instalada", lambda nome: "2024.1.1")

    dias_esperados = 200
    data_release = datetime.now(timezone.utc) - timedelta(days=dias_esperados)

    def _get_fake(url, timeout):
        return _RespostaFake(
            {"urls": [{"upload_time_iso_8601": data_release.isoformat()}]}
        )

    monkeypatch.setattr(robustez.requests, "get", _get_fake)

    resultado = robustez.idade_lib("yt-dlp")

    # margem de 1 dia pela execucao do teste em si (datetime.now() muda
    # entre o calculo de data_release acima e a chamada real de idade_lib).
    assert resultado == pytest.approx(dias_esperados, abs=1)


def test_idade_lib_com_falha_de_rede_retorna_none_sem_propagar_excecao(monkeypatch):
    monkeypatch.setattr(robustez, "versao_instalada", lambda nome: "2024.1.1")

    def _get_levanta_erro(url, timeout):
        raise requests.exceptions.ConnectionError("sem rede")

    monkeypatch.setattr(robustez.requests, "get", _get_levanta_erro)

    resultado = robustez.idade_lib("yt-dlp")

    assert resultado is None


def test_idade_lib_com_pacote_nao_instalado_retorna_none_sem_chamar_a_rede(monkeypatch):
    """Regressao: se a versao instalada nem e' conhecida, idade_lib nao tem
    o que perguntar pra PyPI — nao deveria bater na rede a toa."""
    monkeypatch.setattr(robustez, "versao_instalada", lambda nome: None)

    def _get_nao_deveria_ser_chamado(url, timeout):
        pytest.fail("idade_lib nao deveria chamar requests.get sem versao conhecida")

    monkeypatch.setattr(robustez.requests, "get", _get_nao_deveria_ser_chamado)

    resultado = robustez.idade_lib("pacote-nao-instalado-xyz")

    assert resultado is None


def test_idade_lib_com_resposta_da_pypi_sem_urls_retorna_none(monkeypatch):
    monkeypatch.setattr(robustez, "versao_instalada", lambda nome: "2024.1.1")
    monkeypatch.setattr(
        robustez.requests, "get", lambda url, timeout: _RespostaFake({"urls": []})
    )

    resultado = robustez.idade_lib("yt-dlp")

    assert resultado is None


# ---------------------------------------------------------------------------
# lib_desatualizada
# ---------------------------------------------------------------------------


def test_lib_desatualizada_true_quando_idade_maior_que_janela(monkeypatch):
    monkeypatch.setattr(robustez, "idade_lib", lambda nome, timeout_s=3: robustez.JANELA_DIAS_AVISO + 1)

    assert robustez.lib_desatualizada("yt-dlp") is True


def test_lib_desatualizada_false_quando_idade_igual_ou_menor_que_janela(monkeypatch):
    monkeypatch.setattr(robustez, "idade_lib", lambda nome, timeout_s=3: robustez.JANELA_DIAS_AVISO)

    assert robustez.lib_desatualizada("yt-dlp") is False


def test_lib_desatualizada_false_quando_idade_e_none_nao_alarma_por_falta_de_informacao(monkeypatch):
    monkeypatch.setattr(robustez, "idade_lib", lambda nome, timeout_s=3: None)

    assert robustez.lib_desatualizada("yt-dlp") is False


# ---------------------------------------------------------------------------
# ffmpeg_disponivel
# ---------------------------------------------------------------------------


def test_ffmpeg_disponivel_true_quando_shutil_which_encontra_o_executavel(monkeypatch):
    monkeypatch.setattr(robustez.shutil, "which", lambda nome: r"C:\ffmpeg\bin\ffmpeg.exe")

    assert robustez.ffmpeg_disponivel() is True


def test_ffmpeg_disponivel_false_quando_shutil_which_nao_encontra(monkeypatch):
    monkeypatch.setattr(robustez.shutil, "which", lambda nome: None)

    assert robustez.ffmpeg_disponivel() is False


# ---------------------------------------------------------------------------
# validar_pre_condicoes_pipeline
# ---------------------------------------------------------------------------


def test_validar_pre_condicoes_pipeline_ok_quando_ffmpeg_disponivel(monkeypatch):
    monkeypatch.setattr(robustez, "ffmpeg_disponivel", lambda: True)

    ok, mensagem = robustez.validar_pre_condicoes_pipeline()

    assert ok is True
    assert mensagem is None


def test_validar_pre_condicoes_pipeline_falha_com_mensagem_quando_ffmpeg_ausente(monkeypatch):
    monkeypatch.setattr(robustez, "ffmpeg_disponivel", lambda: False)

    ok, mensagem = robustez.validar_pre_condicoes_pipeline()

    assert ok is False
    assert isinstance(mensagem, str) and mensagem
    assert "ffmpeg" in mensagem
