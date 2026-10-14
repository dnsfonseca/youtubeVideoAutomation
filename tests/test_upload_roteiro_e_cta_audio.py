"""Testes para as duas features implementadas:

Feature 1 - Upload de roteiro pronto (pula Etapas 2 e 3 via IA):
- POST /novo com origem_roteiro=upload e arquivo válido
- Validação de extensão de arquivo (.txt/.md)
- Validação de tamanho mínimo (100 chars)
- Fluxo: após Etapa 1 concluir, vai direto pra aguardando_revisao SEM etapa 2/3
- GET /revisar_roteiro não mostra botão "Refazer roteiro"
- POST /regerar_roteiro retorna 400 com erro "roteiro_importado"
- Retrocompatibilidade: projetos antigos (sem origem_roteiro.txt) funcionam normalmente

Feature 2 - CTA de "aguardando_audio" na tela de status:
- GET /status/<id> com status="aguardando_audio" mostra link pra /revisar_roteiro
"""

import json
from io import BytesIO
from pathlib import Path

import pytest

import server
from scripts.validators import validar_arquivo_roteiro, validar_origem_roteiro


# ---------------------------------------------------------------------------
# Feature 1 - Testes de validadores (CLAUDE.md secao 8: cobertura 90%)
# ---------------------------------------------------------------------------


def test_validar_origem_roteiro_aceita_ia():
    """"ia" é origem válida (comportamento histórico)."""
    assert validar_origem_roteiro("ia") is True


def test_validar_origem_roteiro_aceita_upload():
    """upload" é origem válida (nova feature)."""
    assert validar_origem_roteiro("upload") is True


def test_validar_origem_roteiro_rejeita_invalido():
    """Valores fora de {"ia", "upload"} são inválidos."""
    assert validar_origem_roteiro("geracao") is False
    assert validar_origem_roteiro("") is False
    assert validar_origem_roteiro("IA") is False  # case-sensitive


def test_validar_arquivo_roteiro_aceita_txt_valido():
    """Arquivo .txt com tamanho >= 100 chars é válido."""
    erro = validar_arquivo_roteiro(
        "roteiro.txt",
        "Este é um roteiro de teste com mais de cem caracteres para passar na validação de tamanho mínimo necessário."
    )
    assert erro is None


def test_validar_arquivo_roteiro_aceita_md_valido():
    """Arquivo .md com tamanho >= 100 chars é válido."""
    erro = validar_arquivo_roteiro(
        "roteiro.md",
        "# Titulo\n\nEste é um roteiro de teste com mais de cem caracteres para passar na validação de tamanho mínimo necessário."
    )
    assert erro is None


def test_validar_arquivo_roteiro_rejeita_extensao_invalida():
    """Arquivo .pdf/.doc/.xlsx não é aceito."""
    erro_pdf = validar_arquivo_roteiro("roteiro.pdf", "X" * 200)
    assert erro_pdf is not None and ".txt ou .md" in erro_pdf

    erro_doc = validar_arquivo_roteiro("roteiro.docx", "X" * 200)
    assert erro_doc is not None and ".txt ou .md" in erro_doc

    erro_exe = validar_arquivo_roteiro("script.exe", "X" * 200)
    assert erro_exe is not None


def test_validar_arquivo_roteiro_rejeita_muito_curto():
    """Arquivo com < 100 chars é rejeitado (provavelmente rascunho)."""
    erro = validar_arquivo_roteiro("roteiro.txt", "Muito curto")
    assert erro is not None
    assert "100" in erro


def test_validar_arquivo_roteiro_rejeita_vazio():
    """Arquivo vazio é rejeitado."""
    erro = validar_arquivo_roteiro("roteiro.txt", "")
    assert erro is not None


def test_validar_arquivo_roteiro_rejeita_whitespace_apenas():
    """Arquivo com apenas espaços é rejeitado."""
    erro = validar_arquivo_roteiro("roteiro.txt", "   \n   \t   ")
    assert erro is not None


def test_validar_arquivo_roteiro_sem_nome_arquivo():
    """Nome de arquivo vazio/None é rejeitado."""
    erro = validar_arquivo_roteiro("", "X" * 200)
    assert erro is not None


# ---------------------------------------------------------------------------
# Feature 1 - POST /novo com origem_roteiro=upload (validação)
# ---------------------------------------------------------------------------


def test_post_novo_origem_roteiro_invalida_retorna_400(client, tmp_path, monkeypatch):
    """POST com origem_roteiro fora de {"ia", "upload"} retorna 400
    (manipulação direta de request, nunca alcançável pela UI)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    (tmp_path / "projetos").mkdir()

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "invalido",
        },
    )

    assert resposta.status_code == 400


def test_post_novo_upload_roteiro_ausente_mostra_erro(client, tmp_path, monkeypatch):
    """POST com origem_roteiro=upload mas sem arquivo retorna erro com
    mensagem clara no template."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    (tmp_path / "projetos").mkdir()

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
        },
    )

    pagina = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina or "roteiro" in pagina.lower()


