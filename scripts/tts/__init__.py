"""Fabrica de provedores de TTS (CLAUDE.md secao 5.6).

scripts/4_obter_audio.py e server.py (endpoint /api/vozes/<provedor>/<idioma>)
so conhecem esta funcao - nunca importam um modulo de provedor especifico
diretamente. Adicionar um provedor novo (pos-MVP) e' so registra-lo em
_PROVEDORES; nenhum outro codigo precisa mudar.
"""

from .azure import AzureTTS
from .base import ProvedorTTS
from .darkplanner import DarkPlannerTTS
from .elevenlabs import ElevenLabsTTS
from .erros import (
    ChaveTTSAusenteError,
    ChaveTTSInvalidaError,
    ProvedorTTSInvalidoError,
    QuotaExcedidaError,
    TextoMuitoLongoError,
    TierNaoPermitidoError,
    TTSErro,
    VozInvalidaError,
)
from .google import GoogleTTS
from .openai import OpenAITTS

_PROVEDORES = {
    "google": GoogleTTS,
    "elevenlabs": ElevenLabsTTS,
    "openai": OpenAITTS,
    "azure": AzureTTS,
    "darkplanner": DarkPlannerTTS,
}


def get_provedor(nome: str) -> ProvedorTTS:
    """Retorna uma instancia do provedor TTS pelo nome.

    Provedores disponiveis:
    - "google" (implementado, default/principal - CLAUDE.md secao 5.6)
    - "darkplanner" (implementado - vozes ElevenLabs via plano PRO ja pago,
      API assincrona com polling encapsulado em sintetizar() -
      scripts/tts/darkplanner.py)
    - "elevenlabs" (stub, sintetizar()/validar_configuracao() indicam
      "nao implementado")
    - "openai" (stub, idem)
    - "azure" (stub, idem)

    Levanta ProvedorTTSInvalidoError se `nome` nao corresponder a nenhum
    provedor registrado."""
    classe = _PROVEDORES.get(nome)
    if classe is None:
        raise ProvedorTTSInvalidoError(nome, sorted(_PROVEDORES))
    return classe()


__all__ = [
    "ProvedorTTS",
    "TTSErro",
    "ProvedorTTSInvalidoError",
    "ChaveTTSAusenteError",
    "ChaveTTSInvalidaError",
    "QuotaExcedidaError",
    "VozInvalidaError",
    "TierNaoPermitidoError",
    "TextoMuitoLongoError",
    "get_provedor",
]
