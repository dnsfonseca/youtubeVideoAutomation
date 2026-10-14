"""Testes de scripts/validators.py — normalizacao e validacao do campo
PROJETOS_DIR digitado/colado pelo usuario na tela de Ajustes.

Ver CLAUDE.md secao 8 (convencoes de teste): funcoes puras como estas tem
cobertura alvo de 90%.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from scripts.validators import (
    chave_dedup_youtube,
    classificar_extensao_upload,
    normalizar_caminho,
    prefixo_numerico_arquivo,
    validar_caminho_projetos,
    validar_extensao_intro_ending,
    validar_modo_fontes,
    validar_tipo_projeto,
    validar_tipo_uso,
    validar_video_legivel_ffprobe,
)


# ---------------------------------------------------------------------------
# normalizar_caminho
# ---------------------------------------------------------------------------


def test_normalizar_caminho_remove_barra_final(tmp_path):
    bruto = str(tmp_path) + os.sep
    resultado = normalizar_caminho(bruto)

    assert resultado == str(tmp_path)


def test_normalizar_caminho_remove_aspas_duplas_envolventes(tmp_path):
    bruto = f'"{tmp_path}"'
    resultado = normalizar_caminho(bruto)

    assert resultado == str(tmp_path)


def test_normalizar_caminho_remove_aspas_simples_envolventes(tmp_path):
    bruto = f"'{tmp_path}'"
    resultado = normalizar_caminho(bruto)

    assert resultado == str(tmp_path)


def test_normalizar_caminho_remove_espacos_em_volta(tmp_path):
    bruto = f"   {tmp_path}   "
    resultado = normalizar_caminho(bruto)

    assert resultado == str(tmp_path)


def test_normalizar_caminho_aceita_barras_mistas_e_normaliza_para_separador_nativo(tmp_path):
    """Mistura separador nativo do SO com barra normal ("/") — comportamento
    tipico de caminho colado do Explorer em alguns editores. O resultado tem
    que ser consistente com o separador nativo, sem depender de qual barra
    foi digitada."""
    esperado = Path(f"{tmp_path}{os.sep}pasta_a{os.sep}pasta_b").resolve()
    bruto = f"{tmp_path}{os.sep}pasta_a/pasta_b"

    resultado = normalizar_caminho(bruto)

    assert resultado == str(esperado)


def test_normalizar_caminho_resolve_ponto_ponto(tmp_path):
    """Cria estrutura real tmp_path/a/b e confirma que um caminho terminado
    em ".." resolve para o diretorio pai, exatamente como pathlib.resolve()."""
    pasta_a = tmp_path / "a"
    pasta_b = pasta_a / "b"
    pasta_b.mkdir(parents=True)

    bruto = str(pasta_b / "..")
    resultado = normalizar_caminho(bruto)

    assert resultado == str(pasta_a)


# ---------------------------------------------------------------------------
# validar_caminho_projetos
# ---------------------------------------------------------------------------


def test_validar_caminho_projetos_retorna_true_quando_pasta_ja_existe_e_e_escrivel(tmp_path):
    pasta = tmp_path / "projetos_existentes"
    pasta.mkdir()

    valido, resultado = validar_caminho_projetos(str(pasta))

    assert valido is True
    assert resultado == str(pasta)


def test_validar_caminho_projetos_cria_a_pasta_quando_ela_ainda_nao_existe(tmp_path):
    pasta_nova = tmp_path / "nova_pasta"
    assert not pasta_nova.exists()

    valido, resultado = validar_caminho_projetos(str(pasta_nova))

    assert valido is True
    assert pasta_nova.exists() and pasta_nova.is_dir()
    assert resultado == str(pasta_nova)


def test_validar_caminho_projetos_retorna_false_quando_drive_raiz_nao_existe(monkeypatch):
    """Usa monkeypatch em vez de depender de uma letra de drive real
    (ex: "Z:") estar ausente na maquina — mais robusto contra maquinas
    com drives de rede mapeados em letras incomuns. Como
    validar_caminho_projetos retorna imediatamente apos raiz.exists() dar
    False (antes de qualquer mkdir/escrita), forcar Path.exists a sempre
    retornar False e' seguro e nao mascara nenhum outro comportamento da
    funcao dentro deste teste."""
    monkeypatch.setattr(Path, "exists", lambda self: False)

    valido, mensagem = validar_caminho_projetos(r"Z:\pasta_impossivel_12345\projetos")

    assert valido is False
    assert isinstance(mensagem, str) and mensagem


# ---------------------------------------------------------------------------
# validar_modo_fontes / validar_tipo_uso / classificar_extensao_upload
# (feature de fontes separadas - CLAUDE.md secao 5.7.1-bis)
# ---------------------------------------------------------------------------


def test_validar_modo_fontes_aceita_unificado_e_separado():
    assert validar_modo_fontes("unificado") is True
    assert validar_modo_fontes("separado") is True


def test_validar_modo_fontes_rejeita_valor_invalido():
    assert validar_modo_fontes("misto") is False
    assert validar_modo_fontes("") is False


def test_validar_tipo_uso_aceita_ambos_transcricao_visual():
    assert validar_tipo_uso("ambos") is True
    assert validar_tipo_uso("transcricao") is True
    assert validar_tipo_uso("visual") is True


# ---------------------------------------------------------------------------
# validar_tipo_projeto
# ---------------------------------------------------------------------------


def test_validar_tipo_projeto_aceita_pipeline_completa_e_videos_pre_gerados():
    assert validar_tipo_projeto("pipeline_completa") is True
    assert validar_tipo_projeto("videos_pre_gerados") is True


def test_validar_tipo_projeto_rejeita_valor_invalido():
    assert validar_tipo_projeto("qualquer_coisa") is False
    assert validar_tipo_projeto("") is False


# ---------------------------------------------------------------------------
# prefixo_numerico_arquivo
# ---------------------------------------------------------------------------


def test_prefixo_numerico_arquivo_extrai_numero_do_inicio():
    assert prefixo_numerico_arquivo("1_Wide_shot.mp4") == 1
    assert prefixo_numerico_arquivo("2_Close_up.mp4") == 2


def test_prefixo_numerico_arquivo_10_vem_depois_de_9_numericamente():
    nomes = ["10_ultimo.mp4", "9_penultimo.mp4", "1_primeiro.mp4"]
    ordenado = sorted(nomes, key=prefixo_numerico_arquivo)
    assert ordenado == ["1_primeiro.mp4", "9_penultimo.mp4", "10_ultimo.mp4"]


def test_prefixo_numerico_arquivo_sem_prefixo_vai_pro_fim():
    nomes = ["sem_numero.mp4", "1_primeiro.mp4"]
    ordenado = sorted(nomes, key=prefixo_numerico_arquivo)
    assert ordenado == ["1_primeiro.mp4", "sem_numero.mp4"]


def test_validar_tipo_uso_rejeita_valor_invalido():
    assert validar_tipo_uso("qualquer_coisa") is False
    assert validar_tipo_uso("") is False


def test_classificar_extensao_upload_reconhece_imagens():
    for nome in ("foto.jpg", "FOTO.JPEG", "still.png", "still.WEBP"):
        assert classificar_extensao_upload(nome) == "imagem"


def test_classificar_extensao_upload_reconhece_videos():
    for nome in ("clipe.mp4", "clipe.MOV", "clipe.webm"):
        assert classificar_extensao_upload(nome) == "video"


def test_classificar_extensao_upload_rejeita_extensao_nao_suportada():
    assert classificar_extensao_upload("script.exe") is None
    assert classificar_extensao_upload("documento.pdf") is None
    assert classificar_extensao_upload("sem_extensao") is None


# ---------------------------------------------------------------------------
# normalizar_palavras_alvo / normalizar_duracao_alvo_minutos
# (Sessao de tamanho configuravel do roteiro - CLAUDE.md secao 5.3/7)
# ---------------------------------------------------------------------------


def test_normalizar_palavras_alvo_valor_valido_dentro_da_faixa():
    """Valor 5000 (entre 1000 e 15000) retorna 5000 sem alteração."""
    from scripts.validators import normalizar_palavras_alvo

    resultado = normalizar_palavras_alvo("5000")
    assert resultado == 5000


def test_normalizar_palavras_alvo_abaixo_do_minimo_cai_no_default():
    """Valor 500 (< 1000) cai no default 4000."""
    from scripts.validators import normalizar_palavras_alvo

    resultado = normalizar_palavras_alvo("500")
    assert resultado == 4000


def test_normalizar_palavras_alvo_acima_do_maximo_cai_no_default():
    """Valor 99999 (> 15000) cai no default 4000."""
    from scripts.validators import normalizar_palavras_alvo

    resultado = normalizar_palavras_alvo("99999")
    assert resultado == 4000


def test_normalizar_palavras_alvo_nao_numerico_cai_no_default():
    """Valor "abc" não é convertível a int, cai no default 4000."""
    from scripts.validators import normalizar_palavras_alvo

    resultado = normalizar_palavras_alvo("abc")
    assert resultado == 4000


def test_normalizar_palavras_alvo_none_cai_no_default():
    """Valor None cai no default 4000."""
    from scripts.validators import normalizar_palavras_alvo

    resultado = normalizar_palavras_alvo(None)
    assert resultado == 4000


def test_normalizar_palavras_alvo_vazio_cai_no_default():
    """Valor vazio ("") cai no default 4000."""
    from scripts.validators import normalizar_palavras_alvo

    resultado = normalizar_palavras_alvo("")
    assert resultado == 4000


def test_normalizar_duracao_alvo_minutos_valor_valido_dentro_da_faixa():
    """Valor 30 (entre 5 e 120) retorna 30 sem alteração."""
    from scripts.validators import normalizar_duracao_alvo_minutos

    resultado = normalizar_duracao_alvo_minutos("30")
    assert resultado == 30


def test_normalizar_duracao_alvo_minutos_abaixo_do_minimo_cai_no_default():
    """Valor 2 (< 5) cai no default 25."""
    from scripts.validators import normalizar_duracao_alvo_minutos

    resultado = normalizar_duracao_alvo_minutos("2")
    assert resultado == 25


def test_normalizar_duracao_alvo_minutos_acima_do_maximo_cai_no_default():
    """Valor 999 (> 120) cai no default 25."""
    from scripts.validators import normalizar_duracao_alvo_minutos

    resultado = normalizar_duracao_alvo_minutos("999")
    assert resultado == 25


def test_normalizar_duracao_alvo_minutos_nao_numerico_cai_no_default():
    """Valor "xyz" não é convertível a int, cai no default 25."""
    from scripts.validators import normalizar_duracao_alvo_minutos

    resultado = normalizar_duracao_alvo_minutos("xyz")
    assert resultado == 25


def test_normalizar_duracao_alvo_minutos_none_cai_no_default():
    """Valor None cai no default 25."""
    from scripts.validators import normalizar_duracao_alvo_minutos

    resultado = normalizar_duracao_alvo_minutos(None)
    assert resultado == 25


def test_normalizar_duracao_alvo_minutos_vazio_cai_no_default():
    """Valor vazio ("") cai no default 25."""
    from scripts.validators import normalizar_duracao_alvo_minutos

    resultado = normalizar_duracao_alvo_minutos("")
    assert resultado == 25


# ---------------------------------------------------------------------------
# chave_dedup_youtube (CLAUDE.md secao 5.7.2 - dedup de URL no modo separado)
# ---------------------------------------------------------------------------


def test_chave_dedup_youtube_watch_e_youtu_be_sao_a_mesma_chave():
    a = chave_dedup_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    b = chave_dedup_youtube("https://youtu.be/dQw4w9WgXcQ")
    assert a == b == "youtube:dQw4w9WgXcQ"


def test_chave_dedup_youtube_ignora_www_e_m():
    a = chave_dedup_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    b = chave_dedup_youtube("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
    assert a == b


def test_chave_dedup_youtube_ignora_parametros_extras():
    a = chave_dedup_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    b = chave_dedup_youtube(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxx&index=3&t=90s"
    )
    assert a == b


def test_chave_dedup_youtube_youtube_be_ignora_query_de_timestamp():
    a = chave_dedup_youtube("https://youtu.be/dQw4w9WgXcQ")
    b = chave_dedup_youtube("https://youtu.be/dQw4w9WgXcQ?t=42")
    assert a == b


def test_chave_dedup_youtube_reconhece_shorts():
    a = chave_dedup_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    b = chave_dedup_youtube("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert a == b


def test_chave_dedup_youtube_ids_diferentes_geram_chaves_diferentes():
    a = chave_dedup_youtube("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    b = chave_dedup_youtube("https://www.youtube.com/watch?v=bbbbbbbbbbb")
    assert a != b


def test_chave_dedup_youtube_url_nao_reconhecida_cai_para_url_crua():
    resultado = chave_dedup_youtube("https://vimeo.com/12345678")
    assert resultado == "https://vimeo.com/12345678"


def test_chave_dedup_youtube_url_vazia_retorna_vazia():
    assert chave_dedup_youtube("") == ""
    assert chave_dedup_youtube(None) == ""


def test_chave_dedup_youtube_url_malformada_nao_lanca_excecao():
    resultado = chave_dedup_youtube("não é uma url ::: [[[")
    assert isinstance(resultado, str)


# ---------------------------------------------------------------------------
# validar_extensao_intro_ending / validar_video_legivel_ffprobe (secao
# "Intro e ending anexados ao video final", GRUPO A)
# ---------------------------------------------------------------------------


def test_validar_extensao_intro_ending_aceita_formatos_comuns():
    assert validar_extensao_intro_ending("intro.mp4") is True
    assert validar_extensao_intro_ending("intro.MOV") is True
    assert validar_extensao_intro_ending("intro.webm") is True


def test_validar_extensao_intro_ending_rejeita_outros_formatos():
    assert validar_extensao_intro_ending("intro.avi") is False
    assert validar_extensao_intro_ending("intro.png") is False
    assert validar_extensao_intro_ending("intro") is False


def test_validar_video_legivel_ffprobe_sucesso(monkeypatch, tmp_path):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stdout = "codec_type=video\nduration=12.345\n"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    legivel, duracao_s, mensagem_erro = validar_video_legivel_ffprobe(tmp_path / "intro.mp4")

    assert legivel is True
    assert duracao_s == 12.345
    assert mensagem_erro is None


def test_validar_video_legivel_ffprobe_sem_stream_de_video(monkeypatch, tmp_path):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stdout = "duration=12.345\n"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    legivel, duracao_s, mensagem_erro = validar_video_legivel_ffprobe(tmp_path / "corrompido.mp4")

    assert legivel is False
    assert duracao_s == 0.0
    assert mensagem_erro is not None


def test_validar_video_legivel_ffprobe_returncode_diferente_de_zero(monkeypatch, tmp_path):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stdout = ""
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    legivel, _duracao_s, mensagem_erro = validar_video_legivel_ffprobe(tmp_path / "corrompido.mp4")

    assert legivel is False
    assert mensagem_erro is not None


def test_validar_video_legivel_ffprobe_duracao_zero_e_invalido(monkeypatch, tmp_path):
    def _run_mock(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stdout = "codec_type=video\nduration=0.0\n"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock)

    legivel, duracao_s, mensagem_erro = validar_video_legivel_ffprobe(tmp_path / "vazio.mp4")

    assert legivel is False
    assert duracao_s == 0.0
    assert mensagem_erro is not None


def test_validar_video_legivel_ffprobe_ausente_do_path_nao_lanca_excecao(monkeypatch, tmp_path):
    def _run_raises(*args, **kwargs):
        raise OSError("ffprobe nao encontrado")

    monkeypatch.setattr(subprocess, "run", _run_raises)

    legivel, duracao_s, mensagem_erro = validar_video_legivel_ffprobe(tmp_path / "intro.mp4")

    assert legivel is False
    assert duracao_s == 0.0
    assert "ffprobe" in mensagem_erro.lower()
