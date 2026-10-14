"""Testes dos provedores stub de TTS (scripts/tts/elevenlabs.py, openai.py, azure.py
e factory get_provedor - CLAUDE.md secao 5.6).

Os provedores stub indicam "nao implementado no MVP" quando chamados,
permitindo que a arquitetura pluggavel ja esteja pronta para uma sessao
pos-MVP adicionar os provedores reais sem mudancas no resto do codigo.
"""

from pathlib import Path

import pytest

from scripts.tts import (
    ProvedorTTSInvalidoError,
    get_provedor,
)
from scripts.tts.elevenlabs import ElevenLabsTTS
from scripts.tts.openai import OpenAITTS
from scripts.tts.azure import AzureTTS


# ---------------------------------------------------------------------------
# get_provedor - factory
# ---------------------------------------------------------------------------


def test_get_provedor_google():
    """Factory retorna instancia de GoogleTTS para 'google'."""
    provedor = get_provedor("google")
    assert provedor is not None
    # Deve ter os metodos obrigatorios da interface ProvedorTTS
    assert hasattr(provedor, "sintetizar")
    assert hasattr(provedor, "listar_vozes")
    assert hasattr(provedor, "validar_configuracao")


def test_get_provedor_elevenlabs():
    """Factory retorna instancia de ElevenLabsTTS para 'elevenlabs'."""
    provedor = get_provedor("elevenlabs")
    assert isinstance(provedor, ElevenLabsTTS)


def test_get_provedor_openai():
    """Factory retorna instancia de OpenAITTS para 'openai'."""
    provedor = get_provedor("openai")
    assert isinstance(provedor, OpenAITTS)


def test_get_provedor_azure():
    """Factory retorna instancia de AzureTTS para 'azure'."""
    provedor = get_provedor("azure")
    assert isinstance(provedor, AzureTTS)


def test_get_provedor_invalido_levanta_erro():
    """Factory levanta ProvedorTTSInvalidoError para nome desconhecido."""
    with pytest.raises(ProvedorTTSInvalidoError) as exc_info:
        get_provedor("provedor_inexistente")

    excecao = exc_info.value
    assert "provedor_inexistente" in str(excecao)
    assert "nao existe" in str(excecao).lower()


def test_get_provedor_erro_menciona_provedores_disponiveis():
    """Erro ao pedir provedor invalido menciona quais estao disponiveis."""
    with pytest.raises(ProvedorTTSInvalidoError) as exc_info:
        get_provedor("boom")

    excecao = exc_info.value
    # Deve mencionar os provedores conhecidos
    msg = str(excecao)
    # Pelo menos 'google' deve estar na mensagem
    assert "google" in msg.lower()


# ---------------------------------------------------------------------------
# ElevenLabsTTS - stub
# ---------------------------------------------------------------------------


def test_elevenlabs_sintetizar_levanta_nao_implementado():
    """ElevenLabsTTS.sintetizar leva NotImplementedError."""
    provedor = ElevenLabsTTS()

    with pytest.raises(NotImplementedError) as exc_info:
        provedor.sintetizar("Texto", "voz", Path("/tmp/saida.mp3"))

    msg = str(exc_info.value)
    assert "ElevenLabs" in msg or "nao implementado" in msg.lower()


def test_elevenlabs_listar_vozes_retorna_vazio():
    """ElevenLabsTTS.listar_vozes retorna lista vazia (stub)."""
    provedor = ElevenLabsTTS()
    vozes = provedor.listar_vozes("en-US")

    assert vozes == []
    assert isinstance(vozes, list)


def test_elevenlabs_validar_configuracao_retorna_false():
    """ElevenLabsTTS.validar_configuracao retorna (False, mensagem)."""
    provedor = ElevenLabsTTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is False
    assert isinstance(mensagem, str)
    assert "nao implementado" in mensagem.lower() or "elevenlabs" in mensagem.lower()


# ---------------------------------------------------------------------------
# OpenAITTS - stub
# ---------------------------------------------------------------------------


def test_openai_sintetizar_levanta_nao_implementado():
    """OpenAITTS.sintetizar levanta NotImplementedError."""
    provedor = OpenAITTS()

    with pytest.raises(NotImplementedError) as exc_info:
        provedor.sintetizar("Texto", "voz", Path("/tmp/saida.mp3"))

    msg = str(exc_info.value)
    assert "OpenAI" in msg or "nao implementado" in msg.lower()


def test_openai_listar_vozes_retorna_vazio():
    """OpenAITTS.listar_vozes retorna lista vazia (stub)."""
    provedor = OpenAITTS()
    vozes = provedor.listar_vozes("en-US")

    assert vozes == []


def test_openai_validar_configuracao_retorna_false():
    """OpenAITTS.validar_configuracao retorna (False, mensagem)."""
    provedor = OpenAITTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is False
    assert "nao implementado" in mensagem.lower() or "openai" in mensagem.lower()


# ---------------------------------------------------------------------------
# AzureTTS - stub
# ---------------------------------------------------------------------------


def test_azure_sintetizar_levanta_nao_implementado():
    """AzureTTS.sintetizar levanta NotImplementedError."""
    provedor = AzureTTS()

    with pytest.raises(NotImplementedError) as exc_info:
        provedor.sintetizar("Texto", "voz", Path("/tmp/saida.mp3"))

    msg = str(exc_info.value)
    assert "Azure" in msg or "nao implementado" in msg.lower()


def test_azure_listar_vozes_retorna_vazio():
    """AzureTTS.listar_vozes retorna lista vazia (stub)."""
    provedor = AzureTTS()
    vozes = provedor.listar_vozes("en-US")

    assert vozes == []


def test_azure_validar_configuracao_retorna_false():
    """AzureTTS.validar_configuracao retorna (False, mensagem)."""
    provedor = AzureTTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is False
    assert "nao implementado" in mensagem.lower() or "azure" in mensagem.lower()
