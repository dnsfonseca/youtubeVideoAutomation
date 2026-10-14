"""Loader dinamico de prompts por perfil de conteudo (CLAUDE.md secao 3.1).

Monta o prompt de sistema final da Etapa 3 (geracao de roteiro) lendo os
arquivos de `scripts/prompts/perfis/<perfil>/` e injetando os blocos
certos conforme o idioma alvo. Nao chama nenhuma API - so string building
a partir de arquivos locais.
"""

import importlib.util
from pathlib import Path

from scripts.prompts.erros import (
    ArquivoObrigatorioAusenteError,
    IdiomaNaoSuportadoError,
    PerfilNaoEncontradoError,
)

PERFIS_DIR = Path(__file__).resolve().parent / "perfis"

# Usado so quando montar_prompt() e' chamado sem web_search_max explicito
# (ex: chamadores/testes que nao se importam com o valor exato) - o valor
# de verdade em producao vem de scripts/3_gerar_roteiro.py:WEB_SEARCH_MAX_PADRAO
# (fonte da verdade unica, ligada ao .env WEB_SEARCH_MAX). Duplicado aqui
# como fallback so' pra {WEB_SEARCH_MAX} nunca vazar sem substituicao.
_WEB_SEARCH_MAX_FALLBACK = 8


def _normalizar_idioma_para_nome_arquivo(idioma: str) -> str:
    """en-US -> en_us. Usado so para montar o nome do arquivo
    juridico_<idioma>.md - o lookup em FONTES (fontes_preferidas.py) usa
    o idioma como recebido (chaves literais tipo "en-US", "pt-BR"), sem
    essa normalizacao."""
    return idioma.strip().lower().replace("-", "_")


