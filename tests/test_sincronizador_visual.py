"""Testes da Feature A (sincronizacao inteligente com IA,
scripts/sincronizador_visual.py) - CLAUDE.md secao 8: nunca chama a API
real da Anthropic, sempre injeta um `cliente` fake via o parametro
`cliente=` de cada funcao publica do modulo."""

import json

import pytest

from scripts import sincronizador_visual as sv


class _ClienteFake:
    """Fake de anthropic.Anthropic - `.messages.create(**kwargs)` devolve a
    proxima resposta da fila (`respostas`), registrando os kwargs de cada
    chamada em `.chamadas` para asserts."""

    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if not self._respostas:
            raise AssertionError("ClienteFake: mais chamadas do que respostas configuradas")
        return self._respostas.pop(0)


def _resposta_tool_use(nome_tool, dados_input):
    return {"content": [{"type": "tool_use", "name": nome_tool, "id": "toolu_1", "input": dados_input}]}


def _resposta_sem_tool_use():
    return {"content": [{"type": "text", "text": "sem tool use"}]}


# ---------------------------------------------------------------------------
# _recortar_roteiro_por_duracao
# ---------------------------------------------------------------------------


def test_recortar_roteiro_video_inteiro_quando_duracao_alvo_zero():
    texto = "a" * 1000
    assert sv._recortar_roteiro_por_duracao(texto, 0, 600) == texto


def test_recortar_roteiro_video_inteiro_quando_alvo_maior_que_total():
    texto = "a" * 1000
    assert sv._recortar_roteiro_por_duracao(texto, 900, 600) == texto


def test_recortar_roteiro_corta_proporcional_no_proximo_espaco():
    texto = "palavra " * 100  # 800 chars, palavras de 8 chars cada
    trecho = sv._recortar_roteiro_por_duracao(texto, 300, 600)  # metade
    assert len(trecho) < len(texto)
    assert not trecho or trecho[-1] != " " or texto.startswith(trecho)


# ---------------------------------------------------------------------------
# localizar_posicao_ancoras
# ---------------------------------------------------------------------------


def test_localizar_posicao_ancoras_encontra_texto_exato():
    roteiro = "Ele fugiu de bicicleta pela mata naquela noite fria."
    ancoras = [{"texto_original": "fugiu de bicicleta pela mata", "termo_ancora": "bike", "prioridade": "alta"}]
    palavras = [
        {"palavra": w, "inicio_s": i * 1.0, "fim_s": i * 1.0 + 0.5}
        for i, w in enumerate(roteiro.split())
    ]
    localizadas = sv.localizar_posicao_ancoras(ancoras, roteiro, palavras)
    assert len(localizadas) == 1
    assert localizadas[0]["posicao_s"] >= 0


def test_localizar_posicao_ancoras_descarta_texto_nao_encontrado():
    roteiro = "Um texto qualquer sem relacao nenhuma."
    ancoras = [{"texto_original": "frase que nao existe no roteiro nem parecido", "termo_ancora": "x", "prioridade": "media"}]
    palavras = [{"palavra": "um", "inicio_s": 0.0, "fim_s": 0.5}]
    assert sv.localizar_posicao_ancoras(ancoras, roteiro, palavras) == []


def test_localizar_posicao_ancoras_lista_vazia_sem_palavras():
    assert sv.localizar_posicao_ancoras([{"texto_original": "x", "termo_ancora": "y", "prioridade": "media"}], "x", []) == []


# ---------------------------------------------------------------------------
# _localizar_por_similaridade / fallback tolerante (achado real de producao,
# projeto teste_srt_darkplanner: extracao respondeu ancoras validas [custo
# cobrado] mas 0 bateram caractere-por-caractere - a IA quase nunca cita um
# trecho longo 100% literal mesmo instruida a "copiar exatamente").
# ---------------------------------------------------------------------------


