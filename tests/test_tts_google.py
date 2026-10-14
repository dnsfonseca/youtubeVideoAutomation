"""Testes do provedor Google Cloud TTS (scripts/tts/google.py - CLAUDE.md secao 5.6).

Nunca chama a API Google TTS real nem ffmpeg/ffprobe real (CLAUDE.md secao 8):
`requests.post` e `subprocess.run` sao sempre mockados. O catalogo de vozes
(scripts/tts/vozes_catalogo.json) e' lido de verdade (arquivo estatico).
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.tts.google import (
    FADE_IN_S,
    FADE_OUT_S,
    LIMITE_BYTES_POR_CHAMADA,
    SILENCIO_ENTRE_CHUNKS_S,
    GoogleTTS,
    _concatenar_audios_ffmpeg,
    _construir_filtro_transicao,
    _dividir_em_chunks,
    _sub_dividir_por_palavras,
    _todas_vozes_google,
)
from scripts.tts.erros import (
    ChaveTTSAusenteError,
    ChaveTTSInvalidaError,
    QuotaExcedidaError,
    TierNaoPermitidoError,
    VozInvalidaError,
)


# ---------------------------------------------------------------------------
# _dividir_em_chunks
# ---------------------------------------------------------------------------


def test_dividir_em_chunks_texto_curto():
    """Texto abaixo do limite nao e' dividido."""
    texto = "Este eh um texto muito curto."
    resultado = _dividir_em_chunks(texto, limite=100)
    assert resultado == [texto]


def test_dividir_em_chunks_texto_vazio():
    """Texto vazio resulta em lista vazia."""
    resultado = _dividir_em_chunks("", limite=100)
    assert resultado == []


def test_dividir_em_chunks_texto_longo_preserva_frases():
    """Texto longo e' dividido em chunks que nao cortam frases ao meio."""
    texto = "Primeira frase. Segunda frase. Terceira frase aqui."
    # Simula limite pequeno para forcar divisao
    chunks = _dividir_em_chunks(texto, limite=30)

    # Cada chunk deve ser uma sequencia completa de frases
    assert len(chunks) > 1
    for chunk in chunks:
        # Nenhum chunk deve terminar ou começar cortado no meio de palavra
        assert chunk.strip() == chunk


def test_dividir_em_chunks_limite_padrao():
    """Com limite padrao (LIMITE_BYTES_POR_CHAMADA), texto grande e' dividido
    em chunks que respeitam o limite em BYTES."""
    # Cria texto > limite padrao de bytes (ASCII puro: 1 char = 1 byte)
    frase = "Uma frase qualquer. " * 300  # ~6000 chars/bytes
    chunks = _dividir_em_chunks(frase)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= LIMITE_BYTES_POR_CHAMADA


def test_dividir_em_chunks_mede_bytes_nao_caracteres():
    """Bug real (sessao pos-Sessao 8): texto com em-dashes e aspas curvas
    (UTF-8 multibyte) precisa ser medido em bytes, nao em caracteres -
    senao um chunk 'legalmente' do tamanho em chars estoura o limite de
    bytes da API e a chamada e' rejeitada com HTTP 400."""
    # em-dash (—) e aspas curvas ("") ocupam 3 bytes cada em UTF-8.
    frase_com_multibyte = "Ela disse — “isso nunca vai acontecer” — e saiu. " * 150
    limite = 500

    chunks = _dividir_em_chunks(frase_com_multibyte, limite=limite)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= limite
        # Confirma que o teste de fato exercita o caso multibyte: em texto
        # puramente ASCII, len(chunk) == len(chunk.encode("utf-8")); aqui
        # o numero de bytes deve exceder o numero de caracteres em pelo
        # menos um chunk (senao o bug nao estaria sendo exercitado).
    assert any(len(c.encode("utf-8")) > len(c) for c in chunks)


def test_dividir_em_chunks_ascii_puro_comportamento_consistente():
    """Texto ASCII puro (baseline): bytes e chars coincidem, comportamento
    do chunking continua identico ao anterior (pre-correcao)."""
    texto = "Simple ascii sentence without accents. " * 200
    limite = 300

    chunks = _dividir_em_chunks(texto, limite=limite)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) == len(chunk.encode("utf-8"))
        assert len(chunk) <= limite


