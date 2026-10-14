"""Testes da Etapa 6 do pipeline (scripts/6_montar_video.py) — montagem final do vídeo:
concatenação de clipes, mux com narração (+ música com ducking opcional), geração de legendas
(SRT + ASS opcional queimado), softsub embutido no MP4 final.

Nunca chama ffmpeg real — subprocess.run é sempre mockado. Testes de funções puras
(agrupar_palavras_em_frases, formatadores de timestamp, escapador de caminho) são testados
sem subprocess. Testes de orquestração (montar_video) mockam subprocess.run para simular
sucesso/falha do ffmpeg.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "6_montar_video.py"

_spec = importlib.util.spec_from_file_location("montar_video_etapa6", CAMINHO_SCRIPT)
modulo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = modulo
_spec.loader.exec_module(modulo)


@pytest.fixture(autouse=True)
def _ffmpeg_disponivel_por_padrao(monkeypatch):
    """Por padrão, simula ffmpeg disponível. Testes que exercitam ffmpeg ausente
    sobrescrevem isso explicitamente."""
    monkeypatch.setattr(
        modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None)
    )


@pytest.fixture(autouse=True)
def _marca_dagua_global_isolada(tmp_path, monkeypatch):
    """Isola ARQUIVO_MARCA_DAGUA_GLOBAL do disco real da maquina de dev -
    sem isso, uma marca d'agua global configurada de verdade via Ajustes
    (config/marca_dagua_canal.png no repo real) vazaria pra dentro de TODO
    teste desta suite, tornando o resultado dependente da maquina onde os
    testes rodam. Autouse - todo teste, mesmo um que nunca menciona marca
    d'agua, fica isolado por padrao."""
    monkeypatch.setattr(
        modulo, "ARQUIVO_MARCA_DAGUA_GLOBAL", tmp_path / "_marca_global_isolada" / "marca_dagua_canal.png"
    )


# ---------------------------------------------------------------------------
# _ler_indice_clipes — leitura do índice de clipes gerados
# ---------------------------------------------------------------------------


def test_ler_indice_clipes_arquivo_inexistente_retorna_vazio(tmp_path):
    """Sem arquivo indice.json, retorna lista vazia."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo._ler_indice_clipes(pasta_projeto)

    assert resultado == []


def test_ler_indice_clipes_json_invalido_retorna_vazio(tmp_path):
    """JSON corrompido retorna lista vazia."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "clipes" / "indice.json").write_text(
        "{ bad json ][", encoding="utf-8"
    )

    resultado = modulo._ler_indice_clipes(pasta_projeto)

    assert resultado == []


def test_ler_indice_clipes_arquivo_valido(tmp_path):
    """Arquivo válido retorna lista de clipes."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    dados = {"clipes": [{"arquivo": "clipe_001.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(dados), encoding="utf-8"
    )

    resultado = modulo._ler_indice_clipes(pasta_projeto)

    assert len(resultado) == 1
    assert resultado[0]["arquivo"] == "clipe_001.mp4"


def test_ler_indice_clipes_sem_chave_clipes_retorna_vazio(tmp_path):
    """Se arquivo não tem chave 'clipes', retorna vazio."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    dados = {"metadata": "sem clipes"}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(dados), encoding="utf-8"
    )

    resultado = modulo._ler_indice_clipes(pasta_projeto)

    assert resultado == []


# ---------------------------------------------------------------------------
# _ler_alinhamento_narracao — leitura do alinhamento de narração
# ---------------------------------------------------------------------------


def test_ler_alinhamento_narracao_arquivo_inexistente_retorna_none(tmp_path):
    """Sem arquivo narracao_alinhamento.json, retorna None."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo._ler_alinhamento_narracao(pasta_projeto)

    assert resultado is None


def test_ler_alinhamento_narracao_json_invalido_retorna_none(tmp_path):
    """JSON corrompido retorna None."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        "{ bad json ][", encoding="utf-8"
    )

    resultado = modulo._ler_alinhamento_narracao(pasta_projeto)

    assert resultado is None


