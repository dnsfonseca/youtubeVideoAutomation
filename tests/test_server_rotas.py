"""Testes das rotas do esqueleto Flask (server.py).

Escopo desta etapa: fundação do app (sem autenticação — ferramenta local,
ver CLAUDE.md seção 12 —, /ajustes, listagem de projetos no disco).
Nenhuma lógica de pipeline (etapas 5.1-5.11) existe ainda, então não há
teste para isso aqui — ver CLAUDE.md seções 3 e 8.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

import server
from server import CAMPOS_AJUSTES, MODELOS_ANTHROPIC_SUPORTADOS, _ler_versao


# ---------------------------------------------------------------------------
# Acesso as rotas (sem autenticacao)
# ---------------------------------------------------------------------------


def test_home_acessivel_sem_autenticacao(client):
    resposta = client.get("/")

    assert resposta.status_code == 200


def test_ajustes_acessivel_sem_autenticacao(client):
    resposta = client.get("/ajustes")

    assert resposta.status_code == 200


# ---------------------------------------------------------------------------
# POST /ajustes
# ---------------------------------------------------------------------------


def test_post_ajustes_salva_todos_os_campos_no_env(client, app, tmp_path):
    novos_valores = {
        "PROJETOS_DIR": str(tmp_path / "projetos"),
        "ANTHROPIC_API_KEY": "chave-fake-anthropic-000",
        "ANTHROPIC_MODEL": "claude-opus-5",
        "YOUTUBE_API_KEY": "chave-fake-youtube-000",
        "IDIOMA_ROTEIRO": "pt-BR",
        "WHISPER_MODEL": "medium",
        "KEN_BURNS": "true",
        "CLIPE_DURACAO_MIN_S": "6",
        "CLIPE_DURACAO_MAX_S": "10",
        "TTS_PROVEDOR_PADRAO": "elevenlabs",
        "TTS_VOZ_PADRAO": "voz-fake-001",
        "GOOGLE_TTS_API_KEY": "chave-fake-google-tts-000",
        "DARKPLANNER_API_KEY": "chave-fake-darkplanner-000",
        "ELEVENLABS_API_KEY": "chave-fake-elevenlabs-000",
        "OPENAI_API_KEY": "chave-fake-openai-000",
        "AZURE_TTS_KEY": "chave-fake-azure-000",
        "AZURE_TTS_REGION": "eastus",
        "LEGENDA_FONTE": "Impact",
        "LEGENDA_TAMANHO": "72",
        "LEGENDA_POSICAO": "meio-baixo",
        "LEGENDA_KARAOKE_ATIVO": "true",
        "LEGENDA_DESTAQUE_COR_NOME": "verde",
        "MUSICA_VOLUME_BASE": "0.18",
        "WEB_SEARCH_MAX": "2",
        "COTACAO_USD_BRL": "5.20",
        "GERAR_THUMBNAIL_PADRAO": "true",
        "MARCA_DAGUA_CANAL_POSICAO": "superior_esquerdo",
    }

    # Regressao: se um campo novo for adicionado a CAMPOS_AJUSTES sem
    # entrar aqui, este teste falha em vez de passar "por acidente".
    assert set(novos_valores.keys()) == set(CAMPOS_AJUSTES)

    resposta = client.post("/ajustes", data=novos_valores)

    assert resposta.status_code == 200
    assert "Ajustes salvos" in resposta.get_data(as_text=True)

    valores_gravados = dotenv_values(app.config["ENV_PATH"])
    for campo, valor_esperado in novos_valores.items():
        assert valores_gravados[campo] == valor_esperado


def test_post_ajustes_reflete_valores_atualizados_no_formulario(client, tmp_path):
    resposta = client.post(
        "/ajustes",
        data={
            "PROJETOS_DIR": str(tmp_path / "broll"),
            "ANTHROPIC_API_KEY": "",
            "YOUTUBE_API_KEY": "",
            "IDIOMA_ROTEIRO": "es",
            "WHISPER_MODEL": "small",
        },
    )

    pagina = resposta.get_data(as_text=True)
    assert str(tmp_path / "broll") in pagina
    # value="es" sozinho apareceria sempre (é uma das 5 opções fixas do
    # select); o que importa é que ela venha marcada como "selected".
    assert 'value="es" selected' in pagina
    assert 'value="small" selected' in pagina


def test_post_ajustes_com_campo_ausente_grava_string_vazia(client, app, tmp_path):
    """Se o form vier sem um campo esperado, request.form.get(campo, "")
    grava string vazia em vez de levantar erro. Documentando o
    comportamento atual, não um requisito de negócio."""
    resposta = client.post(
        "/ajustes",
        data={
            "PROJETOS_DIR": str(tmp_path / "broll"),
            # ANTHROPIC_API_KEY omitido de proposito
            "IDIOMA_ROTEIRO": "en-US",
            "WHISPER_MODEL": "medium",
        },
    )

    assert resposta.status_code == 200
    valores_gravados = dotenv_values(app.config["ENV_PATH"])
    assert valores_gravados["ANTHROPIC_API_KEY"] == ""


# ---------------------------------------------------------------------------
# GET / — listagem de projetos a partir do disco
#
# Uma subpasta de PROJETOS_DIR só é reconhecida como projeto do Broll
# Foundry se tiver um marcador característico dentro: entrada/links.txt OU
# job.json na raiz da pasta (ver server.py MARCADORES_PROJETO). Sem isso,
# apontar PROJETOS_DIR para uma pasta com outras coisas dentro listaria
# qualquer subpasta como se fosse projeto.
# ---------------------------------------------------------------------------


def test_home_lista_pasta_com_entrada_links_txt(criar_app, tmp_path):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    caso = projetos_dir / "caso_maria"
    (caso / "entrada").mkdir(parents=True)
    (caso / "entrada" / "links.txt").write_text("https://youtube.com/x\n")

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "caso_maria" in pagina


def test_home_lista_pasta_com_job_json(criar_app, tmp_path):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    caso = projetos_dir / "caso_joao"
    caso.mkdir()
    (caso / "job.json").write_text("{}")

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "caso_joao" in pagina


def test_home_nao_lista_pasta_sem_marcador(criar_app, tmp_path):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    (projetos_dir / "pasta_qualquer").mkdir()

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "pasta_qualquer" not in pagina
    assert "Nenhum projeto encontrado" in pagina


def test_home_nao_lista_arquivo_solto(criar_app, tmp_path):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    (projetos_dir / "arquivo_solto.txt").write_text("nao e uma pasta de projeto")

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "arquivo_solto.txt" not in pagina


def test_home_lista_vazia_quando_projetos_dir_nao_configurado(client):
    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Nenhum projeto encontrado" in pagina


def test_home_lista_vazia_quando_projetos_dir_nao_existe_no_disco(criar_app, tmp_path):
    caminho_inexistente = tmp_path / "esta_pasta_nao_existe"

    app = criar_app(PROJETOS_DIR=str(caminho_inexistente))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Nenhum projeto encontrado" in pagina


def test_home_com_nome_de_projeto_unicode_e_emoji(criar_app, tmp_path):
    """Caso de borda de encoding (CLAUDE.md seção 7): nome de pasta com
    acento e emoji não pode derrubar a renderização da home no Windows."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    nome_projeto = "caso_joão_🔍"
    caso = projetos_dir / nome_projeto
    caso.mkdir()
    (caso / "job.json").write_text("{}")

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")

    assert resposta.status_code == 200
    assert nome_projeto in resposta.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Ordenacao da lista de projetos na home - correcao de UX: a lista era
