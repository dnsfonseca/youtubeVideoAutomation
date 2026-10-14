"""Testes da Etapa 4 do pipeline (scripts/4_obter_audio.py) - obtencao de audio
da narracao via TTS ou upload (CLAUDE.md secao 5.6).

Nunca chama APIs reais (Google TTS, faster-whisper), ffmpeg real, ou ffprobe real
(CLAUDE.md secao 8): `WhisperModel`, `requests.post`, `subprocess.run` sao sempre
mockados. O arquivo de script comeca com digito ("4_obter_audio.py"), entao e'
carregado via importlib.util.spec_from_file_location.
"""

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "4_obter_audio.py"

_spec = importlib.util.spec_from_file_location("obter_audio_etapa4", CAMINHO_SCRIPT)
modulo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = modulo
_spec.loader.exec_module(modulo)


# ---------------------------------------------------------------------------
# Fakes de faster_whisper.WhisperModel
# ---------------------------------------------------------------------------


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


class _ModelFakeFail:
    """Modelo fake que lanca excecao no transcribe."""

    def __init__(self, excecao=None):
        self.excecao = excecao or RuntimeError("Erro fake no transcribe")

    def transcribe(self, caminho, word_timestamps=True):
        raise self.excecao


class _ModelFakeOk:
    """Modelo fake que retorna dados validos."""

    def __init__(self, duracao=10.0, idioma="en"):
        self.duracao = duracao
        self.idioma = idioma

    def transcribe(self, caminho, word_timestamps=True):
        palavras = [
            _PalavraFake(0.0, 0.5, "Hello"),
            _PalavraFake(0.5, 1.0, "world"),
        ]
        segmento = _SegmentoFake(0.0, 1.0, "Hello world", words=palavras)
        info = _InfoFake(duration=self.duracao, language=self.idioma)
        return iter([segmento]), info


def _monkeypatch_whisper_modelo_ok(monkeypatch):
    """Mock de WhisperModel que funciona bem.

    O construtor real e' chamado como WhisperModel(modelo_nome,
    device=..., compute_type=...) (scripts/4_obter_audio.py:_carregar_modelo_whisper,
    mesma assinatura de scripts/2_transcrever.py) - envolve _ModelFakeOk
    numa lambda que absorve esses argumentos, mesmo padrao de
    tests/test_transcrever.py (`lambda *a, **k: model_fake`)."""
    monkeypatch.setattr(modulo, "WhisperModel", lambda *a, **k: _ModelFakeOk())


def _monkeypatch_whisper_modelo_erro(monkeypatch, excecao):
    """Mock de WhisperModel que lanca excecao."""
    def fake_constructor(*args, **kwargs):
        return _ModelFakeFail(excecao)

    monkeypatch.setattr(modulo, "WhisperModel", fake_constructor)


# ---------------------------------------------------------------------------
# classificar_erro_tts
# ---------------------------------------------------------------------------


def test_classificar_erro_chave_ausente():
    from scripts.tts import ChaveTTSAusenteError

    exc = ChaveTTSAusenteError("GOOGLE_TTS_API_KEY")
    tipo, msg = modulo.classificar_erro_tts(exc)

    assert tipo == "chave_ausente"
    assert "GOOGLE_TTS_API_KEY" in msg


def test_classificar_erro_chave_invalida():
    from scripts.tts import ChaveTTSInvalidaError

    exc = ChaveTTSInvalidaError("Chave invalida")
    tipo, msg = modulo.classificar_erro_tts(exc)

    assert tipo == "chave_invalida"


def test_classificar_erro_quota_excedida():
    from scripts.tts import QuotaExcedidaError

    exc = QuotaExcedidaError("Quota excedida")
    tipo, msg = modulo.classificar_erro_tts(exc)

    assert tipo == "quota_excedida"


def test_classificar_erro_voz_invalida():
    from scripts.tts import VozInvalidaError

    exc = VozInvalidaError("en-US-Wavenet-Z")
    tipo, msg = modulo.classificar_erro_tts(exc)

    assert tipo == "voz_invalida"


def test_classificar_erro_tier_nao_permitido():
    from scripts.tts import TierNaoPermitidoError

    exc = TierNaoPermitidoError("en-US-Neural2-A")
    tipo, msg = modulo.classificar_erro_tts(exc)

    assert tipo == "tier_nao_permitido"


def test_classificar_erro_desconhecido():
    exc = ValueError("Algo totalmente diferente")
    tipo, msg = modulo.classificar_erro_tts(exc)

    assert tipo == "erro_desconhecido"


# ---------------------------------------------------------------------------
# _validar_pre_condicoes
# ---------------------------------------------------------------------------