def test_localizar_posicao_ancoras_aceita_parafrase_leve_via_similaridade():
    """Trecho real citado pela IA quase nunca bate 100% literal - virgula
    removida, "the"/"a" trocados, etc. O fallback tolerante precisa
    recuperar esses casos que o match exato (str.find) descarta."""
    roteiro = (
        "Investigators said the gunman had been loitering outside the hotel "
        "for roughly ten minutes before the attack, and surveillance footage "
        "placed him nearby."
    )
    # Paráfrase leve: "the gunman had been" -> "the gunman was", sem virgula.
    ancoras = [{
        "texto_original": "the gunman was loitering outside the hotel for roughly ten minutes before the attack",
        "termo_ancora": "man waiting outside hotel",
        "prioridade": "alta",
    }]
    palavras = [
        {"palavra": w, "inicio_s": i * 0.4, "fim_s": i * 0.4 + 0.3}
        for i, w in enumerate(roteiro.split())
    ]
    # Confirma que o match exato realmente falharia (controle do cenario).
    assert roteiro.find(ancoras[0]["texto_original"]) == -1

    localizadas = sv.localizar_posicao_ancoras(ancoras, roteiro, palavras)
    assert len(localizadas) == 1
    assert localizadas[0]["posicao_s"] >= 0


def test_localizar_posicao_ancoras_rejeita_similaridade_alta_sem_sequencia_real():
    """"bicicleta" ~ "biscoito" (citado na sessao de correcoes UX): strings
    curtas isoladas podem ter ratio() enganosamente alto sem nenhuma
    sequencia real de palavras em comum. So' ratio nao pode ser suficiente -
    por isso a exigencia de >= MIN_PALAVRAS_CONSECUTIVAS_MATCH palavras
    consecutivas junto com o ratio."""
    roteiro = "Ele fugiu de biscoito pela mata naquela noite fria, sem deixar vestigios."
    ancoras = [{"texto_original": "fugiu de bicicleta pela", "termo_ancora": "x", "prioridade": "media"}]
    palavras = [{"palavra": w, "inicio_s": i * 0.4, "fim_s": i * 0.4 + 0.3} for i, w in enumerate(roteiro.split())]

    # Ratio alto isolado (troca de 1 palavra em string curta) nao deve virar
    # match sozinho sem >=3 palavras consecutivas reais - aqui so ha 2
    # ("fugiu de" e "pela"), entao continua rejeitando.
    localizadas = sv.localizar_posicao_ancoras(ancoras, roteiro, palavras)
    assert localizadas == []


def test_localizar_posicao_ancoras_rejeita_texto_totalmente_nao_relacionado_com_similaridade():
    roteiro = (
        "On a December morning in Manhattan, a man walked calmly along a "
        "sidewalk in Midtown, waited outside a hotel for several minutes."
    )
    ancoras = [{
        "texto_original": "purple elephants dancing quietly under a rainbow bridge at dawn today",
        "termo_ancora": "x",
        "prioridade": "media",
    }]
    palavras = [{"palavra": w, "inicio_s": i * 0.4, "fim_s": i * 0.4 + 0.3} for i, w in enumerate(roteiro.split())]
    assert sv.localizar_posicao_ancoras(ancoras, roteiro, palavras) == []