def test_ler_alinhamento_narracao_arquivo_valido(tmp_path):
    """Arquivo válido retorna dados de alinhamento."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    dados = {"duracao_s": 10.0, "palavras": []}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(dados), encoding="utf-8"
    )

    resultado = modulo._ler_alinhamento_narracao(pasta_projeto)

    assert resultado["duracao_s"] == 10.0
    assert resultado["palavras"] == []


# ---------------------------------------------------------------------------
# agrupar_palavras_em_frases — agrupamento de palavras para legendas
# ---------------------------------------------------------------------------


def test_agrupar_palavras_em_frases_lista_vazia_retorna_lista_vazia():
    """Lista vazia de palavras retorna lista vazia de frases."""
    resultado = modulo.agrupar_palavras_em_frases([])
    assert resultado == []


def test_agrupar_palavras_em_frases_palavra_unica():
    """Uma palavra isolada vira uma frase."""
    palavras = [{"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5}]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["texto"] == "Hello"
    assert resultado[0]["inicio_s"] == 0.0
    assert resultado[0]["fim_s"] == 0.5


def test_agrupar_palavras_em_frases_fecha_por_ponto():
    """Frase termina quando encontra palavra com ponto final."""
    palavras = [
        {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5},
        {"palavra": "world.", "inicio_s": 0.5, "fim_s": 1.0},
        {"palavra": "Second", "inicio_s": 1.0, "fim_s": 1.5},
        {"palavra": "sentence.", "inicio_s": 1.5, "fim_s": 2.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 2
    assert resultado[0]["texto"] == "Hello world."
    assert resultado[1]["texto"] == "Second sentence."


def test_agrupar_palavras_em_frases_fecha_por_interrogacao():
    """Frase termina com '?'."""
    palavras = [
        {"palavra": "How", "inicio_s": 0.0, "fim_s": 0.3},
        {"palavra": "are", "inicio_s": 0.3, "fim_s": 0.6},
        {"palavra": "you?", "inicio_s": 0.6, "fim_s": 1.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["texto"] == "How are you?"


def test_agrupar_palavras_em_frases_fecha_por_exclamacao():
    """Frase termina com '!'."""
    palavras = [
        {"palavra": "Watch", "inicio_s": 0.0, "fim_s": 0.5},
        {"palavra": "out!", "inicio_s": 0.5, "fim_s": 1.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["texto"] == "Watch out!"


def test_agrupar_palavras_em_frases_fecha_por_elipsis():
    """Frase termina com '…' (elipsis)."""
    palavras = [
        {"palavra": "Wait", "inicio_s": 0.0, "fim_s": 0.5},
        {"palavra": "for…", "inicio_s": 0.5, "fim_s": 1.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["texto"] == "Wait for…"


def test_agrupar_palavras_em_frases_pontuacao_com_aspas_fechando():
    """Pontuação pode ser seguida de aspas/parênteses fechando."""
    palavras = [
        {"palavra": "He", "inicio_s": 0.0, "fim_s": 0.3},
        {"palavra": "said.", "inicio_s": 0.3, "fim_s": 0.6},
        {"palavra": '"', "inicio_s": 0.6, "fim_s": 0.65},
        {"palavra": "Hello", "inicio_s": 0.65, "fim_s": 1.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    # "said." deve fechar a frase mesmo se seguido de aspas
    assert len(resultado) == 2


def test_agrupar_palavras_em_frases_fecha_por_limite_de_palavras():
    """Frase fecha quando atinge `palavras_max` mesmo sem pontuação."""
    palavras = [
        {"palavra": "One", "inicio_s": 0.0, "fim_s": 0.5},
        {"palavra": "two", "inicio_s": 0.5, "fim_s": 1.0},
        {"palavra": "three", "inicio_s": 1.0, "fim_s": 1.5},
        {"palavra": "four", "inicio_s": 1.5, "fim_s": 2.0},
        {"palavra": "five", "inicio_s": 2.0, "fim_s": 2.5},
        {"palavra": "six", "inicio_s": 2.5, "fim_s": 3.0},
        {"palavra": "seven", "inicio_s": 3.0, "fim_s": 3.5},
        {"palavra": "eight", "inicio_s": 3.5, "fim_s": 4.0},
        {"palavra": "nine", "inicio_s": 4.0, "fim_s": 4.5},
        {"palavra": "ten", "inicio_s": 4.5, "fim_s": 5.0},
        {"palavra": "eleven", "inicio_s": 5.0, "fim_s": 5.5},
        {"palavra": "twelve", "inicio_s": 5.5, "fim_s": 6.0},
        {"palavra": "thirteen", "inicio_s": 6.0, "fim_s": 6.5},
        {"palavra": "fourteen", "inicio_s": 6.5, "fim_s": 7.0},
        {"palavra": "fifteen", "inicio_s": 7.0, "fim_s": 7.5},
    ]
    # palavras_max=14, duracao_max_s bem alta para isolar so' o limite de
    # palavras (as 15 palavras aqui, a 0.5s cada, atingiriam o default de
    # 6.0s bem antes de 14 palavras, então precisa ser desativado aqui).
    resultado = modulo.agrupar_palavras_em_frases(palavras, duracao_max_s=100.0, palavras_max=14)

    # Primeira frase deve ter 14 palavras, segunda o resto
    assert len(resultado) >= 2
    assert len(resultado[0]["texto"].split()) == 14


def test_agrupar_palavras_em_frases_fecha_por_limite_de_duracao():
    """Frase fecha quando `duracao_max_s` é excedido, mesmo sem pontuação nem limite de palavras."""
    palavras = [
        {"palavra": "One", "inicio_s": 0.0, "fim_s": 2.0},
        {"palavra": "two", "inicio_s": 2.0, "fim_s": 4.0},
        {"palavra": "three", "inicio_s": 4.0, "fim_s": 6.5},  # Total desde início: 6.5s
        {"palavra": "four", "inicio_s": 6.5, "fim_s": 8.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras, duracao_max_s=6.0)

    assert len(resultado) >= 2
    # Primeira frase cobre ~0-4s (duracao=4s, < 6s) ou ~0-6.5s (duracao=6.5s, >= 6s)
    # Comportamento exato depende da lógica de fechamento


def test_agrupar_palavras_em_frases_ignora_palavras_vazias():
    """Palavras com texto vazio ou só espaço são ignoradas."""
    palavras = [
        {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5},
        {"palavra": "", "inicio_s": 0.5, "fim_s": 0.6},
        {"palavra": "  ", "inicio_s": 0.6, "fim_s": 0.7},
        {"palavra": "world.", "inicio_s": 0.7, "fim_s": 1.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["texto"] == "Hello world."


def test_agrupar_palavras_em_frases_preserva_ordem_e_timings():
    """Timestamps de início/fim refletem a primeira e última palavra da frase."""
    palavras = [
        {"palavra": "First", "inicio_s": 1.0, "fim_s": 1.5},
        {"palavra": "middle", "inicio_s": 1.5, "fim_s": 2.0},
        {"palavra": "last.", "inicio_s": 2.0, "fim_s": 2.5},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["inicio_s"] == 1.0
    assert resultado[0]["fim_s"] == 2.5


def test_agrupar_palavras_em_frases_inclui_lista_de_palavras_do_grupo():
    """Cada frase carrega a lista original de palavras do grupo (chave
    "palavras") - insumo do karaokê por palavra (gerar_dialogue_karaoke)."""
    palavras = [
        {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5},
        {"palavra": "world.", "inicio_s": 0.5, "fim_s": 1.0},
    ]
    resultado = modulo.agrupar_palavras_em_frases(palavras)

    assert len(resultado) == 1
    assert resultado[0]["palavras"] == palavras


# ---------------------------------------------------------------------------
# _expandir_palavras_multiplas (Grupo B / G2 - achado real de producao:
# alinhamento do provedor DarkPlanner (SRT "srt_palavra") pode vir em
# blocos de varias palavras por timestamp, apesar do nome do campo, o que
# fazia o karaoke destacar o bloco inteiro em vez de palavra por palavra).
# ---------------------------------------------------------------------------


def test_expandir_palavras_multiplas_lista_vazia():
    assert modulo._expandir_palavras_multiplas([]) == []


def test_expandir_palavras_multiplas_entrada_ja_de_uma_palavra_passa_intacta():
    """No-op para alinhamento ja per-palavra (faster-whisper, Etapas 2/4)."""
    palavras = [{"palavra": "hoje,", "inicio_s": 0.036, "fim_s": 0.276}]
    assert modulo._expandir_palavras_multiplas(palavras) == palavras


def test_expandir_palavras_multiplas_divide_bloco_em_sub_palavras():
    bloco = [{"palavra": "On a December morning in Manhattan, a man", "inicio_s": 0.0, "fim_s": 3.065}]
    expandido = modulo._expandir_palavras_multiplas(bloco)

    assert [item["palavra"] for item in expandido] == ["On", "a", "December", "morning", "in", "Manhattan,", "a", "man"]
    assert len(expandido) == 8


def test_expandir_palavras_multiplas_invariante_soma_bate_com_bloco_original():
    """Invariante exigida na sessao de correcoes UX: a primeira sub-palavra
    comeca exatamente onde o bloco original comecava, a ultima termina
    exatamente onde o bloco original terminava, e nao ha gap nem overlap
    entre elas (soma das duracoes == duracao do bloco)."""
    bloco = [{"palavra": "walked calmly along a sidewalk in Midtown, waited", "inicio_s": 3.181, "fim_s": 6.978}]
    expandido = modulo._expandir_palavras_multiplas(bloco)

    assert len(expandido) == 8
    assert expandido[0]["inicio_s"] == bloco[0]["inicio_s"]
    assert expandido[-1]["fim_s"] == bloco[0]["fim_s"]

    soma_duracoes = sum(item["fim_s"] - item["inicio_s"] for item in expandido)
    assert soma_duracoes == pytest.approx(bloco[0]["fim_s"] - bloco[0]["inicio_s"])

    # Sem gap nem overlap: fim de uma sub-palavra == inicio da proxima.
    for anterior, atual in zip(expandido, expandido[1:]):
        assert anterior["fim_s"] == atual["inicio_s"]


def test_expandir_palavras_multiplas_palavras_mais_longas_duram_proporcionalmente_mais():
    """Heuristica documentada: duracao interpolada por comprimento de
    caractere, nao medicao real - mas tem que pelo menos respeitar a
    proporcao (palavra 2x mais longa dura ~2x mais)."""
    bloco = [{"palavra": "a extraordinarily", "inicio_s": 0.0, "fim_s": 3.0}]
    expandido = modulo._expandir_palavras_multiplas(bloco)

    duracao_a = expandido[0]["fim_s"] - expandido[0]["inicio_s"]
    duracao_extraordinarily = expandido[1]["fim_s"] - expandido[1]["inicio_s"]
    assert duracao_extraordinarily > duracao_a


def test_expandir_palavras_multiplas_duracao_zero_mantem_entrada_intacta():
    """Bloco de duracao zero/negativa nao tem base pra interpolar - protege
    contra divisao por zero (CLAUDE.md secao 18.6, validar antes de
    processar) mantendo a entrada original em vez de quebrar."""
    bloco = [{"palavra": "two words", "inicio_s": 5.0, "fim_s": 5.0}]
    assert modulo._expandir_palavras_multiplas(bloco) == bloco


def test_agrupar_palavras_em_frases_expande_bloco_multi_palavra_do_darkplanner():
    """Integracao: agrupar_palavras_em_frases (usada tanto por gerar_srt
    quanto por gerar_ass_estilo_mrbeast) recebe um bloco no formato real do
    provedor DarkPlanner (varias palavras por timestamp) e devolve a lista
    "palavras" da frase ja expandida per-palavra - e' isso que faz o
    karaoke destacar palavra por palavra em vez do bloco inteiro."""
    bloco = [
        {"palavra": "On a December morning in Manhattan, a man", "inicio_s": 0.0, "fim_s": 3.065},
        {"palavra": "walked calmly along a sidewalk in Midtown, waited", "inicio_s": 3.181, "fim_s": 6.978},
    ]
    resultado = modulo.agrupar_palavras_em_frases(bloco)

    # 16 palavras individuais (8 + 8) - LEGENDA_PALAVRAS_MAX=14 fecha o
    # grupo antes do fim do bloco, entao viram 2 frases; o que importa aqui
    # e' que a expansao aconteceu (16 palavras individuais no total, nao 2
    # entradas de bloco).
    total_palavras = sum(len(frase["palavras"]) for frase in resultado)
    assert total_palavras == 16
    assert resultado[0]["palavras"][0]["palavra"] == "On"
    assert resultado[-1]["palavras"][-1]["palavra"] == "waited"


def test_gerar_dialogue_karaoke_bloco_multi_palavra_gera_uma_tag_k_por_palavra():
    """Regressao direta do bug real (G2): antes da expansao, um bloco de N
    palavras virava UMA UNICA tag `\\k` cobrindo o bloco inteiro - o
    destaque do karaoke "pulava" de bloco em bloco (2-9 palavras de cada
    vez) em vez de palavra por palavra."""
    bloco = [{"palavra": "On a December morning in Manhattan, a man", "inicio_s": 0.0, "fim_s": 3.065}]
    frases = modulo.agrupar_palavras_em_frases(bloco)
    texto_karaoke = modulo.gerar_dialogue_karaoke(frases[0])

    tags_k = re.findall(r"\{\\k\d+\}", texto_karaoke)
    assert len(tags_k) == 8  # uma tag por palavra, nao uma so' pro bloco


# ---------------------------------------------------------------------------
# _formatar_timestamp_srt — formato SRT (HH:MM:SS,mmm)
# ---------------------------------------------------------------------------


def test_formatar_timestamp_srt_zero():
    """Zero segundos retorna 00:00:00,000."""
    resultado = modulo._formatar_timestamp_srt(0.0)
    assert resultado == "00:00:00,000"


def test_formatar_timestamp_srt_um_segundo():
    """Um segundo retorna 00:00:01,000."""
    resultado = modulo._formatar_timestamp_srt(1.0)
    assert resultado == "00:00:01,000"


def test_formatar_timestamp_srt_um_minuto():
    """60 segundos retorna 00:01:00,000."""
    resultado = modulo._formatar_timestamp_srt(60.0)
    assert resultado == "00:01:00,000"


def test_formatar_timestamp_srt_uma_hora():
    """3600 segundos retorna 01:00:00,000."""
    resultado = modulo._formatar_timestamp_srt(3600.0)
    assert resultado == "01:00:00,000"


def test_formatar_timestamp_srt_valor_conhecido():
    """3725.4 segundos (1h 2m 5s 400ms) retorna 01:02:05,400."""
    resultado = modulo._formatar_timestamp_srt(3725.4)
    assert resultado == "01:02:05,400"


def test_formatar_timestamp_srt_com_milisegundos_fracao():
    """2.567 segundos retorna 00:00:02,567."""
    resultado = modulo._formatar_timestamp_srt(2.567)
    assert resultado == "00:00:02,567"


def test_formatar_timestamp_srt_negativo_clamped_a_zero():
    """Valores negativos são clamped a 0."""
    resultado = modulo._formatar_timestamp_srt(-5.0)
    assert resultado == "00:00:00,000"


# ---------------------------------------------------------------------------
# _formatar_timestamp_ass — formato ASS (H:MM:SS.cc, centésimos, hora sem zero à esquerda)
# ---------------------------------------------------------------------------


def test_formatar_timestamp_ass_zero():
    """Zero segundos retorna 0:00:00.00."""
    resultado = modulo._formatar_timestamp_ass(0.0)
    assert resultado == "0:00:00.00"


def test_formatar_timestamp_ass_um_segundo():
    """Um segundo retorna 0:00:01.00."""
    resultado = modulo._formatar_timestamp_ass(1.0)
    assert resultado == "0:00:01.00"


def test_formatar_timestamp_ass_um_minuto():
    """60 segundos retorna 0:01:00.00."""
    resultado = modulo._formatar_timestamp_ass(60.0)
    assert resultado == "0:01:00.00"


def test_formatar_timestamp_ass_uma_hora():
    """3600 segundos retorna 1:00:00.00."""
    resultado = modulo._formatar_timestamp_ass(3600.0)
    assert resultado == "1:00:00.00"


def test_formatar_timestamp_ass_valor_conhecido():
    """3725.4 segundos retorna 1:02:05.40."""
    resultado = modulo._formatar_timestamp_ass(3725.4)
    assert resultado == "1:02:05.40"


def test_formatar_timestamp_ass_com_centesimos_fracao():
    """2.567 segundos retorna 0:00:02.57."""
    resultado = modulo._formatar_timestamp_ass(2.567)
    assert resultado == "0:00:02.57"


def test_formatar_timestamp_ass_hora_sem_zero_a_esquerda():
    """Hora não é zero-padded à esquerda (10+ horas aparece sem '0' a mais)."""
    resultado = modulo._formatar_timestamp_ass(36000.0)  # 10 horas
    assert resultado.startswith("10:")


def test_formatar_timestamp_ass_negativo_clamped_a_zero():
    """Valores negativos são clamped a 0."""
    resultado = modulo._formatar_timestamp_ass(-5.0)
    assert resultado == "0:00:00.00"


# ---------------------------------------------------------------------------
# gerar_srt — geração de arquivo SRT
# ---------------------------------------------------------------------------


def test_gerar_srt_lista_vazia_cria_arquivo(tmp_path):
    """Alinhamento vazio ou sem palavras cria arquivo SRT vazio (só cabeçalho)."""
    alinhamento = {"palavras": []}
    caminho_saida = tmp_path / "legendas.srt"

    modulo.gerar_srt(alinhamento, caminho_saida)

    assert caminho_saida.exists()
    conteudo = caminho_saida.read_text(encoding="utf-8")
    # SRT vazio
    assert conteudo.strip() == ""


def test_gerar_srt_uma_frase(tmp_path):
    """Uma frase simples gera um bloco SRT numerado."""
    alinhamento = {
        "palavras": [
            {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5},
            {"palavra": "world.", "inicio_s": 0.5, "fim_s": 1.0},
        ]
    }
    caminho_saida = tmp_path / "test.srt"

    modulo.gerar_srt(alinhamento, caminho_saida)

    assert caminho_saida.exists()
    conteudo = caminho_saida.read_text(encoding="utf-8")
    assert "Hello world." in conteudo
    assert "-->" in conteudo


def test_gerar_srt_multiplas_frases(tmp_path):
    """Múltiplas frases geram múltiplos blocos SRT numerados."""
    alinhamento = {
        "palavras": [
            {"palavra": "First", "inicio_s": 0.0, "fim_s": 0.5},
            {"palavra": "sentence.", "inicio_s": 0.5, "fim_s": 1.0},
            {"palavra": "Second", "inicio_s": 1.0, "fim_s": 1.5},
            {"palavra": "sentence.", "inicio_s": 1.5, "fim_s": 2.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.srt"

    modulo.gerar_srt(alinhamento, caminho_saida)

    assert caminho_saida.exists()
    conteudo = caminho_saida.read_text(encoding="utf-8")
    linhas = conteudo.strip().split("\n")

    # Verifica numeração
    assert "1" in linhas[0]
    assert "2" in conteudo  # Existe um bloco número 2

    # Verifica separador -->
    assert "-->" in conteudo


def test_gerar_srt_cria_diretorios_se_nao_existem(tmp_path):
    """Se o diretório de saída não existe, é criado."""
    alinhamento = {"palavras": []}
    caminho_saida = tmp_path / "subdir" / "outro" / "legendas.srt"

    modulo.gerar_srt(alinhamento, caminho_saida)

    assert caminho_saida.parent.exists()
    assert caminho_saida.exists()


def test_gerar_srt_timestamps_formatados_corretamente(tmp_path):
    """Timestamps no arquivo SRT estão no formato HH:MM:SS,mmm."""
    alinhamento = {
        "palavras": [
            {"palavra": "Test", "inicio_s": 3725.4, "fim_s": 3726.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.srt"

    modulo.gerar_srt(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    # Deve conter timestamps em formato SRT
    assert "01:02:05" in conteudo
    assert "-->" in conteudo


# ---------------------------------------------------------------------------
# _fonte_disponivel — verificação de fonte instalada no Windows
# ---------------------------------------------------------------------------


def test_fonte_disponivel_nao_windows_retorna_false(monkeypatch):
    """Em sistemas não-Windows, sempre retorna False."""
    monkeypatch.setattr("os.name", "posix")

    resultado = modulo._fonte_disponivel("Arial")

    assert resultado is False


def test_fonte_disponivel_windows_fonte_existe(monkeypatch, tmp_path):
    """No Windows, encontra uma fonte existente na pasta Fonts."""
    monkeypatch.setattr("os.name", "nt")

    # Mock a pasta Fonts
    fonts_dir = tmp_path / "Fonts"
    fonts_dir.mkdir()
    (fonts_dir / "Poppins.ttf").touch()

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("WINDIR", str(tmp_path))

    resultado = modulo._fonte_disponivel("Poppins")

    assert resultado is True


def test_fonte_disponivel_windows_fonte_nao_existe(monkeypatch, tmp_path):
    """No Windows, retorna False quando fonte não encontrada."""
    monkeypatch.setattr("os.name", "nt")

    # Pasta Fonts vazia ou inexistente
    monkeypatch.setenv("WINDIR", str(tmp_path))

    resultado = modulo._fonte_disponivel("NonexistentFont")

    assert resultado is False


def test_escolher_fonte_legenda_retorna_padrao_se_disponivel(monkeypatch, tmp_path):
    """Se a família Poppins está instalada, retorna o Fontname "Poppins Bold"
    (estilo MrBeast usa negrito - LEGENDA_FONTE_BASE só verifica se a família
    existe, LEGENDA_FONTE_PADRAO é o que de fato vai pro ASS)."""
    monkeypatch.setattr("os.name", "nt")
    fonts_dir = tmp_path / "Fonts"
    fonts_dir.mkdir()
    (fonts_dir / "Poppins.ttf").touch()
    monkeypatch.setenv("WINDIR", str(tmp_path))

    resultado = modulo.escolher_fonte_legenda()

    assert resultado == "Poppins Bold"


def test_escolher_fonte_legenda_retorna_fallback_se_padrao_nao_existe(monkeypatch, tmp_path):
    """Se Poppins não existe, retorna Arial Black (fallback). Mocka também
    Path.home() (não só WINDIR) - sem isso o teste checa a pasta de fontes
    real do usuário rodando a suíte, o que é não-hermético (CLAUDE.md seção
    8: nunca depender de estado real da máquina em teste)."""
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("WINDIR", str(tmp_path))

    resultado = modulo.escolher_fonte_legenda()

    assert resultado == "Arial Black"


# ---------------------------------------------------------------------------
# gerar_ass_estilo_mrbeast — geração de legenda estilo "MrBeast" (branco,
# contorno preto grosso, karaokê por palavra)
# ---------------------------------------------------------------------------


def test_gerar_ass_estilo_mrbeast_cria_arquivo(tmp_path):
    """Gera um arquivo ASS válido com formato correto."""
    alinhamento = {
        "palavras": [
            {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5},
            {"palavra": "world.", "inicio_s": 0.5, "fim_s": 1.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    assert caminho_saida.exists()


def test_gerar_ass_estilo_mrbeast_usa_borderstyle_1(tmp_path):
    """A linha Style usa BorderStyle=1 (só contorno + sombra, sem caixa de
    fundo - o antigo estilo "pill" usava BorderStyle=3, ilegível sobre vídeo
    escuro). Formato ASS V4+ é posicional (CSV), não key=value, então o
    valor é lido pela posição da coluna "BorderStyle" declarada no Format
    da seção [V4+ Styles]."""
    alinhamento = {
        "palavras": [
            {"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    linha_format = next(l for l in conteudo.splitlines() if l.startswith("Format:") and "BorderStyle" in l)
    linha_style = next(l for l in conteudo.splitlines() if l.startswith("Style:"))
    colunas_format = [c.strip() for c in linha_format[len("Format:"):].split(",")]
    valores_style = [v.strip() for v in linha_style[len("Style:"):].split(",")]
    indice_borderstyle = colunas_format.index("BorderStyle")
    assert valores_style[indice_borderstyle] == "1"


def test_gerar_ass_estilo_mrbeast_fontsize_64(tmp_path):
    """Fontsize é 64pt (preferência confirmada pelo usuário, era 48pt)."""
    alinhamento = {"palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}]}
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    linha_format = next(l for l in conteudo.splitlines() if l.startswith("Format:") and "Fontsize" in l)
    linha_style = next(l for l in conteudo.splitlines() if l.startswith("Style:"))
    colunas_format = [c.strip() for c in linha_format[len("Format:"):].split(",")]
    valores_style = [v.strip() for v in linha_style[len("Style:"):].split(",")]
    indice_fontsize = colunas_format.index("Fontsize")
    assert valores_style[indice_fontsize] == "64"


def test_gerar_ass_estilo_mrbeast_cores_branco_e_amarelo(tmp_path):
    """PrimaryColour é branco (&H00FFFFFF) e SecondaryColour (cor do
    destaque de karaokê) é amarelo (&H0000FFFF)."""
    alinhamento = {"palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}]}
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    linha_format = next(l for l in conteudo.splitlines() if l.startswith("Format:") and "PrimaryColour" in l)
    linha_style = next(l for l in conteudo.splitlines() if l.startswith("Style:"))
    colunas_format = [c.strip() for c in linha_format[len("Format:"):].split(",")]
    valores_style = [v.strip() for v in linha_style[len("Style:"):].split(",")]
    assert valores_style[colunas_format.index("PrimaryColour")] == "&H00FFFFFF"
    assert valores_style[colunas_format.index("SecondaryColour")] == "&H0000FFFF"


def test_gerar_ass_estilo_mrbeast_contém_secao_script_info(tmp_path):
    """Arquivo ASS contém seção [Script Info]."""
    alinhamento = {"palavras": []}
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    assert "[Script Info]" in conteudo


def test_gerar_ass_estilo_mrbeast_contém_secao_styles(tmp_path):
    """Arquivo ASS contém seção [V4+ Styles]."""
    alinhamento = {"palavras": []}
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    assert "[V4+ Styles]" in conteudo


def test_gerar_ass_estilo_mrbeast_contém_secao_events(tmp_path):
    """Arquivo ASS contém seção [Events]."""
    alinhamento = {"palavras": []}
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    assert "[Events]" in conteudo


def test_gerar_ass_estilo_mrbeast_com_fonte_customizada(tmp_path):
    """Se `fonte` é passada, usa essa fonte no arquivo."""
    alinhamento = {
        "palavras": [
            {"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida, fonte="CustomFont")

    conteudo = caminho_saida.read_text(encoding="utf-8")
    # A fonte deve aparecer na seção de estilos
    assert "CustomFont" in conteudo


def test_gerar_ass_estilo_mrbeast_sem_fonte_usa_fallback(monkeypatch, tmp_path):
    """Se `fonte` é None, usa a fonte retornada por `escolher_fonte_legenda()`."""
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("WINDIR", str(tmp_path))

    alinhamento = {
        "palavras": [
            {"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida, fonte=None)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    # Deve conter a fonte fallback
    assert "Arial Black" in conteudo or "Poppins" in conteudo


def test_gerar_ass_estilo_mrbeast_diálogos_contêm_timestamps(tmp_path):
    """Linhas de diálogo contêm timestamps no formato ASS."""
    alinhamento = {
        "palavras": [
            {"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0},
        ]
    }
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    # Deve conter "Dialogue:" com timestamps
    assert "Dialogue:" in conteudo


def test_gerar_ass_estilo_mrbeast_dialogos_contêm_tags_karaoke(tmp_path):
    """Linhas de diálogo contêm tags `\\k` de karaokê por palavra."""
    alinhamento = {
        "palavras": [
            {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.3},
            {"palavra": "there.", "inicio_s": 0.3, "fim_s": 0.7},
        ]
    }
    caminho_saida = tmp_path / "legendas.ass"

    modulo.gerar_ass_estilo_mrbeast(alinhamento, caminho_saida)

    conteudo = caminho_saida.read_text(encoding="utf-8")
    assert "\\k" in conteudo


# ---------------------------------------------------------------------------
# gerar_dialogue_karaoke — texto de diálogo ASS com karaokê por palavra
# ---------------------------------------------------------------------------


def test_gerar_dialogue_karaoke_uma_palavra():
    """Uma palavra vira um bloco {\\kNN}texto."""
    frase = {
        "texto": "Hello",
        "inicio_s": 0.0,
        "fim_s": 0.5,
        "palavras": [{"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.5}],
    }

    resultado = modulo.gerar_dialogue_karaoke(frase)

    assert resultado == "{\\k50}Hello"


def test_gerar_dialogue_karaoke_duracao_em_centesimos():
    """Duração de cada palavra é convertida pra centésimos de segundo
    (0.3s -> 30, arredondado ao inteiro mais próximo)."""
    frase = {
        "texto": "Hello there",
        "inicio_s": 0.0,
        "fim_s": 0.7,
        "palavras": [
            {"palavra": "Hello", "inicio_s": 0.0, "fim_s": 0.3},
            {"palavra": "there", "inicio_s": 0.3, "fim_s": 0.7},
        ],
    }

    resultado = modulo.gerar_dialogue_karaoke(frase)

    assert resultado == "{\\k30}Hello {\\k40}there"


def test_gerar_dialogue_karaoke_escapa_chaves():
    """Chaves `{`/`}` no texto da palavra são escapadas (viram parênteses)
    pra nunca serem confundidas com uma tag de override ASS de verdade."""
    frase = {
        "texto": "{weird}",
        "inicio_s": 0.0,
        "fim_s": 0.5,
        "palavras": [{"palavra": "{weird}", "inicio_s": 0.0, "fim_s": 0.5}],
    }

    resultado = modulo.gerar_dialogue_karaoke(frase)

    assert "{weird}" not in resultado
    assert "(weird)" in resultado


def test_gerar_dialogue_karaoke_sem_palavras_cai_para_texto_plano():
    """Se a frase não tem lista de palavras (alinhamento sem timestamp por
    palavra - defensivo, não deveria acontecer dado o contrato de
    narracao_alinhamento.json), cai para o texto puro sem tags de karaokê."""
    frase = {"texto": "Hello world.", "inicio_s": 0.0, "fim_s": 1.0}

    resultado = modulo.gerar_dialogue_karaoke(frase)

    assert resultado == "Hello world."
    assert "\\k" not in resultado


def test_gerar_dialogue_karaoke_lista_palavras_vazia_cai_para_texto_plano():
    """Lista de palavras vazia (não None, mas []) também cai pro fallback."""
    frase = {"texto": "Hello world.", "inicio_s": 0.0, "fim_s": 1.0, "palavras": []}

    resultado = modulo.gerar_dialogue_karaoke(frase)

    assert resultado == "Hello world."
    assert "\\k" not in resultado


# ---------------------------------------------------------------------------
# ler_configuracao_video — leitura de configuração
# ---------------------------------------------------------------------------


def test_ler_configuracao_video_arquivo_inexistente_retorna_padrao(tmp_path):
    """Arquivo ausente retorna configuração padrão (sem música, sem legenda queimada)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo.ler_configuracao_video(pasta_projeto)

    assert resultado == {
        "legendas_queimadas": False,
        "com_musica_fundo": False,
        "grayscale": False,
        "marca_dagua_projeto": "canal",
    }


