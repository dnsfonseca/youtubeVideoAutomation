"""Testes de `_calcular_custo_detalhado_projeto` (server.py) - CLAUDE.md
secao 5.9 (custo total estimado, tela de conclusao). Correcao de sessao de
refinamento: o total estava subestimado porque duas fontes de custo real
nunca eram somadas - clipes/sincronizacao_vision_log.json (Sincronizacao por
IA/Vision) e thumbnail/metadados.json.custo_usd_estimado (Grupo D/metadados +
Grupo C/briefing exportavel da Etapa 7, que scripts/7_thumbnail.py so' passou
a persistir nesta mesma correcao)."""

import json

from server import _calcular_custo_detalhado_projeto


def test_projeto_sem_nenhum_artefato_devolve_total_zero_sem_itens(tmp_path):
    resultado = _calcular_custo_detalhado_projeto(tmp_path)
    assert resultado == {"total_usd": 0.0, "itens": []}


def test_soma_roteiro_e_narracao(tmp_path):
    (tmp_path / "job_metadata.json").write_text(
        json.dumps({"custo_estimado_usd": 1.0}), encoding="utf-8"
    )
    (tmp_path / "narracao_metadata.json").write_text(
        json.dumps({"custo_estimado_usd": 0.25}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 1.25
    rotulos = [item["rotulo"] for item in resultado["itens"]]
    assert "Roteiro (pesquisa + geração)" in rotulos
    assert "Narração (TTS)" in rotulos


def test_narracao_por_upload_com_custo_zero_nao_aparece_no_detalhamento(tmp_path):
    """custo_estimado_usd=0.0 (origem_audio=upload, CLAUDE.md secao 5.6)
    nao deve virar uma linha "$0.00" no detalhamento - so' fontes com valor
    > 0 aparecem em `itens`."""
    (tmp_path / "narracao_metadata.json").write_text(
        json.dumps({"custo_estimado_usd": 0.0}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 0.0
    assert resultado["itens"] == []


def test_soma_sincronizacao_por_ia_antes_ausente_do_total(tmp_path):
    """Achado real (sessao de refinamento): clipes/sincronizacao_vision_log.json
    tinha `custo_usd_total` mas nunca era somado - o total da tela de
    conclusao ficava sistematicamente abaixo do gasto real em qualquer
    projeto que usou a Feature A (sincronizacao de clipes por Vision)."""
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    (pasta_clipes / "sincronizacao_vision_log.json").write_text(
        json.dumps({"custo_usd_total": 0.098631}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 0.0986
    assert resultado["itens"][0]["rotulo"] == "Sincronização de clipes por IA (Vision)"


def test_soma_metadados_da_thumbnail_antes_ausente_do_total(tmp_path):
    """Achado real: thumbnail/metadados.json nunca teve nenhum campo de
    custo persistido - a chamada de Grupo D (metadados) e o briefing do
    Grupo C (fotos de sujeito via Vision + selecao de template) gastavam
    dinheiro real sem deixar rastro nenhum pra somar."""
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps({"title": [], "custo_usd_estimado": 0.0123}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 0.0123
    assert resultado["itens"][0]["rotulo"] == "Metadados e briefing da thumbnail"


def test_soma_headline_engine_fundo_e_composicao_por_ia(tmp_path):
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_previews = pasta_thumbnail / "previews"
    pasta_previews.mkdir(parents=True)
    (pasta_thumbnail / "headline_engine.json").write_text(
        json.dumps({"custo_usd": 0.0274}), encoding="utf-8"
    )
    (pasta_thumbnail / "fundo_gerado.jpg.custo.json").write_text(
        json.dumps({"custo_usd_estimado": 0.02}), encoding="utf-8"
    )
    (pasta_previews / "composicao_ia.jpg.custo.json").write_text(
        json.dumps({"custo_usd_estimado": 0.02}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 0.0674
    rotulos = {item["rotulo"] for item in resultado["itens"]}
    assert rotulos == {
        "Headline Engine",
        "Fundo da thumbnail gerado por IA",
        "Composição da thumbnail por IA",
    }


def test_custo_json_desconhecido_ainda_e_somado_como_rede_de_seguranca(tmp_path):
    """Um *.custo.json com nome diferente dos dois conhecidos (fundo/
    composicao) nao pode ser perdido silenciosamente - cai no fallback
    generico com rotulo derivado do nome do arquivo."""
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "algo_novo.jpg.custo.json").write_text(
        json.dumps({"custo_usd_estimado": 0.05}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 0.05
    assert "algo_novo.jpg.custo.json" in resultado["itens"][0]["rotulo"]


def test_soma_todas_as_fontes_de_uma_vez_reflete_gasto_real_completo(tmp_path):
    """Projeto realista (baseado num caso real de producao) com TODAS as
    fontes de custo presentes - o total precisa refletir a soma exata de
    cada uma, nao so' o subconjunto que o codigo somava antes desta
    correcao."""
    (tmp_path / "job_metadata.json").write_text(
        json.dumps({"custo_estimado_usd": 1.0448}), encoding="utf-8"
    )
    (tmp_path / "narracao_metadata.json").write_text(
        json.dumps({"custo_estimado_usd": 0.0}), encoding="utf-8"
    )
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    (pasta_clipes / "sincronizacao_vision_log.json").write_text(
        json.dumps({"custo_usd_total": 0.098631}), encoding="utf-8"
    )
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_previews = pasta_thumbnail / "previews"
    pasta_previews.mkdir(parents=True)
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps({"custo_usd_estimado": 0.015}), encoding="utf-8"
    )
    (pasta_thumbnail / "headline_engine.json").write_text(
        json.dumps({"custo_usd": 0.027411}), encoding="utf-8"
    )
    (pasta_thumbnail / "fundo_gerado.jpg.custo.json").write_text(
        json.dumps({"custo_usd_estimado": 0.02}), encoding="utf-8"
    )
    (pasta_previews / "composicao_ia.jpg.custo.json").write_text(
        json.dumps({"custo_usd_estimado": 0.02}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == round(1.0448 + 0.098631 + 0.015 + 0.027411 + 0.02 + 0.02, 4)
    assert len(resultado["itens"]) == 6


def test_arquivo_json_corrompido_nao_derruba_o_calculo(tmp_path):
    (tmp_path / "job_metadata.json").write_text("{invalido", encoding="utf-8")
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "headline_engine.json").write_text(
        json.dumps({"custo_usd": 0.01}), encoding="utf-8"
    )

    resultado = _calcular_custo_detalhado_projeto(tmp_path)

    assert resultado["total_usd"] == 0.01
