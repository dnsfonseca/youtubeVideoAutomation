"""Testes do Grupo C da Etapa 7 (scripts/thumbnail_briefing.py) - briefing
exportavel: descricao de pessoa sem nome (Correcao 4), atributos por foto
via Vision leve, selecao de template (Correcao 3 - EVIDENCE_SCENE sempre
elegivel) e montagem dos 5 prompts (Correcao 1 - headline/emphasis_word de
uma linha so' no INVESTIGATOR_UPDATE; Correcao 2 - guarda de censura).

Convencoes (CLAUDE.md secao 8): nunca chama a API real da Anthropic -
`cliente=` fake em toda funcao que chama a IA.
"""

import json
import re
from pathlib import Path

import pytest
from PIL import Image

from scripts import thumbnail_briefing as tbrief


# ---------------------------------------------------------------------------
# Fakes do cliente Anthropic
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


class _ClienteQuebrado:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise RuntimeError("falha simulada de rede")


def _resposta_tool_use(nome_tool, dados_input, tokens_in=50, tokens_out=20):
    return {
        "content": [{"type": "tool_use", "name": nome_tool, "id": "toolu_1", "input": dados_input}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }


def _resposta_sem_tool_use():
    return {"content": [{"type": "text", "text": "recuso"}], "usage": {"input_tokens": 5, "output_tokens": 2}}


# ---------------------------------------------------------------------------
# descrever_pessoa_para_prompt / descrever_papel_curto (Correcao 4)
# ---------------------------------------------------------------------------


def test_descrever_pessoa_sem_atributos_usa_fallback_por_papel():
    descricao = tbrief.descrever_pessoa_para_prompt("suspeito")
    assert "person established as the case's suspect" in descricao
    assert "serious, unsettling expression" in descricao


def test_descrever_pessoa_papel_invalido_cai_em_outro():
    descricao = tbrief.descrever_pessoa_para_prompt("vilao_desconhecido")
    assert "person connected to the case" in descricao


def test_descrever_pessoa_usa_atributos_quando_presentes():
    descricao = tbrief.descrever_pessoa_para_prompt(
        "vitima", {"genero": "woman", "faixa_etaria": "middle-aged", "expressao": "a gentle smile"}
    )
    assert descricao == "middle-aged woman established as the case's victim, with a gentle smile"


def test_descrever_pessoa_atributos_com_genero_invalido_cai_em_person():
    descricao = tbrief.descrever_pessoa_para_prompt("vitima", {"genero": "robot"})
    assert descricao.startswith("person established as")


def test_descrever_pessoa_nunca_pode_conter_nome_proprio_por_construcao():
    """CORRECAO 4: a funcao nao aceita nenhum parametro de nome - so' papel
    e atributos visuais genericos. Uma chave extra "nome" no dict de
    atributos (ex: um chamador por engano tentando injetar identidade) e'
    simplesmente ignorada - so' `genero`/`faixa_etaria`/`expressao` sao
    lidos."""
    descricao = tbrief.descrever_pessoa_para_prompt("vitima", {"nome": "Nancy Guthrie", "expressao": "a warm smile"})
    assert "Nancy Guthrie" not in descricao
    assert "Nancy" not in descricao


# ---------------------------------------------------------------------------
# Achado real (caso Burke Ramsey/JonBenét): "young child woman" -
# _ajustar_genero_e_prefixo_para_crianca / descrever_pessoa_para_prompt
# nunca podem produzir uma descricao crianca+adulto contraditoria.
# ---------------------------------------------------------------------------


def test_descrever_pessoa_faixa_etaria_crianca_nunca_produz_contradicao():
    """Achado real: genero 'woman' + faixa_etaria 'young child' virava
    literalmente 'young child woman' no briefing gerado pela API real."""
    descricao = tbrief.descrever_pessoa_para_prompt(
        "vitima", {"genero": "woman", "faixa_etaria": "young child", "expressao": "a bright, cheerful smile"}
    )
    assert "woman" not in descricao
    assert "man" not in descricao
    assert descricao.startswith("girl established as the case's victim")


def test_descrever_pessoa_faixa_etaria_crianca_genero_man_vira_boy():
    descricao = tbrief.descrever_pessoa_para_prompt("outro", {"genero": "man", "faixa_etaria": "young child"})
    assert descricao.startswith("boy established as")
    assert "man" not in descricao.split("established")[0]


def test_descrever_pessoa_faixa_etaria_crianca_sem_genero_valido_vira_child():
    descricao = tbrief.descrever_pessoa_para_prompt("outro", {"faixa_etaria": "toddler"})
    assert descricao.startswith("child established as")


def test_descrever_pessoa_faixa_etaria_adulta_normal_nao_e_afetada():
    descricao = tbrief.descrever_pessoa_para_prompt(
        "vitima", {"genero": "woman", "faixa_etaria": "middle-aged", "expressao": "a gentle smile"}
    )
    assert descricao == "middle-aged woman established as the case's victim, with a gentle smile"


def test_ajustar_genero_e_prefixo_para_crianca_sem_sinal_devolve_inalterado():
    assert tbrief._ajustar_genero_e_prefixo_para_crianca("woman", "middle-aged") == ("woman", "middle-aged")
    assert tbrief._ajustar_genero_e_prefixo_para_crianca("man", None) == ("man", None)


def test_descrever_papel_curto_sem_genero():
    assert tbrief.descrever_papel_curto("suspeito") == "suspect"


def test_descrever_papel_curto_com_genero():
    assert tbrief.descrever_papel_curto("vitima", {"genero": "woman"}) == "female victim"
    assert tbrief.descrever_papel_curto("suspeito", {"genero": "man"}) == "male suspect"


# ---------------------------------------------------------------------------
# templates_elegiveis (tabela de selecao POR PAPEL). Decide por CATEGORIA
# de papel (alvo/acusado/autoridade), nao so' por presenca de foto.
#
# REGRA DE SEGURANCA (sessao de simplificacao da Etapa 7 - CLAUDE.md/
# HISTORICO_BUGS.md): EVIDENCE_SCENE NUNCA e' elegivel quando ha' pelo
# menos uma foto de sujeito enviada (`hero_papel` presente) - achado real:
# um par vitima+investigador chegou a ter EVIDENCE_SCENE elegivel (junto
# de outros) e o modelo escolheu, produzindo thumbnail sem nenhum dos
# dois rostos apesar das fotos disponiveis. So' a regra "sem hero nenhum"
# oferece EVIDENCE_SCENE.
# ---------------------------------------------------------------------------


def test_templates_elegiveis_sem_nenhum_sujeito_so_evidence_scene():
    assert tbrief.templates_elegiveis(None, None) == ("EVIDENCE_SCENE",)


def test_templates_elegiveis_so_secondary_sem_hero_trata_como_zero_sujeitos():
    """Upload fora de ordem (so' o slot secondary preenchido) nunca
    reordena os slots por conta propria - tratado como se nao houvesse
    sujeito nenhum utilizavel."""
    assert tbrief.templates_elegiveis(None, "vitima") == ("EVIDENCE_SCENE",)


@pytest.mark.parametrize("papel_unico", ["vitima", "suspeito", "investigador", "testemunha", "outro"])
def test_templates_elegiveis_um_sujeito_nao_seleciona_template_que_exige_dois(papel_unico):
    """Com so' 1 sujeito (qualquer papel), ARROW_TRIO e
    INVESTIGATOR_UPDATE nunca ficam elegiveis - os dois exigem hero E
    secondary pra' fazer sentido (seta/relacao entre duas pessoas).
    EVIDENCE_SCENE tambem nunca aparece aqui - ha' uma foto disponivel."""
    elegiveis = tbrief.templates_elegiveis(papel_unico, None)
    assert elegiveis == ("PROFILE_ISOLATION", "DUOTONE_DOSSIER")
    assert "ARROW_TRIO" not in elegiveis
    assert "INVESTIGATOR_UPDATE" not in elegiveis
    assert "EVIDENCE_SCENE" not in elegiveis


def test_templates_elegiveis_vitima_e_investigador_trava_em_investigator_update():
    """Vitima + investigador e' a referencia real que motivou o
    INVESTIGATOR_UPDATE - unico elegivel de proposito, sem ambiguidade
    genuina a resolver (evita repetir o achado real de um grid absurdo de
    15 copias do mesmo investigador)."""
    assert tbrief.templates_elegiveis("vitima", "investigador") == ("INVESTIGATOR_UPDATE",)
    assert tbrief.templates_elegiveis("investigador", "vitima") == ("INVESTIGATOR_UPDATE",)


@pytest.mark.parametrize("papel_acusado", ["suspeito", "condenado"])
def test_templates_elegiveis_vitima_e_acusado_oferece_arrow_trio_e_duotone(papel_acusado):
    """Vitima + suspeito/condenado - relacao de acusacao clara, "ambos com
    seta de acusacao" (ARROW_TRIO e' o template dedicado a essa
    composicao, DUOTONE_DOSSIER tambem suporta - ver seta sem grid la').
    Real ambiguidade estetica entre os dois: o Claude escolhe. Nunca
    EVIDENCE_SCENE - ha' fotos disponiveis."""
    elegiveis = tbrief.templates_elegiveis("vitima", papel_acusado)
    assert set(elegiveis) == {"ARROW_TRIO", "DUOTONE_DOSSIER"}


def test_templates_elegiveis_mesmo_papel_habilita_so_duotone_com_grid():
    """Multiplos sujeitos do MESMO papel (ex: duas vitimas do mesmo autor)
    - unico cenario onde o grid de 12-15 fotos do DUOTONE_DOSSIER faz
    sentido (representa varios, nao duplica a mesma pessoa). Unico
    elegivel - sem ambiguidade, nem EVIDENCE_SCENE (ha' fotos)."""
    assert tbrief.templates_elegiveis("vitima", "vitima") == ("DUOTONE_DOSSIER",)


def test_templates_elegiveis_combinacao_sem_relacao_clara_cai_no_dual_portrait():
    """Testemunha + outro nao tem relacao de acusacao nem autoridade nem
    mesmo papel - nenhum template de grid/seta/acusacao faz sentido, mas
    ha' DOIS sujeitos com foto disponivel, entao cai no fallback
    DUAL_PORTRAIT (unico elegivel, sem ambiguidade - nunca EVIDENCE_SCENE,
    que descartaria as duas fotos disponiveis).

    CORRECAO (caso real Burke Ramsey/JonBenét - vitima + "outro"): antes
    desta correcao, esta combinacao caia nas opcoes de retrato SOLO
    (PROFILE_ISOLATION/DUOTONE_DOSSIER), que ignoram a segunda foto por
    completo - o sistema nao tinha nenhuma composicao adequada pra' dois
    sujeitos sem relacao de acusacao."""
    assert tbrief.templates_elegiveis("testemunha", "outro") == ("DUAL_PORTRAIT",)
    assert tbrief.templates_elegiveis("vitima", "outro") == ("DUAL_PORTRAIT",)
    # mesmo papel cai na regra 5 (DUOTONE_DOSSIER com grid), nunca DUAL_PORTRAIT
    assert tbrief.templates_elegiveis("outro", "outro") == ("DUOTONE_DOSSIER",)


@pytest.mark.parametrize("papel_acusado", ["suspeito", "condenado"])
def test_templates_elegiveis_acusado_e_investigador_trava_em_investigator_update(papel_acusado):
    """Caso 8 (CORRECAO - seletor de template): suspeito/condenado +
    investigador nao tem um template dedicado 'acusado sendo investigado',
    mas NAO pode dar zero elegiveis nem cair em EVIDENCE_SCENE (haveria
    fotos disponiveis descartadas). Regra escolhida: a categoria
    AUTORIDADE (investigador) combinada com QUALQUER alvo/acusado
    (vitima/suspeito/condenado) sempre trava em INVESTIGATOR_UPDATE, sem
    ambiguidade - mesma regra 3 de `templates_elegiveis`, que nao
    distingue "vitima" de "suspeito/condenado" do outro lado do par."""
    assert tbrief.templates_elegiveis(papel_acusado, "investigador") == ("INVESTIGATOR_UPDATE",)
    assert tbrief.templates_elegiveis("investigador", papel_acusado) == ("INVESTIGATOR_UPDATE",)


@pytest.mark.parametrize(
    "hero_papel, secondary_papel",
    [
        ("vitima", "investigador"),
        ("investigador", "vitima"),
        ("vitima", "suspeito"),
        ("suspeito", "vitima"),
        ("vitima", "condenado"),
        ("condenado", "vitima"),
        ("suspeito", "investigador"),
        ("investigador", "suspeito"),
        ("testemunha", "outro"),
        ("outro", "testemunha"),
        ("vitima", "vitima"),
    ],
)
def test_templates_elegiveis_independente_da_ordem_dos_slots(hero_papel, secondary_papel):
    """Hipotese investigada no bug report (CORRECAO - seletor de
    template): a elegibilidade usaria a POSICAO hero/secondary em vez da
    COMBINACAO de papeis. Confirmado como REFUTADA por leitura de codigo
    (`templates_elegiveis` monta um `set` dos dois papeis antes de
    decidir) - este teste protege isso de regressao: trocar hero<->secondary
    nunca muda o resultado."""
    assert tbrief.templates_elegiveis(hero_papel, secondary_papel) == tbrief.templates_elegiveis(
        secondary_papel, hero_papel
    )


@pytest.mark.parametrize("hero_papel", tbrief.PAPEIS_VALIDOS)
@pytest.mark.parametrize("secondary_papel", tbrief.PAPEIS_VALIDOS + (None,))
def test_templates_elegiveis_evidence_scene_nunca_elegivel_com_hero_presente(hero_papel, secondary_papel):
    """Regressao ampla (varre TODAS as combinacoes de papel com hero
    presente, nao so' os exemplos pontuais acima) da regra de seguranca
    documentada em CLAUDE.md/HISTORICO_BUGS.md: EVIDENCE_SCENE e' UM
    template de "sem sujeito nenhum" - nunca pode aparecer elegivel (e
    portanto nunca pode ser "sugerido") quando ha' pelo menos uma foto
    enviada."""
    assert "EVIDENCE_SCENE" not in tbrief.templates_elegiveis(hero_papel, secondary_papel)


# ---------------------------------------------------------------------------
# template_preferido - desempate deterministico e explicito (nao pode
# depender da ordem de insercao de um dict nem variar entre chamadas para
# a MESMA combinacao de papeis).
# ---------------------------------------------------------------------------


def test_template_preferido_investigator_update_unico_elegivel():
    assert tbrief.template_preferido(("INVESTIGATOR_UPDATE",)) == "INVESTIGATOR_UPDATE"


def test_template_preferido_empate_arrow_trio_x_duotone_prefere_arrow_trio():
    assert tbrief.template_preferido(("ARROW_TRIO", "DUOTONE_DOSSIER")) == "ARROW_TRIO"
    # ordem de insercao invertida no argumento - resultado tem que ser
    # o MESMO, a regra de desempate e' `ORDEM_PREFERENCIA_TEMPLATE`,
    # nunca a ordem da tupla recebida.
    assert tbrief.template_preferido(("DUOTONE_DOSSIER", "ARROW_TRIO")) == "ARROW_TRIO"


def test_template_preferido_empate_profile_x_duotone_prefere_duotone():
    assert tbrief.template_preferido(("PROFILE_ISOLATION", "DUOTONE_DOSSIER")) == "DUOTONE_DOSSIER"
    assert tbrief.template_preferido(("DUOTONE_DOSSIER", "PROFILE_ISOLATION")) == "DUOTONE_DOSSIER"


def test_template_preferido_evidence_scene_unico():
    assert tbrief.template_preferido(("EVIDENCE_SCENE",)) == "EVIDENCE_SCENE"


def test_template_preferido_lista_vazia_devolve_none():
    assert tbrief.template_preferido(()) is None


def test_template_preferido_e_deterministico_para_a_mesma_combinacao_de_papeis():
    """Mesma combinacao de papeis (em qualquer ordem de slot) -> mesma
    sugestao, sempre. Varre as combinacoes reais que `templates_elegiveis`
    pode empatar."""
    combinacoes = [
        (None, None),
        ("vitima", None),
        ("vitima", "investigador"),
        ("investigador", "vitima"),
        ("vitima", "suspeito"),
        ("suspeito", "vitima"),
        ("vitima", "vitima"),
        ("testemunha", "outro"),
    ]
    for hero_papel, secondary_papel in combinacoes:
        elegiveis_a = tbrief.templates_elegiveis(hero_papel, secondary_papel)
        elegiveis_b = tbrief.templates_elegiveis(hero_papel, secondary_papel)
        assert tbrief.template_preferido(elegiveis_a) == tbrief.template_preferido(elegiveis_b)


# ---------------------------------------------------------------------------
# REQUISITO_TEMPLATE / MOTIVO_CURTO_INDISPONIVEL - o texto exibido pro
# usuario quando um template esta' indisponivel precisa mencionar os
# papeis REAIS usados por `templates_elegiveis` (evita o texto ficar
# hardcoded e divergir silenciosamente da regra de verdade).
# ---------------------------------------------------------------------------


def test_requisito_e_motivo_curto_arrow_trio_mencionam_papeis_reais():
    for papel in tbrief._CATEGORIA_ALVO | tbrief._CATEGORIA_ACUSADO:
        assert papel in tbrief.REQUISITO_TEMPLATE["ARROW_TRIO"]
        assert papel in tbrief.MOTIVO_CURTO_INDISPONIVEL["ARROW_TRIO"]


def test_requisito_e_motivo_curto_investigator_update_mencionam_papeis_reais():
    papeis_esperados = tbrief._CATEGORIA_AUTORIDADE | tbrief._CATEGORIA_ALVO | tbrief._CATEGORIA_ACUSADO
    for papel in papeis_esperados:
        assert papel in tbrief.REQUISITO_TEMPLATE["INVESTIGATOR_UPDATE"]
        assert papel in tbrief.MOTIVO_CURTO_INDISPONIVEL["INVESTIGATOR_UPDATE"]


def test_todos_os_templates_tem_nome_descricao_e_requisito():
    for codigo in tbrief.TEMPLATES_VALIDOS:
        assert tbrief.NOME_EXIBICAO_TEMPLATE[codigo]
        assert tbrief.DESCRICAO_AMIGAVEL_TEMPLATE[codigo]
        assert tbrief.REQUISITO_TEMPLATE[codigo]
        assert tbrief.MOTIVO_CURTO_INDISPONIVEL[codigo]


# ---------------------------------------------------------------------------
# selecionar_template
# ---------------------------------------------------------------------------


def test_selecionar_template_unico_elegivel_nao_chama_api():
    cliente = _ClienteFake([])
    resultado = tbrief.selecionar_template("roteiro", "headline", ("EVIDENCE_SCENE",), "fake-key", cliente=cliente)
    assert resultado["template"] == "EVIDENCE_SCENE"
    assert resultado["fonte"] == "unico_elegivel"
    assert cliente.chamadas == []


def test_selecionar_template_sem_cliente_cai_em_fallback_deterministico():
    resultado = tbrief.selecionar_template(
        "roteiro", "headline", ("ARROW_TRIO", "EVIDENCE_SCENE"), api_key=None, cliente=None
    )
    assert resultado["template"] == "EVIDENCE_SCENE"
    assert resultado["fonte"] == "fallback_deterministico"
    assert resultado["erro"] == "cliente_indisponivel"


def test_selecionar_template_resposta_valida_do_modelo():
    elegiveis = ("ARROW_TRIO", "DUOTONE_DOSSIER", "INVESTIGATOR_UPDATE", "EVIDENCE_SCENE")
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_SELECAO_TEMPLATE, {"template": "ARROW_TRIO", "motivo": "ha' acusacao clara"})]
    )
    resultado = tbrief.selecionar_template("roteiro", "headline", elegiveis, "fake-key", cliente=cliente)
    assert resultado["template"] == "ARROW_TRIO"
    assert resultado["fonte"] == "ia"
    assert resultado["motivo"] == "ha' acusacao clara"


