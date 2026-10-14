"""Testes do provedor DarkPlanner TTS (scripts/tts/darkplanner.py -
CLAUDE.md secao 5.6, integracao pos-Sessao 25).

Nunca chama a API DarkPlanner real (CLAUDE.md secao 8): `requests.post` e
`requests.get` sao sempre mockados. A API e' assincrona (job_id + polling);
os testes cobrem o fluxo feliz, timeout, job com falha, chave invalida,
rate limit e o cache em memoria da listagem de vozes.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import requests

import scripts.tts.darkplanner as darkplanner
from scripts.tts.darkplanner import DarkPlannerTTS
from scripts.tts.erros import ChaveTTSAusenteError, ChaveTTSInvalidaError, QuotaExcedidaError


@pytest.fixture(autouse=True)
def _limpar_cache_vozes():
    """Cache em memoria de listar_vozes e' global de modulo - reseta antes
    e depois de cada teste pra um teste nao vazar estado pro proximo."""
    darkplanner.limpar_cache_vozes()
    yield
    darkplanner.limpar_cache_vozes()


def _resposta_mock(status_code=200, json_data=None):
    resposta = MagicMock()
    resposta.status_code = status_code
    resposta.json.return_value = json_data or {}
    resposta.raise_for_status = MagicMock()
    if status_code >= 400:
        resposta.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
    return resposta


# ---------------------------------------------------------------------------
# validar_configuracao
# ---------------------------------------------------------------------------


def test_validar_configuracao_sem_chave(monkeypatch):
    monkeypatch.delenv("DARKPLANNER_API_KEY", raising=False)

    provedor = DarkPlannerTTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is False
    assert "DARKPLANNER_API_KEY" in mensagem


def test_validar_configuracao_com_chave(monkeypatch):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")

    provedor = DarkPlannerTTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is True


# ---------------------------------------------------------------------------
# sintetizar - fluxo feliz
# ---------------------------------------------------------------------------


def test_sintetizar_fluxo_completo(monkeypatch, tmp_path):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-1"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(200, {"audio_url": "https://cdn.example/audio.mp3"})
    resposta_audio = MagicMock()
    resposta_audio.status_code = 200
    resposta_audio.raise_for_status = MagicMock()
    resposta_audio.iter_content.return_value = [b"fake-mp3-bytes"]

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate) as mock_post, patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio],
    ) as mock_get:
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    mock_post.assert_called_once()
    assert mock_get.call_count == 3
    assert saida.read_bytes() == b"fake-mp3-bytes"
    assert resultado["audio_path"] == saida
    assert resultado["alinhamento"] is None
    assert resultado["provedor"] == "darkplanner"
    assert resultado["voz_usada"] == "voz-abc"
    assert resultado["custo_estimado_usd"] == 0.0


def test_sintetizar_sem_chave_levanta_erro(monkeypatch, tmp_path):
    monkeypatch.delenv("DARKPLANNER_API_KEY", raising=False)

    provedor = DarkPlannerTTS()
    with pytest.raises(ChaveTTSAusenteError):
        provedor.sintetizar("Texto", "voz", tmp_path / "saida.mp3")


def test_sintetizar_poll_varias_vezes_ate_completar(monkeypatch, tmp_path):
    """Job que fica 'processing' por duas checagens antes de 'completed' -
    confirma que o polling continua e nao desiste cedo demais."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    monkeypatch.setattr(darkplanner, "INTERVALO_POLLING_S", 0)
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-2"})
    resposta_status_1 = _resposta_mock(200, {"status": "processing"})
    resposta_status_2 = _resposta_mock(200, {"status": "processing"})
    resposta_status_3 = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(200, {"audio_url": "https://cdn.example/audio.mp3"})
    resposta_audio = MagicMock()
    resposta_audio.status_code = 200
    resposta_audio.raise_for_status = MagicMock()
    resposta_audio.iter_content.return_value = [b"bytes"]

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status_1, resposta_status_2, resposta_status_3, resposta_download, resposta_audio],
    ) as mock_get:
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Texto", "voz", saida)

    assert mock_get.call_count == 5
    assert resultado["provedor"] == "darkplanner"


def test_sintetizar_timeout_polling(monkeypatch, tmp_path):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    monkeypatch.setattr(darkplanner, "TIMEOUT_POLLING_S", 0)
    monkeypatch.setattr(darkplanner, "INTERVALO_POLLING_S", 0)
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-3"})
    resposta_status = _resposta_mock(200, {"status": "processing"})

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get", return_value=resposta_status
    ):
        provedor = DarkPlannerTTS()
        with pytest.raises(ChaveTTSInvalidaError) as exc_info:
            provedor.sintetizar("Texto", "voz", saida)

    assert "timeout" in str(exc_info.value).lower()


