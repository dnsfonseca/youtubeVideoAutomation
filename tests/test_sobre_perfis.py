"""Testes da secao "Perfis de conteudo" na tela /sobre (CLAUDE.md secao 16):
renderiza dinamicamente os perfis lidos de scripts/prompts/perfis/ via
scripts/prompts/loader.py:listar_perfis_detalhado() - nome_exibicao,
descricao_curta, descricao_longa (convertida de markdown para HTML) e
custo estimado.
"""


def test_get_sobre_retorna_os_3_perfis(client):
    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "secao-perfis" in pagina
    assert "True Crime" in pagina
    assert "Atualidades Narrativas" in pagina
    assert "História" in pagina


def test_get_sobre_cada_card_mostra_nome_descricao_curta_e_custo(client):
    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert "card-perfil" in pagina
    # descricao_curta.txt do perfil truecrime.
    assert "rigor factual" in pagina.lower()
    assert "Custo estimado: $3-$15 por video" in pagina


def test_get_sobre_renderiza_descricao_longa_como_html(client):
    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    # descricao_longa.md do perfil truecrime tem cabecalho "## Para que
    # serve" - convertido para markdown, vira uma tag <h2>.
    assert "<h2>Para que serve</h2>" in pagina


def test_get_sobre_continua_mostrando_versao_e_botao_licenca(client):
    """Regressao: a secao de perfis nao pode substituir o conteudo
    existente da tela /sobre (versao, botao de licenca, creditos)."""
    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert "Broll Foundry" in pagina
    assert "botao-ver-licenca" in pagina
    assert "yt_automation" in pagina