def test_selecionar_template_injeta_conceito_visual_como_contexto_sem_chamada_extra():
    """GRUPO H (sessao "conceito visual", Parte 2) - `conceito_visual`
    entra como contexto ADICIONAL na MESMA chamada de selecao ja existente
    - zero chamadas novas de API (so' 1 resposta enfileirada, mesma
    contagem de sempre)."""
    elegiveis = ("ARROW_TRIO", "DUOTONE_DOSSIER", "INVESTIGATOR_UPDATE", "EVIDENCE_SCENE")
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_SELECAO_TEMPLATE, {"template": "EVIDENCE_SCENE", "motivo": "x"})]
    )
    resultado = tbrief.selecionar_template(
        "roteiro", "headline", elegiveis, "fake-key", cliente=cliente,
        conceito_visual={
            "elemento_principal": "the sealed 1999 DNA lab envelope",
            "tipo_elemento": "documento",
            "acao_ou_momento": None,
        },
    )
    assert resultado["template"] == "EVIDENCE_SCENE"
    assert len(cliente.chamadas) == 1  # zero chamadas novas
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"]
    assert "the sealed 1999 DNA lab envelope" in texto_enviado


def test_selecionar_template_sem_conceito_visual_nao_injeta_bloco_vazio():
    elegiveis = ("ARROW_TRIO", "DUOTONE_DOSSIER", "INVESTIGATOR_UPDATE", "EVIDENCE_SCENE")
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_SELECAO_TEMPLATE, {"template": "EVIDENCE_SCENE", "motivo": "x"})]
    )
    tbrief.selecionar_template("roteiro", "headline", elegiveis, "fake-key", cliente=cliente)
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"]
    assert "Conceito visual" not in texto_enviado


def test_selecionar_template_resposta_fora_do_enum_cai_em_fallback():
    elegiveis = ("PROFILE_ISOLATION", "DUOTONE_DOSSIER", "EVIDENCE_SCENE")
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_SELECAO_TEMPLATE, {"template": "ARROW_TRIO", "motivo": "x"})]
    )
    resultado = tbrief.selecionar_template("roteiro", "headline", elegiveis, "fake-key", cliente=cliente)
    assert resultado["template"] == "EVIDENCE_SCENE"
    assert resultado["fonte"] == "fallback_deterministico"
    assert resultado["erro"] == "resposta_invalida"


def test_selecionar_template_resposta_sem_tool_use_cai_em_fallback():
    elegiveis = ("PROFILE_ISOLATION", "EVIDENCE_SCENE")
    cliente = _ClienteFake([_resposta_sem_tool_use()])
    resultado = tbrief.selecionar_template("roteiro", "headline", elegiveis, "fake-key", cliente=cliente)
    assert resultado["template"] == "EVIDENCE_SCENE"


