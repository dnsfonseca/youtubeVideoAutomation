"""Testes da feature de "fontes separadas" no formulario de Novo projeto
(CLAUDE.md secao 5.7.1-bis): modo "separado" distingue fontes de
transcricao de fontes visuais, com opcao de upload de imagens/videos como
b-roll proprio.

Cobre:
- Funcoes puras de server.py: _processar_pares_link_marca, _validar_uploads,
  _salvar_uploads.
- POST /novo em modo "separado": criacao de entrada/fontes_tipo_uso.json e
  entrada/fontes_upload.json, validacoes (transcricao vazia, visual vazio,
  upload invalido), e retrocompatibilidade do modo unificado (continua
  gravando so' "ambos", sem fontes_upload.json).

O subprocess da Etapa 1 e' sempre mockado (nunca chama yt-dlp de verdade -
CLAUDE.md secao 8). Uploads no teste usam io.BytesIO com poucos bytes reais
- o teste de tamanho excedido usa um objeto FileStorage-like feito a mao
para nunca alocar 500MB de verdade em memoria.
"""

import io
import json

import server
from server import (
    _fontes_baixadas_com_origem,
    _mesclar_fontes_separadas,
    _processar_pares_link_marca,
    _salvar_uploads,
    _validar_uploads,
)


def _popen_fake(linhas=None, returncode=0):
    linhas = linhas or []

    class _ProcessoFake:
        def __init__(self):
            self.stdout = iter(linhas)
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        return _ProcessoFake()

    return _fake


# ---------------------------------------------------------------------------
# _processar_pares_link_marca (funcao pura)
# ---------------------------------------------------------------------------


def test_processar_pares_link_marca_ignora_linha_vazia_sem_desalinhar():
    links, marcas, erro = _processar_pares_link_marca(
        ["https://youtube.com/watch?v=abc", "", "https://youtube.com/watch?v=def"],
        ["superior_direito", "nenhuma", "banner_inferior"],
    )

    assert erro is None
    assert links == ["https://youtube.com/watch?v=abc", "https://youtube.com/watch?v=def"]
    assert marcas == ["superior_direito", "banner_inferior"]


def test_processar_pares_link_marca_tamanhos_diferentes_retorna_erro():
    links, marcas, erro = _processar_pares_link_marca(
        ["https://youtube.com/watch?v=abc", "https://youtube.com/watch?v=def"],
        ["nenhuma"],
    )

    assert links == []
    assert marcas == []
    assert erro is not None


def test_processar_pares_link_marca_sem_marcas_usa_nenhuma_para_todos():
    links, marcas, erro = _processar_pares_link_marca(["https://youtube.com/watch?v=abc"], [])

    assert erro is None
    assert links == ["https://youtube.com/watch?v=abc"]
    assert marcas == ["nenhuma"]


def test_processar_pares_link_marca_lista_vazia_retorna_tudo_vazio():
    links, marcas, erro = _processar_pares_link_marca([], [])

    assert erro is None
    assert links == []
    assert marcas == []


# ---------------------------------------------------------------------------
# _mesclar_fontes_separadas (dedup de URL repetida entre as duas listas -
# achado real em nancyGuthrieProject03: mesma URL em transcricao e visual
# baixava o mesmo video duas vezes)
# ---------------------------------------------------------------------------


def test_mesclar_fontes_url_repetida_entre_listas_vira_uma_fonte_ambos():
    links, marcas, tipo_uso = _mesclar_fontes_separadas(
        links_transcricao=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        marcas_transcricao=["nenhuma"],
        links_visual=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        marcas_visual=["nenhuma"],
    )

    assert links == ["https://www.youtube.com/watch?v=aaaaaaaaaaa"]
    assert tipo_uso == ["ambos"]
    assert marcas == ["nenhuma"]


def test_mesclar_fontes_formatos_diferentes_da_mesma_url_sao_reconhecidos():
    """youtu.be/<id> na lista de transcricao e youtube.com/watch?v=<id> na
    lista visual sao o MESMO video - tem que fundir mesmo com formato
    diferente."""
    links, marcas, tipo_uso = _mesclar_fontes_separadas(
        links_transcricao=["https://youtu.be/aaaaaaaaaaa"],
        marcas_transcricao=["nenhuma"],
        links_visual=["https://www.youtube.com/watch?v=aaaaaaaaaaa&t=30s"],
        marcas_visual=["nenhuma"],
    )

    assert links == ["https://youtu.be/aaaaaaaaaaa"]
    assert tipo_uso == ["ambos"]


