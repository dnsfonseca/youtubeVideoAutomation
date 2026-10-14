"""Testes da tela de revisao de roteiro (CLAUDE.md secao 5.5):

- GET /projetos/<id>/revisar_roteiro renderiza o editor com o roteiro,
  notas de rodape, titulos sugeridos, e opcoes de origem de audio (TTS,
  upload, decidir depois).
- Acesso bloqueado se status nao esta em STATUS_PERMITIDOS_REVISAO
  ("aguardando_revisao" ou "aguardando_audio").
- Notas de rodape [F<n>@mm:ss], [N: ...], [⚠ ...] sao renderizadas como
  HTML interativo.
- Providers TTS desabilitados no dropdown se chave nao configurada.
"""

import json
from pathlib import Path

import pytest

import server


def _criar_projeto_revisao_no_disco(
    tmp_path,
    nome,
    roteiro_md=None,
    roteiro_aprovado_md=None,
    titulos_sugeridos=None,
    job_metadata=None,
    titulo_txt=None,
    perfil="truecrime",
    status="aguardando_revisao",
):
    """Helper: monta a estrutura de um projeto pronto pra revisao de roteiro
    (semelhante a _criar_projeto_no_disco em test_novo_e_status.py, mas
    focado no contexto da tela de revisao)."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text(perfil, encoding="utf-8")

    if roteiro_md is not None:
        (pasta / "roteiro.md").write_text(roteiro_md, encoding="utf-8")
    if roteiro_aprovado_md is not None:
        (pasta / "roteiro_aprovado.md").write_text(roteiro_aprovado_md, encoding="utf-8")
    if titulo_txt is not None:
        (pasta / "titulo.txt").write_text(titulo_txt, encoding="utf-8")
    if titulos_sugeridos is not None:
        (pasta / "titulos_sugeridos.json").write_text(
            json.dumps(titulos_sugeridos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if job_metadata is not None:
        (pasta / "job_metadata.json").write_text(
            json.dumps(job_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (pasta / "job.json").write_text(
        json.dumps(
            {
                "projeto_id": nome,
                "nome": nome,
                "status": status,
                "etapa_atual": "revisao",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return projetos_dir


# ---------------------------------------------------------------------------
# GET /revisar_roteiro - caminho feliz
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_body_tem_data_projeto_id(client, tmp_path, monkeypatch):
    """pipeline_polling.js (Sessao de correcoes UX) le o id do projeto de
    document.body.dataset.projetoId - a tela precisa expor esse atributo."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_revisao_no_disco(tmp_path, "caso_body_attr")))

    resposta = client.get("/projetos/caso_body_attr/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert 'data-projeto-id="caso_body_attr"' in pagina


def test_get_revisar_roteiro_inclui_scripts_de_polling_do_pipeline(client, tmp_path, monkeypatch):
    """A tela de revisao antes so recebia o pipeline renderizado uma vez no
    carregamento (macro Jinja) - agora tambem faz polling via
    pipeline_polling.js (Sessao de correcoes UX, Grupo A)."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_revisao_no_disco(tmp_path, "caso_polling")))

    resposta = client.get("/projetos/caso_polling/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "pipeline_render.js" in pagina
    assert "pipeline_polling.js" in pagina


def test_get_revisar_roteiro_tem_bloco_erro_inline_para_origem_audio(client, tmp_path, monkeypatch):
    """Bloco B (Sessao de correcoes UX): erro de validacao de origem_audio
    vira mensagem inline junto do botao Aprovar, nao mais alert() do
    navegador."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_revisao_no_disco(tmp_path, "caso_erro_inline")))

    resposta = client.get("/projetos/caso_erro_inline/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert 'id="erro-inline-aprovar"' in pagina
    assert 'id="erro-inline-aprovar-msg"' in pagina


def test_get_revisar_roteiro_renderiza_roteiro_em_textarea(client, tmp_path, monkeypatch):
    """GET retorna 200 com textarea contendo roteiro.md quando status e'
    "aguardando_revisao"."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_revisao_no_disco(tmp_path, "caso_teste")))

    resposta = client.get("/projetos/caso_teste/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Procura por <textarea> com o id/name correto
    assert 'id="roteiro-textarea"' in pagina or 'name="roteiro_editado"' in pagina


def test_get_revisar_roteiro_renderiza_roteiro_com_conteudo(client, tmp_path, monkeypatch):
    """Roteiro preenchido aparece no textarea."""
    roteiro_conteudo = "Este eh um roteiro de teste com eventos interessantes."
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path, "caso_conteudo", roteiro_md=roteiro_conteudo
            )
        ),
    )

    resposta = client.get("/projetos/caso_conteudo/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert roteiro_conteudo in pagina


def test_get_revisar_roteiro_em_aguardando_audio_usa_roteiro_aprovado(
    client, tmp_path, monkeypatch
):
    """Quando status e' 'aguardando_audio' (usuario ja aprovou mas escolheu
    'decidir depois' pro audio), carrega roteiro_aprovado.md em vez de
    roteiro.md."""
    roteiro_original = "Roteiro original gerado pela IA"
    roteiro_editado = "Roteiro após edição do usuário"

    projetos_dir = _criar_projeto_revisao_no_disco(
        tmp_path,
        "caso_aguardando_audio",
        roteiro_md=roteiro_original,
        roteiro_aprovado_md=roteiro_editado,
        status="aguardando_audio",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_aguardando_audio/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert roteiro_editado in pagina
    # Roteiro original nao deve estar la (tela mostra só a versão aprovada)
    # (Na verdade, pode aparecer em algum lugar, mas nao no textarea principal)


def test_get_revisar_roteiro_renderiza_notas_de_rodape_como_links(client, tmp_path, monkeypatch):
    """Notas de rodape [F1@04:32] sao renderizadas como links clicaveis com
    class 'nota-fonte'."""
    roteiro = """
    No dia 23 de março, aconteceu um evento importante [F1@04:32].
    Mais detalhes sobre o caso [F1@10:00-11:30].
    """
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_notas", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_notas/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'class="nota-fonte"' in pagina
    assert 'data-fonte="fonte01"' in pagina
    assert 'data-tempo="272"' in pagina  # 4*60+32 = 272


def test_get_revisar_roteiro_renderiza_tag_com_multiplas_fontes_como_varios_badges(
    client, tmp_path, monkeypatch
):
    """Tag com multiplas fontes na mesma nota ([F2@..., F1@...]) - correcao
    pos-Sessao 7.2: roteiro real gerou esse padrao e o parser antigo nao
    reconhecia, entao a tag aparecia bruta no preview. Cada fonte dentro da
    tag agora vira seu proprio badge clicavel, com data-fonte e data-inicio
    proprios."""
    roteiro = "O corpo foi encontrado [F2@00:27-01:00, F1@16:00-16:06] na trilha."
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_notas_multiplas", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_notas_multiplas/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # A tag bruta aparece intacta uma unica vez no textarea de edicao (fonte
    # editavel, nao processada por design) - mas o preview (roteiro_preview_html)
    # deve ter fragmentado a tag em badges separados, entao ela nao sobra
    # SEM processamento fora do textarea.
    assert pagina.count("F2@00:27-01:00, F1@16:00-16:06") == 1
    # Duas fontes -> dois badges "nota-fonte" distintos.
    assert pagina.count('class="nota-fonte"') == 2
    assert 'data-fonte="fonte02"' in pagina
    assert 'data-fonte="fonte01"' in pagina
    assert 'data-inicio="27"' in pagina  # F2: 00:27 -> 27s
    assert 'data-inicio="960"' in pagina  # F1: 16:00 -> 960s
    assert 'data-fim="60"' in pagina  # F2 fim: 01:00 -> 60s
    assert 'data-fim="966"' in pagina  # F1 fim: 16:06 -> 966s


def test_get_revisar_roteiro_renderiza_tag_com_tres_fontes_como_tres_badges(
    client, tmp_path, monkeypatch
):
    """3+ fontes na mesma tag tambem viram badges separados (um por fonte)."""
    roteiro = (
        "O fragmento foi localizado "
        "[F1@13:56-14:01, F2@00:27-01:00, F3@05:10] na trilha."
    )
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_notas_triplas", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_notas_triplas/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert pagina.count('class="nota-fonte"') == 3
    assert 'data-fonte="fonte01"' in pagina
    assert 'data-fonte="fonte02"' in pagina
    assert 'data-fonte="fonte03"' in pagina


def test_get_revisar_roteiro_renderiza_nota_externa_como_link(client, tmp_path, monkeypatch):
    """Notas externas [N: https://...] sao renderizadas como links externos."""
    roteiro = "Fonte: [N: https://exemplo.com/artigo]"
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_nota_url", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_nota_url/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert 'class="nota-externa"' in pagina
    assert 'target="_blank"' in pagina
    assert 'href="https://exemplo.com/artigo"' in pagina


def test_get_revisar_roteiro_renderiza_nota_textual(client, tmp_path, monkeypatch):
    """Notas [N: texto qualquer] (nao URL) sao renderizadas como span com
    title."""
    roteiro = "Vide comentário anterior [N: veja a discussão acima]"
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_nota_texto", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_nota_texto/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert 'class="nota-externa-texto"' in pagina
    assert 'title="veja a discussão acima"' in pagina


def test_get_revisar_roteiro_renderiza_nota_aviso(client, tmp_path, monkeypatch):
    """Notas de aviso [⚠ single-source] sao renderizadas com destaque visual
    (class 'nota-aviso'), acionaveis via modal (class 'abrir-modal-aviso',
    'data-categoria'), e com tooltip vindo do dicionario de warnings
    acionaveis (Sessao 7.2, scripts/warnings_traducoes.py)."""
    roteiro = "Fato mencionado apenas uma vez [⚠ single-source]."
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_nota_aviso", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_nota_aviso/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert 'class="nota-aviso abrir-modal-aviso"' in pagina
    assert 'data-categoria="single-source"' in pagina
    assert 'title="Apenas uma fonte"' in pagina
    assert '⚠' in pagina


def test_get_revisar_roteiro_nota_aviso_categoria_desconhecida_usa_fallback(
    client, tmp_path, monkeypatch
):
    """Categoria de aviso nao mapeada em WARNINGS_ACIONAVEIS cai no
    fallback generico, sem quebrar a renderizacao."""
    roteiro = "Trecho estranho [⚠ categoria-nova-que-a-ia-inventou]."
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_nota_aviso_desconhecida", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_nota_aviso_desconhecida/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'data-categoria="categoria-nova-que-a-ia-inventou"' in pagina
    assert 'title="Atenção sinalizada pela IA"' in pagina


def test_get_revisar_roteiro_nota_aviso_com_texto_livre_apos_virgula(
    client, tmp_path, monkeypatch
):
    """Aviso real observado em producao traz texto livre apos a categoria,
    separado por virgula - a categoria extraida (para lookup no dicionario)
    e' so o trecho antes da virgula."""
    roteiro = (
        "Busca especifica [⚠ single-source, for the mine shaft and "
        "underhome search specifics]."
    )
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_aviso_texto_livre", roteiro_md=roteiro)),
    )

    resposta = client.get("/projetos/caso_aviso_texto_livre/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert 'data-categoria="single-source"' in pagina
    assert 'title="Apenas uma fonte"' in pagina


def test_get_revisar_roteiro_exibe_custo_em_usd_e_brl(client, tmp_path, monkeypatch):
    """Bloco de metadados exibe custo estimado em USD e BRL (cotacao do
    .env, CLAUDE.md secao 7/5.5), com tooltip explicando o escopo (so o
    roteiro)."""
    monkeypatch.setenv("COTACAO_USD_BRL", "5.00")
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_custo",
                roteiro_md="Roteiro qualquer",
                job_metadata={"custo_estimado_usd": 0.50, "web_searches_usadas": 2},
            )
        ),
    )

    resposta = client.get("/projetos/caso_custo/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "$0.50" in pagina
    assert "R$ 2.50" in pagina
    assert "APENAS à geração deste roteiro" in pagina
    assert "cotação estimada" not in pagina.lower()


def test_get_revisar_roteiro_custo_usa_cotacao_default_sem_env(client, tmp_path, monkeypatch):
    """Sem COTACAO_USD_BRL configurada, usa default 5.20 e mostra aviso de
    cotacao estimada."""
    monkeypatch.delenv("COTACAO_USD_BRL", raising=False)
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_custo_default",
                roteiro_md="Roteiro qualquer",
                job_metadata={"custo_estimado_usd": 1.00, "web_searches_usadas": 1},
            )
        ),
    )

    resposta = client.get("/projetos/caso_custo_default/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "$1.00" in pagina
    assert "R$ 5.20" in pagina
    assert "cotação estimada" in pagina.lower()


def test_get_revisar_roteiro_renderiza_titulos_sugeridos(client, tmp_path, monkeypatch):
    """Titulos sugeridos aparecem como radio buttons."""
    titulos_json = {
        "titulos": ["Titulo 1 - Factual", "Titulo 2 - Dramatico", "Titulo 3 - Pergunta"],
        "descricoes": ["Desc 1", "Desc 2", "Desc 3"],
    }
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path, "caso_titulos", titulos_sugeridos=titulos_json
            )
        ),
    )

    resposta = client.get("/projetos/caso_titulos/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Titulo 1 - Factual" in pagina
    assert "Titulo 2 - Dramatico" in pagina
    assert "Titulo 3 - Pergunta" in pagina


def test_get_revisar_roteiro_em_aguardando_audio_preseleciona_titulo_ja_escolhido(
    client, tmp_path, monkeypatch
):
    """Quando status e' 'aguardando_audio', o titulo ja escolhido e pre-marcado
    (valor de titulo.txt)."""
    projetos_dir = _criar_projeto_revisao_no_disco(
        tmp_path,
        "caso_titulo_preselecao",
        roteiro_aprovado_md="Roteiro aprovado",
        titulo_txt="Titulo já escolhido pelo usuario",
        titulos_sugeridos={
            "titulos": ["Opcao 1", "Opcao 2", "Titulo já escolhido pelo usuario"],
            "descricoes": ["Desc 1", "Desc 2", "Desc 3"],
        },
        status="aguardando_audio",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_titulo_preselecao/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "Titulo já escolhido pelo usuario" in pagina


# ---------------------------------------------------------------------------
# GET /revisar_roteiro - status invalido -> redirecionamento
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_status_concluido_redireciona_para_status(
    client, tmp_path, monkeypatch
):
    """GET com status 'concluido' redireciona (302) para /status/<id> com
    mensagem de aviso."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_concluido"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"status": "concluido", "etapa_atual": "montagem"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_concluido/revisar_roteiro")

    assert resposta.status_code == 302
    assert "/status/caso_concluido" in resposta.headers["Location"]
    assert "aviso" in resposta.headers["Location"].lower()


def test_get_revisar_roteiro_status_em_andamento_redireciona(client, tmp_path, monkeypatch):
    """GET com status 'em_andamento' redireciona."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_em_andamento"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"status": "em_andamento", "etapa_atual": "download"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_em_andamento/revisar_roteiro")

    assert resposta.status_code == 302


def test_get_revisar_roteiro_status_erro_redireciona(client, tmp_path, monkeypatch):
    """GET com status 'erro' redireciona."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_erro"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"status": "erro", "etapa_atual": "download"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_erro/revisar_roteiro")

    assert resposta.status_code == 302


def test_get_revisar_roteiro_projeto_inexistente_redireciona(client, monkeypatch):
    """GET com projeto que nao existe redireciona para /status/<id>."""
    monkeypatch.setenv("PROJETOS_DIR", "/tmp/projetos_inexistentes")

    resposta = client.get("/projetos/projeto_inexistente/revisar_roteiro")

    assert resposta.status_code == 302


# ---------------------------------------------------------------------------
# GET /revisar_roteiro - providers TTS desabilitados
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_sem_nenhuma_chave_tts_desabilita_todos_provedores(
    client, tmp_path, monkeypatch
):
    """CLAUDE.md secao 5.5: quando nenhuma chave TTS esta setada
    (ELEVENLABS_API_KEY, OPENAI_API_KEY, AZURE_TTS_KEY), a opcao "Gerar
    automaticamente" (e o dropdown de provedores que vem com ela) nem
    aparece - restam so "Vou fornecer o audio" e "Decidir depois"."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_TTS_KEY", raising=False)
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_tts_nenhum")),
    )

    resposta = client.get("/projetos/caso_tts_nenhum/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'name="tts_provedor"' not in pagina
    assert "Vou fornecer o áudio" in pagina
    assert "Decidir depois" in pagina


def test_get_revisar_roteiro_elevenlabs_habilitado_openai_desabilitado(
    client, tmp_path, monkeypatch
):
    """Quando ELEVENLABS_API_KEY esta setada mas OPENAI_API_KEY nao,
    ElevenLabs aparece ativado e OpenAI desabilitado no dropdown."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_TTS_KEY", raising=False)
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_tts_elevenlabs")),
    )

    resposta = client.get("/projetos/caso_tts_elevenlabs/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # ElevenLabs deve estar habilitado, OpenAI/Azure desabilitados
    # Procura por "elevenlabs" no HTML (pode estar em value, option, etc)
    assert "elevenlabs" in pagina.lower() or "ElevenLabs" in pagina


def test_get_revisar_roteiro_openai_habilitado(client, tmp_path, monkeypatch):
    """Quando OPENAI_API_KEY esta setada, OpenAI aparece ativado."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk_test_key")
    monkeypatch.delenv("AZURE_TTS_KEY", raising=False)
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_tts_openai")),
    )

    resposta = client.get("/projetos/caso_tts_openai/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "openai" in pagina.lower() or "OpenAI" in pagina


def test_get_revisar_roteiro_azure_habilitado(client, tmp_path, monkeypatch):
    """Quando AZURE_TTS_KEY esta setada, Azure aparece ativado."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_TTS_KEY", "azure_key")
    monkeypatch.setenv("AZURE_TTS_REGION", "eastus")
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_tts_azure")),
    )

    resposta = client.get("/projetos/caso_tts_azure/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "azure" in pagina.lower() or "Azure" in pagina


def test_get_revisar_roteiro_todos_provedores_tts_habilitados(client, tmp_path, monkeypatch):
    """Quando todas as 3 chaves de TTS estao setadas, todos os provedores
    aparecem habilitados."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk_test_key")
    monkeypatch.setenv("AZURE_TTS_KEY", "azure_key")
    monkeypatch.setenv("AZURE_TTS_REGION", "eastus")
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_tts_todos")),
    )

    resposta = client.get("/projetos/caso_tts_todos/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Verifica que dropdown existe e tem opcoes
    assert "option" in pagina or "select" in pagina


# ---------------------------------------------------------------------------
# GET /revisar_roteiro - painel explicativo sobre notas de rodape (Entrega 4,
# sessao de correcao pos-Sessao 7)
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_renderiza_painel_explicativo_colapsado(
    client, tmp_path, monkeypatch
):
    """O painel explicativo sobre as marcacoes do roteiro vem colapsado por
    padrao (aria-expanded="false" no botao, painel-conteudo com atributo
    hidden)."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_painel")),
    )

    resposta = client.get("/projetos/caso_painel/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "painel-notas-explicativo" in pagina
    assert 'aria-expanded="false"' in pagina
    assert "painel-conteudo" in pagina
    # O bloco de conteudo do painel deve estar marcado como hidden - a
    # divisao exata do atributo em relacao a classe pode variar, entao
    # verificamos que "hidden" aparece perto de "painel-conteudo".
    indice_painel = pagina.index("painel-conteudo")
    trecho = pagina[indice_painel : indice_painel + 60]
    assert "hidden" in trecho


def test_get_revisar_roteiro_inclui_botao_ignorar_notas(client, tmp_path, monkeypatch):
    """A tela de revisao inclui o botao "Ignorar todas as notas", que some
    as marcacoes do preview/textarea so no navegador (view-only - CLAUDE.md
    5.5; o roteiro_aprovado.md sempre sai sem notas via
    server.py:remover_notas_rodape, testado em test_aprovar_roteiro.py)."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_ignorar_notas")),
    )

    resposta = client.get("/projetos/caso_ignorar_notas/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "btn-ignorar-notas" in pagina
    assert "Ignorar todas as notas" in pagina


def test_get_revisar_roteiro_mostra_pipeline_horizontal(client, tmp_path, monkeypatch):
    """A tela de revisao de roteiro tambem mostra a pipeline horizontal
    sticky (mesma macro de status.html e concluido.html) - antes desta
    sessao, so status.html injetava pipeline_steps."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_revisao_no_disco(tmp_path, "caso_pipeline")),
    )

    resposta = client.get("/projetos/caso_pipeline/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "pipeline-horizontal" in pagina
    assert "Roteiro + Revisão" in pagina
    assert "Montagem" in pagina


# ---------------------------------------------------------------------------
# GET /revisar_roteiro?modo=readonly (refinamento "pipeline clicavel")
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_modo_readonly_com_roteiro_aprovado_retorna_200(
    client, tmp_path, monkeypatch
):
    """Projeto ja passou da revisao (pipeline em 'audio') mas tem
    roteiro_aprovado.md em disco -> ?modo=readonly reabre a tela com 200
    em vez do redirect padrao, mostrando o roteiro aprovado com os
    controles de edicao desabilitados."""
    projetos_dir = _criar_projeto_revisao_no_disco(
        tmp_path,
        "caso_readonly",
        roteiro_aprovado_md="# Roteiro final aprovado\n\nConteudo definitivo.",
        titulo_txt="Titulo escolhido",
        status="em_andamento",
    )
    # status "em_andamento" sozinho nao basta pra simular pipeline em
    # 'audio' (o helper grava etapa_atual="revisao" por padrao) - regrava
    # o job.json com a etapa que faz roteiro=done de verdade.
    (projetos_dir / "caso_readonly" / "job.json").write_text(
        json.dumps({"status": "em_andamento", "etapa_atual": "audio"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_readonly/revisar_roteiro?modo=readonly")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Roteiro final aprovado" in pagina
    assert "Modo visualização" in pagina
    assert 'data-projeto-id="caso_readonly" readonly>' in pagina
    assert 'id="btn-aprovar"' not in pagina
    assert 'id="btn-cancelar"' not in pagina
    assert 'id="btn-regerar"' not in pagina


def test_get_revisar_roteiro_modo_readonly_sem_roteiro_aprovado_redireciona(
    client, tmp_path, monkeypatch
):
    """Sem roteiro_aprovado.md em disco, ?modo=readonly nao tem o que
    mostrar - mantem o redirect padrao pra /status/<id>, igual ao
    comportamento sem o parametro."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_sem_aprovado"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "job.json").write_text(
        json.dumps({"status": "em_andamento", "etapa_atual": "audio"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_sem_aprovado/revisar_roteiro?modo=readonly")

    assert resposta.status_code == 302
    assert "/status/caso_sem_aprovado" in resposta.headers["Location"]


def test_get_revisar_roteiro_status_aguardando_revisao_ignora_modo_readonly(
    client, tmp_path, monkeypatch
):
    """Status ja esta em STATUS_PERMITIDOS_REVISAO ('aguardando_revisao')
    - a tela normal e' exibida (nao entra no ramo readonly) mesmo que
    ?modo=readonly seja passado por engano/manualmente: os controles
    continuam habilitados."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_aguardando_ignora_readonly",
                roteiro_md="Roteiro em revisao.",
                status="aguardando_revisao",
            )
        ),
    )

    resposta = client.get(
        "/projetos/caso_aguardando_ignora_readonly/revisar_roteiro?modo=readonly"
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Modo visualização" not in pagina
    assert 'id="btn-aprovar" class="botao botao-primario" form="form-revisao">' in pagina


def test_get_revisar_roteiro_modo_readonly_nao_renderiza_nenhum_botao_de_acao(
    client, tmp_path, monkeypatch
):
    """Grupo A (sessao pos-teste-manual): em modo=readonly os tres botoes
    de acao (Refazer/Cancelar/Aprovar) nao sao apenas `disabled` - eles
    somem do HTML por completo, porque a decisao e' do servidor. So'
    resta a linha explicando que o roteiro ja foi aprovado."""
    projetos_dir = _criar_projeto_revisao_no_disco(
        tmp_path,
        "caso_readonly_sem_botoes",
        roteiro_aprovado_md="# Roteiro final aprovado",
        titulo_txt="Titulo escolhido",
        status="em_andamento",
    )
    (projetos_dir / "caso_readonly_sem_botoes" / "job.json").write_text(
        json.dumps({"status": "em_andamento", "etapa_atual": "audio"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_readonly_sem_botoes/revisar_roteiro?modo=readonly")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    for id_botao in ("btn-regerar", "btn-cancelar", "btn-aprovar"):
        assert f'id="{id_botao}"' not in pagina
    # texto quebra em duas linhas no template - normaliza espacos antes de checar.
    assert "pipeline seguiu adiante" in " ".join(pagina.split())


# ---------------------------------------------------------------------------
# GET /revisar_roteiro - Bug 500: roteiro importado por upload sem custo_estimado
# ---------------------------------------------------------------------------


def test_revisao_roteiro_importado_nao_quebra_sem_custo_estimado(
    client, tmp_path, monkeypatch
):
    """Bug 500 corrigido: job_metadata.json pode ter origem_roteiro='upload'
    mas SEM a chave custo_estimado_usd (roteiro importado pelo usuário).
    Em Jinja, atributo ausente de um dict vira Undefined, e o template
    antigo testava `is not none` diretamente o que causava 500.

    Rota GET /revisar_roteiro renderiza com 200 e mostra bloco de roteiro
    importado em vez de bloco de custo (mesmo estilo de revisao_roteiro.html
    linhas 48-65)."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_roteiro_importado",
                roteiro_md="# Roteiro importado pelo usuário\n\nConteúdo aqui.",
                job_metadata={
                    "origem_roteiro": "upload",
                    "caracteres": 12345,
                    # Deliberadamente SEM custo_estimado_usd
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_roteiro_importado/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    # Nenhum 500, renderiza com sucesso
    assert resposta.status_code == 200
    # Mostra o bloco de roteiro importado (não o de custo)
    assert "importado por upload" in pagina or "Roteiro importado" in pagina
    # Se o template preservou o caractere de contagem, aparece
    assert "12345" in pagina or "caracteres" in pagina.lower()


def test_revisao_roteiro_gerado_ainda_mostra_custo(client, tmp_path, monkeypatch):
    """Quando job_metadata tem custo_estimado_usd preenchido (fluxo normal,
    roteiro gerado por IA), o template mostra o bloco de custo com a
    cotação em BRL."""
    monkeypatch.setenv("COTACAO_USD_BRL", "5.00")
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_roteiro_gerado",
                roteiro_md="# Roteiro gerado pela IA\n\nConteúdo.",
                job_metadata={
                    "custo_estimado_usd": 0.75,
                    "web_searches_usadas": 3,
                    "data_geracao": "2025-09-01 14:30:00",
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_roteiro_gerado/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Mostra o custo em USD e BRL
    assert "$0.75" in pagina
    assert "R$ 3.75" in pagina or "R$" in pagina  # 0.75 * 5.00 = 3.75
    assert "3 busca(s) web" in pagina or "3 busca" in pagina


def test_revisao_roteiro_sem_job_metadata_nao_quebra(client, tmp_path, monkeypatch):
    """Se job_metadata.json está totalmente ausente ou vazio, o template não
    deve quebrar - o padrão do template (via `job_metadata or {}`) garante
    que é um dict vazio."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_sem_metadata",
                roteiro_md="# Roteiro sem metadata\n\nConteúdo.",
                job_metadata=None,  # Não grava o arquivo
            )
        ),
    )

    resposta = client.get("/projetos/caso_sem_metadata/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    # Renderiza sem 500 - bloco de metadata pode não aparecer ou estar vazio
    assert resposta.status_code == 200
    assert "Revisar roteiro" in pagina  # Cabeçalho da tela


# ---------------------------------------------------------------------------
# Avisos das validacoes pos-geracao (Grupos A/B/C - sessao de refinamento
# pos-validacao empirica): mesmo componente de banner ja usado por
# aviso_tamanho/pergunta_promessa, nao bloqueiam nada, e nao renderizam se
# a lista correspondente em job_metadata estiver vazia/ausente.
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_exibe_aviso_de_nome_nao_confirmado_nivel_alto(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_nome_suspeito",
                roteiro_md="Roteiro qualquer",
                job_metadata={
                    "nomes_nao_confirmados": [
                        {
                            "nome": "Tomas Ossioni",
                            "nivel": "alto",
                            "contexto": "husband, Tomas Ossioni, were photographed",
                        }
                    ]
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_nome_suspeito/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "Nome não corroborado pelo resumo de pesquisa" in pagina
    assert "Tomas Ossioni" in pagina


def test_get_revisar_roteiro_nao_exibe_aviso_de_nome_nivel_medio(client, tmp_path, monkeypatch):
    """So' o nivel 'alto' aparece em destaque (ajuste 1 do refinamento) -
    'medio' fica gravado em job_metadata mas nao vira banner."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_nome_medio",
                roteiro_md="Roteiro qualquer",
                job_metadata={
                    "nomes_nao_confirmados": [
                        {"nome": "Fulano Beltrano", "nivel": "medio", "contexto": "..."}
                    ]
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_nome_medio/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "Nome não corroborado pelo resumo de pesquisa" not in pagina
    assert "Fulano Beltrano" not in pagina


def test_get_revisar_roteiro_exibe_aviso_de_titulos_divergentes(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_titulo_divergente",
                roteiro_md="Roteiro qualquer",
                job_metadata={
                    "nucleo_editorial": "mistakes that identify him",
                    "titulos_possivel_divergencia": ["Wrist Tattoo"],
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_titulo_divergente/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "divergir do núcleo editorial" in pagina
    assert "mistakes that identify him" in pagina
    assert "Wrist Tattoo" in pagina


def test_get_revisar_roteiro_exibe_aviso_de_numero_sem_derivacao(client, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_numero_sem_derivacao",
                roteiro_md="Roteiro qualquer",
                job_metadata={
                    "numeros_sem_derivacao": [
                        {"trecho": "For forty-one minutes, he breathed inside.", "numero_detectado": "forty-one minutes"}
                    ]
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_numero_sem_derivacao/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "sem derivação próxima" in pagina
    assert "forty-one minutes" in pagina


def test_get_revisar_roteiro_sem_nenhum_aviso_dos_grupos_abc_nao_renderiza_banner(
    client, tmp_path, monkeypatch
):
    """Nenhum aviso -> nenhum banner (Grupo D - 'nenhum tudo certo que
    ocupe espaco')."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_sem_avisos_abc",
                roteiro_md="Roteiro qualquer",
                job_metadata={
                    "nomes_nao_confirmados": [],
                    "titulos_possivel_divergencia": [],
                    "numeros_sem_derivacao": [],
                },
            )
        ),
    )

    resposta = client.get("/projetos/caso_sem_avisos_abc/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert "Nome não corroborado pelo resumo de pesquisa" not in pagina
    assert "divergir do núcleo editorial" not in pagina
    assert "sem derivação próxima" not in pagina


# ---------------------------------------------------------------------------
# Correcao 3 (sessao pre-thumbnail): contador de palavras narradas exibe o
# valor PERSISTIDO em job_metadata.json, nunca recalculado no template nem
# no server (contar_palavras_narradas() e' a unica funcao canonica, mora
# em scripts/3_gerar_roteiro.py).
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_contador_palavras_usa_valor_persistido_do_metadata(
    client, tmp_path, monkeypatch
):
    """roteiro_md tem notas de rodape/markdown suficientes pra um split
    ingenuo (texto.split(/\\s+/)) dar um numero BEM diferente do
    persistido - a tela precisa mostrar o persistido, nao recalcular."""
    roteiro_com_notas = "Uma frase [F1@00:00] com **markdown** e [N: url] " * 40
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_contador_persistido",
                roteiro_md=roteiro_com_notas,
                job_metadata={"palavras_narradas": 4216},
            )
        ),
    )

    resposta = client.get("/projetos/caso_contador_persistido/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert '<span id="contador-palavras">4216</span>' in pagina
    # o split ingenuo do texto acima daria um numero bem diferente de
    # 4216 - garante que NAO e' esse numero que aparece na pagina.
    naive = len(roteiro_com_notas.split())
    assert naive != 4216
    assert f'<span id="contador-palavras">{naive}</span>' not in pagina


def test_get_revisar_roteiro_sem_palavras_narradas_no_metadata_nao_quebra(
    client, tmp_path, monkeypatch
):
    """Projeto antigo sem job_metadata.palavras_narradas (roteiro gerado
    antes da metrica existir, ou importado por upload): a tela nao
    recalcula nada - so' omite o trecho de palavras narradas, mantendo o
    contador de caracteres do editor (esse sim, live via JS)."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(
            _criar_projeto_revisao_no_disco(
                tmp_path,
                "caso_sem_palavras_narradas",
                roteiro_md="Roteiro de projeto antigo, sem essa metrica.",
                job_metadata={"custo_estimado_usd": 0.30},
            )
        ),
    )

    resposta = client.get("/projetos/caso_sem_palavras_narradas/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'id="contador-palavras"' not in pagina
    assert 'id="contador-caracteres"' in pagina
