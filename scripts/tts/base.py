"""Contrato abstrato dos provedores de TTS (CLAUDE.md secao 5.6).

Cada provedor (scripts/tts/google.py, e os stubs elevenlabs.py/openai.py/
azure.py) implementa esta interface. scripts/4_obter_audio.py so conhece
este contrato - nunca importa um modulo de provedor especifico
diretamente, sempre atraves de scripts/tts/__init__.py:get_provedor().
"""

from abc import ABC, abstractmethod
from pathlib import Path


class ProvedorTTS(ABC):
    @abstractmethod
    def sintetizar(self, texto: str, voz: str, saida: Path) -> dict:
        """Sintetiza `texto` em audio usando `voz`, gravando o resultado em
        `saida` (caminho de arquivo MP3).

        Retorna um dict:
        {
            "audio_path": Path,
            "alinhamento": list[dict] | None,  # None se o provedor nao fornece
            "duracao_s": float,
            "provedor": str,
            "voz_usada": str,
            "custo_estimado_usd": float,
        }
        """
        raise NotImplementedError

    @abstractmethod
    def listar_vozes(self, idioma: str) -> list:
        """Lista vozes curadas disponiveis para `idioma`. Cada voz:
        {
            "id": "en-US-Wavenet-D",
            "genero": "masculina" | "feminina",
            "descricao": "Grave e autoritativa. Ideal pra true crime.",
            "recomendada_para": ["truecrime", "historia"],
            "amostra_url": None,
        }

        Lista vazia (nunca excecao) se o idioma nao tiver vozes curadas."""
        raise NotImplementedError

    @abstractmethod
    def validar_configuracao(self) -> tuple:
        """Verifica se a chave de API deste provedor esta configurada.
        Retorna (ok: bool, mensagem: str)."""
        raise NotImplementedError