def test_selecionar_template_excecao_da_api_nunca_propaga():
    elegiveis = ("PROFILE_ISOLATION", "EVIDENCE_SCENE")
    resultado = tbrief.selecionar_template("roteiro", "headline", elegiveis, "fake-key", cliente=_ClienteQuebrado())
    assert resultado["template"] == "EVIDENCE_SCENE"
    assert resultado["erro"] == "chamada_api_falhou"


# ---------------------------------------------------------------------------
# extrair_atributos_foto (Vision LEVE - nunca decide identidade)
# ---------------------------------------------------------------------------


@pytest.fixture
def _foto(tmp_path):
    caminho = tmp_path / "foto.jpg"
    Image.new("RGB", (60, 60), (40, 50, 60)).save(caminho, quality=90)
    return caminho


def test_extrair_atributos_sem_api_key_cai_em_fallback(_foto):
    resultado = tbrief.extrair_atributos_foto(_foto, "vitima", api_key=None, cliente=None)
    assert resultado == {
        "genero": None, "faixa_etaria": None, "expressao": None, "enquadramento": None,
        "fonte": "fallback_sem_vision",
    }


def test_extrair_atributos_arquivo_ausente_cai_em_fallback(tmp_path):
    resultado = tbrief.extrair_atributos_foto(
        tmp_path / "nao_existe.jpg", "vitima", "fake-key", cliente=_ClienteFake([])
    )
    assert resultado["fonte"] == "fallback_sem_vision"


def test_extrair_atributos_extensao_nao_suportada_cai_em_fallback(tmp_path):
    caminho = tmp_path / "foto.bmp"
    caminho.write_bytes(b"fake")
    resultado = tbrief.extrair_atributos_foto(caminho, "vitima", "fake-key", cliente=_ClienteFake([]))
    assert resultado["fonte"] == "fallback_sem_vision"


def test_extrair_atributos_sucesso_normaliza_campos(_foto):
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "woman", "faixa_etaria": "middle-aged", "expressao": "a warm smile", "enquadramento": "close_up"},
            )
        ]
    )
    custos = []
    resultado = tbrief.extrair_atributos_foto(_foto, "vitima", "fake-key", cliente=cliente, _custos=custos)
    assert resultado == {
        "genero": "woman", "faixa_etaria": "middle-aged", "expressao": "a warm smile",
        "enquadramento": "close_up", "fonte": "vision",
    }
    assert len(custos) == 1 and custos[0] > 0


def test_extrair_atributos_valores_fora_do_enum_viram_none(_foto):
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "alien", "faixa_etaria": "", "expressao": "", "enquadramento": "wide"},
            )
        ]
    )
    resultado = tbrief.extrair_atributos_foto(_foto, "vitima", "fake-key", cliente=cliente)
    assert resultado["genero"] is None
    assert resultado["faixa_etaria"] is None
    assert resultado["expressao"] is None
    assert resultado["enquadramento"] is None
    assert resultado["fonte"] == "vision"


def test_extrair_atributos_excecao_da_api_nunca_propaga(_foto):
    resultado = tbrief.extrair_atributos_foto(_foto, "vitima", "fake-key", cliente=_ClienteQuebrado())
    assert resultado["fonte"] == "fallback_sem_vision"


def test_extrair_atributos_nunca_pede_identificacao_no_prompt(_foto):
    """O texto enviado ao modelo nunca menciona o papel como se fosse pra'
    IDENTIFICAR a pessoa - so' descrever atributos visuais."""
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_ATRIBUTOS, {"genero": "man", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"})]
    )
    tbrief.extrair_atributos_foto(_foto, "suspeito", "fake-key", cliente=cliente)
    texto_pedido = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert "NAO tente identificar" in texto_pedido


# ---------------------------------------------------------------------------
# montar_prompt_arrow_trio (Correcao 2 - guarda de censura)
# ---------------------------------------------------------------------------


def _caso_base(**overrides):
    caso = {
        "hero_papel": "vitima",
        "hero_atributos": None,
        "secondary_papel": "suspeito",
        "secondary_atributos": None,
        "headline": "THE MARK ON HIS WRIST",
        "emphasis_word": "MARK",
        "secondary_texto": "",
        "accent": "red",
        "censor": False,
        "subject_name": "Jane Doe",
        "background_prompt": "a dark suburban street",
    }
    caso.update(overrides)
    return caso


def test_arrow_trio_censura_aplicada_quando_secondary_e_suspeito_e_censor_true():
    prompt, meta = tbrief.montar_prompt_arrow_trio(_caso_base(censor=True, secondary_papel="suspeito"))
    assert meta["censura_aplicada"] is True
    assert "censorship bar" in prompt


def test_arrow_trio_censura_aplicada_quando_secondary_e_condenado_e_censor_true():
    prompt, meta = tbrief.montar_prompt_arrow_trio(_caso_base(censor=True, secondary_papel="condenado"))
    assert meta["censura_aplicada"] is True


@pytest.mark.parametrize("papel_nao_censuravel", ["vitima", "investigador", "testemunha", "outro"])
def test_arrow_trio_censura_nunca_aplicada_para_papel_nao_suspeito(papel_nao_censuravel):
    """CORRECAO 2 (regra de seguranca): censor=True nunca cobre os olhos de
    vitima/investigador/testemunha/outro, mesmo pedido explicitamente."""
    prompt, meta = tbrief.montar_prompt_arrow_trio(_caso_base(censor=True, secondary_papel=papel_nao_censuravel))
    assert meta["censura_aplicada"] is False
    assert "censorship bar" not in prompt


def test_arrow_trio_censor_false_nunca_aplica_mesmo_com_suspeito():
    prompt, meta = tbrief.montar_prompt_arrow_trio(_caso_base(censor=False, secondary_papel="suspeito"))
    assert meta["censura_aplicada"] is False
    assert "censorship bar" not in prompt


def test_arrow_trio_prompt_nao_contem_nome_da_pessoa_na_descricao():
    prompt, _ = tbrief.montar_prompt_arrow_trio(_caso_base(subject_name="Jane Doe"))
    # "Jane Doe" so' pode aparecer se entrar via censura textual (que usa
    # subject_name como TEXTO tipografico, nunca como instrucao de rosto) -
    # sem censura, o nome nao aparece em lugar nenhum do prompt.
    assert "Jane Doe" not in prompt


def test_arrow_trio_tertiary_omitido_por_padrao():
    prompt, _ = tbrief.montar_prompt_arrow_trio(_caso_base())
    assert "far right" not in prompt


# ---------------------------------------------------------------------------
# montar_prompt_investigator_update (Correcao 1 - bug do headline duplicado)
# ---------------------------------------------------------------------------


def test_investigator_update_usa_headline_e_emphasis_word_uma_linha_so():
    prompt, _ = tbrief.montar_prompt_investigator_update(
        _caso_base(headline="WHAT ABDUCTOR WANTED", emphasis_word="ABDUCTOR WANTED")
    )
    assert 'huge headline "WHAT ABDUCTOR WANTED"' in prompt
    assert '"ABDUCTOR WANTED" in red uppercase' in prompt
    # headline nao pode aparecer DUAS vezes como campos separados (bug
    # original: `"{HEADLINE_SMALL}", with "{HEADLINE_SMALL}" in white...`).
    assert prompt.count("WHAT ABDUCTOR WANTED") == 1


def test_investigator_update_emphasis_word_vazio_nao_quebra():
    prompt, _ = tbrief.montar_prompt_investigator_update(_caso_base(headline="A CASE UPDATE", emphasis_word=""))
    assert 'huge headline "A CASE UPDATE" in white uppercase.' in prompt


def test_investigator_update_emphasis_word_que_nao_e_substring_e_ignorada():
    prompt, _ = tbrief.montar_prompt_investigator_update(
        _caso_base(headline="A CASE UPDATE", emphasis_word="NAO ESTA NO HEADLINE")
    )
    assert 'huge headline "A CASE UPDATE" in white uppercase.' in prompt


def test_investigator_update_sem_secondary_usa_silhueta_generica():
    caso = _caso_base(secondary_papel=None, secondary_atributos=None)
    prompt, _ = tbrief.montar_prompt_investigator_update(caso)
    assert "blurred, out-of-focus silhouette" in prompt


def test_investigator_update_headline_titlecase_vira_uppercase_no_prompt():
    """GRUPO G (achado da validacao empirica, nancyGuthrieProject03): o
    headline persistido vem em Title Case ("The Mark On His Wrist"), nao
    uppercase - o prompt tem que exibir maiusculo (a propria instrucao diz
    "in white uppercase" logo ao lado), mas a checagem de substring de
    emphasis_word usa o case original."""
    prompt, _ = tbrief.montar_prompt_investigator_update(
        _caso_base(headline="The Mark On His Wrist", emphasis_word="Wrist")
    )
    assert 'huge headline "THE MARK ON HIS WRIST"' in prompt
    assert '"WRIST" in red uppercase' in prompt
    assert "The Mark On His Wrist" not in prompt


def test_investigator_update_case_name_vem_de_subject_name():
    prompt, _ = tbrief.montar_prompt_investigator_update(_caso_base(subject_name="Nancy Guthrie"))
    assert '"NANCY GUTHRIE UPDATE"' in prompt


# ---------------------------------------------------------------------------
# montar_prompt_evidence_scene (Correcao 3)
# ---------------------------------------------------------------------------


def test_evidence_scene_funciona_sem_nenhum_sujeito():
    prompt, meta = tbrief.montar_prompt_evidence_scene(_caso_base(hero_papel=None, secondary_papel=None))
    assert "victim photograph" not in prompt
    assert meta["censura_aplicada"] is False


def test_evidence_scene_inclui_foto_de_evidencia_so_quando_ha_vitima():
    prompt, _ = tbrief.montar_prompt_evidence_scene(_caso_base(hero_papel="vitima", secondary_papel="suspeito"))
    assert "a small victim photograph," in prompt


def test_evidence_scene_sem_vitima_nao_inclui_foto_de_evidencia():
    prompt, _ = tbrief.montar_prompt_evidence_scene(_caso_base(hero_papel="investigador", secondary_papel="suspeito"))
    assert "victim photograph" not in prompt


# ---------------------------------------------------------------------------
# montar_prompt_duotone_dossier / montar_prompt_profile_isolation
#
# GRUPO A (correcao desta sessao): o grid de "12-15 fotos" so' e' acionado
# quando hero e secondary tem o MESMO papel (multiplos sujeitos do mesmo
# tipo, ex: varias vitimas do mesmo autor) - nunca so' porque secondary
# esta presente. Papeis diferentes com relacao de acusacao (vitima <->
# suspeito/condenado) usam seta com UMA foto, sem grid. Qualquer outra
# combinacao nao tem clausula nenhuma.
# ---------------------------------------------------------------------------


def test_duotone_dossier_sem_secondary_nao_tem_seta_nem_grid():
    prompt, _ = tbrief.montar_prompt_duotone_dossier(_caso_base(secondary_papel=None))
    assert "evidence-board panel" not in prompt


def test_duotone_dossier_mesmo_papel_do_hero_tem_grid_e_seta():
    prompt, _ = tbrief.montar_prompt_duotone_dossier(_caso_base(hero_papel="vitima", secondary_papel="vitima"))
    assert "evidence-board panel" in prompt
    assert "arrow pointing from the photographs" in prompt


