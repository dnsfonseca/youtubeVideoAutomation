"""Testes das rotas da tela de thumbnail (Grupo G, Etapa 7): /projetos/<id>/thumbnail
e as acoes POST (upload de sujeito, remover sujeito, gerar briefing,
salvar briefing, gerar/excluir/escolher composicao) + as rotas de imagem
(protecao contra path traversal).

Sessao de simplificacao da Etapa 7 (ver HISTORICO_BUGS.md): os 5 templates
de composicao via Pillow (scripts/thumbnail_templates.py) foram removidos
por inteiro, junto do scan de cenario (thumbnail/candidatos_cena/) e do
recorte de sujeito via rembg. Os testes que cobriam esse caminho saem
daqui - `/thumbnail/renderizar` e `/thumbnail/salvar_textos` nao existem
mais; `/thumbnail/escolher_template` virou `/thumbnail/escolher_composicao`
(valida contra arquivo em disco, nao contra nome de template fixo); novas
rotas `/thumbnail/excluir_composicao` e `/thumbnail/salvar_briefing`.

Testes puros do Grupo C (briefing) vivem em tests/test_thumbnail_briefing.py
- aqui cobre so' a integracao via rota.

CLAUDE.md secao 8 - nenhuma chamada real a Anthropic/OpenAI: os testes que
tocam essas chamadas usam `cliente=`/monkeypatch fake."""

import io
import json
import re

from PIL import Image

import server


def _criar_projeto_thumbnail(tmp_path, nome, status="aguardando_thumbnail", com_metadados=True, com_sujeitos=False):
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "links.txt").write_text("https://www.youtube.com/watch?v=abc", encoding="utf-8")
    (pasta / "clipes").mkdir()
    (pasta / "clipes" / "indice.json").write_text("[]", encoding="utf-8")
    (pasta / "job.json").write_text(
        json.dumps({"nome": nome, "status": status, "etapa_atual": "thumbnail"}), encoding="utf-8"
    )
    pasta_thumbnail = pasta / "thumbnail"
    pasta_thumbnail.mkdir()

    if com_metadados:
        (pasta_thumbnail / "metadados.json").write_text(
            json.dumps(
                {
                    "title": ["A", "B", "C"],
                    "description": "d",
                    "tags": [],
                    "thumbnail": {
                        "subject_name": "Fulano",
                        "headline": "O CASO",
                        "emphasis_word": "",
                        "secondary": "",
                        "accent": "red",
                        "censor": False,
                        "background_prompt": "",
                        "briefing_completo": "",
                    },
                }
            ),
            encoding="utf-8",
        )

    if com_sujeitos:
        pasta_sujeitos = pasta_thumbnail / "sujeitos"
        pasta_sujeitos.mkdir()
        Image.new("RGB", (200, 300), (10, 20, 30)).save(pasta_sujeitos / "hero.jpg")
        (pasta_sujeitos / "sujeitos.json").write_text(
            json.dumps({"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": None}), encoding="utf-8"
        )

    return projetos_dir, pasta


def _criar_composicao(pasta, nome_arquivo, cor=(1, 2, 3)):
    pasta_previews = pasta / "thumbnail" / "previews"
    pasta_previews.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1536, 864), cor).save(pasta_previews / nome_arquivo)


# ---------------------------------------------------------------------------
# GET /projetos/<id>/thumbnail
# ---------------------------------------------------------------------------


def test_tela_thumbnail_redireciona_se_status_invalido(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_status_errado", status="aguardando_legendas")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_status_errado/thumbnail")

    assert resposta.status_code == 302
    assert "/status/caso_status_errado" in resposta.headers["Location"]


def test_tela_thumbnail_renderiza_briefing_e_sujeitos_declarados(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_ok", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_ok/thumbnail")

    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "hero.jpg" in corpo
    assert "vitima" in corpo
    assert 'id="campo-briefing"' in corpo
    assert 'id="campo-template"' in corpo


def test_tela_thumbnail_mostra_bloco_de_leitura_do_conceito_visual(client, tmp_path, monkeypatch):
    """GRUPO I (sessao "conceito visual", Parte 2): o conceito aparece como
    bloco de LEITURA acima do textarea do briefing - sem campo editavel
    proprio (a fonte canonica editavel continua so' o briefing_completo)."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_conceito_visual")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["conceito_visual"] = {
        "elemento_principal": "the doorbell camera",
        "tipo_elemento": "camera_filmagem",
        "acao_ou_momento": "the masked figure reaching up to block the lens",
        "revelacao": "exposing a tattoo on his wrist",
        "papel_na_composicao": "apoio",
    }
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")

    corpo = client.get("/projetos/caso_conceito_visual/thumbnail").get_data(as_text=True)

    assert "the doorbell camera" in corpo
    assert "the masked figure reaching up to block the lens" in corpo
    assert "exposing a tattoo on his wrist" in corpo
    # nao ha' <input>/<textarea> proprio pro conceito - so' o bloco de
    # leitura acima do textarea real (id="campo-briefing").
    pos_conceito = corpo.index("the doorbell camera")
    pos_textarea = corpo.index('id="campo-briefing"')
    assert pos_conceito < pos_textarea


def test_tela_thumbnail_sem_conceito_visual_nao_mostra_bloco(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_sem_conceito_visual")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    corpo = client.get("/projetos/caso_sem_conceito_visual/thumbnail").get_data(as_text=True)

    assert "Conceito visual (extraído automaticamente" not in corpo


def test_tela_thumbnail_prefeenche_textarea_do_briefing_e_mostra_template(client, tmp_path, monkeypatch):
    """Se ja' houver briefing persistido em metadados.json, o textarea vem
    preenchido no carregamento da tela (server-side, Jinja) - nao depende
    do JS pra isso, so' o botao "Gerar/regenerar" usa JS."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_briefing_prefill")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_completo"] = "Create a 16:9 dramatic true-crime YouTube thumbnail..."
    metadados["thumbnail"]["briefing_template"] = "DUOTONE_DOSSIER"
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")

    corpo = client.get("/projetos/caso_briefing_prefill/thumbnail").get_data(as_text=True)

    assert "Create a 16:9 dramatic true-crime YouTube thumbnail..." in corpo
    assert "DUOTONE_DOSSIER" in corpo


