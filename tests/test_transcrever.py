"""Testes da Etapa 2 do pipeline (scripts/2_transcrever.py) - transcricao
via faster-whisper (CLAUDE.md secao 5.2).

Nunca chama faster-whisper real nem nvidia-smi real (CLAUDE.md secao 8): o
`WhisperModel` e' sempre um fake monkeypatchado, e `ambiente.detectar_gpu`
e' sempre mockado para simular um ambiente compativel por padrao.

O nome do arquivo do script comeca com digito ("2_transcrever.py"), entao
nao pode ser importado com `import` normal - carregado via
importlib.util.spec_from_file_location, igual test_baixar_videos.py faz
para 1_baixar_videos.py.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "2_transcrever.py"

_spec = importlib.util.spec_from_file_location("transcrever_etapa2", CAMINHO_SCRIPT)
modulo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = modulo
_spec.loader.exec_module(modulo)


GPU_COMPATIVEL = {
    "presente": True,
    "modelo": "NVIDIA GeForce RTX 3070 Ti",
    "vram_mb": 8192,
    "driver_version": "560.94",
    "compute_capability": "8.6",
    "cuda_umd_version": "12.6",
    "erro": None,
}


@pytest.fixture(autouse=True)
def _ambiente_padrao(monkeypatch):
    """Isola os testes deste arquivo de hardware/rede reais: por padrao,
    ffmpeg disponivel e GPU compativel. Os testes que exercitam
    especificamente esses cenarios de falha sobrescrevem explicitamente."""
    monkeypatch.setattr(modulo.robustez, "ffmpeg_disponivel", lambda: True)
    monkeypatch.setattr(modulo.ambiente, "detectar_gpu", lambda: dict(GPU_COMPATIVEL))


def _criar_manifest(pasta_projeto: Path, fontes):
    pasta_fontes = pasta_projeto / "fontes"
    pasta_fontes.mkdir(parents=True, exist_ok=True)
    (pasta_fontes / "manifest_fontes.json").write_text(
        json.dumps({"fontes": fontes, "sucesso": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    return pasta_fontes


def _criar_arquivo_fonte(pasta_fontes: Path, nome):
    (pasta_fontes / nome).write_bytes(b"conteudo fake de video")


class _PalavraFake:
    def __init__(self, start, end, word):
        self.start = start
        self.end = end
        self.word = word


class _SegmentoFake:
    def __init__(self, start, end, text, words=None):
        self.start = start
        self.end = end
        self.text = text
        self.words = words or []


class _InfoFake:
    def __init__(self, duration=10.0, language="en"):
        self.duration = duration
        self.language = language


class _ModelFake:
    """Substitui faster_whisper.WhisperModel nos testes. `respostas_por_arquivo`
    mapeia nome do arquivo -> (segmentos, info) ou -> excecao a levantar."""

    def __init__(self, respostas_por_arquivo=None, erro_construtor=None):
        self._respostas = respostas_por_arquivo or {}
        self._erro_construtor = erro_construtor
        if erro_construtor:
            raise erro_construtor

    def transcribe(self, caminho, word_timestamps=True):
        nome_arquivo = Path(caminho).name
        resposta = self._respostas.get(nome_arquivo)
        if isinstance(resposta, Exception):
            raise resposta
        segmentos, info = resposta
        return iter(segmentos), info


def _fake_ffprobe_sempre_ok(comando, **kwargs):
    class _Resultado:
        stdout = "10.5\n"
        stderr = ""
        returncode = 0

    return _Resultado()


# ---------------------------------------------------------------------------
# classificar_erro_transcricao
# ---------------------------------------------------------------------------


def test_classificar_erro_vram_insuficiente():
    categoria, mensagem = modulo.classificar_erro_transcricao(
        "RuntimeError: CUDA failed with error out of memory", modelo="large-v3"
    )

    assert categoria == "vram_insuficiente"
    assert "large-v3" in mensagem
    assert "modelo menor" in mensagem


def test_classificar_erro_gpu_indisponivel():
    categoria, mensagem = modulo.classificar_erro_transcricao(
        "RuntimeError: CUDA driver version is insufficient for CUDA runtime version"
    )

    assert categoria == "gpu_indisponivel"
    assert "drivers" in mensagem.lower()


def test_classificar_erro_gpu_indisponivel_dll_cuda_ausente():
    """Achado real (Sessao 4, RTX 3070 Ti): bibliotecas de runtime CUDA
    (cuBLAS) ausentes/nao carregaveis - mensagem exata do ctranslate2."""
    categoria, mensagem = modulo.classificar_erro_transcricao(
        "RuntimeError: Library cublas64_12.dll is not found or cannot be loaded"
    )

    assert categoria == "gpu_indisponivel"


def test_classificar_erro_modelo_nao_encontrado():
    categoria, mensagem = modulo.classificar_erro_transcricao(
        "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='huggingface.co', "
        "port=443): Max retries exceeded"
    )

    assert categoria == "modelo_nao_encontrado"
    assert "internet" in mensagem.lower()


def test_classificar_erro_arquivo_corrompido():
    categoria, mensagem = modulo.classificar_erro_transcricao(
        "moov atom not found", arquivo="fonte03.mp4"
    )

    assert categoria == "arquivo_corrompido"
    assert "fonte03.mp4" in mensagem


def test_classificar_erro_timeout():
    categoria, mensagem = modulo.classificar_erro_transcricao(
        "Transcricao excedeu o tempo limite de 3600s (timeout)."
    )

    assert categoria == "timeout"
    assert "60min" in mensagem


def test_classificar_erro_desconhecido_cai_no_fallback():
    categoria, mensagem = modulo.classificar_erro_transcricao("algo totalmente inesperado")

    assert categoria == "erro_desconhecido"
    assert "algo totalmente inesperado" in mensagem


def test_classificar_erro_vazio_cai_no_fallback():
    categoria, mensagem = modulo.classificar_erro_transcricao("")

    assert categoria == "erro_desconhecido"


# ---------------------------------------------------------------------------
# _validar_pre_condicoes
# ---------------------------------------------------------------------------


def test_pre_condicoes_falha_sem_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo.robustez, "ffmpeg_disponivel", lambda: False)

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(tmp_path)

    assert ok is False
    assert "ffmpeg" in mensagem


def test_pre_condicoes_falha_sem_manifest(tmp_path):
    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(tmp_path)

    assert ok is False
    assert "manifest_fontes.json" in mensagem


def test_pre_condicoes_falha_com_manifest_sem_fontes_ok(tmp_path):
    _criar_manifest(tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": False}])

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(tmp_path)

    assert ok is False
    assert "Etapa 1" in mensagem


def test_pre_condicoes_falha_com_ambiente_incompativel(tmp_path, monkeypatch):
    _criar_manifest(tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}])
    monkeypatch.setattr(
        modulo.ambiente,
        "detectar_gpu",
        lambda: {
            "presente": False,
            "modelo": None,
            "vram_mb": None,
            "driver_version": None,
            "compute_capability": None,
            "cuda_umd_version": None,
            "erro": "nvidia-smi nao encontrado. Driver NVIDIA nao instalado.",
        },
    )

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(tmp_path)

    assert ok is False
    assert tipo_erro == "gpu_indisponivel"


def test_pre_condicoes_ok(tmp_path):
    _criar_manifest(tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}])

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(tmp_path)

    assert ok is True
    assert mensagem is None
    assert tipo_erro is None


# ---------------------------------------------------------------------------
# transcrever_todos - pre-condicoes propagadas como @PROGRESSO
# ---------------------------------------------------------------------------


def test_transcrever_todos_sem_manifest_emite_progresso_de_erro(tmp_path, capsys):
    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    saida = capsys.readouterr().out
    assert "@PROGRESSO" in saida
    assert '"sucesso": false' in saida


def test_transcrever_todos_ambiente_incompativel_nao_carrega_modelo(tmp_path, monkeypatch):
    _criar_manifest(tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}])
    monkeypatch.setattr(
        modulo.ambiente,
        "detectar_gpu",
        lambda: {"presente": False, "modelo": None, "vram_mb": None, "driver_version": None,
                 "compute_capability": None, "cuda_umd_version": None, "erro": "sem gpu"},
    )

    def _model_nao_deveria_ser_chamado(*args, **kwargs):
        pytest.fail("WhisperModel nao deveria ser instanciado com ambiente incompativel")

    monkeypatch.setattr(modulo, "WhisperModel", _model_nao_deveria_ser_chamado)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    assert resultado["transcricoes"] == []


def test_transcrever_todos_sem_faster_whisper_instalado(tmp_path, monkeypatch):
    _criar_manifest(tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}])
    monkeypatch.setattr(modulo, "WhisperModel", None)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    assert "erro_fatal" in resultado


# ---------------------------------------------------------------------------
# transcrever_todos - caminho feliz: schema do JSON de saida
# ---------------------------------------------------------------------------


def test_transcrever_todos_caminho_feliz_gera_json_no_schema_esperado(tmp_path, monkeypatch):
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    segmentos = [
        _SegmentoFake(
            0.0, 4.2, "Tonight we're going to talk about...",
            words=[_PalavraFake(0.0, 0.3, "Tonight")],
        ),
        _SegmentoFake(4.2, 8.0, "a case that shocked the nation."),
    ]
    info = _InfoFake(duration=1247.3, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is True
    assert resultado["sucessos"] == 1

    caminho_saida = tmp_path / "transcricoes" / "fonte01.json"
    assert caminho_saida.exists()
    dados = json.loads(caminho_saida.read_text(encoding="utf-8"))

    assert dados["arquivo"] == "fonte01.mp4"
    assert dados["duracao_s"] == 1247.3
    assert dados["idioma"] == "en"
    assert len(dados["segmentos"]) == 2
    assert dados["segmentos"][0]["start"] == 0.0
    assert dados["segmentos"][0]["end"] == 4.2
    assert dados["segmentos"][0]["text"] == "Tonight we're going to talk about..."
    assert dados["segmentos"][0]["palavras"] == [{"start": 0.0, "end": 0.3, "word": "Tonight"}]
    assert dados["segmentos"][1]["palavras"] == []


# ---------------------------------------------------------------------------
# Filtro por tipo_uso/origem (feature de fontes separadas - CLAUDE.md secao
# 5.7.1-bis): so' fontes "ambos"/"transcricao" com origem "youtube" sao
# transcritas.
# ---------------------------------------------------------------------------


def test_transcrever_todos_pula_fontes_com_tipo_uso_visual(tmp_path, monkeypatch):
    pasta_fontes = _criar_manifest(
        tmp_path,
        [
            {"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True, "origem": "youtube"},
            {"id": "fonte02", "arquivo": "fonte02.mp4", "sucesso": True, "origem": "youtube"},
        ],
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    _criar_arquivo_fonte(pasta_fontes, "fonte02.mp4")
    (tmp_path / "entrada").mkdir(parents=True, exist_ok=True)
    (tmp_path / "entrada" / "fontes_tipo_uso.json").write_text(
        json.dumps({"fonte01": "ambos", "fonte02": "visual"}), encoding="utf-8"
    )
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    segmentos = [_SegmentoFake(0.0, 4.2, "trecho")]
    info = _InfoFake(duration=8.0, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is True
    assert resultado["sucessos"] == 1
    assert (tmp_path / "transcricoes" / "fonte01.json").exists()
    assert not (tmp_path / "transcricoes" / "fonte02.json").exists()


def test_transcrever_todos_nunca_transcreve_fonte_de_upload_mesmo_com_tipo_uso_ambos(
    tmp_path, monkeypatch
):
    """origem "upload" e' sempre excluida da transcricao, independente do
    tipo_uso - garantia de verdade contra manipulacao/estado inconsistente
    de entrada/fontes_tipo_uso.json (a UI nunca oferece "transcricao"/"ambos"
    para uma fonte de upload, mas o codigo nao confia so nisso)."""
    pasta_fontes = _criar_manifest(
        tmp_path,
        [{"id": "fonte02", "arquivo": "fonte02.mp4", "sucesso": True, "origem": "upload"}],
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte02.mp4")
    (tmp_path / "entrada").mkdir(parents=True, exist_ok=True)
    (tmp_path / "entrada" / "fontes_tipo_uso.json").write_text(
        json.dumps({"fonte02": "ambos"}), encoding="utf-8"
    )
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: pytest.fail("nao deveria transcrever upload"))

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    assert "erro_fatal" in resultado


def test_transcrever_todos_sem_fontes_tipo_uso_json_trata_tudo_como_ambos(tmp_path, monkeypatch):
    """Retrocompatibilidade: projeto sem a feature de fontes separadas (sem
    entrada/fontes_tipo_uso.json) transcreve normalmente, como antes."""
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    segmentos = [_SegmentoFake(0.0, 4.2, "trecho")]
    info = _InfoFake(duration=8.0, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is True
    assert resultado["sucessos"] == 1


def test_transcrever_todos_emite_progresso_por_segmento(tmp_path, monkeypatch, capsys):
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    segmentos = [_SegmentoFake(0.0, 4.2, "trecho 1"), _SegmentoFake(4.2, 8.0, "trecho 2")]
    info = _InfoFake(duration=8.0, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    modulo.transcrever_todos(tmp_path)

    linhas_progresso = [
        linha for linha in capsys.readouterr().out.splitlines() if linha.startswith("@PROGRESSO")
    ]
    assert len(linhas_progresso) >= 2
    assert any("Transcrevendo 1/1" in linha for linha in linhas_progresso)


def _payloads_progresso(saida_capturada):
    return [
        json.loads(linha[len("@PROGRESSO "):])
        for linha in saida_capturada.splitlines()
        if linha.startswith("@PROGRESSO")
    ]


def test_transcricao_progresso_pct_baseado_em_audio_processado(tmp_path, monkeypatch, capsys):
    """pct de cada linha de progresso reflete fracao de audio ja coberta
    (seg.end / duracao), nao tempo de execucao - matematica inalterada pela
    correcao da mensagem de ETA (so' o texto exibido mudou)."""
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    segmentos = [_SegmentoFake(0.0, 4.0, "trecho 1"), _SegmentoFake(4.0, 8.0, "trecho 2")]
    info = _InfoFake(duration=8.0, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    modulo.transcrever_todos(tmp_path)

    payloads = _payloads_progresso(capsys.readouterr().out)
    payloads_transcrevendo = [p for p in payloads if p["detalhe"].startswith("Transcrevendo")]
    assert payloads_transcrevendo[0]["pct"] == pytest.approx(50.0)
    assert payloads_transcrevendo[1]["pct"] == pytest.approx(100.0)


def test_transcricao_calcula_tempo_restante_baseado_em_velocidade(tmp_path, monkeypatch, capsys):
    """A mensagem de progresso projeta o tempo restante pela velocidade
    REAL medida (segundos de audio cobertos / tempo de execucao decorrido),
    nao pela posicao crua no audio - achado real de teste de ponta a ponta
    (CLAUDE.md secao 5.2): a mensagem antiga ("612.3s/1247.3s") era lida
    como se a transcricao levasse tanto tempo quanto o audio, quando
    faster-whisper em GPU roda bem mais rapido que 1:1."""
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    # 3 chamadas a time.monotonic(): 1 para marcar o inicio do arquivo, 1
    # por segmento processado. Velocidade apos o 1o segmento: 4.0s de audio
    # em 5.0s decorridos = 0.8x - restam 4.0s de audio -> ~5s restantes.
    tempos = [1_000.0, 1_005.0, 1_015.0]
    monkeypatch.setattr(modulo.time, "monotonic", lambda: tempos.pop(0))

    segmentos = [_SegmentoFake(0.0, 4.0, "trecho 1"), _SegmentoFake(4.0, 8.0, "trecho 2")]
    info = _InfoFake(duration=8.0, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    modulo.transcrever_todos(tmp_path)

    payloads = _payloads_progresso(capsys.readouterr().out)
    mensagens = [p["detalhe"] for p in payloads if p["detalhe"].startswith("Transcrevendo")]
    assert "restantes" in mensagens[0]
    assert "s/" not in mensagens[0]  # formato cru "X.Xs/Y.Ys" nao existe mais


# ---------------------------------------------------------------------------
# _formatar_duracao_amigavel
# ---------------------------------------------------------------------------


def test_formatar_duracao_amigavel_menor_que_60s():
    assert modulo._formatar_duracao_amigavel(45) == "45s"


def test_formatar_duracao_amigavel_exato_60s():
    assert modulo._formatar_duracao_amigavel(60) == "1min"


def test_formatar_duracao_amigavel_com_segundos():
    assert modulo._formatar_duracao_amigavel(323) == "5min 23s"


def test_formatar_duracao_amigavel_sem_segundos():
    assert modulo._formatar_duracao_amigavel(300) == "5min"


def test_transcrever_todos_final_com_sucesso_marca_sucesso_true(tmp_path, monkeypatch, capsys):
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    segmentos = [_SegmentoFake(0.0, 4.2, "trecho 1")]
    info = _InfoFake(duration=4.2, language="en")
    model_fake = _ModelFake({"fonte01.mp4": (segmentos, info)})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    modulo.transcrever_todos(tmp_path)

    saida = capsys.readouterr().out
    ultima_linha = [l for l in saida.splitlines() if l.startswith("@PROGRESSO")][-1]
    payload = json.loads(ultima_linha[len("@PROGRESSO "):])
    assert payload["pct"] == 100.0
    assert payload["sucesso"] is True


# ---------------------------------------------------------------------------
# transcrever_todos - arquivo corrompido (ffprobe falha)
# ---------------------------------------------------------------------------


def test_transcrever_todos_arquivo_corrompido_via_ffprobe(tmp_path, monkeypatch):
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")

    def _ffprobe_falha(comando, **kwargs):
        class _Resultado:
            stdout = ""
            stderr = "Invalid data found when processing input"
            returncode = 1

        return _Resultado()

    monkeypatch.setattr(modulo.subprocess, "run", _ffprobe_falha)

    def _model_nao_deveria_ser_chamado(*a, **k):
        pytest.fail("model.transcribe nao deveria ser chamado para arquivo corrompido")

    model_fake = _ModelFake()
    model_fake.transcribe = _model_nao_deveria_ser_chamado
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    assert resultado["sucessos"] == 0
    item = resultado["transcricoes"][0]
    assert item["tipo_erro"] == "arquivo_corrompido"
    assert "fonte01.mp4" in item["mensagem_usuario"]


def test_transcrever_todos_arquivo_ausente_marca_corrompido_sem_chamar_ffprobe(
    tmp_path, monkeypatch
):
    _criar_manifest(tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}])
    # nao cria o arquivo fisico fonte01.mp4 de proposito.

    def _run_nao_deveria_ser_chamado(*a, **k):
        pytest.fail("subprocess.run (ffprobe) nao deveria ser chamado sem o arquivo existir")

    monkeypatch.setattr(modulo.subprocess, "run", _run_nao_deveria_ser_chamado)
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: _ModelFake())

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    assert resultado["transcricoes"][0]["tipo_erro"] == "arquivo_corrompido"