def test_localizar_posicao_ancoras_prosa_longa_recupera_maioria_das_ancoras_parafraseadas():
    """Regressao direta do bug real (Grupo A/G1): roteiro longo (prosa
    corrida, sem pontuacao facilitando o corte) com varias ancoras citadas
    com parafrase leve, tipica de saida real de LLM. Antes do fallback
    tolerante, isso resultava em 0 ancoras localizadas apesar da IA ter
    respondido texto valido (achado real, projeto teste_srt_darkplanner:
    16 min de narracao, custo cobrado, 0 ancoras). Depois do fix, a maioria
    tem que ser recuperada - nao dependemos mais de match caractere-por-
    caractere."""
    roteiro = (
        "On a quiet afternoon in Riverside, a man walked slowly along the "
        "pier, waited outside a warehouse for several minutes, made a short "
        "phone call, and then vanished into the industrial district on a "
        "battered motorcycle. Investigators later said the suspect had been "
        "loitering near the loading dock for roughly twenty minutes before "
        "the incident, and surveillance footage placed him closer to the "
        "gate than first believed. A masked figure approached from the "
        "shadows and forced open a side door using a heavy iron crowbar. "
        "Detectives recovered a rusted toolbox, a torn duffel bag, and a "
        "handwritten note left near the loading dock. The department "
        "eventually offered a reward of up to twenty thousand dollars for "
        "information leading to an arrest."
    )
    palavras = [
        {"palavra": w, "inicio_s": i * 0.35, "fim_s": i * 0.35 + 0.3}
        for i, w in enumerate(roteiro.split())
    ]
    ancoras = [
        # parafrase leve (troca de 1-2 palavras / pontuacao), como a IA
        # costuma citar mesmo quando instruida a copiar literalmente.
        {"texto_original": "a man walked slowly along the pier", "termo_ancora": "man walking on pier", "prioridade": "alta"},
        {"texto_original": "then vanished into the industrial area on a battered motorcycle", "termo_ancora": "motorcycle fleeing", "prioridade": "alta"},
        {"texto_original": "the suspect was loitering near the loading dock for roughly twenty minutes", "termo_ancora": "man loitering", "prioridade": "media"},
        {"texto_original": "a masked man approached from the shadows and forced open a side door", "termo_ancora": "masked figure at door", "prioridade": "alta"},
        {"texto_original": "detectives recovered a rusted toolbox and a torn duffel bag", "termo_ancora": "toolbox and duffel bag", "prioridade": "media"},
        {"texto_original": "offered a big reward of up to twenty thousand dollars", "termo_ancora": "reward announcement", "prioridade": "media"},
        # controle: sem nenhuma relacao com o roteiro - nao pode aparecer.
        {"texto_original": "purple elephants dancing under a rainbow bridge at dawn", "termo_ancora": "x", "prioridade": "media"},
    ]

    localizadas = sv.localizar_posicao_ancoras(ancoras, roteiro, palavras)

    assert len(localizadas) >= 5
    textos_localizados = {loc["texto_original"] for loc in localizadas}
    assert "purple elephants dancing under a rainbow bridge at dawn" not in textos_localizados


# ---------------------------------------------------------------------------
# selecionar_clipes_candidatos
# ---------------------------------------------------------------------------


def _clipe(clipe_id, duracao_s):
    return {"clipe_id": clipe_id, "arquivo": f"{clipe_id}.mp4", "duracao_s": duracao_s}


def test_selecionar_clipes_candidatos_video_inteiro_quando_duracao_zero():
    clipes = [_clipe(f"c{i}", 8.0) for i in range(10)]
    assert sv.selecionar_clipes_candidatos(clipes, 0) == clipes


def test_selecionar_clipes_candidatos_limita_pela_janela():
    clipes = [_clipe(f"c{i}", 8.0) for i in range(10)]  # 80s totais
    candidatos = sv.selecionar_clipes_candidatos(clipes, 30.0)  # cabe ~4 clipes (32s)
    assert len(candidatos) == 4
    assert candidatos[0]["clipe_id"] == "c0"


# ---------------------------------------------------------------------------
# _posicao_para_indice_clipe
# ---------------------------------------------------------------------------


def test_posicao_para_indice_clipe_mapeia_pela_soma_cumulativa():
    clipes = [_clipe("c0", 5.0), _clipe("c1", 5.0), _clipe("c2", 5.0)]
    assert sv._posicao_para_indice_clipe(2.0, clipes) == 0
    assert sv._posicao_para_indice_clipe(6.0, clipes) == 1
    assert sv._posicao_para_indice_clipe(11.0, clipes) == 2


def test_posicao_para_indice_clipe_clampa_no_ultimo():
    clipes = [_clipe("c0", 5.0)]
    assert sv._posicao_para_indice_clipe(999.0, clipes) == 0


def test_posicao_para_indice_clipe_lista_vazia():
    assert sv._posicao_para_indice_clipe(1.0, []) is None


# ---------------------------------------------------------------------------
# aplicar_swaps_automaticos
# ---------------------------------------------------------------------------


