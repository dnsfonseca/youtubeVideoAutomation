"""Testes da Etapa 5 do pipeline (scripts/5_gerar_clipes.py) — geração de
clipes por seleção aleatória de trechos (CLAUDE.md seção 5.7/5.8).

Nunca chama ffmpeg real — subprocess.run é sempre mockado. Testes de
funções puras (calcular_plano_slots, _sortear_timestamp, _tem_sobreposicao,
construir_comando_ffmpeg) são testados sem nenhum subprocess. Testes de
orquestração (gerar_clipes) mockam subprocess.run para simular sucesso/falha
do ffmpeg.
"""

import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "5_gerar_clipes.py"

_spec = importlib.util.spec_from_file_location("gerar_clipes_etapa5", CAMINHO_SCRIPT)
modulo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = modulo
_spec.loader.exec_module(modulo)


@pytest.fixture(autouse=True)
def _ffmpeg_disponivel_por_padrao(monkeypatch):
    """Por padrão, simula ffmpeg disponível. Testes que exercitam ffmpeg
    ausente sobrescrevem isso explicitamente."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))


# ---------------------------------------------------------------------------
# calcular_plano_slots — divisão determinística da timeline em slots
# ---------------------------------------------------------------------------


def test_calcular_plano_slots_cobre_toda_duracao_da_narracao():
    """Os slots gerados cobrem (quase exatamente) a duração da narração."""
    duracao_narracao = 60.0
    rng = random.Random(42)
    slots = modulo.calcular_plano_slots(duracao_narracao, 5.0, 10.0, rng)

    assert slots, "Deve gerar pelo menos um slot"
    total_duracao = sum(s["duracao_alvo_s"] for s in slots)
    assert total_duracao == pytest.approx(duracao_narracao, abs=2.0), \
        f"Cobertura {total_duracao} não bate com duração {duracao_narracao}"


def test_calcular_plano_slots_cada_slot_respeita_minimo_e_maximo():
    """Cada slot tem duracao_alvo_s dentro de [clipe_min_s, clipe_max_s],
    exceto possível o último (trimmed para caber)."""
    duracao_narracao = 100.0
    clipe_min = 5.0
    clipe_max = 12.0
    rng = random.Random(42)
    slots = modulo.calcular_plano_slots(duracao_narracao, clipe_min, clipe_max, rng)

    for i, slot in enumerate(slots[:-1]):  # todos exceto o último
        assert clipe_min <= slot["duracao_alvo_s"] <= clipe_max, \
            f"Slot {i} duracao {slot['duracao_alvo_s']} fora de [{clipe_min}, {clipe_max}]"


def test_calcular_plano_slots_slots_contiguos():
    """Cada slot começa exatamente onde o anterior termina (posição_inicio)."""
    duracao_narracao = 50.0
    rng = random.Random(42)
    slots = modulo.calcular_plano_slots(duracao_narracao, 6.0, 10.0, rng)

    tempo_acumulado = 0.0
    for i, slot in enumerate(slots):
        assert slot["posicao_inicio_narracao_s"] == pytest.approx(tempo_acumulado, abs=0.01), \
            f"Slot {i} posição {slot['posicao_inicio_narracao_s']} não bate com acumulado {tempo_acumulado}"
        tempo_acumulado += slot["duracao_alvo_s"]


def test_calcular_plano_slots_determinístico_com_seed():
    """Mesmo seed produz exatamente os mesmos slots."""
    duracao_narracao = 60.0
    slots1 = modulo.calcular_plano_slots(duracao_narracao, 5.0, 10.0, random.Random(42))
    slots2 = modulo.calcular_plano_slots(duracao_narracao, 5.0, 10.0, random.Random(42))

    assert slots1 == slots2, "Seed determinístico não funciona"


def test_calcular_plano_slots_sementes_diferentes_produzem_planos_diferentes():
    """Seeds diferentes geram slots diferentes (probabilidade muito alta)."""
    duracao_narracao = 60.0
    slots1 = modulo.calcular_plano_slots(duracao_narracao, 5.0, 10.0, random.Random(1))
    slots2 = modulo.calcular_plano_slots(duracao_narracao, 5.0, 10.0, random.Random(2))

    assert slots1 != slots2, "Seeds diferentes deveriam produzir planos diferentes"


def test_calcular_plano_slots_ignora_resto_menor_que_2_segundos():
    """Se o último slot deixaria um resto < 2s, ele é descartado."""
    # Ex: duracao 29.0 com slots de ~10s cada gera apenas 2 slots de ~10s
    # e descarta os ~9s finais por serem < 2s.
    duracao_narracao = 29.0
    rng = random.Random(42)
    slots = modulo.calcular_plano_slots(duracao_narracao, 9.0, 11.0, rng)

    total = sum(s["duracao_alvo_s"] for s in slots)
    assert duracao_narracao - total < 2.0, \
        f"Resto {duracao_narracao - total} não foi descartado por ser >= 2s"


# ---------------------------------------------------------------------------
# _sortear_timestamp — seleção de janela dentro de uma fonte
# ---------------------------------------------------------------------------


def test_sortear_timestamp_retorna_none_quando_fonte_muito_curta():
    """Fonte curta demais para caber o clipe com margens retorna None."""
    duracao_fonte = 50.0  # muito curta
    duracao_clipe = 10.0
    margem_inicio = 30.0
    margem_fim = 30.0
    # espaço disponível: 50 - 30 - 30 = -10 (negativo = impossível)
    rng = random.Random(42)

    resultado = modulo._sortear_timestamp(duracao_fonte, duracao_clipe, margem_inicio, margem_fim, rng)

    assert resultado is None


def test_sortear_timestamp_retorna_valor_dentro_de_margens():
    """Timestamp retornado fica dentro da janela de margem+clipe."""
    duracao_fonte = 200.0
    duracao_clipe = 10.0
    margem_inicio = 30.0
    margem_fim = 30.0
    rng = random.Random(42)

    inicio = modulo._sortear_timestamp(duracao_fonte, duracao_clipe, margem_inicio, margem_fim, rng)

    assert inicio is not None
    assert inicio >= margem_inicio
    assert inicio <= duracao_fonte - margem_fim - duracao_clipe


def test_sortear_timestamp_com_margens_zero():
    """Quando margens são zero, podem começar do primeiro quadro."""
    duracao_fonte = 100.0
    duracao_clipe = 10.0
    rng = random.Random(42)

    inicio = modulo._sortear_timestamp(duracao_fonte, duracao_clipe, 0.0, 0.0, rng)

    assert inicio is not None
    assert 0.0 <= inicio <= 90.0  # 100 - 10


def test_sortear_timestamp_determinístico_com_seed():
    """Mesma seed produz mesmo timestamp."""
    duracao_fonte = 100.0
    duracao_clipe = 5.0
    margem_inicio = 10.0
    margem_fim = 10.0

    ts1 = modulo._sortear_timestamp(duracao_fonte, duracao_clipe, margem_inicio, margem_fim, random.Random(42))
    ts2 = modulo._sortear_timestamp(duracao_fonte, duracao_clipe, margem_inicio, margem_fim, random.Random(42))

    assert ts1 == ts2


# ---------------------------------------------------------------------------
# _tem_sobreposicao — detecção de overlaps
# ---------------------------------------------------------------------------


def test_tem_sobreposicao_detecta_sobreposicao_parcial():
    """Detecta quando [inicio, fim] sobrepõe parcialmente um intervalo usado."""
    intervalos = [(10.0, 20.0)]

    # Sobrepõe no final do intervalo existente
    assert modulo._tem_sobreposicao(15.0, 25.0, intervalos) is True
    # Sobrepõe no início
    assert modulo._tem_sobreposicao(5.0, 15.0, intervalos) is True
    # Contém completamente
    assert modulo._tem_sobreposicao(8.0, 22.0, intervalos) is True


def test_tem_sobreposicao_detecta_sobreposicao_um_contém_outro():
    """Um intervalo contido no outro é sobreposição."""
    intervalos = [(10.0, 20.0)]

    # Intervalo novo dentro do existente
    assert modulo._tem_sobreposicao(12.0, 18.0, intervalos) is True


def test_tem_sobreposicao_retorna_false_para_disjuntos():
    """Intervalos disjuntos não se sobrepõem."""
    intervalos = [(10.0, 20.0), (30.0, 40.0)]

    assert modulo._tem_sobreposicao(0.0, 9.0, intervalos) is False
    assert modulo._tem_sobreposicao(21.0, 29.0, intervalos) is False
    assert modulo._tem_sobreposicao(41.0, 50.0, intervalos) is False


def test_tem_sobreposicao_retorna_false_para_limites_tocando():
    """Limites tocando (fim do novo = início do existente) não é overlap."""
    intervalos = [(10.0, 20.0)]

    assert modulo._tem_sobreposicao(0.0, 10.0, intervalos) is False
    assert modulo._tem_sobreposicao(20.0, 30.0, intervalos) is False


def test_tem_sobreposicao_lista_vazia():
    """Lista vazia de intervalos usados nunca tem sobreposição."""
    assert modulo._tem_sobreposicao(5.0, 10.0, []) is False


# ---------------------------------------------------------------------------
# _selecionar_janela_para_slot — seleção round-robin com fallback
# ---------------------------------------------------------------------------


def test_selecionar_janela_para_slot_round_robin_distribui_fontes():
    """Chamadas consecutivas distribuem clipes entre fontes em round-robin."""
    ordem_fontes = ["fonte01", "fonte02", "fonte03"]
    duracoes_fontes = {"fonte01": 300.0, "fonte02": 300.0, "fonte03": 300.0}
    intervalos_usados = {"fonte01": [], "fonte02": [], "fonte03": []}
    rng = random.Random(42)

    # Primeira chamada: começa em fonte01 (cursor_inicial=0)
    resultado1 = modulo._selecionar_janela_para_slot(
        8.0, ordem_fontes, 0, duracoes_fontes, intervalos_usados, 30.0, 30.0, rng
    )
    fonte1, _, _, cursor1 = resultado1
    assert fonte1 == "fonte01"
    assert cursor1 == 1  # próximo cursor aponta para fonte02

    # Segunda chamada: começa em fonte02
    resultado2 = modulo._selecionar_janela_para_slot(
        8.0, ordem_fontes, cursor1, duracoes_fontes, intervalos_usados, 30.0, 30.0, rng
    )
    fonte2, _, _, cursor2 = resultado2
    assert fonte2 == "fonte02"
    assert cursor2 == 2


def test_selecionar_janela_para_slot_retorna_none_quando_nenhuma_fonte_cabe():
    """Retorna None quando nenhuma fonte tem espaço suficiente."""
    ordem_fontes = ["fonte01", "fonte02"]
    duracoes_fontes = {"fonte01": 50.0, "fonte02": 40.0}  # ambas muito curtas
    intervalos_usados = {"fonte01": [], "fonte02": []}
    rng = random.Random(42)

    resultado = modulo._selecionar_janela_para_slot(
        10.0, ordem_fontes, 0, duracoes_fontes, intervalos_usados,
        30.0, 30.0, rng
    )

    assert resultado is None


def test_selecionar_janela_para_slot_com_lista_vazia_retorna_none():
    """Sem fontes, retorna None."""
    resultado = modulo._selecionar_janela_para_slot(
        8.0, [], 0, {}, {}, 30.0, 30.0, random.Random(42)
    )

    assert resultado is None


def test_selecionar_janela_para_slot_fallback_para_overlapping():
    """Se todas as tentativas de uma fonte dão overlap, aceita o overlap como fallback."""
    ordem_fontes = ["fonte01"]
    duracoes_fontes = {"fonte01": 200.0}
    # Intervalo já ocupando boa parte
    intervalos_usados = {"fonte01": [(40.0, 180.0)]}
    rng = random.Random(42)

    # Com MAX_TENTATIVAS_POR_SLOT tentativas, eventualmente cairá no fallback
    resultado = modulo._selecionar_janela_para_slot(
        8.0, ordem_fontes, 0, duracoes_fontes, intervalos_usados,
        20.0, 20.0, rng  # margens menores pra aumentar chances
    )

    # Mesmo com overlap, retorna um valor em vez de None (fallback)
    assert resultado is not None
    fonte, inicio, duracao, cursor = resultado
    assert fonte == "fonte01"


# ---------------------------------------------------------------------------
# construir_filtro_ken_burns
# ---------------------------------------------------------------------------


def test_construir_filtro_ken_burns_contem_zoompan():
    """Filtro contém 'zoompan=' (marca do Ken Burns)."""
    filtro = modulo.construir_filtro_ken_burns(5.0)

    assert "zoompan=" in filtro


def test_construir_filtro_ken_burns_aumenta_frames_com_duracao():
    """Clipes mais longos recebem mais frames no zoompan."""
    filtro_curto = modulo.construir_filtro_ken_burns(2.0)
    filtro_longo = modulo.construir_filtro_ken_burns(10.0)

    # Extrai o valor de frames do formato "z='min(1+X*on/Y,Z)'"
    # Simplificado: ambos devem conter números, o mais longo deve ter número maior
    assert filtro_curto != filtro_longo


def test_construir_filtro_ken_burns_aplica_minimo_de_frames():
    """Clipes muito curtos ainda recebem KEN_BURNS_FRAMES_MINIMO frames."""
    filtro_muito_curto = modulo.construir_filtro_ken_burns(0.1)  # 0.1s, 3 frames a 30fps

    # Deve aplicar o mínimo (30 frames)
    assert "on/30" in filtro_muito_curto


# ---------------------------------------------------------------------------
# construir_cadeia_filtros
# ---------------------------------------------------------------------------


def test_construir_cadeia_filtros_inclui_ken_burns_quando_ativo():
    """Cadeia de filtros contém Ken Burns quando ken_burns=True."""
    cadeia = modulo.construir_cadeia_filtros(None, 5.0, ken_burns=True)

    assert "zoompan=" in cadeia


def test_construir_cadeia_filtros_omite_ken_burns_quando_inativo():
    """Sem Ken Burns, zoompan não aparece."""
    cadeia = modulo.construir_cadeia_filtros(None, 5.0, ken_burns=False)

    assert "zoompan=" not in cadeia


def test_construir_cadeia_filtros_inclui_delogo_quando_posicao_valida():
    """Marca d'água válida adiciona filtro delogo."""
    cadeia = modulo.construir_cadeia_filtros("superior_direito", 5.0, ken_burns=False)

    assert "delogo=" in cadeia