def test_tela_thumbnail_nao_sugere_template_stale_que_deixou_de_ser_elegivel(client, tmp_path, monkeypatch):
    """CORRECAO (bug real reportado): `briefing_template` persistido em
    metadados.json vem de uma geracao ANTERIOR (ex: o Grupo D/C automatico
    que roda antes de qualquer sujeito ser enviado, gravando
    "EVIDENCE_SCENE") - se o usuario depois envia 2 fotos que tornam OUTRO
    template elegivel (e EVIDENCE_SCENE inelegivel, regra de seguranca de
    `templates_elegiveis`), a tela nao pode continuar sugerindo/pre-
    selecionando o valor stale. Reproduz o cenario real do bug report:
    hero=investigador + secondary=vitima -> unico elegivel e'
    INVESTIGATOR_UPDATE, tem que ser o sugerido, nunca EVIDENCE_SCENE."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_sugestao_stale")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_template"] = "EVIDENCE_SCENE"
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")
    pasta_sujeitos = pasta / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True)
    Image.new("RGB", (200, 300), (10, 20, 30)).save(pasta_sujeitos / "hero.jpg")
    Image.new("RGB", (200, 300), (40, 50, 60)).save(pasta_sujeitos / "secondary.jpg")
    (pasta_sujeitos / "sujeitos.json").write_text(
        json.dumps(
            {
                "hero": {"arquivo": "hero.jpg", "papel": "investigador"},
                "secondary": {"arquivo": "secondary.jpg", "papel": "vitima"},
            }
        ),
        encoding="utf-8",
    )

    corpo = client.get("/projetos/caso_sugestao_stale/thumbnail").get_data(as_text=True)

    trecho_investigator = re.search(r'<option value="INVESTIGATOR_UPDATE"[^>]*>', corpo).group(0)
    trecho_evidence = re.search(r'<option value="EVIDENCE_SCENE"[^>]*>', corpo).group(0)
    assert "selected" in trecho_investigator
    assert "disabled" not in trecho_investigator
    assert "disabled" in trecho_evidence
    assert "selected" not in trecho_evidence


def test_tela_thumbnail_dropdown_de_papel_lista_todos_os_papeis_validos(client, tmp_path, monkeypatch):
    """Investigacao do bug de papel divergente (HISTORICO_BUGS.md): a
    lista canonica de papeis (thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS) tem
    6 valores, inclusive "condenado" - o dropdown tem que oferecer os 6,
    nunca so' um subconjunto (papel persistido fora da lista do dropdown
    faz o <select> cair no primeiro item, parte do sintoma observado)."""
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_dropdown_papeis", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    corpo = client.get("/projetos/caso_dropdown_papeis/thumbnail").get_data(as_text=True)

    for papel in server.thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS:
        assert f'value="{papel}"' in corpo, f"papel '{papel}' ausente do dropdown"
    assert server.thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS == (
        "vitima", "suspeito", "condenado", "investigador", "testemunha", "outro",
    )


def test_tela_thumbnail_sem_metadados_nao_quebra(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_sem_metadados", com_metadados=False)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_sem_metadados/thumbnail")

    assert resposta.status_code == 200


def test_tela_thumbnail_projeto_inexistente_redireciona(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    resposta = client.get("/projetos/nao_existe/thumbnail")
    assert resposta.status_code == 302


def test_tela_thumbnail_sem_chave_openai_nao_quebra_projeto_antigo(client, tmp_path, monkeypatch):
    """Projeto com a flag de thumbnail ligada (ou criado antes da checagem
    de chave existir) e sem OPENAI_API_KEY nao pode quebrar - a Etapa 7
    so' informa a ausencia da chave, o briefing continua disponivel pra
    uso externo (CLAUDE.md secao 5.85)."""
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_projeto_antigo_sem_chave")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resposta = client.get("/projetos/caso_projeto_antigo_sem_chave/thumbnail")
    corpo = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'id="btn-composicao-ia"' not in corpo
    assert "OPENAI_API_KEY" in corpo


# ---------------------------------------------------------------------------
# GET /projetos/<id>/thumbnail - etapa 7 falhou
# ---------------------------------------------------------------------------


def test_tela_thumbnail_etapa7_falhou_explica_falha_e_oferece_retry(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_falhou", com_metadados=False)
    (pasta / "job.json").write_text(
        json.dumps(
            {
                "nome": "caso_falhou",
                "status": "aguardando_thumbnail",
                "etapa_atual": "thumbnail",
                "etapa7_falhou": True,
                "mensagem_usuario": "scripts/7_thumbnail.py terminou com codigo 1.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_falhou/thumbnail")
    corpo = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "preparação automática da thumbnail falhou" in corpo
    assert "scripts/7_thumbnail.py terminou com codigo 1." in corpo
    assert "Tentar novamente" in corpo
    assert "/projetos/caso_falhou/gerar_thumbnail" in corpo


def test_tela_thumbnail_etapa7_ok_nao_mostra_banner_de_falha(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_etapa7_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    corpo = client.get("/projetos/caso_etapa7_ok/thumbnail").get_data(as_text=True)

    assert "preparação automática da thumbnail falhou" not in corpo


# ---------------------------------------------------------------------------
# GET /projetos/<id>/thumbnail?modo=readonly (refinamento "pipeline
# clicavel")
# ---------------------------------------------------------------------------


def test_tela_thumbnail_modo_readonly_com_pasta_thumbnail_retorna_200(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_thumb_readonly", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_thumb_readonly/thumbnail?modo=readonly")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Modo visualização" in pagina
    assert "uploadSujeito" not in pagina


def test_tela_thumbnail_modo_readonly_mostra_final_jpg_sem_forcar_aspect_ratio(client, tmp_path, monkeypatch):
    """O modo readonly exibe thumbnail/final.jpg na proporcao real (sem
    aspect-ratio/object-fit forcado por CSS inline na propria card) - a
    imagem pode ter vindo da composicao por IA em qualquer proporcao."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_thumb_final_readonly", status="concluido")
    Image.new("RGB", (1536, 864), (10, 10, 10)).save(pasta / "thumbnail" / "final.jpg")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_thumb_final_readonly/thumbnail?modo=readonly")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Thumbnail escolhida" in pagina
    assert "/thumbnail/arquivo/final.jpg" in pagina
    assert "aspect-ratio" not in pagina[pagina.index("Thumbnail escolhida") : pagina.index("Thumbnail escolhida") + 400]


