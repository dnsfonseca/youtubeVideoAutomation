"""Regioes de marca d'agua e filtro ffmpeg `delogo` correspondente
(CLAUDE.md secao 5.7.1) - usado pela Etapa 7 (scripts/7_renderizar_clipes.py)
para remover a marca d'agua da posicao escolhida pelo usuario no
formulario de Novo projeto (entrada/marcas_dagua.json) antes de aplicar
Ken Burns e escalar para a resolucao final.

Modulo autocontido (CLAUDE.md secao 9) - so a lista de posicoes validas e'
compartilhada com scripts/validators.py (MARCAS_DAGUA_VALIDAS), que e'
quem valida o formulario; aqui so as coordenadas e a construcao do filtro.

Coordenadas assumem video-fonte 1920x1080 (CLAUDE.md secao 5.7.1) - se a
fonte tiver outra resolucao, escalar proporcionalmente antes de aplicar
fica para quando um caso real exigir (nao e' escopo desta sessao).
"""

REGIOES_MARCA_DAGUA = {
    "nenhuma": None,
    "superior_direito": {"x": 1620, "y": 30, "w": 270, "h": 110},
    "superior_esquerdo": {"x": 30, "y": 30, "w": 270, "h": 110},
    "inferior_direito": {"x": 1620, "y": 940, "w": 270, "h": 110},
    "inferior_esquerdo": {"x": 30, "y": 940, "w": 270, "h": 110},
    "banner_inferior": {"x": 0, "y": 980, "w": 1920, "h": 100},
}


def gerar_filtro_delogo(posicao: str) -> str | None:
    """Retorna o filtro `delogo=...` do ffmpeg para `posicao`, ou None se
    `posicao` for "nenhuma" ou nao for uma posicao conhecida (nunca
    levanta excecao - CLAUDE.md secao 18.6, entrada invalida vira
    ausencia de filtro, nao crash)."""
    try:
        regiao = REGIOES_MARCA_DAGUA.get(posicao)
    except TypeError:
        # `posicao` de tipo nao-hasheavel (ex: list) - trata como posicao
        # desconhecida em vez de propagar o TypeError.
        return None
    if regiao is None:
        return None
    return f"delogo=x={regiao['x']}:y={regiao['y']}:w={regiao['w']}:h={regiao['h']}"
