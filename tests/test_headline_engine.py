"""Testes do Headline Engine v2 (scripts/headline_engine.py) - geracao
isolada do `headline` da thumbnail (Grupos A-F, CLAUDE.md / docstring do
modulo). Cobre:

- Grupo A: extracao de payload editorial (distinto da conclusao central),
  fallback gracioso quando a extracao falha.
- Grupo B: geracao por mecanismo (filtros de FORMATO deterministicos -
  tamanho, repeticao de titulo, encaixe tipografico com fonte real,
  emphasis_word, termos de risco - preservados da v1).
- Grupo C: filtros SEMANTICOS deterministicos (pergunta sim/nao, sem
  mecanismo identificavel, so' palavra generica, afirmacao nao
  sustentada) + juiz com `answer_leak` como criterio-porta + juiz nunca
  reescreve.
- Grupo D: regeneracao (no maximo 1 rodada extra) e fallback pro melhor
  candidato com aviso de revisao humana quando as duas rodadas falham.
- Grupo F: modo degradado quando nucleo_editorial_status e' "ausente"
  (ou o campo nao existe).
- Grupo E: persistencia de auditoria completa em tres etapas separadas
  (payload_editorial, candidatos por rodada, julgamentos por rodada).

Convencoes (CLAUDE.md secao 8): nunca chama a API real - `cliente=` fake
em toda funcao (mesmo padrao de tests/test_thumbnail.py).
"""

import json

import pytest

from scripts import headline_engine as he

# ---------------------------------------------------------------------------
# Fakes do cliente Anthropic - mesmo padrao de tests/test_thumbnail.py
# ---------------------------------------------------------------------------


class _ClienteFake:
    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if not self._respostas:
            raise AssertionError("ClienteFake: mais chamadas do que respostas configuradas")
        return self._respostas.pop(0)