def test_validar_pre_condicoes_origem_audio_ausente(tmp_path, monkeypatch):
    """Sem origem_audio.json, validacao falha."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, None)

    assert ok is False
    assert "origem_audio" in mensagem.lower()
    assert tipo_erro == "erro_desconhecido"


def test_validar_pre_condicoes_origem_depois(tmp_path, monkeypatch):
    """origem_audio.json com origem='depois' eh um erro (nao deveria chegar aqui)."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()

    origem_audio = {"origem": "depois"}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, origem_audio)

    assert ok is False
    assert "decidir depois" in mensagem.lower() or "origem" in mensagem.lower()


def test_validar_pre_condicoes_tts_sem_roteiro(tmp_path, monkeypatch):
    """TTS sem roteiro_aprovado.md eh erro."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()

    origem_audio = {"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, origem_audio)

    assert ok is False
    assert "roteiro" in mensagem.lower()


def test_validar_pre_condicoes_upload_sem_arquivo(tmp_path, monkeypatch):
    """Upload sem arquivo especificado eh erro."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()

    origem_audio = {"origem": "upload"}  # Sem upload_arquivo

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, origem_audio)

    assert ok is False
    assert "arquivo" in mensagem.lower() or "upload" in mensagem.lower()


def test_validar_pre_condicoes_upload_arquivo_nao_existe(tmp_path, monkeypatch):
    """Upload com arquivo inexistente eh erro."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()

    origem_audio = {"origem": "upload", "upload_arquivo": "narracao.mp3"}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, origem_audio)

    assert ok is False
    assert "nao encontrado" in mensagem.lower() or "arquivo" in mensagem.lower()


def test_validar_pre_condicoes_tts_valido(tmp_path, monkeypatch):
    """Validacao passa para TTS com roteiro_aprovado.md existente."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "roteiro_aprovado.md").write_text("Roteiro teste")

    origem_audio = {"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, origem_audio)

    assert ok is True


def test_validar_pre_condicoes_upload_valido(tmp_path, monkeypatch):
    """Validacao passa para upload com arquivo existente."""
    monkeypatch.setattr(modulo.robustez, "validar_pre_condicoes_pipeline", lambda: (True, None))

    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "narracao_upload.mp3").write_bytes(b"audio fake")

    origem_audio = {"origem": "upload", "upload_arquivo": "narracao_upload.mp3"}

    ok, mensagem, tipo_erro = modulo._validar_pre_condicoes(pasta, origem_audio)

    assert ok is True


# ---------------------------------------------------------------------------
# _gerar_alinhamento_whisper
# ---------------------------------------------------------------------------


def test_gerar_alinhamento_whisper_sucesso(tmp_path, monkeypatch):
    """Alinhamento gerado corretamente via fake WhisperModel."""
    _monkeypatch_whisper_modelo_ok(monkeypatch)

    arquivo_audio = tmp_path / "audio.mp3"
    arquivo_audio.write_bytes(b"fake audio")

    inicio = __import__("time").monotonic()
    resultado = modulo._gerar_alinhamento_whisper(arquivo_audio, inicio)

    assert "duracao_s" in resultado
    assert "idioma_detectado" in resultado
    assert "texto_transcrito" in resultado
    assert "palavras" in resultado
    assert isinstance(resultado["palavras"], list)
    assert len(resultado["palavras"]) > 0


def test_gerar_alinhamento_whisper_com_timeout(tmp_path, monkeypatch):
    """Timeout no transcribe levanta TimeoutError."""
    import time

    def fake_whisper_com_delay(*args, **kwargs):
        class FakeModel:
            def transcribe(self, caminho, word_timestamps=True):
                time.sleep(20)  # Delay maior que timeout
                return iter([]), _InfoFake()

        return FakeModel()

    monkeypatch.setattr(modulo, "WhisperModel", fake_whisper_com_delay)
    monkeypatch.setattr(modulo, "TIMEOUT_WHISPER_S", 0.1)  # Timeout curto pra teste

    arquivo_audio = tmp_path / "audio.mp3"
    arquivo_audio.write_bytes(b"fake audio")

    inicio = __import__("time").monotonic()

    with pytest.raises(TimeoutError):
        modulo._gerar_alinhamento_whisper(arquivo_audio, inicio)


def test_gerar_alinhamento_whisper_erro_modelo(tmp_path, monkeypatch):
    """Erro no modelo eh repassado."""
    erro = RuntimeError("Modelo com problema")
    _monkeypatch_whisper_modelo_erro(monkeypatch, erro)

    arquivo_audio = tmp_path / "audio.mp3"
    arquivo_audio.write_bytes(b"fake audio")

    inicio = __import__("time").monotonic()

    with pytest.raises(RuntimeError, match="Modelo com problema"):
        modulo._gerar_alinhamento_whisper(arquivo_audio, inicio)


# ---------------------------------------------------------------------------
# _converter_para_mp3
# ---------------------------------------------------------------------------


