"""Testes de correcoes de UI que sobreviveram a reconstrucao da tela de
thumbnail (Sessao pos-Sessao 26): botao duplicado em Ajustes, posicao do
link Voltar em revisao_roteiro, e a garantia de que coletarTextos() nunca
envia background_prompt pro backend.

Os testes do Grupo A original desta sessao de correcoes (destaque de
selecao nos grids "Candidatos com rosto"/"Cenário") saem daqui - os dois
grids foram removidos por inteiro na reconstrucao da Etapa 7 (upload de
sujeitos com papel declarado substitui a identificacao automatica por
Vision-sobre-clipe - ver docstring de scripts/7_thumbnail.py). A cobertura
de UI da tela nova vive em tests/test_thumbnail_rotas.py.

CLAUDE.md secao 8: sem runtime JS neste projeto (sem package.json/node),
entao os testes abaixo verificam o CODIGO FONTE de static/thumbnail.js e
dos templates - mesmo espirito do teste estatico de tests/test_iniciar_bat.py
sobre iniciar.bat."""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
THUMBNAIL_JS = (BASE_DIR / "static" / "thumbnail.js").read_text(encoding="utf-8")
AJUSTES_HTML = (BASE_DIR / "templates" / "ajustes.html").read_text(encoding="utf-8")
REVISAO_HTML = (BASE_DIR / "templates" / "revisao_roteiro.html").read_text(encoding="utf-8")
THUMBNAIL_HTML = (BASE_DIR / "templates" / "thumbnail.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# GRUPO B (sessao de correcoes anterior) - um unico botao de acao primaria
# em Ajustes
# ---------------------------------------------------------------------------


def test_ajustes_html_source_tem_um_unico_botao_salvar():
    """A duplicata era um <button type="submit" class="btn btn-primary">
    solto no rodapé do <form id="form-ajustes">, alem do botao no
    acoes_header. So' deve sobrar o do header."""
    ocorrencias = re.findall(r'<button type="submit"[^>]*>\s*Salvar', AJUSTES_HTML)
    assert len(ocorrencias) == 1


def test_get_ajustes_pagina_renderizada_tem_um_unico_botao_salvar(client):
    pagina = client.get("/ajustes").get_data(as_text=True)
    ocorrencias = re.findall(r'<button type="submit"[^>]*>\s*Salvar', pagina)
    assert len(ocorrencias) == 1


# ---------------------------------------------------------------------------
# GRUPO C (sessao de correcoes anterior) - posicao do link Voltar em
# revisao_roteiro (dentro da barra de pipeline, igual ao padrao majoritario
# de status/thumbnail/concluido)
# ---------------------------------------------------------------------------


def test_revisao_roteiro_link_voltar_dentro_do_bloco_pipeline():
    bloco_pipeline = REVISAO_HTML[REVISAO_HTML.index("{% block pipeline %}") : REVISAO_HTML.index("{% endblock %}", REVISAO_HTML.index("{% block pipeline %}"))]
    assert "Voltar" in bloco_pipeline


def test_revisao_roteiro_nao_tem_mais_link_voltar_solto_no_corpo():
    bloco_conteudo_inicio = REVISAO_HTML.index("{% block conteudo %}")
    trecho = REVISAO_HTML[bloco_conteudo_inicio : bloco_conteudo_inicio + 400]
    assert "link-voltar" not in trecho


def _criar_projeto_revisao(tmp_path, nome, status="aguardando_revisao"):
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta / "roteiro.md").write_text("Roteiro de teste", encoding="utf-8")
    (pasta / "titulos_sugeridos.json").write_text(json.dumps({"titulos": [], "descricoes": []}), encoding="utf-8")
    (pasta / "job.json").write_text(json.dumps({"nome": nome, "status": status, "etapa_atual": "revisao"}), encoding="utf-8")
    return projetos_dir


