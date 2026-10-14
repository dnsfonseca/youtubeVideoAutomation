"""Stub do provedor Azure TTS (CLAUDE.md secao 5.6) - nao implementado
nesta sessao. Ver docstring de scripts/tts/elevenlabs.py (mesmo espirito)."""

from pathlib import Path

from .base import ProvedorTTS

_MENSAGEM = (
    "Provedor Azure TTS ainda nao implementado no MVP. Use 'google' por "
    "enquanto. Este provedor sera adicionado em versao futura."
)


class AzureTTS(ProvedorTTS):
    def sintetizar(self, texto: str, voz: str, saida: Path) -> dict:
        raise NotImplementedError(_MENSAGEM)

    def listar_vozes(self, idioma: str) -> list:
        return []

    def validar_configuracao(self) -> tuple:
        return False, _MENSAGEM