# ---------------------------------------------------------------------------
# transcrever_todos - falha parcial (alguns arquivos ok, outros nao)
# ---------------------------------------------------------------------------


def test_transcrever_todos_falha_parcial_mantem_sucesso_true_com_avisos(tmp_path, monkeypatch):
    pasta_fontes = _criar_manifest(
        tmp_path,
        [
            {"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True},
            {"id": "fonte02", "arquivo": "fonte02.mp4", "sucesso": True},
        ],
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    _criar_arquivo_fonte(pasta_fontes, "fonte02.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    info = _InfoFake(duration=4.2, language="en")
    segmentos_ok = [_SegmentoFake(0.0, 4.2, "trecho 1")]
    model_fake = _ModelFake(
        {
            "fonte01.mp4": (segmentos_ok, info),
            "fonte02.mp4": RuntimeError("CUDA failed with error out of memory"),
        }
    )
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is True
    assert resultado["sucessos"] == 1
    assert resultado["total"] == 2
    falha = next(r for r in resultado["transcricoes"] if not r["sucesso"])
    assert falha["tipo_erro"] == "vram_insuficiente"


# ---------------------------------------------------------------------------
# transcrever_todos - falha total (nenhum arquivo transcrito)
# ---------------------------------------------------------------------------


def test_transcrever_todos_falha_total_marca_sucesso_false(tmp_path, monkeypatch):
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)

    model_fake = _ModelFake({"fonte01.mp4": RuntimeError("erro insuspeitado qualquer")})
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: model_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    assert resultado["sucessos"] == 0


# ---------------------------------------------------------------------------
# transcrever_todos - timeout por video
# ---------------------------------------------------------------------------


def test_transcrever_todos_timeout_marca_categoria_timeout(tmp_path, monkeypatch):
    pasta_fontes = _criar_manifest(
        tmp_path, [{"id": "fonte01", "arquivo": "fonte01.mp4", "sucesso": True}]
    )
    _criar_arquivo_fonte(pasta_fontes, "fonte01.mp4")
    monkeypatch.setattr(modulo.subprocess, "run", _fake_ffprobe_sempre_ok)
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: _ModelFake())

    def _transcrever_com_timeout_fake(model, caminho, callback, timeout_s):
        raise TimeoutError("Transcricao excedeu o tempo limite de 3600s (timeout).")

    monkeypatch.setattr(modulo, "_transcrever_com_timeout", _transcrever_com_timeout_fake)

    resultado = modulo.transcrever_todos(tmp_path)

    assert resultado["sucesso"] is False
    item = resultado["transcricoes"][0]
    assert item["tipo_erro"] == "timeout"
    assert "60min" in item["mensagem_usuario"]


# Registro de DLLs cuBLAS/cuDNN (achado real da Sessao 4) foi extraido pra
# scripts/whisper_setup.py na Sessao 8.1-fix (CLAUDE.md secao 4/18.9) -
# reusado tambem por scripts/4_obter_audio.py. Testes de
# `registrar_dlls_cuda()` ficam em tests/test_whisper_setup.py; aqui so
# confirmamos que 2_transcrever.py de fato usa o modulo compartilhado.


def test_transcrever_usa_modulo_whisper_setup_compartilhado():
    assert modulo.whisper_setup.__name__ == "whisper_setup"
    assert hasattr(modulo.whisper_setup, "registrar_dlls_cuda")


def test_transcrever_com_timeout_real_estoura_prazo(tmp_path, monkeypatch):
    """Teste de integracao leve da propria _transcrever_com_timeout (nao
    mockada) - usa um timeout curto de verdade e um model fake que demora
    mais que isso para retornar, confirmando que TimeoutError e' levantado."""
    import time

    class _ModelLento:
        def transcribe(self, caminho, word_timestamps=True):
            time.sleep(0.5)
            return iter([]), _InfoFake()

    with pytest.raises(TimeoutError):
        modulo._transcrever_com_timeout(_ModelLento(), Path("fonte01.mp4"), lambda *a: None, 0.05)
