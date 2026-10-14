"""Testes de regressao pro bug do tipo_projeto no formulario /novo:
clicar em "Criar projeto" com "Videos pre-gerados" selecionado nao fazia
nada, sem erro visivel, sem redirect.

Causa raiz original: os campos "nome" (name="nome") e "links[]" do modo
pipeline completa tinham o atributo `required` fixo no HTML e ficavam
dentro de `#secao-pipeline-completa`, escondida via `display:none` quando
tipo_projeto="videos_pre_gerados". Mesmo padrao do bug da Sessao 20.1
(modo_fontes) - um campo obrigatorio escondido trava a validacao nativa
HTML5 do navegador em silencio.

Regressao adicional (Grupo D, sessao de correcoes UX seguinte): mesmo
depois do JS remover o `required` da secao escondida (o que destrava o
submit), "nome" continuava fisicamente dentro de
`#secao-pipeline-completa` - entao ao escolher "Videos pre-gerados" o
campo sumia da tela e o backend recebia `nome=""`, rejeitando com
"Informe um nome para o projeto." Fix: "nome" saiu de dentro da secao
condicional e virou campo sempre visivel (perfil -> nome -> radio
tipo_projeto), sem precisar de nenhum bookkeeping de `required`.

pytest faz requests HTTP diretas (via Flask test client), sem motor de
JS/DOM - nao reproduz a validacao HTML5 do navegador nem executa
static/novo_projeto.js. Por isso os testes aqui se dividem em duas
categorias, no mesmo espirito de test_novo_projeto_modo_separado_ui.py:
1. Testes de estrutura HTML (o que o servidor renderiza) - via `client`.
2. Testes estaticos sobre o conteudo do JS - garantem que a logica de
   ajuste de `required` existe e esta com a forma esperada. Nao
   substituem o teste manual no navegador real (CLAUDE.md secao 8).
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
JS_PATH = BASE_DIR / "static" / "novo_projeto.js"


# ---------------------------------------------------------------------------
# Estrutura HTML renderizada por GET /novo
# ---------------------------------------------------------------------------


def test_novo_projeto_html_pipeline_completa_tem_required(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'id="secao-pipeline-completa"' in pagina

    inicio_secao = pagina.index('id="secao-pipeline-completa"')
    fim_secao = pagina.index('id="secao-videos-pre-gerados"')
    trecho_pipeline = pagina[inicio_secao:fim_secao]

    match_link = re.search(r'<input[^>]*name="links\[\]"[^>]*>', trecho_pipeline)
    assert match_link is not None
    assert "required" in match_link.group(0)


def test_novo_projeto_html_nome_sempre_visivel_fora_da_secao_pipeline_completa(client):
    """Grupo D: "nome" nao mora mais dentro de #secao-pipeline-completa -
    e' campo sempre visivel, na ordem perfil -> nome -> radio tipo_projeto
    -> secao condicional, e nunca fica vazio so' porque o usuario escolheu
    "Videos pre-gerados"."""
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    indice_perfil = pagina.index('id="perfil"')
    indice_nome = pagina.index('name="nome"')
    indice_tipo_projeto_radio = pagina.index('name="tipo_projeto"')
    indice_secao_pipeline = pagina.index('id="secao-pipeline-completa"')

    assert indice_perfil < indice_nome < indice_tipo_projeto_radio < indice_secao_pipeline

    match_nome = re.search(r'<input[^>]*name="nome"[^>]*>', pagina)
    assert match_nome is not None
    assert "required" in match_nome.group(0)

    inicio_secao_pipeline = pagina.index('id="secao-pipeline-completa"')
    fim_secao_pipeline = pagina.index('id="secao-videos-pre-gerados"')
    trecho_pipeline = pagina[inicio_secao_pipeline:fim_secao_pipeline]
    assert 'name="nome"' not in trecho_pipeline

    inicio_secao_videos = pagina.index('id="secao-videos-pre-gerados"')
    trecho_videos = pagina[inicio_secao_videos:]
    assert 'name="nome"' not in trecho_videos


def test_novo_projeto_html_videos_pre_gerados_tem_required(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    inicio_secao = pagina.index('id="secao-videos-pre-gerados"')
    trecho_videos = pagina[inicio_secao:]

    match = re.search(r'<input[^>]*name="videos_pre_gerados\[\]"[^>]*>', trecho_videos)
    assert match is not None
    # So' vem `required` quando tipo_projeto_atual ja' e' videos_pre_gerados
    # (default do form e' pipeline_completa, entao aqui deve estar ausente).
    assert "required" not in match.group(0)


def test_novo_projeto_html_secao_pipeline_completa_escondida_quando_form_reenvia_videos_pre_gerados(client):
    resposta = client.post(
        "/novo",
        data={"nome": "", "perfil": "", "tipo_projeto": "videos_pre_gerados"},
    )
    pagina = resposta.get_data(as_text=True)

    inicio_pipeline = pagina.index('id="secao-pipeline-completa"')
    fim_pipeline_tag = pagina.index(">", inicio_pipeline)
    tag_pipeline = pagina[inicio_pipeline:fim_pipeline_tag]
    assert "display:none" in tag_pipeline

    inicio_videos = pagina.index('id="secao-videos-pre-gerados"')
    fim_videos_tag = pagina.index(">", inicio_videos)
    tag_videos = pagina[inicio_videos:fim_videos_tag]
    assert "display:none" not in tag_videos


# ---------------------------------------------------------------------------
# static/novo_projeto.js - logica de ajuste de required por tipo_projeto
# ---------------------------------------------------------------------------


def _corpo_aplicar_tipo_projeto(conteudo):
    match = re.search(r"function aplicarTipoProjeto\s*\([^)]*\)\s*\{(.*?)\n  \}", conteudo, re.S)
    assert match is not None, "funcao aplicarTipoProjeto() nao encontrada em novo_projeto.js"
    return match.group(1)


def test_js_ajusta_requireds_por_tipo_projeto():
    conteudo = JS_PATH.read_text(encoding="utf-8")
    corpo = _corpo_aplicar_tipo_projeto(conteudo)

    # Precisa capturar TODOS os [required] de dentro de secao-pipeline-completa
    # (nao so' o input de videos pre-gerados) ao esconder a secao, e restaurar
    # ao voltar - senao "nome"/"links[]" ficam required numa secao oculta.
    assert 'secaoPipelineCompleta.querySelectorAll("[required]")' in corpo
    assert "removeAttribute(\"required\")" in corpo
    assert "setAttribute(\"required\"" in corpo


def test_js_guarda_required_removido_em_dataset_proprio_sem_colidir_com_modo_fontes():
    conteudo = JS_PATH.read_text(encoding="utf-8")

    # Namespace de atributo dedicado (distinto de data-required-quando, usado
    # pelo toggle de modo_fontes da Sessao 20.1) - evita que os dois toggles
    # se pisem quando convivem (ex: tipo=pipeline_completa + modo_fontes=separado).
    assert "data-required-tipo-projeto" in conteudo
    assert "dataset.requiredTipoProjeto" in conteudo
    assert "data-required-quando" in conteudo  # fix antigo tem que continuar existindo


def test_js_toggle_de_tipo_projeto_chama_ajuste_de_required_no_dom_content_loaded():
    conteudo = JS_PATH.read_text(encoding="utf-8")
    corpo = _corpo_aplicar_tipo_projeto(conteudo)

    assert "secaoPipelineCompleta.style.display" in corpo
    assert "secaoVideosPreGerados.style.display" in corpo

    # aplicarTipoProjeto() precisa ser chamada tanto no change dos radios
    # quanto uma vez no carregamento da pagina (estado inicial do form).
    assert re.search(r"radio\.addEventListener\(\"change\",\s*aplicarTipoProjeto\)", conteudo)
    assert re.search(r"\}\)\s*;\s*\n\s*aplicarTipoProjeto\(\)\s*;", conteudo)