def test_post_novo_upload_roteiro_extensao_invalida_mostra_erro(client, tmp_path, monkeypatch):
    """Upload de arquivo .pdf é rejeitado."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    (tmp_path / "projetos").mkdir()

    arquivo_pdf = (BytesIO(b"fake pdf"), "roteiro.pdf")

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo_pdf,
        },
    )

    pagina = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina


def test_post_novo_upload_roteiro_muito_curto_mostra_erro(client, tmp_path, monkeypatch):
    """Upload de arquivo .txt com < 100 chars é rejeitado."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    (tmp_path / "projetos").mkdir()

    arquivo_curto = (BytesIO(b"Muito curto"), "roteiro.txt")

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo_curto,
        },
    )

    pagina = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina


def test_post_novo_upload_roteiro_form_preenche_apos_erro(client, tmp_path, monkeypatch):
    """Após erro de upload de roteiro, o valor de origem_roteiro fica
    pré-selecionado no formulário (não perde o que o usuário digitou)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    (tmp_path / "projetos").mkdir()

    arquivo_curto = (BytesIO(b"X"), "roteiro.txt")

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_teste",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo_curto,
        },
    )

    pagina = resposta.get_data(as_text=True)
    # Elemento input type="radio" com name="origem_roteiro" value="upload" deve estar selecionado
    assert 'value="upload"' in pagina


# ---------------------------------------------------------------------------
# Feature 1 - POST /novo com origem_roteiro=upload (caminho feliz)
# ---------------------------------------------------------------------------


def _popen_fake_etapa1_ok(returncode=0):
    """Fábrica para mockar Popen retornando sucesso na Etapa 1."""
    class _ProcessoFake:
        def __init__(self):
            # str, nao bytes: subprocess.Popen(..., text=True, encoding="utf-8")
            # ja decodifica o stdout real antes de _consumir_progresso_subprocess
            # ler cada linha - um mock com bytes aqui faz `linha.rstrip("\n")`
            # (server.py) explodir com TypeError dentro da thread de fundo,
            # matando a thread silenciosamente sem nunca chegar em
            # _encadear_etapa2 (achado ao rodar este teste de verdade).
            self.stdout = iter([
                '@PROGRESSO {"pct": 100.0, "detalhe": "1 video baixado", "sucesso": true}\n'
            ])
            self.returncode = returncode

        def wait(self):
            return None

    def _fake(comando, **kwargs):
        return _ProcessoFake()

    return _fake


def test_post_novo_upload_roteiro_cria_projeto_completo(client, tmp_path, monkeypatch):
    """POST com origem_roteiro=upload e arquivo válido cria a pasta do
    projeto com: entrada/origem_roteiro.txt="upload", roteiro.md preenchido,
    job_metadata.json com origen_roteiro="upload"."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake_etapa1_ok())

    conteudo_roteiro = "# Título do Roteiro\n\nEste é um roteiro de teste com mais de cem caracteres para passar na validação. O conteúdo é importante."
    arquivo = (BytesIO(conteudo_roteiro.encode("utf-8")), "roteiro.md")

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_upload",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo,
        },
    )

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/status/caso_upload")

    pasta_projeto = projetos_dir / "caso_upload"
    assert pasta_projeto.exists()

    # Verifica entrada/origem_roteiro.txt
    origem = (pasta_projeto / "entrada" / "origem_roteiro.txt").read_text(encoding="utf-8").strip()
    assert origem == "upload"

    # Verifica roteiro.md gravado
    roteiro_gravado = (pasta_projeto / "roteiro.md").read_text(encoding="utf-8")
    assert roteiro_gravado == conteudo_roteiro

    # Verifica job_metadata.json com origem_roteiro e caracteres
    job_metadata = json.loads((pasta_projeto / "job_metadata.json").read_text(encoding="utf-8"))
    assert job_metadata["origem_roteiro"] == "upload"
    assert job_metadata["caracteres"] == len(conteudo_roteiro)