def test_mesclar_fontes_urls_diferentes_continuam_separadas():
    links, marcas, tipo_uso = _mesclar_fontes_separadas(
        links_transcricao=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        marcas_transcricao=["nenhuma"],
        links_visual=["https://www.youtube.com/watch?v=bbbbbbbbbbb"],
        marcas_visual=["nenhuma"],
    )

    assert links == [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
    ]
    assert tipo_uso == ["transcricao", "visual"]


def test_mesclar_fontes_preserva_marca_dagua_real_da_fonte_visual():
    """A entrada de transcricao veio sem marca ("nenhuma"); a entrada
    visual da mesma URL tinha marca real - a fusao nao pode perder essa
    marca d'agua so' porque a transcricao "chegou primeiro"."""
    links, marcas, tipo_uso = _mesclar_fontes_separadas(
        links_transcricao=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        marcas_transcricao=["nenhuma"],
        links_visual=["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
        marcas_visual=["superior_direito"],
    )

    assert marcas == ["superior_direito"]
    assert tipo_uso == ["ambos"]


def test_mesclar_fontes_duplicata_dentro_da_mesma_lista_nao_vira_ambos():
    """Duas ocorrencias da mesma URL dentro da lista de VISUAL (nao entre
    listas diferentes) devem deduplicar sem promover para "ambos" - o
    proposito continua sendo so' visual."""
    links, marcas, tipo_uso = _mesclar_fontes_separadas(
        links_transcricao=[],
        marcas_transcricao=[],
        links_visual=[
            "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "https://youtu.be/aaaaaaaaaaa",
        ],
        marcas_visual=["nenhuma", "nenhuma"],
    )

    assert links == ["https://www.youtube.com/watch?v=aaaaaaaaaaa"]
    assert tipo_uso == ["visual"]


def test_mesclar_fontes_lista_vazia_retorna_tudo_vazio():
    links, marcas, tipo_uso = _mesclar_fontes_separadas([], [], [], [])
    assert links == marcas == tipo_uso == []


# ---------------------------------------------------------------------------
# _validar_uploads (funcao pura, sem tocar disco)
# ---------------------------------------------------------------------------


class _FileStorageFake:
    """Duck-type minimo de werkzeug.FileStorage - so' o que
    _validar_uploads/_salvar_uploads realmente usam (filename, seek, tell,
    save). Permite simular um arquivo de 500MB+ sem alocar memoria real."""

    def __init__(self, filename, tamanho_bytes):
        self.filename = filename
        self._tamanho = tamanho_bytes
        self._posicao = 0
        self.salvo_em = None

    def seek(self, offset, whence=0):
        if whence == 2:  # SEEK_END
            self._posicao = self._tamanho + offset
        else:
            self._posicao = offset

    def tell(self):
        return self._posicao

    def save(self, caminho):
        self.salvo_em = caminho


def test_validar_uploads_aceita_arquivos_validos():
    arquivos = [
        _FileStorageFake("foto.jpg", 1024),
        _FileStorageFake("clipe.mp4", 2048),
    ]

    validados, erro = _validar_uploads(arquivos)

    assert erro is None
    assert len(validados) == 2
    assert validados[0][2] == "imagem"
    assert validados[1][2] == "video"


def test_validar_uploads_rejeita_extensao_invalida():
    arquivos = [_FileStorageFake("script.exe", 1024)]

    validados, erro = _validar_uploads(arquivos)

    assert validados == []
    assert erro is not None
    assert "extensao" in erro.lower() or "extensão" in erro.lower()


def test_validar_uploads_rejeita_tamanho_excedido():
    """501MB simulados via FileStorageFake - nunca aloca 500MB reais."""
    arquivos = [_FileStorageFake("clipe_gigante.mp4", 501 * 1024 * 1024)]

    validados, erro = _validar_uploads(arquivos)

    assert validados == []
    assert erro is not None
    assert "500" in erro


def test_validar_uploads_ignora_entradas_sem_filename():
    """Um <input type=file multiple> sem nenhum arquivo selecionado ainda
    manda uma entrada FileStorage vazia (filename == "") - tem que ser
    ignorada, nao rejeitada como extensao invalida."""
    arquivos = [_FileStorageFake("", 0)]

    validados, erro = _validar_uploads(arquivos)

    assert validados == []
    assert erro is None


# ---------------------------------------------------------------------------
# _salvar_uploads (escreve em disco - sanitizacao de nome, numeracao)
# ---------------------------------------------------------------------------


def test_salvar_uploads_numera_sequencialmente_a_partir_do_indice_inicial(tmp_path):
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    uploads_validados, _ = _validar_uploads(
        [_FileStorageFake("a.jpg", 100), _FileStorageFake("b.mp4", 100)]
    )

    entradas = _salvar_uploads(pasta_projeto, uploads_validados, indice_inicial=3)

    assert [e["id"] for e in entradas] == ["fonte03", "fonte04"]
    assert entradas[0]["arquivo"] == "fonte03.jpg"
    assert entradas[1]["arquivo"] == "fonte04.mp4"
    assert entradas[0]["tipo"] == "imagem"
    assert entradas[1]["tipo"] == "video"
    assert entradas[0]["titulo"] == "a.jpg"


def test_salvar_uploads_sanitiza_nome_contra_path_traversal(tmp_path):
    """secure_filename() remove componentes de path - o arquivo tem que
    cair dentro de fontes/, nunca fora, mesmo com um filename malicioso."""
    pasta_projeto = tmp_path / "projeto"
    pasta_projeto.mkdir()
    uploads_validados, erro = _validar_uploads(
        [_FileStorageFake("../../../etc/passwd.mp4", 100)]
    )
    assert erro is None

    entradas = _salvar_uploads(pasta_projeto, uploads_validados, indice_inicial=1)

    assert entradas[0]["arquivo"] == "fonte01.mp4"
    arquivo_fake = uploads_validados[0][0]
    caminho_salvo = str(arquivo_fake.salvo_em)
    assert ".." not in caminho_salvo
    assert caminho_salvo.startswith(str(pasta_projeto / "fontes"))


# ---------------------------------------------------------------------------
# POST /novo - modo separado (integracao via Flask test client)
# ---------------------------------------------------------------------------


def test_post_novo_modo_separado_cria_fontes_tipo_uso_ordenado(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_separado",
            "perfil": "truecrime",
            "modo_fontes": "separado",
            "links_transcricao[]": ["https://youtube.com/watch?v=t1", "https://youtube.com/watch?v=t2"],
            "marcas_dagua_transcricao[]": ["nenhuma", "nenhuma"],
            "links_visual[]": ["https://youtube.com/watch?v=v1"],
            "marcas_dagua_visual[]": ["superior_direito"],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_separado"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_separado"
    links_gravados = (pasta_projeto / "entrada" / "links.txt").read_text(encoding="utf-8").splitlines()
    assert links_gravados == [
        "https://youtube.com/watch?v=t1",
        "https://youtube.com/watch?v=t2",
        "https://youtube.com/watch?v=v1",
    ]

    tipo_uso = json.loads((pasta_projeto / "entrada" / "fontes_tipo_uso.json").read_text(encoding="utf-8"))
    assert tipo_uso == {
        "fonte01": "transcricao",
        "fonte02": "transcricao",
        "fonte03": "visual",
    }

    marcas = json.loads((pasta_projeto / "entrada" / "marcas_dagua.json").read_text(encoding="utf-8"))
    assert marcas["fonte03"] == "superior_direito"

    assert not (pasta_projeto / "entrada" / "fontes_upload.json").exists()


def test_post_novo_modo_separado_url_repetida_nas_duas_listas_baixa_uma_vez(client, tmp_path, monkeypatch):
    """Achado real (nancyGuthrieProject03): a mesma URL colada em
    transcricao E visual nao pode gerar duas fontes/dois downloads - vira
    UMA fonte com tipo_uso "ambos"."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_url_repetida",
            "perfil": "truecrime",
            "modo_fontes": "separado",
            "links_transcricao[]": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"],
            "marcas_dagua_transcricao[]": ["nenhuma"],
            "links_visual[]": ["https://youtu.be/aaaaaaaaaaa"],
            "marcas_dagua_visual[]": ["superior_direito"],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_url_repetida"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_url_repetida"
    links_gravados = (pasta_projeto / "entrada" / "links.txt").read_text(encoding="utf-8").splitlines()
    assert links_gravados == ["https://www.youtube.com/watch?v=aaaaaaaaaaa"]

    tipo_uso = json.loads((pasta_projeto / "entrada" / "fontes_tipo_uso.json").read_text(encoding="utf-8"))
    assert tipo_uso == {"fonte01": "ambos"}

    marcas = json.loads((pasta_projeto / "entrada" / "marcas_dagua.json").read_text(encoding="utf-8"))
    assert marcas["fonte01"] == "superior_direito"


def test_post_novo_modo_separado_com_upload_cria_fonte_upload(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_upload",
            "perfil": "truecrime",
            "modo_fontes": "separado",
            "links_transcricao[]": ["https://youtube.com/watch?v=t1"],
            "marcas_dagua_transcricao[]": ["nenhuma"],
            "uploads[]": (io.BytesIO(b"fake-image-bytes"), "still.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_upload"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_upload"
    assert (pasta_projeto / "fontes" / "fonte02.jpg").exists()

    fontes_upload = json.loads((pasta_projeto / "entrada" / "fontes_upload.json").read_text(encoding="utf-8"))
    assert fontes_upload == [
        {"id": "fonte02", "arquivo": "fonte02.jpg", "tipo": "imagem", "titulo": "still.jpg"}
    ]

    tipo_uso = json.loads((pasta_projeto / "entrada" / "fontes_tipo_uso.json").read_text(encoding="utf-8"))
    assert tipo_uso["fonte02"] == "visual"


def test_post_novo_modo_separado_sem_transcricao_retorna_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sem_transcricao",
            "perfil": "truecrime",
            "modo_fontes": "separado",
            "links_visual[]": ["https://youtube.com/watch?v=v1"],
            "marcas_dagua_visual[]": ["nenhuma"],
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "caso_sem_transcricao" not in server.jobs


def test_post_novo_modo_separado_sem_visual_e_sem_upload_retorna_erro(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sem_visual",
            "perfil": "truecrime",
            "modo_fontes": "separado",
            "links_transcricao[]": ["https://youtube.com/watch?v=t1"],
            "marcas_dagua_transcricao[]": ["nenhuma"],
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "caso_sem_visual" not in server.jobs


def test_post_novo_modo_separado_upload_invalido_nao_cria_projeto(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_upload_invalido",
            "perfil": "truecrime",
            "modo_fontes": "separado",
            "links_transcricao[]": ["https://youtube.com/watch?v=t1"],
            "marcas_dagua_transcricao[]": ["nenhuma"],
            "uploads[]": (io.BytesIO(b"conteudo"), "virus.exe"),
        },
        content_type="multipart/form-data",
    )
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina
    assert "caso_upload_invalido" not in server.jobs
    projetos_dir = tmp_path / "projetos"
    assert not (projetos_dir / "caso_upload_invalido").exists()


def test_post_novo_modo_fontes_invalido_retorna_400(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_modo_invalido",
            "perfil": "truecrime",
            "modo_fontes": "hibrido",
            "links[]": ["https://youtube.com/watch?v=abc"],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 400
    assert "caso_modo_invalido" not in server.jobs


# ---------------------------------------------------------------------------
# POST /novo - modo unificado (retrocompatibilidade da feature)
# ---------------------------------------------------------------------------


def test_post_novo_modo_unificado_grava_tipo_uso_ambos_para_todos(client, tmp_path, monkeypatch):
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_unificado_padrao",
            "perfil": "truecrime",
            "links[]": ["https://youtube.com/watch?v=abc", "https://youtube.com/watch?v=def"],
            "marcas_dagua[]": ["nenhuma", "nenhuma"],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    server._threads["caso_unificado_padrao"].join(timeout=2)

    pasta_projeto = projetos_dir / "caso_unificado_padrao"
    tipo_uso = json.loads((pasta_projeto / "entrada" / "fontes_tipo_uso.json").read_text(encoding="utf-8"))
    assert tipo_uso == {"fonte01": "ambos", "fonte02": "ambos"}
    assert not (pasta_projeto / "entrada" / "fontes_upload.json").exists()


# ---------------------------------------------------------------------------
# Nao-regressao: projeto ja existente com fontes duplicadas em disco (antes
# desta correcao) continua funcionando sem reprocessamento - o dedup so'
# roda na CRIACAO de um projeto novo, nunca relendo um manifest ja gravado.
# Reproduz em miniatura o estado real de nancyGuthrieProject03: fonte01
# (transcricao) e fonte03 (visual) sao a MESMA URL, baixadas duas vezes
# antes desta correcao existir.
# ---------------------------------------------------------------------------


def test_projeto_existente_com_duplicata_em_disco_continua_exibindo_as_mesmas_fontes(tmp_path):
    pasta_projeto = tmp_path / "nancyGuthrieProject03"
    (pasta_projeto / "fontes").mkdir(parents=True)
    (pasta_projeto / "entrada").mkdir()

    manifest = {
        "fontes": [
            {
                "id": "fonte01",
                "arquivo": "fonte01.mp4",
                "url_original": "https://www.youtube.com/watch?v=xW5A4ffM34k",
                "titulo": "video 1",
                "duracao_s": 2323,
                "sucesso": True,
                "origem": "youtube",
            },
            {
                "id": "fonte02",
                "arquivo": "fonte02.mp4",
                "url_original": "https://www.youtube.com/watch?v=vvSMVEwnMRU",
                "titulo": "video 2",
                "duracao_s": 2660,
                "sucesso": True,
                "origem": "youtube",
            },
            {
                "id": "fonte03",
                "arquivo": "fonte03.mp4",
                "url_original": "https://www.youtube.com/watch?v=xW5A4ffM34k",
                "titulo": "video 1",
                "duracao_s": 2323,
                "sucesso": True,
                "origem": "youtube",
            },
        ],
        "sucesso": True,
    }
    (pasta_projeto / "fontes" / "manifest_fontes.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (pasta_projeto / "entrada" / "fontes_tipo_uso.json").write_text(
        json.dumps({"fonte01": "transcricao", "fonte02": "visual", "fonte03": "visual"}),
        encoding="utf-8",
    )
    indice_clipes = {
        "clipes": [
            {"arquivo": "clipe_0001.mp4", "fonte_original": "fonte02"},
            {"arquivo": "clipe_0002.mp4", "fonte_original": "fonte03"},
        ]
    }
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(indice_clipes, ensure_ascii=False), encoding="utf-8"
    )

    fontes_baixadas, mensagem = _fontes_baixadas_com_origem(pasta_projeto)

    # As 3 fontes continuam aparecendo separadas (nao ha migracao
    # retroativa) - exatamente o estado gravado em disco antes da correcao.
    assert mensagem is None
    assert [f["id"] for f in fontes_baixadas] == ["fonte01", "fonte02", "fonte03"]
    assert fontes_baixadas[0]["tipo_uso"] == "transcricao"
    assert fontes_baixadas[2]["tipo_uso"] == "visual"
    assert fontes_baixadas[0]["url"] == fontes_baixadas[2]["url"]

    # clipes/indice.json continua apontando para os arquivos corretos -
    # nenhum identificador de fonte mudou de significado.
    indice_lido = json.loads((pasta_projeto / "clipes" / "indice.json").read_text(encoding="utf-8"))
    assert indice_lido["clipes"][0]["fonte_original"] == "fonte02"
    assert indice_lido["clipes"][1]["fonte_original"] == "fonte03"


def test_get_novo_renderiza_toggle_de_modo_de_fontes(client):
    resposta = client.get("/novo")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'name="modo_fontes"' in pagina
    assert 'id="secao-fontes-separadas"' in pagina
    assert 'id="lista-transcricao"' in pagina
    assert 'id="lista-visual-links"' in pagina
    assert 'id="upload-input"' in pagina