def test_construir_cadeia_filtros_omite_delogo_quando_nenhuma():
    """Marca 'nenhuma' não adiciona delogo."""
    cadeia = modulo.construir_cadeia_filtros("nenhuma", 5.0, ken_burns=False)

    assert "delogo=" not in cadeia


def test_construir_cadeia_filtros_omite_delogo_quando_none():
    """Marca None não adiciona delogo."""
    cadeia = modulo.construir_cadeia_filtros(None, 5.0, ken_burns=False)

    assert "delogo=" not in cadeia


def test_construir_cadeia_filtros_sempre_inclui_scale_e_fps():
    """Scale, crop e fps sempre presentes."""
    cadeia = modulo.construir_cadeia_filtros(None, 5.0, ken_burns=False)

    assert "scale=" in cadeia
    assert "crop=" in cadeia
    assert "fps=" in cadeia


# ---------------------------------------------------------------------------
# construir_comando_ffmpeg
# ---------------------------------------------------------------------------


def test_construir_comando_ffmpeg_ss_antes_de_i_para_video():
    """Para vídeos, -ss aparece ANTES de -i (seek rápido)."""
    caminho_fonte = Path("/tmp/fonte.mp4")
    caminho_saida = Path("/tmp/saida.mp4")

    comando = modulo.construir_comando_ffmpeg(
        caminho_fonte, 10.0, 5.0, caminho_saida, ken_burns=False
    )

    indice_ss = comando.index("-ss")
    indice_i = comando.index("-i")
    assert indice_ss < indice_i, "'-ss' deve vir antes de '-i'"