def test_dividir_em_chunks_frase_unica_maior_que_limite_sub_divide():
    """Uma unica 'frase' (sem '.' nem quebra de linha) maior que o limite
    de bytes aciona a salvaguarda de sub-divisao por palavras."""
    frase_unica_gigante = "palavra " * 900  # sem ponto final, uma frase so
    limite = 500

    chunks = _dividir_em_chunks(frase_unica_gigante, limite=limite)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= limite
    # Reconstrucao (ignorando espacos) preserva todas as palavras originais.
    assert " ".join(chunks).split() == frase_unica_gigante.split()


def test_sub_dividir_por_palavras_respeita_limite_bytes():
    """_sub_dividir_por_palavras nunca produz chunk acima do limite,
    mesmo com palavras multibyte misturadas."""
    texto = "café " * 400 + "coração " * 200  # multibyte (UTF-8: 2-3 bytes/char extra)
    limite = 400

    chunks = _sub_dividir_por_palavras(texto, limite)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= limite


def test_limite_bytes_por_chamada_e_4800():
    """Constante de margem de seguranca confirmada (200 bytes abaixo do
    limite real de 5000 bytes da API Google TTS)."""
    assert LIMITE_BYTES_POR_CHAMADA == 4800


# ---------------------------------------------------------------------------
# _todas_vozes_google
# ---------------------------------------------------------------------------


def test_todas_vozes_google_contem_vozes_conhecidas():
    """Catalogo de vozes tem vozes conhecidas em idiomas suportados."""
    vozes = _todas_vozes_google()

    # Vozes conhecidas (do vozes_catalogo.json)
    vozes_esperadas = [
        "en-US-Wavenet-A",
        "en-US-Wavenet-D",
        "pt-BR-Wavenet-B",
        "de-DE-Wavenet-B",
    ]

    for voz_id in vozes_esperadas:
        assert voz_id in vozes
        assert "id" in vozes[voz_id]


def test_todas_vozes_google_so_wavenet():
    """Protecao de custo: o catalogo curado so contem vozes Wavenet."""
    vozes = _todas_vozes_google()

    for voz_id in vozes:
        # Wavenet deve estar no id da voz (protecao contra tier caro)
        assert "Wavenet" in voz_id


# ---------------------------------------------------------------------------
# validar_configuracao
# ---------------------------------------------------------------------------


def test_validar_configuracao_sem_chave(monkeypatch):
    """Sem GOOGLE_TTS_API_KEY, validacao falha."""
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)

    provedor = GoogleTTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is False
    assert "GOOGLE_TTS_API_KEY" in mensagem


def test_validar_configuracao_com_chave(monkeypatch):
    """Com GOOGLE_TTS_API_KEY configurada, validacao passa."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key_123")

    provedor = GoogleTTS()
    ok, mensagem = provedor.validar_configuracao()

    assert ok is True


# ---------------------------------------------------------------------------
# listar_vozes
# ---------------------------------------------------------------------------


def test_listar_vozes_idioma_valido():
    """listar_vozes retorna vozes do catalogo para idioma existente."""
    provedor = GoogleTTS()
    vozes = provedor.listar_vozes("en-US")

    assert isinstance(vozes, list)
    assert len(vozes) > 0
    # Todas devem ter os campos obrigatorios
    for voz in vozes:
        assert "id" in voz
        assert "genero" in voz
        assert "descricao" in voz


def test_listar_vozes_idioma_invalido(capsys):
    """listar_vozes retorna [] para idioma inexistente, com warning."""
    provedor = GoogleTTS()
    vozes = provedor.listar_vozes("xx-XX")

    assert vozes == []
    # Deve ter emitido um warning
    capturado = capsys.readouterr()
    assert "xx-XX" in capturado.out or "WARN" in capturado.out


def test_listar_vozes_tous_idiomas_suportados():
    """Todos os idiomas do CLAUDE.md (secao 3) tem vozes curadas."""
    provedor = GoogleTTS()
    idiomas_suportados = ["en-US", "en-GB", "pt-BR", "es", "de"]

    for idioma in idiomas_suportados:
        vozes = provedor.listar_vozes(idioma)
        assert len(vozes) > 0, f"Nenhuma voz para idioma '{idioma}'"


# ---------------------------------------------------------------------------
# sintetizar - validacoes pre-chamada
# ---------------------------------------------------------------------------


def test_sintetizar_sem_chave_levanta_chave_ausente(tmp_path, monkeypatch):
    """Sem chave configurada, sintetizar levanta ChaveTTSAusenteError."""
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    with pytest.raises(ChaveTTSAusenteError):
        provedor.sintetizar("Texto teste", "en-US-Wavenet-A", saida)


def test_sintetizar_voz_tier_invalido_levanta_tier_nao_permitido(tmp_path, monkeypatch):
    """Voz com tier Neural2 (nao Wavenet) levanta TierNaoPermitidoError sem chamar API."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    # Neural2 nao e' permitido (so Wavenet no MVP)
    with pytest.raises(TierNaoPermitidoError):
        provedor.sintetizar("Texto", "en-US-Neural2-A", saida)