def test_duotone_dossier_papel_diferente_do_hero_mas_investigador_nao_tem_grid():
    """GRUPO F: reproducao direta do achado real (par vitima+investigador
    nunca deve gerar um grid de "12-15 fotos" repetindo o UNICO
    investigador enviado)."""
    prompt, _ = tbrief.montar_prompt_duotone_dossier(_caso_base(hero_papel="vitima", secondary_papel="investigador"))
    assert "evidence-board panel" not in prompt
    assert "12" not in prompt


def test_duotone_dossier_relacao_acusatoria_tem_seta_sem_grid():
    prompt, _ = tbrief.montar_prompt_duotone_dossier(_caso_base(hero_papel="vitima", secondary_papel="suspeito"))
    assert "evidence-board panel" not in prompt
    assert "12" not in prompt
    assert "arrow" in prompt
    assert "smaller portrait" in prompt


def test_duotone_dossier_papeis_traduzidos_para_ingles_no_texto():
    """GRUPO C: papel cru (PT-BR) nunca entra direto em texto de prompt em
    ingles - so' via `_papel_em_ingles`/`descrever_pessoa_para_prompt`."""
    prompt, _ = tbrief.montar_prompt_duotone_dossier(_caso_base(hero_papel="vitima", secondary_papel="vitima"))
    assert "vitima" not in prompt
    assert "victim" in prompt


def test_profile_isolation_usa_hero_e_nao_menciona_secondary():
    prompt, _ = tbrief.montar_prompt_profile_isolation(_caso_base())
    assert "side-profile close-up" in prompt


def test_profile_isolation_label_usa_subject_name_nao_repete_headline():
    """GRUPO B (bug corrigido nesta sessao): antes, o label pequeno abaixo
    do headline repetia o proprio `headline` (ja' e' a linha grande) -
    texto duplicado na imagem. Agora usa `subject_name`, unico uso
    legitimo que sobra pra' esse label."""
    prompt, _ = tbrief.montar_prompt_profile_isolation(
        _caso_base(headline="THE MARK ON HIS WRIST", subject_name="Jane Doe")
    )
    assert prompt.count("THE MARK ON HIS WRIST") == 1
    assert "JANE DOE" in prompt


def test_profile_isolation_sem_subject_name_omite_label():
    prompt, _ = tbrief.montar_prompt_profile_isolation(_caso_base(subject_name=""))
    assert "off-white label" not in prompt


# ---------------------------------------------------------------------------
# GRUPO B: HEADLINE_LARGE e' sempre o headline (Headline Engine), nunca
# subject_name - correcao do achado real ("NANCY GUTHRIE" virando a linha
# grande no lugar do headline com lacuna de curiosidade).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "montador",
    [
        tbrief.montar_prompt_arrow_trio,
        tbrief.montar_prompt_evidence_scene,
        tbrief.montar_prompt_duotone_dossier,
        tbrief.montar_prompt_dual_portrait,
    ],
)
def test_headline_grande_e_sempre_o_headline_nunca_subject_name(montador):
    caso = _caso_base(
        headline="THE MARK ON HIS WRIST", subject_name="Jane Doe", secondary_papel="suspeito", hero_papel="vitima"
    )
    prompt, _ = montador(caso)
    assert "THE MARK ON HIS WRIST" in prompt
    assert "JANE DOE" not in prompt


# ---------------------------------------------------------------------------
# gerar_briefing_completo (orquestracao)
# ---------------------------------------------------------------------------


def _escrever_metadados(pasta_projeto: Path, thumbnail: dict):
    pasta_thumbnail = pasta_projeto / "thumbnail"
    pasta_thumbnail.mkdir(parents=True, exist_ok=True)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps({"title": [], "description": "", "tags": [], "thumbnail": thumbnail}), encoding="utf-8"
    )


def test_gerar_briefing_completo_sem_sujeitos_usa_evidence_scene(tmp_path):
    _escrever_metadados(tmp_path, {"headline": "COLD CASE REOPENED", "emphasis_word": "REOPENED", "accent": "amber"})

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    assert resultado["template_escolhido"] == "EVIDENCE_SCENE"
    assert "COLD CASE REOPENED" in resultado["briefing_completo"] or "REOPENED" in resultado["briefing_completo"]
    auditoria = json.loads((tmp_path / "thumbnail" / "briefing.json").read_text(encoding="utf-8"))
    assert auditoria["template_escolhido"] == "EVIDENCE_SCENE"
    assert auditoria["hero"] is None
    assert auditoria["secondary"] is None


def test_gerar_briefing_completo_com_hero_e_secondary_le_papeis_do_disco(tmp_path):
    _escrever_metadados(tmp_path, {"headline": "H", "emphasis_word": "", "accent": "red"})
    pasta_sujeitos = tmp_path / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True)
    Image.new("RGB", (40, 40), (1, 2, 3)).save(pasta_sujeitos / "hero.jpg")
    Image.new("RGB", (40, 40), (4, 5, 6)).save(pasta_sujeitos / "secondary.jpg")
    (pasta_sujeitos / "sujeitos.json").write_text(
        json.dumps(
            {"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": {"arquivo": "secondary.jpg", "papel": "suspeito"}}
        ),
        encoding="utf-8",
    )
    # 3 chamadas na ordem: atributos do hero, atributos do secondary,
    # selecao de template (gerar_briefing_completo chama nessa ordem).
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "woman", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"},
            ),
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "man", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"},
            ),
            _resposta_tool_use(tbrief.NOME_TOOL_SELECAO_TEMPLATE, {"template": "ARROW_TRIO", "motivo": "acusacao clara"}),
        ]
    )

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key="fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["template_escolhido"] == "ARROW_TRIO"
    auditoria = json.loads((tmp_path / "thumbnail" / "briefing.json").read_text(encoding="utf-8"))
    assert auditoria["hero"]["papel"] == "vitima"
    assert auditoria["secondary"]["papel"] == "suspeito"


def test_gerar_briefing_completo_sem_headline_falha_sem_levantar_excecao(tmp_path):
    """GRUPO B (correcao desta sessao): headline ausente/vazio nao cai mais
    num fallback silencioso (subject_name/emphasis_word como linha grande)
    - a funcao falha de forma controlada, sem escrever briefing.json, e
    nunca levanta excecao. Cobre tanto "sem metadados.json nenhum" quanto
    "metadados.json existe mas thumbnail.headline esta vazio"."""
    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)
    assert resultado == {"sucesso": False, "erro": "headline_ausente"}
    assert not (tmp_path / "thumbnail" / "briefing.json").exists()

    _escrever_metadados(tmp_path, {"headline": "", "emphasis_word": "", "subject_name": "Jane Doe"})
    resultado_headline_vazio = tbrief.gerar_briefing_completo(tmp_path, api_key=None)
    assert resultado_headline_vazio == {"sucesso": False, "erro": "headline_ausente"}


def test_gerar_briefing_completo_sujeito_apontado_mas_arquivo_ausente_e_tratado_como_ausente(tmp_path):
    _escrever_metadados(tmp_path, {"headline": "H", "emphasis_word": "", "accent": "red"})
    pasta_sujeitos = tmp_path / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True)
    (pasta_sujeitos / "sujeitos.json").write_text(
        json.dumps({"hero": {"arquivo": "nao_existe.jpg", "papel": "vitima"}, "secondary": None}), encoding="utf-8"
    )

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    auditoria = json.loads((tmp_path / "thumbnail" / "briefing.json").read_text(encoding="utf-8"))
    # hero_info existe (sujeitos.json tem a entrada), mas o arquivo de foto
    # nao existe em disco - extrair_atributos_foto cai no fallback (nunca
    # levanta excecao por causa de um arquivo ausente).
    assert auditoria["hero"]["atributos"]["fonte"] == "fallback_sem_vision"


# ---------------------------------------------------------------------------
# GRUPO F (testes ponta a ponta pedidos nesta sessao)
# ---------------------------------------------------------------------------


def _escrever_sujeitos(pasta_projeto: Path, hero_papel=None, secondary_papel=None):
    pasta_sujeitos = pasta_projeto / "thumbnail" / "sujeitos"
    pasta_sujeitos.mkdir(parents=True, exist_ok=True)
    dados = {"hero": None, "secondary": None}
    if hero_papel:
        Image.new("RGB", (40, 40), (1, 2, 3)).save(pasta_sujeitos / "hero.jpg")
        dados["hero"] = {"arquivo": "hero.jpg", "papel": hero_papel}
    if secondary_papel:
        Image.new("RGB", (40, 40), (4, 5, 6)).save(pasta_sujeitos / "secondary.jpg")
        dados["secondary"] = {"arquivo": "secondary.jpg", "papel": secondary_papel}
    (pasta_sujeitos / "sujeitos.json").write_text(json.dumps(dados), encoding="utf-8")


def test_gerar_briefing_completo_vitima_investigador_seleciona_investigator_update_sem_chamar_api(tmp_path):
    """GRUPO F: reproducao do caso real do pedido desta sessao (vitima +
    investigador) - o template e' INVESTIGATOR_UPDATE e a selecao nem
    precisa de API (unico elegivel), entao funciona mesmo sem
    ANTHROPIC_API_KEY."""
    _escrever_metadados(tmp_path, {"headline": "THE MARK ON HIS WRIST", "emphasis_word": "MARK"})
    _escrever_sujeitos(tmp_path, hero_papel="vitima", secondary_papel="investigador")

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    assert resultado["template_escolhido"] == "INVESTIGATOR_UPDATE"
    assert "THE MARK ON HIS WRIST" in resultado["briefing_completo"]


@pytest.mark.parametrize(
    "hero_papel,secondary_papel",
    [
        ("vitima", "investigador"),
        ("vitima", "suspeito"),
        ("vitima", "vitima"),
        ("testemunha", "outro"),
        ("condenado", None),
    ],
)
def test_gerar_briefing_completo_nunca_contem_acento_ou_termo_em_portugues(tmp_path, hero_papel, secondary_papel):
    """GRUPO C: o briefing e' um prompt em INGLES - nenhum caractere
    acentuado (regex fora do ASCII basico) nem palavra crua em portugues
    dos papeis pode vazar pro texto final, seja qual for a combinacao de
    papeis enviada."""
    _escrever_metadados(tmp_path, {"headline": "THE MARK ON HIS WRIST", "emphasis_word": "MARK", "subject_name": "Jane Doe"})
    _escrever_sujeitos(tmp_path, hero_papel=hero_papel, secondary_papel=secondary_papel)

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    briefing = resultado["briefing_completo"]
    assert re.search(r"[^\x00-\x7f]", briefing) is None, briefing
    for termo_pt in ("vitima", "suspeito", "investigador", "testemunha", "condenado"):
        assert termo_pt not in briefing.lower(), f"'{termo_pt}' vazou pro briefing: {briefing}"


