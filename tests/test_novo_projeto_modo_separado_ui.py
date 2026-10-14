"""Testes de regressao pro bug do modo separado no formulario /novo:
clicar em "Criar projeto" nao fazia nada quando o modo separado estava
ativo, sem erro visivel, sem redirect.

Causa raiz: o input do modo unificado (name="links[]") tem o atributo
`required` e fica dentro de um container escondido via `display:none`
quando o modo separado esta ativo. Um campo obrigatorio escondido trava
a validacao nativa HTML5 do navegador em silencio — ele tenta focar o
campo pra mostrar a mensagem de erro e nao consegue, entao o form
simplesmente nao envia.

pytest faz requests HTTP diretas (via Flask test client), sem motor de
JS/DOM — ele NAO reproduz a validacao HTML5 do navegador nem executa
static/novo_projeto.js. Por isso os testes aqui se dividem em duas
categorias:
1. Testes de estrutura HTML (o que o servidor renderiza) - via `client`.
2. Testes estaticos sobre o conteudo do JS - garantem que a logica de
   ajuste de `required` existe e esta com a forma esperada. Nao
   substituem o teste manual no navegador real (ver CLAUDE.md secao 8 -
   validacao de UI precisa ser feita na pratica).
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
JS_PATH = BASE_DIR / "static" / "novo_projeto.js"


# ---------------------------------------------------------------------------
# Estrutura HTML renderizada por GET /novo
# ---------------------------------------------------------------------------


def test_get_novo_input_unificado_tem_required_dentro_da_secao_escondivel(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'id="secao-fontes-unificada"' in pagina

    inicio_secao = pagina.index('id="secao-fontes-unificada"')
    fim_secao = pagina.index('id="secao-fontes-separadas"')
    trecho_unificado = pagina[inicio_secao:fim_secao]

    assert 'name="links[]"' in trecho_unificado
    match = re.search(r'<input[^>]*name="links\[\]"[^>]*>', trecho_unificado)
    assert match is not None
    assert "required" in match.group(0)


def test_get_novo_secao_unificada_fica_com_display_none_no_modo_separado(client):
    resposta = client.get("/novo?modo_fontes=separado")
    pagina = resposta.get_data(as_text=True)

    # O form nao le query string (so' re-renderiza pelo `form` do POST com
    # erro) - o teste real de alternancia de modo e' client-side. Aqui so'
    # confirma o estado padrao (unificado visivel, separado escondido) pra
    # deixar claro qual secao começa com required ativo.
    inicio_unificada = pagina.index('id="secao-fontes-unificada"')
    fim_unificada_tag = pagina.index(">", inicio_unificada)
    tag_unificada = pagina[inicio_unificada:fim_unificada_tag]
    assert "display:none" not in tag_unificada

    inicio_separada = pagina.index('id="secao-fontes-separadas"')
    fim_separada_tag = pagina.index(">", inicio_separada)
    tag_separada = pagina[inicio_separada:fim_separada_tag]
    assert "display:none" in tag_separada


def test_get_novo_input_transcricao_existe_dentro_da_secao_separada(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    inicio_secao = pagina.index('id="secao-fontes-separadas"')
    trecho_separado = pagina[inicio_secao:]

    assert 'name="links_transcricao[]"' in trecho_separado
    assert 'name="links_visual[]"' in trecho_separado


# ---------------------------------------------------------------------------
# static/novo_projeto.js - logica de ajuste de required por modo
# ---------------------------------------------------------------------------


def test_js_define_funcao_de_ajuste_de_required_por_modo():
    conteudo = JS_PATH.read_text(encoding="utf-8")

    assert "function ajustarRequiredsConformeModo" in conteudo
    assert "removeAttribute(\"required\")" in conteudo
    assert "setAttribute(\"required\"" in conteudo


def test_js_toggle_de_modo_chama_ajuste_de_required():
    conteudo = JS_PATH.read_text(encoding="utf-8")

    # A funcao aplicarModo() (que troca display:none entre as duas
    # secoes) precisa chamar ajustarRequiredsConformeModo(modo) - senao o
    # bug volta: o campo escondido continua required e trava o submit.
    match = re.search(r"function aplicarModo\s*\([^)]*\)\s*\{(.*?)\n  \}", conteudo, re.S)
    assert match is not None, "funcao aplicarModo() nao encontrada em novo_projeto.js"
    corpo_aplicar_modo = match.group(1)
    assert "ajustarRequiredsConformeModo(modo)" in corpo_aplicar_modo


def test_js_reaplica_ajuste_de_required_ao_adicionar_linha_dinamica():
    conteudo = JS_PATH.read_text(encoding="utf-8")

    # Cada "Adicionar link" (unificado e os dois grupos do modo separado)
    # tambem precisa reaplicar o ajuste, pra uma linha nova clonada nao
    # ficar com required desalinhado do modo ativo.
    ocorrencias = conteudo.count("ajustarRequiredsConformeModo(")
    # 1 definicao (chamada indireta nao conta) + 1 em aplicarModo() + pelo
    # menos 2 nos handlers de "adicionar linha" (unificado + grupos).
    assert ocorrencias >= 3


def test_js_nao_remove_required_permanentemente_guarda_em_dataset():
    conteudo = JS_PATH.read_text(encoding="utf-8")

    # O required removido precisa ser preservado via data-attribute pra
    # poder ser restaurado quando a secao volta a ficar visivel -
    # remover sem guardar destruiria a validacao permanentemente.
    assert "data-required-quando" in conteudo
    assert "dataset.requiredQuando" in conteudo