def test_converter_para_mp3_sucesso(tmp_path, monkeypatch):
    """Conversao bem-sucedida via ffmpeg mockado."""
    origem = tmp_path / "audio.wav"
    origem.write_bytes(b"fake wav")
    destino = tmp_path / "audio.mp3"

    def fake_subprocess_run(comando, **kwargs):
        # Simula criacao do arquivo de saida
        destino.write_bytes(b"fake mp3")
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        return resultado

    monkeypatch.setattr(modulo.subprocess, "run", fake_subprocess_run)

    ok, erro = modulo._converter_para_mp3(origem, destino)

    assert ok is True
    assert erro is None
    assert destino.exists()


def test_converter_para_mp3_falha_ffmpeg(tmp_path, monkeypatch):
    """Falha do ffmpeg retorna (False, mensagem)."""
    origem = tmp_path / "audio.wav"
    origem.write_bytes(b"fake wav")
    destino = tmp_path / "audio.mp3"

    def fake_subprocess_run(comando, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "Formato nao suportado"
        return resultado

    monkeypatch.setattr(modulo.subprocess, "run", fake_subprocess_run)

    ok, erro = modulo._converter_para_mp3(origem, destino)

    assert ok is False
    assert "Formato nao suportado" in erro


def test_converter_para_mp3_arquivo_nao_criado(tmp_path, monkeypatch):
    """Se ffmpeg sai com sucesso mas arquivo nao aparece, eh erro."""
    origem = tmp_path / "audio.wav"
    origem.write_bytes(b"fake wav")
    destino = tmp_path / "audio.mp3"

    def fake_subprocess_run(comando, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        # NAO cria o arquivo de destino
        return resultado

    monkeypatch.setattr(modulo.subprocess, "run", fake_subprocess_run)

    ok, erro = modulo._converter_para_mp3(origem, destino)

    assert ok is False


# ---------------------------------------------------------------------------
# obter_audio - fluxo TTS
# ---------------------------------------------------------------------------


def test_obter_audio_tts_sucesso(tmp_path, monkeypatch):
    """Fluxo TTS completo: le roteiro, chama provedor, gera alinhamento."""
    _monkeypatch_whisper_modelo_ok(monkeypatch)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "roteiro_aprovado.md").write_text("Roteiro teste com conteudo.")
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"})
    )

    # Mock do provedor google
    fake_resposta = MagicMock()
    fake_resposta.status_code = 200
    fake_resposta.json.return_value = {"audioContent": "QQ=="}  # "A" em base64

    import scripts.tts.google as modulo_google

    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_resposta))

    # Mock de ffprobe
    def fake_subprocess_run(comando, **kwargs):
        resultado = MagicMock()
        resultado.stdout = "5.2\n"
        resultado.returncode = 0
        resultado.stderr = ""
        return resultado

    monkeypatch.setattr(modulo_google.subprocess, "run", fake_subprocess_run)

    resultado = modulo.obter_audio(pasta)

    assert resultado["sucesso"] is True
    assert (pasta / "narracao.mp3").exists()
    assert (pasta / "narracao_alinhamento.json").exists()
    assert (pasta / "narracao_metadata.json").exists()

    # Verifica metadata
    metadata = json.loads((pasta / "narracao_metadata.json").read_text())
    assert metadata["origem"] == "tts"
    assert metadata["provedor"] == "google"
    assert metadata["voz_usada"] == "en-US-Wavenet-A"


def test_remover_cabecalhos_markdown_remove_ate_h6_e_colapsa_linhas_em_branco():
    texto = "Paragrafo um.\n\n## Titulo de secao\n\nParagrafo dois.\n### Outro\nParagrafo tres."
    resultado = modulo._remover_cabecalhos_markdown(texto)
    assert "#" not in resultado
    assert "Titulo de secao" not in resultado
    assert "Paragrafo um." in resultado
    assert "Paragrafo dois." in resultado
    assert "Paragrafo tres." in resultado


def test_remover_cabecalhos_markdown_vazio_nao_quebra():
    assert modulo._remover_cabecalhos_markdown("") == ""
    assert modulo._remover_cabecalhos_markdown(None) is None