def test_ler_configuracao_video_json_invalido_retorna_padrao(tmp_path):
    """JSON corrompido retorna configuração padrão."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        "{ bad json ][", encoding="utf-8"
    )

    resultado = modulo.ler_configuracao_video(pasta_projeto)

    assert resultado == {
        "legendas_queimadas": False,
        "com_musica_fundo": False,
        "grayscale": False,
        "marca_dagua_projeto": "canal",
    }


def test_ler_configuracao_video_arquivo_valido(tmp_path):
    """Arquivo válido retorna configuração lida."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    config = {"legendas_queimadas": True, "com_musica_fundo": False}
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    resultado = modulo.ler_configuracao_video(pasta_projeto)

    assert resultado == {**config, "grayscale": False, "marca_dagua_projeto": "canal"}


def test_ler_configuracao_video_parcial_usa_padrao_para_faltantes(tmp_path):
    """Se apenas um campo está no arquivo, o outro usa padrão."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    config = {"legendas_queimadas": True}  # falta com_musica_fundo
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    resultado = modulo.ler_configuracao_video(pasta_projeto)

    assert resultado["legendas_queimadas"] is True
    assert resultado["com_musica_fundo"] is False  # padrão


# ---------------------------------------------------------------------------
# descobrir_musica_upload — localização de arquivo de música
# ---------------------------------------------------------------------------


def test_descobrir_musica_upload_nenhum_arquivo_retorna_none(tmp_path):
    """Sem arquivo de música, retorna None."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()

    resultado = modulo.descobrir_musica_upload(pasta_projeto)

    assert resultado is None


def test_descobrir_musica_upload_encontra_mp3(tmp_path):
    """Encontra arquivo musica_fundo.mp3."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    caminho_musica = pasta_projeto / "entrada" / "musica_fundo.mp3"
    caminho_musica.write_bytes(b"fake audio")

    resultado = modulo.descobrir_musica_upload(pasta_projeto)

    assert resultado == caminho_musica


def test_descobrir_musica_upload_encontra_wav(tmp_path):
    """Encontra arquivo musica_fundo.wav."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    caminho_musica = pasta_projeto / "entrada" / "musica_fundo.wav"
    caminho_musica.write_bytes(b"fake audio")

    resultado = modulo.descobrir_musica_upload(pasta_projeto)

    assert resultado == caminho_musica


def test_descobrir_musica_upload_encontra_m4a(tmp_path):
    """Encontra arquivo musica_fundo.m4a."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    caminho_musica = pasta_projeto / "entrada" / "musica_fundo.m4a"
    caminho_musica.write_bytes(b"fake audio")

    resultado = modulo.descobrir_musica_upload(pasta_projeto)

    assert resultado == caminho_musica


def test_descobrir_musica_upload_prioriza_mp3(tmp_path):
    """Se múltiplos arquivos existem, retorna o primeiro encontrado."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    # Cria múltiplos arquivos
    (pasta_projeto / "entrada" / "musica_fundo.mp3").write_bytes(b"mp3")
    (pasta_projeto / "entrada" / "musica_fundo.wav").write_bytes(b"wav")

    resultado = modulo.descobrir_musica_upload(pasta_projeto)

    # O loop itera sobre EXTENSOES_MUSICA_VALIDAS na ordem: .mp3, .wav, .m4a
    assert resultado is not None


# ---------------------------------------------------------------------------
# descobrir_playlist_musicas — playlist de música (pasta) com fallback legado
# ---------------------------------------------------------------------------


def test_descobrir_playlist_musicas_pasta_inexistente_cai_para_legado(tmp_path):
    """Sem a pasta entrada/musica_fundo/, cai para o arquivo único legado."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    caminho_legado = pasta_projeto / "entrada" / "musica_fundo.mp3"
    caminho_legado.write_bytes(b"fake")

    resultado = modulo.descobrir_playlist_musicas(pasta_projeto)

    assert resultado == [caminho_legado]


def test_descobrir_playlist_musicas_nenhuma_musica_retorna_vazio(tmp_path):
    """Sem pasta nem arquivo legado, retorna lista vazia."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()

    resultado = modulo.descobrir_playlist_musicas(pasta_projeto)

    assert resultado == []


def test_descobrir_playlist_musicas_pasta_vazia_cai_para_legado(tmp_path):
    """Pasta entrada/musica_fundo/ existente mas vazia (sem faixa válida)
    cai para o arquivo único legado."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada" / "musica_fundo").mkdir(parents=True)
    caminho_legado = pasta_projeto / "entrada" / "musica_fundo.mp3"
    caminho_legado.write_bytes(b"fake")

    resultado = modulo.descobrir_playlist_musicas(pasta_projeto)

    assert resultado == [caminho_legado]


def test_descobrir_playlist_musicas_ordena_alfabeticamente(tmp_path):
    """Faixas da pasta são retornadas em ordem alfabética de nome de
    arquivo (a ordem alfabética define a ordem da playlist)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    (pasta_musicas / "m3.mp3").write_bytes(b"3")
    (pasta_musicas / "m1.mp3").write_bytes(b"1")
    (pasta_musicas / "m2.mp3").write_bytes(b"2")

    resultado = modulo.descobrir_playlist_musicas(pasta_projeto)

    assert [p.name for p in resultado] == ["m1.mp3", "m2.mp3", "m3.mp3"]


def test_descobrir_playlist_musicas_ignora_extensoes_invalidas(tmp_path):
    """Arquivos com extensão fora de EXTENSOES_MUSICA_VALIDAS são ignorados
    (ex.: .txt de metadados, .DS_Store, etc.)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    (pasta_musicas / "musica.mp3").write_bytes(b"audio")
    (pasta_musicas / "leiame.txt").write_text("nao e' musica")

    resultado = modulo.descobrir_playlist_musicas(pasta_projeto)

    assert resultado == [pasta_musicas / "musica.mp3"]


def test_descobrir_playlist_musicas_multiplos_formatos(tmp_path):
    """Playlist pode misturar mp3/wav/m4a."""
    pasta_projeto = tmp_path / "projeto"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    (pasta_musicas / "a.mp3").write_bytes(b"1")
    (pasta_musicas / "b.wav").write_bytes(b"2")
    (pasta_musicas / "c.m4a").write_bytes(b"3")

    resultado = modulo.descobrir_playlist_musicas(pasta_projeto)

    assert len(resultado) == 3


# ---------------------------------------------------------------------------
# construir_comando_concat_musicas / construir_comando_loop_musica /
# preparar_faixa_musica_playlist — playlist com loop sequencial
# ---------------------------------------------------------------------------


def test_construir_comando_concat_musicas_usa_demuxer_concat(tmp_path):
    """Comando contém `-f concat -safe 0`, igual ao concat de clipes."""
    caminho_lista = tmp_path / "musica_concat_list.txt"
    caminho_saida = tmp_path / "musica_concat.mp3"

    comando = modulo.construir_comando_concat_musicas(caminho_lista, caminho_saida)

    assert "-f" in comando
    assert "concat" in comando
    assert "-safe" in comando
    assert str(caminho_lista) in comando
    assert str(caminho_saida) in comando


def test_construir_comando_loop_musica_usa_stream_loop_infinito(tmp_path):
    """Comando contém `-stream_loop -1` (loop sequencial indefinido)."""
    faixa_concat = tmp_path / "musica_concat.mp3"
    caminho_saida = tmp_path / "musica_final.mp3"

    comando = modulo.construir_comando_loop_musica(faixa_concat, 1122.5, caminho_saida)

    assert "-stream_loop" in comando
    assert "-1" in comando


def test_construir_comando_loop_musica_corta_na_duracao_alvo(tmp_path):
    """Comando contém `-t <duracao_alvo>` pra cortar o loop na duração
    exata pedida."""
    faixa_concat = tmp_path / "musica_concat.mp3"
    caminho_saida = tmp_path / "musica_final.mp3"

    comando = modulo.construir_comando_loop_musica(faixa_concat, 1122.5, caminho_saida)

    assert "-t" in comando
    indice_t = comando.index("-t")
    assert comando[indice_t + 1] == "1122.500"


def test_preparar_faixa_musica_playlist_sucesso_roda_concat_e_loop(tmp_path, monkeypatch):
    """Em sucesso, roda concat seguido de loop e retorna o caminho final."""
    pasta_projeto = tmp_path / "projeto"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    m1 = pasta_musicas / "m1.mp3"
    m2 = pasta_musicas / "m2.mp3"
    m1.write_bytes(b"1")
    m2.write_bytes(b"2")

    comandos_run = []

    def _run_mock(cmd, *args, **kwargs):
        comandos_run.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"fake audio")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    caminho, tipo_erro, mensagem = modulo.preparar_faixa_musica_playlist([m1, m2], 120.0, pasta_projeto)

    assert caminho is not None
    assert tipo_erro is None
    assert mensagem is None
    assert len(comandos_run) == 2
    assert "-stream_loop" in comandos_run[1]


def test_preparar_faixa_musica_playlist_falha_no_concat_nao_roda_loop(tmp_path, monkeypatch):
    """Se o concat falha, não chega a rodar o comando de loop."""
    pasta_projeto = tmp_path / "projeto"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    m1 = pasta_musicas / "m1.mp3"
    m1.write_bytes(b"1")

    comandos_run = []

    def _run_mock_falha(cmd, *args, **kwargs):
        comandos_run.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "ffmpeg concat de musica falhou"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_falha)

    caminho, tipo_erro, mensagem = modulo.preparar_faixa_musica_playlist([m1], 60.0, pasta_projeto)

    assert caminho is None
    assert tipo_erro is not None
    assert mensagem is not None
    assert len(comandos_run) == 1


# ---------------------------------------------------------------------------
# _escrever_lista_concat — escrita do arquivo de lista para concat
# ---------------------------------------------------------------------------


def test_escrever_lista_concat_cria_arquivo(tmp_path):
    """Cria arquivo de lista com paths dos clipes."""
    indice_clipes = [
        {"arquivo": "clipe_001.mp4"},
        {"arquivo": "clipe_002.mp4"},
    ]
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    caminho_lista = tmp_path / "concat_list.txt"

    modulo._escrever_lista_concat(indice_clipes, pasta_clipes, caminho_lista)

    assert caminho_lista.exists()


def test_escrever_lista_concat_formato_correto(tmp_path):
    """Arquivo contém linhas no formato 'file <path>'."""
    indice_clipes = [
        {"arquivo": "clipe_001.mp4"},
    ]
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    caminho_lista = tmp_path / "concat_list.txt"

    modulo._escrever_lista_concat(indice_clipes, pasta_clipes, caminho_lista)

    conteudo = caminho_lista.read_text(encoding="utf-8")
    assert "file " in conteudo
    assert "clipe_001.mp4" in conteudo


def test_escrever_lista_concat_cria_diretorios(tmp_path):
    """Se o diretório de saída não existe, é criado."""
    indice_clipes = [{"arquivo": "clipe.mp4"}]
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    caminho_lista = tmp_path / "subdir" / "concat_list.txt"

    modulo._escrever_lista_concat(indice_clipes, pasta_clipes, caminho_lista)

    assert caminho_lista.parent.exists()
    assert caminho_lista.exists()


# ---------------------------------------------------------------------------
# construir_comando_concat — construção de comando ffmpeg para concat
# ---------------------------------------------------------------------------


def test_construir_comando_concat_usa_demuxer_concat(tmp_path):
    """Comando contém `-f concat -safe 0`."""
    caminho_lista = tmp_path / "concat.txt"
    caminho_saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_concat(caminho_lista, caminho_saida)

    assert "-f" in comando
    assert "concat" in comando
    assert "-safe" in comando
    assert "0" in comando


def test_construir_comando_concat_usa_copy(tmp_path):
    """Comando contém `-c copy` (sem reencoding)."""
    caminho_lista = tmp_path / "concat.txt"
    caminho_saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_concat(caminho_lista, caminho_saida)

    assert "-c" in comando
    assert "copy" in comando


def test_construir_comando_concat_input_e_output(tmp_path):
    """Comando inclui input (lista) e output (vídeo)."""
    caminho_lista = tmp_path / "concat.txt"
    caminho_saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_concat(caminho_lista, caminho_saida)

    assert str(caminho_lista) in comando
    assert str(caminho_saida) in comando


# ---------------------------------------------------------------------------
# _migrar_slots_clipes — Feature B (reorganizacao manual, duracao por slot)
# ---------------------------------------------------------------------------


def test_migrar_slots_clipes_fallback_usa_duracao_s():
    """Indice sem duracao_slot_s (todo projeto anterior a esta sessao) cai
    no fallback duracao_slot_s = duracao_s."""
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0}, {"clipe_id": "c1", "duracao_s": 6.0}]

    migrados = modulo._migrar_slots_clipes(clipes)

    assert migrados[0]["duracao_slot_s"] == 8.0
    assert migrados[1]["duracao_slot_s"] == 6.0


def test_migrar_slots_clipes_preserva_duracao_slot_existente():
    """Se duracao_slot_s ja existe (gravado por /reordenar_clipes), o
    fallback NAO sobrescreve - o valor persistido e' o que manda."""
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}]

    migrados = modulo._migrar_slots_clipes(clipes)

    assert migrados[0]["duracao_slot_s"] == 5.0
    assert migrados[0]["duracao_s"] == 8.0