def _resposta_tool_use(nome_tool, dados_input, tokens_in=200, tokens_out=100):
    return {
        "content": [{"type": "tool_use", "name": nome_tool, "id": "toolu_1", "input": dados_input}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }


def _candidato(headline, mechanism="informacao_retida", withheld_fact="o que aconteceu depois", emphasis_word=""):
    return {"headline": headline, "mechanism": mechanism, "withheld_fact": withheld_fact, "emphasis_word": emphasis_word}


def _resposta_candidatos(lista_candidatos):
    return _resposta_tool_use(he.NOME_TOOL_CANDIDATOS, {"candidates": lista_candidatos})


def _julgamento(indice, opens_gap=2, anchored_to_case=2, not_title_repeat=2, not_revealing=2, answer_leak=2, concise_impact=2, visualizable=2):
    return {
        "candidate_index": indice,
        "opens_gap": opens_gap,
        "anchored_to_case": anchored_to_case,
        "not_title_repeat": not_title_repeat,
        "not_revealing": not_revealing,
        "answer_leak": answer_leak,
        "concise_impact": concise_impact,
        "visualizable": visualizable,
    }


def _resposta_julgamento(lista_notas):
    return _resposta_tool_use(he.NOME_TOOL_JULGAMENTO, {"judgments": lista_notas})


def _resposta_nucleo_compacto(texto):
    return _resposta_tool_use(he.NOME_TOOL_NUCLEO_COMPACTO, {"nucleo_compacto": texto})


def _payload_editorial(
    conclusao_central="A testemunha foi silenciada por causa do que sabia",
    payload="um pagamento de $50 mil dias antes do julgamento",
    payload_role="numero",
    hidden_question="What was that payment for?",
    tension_source="a hidden financial motive",
    concrete_anchor="a bank transfer receipt",
    information_gap="o que o pagamento realmente comprou",
    supporting_facts=None,
    reveal_level="partial",
):
    return {
        "conclusao_central": conclusao_central,
        "payload": payload,
        "payload_role": payload_role,
        "hidden_question": hidden_question,
        "tension_source": tension_source,
        "concrete_anchor": concrete_anchor,
        "information_gap": information_gap,
        "supporting_facts": supporting_facts if supporting_facts is not None else ["pagamento registrado em banco", "testemunha morreu na vespera do julgamento"],
        "reveal_level": reveal_level,
    }


def _resposta_payload(**overrides):
    dados = _payload_editorial(**overrides)
    return _resposta_tool_use(he.NOME_TOOL_PAYLOAD, dados)


def _montar_projeto(
    pasta,
    nucleo_editorial="A morte de uma testemunha-chave",
    status="ok",
    pergunta_promessa="Por que a testemunha-chave morreu na vespera do julgamento?",
    titulo="A Testemunha Que Nunca Depos",
    incluir_job_metadata=True,
):
    if incluir_job_metadata:
        job_metadata = {"pergunta_promessa": pergunta_promessa}
        if nucleo_editorial is not None:
            job_metadata["nucleo_editorial"] = nucleo_editorial
        if status is not None:
            job_metadata["nucleo_editorial_status"] = status
        (pasta / "job_metadata.json").write_text(json.dumps(job_metadata), encoding="utf-8")
    (pasta / "titulo.txt").write_text(titulo, encoding="utf-8")


ROTEIRO_TEXTO = "Era uma vez um caso real investigado pela policia local."


# ---------------------------------------------------------------------------
# Grupo A - extracao de payload editorial
# ---------------------------------------------------------------------------


def test_extrair_payload_editorial_sucesso():
    cliente = _ClienteFake([_resposta_payload()])
    payload, erro = he.extrair_payload_editorial(
        cliente, "modelo-fake", "nucleo", "pergunta", "titulo", ROTEIRO_TEXTO
    )
    assert erro is None
    assert payload["payload"] == "um pagamento de $50 mil dias antes do julgamento"
    assert payload["conclusao_central"] == "A testemunha foi silenciada por causa do que sabia"
    assert payload["payload_role"] == "numero"
    assert payload["fallback"] is False


def test_extrair_payload_editorial_payload_igual_conclusao_ainda_e_aceito_pela_funcao():
    """A funcao em si nao IMPEDE payload==conclusao (isso e' regra de
    PROMPT, nao de codigo - o modelo e' instruido a nunca fazer isso) -
    so' valida presenca/nao-vazio dos dois campos obrigatorios."""
    cliente = _ClienteFake([_resposta_payload(payload="X", conclusao_central="X")])
    payload, erro = he.extrair_payload_editorial(cliente, "modelo-fake", "n", "p", "t", ROTEIRO_TEXTO)
    assert erro is None
    assert payload["payload"] == "X"


def test_extrair_payload_editorial_sem_payload_ou_conclusao_e_invalido():
    dados = _payload_editorial()
    dados["payload"] = ""
    cliente = _ClienteFake([_resposta_tool_use(he.NOME_TOOL_PAYLOAD, dados)])
    payload, erro = he.extrair_payload_editorial(cliente, "modelo-fake", "n", "p", "t", ROTEIRO_TEXTO)
    assert payload is None
    assert erro == "payload_invalido"


def test_extrair_payload_editorial_excecao_da_api_nunca_propaga():
    class _Quebrado:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("falha simulada")

    payload, erro = he.extrair_payload_editorial(_Quebrado(), "modelo-fake", "n", "p", "t", ROTEIRO_TEXTO)
    assert payload is None
    assert erro["codigo"] == "chamada_api_falhou"
    assert erro["tipo"] == "RuntimeError"


def test_extrair_payload_editorial_descarta_supporting_facts_com_caracteres_isolados():
    """Achado real (validacao Grupo G contra API real, projeto Burke
    Ramsey): uma resposta real devolveu `supporting_facts` como uma lista
    de caracteres isolados (lixo de formato) em vez de frases curtas -
    esses itens tem que ser descartados, nunca persistidos como se fossem
    fatos de verdade."""
    dados = _payload_editorial(supporting_facts=["a", "p", "fato real com mais de 8 caracteres", "x"])
    cliente = _ClienteFake([_resposta_tool_use(he.NOME_TOOL_PAYLOAD, dados)])
    payload, erro = he.extrair_payload_editorial(cliente, "modelo-fake", "n", "p", "t", ROTEIRO_TEXTO)
    assert erro is None
    assert payload["supporting_facts"] == ["fato real com mais de 8 caracteres"]


def test_payload_fallback_marca_fallback_true_e_nunca_usa_pergunta_como_payload_role_invalido():
    fallback = he._payload_fallback("nucleo aqui", "pergunta aqui")
    assert fallback["fallback"] is True
    assert fallback["payload"] == "nucleo aqui"
    assert fallback["conclusao_central"] == "pergunta aqui"
    assert fallback["payload_role"] in he.PAYLOAD_ROLES_VALIDOS
    assert fallback["supporting_facts"] == []


# ---------------------------------------------------------------------------
# Grupo B(filtros) - filtros deterministicos de FORMATO (preservados da v1)
# ---------------------------------------------------------------------------


def test_filtro_formato_elimina_candidato_com_mais_de_6_palavras():
    candidatos = [_candidato("THIS HEADLINE HAS WAY TOO MANY WORDS INDEED")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "mais_de_6_palavras"


def test_filtro_formato_mantem_candidato_com_exatamente_6_palavras():
    candidatos = [_candidato("ONE TWO THREE FOUR FIVE SIX")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert eliminados == []
    assert len(sobreviventes) == 1


def test_filtro_formato_elimina_candidato_substring_do_titulo():
    titulo = "The Shocking Case That Stunned The City"
    candidatos = [_candidato("SHOCKING CASE THAT STUNNED")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, titulo)
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "substring_do_titulo"


def test_filtro_formato_elimina_candidato_com_alta_sobreposicao_de_titulo_sem_ser_substring():
    titulo = "What The Detective Found In Her House"
    candidatos = [_candidato("HOUSE FOUND HER DETECTIVE STRANGE")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, titulo)
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "alta_sobreposicao_com_titulo"


def test_filtro_formato_elimina_candidato_com_emphasis_word_ausente_do_headline():
    candidatos = [_candidato("WHAT SHE SAW THAT NIGHT", emphasis_word="PALAVRA_ORFA")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "emphasis_word_ausente_no_headline"


def test_filtro_formato_mantem_candidato_com_emphasis_word_vazia():
    candidatos = [_candidato("WHAT SHE SAW THAT NIGHT", emphasis_word="")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert eliminados == []


def test_filtro_formato_elimina_candidato_com_termo_de_risco(monkeypatch):
    monkeypatch.delenv("HEADLINE_TERMOS_RISCO", raising=False)
    candidatos = [_candidato("WHY HE WAS KILLED THAT NIGHT")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert sobreviventes == []
    assert eliminados[0]["motivo"].startswith("termo_de_risco:")


def test_filtro_formato_respeita_lista_de_risco_configurada_por_env(monkeypatch):
    monkeypatch.setenv("HEADLINE_TERMOS_RISCO", "banana")
    candidatos = [_candidato("WHY HE WAS KILLED THAT NIGHT")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert eliminados == []
    assert len(sobreviventes) == 1


def test_filtro_formato_encaixe_tipografico_usa_fonte_real_e_elimina_headline_largo():
    candidato_largo = _candidato("INVESTIGATORS DISCOVERED SOMETHING TRULY UNEXPECTED YESTERDAY")
    candidato_curto = _candidato("WHY SHE NEVER LEFT")

    assert he._cabe_na_area_segura(candidato_largo["headline"]) is False
    assert he._cabe_na_area_segura(candidato_curto["headline"]) is True

    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(
        [candidato_largo, candidato_curto], "Titulo Qualquer"
    )
    assert len(sobreviventes) == 1
    assert sobreviventes[0]["headline"] == "WHY SHE NEVER LEFT"
    assert eliminados[0]["motivo"] == "nao_cabe_area_segura"


def test_filtro_formato_elimina_candidato_com_headline_vazio():
    candidatos = [_candidato("")]
    sobreviventes, eliminados = he.filtrar_candidatos_deterministicos(candidatos, "Titulo Qualquer")
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "headline_vazio"


# ---------------------------------------------------------------------------
# Grupo C(rejeicao) - filtros semanticos deterministicos (novos na v2)
# ---------------------------------------------------------------------------


def test_rejeicao_pergunta_sim_nao_e_eliminada_antes_do_juiz():
    """Achado real (caso Burke Ramsey): "DNA EXCLUDED HIM?" tem o formato
    de pergunta fechada - a resposta ja' parece implicita ao lado do
    titulo."""
    candidatos = [_candidato("DNA EXCLUDED HIM?")]
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos(candidatos, _payload_editorial())
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "pergunta_sim_nao"


def test_rejeicao_pergunta_aberta_wh_nunca_e_tratada_como_sim_nao():
    candidatos = [_candidato("WHY SHE NEVER LEFT?", withheld_fact="o motivo dela ficar")]
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos(candidatos, _payload_editorial(supporting_facts=["ela nunca deixou a casa", "motivo desconhecido"]))
    assert eliminados == []
    assert len(sobreviventes) == 1


def test_rejeicao_headline_sem_ponto_de_interrogacao_nunca_e_pergunta_sim_nao():
    assert he._e_pergunta_sim_nao("DNA EXCLUDED HIM") is False


def test_rejeicao_sem_mecanismo_identificavel():
    candidato_sem_mecanismo = _candidato("SOMETHING VAGUE HAPPENED HERE", mechanism="nao_existe")
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato_sem_mecanismo], _payload_editorial())
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "sem_mecanismo_identificavel"


def test_rejeicao_withheld_fact_vazio_conta_como_sem_mecanismo():
    candidato = _candidato("SOMETHING HAPPENED", mechanism="tempo", withheld_fact="")
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato], _payload_editorial())
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "sem_mecanismo_identificavel"


def test_rejeicao_apenas_palavra_generica():
    candidato = _candidato("THE SHOCKING TRUTH", withheld_fact="pagamento oculto")
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato], _payload_editorial())
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "apenas_palavra_generica"


def test_rejeicao_palavra_generica_com_termo_concreto_junto_sobrevive():
    """"THE SECRET PAYMENT" tem "secret" (generico) mas TAMBEM "payment"
    (conteudo concreto nao-generico) - nao e' eliminado por esta regra
    (pode ainda ser eliminado por outra, mas nao por "so' generico")."""
    candidato = _candidato("THE SECRET PAYMENT", withheld_fact="um pagamento de $50 mil registrado em banco")
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato], _payload_editorial())
    assert eliminados == []
    assert len(sobreviventes) == 1