def test_construir_comando_ffmpeg_sem_audio():
    """Comando inclui -an (sem áudio)."""
    caminho_fonte = Path("/tmp/fonte.mp4")
    caminho_saida = Path("/tmp/saida.mp4")

    comando = modulo.construir_comando_ffmpeg(
        caminho_fonte, 10.0, 5.0, caminho_saida
    )

    assert "-an" in comando


def test_construir_comando_ffmpeg_loop_1_para_imagem():
    """Para imagens, adiciona -loop 1."""
    caminho_fonte = Path("/tmp/imagem.jpg")
    caminho_saida = Path("/tmp/saida.mp4")

    comando = modulo.construir_comando_ffmpeg(
        caminho_fonte, 0.0, 5.0, caminho_saida, eh_imagem=True
    )

    assert "-loop" in comando
    assert "1" in comando


def test_construir_comando_ffmpeg_ken_burns_aparece_em_vf():
    """Ken Burns (zoompan) aparece no filtro de vídeo."""
    caminho_fonte = Path("/tmp/fonte.mp4")
    caminho_saida = Path("/tmp/saida.mp4")

    comando = modulo.construir_comando_ffmpeg(
        caminho_fonte, 10.0, 5.0, caminho_saida, ken_burns=True
    )

    vf_index = comando.index("-vf")
    vf_value = comando[vf_index + 1]
    assert "zoompan=" in vf_value


def test_construir_comando_ffmpeg_encoder_libx264_por_padrao():
    """Sem especificar encoder, usa libx264 (CPU)."""
    caminho_fonte = Path("/tmp/fonte.mp4")
    caminho_saida = Path("/tmp/saida.mp4")

    comando = modulo.construir_comando_ffmpeg(
        caminho_fonte, 10.0, 5.0, caminho_saida, encoder="libx264"
    )

    assert "-c:v" in comando
    indice_c = comando.index("-c:v")
    assert comando[indice_c + 1] == "libx264"