# ---------------------------------------------------------------------------
# GRUPO G (correcao de bugs - teste real video_teste_01): o papel declarado
# de CADA sujeito e' a fonte de verdade do briefing - nunca um papel fixo
# hardcoded, nunca inferido so' pela posicao (hero) do sujeito. Achado real
# reportado: sujeito principal declarado como "suspeito" saiu descrito como
# "established as the case's VICTIM" no briefing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "papel,substantivo_esperado",
    [
        ("vitima", "the case's victim"),
        ("suspeito", "the case's suspect"),
        ("investigador", "the case's investigator"),
        ("condenado", "a convicted individual in the case"),
        ("testemunha", "a witness in the case"),
    ],
)
def test_gerar_briefing_completo_um_sujeito_usa_o_papel_declarado_nunca_fixo(tmp_path, papel, substantivo_esperado):
    """Teste critico do bug 3: com 1 sujeito so' (hero), o briefing tem que
    descrever a pessoa com o SUBSTANTIVO do papel realmente declarado -
    nunca "victim" hardcoded independente do que o usuario escolheu.

    `template_forcado="PROFILE_ISOLATION"` (Grupo F, escolha manual - o
    mesmo caminho que a tela usa) elimina a ambiguidade entre os 2
    elegiveis (PROFILE_ISOLATION/DUOTONE_DOSSIER) sem precisar de API real
    - sem isso, sem cliente disponivel, `selecionar_template` cairia no
    fallback deterministico EVIDENCE_SCENE, que nao descreve pessoa
    nenhuma e mascararia o proprio bug que este teste existe pra' pegar."""
    _escrever_metadados(tmp_path, {"headline": "WHAT HE LEFT BEHIND", "emphasis_word": "LEFT"})
    _escrever_sujeitos(tmp_path, hero_papel=papel, secondary_papel=None)

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None, template_forcado="PROFILE_ISOLATION")

    assert resultado["sucesso"] is True
    briefing = resultado["briefing_completo"].lower()
    assert substantivo_esperado in briefing
    # Nunca "victim" quando o papel declarado NAO e' vitima - e' o sintoma
    # exato do bug real (suspeito descrito como victim).
    if papel != "vitima":
        assert "victim" not in briefing, f"papel={papel!r} mas 'victim' apareceu no briefing: {briefing}"


def test_gerar_briefing_completo_trocar_papel_do_hero_muda_o_briefing(tmp_path):
    """Trocar o papel no seletor tem que alterar o briefing gerado (regra
    explicita do pedido) - gera dois briefings pro MESMO hero.jpg, so'
    variando o papel declarado, e confere que o texto realmente muda."""
    _escrever_metadados(tmp_path, {"headline": "WHAT HE LEFT BEHIND", "emphasis_word": "LEFT"})

    _escrever_sujeitos(tmp_path, hero_papel="vitima", secondary_papel=None)
    briefing_vitima = tbrief.gerar_briefing_completo(
        tmp_path, api_key=None, template_forcado="PROFILE_ISOLATION"
    )["briefing_completo"]

    _escrever_sujeitos(tmp_path, hero_papel="suspeito", secondary_papel=None)
    briefing_suspeito = tbrief.gerar_briefing_completo(
        tmp_path, api_key=None, template_forcado="PROFILE_ISOLATION"
    )["briefing_completo"]

    assert briefing_vitima != briefing_suspeito
    assert "the case's victim" in briefing_vitima.lower()
    assert "the case's suspect" in briefing_suspeito.lower()


def test_gerar_briefing_completo_vitima_suspeito_arrow_trio_eh_o_preferido(tmp_path):
    """Teste critico do bug 2 (reproducao literal do cenario do pedido):
    hero=vitima + secondary=suspeito. ARROW_TRIO tem que estar entre os
    elegiveis (e ser a PRIMEIRA opcao, ou seja a preferida/sugerida) -
    DUOTONE_DOSSIER tambem elegivel, mas nunca o UNICO."""
    hero_papel, secondary_papel = "vitima", "suspeito"
    elegiveis = tbrief.templates_elegiveis(hero_papel, secondary_papel)

    assert "ARROW_TRIO" in elegiveis
    assert elegiveis[0] == "ARROW_TRIO"
    assert set(elegiveis) == {"ARROW_TRIO", "DUOTONE_DOSSIER"}

    _escrever_metadados(tmp_path, {"headline": "WHAT HE LEFT BEHIND", "emphasis_word": "LEFT"})
    _escrever_sujeitos(tmp_path, hero_papel=hero_papel, secondary_papel=secondary_papel)
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "woman", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"},
            ),
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "man", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"},
            ),
            _resposta_tool_use(tbrief.NOME_TOOL_SELECAO_TEMPLATE, {"template": "ARROW_TRIO", "motivo": "acusacao clara"}),
        ]
    )
    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key="fake-key", cliente=cliente)
    assert resultado["template_escolhido"] == "ARROW_TRIO"
    briefing = resultado["briefing_completo"].lower()
    assert "the case's victim" in briefing
    assert "the case's suspect" in briefing


def test_duotone_dossier_grid_nunca_dispara_com_secondary_unico_de_papel_diferente():
    """Acrescimo ao bug 3 (pedido explicito): a clausula de grid do
    DUOTONE_DOSSIER ("12-15 photographs arranged in a grid") so' faz
    sentido com MULTIPLOS sujeitos do MESMO papel - nunca pode disparar
    com um unico secondary de papel diferente do hero (achado real
    anterior: gerou "quinze copias do mesmo investigador"). Cobre as
    combinacoes que efetivamente chegam a montar_prompt_duotone_dossier
    (as demais combinacoes de papeis diferentes vao pra' ARROW_TRIO ou
    INVESTIGATOR_UPDATE antes disso, via templates_elegiveis)."""
    for secondary_papel in ("investigador", "testemunha", "outro", "suspeito", "condenado"):
        prompt, _ = tbrief.montar_prompt_duotone_dossier(
            _caso_base(hero_papel="vitima", secondary_papel=secondary_papel)
        )
        assert "12-15" not in prompt, f"secondary_papel={secondary_papel!r} disparou o grid indevidamente: {prompt}"


# ---------------------------------------------------------------------------
# DUAL_PORTRAIT (Problema 1 do pedido - caso real Burke Ramsey/JonBenét):
# fallback pra' dois sujeitos sem relacao de acusacao, autoridade ou mesmo
# papel entre eles. Sem seta, sem culpa presumida.
# ---------------------------------------------------------------------------


def test_dual_portrait_elegivel_para_vitima_e_outro():
    """Validacao 1 do pedido: vitima + outro habilita DUAL_PORTRAIT."""
    assert tbrief.templates_elegiveis("vitima", "outro") == ("DUAL_PORTRAIT",)
    assert tbrief.templates_elegiveis("outro", "vitima") == ("DUAL_PORTRAIT",)


def test_dual_portrait_nunca_substitui_arrow_trio():
    """Validacao 2 do pedido: vitima + suspeito continua priorizando
    ARROW_TRIO - a regra do ARROW_TRIO nao foi enfraquecida por
    DUAL_PORTRAIT existir."""
    elegiveis = tbrief.templates_elegiveis("vitima", "suspeito")
    assert elegiveis[0] == "ARROW_TRIO"
    assert "DUAL_PORTRAIT" not in elegiveis


def test_dual_portrait_nunca_substitui_investigator_update():
    """Validacao 3 do pedido: investigador + qualquer sujeito continua
    podendo usar INVESTIGATOR_UPDATE."""
    for papel in ("vitima", "suspeito", "condenado"):
        elegiveis = tbrief.templates_elegiveis("investigador", papel)
        assert elegiveis == ("INVESTIGATOR_UPDATE",)
        assert "DUAL_PORTRAIT" not in elegiveis


@pytest.mark.parametrize(
    "hero_papel,secondary_papel",
    [("testemunha", "outro"), ("vitima", "outro"), ("condenado", "testemunha")],
)
def test_dual_portrait_fallback_universal_para_dois_sujeitos_sem_template_especifico(hero_papel, secondary_papel):
    """Validacao 4 do pedido: qualquer combinacao de dois sujeitos sem
    relacao de acusacao/autoridade/mesmo papel cai em DUAL_PORTRAIT."""
    assert tbrief.templates_elegiveis(hero_papel, secondary_papel) == ("DUAL_PORTRAIT",)


def test_todos_os_templates_tem_montador_registrado():
    for codigo in tbrief.TEMPLATES_VALIDOS:
        assert codigo in tbrief._MONTADORES


def test_dual_portrait_nunca_tem_seta_nem_pressupoe_culpa():
    prompt, meta = tbrief.montar_prompt_dual_portrait(_caso_base(hero_papel="vitima", secondary_papel="outro"))
    assert "arrow pointing" not in prompt
    assert "no arrow" in prompt
    assert "no visual implication of guilt or accusation" in prompt
    assert meta["censura_aplicada"] is False


def test_dual_portrait_nao_suprime_tensao_como_efeito_colateral_da_restricao_etica():
    """Achado real (caso Burke Ramsey, ver HISTORICO_BUGS.md): a versao
    anterior traduzia "nao implicar culpa" em estetica neutra - o
    briefing real continha "neutral"/"balanced"/"dignified"/"equal
    visual importance", numa composicao parecida com retrospectiva
    memorial. Nao implicar culpa e' correto; suprimir toda tensao e' um
    efeito colateral que nao deveria existir - a restricao e' sobre o
    ALVO da tensao (nunca uma pessoa), nunca sobre a existencia dela."""
    prompt, _ = tbrief.montar_prompt_dual_portrait(_caso_base(hero_papel="vitima", secondary_papel="outro"))
    # Frases EXATAS do briefing real que motivou a correcao (nao palavras
    # soltas - "neutral" continua aparecendo legitimamente como NEGACAO,
    # "never a neutral or calm half-smile", que e' o oposto do bug).
    proibidos = (
        "neutral, balanced lighting", "composed and dignified", "equal visual importance",
        "calm, contemplative half-smile",
    )
    prompt_lower = prompt.lower()
    for termo in proibidos:
        assert termo not in prompt_lower, f"frase suprime tensao indevidamente: {termo!r}"
    # Tensao/drama continuam presentes - a composicao nao virou neutra.
    assert "high-contrast" in prompt_lower
    assert "deep shadows" in prompt_lower
    assert "genuine, weighted emotional expression" in prompt


def test_dual_portrait_tensao_de_conceito_aponta_pro_objeto_nunca_pra_pessoa():
    """A tensao visual (quando ha' conceito_visual) tem que mirar o
    ELEMENTO do caso, nunca uma das duas pessoas - texto explicito
    reforça isso no proprio prompt (GRUPO E/G, sessao "conceito visual",
    Parte 2 - substitui o antigo `evidencia_central`)."""
    prompt, _ = tbrief.montar_prompt_dual_portrait(
        _caso_base(
            hero_papel="vitima", secondary_papel="outro",
            conceito_visual={
                "elemento_principal": "a sealed 1999 DNA lab envelope",
                "tipo_elemento": "documento",
                "acao_ou_momento": None,
                "revelacao": None,
                "papel_na_composicao": "apoio",
            },
        )
    )
    assert "a sealed 1999 DNA lab envelope" in prompt
    assert "never at either person" in prompt


def test_dual_portrait_censor_true_nunca_aplica_censura():
    """DUAL_PORTRAIT e' deliberadamente uma composicao SEM acusacao - censor
    nunca se aplica aqui, mesmo pedido explicitamente (nao ha' 'acusado'
    nesta composicao pra' justificar cobrir o rosto de ninguem)."""
    prompt, meta = tbrief.montar_prompt_dual_portrait(
        _caso_base(hero_papel="vitima", secondary_papel="outro", censor=True)
    )
    assert meta["censura_aplicada"] is False
    assert "censorship bar" not in prompt