def test_rejeicao_afirmacao_nao_sustentada_pelo_roteiro():
    candidato = _candidato("SOMETHING HAPPENED", mechanism="objeto", withheld_fact="uma nave espacial apareceu no quintal")
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato], _payload_editorial())
    assert sobreviventes == []
    assert eliminados[0]["motivo"] == "afirmacao_nao_sustentada"


def test_rejeicao_afirmacao_sustentada_por_overlap_com_supporting_facts_sobrevive():
    candidato = _candidato(
        "SOMETHING HAPPENED", mechanism="numero",
        withheld_fact="o pagamento registrado em banco antes do julgamento",
    )
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato], _payload_editorial())
    assert eliminados == []
    assert len(sobreviventes) == 1


def test_rejeicao_afirmacao_sem_material_de_payload_nunca_reprova_por_falta_de_lastro():
    """Payload em fallback (sem supporting_facts, sem concrete_anchor) -
    nunca ha' base pra' comparar, entao esta regra especifica NUNCA vira o
    motivo de reprovacao (outras regras continuam valendo)."""
    payload_vazio = he._payload_fallback("", "")
    candidato = _candidato("SOMETHING HAPPENED", mechanism="numero", withheld_fact="qualquer coisa")
    sobreviventes, eliminados = he.filtrar_candidatos_semanticos([candidato], payload_vazio)
    assert eliminados == []


