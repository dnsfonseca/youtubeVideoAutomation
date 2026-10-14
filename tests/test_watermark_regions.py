"""Testes de scripts/watermark_regions.py - regiao de marca d'agua e filtro
delogo correspondente (CLAUDE.md secao 5.7.1).

Modulo autocontido, nao faz subprocess, pode ser testado com import normal.
"""

from scripts.watermark_regions import REGIOES_MARCA_DAGUA, gerar_filtro_delogo


class TestRegioesMarCaDagua:
    """Invariantes da estrutura REGIOES_MARCA_DAGUA."""

    def test_regioes_marca_dagua_tem_todas_as_posicoes_documentadas(self):
        """CLAUDE.md secao 5.7.1 lista exatamente 6 posicoes: nenhuma + 5
        reais. Todas devem estar no dict."""
        posicoes_esperadas = {
            "nenhuma",
            "superior_direito",
            "superior_esquerdo",
            "inferior_direito",
            "inferior_esquerdo",
            "banner_inferior",
        }
        assert set(REGIOES_MARCA_DAGUA.keys()) == posicoes_esperadas

    def test_nenhuma_mapeia_para_none(self):
        assert REGIOES_MARCA_DAGUA["nenhuma"] is None

    def test_todas_as_posicoes_reais_tem_dict_com_x_y_w_h(self):
        posicoes_reais = [
            "superior_direito",
            "superior_esquerdo",
            "inferior_direito",
            "inferior_esquerdo",
            "banner_inferior",
        ]
        for posicao in posicoes_reais:
            regiao = REGIOES_MARCA_DAGUA[posicao]
            assert isinstance(regiao, dict), f"{posicao} nao e' um dict"
            assert set(regiao.keys()) == {"x", "y", "w", "h"}
            assert all(isinstance(regiao[k], int) for k in "xywh")

    def test_coordenadas_superiores_dentro_de_1080p(self):
        """Coordenadas documentadas em CLAUDE.md 5.7.1 sao para 1920x1080 -
        y deve estar abaixo de 1080, e x + w abaixo de 1920 (com folga)."""
        for posicao in ["superior_direito", "superior_esquerdo"]:
            regiao = REGIOES_MARCA_DAGUA[posicao]
            assert regiao["y"] == 30
            assert regiao["y"] + regiao["h"] <= 1080
            assert regiao["x"] + regiao["w"] <= 1920

    def test_coordenadas_inferiores_dentro_de_1080p(self):
        for posicao in ["inferior_direito", "inferior_esquerdo"]:
            regiao = REGIOES_MARCA_DAGUA[posicao]
            assert regiao["y"] >= 900  # Perto do fim
            assert regiao["y"] + regiao["h"] <= 1080
            assert regiao["x"] + regiao["w"] <= 1920

    def test_banner_inferior_cobre_largura_inteira(self):
        regiao = REGIOES_MARCA_DAGUA["banner_inferior"]
        assert regiao["x"] == 0
        assert regiao["w"] == 1920  # Largura total
        assert regiao["y"] == 980  # Perto do fim
        assert regiao["h"] == 100


