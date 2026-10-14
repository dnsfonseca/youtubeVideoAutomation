"""Testes de regressao pra correcao cirurgica do CLAUDE.md (sessao de
correcao pos-Sessoes 18-K). Nao testam prosa/redacao - so' garantem que
referencias a arquiteturas ja removidas (Veo3, deteccao de cena) nao
voltem a aparecer como se ainda existissem.

Cuidado: o CLAUDE.md legitimamente MENCIONA essas strings em contexto
historico ("Nao existem mais X", "removido na sessao de limpeza") - os
testes abaixo nao proibem a string inteira, so' o padrao que indicaria
que o item ainda esta documentado como parte viva do produto (linha de
arvore de arquivos, ou linha de tabela de env var).
"""
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CLAUDE_MD = BASE_DIR / "CLAUDE.md"


def _conteudo():
    return CLAUDE_MD.read_text(encoding="utf-8")


def test_claude_md_nao_lista_veo3_estilo_na_arvore_de_arquivos():
    """veo3_estilo.md nao existe mais em nenhum perfil (scripts/prompts/
    perfis/*/) - so' pode aparecer em prosa historica com backticks,
    nunca como linha solta de arvore de diretorio."""
    conteudo = _conteudo()
    assert not re.search(r"^\s+veo3_estilo\.md\s*(#.*)?$", conteudo, re.MULTILINE)


def test_claude_md_nao_lista_veo3_linguagem_segura_na_arvore_de_arquivos():
    conteudo = _conteudo()
    assert not re.search(
        r"^\s+veo3_linguagem_segura\.md\s*(#.*)?$", conteudo, re.MULTILINE
    )


def test_claude_md_nao_menciona_detector_cenas_fora_do_historico():
    """detector_cenas.py so' pode aparecer na frase historica unica
    ("Nao existem mais ... scripts/detector_cenas.py ..."), nunca de
    novo como se fosse parte da arquitetura atual."""
    assert _conteudo().count("detector_cenas") <= 1


def test_claude_md_nao_menciona_5_planejar_edicao_fora_do_historico():
    assert _conteudo().count("5_planejar_edicao") <= 1


def test_claude_md_nao_tem_bloco_veo3_na_tela_de_revisao():
    """O bloco "Enriquecer com cenas geradas por IA (Veo3)?" foi removido
    da tela de revisao ha' varias sessoes - CLAUDE.md nao deve mais
    descrever esse checkbox como se existisse (secao 5.5)."""
    assert 'Bloco "Enriquecer com cenas' not in _conteudo()


def test_claude_md_nao_tem_linha_de_tabela_para_google_api_key():
    """GOOGLE_API_KEY (chave do Veo3) nunca e' lida em nenhum lugar do
    codigo - nao pode mais aparecer como linha de tabela de env var
    (so' na frase "Removidas desta tabela", em prosa)."""
    conteudo = _conteudo()
    assert not re.search(r"^\|\s*`GOOGLE_API_KEY`", conteudo, re.MULTILINE)


def test_claude_md_nao_tem_linha_de_tabela_para_curadoria_semantica():
    conteudo = _conteudo()
    assert not re.search(r"^\|\s*`CURADORIA_SEMANTICA`", conteudo, re.MULTILINE)


def test_claude_md_tabela_env_usa_nomes_reais_de_legenda():
    """LEGENDA_COR/LEGENDA_CONTORNO_COR/LEGENDA_CONTORNO_ESPESSURA/
    LEGENDA_DESTAQUE_PALAVRA/LEGENDA_DESTAQUE_COR nao sao lidas em
    nenhum lugar do codigo - os nomes reais sao LEGENDA_KARAOKE_ATIVO e
    LEGENDA_DESTAQUE_COR_NOME (ver .env.example)."""
    conteudo = _conteudo()
    for nome_antigo in (
        "LEGENDA_COR",
        "LEGENDA_CONTORNO_COR",
        "LEGENDA_CONTORNO_ESPESSURA",
        "LEGENDA_DESTAQUE_PALAVRA",
        "LEGENDA_DESTAQUE_COR",
    ):
        assert not re.search(rf"^\|\s*`{nome_antigo}`", conteudo, re.MULTILINE)

    assert "LEGENDA_KARAOKE_ATIVO" in conteudo
    assert "LEGENDA_DESTAQUE_COR_NOME" in conteudo


def test_claude_md_tabela_env_tem_darkplanner():
    assert "`DARKPLANNER_API_KEY`" in _conteudo()


def test_claude_md_nao_lista_musica_de_fundo_como_fora_do_mvp():
    """Musica de fundo com ducking automatico ja esta implementada
    (secao 5.8) - nao pode mais aparecer na lista "Fora do escopo do
    MVP" (secao 3)."""
    assert "Música de fundo com ducking automático" not in _conteudo()