def test_contar_mecanismos_distintos():
    candidatos = [
        _candidato("A", mechanism="tempo"),
        _candidato("B", mechanism="tempo"),
        _candidato("C", mechanism="numero"),
        _candidato("D", mechanism="objeto"),
        _candidato("E", mechanism="consequencia"),
        _candidato("F", mechanism="consequencia"),
    ]
    assert he.contar_mecanismos_distintos(candidatos) == 4


# ---------------------------------------------------------------------------
# Grupo C(juiz) - juiz nunca reescreve, answer_leak e' porta
# ---------------------------------------------------------------------------


def test_juiz_nunca_altera_texto_dos_candidatos():
    candidatos = [_candidato("WHAT ABDUCTOR WANTED"), _candidato("WHY SHE NEVER LEFT")]
    candidatos_copia = [dict(c) for c in candidatos]

    cliente = _ClienteFake([_resposta_julgamento([_julgamento(0), _julgamento(1, opens_gap=0)])])
    julgamentos, erro = he.julgar_candidatos(cliente, "modelo-fake", candidatos, "Titulo Qualquer", "conclusao central")

    assert erro is None
    assert candidatos == candidatos_copia  # juiz nao mutou a lista de entrada
    for j in julgamentos:
        assert "headline" not in j
    assert julgamentos[0]["total"] == 14
    assert julgamentos[1]["opens_gap"] == 0


def test_juiz_envia_conclusao_central_na_mensagem():
    cliente = _ClienteFake([_resposta_julgamento([_julgamento(0)])])
    he.julgar_candidatos(cliente, "modelo-fake", [_candidato("X")], "Titulo", "a conclusao secreta do caso")
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"]
    assert "a conclusao secreta do caso" in texto_enviado


def test_juiz_chamada_nao_passa_temperature():
    """Bug corrigido na v1 (pos-Sessao 24): a Claude Sonnet 5 REMOVEU o
    parametro de sampling explicito - `temperature`/`top_p`/`top_k`
    sempre devolvem 400. Nunca reintroduzir nesta chamada."""
    cliente = _ClienteFake([_resposta_julgamento([_julgamento(0)])])
    he.julgar_candidatos(cliente, "modelo-fake", [_candidato("WHAT ABDUCTOR WANTED")], "Titulo", "conclusao")
    assert "temperature" not in cliente.chamadas[0]
    assert "top_p" not in cliente.chamadas[0]
    assert "top_k" not in cliente.chamadas[0]


def test_juiz_excecao_da_api_nunca_propaga():
    class _Quebrado:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("falha simulada")

    julgamentos, erro = he.julgar_candidatos(_Quebrado(), "modelo-fake", [_candidato("X")], "Titulo", "conclusao")
    assert julgamentos is None
    assert erro["codigo"] == "chamada_api_falhou"
    assert erro["tipo"] == "RuntimeError"
    assert erro["mensagem"] == "falha simulada"
    assert erro["status_code"] is None


def test_selecionar_vencedor_nao_aprova_quando_criterio_1_ou_2_zerado():
    candidatos = [_candidato("A B C"), _candidato("D E F")]
    julgamentos = [
        {"opens_gap": 2, "anchored_to_case": 0, "not_title_repeat": 2, "not_revealing": 2, "answer_leak": 2, "concise_impact": 2, "visualizable": 2, "total": 12},
        {"opens_gap": 1, "anchored_to_case": 1, "not_title_repeat": 1, "not_revealing": 1, "answer_leak": 1, "concise_impact": 1, "visualizable": 1, "total": 7},
    ]
    indice, aprovado = he.selecionar_vencedor(candidatos, julgamentos)
    assert aprovado is False
    assert indice is None


def test_selecionar_vencedor_nao_aprova_quando_answer_leak_zerado_mesmo_com_total_alto():
    """O criterio NOVO da v2 (answer_leak) e' porta igual aos outros dois
    - um candidato pode ter opens_gap/anchored_to_case altos e ainda
    assim ser desqualificado por vazar a conclusao quando somado ao
    titulo."""
    candidatos = [_candidato("DNA EXCLUDED HIM SOMEHOW")]
    julgamentos = [
        {"opens_gap": 2, "anchored_to_case": 2, "not_title_repeat": 2, "not_revealing": 2, "answer_leak": 0, "concise_impact": 2, "visualizable": 2, "total": 12},
    ]
    indice, aprovado = he.selecionar_vencedor(candidatos, julgamentos)
    assert aprovado is False
    assert indice is None