class TestGerarFiltroDelogo:
    """Funcao pura que gera filtro ffmpeg `delogo=...` dado uma posicao."""

    def test_gerar_filtro_nenhuma_retorna_none(self):
        resultado = gerar_filtro_delogo("nenhuma")
        assert resultado is None

    def test_gerar_filtro_superior_direito(self):
        resultado = gerar_filtro_delogo("superior_direito")
        assert resultado is not None
        assert "delogo=" in resultado
        assert "x=1620" in resultado
        assert "y=30" in resultado
        assert "w=270" in resultado
        assert "h=110" in resultado

    def test_gerar_filtro_superior_esquerdo(self):
        resultado = gerar_filtro_delogo("superior_esquerdo")
        assert resultado is not None
        assert "delogo=" in resultado
        assert "x=30" in resultado
        assert "y=30" in resultado
        assert "w=270" in resultado
        assert "h=110" in resultado

    def test_gerar_filtro_inferior_direito(self):
        resultado = gerar_filtro_delogo("inferior_direito")
        assert resultado is not None
        assert "delogo=" in resultado
        assert "x=1620" in resultado
        assert "y=940" in resultado
        assert "w=270" in resultado
        assert "h=110" in resultado

    def test_gerar_filtro_inferior_esquerdo(self):
        resultado = gerar_filtro_delogo("inferior_esquerdo")
        assert resultado is not None
        assert "delogo=" in resultado
        assert "x=30" in resultado
        assert "y=940" in resultado
        assert "w=270" in resultado
        assert "h=110" in resultado

    def test_gerar_filtro_banner_inferior(self):
        resultado = gerar_filtro_delogo("banner_inferior")
        assert resultado is not None
        assert "delogo=" in resultado
        assert "x=0" in resultado
        assert "y=980" in resultado
        assert "w=1920" in resultado
        assert "h=100" in resultado

    def test_gerar_filtro_posicao_invalida_retorna_none(self):
        """Posicao desconhecida nao crasha, retorna None (CLAUDE.md 18.6)."""
        resultado = gerar_filtro_delogo("centro_absoluto")
        assert resultado is None

    def test_gerar_filtro_posicao_vazia_retorna_none(self):
        resultado = gerar_filtro_delogo("")
        assert resultado is None

    def test_gerar_filtro_posicao_none_retorna_none(self):
        resultado = gerar_filtro_delogo(None)
        assert resultado is None

    def test_gerar_filtro_preserva_estrutura_delogo_ffmpeg(self):
        """Formato esperado pelo ffmpeg: delogo=x=NNN:y=NNN:w=NNN:h=NNN
        (sem espacos entre os parametros)."""
        resultado = gerar_filtro_delogo("superior_direito")
        # Valida a estrutura generica do filtro ffmpeg
        assert resultado.startswith("delogo=")
        assert resultado.count(":") == 3  # Exatamente 3 dois-pontos
        # Nenhum espaco (ffmpeg e' sensivel)
        assert " " not in resultado

    def test_gerar_filtro_posicoes_diferentes_retornam_filtros_diferentes(self):
        """Posicoes diferentes devem gerar filtros diferentes."""
        filtro_super_dir = gerar_filtro_delogo("superior_direito")
        filtro_super_esq = gerar_filtro_delogo("superior_esquerdo")
        filtro_inf_dir = gerar_filtro_delogo("inferior_direito")
        filtro_inf_esq = gerar_filtro_delogo("inferior_esquerdo")
        filtro_banner = gerar_filtro_delogo("banner_inferior")

        # Todos devem ser diferentes
        filtros = {filtro_super_dir, filtro_super_esq, filtro_inf_dir, filtro_inf_esq, filtro_banner}
        assert len(filtros) == 5, "Nem todos os filtros sao unicos"

    def test_gerar_filtro_e_determinisitco(self):
        """Chamadas identicas produzem resultado identico (nenhuma
        aleatoriedade)."""
        resultado1 = gerar_filtro_delogo("superior_direito")
        resultado2 = gerar_filtro_delogo("superior_direito")
        assert resultado1 == resultado2

    def test_gerar_filtro_case_sensitive(self):
        """Posicoes sao case-sensitive (CLAUDE.md espera minusculas)."""
        resultado_minusculo = gerar_filtro_delogo("superior_direito")
        resultado_maiusculo = gerar_filtro_delogo("SUPERIOR_DIREITO")
        # Um deve funcionar, o outro nao
        assert resultado_minusculo is not None
        assert resultado_maiusculo is None


class TestEdgeCases:
    """Casos de borda e situacoes incomuns."""

    def test_gerar_filtro_com_posicao_whitespace(self):
        """Posicoes com espacos / tabs / newlines sao invalidas."""
        assert gerar_filtro_delogo(" superior_direito") is None
        assert gerar_filtro_delogo("superior_direito ") is None
        assert gerar_filtro_delogo("supe rior_direito") is None

    def test_gerar_filtro_com_posicao_similar_mas_errada(self):
        """Erros de digitacao nao devem matchear."""
        assert gerar_filtro_delogo("superior_direto") is None  # Falta 'i'
        assert gerar_filtro_delogo("super_direito") is None  # Falta 'ior'
        assert gerar_filtro_delogo("superir_direito") is None  # Troca de letras

    def test_gerar_filtro_unicode_nao_bate(self):
        """Acentuacao unicode (acento agudo vs sem acento) nao matcheia."""
        # "superior_esquerdo" vs "superior_esquerdo" (sem diferenca aqui, mas
        # em nome potencial de perfil com acentuacao poderia acontecer)
        assert gerar_filtro_delogo("superiór_direito") is None

    def test_gerar_filtro_com_tipo_errado(self):
        """Entrada de tipo nao-string retorna None sem crash."""
        assert gerar_filtro_delogo(123) is None
        assert gerar_filtro_delogo([]) is None
        assert gerar_filtro_delogo({}) is None
