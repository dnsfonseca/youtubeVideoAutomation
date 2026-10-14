"""Testes da Sessao de correcoes UX (Grupo D.1/D.2): os perfis
`atualidades_narrativas` e `historia` nao tinham secao explicita de
"Comprimento do roteiro" nem regra anti-hedging (resolucao narrativa de
conflitos) - so o perfil `truecrime` tinha as duas. Confirma so que as
secoes foram adicionadas e que a montagem de prompt via loader continua
funcionando - nao testa qualidade editorial do texto em si."""

from pathlib import Path

from scripts.prompts import loader

PERFIS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "prompts" / "perfis"


def _ler_sistema(perfil: str) -> str:
    return (PERFIS_DIR / perfil / "sistema.md").read_text(encoding="utf-8")


def test_truecrime_ja_tinha_e_continua_com_regra_absoluta_e_proibido():
    texto = _ler_sistema("truecrime")
    assert "REGRA ABSOLUTA" in texto
    assert "PROIBIDO" in texto
    assert "Comprimento do roteiro" in texto


def test_atualidades_narrativas_contem_secao_resolucao_narrativa_de_conflitos():
    texto = _ler_sistema("atualidades_narrativas")
    assert "Resolução narrativa de conflitos entre fontes" in texto
    assert "REGRA ABSOLUTA" in texto
    assert "PROIBIDO" in texto
    assert "ESCOLHA UMA versão" in texto


def test_atualidades_narrativas_contem_secao_comprimento_do_roteiro():
    """A secao existe, mas nao pode mais citar faixa numerica propria - o
    unico numero valido de tamanho vem do bloco montado em runtime por
    scripts/3_gerar_roteiro.py:_montar_bloco_tamanho_alvo (Investigacao de
    tamanho curto, Grupo A). Um teste que travasse nesse numero literal
    seria o mesmo bug do prompt virando contrato de teste."""
    texto = _ler_sistema("atualidades_narrativas")
    assert "Comprimento do roteiro" in texto
    assert "25.000-35.000 caracteres" not in texto
    assert "20.000" not in texto
    assert "40.000" not in texto


def test_historia_contem_secao_resolucao_narrativa_de_divergencias():
    texto = _ler_sistema("historia")
    assert "Resolução narrativa de divergências historiográficas" in texto
    assert "REGRA ABSOLUTA" in texto
    assert "PROIBIDO" in texto
    assert "ESCOLHA UMA versão" in texto


def test_historia_contem_secao_comprimento_do_roteiro():
    """Ver docstring de test_atualidades_narrativas_contem_secao_comprimento_do_roteiro
    acima - mesma razao para checar AUSENCIA da faixa numerica, nao presenca."""
    texto = _ler_sistema("historia")
    assert "Comprimento do roteiro" in texto
    assert "25.000-35.000 caracteres" not in texto
    assert "20.000" not in texto
    assert "40.000" not in texto


def test_novas_secoes_ficam_fora_do_bloco_juridico_atualidades():
    texto = _ler_sistema("atualidades_narrativas")
    indice_bloco_juridico = texto.index("{BLOCO_JURIDICO}")
    indice_resolucao = texto.index("Resolução narrativa de conflitos entre fontes")
    assert indice_resolucao < indice_bloco_juridico


def test_novas_secoes_ficam_fora_do_bloco_juridico_historia():
    texto = _ler_sistema("historia")
    indice_bloco_juridico = texto.index("{BLOCO_JURIDICO}")
    indice_resolucao = texto.index("Resolução narrativa de divergências historiográficas")
    assert indice_resolucao < indice_bloco_juridico


def test_loader_monta_prompt_dos_3_perfis_sem_erro_apos_revisao():
    for perfil in ("truecrime", "atualidades_narrativas", "historia"):
        prompt = loader.montar_prompt(perfil, "en-US", web_search_max=4)
        assert isinstance(prompt, str) and prompt.strip()
        assert "{WEB_SEARCH_MAX}" not in prompt
        assert "{BLOCO_JURIDICO}" not in prompt