def test_obter_audio_tts_remove_cabecalhos_markdown_antes_de_sintetizar(tmp_path, monkeypatch):
    """Rede de seguranca defensiva (CLAUDE.md secao 18.6/18.7): mesmo que
    roteiro_aprovado.md chegue com cabecalhos markdown ATX intactos (achado
    real - nancyGuthrieProject03 aprovado em producao chegou aqui com 17
    cabecalhos "## Titulo de secao" que a tela de revisao deveria ter
    removido), o TTS nunca deve receber essas linhas literalmente - o
    narrador leria o titulo em voz alta."""
    _monkeypatch_whisper_modelo_ok(monkeypatch)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "roteiro_aprovado.md").write_text(
        "## The Woman Who Lived Alone in the Foothills\n\nRoteiro teste com conteudo real."
    )
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"})
    )

    fake_resposta = MagicMock()
    fake_resposta.status_code = 200
    fake_resposta.json.return_value = {"audioContent": "QQ=="}

    import scripts.tts.google as modulo_google

    mock_post = MagicMock(return_value=fake_resposta)
    monkeypatch.setattr(modulo_google.requests, "post", mock_post)

    def fake_subprocess_run(comando, **kwargs):
        resultado = MagicMock()
        resultado.stdout = "5.2\n"
        resultado.returncode = 0
        resultado.stderr = ""
        return resultado

    monkeypatch.setattr(modulo_google.subprocess, "run", fake_subprocess_run)

    resultado = modulo.obter_audio(pasta)
    assert resultado["sucesso"] is True

    textos_enviados = [chamada.kwargs["json"]["input"]["text"] for chamada in mock_post.call_args_list]
    texto_completo_enviado = " ".join(textos_enviados)
    assert "##" not in texto_completo_enviado
    assert "The Woman Who Lived Alone in the Foothills" not in texto_completo_enviado
    assert "Roteiro teste com conteudo real." in texto_completo_enviado


def test_obter_audio_tts_chave_ausente(tmp_path, monkeypatch):
    """TTS sem chave configurada retorna erro."""
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)

    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "roteiro_aprovado.md").write_text("Roteiro teste.")
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "en-US-Wavenet-A"})
    )

    resultado = modulo.obter_audio(pasta)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "chave_ausente"


# ---------------------------------------------------------------------------
# obter_audio - fluxo upload
# ---------------------------------------------------------------------------


def test_obter_audio_upload_sucesso(tmp_path, monkeypatch):
    """Fluxo upload completo: converte, gera alinhamento."""
    _monkeypatch_whisper_modelo_ok(monkeypatch)

    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "narracao_upload.mp3").write_bytes(b"fake audio")
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "upload", "upload_arquivo": "narracao_upload.mp3"})
    )

    # Mock de subprocess.run (conversao + ffprobe)
    def fake_subprocess_run(comando, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 0
        resultado.stderr = ""
        # Se for conversao, cria arquivo de saida
        if len(comando) > 2 and "narracao.mp3" in str(comando):
            (pasta / "narracao.mp3").write_bytes(b"converted audio")
        # Se for ffprobe, retorna duracao
        resultado.stdout = "5.2\n"
        return resultado

    import scripts.tts.google as modulo_google

    monkeypatch.setattr(modulo_google.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(modulo.subprocess, "run", fake_subprocess_run)

    resultado = modulo.obter_audio(pasta)

    assert resultado["sucesso"] is True
    assert (pasta / "narracao.mp3").exists()
    assert (pasta / "narracao_alinhamento.json").exists()
    assert (pasta / "narracao_metadata.json").exists()

    metadata = json.loads((pasta / "narracao_metadata.json").read_text())
    assert metadata["origem"] == "upload"
    assert metadata["provedor"] is None
    assert metadata["custo_estimado_usd"] == 0.0


def test_obter_audio_upload_conversao_falha(tmp_path, monkeypatch):
    """Upload com falha na conversao retorna erro."""
    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "narracao_upload.mp3").write_bytes(b"fake audio")
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "upload", "upload_arquivo": "narracao_upload.mp3"})
    )

    # Mock de subprocess.run que falha na conversao
    def fake_subprocess_run_falha(comando, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        resultado.stderr = "Codec nao suportado"
        return resultado

    monkeypatch.setattr(modulo.subprocess, "run", fake_subprocess_run_falha)

    resultado = modulo.obter_audio(pasta)

    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "conversao_ffmpeg_falhou"


# ---------------------------------------------------------------------------
# obter_audio - erros de pre-condicao
# ---------------------------------------------------------------------------


def test_obter_audio_origem_audio_ausente(tmp_path):
    """origem_audio.json ausente retorna erro sem crashar."""
    pasta = tmp_path / "projeto"
    pasta.mkdir()

    resultado = modulo.obter_audio(pasta)

    assert resultado["sucesso"] is False
    assert "origem_audio" in resultado.get("erro_fatal", "").lower()


def test_obter_audio_origem_depois(tmp_path):
    """origem='depois' retorna erro (decisao adiada nao deveria chegar aqui)."""
    pasta = tmp_path / "projeto"
    pasta.mkdir()
    (pasta / "origem_audio.json").write_text(json.dumps({"origem": "depois"}))

    resultado = modulo.obter_audio(pasta)

    assert resultado["sucesso"] is False
    assert "depois" in resultado.get("erro_fatal", "").lower()
