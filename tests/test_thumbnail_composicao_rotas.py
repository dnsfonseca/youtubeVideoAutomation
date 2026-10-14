"""Testes de rota da composicao completa por IA: POST
/projetos/<id>/thumbnail/gerar_composicao_ia + botao condicional a
OPENAI_API_KEY na tela de thumbnail + integracao com "escolher_composicao".
Nunca chama scripts.imagem.openai.gerar_composicao de verdade (CLAUDE.md
secao 8) - a rota e' mockada em server.imagem_openai.gerar_composicao.

Sessao de simplificacao da Etapa 7 (ver HISTORICO_BUGS.md): cada geracao
grava num arquivo SEQUENCIAL em thumbnail/previews/ (composicao_ia_01.jpg,
_02.jpg, ...) em vez de sobrescrever um unico composicao_ia.jpg fixo -
cada chamada custa dinheiro real, as tentativas acumulam pra' o usuario
comparar/escolher/excluir."""

import io
import json

from PIL import Image

from scripts import thumbnail_briefing
from tests.test_thumbnail_rotas import _criar_projeto_thumbnail


def _preparar_com_briefing_e_sujeitos(tmp_path, nome, status="aguardando_thumbnail"):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, nome, status=status, com_metadados=True, com_sujeitos=True)
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_completo"] = "Create a thumbnail with this person."
    # Fase 1 (correcao do estado do briefing): o fingerprint precisa
    # corresponder ao estado REAL de sujeitos.json que `_criar_projeto_
    # thumbnail(com_sujeitos=True)` grava (so' hero=vitima) - senao a
    # checagem de staleness (server.py:_briefing_stale) bloquearia TODOS
    # os testes deste arquivo como "legado sem fingerprint", que nao e' o
    # cenario que eles testam (esses testes simulam um briefing valido e
    # ATUALIZADO pro estado atual de sujeitos, nunca o caso stale).
    sujeitos = json.loads((pasta / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_subjects_fingerprint"] = thumbnail_briefing.calcular_fingerprint_sujeitos(sujeitos)
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")
    return projetos_dir, pasta


def _fake_gerar_composicao_sucesso(cor=(5, 5, 5)):
    def _fake(briefing, caminhos_fotos, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1536, 864), cor).save(output_path)
        return {"sucesso": True, "caminho": str(output_path), "custo_usd_estimado": 0.02}

    return _fake


# ---------------------------------------------------------------------------
# GET /thumbnail - botao so' ativo com OPENAI_API_KEY configurada
# ---------------------------------------------------------------------------


def test_tela_thumbnail_sem_chave_openai_nao_mostra_botao_ativo(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_sem_chave_openai")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    corpo = client.get("/projetos/caso_sem_chave_openai/thumbnail").get_data(as_text=True)

    assert 'id="btn-composicao-ia"' not in corpo
    assert "OPENAI_API_KEY" in corpo  # explicacao do requisito continua visivel


def test_tela_thumbnail_com_chave_openai_mostra_botao_ativo(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_com_chave_openai")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    corpo = client.get("/projetos/caso_com_chave_openai/thumbnail").get_data(as_text=True)

    assert 'id="btn-composicao-ia"' in corpo


# ---------------------------------------------------------------------------
# POST /thumbnail/gerar_composicao_ia
# ---------------------------------------------------------------------------


def test_gerar_composicao_ia_sem_chave_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_post_sem_chave")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resposta = client.post("/projetos/caso_post_sem_chave/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro_tipo"] == "sem_chave"


def test_gerar_composicao_ia_sem_briefing_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_post_sem_briefing", com_metadados=True, com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    # fixture ja' grava briefing_completo: "" (vazio) por padrao

    resposta = client.post("/projetos/caso_post_sem_briefing/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro_tipo"] == "briefing_ausente"


def test_gerar_composicao_ia_projeto_fora_de_revisao_recusa(client, tmp_path, monkeypatch):
    projetos_dir, _ = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_post_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    resposta = client.post("/projetos/caso_post_status_errado/thumbnail/gerar_composicao_ia")

    assert resposta.status_code != 200


def test_gerar_composicao_ia_sucesso_chama_com_fotos_na_ordem_e_devolve_preview_url(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_post_sucesso")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    chamadas = {}

    def _fake_gerar_composicao(briefing, caminhos_fotos, output_path, **kwargs):
        chamadas["briefing"] = briefing
        chamadas["nomes_fotos"] = [c.name for c in caminhos_fotos]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1536, 864), (5, 5, 5)).save(output_path)
        return {"sucesso": True, "caminho": str(output_path), "custo_usd_estimado": 0.02}

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao)

    resposta = client.post("/projetos/caso_post_sucesso/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert "preview_url" in dados
    assert dados["arquivo"] == "composicao_ia_01.jpg"
    assert chamadas["briefing"] == "Create a thumbnail with this person."
    assert chamadas["nomes_fotos"] == ["hero.jpg"]  # so' hero na fixture de _criar_projeto_thumbnail
    assert (pasta / "thumbnail" / "previews" / "composicao_ia_01.jpg").exists()


def test_gerar_composicao_ia_briefing_editado_no_corpo_e_persistido_antes_de_gerar(client, tmp_path, monkeypatch):
    """Grupo B (simplificacao da Etapa 7): se o usuario editou o texto do
    briefing na tela, a rota persiste esse valor ANTES de gerar - nao
    perde a edicao, e usa o texto editado (nao o que estava salvo antes)
    na chamada real."""
    projetos_dir, pasta = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_post_briefing_editado")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    chamadas = {}

    def _fake_gerar_composicao(briefing, caminhos_fotos, output_path, **kwargs):
        chamadas["briefing"] = briefing
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1536, 864), (5, 5, 5)).save(output_path)
        return {"sucesso": True, "caminho": str(output_path), "custo_usd_estimado": 0.02}

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao)

    resposta = client.post(
        "/projetos/caso_post_briefing_editado/thumbnail/gerar_composicao_ia",
        json={"briefing_completo": "Texto editado pelo usuario na tela."},
    )

    assert resposta.status_code == 200
    assert chamadas["briefing"] == "Texto editado pelo usuario na tela."
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert metadados["thumbnail"]["briefing_completo"] == "Texto editado pelo usuario na tela."