def test_sintetizar_job_falhou(monkeypatch, tmp_path):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-4"})
    resposta_status = _resposta_mock(200, {"status": "failed", "message": "voz invalida"})

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get", return_value=resposta_status
    ):
        provedor = DarkPlannerTTS()
        with pytest.raises(ChaveTTSInvalidaError) as exc_info:
            provedor.sintetizar("Texto", "voz", saida)

    assert "voz invalida" in str(exc_info.value)


def test_sintetizar_chave_invalida_401(monkeypatch, tmp_path):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_invalida")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(401, {})

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate):
        provedor = DarkPlannerTTS()
        with pytest.raises(ChaveTTSInvalidaError):
            provedor.sintetizar("Texto", "voz", saida)


def test_sintetizar_rate_limit_429(monkeypatch, tmp_path):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(429, {})

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate):
        provedor = DarkPlannerTTS()
        with pytest.raises(QuotaExcedidaError):
            provedor.sintetizar("Texto", "voz", saida)


def test_sintetizar_resposta_sem_job_id(monkeypatch, tmp_path):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {})

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate):
        provedor = DarkPlannerTTS()
        with pytest.raises(ChaveTTSInvalidaError):
            provedor.sintetizar("Texto", "voz", saida)


# ---------------------------------------------------------------------------
# sintetizar - alinhamento via SRT palavra (urls.srt_palavra)
# ---------------------------------------------------------------------------


def _resposta_texto_mock(status_code=200, texto=""):
    resposta = MagicMock()
    resposta.status_code = status_code
    resposta.raise_for_status = MagicMock()
    resposta.iter_content.return_value = [texto.encode("utf-8")]
    return resposta


_SRT_PALAVRA_EXEMPLO = (
    "1\n00:00:00,000 --> 00:00:00,300\nOla\n\n"
    "2\n00:00:00,300 --> 00:00:00,700\nmundo\n\n"
)


def test_darkplanner_le_urls_audio_aninhado(monkeypatch, tmp_path):
    """Formato documentado atual: audio_url vem de urls.audio (aninhado),
    nao da raiz da resposta."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-aninhado"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(200, {"urls": {"audio": "https://cdn.example/audio.mp3"}})
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio],
    ) as mock_get:
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert mock_get.call_count == 3
    assert saida.read_bytes() == b"fake-mp3-bytes"
    assert resultado["alinhamento"] is None  # sem srt_palavra nesta resposta


def test_darkplanner_le_audio_url_raiz_como_fallback(monkeypatch, tmp_path):
    """Formato achatado (campo audio_url na raiz, sem objeto "urls") - o
    formato que o codigo anterior desta integracao assumia e que pode ainda
    estar em uso em alguma versao da API."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-raiz"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(200, {"audio_url": "https://cdn.example/audio.mp3"})
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio],
    ) as mock_get:
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert mock_get.call_count == 3
    assert saida.read_bytes() == b"fake-mp3-bytes"
    assert resultado["alinhamento"] is None


def test_darkplanner_le_urls_srt_palavra_aninhado(monkeypatch, tmp_path):
    """Quando urls.srt_palavra esta presente, sintetizar() baixa e converte
    o SRT em `alinhamento`, com duracao_s vindo de ffprobe (nunca do ultimo
    fim_s do SRT)."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-srt"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(
        200,
        {"urls": {"audio": "https://cdn.example/audio.mp3", "srt_palavra": "https://cdn.example/palavra.srt"}},
    )
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")
    resposta_srt = _resposta_texto_mock(200, _SRT_PALAVRA_EXEMPLO)

    ffprobe_mock = MagicMock(stdout="0.900\n")
    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio, resposta_srt],
    ) as mock_get, patch("scripts.tts.darkplanner.subprocess.run", return_value=ffprobe_mock) as mock_run:
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert mock_get.call_count == 4
    mock_run.assert_called_once()
    assert resultado["alinhamento"] is not None
    assert resultado["alinhamento"]["duracao_s"] == 0.9  # veio do ffprobe mockado, nao do fim_s do SRT (0.7)
    assert resultado["alinhamento"]["palavras"] == [
        {"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.3},
        {"palavra": "mundo", "inicio_s": 0.3, "fim_s": 0.7},
    ]
    assert resultado["duracao_s"] == 0.9


def test_darkplanner_sem_srt_palavra_ainda_baixa_audio(monkeypatch, tmp_path):
    """Contrato pode nao retornar SRT em algum plano (urls.srt_palavra
    ausente) - o audio continua baixado normalmente e alinhamento vem None
    (fallback Whisper em scripts/4_obter_audio.py), sem GET extra pro SRT."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-sem-srt"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(200, {"urls": {"audio": "https://cdn.example/audio.mp3"}})
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio],
    ) as mock_get:
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert mock_get.call_count == 3  # nenhuma chamada extra pro SRT
    assert saida.read_bytes() == b"fake-mp3-bytes"
    assert resultado["alinhamento"] is None