def test_tela_revisao_roteiro_renderizada_tem_voltar_dentro_da_pipeline_acoes(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_revisao(tmp_path, "caso_voltar_revisao")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    pagina = client.get("/projetos/caso_voltar_revisao/revisar_roteiro").get_data(as_text=True)

    assert 'class="pipeline-acoes"' in pagina
    inicio_acoes = pagina.index('class="pipeline-acoes"')
    fim_acoes = pagina.index("</div>", inicio_acoes)
    trecho_acoes = pagina[inicio_acoes:fim_acoes]
    assert trecho_acoes.count(">Voltar<") == 1
    assert 'class="link-voltar"' not in pagina


# ---------------------------------------------------------------------------
# Sessao de simplificacao da Etapa 7 - o bloco "Textos da thumbnail" (e a
# funcao coletarTextos() que o acompanhava) foi removido por inteiro; o
# briefing exportavel passou a ser o UNICO campo de texto editavel da
# tela. A garantia que sobrevive - background_prompt nunca sai do
# navegador pro backend - agora e' estrutural: nenhuma funcao em
# thumbnail.js sequer conhece essa chave.
# ---------------------------------------------------------------------------


def test_thumbnail_js_nunca_envia_background_prompt_num_payload():
    """background_prompt e' campo interno gerado pelo servidor (Grupo D) -
    a tela nao tem mais NENHUM campo estruturado editavel (so' o texto do
    briefing), entao a chave nao pode aparecer dentro de nenhum objeto
    passado pra' postJson (pode aparecer em comentario, isso e' so'
    documentacao)."""
    for match in re.finditer(r"postJson\([^;]*?\);", THUMBNAIL_JS, re.DOTALL):
        assert "background_prompt" not in match.group(0)


def test_thumbnail_js_briefing_e_o_unico_campo_de_texto_persistido_pelo_cliente():
    """salvar_briefing/gerar_composicao_ia so' mandam briefing_completo -
    nenhum outro campo estruturado (headline/accent/etc) e' lido do DOM
    pelo JS pra' ser enviado ao servidor."""
    assert "campoBriefing.value" in THUMBNAIL_JS
    for campo_removido in ("campo-subject-name", "campo-headline", "campo-accent", "campo-layout", "campo-style"):
        assert campo_removido not in THUMBNAIL_JS


# ---------------------------------------------------------------------------
# Item 2 (sessao de correcoes de composicao/interface, preservado na
# simplificacao) - escolher uma composicao so' MARCA a selecao (destaque
# visual), nunca finaliza o projeto sozinha. So' o botao separado
# "Finalizar projeto" (com confirmacao explicita) de fato chama o backend
# e conclui o job.
# ---------------------------------------------------------------------------


def test_selecionar_composicao_nunca_chama_o_backend():
    match = re.search(r"function selecionarComposicao\([^)]*\)\s*{(.*?)\n  }", THUMBNAIL_JS, re.DOTALL)
    assert match is not None, "funcao selecionarComposicao nao encontrada"
    corpo = match.group(1)
    assert "postJson" not in corpo
    assert "urlEscolherComposicao" not in corpo
    assert "window.location" not in corpo


def test_finalizar_projeto_pede_confirmacao_explicita_antes_de_chamar_o_backend():
    """Correcao de sessao de refinamento: window.confirm() nativo (caixa do
    sistema, fora do tema escuro) foi substituido pelo modal do tema
    (static/confirm_modal.js, BrollFoundryConfirm.perguntar) - a chamada ao
    backend so' acontece dentro do .then(), depois da confirmacao."""
    match = re.search(r"function finalizarProjeto\(\)\s*{(.*?)\n  }", THUMBNAIL_JS, re.DOTALL)
    assert match is not None, "funcao finalizarProjeto nao encontrada"
    corpo = match.group(1)
    assert "window.confirm(" not in corpo
    assert "BrollFoundryConfirm.perguntar(" in corpo
    assert "urlEscolherComposicao" in corpo
    assert "postJson" in corpo


def test_thumbnail_html_tem_botao_finalizar_projeto_separado_do_grid():
    assert 'id="btn-finalizar-projeto"' in THUMBNAIL_HTML
    assert "BrollFoundryThumbnail.finalizarProjeto()" in THUMBNAIL_HTML
    # O botao comeca desabilitado - so' habilita depois de uma selecao (JS:
    # atualizarBotaoFinalizar()) - nunca finaliza sem escolha nenhuma.
    inicio = THUMBNAIL_HTML.index('id="btn-finalizar-projeto"')
    fim = THUMBNAIL_HTML.index(">", inicio)
    assert "disabled" in THUMBNAIL_HTML[inicio:fim]


def test_thumbnail_html_grid_forca_moldura_16_9_sem_sangrar():
    """GRUPO G (sessao de simplificacao): a API sempre devolve a
    composicao ja' em 16:9 exato (1536x864, scripts/imagem/openai.py:
    TAMANHO_API_COMPOSICAO) - o grid usa uma moldura fixa
    (aspect-ratio:16/9 + overflow:hidden) pra' a imagem nunca sangrar pra'
    fora do container, com object-fit:cover garantindo que ela preencha a
    moldura mesmo numa eventual variacao minima de proporcao."""
    assert "aspect-ratio:16/9" in THUMBNAIL_HTML
    assert "overflow:hidden" in THUMBNAIL_HTML
    assert "object-fit:cover" in THUMBNAIL_HTML