def test_sintetizar_voz_fora_catalogo_levanta_voz_invalida(tmp_path, monkeypatch):
    """Voz Wavenet fora do catalogo levanta VozInvalidaError sem chamar API."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    # Voz inventada (mesmo que tenha Wavenet no nome)
    with pytest.raises(VozInvalidaError):
        provedor.sintetizar("Texto", "en-US-Wavenet-Z", saida)


# ---------------------------------------------------------------------------
# sintetizar - sucesso com uma chamada
# ---------------------------------------------------------------------------


def test_sintetizar_texto_curto_sucesso(tmp_path, monkeypatch):
    """Sintetizar texto curto realiza uma chamada de API e retorna dict correto."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    # Mock de requests.post
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "audioContent": "SGVsbG8gV29ybGQ="  # "Hello World" em base64
    }

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_response))

    # Mock de subprocess.run para ffprobe
    fake_ffprobe = MagicMock()
    fake_ffprobe.stdout = "5.2\n"
    fake_ffprobe.returncode = 0
    monkeypatch.setattr(modulo_google.subprocess, "run", MagicMock(return_value=fake_ffprobe))

    provedor = GoogleTTS()
    texto = "Olá mundo. Como você está?"
    saida = tmp_path / "audio.mp3"

    resultado = provedor.sintetizar(texto, "en-US-Wavenet-A", saida)

    # Arquivo deve ter sido criado
    assert saida.exists()

    # Resultado deve ter os campos esperados
    assert resultado["provedor"] == "google"
    assert resultado["voz_usada"] == "en-US-Wavenet-A"
    assert resultado["audio_path"] == saida
    assert resultado["alinhamento"] is None  # Google nao fornece alinhamento nativo
    assert resultado["duracao_s"] == 5.2
    assert "chunks_processados" in resultado
    assert resultado["chunks_processados"] == 1


