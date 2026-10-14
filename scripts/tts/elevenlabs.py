"""Stub do provedor ElevenLabs (CLAUDE.md secao 5.6) - nao implementado
nesta sessao. Estrutura pronta para uma sessao futura pos-MVP: quando for
implementado de verdade, so este arquivo muda (mesma interface ProvedorTTS,
mesmo registro em scripts/tts/__init__.py)."""

from pathlib import Path

from .base import ProvedorTTS

_MENSAGEM = (
    "Provedor ElevenLabs ainda nao implementado no MVP. Use 'google' por "
    "enquanto. Este provedor sera adicionado em versao futura."
)


class ElevenLabsTTS(ProvedorTTS):
    def sintetizar(self, texto: str, voz: str, saida: Path) -> dict:
        raise NotImplementedError(_MENSAGEM)

    def listar_vozes(self, idioma: str) -> list:
        return []

    def validar_configuracao(self) -> tuple:
        return False, _MENSAGEM