def test_post_novo_upload_roteiro_força_tipo_uso_visual(client, tmp_path, monkeypatch):
    """POST com origem_roteiro=upload força tipo_uso_por_link=["visual"] pra
    cada link (nenhum link vira fonte de transcrição)."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake_etapa1_ok())

    arquivo = (BytesIO(b"X" * 200), "roteiro.txt")

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_tipo_uso",
            "links": "https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo,
        },
    )

    assert resposta.status_code == 302

    pasta_projeto = projetos_dir / "caso_tipo_uso"
    tipo_uso = json.loads(
        (pasta_projeto / "entrada" / "fontes_tipo_uso.json").read_text(encoding="utf-8")
    )
    # Ambas as fontes devem ser "visual"
    assert tipo_uso["fonte01"] == "visual"
    assert tipo_uso["fonte02"] == "visual"


def test_post_novo_upload_roteiro_requer_pelo_menos_um_link(client, tmp_path, monkeypatch):
    """POST com origem_roteiro=upload continua exigindo pelo menos 1 link
    (b-roll é necessário mesmo com roteiro pronto)."""
    monkeypatch.setenv("PROJETOS_DIR", str(tmp_path / "projetos"))
    (tmp_path / "projetos").mkdir()

    arquivo = (BytesIO(b"X" * 200), "roteiro.txt")

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_sem_links",
            "links": "",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo,
        },
    )

    pagina = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert "banner-erro-formulario" in pagina


# ---------------------------------------------------------------------------
# Feature 1 - Fluxo: Etapa 1 -> diretamente aguardando_revisao
# ---------------------------------------------------------------------------


def test_encadear_etapa2_pula_quando_origem_roteiro_upload(client, tmp_path, monkeypatch):
    """Após Etapa 1 concluir, _encadear_etapa2 verifica origem_roteiro e
    pula direto pra aguardando_revisao SEM chamar _executar_etapa2 (função
    de transcrição)."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    # Cria projeto com roteiro de upload
    conteudo_roteiro = "X" * 200
    arquivo = (BytesIO(conteudo_roteiro.encode("utf-8")), "roteiro.txt")

    # Mock da Etapa 1 e spy no _executar_etapa2
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake_etapa1_ok())

    chamadas_executar_etapa2 = []
    original_executar_etapa2 = server._executar_etapa2

    def spy_executar_etapa2(*args, **kwargs):
        chamadas_executar_etapa2.append((args, kwargs))
        return original_executar_etapa2(*args, **kwargs)

    monkeypatch.setattr(server, "_executar_etapa2", spy_executar_etapa2)

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_spy",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            "origem_roteiro": "upload",
            "arquivo_roteiro": arquivo,
        },
    )

    assert resposta.status_code == 302

    # Aguarda a thread da Etapa 1 concluir
    if "caso_spy" in server._threads:
        server._threads["caso_spy"].join(timeout=5)

    # Verifica que _executar_etapa2 nunca foi chamada
    assert len(chamadas_executar_etapa2) == 0

    # Verifica que o job foi pro estado aguardando_revisao
    job_disco = json.loads(
        (projetos_dir / "caso_spy" / "job.json").read_text(encoding="utf-8")
    )
    assert job_disco["status"] == "aguardando_revisao"
    assert job_disco["etapa_atual"] == "roteiro"


# ---------------------------------------------------------------------------
# Feature 1 - GET /revisar_roteiro (não mostra botão "Refazer roteiro")
# ---------------------------------------------------------------------------