def _carregar_modulo_python(caminho: Path, nome_modulo: str):
    """Importa um arquivo .py solto (config.py ou fontes_preferidas.py de
    um perfil) sem exigir que scripts/prompts/perfis/<perfil>/ seja um
    pacote Python com __init__.py - cada perfil e' so uma pasta de
    conteudo, nao um modulo importavel do jeito normal."""
    spec = importlib.util.spec_from_file_location(nome_modulo, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def montar_prompt(
    perfil: str,
    idioma: str,
    web_search_max: int | None = None,
) -> str:
    """Monta o prompt de sistema completo pro perfil + idioma escolhidos.

    Args:
        perfil: nome do diretorio em scripts/prompts/perfis/ (ex: "truecrime")
        idioma: codigo de idioma (en-US, en-GB, pt-BR, es, de)
        web_search_max: teto de buscas web da Etapa 3 (CLAUDE.md secao 7,
                     env var WEB_SEARCH_MAX) - interpolado no placeholder
                     {WEB_SEARCH_MAX} de sistema.md, se presente (perfis
                     sem esse placeholder ignoram o valor). None usa
                     _WEB_SEARCH_MAX_FALLBACK.

    Returns:
        string unica com o prompt completo montado (placeholders
        {BLOCO_JURIDICO}, {FONTES_PREFERIDAS} e {WEB_SEARCH_MAX} de
        sistema.md ja substituidos).

    Raises:
        PerfilNaoEncontradoError: perfil nao corresponde a nenhuma pasta
            em scripts/prompts/perfis/.
        ArquivoObrigatorioAusenteError: falta um arquivo essencial do
            perfil (config.py, sistema.md ou fontes_preferidas.py).
        IdiomaNaoSuportadoError: CONFIG["usa_juridico"] e' True mas falta
            juridico_<idioma_normalizado>.md para o idioma pedido.
    """
    pasta_perfil = PERFIS_DIR / perfil
    if not pasta_perfil.is_dir():
        raise PerfilNaoEncontradoError(perfil)

    caminho_config = pasta_perfil / "config.py"
    if not caminho_config.exists():
        raise ArquivoObrigatorioAusenteError(perfil, "config.py")
    modulo_config = _carregar_modulo_python(
        caminho_config, f"broll_foundry_perfil_{perfil}_config"
    )
    config = getattr(modulo_config, "CONFIG", None)
    if config is None:
        raise ArquivoObrigatorioAusenteError(perfil, "config.py (falta o dict CONFIG)")

    caminho_sistema = pasta_perfil / "sistema.md"
    if not caminho_sistema.exists():
        raise ArquivoObrigatorioAusenteError(perfil, "sistema.md")
    prompt = caminho_sistema.read_text(encoding="utf-8")

    if config.get("usa_juridico"):
        idioma_arquivo = _normalizar_idioma_para_nome_arquivo(idioma)
        caminho_juridico = pasta_perfil / f"juridico_{idioma_arquivo}.md"
        if not caminho_juridico.exists():
            raise IdiomaNaoSuportadoError(perfil, idioma)
        bloco_juridico = caminho_juridico.read_text(encoding="utf-8")
    else:
        bloco_juridico = ""
    prompt = prompt.replace("{BLOCO_JURIDICO}", bloco_juridico)

    caminho_fontes = pasta_perfil / "fontes_preferidas.py"
    if not caminho_fontes.exists():
        raise ArquivoObrigatorioAusenteError(perfil, "fontes_preferidas.py")
    modulo_fontes = _carregar_modulo_python(
        caminho_fontes, f"broll_foundry_perfil_{perfil}_fontes"
    )
    fontes_por_idioma = getattr(modulo_fontes, "FONTES", {})
    fontes_do_idioma = fontes_por_idioma.get(idioma, [])
    texto_fontes = "\n".join(f"- {fonte}" for fonte in fontes_do_idioma)
    prompt = prompt.replace("{FONTES_PREFERIDAS}", texto_fontes)

    valor_web_search_max = web_search_max if web_search_max is not None else _WEB_SEARCH_MAX_FALLBACK
    prompt = prompt.replace("{WEB_SEARCH_MAX}", str(valor_web_search_max))

    return prompt


def listar_perfis() -> list:
    """Lista os perfis disponiveis em PERFIS_DIR, para preencher o
    dropdown "Tipo de conteudo" do formulario de Novo projeto e a tela
    /sobre (CLAUDE.md secoes 3.1 e 16). Cada item retornado:
    {"nome": "truecrime", "nome_exibicao": "True Crime",
    "descricao_curta": "..."}.

    Uma pasta sem config.py e' ignorada silenciosamente aqui (nao
    aparece na lista) - montar_prompt() e' quem levanta
    ArquivoObrigatorioAusenteError quando alguem de fato tenta usar esse
    perfil incompleto, esta funcao so alimenta a UI de selecao."""
    perfis = []
    if not PERFIS_DIR.is_dir():
        return perfis
    for pasta in sorted(PERFIS_DIR.iterdir()):
        if not pasta.is_dir():
            continue
        caminho_config = pasta / "config.py"
        if not caminho_config.exists():
            continue
        modulo_config = _carregar_modulo_python(
            caminho_config, f"broll_foundry_perfil_{pasta.name}_config_listagem"
        )
        config = getattr(modulo_config, "CONFIG", {}) or {}
        caminho_descricao = pasta / "descricao_curta.txt"
        descricao_curta = (
            caminho_descricao.read_text(encoding="utf-8").strip()
            if caminho_descricao.exists()
            else ""
        )
        perfis.append(
            {
                "nome": pasta.name,
                "nome_exibicao": config.get("nome_exibicao", pasta.name),
                "descricao_curta": descricao_curta,
            }
        )
    return perfis


def listar_perfis_detalhado() -> list:
    """Lista os perfis disponiveis com os metadados usados pela tela /sobre
    (CLAUDE.md secao 16, secao "Perfis de conteudo"): nome_exibicao,
    descricao_curta, descricao_longa_md (markdown cru - a rota /sobre
    converte para HTML) e custo_min/custo_max (de
    CONFIG["custo_estimado_por_video_usd"]).

    Mesmo espirito de listar_perfis(): uma pasta sem config.py e' ignorada
    silenciosamente, nao levanta erro (isso e' responsabilidade de
    montar_prompt() quando alguem de fato tenta usar o perfil)."""
    perfis = []
    if not PERFIS_DIR.is_dir():
        return perfis
    for pasta in sorted(PERFIS_DIR.iterdir()):
        if not pasta.is_dir():
            continue
        caminho_config = pasta / "config.py"
        if not caminho_config.exists():
            continue
        modulo_config = _carregar_modulo_python(
            caminho_config, f"broll_foundry_perfil_{pasta.name}_config_detalhado"
        )
        config = getattr(modulo_config, "CONFIG", {}) or {}

        caminho_descricao_curta = pasta / "descricao_curta.txt"
        descricao_curta = (
            caminho_descricao_curta.read_text(encoding="utf-8").strip()
            if caminho_descricao_curta.exists()
            else ""
        )

        caminho_descricao_longa = pasta / "descricao_longa.md"
        descricao_longa_md = (
            caminho_descricao_longa.read_text(encoding="utf-8")
            if caminho_descricao_longa.exists()
            else ""
        )

        custo_min, custo_max = config.get("custo_estimado_por_video_usd", (None, None))

        perfis.append(
            {
                "nome": pasta.name,
                "nome_exibicao": config.get("nome_exibicao", pasta.name),
                "descricao_curta": descricao_curta,
                "descricao_longa_md": descricao_longa_md,
                "custo_min": custo_min,
                "custo_max": custo_max,
            }
        )
    return perfis