def test_selecionar_vencedor_empate_escolhe_o_mais_curto():
    candidatos = [_candidato("A LONGER HEADLINE HERE"), _candidato("SHORT ONE")]
    nota_cheia = {"opens_gap": 2, "anchored_to_case": 2, "not_title_repeat": 1, "not_revealing": 1, "answer_leak": 1, "concise_impact": 1, "visualizable": 1, "total": 9}
    julgamentos = [dict(nota_cheia), dict(nota_cheia)]
    indice, aprovado = he.selecionar_vencedor(candidatos, julgamentos)
    assert aprovado is True
    assert candidatos[indice]["headline"] == "SHORT ONE"


# ---------------------------------------------------------------------------
# Grupo D/A-C/E - orquestracao completa (gerar_headline)
# ---------------------------------------------------------------------------


def _seis_candidatos_sustentados(prefixo="HEADLINE NUMERO"):
    """6 candidatos que sobrevivem aos filtros de formato E semanticos
    contra o `_payload_editorial()` padrao (withheld_fact compartilha
    token >=4 chars com os supporting_facts padrao: "pagamento"/
    "testemunha"/"banco"/"julgamento")."""
    return [
        _candidato(f"{prefixo} {i}", mechanism="numero", withheld_fact="detalhes do pagamento registrado em banco")
        for i in range(6)
    ]


def test_gerar_headline_sucesso_de_primeira_persiste_auditoria(tmp_path):
    _montar_projeto(tmp_path)
    candidatos = _seis_candidatos_sustentados()
    julgamentos = [
        _julgamento(i, opens_gap=1, anchored_to_case=1, not_title_repeat=1, not_revealing=1, answer_leak=1, concise_impact=0, visualizable=0)
        for i in range(6)
    ]
    julgamentos[3] = _julgamento(3)  # nota cheia (14/14)

    cliente = _ClienteFake([_resposta_payload(), _resposta_candidatos(candidatos), _resposta_julgamento(julgamentos)])
    custos = []
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente, _custos=custos)

    assert resultado["sucesso"] is True
    assert resultado["headline"] == "HEADLINE NUMERO 3"
    assert resultado["judge_score"] == 14
    assert resultado["fallback_usado"] is False
    assert resultado["aviso_revisao_humana"] is False
    assert resultado["nucleo_editorial_status"] == "ok"
    assert resultado["conclusao_central"] == "A testemunha foi silenciada por causa do que sabia"
    assert resultado["payload"] == "um pagamento de $50 mil dias antes do julgamento"
    assert resultado["payload_extracao_fallback"] is False
    assert len(cliente.chamadas) == 3  # payload + candidatos + juiz
    assert len(custos) == 3

    auditoria = json.loads((tmp_path / "thumbnail" / "headline_engine.json").read_text(encoding="utf-8"))
    assert auditoria["numero_rodadas"] == 1
    assert auditoria["vencedor"]["headline"] == "HEADLINE NUMERO 3"
    assert auditoria["versao_prompt"] == he.VERSAO_PROMPT
    # Grupo D - auditoria por etapa: payload extraido persistido separado.
    assert auditoria["payload_editorial"]["payload"] == "um pagamento de $50 mil dias antes do julgamento"
    assert auditoria["payload_extracao_fallback"] is False
    assert auditoria["rodadas"][0]["mecanismos_distintos_gerados"] == 1


def test_gerar_headline_payload_extraction_falha_cai_em_fallback_e_segue(tmp_path):
    _montar_projeto(tmp_path)
    candidatos = _seis_candidatos_sustentados()
    julgamentos = [_julgamento(i) for i in range(6)]

    # Sem resposta configurada pra' payload -> primeira chamada
    # (extrair_payload_editorial) falha; o motor tem que degradar com
    # _payload_fallback e seguir pra' Grupo B normalmente.
    class _ClienteComFalhaSoNaPrimeira(_ClienteFake):
        def create(self, **kwargs):
            self.chamadas.append(kwargs)
            if len(self.chamadas) == 1:
                raise RuntimeError("payload API fora do ar")
            return self._respostas.pop(0)

    cliente = _ClienteComFalhaSoNaPrimeira([_resposta_candidatos(candidatos), _resposta_julgamento(julgamentos)])
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["payload_extracao_fallback"] is True
    # Fallback usa nucleo_editorial como payload.
    assert resultado["payload"] == "A morte de uma testemunha-chave"

    auditoria = json.loads((tmp_path / "thumbnail" / "headline_engine.json").read_text(encoding="utf-8"))
    assert auditoria["payload_extracao_fallback"] is True
    assert auditoria["payload_editorial"]["fallback"] is True


def test_gerar_headline_todos_eliminados_na_primeira_rodada_dispara_regeneracao(tmp_path):
    _montar_projeto(tmp_path)
    candidatos_ruins = [
        _candidato(f"THIS HEADLINE HAS WAY TOO MANY WORDS NUMBER {i}", mechanism="numero", withheld_fact="pagamento em banco")
        for i in range(6)
    ]
    candidatos_bons = _seis_candidatos_sustentados("SHORT HEADLINE")
    julgamentos_rodada2 = [
        _julgamento(i, opens_gap=0, anchored_to_case=0, not_title_repeat=0, not_revealing=0, answer_leak=0, concise_impact=0, visualizable=0)
        for i in range(6)
    ]
    julgamentos_rodada2[5] = _julgamento(5)

    cliente = _ClienteFake(
        [
            _resposta_payload(),
            _resposta_candidatos(candidatos_ruins),
            _resposta_candidatos(candidatos_bons),
            _resposta_julgamento(julgamentos_rodada2),
        ]
    )
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["headline"] == "SHORT HEADLINE 5"
    assert resultado["aviso_revisao_humana"] is False
    assert len(cliente.chamadas) == 4  # payload + 2 rodadas de candidatos + 1 juiz

    auditoria = json.loads((tmp_path / "thumbnail" / "headline_engine.json").read_text(encoding="utf-8"))
    assert auditoria["numero_rodadas"] == 2
    assert auditoria["rodadas"][0]["sobreviventes"] == []
    assert len(auditoria["rodadas"][0]["eliminados"]) == 6
    for eliminado in auditoria["rodadas"][0]["eliminados"]:
        assert eliminado["motivo"] == "mais_de_6_palavras"
        assert "candidato" in eliminado