def test_migrar_slots_clipes_inicio_fim_sao_cumulativos():
    clipes = [{"clipe_id": "c0", "duracao_s": 5.0}, {"clipe_id": "c1", "duracao_s": 3.0}, {"clipe_id": "c2", "duracao_s": 4.0}]

    migrados = modulo._migrar_slots_clipes(clipes)

    assert migrados[0]["inicio_slot_s"] == 0.0
    assert migrados[0]["fim_slot_s"] == 5.0
    assert migrados[1]["inicio_slot_s"] == 5.0
    assert migrados[1]["fim_slot_s"] == 8.0
    assert migrados[2]["inicio_slot_s"] == 8.0
    assert migrados[2]["fim_slot_s"] == 12.0


def test_migrar_slots_clipes_nao_muta_lista_original():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0}]

    modulo._migrar_slots_clipes(clipes)

    assert "duracao_slot_s" not in clipes[0]


def test_migrar_slots_clipes_lista_vazia():
    assert modulo._migrar_slots_clipes([]) == []


def test_migrar_slots_clipes_duracao_s_ausente_cai_em_zero():
    clipes = [{"clipe_id": "c0"}]

    migrados = modulo._migrar_slots_clipes(clipes)

    assert migrados[0]["duracao_slot_s"] == 0.0


# ---------------------------------------------------------------------------
# _precisa_de_trim
# ---------------------------------------------------------------------------


def test_precisa_de_trim_false_quando_slot_igual_duracao():
    clipes = modulo._migrar_slots_clipes([{"clipe_id": "c0", "duracao_s": 8.0}])
    assert modulo._precisa_de_trim(clipes) is False


def test_precisa_de_trim_true_quando_slot_diferente():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}]
    assert modulo._precisa_de_trim(clipes) is True


def test_precisa_de_trim_tolera_diferenca_minuscula_de_arredondamento():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 8.001}]
    assert modulo._precisa_de_trim(clipes) is False


# ---------------------------------------------------------------------------
# construir_filtro_complexo_trim / construir_comando_concat_filtro
# ---------------------------------------------------------------------------


def test_construir_filtro_complexo_trim_contem_trim_por_clipe():
    clipes = modulo._migrar_slots_clipes([{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}])

    filtro = modulo.construir_filtro_complexo_trim(clipes)

    assert "[0:v]trim=duration=5.000" in filtro
    assert "setpts=PTS-STARTPTS[v0]" in filtro


def test_construir_filtro_complexo_trim_contem_concat_final():
    clipes = modulo._migrar_slots_clipes(
        [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}, {"clipe_id": "c1", "duracao_s": 6.0, "duracao_slot_s": 6.0}]
    )

    filtro = modulo.construir_filtro_complexo_trim(clipes)

    assert "[v0][v1]concat=n=2:v=1:a=0[outv]" in filtro


def test_construir_comando_concat_filtro_um_i_por_clipe(tmp_path):
    clipes = modulo._migrar_slots_clipes(
        [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0, "duracao_slot_s": 5.0}]
    )
    pasta_clipes = tmp_path / "clipes"

    comando = modulo.construir_comando_concat_filtro(clipes, pasta_clipes, tmp_path / "saida.mp4")

    assert comando.count("-i") == 1
    assert "-filter_complex" in comando
    assert "-filter_complex_script" not in comando  # indisponivel no build de ffmpeg deste produto (achado empirico)
    assert str((pasta_clipes / "clipe_0000.mp4").resolve()) in comando


# ---------------------------------------------------------------------------
# concat_clipes — caminho rapido (sem trim) vs caminho com trim (Feature B)
# ---------------------------------------------------------------------------


def test_concat_clipes_usa_caminho_rapido_quando_nao_precisa_trim(tmp_path, monkeypatch):
    """Indice sem duracao_slot_s (fallback = duracao_s em todo clipe) usa o
    concat demuxer -c copy ORIGINAL, sem reencoding - comportamento default
    preservado (CLAUDE.md)."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "clipe_0000.mp4").write_bytes(b"fake")

    comandos = []

    def _run_mock(cmd, *args, **kwargs):
        comandos.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    caminho, tipo_erro, mensagem = modulo.concat_clipes(
        pasta_projeto, [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0}]
    )

    assert caminho is not None
    assert len(comandos) == 1
    assert "-f" in comandos[0] and "concat" in comandos[0]
    assert "-c" in comandos[0] and "copy" in comandos[0]
    assert "-filter_complex" not in comandos[0]
    assert not (pasta_projeto / "temp" / "concat_filter_lote_000.mp4").exists()


def test_concat_clipes_usa_caminho_com_trim_quando_precisa(tmp_path, monkeypatch):
    """Clipe com duracao_slot_s != duracao_s (pos-reordenacao manual) forca
    o caminho com trim (filter_complex), nao o -c copy."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "clipe_0000.mp4").write_bytes(b"fake")

    comandos = []

    def _run_mock(cmd, *args, **kwargs):
        comandos.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    caminho, tipo_erro, mensagem = modulo.concat_clipes(
        pasta_projeto,
        [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0, "duracao_slot_s": 5.0}],
    )

    assert caminho is not None
    assert any("-filter_complex" in cmd for cmd in comandos)
    assert not any("-filter_complex_script" in cmd for cmd in comandos)


def test_concat_clipes_com_trim_e_multiplos_lotes_junta_no_final(tmp_path, monkeypatch):
    """Mais clipes que TAMANHO_LOTE_FILTRO_TRIM (com trim necessario) gera
    varios lotes reencodados e um concat final (-c copy) juntando eles."""
    monkeypatch.setattr(modulo, "TAMANHO_LOTE_FILTRO_TRIM", 2)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    for i in range(5):
        (pasta_projeto / "clipes" / f"clipe_{i:04d}.mp4").write_bytes(b"fake")

    comandos = []

    def _run_mock(cmd, *args, **kwargs):
        comandos.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    indice_clipes = [
        {"clipe_id": f"c{i}", "arquivo": f"clipe_{i:04d}.mp4", "duracao_s": 8.0, "duracao_slot_s": 5.0} for i in range(5)
    ]

    caminho, tipo_erro, mensagem = modulo.concat_clipes(pasta_projeto, indice_clipes)

    assert caminho is not None
    # 5 clipes / lote de 2 = 3 lotes (2+2+1) + 1 comando de concat final dos lotes.
    comandos_filtro = [cmd for cmd in comandos if "-filter_complex" in cmd]
    comandos_concat_final = [cmd for cmd in comandos if "-f" in cmd and "concat" in cmd]
    assert len(comandos_filtro) == 3
    assert len(comandos_concat_final) == 1


def test_concat_clipes_com_trim_falha_retorna_erro(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "clipe_0000.mp4").write_bytes(b"fake")

    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    def _run_falha(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "erro simulado"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_falha)

    caminho, tipo_erro, mensagem = modulo.concat_clipes(
        pasta_projeto,
        [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0, "duracao_slot_s": 5.0}],
    )

    assert caminho is None
    assert tipo_erro is not None


# ---------------------------------------------------------------------------
# Grayscale (sessao de correcoes UX) — hook na arquitetura filter_complex
# batelado ja existente (Feature B), nao um caminho novo.
# ---------------------------------------------------------------------------


def test_construir_filtro_complexo_trim_com_grayscale_adiciona_hue():
    clipes = modulo._migrar_slots_clipes([{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 8.0}])

    filtro_normal = modulo.construir_filtro_complexo_trim(clipes)
    filtro_grayscale = modulo.construir_filtro_complexo_trim(clipes, grayscale=True)

    assert "hue=s=0" not in filtro_normal
    assert "hue=s=0" in filtro_grayscale
    assert "[v0]concat" in filtro_grayscale.split(";")[-1] or "concat=n=1" in filtro_grayscale


def test_ler_configuracao_video_aceita_grayscale(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"grayscale": True}), encoding="utf-8"
    )

    config = modulo.ler_configuracao_video(pasta_projeto)

    assert config["grayscale"] is True


def test_ler_configuracao_video_grayscale_ausente_e_falso(tmp_path):
    """Projeto criado antes do grayscale (sem o campo no JSON, ou sem o
    arquivo) cai no default False - retrocompatibilidade total."""
    pasta_projeto = tmp_path / "projeto_antigo"
    pasta_projeto.mkdir()

    assert modulo.ler_configuracao_video(pasta_projeto)["grayscale"] is False


def test_concat_clipes_grayscale_forca_filter_complex_mesmo_sem_trim(tmp_path, monkeypatch):
    """Sem grayscale, indice sem duracao_slot_s usaria o caminho -c copy
    (ver test_concat_clipes_usa_caminho_rapido_quando_nao_precisa_trim).
    Com grayscale=True, mesmo sem nenhum trim necessario, forca o caminho
    filter_complex (unico jeito de aplicar hue=s=0 a todos os clipes)."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "clipe_0000.mp4").write_bytes(b"fake")

    comandos = []

    def _run_mock(cmd, *args, **kwargs):
        comandos.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    caminho, tipo_erro, mensagem = modulo.concat_clipes(
        pasta_projeto,
        [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0}],
        grayscale=True,
    )

    assert caminho is not None
    assert any("-filter_complex" in cmd for cmd in comandos)
    assert any("hue=s=0" in "".join(cmd) for cmd in comandos)


def test_concat_clipes_grayscale_false_preserva_caminho_rapido(tmp_path, monkeypatch):
    """grayscale=False (default) preserva exatamente o caminho -c copy
    original - nao regride o Grupo C (filter_complex batelado ja existente)
    quando o filtro nao foi pedido."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "clipe_0000.mp4").write_bytes(b"fake")

    comandos = []

    def _run_mock(cmd, *args, **kwargs):
        comandos.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    caminho, tipo_erro, mensagem = modulo.concat_clipes(
        pasta_projeto,
        [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0}],
        grayscale=False,
    )

    assert caminho is not None
    assert len(comandos) == 1
    assert "-filter_complex" not in comandos[0]


# ---------------------------------------------------------------------------
# construir_filtro_ducking — construção do filtro de ducking
# ---------------------------------------------------------------------------


def test_construir_filtro_ducking_contém_sidechaincompress():
    """Filtro contém 'sidechaincompress'."""
    filtro = modulo.construir_filtro_ducking()

    assert "sidechaincompress" in filtro


def test_construir_filtro_ducking_contém_parametros_esperados():
    """Filtro contém threshold, ratio, attack, release."""
    filtro = modulo.construir_filtro_ducking()

    assert "threshold=" in filtro
    assert "ratio=" in filtro
    assert "attack=" in filtro
    assert "release=" in filtro


def test_construir_filtro_ducking_valores_corretos():
    """Filtro usa os valores corretos de constantes."""
    filtro = modulo.construir_filtro_ducking()

    assert f"threshold={modulo.DUCKING_THRESHOLD}" in filtro
    assert f"ratio={modulo.DUCKING_RATIO}" in filtro
    assert f"attack={modulo.DUCKING_ATTACK_MS}" in filtro
    assert f"release={modulo.DUCKING_RELEASE_MS}" in filtro


def test_construir_filtro_ducking_volume_base_aplicado():
    """Filtro aplica volume base à música."""
    filtro = modulo.construir_filtro_ducking()

    assert f"volume={modulo.MUSICA_VOLUME_BASE}" in filtro


# ---------------------------------------------------------------------------
# construir_comando_mux — construção de comando para mux audio
# ---------------------------------------------------------------------------


def test_construir_comando_mux_sem_musica_dois_inputs(tmp_path):
    """Sem música, comando tem 2 inputs (vídeo + narração)."""
    video = tmp_path / "video.mp4"
    narracao = tmp_path / "narracao.mp3"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_mux(video, narracao, saida)

    # Conta quantas vezes `-i` aparece
    count_i = comando.count("-i")
    assert count_i == 2


def test_construir_comando_mux_com_musica_tres_inputs(tmp_path):
    """Com música, comando tem 3 inputs (vídeo + narração + música)."""
    video = tmp_path / "video.mp4"
    narracao = tmp_path / "narracao.mp3"
    musica = tmp_path / "musica.mp3"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_mux(video, narracao, saida, musica)

    # Conta quantas vezes `-i` aparece
    count_i = comando.count("-i")
    assert count_i == 3


def test_construir_comando_mux_com_musica_usa_filter_complex(tmp_path):
    """Com música, comando contém `-filter_complex` com ducking."""
    video = tmp_path / "video.mp4"
    narracao = tmp_path / "narracao.mp3"
    musica = tmp_path / "musica.mp3"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_mux(video, narracao, saida, musica)

    assert "-filter_complex" in comando