def test_sintetizar_custo_calculado_corretamente(tmp_path, monkeypatch):
    """Custo e' calculado corretamente (chars / 1_000_000 * 4.00)."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"audioContent": "SGVsbG8="}

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_response))

    fake_ffprobe = MagicMock()
    fake_ffprobe.stdout = "1.0\n"
    fake_ffprobe.returncode = 0
    monkeypatch.setattr(modulo_google.subprocess, "run", MagicMock(return_value=fake_ffprobe))

    provedor = GoogleTTS()
    texto = "X" * 1_000_000  # Exatamente 1 milhao de caracteres
    saida = tmp_path / "audio.mp3"

    resultado = provedor.sintetizar(texto, "en-US-Wavenet-A", saida)

    # Custo deve ser 1_000_000 / 1_000_000 * 4.00 = 4.0
    assert resultado["custo_estimado_usd"] == 4.0


# ---------------------------------------------------------------------------
# sintetizar - chunking
# ---------------------------------------------------------------------------


def test_sintetizar_texto_longo_faz_chunking(tmp_path, monkeypatch):
    """Texto > 5000 chars dispara chunking automatico com multiplas chamadas."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    chamadas = []

    def fake_post(url, **kwargs):
        chamadas.append(kwargs)
        resposta = MagicMock()
        resposta.status_code = 200
        resposta.json.return_value = {"audioContent": "QQ=="}  # "A" em base64
        return resposta

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", fake_post)

    # Mock de subprocess para concat e ffprobe
    def fake_subprocess_run(comando, **kwargs):
        resultado = MagicMock()
        resultado.stdout = "10.0\n"
        resultado.returncode = 0
        resultado.stderr = ""
        return resultado

    monkeypatch.setattr(modulo_google.subprocess, "run", fake_subprocess_run)

    provedor = GoogleTTS()
    # Texto > 5000 caracteres, mas formado de frases que podem ser divididas
    frase = "Uma frase aqui. " * 350  # ~5600 caracteres
    saida = tmp_path / "audio.mp3"

    resultado = provedor.sintetizar(frase, "en-US-Wavenet-D", saida)

    # Deve ter havido multiplas chamadas (chunking)
    assert len(chamadas) > 1
    assert resultado["chunks_processados"] > 1


# ---------------------------------------------------------------------------
# _construir_filtro_transicao / _concatenar_audios_ffmpeg - transicoes
# ---------------------------------------------------------------------------


def test_construir_filtro_transicao_primeiro_chunk_sem_fade_in():
    """Primeiro chunk comeca normal (sem fade in), mas tem fade out pra
    transicionar pro silencio antes do proximo chunk."""
    filtro = _construir_filtro_transicao([3.0, 4.0])
    partes = filtro.split(";")
    parte_chunk0 = next(p for p in partes if p.startswith("[0:a]"))

    assert "afade=t=in" not in parte_chunk0
    esperado_fade_out = f"afade=t=out:st={max(0.0, 3.0 - FADE_OUT_S)}:d={FADE_OUT_S}"
    assert esperado_fade_out in parte_chunk0


def test_construir_filtro_transicao_ultimo_chunk_sem_fade_out():
    """Ultimo chunk termina normal (sem fade out), mas tem fade in pra
    suavizar a entrada apos o silencio do chunk anterior."""
    filtro = _construir_filtro_transicao([3.0, 4.0])
    partes = filtro.split(";")
    parte_chunk1 = next(p for p in partes if p.startswith("[1:a]"))

    assert f"afade=t=in:st=0:d={FADE_IN_S}" in parte_chunk1
    assert "afade=t=out" not in parte_chunk1


def test_construir_filtro_transicao_chunk_intermediario_tem_ambos_fades():
    """Chunk do meio (nem primeiro nem ultimo) tem fade in E fade out."""
    filtro = _construir_filtro_transicao([2.0, 3.0, 2.5])
    partes = filtro.split(";")
    parte_meio = next(p for p in partes if p.startswith("[1:a]"))

    assert f"afade=t=in:st=0:d={FADE_IN_S}" in parte_meio
    esperado_fade_out = f"afade=t=out:st={max(0.0, 3.0 - FADE_OUT_S)}:d={FADE_OUT_S}"
    assert esperado_fade_out in parte_meio


def test_construir_filtro_transicao_silencio_entre_cada_par():
    """Silencio de SILENCIO_ENTRE_CHUNKS_S inserido entre cada par de
    chunks - para N chunks, concat tem N + (N-1) segmentos."""
    filtro = _construir_filtro_transicao([2.0, 3.0, 2.5])

    assert f"aevalsrc=0:d={SILENCIO_ENTRE_CHUNKS_S}[silencio]" in filtro
    # 3 chunks + 2 silencios = 5 segmentos no concat final
    assert "concat=n=5:v=0:a=1[out]" in filtro