def test_gerar_headline_duas_rodadas_reprovadas_persiste_melhor_com_aviso(tmp_path):
    _montar_projeto(tmp_path)
    candidatos_r1 = _seis_candidatos_sustentados("HEADLINE R1")
    julgamentos_r1 = [
        _julgamento(i, opens_gap=1, anchored_to_case=1, not_title_repeat=0, not_revealing=0, answer_leak=1, concise_impact=0, visualizable=0)
        for i in range(6)
    ]  # total 3 cada - nunca passa do limiar (9)
    candidatos_r2 = _seis_candidatos_sustentados("HEADLINE R2")
    julgamentos_r2 = [
        _julgamento(i, opens_gap=1, anchored_to_case=1, not_title_repeat=0, not_revealing=0, answer_leak=1, concise_impact=1, visualizable=0)
        for i in range(6)
    ]  # total 4 cada - ainda abaixo do limiar, mas maior que a rodada 1

    cliente = _ClienteFake(
        [
            _resposta_payload(),
            _resposta_candidatos(candidatos_r1),
            _resposta_julgamento(julgamentos_r1),
            _resposta_candidatos(candidatos_r2),
            _resposta_julgamento(julgamentos_r2),
        ]
    )
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["aviso_revisao_humana"] is True
    assert resultado["headline"].startswith("HEADLINE R2")
    assert resultado["judge_score"] == 4
    assert len(cliente.chamadas) == 5

    auditoria = json.loads((tmp_path / "thumbnail" / "headline_engine.json").read_text(encoding="utf-8"))
    assert auditoria["numero_rodadas"] == 2
    assert auditoria["aviso_revisao_humana"] is True
    assert resultado["fallback_sem_julgamento"] is False
    assert auditoria["fallback_sem_julgamento"] is False


# ---------------------------------------------------------------------------
# Bug corrigido na v1 (pos-Sessao 24), preservado na v2: falha do juiz
# (erro de infraestrutura) NAO pode disparar uma rodada extra de geracao.
# ---------------------------------------------------------------------------


def test_gerar_headline_juiz_falha_na_primeira_rodada_nao_dispara_segunda_geracao(tmp_path):
    _montar_projeto(tmp_path)
    candidatos = _seis_candidatos_sustentados()
    # payload + candidatos respondem; a chamada do juiz (3a chamada) cai
    # no "mais chamadas do que respostas configuradas".
    cliente = _ClienteFake([_resposta_payload(), _resposta_candidatos(candidatos)])

    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["aviso_revisao_humana"] is True
    assert resultado["fallback_sem_julgamento"] is True
    assert resultado["judge_score"] is None
    assert resultado["headline"] == "HEADLINE NUMERO 0"
    # 3 chamadas: payload + candidatos (sucesso) + juiz (falhou). NUNCA 4 -
    # se fosse 4, teria disparado uma segunda rodada de geracao por causa
    # da falha do juiz.
    assert len(cliente.chamadas) == 3

    auditoria = json.loads((tmp_path / "thumbnail" / "headline_engine.json").read_text(encoding="utf-8"))
    assert auditoria["numero_rodadas"] == 1
    assert auditoria["juiz_falhou_com_sobreviventes"] is True
    assert auditoria["fallback_sem_julgamento"] is True
    assert auditoria["rodadas"][0]["julgamentos"] is None
    erro_julgamento = auditoria["rodadas"][0]["erro_julgamento"]
    assert erro_julgamento["codigo"] == "chamada_api_falhou"
    assert erro_julgamento["tipo"] == "AssertionError"


def test_gerar_headline_juiz_sucesso_mas_sem_sobreviventes_ainda_permite_regeneracao(tmp_path):
    """Contraste com o teste acima: quando o problema e' "todos os
    candidatos foram eliminados pelos filtros" (nunca chega a chamar o
    juiz), a regeneracao CONTINUA valendo - so' falha de INFRAESTRUTURA
    do juiz e' que nao dispara mais rodada extra."""
    _montar_projeto(tmp_path)
    candidatos_ruins = [
        _candidato(f"THIS HEADLINE HAS WAY TOO MANY WORDS NUMBER {i}", mechanism="numero", withheld_fact="pagamento em banco")
        for i in range(6)
    ]
    candidatos_bons = _seis_candidatos_sustentados("SHORT HEADLINE")
    julgamentos_bons = [_julgamento(i) for i in range(6)]

    cliente = _ClienteFake(
        [
            _resposta_payload(),
            _resposta_candidatos(candidatos_ruins),
            _resposta_candidatos(candidatos_bons),
            _resposta_julgamento(julgamentos_bons),
        ]
    )
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["fallback_sem_julgamento"] is False
    assert len(cliente.chamadas) == 4


