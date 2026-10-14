"""Excecoes customizadas dos provedores de TTS (CLAUDE.md secao 5.6).

Cada uma carrega uma mensagem pronta pra exibir ao usuario final (nunca so
um traceback cru), mesmo espirito de scripts/prompts/erros.py. Categorias
usadas por scripts/4_obter_audio.py para classificar falhas no @PROGRESSO
final (CLAUDE.md secao 18.5).
"""


class TTSErro(Exception):
    """Classe base das excecoes dos provedores de TTS (scripts/tts/)."""


class ProvedorTTSInvalidoError(TTSErro):
    """O nome de provedor pedido nao corresponde a nenhum provedor
    registrado em scripts/tts/__init__.py:get_provedor()."""

    def __init__(self, nome: str, disponiveis):
        self.nome = nome
        lista = ", ".join(disponiveis) if disponiveis else "(nenhum provedor registrado)"
        super().__init__(f"Provedor de TTS '{nome}' nao existe. Provedores disponiveis: {lista}.")


class ChaveTTSAusenteError(TTSErro):
    """A variavel de ambiente da chave de API do provedor nao esta
    configurada."""

    def __init__(self, variavel_env: str):
        self.variavel_env = variavel_env
        super().__init__(
            f"Configure {variavel_env} em Ajustes antes de usar este provedor de TTS."
        )


class ChaveTTSInvalidaError(TTSErro):
    """A API do provedor rejeitou a chave configurada (401/403)."""

    def __init__(self, mensagem: str = "Chave de TTS invalida ou sem permissao."):
        super().__init__(mensagem)


class QuotaExcedidaError(TTSErro):
    """A API do provedor recusou a chamada por limite de uso (429)."""

    def __init__(self, mensagem: str = "Limite de uso da API de TTS excedido. Tente novamente mais tarde."):
        super().__init__(mensagem)


class VozInvalidaError(TTSErro):
    """A voz pedida nao esta no catalogo curado (scripts/tts/vozes_catalogo.json)
    - protecao contra chamar a API com uma voz fora do catalogo aprovado
    (manipulacao de origem_audio.json, ou catalogo desatualizado)."""

    def __init__(self, voz: str, idioma: str = None):
        self.voz = voz
        self.idioma = idioma
        detalhe = f" para o idioma '{idioma}'" if idioma else ""
        super().__init__(f"Voz '{voz}' nao esta no catalogo curado{detalhe}.")


class TierNaoPermitidoError(TTSErro):
    """A voz pedida usa um tier de custo mais caro que o permitido
    (CLAUDE.md - protecao de custo: so Wavenet e' permitido no MVP)."""

    def __init__(self, voz: str, tier_permitido: str = "Wavenet"):
        self.voz = voz
        super().__init__(
            f"Voz '{voz}' usa um tier de custo nao permitido nesta versao. "
            f"Apenas vozes '{tier_permitido}' sao suportadas (protecao de custo)."
        )


class TextoMuitoLongoError(TTSErro):
    """Texto excede o limite de caracteres por chamada da API do provedor.
    Na pratica, scripts/tts/google.py trata isso com chunking automatico
    (ver _dividir_em_chunks) em vez de levantar este erro - mantido para
    provedores futuros que nao suportem chunking."""

    def __init__(self, tamanho: int, limite: int):
        self.tamanho = tamanho
        self.limite = limite
        super().__init__(
            f"Texto com {tamanho} caracteres excede o limite de {limite} "
            "caracteres por chamada."
        )