def test_dual_portrait_protagonista_padrao_e_hero():
    prompt, meta = tbrief.montar_prompt_dual_portrait(
        _caso_base(hero_papel="vitima", secondary_papel="outro")
    )
    assert meta["protagonista"] == "hero"
    # o papel do hero (vitima) aparece na clausula "dominant position"
    pos_dominante = prompt.index("dominant position")
    pos_vitima = prompt.index("the case's victim")
    pos_outro = prompt.index("person connected to the case")
    assert pos_vitima < pos_dominante < pos_outro


def test_dual_portrait_protagonista_secondary_inverte_posicao_dominante():
    """Validacao 11 do pedido (caso real Burke Ramsey): quando o eixo
    editorial aponta o SECONDARY como protagonista (ex: Burke, papel
    'outro'), ele ocupa a posicao dominante mesmo tendo sido enviado no
    slot secundario - JonBenét (hero, vitima) fica na posicao
    complementar. Papel declarado de cada um nunca muda."""
    prompt, meta = tbrief.montar_prompt_dual_portrait(
        _caso_base(hero_papel="vitima", secondary_papel="outro", protagonista="secondary")
    )
    assert meta["protagonista"] == "secondary"
    pos_outro = prompt.index("person connected to the case")
    pos_vitima = prompt.index("the case's victim")
    assert pos_outro < pos_vitima
    # papel continua o mesmo - nunca "outro" descrito como vitima nem
    # vice-versa, so' a POSICAO no prompt mudou.
    assert "the case's victim" in prompt
    assert "person connected to the case" in prompt


def test_dual_portrait_inclui_conceito_visual_quando_presente():
    prompt, _ = tbrief.montar_prompt_dual_portrait(
        _caso_base(
            hero_papel="vitima",
            secondary_papel="outro",
            conceito_visual={
                "elemento_principal": "a DNA test swab and lab report",
                "tipo_elemento": "objeto",
                "acao_ou_momento": None,
                "revelacao": None,
                "papel_na_composicao": "apoio",
            },
        )
    )
    assert "a DNA test swab and lab report" in prompt


def test_dual_portrait_sem_conceito_visual_nao_inventa_nada():
    prompt, _ = tbrief.montar_prompt_dual_portrait(_caso_base(hero_papel="vitima", secondary_papel="outro"))
    assert "prominently feature" not in prompt
    assert "concrete detail from the case" not in prompt


def test_evidence_scene_inclui_conceito_visual_quando_presente():
    prompt, _ = tbrief.montar_prompt_evidence_scene(
        _caso_base(
            hero_papel=None,
            secondary_papel=None,
            conceito_visual={
                "elemento_principal": "a sealed 1999 lab report envelope",
                "tipo_elemento": "documento",
                "acao_ou_momento": None,
                "revelacao": None,
                "papel_na_composicao": "apoio",
            },
        )
    )
    assert "a sealed 1999 lab report envelope" in prompt


def test_evidence_scene_conceito_visual_ausente_nao_quebra():
    prompt, _ = tbrief.montar_prompt_evidence_scene(_caso_base(hero_papel=None, secondary_papel=None))
    assert "prominently feature" not in prompt
    assert "concrete detail from the case" not in prompt


# ---------------------------------------------------------------------------
# selecionar_protagonista_dual_portrait (validacao 11 do pedido)
# ---------------------------------------------------------------------------


def test_selecionar_protagonista_sem_cliente_cai_em_fallback_hero():
    resultado = tbrief.selecionar_protagonista_dual_portrait(
        "Titulo qualquer", "HEADLINE", "vitima", "outro", api_key=None, cliente=None
    )
    assert resultado["protagonista"] == "hero"
    assert resultado["fonte"] == "fallback_deterministico"
    assert resultado["erro"] == "cliente_indisponivel"


def test_selecionar_protagonista_sem_titulo_nem_headline_cai_em_fallback():
    cliente = _ClienteFake([])
    resultado = tbrief.selecionar_protagonista_dual_portrait(
        "", "", "vitima", "outro", api_key="fake-key", cliente=cliente
    )
    assert resultado["protagonista"] == "hero"
    assert resultado["erro"] == "contexto_insuficiente"
    assert cliente.chamadas == []


def test_selecionar_protagonista_resposta_valida_secondary():
    """CORRECAO (achado real na validacao contra a API real): o modelo
    responde com o PROPRIO PAPEL ("outro", o papel do secondary neste
    caso), nunca com o rotulo abstrato "secondary" - `selecionar_
    protagonista_dual_portrait` e' quem traduz papel -> slot."""
    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                tbrief.NOME_TOOL_PROTAGONISTA_DUAL,
                {"protagonista_papel": "outro", "motivo": "o titulo e' sobre o Burke, papel outro"},
            )
        ]
    )
    resultado = tbrief.selecionar_protagonista_dual_portrait(
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother",
        "CLEARED BY DNA, THEN ACCUSED",
        "vitima",
        "outro",
        api_key="fake-key",
        cliente=cliente,
    )
    assert resultado["protagonista"] == "secondary"
    assert resultado["fonte"] == "ia"

    # Enum do schema enviado a' API e' fechado aos DOIS papeis reais do par
    # (nunca "hero"/"secondary") - garante que o modelo so' pode responder
    # com algo mapeavel de volta sem ambiguidade.
    schema_enviado = cliente.chamadas[0]["tools"][0]
    assert schema_enviado["input_schema"]["properties"]["protagonista_papel"]["enum"] == ["vitima", "outro"]


def test_selecionar_protagonista_injeta_subject_name_quando_disponivel():
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_PROTAGONISTA_DUAL, {"protagonista_papel": "outro", "motivo": "x"})]
    )
    tbrief.selecionar_protagonista_dual_portrait(
        "Titulo", "Headline", "vitima", "outro", api_key="fake-key", cliente=cliente, subject_name="Burke Ramsey",
    )
    texto_enviado = cliente.chamadas[0]["messages"][0]["content"]
    assert "Burke Ramsey" in texto_enviado


def test_selecionar_protagonista_resposta_fora_do_enum_cai_em_fallback():
    cliente = _ClienteFake(
        [_resposta_tool_use(tbrief.NOME_TOOL_PROTAGONISTA_DUAL, {"protagonista_papel": "hero", "motivo": "x"})]
    )
    resultado = tbrief.selecionar_protagonista_dual_portrait(
        "Titulo", "Headline", "vitima", "outro", api_key="fake-key", cliente=cliente
    )
    assert resultado["protagonista"] == "hero"
    assert resultado["erro"] == "resposta_invalida"


def test_selecionar_protagonista_papeis_identicos_cai_em_fallback_sem_chamar_api():
    """Par degenerado (nao deveria acontecer via templates_elegiveis - regra
    5 forca DUOTONE_DOSSIER quando os papeis sao iguais) - mesmo assim
    nunca quebra nem chama a API sem ter como desambiguar."""
    cliente = _ClienteFake([])
    resultado = tbrief.selecionar_protagonista_dual_portrait(
        "Titulo", "Headline", "vitima", "vitima", api_key="fake-key", cliente=cliente
    )
    assert resultado["protagonista"] == "hero"
    assert resultado["erro"] == "papeis_insuficientes_ou_identicos"
    assert cliente.chamadas == []


def test_selecionar_protagonista_excecao_da_api_nunca_propaga():
    resultado = tbrief.selecionar_protagonista_dual_portrait(
        "Titulo", "Headline", "vitima", "outro", api_key="fake-key", cliente=_ClienteQuebrado()
    )
    assert resultado["protagonista"] == "hero"
    assert resultado["erro"] == "chamada_api_falhou"


# ---------------------------------------------------------------------------
# GRUPO F/H - caso real Burke Ramsey/JonBenét (ponta a ponta)
# ---------------------------------------------------------------------------


def test_gerar_briefing_completo_caso_burke_ramsey_seleciona_dual_portrait_e_protagonista_pelo_titulo(tmp_path):
    """Reproducao literal do caso real do pedido: JonBenét (vitima, slot
    hero) + Burke (outro, slot secondary). O titulo e' sobre Burke - o
    protagonista visual do DUAL_PORTRAIT tem que ser ele (secondary),
    mesmo enviado no slot secundario (validacao 11). O `conceito_visual`
    (Grupo A do Headline Engine, GRUPO E/G desta sessao - substitui o
    antigo `evidencia_central`/`conflito`/`data_chave`) chega ao briefing
    e aparece no texto final; 'bowl'/'2008' (detalhes irrelevantes ao
    conceito visual) nunca aparecem porque nunca sao passados pra'
    `montar_prompt_dual_portrait` - so' o que o Headline Engine decidiu
    como conceito visual chega aqui."""
    (tmp_path / "titulo.txt").write_text(
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother", encoding="utf-8"
    )
    _escrever_metadados(
        tmp_path,
        {
            "headline": "CLEARED BY DNA, THEN ACCUSED",
            "emphasis_word": "",
            "accent": "blue",
            "conceito_visual": {
                "elemento_principal": "a 1999 DNA lab report and test swab",
                "tipo_elemento": "documento",
                "acao_ou_momento": None,
                "revelacao": None,
                "papel_na_composicao": "apoio",
            },
        },
    )
    _escrever_sujeitos(tmp_path, hero_papel="vitima", secondary_papel="outro")

    cliente = _ClienteFake(
        [
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "woman", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"},
            ),
            _resposta_tool_use(
                tbrief.NOME_TOOL_ATRIBUTOS,
                {"genero": "man", "faixa_etaria": "", "expressao": "", "enquadramento": "unknown"},
            ),
            _resposta_tool_use(
                tbrief.NOME_TOOL_RELACAO_CONCEITO,
                {"pertence_a_papel": "outro", "motivo": "o documento de DNA e' o eixo do caso de Burke"},
            ),
            _resposta_tool_use(
                tbrief.NOME_TOOL_PROTAGONISTA_DUAL,
                {"protagonista_papel": "outro", "motivo": "o titulo e o video sao sobre Burke"},
            ),
        ]
    )

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key="fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["template_escolhido"] == "DUAL_PORTRAIT"
    briefing = resultado["briefing_completo"]

    assert "a 1999 DNA lab report and test swab" in briefing
    assert "bowl" not in briefing.lower()
    assert "2008" not in briefing
    assert "exoneration" not in briefing.lower()

    auditoria = json.loads((tmp_path / "thumbnail" / "briefing.json").read_text(encoding="utf-8"))
    assert auditoria["protagonista_dual_portrait"]["protagonista"] == "secondary"
    assert auditoria["conceito_visual"]["elemento_principal"] == "a 1999 DNA lab report and test swab"

    # protagonista=secondary ("outro"/Burke) fica na posicao dominante,
    # mesmo enviado no slot secundario.
    pos_outro = briefing.index("person connected to the case")
    pos_vitima = briefing.index("the case's victim")
    assert pos_outro < pos_vitima