def test_construir_comando_mux_sem_musica_usa_map_simples(tmp_path):
    """Sem música, usa `-map 0:v -map 1:a`."""
    video = tmp_path / "video.mp4"
    narracao = tmp_path / "narracao.mp3"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_mux(video, narracao, saida)

    assert "-map" in comando
    assert "0:v" in comando
    assert "1:a" in comando


def test_construir_comando_mux_saida_presente(tmp_path):
    """Comando inclui caminho de saída."""
    video = tmp_path / "video.mp4"
    narracao = tmp_path / "narracao.mp3"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_mux(video, narracao, saida)

    assert str(saida) in comando


# ---------------------------------------------------------------------------
# _escapar_caminho_filtro_ffmpeg — escapador de caminho para filtros
# ---------------------------------------------------------------------------


def test_escapar_caminho_filtro_ffmpeg_converte_backslash():
    """Backslashes Windows (separador de path) são convertidos para forward
    slash. O único backslash que sobra é o escape do ':' da letra de
    unidade (ex. "C\\:") - coberto separadamente pelo teste abaixo."""
    caminho = Path("C:\\Users\\test\\video.mp4")

    resultado = modulo._escapar_caminho_filtro_ffmpeg(caminho)

    assert "\\Users" not in resultado
    assert "\\test" not in resultado
    assert "/" in resultado


def test_escapar_caminho_filtro_ffmpeg_escapa_dois_pontos():
    """Dois-pontos (letra de unidade) são escapados com backslash."""
    caminho = Path("C:\\Users\\test\\video.mp4")

    resultado = modulo._escapar_caminho_filtro_ffmpeg(caminho)

    # C: deve virar C\:
    assert "C\\:" in resultado


def test_escapar_caminho_filtro_ffmpeg_posix_retorna_simples(tmp_path):
    """Em caminhos POSIX, apenas backslashes são convertidos (não há nenhum)."""
    caminho = Path("/home/user/video.mp4")

    resultado = modulo._escapar_caminho_filtro_ffmpeg(caminho)

    # Deve retornar o caminho quase idêntico (o Path pode ajustar format)
    assert "home" in resultado


# ---------------------------------------------------------------------------
# construir_comando_queimar_legendas — comando para queimar ASS
# ---------------------------------------------------------------------------


def test_construir_comando_queimar_legendas_contém_input_video(tmp_path):
    """Comando contém input do vídeo."""
    video = tmp_path / "video.mp4"
    ass = tmp_path / "legendas.ass"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_queimar_legendas(video, ass, saida)

    assert str(video) in comando


def test_construir_comando_queimar_legendas_contém_filtro_ass(tmp_path):
    """Comando contém filtro `ass=` com caminho escapado."""
    video = tmp_path / "video.mp4"
    ass = tmp_path / "legendas.ass"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_queimar_legendas(video, ass, saida)

    comando_str = " ".join(comando)
    assert "ass=" in comando_str


def test_construir_comando_queimar_legendas_copia_audio(tmp_path):
    """Comando copia áudio sem reencoding."""
    video = tmp_path / "video.mp4"
    ass = tmp_path / "legendas.ass"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_queimar_legendas(video, ass, saida)

    assert "-c:a" in comando
    assert "copy" in comando


def test_construir_comando_queimar_legendas_encoder_padrao(tmp_path):
    """Sem especificar encoder, usa libx264."""
    video = tmp_path / "video.mp4"
    ass = tmp_path / "legendas.ass"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_queimar_legendas(
        video, ass, saida, encoder="libx264"
    )

    assert "libx264" in comando


def test_construir_comando_queimar_legendas_encoder_nvenc(tmp_path):
    """Com h264_nvenc, usa esse encoder."""
    video = tmp_path / "video.mp4"
    ass = tmp_path / "legendas.ass"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_queimar_legendas(
        video, ass, saida, encoder="h264_nvenc"
    )

    assert "h264_nvenc" in comando


# ---------------------------------------------------------------------------
# _params_encoder e _detectar_encoder_gpu — encoder de vídeo
# ---------------------------------------------------------------------------


def test_params_encoder_libx264_padrao():
    """Com encoder libx264, retorna parâmetros CPU-padrão."""
    params = modulo._params_encoder("libx264")

    assert "-c:v" in params
    assert "libx264" in params
    assert "-preset" in params
    assert modulo.PRESET_X264 in params


def test_params_encoder_h264_nvenc():
    """Com encoder h264_nvenc, retorna parâmetros NVENC."""
    params = modulo._params_encoder("h264_nvenc")

    assert "-c:v" in params
    assert "h264_nvenc" in params
    assert "-preset" in params
    assert "-tune" in params
    assert "-rc" in params


def test_detectar_encoder_gpu_retorna_string(monkeypatch):
    """Sempre retorna uma string de encoder válida."""
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.stdout = "libx264 libx265"
        resultado.returncode = 0
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    encoder = modulo._detectar_encoder_gpu()

    assert isinstance(encoder, str)
    assert len(encoder) > 0


def test_detectar_encoder_gpu_nunca_levanta_excecao(monkeypatch):
    """Mesmo com erro, não levanta exceção."""
    def _run_raises(*args, **kwargs):
        raise OSError("simulado")

    monkeypatch.setattr(subprocess, "run", _run_raises)

    # Não deve levantar
    encoder = modulo._detectar_encoder_gpu()
    assert encoder == modulo.ENCODER_PADRAO


# ---------------------------------------------------------------------------
# _obter_duracao_video_via_ffprobe — duração REAL do vídeo final (correção
# de sessão de refinamento: não confundir com tempo_total_s, que é tempo de
# PROCESSAMENTO da montagem, não a duração do vídeo produzido).
# ---------------------------------------------------------------------------


def test_obter_duracao_video_via_ffprobe_sucesso(tmp_path, monkeypatch):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stdout = "1512.345\n"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    duracao = modulo._obter_duracao_video_via_ffprobe(tmp_path / "video_final.mp4")

    assert duracao == 1512.345


def test_obter_duracao_video_via_ffprobe_returncode_diferente_de_zero_devolve_none(monkeypatch):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stdout = ""
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    assert modulo._obter_duracao_video_via_ffprobe(Path("qualquer.mp4")) is None


def test_obter_duracao_video_via_ffprobe_excecao_de_subprocess_devolve_none(monkeypatch):
    def _run_raises(*args, **kwargs):
        raise OSError("ffprobe ausente")

    monkeypatch.setattr(subprocess, "run", _run_raises)

    assert modulo._obter_duracao_video_via_ffprobe(Path("qualquer.mp4")) is None


def test_obter_duracao_video_via_ffprobe_stdout_nao_numerico_devolve_none(monkeypatch):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stdout = "N/A"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    assert modulo._obter_duracao_video_via_ffprobe(Path("qualquer.mp4")) is None


def test_montar_video_metadata_inclui_duracao_video_s_distinta_de_tempo_total_s(tmp_path, monkeypatch):
    """Achado real (sessao de refinamento): a tela de conclusao mostrava
    "5:02" rotulado "Duracao" quando o video tinha ~25min de fato, porque
    lia `tempo_total_s` (tempo de PROCESSAMENTO) em vez da duracao real do
    video. `duracao_video_s` (via ffprobe no video_final.mp4 apos a
    montagem) precisa existir e ser um numero DIFERENTE de tempo_total_s."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps(indice), encoding="utf-8")
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(json.dumps(alinhamento), encoding="utf-8")

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        if "ffprobe" in cmd:
            resultado.stdout = "1500.0"  # 25min - bem diferente do tempo de processamento
            return resultado
        for arg in reversed(cmd):
            if isinstance(arg, str) and arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake video")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    resultado = modulo.montar_video(pasta_projeto)
    assert resultado["sucesso"] is True

    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["duracao_video_s"] == 1500.0
    assert metadata["duracao_video_s"] != metadata["tempo_total_s"]


# ---------------------------------------------------------------------------
# construir_comando_softsub — comando para softsub SRT embutido
# ---------------------------------------------------------------------------


def test_construir_comando_softsub_dois_inputs(tmp_path):
    """Comando tem 2 inputs (vídeo + SRT)."""
    video = tmp_path / "video.mp4"
    srt = tmp_path / "legendas.srt"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_softsub(video, srt, saida)

    count_i = comando.count("-i")
    assert count_i == 2


def test_construir_comando_softsub_mov_text_codec(tmp_path):
    """Comando usa `-c:s mov_text` para codec de legenda."""
    video = tmp_path / "video.mp4"
    srt = tmp_path / "legendas.srt"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_softsub(video, srt, saida)

    assert "-c:s" in comando
    assert "mov_text" in comando


def test_construir_comando_softsub_copia_video_audio(tmp_path):
    """Comando copia vídeo e áudio sem reencoding."""
    video = tmp_path / "video.mp4"
    srt = tmp_path / "legendas.srt"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_softsub(video, srt, saida)

    assert "-c:v" in comando
    assert "-c:a" in comando


def test_construir_comando_softsub_map_0_e_1(tmp_path):
    """Comando usa `-map 0 -map 1` para incluir todos streams."""
    video = tmp_path / "video.mp4"
    srt = tmp_path / "legendas.srt"
    saida = tmp_path / "output.mp4"

    comando = modulo.construir_comando_softsub(video, srt, saida)

    assert "-map" in comando


# ---------------------------------------------------------------------------
# classificar_erro_ffmpeg — categorização de erros
# ---------------------------------------------------------------------------


def test_classificar_erro_ffmpeg_disco_cheio():
    """Detecta erro de disco cheio."""
    stderr = "ffmpeg error: no space left on device"

    tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)

    assert tipo == "disco_cheio"
    assert "libere espaco" in mensagem.lower()


def test_classificar_erro_ffmpeg_disco_cheio_variants():
    """Detecta variantes de 'disco cheio'."""
    for texto in ["no space left on device", "disk full", "enospc"]:
        stderr = f"ffmpeg error: {texto}"
        tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)
        assert tipo == "disco_cheio", f"Não detectou: {texto}"


def test_classificar_erro_ffmpeg_fonte_corrompida():
    """Detecta arquivo corrompido."""
    stderr = "ffmpeg error: invalid data found when processing input"

    tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)

    assert tipo == "fonte_corrompida"
    assert "corrompido" in mensagem.lower()


def test_classificar_erro_ffmpeg_moov_atom():
    """Detecta 'moov atom not found' (vídeo corrompido)."""
    stderr = "moov atom not found"

    tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)

    assert tipo == "fonte_corrompida"


def test_classificar_erro_ffmpeg_could_not_open_file():
    """Detecta 'could not open file'."""
    stderr = "could not open file for reading"

    tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)

    assert tipo == "fonte_corrompida"


def test_classificar_erro_ffmpeg_generico():
    """Erro desconhecido vira 'ffmpeg_falhou'."""
    stderr = "some random ffmpeg error message"

    tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)

    assert tipo == "ffmpeg_falhou"
    assert "ffmpeg falhou" in mensagem.lower()


def test_classificar_erro_ffmpeg_stderr_vazio():
    """stderr vazio retorna 'ffmpeg_falhou' genérico."""
    stderr = ""

    tipo, mensagem = modulo.classificar_erro_ffmpeg(stderr)

    assert tipo == "ffmpeg_falhou"


# ---------------------------------------------------------------------------
# _validar_pre_condicoes — validação de pré-condições
# ---------------------------------------------------------------------------


def test_validar_pre_condicoes_ffmpeg_ausente(monkeypatch):
    """Sem ffmpeg no PATH, retorna erro."""
    monkeypatch.setattr(
        modulo.robustez,
        "validar_pre_condicoes_pipeline",
        lambda: (False, "ffmpeg não encontrado"),
    )

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(
        Path("/tmp"), [], None
    )

    assert ok is False
    assert tipo_erro == "ffmpeg_ausente"


def test_validar_pre_condicoes_clipes_vazio(tmp_path):
    """Lista vazia de clipes retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(
        pasta_projeto, [], None
    )

    assert ok is False
    assert tipo_erro == "clipes_ausentes"


def test_validar_pre_condicoes_alinhamento_none(tmp_path):
    """Alinhamento None retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(
        pasta_projeto, [{"arquivo": "clipe.mp4"}], None
    )

    assert ok is False
    assert tipo_erro == "narracao_ausente"


def test_validar_pre_condicoes_narracao_arquivo_ausente(tmp_path):
    """Arquivo narracao.mp3 ausente retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    alinhamento = {"palavras": []}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(
        pasta_projeto, [{"arquivo": "clipe.mp4"}], alinhamento
    )

    assert ok is False
    assert tipo_erro == "narracao_ausente"


def test_validar_pre_condicoes_sucesso(tmp_path):
    """Com clipes, alinhamento, e arquivo de narração, valida."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake audio")

    clipes = [{"arquivo": "clipe.mp4"}]
    alinhamento = {"palavras": []}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(
        pasta_projeto, clipes, alinhamento
    )

    assert ok is True
    assert mensagem is None
    assert tipo_erro is None


# ---------------------------------------------------------------------------
# montar_video — orquestração principal
# ---------------------------------------------------------------------------


def test_montar_video_pre_condicoes_falham(monkeypatch, tmp_path):
    """Se pré-condições falham, retorna erro sem prosseguir."""
    monkeypatch.setattr(
        modulo.robustez,
        "validar_pre_condicoes_pipeline",
        lambda: (False, "ffmpeg não encontrado"),
    )
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "ffmpeg_ausente"


def test_montar_video_clipes_ausentes(tmp_path):
    """Sem clipes, retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "clipes_ausentes"


def test_montar_video_cria_estrutura_minima(tmp_path, monkeypatch):
    """Caso feliz mínimo: cria SRT e montagem_metadata.json."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    # Mínimo de dados
    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [
            {"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0},
        ],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    # Mock ffmpeg para criação de arquivos
    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        # Cria o arquivo esperado (video_final.mp4)
        if "-i" in cmd:  # qualquer etapa que rode ffmpeg
            # Tenta encontrar o output (último argumento que termina com .mp4)
            for arg in reversed(cmd):
                if arg.endswith(".mp4"):
                    Path(arg).parent.mkdir(parents=True, exist_ok=True)
                    Path(arg).write_bytes(b"fake video")
                    break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "saida" / "legendas.srt").exists()
    assert (pasta_projeto / "saida" / "montagem_metadata.json").exists()
    assert (pasta_projeto / "saida" / "video_final.mp4").exists()


def test_montar_video_metadata_contém_campos_requeridos(tmp_path, monkeypatch):
    """Metadata JSON contém campos obrigatórios."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake video")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True

    metadata_path = pasta_projeto / "saida" / "montagem_metadata.json"
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert "total_clipes" in metadata
    assert "legendas_queimadas" in metadata
    assert "com_musica_fundo" in metadata
    assert "tempo_total_s" in metadata
    assert "data_geracao" in metadata