def test_gerar_headline_modo_degradado_quando_status_ausente(tmp_path):
    _montar_projeto(tmp_path, nucleo_editorial=None, status="ausente")
    candidatos = _seis_candidatos_sustentados()
    julgamentos = [_julgamento(i) for i in range(6)]

    cliente = _ClienteFake(
        [
            _resposta_nucleo_compacto("nucleo compacto derivado"),
            _resposta_payload(),
            _resposta_candidatos(candidatos),
            _resposta_julgamento(julgamentos),
        ]
    )
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["fallback_usado"] is True
    assert resultado["nucleo_editorial_status"] == "ausente"
    assert len(cliente.chamadas) == 4

    auditoria = json.loads((tmp_path / "thumbnail" / "headline_engine.json").read_text(encoding="utf-8"))
    assert auditoria["fallback_usado"] is True
    assert auditoria["nucleo_editorial_usado"] == "nucleo compacto derivado"


def test_gerar_headline_modo_degradado_quando_campo_nao_existe(tmp_path):
    """Projeto antigo (job_metadata.json sem nucleo_editorial_status
    nenhum, campo nunca existiu) tambem cai no modo degradado."""
    (tmp_path / "job_metadata.json").write_text(
        json.dumps({"pergunta_promessa": "Por que ela nunca foi embora daquela casa?"}), encoding="utf-8"
    )
    (tmp_path / "titulo.txt").write_text("Titulo Aprovado", encoding="utf-8")

    candidatos = _seis_candidatos_sustentados()
    julgamentos = [_julgamento(i) for i in range(6)]
    cliente = _ClienteFake(
        [_resposta_nucleo_compacto("nucleo derivado"), _resposta_payload(), _resposta_candidatos(candidatos), _resposta_julgamento(julgamentos)]
    )
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)
    assert resultado["fallback_usado"] is True


def test_gerar_headline_sem_job_metadata_cai_em_modo_degradado_com_pergunta_vazia(tmp_path):
    """Sem job_metadata.json (upload de roteiro) - modo degradado tenta
    extrair nucleo da pergunta-promessa vazia, falha graciosamente, e
    segue com um nucleo minimo em vez de travar."""
    (tmp_path / "titulo.txt").write_text("Titulo Aprovado", encoding="utf-8")
    candidatos = _seis_candidatos_sustentados()
    julgamentos = [_julgamento(i) for i in range(6)]
    cliente = _ClienteFake([_resposta_payload(), _resposta_candidatos(candidatos), _resposta_julgamento(julgamentos)])

    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["fallback_usado"] is True
    # extrair_nucleo_compacto devolveu erro (sem pergunta-promessa) sem
    # chamar a API - so' 3 chamadas (payload + candidatos + juiz), nao 4.
    assert len(cliente.chamadas) == 3


def test_gerar_headline_primeira_rodada_de_candidatos_falha_sem_persistir_nada(tmp_path):
    """Payload extraido com sucesso, mas Grupo B (candidatos) falha nas
    duas rodadas - nenhuma geracao de candidatos aconteceu, entao nao ha'
    nada pra' persistir."""
    _montar_projeto(tmp_path)
    cliente = _ClienteFake([_resposta_payload()])  # so' a resposta do payload - candidatos falha
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is False
    assert resultado["erro"]["codigo"] == "chamada_api_falhou"
    assert resultado["erro"]["tipo"] == "AssertionError"
    assert not (tmp_path / "thumbnail" / "headline_engine.json").exists()


def test_gerar_headline_cliente_indisponivel(tmp_path):
    _montar_projeto(tmp_path)
    resultado = he.gerar_headline(tmp_path, ROTEIRO_TEXTO, api_key=None, cliente=None)
    assert resultado == {"sucesso": False, "erro": "cliente_indisponivel"}


# ---------------------------------------------------------------------------
# Grupo F - extracao de nucleo compacto (funcao isolada)
# ---------------------------------------------------------------------------


def test_extrair_nucleo_compacto_sem_pergunta_promessa_nao_chama_api():
    cliente = _ClienteFake([])
    nucleo, erro = he.extrair_nucleo_compacto(cliente, "modelo-fake", "")
    assert nucleo is None
    assert erro == "pergunta_promessa_ausente"
    assert cliente.chamadas == []


def test_extrair_nucleo_compacto_valida_faixa_de_2_a_8_palavras():
    cliente = _ClienteFake([_resposta_nucleo_compacto("uma palavra so")])
    nucleo, erro = he.extrair_nucleo_compacto(cliente, "modelo-fake", "pergunta valida aqui")
    assert nucleo == "uma palavra so"
    assert erro is None

    cliente2 = _ClienteFake([_resposta_nucleo_compacto("nucleo")])  # 1 palavra - invalido
    nucleo2, erro2 = he.extrair_nucleo_compacto(cliente2, "modelo-fake", "pergunta valida aqui")
    assert nucleo2 is None
    assert erro2 == "nucleo_invalido"