def test_tela_thumbnail_modo_readonly_projeto_concluido_mostra_dois_botoes(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_thumb_dois_botoes", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    pagina = client.get("/projetos/caso_thumb_dois_botoes/thumbnail?modo=readonly").get_data(as_text=True)

    assert "Voltar à conclusão" in pagina
    assert "Voltar aos projetos" in pagina


def test_tela_thumbnail_modo_readonly_sem_pasta_thumbnail_redireciona(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_sem_pasta_thumb"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(json.dumps({"status": "concluido", "etapa_atual": "thumbnail"}), encoding="utf-8")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_sem_pasta_thumb/thumbnail?modo=readonly")

    assert resposta.status_code == 302
    assert "/status/caso_sem_pasta_thumb" in resposta.headers["Location"]


def test_tela_thumbnail_status_aguardando_thumbnail_ignora_modo_readonly(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_aguardando_ignora_readonly")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    pagina = client.get(
        "/projetos/caso_aguardando_ignora_readonly/thumbnail?modo=readonly"
    ).get_data(as_text=True)

    assert "Modo visualização" not in pagina
    assert "uploadSujeito" in pagina


# ---------------------------------------------------------------------------
# GET /projetos/<id>/thumbnail - Grupo E: grid populado a partir do disco,
# sem depender de geracao na mesma sessao de pagina.
# ---------------------------------------------------------------------------


def test_tela_thumbnail_grid_populado_com_composicoes_ja_existentes_em_disco(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_grid_persistente")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_composicao(pasta, "composicao_ia_01.jpg")
    _criar_composicao(pasta, "composicao_ia_02.jpg")

    corpo = client.get("/projetos/caso_grid_persistente/thumbnail").get_data(as_text=True)

    assert "composicao_ia_01.jpg" in corpo
    assert "composicao_ia_02.jpg" in corpo
    assert 'id="bloco-previews"' in corpo
    # bloco nao pode estar escondido (hidden) quando ha' composicoes
    inicio = corpo.index('id="bloco-previews"')
    tag_completa = corpo[max(0, inicio - 200) : inicio + 50]
    assert "hidden" not in tag_completa


def test_tela_thumbnail_grid_vazio_fica_escondido(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_grid_vazio")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    corpo = client.get("/projetos/caso_grid_vazio/thumbnail").get_data(as_text=True)

    inicio = corpo.index('id="bloco-previews"')
    tag_completa = corpo[inicio : inicio + 50]
    assert "hidden" in tag_completa


# ---------------------------------------------------------------------------
# GET /projetos/<id>/thumbnail - Grupo F: seletor de template, EVIDENCE_SCENE
# nunca elegivel com sujeito enviado.
# ---------------------------------------------------------------------------


def test_tela_thumbnail_evidence_scene_desabilitado_quando_ha_sujeito(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_evidence_desabilitado", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    corpo = client.get("/projetos/caso_evidence_desabilitado/thumbnail").get_data(as_text=True)

    inicio_opcao = corpo.index('value="EVIDENCE_SCENE"')
    tag_opcao = corpo[inicio_opcao : inicio_opcao + 400]
    assert "disabled" in tag_opcao
    # motivo visivel, nao escondido (title=tooltip do <option>)
    assert "title=" in tag_opcao


def test_tela_thumbnail_evidence_scene_habilitado_sem_sujeito(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_evidence_habilitado", com_sujeitos=False)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    corpo = client.get("/projetos/caso_evidence_habilitado/thumbnail").get_data(as_text=True)

    inicio_opcao = corpo.index('value="EVIDENCE_SCENE"')
    tag_opcao = corpo[inicio_opcao : inicio_opcao + 200]
    assert "disabled" not in tag_opcao


# ---------------------------------------------------------------------------
# POST /thumbnail/* - guard de status: as rotas de mutacao recusam fora de
# "aguardando_thumbnail", mesmo chamadas direto.
# ---------------------------------------------------------------------------


def test_thumbnail_upload_sujeito_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_upload_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_upload_status_errado/thumbnail/upload_sujeito",
        data={"foto": (io.BytesIO(b"fake"), "foto.jpg"), "slot": "hero", "papel": "vitima"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_thumbnail_remover_sujeito_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_remover_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_remover_status_errado/thumbnail/remover_sujeito", json={"slot": "hero"}
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_thumbnail_gerar_briefing_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_briefing_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_briefing_status_errado/thumbnail/gerar_briefing")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_thumbnail_salvar_briefing_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_salvar_briefing_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_salvar_briefing_status_errado/thumbnail/salvar_briefing",
        json={"briefing_completo": "x"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_thumbnail_escolher_composicao_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_escolher_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_composicao(pasta, "composicao_ia_01.jpg")

    resposta = client.post(
        "/projetos/caso_escolher_status_errado/thumbnail/escolher_composicao",
        json={"arquivo": "composicao_ia_01.jpg"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_thumbnail_excluir_composicao_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_excluir_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_composicao(pasta, "composicao_ia_01.jpg")

    resposta = client.post(
        "/projetos/caso_excluir_status_errado/thumbnail/excluir_composicao",
        json={"arquivo": "composicao_ia_01.jpg"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


# ---------------------------------------------------------------------------
# POST /thumbnail/upload_sujeito
# ---------------------------------------------------------------------------


def test_upload_sujeito_sem_arquivo_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_upload")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_upload/thumbnail/upload_sujeito",
        data={"slot": "hero", "papel": "vitima"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "arquivo_ausente"


def test_upload_sujeito_slot_invalido_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_upload_slot")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_upload_slot/thumbnail/upload_sujeito",
        data={"foto": (io.BytesIO(b"fake"), "foto.jpg"), "slot": "terciario", "papel": "vitima"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "slot_invalido"


def test_upload_sujeito_papel_invalido_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_upload_papel")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_upload_papel/thumbnail/upload_sujeito",
        data={"foto": (io.BytesIO(b"fake"), "foto.jpg"), "slot": "hero", "papel": "vilao"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "papel_invalido"


def test_upload_sujeito_extensao_invalida_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_upload_ext")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_upload_ext/thumbnail/upload_sujeito",
        data={"foto": (io.BytesIO(b"conteudo"), "arquivo.txt"), "slot": "hero", "papel": "vitima"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "extensao_invalida"


def test_upload_sujeito_sucesso_hero_persiste_papel_sem_recorte(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_upload_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    buffer = io.BytesIO()
    Image.new("RGB", (200, 300), (10, 20, 30)).save(buffer, format="JPEG")
    buffer.seek(0)

    resposta = client.post(
        "/projetos/caso_upload_ok/thumbnail/upload_sujeito",
        data={"foto": (buffer, "minha_foto.jpg"), "slot": "hero", "papel": "vitima"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["slot"] == "hero"
    assert dados["papel"] == "vitima"
    assert dados["arquivo"] == "hero.jpg"
    assert (pasta / "thumbnail" / "sujeitos" / "hero.jpg").exists()
    # sem recorte nenhum - nao existe mais thumbnail/sujeito.* nem
    # thumbnail/sujeito_origem.json (removidos na simplificacao da Etapa 7).
    assert not (pasta / "thumbnail" / "sujeito.jpg").exists()
    assert not (pasta / "thumbnail" / "sujeito.png").exists()
    assert not (pasta / "thumbnail" / "sujeito_origem.json").exists()
    sujeitos = json.loads((pasta / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    assert sujeitos == {"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": None}


def test_upload_sujeito_secondary_nao_apaga_hero(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_upload_dois", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    buffer = io.BytesIO()
    Image.new("RGB", (200, 300), (50, 60, 70)).save(buffer, format="JPEG")
    buffer.seek(0)

    resposta = client.post(
        "/projetos/caso_upload_dois/thumbnail/upload_sujeito",
        data={"foto": (buffer, "outra_foto.jpg"), "slot": "secondary", "papel": "suspeito"},
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 200
    sujeitos = json.loads((pasta / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    assert sujeitos["hero"] == {"arquivo": "hero.jpg", "papel": "vitima"}
    assert sujeitos["secondary"] == {"arquivo": "secondary.jpg", "papel": "suspeito"}


# ---------------------------------------------------------------------------
# POST /thumbnail/remover_sujeito
# ---------------------------------------------------------------------------


def test_remover_sujeito_slot_invalido_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_remover_invalido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_remover_invalido/thumbnail/remover_sujeito", json={"slot": "terciario"}
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "slot_invalido"


def test_remover_sujeito_sucesso_esvazia_slot(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_remover_ok", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_remover_ok/thumbnail/remover_sujeito", json={"slot": "hero"})

    assert resposta.status_code == 200
    assert resposta.get_json()["sucesso"] is True
    sujeitos = json.loads((pasta / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    assert sujeitos["hero"] is None


# ---------------------------------------------------------------------------
# POST /thumbnail/atualizar_papel_sujeito - correcao de bug: trocar o papel
# no dropdown de um slot que ja tem foto precisa persistir sem exigir novo
# upload (ver HISTORICO_BUGS.md).
# ---------------------------------------------------------------------------


def test_atualizar_papel_sujeito_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(
        tmp_path, "caso_papel_status_errado", status="aguardando_legendas", com_sujeitos=True
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_papel_status_errado/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "suspeito"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_atualizar_papel_sujeito_slot_invalido_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_papel_slot_invalido", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_papel_slot_invalido/thumbnail/atualizar_papel_sujeito",
        json={"slot": "terciario", "papel": "suspeito"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "slot_invalido"


def test_atualizar_papel_sujeito_papel_invalido_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_papel_papel_invalido", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_papel_papel_invalido/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "vilao"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "papel_invalido"


def test_atualizar_papel_sujeito_sem_foto_nao_persiste(client, tmp_path, monkeypatch):
    """Slot ainda sem foto enviada: nao ha' nada pra' persistir - o valor
    escolhido so' passa a valer no proximo upload (que ja manda o dropdown
    atual)."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_papel_sem_foto")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_papel_sem_foto/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "suspeito"},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["persistido"] is False
    assert not (pasta / "thumbnail" / "sujeitos" / "sujeitos.json").exists()


def test_atualizar_papel_sujeito_persiste_sem_reenviar_foto(client, tmp_path, monkeypatch):
    """Causa raiz do bug: o dropdown so' persistia o papel se o usuario
    reenviasse a foto (uploadSujeito). Esta rota persiste SO' o papel,
    reaproveitando o arquivo ja salvo em disco."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_papel_ok", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_papel_ok/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "condenado"},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["persistido"] is True
    assert dados["papel"] == "condenado"
    sujeitos = json.loads((pasta / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    # O arquivo original (do fixture com_sujeitos=True) continua o mesmo -
    # a foto nao precisou ser reenviada.
    assert sujeitos["hero"] == {"arquivo": "hero.jpg", "papel": "condenado"}


def test_atualizar_papel_sujeito_sobrevive_a_reload(client, tmp_path, monkeypatch):
    """Depois de persistir, um novo GET na tela mostra o texto ao lado da
    miniatura E o dropdown pre-selecionado com o MESMO valor - nunca
    divergentes."""
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_papel_reload", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    client.post(
        "/projetos/caso_papel_reload/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "suspeito"},
    )
    resposta = client.get("/projetos/caso_papel_reload/thumbnail")
    html = resposta.get_data(as_text=True)

    assert "papel: <span id=\"papel-atual-hero\">suspeito</span>" in html
    assert 'id="papel-hero" data-tem-foto="true"' in html
    assert '<option value="suspeito" selected' in html


def test_atualizar_papel_sujeito_recalcula_elegibilidade_arrow_trio(client, tmp_path, monkeypatch):
    """vitima (hero) + investigador (secondary) trocado pra' suspeito deve
    tornar ARROW_TRIO elegivel imediatamente, sem novo upload."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_papel_elegibilidade")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta_sujeitos = pasta / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True)
    Image.new("RGB", (200, 300), (10, 20, 30)).save(pasta_sujeitos / "hero.jpg")
    Image.new("RGB", (200, 300), (40, 50, 60)).save(pasta_sujeitos / "secondary.jpg")
    (pasta_sujeitos / "sujeitos.json").write_text(
        json.dumps(
            {
                "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
                "secondary": {"arquivo": "secondary.jpg", "papel": "investigador"},
            }
        ),
        encoding="utf-8",
    )

    resposta = client.post(
        "/projetos/caso_papel_elegibilidade/thumbnail/atualizar_papel_sujeito",
        json={"slot": "secondary", "papel": "suspeito"},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert "ARROW_TRIO" in dados["templates_elegiveis"]
    assert "INVESTIGATOR_UPDATE" not in dados["templates_elegiveis"]
    # Desempate deterministico e explicito (thumbnail_briefing.
    # ORDEM_PREFERENCIA_TEMPLATE): entre ARROW_TRIO e DUOTONE_DOSSIER
    # empatados, a sugestao sempre e' ARROW_TRIO - nunca depende de qual
    # ordem `templates_elegiveis` construiu a tupla internamente.
    assert dados["template_sugerido"] == "ARROW_TRIO"


def test_atualizar_papel_sujeito_marca_briefing_desatualizado(client, tmp_path, monkeypatch):
    """Papel mudou o significado do sujeito - um briefing ja gerado nao
    pode continuar sendo tratado como valido."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_papel_briefing_stale", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    caminho_metadados = pasta / "thumbnail" / "metadados.json"
    metadados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_completo"] = "um briefing ja gerado descrevendo a vitima..."
    caminho_metadados.write_text(json.dumps(metadados), encoding="utf-8")

    resposta = client.post(
        "/projetos/caso_papel_briefing_stale/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "suspeito"},
    )

    assert resposta.status_code == 200
    persistido = json.loads(caminho_metadados.read_text(encoding="utf-8"))
    assert persistido["thumbnail"]["briefing_desatualizado"] is True


def test_atualizar_papel_sujeito_sem_briefing_previo_nao_marca_flag(client, tmp_path, monkeypatch):
    """Sem briefing_completo previo (string vazia, valor padrao do
    fixture), nao ha' nada pra' invalidar."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_papel_sem_briefing_previo", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    client.post(
        "/projetos/caso_papel_sem_briefing_previo/thumbnail/atualizar_papel_sujeito",
        json={"slot": "hero", "papel": "suspeito"},
    )

    persistido = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert "briefing_desatualizado" not in persistido["thumbnail"]


def test_gerar_briefing_limpa_flag_desatualizado(client, tmp_path, monkeypatch):
    """Regenerar o briefing pela acao explicita ja existente ("Gerar /
    regenerar briefing") limpa a marca de desatualizado - o texto novo
    reflete o papel atual."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_papel_limpa_flag", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    caminho_metadados = pasta / "thumbnail" / "metadados.json"
    metadados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
    metadados["thumbnail"]["briefing_completo"] = "texto antigo"
    metadados["thumbnail"]["briefing_desatualizado"] = True
    caminho_metadados.write_text(json.dumps(metadados), encoding="utf-8")

    resposta = client.post("/projetos/caso_papel_limpa_flag/thumbnail/gerar_briefing")

    assert resposta.status_code == 200
    persistido = json.loads(caminho_metadados.read_text(encoding="utf-8"))
    assert "briefing_desatualizado" not in persistido["thumbnail"]


# ---------------------------------------------------------------------------
# POST /thumbnail/gerar_briefing
# ---------------------------------------------------------------------------


def test_gerar_briefing_sem_metadados_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_briefing_sem_metadados", com_metadados=False)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_briefing_sem_metadados/thumbnail/gerar_briefing")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "metadados_ausentes"


def test_gerar_briefing_sucesso_funciona_sem_chave_anthropic(client, tmp_path, monkeypatch):
    """Grupo C funciona 100% sem nenhuma API de imagem/texto configurada -
    e' a entrega que sempre funciona."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_briefing_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resposta = client.post("/projetos/caso_briefing_ok/thumbnail/gerar_briefing")

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["thumbnail"]["briefing_completo"]
    persistido = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["thumbnail"]["briefing_completo"]


def test_gerar_briefing_sem_headline_falha_e_reporta(client, tmp_path, monkeypatch):
    """Sem headline aprovado, a rota dedicada devolve sucesso=False de
    verdade (nao um "sucesso" com briefing vazio) - o JS mostra o erro
    real em vez de fingir que funcionou."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_briefing_sem_headline")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["headline"] = ""
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")

    resposta = client.post("/projetos/caso_briefing_sem_headline/thumbnail/gerar_briefing")

    assert resposta.status_code == 400
    dados = resposta.get_json()
    assert dados["sucesso"] is False
    assert dados["erro"] == "headline_ausente"


def test_gerar_briefing_com_template_forcado_elegivel_usa_o_escolhido(client, tmp_path, monkeypatch):
    """Grupo F: trocar a selecao do template na tela forca esse template
    especifico (sem chamar a IA de selecao) - a rota repassa `template` do
    corpo da requisicao como `template_forcado`."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_template_forcado")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    pasta_sujeitos = pasta / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True)
    Image.new("RGB", (200, 300), (10, 20, 30)).save(pasta_sujeitos / "hero.jpg")
    Image.new("RGB", (200, 300), (40, 50, 60)).save(pasta_sujeitos / "secondary.jpg")
    (pasta_sujeitos / "sujeitos.json").write_text(
        json.dumps(
            {
                "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
                "secondary": {"arquivo": "secondary.jpg", "papel": "suspeito"},
            }
        ),
        encoding="utf-8",
    )

    resposta = client.post(
        "/projetos/caso_template_forcado/thumbnail/gerar_briefing", json={"template": "ARROW_TRIO"}
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["thumbnail"]["briefing_template"] == "ARROW_TRIO"


def test_gerar_briefing_com_template_forcado_nao_elegivel_e_ignorado(client, tmp_path, monkeypatch):
    """Template fora do conjunto elegivel pro estado atual de sujeitos e'
    ignorado em silencio (nunca confia so' no frontend) - cai na selecao
    normal (EVIDENCE_SCENE, unico elegivel sem sujeito nenhum)."""
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_template_forcado_invalido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_template_forcado_invalido/thumbnail/gerar_briefing", json={"template": "ARROW_TRIO"}
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["thumbnail"]["briefing_template"] == "EVIDENCE_SCENE"


# ---------------------------------------------------------------------------
# POST /thumbnail/salvar_briefing - unico campo de texto editavel da tela
# ---------------------------------------------------------------------------


def test_salvar_briefing_persiste_o_texto(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_salvar_briefing")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_salvar_briefing/thumbnail/salvar_briefing",
        json={"briefing_completo": "Texto editado manualmente pelo usuario."},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["thumbnail"]["briefing_completo"] == "Texto editado manualmente pelo usuario."
    persistido = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["thumbnail"]["briefing_completo"] == "Texto editado manualmente pelo usuario."


def test_salvar_briefing_nunca_toca_em_outros_campos(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_salvar_briefing_preserva")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    metadados = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    metadados["thumbnail"]["headline"] = "HEADLINE ORIGINAL"
    metadados["thumbnail"]["briefing_template"] = "EVIDENCE_SCENE"
    (pasta / "thumbnail" / "metadados.json").write_text(json.dumps(metadados), encoding="utf-8")

    client.post(
        "/projetos/caso_salvar_briefing_preserva/thumbnail/salvar_briefing",
        json={"briefing_completo": "novo texto"},
    )

    persistido = json.loads((pasta / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["thumbnail"]["headline"] == "HEADLINE ORIGINAL"
    assert persistido["thumbnail"]["briefing_template"] == "EVIDENCE_SCENE"


def test_salvar_briefing_valor_nao_string_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_salvar_briefing_invalido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_salvar_briefing_invalido/thumbnail/salvar_briefing",
        json={"briefing_completo": 123},
    )

    assert resposta.status_code == 400


# ---------------------------------------------------------------------------
# POST /thumbnail/excluir_composicao + /thumbnail/escolher_composicao
# (Grupo D/E - composicoes acumuladas, nunca sobrescritas)
# ---------------------------------------------------------------------------


def test_excluir_composicao_invalida_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_excluir_invalida")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_excluir_invalida/thumbnail/excluir_composicao",
        json={"arquivo": "nao_existe.jpg"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "composicao_invalida"


def test_excluir_composicao_sucesso_remove_do_disco_e_devolve_lista_atualizada(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_excluir_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_composicao(pasta, "composicao_ia_01.jpg")
    _criar_composicao(pasta, "composicao_ia_02.jpg")

    resposta = client.post(
        "/projetos/caso_excluir_ok/thumbnail/excluir_composicao",
        json={"arquivo": "composicao_ia_01.jpg"},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["composicoes"] == ["composicao_ia_02.jpg"]
    assert not (pasta / "thumbnail" / "previews" / "composicao_ia_01.jpg").exists()
    assert (pasta / "thumbnail" / "previews" / "composicao_ia_02.jpg").exists()


def test_excluir_composicao_rejeita_path_traversal(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_excluir_traversal")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    (pasta / "entrada" / "segredo.txt").write_text("nao apagar", encoding="utf-8")

    resposta = client.post(
        "/projetos/caso_excluir_traversal/thumbnail/excluir_composicao",
        json={"arquivo": "../entrada/segredo.txt"},
    )

    assert resposta.status_code == 400
    assert (pasta / "entrada" / "segredo.txt").exists()


def test_escolher_composicao_invalida_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_escolha_invalida")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_escolha_invalida/thumbnail/escolher_composicao",
        json={"arquivo": "nao_existe.jpg"},
    )

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "composicao_invalida"


def test_fluxo_completo_gerar_e_escolher_composicao_conclui_job(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_fluxo_completo")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_composicao(pasta, "composicao_ia_01.jpg")

    resposta = client.post(
        "/projetos/caso_fluxo_completo/thumbnail/escolher_composicao",
        json={"arquivo": "composicao_ia_01.jpg"},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True
    assert dados["redirect"] == "/projetos/caso_fluxo_completo/concluido"

    assert (pasta / "thumbnail" / "final.jpg").exists()
    job_disco = json.loads((pasta / "job.json").read_text(encoding="utf-8"))
    assert job_disco["status"] == "concluido"
    assert job_disco["etapa_atual"] == "thumbnail"


# ---------------------------------------------------------------------------
# GET /thumbnail/imagem/<subpasta>/<arquivo> - protecao contra path traversal
# ---------------------------------------------------------------------------


def test_thumbnail_imagem_subpasta_fora_da_lista_retorna_404(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_imagem_subpasta")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_imagem_subpasta/thumbnail/imagem/entrada/links.txt")

    assert resposta.status_code == 404


def test_thumbnail_imagem_candidatos_cena_nao_e_mais_aceito(client, tmp_path, monkeypatch):
    """`candidatos_cena`/`candidatos_rosto` sairam da allowlist na sessao
    de simplificacao da Etapa 7 - nao existe mais scan de cenario nem
    identificacao de rosto."""
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_imagem_cena_removida")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_imagem_cena_removida/thumbnail/imagem/candidatos_cena/x.jpg")

    assert resposta.status_code == 404


def test_thumbnail_imagem_path_traversal_retorna_404(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_imagem_traversal")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_imagem_traversal/thumbnail/imagem/previews/..%2F..%2Fjob.json")

    assert resposta.status_code == 404


def test_thumbnail_imagem_arquivo_ausente_retorna_404(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_imagem_ausente")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_imagem_ausente/thumbnail/imagem/previews/nao_existe.jpg")

    assert resposta.status_code == 404


def test_thumbnail_imagem_sucesso_serve_arquivo(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_imagem_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    _criar_composicao(pasta, "composicao_ia_01.jpg")

    resposta = client.get("/projetos/caso_imagem_ok/thumbnail/imagem/previews/composicao_ia_01.jpg")

    assert resposta.status_code == 200


def test_thumbnail_arquivo_raiz_nome_fora_da_lista_retorna_404(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_arquivo_raiz")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    (pasta / "thumbnail" / "job.json.bak").write_text("segredo", encoding="utf-8")

    resposta = client.get("/projetos/caso_arquivo_raiz/thumbnail/arquivo/job.json.bak")

    assert resposta.status_code == 404


def test_thumbnail_arquivo_raiz_sucesso(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_arquivo_raiz_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    Image.new("RGB", (100, 100), (1, 2, 3)).save(pasta / "thumbnail" / "final.jpg")

    resposta = client.get("/projetos/caso_arquivo_raiz_ok/thumbnail/arquivo/final.jpg")

    assert resposta.status_code == 200


def test_thumbnail_arquivo_raiz_nao_aceita_mais_sujeito_recortado(client, tmp_path, monkeypatch):
    """sujeito.png/.jpg e sujeito_secundario.png/.jpg eram os recortes via
    rembg (Grupo B antigo) - nao existem mais, essa rota nao serve mais
    esses nomes (so' `final.jpg` sobrou)."""
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_arquivo_raiz_sem_recorte")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    Image.new("RGB", (100, 100), (1, 2, 3)).save(pasta / "thumbnail" / "sujeito_secundario.jpg")

    resposta = client.get("/projetos/caso_arquivo_raiz_sem_recorte/thumbnail/arquivo/sujeito_secundario.jpg")

    assert resposta.status_code == 404


# ---------------------------------------------------------------------------
# GET /thumbnail/sujeito_original/<slot> - foto ORIGINAL (sem recorte),
# usada pelo bloco de download do briefing e mandada direto pra composicao
# por IA
# ---------------------------------------------------------------------------


def test_sujeito_original_slot_invalido_retorna_404(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_original_slot_invalido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_original_slot_invalido/thumbnail/sujeito_original/terciario")

    assert resposta.status_code == 404


def test_sujeito_original_sem_upload_retorna_404(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_original_sem_upload")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_original_sem_upload/thumbnail/sujeito_original/hero")

    assert resposta.status_code == 404


def test_sujeito_original_sucesso_serve_arquivo(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_original_ok", com_sujeitos=True)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_original_ok/thumbnail/sujeito_original/hero")

    assert resposta.status_code == 200


# ---------------------------------------------------------------------------
# POST /thumbnail/regenerar_metadados - regenera so' o bloco thumbnail,
# preservando title/description/tags.
# ---------------------------------------------------------------------------


def test_regenerar_metadados_sem_chave_anthropic_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_regen_sem_chave")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resposta = client.post("/projetos/caso_regen_sem_chave/thumbnail/regenerar_metadados")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "sem_chave_anthropic"


def test_regenerar_metadados_fora_de_aguardando_thumbnail_retorna_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_regen_status_errado", status="concluido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    resposta = client.post("/projetos/caso_regen_status_errado/thumbnail/regenerar_metadados")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"


def test_regenerar_metadados_sucesso_devolve_thumbnail_atualizado(client, tmp_path, monkeypatch):
    projetos_dir, pasta = _criar_projeto_thumbnail(tmp_path, "caso_regen_ok")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")

    def _fake_regenerar(pasta_projeto, api_key, modelo):
        return {"sucesso": True, "thumbnail": {"headline": "NOVO"}, "metadados": {}}

    monkeypatch.setattr(server.thumbnail_etapa7, "regenerar_thumbnail_briefing", _fake_regenerar)

    resposta = client.post("/projetos/caso_regen_ok/thumbnail/regenerar_metadados")

    assert resposta.status_code == 200
    assert resposta.get_json()["thumbnail"]["headline"] == "NOVO"


def test_regenerar_metadados_falha_repassa_erro_com_400(client, tmp_path, monkeypatch):
    projetos_dir, _ = _criar_projeto_thumbnail(tmp_path, "caso_regen_falha")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    monkeypatch.setattr(
        server.thumbnail_etapa7, "regenerar_thumbnail_briefing",
        lambda *a, **k: {"sucesso": False, "erro": "roteiro_ausente"},
    )

    resposta = client.post("/projetos/caso_regen_falha/thumbnail/regenerar_metadados")

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "roteiro_ausente"