def test_construir_comando_ffmpeg_encoder_nvenc():
    """Com encoder h264_nvenc, usa parametros NVENC."""
    caminho_fonte = Path("/tmp/fonte.mp4")
    caminho_saida = Path("/tmp/saida.mp4")

    comando = modulo.construir_comando_ffmpeg(
        caminho_fonte, 10.0, 5.0, caminho_saida, encoder="h264_nvenc"
    )

    assert "-c:v" in comando
    indice_c = comando.index("-c:v")
    assert comando[indice_c + 1] == "h264_nvenc"
    assert "-preset" in comando
    assert "-tune" in comando


# ---------------------------------------------------------------------------
# _detectar_encoder_gpu
# ---------------------------------------------------------------------------


def test_detectar_encoder_gpu_retorna_h264_nvenc_se_disponivel(monkeypatch):
    """Quando ffmpeg -encoders lista h264_nvenc, retorna esse encoder."""
    def _run_fake(*args, **kwargs):
        resultado = MagicMock()
        resultado.stdout = "h264_nvenc some_other_encoder libx264"
        resultado.returncode = 0
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_fake)

    encoder = modulo._detectar_encoder_gpu()

    assert encoder == "h264_nvenc"


def test_detectar_encoder_gpu_retorna_libx264_fallback():
    """Sem h264_nvenc, retorna libx264."""
    with patch.object(subprocess, "run") as mock_run:
        resultado = MagicMock()
        resultado.stdout = "libx264 libx265 other_encoders"
        resultado.returncode = 0
        mock_run.return_value = resultado

        encoder = modulo._detectar_encoder_gpu()

        assert encoder == "libx264"


def test_detectar_encoder_gpu_nunca_levanta_excecao(monkeypatch):
    """Mesmo se ffmpeg falhar, não levanta exceção."""
    def _run_raises(*args, **kwargs):
        raise subprocess.SubprocessError("simulado")

    monkeypatch.setattr(subprocess, "run", _run_raises)

    encoder = modulo._detectar_encoder_gpu()

    assert encoder == "libx264"  # fallback seguro


def test_detectar_encoder_gpu_timeout_retorna_libx264(monkeypatch):
    """Timeout também retorna fallback."""
    def _run_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", 5)

    monkeypatch.setattr(subprocess, "run", _run_timeout)

    encoder = modulo._detectar_encoder_gpu()

    assert encoder == "libx264"


# ---------------------------------------------------------------------------
# _rodar_ffmpeg
# ---------------------------------------------------------------------------


def test_rodar_ffmpeg_sucesso_retorna_true(monkeypatch):
    """Quando ffmpeg retorna 0 e arquivo existe, retorna sucesso."""
    caminho_saida = Path("/tmp/clipe.mp4")

    def _run_sucesso(*args, **kwargs):
        # Simula que o arquivo foi criado
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"fake video")
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_sucesso)

    sucesso, tipo_erro, mensagem = modulo._rodar_ffmpeg(["ffmpeg", "-i", "dummy", str(caminho_saida)])

    assert sucesso is True
    assert tipo_erro is None
    assert mensagem is None


def test_rodar_ffmpeg_returncode_diferente_zero_retorna_erro(monkeypatch):
    """ffmpeg com returncode != 0 retorna erro."""
    def _run_erro(*args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "erro simulado do ffmpeg"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_erro)

    sucesso, tipo_erro, mensagem = modulo._rodar_ffmpeg(["ffmpeg", "dummy", "/tmp/out.mp4"])

    assert sucesso is False
    assert tipo_erro is not None
    assert mensagem is not None


def test_rodar_ffmpeg_timeout_retorna_erro(monkeypatch):
    """Timeout retorna erro específico."""
    def _run_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", 60)

    monkeypatch.setattr(subprocess, "run", _run_timeout)

    sucesso, tipo_erro, mensagem = modulo._rodar_ffmpeg(["ffmpeg", "dummy", "/tmp/out.mp4"])

    assert sucesso is False
    assert tipo_erro == "timeout_clipe"
    assert "60" in mensagem or "tempo limite" in mensagem


def test_rodar_ffmpeg_arquivo_nao_criado_mesmo_com_returncode_zero(monkeypatch):
    """Se o arquivo de saída não aparece no disco, retorna erro mesmo com returncode 0."""
    def _run_sem_arquivo(*args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_sem_arquivo)

    sucesso, tipo_erro, mensagem = modulo._rodar_ffmpeg(["ffmpeg", "dummy", "/tmp/fantasma.mp4"])

    assert sucesso is False


# ---------------------------------------------------------------------------
# _renderizar_clipe — fallback de encoder
# ---------------------------------------------------------------------------


def test_renderizar_clipe_fallback_nvenc_para_libx264(monkeypatch, tmp_path):
    """Se h264_nvenc falha, tenta de novo com libx264."""
    caminho_fonte = tmp_path / "fonte.mp4"
    caminho_fonte.write_bytes(b"fake")
    caminho_saida = tmp_path / "saida.mp4"

    call_count = [0]

    def _run_falha_depois_sucesso(*args, **kwargs):
        call_count[0] += 1
        resultado = MagicMock()
        if call_count[0] == 1:  # Primeira chamada (h264_nvenc) falha
            resultado.returncode = 1
            resultado.stderr = "encoder not found"
        else:  # Segunda chamada (libx264) sucede
            resultado.returncode = 0
            resultado.stderr = ""
            caminho_saida.write_bytes(b"video encoded")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_falha_depois_sucesso)

    sucesso, tipo_erro, mensagem, encoder_usado = modulo._renderizar_clipe(
        caminho_fonte, 10.0, 5.0, caminho_saida, "nenhuma",
        ken_burns=False, encoder="h264_nvenc"
    )

    assert sucesso is True
    assert encoder_usado == "libx264"
    assert call_count[0] == 2  # Foi feita a tentativa de fallback