def test_aplicar_swaps_automaticos_preserva_total_de_clipes():
    clipes = [_clipe(f"c{i}", 8.0) for i in range(5)]
    ancoras = [{"termo_ancora": "bike", "posicao_s": 32.0, "prioridade": "alta"}]  # indice 4
    matches = [{"ancora_termo": "bike", "clipe_id_candidato": "c0", "confianca": "alta"}]

    log = sv.aplicar_swaps_automaticos(matches, ancoras, clipes)

    assert len(clipes) == 5
    assert {c["clipe_id"] for c in clipes} == {f"c{i}" for i in range(5)}
    assert len(log) == 1
    assert log[0] == {
        "ancora_termo": "bike",
        "clipe_id": "c0",
        "bloco_origem": 0,
        "bloco_destino": 4,
        "confianca": "alta",
    }
    assert clipes[4]["clipe_id"] == "c0"
    assert clipes[0]["clipe_id"] == "c4"  # quem estava no destino foi pro lugar do c0


def test_aplicar_swaps_automaticos_prioriza_ancora_alta_sobre_media_no_mesmo_destino():
    clipes = [_clipe(f"c{i}", 8.0) for i in range(3)]
    ancoras = [
        {"termo_ancora": "a_media", "posicao_s": 20.0, "prioridade": "media"},  # indice 2
        {"termo_ancora": "a_alta", "posicao_s": 20.0, "prioridade": "alta"},  # mesmo indice 2
    ]
    matches = [
        {"ancora_termo": "a_media", "clipe_id_candidato": "c0", "confianca": "alta"},
        {"ancora_termo": "a_alta", "clipe_id_candidato": "c1", "confianca": "alta"},
    ]

    log = sv.aplicar_swaps_automaticos(matches, ancoras, clipes)

    assert len(log) == 1
    assert log[0]["ancora_termo"] == "a_alta"
    assert clipes[2]["clipe_id"] == "c1"


def test_aplicar_swaps_automaticos_sem_match_nao_altera_nada():
    clipes = [_clipe(f"c{i}", 8.0) for i in range(3)]
    original = list(clipes)
    assert sv.aplicar_swaps_automaticos([], [], clipes) == []
    assert clipes == original


def test_aplicar_swaps_automaticos_origem_igual_destino_nao_gera_swap():
    clipes = [_clipe(f"c{i}", 8.0) for i in range(3)]
    ancoras = [{"termo_ancora": "a", "posicao_s": 2.0, "prioridade": "alta"}]  # indice 0
    matches = [{"ancora_termo": "a", "clipe_id_candidato": "c0", "confianca": "alta"}]
    log = sv.aplicar_swaps_automaticos(matches, ancoras, clipes)
    assert log == []


# ---------------------------------------------------------------------------
# extrair_ancoras_do_roteiro (cliente fake)
# ---------------------------------------------------------------------------


def test_extrair_ancoras_do_roteiro_roteiro_vazio_nao_chama_api():
    cliente = _ClienteFake([])
    assert sv.extrair_ancoras_do_roteiro("   ", 600, 1200, "fake-key", cliente=cliente) == []
    assert cliente.chamadas == []


def test_extrair_ancoras_do_roteiro_retorna_ancoras_validas():
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                sv.NOME_TOOL_ANCORAS,
                {
                    "ancoras": [
                        {"texto_original": "fugiu de bicicleta", "termo_ancora": "bike chase", "prioridade": "alta"},
                        {"texto_original": "", "termo_ancora": "vazio", "prioridade": "media"},
                    ]
                },
            )
        ]
    )
    ancoras = sv.extrair_ancoras_do_roteiro("Ele fugiu de bicicleta.", 600, 1200, "fake-key", cliente=cliente)
    assert len(ancoras) == 1
    assert ancoras[0]["termo_ancora"] == "bike chase"
    assert ancoras[0]["prioridade"] == "alta"