# ---------------------------------------------------------------------------
# Idioma explicito (preservado da v1) - agora tambem na Grupo A (payload).
# ---------------------------------------------------------------------------


def test_extrair_payload_editorial_inclui_idioma_explicito_na_mensagem():
    cliente = _ClienteFake([_resposta_payload()])
    he.extrair_payload_editorial(cliente, "modelo-fake", "nucleo", "pergunta", "titulo", ROTEIRO_TEXTO, idioma="es")
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert "Idioma exigido para TODOS os campos de texto: es" in texto_enviado


def test_gerar_candidatos_headline_inclui_idioma_explicito_na_mensagem():
    cliente = _ClienteFake([_resposta_candidatos(_seis_candidatos_sustentados())])
    he.gerar_candidatos_headline(
        cliente, "modelo-fake", _payload_editorial(), "titulo", ROTEIRO_TEXTO, idioma="es"
    )
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert "Idioma exigido para TODOS os campos de texto (headline, withheld_fact): es" in texto_enviado


def test_gerar_candidatos_headline_usa_idioma_padrao_quando_omitido():
    cliente = _ClienteFake([_resposta_candidatos(_seis_candidatos_sustentados())])
    he.gerar_candidatos_headline(cliente, "modelo-fake", _payload_editorial(), "titulo", ROTEIRO_TEXTO)
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert f"Idioma exigido para TODOS os campos de texto (headline, withheld_fact): {he.IDIOMA_PADRAO}" in texto_enviado


def test_gerar_candidatos_headline_envia_conclusao_central_e_nunca_so_nucleo():
    """Mudanca de assinatura v1->v2: a Chamada B recebe o `payload_editorial`
    inteiro (payload/conclusao_central/etc), nao mais nucleo_editorial/
    pergunta_promessa soltos."""
    cliente = _ClienteFake([_resposta_candidatos(_seis_candidatos_sustentados())])
    he.gerar_candidatos_headline(cliente, "modelo-fake", _payload_editorial(), "titulo", ROTEIRO_TEXTO)
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert "um pagamento de $50 mil dias antes do julgamento" in texto_enviado
    assert "A testemunha foi silenciada por causa do que sabia" in texto_enviado


def test_extrair_nucleo_compacto_inclui_idioma_explicito_na_mensagem():
    cliente = _ClienteFake([_resposta_nucleo_compacto("um nucleo qualquer aqui")])
    he.extrair_nucleo_compacto(cliente, "modelo-fake", "pergunta valida aqui", idioma="de")
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"]
    assert "Idioma exigido para a resposta: de" in texto_enviado


def test_ler_contexto_usa_idioma_do_job_metadata(tmp_path):
    _montar_projeto(tmp_path)
    job_metadata = json.loads((tmp_path / "job_metadata.json").read_text(encoding="utf-8"))
    job_metadata["idioma"] = "pt-BR"
    (tmp_path / "job_metadata.json").write_text(json.dumps(job_metadata), encoding="utf-8")

    contexto = he._ler_contexto(tmp_path)
    assert contexto["idioma"] == "pt-BR"


def test_ler_contexto_usa_idioma_roteiro_env_quando_job_metadata_nao_tem(tmp_path, monkeypatch):
    _montar_projeto(tmp_path)  # job_metadata.json sem campo "idioma"
    monkeypatch.setenv("IDIOMA_ROTEIRO", "en-GB")

    contexto = he._ler_contexto(tmp_path)
    assert contexto["idioma"] == "en-GB"


def test_ler_contexto_usa_default_en_us_sem_job_metadata_nem_env(tmp_path, monkeypatch):
    monkeypatch.delenv("IDIOMA_ROTEIRO", raising=False)
    contexto = he._ler_contexto(tmp_path)  # pasta vazia, sem job_metadata.json
    assert contexto["idioma"] == he.IDIOMA_PADRAO == "en-US"


def test_gerar_headline_repassa_idioma_do_projeto_para_grupo_a_e_b(tmp_path):
    """Integracao: job_metadata.json com idioma="es" - tanto a mensagem
    da Grupo A (payload) quanto da Grupo B (candidatos) tem que carregar
    essa diretiva, nunca o default."""
    _montar_projeto(tmp_path)
    job_metadata = json.loads((tmp_path / "job_metadata.json").read_text(encoding="utf-8"))
    job_metadata["idioma"] = "es"
    (tmp_path / "job_metadata.json").write_text(json.dumps(job_metadata), encoding="utf-8")

    candidatos = _seis_candidatos_sustentados()
    julgamentos = [_julgamento(i) for i in range(6)]
    cliente = _ClienteFake([_resposta_payload(), _resposta_candidatos(candidatos), _resposta_julgamento(julgamentos)])

    he.gerar_headline(tmp_path, ROTEIRO_TEXTO, "fake-key", cliente=cliente)

    texto_payload = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert "Idioma exigido para TODOS os campos de texto: es" in texto_payload
    texto_candidatos = cliente.chamadas[1]["messages"][0]["content"][0]["text"]
    assert "Idioma exigido para TODOS os campos de texto (headline, withheld_fact): es" in texto_candidatos