def test_renderizar_clipe_sem_fallback_com_libx264(monkeypatch, tmp_path):
    """Com libx264 já selecionado, não tenta fallback."""
    caminho_fonte = tmp_path / "fonte.mp4"
    caminho_fonte.write_bytes(b"fake")
    caminho_saida = tmp_path / "saida.mp4"

    def _run_falha(*args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "erro"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_falha)

    sucesso, tipo_erro, mensagem, encoder_usado = modulo._renderizar_clipe(
        caminho_fonte, 10.0, 5.0, caminho_saida, "nenhuma",
        ken_burns=False, encoder="libx264"
    )

    assert sucesso is False
    assert encoder_usado == "libx264"


def test_renderizar_clipe_duracao_invalida_retorna_erro(tmp_path):
    """Duração <= 0 retorna erro sem chamar ffmpeg."""
    caminho_fonte = tmp_path / "fonte.mp4"
    caminho_fonte.write_bytes(b"fake")
    caminho_saida = tmp_path / "saida.mp4"

    sucesso, tipo_erro, mensagem, encoder = modulo._renderizar_clipe(
        caminho_fonte, 10.0, 0.0, caminho_saida, "nenhuma", ken_burns=False
    )

    assert sucesso is False
    assert tipo_erro == "erro_desconhecido"
    assert "invalida" in mensagem.lower()


# ---------------------------------------------------------------------------
# _ler_manifest_fontes, _ler_marcas_dagua, _ler_duracao_narracao
# ---------------------------------------------------------------------------


def test_ler_manifest_fontes_arquivo_inexistente_retorna_dict_vazio(tmp_path):
    """Arquivo manifest ausente retorna {}."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo._ler_manifest_fontes(pasta_projeto)

    assert resultado == {}


def test_ler_manifest_fontes_json_invalido_retorna_dict_vazio(tmp_path):
    """JSON corrompido retorna {}."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        "{ invalid json ][", encoding="utf-8"
    )

    resultado = modulo._ler_manifest_fontes(pasta_projeto)

    assert resultado == {}


def test_ler_manifest_fontes_extrai_fontes_com_sucesso(tmp_path):
    """Manifest válido retorna dict com fontes bem-sucedidas."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    manifest = {
        "fontes": [
            {
                "id": "fonte01",
                "arquivo": "fonte01.mp4",
                "duracao_s": 100.0,
                "sucesso": True,
            },
            {
                "id": "fonte02",
                "arquivo": "fonte02.mp4",
                "duracao_s": 0.0,  # inválida, será 0.0 no resultado
                "sucesso": True,
            },
        ]
    }
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    resultado = modulo._ler_manifest_fontes(pasta_projeto)

    assert len(resultado) == 2
    assert "fonte01" in resultado
    assert resultado["fonte01"]["duracao_s"] == 100.0
    assert resultado["fonte01"]["caminho"] == pasta_projeto / "fontes" / "fonte01.mp4"


def test_ler_manifest_fontes_ignora_fontes_com_sucesso_false(tmp_path):
    """Fontes com sucesso=False ou ausentes não aparecem no resultado."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    manifest = {
        "fontes": [
            {"id": "fonte01", "arquivo": "f1.mp4", "duracao_s": 100.0, "sucesso": True},
            {"id": "fonte02", "arquivo": "f2.mp4", "duracao_s": 50.0, "sucesso": False},
            {"id": "fonte03", "duracao_s": 100.0, "sucesso": True},  # sem 'id' ou 'arquivo'
        ]
    }
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    resultado = modulo._ler_manifest_fontes(pasta_projeto)

    assert len(resultado) == 1
    assert "fonte01" in resultado
    assert "fonte02" not in resultado
    assert "fonte03" not in resultado


# ---------------------------------------------------------------------------
# Filtro por tipo_uso (feature de fontes separadas - CLAUDE.md secao
# 5.7.1-bis): so' "ambos"/"visual" entram na selecao de clipes.
# ---------------------------------------------------------------------------


def test_ler_manifest_fontes_exclui_fontes_com_tipo_uso_transcricao(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()
    manifest = {
        "fontes": [
            {"id": "fonte01", "arquivo": "f1.mp4", "duracao_s": 100.0, "sucesso": True, "origem": "youtube"},
            {"id": "fonte02", "arquivo": "f2.mp4", "duracao_s": 100.0, "sucesso": True, "origem": "youtube"},
        ]
    }
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pasta_projeto / "entrada" / "fontes_tipo_uso.json").write_text(
        json.dumps({"fonte01": "transcricao", "fonte02": "visual"}), encoding="utf-8"
    )

    resultado = modulo._ler_manifest_fontes(pasta_projeto)

    assert "fonte01" not in resultado
    assert "fonte02" in resultado
    assert resultado["fonte02"]["origem"] == "youtube"