def test_extrair_ancoras_do_roteiro_resposta_sem_tool_use_retorna_vazio():
    cliente = _ClienteFake([_resposta_sem_tool_use()])
    assert sv.extrair_ancoras_do_roteiro("texto", 600, 1200, "fake-key", cliente=cliente) == []


def test_extrair_ancoras_do_roteiro_campo_ancoras_como_string_json_aninhada():
    """Achado real de producao (projeto teste_srt_darkplanner, sessao de
    correcoes UX): apesar do `tool_choice` forcado com schema tipado
    (`ancoras` como array), o Claude real ocasionalmente devolve o campo
    como uma STRING contendo o objeto inteiro serializado de novo por
    dentro (`{"ancoras": "{\\"ancoras\\": [...]}"}}` em vez de
    `{"ancoras": [...]}`). Sem tratar esse caso, `isinstance(ancoras,
    list)` falha e a extracao inteira e' descartada silenciosamente - foi
    exatamente esse achado (nao a tolerancia de match, que e' um bug
    separado) que explicou "custo cobrado, 0 ancoras" numa chamada real."""
    dados_reais = {
        "ancoras": [
            {"texto_original": "fugiu de bicicleta pela mata", "termo_ancora": "bike chase", "prioridade": "alta"},
        ]
    }
    cliente = _ClienteFake(
        [_resposta_tool_use(sv.NOME_TOOL_ANCORAS, {"ancoras": json.dumps(dados_reais)})]
    )
    ancoras = sv.extrair_ancoras_do_roteiro("Ele fugiu de bicicleta pela mata.", 600, 1200, "fake-key", cliente=cliente)
    assert len(ancoras) == 1
    assert ancoras[0]["termo_ancora"] == "bike chase"


def test_extrair_ancoras_do_roteiro_campo_ancoras_como_string_json_lista_direta():
    """Variante do achado acima: a string contem so' o array (nao o objeto
    inteiro re-aninhado) - `json.dumps([...])` em vez de
    `json.dumps({"ancoras": [...]})`."""
    lista_ancoras = [{"texto_original": "fugiu de bicicleta pela mata", "termo_ancora": "bike chase", "prioridade": "alta"}]
    cliente = _ClienteFake(
        [_resposta_tool_use(sv.NOME_TOOL_ANCORAS, {"ancoras": json.dumps(lista_ancoras)})]
    )
    ancoras = sv.extrair_ancoras_do_roteiro("Ele fugiu de bicicleta pela mata.", 600, 1200, "fake-key", cliente=cliente)
    assert len(ancoras) == 1
    assert ancoras[0]["termo_ancora"] == "bike chase"


def test_extrair_ancoras_do_roteiro_campo_ancoras_string_nao_json_retorna_vazio():
    """String que nao e' JSON valido nenhum (nao e' o caso conhecido) -
    continua descartando com seguranca, sem levantar excecao."""
    cliente = _ClienteFake([_resposta_tool_use(sv.NOME_TOOL_ANCORAS, {"ancoras": "isso nao e' json"})])
    assert sv.extrair_ancoras_do_roteiro("texto", 600, 1200, "fake-key", cliente=cliente) == []


def test_extrair_ancoras_do_roteiro_excecao_da_api_retorna_vazio():
    class _ClienteQuebrado:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("erro de rede simulado")

    assert sv.extrair_ancoras_do_roteiro("texto", 600, 1200, "fake-key", cliente=_ClienteQuebrado()) == []


# ---------------------------------------------------------------------------
# descrever_clipes_via_vision (cliente fake + cache)
# ---------------------------------------------------------------------------


def test_descrever_clipes_via_vision_usa_cache_existente(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "descricoes_vision.json").write_text(
        json.dumps({"c0": "a bicycle on a dirt road"}), encoding="utf-8"
    )
    cliente = _ClienteFake([])  # nao deveria ser chamado - c0 ja esta no cache

    descricoes = sv.descrever_clipes_via_vision([_clipe("c0", 8.0)], pasta_projeto, "fake-key", cliente=cliente)

    assert descricoes == {"c0": "a bicycle on a dirt road"}
    assert cliente.chamadas == []