def test_darkplanner_srt_download_falha_cai_para_whisper(monkeypatch, tmp_path):
    """Download do SRT palavra falhando (erro de rede) nao derruba
    sintetizar() inteiro - so' faz alinhamento voltar None."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-srt-falha"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(
        200,
        {"urls": {"audio": "https://cdn.example/audio.mp3", "srt_palavra": "https://cdn.example/palavra.srt"}},
    )
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio, requests.ConnectionError("fora do ar")],
    ):
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert resultado["alinhamento"] is None
    assert saida.read_bytes() == b"fake-mp3-bytes"  # audio principal nao e' afetado


def test_darkplanner_srt_sem_palavras_validas_cai_para_whisper(monkeypatch, tmp_path):
    """SRT baixado mas sem nenhum bloco valido (formato inesperado) - trata
    como falha do caminho SRT, nao levanta excecao."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-srt-vazio"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(
        200,
        {"urls": {"audio": "https://cdn.example/audio.mp3", "srt_palavra": "https://cdn.example/palavra.srt"}},
    )
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")
    resposta_srt = _resposta_texto_mock(200, "conteudo sem formato de SRT nenhum")

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio, resposta_srt],
    ):
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert resultado["alinhamento"] is None


def test_darkplanner_ffprobe_falha_cai_para_whisper(monkeypatch, tmp_path):
    """ffprobe falhando ao medir a duracao real do mp3 trata o caminho SRT
    inteiro como falho (duracao_s e' critico para o planejamento de slots
    da Etapa 5 - nunca aceitar alinhamento sem duracao_s confiavel)."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    saida = tmp_path / "narracao.mp3"

    resposta_generate = _resposta_mock(200, {"job_id": "job-ffprobe-falha"})
    resposta_status = _resposta_mock(200, {"status": "completed"})
    resposta_download = _resposta_mock(
        200,
        {"urls": {"audio": "https://cdn.example/audio.mp3", "srt_palavra": "https://cdn.example/palavra.srt"}},
    )
    resposta_audio = _resposta_texto_mock(200, "fake-mp3-bytes")
    resposta_srt = _resposta_texto_mock(200, _SRT_PALAVRA_EXEMPLO)

    with patch("scripts.tts.darkplanner.requests.post", return_value=resposta_generate), patch(
        "scripts.tts.darkplanner.requests.get",
        side_effect=[resposta_status, resposta_download, resposta_audio, resposta_srt],
    ), patch(
        "scripts.tts.darkplanner.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "ffprobe"),
    ):
        provedor = DarkPlannerTTS()
        resultado = provedor.sintetizar("Ola mundo", "voz-abc", saida)

    assert resultado["alinhamento"] is None


# ---------------------------------------------------------------------------
# _srt_para_palavras (parser puro)
# ---------------------------------------------------------------------------


def test_srt_para_palavras_formato_padrao(tmp_path):
    caminho = tmp_path / "palavra.srt"
    caminho.write_text(_SRT_PALAVRA_EXEMPLO, encoding="utf-8")

    palavras = darkplanner._srt_para_palavras(caminho)

    assert palavras == [
        {"palavra": "Ola", "inicio_s": 0.0, "fim_s": 0.3},
        {"palavra": "mundo", "inicio_s": 0.3, "fim_s": 0.7},
    ]


def test_srt_para_palavras_sem_linha_de_indice(tmp_path):
    """Alguns geradores omitem o numero sequencial antes do timestamp -
    parser precisa aceitar os dois formatos."""
    caminho = tmp_path / "palavra.srt"
    caminho.write_text("00:00:01,000 --> 00:00:01,500\noi\n", encoding="utf-8")

    palavras = darkplanner._srt_para_palavras(caminho)

    assert palavras == [{"palavra": "oi", "inicio_s": 1.0, "fim_s": 1.5}]


def test_srt_para_palavras_ignora_bloco_vazio_final(tmp_path):
    caminho = tmp_path / "palavra.srt"
    caminho.write_text(_SRT_PALAVRA_EXEMPLO + "\n\n\n", encoding="utf-8")

    palavras = darkplanner._srt_para_palavras(caminho)

    assert len(palavras) == 2


def test_srt_para_palavras_conteudo_invalido_retorna_lista_vazia(tmp_path):
    caminho = tmp_path / "palavra.srt"
    caminho.write_text("isto nao e' um SRT valido", encoding="utf-8")

    assert darkplanner._srt_para_palavras(caminho) == []


# ---------------------------------------------------------------------------
# listar_vozes / cache
# ---------------------------------------------------------------------------


def test_listar_vozes_sem_chave_retorna_vazio(monkeypatch):
    monkeypatch.delenv("DARKPLANNER_API_KEY", raising=False)

    provedor = DarkPlannerTTS()
    assert provedor.listar_vozes("en-US") == []


def test_listar_vozes_retorna_catalogo_da_api(monkeypatch):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    resposta = _resposta_mock(
        200,
        {
            "voices": [
                {"id": "v1", "name": "Helena", "gender": "feminina", "preview_url": "https://cdn/v1.mp3"},
                {"id": "v2", "name": "Marco", "gender": "masculina", "preview_url": "https://cdn/v2.mp3"},
            ]
        },
    )

    with patch("scripts.tts.darkplanner.requests.get", return_value=resposta) as mock_get:
        provedor = DarkPlannerTTS()
        vozes = provedor.listar_vozes("pt-BR")

    assert mock_get.call_count == 1
    assert len(vozes) == 2
    assert vozes[0]["id"] == "v1"
    assert vozes[0]["descricao"] == "Helena"
    assert vozes[0]["amostra_url"] == "https://cdn/v1.mp3"


def test_listar_vozes_ignora_idioma_retorna_mesma_lista(monkeypatch):
    """listar_vozes nao filtra por idioma (API nao devolve esse dado) -
    chamar com idiomas diferentes usa o mesmo cache, sem nova requisicao."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    resposta = _resposta_mock(200, {"voices": [{"id": "v1", "name": "Helena"}]})

    with patch("scripts.tts.darkplanner.requests.get", return_value=resposta) as mock_get:
        provedor = DarkPlannerTTS()
        vozes_en = provedor.listar_vozes("en-US")
        vozes_pt = provedor.listar_vozes("pt-BR")

    assert vozes_en == vozes_pt
    assert mock_get.call_count == 1  # segunda chamada veio do cache


