"""Testes do refinamento "pipeline horizontal clicavel": etapas com tela
navegavel (Roteiro, o alcance de /concluido pela ultima etapa "Montagem",
e - desde o item 3 da sessao de correcoes de composicao/interface -
Download/Transcricao/Audio/Clipes via a rota generica somente-leitura
`ver_etapa_pipeline`) ganham `clicavel`/`url` em cada passo de
`pipeline_steps` (server.py:_determinar_click / _parsear_pipeline_steps).

Usa a rota /status/<id> pra inspecionar `pipeline_steps` porque ela nao
tem nenhum gate de status (ao contrario de /revisar_roteiro) - ideal pra
exercitar a matriz de estados sem precisar simular cada pre-condicao de
outras rotas.
"""

import json

import pytest


def _criar_projeto(projetos_dir, nome, status, etapa_atual, roteiro_aprovado=False):
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    if roteiro_aprovado:
        (pasta / "roteiro_aprovado.md").write_text("Roteiro aprovado.", encoding="utf-8")
    (pasta / "job.json").write_text(
        json.dumps(
            {"projeto_id": nome, "status": status, "etapa_atual": etapa_atual},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return pasta


@pytest.fixture
def pipeline_steps_de(client, tmp_path, monkeypatch):
    """Helper de teste: cria o projeto no disco com o status/etapa dados e
    devolve a lista `pipeline_steps` que a rota /status/<id> calculou pra
    ele (le direto do server via um hook simples: recarrega a pagina e
    reconstrói os passos batendo em _parsear_pipeline_steps nao seria
    fiel ao fluxo real, entao inspecionamos o HTML renderizado)."""

    def _executar(nome, status, etapa_atual, roteiro_aprovado=False):
        projetos_dir = tmp_path / "projetos"
        monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
        _criar_projeto(projetos_dir, nome, status, etapa_atual, roteiro_aprovado)
        resposta = client.get(f"/status/{nome}")
        assert resposta.status_code == 200
        return resposta.get_data(as_text=True)

    return _executar


def test_roteiro_done_e_clicavel_aponta_para_modo_readonly(pipeline_steps_de):
    """Pipeline avancou pra 'audio' (roteiro ja aprovado, fica 'done') ->
    circulo do Roteiro vira link pra /revisar_roteiro?modo=readonly."""
    pagina = pipeline_steps_de(
        "caso_roteiro_done", status="aguardando_audio", etapa_atual="audio"
    )

    assert "pipeline-step-clicavel" in pagina
    assert "/projetos/caso_roteiro_done/revisar_roteiro?modo=readonly" in pagina


def test_roteiro_waiting_e_clicavel_aponta_para_modo_normal(pipeline_steps_de):
    """Job pausado aguardando revisao (a propria etapa 'roteiro' esta
    'waiting') -> circulo do Roteiro aponta pra /revisar_roteiro sem
    modo=readonly (e' a tela de aprovacao ainda ativa)."""
    pagina = pipeline_steps_de(
        "caso_roteiro_waiting", status="aguardando_revisao", etapa_atual="roteiro"
    )

    assert "/projetos/caso_roteiro_waiting/revisar_roteiro" in pagina
    assert "modo=readonly" not in pagina


def test_roteiro_pending_nao_e_clicavel(pipeline_steps_de):
    """Job ainda em download - Roteiro nem comecou (pending) -> nao
    clicavel."""
    pagina = pipeline_steps_de(
        "caso_roteiro_pending", status="em_andamento", etapa_atual="download"
    )

    assert "pipeline-step-clicavel" not in pagina


def test_montagem_done_com_job_concluido_aponta_para_concluido(pipeline_steps_de):
    """Job inteiro concluido -> a ultima etapa (Montagem) e' a unica forma
    de ficar 'done' nessa posicao, e vira link pra /concluido."""
    pagina = pipeline_steps_de(
        "caso_montagem_done", status="concluido", etapa_atual="montagem"
    )

    assert "/projetos/caso_montagem_done/concluido" in pagina
    assert "pipeline-step-clicavel" in pagina


def test_montagem_running_nao_e_clicavel(pipeline_steps_de):
    """Job ainda montando o video (etapa atual = montagem, em andamento,
    status != 'concluido') -> o circulo da Montagem (estado 'running')
    nao vira link. status.html tem, à parte da pipeline, um botao "Ver
    video" que tambem aponta pra /concluido quando o video ja existe -
    por isso a checagem e' na classe CSS do proprio circulo do pipeline
    (só ela combina estado + clicavel), nao so' na presenca da URL na
    pagina."""
    pagina = pipeline_steps_de(
        "caso_montagem_running", status="em_andamento", etapa_atual="montagem"
    )

    assert 'pipeline-step-running pipeline-step-clicavel' not in pagina


def test_aguardando_revisao_mostra_download_e_transcricao_como_done(pipeline_steps_de):
    """Regressao: ate a correcao pos-Sessao 20, a Etapa 3 gravava
    etapa_atual="revisao" (valor que nunca existiu em PIPELINE_ETAPAS) ao
    pausar para revisao humana. _parsear_pipeline_steps nao achava o
    indice dessa etapa e marcava TODOS os circulos como 'pending',
    inclusive Download/Transcricao ja concluidos. O codigo correto grava
    etapa_atual="roteiro" - Download e Transcricao (indices 0 e 1, antes
    do indice de 'roteiro') devem aparecer 'done'. Pipeline tem 7 etapas
    hoje (Thumbnail adicionada como Etapa 7) - 2 done + 1 waiting (roteiro)
    + 4 pending (audio, clipes, montagem, thumbnail)."""
    pagina = pipeline_steps_de(
        "caso_aguardando_revisao_regressao", status="aguardando_revisao", etapa_atual="roteiro"
    )

    assert pagina.count("pipeline-step-done") == 2
    assert "pipeline-step-waiting" in pagina
    assert pagina.count("pipeline-step-pending") == 4


def test_etapa_atual_revisao_legacy_normalizada_nao_quebra_pipeline(pipeline_steps_de):
    """Projetos que pausaram para revisao ANTES da correcao ainda tem
    etapa_atual="revisao" gravado em disco. ETAPA_ATUAL_MIGRATION (leitura
    de job.json, nunca reescreve o disco) normaliza esse valor legado para
    "roteiro" - o pipeline horizontal deve renderizar do mesmo jeito que
    um projeto novo (Download/Transcricao 'done', Roteiro 'waiting'), sem
    crashar e sem regredir para "tudo pending"."""
    pagina = pipeline_steps_de(
        "caso_etapa_atual_legado", status="aguardando_revisao", etapa_atual="revisao"
    )

    assert pagina.count("pipeline-step-done") == 2
    assert "pipeline-step-waiting" in pagina


def test_thumbnail_done_com_job_concluido_aponta_para_modo_readonly(pipeline_steps_de):
    """Job inteiro concluido -> a etapa Thumbnail (ultima do pipeline) fica
    'done' e agora reabre a propria tela (/thumbnail?modo=readonly) em vez
    de /concluido - ANTES apontava pro mesmo lugar que Montagem, o que
    dava a impressao de que so' Roteiro tinha tela propria de revisita."""
    pagina = pipeline_steps_de(
        "caso_thumbnail_done", status="concluido", etapa_atual="thumbnail"
    )

    assert "/projetos/caso_thumbnail_done/thumbnail?modo=readonly" in pagina


def test_todas_as_7_etapas_viram_clicaveis_quando_concluido(pipeline_steps_de):
    """Com o job inteiro concluido, as 7 etapas ficam "done"
    (server.py:_parsear_pipeline_steps) e AGORA (item 3 da sessao de
    correcoes de composicao/interface) todas as 7 tem alguma tela de
    revisita: Roteiro (modo=readonly), Montagem (/concluido - unica forma
    dela ficar 'done'), Thumbnail (/thumbnail?modo=readonly) e
    Download/Transcricao/Audio/Clipes via `ver_etapa_pipeline` - contar os
    links clicaveis e' o jeito mais direto de provar isso sem depender de
    HTML interno de cada circulo."""
    pagina = pipeline_steps_de(
        "caso_todas_clicaveis", status="concluido", etapa_atual="thumbnail"
    )

    assert pagina.count("pipeline-step-clicavel") == 7
    assert "/projetos/caso_todas_clicaveis/pipeline/download" in pagina
    assert "/projetos/caso_todas_clicaveis/pipeline/transcricao" in pagina
    assert "/projetos/caso_todas_clicaveis/pipeline/audio" in pagina
    assert "/projetos/caso_todas_clicaveis/pipeline/geracao_clipes" in pagina


def test_download_pending_nao_e_clicavel(pipeline_steps_de):
    """Job ainda na propria etapa de download (running) - Download nunca
    fica 'done' antes de terminar, entao nao vira link ainda."""
    pagina = pipeline_steps_de(
        "caso_download_running", status="em_andamento", etapa_atual="download"
    )

    assert "/projetos/caso_download_running/pipeline/download" not in pagina