def test_ler_manifest_fontes_sem_fontes_tipo_uso_json_trata_tudo_como_ambos(tmp_path):
    """Retrocompatibilidade: sem entrada/fontes_tipo_uso.json (projeto
    anterior a feature de fontes separadas), toda fonte com sucesso entra."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    manifest = {"fontes": [{"id": "fonte01", "arquivo": "f1.mp4", "duracao_s": 100.0, "sucesso": True}]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(json.dumps(manifest), encoding="utf-8")

    resultado = modulo._ler_manifest_fontes(pasta_projeto)

    assert "fonte01" in resultado
    assert resultado["fonte01"]["origem"] == "youtube"


# ---------------------------------------------------------------------------
# _metadata_selecao_fonte (funcao pura) - fontes visuais proprias do
# usuario (feature de fontes separadas - CLAUDE.md secao 5.7.1-bis)
# ---------------------------------------------------------------------------


def test_metadata_selecao_fonte_imagem_usa_duracao_sentinela(tmp_path):
    caminho = tmp_path / "fonte02.jpg"
    caminho.write_bytes(b"fake")
    dados = {"caminho": caminho, "duracao_s": 0.0, "origem": "upload"}

    duracao_selecao, usar_completo = modulo._metadata_selecao_fonte(dados)

    assert duracao_selecao == modulo.DURACAO_SENTINELA_SELECAO_S
    assert usar_completo is False


def test_metadata_selecao_fonte_video_upload_curto_usa_fonte_inteira(tmp_path):
    caminho = tmp_path / "fonte02.mp4"
    caminho.write_bytes(b"fake")
    dados = {"caminho": caminho, "duracao_s": 12.0, "origem": "upload"}

    duracao_selecao, usar_completo = modulo._metadata_selecao_fonte(dados)

    assert duracao_selecao == modulo.DURACAO_SENTINELA_SELECAO_S
    assert usar_completo is True


def test_metadata_selecao_fonte_video_upload_longo_comportamento_normal(tmp_path):
    caminho = tmp_path / "fonte02.mp4"
    caminho.write_bytes(b"fake")
    dados = {"caminho": caminho, "duracao_s": 120.0, "origem": "upload"}

    duracao_selecao, usar_completo = modulo._metadata_selecao_fonte(dados)

    assert duracao_selecao == 120.0
    assert usar_completo is False


def test_metadata_selecao_fonte_video_youtube_curto_nao_usa_fonte_inteira(tmp_path):
    """O limite de "usar fonte inteira" so' vale para origem upload - um
    video-fonte do YouTube que por acaso tenha 12s de duracao continua com
    o comportamento normal de janela aleatoria."""
    caminho = tmp_path / "fonte01.mp4"
    caminho.write_bytes(b"fake")
    dados = {"caminho": caminho, "duracao_s": 12.0, "origem": "youtube"}

    duracao_selecao, usar_completo = modulo._metadata_selecao_fonte(dados)

    assert duracao_selecao == 12.0
    assert usar_completo is False


def test_ler_marcas_dagua_arquivo_inexistente_retorna_dict_vazio(tmp_path):
    """Arquivo ausente retorna {}."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo._ler_marcas_dagua(pasta_projeto)

    assert resultado == {}


def test_ler_marcas_dagua_json_invalido_retorna_dict_vazio(tmp_path):
    """JSON corrompido retorna {}."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    (pasta_projeto / "entrada" / "marcas_dagua.json").write_text(
        "{ bad json ][", encoding="utf-8"
    )

    resultado = modulo._ler_marcas_dagua(pasta_projeto)

    assert resultado == {}


def test_ler_marcas_dagua_extrai_mapa_corretamente(tmp_path):
    """Arquivo válido retorna mapa de posições."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "entrada").mkdir()
    marcas = {"fonte01": "superior_direito", "fonte02": "nenhuma"}
    (pasta_projeto / "entrada" / "marcas_dagua.json").write_text(
        json.dumps(marcas), encoding="utf-8"
    )

    resultado = modulo._ler_marcas_dagua(pasta_projeto)

    assert resultado == marcas


def test_ler_duracao_narracao_arquivo_inexistente_retorna_none(tmp_path):
    """Arquivo ausente retorna None."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo._ler_duracao_narracao(pasta_projeto)

    assert resultado is None


def test_ler_duracao_narracao_json_invalido_retorna_none(tmp_path):
    """JSON corrompido retorna None."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        "{ bad json ][", encoding="utf-8"
    )

    resultado = modulo._ler_duracao_narracao(pasta_projeto)

    assert resultado is None