def test_gerar_briefing_completo_projeto_antigo_sem_conceito_visual_continua_funcionando(tmp_path):
    """Validacao 9 do pedido / GRUPO J (sessao "conceito visual", Parte 2):
    projeto sem `conceito_visual` (gerado antes desta feature existir, ou
    Grupo A do Headline Engine falhou) nunca quebra - tratado com graca em
    toda a cadeia, ate' `gerar_briefing_completo`/`montar_prompt_*`."""
    _escrever_metadados(tmp_path, {"headline": "COLD CASE REOPENED", "emphasis_word": "REOPENED"})
    _escrever_sujeitos(tmp_path, hero_papel="vitima", secondary_papel="outro")

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    assert resultado["template_escolhido"] == "DUAL_PORTRAIT"
    auditoria = json.loads((tmp_path / "thumbnail" / "briefing.json").read_text(encoding="utf-8"))
    assert auditoria["conceito_visual"] is None
    assert "prominently feature" not in resultado["briefing_completo"]
    # protagonista nao decidido (sem cliente) -> fallback "hero", preserva
    # comportamento de sempre.
    assert auditoria["protagonista_dual_portrait"]["protagonista"] == "hero"


# ---------------------------------------------------------------------------
# GRUPO E/F/G/J (sessao "conceito visual", Parte 2) - montar_clausula_
# conceito_visual (funcao pura), enforcement estrutural sobre os 6
# montadores, e prioridade semantica sobre o background_prompt.
# ---------------------------------------------------------------------------


def test_montar_clausula_conceito_visual_none_ou_vazio_devolve_string_vazia():
    assert tbrief.montar_clausula_conceito_visual(None) == ""
    assert tbrief.montar_clausula_conceito_visual({}) == ""
    assert tbrief.montar_clausula_conceito_visual({"elemento_principal": ""}) == ""


def test_montar_clausula_conceito_visual_so_elemento_principal_sem_acao():
    """D. Somente elemento -> so' descreve o elemento, sem prefixo de
    categoria (Correcao 10 - `tipo_elemento` nao entra mais como prefixo
    generico redundante tipo "a document: a sealed lab envelope")."""
    clausula = tbrief.montar_clausula_conceito_visual(
        {"elemento_principal": "a sealed lab envelope", "tipo_elemento": "documento"}
    )
    assert "a sealed lab envelope" in clausula
    assert "prominently feature" in clausula
    assert "captured in the exact moment" not in clausula
    # Correcao 10: tipo_elemento nunca vira prefixo generico duplicando o
    # que elemento_principal ja' diz.
    assert "a document" not in clausula


def test_montar_clausula_conceito_visual_nao_duplica_categoria_do_tipo_elemento():
    """Correcao 10 - caso real: o briefing abria com "a piece of
    recording/camera equipment, the doorbell camera..." - categoria e
    elemento concreto repetidos. `tipo_elemento` nunca deve aparecer como
    prefixo generico antes de `elemento_principal`."""
    clausula = tbrief.montar_clausula_conceito_visual(
        {
            "elemento_principal": "the doorbell camera and the suspect's exposed wrist tattoo",
            "tipo_elemento": "camera_filmagem",
        }
    )
    assert "a piece of recording/camera equipment" not in clausula
    assert "the doorbell camera and the suspect's exposed wrist tattoo" in clausula


def test_montar_clausula_conceito_visual_acao_sem_revelacao_descreve_so_o_momento():
    """B. Elemento + acao sem revelacao -> so' a acao, sem inventar
    revelacao nenhuma."""
    clausula = tbrief.montar_clausula_conceito_visual(
        {
            "elemento_principal": "the doorbell camera",
            "tipo_elemento": "camera_filmagem",
            "acao_ou_momento": "the masked figure reaching up to block the lens",
            "revelacao": None,
        }
    )
    assert "the doorbell camera" in clausula
    assert "the masked figure reaching up to block the lens" in clausula
    assert "leads directly to" not in clausula
    assert "exposing" not in clausula


def test_montar_clausula_conceito_visual_revelacao_sem_acao_nao_inventa_acao():
    """C. Elemento + revelacao sem acao (ramo defensivo - `_normalizar_
    conceito_visual` no Headline Engine normalmente evita essa
    combinacao, mas a funcao pura nunca deve inventar uma acao pra'
    preencher o vazio nem quebrar)."""
    clausula = tbrief.montar_clausula_conceito_visual(
        {
            "elemento_principal": "the doorbell camera",
            "tipo_elemento": "camera_filmagem",
            "acao_ou_momento": None,
            "revelacao": "exposing a tattoo on his wrist",
        }
    )
    assert "the doorbell camera" in clausula
    assert "exposing a tattoo on his wrist" in clausula
    assert "captured in the exact moment" not in clausula


def test_montar_clausula_conceito_visual_acao_com_revelacao_liga_a_cadeia_causal():
    """A. Elemento + acao + revelacao - a relacao causal COMPLETA -
    elemento -> acao -> revelacao - numa unica clausula gramatical, nao
    so' os 3 campos concatenados soltos (Grupo K: um briefing que
    menciona "doorbell camera" e "tattoo" separados passaria num teste
    raso mas produziria imagem ruim)."""
    clausula = tbrief.montar_clausula_conceito_visual(
        {
            "elemento_principal": "the doorbell camera",
            "tipo_elemento": "camera_filmagem",
            "acao_ou_momento": "the masked figure reaching up to block the lens",
            "revelacao": "exposing a tattoo on his wrist",
        }
    )
    assert "the doorbell camera" in clausula
    assert "the masked figure reaching up to block the lens" in clausula
    assert "exposing a tattoo on his wrist" in clausula
    # Acao e revelacao aparecem na mesma clausula, na ordem certa e
    # conectadas causalmente - nunca a construcao quebrada "a moment
    # that directly leads to <oracao completa>".
    assert clausula.index("the masked figure reaching up to block the lens") < clausula.index(
        "exposing a tattoo on his wrist"
    )
    assert "a moment that directly leads to" not in clausula


def test_montar_clausula_conceito_visual_caso_nancy_real_nao_produz_construcao_quebrada():
    """E. Caso Nancy real (validado contra a API de verdade - Grupo K).
    `revelacao` chega como oracao completa (sujeito+verbo: "the blocking
    motion rotates his wrist..."), o que quebrava o conector antigo "a
    moment that directly leads to {revelacao}" em "leads to the blocking
    motion rotates..." - gramaticalmente invalido. O conector novo tem
    que encaixar `revelacao` sem forcar essa concatenacao quebrada."""
    acao = "the masked figure reaching up with a branch to block the doorbell camera lens"
    revelacao = (
        "the blocking motion rotates his wrist into view, exposing a tattoo on the underside "
        "of his right wrist"
    )
    clausula = tbrief.montar_clausula_conceito_visual(
        {
            "elemento_principal": "the doorbell camera and the suspect's exposed wrist tattoo",
            "tipo_elemento": "camera_filmagem",
            "acao_ou_momento": acao,
            "revelacao": revelacao,
        }
    )
    assert acao in clausula
    assert revelacao in clausula
    assert "leads to the blocking motion rotates" not in clausula
    assert "a moment that directly leads to" not in clausula
    # acao e revelacao aparecem na mesma clausula, na ordem certa.
    assert clausula.index(acao) < clausula.index(revelacao)


@pytest.mark.parametrize("nome_template", list(tbrief._MONTADORES.keys()))
def test_todos_os_montadores_incorporam_a_clausula_do_conceito_visual(nome_template):
    """GRUPO F. Itera o dict REAL `_MONTADORES` (nunca uma lista de nomes
    escrita a' mao - um template novo que esqueca de incorporar o conceito
    visual seria pego automaticamente aqui). Marcadores UNICOS em
    elemento_principal/acao_ou_momento/revelacao - a clausula PRODUZIDA por
    `montar_clausula_conceito_visual()` (nao so' os marcadores soltos)
    precisa aparecer LITERALMENTE no prompt final: um template que so'
    copiasse `elemento_principal` sem transportar a relacao causal (ex:
    inserindo so' "UNIQMARKER_ELEMENTO" sem a frase de conexao) faz este
    assert falhar."""
    conceito = {
        "elemento_principal": "the UNIQMARKER_ELEMENTO doorbell camera",
        "tipo_elemento": "camera_filmagem",
        "acao_ou_momento": "UNIQMARKER_ACAO the masked figure reaching up",
        "revelacao": "UNIQMARKER_REVELACAO exposing a tattoo on his wrist",
        "papel_na_composicao": "apoio",
    }
    montador = tbrief._MONTADORES[nome_template]

    prompt, _ = montador(_caso_base(conceito_visual=conceito))

    assert "UNIQMARKER_ELEMENTO" in prompt
    assert "UNIQMARKER_ACAO" in prompt
    assert "UNIQMARKER_REVELACAO" in prompt
    assert tbrief.montar_clausula_conceito_visual(conceito) in prompt


def test_frase_dominancia_conceito_dominante_vem_primeiro_fundo_fica_subordinado():
    resultado = tbrief._frase_dominancia_conceito("CLAUSULA_X", "dominante", "FUNDO_Y")
    assert resultado.index("CLAUSULA_X") < resultado.index("FUNDO_Y")
    assert "secondary backdrop" in resultado


def test_frase_dominancia_conceito_apoio_mantem_fundo_como_ancora_primaria():
    resultado = tbrief._frase_dominancia_conceito("CLAUSULA_X", "apoio", "FUNDO_Y")
    assert resultado.index("FUNDO_Y") < resultado.index("CLAUSULA_X")


def test_frase_dominancia_conceito_sem_clausula_devolve_so_o_fundo_original():
    assert tbrief._frase_dominancia_conceito("", "dominante", "FUNDO_Y") == "FUNDO_Y"
    assert tbrief._frase_dominancia_conceito("", "apoio", "FUNDO_Y") == "FUNDO_Y"


def test_mesmo_conceito_visual_em_dois_templates_diferentes_cada_um_com_sua_estetica():
    """GRUPO J - o mesmo conceito incorporado em dois templates distintos:
    ambos mostram o elemento, mas o texto ao redor preserva a estetica
    PROPRIA de cada template (nunca o mesmo prompt duas vezes)."""
    conceito = {
        "elemento_principal": "the sealed 1999 DNA lab envelope",
        "tipo_elemento": "documento",
        "acao_ou_momento": None,
        "revelacao": None,
        "papel_na_composicao": "apoio",
    }
    caso = _caso_base(conceito_visual=conceito)

    prompt_evidence, _ = tbrief.montar_prompt_evidence_scene(caso)
    prompt_dossier, _ = tbrief.montar_prompt_duotone_dossier(caso)

    assert "the sealed 1999 DNA lab envelope" in prompt_evidence
    assert "the sealed 1999 DNA lab envelope" in prompt_dossier
    assert prompt_evidence != prompt_dossier
    assert "police cars" in prompt_evidence  # estetica propria do EVIDENCE_SCENE
    assert "black-and-white" in prompt_dossier  # estetica propria do DUOTONE_DOSSIER