# ordenada alfabeticamente, escondendo projetos recem-criados no meio dela.
# Agora ordena por data de criacao decrescente (mais recentes primeiro),
# priorizando job.json/data_criacao e caindo para o timestamp do
# filesystem (os.path.getctime) quando o job.json nao existe ou nao tem
# o campo (server.py:_data_criacao_projeto).
# ---------------------------------------------------------------------------


def test_home_ordena_projetos_por_data_criacao_decrescente(criar_app, tmp_path):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()

    definicoes = [
        ("caso_antigo", "2026-01-10T09:00:00"),
        ("caso_intermediario", "2026-05-15T09:00:00"),
        ("caso_recente", "2026-08-20T09:00:00"),
    ]
    for nome, data_criacao in definicoes:
        pasta = projetos_dir / nome
        pasta.mkdir()
        (pasta / "job.json").write_text(
            json.dumps({"nome": nome, "data_criacao": data_criacao}), encoding="utf-8"
        )

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    pos_recente = pagina.index("caso_recente")
    pos_intermediario = pagina.index("caso_intermediario")
    pos_antigo = pagina.index("caso_antigo")
    assert pos_recente < pos_intermediario < pos_antigo


def test_home_projeto_sem_job_json_usa_timestamp_do_filesystem(
    criar_app, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    antigo = projetos_dir / "caso_antigo"
    novo = projetos_dir / "caso_novo"
    for pasta in (antigo, novo):
        (pasta / "entrada").mkdir(parents=True)
        (pasta / "entrada" / "links.txt").write_text("https://youtube.com/x\n")

    timestamps = {
        str(antigo): datetime(2026, 1, 1).timestamp(),
        str(novo): datetime(2026, 6, 1).timestamp(),
    }
    monkeypatch.setattr(server.os.path, "getctime", lambda caminho: timestamps[str(caminho)])

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert pagina.index("caso_novo") < pagina.index("caso_antigo")


def test_home_projeto_com_job_json_sem_data_criacao_usa_timestamp_do_filesystem(
    criar_app, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    antigo = projetos_dir / "caso_antigo"
    novo = projetos_dir / "caso_novo"
    antigo.mkdir()
    novo.mkdir()
    # job.json existe, mas sem o campo data_criacao (formato antigo, ou
    # gravado por algum caminho que nao passou por _criar_pasta_projeto).
    (antigo / "job.json").write_text(json.dumps({"nome": "caso_antigo"}), encoding="utf-8")
    (novo / "job.json").write_text(json.dumps({"nome": "caso_novo"}), encoding="utf-8")

    timestamps = {
        str(antigo): datetime(2026, 1, 1).timestamp(),
        str(novo): datetime(2026, 6, 1).timestamp(),
    }
    monkeypatch.setattr(server.os.path, "getctime", lambda caminho: timestamps[str(caminho)])

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert pagina.index("caso_novo") < pagina.index("caso_antigo")


def test_home_mistura_projetos_com_e_sem_job_json_ordena_corretamente(
    criar_app, tmp_path, monkeypatch
):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()

    com_job = projetos_dir / "caso_com_job"
    com_job.mkdir()
    (com_job / "job.json").write_text(
        json.dumps({"nome": "caso_com_job", "data_criacao": "2026-08-01T10:00:00"}),
        encoding="utf-8",
    )

    sem_job = projetos_dir / "caso_sem_job"
    (sem_job / "entrada").mkdir(parents=True)
    (sem_job / "entrada" / "links.txt").write_text("https://youtube.com/x\n")

    original_getctime = server.os.path.getctime

    def _getctime_fake(caminho):
        if str(caminho) == str(sem_job):
            return datetime(2026, 8, 15).timestamp()
        return original_getctime(caminho)

    monkeypatch.setattr(server.os.path, "getctime", _getctime_fake)

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    # caso_sem_job (15/08, via filesystem) e' mais recente que caso_com_job
    # (01/08, via job.json).
    assert pagina.index("caso_sem_job") < pagina.index("caso_com_job")


def test_home_projetos_dir_existente_mas_vazio_nao_crasha(criar_app, tmp_path):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()

    app = criar_app(PROJETOS_DIR=str(projetos_dir))
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Nenhum projeto encontrado" in pagina


# ---------------------------------------------------------------------------
# _data_criacao_projeto (funcao pura usada por listar_projetos)
# ---------------------------------------------------------------------------


def test_data_criacao_projeto_usa_data_criacao_do_job_json(tmp_path):
    pasta = tmp_path / "caso"
    pasta.mkdir()
    (pasta / "job.json").write_text(
        json.dumps({"data_criacao": "2026-03-05T10:30:00"}), encoding="utf-8"
    )

    resultado = server._data_criacao_projeto(str(pasta))

    assert resultado == datetime(2026, 3, 5, 10, 30, 0)


def test_data_criacao_projeto_cai_para_filesystem_se_job_json_ausente(tmp_path):
    pasta = tmp_path / "caso"
    pasta.mkdir()

    resultado = server._data_criacao_projeto(str(pasta))

    assert resultado is not None
    assert isinstance(resultado, datetime)


def test_data_criacao_projeto_cai_para_filesystem_se_data_criacao_ausente_no_job(tmp_path):
    pasta = tmp_path / "caso"
    pasta.mkdir()
    (pasta / "job.json").write_text(json.dumps({"nome": "caso"}), encoding="utf-8")

    resultado = server._data_criacao_projeto(str(pasta))

    assert resultado is not None


def test_data_criacao_projeto_data_criacao_malformada_cai_para_filesystem(tmp_path):
    pasta = tmp_path / "caso"
    pasta.mkdir()
    (pasta / "job.json").write_text(
        json.dumps({"data_criacao": "nao-e-uma-data-valida"}), encoding="utf-8"
    )

    resultado = server._data_criacao_projeto(str(pasta))

    assert resultado is not None


def test_data_criacao_projeto_retorna_none_se_tudo_falhar(tmp_path, monkeypatch):
    pasta = tmp_path / "caso"
    pasta.mkdir()

    def _getctime_que_falha(caminho):
        raise OSError("falhou ao ler ctime")

    monkeypatch.setattr(server.os.path, "getctime", _getctime_que_falha)

    resultado = server._data_criacao_projeto(str(pasta))

    assert resultado is None


# ---------------------------------------------------------------------------
# GET /sobre — versao lida do VERSION.txt e licenca lida do LICENSE.txt
# (CLAUDE.md secao 16 — preparacao para licenciamento futuro)
# ---------------------------------------------------------------------------


def test_sobre_acessivel_sem_autenticacao(client):
    resposta = client.get("/sobre")

    assert resposta.status_code == 200


def test_sobre_mostra_versao_lida_do_arquivo_real(client):
    """Nao fixa o valor "0.1.0-mvp" no teste — usa _ler_versao() para
    continuar valido se o conteudo do VERSION.txt real mudar depois."""
    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert _ler_versao() in pagina


def test_sobre_mostra_texto_da_licenca_lida_do_arquivo_real(client):
    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    licenca_real = server.LICENSE_PATH.read_text(encoding="utf-8")
    assert licenca_real in pagina


def test_sobre_usa_versao_de_arquivo_fake_via_monkeypatch(client, monkeypatch, tmp_path):
    """Isola o teste do conteudo real de VERSION.txt: sobrescreve
    server.VERSION_PATH para um arquivo temporario com versao inventada."""
    versao_fake = tmp_path / "VERSION.txt"
    versao_fake.write_text("9.9.9-teste\n", encoding="utf-8")
    monkeypatch.setattr(server, "VERSION_PATH", versao_fake)

    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert "9.9.9-teste" in pagina


def test_sobre_usa_licenca_de_arquivo_fake_via_monkeypatch(client, monkeypatch, tmp_path):
    """Idem para LICENSE_PATH — nao depende do texto real do LICENSE.txt,
    inclusive com acento/emoji para pegar problema de encoding no Windows."""
    licenca_fake = tmp_path / "LICENSE.txt"
    texto_fake = "Licenca de teste com acentuação e emoji 📄 — não redistribuir."
    licenca_fake.write_text(texto_fake, encoding="utf-8")
    monkeypatch.setattr(server, "LICENSE_PATH", licenca_fake)

    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert texto_fake in pagina


def test_sobre_com_version_txt_inexistente_nao_quebra(client, monkeypatch, tmp_path):
    """_ler_versao() tem fallback ("desconhecida") quando VERSION_PATH nao
    existe no disco — a rota nao pode levantar erro por causa disso."""
    monkeypatch.setattr(server, "VERSION_PATH", tmp_path / "nao_existe.txt")

    resposta = client.get("/sobre")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "desconhecida" in pagina


def test_sobre_com_license_txt_inexistente_nao_quebra(client, monkeypatch, tmp_path):
    """Rota trata LICENSE_PATH ausente com string vazia, sem levantar erro."""
    monkeypatch.setattr(server, "LICENSE_PATH", tmp_path / "nao_existe.txt")

    resposta = client.get("/sobre")

    assert resposta.status_code == 200


# ---------------------------------------------------------------------------
# GET /verificar_atualizacao — rota stub (CLAUDE.md secao 16)
# ---------------------------------------------------------------------------


def test_verificar_atualizacao_retorna_json_com_as_tres_chaves_esperadas(client):
    resposta = client.get("/verificar_atualizacao")

    assert resposta.status_code == 200
    corpo = resposta.get_json()
    assert set(corpo.keys()) == {"versao_local", "versao_disponivel", "mensagem"}


def test_verificar_atualizacao_versao_local_bate_com_ler_versao(client):
    resposta = client.get("/verificar_atualizacao")
    corpo = resposta.get_json()

    assert corpo["versao_local"] == _ler_versao()


def test_verificar_atualizacao_versao_disponivel_e_none(client):
    resposta = client.get("/verificar_atualizacao")
    corpo = resposta.get_json()

    assert corpo["versao_disponivel"] is None


def test_verificar_atualizacao_mensagem_nao_vazia(client):
    resposta = client.get("/verificar_atualizacao")
    corpo = resposta.get_json()

    assert isinstance(corpo["mensagem"], str) and corpo["mensagem"]


# ---------------------------------------------------------------------------
# Extensoes da tela de ajustes: TTS, estrategia de corte, legendas
# (CLAUDE.md secoes 5.6 e 7 — nenhuma chave de TTS e obrigatoria)
#
# test_post_ajustes_salva_todos_os_campos_no_env ja cobre que TODOS os
# campos de CAMPOS_AJUSTES sao persistidos no .env — os testes abaixo nao
# repetem isso, focam em comportamento observavel especifico.
# ---------------------------------------------------------------------------


def test_get_ajustes_sem_nenhuma_chave_tts_configurada_carrega_normalmente(client):
    """Nenhuma chave de TTS e obrigatoria globalmente (CLAUDE.md secao 5.6)
    — a tela de ajustes tem que carregar mesmo sem ELEVENLABS_API_KEY,
    OPENAI_API_KEY nem AZURE_TTS_KEY no .env."""
    resposta = client.get("/ajustes")

    assert resposta.status_code == 200


def test_post_ajustes_com_provedor_tts_mas_sem_chaves_grava_sem_erro(client, app):
    """Regra de negocio explicita (CLAUDE.md secao 5.6): o usuario pode
    escolher um provedor de TTS padrao sem ter configurado a chave dele
    ainda — a validacao da chave acontece so na hora de gerar o audio de
    um projeto, nao na tela de ajustes."""
    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["TTS_PROVEDOR_PADRAO"] = "openai"
    dados["ELEVENLABS_API_KEY"] = ""
    dados["OPENAI_API_KEY"] = ""
    dados["AZURE_TTS_KEY"] = ""
    dados["AZURE_TTS_REGION"] = ""

    resposta = client.post("/ajustes", data=dados)

    assert resposta.status_code == 200
    assert "Ajustes salvos" in resposta.get_data(as_text=True)
    valores_gravados = dotenv_values(app.config["ENV_PATH"])
    assert valores_gravados["TTS_PROVEDOR_PADRAO"] == "openai"
    assert valores_gravados["OPENAI_API_KEY"] == ""


def test_post_ajustes_reflete_legenda_posicao_selecionada(client):
    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["LEGENDA_POSICAO"] = "meio-baixo"

    resposta = client.post("/ajustes", data=dados)
    pagina = resposta.get_data(as_text=True)

    assert 'value="meio-baixo" selected' in pagina


# ---------------------------------------------------------------------------
# POST /ajustes — validacao de PROJETOS_DIR (scripts/validators.py)
#
# Antes de gravar no .env, a rota normaliza (normalizar_caminho) e valida
# (validar_caminho_projetos) o PROJETOS_DIR recebido. Se a validacao falhar,
# nada e' gravado e o formulario e' re-renderizado com o erro e os valores
# que o usuario tinha acabado de digitar.
# ---------------------------------------------------------------------------


def test_post_ajustes_normaliza_projetos_dir_antes_de_gravar(client, app, tmp_path):
    """Manda PROJETOS_DIR com espacos e aspas envolventes (como o Explorer
    as vezes cola) e confere que o valor gravado no .env ja esta limpo/
    normalizado, nao o texto bruto digitado."""
    pasta = tmp_path / "projetos"
    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["PROJETOS_DIR"] = f'  "{pasta}"  '

    resposta = client.post("/ajustes", data=dados)

    assert resposta.status_code == 200
    valores_gravados = dotenv_values(app.config["ENV_PATH"])
    assert valores_gravados["PROJETOS_DIR"] == str(pasta)


def test_post_ajustes_com_projetos_dir_invalido_nao_grava_e_mostra_erro(client, app):
    """Drive/raiz inexistente ("Z:") assume que essa letra nao esta mapeada
    na maquina que roda o teste — cenario razoavel no Windows de
    desenvolvimento deste projeto (ver CLAUDE.md secao 13)."""
    caminho_invalido = r"Z:\pasta_impossivel_12345\projetos"
    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["PROJETOS_DIR"] = caminho_invalido

    resposta = client.post("/ajustes", data=dados)
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'class="aviso erro"' in pagina

    valores_gravados = dotenv_values(app.config["ENV_PATH"])
    assert valores_gravados.get("PROJETOS_DIR", "") != caminho_invalido


def test_post_ajustes_com_projetos_dir_invalido_mantem_outros_campos_no_formulario(client):
    """Mesmo com o save inteiro falhando por causa do PROJETOS_DIR, os
    outros campos que o usuario tinha preenchido no mesmo POST continuam
    visiveis no formulario re-renderizado — nao volta pros valores antigos
    do .env nem perde o que foi digitado."""
    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["PROJETOS_DIR"] = r"Z:\pasta_impossivel_12345\projetos"
    dados["IDIOMA_ROTEIRO"] = "pt-BR"

    resposta = client.post("/ajustes", data=dados)
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'value="pt-BR" selected' in pagina


def test_post_ajustes_projetos_dir_valido_persiste_e_aparece_pre_preenchido_no_get(client, tmp_path):
    """Regressao: depois de salvar um PROJETOS_DIR valido, uma requisicao
    GET /ajustes separada (nao a resposta do POST) tem que trazer o valor
    pre-preenchido no atributo value do input id="PROJETOS_DIR"."""
    pasta = tmp_path / "projetos_regressao"
    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["PROJETOS_DIR"] = str(pasta)

    resposta_post = client.post("/ajustes", data=dados)
    assert resposta_post.status_code == 200

    resposta_get = client.get("/ajustes")
    pagina = resposta_get.get_data(as_text=True)

    correspondencia = re.search(r'id="PROJETOS_DIR"[^>]*value="([^"]*)"', pagina, re.DOTALL)
    assert correspondencia is not None
    assert correspondencia.group(1) == str(pasta)


# ---------------------------------------------------------------------------
# Banners de robustez (CLAUDE.md secao 18.2) — lib volatil desatualizada
# (dispensavel via cookie) e ffmpeg ausente (nao-dispensavel).
#
# Estes testes usam a fixture `criar_app` diretamente (nao `client`/`app`)
# porque precisam fazer o monkeypatch de server.robustez ANTES de chamar
# criar_app(...) — a checagem de robustez roda uma unica vez dentro de
# create_app(), nao a cada request.
# ---------------------------------------------------------------------------


def test_home_mostra_banner_de_lib_desatualizada_quando_acima_da_janela(criar_app, monkeypatch):
    monkeypatch.setattr(server.robustez, "idade_lib", lambda nome, timeout_s=3: 150)

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert 'class="banner banner-aviso"' in pagina
    assert "yt-dlp" in pagina
    assert "150" in pagina


def test_home_nao_mostra_banner_quando_lib_esta_dentro_da_janela(criar_app, monkeypatch):
    monkeypatch.setattr(server.robustez, "idade_lib", lambda nome, timeout_s=3: 30)

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert 'class="banner banner-aviso"' not in pagina


def test_home_nao_mostra_banner_quando_idade_e_desconhecida(criar_app, monkeypatch):
    """Sem informacao de idade (rede indisponivel, PyPI fora do ar), o
    banner nao alarma o usuario a toa (CLAUDE.md secao 18.2)."""
    monkeypatch.setattr(server.robustez, "idade_lib", lambda nome, timeout_s=3: None)

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert 'class="banner banner-aviso"' not in pagina


def test_home_mostra_banner_vermelho_de_ffmpeg_ausente(criar_app, monkeypatch):
    monkeypatch.setattr(server.robustez, "ffmpeg_disponivel", lambda: False)

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert 'class="banner banner-perigo"' in pagina
    assert "ffmpeg" in pagina


def test_post_banner_dispensar_esconde_banner_de_lib_e_cookie_persiste_entre_requests(
    criar_app, monkeypatch
):
    monkeypatch.setattr(server.robustez, "idade_lib", lambda nome, timeout_s=3: 150)

    app = criar_app()
    client = app.test_client()

    resposta_dispensar = client.post("/banner/dispensar/yt-dlp", follow_redirects=True)
    pagina_apos_dispensar = resposta_dispensar.get_data(as_text=True)

    assert resposta_dispensar.status_code == 200
    assert 'class="banner banner-aviso"' not in pagina_apos_dispensar

    # segunda requisicao GET / separada, mesmo client (mesmo cookie) — o
    # banner dispensado continua ausente.
    resposta_get_normal = client.get("/")
    pagina_get_normal = resposta_get_normal.get_data(as_text=True)

    assert 'class="banner banner-aviso"' not in pagina_get_normal


def test_post_banner_dispensar_retorna_redirect(criar_app, monkeypatch):
    monkeypatch.setattr(server.robustez, "idade_lib", lambda nome, timeout_s=3: 150)

    app = criar_app()
    client = app.test_client()

    resposta = client.post("/banner/dispensar/yt-dlp")

    assert resposta.status_code == 302


def test_banner_de_ffmpeg_ausente_nao_e_dispensavel_via_cookie(criar_app, monkeypatch):
    """Banner de ffmpeg ausente bloqueia o pipeline de verdade — ao
    contrario do banner de lib desatualizada, nao existe rota nem cookie
    que faca ele sumir (CLAUDE.md secao 18.2)."""
    monkeypatch.setattr(server.robustez, "ffmpeg_disponivel", lambda: False)

    app = criar_app()
    client = app.test_client()

    client.post("/banner/dispensar/ffmpeg", follow_redirects=True)
    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert 'class="banner banner-perigo"' in pagina
    assert "ffmpeg" in pagina


# ---------------------------------------------------------------------------
# Deteccao de ambiente NVIDIA/CUDA no boot (CLAUDE.md secao 13/18) - banner
# global persistente + bloco "Ambiente detectado" na tela de Ajustes.
#
# `criar_app` ja isola por padrao com uma GPU compativel via a fixture
# `_ambiente_compativel_padrao` (conftest.py) - os testes abaixo que querem
# o cenario incompativel sobrescrevem `server.ambiente.detectar_gpu`
# explicitamente ANTES de chamar `criar_app(...)`, mesmo padrao usado para
# os banners de robustez.
# ---------------------------------------------------------------------------


def _gpu_incompativel_sem_deteccao():
    return {
        "presente": False,
        "modelo": None,
        "vram_mb": None,
        "driver_version": None,
        "compute_capability": None,
        "cuda_umd_version": None,
        "erro": "nvidia-smi nao encontrado. Driver NVIDIA nao instalado.",
    }


def test_server_carrega_com_ambiente_compativel_sem_banner_nem_crash(criar_app):
    app = criar_app()
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Ambiente incompatível" not in pagina


def test_server_carrega_com_ambiente_incompativel_nao_crasha_e_mostra_banner(
    criar_app, monkeypatch
):
    """CLAUDE.md secao 13/18: ambiente incompativel NAO derruba o boot do
    servidor - o usuario precisa poder abrir Ajustes pra diagnosticar."""
    monkeypatch.setattr(server.ambiente, "detectar_gpu", _gpu_incompativel_sem_deteccao)

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "Ambiente incompatível" in pagina
    assert 'class="banner banner-perigo"' in pagina


def test_banner_de_ambiente_incompativel_aparece_em_todas_as_paginas(criar_app, monkeypatch):
    monkeypatch.setattr(server.ambiente, "detectar_gpu", _gpu_incompativel_sem_deteccao)

    app = criar_app()
    client = app.test_client()

    for rota in ("/", "/ajustes", "/novo", "/sobre"):
        resposta = client.get(rota)
        pagina = resposta.get_data(as_text=True)
        assert "Ambiente incompatível" in pagina, f"banner ausente em {rota}"


def test_ajustes_mostra_bloco_ambiente_compativel(criar_app):
    app = criar_app()
    client = app.test_client()

    resposta = client.get("/ajustes")
    pagina = resposta.get_data(as_text=True)

    assert "Ambiente detectado" in pagina
    assert "NVIDIA GeForce RTX 3070 Ti" in pagina
    assert "8.0 GB" in pagina
    assert "small, medium, large-v3" in pagina
    assert "Recomendado: medium" in pagina


def test_ajustes_mostra_bloco_ambiente_incompativel(criar_app, monkeypatch):
    monkeypatch.setattr(server.ambiente, "detectar_gpu", _gpu_incompativel_sem_deteccao)

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/ajustes")
    pagina = resposta.get_data(as_text=True)

    assert "Ambiente incompatível" in pagina
    assert "Não encontrada" in pagina
    assert "LEIAME.md" in pagina


def test_ajustes_dropdown_whisper_model_filtra_pela_vram_detectada(criar_app, monkeypatch):
    """GPU de 4GB so suporta "small" (CLAUDE.md secao 13) - o dropdown de
    WHISPER_MODEL nao pode oferecer "medium" nem "large-v3" nessa
    maquina."""
    monkeypatch.setattr(
        server.ambiente,
        "detectar_gpu",
        lambda: {
            "presente": True,
            "modelo": "NVIDIA GeForce GTX 1650",
            "vram_mb": 4096,
            "driver_version": "551.23",
            "compute_capability": "7.5",
            "cuda_umd_version": "12.4",
            "erro": None,
        },
    )

    app = criar_app()
    client = app.test_client()

    resposta = client.get("/ajustes")
    pagina = resposta.get_data(as_text=True)

    trecho_select = pagina.split('id="WHISPER_MODEL"')[1].split("</select>")[0]
    assert 'value="small"' in trecho_select
    assert 'value="medium"' not in trecho_select
    assert 'value="large-v3"' not in trecho_select


def test_ajustes_mostra_aviso_amarelo_para_modelo_apertado_na_vram(criar_app, monkeypatch):
    """GPU de 6GB suporta "medium", mas com pouca folga - selecionar
    "medium" mostra o aviso amarelo (ver CLAUDE.md - prompt desta sessao,
    ENTREGA 4)."""
    monkeypatch.setattr(
        server.ambiente,
        "detectar_gpu",
        lambda: {
            "presente": True,
            "modelo": "NVIDIA GeForce RTX 2060",
            "vram_mb": 6144,
            "driver_version": "551.23",
            "compute_capability": "7.5",
            "cuda_umd_version": "12.4",
            "erro": None,
        },
    )

    app = criar_app()
    client = app.test_client()

    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["WHISPER_MODEL"] = "medium"

    resposta = client.post("/ajustes", data=dados)
    pagina = resposta.get_data(as_text=True)

    assert "aviso-amarelo" in pagina
    assert "6GB total" in pagina


def test_ajustes_sem_aviso_amarelo_para_modelo_pequeno_com_folga(criar_app):
    """GPU compativel padrao (8GB) com "small" selecionado tem folga de
    sobra - nenhum aviso amarelo deveria aparecer."""
    app = criar_app()
    client = app.test_client()

    dados = {campo: "" for campo in CAMPOS_AJUSTES}
    dados["WHISPER_MODEL"] = "small"

    resposta = client.post("/ajustes", data=dados)
    pagina = resposta.get_data(as_text=True)

    assert "aviso-amarelo" not in pagina


# Nota (consolidacao Etapa 5/6/7): os testes de GET /projetos/<id>/plano_edicao
# que existiam aqui foram removidos - a rota foi eliminada junto com o
# conceito de "plano de edicao" separado (planejamento e renderizacao agora
# sao uma unica etapa, scripts/5_gerar_clipes.py, sem catalogo de cenas
# intermediario). Ver tests/test_gerar_clipes.py para a cobertura da nova
# Etapa 5.


# ---------------------------------------------------------------------------
# CAMPOS_AJUSTES / MODELOS_ANTHROPIC_SUPORTADOS - reorganizacao de Ajustes
# (CLAUDE.md secao 7): campos religados de legenda/musica, campos novos
# (ANTHROPIC_MODEL, WEB_SEARCH_MAX, COTACAO_USD_BRL, CLIPE_DURACAO_MIN/MAX_S)
# e campos removidos (CURADORIA_SEMANTICA dead setting, GOOGLE_API_KEY/Veo3,
# LEGENDA_COR/CONTORNO_COR/CONTORNO_ESPESSURA/DESTAQUE_PALAVRA fixos agora).
# ---------------------------------------------------------------------------


def test_campos_ajustes_contem_campos_novos():
    esperados = {
        "ANTHROPIC_MODEL",
        "CLIPE_DURACAO_MIN_S",
        "CLIPE_DURACAO_MAX_S",
        "LEGENDA_KARAOKE_ATIVO",
        "LEGENDA_DESTAQUE_COR_NOME",
        "MUSICA_VOLUME_BASE",
        "WEB_SEARCH_MAX",
        "COTACAO_USD_BRL",
    }
    assert esperados.issubset(set(CAMPOS_AJUSTES))


def test_campos_ajustes_nao_contem_campos_removidos():
    removidos = {
        "CURADORIA_SEMANTICA",
        "GOOGLE_API_KEY",
        "LEGENDA_COR",
        "LEGENDA_CONTORNO_COR",
        "LEGENDA_CONTORNO_ESPESSURA",
        "LEGENDA_DESTAQUE_PALAVRA",
        "LEGENDA_DESTAQUE_COR",
    }
    assert removidos.isdisjoint(set(CAMPOS_AJUSTES))


def test_modelos_anthropic_suportados_tem_sonnet_opus_haiku():
    assert MODELOS_ANTHROPIC_SUPORTADOS == ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"]


def test_get_ajustes_renderiza_secao_musica_e_dropdown_modelo(client):
    resposta = client.get("/ajustes")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'id="secao-musica"' in pagina
    assert 'name="MUSICA_VOLUME_BASE"' in pagina
    assert 'name="ANTHROPIC_MODEL"' in pagina
    for modelo in MODELOS_ANTHROPIC_SUPORTADOS:
        assert modelo in pagina


def test_get_ajustes_nao_renderiza_campos_removidos(client):
    resposta = client.get("/ajustes")
    pagina = resposta.get_data(as_text=True)

    assert 'name="CURADORIA_SEMANTICA"' not in pagina
    assert 'name="GOOGLE_API_KEY"' not in pagina
    assert 'name="LEGENDA_COR"' not in pagina
    assert 'name="LEGENDA_CONTORNO_COR"' not in pagina
    assert 'name="LEGENDA_CONTORNO_ESPESSURA"' not in pagina
    assert 'name="LEGENDA_DESTAQUE_PALAVRA"' not in pagina


# ---------------------------------------------------------------------------
# GRUPO D (teste manual pos-Sessao 18) - OPENAI_API_KEY unica, so' na secao
# Thumbnail, e sem o efeito colateral do JS de opacidade da secao TTS.
# ---------------------------------------------------------------------------


def test_ajustes_openai_api_key_aparece_uma_unica_vez(client):
    """So' pode haver UM campo de fato pra OPENAI_API_KEY na pagina - a
    secao TTS tem so' texto referenciando a secao Thumbnail, nunca um
    segundo <input>."""
    pagina = client.get("/ajustes").get_data(as_text=True)

    assert pagina.count('name="OPENAI_API_KEY"') == 1


def test_ajustes_openai_api_key_nao_carrega_classe_tts_chave(client):
    """A armadilha que motivou esta correcao: se o campo movido pra
    Thumbnail mantivesse `class="tts-chave" data-provedor="openai"`, o
    querySelectorAll(".tts-chave") de ajustes.js continuaria escurecendo
    o campo so' porque outro provedor de TTS foi selecionado - mesmo o
    campo estando fisicamente fora da secao TTS. `data-provedor="openai"`
    so' existia pra esse campo (nenhum outro usa esse valor), entao a
    ausencia dele na pagina prova que o campo nao esta mais no grupo
    afetado pelo toggle."""
    pagina = client.get("/ajustes").get_data(as_text=True)

    assert 'data-provedor="openai"' not in pagina


def test_ajustes_openai_api_key_vive_na_secao_thumbnail(client):
    """O campo precisa estar fisicamente dentro de #secao-thumbnail, nao
    apenas ausente de #secao-tts - garante que a mudanca foi mover o
    campo, nao so' apagar a duplicata."""
    pagina = client.get("/ajustes").get_data(as_text=True)

    inicio_thumbnail = pagina.index('id="secao-thumbnail"')
    fim_thumbnail = pagina.index("</details>", inicio_thumbnail)
    secao_thumbnail = pagina[inicio_thumbnail:fim_thumbnail]

    assert 'name="OPENAI_API_KEY"' in secao_thumbnail


def test_ajustes_secao_thumbnail_nunca_tem_campo_tts_chave(client):
    """Selecionar um provedor de TTS (ajustes.js) so' deve afetar
    elementos `.tts-chave` dentro da secao TTS. Provar isso sem executar
    JS de verdade: nenhum elemento dentro de #secao-thumbnail carrega
    essa classe, entao o toggle de opacidade nao tem o que tocar la'."""
    pagina = client.get("/ajustes").get_data(as_text=True)

    inicio_thumbnail = pagina.index('id="secao-thumbnail"')
    fim_thumbnail = pagina.index("</details>", inicio_thumbnail)
    secao_thumbnail = pagina[inicio_thumbnail:fim_thumbnail]

    assert "tts-chave" not in secao_thumbnail


def test_post_ajustes_legenda_fonte_impact_reflete_no_formulario(client, tmp_path):
    resposta = client.post(
        "/ajustes",
        data={
            "PROJETOS_DIR": str(tmp_path / "broll"),
            "LEGENDA_FONTE": "Impact",
            "LEGENDA_TAMANHO": "72",
            "LEGENDA_POSICAO": "meio-baixo",
            "LEGENDA_KARAOKE_ATIVO": "false",
            "LEGENDA_DESTAQUE_COR_NOME": "verde",
            "MUSICA_VOLUME_BASE": "0.30",
        },
    )

    pagina = resposta.get_data(as_text=True)
    assert 'value="Impact" selected' in pagina
    assert 'value="72" selected' in pagina
    assert 'value="meio-baixo" selected' in pagina
    assert 'value="false" selected' in pagina
    assert 'value="verde" selected' in pagina
    assert 'value="0.30"' in pagina


# ---------------------------------------------------------------------------
# .env.example - limpeza de variaveis mortas (CURADORIA_SEMANTICA, Veo3) e
# novas variaveis de legenda/musica (CLAUDE.md secao 7)
# ---------------------------------------------------------------------------


def _ler_env_example():
    caminho = Path(__file__).resolve().parent.parent / ".env.example"
    return caminho.read_text(encoding="utf-8")


def test_env_example_nao_tem_variaveis_mortas():
    conteudo = _ler_env_example()
    linhas_ativas = [
        linha.strip()
        for linha in conteudo.splitlines()
        if linha.strip() and not linha.strip().startswith("#")
    ]
    removidas = (
        "CURADORIA_SEMANTICA=",
        "GOOGLE_API_KEY=",
        "LEGENDA_COR=",
        "LEGENDA_CONTORNO_COR=",
        "LEGENDA_CONTORNO_ESPESSURA=",
        "LEGENDA_DESTAQUE_PALAVRA=",
        "CLIPE_MIN_S=",
        "CLIPE_MAX_S=",
        "CLIPE_TOLERANCIA_S=",
        "ESTRATEGIA_CORTE=",
    )
    for prefixo in removidas:
        assert not any(linha.startswith(prefixo) for linha in linhas_ativas), prefixo


def test_env_example_tem_novas_variaveis_de_legenda_e_musica():
    conteudo = _ler_env_example()
    for prefixo in (
        "MUSICA_VOLUME_BASE=0.18",
        "LEGENDA_FONTE=Poppins Bold",
        "LEGENDA_TAMANHO=64",
        "LEGENDA_POSICAO=baixo",
        "LEGENDA_KARAOKE_ATIVO=true",
        "LEGENDA_DESTAQUE_COR_NOME=amarelo",
    ):
        assert prefixo in conteudo