def test_listar_vozes_falha_api_retorna_vazio(monkeypatch):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")

    with patch("scripts.tts.darkplanner.requests.get", side_effect=requests.ConnectionError("fora do ar")):
        provedor = DarkPlannerTTS()
        vozes = provedor.listar_vozes("en-US")

    assert vozes == []


def test_listar_vozes_cache_expira_apos_ttl(monkeypatch):
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    resposta = _resposta_mock(200, {"voices": [{"id": "v1", "name": "Helena"}]})

    with patch("scripts.tts.darkplanner.requests.get", return_value=resposta) as mock_get:
        provedor = DarkPlannerTTS()
        provedor.listar_vozes("en-US")
        # Forca expiracao do cache retrocedendo o timestamp gravado.
        darkplanner._cache_vozes["obtido_em"] -= darkplanner.CACHE_TTL_S + 1
        provedor.listar_vozes("en-US")

    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# Registro na factory get_provedor
# ---------------------------------------------------------------------------


def test_get_provedor_darkplanner_retorna_instancia():
    from scripts.tts import get_provedor

    provedor = get_provedor("darkplanner")

    assert isinstance(provedor, DarkPlannerTTS)
    assert hasattr(provedor, "sintetizar")
    assert hasattr(provedor, "listar_vozes")
    assert hasattr(provedor, "validar_configuracao")


def test_listar_vozes_ignora_voz_sem_id(monkeypatch):
    """Entrada malformada da API (sem 'id') e' descartada em vez de quebrar
    o dropdown inteiro (mesmo espirito defensivo do resto do pipeline)."""
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")
    resposta = _resposta_mock(
        200, {"voices": [{"id": "v1", "name": "Helena"}, {"name": "Sem ID"}]}
    )

    with patch("scripts.tts.darkplanner.requests.get", return_value=resposta):
        provedor = DarkPlannerTTS()
        vozes = provedor.listar_vozes("en-US")

    assert len(vozes) == 1
    assert vozes[0]["id"] == "v1"