def test_gerar_composicao_ia_falha_repassa_motivo_real_sem_generico(client, tmp_path, monkeypatch):
    projetos_dir, _ = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_post_falha")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    def _fake_falha(briefing, caminhos_fotos, output_path, **kwargs):
        return {
            "sucesso": False,
            "erro_tipo": "content_policy_violation",
            "erro_mensagem": "Your request was rejected by the safety system.",
            "status_http": 400,
        }

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_falha)

    resposta = client.post("/projetos/caso_post_falha/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 400
    dados = resposta.get_json()
    assert dados["erro_tipo"] == "content_policy_violation"
    assert "safety system" in dados["mensagem"]


def test_gerar_composicao_ia_segunda_geracao_nao_sobrescreve_a_primeira(client, tmp_path, monkeypatch):
    """Grupo D (simplificacao da Etapa 7): cada geracao custa dinheiro
    real - a segunda chamada tem que gravar num arquivo NOVO, preservando
    o resultado da primeira (nunca mais composicao_ia.jpg fixo)."""
    projetos_dir, pasta = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_post_acumula")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao_sucesso((5, 5, 5)))
    primeira = client.post("/projetos/caso_post_acumula/thumbnail/gerar_composicao_ia").get_json()

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao_sucesso((9, 9, 9)))
    segunda = client.post("/projetos/caso_post_acumula/thumbnail/gerar_composicao_ia").get_json()

    assert primeira["arquivo"] == "composicao_ia_01.jpg"
    assert segunda["arquivo"] == "composicao_ia_02.jpg"
    assert (pasta / "thumbnail" / "previews" / "composicao_ia_01.jpg").exists()
    assert (pasta / "thumbnail" / "previews" / "composicao_ia_02.jpg").exists()

    # a primeira imagem continua intacta (nao foi sobrescrita pela segunda)
    with Image.open(pasta / "thumbnail" / "previews" / "composicao_ia_01.jpg") as imagem:
        assert imagem.convert("RGB").getpixel((0, 0)) == (5, 5, 5)
    with Image.open(pasta / "thumbnail" / "previews" / "composicao_ia_02.jpg") as imagem:
        assert imagem.convert("RGB").getpixel((0, 0)) == (9, 9, 9)


# ---------------------------------------------------------------------------
# Integracao com escolher_composicao - arquivo gerado pela composicao por
# IA e' aceito como qualquer outra composicao acumulada
# ---------------------------------------------------------------------------


def test_escolher_composicao_aceita_arquivo_gerado_pela_composicao_ia(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_escolher_composicao")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    pasta_previews = pasta / "thumbnail" / "previews"
    pasta_previews.mkdir(parents=True)
    Image.new("RGB", (1536, 864), (1, 2, 3)).save(pasta_previews / "composicao_ia_01.jpg")

    resposta = client.post(
        "/projetos/caso_escolher_composicao/thumbnail/escolher_composicao",
        json={"arquivo": "composicao_ia_01.jpg"},
    )

    assert resposta.status_code == 200
    assert resposta.get_json()["sucesso"] is True
    assert (pasta / "thumbnail" / "final.jpg").exists()


# ---------------------------------------------------------------------------
# FASE 1 (correcao do estado do briefing) - a rota bloqueia a composicao
# por IA quando o briefing persistido nao corresponde mais ao estado ATUAL
# de sujeitos.json (fingerprint), em vez de confiar so' na flag
# `briefing_desatualizado`. Ver scripts/thumbnail_briefing.
# calcular_fingerprint_sujeitos e server.py:_briefing_stale.
# ---------------------------------------------------------------------------


def _foto_jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (200, 300), (10, 20, 30)).save(buffer, format="JPEG")
    buffer.seek(0)
    return buffer