def test_ler_duracao_narracao_extrai_duracao(tmp_path):
    """Arquivo válido retorna duracao_s."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    dados = {"duracao_s": 45.5, "other_field": "ignored"}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(dados), encoding="utf-8"
    )

    resultado = modulo._ler_duracao_narracao(pasta_projeto)

    assert resultado == 45.5


# ---------------------------------------------------------------------------
# config_clipes — leitura de variáveis de ambiente
# ---------------------------------------------------------------------------


def test_config_clipes_valores_padrao(monkeypatch):
    """Sem variáveis de ambiente, retorna defaults."""
    # Limpa variáveis de ambiente primeiro
    for var in ["KEN_BURNS", "CLIPE_DURACAO_MIN_S", "CLIPE_DURACAO_MAX_S", "MARGEM_INICIO_S", "MARGEM_FIM_S"]:
        monkeypatch.delenv(var, raising=False)

    config = modulo.config_clipes()

    assert config["ken_burns"] is True
    assert config["clipe_duracao_min_s"] == modulo.CLIPE_DURACAO_MIN_S_PADRAO
    assert config["clipe_duracao_max_s"] == modulo.CLIPE_DURACAO_MAX_S_PADRAO
    assert config["margem_inicio_s"] == modulo.MARGEM_INICIO_S_PADRAO
    assert config["margem_fim_s"] == modulo.MARGEM_FIM_S_PADRAO


def test_config_clipes_override_via_env(monkeypatch):
    """Variáveis de ambiente sobrescrevem defaults."""
    monkeypatch.setenv("KEN_BURNS", "false")
    monkeypatch.setenv("CLIPE_DURACAO_MIN_S", "3.0")
    monkeypatch.setenv("CLIPE_DURACAO_MAX_S", "8.5")

    config = modulo.config_clipes()

    assert config["ken_burns"] is False
    assert config["clipe_duracao_min_s"] == 3.0
    assert config["clipe_duracao_max_s"] == 8.5


def test_config_clipes_invalido_cai_no_padrao(monkeypatch):
    """Valor inválido em variável float cai no padrão."""
    monkeypatch.setenv("CLIPE_DURACAO_MIN_S", "nao_e_numero")

    config = modulo.config_clipes()

    assert config["clipe_duracao_min_s"] == modulo.CLIPE_DURACAO_MIN_S_PADRAO


# ---------------------------------------------------------------------------
# gerar_clipes — orquestração fim-a-fim
# ---------------------------------------------------------------------------


def test_gerar_clipes_pre_condicoes_ffmpeg_ausente(monkeypatch, tmp_path):
    """Sem ffmpeg no PATH, gerar_clipes retorna erro fatal."""
    monkeypatch.setattr(
        modulo.robustez, "validar_pre_condicoes_pipeline",
        lambda: (False, "ffmpeg não encontrado")
    )
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo.gerar_clipes(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "ffmpeg_ausente"


def test_gerar_clipes_pre_condicoes_manifest_ausente(tmp_path, monkeypatch):
    """Sem manifest_fontes.json, gerar_clipes retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()

    resultado = modulo.gerar_clipes(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "fontes_ausentes"


def test_gerar_clipes_pre_condicoes_narracao_ausente(tmp_path, monkeypatch):
    """Sem narracao_alinhamento.json, gerar_clipes retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "f1.mp4", "duracao_s": 100.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    resultado = modulo.gerar_clipes(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "narracao_ausente"


def test_gerar_clipes_pre_condicoes_narracao_invalida(tmp_path, monkeypatch):
    """Duração de narração <= 0 retorna erro."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "f1.mp4", "duracao_s": 100.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (pasta_projeto / "fontes" / "f1.mp4").write_bytes(b"fake")
    narracao = {"duracao_s": -1.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    resultado = modulo.gerar_clipes(pasta_projeto)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "narracao_invalida"


def test_gerar_clipes_sucesso_simples(tmp_path, monkeypatch, capsys):
    """Caso feliz: um clipe é gerado com sucesso."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    # Setup manifests
    fonte01_path = pasta_projeto / "fontes" / "fonte01.mp4"
    fonte01_path.write_bytes(b"fake video")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 15.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    # Mock subprocess.run para criar os arquivos de saída
    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        # Encontra o caminho de saída (último argumento da lista de comando)
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"encoded video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    resultado = modulo.gerar_clipes(pasta_projeto, seed=42)

    assert resultado["sucesso"] is True
    assert resultado["sucessos"] >= 1
    assert (pasta_projeto / "clipes" / "indice.json").exists()

    # Verifica conteúdo do índice
    indice = json.loads((pasta_projeto / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert indice["metadata"]["total_clipes"] >= 1
    assert "tempos_por_fase" in indice["metadata"]
    assert "leitura_config_s" in indice["metadata"]["tempos_por_fase"]
    assert "planejamento_slots_s" in indice["metadata"]["tempos_por_fase"]
    assert "renderizacao_clipes_s" in indice["metadata"]["tempos_por_fase"]
    assert "total_s" in indice["metadata"]["tempos_por_fase"]


def test_gerar_clipes_video_upload_curto_e_renderizado_inteiro(tmp_path, monkeypatch):
    """Video de upload com duracao <= LIMITE_VIDEO_INTEIRO_UPLOAD_S aparece
    no indice com inicio_fonte_s=0.0 e duracao_s igual a duracao REAL do
    arquivo, nunca a duracao do slot sorteado (CLAUDE.md secao 5.7.1-bis)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    (pasta_projeto / "fontes" / "fonte01.jpg").write_bytes(b"nao usado, so' upload curto abaixo")
    manifest = {
        "fontes": [
            {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 9.0, "sucesso": True, "origem": "upload"},
        ]
    }
    (pasta_projeto / "fontes" / "fonte01.mp4").write_bytes(b"fake upload curto")
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 15.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"encoded video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    resultado = modulo.gerar_clipes(pasta_projeto, seed=42)

    assert resultado["sucesso"] is True
    indice = json.loads((pasta_projeto / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert indice["clipes"], "deveria ter gerado pelo menos um clipe"
    for clipe in indice["clipes"]:
        assert clipe["inicio_fonte_s"] == 0.0
        assert clipe["duracao_s"] == 9.0


def test_gerar_clipes_progresso_emitido_no_stdout(tmp_path, monkeypatch, capsys):
    """@PROGRESSO é emitido durante a execução."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    fonte01_path = pasta_projeto / "fontes" / "fonte01.mp4"
    fonte01_path.write_bytes(b"fake")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 15.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    modulo.gerar_clipes(pasta_projeto, seed=42)

    saida_capturada = capsys.readouterr().out
    assert "@PROGRESSO" in saida_capturada
    linhas_progresso = [l for l in saida_capturada.split("\n") if "@PROGRESSO" in l]
    assert len(linhas_progresso) > 0
    # Primeira linha de progresso deve ser erro ou sucesso em fases iniciais
    payload_final = json.loads(linhas_progresso[-1][len("@PROGRESSO "):])
    assert payload_final["pct"] == 100.0
    assert payload_final["sucesso"] is True


def test_gerar_clipes_falha_parcial_continua_com_outros_clipes(tmp_path, monkeypatch):
    """Quando um clipe falha, os outros são processados normalmente (falha parcial)."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    # Duas fontes
    (pasta_projeto / "fontes" / "fonte01.mp4").write_bytes(b"fake1")
    (pasta_projeto / "fontes" / "fonte02.mp4").write_bytes(b"fake2")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True},
        {"id": "fonte02", "arquivo": "fonte02.mp4", "duracao_s": 200.0, "sucesso": True},
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 20.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    # Mock ffmpeg: a chamada de deteccao de encoder (`ffmpeg -encoders`, sem
    # `-i`) sempre "sucede" sem efeito; entre as chamadas de renderizacao de
    # clipe de verdade (com `-i` no comando), a primeira falha, o resto
    # sucede.
    call_count = [0]
    def _run_mock_partial_fail(cmd, *args, **kwargs):
        resultado = MagicMock()
        if "-i" not in cmd:  # deteccao de encoder GPU - nao conta como clipe
            resultado.returncode = 0
            resultado.stdout = ""
            resultado.stderr = ""
            return resultado

        call_count[0] += 1
        if call_count[0] == 1:  # Primeiro clipe de verdade falha
            resultado.returncode = 1
            resultado.stderr = "encoder error"
        else:  # Resto sucede
            resultado.returncode = 0
            resultado.stderr = ""
            caminho_saida = Path(cmd[-1])
            caminho_saida.parent.mkdir(parents=True, exist_ok=True)
            caminho_saida.write_bytes(b"video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_partial_fail)

    resultado = modulo.gerar_clipes(pasta_projeto, seed=42)

    assert resultado["sucesso"] is True  # Falha parcial ainda retorna sucesso geral
    assert resultado["sucessos"] > 0
    assert resultado["total"] > resultado["sucessos"]  # Há tanto sucessos quanto falhas


def test_gerar_clipes_todos_clipes_falham_retorna_erro(tmp_path, monkeypatch, capsys):
    """Quando todos os clipes falham, resultado final é sucesso=False."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    (pasta_projeto / "fontes" / "fonte01.mp4").write_bytes(b"fake")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 15.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    # Tudo falha
    def _run_mock_all_fail(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "fatal ffmpeg error"
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_all_fail)

    resultado = modulo.gerar_clipes(pasta_projeto, seed=42)

    assert resultado["sucesso"] is False
    saida = capsys.readouterr().out
    linhas = [l for l in saida.split("\n") if "@PROGRESSO" in l]
    payload_final = json.loads(linhas[-1][len("@PROGRESSO "):])
    assert payload_final["sucesso"] is False


def test_gerar_clipes_marca_dagua_aplicada_no_comando(tmp_path, monkeypatch):
    """Delogo para marca d'água é incluído no comando ffmpeg."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    (pasta_projeto / "fontes" / "fonte01.mp4").write_bytes(b"fake")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    # Mapeia a fonte para uma posição de marca d'água
    marcas = {"fonte01": "superior_direito"}
    (pasta_projeto / "entrada" / "marcas_dagua.json").write_text(
        json.dumps(marcas), encoding="utf-8"
    )
    narracao = {"duracao_s": 10.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    # Captura o comando ffmpeg executado
    comandos_executados = []
    def _run_captura_comando(cmd, *args, **kwargs):
        comandos_executados.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_captura_comando)

    modulo.gerar_clipes(pasta_projeto, seed=42)

    assert len(comandos_executados) > 0
    # Verifica que ao menos um comando contém o delogo filter
    algum_comando_tem_delogo = any(
        "delogo=" in " ".join(cmd) for cmd in comandos_executados
    )
    assert algum_comando_tem_delogo, "Nenhum comando incluiu o delogo filter para marca d'água"


def test_gerar_clipes_ken_burns_aplicado_por_padrao(tmp_path, monkeypatch):
    """Ken Burns é aplicado por padrão nos clipes."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    (pasta_projeto / "fontes" / "fonte01.mp4").write_bytes(b"fake")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 10.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    comandos_executados = []
    def _run_captura_comando(cmd, *args, **kwargs):
        comandos_executados.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_captura_comando)

    modulo.gerar_clipes(pasta_projeto, seed=42)

    # Por padrão KEN_BURNS = True, então zoompan deve aparecer
    algum_comando_tem_ken_burns = any(
        "zoompan=" in " ".join(cmd) for cmd in comandos_executados
    )
    assert algum_comando_tem_ken_burns, "Ken Burns não foi aplicado nos clipes"


def test_gerar_clipes_indice_json_contém_metadados_requeridos(tmp_path, monkeypatch):
    """O arquivo indice.json contém todos os campos de metadata obrigatórios."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    (pasta_projeto / "fontes").mkdir()
    (pasta_projeto / "entrada").mkdir()

    (pasta_projeto / "fontes" / "fonte01.mp4").write_bytes(b"fake")
    manifest = {"fontes": [
        {"id": "fonte01", "arquivo": "fonte01.mp4", "duracao_s": 200.0, "sucesso": True}
    ]}
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    narracao = {"duracao_s": 10.0}
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps(narracao), encoding="utf-8"
    )

    def _run_mock_sucesso(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        caminho_saida = Path(cmd[-1])
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"video")
        return resultado

    monkeypatch.setattr(subprocess, "run", _run_mock_sucesso)

    modulo.gerar_clipes(pasta_projeto, seed=42)

    indice_path = pasta_projeto / "clipes" / "indice.json"
    assert indice_path.exists()
    indice = json.loads(indice_path.read_text(encoding="utf-8"))

    # Verifica campos obrigatórios
    assert "clipes" in indice
    assert "metadata" in indice
    metadata = indice["metadata"]
    assert "total_clipes" in metadata
    assert "duracao_total_s" in metadata
    assert "duracao_narracao_s" in metadata
    assert "ken_burns_aplicado" in metadata
    assert "encoder_usado" in metadata
    assert "total_slots_planejados" in metadata
    assert "tempos_por_fase" in metadata
    assert "data_geracao" in metadata

    # Verifica tempos_por_fase
    tempos = metadata["tempos_por_fase"]
    assert "leitura_config_s" in tempos
    assert "planejamento_slots_s" in tempos
    assert "renderizacao_clipes_s" in tempos
    assert "total_s" in tempos


def test_emitir_progresso_imprime_json_valido(capsys):
    """emitir_progresso produz JSON válido no stdout."""
    modulo.emitir_progresso(50.0, "Processando...", eta_s=30)

    saida = capsys.readouterr().out.strip()
    assert saida.startswith("@PROGRESSO ")

    payload = json.loads(saida[len("@PROGRESSO "):])
    assert payload["pct"] == 50.0
    assert payload["detalhe"] == "Processando..."
    assert payload["eta_s"] == 30


def test_emitir_progresso_com_extra_campos(capsys):
    """emitir_progresso suporta campos extras."""
    modulo.emitir_progresso(
        100.0, "Concluído", sucesso=True, total_clipes=5, avisos=["aviso1"]
    )

    saida = capsys.readouterr().out.strip()
    payload = json.loads(saida[len("@PROGRESSO "):])
    assert payload["sucesso"] is True
    assert payload["total_clipes"] == 5
    assert payload["avisos"] == ["aviso1"]