def test_montar_video_com_musica(tmp_path, monkeypatch):
    """Se configuração pede música e arquivo existe, é usado."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "entrada").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    (pasta_projeto / "entrada" / "musica_fundo.mp3").write_bytes(b"fake music")

    config = {"legendas_queimadas": False, "com_musica_fundo": True}
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    comandos_run = []

    def _run_captura(cmd, *args, **kwargs):
        comandos_run.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith((".mp4", ".mp3")):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake audio/video")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_captura)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True

    # Verifica que a playlist foi preparada (concat + loop) antes do mux, e
    # que o mux usou a faixa preparada (musica_playlist_final.mp3) - o
    # arquivo legado original (musica_fundo.mp3) não vai direto pro mux
    # mais, ele é o input do concat que gera a faixa final.
    algum_tem_faixa_preparada = any(
        "musica_playlist_final" in " ".join(cmd) for cmd in comandos_run
    )
    assert algum_tem_faixa_preparada, "Nenhum comando usou a faixa de música preparada"
    algum_e_loop = any("-stream_loop" in cmd for cmd in comandos_run)
    assert algum_e_loop, "Nenhum comando fez o loop sequencial da música"


def test_montar_video_com_playlist_de_musicas(tmp_path, monkeypatch):
    """Com uma pasta entrada/musica_fundo/ com múltiplas faixas, a playlist
    inteira é usada (concat + loop), não só a primeira faixa."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    (pasta_musicas / "m1.mp3").write_bytes(b"1")
    (pasta_musicas / "m2.mp3").write_bytes(b"2")
    (pasta_musicas / "m3.mp3").write_bytes(b"3")

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")

    config = {"legendas_queimadas": False, "com_musica_fundo": True}
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    alinhamento = {
        "duracao_s": 1200.0,  # 20 minutos - bem mais longo que a playlist
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    comandos_run = []

    def _run_captura(cmd, *args, **kwargs):
        comandos_run.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith((".mp4", ".mp3")):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake audio/video")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_captura)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True

    comando_concat_musica = next(
        (cmd for cmd in comandos_run if "musica_concat_list" in " ".join(cmd)), None
    )
    assert comando_concat_musica is not None, "Playlist não foi concatenada"

    comando_loop = next((cmd for cmd in comandos_run if "-stream_loop" in cmd), None)
    assert comando_loop is not None, "Loop sequencial não foi aplicado"
    indice_t = comando_loop.index("-t")
    # Duracao alvo = duracao_s (1200.0) + FOLGA_MUSICA_S (5.0)
    assert comando_loop[indice_t + 1] == f"{1200.0 + modulo.FOLGA_MUSICA_S:.3f}"


def test_montar_video_com_legendas_queimadas(tmp_path, monkeypatch):
    """Se configuração pede legendas queimadas, são geradas e aplicadas."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "entrada").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")

    config = {"legendas_queimadas": True, "com_musica_fundo": False}
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake video")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    # Verifica que ASS foi gerado
    assert (pasta_projeto / "saida" / "legendas.ass").exists()

    metadata_path = pasta_projeto / "saida" / "montagem_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["legendas_queimadas"] is True


def test_montar_video_emite_progresso(tmp_path, monkeypatch, capsys):
    """Durante execução, emite @PROGRESSO no stdout."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        for arg in reversed(cmd):
            if arg.endswith(".mp4"):
                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake video")
                break
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    modulo.montar_video(pasta_projeto)

    saida_capturada = capsys.readouterr().out
    assert "@PROGRESSO" in saida_capturada

    linhas_progresso = [
        l for l in saida_capturada.split("\n") if "@PROGRESSO" in l
    ]
    assert len(linhas_progresso) > 0

    # Última linha deve indicar sucesso
    payload_final = json.loads(linhas_progresso[-1][len("@PROGRESSO ") :])
    assert payload_final["sucesso"] is True
    assert payload_final["pct"] == 100.0


def test_montar_video_falha_parcial_concat(tmp_path, monkeypatch, capsys):
    """Se concat falha, não continua para etapas seguintes."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice), encoding="utf-8"
    )
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(alinhamento), encoding="utf-8"
    )

    def _run_mock_falha(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "ffmpeg concat failed"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_falha)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is False
    saida = capsys.readouterr().out
    linhas = [l for l in saida.split("\n") if "@PROGRESSO" in l]
    payload_final = json.loads(linhas[-1][len("@PROGRESSO ") :])
    assert payload_final["sucesso"] is False


# ---------------------------------------------------------------------------
# _ler_tipo_projeto — marcador entrada/tipo_projeto.txt (CLAUDE.md secao 3,
# "Vídeos pré-gerados")
# ---------------------------------------------------------------------------


def test_ler_tipo_projeto_ausente_retorna_pipeline_completa(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    assert modulo._ler_tipo_projeto(pasta_projeto) == "pipeline_completa"


def test_ler_tipo_projeto_videos_pre_gerados(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "tipo_projeto.txt").write_text("videos_pre_gerados", encoding="utf-8")

    assert modulo._ler_tipo_projeto(pasta_projeto) == "videos_pre_gerados"


def test_ler_tipo_projeto_valor_invalido_cai_no_default(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "tipo_projeto.txt").write_text("lixo_qualquer", encoding="utf-8")

    assert modulo._ler_tipo_projeto(pasta_projeto) == "pipeline_completa"


# ---------------------------------------------------------------------------
# montar_video — tipo de projeto "videos_pre_gerados" (CLAUDE.md secao 3):
# so' concatena, SEM narracao/mux_audio - os clipes ja vem com audio
# embutido. Confirma que o dispatcher nunca exige narracao.mp3/
# narracao_alinhamento.json para este tipo de projeto (diferenca central em
# relacao a pipeline_completa).
# ---------------------------------------------------------------------------


def _criar_projeto_videos_pre_gerados(tmp_path, com_srt=False, legendas_queimadas=False):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "tipo_projeto.txt").write_text("videos_pre_gerados", encoding="utf-8")
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"legendas_queimadas": legendas_queimadas, "com_musica_fundo": False}), encoding="utf-8"
    )
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps({"clipes": [{"clipe_id": "clipe_0000", "arquivo": "clipe_0000.mp4", "duracao_s": 5.0}]}),
        encoding="utf-8",
    )
    if com_srt:
        (pasta_projeto / "entrada" / "legenda_importada.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nOla\n", encoding="utf-8"
        )
    return pasta_projeto


def _mock_ffmpeg_cria_saida(cmd, *args, **kwargs):
    resultado = MagicMock()
    resultado.returncode = 0
    resultado.stderr = ""
    for arg in reversed(cmd):
        if arg.endswith(".mp4"):
            Path(arg).parent.mkdir(parents=True, exist_ok=True)
            Path(arg).write_bytes(b"fake video")
            break
    return resultado


def test_montar_video_videos_pre_gerados_nunca_exige_narracao(tmp_path, monkeypatch):
    """Diferenca central deste tipo de projeto: sem narracao.mp3 nem
    narracao_alinhamento.json no disco, e ainda assim monta com sucesso -
    o dispatcher nao roteia para a validacao de pre-condicoes da pipeline
    completa (que rejeitaria com tipo_erro=narracao_ausente)."""
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path)
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "saida" / "video_final.mp4").exists()
    assert not (pasta_projeto / "narracao.mp3").exists()


def test_montar_video_videos_pre_gerados_sem_srt_nao_gera_legendas_srt(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path, com_srt=False)
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert not (pasta_projeto / "saida" / "legendas.srt").exists()


def test_montar_video_videos_pre_gerados_srt_sem_flag_copia_mas_nao_queima(tmp_path, monkeypatch):
    """SRT importado presente mas legendas_queimadas=False: vira softsub
    (saida/legendas.srt) mas NAO reencoda o video queimando nada -
    queimar_srt_importado nunca e' chamada."""
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path, com_srt=True, legendas_queimadas=False)
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)
    chamou_queimar = []
    monkeypatch.setattr(
        modulo, "queimar_srt_importado", lambda *a, **k: chamou_queimar.append(1) or (None, None, None)
    )

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "saida" / "legendas.srt").exists()
    assert chamou_queimar == []


def test_montar_video_videos_pre_gerados_com_legenda_queimada(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path, com_srt=True, legendas_queimadas=True)
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "saida" / "video_final.mp4").exists()
    assert (pasta_projeto / "saida" / "legendas.srt").exists()

    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["legendas_queimadas"] is True


def test_montar_video_videos_pre_gerados_clipes_ausentes(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "tipo_projeto.txt").write_text("videos_pre_gerados", encoding="utf-8")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "clipes_ausentes"


def test_montar_video_videos_pre_gerados_metadata_marca_tipo_projeto(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path)
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)

    modulo.montar_video(pasta_projeto)

    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["tipo_projeto"] == "videos_pre_gerados"


def test_montar_video_videos_pre_gerados_concat_falha_nao_prossegue(tmp_path, monkeypatch):
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path)

    def _run_mock_falha(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "ffmpeg concat failed"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_falha)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is False
    assert not (pasta_projeto / "saida" / "video_final.mp4").exists()


def test_montar_video_marcador_ausente_continua_pipeline_completa(tmp_path, monkeypatch):
    """Regressao: projeto SEM entrada/tipo_projeto.txt (todo projeto criado
    antes desta feature) continua caindo no caminho pipeline_completa, que
    exige narracao - confirma que o dispatcher nao muda o comportamento
    historico quando o marcador nao existe."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps(indice), encoding="utf-8")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "narracao_ausente"


# ---------------------------------------------------------------------------
# Marca d'agua do canal (sessao "Marca d'agua do canal aplicada ao video
# final") - ler_configuracao_video, resolver_marca_dagua, construcao do
# comando de overlay, e integracao ponta-a-ponta via montar_video (pipeline
# completa E videos_pre_gerados).
# ---------------------------------------------------------------------------


def test_ler_configuracao_video_default_marca_dagua_projeto_e_canal(tmp_path):
    """Projeto SEM entrada/configuracao_video.json - todos os defaults,
    incluindo marca_dagua_projeto="canal" (retrocompatibilidade: comporta-se
    como "usar a marca do canal", que so' tem efeito de verdade se uma
    marca global ja estiver configurada)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    config = modulo.ler_configuracao_video(pasta_projeto)

    assert config["marca_dagua_projeto"] == "canal"


def test_ler_configuracao_video_projeto_antigo_sem_campo_cai_no_default(tmp_path):
    """configuracao_video.json de um projeto criado ANTES desta feature (sem
    a chave marca_dagua_projeto) nunca quebra - cai no default "canal"."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"legendas_queimadas": True, "com_musica_fundo": False}), encoding="utf-8"
    )

    config = modulo.ler_configuracao_video(pasta_projeto)

    assert config["marca_dagua_projeto"] == "canal"
    assert config["legendas_queimadas"] is True


def test_ler_configuracao_video_valor_invalido_de_marca_dagua_cai_no_default(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"marca_dagua_projeto": "valor_bagunçado"}), encoding="utf-8"
    )

    config = modulo.ler_configuracao_video(pasta_projeto)

    assert config["marca_dagua_projeto"] == "canal"


def test_resolver_marca_dagua_modo_nenhuma_retorna_none_sem_aviso(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    caminho, aviso = modulo.resolver_marca_dagua(pasta_projeto, {"marca_dagua_projeto": "nenhuma"})

    assert caminho is None
    assert aviso is None


def test_resolver_marca_dagua_modo_canal_sem_marca_global_configurada_e_silencioso(tmp_path):
    """"canal" e' o default - se o usuario nunca configurou marca global em
    Ajustes, isso NAO e' um erro, so' significa "nenhuma marca aplicada"."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    caminho, aviso = modulo.resolver_marca_dagua(pasta_projeto, {"marca_dagua_projeto": "canal"})

    assert caminho is None
    assert aviso is None


def test_resolver_marca_dagua_modo_canal_usa_marca_global_configurada(tmp_path):
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(b"fake png")
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    caminho, aviso = modulo.resolver_marca_dagua(pasta_projeto, {"marca_dagua_projeto": "canal"})

    assert caminho == modulo.ARQUIVO_MARCA_DAGUA_GLOBAL
    assert aviso is None


def test_resolver_marca_dagua_modo_outra_ausente_do_disco_gera_aviso_sem_quebrar(tmp_path):
    """PNG proprio do projeto configurado ("outra") mas nunca chegou a ser
    salvo em disco (ou foi removido) - montagem segue sem marca, com aviso
    registrado, nunca uma excecao."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    caminho, aviso = modulo.resolver_marca_dagua(pasta_projeto, {"marca_dagua_projeto": "outra"})

    assert caminho is None
    assert aviso is not None
    assert "não foi encontrada" in aviso or "nao foi encontrada" in aviso


def test_resolver_marca_dagua_modo_outra_tem_precedencia_sobre_global(tmp_path):
    """Sobrescrita por projeto ("outra") vence mesmo com uma marca GLOBAL
    tambem configurada - a global e' ignorada nesse caso."""
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(b"marca global")

    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    marca_propria = pasta_projeto / "entrada" / "marca_dagua_canal.png"
    marca_propria.write_bytes(b"marca propria do projeto")

    caminho, aviso = modulo.resolver_marca_dagua(pasta_projeto, {"marca_dagua_projeto": "outra"})

    assert caminho == marca_propria
    assert caminho != modulo.ARQUIVO_MARCA_DAGUA_GLOBAL
    assert aviso is None


def test_construir_comando_marca_dagua_inclui_input_do_png(tmp_path):
    video = tmp_path / "video.mp4"
    marca = tmp_path / "marca.png"
    saida = tmp_path / "saida.mp4"

    comando = modulo.construir_comando_marca_dagua(video, marca, saida, largura_video=1920)

    assert str(marca) in comando
    assert "-filter_complex" in comando


def test_construir_comando_marca_dagua_filtro_contem_overlay_e_opacidade(tmp_path):
    video = tmp_path / "video.mp4"
    marca = tmp_path / "marca.png"
    saida = tmp_path / "saida.mp4"

    comando = modulo.construir_comando_marca_dagua(video, marca, saida, largura_video=1920)
    indice_filtro = comando.index("-filter_complex") + 1
    filtro = comando[indice_filtro]

    assert "overlay=" in filtro
    assert f"aa={modulo.marca_dagua_canal.OPACIDADE}" in filtro
    assert f"scale={modulo.marca_dagua_canal.calcular_largura_marca_px(1920)}:-1" in filtro


def test_construir_comando_marca_dagua_sem_legenda_nao_referencia_ass(tmp_path):
    video = tmp_path / "video.mp4"
    marca = tmp_path / "marca.png"
    saida = tmp_path / "saida.mp4"

    comando = modulo.construir_comando_marca_dagua(video, marca, saida, legenda_path=None, largura_video=1920)
    filtro = comando[comando.index("-filter_complex") + 1]

    assert "ass=" not in filtro
    assert "subtitles=" not in filtro


def test_construir_comando_marca_dagua_com_legenda_ass_funde_os_dois_filtros(tmp_path):
    video = tmp_path / "video.mp4"
    marca = tmp_path / "marca.png"
    ass = tmp_path / "legendas.ass"
    saida = tmp_path / "saida.mp4"

    comando = modulo.construir_comando_marca_dagua(
        video, marca, saida, legenda_path=ass, modo_legenda="ass", largura_video=1920
    )
    filtro = comando[comando.index("-filter_complex") + 1]

    assert "ass=" in filtro
    assert "overlay=" in filtro