def test_descrever_clipes_via_vision_descreve_clipe_novo(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "c0.mp4").write_bytes(b"fake video bytes")

    def _fake_extrair(caminho_clipe, caminho_saida):
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminho_saida.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(sv, "extrair_frame_clipe", _fake_extrair)

    cliente = _ClienteFake(
        [_resposta_tool_use(sv.NOME_TOOL_DESCRICOES, {"descricoes": [{"clipe_id": "c0", "descricao_visual": "a bicycle"}]})]
    )

    descricoes = sv.descrever_clipes_via_vision([_clipe("c0", 8.0)], pasta_projeto, "fake-key", cliente=cliente)

    assert descricoes == {"c0": "a bicycle"}
    assert len(cliente.chamadas) == 1
    cache_em_disco = json.loads((pasta_projeto / "clipes" / "descricoes_vision.json").read_text(encoding="utf-8"))
    assert cache_em_disco == {"c0": "a bicycle"}


def test_descrever_clipes_via_vision_sem_pendentes_nao_chama_api(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "clipes" / "descricoes_vision.json").write_text(json.dumps({"c0": "x"}), encoding="utf-8")
    cliente = _ClienteFake([])
    descricoes = sv.descrever_clipes_via_vision([_clipe("c0", 8.0)], pasta_projeto, "fake-key", cliente=cliente)
    assert descricoes == {"c0": "x"}
    assert cliente.chamadas == []


# ---------------------------------------------------------------------------
# casar_ancoras_com_clipes
# ---------------------------------------------------------------------------


def test_casar_ancoras_com_clipes_filtra_confianca_baixa():
    ancoras = [{"termo_ancora": "bike", "posicao_s": 5.0, "prioridade": "alta"}]
    descricoes = {"c0": "a bicycle on a road", "c1": "an empty room"}
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                sv.NOME_TOOL_MATCHES,
                {"matches": [{"ancora_termo": "bike", "clipe_id_candidato": "c1", "confianca": "baixa"}]},
            )
        ]
    )
    assert sv.casar_ancoras_com_clipes(ancoras, descricoes, "fake-key", cliente=cliente) == []


def test_casar_ancoras_com_clipes_ignora_clipe_id_inexistente():
    ancoras = [{"termo_ancora": "bike", "posicao_s": 5.0, "prioridade": "alta"}]
    descricoes = {"c0": "a bicycle on a road"}
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                sv.NOME_TOOL_MATCHES,
                {"matches": [{"ancora_termo": "bike", "clipe_id_candidato": "c999", "confianca": "alta"}]},
            )
        ]
    )
    assert sv.casar_ancoras_com_clipes(ancoras, descricoes, "fake-key", cliente=cliente) == []


def test_casar_ancoras_com_clipes_aceita_match_valido():
    ancoras = [{"termo_ancora": "bike", "posicao_s": 5.0, "prioridade": "alta"}]
    descricoes = {"c0": "a bicycle on a road"}
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                sv.NOME_TOOL_MATCHES,
                {"matches": [{"ancora_termo": "bike", "clipe_id_candidato": "c0", "confianca": "alta"}]},
            )
        ]
    )
    matches = sv.casar_ancoras_com_clipes(ancoras, descricoes, "fake-key", cliente=cliente)
    assert matches == [{"ancora_termo": "bike", "clipe_id_candidato": "c0", "confianca": "alta"}]


def test_casar_ancoras_com_clipes_sem_ancoras_ou_descricoes_nao_chama_api():
    cliente = _ClienteFake([])
    assert sv.casar_ancoras_com_clipes([], {"c0": "x"}, "fake-key", cliente=cliente) == []
    assert sv.casar_ancoras_com_clipes([{"termo_ancora": "a", "posicao_s": 1.0, "prioridade": "alta"}], {}, "fake-key", cliente=cliente) == []
    assert cliente.chamadas == []


# ---------------------------------------------------------------------------
# sincronizar_projeto (orquestracao)
# ---------------------------------------------------------------------------


