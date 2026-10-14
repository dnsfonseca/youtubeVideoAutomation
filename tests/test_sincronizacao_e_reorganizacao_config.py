"""Testes de configuracao e encadeamento das Features A (sincronizacao
inteligente com IA) e B (reorganizacao manual de clipes):

- POST /novo persiste os 3 campos novos em entrada/configuracao_video.json,
  sem alterar o comportamento dos campos ja existentes (legendas_queimadas/
  com_musica_fundo).
- `_ler_configuracao_video` preserva retrocompatibilidade total: projeto
  sem o arquivo, ou com um configuracao_video.json anterior a esta feature
  (so' os 2 campos antigos), sempre cai nos defaults desligados.
- `_apos_etapa5_sucesso` (encadeamento pos-Etapa 5): comportamento default
  (ambas desligadas) chama `_encadear_etapa6` direto, identico a antes;
  Feature A ativa roda a sincronizacao antes de seguir para a Etapa 6;
  Feature B ativa pausa em `aguardando_reorganizacao` SEM chamar
  `_encadear_etapa6`.
"""

import json

import server


def _popen_fake(linhas=None, returncode=0):
    linhas = linhas or []

    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        return _ProcessoFake()

    return _fake


def _payload_basico(nome, **extra):
    payload = {
        "nome": nome,
        "perfil": "truecrime",
        "links": "https://youtube.com/watch?v=abc",
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# POST /novo - persistencia de configuracao_video.json
# ---------------------------------------------------------------------------


def test_novo_projeto_com_sincronizacao_ia_salva_config(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data=_payload_basico("caso_sync", sincronizacao_ia_ativa="on", sincronizacao_duracao="900"),
    )

    assert resposta.status_code == 302
    server._threads["caso_sync"].join(timeout=2)

    config = json.loads((projetos_dir / "caso_sync" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    assert config["sincronizacao_ia_ativa"] is True
    assert config["sincronizacao_duracao_s"] == 900
    assert config["reorganizacao_manual_ativa"] is False


def test_novo_projeto_com_reorganizacao_manual_salva_config(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post("/novo", data=_payload_basico("caso_reorg", reorganizacao_manual_ativa="on"))

    assert resposta.status_code == 302
    server._threads["caso_reorg"].join(timeout=2)

    config = json.loads((projetos_dir / "caso_reorg" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    assert config["reorganizacao_manual_ativa"] is True
    assert config["sincronizacao_ia_ativa"] is False


def test_novo_projeto_com_ambas_features_ativas_simultaneamente(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data=_payload_basico(
            "caso_ambas",
            sincronizacao_ia_ativa="on",
            sincronizacao_duracao="300",
            reorganizacao_manual_ativa="on",
        ),
    )

    assert resposta.status_code == 302
    server._threads["caso_ambas"].join(timeout=2)

    config = json.loads((projetos_dir / "caso_ambas" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    assert config["sincronizacao_ia_ativa"] is True
    assert config["sincronizacao_duracao_s"] == 300
    assert config["reorganizacao_manual_ativa"] is True


def test_novo_projeto_sem_ajustes_avancados_preserva_defaults_desligados(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post("/novo", data=_payload_basico("caso_default"))

    assert resposta.status_code == 302
    server._threads["caso_default"].join(timeout=2)

    config = json.loads((projetos_dir / "caso_default" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8"))
    assert config["sincronizacao_ia_ativa"] is False
    assert config["reorganizacao_manual_ativa"] is False
    assert config["sincronizacao_duracao_s"] == 600
    # Campos pre-existentes continuam funcionando identico a antes.
    assert config["legendas_queimadas"] is False
    assert config["com_musica_fundo"] is False


def test_novo_projeto_com_duracao_sincronizacao_invalida_cai_no_default(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data=_payload_basico("caso_duracao_invalida", sincronizacao_ia_ativa="on", sincronizacao_duracao="12345"),
    )

    assert resposta.status_code == 302
    server._threads["caso_duracao_invalida"].join(timeout=2)

    config = json.loads(
        (projetos_dir / "caso_duracao_invalida" / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config["sincronizacao_duracao_s"] == 600


# ---------------------------------------------------------------------------
# _ler_configuracao_video - retrocompatibilidade
# ---------------------------------------------------------------------------


def test_ler_configuracao_video_pasta_none_retorna_defaults():
    config = server._ler_configuracao_video(None)
    assert config == {
        "legendas_queimadas": False,
        "com_musica_fundo": False,
        "sincronizacao_ia_ativa": False,
        "sincronizacao_duracao_s": 600,
        "reorganizacao_manual_ativa": False,
        "palavras_alvo": 4000,
        "duracao_alvo_minutos": 25,
        "grayscale": False,
        "gerar_thumbnail": True,
    }


def test_ler_configuracao_video_arquivo_ausente_retorna_defaults(tmp_path):
    pasta_projeto = tmp_path / "projeto_sem_config"
    pasta_projeto.mkdir()
    config = server._ler_configuracao_video(pasta_projeto)
    assert config["sincronizacao_ia_ativa"] is False
    assert config["reorganizacao_manual_ativa"] is False


def test_ler_configuracao_video_arquivo_antigo_sem_campos_novos(tmp_path):
    """Projeto criado ANTES das Features A/B - configuracao_video.json so'
    tem os 2 campos historicos. Os 3 campos novos precisam cair no default
    desligado, nunca levantar KeyError."""
    pasta_projeto = tmp_path / "projeto_antigo"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"legendas_queimadas": True, "com_musica_fundo": False}), encoding="utf-8"
    )

    config = server._ler_configuracao_video(pasta_projeto)

    assert config["legendas_queimadas"] is True
    assert config["sincronizacao_ia_ativa"] is False
    assert config["reorganizacao_manual_ativa"] is False
    assert config["sincronizacao_duracao_s"] == 600


# ---------------------------------------------------------------------------
# _apos_etapa5_sucesso - encadeamento
# ---------------------------------------------------------------------------


def test_apos_etapa5_sem_features_chama_encadear_etapa6_direto(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_sem_features"
    pasta_projeto.mkdir()
    server.jobs["caso_sem_features"] = {"status": "aguardando_legendas", "etapa": "legendas", "log": []}

    chamadas = []
    monkeypatch.setattr(server, "_encadear_etapa6", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta)))

    server._apos_etapa5_sucesso("caso_sem_features", pasta_projeto)

    assert chamadas == [("caso_sem_features", pasta_projeto)]
    # Estado que _executar_etapa5 ja tinha persistido nao foi tocado.
    assert server.jobs["caso_sem_features"]["status"] == "aguardando_legendas"


def test_apos_etapa5_com_sincronizacao_ativa_roda_sync_e_segue_para_etapa6(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_sync"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"sincronizacao_ia_ativa": True, "sincronizacao_duracao_s": 300}), encoding="utf-8"
    )
    server.jobs["caso_sync"] = {"status": "aguardando_legendas", "etapa": "legendas", "log": []}

    chamadas_sync = []
    chamadas_etapa6 = []
    monkeypatch.setattr(
        server,
        "_executar_sincronizacao_ia",
        lambda projeto_id, pasta, duracao: chamadas_sync.append((projeto_id, pasta, duracao)),
    )
    monkeypatch.setattr(server, "_encadear_etapa6", lambda projeto_id, pasta: chamadas_etapa6.append((projeto_id, pasta)))

    server._apos_etapa5_sucesso("caso_sync", pasta_projeto)

    assert chamadas_sync == [("caso_sync", pasta_projeto, 300)]
    assert chamadas_etapa6 == [("caso_sync", pasta_projeto)]


def test_apos_etapa5_com_reorganizacao_ativa_pausa_sem_chamar_etapa6(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_reorg"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"reorganizacao_manual_ativa": True}), encoding="utf-8"
    )
    server.jobs["caso_reorg"] = {"status": "aguardando_legendas", "etapa": "legendas", "log": []}

    chamadas_etapa6 = []
    chamadas_thumbs = []
    monkeypatch.setattr(server, "_encadear_etapa6", lambda projeto_id, pasta: chamadas_etapa6.append((projeto_id, pasta)))
    monkeypatch.setattr(server, "_gerar_thumbnails_clipes_em_background", lambda pasta: chamadas_thumbs.append(pasta))

    server._apos_etapa5_sucesso("caso_reorg", pasta_projeto)

    assert chamadas_etapa6 == []
    assert chamadas_thumbs == [pasta_projeto]
    assert server.jobs["caso_reorg"]["status"] == "aguardando_reorganizacao"

    job_disco = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "aguardando_reorganizacao"
    assert job_disco["etapa_atual"] == "geracao_clipes"


def test_apos_etapa5_com_ambas_features_roda_sync_depois_pausa(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_ambas_encadeamento"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps({"sincronizacao_ia_ativa": True, "reorganizacao_manual_ativa": True}), encoding="utf-8"
    )
    server.jobs["caso_ambas_encadeamento"] = {"status": "aguardando_legendas", "etapa": "legendas", "log": []}

    ordem = []
    monkeypatch.setattr(
        server, "_executar_sincronizacao_ia", lambda projeto_id, pasta, duracao: ordem.append("sync")
    )
    monkeypatch.setattr(server, "_gerar_thumbnails_clipes_em_background", lambda pasta: ordem.append("thumbs"))
    monkeypatch.setattr(server, "_encadear_etapa6", lambda projeto_id, pasta: ordem.append("etapa6"))

    server._apos_etapa5_sucesso("caso_ambas_encadeamento", pasta_projeto)

    assert ordem == ["sync", "thumbs"]
    assert server.jobs["caso_ambas_encadeamento"]["status"] == "aguardando_reorganizacao"


def test_executar_sincronizacao_ia_sem_chave_pula_e_loga(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pasta_projeto = tmp_path / "caso_sem_chave"
    server.jobs["caso_sem_chave"] = {"status": "em_andamento", "log": []}

    chamado = []
    monkeypatch.setattr(server.sincronizador_visual, "sincronizar_projeto", lambda *a, **k: chamado.append(1))

    server._executar_sincronizacao_ia("caso_sem_chave", pasta_projeto, 600)

    assert chamado == []
    assert any("ANTHROPIC_API_KEY" in linha for linha in server.jobs["caso_sem_chave"]["log"])


def test_executar_sincronizacao_ia_falha_nao_levanta_excecao(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    pasta_projeto = tmp_path / "caso_falha_sync"
    server.jobs["caso_falha_sync"] = {"status": "em_andamento", "log": []}

    def _sincronizar_que_falha(*args, **kwargs):
        raise RuntimeError("falha simulada de API")

    monkeypatch.setattr(server.sincronizador_visual, "sincronizar_projeto", _sincronizar_que_falha)

    # Nao deve levantar excecao - Feature A nunca derruba o pipeline.
    server._executar_sincronizacao_ia("caso_falha_sync", pasta_projeto, 600)

    assert any("falhou" in linha.lower() for linha in server.jobs["caso_falha_sync"]["log"])


def test_executar_sincronizacao_ia_atualiza_detalhe_do_job_no_inicio_e_no_fim(tmp_path, monkeypatch):
    """Regressao (Grupo C/G3): antes desta correcao, job["detalhe"] ficava
    parado no texto da Etapa 5 durante toda a chamada de sincronizacao (pode
    levar dezenas de segundos com Vision) - a tela parecia travada mesmo com
    o polling funcionando. Agora "detalhe" reflete o que esta acontecendo."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    pasta_projeto = tmp_path / "caso_detalhe"
    server.jobs["caso_detalhe"] = {"status": "em_andamento", "detalhe": "5 clipes gerados com sucesso", "log": []}

    detalhes_vistos_durante_a_chamada = []

    def _sincronizar_capturando_detalhe(*args, **kwargs):
        detalhes_vistos_durante_a_chamada.append(server.jobs["caso_detalhe"]["detalhe"])
        return {"sucesso": True, "swaps_aplicados": 2, "ancoras_encontradas": 5, "custo_usd_total": 0.01}

    monkeypatch.setattr(server.sincronizador_visual, "sincronizar_projeto", _sincronizar_capturando_detalhe)

    server._executar_sincronizacao_ia("caso_detalhe", pasta_projeto, 600)

    # No meio da chamada, "detalhe" ja tinha sido trocado (nao ficou parado
    # no texto residual da Etapa 5).
    assert detalhes_vistos_durante_a_chamada == ["Sincronizando clipes com IA (Feature A)..."]
    # Ao final, reflete o resultado (nao fica preso no texto de "iniciando").
    assert "2 swap" in server.jobs["caso_detalhe"]["detalhe"]