def test_gerar_composicao_ia_bloqueia_briefing_legado_sem_fingerprint(client, tmp_path, monkeypatch):
    """TESTE G (a nivel de rota): briefing persistido SEM
    `briefing_subjects_fingerprint` (legado - gerado antes desta protecao
    existir) nunca e' confiavel por padrao - a rota bloqueia em vez de
    mandar pra' composicao por IA."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_briefing_legado", com_metadados=True, com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_completo"] = "briefing antigo, gerado antes do fingerprint existir."
    # De proposito: SEM "briefing_subjects_fingerprint".
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")

    chamou_openai = {"vezes": 0}

    def _fake_gerar_composicao(*args, **kwargs):
        chamou_openai["vezes"] += 1
        return {"sucesso": True, "caminho": "nao deveria chegar aqui"}

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao)

    resposta = client.post("/projetos/caso_briefing_legado/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 400
    dados = resposta.get_json()
    assert dados["sucesso"] is False
    assert dados["erro_tipo"] == "briefing_desatualizado"
    assert chamou_openai["vezes"] == 0


def test_gerar_composicao_ia_bloqueia_quando_sujeitos_mudaram_apos_o_briefing_teste_h(client, tmp_path, monkeypatch):
    """TESTE H (Fase 1) - reproduz o caminho REAL que causou o bug (caso
    Nancy Guthrie):

    1. Etapa 7 roda automaticamente sem sujeitos -> briefing de
       EVIDENCE_SCENE gravado com o fingerprint do estado VAZIO (simula o
       que `_aplicar_briefing_grupo_c` grava de verdade nesse cenario).
    2. Upload de hero (vitima) via rota real `/thumbnail/upload_sujeito`.
    3. Upload de secondary (investigador) via a mesma rota.
    4. Chamada direta a' rota de composicao pela OpenAI SEM passar por
       "Gerar/regenerar briefing".

    Comportamento escolhido: BLOQUEAR (nunca regerar sozinho - custaria
    uma chamada de API real sem o usuario pedir, mesmo espirito de
    `thumbnail_atualizar_papel_sujeito`). O texto de EVIDENCE_SCENE NUNCA
    pode chegar em `imagem_openai.gerar_composicao`."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_teste_h", com_metadados=True, com_sujeitos=False)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    # Passo 1: briefing de EVIDENCE_SCENE gerado automaticamente, ANTES de
    # qualquer sujeito existir - fingerprint do estado {"hero": None,
    # "secondary": None}.
    caminho_metadados = pasta / "thumbnail" / "metadados.json"
    metadados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_completo"] = "EVIDENCE_SCENE prompt - no subjects available."
    metadados["thumbnail"]["briefing_template"] = "EVIDENCE_SCENE"
    metadados["thumbnail"]["briefing_subjects_fingerprint"] = thumbnail_briefing.calcular_fingerprint_sujeitos(
        {"hero": None, "secondary": None}
    )
    caminho_metadados.write_text(json.dumps(metadados), encoding="utf-8")

    # Passo 2: upload de hero (vitima) pela rota real.
    resposta_hero = client.post(
        "/projetos/caso_teste_h/thumbnail/upload_sujeito",
        data={"foto": (_foto_jpeg(), "hero.jpg"), "slot": "hero", "papel": "vitima"},
        content_type="multipart/form-data",
    )
    assert resposta_hero.status_code == 200

    # Passo 3: upload de secondary (investigador) pela rota real.
    resposta_secondary = client.post(
        "/projetos/caso_teste_h/thumbnail/upload_sujeito",
        data={"foto": (_foto_jpeg(), "secondary.jpg"), "slot": "secondary", "papel": "investigador"},
        content_type="multipart/form-data",
    )
    assert resposta_secondary.status_code == 200

    # Passo 4: composicao por IA DIRETO - nunca passou por "Gerar/regenerar
    # briefing" depois dos uploads.
    chamou_openai = {"vezes": 0}

    def _fake_gerar_composicao(*args, **kwargs):
        chamou_openai["vezes"] += 1
        return {"sucesso": True, "caminho": "nao deveria chegar aqui"}

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao)

    resposta = client.post("/projetos/caso_teste_h/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 400
    dados = resposta.get_json()
    assert dados["sucesso"] is False
    assert dados["erro_tipo"] == "briefing_desatualizado"
    # O ponto central do teste: a API de imagem NUNCA e' chamada com o
    # texto stale de EVIDENCE_SCENE.
    assert chamou_openai["vezes"] == 0


def test_gerar_composicao_ia_com_fingerprint_correspondente_nao_bloqueia(client, tmp_path, monkeypatch):
    """Contraprova do TESTE H: quando o fingerprint persistido CORRESPONDE
    ao estado atual de sujeitos.json (briefing gerado depois dos uploads,
    ou nunca mudou), a composicao segue normalmente - a checagem nova
    nunca bloqueia um briefing valido."""
    projetos_dir, _ = _preparar_com_briefing_e_sujeitos(tmp_path, "caso_fingerprint_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    import server

    monkeypatch.setattr(server.imagem_openai, "gerar_composicao", _fake_gerar_composicao_sucesso())

    resposta = client.post("/projetos/caso_fingerprint_ok/thumbnail/gerar_composicao_ia")

    assert resposta.status_code == 200
    assert resposta.get_json()["sucesso"] is True
