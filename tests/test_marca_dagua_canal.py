"""Testes de scripts/marca_dagua_canal.py - geometria da marca d'agua do
CANAL aplicada ao video final (sessao "Marca d'agua do canal aplicada ao
video final"). Modulo puro (sem I/O, sem subprocess) - testado sem mocks.
"""

from scripts import marca_dagua_canal as modulo


# ---------------------------------------------------------------------------
# validar_posicao
# ---------------------------------------------------------------------------


def test_validar_posicao_aceita_os_4_cantos():
    for posicao in ("superior_direito", "superior_esquerdo", "inferior_direito", "inferior_esquerdo"):
        assert modulo.validar_posicao(posicao) is True


def test_validar_posicao_rejeita_banner_inferior():
    """"banner_inferior"/"nenhuma" sao posicoes de REMOCAO (watermark_regions.py),
    nao fazem sentido para a marca a ADICIONAR."""
    assert modulo.validar_posicao("banner_inferior") is False
    assert modulo.validar_posicao("nenhuma") is False
    assert modulo.validar_posicao("qualquer_coisa") is False


# ---------------------------------------------------------------------------
# calcular_margem_px / calcular_largura_marca_px
# ---------------------------------------------------------------------------


def test_calcular_largura_marca_px_10_por_cento_da_largura_real():
    assert modulo.calcular_largura_marca_px(1920) == 192
    assert modulo.calcular_largura_marca_px(1280) == 128


def test_calcular_margem_px_proporcional_a_largura():
    assert modulo.calcular_margem_px(1920) == round(1920 * 0.025)
    assert modulo.calcular_margem_px(1280) != modulo.calcular_margem_px(1920)


def test_calcular_margem_px_nunca_zero():
    assert modulo.calcular_margem_px(1) >= 1


# ---------------------------------------------------------------------------
# gerar_overlay_xy - as 4 posicoes produzem coordenadas DISTINTAS e corretas
# ---------------------------------------------------------------------------


def test_gerar_overlay_xy_4_posicoes_sao_todas_distintas():
    resultados = {
        posicao: modulo.gerar_overlay_xy(posicao, 1920) for posicao in modulo.POSICOES_MARCA_DAGUA_CANAL
    }
    valores = list(resultados.values())
    assert len(set(valores)) == 4, f"esperava 4 combinacoes (x,y) distintas, veio {resultados}"


def test_gerar_overlay_xy_superior_esquerdo_usa_margem_nos_dois_eixos():
    x, y = modulo.gerar_overlay_xy("superior_esquerdo", 1920)
    margem = modulo.calcular_margem_px(1920)
    assert x == str(margem)
    assert y == str(margem)


def test_gerar_overlay_xy_inferior_direito_usa_expressoes_main_w_main_h():
    x, y = modulo.gerar_overlay_xy("inferior_direito", 1920)
    assert "main_w-overlay_w" in x
    assert "main_h-overlay_h" in y


def test_gerar_overlay_xy_superior_direito_x_usa_main_w_y_usa_margem():
    x, y = modulo.gerar_overlay_xy("superior_direito", 1920)
    margem = modulo.calcular_margem_px(1920)
    assert "main_w-overlay_w" in x
    assert y == str(margem)


def test_gerar_overlay_xy_inferior_esquerdo_x_usa_margem_y_usa_main_h():
    x, y = modulo.gerar_overlay_xy("inferior_esquerdo", 1920)
    margem = modulo.calcular_margem_px(1920)
    assert x == str(margem)
    assert "main_h-overlay_h" in y


def test_gerar_overlay_xy_posicao_desconhecida_cai_no_default():
    padrao = modulo.gerar_overlay_xy(modulo.POSICAO_PADRAO, 1920)
    desconhecida = modulo.gerar_overlay_xy("posicao_que_nao_existe", 1920)
    assert desconhecida == padrao