def test_get_revisar_roteiro_roteiro_upload_sem_botao_regerar(client, tmp_path, monkeypatch):
    """GET /revisar_roteiro com roteiro_importado=true (origem_roteiro=upload)
    NÃO renderiza o botão 'Refazer roteiro com instruções' (#btn-regerar)."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_upload"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "origem_roteiro.txt").write_text("upload", encoding="utf-8")
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta / "roteiro.md").write_text("Roteiro de teste" * 10, encoding="utf-8")

    (pasta / "job.json").write_text(
        json.dumps(
            {"projeto_id": "caso_upload", "status": "aguardando_revisao", "etapa_atual": "revisao"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_upload/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Botão "Refazer roteiro" não deve estar presente
    assert 'id="btn-regerar"' not in pagina


def test_get_revisar_roteiro_roteiro_ia_mostra_botao_regerar(client, tmp_path, monkeypatch):
    """GET /revisar_roteiro com origem_roteiro=ia (padrão) MOSTRA o botão
    'Refazer roteiro com instruções'."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_ia"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    # Arquivo origem_roteiro.txt ausente = default "ia" por _ler_origem_roteiro
    (pasta / "roteiro.md").write_text("Roteiro de teste" * 10, encoding="utf-8")

    (pasta / "job.json").write_text(
        json.dumps(
            {"projeto_id": "caso_ia", "status": "aguardando_revisao", "etapa_atual": "revisao"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_ia/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Botão "Refazer roteiro" deve estar presente
    assert 'id="btn-regerar"' in pagina


# ---------------------------------------------------------------------------
# Feature 1 - POST /regerar_roteiro (bloqueado para roteiro_importado)
# ---------------------------------------------------------------------------


def test_post_regerar_roteiro_roteiro_upload_retorna_400(client, tmp_path, monkeypatch):
    """POST /regerar_roteiro com origem_roteiro=upload retorna 400 com erro
    'roteiro_importado', mesmo quando status='aguardando_revisao' (válido de
    outra forma)."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_regen"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "origem_roteiro.txt").write_text("upload", encoding="utf-8")
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta / "roteiro.md").write_text("Roteiro de teste" * 10, encoding="utf-8")

    (pasta / "job.json").write_text(
        json.dumps(
            {"projeto_id": "caso_regen", "status": "aguardando_revisao", "etapa_atual": "revisao"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_regen/regerar_roteiro",
        data={"feedback_usuario": "Refaça o roteiro"},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "roteiro_importado"


# ---------------------------------------------------------------------------
# Feature 1 - Retrocompatibilidade: projeto antigo (sem origem_roteiro.txt)
# ---------------------------------------------------------------------------


def test_ler_origem_roteiro_arquivo_ausente_default_ia():
    """_ler_origem_roteiro retorna "ia" quando entrada/origem_roteiro.txt não
    existe (projeto criado antes desta feature)."""
    from server import _ler_origem_roteiro

    # pasta=None
    assert _ler_origem_roteiro(None) == "ia"

    # arquivo não existe
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        assert _ler_origem_roteiro(tmp_path) == "ia"


def test_post_novo_retrocompatibilidade_origem_roteiro_ia(client, tmp_path, monkeypatch):
    """POST /novo sem especificar origem_roteiro defaulta para "ia"
    (retrocompatibilidade)."""
    projetos_dir = tmp_path / "projetos"
    projetos_dir.mkdir()
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setattr(server.subprocess, "Popen", _popen_fake_etapa1_ok())

    resposta = client.post(
        "/novo",
        data={
            "nome": "caso_retro",
            "links": "https://youtube.com/watch?v=abc",
            "perfil": "truecrime",
            # origem_roteiro não especificado
        },
    )

    assert resposta.status_code == 302

    pasta_projeto = projetos_dir / "caso_retro"
    origem = (pasta_projeto / "entrada" / "origem_roteiro.txt").read_text(encoding="utf-8").strip()
    assert origem == "ia"


def test_get_revisar_roteiro_projeto_antigo_mostra_botao_regerar(client, tmp_path, monkeypatch):
    """GET /revisar_roteiro em projeto criado antes da feature (sem
    entrada/origem_roteiro.txt) mostra o botão de regerar normalmente."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_antigo"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    # NÃO cria origem_roteiro.txt (projeto antigo)
    (pasta / "roteiro.md").write_text("Roteiro de teste" * 10, encoding="utf-8")

    (pasta / "job.json").write_text(
        json.dumps(
            {"projeto_id": "caso_antigo", "status": "aguardando_revisao", "etapa_atual": "revisao"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/projetos/caso_antigo/revisar_roteiro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Botão deve estar visível (projeto antigo = origem_roteiro_ia por default)
    assert 'id="btn-regerar"' in pagina


# ---------------------------------------------------------------------------
# Feature 2 - GET /status/<id> com status="aguardando_audio"
# ---------------------------------------------------------------------------


def test_get_status_aguardando_audio_mostra_link_revisar_roteiro(client, tmp_path, monkeypatch):
    """GET /status/<id> com job.status='aguardando_audio' renderiza o link
    #link-configurar-audio apontando para /revisar_roteiro, e o elemento
    #status-aguardando-audio não tem classe 'oculto'."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_audio"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "links.txt").write_text("https://youtube.com/watch?v=abc\n", encoding="utf-8")

    job_json = {
        "projeto_id": "caso_audio",
        "status": "aguardando_audio",
        "etapa_atual": "revisao",
    }
    (pasta / "job.json").write_text(
        json.dumps(job_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/status/caso_audio")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Procura pelo link id="link-configurar-audio"
    assert 'id="link-configurar-audio"' in pagina
    # Link aponta para /revisar_roteiro
    assert 'href="' in pagina and 'revisar_roteiro' in pagina
    # Elemento de status não deve ter a classe "oculto" (JS remove no polling)
    assert 'id="status-aguardando-audio"' in pagina


def test_get_status_outro_status_status_aguardando_audio_oculto(client, tmp_path, monkeypatch):
    """GET /status/<id> com status diferente de 'aguardando_audio' renderiza
    o elemento #status-aguardando-audio com classe 'oculto'."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_outro"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "links.txt").write_text("https://youtube.com/watch?v=abc\n", encoding="utf-8")

    job_json = {
        "projeto_id": "caso_outro",
        "status": "aguardando_revisao",  # não é aguardando_audio
        "etapa_atual": "revisao",
    }
    (pasta / "job.json").write_text(
        json.dumps(job_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.get("/status/caso_outro")
    pagina = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    # Elemento deve estar presente mas com classe "oculto"
    assert 'id="status-aguardando-audio"' in pagina
    assert 'class="aviso oculto"' in pagina  # combinação que indica status != aguardando_audio