def test_construir_comando_marca_dagua_com_srt_usa_filtro_subtitles(tmp_path):
    video = tmp_path / "video.mp4"
    marca = tmp_path / "marca.png"
    srt = tmp_path / "legendas.srt"
    saida = tmp_path / "saida.mp4"

    comando = modulo.construir_comando_marca_dagua(
        video, marca, saida, legenda_path=srt, modo_legenda="srt", largura_video=1920
    )
    filtro = comando[comando.index("-filter_complex") + 1]

    assert "subtitles=" in filtro
    assert "ass=" not in filtro


def _criar_projeto_pipeline_completa_minimo(tmp_path, legendas_queimadas=False, marca_dagua_projeto=None):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)

    indice = {"clipes": [{"arquivo": "clipe.mp4"}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps(indice), encoding="utf-8")
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 2.0,
        "palavras": [{"palavra": "Test", "inicio_s": 0.0, "fim_s": 1.0}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(json.dumps(alinhamento), encoding="utf-8")

    config_video = {"legendas_queimadas": legendas_queimadas, "com_musica_fundo": False}
    if marca_dagua_projeto is not None:
        config_video["marca_dagua_projeto"] = marca_dagua_projeto
        (pasta_projeto / "entrada").mkdir(exist_ok=True)
        (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
            json.dumps(config_video), encoding="utf-8"
        )
    return pasta_projeto


def _run_mock_sucesso_generico(cmd, *args, **kwargs):
    resultado = MagicMock()
    resultado.returncode = 0
    resultado.stderr = ""
    for arg in reversed(cmd):
        if isinstance(arg, str) and arg.endswith(".mp4"):
            Path(arg).parent.mkdir(parents=True, exist_ok=True)
            Path(arg).write_bytes(b"fake video")
            break
    return resultado


def test_montar_video_sem_marca_configurada_comando_identico_ao_historico(tmp_path, monkeypatch):
    """Nao-regressao (GRUPO F): sem marca d'agua nenhuma configurada
    (default "canal", sem marca global), a montagem NUNCA passa pelo
    caminho novo de overlay - `aplicar_marca_dagua` nunca e' chamada."""
    pasta_projeto = _criar_projeto_pipeline_completa_minimo(tmp_path)
    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso_generico)
    chamou_marca_dagua = []
    monkeypatch.setattr(
        modulo, "aplicar_marca_dagua", lambda *a, **k: chamou_marca_dagua.append(1) or (None, None, None)
    )

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert chamou_marca_dagua == []
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["marca_dagua_aplicada"] is False
    assert metadata["marca_dagua_aviso"] is None


def test_montar_video_com_marca_global_aplica_e_registra_metadata(tmp_path, monkeypatch):
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(b"fake png")
    pasta_projeto = _criar_projeto_pipeline_completa_minimo(tmp_path, marca_dagua_projeto="canal")
    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso_generico)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["marca_dagua_aplicada"] is True
    assert metadata["marca_dagua_origem"] == "canal"
    assert metadata["marca_dagua_aviso"] is None


def test_montar_video_marca_outra_ausente_segue_sem_marca_com_aviso(tmp_path, monkeypatch):
    """GRUPO E: PNG configurado ("outra") mas ausente do disco - a
    montagem NUNCA falha por causa disso, so' registra o aviso."""
    pasta_projeto = _criar_projeto_pipeline_completa_minimo(tmp_path, marca_dagua_projeto="outra")
    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso_generico)

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "saida" / "video_final.mp4").exists()
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["marca_dagua_aplicada"] is False
    assert metadata["marca_dagua_aviso"] is not None


def test_montar_video_falha_no_overlay_de_marca_nunca_derruba_o_video(tmp_path, monkeypatch):
    """GRUPO E: erro REAL do ffmpeg no overlay (nao PNG ausente) - a
    montagem segue (cai de volta pro caminho sem marca), nunca falha o
    video inteiro por causa da logo, e registra o motivo real do erro."""
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(b"fake png")
    pasta_projeto = _criar_projeto_pipeline_completa_minimo(tmp_path, marca_dagua_projeto="canal")
    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso_generico)
    monkeypatch.setattr(
        modulo,
        "aplicar_marca_dagua",
        lambda *a, **k: (None, "ffmpeg_falhou", "motivo real do ffmpeg: filtro invalido"),
    )

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert (pasta_projeto / "saida" / "video_final.mp4").exists()
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["marca_dagua_aplicada"] is False
    assert "motivo real do ffmpeg" in metadata["marca_dagua_aviso"]


def test_montar_video_marca_e_legenda_juntas_uma_unica_chamada_de_overlay(tmp_path, monkeypatch):
    """Quando legenda queimada E marca d'agua estao ativas, `aplicar_marca_dagua`
    (a fusao das duas num filter_complex so) e' chamada, e `queimar_legendas`
    (caminho so'-legenda) NUNCA e' chamada - uma unica passada de reencode."""
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(b"fake png")
    pasta_projeto = _criar_projeto_pipeline_completa_minimo(
        tmp_path, legendas_queimadas=True, marca_dagua_projeto="canal"
    )
    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso_generico)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")
    chamou_so_legenda = []
    monkeypatch.setattr(
        modulo, "queimar_legendas", lambda *a, **k: chamou_so_legenda.append(1) or (None, None, None)
    )

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert chamou_so_legenda == []
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["marca_dagua_aplicada"] is True
    assert metadata["legendas_queimadas"] is True


def test_montar_video_videos_pre_gerados_com_marca_dagua_tambem_aplica(tmp_path, monkeypatch):
    """GRUPO D: "videos_pre_gerados" usa um caminho de montagem separado da
    pipeline completa - confirma que a marca d'agua tambem e' aplicada la,
    nao so' no caminho principal."""
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    modulo.ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(b"fake png")
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path)
    config_atual = json.loads((pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    config_atual["marca_dagua_projeto"] = "canal"
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(json.dumps(config_atual), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["tipo_projeto"] == "videos_pre_gerados"
    assert metadata["marca_dagua_aplicada"] is True


def test_montar_video_videos_pre_gerados_sem_marca_nao_muda_comportamento(tmp_path, monkeypatch):
    """Nao-regressao para "videos_pre_gerados": sem marca configurada,
    `aplicar_marca_dagua` nunca e' chamada."""
    pasta_projeto = _criar_projeto_videos_pre_gerados(tmp_path)
    monkeypatch.setattr(subprocess, "run", _mock_ffmpeg_cria_saida)
    chamou_marca_dagua = []
    monkeypatch.setattr(
        modulo, "aplicar_marca_dagua", lambda *a, **k: chamou_marca_dagua.append(1) or (None, None, None)
    )

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    assert chamou_marca_dagua == []


# ---------------------------------------------------------------------------
# Constantes de legenda/musica religadas ao .env (CLAUDE.md secao 7) - as
# constantes sao lidas de os.environ no nivel do modulo, entao cada teste
# que exercita um valor de env diferente precisa recarregar o modulo do
# zero (o `modulo` global no topo deste arquivo foi carregado uma unica vez
# na coleta dos testes, antes de qualquer monkeypatch.setenv rodar).
# ---------------------------------------------------------------------------


def _recarregar_modulo_com_env(monkeypatch, **env_vars):
    for chave in (
        "LEGENDA_FONTE",
        "LEGENDA_TAMANHO",
        "LEGENDA_POSICAO",
        "LEGENDA_KARAOKE_ATIVO",
        "LEGENDA_DESTAQUE_COR_NOME",
        "MUSICA_VOLUME_BASE",
        "MARCA_DAGUA_CANAL_POSICAO",
    ):
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in env_vars.items():
        monkeypatch.setenv(chave, valor)

    spec_local = importlib.util.spec_from_file_location(
        f"montar_video_etapa6_env_{id(env_vars)}_{len(env_vars)}", CAMINHO_SCRIPT
    )
    mod = importlib.util.module_from_spec(spec_local)
    sys.modules[spec_local.name] = mod
    spec_local.loader.exec_module(mod)
    return mod


class TestLegendaFonteDoEnv:
    def test_fonte_padrao_sem_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.LEGENDA_FONTE_PADRAO == "Poppins Bold"

    def test_fonte_do_env_valida(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_FONTE="Impact")
        assert mod.LEGENDA_FONTE_PADRAO == "Impact"

    def test_fonte_do_env_invalida_cai_para_padrao(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_FONTE="Comic Sans MS")
        assert mod.LEGENDA_FONTE_PADRAO == "Poppins Bold"

    def test_fontes_suportadas_tem_as_3_opcoes(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.FONTES_LEGENDA_SUPORTADAS == ["Poppins Bold", "Arial Black", "Impact"]


class TestLegendaTamanhoDoEnv:
    def test_tamanho_padrao_sem_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.LEGENDA_TAMANHO_PT == 64

    def test_tamanho_do_env_valido(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_TAMANHO="72")
        assert mod.LEGENDA_TAMANHO_PT == 72

    def test_tamanho_fora_da_lista_cai_para_padrao(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_TAMANHO="100")
        assert mod.LEGENDA_TAMANHO_PT == 64

    def test_tamanho_nao_numerico_cai_para_padrao(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_TAMANHO="abc")
        assert mod.LEGENDA_TAMANHO_PT == 64


class TestLegendaPosicaoDoEnv:
    def test_posicao_padrao_sem_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.LEGENDA_MARGEM_V == 140

    def test_posicao_meio_baixo(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_POSICAO="meio-baixo")
        assert mod.LEGENDA_MARGEM_V == 300

    def test_posicao_invalida_cai_para_padrao(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_POSICAO="topo")
        assert mod.LEGENDA_MARGEM_V == 140


class TestLegendaKaraokeAtivoDoEnv:
    def test_karaoke_ativo_por_padrao_sem_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.LEGENDA_KARAOKE_ATIVO is True

    @pytest.mark.parametrize("valor", ["true", "TRUE", "1", "sim", "SIM"])
    def test_valores_que_ativam(self, monkeypatch, valor):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_KARAOKE_ATIVO=valor)
        assert mod.LEGENDA_KARAOKE_ATIVO is True

    @pytest.mark.parametrize("valor", ["false", "0", "nao", ""])
    def test_valores_que_desativam(self, monkeypatch, valor):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_KARAOKE_ATIVO=valor)
        assert mod.LEGENDA_KARAOKE_ATIVO is False

    def test_karaoke_desativado_gerar_dialogue_sem_tags_k(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_KARAOKE_ATIVO="false")
        frase = {
            "texto": "Ola mundo",
            "palavras": [
                {"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.5},
                {"palavra": "mundo", "inicio_s": 0.5, "fim_s": 1.0},
            ],
        }
        resultado = mod.gerar_dialogue_karaoke(frase)
        assert "\\k" not in resultado
        assert resultado == "Ola mundo"

    def test_karaoke_ativado_gerar_dialogue_com_tags_k(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_KARAOKE_ATIVO="true")
        frase = {
            "texto": "Ola mundo",
            "palavras": [
                {"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.5},
                {"palavra": "mundo", "inicio_s": 0.5, "fim_s": 1.0},
            ],
        }
        resultado = mod.gerar_dialogue_karaoke(frase)
        assert "\\k" in resultado


class TestLegendaCorDestaqueDoEnv:
    def test_cor_padrao_amarelo_sem_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.MRBEAST_COR_DESTAQUE == "&H0000FFFF"

    def test_cor_verde(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_DESTAQUE_COR_NOME="verde")
        assert mod.MRBEAST_COR_DESTAQUE == "&H0000FF00"

    def test_cor_laranja(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_DESTAQUE_COR_NOME="laranja")
        assert mod.MRBEAST_COR_DESTAQUE == "&H000080FF"

    def test_cor_rosa(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_DESTAQUE_COR_NOME="rosa")
        assert mod.MRBEAST_COR_DESTAQUE == "&H00FF00FF"

    def test_cor_invalida_cai_para_amarelo(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_DESTAQUE_COR_NOME="roxo")
        assert mod.MRBEAST_COR_DESTAQUE == "&H0000FFFF"


class TestMusicaVolumeBaseDoEnv:
    def test_volume_padrao_sem_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch)
        assert mod.MUSICA_VOLUME_BASE == 0.18

    def test_volume_do_env_dentro_do_range(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="0.30")
        assert mod.MUSICA_VOLUME_BASE == 0.30

    def test_volume_acima_do_maximo_e_clampado(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="0.99")
        assert mod.MUSICA_VOLUME_BASE == 0.50

    def test_volume_abaixo_do_minimo_e_clampado(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="0.01")
        assert mod.MUSICA_VOLUME_BASE == 0.05

    def test_volume_nao_numerico_cai_para_padrao(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="abc")
        assert mod.MUSICA_VOLUME_BASE == 0.18

    def test_filtro_ducking_usa_volume_do_env(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="0.25")
        filtro = mod.construir_filtro_ducking()
        assert "volume=0.25" in filtro

    def test_filtro_ducking_usa_volume_clampado_maximo(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="0.99")
        filtro = mod.construir_filtro_ducking()
        assert "volume=0.5[music_base]" in filtro

    def test_filtro_ducking_usa_volume_clampado_minimo(self, monkeypatch):
        mod = _recarregar_modulo_com_env(monkeypatch, MUSICA_VOLUME_BASE="0.001")
        filtro = mod.construir_filtro_ducking()
        assert "volume=0.05[music_base]" in filtro


class TestGerarAssEstiloMrbeastComEnv:
    """`gerar_ass_estilo_mrbeast` grava a linha `Style: MrBeastStyle,<fonte>,
    <tamanho>,<cor_primaria>,<cor_destaque>,...,<margem_v>,1` no cabecalho
    [V4+ Styles] do .ass - os testes abaixo verificam que os valores lidos
    do env aparecem nessa linha."""

    def _alinhamento(self):
        return {
            "palavras": [
                {"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.5},
                {"palavra": "mundo", "inicio_s": 0.5, "fim_s": 1.0},
            ]
        }

    def test_fonte_do_env_aparece_na_style_line(self, monkeypatch, tmp_path):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_FONTE="Impact")
        caminho_saida = tmp_path / "legendas.ass"

        mod.gerar_ass_estilo_mrbeast(self._alinhamento(), caminho_saida, fonte="Impact")

        conteudo = caminho_saida.read_text(encoding="utf-8")
        assert "Style: MrBeastStyle,Impact," in conteudo

    def test_tamanho_do_env_aparece_na_style_line(self, monkeypatch, tmp_path):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_TAMANHO="72")
        caminho_saida = tmp_path / "legendas.ass"

        mod.gerar_ass_estilo_mrbeast(self._alinhamento(), caminho_saida, fonte="Impact")

        conteudo = caminho_saida.read_text(encoding="utf-8")
        assert "Style: MrBeastStyle,Impact,72," in conteudo

    def test_posicao_do_env_aparece_na_style_line(self, monkeypatch, tmp_path):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_POSICAO="meio-baixo")
        caminho_saida = tmp_path / "legendas.ass"

        mod.gerar_ass_estilo_mrbeast(self._alinhamento(), caminho_saida, fonte="Impact")

        conteudo = caminho_saida.read_text(encoding="utf-8")
        assert ",300,1\n" in conteudo

    def test_cor_destaque_do_env_aparece_na_style_line(self, monkeypatch, tmp_path):
        mod = _recarregar_modulo_com_env(monkeypatch, LEGENDA_DESTAQUE_COR_NOME="verde")
        caminho_saida = tmp_path / "legendas.ass"

        mod.gerar_ass_estilo_mrbeast(self._alinhamento(), caminho_saida, fonte="Impact")

        conteudo = caminho_saida.read_text(encoding="utf-8")
        assert "&H0000FF00" in conteudo


# ---------------------------------------------------------------------------
# Intro/ending anexados ao video final (sessao "Intro e ending anexados ao
# video final") - descoberta, normalizacao (GRUPO B) e concatenacao final
# (GRUPO C). Mocka subprocess.run (ffmpeg e ffprobe) - nunca chama ffmpeg
# real (CLAUDE.md secao 8).
# ---------------------------------------------------------------------------


def _mock_ffprobe_ffmpeg(
    duracao_s=10.0,
    specs="1920,1080,30/1,yuv420p,h264",
    tem_audio=True,
    falhar_ffmpeg=False,
):
    """Fabrica de mock de `subprocess.run` que responde de forma diferente
    conforme o comando (ffprobe de duracao / specs / audio, ou ffmpeg) -
    generalizacao do padrao `_run_mock` ja usado no resto deste arquivo,
    necessario aqui porque a normalizacao de intro/ending chama ffprobe de
    3 formas diferentes."""

    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        if cmd[0] == "ffprobe":
            if any("width,height,r_frame_rate,pix_fmt,codec_name" in str(arg) for arg in cmd):
                resultado.stdout = specs
            elif "-select_streams" in cmd and cmd[cmd.index("-select_streams") + 1] == "a":
                resultado.stdout = "0" if tem_audio else ""
            else:
                resultado.stdout = str(duracao_s)
            return resultado
        # ffmpeg - grava o arquivo de saida (ultimo argumento) pra
        # `.exists()` bater, exceto quando o teste pede falha proposital.
        if falhar_ffmpeg:
            resultado.returncode = 1
            resultado.stderr = "erro fabricado de teste"
            return resultado
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"fake")
        return resultado

    return _run_mock


