"""Testes da correcao desta sessao: OPENAI_API_KEY passou a servir dois
propositos (TTS OpenAI, ainda stub, e o provedor de imagem "openai" da
thumbnail - scripts/imagem/openai.py, esse sim implementado). A chave
configurada NUNCA pode fazer o provedor de TTS OpenAI parecer disponivel
- ele continua stub (`scripts/tts/openai.py:sintetizar` levanta
NotImplementedError). Escopo DELIBERADAMENTE estreito: so' "openai" e'
afetado (server.PROVEDOR_TTS_OPENAI_INDISPONIVEL_COM_CHAVE) - elevenlabs/
azure tem chave propria (sem uso duplo) e continuam no comportamento
antigo (passam na validacao com a chave presente, falham depois dentro do
subprocess da Etapa 4 - CLAUDE.md secao 5.6, ja coberto por
tests/test_aprovar_roteiro.py). Checado em tres lugares:
- tela de revisao (tts_disponiveis, dropdown desabilitado)
- POST /aprovar_roteiro (validacao de backend)
- POST /gerar_audio (retry/decidir depois)
"""

import json

import server


def _criar_projeto_com_roteiro_aprovado(tmp_path, nome):
    pasta = tmp_path / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")
    (pasta / "job.json").write_text(
        json.dumps({"nome": nome, "status": "aguardando_audio", "etapa_atual": "audio"}), encoding="utf-8"
    )
    return pasta


def test_constante_de_excecao_e_so_openai():
    assert server.PROVEDOR_TTS_OPENAI_INDISPONIVEL_COM_CHAVE == "openai"


def test_gerar_audio_retry_openai_recusa_mesmo_com_chave_configurada(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta = _criar_projeto_com_roteiro_aprovado(projetos_dir, "caso_retry")
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "openai", "voz": "alloy"}), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-chave-real-usada-so-pra-imagem")

    resposta = client.post("/projetos/caso_retry/gerar_audio")

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "provedor_nao_implementado"
    assert "openai" in corpo["mensagem"]


def test_gerar_audio_retry_openai_sem_chave_tambem_recusa_com_a_mesma_mensagem(client, tmp_path, monkeypatch):
    """Sem chave nenhuma, o motivo do bloqueio continua sendo
    "nao implementado" (nao "chave ausente") - a causa raiz nunca foi a
    chave, era o provedor nunca ter sido implementado."""
    projetos_dir = tmp_path / "projetos"
    pasta = _criar_projeto_com_roteiro_aprovado(projetos_dir, "caso_retry_sem_chave")
    (pasta / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "openai", "voz": "alloy"}), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resposta = client.post("/projetos/caso_retry_sem_chave/gerar_audio")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "provedor_nao_implementado"


def test_gerar_audio_retry_google_com_chave_continua_funcionando(client, tmp_path, monkeypatch):
    """Nao-regressao: provedor implementado de verdade (google) com chave
    configurada continua disparando a Etapa 4 normalmente."""
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_roteiro_aprovado(projetos_dir, "caso_google")
    (projetos_dir / "caso_google" / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "google", "voz": "pt-BR-Wavenet-B"}), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "chave-google-fake")
    monkeypatch.setattr(server, "_disparar_etapa4", lambda *a, **k: None)

    resposta = client.post("/projetos/caso_google/gerar_audio")

    assert resposta.status_code == 202


def test_gerar_audio_retry_elevenlabs_com_chave_continua_passando_da_validacao(client, tmp_path, monkeypatch):
    """Nao-regressao explicita do escopo estreito desta correcao:
    elevenlabs (stub, chave PROPRIA, sem uso duplo) continua exatamente
    como antes - passa da validacao com a chave presente, sem o bloqueio
    extra que so' se aplica a openai."""
    projetos_dir = tmp_path / "projetos"
    _criar_projeto_com_roteiro_aprovado(projetos_dir, "caso_elevenlabs")
    (projetos_dir / "caso_elevenlabs" / "origem_audio.json").write_text(
        json.dumps({"origem": "tts", "provedor": "elevenlabs", "voz": "Rachel"}), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "chave-elevenlabs-fake")
    monkeypatch.setattr(server, "_disparar_etapa4", lambda *a, **k: None)

    resposta = client.post("/projetos/caso_elevenlabs/gerar_audio")

    assert resposta.status_code == 202


def test_tela_revisao_openai_desabilitado_mesmo_com_chave(client, tmp_path, monkeypatch):
    """GET /revisar_roteiro nunca pode oferecer 'openai' como opcao
    habilitada de TTS, mesmo com OPENAI_API_KEY setada pro provedor de
    imagem. Precisa de ALGUMA chave TTS real configurada tambem (google
    aqui) - senao o bloco de TTS inteiro fica oculto (`algum_tts_configurado`
    e' False so' com a chave ambigua, comportamento existente da tela,
    fora do escopo desta correcao) e o dropdown nem chega a renderizar."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_tela"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "roteiro.md").write_text("Roteiro gerado.", encoding="utf-8")
    (pasta / "job.json").write_text(
        json.dumps({"nome": "caso_tela", "status": "aguardando_revisao", "etapa_atual": "roteiro"}), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-chave-real-usada-so-pra-imagem")
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "chave-google-fake")

    pagina = client.get("/projetos/caso_tela/revisar_roteiro").get_data(as_text=True)

    assert 'value="openai" disabled' in pagina
    assert 'value="google" disabled' not in pagina
    assert "ainda não implementado" in pagina


def test_tela_revisao_elevenlabs_habilitado_com_chave_continua_igual(client, tmp_path, monkeypatch):
    """Nao-regressao: elevenlabs com chave configurada continua aparecendo
    HABILITADO no dropdown (comportamento antigo, fora do escopo desta
    correcao)."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_tela_elevenlabs"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "roteiro.md").write_text("Roteiro gerado.", encoding="utf-8")
    (pasta / "job.json").write_text(
        json.dumps({"nome": "caso_tela_elevenlabs", "status": "aguardando_revisao", "etapa_atual": "roteiro"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "chave-elevenlabs-fake")

    pagina = client.get("/projetos/caso_tela_elevenlabs/revisar_roteiro").get_data(as_text=True)

    assert 'value="elevenlabs" disabled' not in pagina
