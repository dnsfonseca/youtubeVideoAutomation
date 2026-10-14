"""Traducao das categorias de aviso `[⚠ ...]` que a IA insere no roteiro
(CLAUDE.md secao 5.4, Regras 4 e 5) para texto acionavel exibido na tela de
revisao (CLAUDE.md secao 5.5).

Categorias confirmadas por investigacao (Sessao 7.2):
- Ambas as instrucoes de sistema.md dos 3 perfis (truecrime,
  atualidades_narrativas, historia) so mencionam duas categorias:
  `single-source` (Regra 4/6, fato sem corroboracao) e `conflict`
  (Regra 5/6, fontes divergentes).
- Roteiros reais gerados (REAL_PROJECT_01/03/04, caso Lily & Jack Sullivan)
  so contem essas duas categorias em producao. Uma ocorrencia real trouxe
  texto livre apos a categoria (`[⚠ single-source, for the mine shaft and
  underhome search specifics]`) - por isso a extracao de categoria (em
  server.py e static/revisao.js) sempre pega so o trecho antes da primeira
  virgula.

Categorias que a IA vier a inventar fora dessas duas (o prompt nao proibe
explicitamente formatos diferentes) caem em WARNING_FALLBACK - nunca falha
silenciosamente nem quebra a renderizacao.
"""

WARNINGS_ACIONAVEIS = {
    "single-source": {
        "titulo": "Apenas uma fonte",
        "descricao": (
            "Este fato foi confirmado por apenas uma das fontes. "
            "Considere verificar em outra fonte antes de publicar, "
            "ou reformular o trecho pra deixar essa limitação clara."
        ),
    },
    "conflict": {
        "titulo": "Fontes divergem",
        "descricao": (
            "As fontes usadas dão versões diferentes desse detalhe. "
            "Escolha a versão que você considera mais confiável, "
            "ou mantenha a divergência explícita no texto."
        ),
    },
}

WARNING_FALLBACK = {
    "titulo": "Atenção sinalizada pela IA",
    "descricao": (
        "A IA sinalizou este trecho pra revisão. "
        "Se você não conhece a razão específica, reveja o texto "
        "e decida se mantém, edita ou remove."
    ),
}


def categoria_do_aviso(texto_aviso: str) -> str:
    """Extrai a categoria de um texto de aviso cru (o que fica dentro de
    `[⚠ ...]`, sem os colchetes/simbolo). Alguns avisos reais trazem texto
    livre apos a categoria, separado por virgula (ex: "single-source, for
    the mine shaft...") - so o trecho antes da primeira virgula conta como
    categoria para fins de lookup no dicionario."""
    if not texto_aviso:
        return ""
    return texto_aviso.split(",", 1)[0].strip()


def traduzir_aviso(texto_aviso: str) -> dict:
    """Retorna {"titulo", "descricao"} para o texto de aviso cru, caindo em
    WARNING_FALLBACK se a categoria nao for reconhecida."""
    categoria = categoria_do_aviso(texto_aviso)
    return WARNINGS_ACIONAVEIS.get(categoria, WARNING_FALLBACK)
