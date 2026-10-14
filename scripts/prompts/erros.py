"""Excecoes customizadas do loader de prompts (scripts/prompts/loader.py).

Cada uma carrega uma mensagem pronta pra exibir ao usuario final (nunca
so um traceback cru) - CLAUDE.md secao 3.1: "Faltar um [arquivo do
perfil] levanta erro claro na inicializacao do servidor, nao no meio do
pipeline."
"""

from pathlib import Path

# Independente do PERFIS_DIR de scripts/prompts/loader.py de proposito -
# erros.py fica utilizavel (e a mensagem de PerfilNaoEncontradoError
# continua correta) mesmo em testes que monkeypatcham loader.PERFIS_DIR
# para simular um perfil incompleto num diretorio temporario.
_PERFIS_DIR = Path(__file__).resolve().parent / "perfis"


def _listar_perfis_disponiveis() -> list:
    """Nomes dos perfis que existem de verdade em disco (pasta contendo
    config.py) - usado so para compor a mensagem amigavel de
    PerfilNaoEncontradoError."""
    if not _PERFIS_DIR.is_dir():
        return []
    return sorted(
        pasta.name
        for pasta in _PERFIS_DIR.iterdir()
        if pasta.is_dir() and (pasta / "config.py").exists()
    )


class PromptErro(Exception):
    """Classe base das excecoes do loader de prompts (scripts/prompts/loader.py)."""


class PerfilNaoEncontradoError(PromptErro):
    """O perfil pedido nao corresponde a nenhuma pasta em
    scripts/prompts/perfis/."""

    def __init__(self, perfil: str):
        self.perfil = perfil
        disponiveis = _listar_perfis_disponiveis()
        lista = ", ".join(disponiveis) if disponiveis else "(nenhum perfil encontrado)"
        super().__init__(
            f"O perfil '{perfil}' nao existe. Perfis disponiveis: {lista}."
        )


class ArquivoObrigatorioAusenteError(PromptErro):
    """O perfil existe, mas falta um arquivo que ele precisa pra montar o
    prompt (config.py, sistema.md ou fontes_preferidas.py)."""

    def __init__(self, perfil: str, arquivo: str):
        self.perfil = perfil
        self.arquivo = arquivo
        super().__init__(
            f"O perfil '{perfil}' requer o arquivo '{arquivo}' mas ele nao "
            "foi encontrado."
        )


class IdiomaNaoSuportadoError(PromptErro):
    """O perfil usa bloco juridico (CONFIG['usa_juridico'] == True), mas
    nao tem o arquivo juridico_<idioma>.md para o idioma pedido."""

    def __init__(self, perfil: str, idioma: str):
        self.perfil = perfil
        self.idioma = idioma
        super().__init__(
            f"O perfil '{perfil}' nao suporta o idioma '{idioma}' - falta o "
            "arquivo de regras juridicas correspondente para este idioma."
        )