def test_concatenar_audios_ffmpeg_chunk_unico_apenas_copia(tmp_path, monkeypatch):
    """Chunk unico e' apenas copiado pra saida - sem fade nem silencio,
    nao ha nada pra suavizar numa concatenacao de um item so."""
    import scripts.tts.google as modulo_google

    chunk = tmp_path / "chunk_000.mp3"
    chunk.write_bytes(b"conteudo-fake-mp3")
    saida = tmp_path / "audio.mp3"

    subprocess_mock = MagicMock()
    monkeypatch.setattr(modulo_google.subprocess, "run", subprocess_mock)

    _concatenar_audios_ffmpeg([chunk], saida)

    subprocess_mock.assert_not_called()
    assert saida.read_bytes() == chunk.read_bytes()


def test_concatenar_audios_ffmpeg_multiplos_chunks_usa_filter_complex(tmp_path, monkeypatch):
    """Com 2+ chunks, o comando ffmpeg usa -filter_complex com fades e
    silencio, uma -i por chunk, e mapeia [out]."""
    import scripts.tts.google as modulo_google

    chunks = []
    for indice in range(3):
        caminho = tmp_path / f"chunk_{indice:03d}.mp3"
        caminho.write_bytes(b"fake")
        chunks.append(caminho)
    saida = tmp_path / "audio.mp3"

    comandos_capturados = []

    def fake_run(comando, **kwargs):
        comandos_capturados.append(comando)
        resultado = MagicMock()
        resultado.stdout = "4.0\n"
        resultado.returncode = 0
        return resultado

    monkeypatch.setattr(modulo_google.subprocess, "run", fake_run)

    _concatenar_audios_ffmpeg(chunks, saida)

    comando_ffmpeg = next(c for c in comandos_capturados if c[0] == "ffmpeg")
    assert "-filter_complex" in comando_ffmpeg
    assert comando_ffmpeg.count("-i") == 3
    assert "-map" in comando_ffmpeg
    assert "[out]" in comando_ffmpeg

    filtro = comando_ffmpeg[comando_ffmpeg.index("-filter_complex") + 1]
    assert "afade=t=in" in filtro
    assert "afade=t=out" in filtro
    assert f"aevalsrc=0:d={SILENCIO_ENTRE_CHUNKS_S}" in filtro


# ---------------------------------------------------------------------------
# sintetizar - erros HTTP
# ---------------------------------------------------------------------------


def test_sintetizar_erro_401_levanta_chave_invalida(tmp_path, monkeypatch):
    """Resposta 401 da API levanta ChaveTTSInvalidaError."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "invalid_key")

    fake_response = MagicMock()
    fake_response.status_code = 401
    fake_response.json.return_value = {"error": "Unauthorized"}

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_response))

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    with pytest.raises(ChaveTTSInvalidaError):
        provedor.sintetizar("Teste", "en-US-Wavenet-A", saida)


def test_sintetizar_erro_403_levanta_chave_invalida(tmp_path, monkeypatch):
    """Resposta 403 da API levanta ChaveTTSInvalidaError."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    fake_response = MagicMock()
    fake_response.status_code = 403

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_response))

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    with pytest.raises(ChaveTTSInvalidaError):
        provedor.sintetizar("Teste", "en-US-Wavenet-A", saida)


def test_sintetizar_erro_429_levanta_quota_excedida(tmp_path, monkeypatch):
    """Resposta 429 (rate limit) levanta QuotaExcedidaError."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    fake_response = MagicMock()
    fake_response.status_code = 429

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_response))

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    with pytest.raises(QuotaExcedidaError):
        provedor.sintetizar("Teste", "en-US-Wavenet-D", saida)


def test_sintetizar_erro_sem_audioContent_levanta_chave_invalida(tmp_path, monkeypatch):
    """Resposta 200 mas sem audioContent levanta ChaveTTSInvalidaError."""
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {}  # Sem audioContent

    import scripts.tts.google as modulo_google
    monkeypatch.setattr(modulo_google.requests, "post", MagicMock(return_value=fake_response))

    provedor = GoogleTTS()
    saida = tmp_path / "audio.mp3"

    with pytest.raises(ChaveTTSInvalidaError):
        provedor.sintetizar("Teste", "en-US-Wavenet-A", saida)