def test_sincronizar_projeto_arquivos_ausentes_retorna_erro(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    resultado = sv.sincronizar_projeto(pasta_projeto, "fake-key", 600, cliente=_ClienteFake([]))
    assert resultado["sucesso"] is False
    assert resultado["erro"]


def test_sincronizar_projeto_sem_ancoras_e_sucesso_sem_swaps(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "roteiro_aprovado.md").write_text("Um roteiro qualquer sem ancoras.", encoding="utf-8")
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps({"palavras": [{"palavra": "um", "inicio_s": 0.0, "fim_s": 0.5}]}), encoding="utf-8"
    )
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps({"clipes": [_clipe("c0", 8.0)]}), encoding="utf-8"
    )

    cliente = _ClienteFake([_resposta_tool_use(sv.NOME_TOOL_ANCORAS, {"ancoras": []})])
    resultado = sv.sincronizar_projeto(pasta_projeto, "fake-key", 600, cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["swaps_aplicados"] == 0
    assert resultado["ancoras_encontradas"] == 0


def test_sincronizar_projeto_fluxo_completo_aplica_swap_e_grava_indice(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    roteiro_texto = "No inicio ele andava calmo. Depois fugiu de bicicleta pela mata."
    (pasta_projeto / "roteiro_aprovado.md").write_text(roteiro_texto, encoding="utf-8")

    palavras = [
        {"palavra": w, "inicio_s": i * 2.0, "fim_s": i * 2.0 + 1.0}
        for i, w in enumerate(roteiro_texto.split())
    ]
    (pasta_projeto / "narracao_alinhamento.json").write_text(json.dumps({"palavras": palavras}), encoding="utf-8")

    clipes = [_clipe("c0", 8.0), _clipe("c1", 8.0), _clipe("c2", 8.0)]
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps({"clipes": clipes}), encoding="utf-8")
    (pasta_projeto / "clipes" / "descricoes_vision.json").write_text(
        json.dumps({"c0": "calm walk", "c1": "bicycle chase in forest", "c2": "empty street"}), encoding="utf-8"
    )

    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                sv.NOME_TOOL_ANCORAS,
                {
                    "ancoras": [
                        {"texto_original": "fugiu de bicicleta pela mata", "termo_ancora": "bicycle chase", "prioridade": "alta"}
                    ]
                },
            ),
            _resposta_tool_use(
                sv.NOME_TOOL_MATCHES,
                {"matches": [{"ancora_termo": "bicycle chase", "clipe_id_candidato": "c1", "confianca": "alta"}]},
            ),
        ]
    )

    resultado = sv.sincronizar_projeto(pasta_projeto, "fake-key", 600, cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["ancoras_encontradas"] == 1
    assert resultado["clipes_descritos"] == 3

    indice_final = json.loads((pasta_projeto / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert len(indice_final["clipes"]) == 3
    assert {c["clipe_id"] for c in indice_final["clipes"]} == {"c0", "c1", "c2"}


# ---------------------------------------------------------------------------
# _custo_usd_da_resposta — custo real via `usage` (GRUPO B da sessao de
# correcoes UX - o modulo nao rastreava custo nenhum antes desta sessao)
# ---------------------------------------------------------------------------


def test_custo_usd_da_resposta_sem_usage_retorna_zero():
    assert sv._custo_usd_da_resposta({"content": []}) == 0.0


def test_custo_usd_da_resposta_calcula_a_partir_de_tokens():
    resposta = {"content": [], "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000}}
    custo = sv._custo_usd_da_resposta(resposta)
    assert custo == sv.CUSTO_INPUT_POR_MILHAO_USD + sv.CUSTO_OUTPUT_POR_MILHAO_USD


# ---------------------------------------------------------------------------
# sincronizar_projeto — log persistido (GRUPO B: clipes/sincronizacao_vision_log.json)
# ---------------------------------------------------------------------------


def test_sincronizar_projeto_salva_log_com_swaps_e_custo(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    roteiro_texto = "No inicio ele andava calmo. Depois fugiu de bicicleta pela mata."
    (pasta_projeto / "roteiro_aprovado.md").write_text(roteiro_texto, encoding="utf-8")

    palavras = [
        {"palavra": w, "inicio_s": i * 2.0, "fim_s": i * 2.0 + 1.0}
        for i, w in enumerate(roteiro_texto.split())
    ]
    (pasta_projeto / "narracao_alinhamento.json").write_text(json.dumps({"palavras": palavras}), encoding="utf-8")

    clipes = [_clipe("c0", 8.0), _clipe("c1", 8.0), _clipe("c2", 8.0)]
    (pasta_projeto / "clipes" / "indice.json").write_text(json.dumps({"clipes": clipes}), encoding="utf-8")
    (pasta_projeto / "clipes" / "descricoes_vision.json").write_text(
        json.dumps({"c0": "calm walk", "c1": "bicycle chase in forest", "c2": "empty street"}), encoding="utf-8"
    )

    usage = {"input_tokens": 1000, "output_tokens": 200}
    cliente = _ClienteFake(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": sv.NOME_TOOL_ANCORAS,
                        "id": "toolu_1",
                        "input": {
                            "ancoras": [
                                {
                                    "texto_original": "fugiu de bicicleta pela mata",
                                    "termo_ancora": "bicycle chase",
                                    "prioridade": "alta",
                                }
                            ]
                        },
                    }
                ],
                "usage": usage,
            },
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": sv.NOME_TOOL_MATCHES,
                        "id": "toolu_2",
                        "input": {
                            "matches": [
                                # c0 (nao c1, que ja' esta' na posicao que a ancora aponta -
                                # nao geraria swap nenhum, ver aplicar_swaps_automaticos:
                                # bloco_origem == bloco_destino -> sem swap) para forcar um
                                # swap de verdade e exercitar o enriquecimento do log.
                                {"ancora_termo": "bicycle chase", "clipe_id_candidato": "c0", "confianca": "alta"}
                            ]
                        },
                    }
                ],
                "usage": usage,
            },
        ]
    )

    resultado = sv.sincronizar_projeto(pasta_projeto, "fake-key", 600, cliente=cliente)

    assert resultado["custo_usd_total"] > 0.0
    assert len(resultado["log_swaps"]) == 1
    assert resultado["log_swaps"][0]["texto_original"] == "fugiu de bicicleta pela mata"
    assert resultado["log_swaps"][0]["descricao_visual"] == "calm walk"
    assert resultado["log_swaps"][0]["confianca"] == "alta"

    caminho_log = pasta_projeto / "clipes" / "sincronizacao_vision_log.json"
    assert caminho_log.exists()
    log_disco = json.loads(caminho_log.read_text(encoding="utf-8"))
    assert log_disco["custo_usd_total"] > 0.0
    assert len(log_disco["swaps_aplicados"]) == 1
    assert log_disco["swaps_aplicados"][0]["clipe_id"] == "c0"
    assert "timestamp" in log_disco


def test_sincronizar_projeto_sem_ancoras_salva_log_vazio(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    (pasta_projeto / "clipes").mkdir(parents=True)
    (pasta_projeto / "roteiro_aprovado.md").write_text("Um roteiro qualquer sem ancoras.", encoding="utf-8")
    (pasta_projeto / "narracao_alinhamento.json").write_text(
        json.dumps({"palavras": [{"palavra": "um", "inicio_s": 0.0, "fim_s": 0.5}]}), encoding="utf-8"
    )
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps({"clipes": [_clipe("c0", 8.0)]}), encoding="utf-8"
    )

    cliente = _ClienteFake([_resposta_tool_use(sv.NOME_TOOL_ANCORAS, {"ancoras": []})])
    sv.sincronizar_projeto(pasta_projeto, "fake-key", 600, cliente=cliente)

    caminho_log = pasta_projeto / "clipes" / "sincronizacao_vision_log.json"
    assert caminho_log.exists()
    log_disco = json.loads(caminho_log.read_text(encoding="utf-8"))
    assert log_disco["swaps_aplicados"] == []
    assert log_disco["ancoras_encontradas"] == 0
