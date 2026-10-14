"""Marca d'agua do CANAL (logo do usuario) aplicada por cima do video final
na Etapa 6 (scripts/6_montar_video.py) - sessao "Marca d'agua do canal
aplicada ao video final". Oposto de scripts/watermark_regions.py (que
REMOVE marca d'agua das fontes na Etapa 5 via `delogo`): aqui a marca e' do
USUARIO, aplicada por cima do video ja montado via `overlay`.

Modulo autocontido de geometria/constantes (mesmo espirito de
watermark_regions.py) - scripts/6_montar_video.py monta o comando ffmpeg de
verdade; este modulo so calcula posicao/escala/opacidade em funcao da
largura real do video (ffprobe), nunca assume 1920x1080 fixo porque
"videos_pre_gerados" (CLAUDE.md secao 3) pode ter outra resolucao.
"""

# 4 cantos - "banner_inferior"/"nenhuma" (usados na remocao, watermark_regions.py)
# nao fazem sentido aqui: marca a ADICIONAR e' sempre um logo compacto de canto,
# nunca uma faixa/banner.
POSICOES_MARCA_DAGUA_CANAL = frozenset(
    {"superior_direito", "superior_esquerdo", "inferior_direito", "inferior_esquerdo"}
)
POSICAO_PADRAO = "inferior_direito"

# Especificacao da sessao: 10% da largura do video, altura proporcional
# (scale=W:-1 preserva a proporcao do PNG), opacidade 40% do canal alfa.
LARGURA_PROPORCAO = 0.10
OPACIDADE = 0.4

# Margem das bordas, proporcional a largura do video (nao um valor fixo em
# px - "videos_pre_gerados" pode nao ser 1920 de largura). 2.5% e' a mesma
# ordem de grandeza da margem segura de thumbnail (INSTRUCAO_AREA_SEGURA -
# scripts/imagem/openai.py) sem invadir o miolo do frame.
MARGEM_PROPORCAO = 0.025


def validar_posicao(valor: str) -> bool:
    """True se `valor` e' uma das 4 posicoes de canto suportadas."""
    return valor in POSICOES_MARCA_DAGUA_CANAL


def calcular_margem_px(largura_video: int) -> int:
    """Margem das bordas em pixels, proporcional a largura real do video.
    Nunca zero (mesmo pra video muito estreito) - `max(1, ...)` evita a
    marca colar exatamente na borda."""
    return max(1, round(largura_video * MARGEM_PROPORCAO))


def calcular_largura_marca_px(largura_video: int) -> int:
    """Largura em pixels que a marca d'agua deve ocupar (10% da largura real
    do video) - a altura e' derivada pelo proprio ffmpeg (`scale=W:-1`),
    preservando a proporcao original do PNG."""
    return max(1, round(largura_video * LARGURA_PROPORCAO))


def gerar_overlay_xy(posicao: str, largura_video: int) -> tuple[str, str]:
    """Retorna as expressoes (x, y) do filtro `overlay=` do ffmpeg para a
    posicao dada. `main_w`/`main_h`/`overlay_w`/`overlay_h` sao variaveis de
    runtime do proprio filtro `overlay` - a marca so tem a largura/altura
    FINAIS conhecidas depois do `scale`, entao usamos essas variaveis em vez
    de um numero fixo (funciona pra qualquer PNG, qualquer proporcao).

    `posicao` desconhecida (protecao defensiva - CLAUDE.md secao 18.6) cai
    no default `inferior_direito`, nunca levanta excecao."""
    margem = calcular_margem_px(largura_video)
    esquerda = f"{margem}"
    direita = f"main_w-overlay_w-{margem}"
    topo = f"{margem}"
    base = f"main_h-overlay_h-{margem}"
    mapa = {
        "superior_esquerdo": (esquerda, topo),
        "superior_direito": (direita, topo),
        "inferior_esquerdo": (esquerda, base),
        "inferior_direito": (direita, base),
    }
    return mapa.get(posicao, mapa[POSICAO_PADRAO])
