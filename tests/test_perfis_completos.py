"""Testes dos perfis `atualidades_narrativas` e `historia` completos
(Sessao 5b - CLAUDE.md secoes 3.1 e 3.2), e teste de regressao do perfil
`truecrime` (Sessao 5a).

Cobre: proibicoes editoriais especificas de cada perfil (secao 3.2 para
atualidades_narrativas; contextualizacao temporal para historia), ausencia
do bloco juridico nos dois perfis novos, e fontes preferidas nao-vazias
para os 5 idiomas suportados nos 3 perfis do MVP.

Nunca chama a API real do Claude - so monta o prompt a partir dos
arquivos locais em scripts/prompts/perfis/ (CLAUDE.md secao 8).
"""

import pytest

from scripts.prompts import loader

IDIOMAS_SUPORTADOS = ["en-US", "en-GB", "pt-BR", "es", "de"]

# Palavras/construcoes proibidas pelo prompt do perfil atualidades_narrativas
# (CLAUDE.md secao 3.2). Checadas em minusculo contra o prompt inteiro em
# minusculo - o objetivo aqui e' confirmar que o PROMPT descreve a proibicao
# (ou seja, instrui o modelo a nao usar essas palavras), nao que a palavra
# nunca aparece em lugar nenhum do arquivo (a propria regra precisa citar a
# palavra proibida para explicar a proibicao).
PALAVRAS_PROIBIDAS_ATUALIDADES = [
    "chocante",
    "revelador",
    "verdade oculta",
    "ninguém está contando",
]


# ---------------------------------------------------------------------------
# Perfil atualidades_narrativas - proibicoes editoriais (CLAUDE.md 3.2)
# ---------------------------------------------------------------------------


def test_prompt_atualidades_narrativas_documenta_todas_as_palavras_proibidas():
    """O prompt precisa EXPLICITAMENTE proibir cada uma dessas palavras -
    isso significa que a palavra aparece no prompt (dentro da regra que a
    proibe), nao que ela esta ausente do arquivo."""
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US")
    prompt_lower = prompt.lower()

    for palavra in PALAVRAS_PROIBIDAS_ATUALIDADES:
        assert palavra in prompt_lower, f"prompt nao menciona a proibicao de '{palavra}'"


def test_prompt_atualidades_narrativas_proibe_intensificacao_de_numeros():
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US").lower()

    assert "centenas" in prompt and "milhares" in prompt
    assert "intensifica" in prompt


def test_prompt_atualidades_narrativas_proibe_gancho_de_urgencia_sem_base():
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US").lower()

    assert "urgência" in prompt or "urgencia" in prompt


def test_prompt_atualidades_narrativas_proibe_especulacao_como_fato():
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US").lower()

    assert "especula" in prompt


def test_prompt_atualidades_narrativas_incentiva_gancho_narrativo_sem_exagero():
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US").lower()

    assert "gancho" in prompt
    assert "storytelling" in prompt or "ritmo" in prompt


def test_prompt_atualidades_narrativas_exige_notas_de_rodape():
    prompt = loader.montar_prompt("atualidades_narrativas", "pt-BR")

    assert "[F1@" in prompt or "F1@04:32" in prompt
    assert "[N:" in prompt


def test_prompt_atualidades_narrativas_sinaliza_cuidado_temporal():
    prompt = loader.montar_prompt("atualidades_narrativas", "en-US").lower()

    assert "informação até" in prompt or "informacao ate" in prompt or "em andamento" in prompt


# ---------------------------------------------------------------------------
# Perfil historia - contextualizacao temporal e rigor (CLAUDE.md 3.1)
# ---------------------------------------------------------------------------


def test_prompt_historia_contem_instrucao_de_contextualizacao_temporal():
    prompt = loader.montar_prompt("historia", "en-US").lower()

    assert "contextualiza" in prompt
    assert "data" in prompt


def test_prompt_historia_exige_respeito_em_temas_graves():
    prompt = loader.montar_prompt("historia", "en-US").lower()

    assert "holocausto" in prompt
    assert "escravidão" in prompt or "escravidao" in prompt


def test_prompt_historia_distingue_consenso_academico_de_teoria_marginal():
    prompt = loader.montar_prompt("historia", "en-US").lower()

    assert "consenso" in prompt
    assert "marginal" in prompt


def test_prompt_historia_alerta_contra_anacronismo():
    prompt = loader.montar_prompt("historia", "en-US").lower()

    assert "anacron" in prompt


def test_prompt_historia_exige_notas_de_rodape():
    prompt = loader.montar_prompt("historia", "pt-BR")

    assert "[F1@" in prompt or "F1@04:32" in prompt
    assert "[N:" in prompt


# ---------------------------------------------------------------------------
# Ambos os perfis novos nao injetam bloco juridico (usa_juridico=False)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["atualidades_narrativas", "historia"])
@pytest.mark.parametrize("idioma", IDIOMAS_SUPORTADOS)
def test_perfis_sem_juridico_nao_injetam_bloco_juridico(perfil, idioma):
    prompt = loader.montar_prompt(perfil, idioma)

    assert "{BLOCO_JURIDICO}" not in prompt
    # Termos exclusivos do bloco juridico do truecrime nao podem vazar aqui.
    assert "person of interest" not in prompt.lower()


# ---------------------------------------------------------------------------
# Fontes preferidas - listas nao vazias para os 5 idiomas, nos 3 perfis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["truecrime", "atualidades_narrativas", "historia"])
@pytest.mark.parametrize("idioma", IDIOMAS_SUPORTADOS)
def test_fontes_preferidas_nao_vazias_para_todos_idiomas(perfil, idioma):
    prompt = loader.montar_prompt(perfil, idioma)

    # Se a lista de fontes estivesse vazia, o loader teria substituido
    # {FONTES_PREFERIDAS} por uma string vazia - garantimos que ha pelo
    # menos um item de fonte (marcado com "- " pelo loader) no prompt.
    assert "\n- " in prompt or prompt.count("- ") > 0


@pytest.mark.parametrize("idioma", IDIOMAS_SUPORTADOS)
def test_fontes_atualidades_narrativas_nao_vazias_direto_do_modulo(idioma):
    from scripts.prompts.perfis.atualidades_narrativas import fontes_preferidas

    assert fontes_preferidas.FONTES.get(idioma)


@pytest.mark.parametrize("idioma", IDIOMAS_SUPORTADOS)
def test_fontes_historia_nao_vazias_direto_do_modulo(idioma):
    from scripts.prompts.perfis.historia import fontes_preferidas

    assert fontes_preferidas.FONTES.get(idioma)


@pytest.mark.parametrize("idioma", IDIOMAS_SUPORTADOS)
def test_fontes_truecrime_nao_vazias_direto_do_modulo(idioma):
    from scripts.prompts.perfis.truecrime import fontes_preferidas

    assert fontes_preferidas.FONTES.get(idioma)


# ---------------------------------------------------------------------------
# Regressao - perfil truecrime continua funcionando (Sessao 5a)
# ---------------------------------------------------------------------------


def test_truecrime_continua_funcionando_apos_mudancas_do_5b():
    prompt = loader.montar_prompt("truecrime", "en-US")

    assert "{BLOCO_JURIDICO}" not in prompt
    assert "suspect" in prompt.lower()
    assert "indicted" in prompt.lower()


def test_listar_perfis_continua_listando_os_3_perfis_do_mvp():
    nomes = {p["nome"] for p in loader.listar_perfis()}

    assert nomes == {"truecrime", "atualidades_narrativas", "historia"}