def test_descobrir_intro_ausente_retorna_none(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)

    assert modulo.descobrir_intro(pasta_projeto) is None
    assert modulo.descobrir_ending(pasta_projeto) is None


def test_descobrir_intro_encontra_arquivo(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mov").write_bytes(b"fake")

    caminho = modulo.descobrir_intro(pasta_projeto)

    assert caminho == pasta_projeto / "entrada" / "intro.mov"


def test_video_ja_no_padrao_bate_todos_campos():
    specs = {"largura": 1920, "altura": 1080, "fps": 30.0, "pix_fmt": "yuv420p", "codec": "h264"}
    assert modulo._video_ja_no_padrao(specs, 1920, 1080, 30.0) is True


def test_video_ja_no_padrao_resolucao_diferente_reprova():
    specs = {"largura": 1280, "altura": 720, "fps": 30.0, "pix_fmt": "yuv420p", "codec": "h264"}
    assert modulo._video_ja_no_padrao(specs, 1920, 1080, 30.0) is False


def test_video_ja_no_padrao_fps_dentro_da_tolerancia_aprova():
    specs = {"largura": 1920, "altura": 1080, "fps": 29.97, "pix_fmt": "yuv420p", "codec": "h264"}
    assert modulo._video_ja_no_padrao(specs, 1920, 1080, 29.99) is True


def test_video_ja_no_padrao_specs_none_reprova():
    assert modulo._video_ja_no_padrao(None, 1920, 1080, 30.0) is False


def test_construir_comando_normalizar_intro_ending_pula_filtro_quando_ja_no_padrao():
    comando = modulo.construir_comando_normalizar_intro_ending(
        Path("intro.mp4"), Path("saida.mp4"), 1920, 1080, 30.0,
        tem_audio=True, duracao_s=5.0, pular_filtro_escala=True,
        marca_path=None, posicao_marca="inferior_direito", encoder="libx264",
    )
    assert "-filter_complex" not in comando
    assert "copy" in comando[comando.index("-c:v") + 1]
    assert "0:a" in comando


def test_construir_comando_normalizar_intro_ending_sem_audio_usa_anullsrc():
    comando = modulo.construir_comando_normalizar_intro_ending(
        Path("intro.mp4"), Path("saida.mp4"), 1920, 1080, 30.0,
        tem_audio=False, duracao_s=5.0, pular_filtro_escala=True,
        marca_path=None, posicao_marca="inferior_direito", encoder="libx264",
    )
    assert any("anullsrc" in str(item) for item in comando)


def test_construir_comando_normalizar_intro_ending_com_marca_adiciona_overlay(tmp_path):
    marca_path = tmp_path / "marca.png"
    comando = modulo.construir_comando_normalizar_intro_ending(
        Path("intro.mp4"), Path("saida.mp4"), 1920, 1080, 30.0,
        tem_audio=True, duracao_s=5.0, pular_filtro_escala=True,
        marca_path=marca_path, posicao_marca="inferior_direito", encoder="libx264",
    )
    assert "-filter_complex" in comando
    filtro = comando[comando.index("-filter_complex") + 1]
    assert "overlay=" in filtro
    # Filtro de escala foi pulado (pular_filtro_escala=True) mas o overlay
    # da marca continua presente - reencode acontece so' por causa dela.
    assert "scale=1920:1080:force_original_aspect_ratio" not in filtro


def test_construir_comando_normalizar_intro_ending_sem_pular_aplica_filtro_de_escala():
    comando = modulo.construir_comando_normalizar_intro_ending(
        Path("intro.mp4"), Path("saida.mp4"), 1280, 720, 24.0,
        tem_audio=True, duracao_s=5.0, pular_filtro_escala=False,
        marca_path=None, posicao_marca="inferior_direito", encoder="libx264",
    )
    filtro = comando[comando.index("-filter_complex") + 1]
    assert "scale=1280:720:force_original_aspect_ratio=decrease" in filtro
    assert "fps=24.000" in filtro


def test_anexar_intro_ending_sem_intro_nem_ending_retorna_video_original(tmp_path, monkeypatch):
    """Nao-regressao (GRUPO H): projeto sem intro/ending nunca chama
    ffprobe/ffmpeg nesta funcao - o video pronto volta inalterado."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    chamou_subprocess = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: chamou_subprocess.append(1))

    resultado = modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    assert resultado["video"] == video_pronto
    assert resultado["duracao_intro_s"] == 0.0
    assert resultado["intro_aplicada"] is False
    assert resultado["ending_aplicada"] is False
    assert resultado["avisos"] == []
    assert not chamou_subprocess


def test_anexar_intro_ending_so_intro(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg(duracao_s=6.0))

    resultado = modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    assert resultado["intro_aplicada"] is True
    assert resultado["ending_aplicada"] is False
    assert resultado["duracao_intro_s"] == 6.0
    assert resultado["video"] != video_pronto
    assert resultado["video"].exists()
    assert resultado["avisos"] == []


def test_anexar_intro_ending_so_ending(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "ending.mp4").write_bytes(b"fake")
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg())

    resultado = modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    assert resultado["intro_aplicada"] is False
    assert resultado["ending_aplicada"] is True
    # Ending nao afeta o inicio da narracao - duracao_intro_s continua 0.
    assert resultado["duracao_intro_s"] == 0.0
    assert resultado["video"] != video_pronto


def test_anexar_intro_ending_ambos(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")
    (pasta_projeto / "entrada" / "ending.mp4").write_bytes(b"fake")
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg(duracao_s=4.5))

    resultado = modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    assert resultado["intro_aplicada"] is True
    assert resultado["ending_aplicada"] is True
    assert resultado["duracao_intro_s"] == 4.5


def test_anexar_intro_ending_normalizacao_ja_no_padrao_pula_reencode_de_video(tmp_path, monkeypatch):
    """GRUPO B: specs do arquivo ja' batem com o video montado - o filtro de
    escala e' pulado (so' o audio e' reencodado)."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    comandos_ffmpeg = []

    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        if cmd[0] == "ffprobe":
            if any("width,height,r_frame_rate,pix_fmt,codec_name" in str(arg) for arg in cmd):
                resultado.stdout = "1920,1080,30/1,yuv420p,h264"
            elif "-select_streams" in cmd and cmd[cmd.index("-select_streams") + 1] == "a":
                resultado.stdout = "0"
            else:
                resultado.stdout = "5.0"
            return resultado
        comandos_ffmpeg.append(cmd)
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"fake")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    comando_normalizacao = comandos_ffmpeg[0]
    assert "-filter_complex" not in comando_normalizacao
    assert "copy" in comando_normalizacao[comando_normalizacao.index("-c:v") + 1]


def test_anexar_intro_ending_falha_normalizacao_nao_derruba_montagem(tmp_path, monkeypatch):
    """GRUPO B: normalizacao falha (ffmpeg retorna erro) - o video segue
    exatamente como estava, so' com um aviso real registrado."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg(falhar_ffmpeg=True))

    resultado = modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    assert resultado["video"] == video_pronto
    assert resultado["intro_aplicada"] is False
    assert resultado["duracao_intro_s"] == 0.0
    assert len(resultado["avisos"]) == 1
    assert "intro" in resultado["avisos"][0]


def test_anexar_intro_ending_falha_concat_final_nao_derruba_montagem(tmp_path, monkeypatch):
    """GRUPO C: normalizacao da intro funciona, mas o concat FINAL (intro +
    video pronto) falha - o video segue sem intro, com aviso real."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")
    video_pronto = tmp_path / "video_pronto.mp4"
    video_pronto.write_bytes(b"fake")

    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        if cmd[0] == "ffprobe":
            if any("width,height,r_frame_rate,pix_fmt,codec_name" in str(arg) for arg in cmd):
                resultado.stdout = "1920,1080,30/1,yuv420p,h264"
            elif "-select_streams" in cmd and cmd[cmd.index("-select_streams") + 1] == "a":
                resultado.stdout = "0"
            else:
                resultado.stdout = "5.0"
            return resultado
        # ffmpeg: normalizacao (saida termina em "_normalizado.mp4") sempre
        # funciona; o concat final (demuxer, sem esse sufixo) falha.
        if "_normalizado.mp4" in cmd[-1]:
            caminho_saida = Path(cmd[-1])
            caminho_saida.parent.mkdir(parents=True, exist_ok=True)
            caminho_saida.write_bytes(b"fake")
            return resultado
        resultado.returncode = 1
        resultado.stderr = "falha fabricada no concat final"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    resultado = modulo.anexar_intro_ending(pasta_projeto, video_pronto, None, "inferior_direito", "libx264")

    assert resultado["video"] == video_pronto
    assert resultado["intro_aplicada"] is False
    assert any("concatenar" in aviso for aviso in resultado["avisos"])


def test_gerar_srt_offset_zero_preserva_comportamento_historico(tmp_path):
    alinhamento = {"palavras": [{"palavra": "Ola", "inicio_s": 1.0, "fim_s": 1.5}]}
    caminho = modulo.gerar_srt(alinhamento, tmp_path / "legendas.srt")

    conteudo = caminho.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:01,500" in conteudo


def test_gerar_srt_com_offset_desloca_todos_os_timestamps(tmp_path):
    """TESTE OBRIGATORIO (GRUPO E): com intro de duracao conhecida, a
    primeira legenda no video final precisa aparecer exatamente quando a
    narracao comeca (offset_s = duracao da intro), nunca antes."""
    alinhamento = {"palavras": [{"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.5}]}
    caminho = modulo.gerar_srt(alinhamento, tmp_path / "legendas.srt", offset_s=5.0)

    conteudo = caminho.read_text(encoding="utf-8")
    assert "00:00:05,000 --> 00:00:05,500" in conteudo
    assert "00:00:00,000" not in conteudo


def _projeto_pipeline_completa_minimo(pasta_projeto: Path):
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "saida").mkdir(exist_ok=True)
    indice = {"clipes": [{"arquivo": "clipe.mp4", "duracao_s": 8.0}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps(indice), encoding="utf-8")
    (pasta_projeto / "narracao.mp3").write_bytes(b"fake")
    alinhamento = {
        "duracao_s": 8.0,
        "palavras": [{"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.5}],
    }
    (pasta_projeto / "narracao_alinhamento.json").write_text(json.dumps(alinhamento), encoding="utf-8")


def test_montar_video_pipeline_completa_com_intro_desloca_softsub_e_marca_metadata(tmp_path, monkeypatch):
    """Integracao: projeto com intro configurada roda o pipeline completo
    (mockado) de ponta a ponta e confirma que a legenda embutida final (SRT
    do softsub) foi deslocada pela duracao da intro, e que a metadata reflete
    intro_aplicada=True."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    _projeto_pipeline_completa_minimo(pasta_projeto)
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg(duracao_s=3.0))
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["intro_aplicada"] is True
    assert metadata["duracao_intro_s"] == 3.0

    srt_final = (pasta_projeto / "saida" / "legendas.srt").read_text(encoding="utf-8")
    assert "00:00:03,000 --> 00:00:03,500" in srt_final
    assert "00:00:00,000" not in srt_final


def test_montar_video_pipeline_completa_sem_intro_nem_ending_metadata_reflete_ausencia(tmp_path, monkeypatch):
    """Nao-regressao: projeto sem intro/ending tem intro_aplicada=False e
    duracao_intro_s=0.0 na metadata, e a legenda final continua comecando em
    t=0 (comportamento historico, sem deslocamento nenhum)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    _projeto_pipeline_completa_minimo(pasta_projeto)

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg())
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["intro_aplicada"] is False
    assert metadata["ending_aplicada"] is False
    assert metadata["duracao_intro_s"] == 0.0

    srt_final = (pasta_projeto / "saida" / "legendas.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:00,500" in srt_final


def test_montar_video_videos_pre_gerados_aplica_intro_ending(tmp_path, monkeypatch):
    """GRUPO G: "videos_pre_gerados" tambem aplica intro/ending, sem nenhuma
    logica de deslocamento de timing (nao ha narracao/softsub nesse tipo de
    projeto)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "saida").mkdir(exist_ok=True)
    (pasta_projeto / "entrada").mkdir(parents=True, exist_ok=True)
    (pasta_projeto / "entrada" / "tipo_projeto.txt").write_text("videos_pre_gerados", encoding="utf-8")
    (pasta_projeto / "entrada" / "intro.mp4").write_bytes(b"fake")
    indice = {"clipes": [{"arquivo": "clipe.mp4", "duracao_s": 8.0}]}
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps(indice), encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", _mock_ffprobe_ffmpeg(duracao_s=2.0))
    monkeypatch.setattr(modulo, "_detectar_encoder_gpu", lambda: "libx264")

    resultado = modulo.montar_video(pasta_projeto)

    assert resultado["sucesso"] is True
    metadata = json.loads((pasta_projeto / "saida" / "montagem_metadata.json").read_text(encoding="utf-8"))
    assert metadata["tipo_projeto"] == "videos_pre_gerados"
    assert metadata["intro_aplicada"] is True


def test_projeto_antigo_sem_intro_ending_nao_quebra_descoberta(tmp_path):
    """Projeto criado antes desta feature (entrada/ existe, mas sem
    intro.*/ending.*) - descoberta retorna None pros dois, nunca levanta
    excecao."""
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text("http://x", encoding="utf-8")

    assert modulo.descobrir_intro(pasta_projeto) is None
    assert modulo.descobrir_ending(pasta_projeto) is None
