"""Testes da Feature B (reorganizacao manual de clipes - timeline horizontal
com drag livre): tela /projetos/<id>/reorganizar_clipes, POST
/reordenar_clipes, GET /thumb_clipe, GET /narracao_audio e GET
/preview_video. CLAUDE.md secao 8 - nenhuma chamada real a ffmpeg (sempre
monkeypatch em server.subprocess.run ou nas funcoes que o chamam)."""

import json

import pytest

import server


def _criar_projeto_com_clipes(
    tmp_path,
    nome,
    clipes,
    status="aguardando_reorganizacao",
    palavras=None,
    descricoes_vision=None,
):
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "clipes").mkdir(parents=True)
    (pasta / "clipes" / "indice.json").write_text(
        json.dumps({"clipes": clipes}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if descricoes_vision is not None:
        (pasta / "clipes" / "descricoes_vision.json").write_text(
            json.dumps(descricoes_vision, ensure_ascii=False), encoding="utf-8"
        )
    if palavras is not None:
        (pasta / "narracao_alinhamento.json").write_text(
            json.dumps({"palavras": palavras}, ensure_ascii=False), encoding="utf-8"
        )
    (pasta / "job.json").write_text(
        json.dumps({"projeto_id": nome, "status": status, "etapa_atual": "geracao_clipes"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return projetos_dir


def _clipe(clipe_id, duracao_s=8.0):
    return {"clipe_id": clipe_id, "arquivo": f"{clipe_id}.mp4", "duracao_s": duracao_s}


# ---------------------------------------------------------------------------
# GET /reorganizar_clipes
# ---------------------------------------------------------------------------


def test_reorganizar_clipes_redireciona_se_status_invalido(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_com_clipes(tmp_path, "caso_status_errado", [_clipe("c0")], status="aguardando_legendas")),
    )
    resposta = client.get("/projetos/caso_status_errado/reorganizar_clipes")
    assert resposta.status_code == 302
    assert "/status/caso_status_errado" in resposta.headers["Location"]


def test_reorganizar_clipes_renderiza_timeline_e_banco(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_com_clipes(
                tmp_path,
                "caso_ok",
                [_clipe("c0"), _clipe("c1")],
                descricoes_vision={"c0": "a bicycle"},
            )
        ),
    )

    resposta = client.get("/projetos/caso_ok/reorganizar_clipes")

    assert resposta.status_code == 200
    pagina = resposta.get_data(as_text=True)
    assert "c0" in pagina
    assert "c1" in pagina
    assert "a bicycle" in pagina
    assert "Reorganizar clipes" in pagina
    assert "timeline-track" in pagina
    assert "banco-grid" in pagina


def test_reorganizar_clipes_projeto_sem_dados_redireciona(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    resposta = client.get("/projetos/inexistente/reorganizar_clipes")
    assert resposta.status_code == 302


# ---------------------------------------------------------------------------
# GET /reorganizar_clipes - resultado da Feature A (sincronizacao com IA),
# GRUPO B da sessao de correcoes UX: antes desta sessao o resultado so'
# existia como uma linha de resumo no log efemero do job, nunca visivel
# nesta tela.
# ---------------------------------------------------------------------------


def test_reorganizar_carrega_log_se_existe(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_com_log", [_clipe("c0"), _clipe("c1")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    log = {
        "timestamp": "2026-09-02T00:00:00+00:00",
        "duracao_alvo_s": 600,
        "ancoras_encontradas": 1,
        "clipes_descritos": 2,
        "swaps_aplicados": [
            {
                "ancora_termo": "bicycle chase",
                "clipe_id": "c1",
                "bloco_origem": 0,
                "bloco_destino": 1,
                "confianca": "alta",
                "texto_original": "fugiu de bicicleta pela mata",
                "prioridade": "alta",
                "posicao_s": 12.0,
                "descricao_visual": "bicycle chase in forest",
            }
        ],
        "custo_usd_total": 0.0123,
    }
    (projetos_dir / "caso_com_log" / "clipes" / "sincronizacao_vision_log.json").write_text(
        json.dumps(log, ensure_ascii=False), encoding="utf-8"
    )

    resposta = client.get("/projetos/caso_com_log/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Sincronização com IA aplicada" in pagina
    assert "bicycle chase" in pagina
    assert "bicycle chase in forest" in pagina


def test_reorganizar_nao_quebra_sem_log(client, tmp_path, monkeypatch):
    """Projeto sem Feature A ativada (nenhum sincronizacao_vision_log.json)
    renderiza normalmente, sem o bloco de resultado."""
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_sem_log", [_clipe("c0")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_sem_log/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Sincronização com IA aplicada" not in pagina


# ---------------------------------------------------------------------------
# _formatar_mmss - sessao de correcoes UX GRUPO B/C: formato unico de
# timestamp usado no rodape dos cards da timeline E na coluna de tempo da
# tabela de swaps (nunca dois formatos diferentes na mesma tela).
# ---------------------------------------------------------------------------


def test_formatar_mmss_valores_basicos():
    assert server._formatar_mmss(0) == "00:00"
    assert server._formatar_mmss(5) == "00:05"
    assert server._formatar_mmss(65) == "01:05"


def test_formatar_mmss_acima_de_uma_hora():
    # 3661s = 1h01min01s - minutos NAO tem cap em 59 (formato mm:ss sem
    # componente de hora, entao vira "61:01", nao "01:01:01").
    assert server._formatar_mmss(3661) == "61:01"


def test_formatar_mmss_none_e_negativo_vira_zero():
    assert server._formatar_mmss(None) == "00:00"
    assert server._formatar_mmss(-5) == "00:00"


# ---------------------------------------------------------------------------
# _montar_timeline_reorganizacao / _primeira_posicao_aproximada - GRUPO A:
# fallback de duracao tem que ficar VISIVEL (nao so' um console.warn), e o
# acumulo das posicoes seguintes nao pode quebrar por causa dele.
# ---------------------------------------------------------------------------


def test_montar_timeline_marca_posicao_sem_duracao_como_aproximada():
    clipes = [
        {"clipe_id": "c0", "duracao_s": 6.0},
        {"clipe_id": "c1", "duracao_s": None},  # sem duracao valida
        {"clipe_id": "c2", "duracao_s": 7.0},
    ]
    timeline, _banco = server._montar_timeline_reorganizacao(clipes, {}, duracao_padrao_s=8.0)

    assert timeline[0]["duracao_aproximada"] is False
    assert timeline[1]["duracao_aproximada"] is True
    assert timeline[2]["duracao_aproximada"] is False
    # A posicao seguinte ao fallback continua acumulando corretamente com o
    # padrao usado (6.0 + 8.0 = 14.0) - o fallback nao quebra o calculo das
    # posicoes seguintes.
    assert timeline[1]["inicio_slot_s"] == 6.0
    assert timeline[2]["inicio_slot_s"] == 14.0


def test_primeira_posicao_aproximada():
    clipes = [{"clipe_id": "c0", "duracao_s": 6.0}, {"clipe_id": "c1", "duracao_s": 0}]
    timeline, _banco = server._montar_timeline_reorganizacao(clipes, {}, duracao_padrao_s=8.0)
    assert server._primeira_posicao_aproximada(timeline) == 1


def test_primeira_posicao_aproximada_none_quando_tudo_tem_duracao():
    clipes = [{"clipe_id": "c0", "duracao_s": 6.0}]
    timeline, _banco = server._montar_timeline_reorganizacao(clipes, {}, duracao_padrao_s=8.0)
    assert server._primeira_posicao_aproximada(timeline) is None


# ---------------------------------------------------------------------------
# _checar_divergencia_narracao - GRUPO A: soma das posicoes tem que bater
# com a duracao real da narracao dentro de uma tolerancia.
# ---------------------------------------------------------------------------


def test_checar_divergencia_dentro_da_tolerancia_nao_avisa():
    assert server._checar_divergencia_narracao(100.0, 101.5) is None


def test_checar_divergencia_fora_da_tolerancia_avisa():
    aviso = server._checar_divergencia_narracao(100.0, 110.0)
    assert aviso is not None
    assert "diverge" in aviso


def test_checar_divergencia_sem_duracao_narracao_nao_avisa():
    assert server._checar_divergencia_narracao(100.0, None) is None
    assert server._checar_divergencia_narracao(100.0, 0) is None


# ---------------------------------------------------------------------------
# _montar_linhas_swap - GRUPO B: posicao SEMPRE resolvida pela timeline
# atual (nunca por bloco_destino/posicao_s do log, que ficam desatualizados
# apos uma reorganizacao manual), e ocorrencia multipla do mesmo clipe_id
# resolve pra primeira posicao e sinaliza em vez de apontar pro lugar errado
# em silencio.
# ---------------------------------------------------------------------------


def test_montar_linhas_swap_resolve_posicao_atual_ignorando_log():
    timeline = [
        {"posicao": 0, "clipe_id": "c1", "tempo_formatado": "00:00"},
        {"posicao": 1, "clipe_id": "c0", "tempo_formatado": "00:06"},
    ]
    # log diz que c0 esta no bloco 0 (snapshot de antes de um drag manual) -
    # a timeline atual diz que c0 esta na posicao 1.
    swaps = [{"clipe_id": "c0", "bloco_destino": 0, "posicao_s": 0.0, "ancora_termo": "x"}]

    linhas = server._montar_linhas_swap(swaps, timeline)

    assert linhas[0]["posicao"] == 1
    assert linhas[0]["tempo_formatado"] == "00:06"
    assert linhas[0]["outras_ocorrencias"] == 0


def test_montar_linhas_swap_clipe_id_ausente_da_timeline():
    timeline = [{"posicao": 0, "clipe_id": "c0", "tempo_formatado": "00:00"}]
    swaps = [{"clipe_id": "clipe_removido", "ancora_termo": "x"}]

    linhas = server._montar_linhas_swap(swaps, timeline)

    assert linhas[0]["posicao"] is None
    assert linhas[0]["tempo_formatado"] is None
    assert linhas[0]["outras_ocorrencias"] == 0


def test_montar_linhas_swap_ocorrencia_multipla_resolve_primeira_e_sinaliza():
    timeline = [
        {"posicao": 0, "clipe_id": "c0", "tempo_formatado": "00:00"},
        {"posicao": 1, "clipe_id": "c1", "tempo_formatado": "00:06"},
        {"posicao": 2, "clipe_id": "c0", "tempo_formatado": "00:14"},
    ]
    swaps = [{"clipe_id": "c0", "ancora_termo": "x"}]

    linhas = server._montar_linhas_swap(swaps, timeline)

    assert linhas[0]["posicao"] == 0
    assert linhas[0]["tempo_formatado"] == "00:00"
    assert linhas[0]["outras_ocorrencias"] == 1


# ---------------------------------------------------------------------------
# _montar_regua_tempo - GRUPO C
# ---------------------------------------------------------------------------


def test_montar_regua_tempo_marcas_a_cada_30s():
    marcas = server._montar_regua_tempo(65.0, px_por_segundo=10, intervalo_s=30.0)
    assert [m["tempo_formatado"] for m in marcas] == ["00:00", "00:30", "01:00"]
    assert [m["left_px"] for m in marcas] == [0, 300, 600]


def test_montar_regua_tempo_vazia_sem_duracao():
    assert server._montar_regua_tempo(0, px_por_segundo=10) == []


# ---------------------------------------------------------------------------
# GET /reorganizar_clipes - GRUPOS A/B/C/D integrados na rota
# ---------------------------------------------------------------------------


def test_reorganizar_avisa_quando_posicao_usa_duracao_aproximada(client, tmp_path, monkeypatch):
    clipes = [_clipe("c0", duracao_s=6.0), {"clipe_id": "c1", "arquivo": "c1.mp4", "duracao_s": None}]
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_aproximado", clipes)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_aproximado/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Tempos aproximados a partir da posição #1" in pagina
    assert "~00:06" in pagina  # card da posicao 1 marcado com "~" no rodape


def test_reorganizar_sem_fallback_nao_mostra_aviso_de_aproximacao(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_sem_fallback", [_clipe("c0"), _clipe("c1")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_sem_fallback/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Tempos aproximados" not in pagina


def test_reorganizar_avisa_divergencia_narracao(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(
        tmp_path, "caso_divergencia", [_clipe("c0", duracao_s=6.0), _clipe("c1", duracao_s=6.0)]
    )
    caminho_indice = projetos_dir / "caso_divergencia" / "clipes" / "indice.json"
    indice = json.loads(caminho_indice.read_text(encoding="utf-8"))
    indice["metadata"] = {"duracao_narracao_s": 30.0}  # soma real = 12.0s, diferenca = 18.0s
    caminho_indice.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_divergencia/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "diverge" in pagina


def test_reorganizar_sem_divergencia_nao_avisa(client, tmp_path, monkeypatch):
    # Nome do projeto de proposito sem a substring "diverge" - o titulo da
    # pagina inclui o nome do projeto, e' o proprio texto do aviso que a
    # asserção abaixo precisa distinguir, nao um match acidental no titulo.
    projetos_dir = _criar_projeto_com_clipes(
        tmp_path, "caso_narracao_ok", [_clipe("c0", duracao_s=6.0), _clipe("c1", duracao_s=6.0)]
    )
    caminho_indice = projetos_dir / "caso_narracao_ok" / "clipes" / "indice.json"
    indice = json.loads(caminho_indice.read_text(encoding="utf-8"))
    indice["metadata"] = {"duracao_narracao_s": 12.5}  # diferenca = 0.5s, dentro da tolerancia
    caminho_indice.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_narracao_ok/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "diverge" not in pagina


def test_reorganizar_tabela_swaps_mostra_coluna_tempo_e_ocorrencia_multipla(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_swap_tabela", [_clipe("c0"), _clipe("c1"), _clipe("c2")])
    # Forca ocorrencia multipla do mesmo clipe_id na timeline - defensivo,
    # nao deveria acontecer na pratica (Etapa 5/reordenar nunca duplicam
    # clipe_id), mas o GRUPO B pede tratamento explicito em vez de silencio.
    caminho_indice = projetos_dir / "caso_swap_tabela" / "clipes" / "indice.json"
    indice = json.loads(caminho_indice.read_text(encoding="utf-8"))
    indice["clipes"][2]["clipe_id"] = "c0"
    caminho_indice.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")

    log = {
        "timestamp": "2026-09-02T00:00:00+00:00",
        "duracao_alvo_s": 600,
        "ancoras_encontradas": 1,
        "clipes_descritos": 2,
        "swaps_aplicados": [
            {
                "ancora_termo": "bicycle chase",
                "clipe_id": "c0",
                "bloco_origem": 0,
                "bloco_destino": 99,  # snapshot desatualizado de proposito
                "confianca": "alta",
                "texto_original": "fugiu de bicicleta",
                "prioridade": "alta",
                "posicao_s": 999.0,  # tambem desatualizado
                "descricao_visual": "bicycle chase in forest",
            }
        ],
        "custo_usd_total": 0.0123,
    }
    (projetos_dir / "caso_swap_tabela" / "clipes" / "sincronizacao_vision_log.json").write_text(
        json.dumps(log, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_swap_tabela/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "<th>Tempo</th>" in pagina
    assert 'class="swap-row"' in pagina
    assert 'data-posicao="0"' in pagina  # resolvido pela posicao ATUAL (0), nao bloco_destino=99 do log
    assert "outra(s) posição" in pagina  # ocorrencia multipla sinalizada


def test_reorganizar_sem_narracao_mostra_timestamps_mesmo_assim(client, tmp_path, monkeypatch):
    """GRUPO D: sem narracao.mp3 no disco, a rota /narracao_audio devolveria
    404, mas a tela de reorganizacao continua mostrando os timestamps
    normalmente - so' o salto do player (JS) fica inativo, e isso nao e'
    testavel aqui (comportamento de browser)."""
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_sem_audio", [_clipe("c0"), _clipe("c1")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    assert not (projetos_dir / "caso_sem_audio" / "narracao.mp3").exists()

    resposta = client.get("/projetos/caso_sem_audio/reorganizar_clipes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "00:00" in pagina
    assert "00:08" in pagina  # inicio do segundo clipe (duracao default 8.0s do helper _clipe)


# ---------------------------------------------------------------------------
# POST /reordenar_clipes
# ---------------------------------------------------------------------------


def test_reordenar_clipes_move_da_origem_para_destino(client, tmp_path, monkeypatch):
    """pop(origem) + insert(destino) - NAO e' swap 2-a-2: mover o clipe da
    posicao 0 para a posicao 2 empurra os demais, nao troca so' os dois."""
    projetos_dir = _criar_projeto_com_clipes(
        tmp_path, "caso_reordenar", [_clipe("c0"), _clipe("c1"), _clipe("c2"), _clipe("c3")]
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_reordenar/reordenar_clipes",
        json={"origem": 0, "destino": 2},
    )

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["sucesso"] is True

    indice = json.loads((projetos_dir / "caso_reordenar" / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert [c["clipe_id"] for c in indice["clipes"]] == ["c1", "c2", "c0", "c3"]


def test_reordenar_clipes_preserva_duracao_de_slot_por_posicao(client, tmp_path, monkeypatch):
    """A duracao de cada POSICAO (duracao_slot_s) e' fixa - reordenar move
    o clipe (arquivo/duracao_s), mas a posicao continua tendo a mesma
    duracao de slot de antes, agora ocupada por outro clipe. Isso e' o que
    evita dessincronizar a narracao ao arrastar clipes de duracao diferente."""
    clipes = [_clipe("c0", duracao_s=6.0), _clipe("c1", duracao_s=9.0), _clipe("c2", duracao_s=7.0)]
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_slots", clipes)
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    # Duracoes de slot originais (fallback = duracao_s): posicao 0 -> 6.0,
    # posicao 1 -> 9.0, posicao 2 -> 7.0. Move c0 (posicao 0) pra posicao 2.
    resposta = client.post("/projetos/caso_slots/reordenar_clipes", json={"origem": 0, "destino": 2})
    assert resposta.status_code == 200

    indice = json.loads((projetos_dir / "caso_slots" / "clipes" / "indice.json").read_text(encoding="utf-8"))
    clipes_pos = indice["clipes"]
    assert [c["clipe_id"] for c in clipes_pos] == ["c1", "c2", "c0"]
    # A posicao 0 (antes ocupada por c0, slot 6.0s) agora tem c1 (duracao_s
    # real 9.0) MAS com duracao_slot_s ainda 6.0 - a posicao, nao o clipe.
    assert clipes_pos[0]["clipe_id"] == "c1"
    assert clipes_pos[0]["duracao_slot_s"] == 6.0
    assert clipes_pos[0]["duracao_s"] == 9.0
    # Posicao 1 (antes c1, slot 9.0) agora tem c2.
    assert clipes_pos[1]["duracao_slot_s"] == 9.0
    # Posicao 2 (antes c2, slot 7.0) agora tem c0.
    assert clipes_pos[2]["duracao_slot_s"] == 7.0
    # inicio_slot_s/fim_slot_s sao cumulativos na nova ordem.
    assert clipes_pos[0]["inicio_slot_s"] == 0.0
    assert clipes_pos[1]["inicio_slot_s"] == 6.0
    assert clipes_pos[2]["inicio_slot_s"] == 15.0
    assert clipes_pos[2]["fim_slot_s"] == 22.0


def test_reordenar_clipes_origem_igual_destino_nao_altera_nada(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_mesmo", [_clipe("c0"), _clipe("c1")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_mesmo/reordenar_clipes", json={"origem": 1, "destino": 1})

    assert resposta.status_code == 200
    indice = json.loads((projetos_dir / "caso_mesmo" / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert [c["clipe_id"] for c in indice["clipes"]] == ["c0", "c1"]


def test_reordenar_clipes_rejeita_se_status_invalido(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(
        tmp_path, "caso_status_invalido", [_clipe("c0"), _clipe("c1")], status="aguardando_legendas"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_status_invalido/reordenar_clipes", json={"origem": 0, "destino": 1})

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "status_invalido"
    indice = json.loads((projetos_dir / "caso_status_invalido" / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert [c["clipe_id"] for c in indice["clipes"]] == ["c0", "c1"]


def test_reordenar_clipes_rejeita_indices_fora_do_intervalo(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_fora", [_clipe("c0"), _clipe("c1")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_fora/reordenar_clipes", json={"origem": 0, "destino": 99})

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "indices_fora_do_intervalo"


def test_reordenar_clipes_rejeita_indices_nao_numericos(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_nao_numerico", [_clipe("c0"), _clipe("c1")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_nao_numerico/reordenar_clipes", json={"origem": "x", "destino": 1})

    assert resposta.status_code == 400
    assert resposta.get_json()["erro"] == "indices_invalidos"


# ---------------------------------------------------------------------------
# GET /thumb_clipe/<clipe_id>
# ---------------------------------------------------------------------------


def test_thumb_clipe_serve_arquivo_existente(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_thumb_existe", [_clipe("c0")])
    pasta_thumbs = projetos_dir / "caso_thumb_existe" / "clipes" / "thumbs"
    pasta_thumbs.mkdir(parents=True)
    (pasta_thumbs / "c0.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_thumb_existe/thumb_clipe/c0")

    assert resposta.status_code == 200
    assert resposta.mimetype == "image/jpeg"


def test_thumb_clipe_gera_sob_demanda_quando_ausente(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_thumb_sob_demanda", [_clipe("c0")])
    (projetos_dir / "caso_thumb_sob_demanda" / "clipes" / "c0.mp4").write_bytes(b"fake mp4 bytes")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _fake_extrair(caminho_clipe, caminho_saida):
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
        return True

    monkeypatch.setattr(server.sincronizador_visual, "extrair_frame_clipe", _fake_extrair)

    resposta = client.get("/projetos/caso_thumb_sob_demanda/thumb_clipe/c0")

    assert resposta.status_code == 200


def test_thumb_clipe_path_traversal_devolve_404(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_traversal", [_clipe("c0")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_traversal/thumb_clipe/..%2F..%2F.env")

    assert resposta.status_code == 404


# ---------------------------------------------------------------------------
# GET /preview_video
# ---------------------------------------------------------------------------


def test_preview_video_gerado_sob_demanda(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_preview", [_clipe("c0")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    def _fake_gerar(pasta_projeto, indice):
        (pasta_projeto / "preview.mp4").write_bytes(b"fake preview mp4")
        return True

    monkeypatch.setattr(server, "_gerar_preview_video", _fake_gerar)

    resposta = client.get("/projetos/caso_preview/preview_video")

    assert resposta.status_code == 200
    hash_gravado = (projetos_dir / "caso_preview" / "temp" / "preview_hash.txt").read_text(encoding="utf-8")
    assert hash_gravado  # hash nao vazio


def test_preview_video_sem_clipes_devolve_404(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_preview_vazio", [])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_preview_vazio/preview_video")

    assert resposta.status_code == 404


def test_preview_video_falha_geracao_devolve_404(client, tmp_path, monkeypatch):
    projetos_dir = _criar_projeto_com_clipes(tmp_path, "caso_preview_falha", [_clipe("c0")])
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server, "_gerar_preview_video", lambda pasta_projeto, indice: False)

    resposta = client.get("/projetos/caso_preview_falha/preview_video")

    assert resposta.status_code == 404