@pytest.mark.parametrize(
    "hero_papel,secondary_papel",
    [(None, None), ("vitima", None), ("vitima", "suspeito")],
    ids=["zero_sujeitos", "um_sujeito", "dois_sujeitos"],
)
def test_gerar_briefing_completo_conceito_visual_aparece_com_zero_um_ou_dois_sujeitos(
    tmp_path, hero_papel, secondary_papel
):
    """GRUPO J - o conceito visual precisa aparecer no briefing final
    independente de quantos sujeitos existem - a clausula nao depende de
    foto de sujeito nenhuma (o elemento pode ser camera/documento/local,
    sem relacao com pessoa alguma)."""
    _escrever_metadados(
        tmp_path,
        {
            "headline": "WHAT THE DOORBELL CAUGHT",
            "emphasis_word": "CAUGHT",
            "conceito_visual": {
                "elemento_principal": "the doorbell camera",
                "tipo_elemento": "camera_filmagem",
                "acao_ou_momento": None,
                "revelacao": None,
                "papel_na_composicao": "apoio",
            },
        },
    )
    if hero_papel:
        _escrever_sujeitos(tmp_path, hero_papel=hero_papel, secondary_papel=secondary_papel)

    resultado = tbrief.gerar_briefing_completo(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    assert "the doorbell camera" in resultado["briefing_completo"]


# ---------------------------------------------------------------------------
# FASE 1 (correcao do estado do briefing) - fingerprint deterministico de
# sujeitos.json e mensagem de indisponibilidade contextual. Ver
# `scripts/thumbnail_briefing.calcular_fingerprint_sujeitos`/
# `motivo_indisponibilidade` e a checagem de staleness em
# `server.py:thumbnail_gerar_composicao_ia` (testada em
# tests/test_thumbnail_rotas.py - TESTE H, caso real Nancy Guthrie).
# ---------------------------------------------------------------------------


def test_fingerprint_sujeitos_estado_a_hero_none_secondary_none():
    """TESTE A: os dois slots vazios produz um fingerprint valido e
    deterministico (nunca lanca excecao com entrada vazia)."""
    fingerprint = tbrief.calcular_fingerprint_sujeitos({"hero": None, "secondary": None})
    assert isinstance(fingerprint, str) and len(fingerprint) == 64


def test_fingerprint_sujeitos_estado_b_difere_do_estado_a():
    """TESTE B: hero=vitima/secondary=None produz fingerprint DIFERENTE do
    estado A (os dois vazios)."""
    fingerprint_a = tbrief.calcular_fingerprint_sujeitos({"hero": None, "secondary": None})
    fingerprint_b = tbrief.calcular_fingerprint_sujeitos(
        {"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": None}
    )
    assert fingerprint_b != fingerprint_a


def test_fingerprint_sujeitos_estado_c_difere_do_estado_b():
    """TESTE C: hero=vitima/secondary=investigador produz fingerprint
    DIFERENTE do estado B (so' hero preenchido)."""
    fingerprint_b = tbrief.calcular_fingerprint_sujeitos(
        {"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": None}
    )
    fingerprint_c = tbrief.calcular_fingerprint_sujeitos(
        {
            "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
            "secondary": {"arquivo": "secondary.jpg", "papel": "investigador"},
        }
    )
    assert fingerprint_c != fingerprint_b


def test_fingerprint_sujeitos_estado_d_mudar_so_o_papel_do_secondary_muda_o_fingerprint():
    """TESTE D: alterar SO' o papel do secondary (investigador -> suspeito,
    mesmo arquivo) muda o fingerprint."""
    base = {
        "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
        "secondary": {"arquivo": "secondary.jpg", "papel": "investigador"},
    }
    alterado = {
        "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
        "secondary": {"arquivo": "secondary.jpg", "papel": "suspeito"},
    }
    assert tbrief.calcular_fingerprint_sujeitos(alterado) != tbrief.calcular_fingerprint_sujeitos(base)


def test_fingerprint_sujeitos_estado_e_remover_secondary_muda_o_fingerprint_de_novo():
    """TESTE E: remover o secondary (volta pra None) produz um fingerprint
    diferente do estado com secondary preenchido - nunca volta a ser igual
    ao estado A por coincidencia (hero continua preenchido)."""
    com_secondary = {
        "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
        "secondary": {"arquivo": "secondary.jpg", "papel": "suspeito"},
    }
    sem_secondary = {"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": None}
    assert tbrief.calcular_fingerprint_sujeitos(sem_secondary) != tbrief.calcular_fingerprint_sujeitos(com_secondary)


def test_fingerprint_sujeitos_estado_f_mesmo_estado_produz_o_mesmo_fingerprint():
    """TESTE F: gerar o fingerprint duas vezes sem alterar o estado
    devolve exatamente o mesmo valor - determinismo, nao so' "parecido"."""
    estado = {
        "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
        "secondary": {"arquivo": "secondary.jpg", "papel": "investigador"},
    }
    primeira = tbrief.calcular_fingerprint_sujeitos(estado)
    segunda = tbrief.calcular_fingerprint_sujeitos(json.loads(json.dumps(estado)))  # copia independente
    assert primeira == segunda


def test_fingerprint_sujeitos_ignora_ordem_de_insercao_do_dict():
    """Nunca depende de ordem de insercao/chaves extras irrelevantes -
    so' hero.arquivo/hero.papel/secondary.arquivo/secondary.papel
    importam pro fingerprint."""
    estado_1 = {
        "secondary": {"papel": "investigador", "arquivo": "secondary.jpg"},
        "hero": {"papel": "vitima", "arquivo": "hero.jpg"},
    }
    estado_2 = {
        "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
        "secondary": {"arquivo": "secondary.jpg", "papel": "investigador"},
    }
    assert tbrief.calcular_fingerprint_sujeitos(estado_1) == tbrief.calcular_fingerprint_sujeitos(estado_2)


def test_fingerprint_sujeitos_entrada_invalida_nunca_levanta_excecao():
    fingerprint_estado_vazio = tbrief.calcular_fingerprint_sujeitos({"hero": None, "secondary": None})
    assert tbrief.calcular_fingerprint_sujeitos(None) == fingerprint_estado_vazio
    assert tbrief.calcular_fingerprint_sujeitos({}) == fingerprint_estado_vazio
    # slot que nao e' dict (lixo/corrompido) e' tratado como slot vazio -
    # nunca levanta excecao.
    assert tbrief.calcular_fingerprint_sujeitos({"hero": "nao e' dict", "secondary": 123}) == fingerprint_estado_vazio


def test_gerar_briefing_completo_persiste_fingerprint_correspondente_ao_estado(tmp_path):
    """Briefing gerado pra' um estado de sujeitos recebe o fingerprint
    DESSE estado, tanto no retorno quanto em briefing.json - e o
    fingerprint muda entre um estado sem sujeitos e um com sujeitos."""
    _escrever_metadados(tmp_path, {"headline": "COLD CASE REOPENED", "emphasis_word": "REOPENED"})

    resultado_sem_sujeitos = tbrief.gerar_briefing_completo(tmp_path, api_key=None)
    assert resultado_sem_sujeitos["sucesso"] is True
    fingerprint_sem_sujeitos = resultado_sem_sujeitos["subjects_fingerprint"]
    assert fingerprint_sem_sujeitos == tbrief.calcular_fingerprint_sujeitos({"hero": None, "secondary": None})

    _escrever_sujeitos(tmp_path, hero_papel="vitima", secondary_papel="investigador")
    resultado_com_sujeitos = tbrief.gerar_briefing_completo(tmp_path, api_key=None)
    assert resultado_com_sujeitos["sucesso"] is True
    fingerprint_com_sujeitos = resultado_com_sujeitos["subjects_fingerprint"]

    assert fingerprint_com_sujeitos != fingerprint_sem_sujeitos
    auditoria = json.loads((tmp_path / "thumbnail" / "briefing.json").read_text(encoding="utf-8"))
    assert auditoria["subjects_fingerprint"] == fingerprint_com_sujeitos


# ---------------------------------------------------------------------------
# FASE 1 - mensagem de indisponibilidade contextual (nunca afirma que
# falta um sujeito que na verdade existe).
# ---------------------------------------------------------------------------


def test_motivo_indisponibilidade_profile_isolation_sem_hero_e_estrutural():
    assert (
        tbrief.motivo_indisponibilidade("PROFILE_ISOLATION", None, None)
        == tbrief.MOTIVO_CURTO_INDISPONIVEL["PROFILE_ISOLATION"]
    )


def test_motivo_indisponibilidade_profile_isolation_com_hero_e_generico_nunca_afirma_falta_de_sujeito():
    """Caso do pedido: hero=vitima + secondary=investigador faz
    INVESTIGATOR_UPDATE vencer com exclusividade - PROFILE_ISOLATION fica
    inelegivel apesar de HAVER sujeito principal. A mensagem nunca pode
    afirmar que falta o sujeito principal nesse caso."""
    motivo = tbrief.motivo_indisponibilidade("PROFILE_ISOLATION", "vitima", "investigador")
    assert motivo == tbrief.MOTIVO_GENERICO_INDISPONIVEL
    assert "sujeito principal" not in motivo.lower()


def test_motivo_indisponibilidade_duotone_dossier_com_hero_e_generico():
    motivo = tbrief.motivo_indisponibilidade("DUOTONE_DOSSIER", "vitima", "investigador")
    assert motivo == tbrief.MOTIVO_GENERICO_INDISPONIVEL
    assert "sujeito principal" not in motivo.lower()


def test_motivo_indisponibilidade_dual_portrait_com_dois_sujeitos_e_generico_nunca_afirma_faltam_2():
    """Mesmo caso, pro DUAL_PORTRAIT: 2 sujeitos existem (vitima +
    investigador), mas o template perde pra' INVESTIGATOR_UPDATE por
    exclusividade - a mensagem nunca pode dizer que faltam 2 sujeitos."""
    motivo = tbrief.motivo_indisponibilidade("DUAL_PORTRAIT", "vitima", "investigador")
    assert motivo == tbrief.MOTIVO_GENERICO_INDISPONIVEL
    assert "2 sujeitos" not in motivo


def test_motivo_indisponibilidade_dual_portrait_sem_secondary_e_estrutural():
    assert (
        tbrief.motivo_indisponibilidade("DUAL_PORTRAIT", "vitima", None)
        == tbrief.MOTIVO_CURTO_INDISPONIVEL["DUAL_PORTRAIT"]
    )


def test_motivo_indisponibilidade_dual_portrait_sem_nenhum_sujeito_e_estrutural():
    assert (
        tbrief.motivo_indisponibilidade("DUAL_PORTRAIT", None, None)
        == tbrief.MOTIVO_CURTO_INDISPONIVEL["DUAL_PORTRAIT"]
    )


@pytest.mark.parametrize(
    "template,hero_papel,secondary_papel",
    [
        ("ARROW_TRIO", "testemunha", "outro"),
        ("INVESTIGATOR_UPDATE", "testemunha", "outro"),
        ("EVIDENCE_SCENE", "vitima", None),
    ],
)
def test_motivo_indisponibilidade_templates_sem_ambiguidade_usa_sempre_o_motivo_estatico(
    template, hero_papel, secondary_papel
):
    """ARROW_TRIO/INVESTIGATOR_UPDATE/EVIDENCE_SCENE nunca perdem por
    exclusividade quando o requisito deles esta' atendido (ver docstring
    de `templates_elegiveis`) - o texto estatico continua correto em
    qualquer combinacao onde eles ficam inelegiveis."""
    assert (
        tbrief.motivo_indisponibilidade(template, hero_papel, secondary_papel)
        == tbrief.MOTIVO_CURTO_INDISPONIVEL[template]
    )


def test_motivos_indisponibilidade_cobre_todos_os_templates_validos():
    motivos = tbrief.motivos_indisponibilidade("vitima", "investigador")
    assert set(motivos.keys()) == set(tbrief.TEMPLATES_VALIDOS)
    for codigo in tbrief.TEMPLATES_VALIDOS:
        assert isinstance(motivos[codigo], str) and motivos[codigo]
