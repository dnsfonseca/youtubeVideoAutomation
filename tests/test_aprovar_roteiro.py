"""Testes de POST /projetos/<id>/aprovar_roteiro (CLAUDE.md secao 5.5):

- Validacao de campos obrigatorios (roteiro_editado, titulo, origem_audio)
- Gravacao de roteiro_aprovado.md (texto editado exato, nao original)
- Gravacao de titulo.txt (titulo escolhido ou custom)
- Gravacao de origem_audio.json (TTS/upload/depois com detalhes)
- Validacoes de TTS (provedor/voz ausentes, chave nao configurada)
- Validacoes de upload (formato invalido, arquivo vazio, arquivo grande)
- Atualizacao de job.json com status correto (aguardando_audio ou
  aguardando_implementacao_etapa_4)
- Redirecionamento para /status/<id> apos sucesso
- Rejeicao de status invalido
"""

import json
import os
from io import BytesIO
from pathlib import Path

import pytest

import server


@pytest.fixture(autouse=True)
def _sem_dispatch_real_de_etapa4(monkeypatch):
    """POST /aprovar_roteiro dispara a Etapa 4 de verdade (scripts/
    4_obter_audio.py via subprocess.Popen numa thread de fundo) quando a
    origem do audio nao e' "depois" (Sessao 8). Nenhum teste deste arquivo
    testa a Etapa 4 em si (isso e' tests/test_obter_audio.py) - por padrao,
    `_disparar_etapa4` vira um no-op para manter estes testes rapidos e
    deterministicos. Os testes que especificamente querem verificar o
    disparo sobrescrevem este monkeypatch."""
    monkeypatch.setattr(server, "_disparar_etapa4", lambda *a, **k: None)


def _criar_projeto_para_aprovar(
    tmp_path,
    nome,
    roteiro_md="Roteiro original",
    titulos_sugeridos=None,
    status="aguardando_revisao",
):
    """Helper: cria projeto pronto pra ser aprovado (roteiro + titulos)."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")

    (pasta / "roteiro.md").write_text(roteiro_md, encoding="utf-8")

    if titulos_sugeridos is None:
        titulos_sugeridos = {
            "titulos": ["Titulo 1", "Titulo 2", "Titulo 3"],
            "descricoes": ["Desc 1", "Desc 2", "Desc 3"],
        }
    (pasta / "titulos_sugeridos.json").write_text(
        json.dumps(titulos_sugeridos, ensure_ascii=False, indent=2),
        encoding="utf-8",
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


def _assert_redirect_com_flash(client, resposta, projeto_id, trecho_mensagem):
    """As validacoes de /aprovar_roteiro (Sessao de correcoes UX pos-Sessao
    18) pararam de responder JSON cru - o form de revisao e' um POST comum
    (revisao_roteiro.html:84, sem fetch/JS), entao um JSON de erro aparecia
    como texto solto na tela pro usuario. Agora toda falha de validacao
    volta pra /revisar_roteiro com flash message (base.html)."""
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith(f"/projetos/{projeto_id}/revisar_roteiro")
    pagina = client.get(resposta.headers["Location"]).get_data(as_text=True)
    assert trecho_mensagem in pagina


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - validacao de campo roteiro_editado
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_vazio_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST com roteiro_editado vazio (ou só espaços) redireciona pra
    /revisar_roteiro com flash message - nao mais JSON cru."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "   \n   ",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test_voz",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "roteiro nao pode ficar vazio")


def test_post_aprovar_roteiro_sem_roteiro_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST sem campo roteiro_editado redireciona com flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test_voz",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "roteiro nao pode ficar vazio")


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - validacao de titulo
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_com_titulo_opcao_valida(client, tmp_path, monkeypatch):
    """POST com titulo_opcao="0" (indice valido de titulo sugerido) grava titulo
    correto."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_titulo")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_titulo/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "1",  # Indice 1 -> "Titulo 2"
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test_voz",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_titulo"
    titulo_gravado = (pasta_projeto / "titulo.txt").read_text(encoding="utf-8")
    assert titulo_gravado == "Titulo 2"


def test_post_aprovar_roteiro_com_titulo_custom(client, tmp_path, monkeypatch):
    """POST com titulo_opcao='custom' e titulo_custom preenchido grava titulo
    custom."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_custom")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_custom/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "custom",
            "titulo_custom": "Meu titulo personalizado",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test_voz",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_custom"
    titulo_gravado = (pasta_projeto / "titulo.txt").read_text(encoding="utf-8")
    assert titulo_gravado == "Meu titulo personalizado"


@pytest.mark.parametrize(
    "indice,texto_esperado",
    [(0, "Titulo 1"), (1, "Titulo 2"), (2, "Titulo 3")],
)
def test_post_aprovar_roteiro_titulo_escolhido_e_o_unico_exibido_na_conclusao(
    client, tmp_path, monkeypatch, indice, texto_esperado
):
    """Regressao (sessao "titulo canonico" - achado real, projeto Burke
    Ramsey): qualquer que seja a opcao de titulo escolhida pelo usuario na
    revisao (1a, 2a ou 3a sugestao), esse EXATO texto - e nenhum outro -
    tem que ser o titulo mostrado na tela de conclusao (CLAUDE.md secao
    5.9). Usa origem_audio="depois" pra' nao precisar mockar TTS - o que
    importa aqui e' so' o caminho titulo.txt -> /concluido."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_titulo_conclusao")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_titulo_conclusao/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": str(indice),
            "origem_audio": "depois",
        },
    )
    assert resposta.status_code == 302

    pasta_projeto = projetos_dir / "caso_titulo_conclusao"
    assert (pasta_projeto / "titulo.txt").read_text(encoding="utf-8") == texto_esperado

    pagina_conclusao = client.get("/projetos/caso_titulo_conclusao/concluido").get_data(as_text=True)
    # O titulo escolhido aparece como o titulo CANONICO da pagina (header -
    # templates/concluido.html:titulo_pagina, "bf-header-titulo") -
    # nenhuma etapa posterior gerou um quarto titulo substituindo-o.
    assert f'bf-header-titulo">{texto_esperado}<' in pagina_conclusao


def test_post_aprovar_roteiro_titulo_vazio_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST com titulo_opcao invalido (indice fora de range ou sem titulo
    custom) redireciona com flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "99",  # indice invalido
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test_voz",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Escolha ou digite um titulo")


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - validacao de origem_audio
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_origem_audio_invalida_redireciona_com_flash(
    client, tmp_path, monkeypatch
):
    """POST com origem_audio fora de ['tts', 'upload', 'depois'] redireciona
    com flash - bug real observado em teste de ponta a ponta (Sessao 18):
    no fluxo "decidir depois -> voltar depois" com TTS configurado, nenhum
    radio de origem_audio vem pre-marcado (revisao_roteiro.html:139,174),
    entao aprovar sem tocar nos radios batia nesta validacao e mostrava
    JSON cru na tela."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "spotify",  # invalido
        },
    )

    _assert_redirect_com_flash(
        client, resposta, "caso_teste", "Selecione a origem do audio antes de aprovar"
    )


def test_post_aprovar_roteiro_sem_origem_audio_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST sem origem_audio redireciona com flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
        },
    )

    _assert_redirect_com_flash(
        client, resposta, "caso_teste", "Selecione a origem do audio antes de aprovar"
    )


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - validacao de TTS (provedor/voz/chave)
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_tts_provedor_invalido_redireciona_com_flash(
    client, tmp_path, monkeypatch
):
    """POST com origem_audio='tts' mas tts_provedor invalido redireciona
    com flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "spotify",  # invalido
            "tts_voz": "test_voz",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Selecione um provedor de TTS valido")


def test_post_aprovar_roteiro_tts_voz_ausente_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST com origem_audio='tts' mas tts_voz ausente redireciona com
    flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            # tts_voz falta
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Selecione uma voz")


def test_post_aprovar_roteiro_tts_chave_nao_configurada_redireciona_com_flash(
    client, tmp_path, monkeypatch
):
    """POST com origem_audio='tts' e provedor cujas chave nao esta
    configurada redireciona com flash mencionando a chave certa."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test_voz",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "ELEVENLABS_API_KEY")


def test_post_aprovar_roteiro_google_voz_indisponivel_bloqueia_com_flash(
    client, tmp_path, monkeypatch
):
    """POST com provedor='google' e uma voz marcada indisponivel (falha
    anterior de geracao de preview, scripts/tts/preview_vozes.py) e'
    bloqueado com flash - o backend nunca confia so' na validacao do lado
    do cliente (static/preview_voz.js)."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")
    monkeypatch.setattr(
        server.preview_vozes,
        "carregar_indisponiveis",
        lambda: {"pt-BR-Wavenet-B": "Chave Google TTS invalida ou sem permissao."},
    )

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "google",
            "tts_voz": "pt-BR-Wavenet-B",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "esta marcada como indisponivel")


def test_post_aprovar_roteiro_google_voz_disponivel_grava_dados(client, tmp_path, monkeypatch):
    """Voz google que NAO esta na lista de indisponiveis segue o fluxo
    normal (grava origem_audio.json e dispara a Etapa 4)."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_teste")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test_key")
    monkeypatch.setattr(server.preview_vozes, "carregar_indisponiveis", lambda: {})

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "google",
            "tts_voz": "pt-BR-Wavenet-B",
        },
    )

    assert resposta.status_code == 302
    origem_audio = json.loads(
        (projetos_dir / "caso_teste" / "origem_audio.json").read_text(encoding="utf-8")
    )
    assert origem_audio == {"origem": "tts", "provedor": "google", "voz": "pt-BR-Wavenet-B"}


def test_post_aprovar_roteiro_tts_openai_nao_implementado_sem_chave(client, tmp_path, monkeypatch):
    """OpenAI TTS e' stub (nunca implementado nesta versao) - o flash tem
    que dizer isso, nao "configure a chave" (a chave sozinha nunca
    resolveria, o provedor continuaria indisponivel)."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "openai",
            "tts_voz": "alloy",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "ainda nao esta implementado")


def test_post_aprovar_roteiro_tts_openai_nao_implementado_mesmo_com_chave_configurada(client, tmp_path, monkeypatch):
    """Regressao critica desta sessao: OPENAI_API_KEY pode estar
    configurada so' porque o provedor de IMAGEM da thumbnail (Etapa 7,
    scripts/imagem/openai.py) usa a MESMA chave (mesma conta OpenAI). Isso
    NUNCA pode fazer o provedor de TTS OpenAI parecer disponivel - continua
    stub, `sintetizar()` levantaria NotImplementedError. A checagem de
    "implementado" tem que vir ANTES da checagem de chave."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-chave-real-usada-so-pra-imagem")

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "openai",
            "tts_voz": "alloy",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "ainda nao esta implementado")


def test_post_aprovar_roteiro_tts_azure_chave_ausente(client, tmp_path, monkeypatch):
    """Azure: chave ausente redireciona com flash claro."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.delenv("AZURE_TTS_KEY", raising=False)

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "azure",
            "tts_voz": "en-US-GuyNeural",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "AZURE_TTS_KEY")


def test_post_aprovar_roteiro_tts_darkplanner_chave_ausente(client, tmp_path, monkeypatch):
    """DarkPlanner: chave ausente redireciona com flash claro (mesmo
    espirito dos demais provedores TTS - CLAUDE.md secao 5.6)."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))
    monkeypatch.delenv("DARKPLANNER_API_KEY", raising=False)

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "darkplanner",
            "tts_voz": "v1",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "DARKPLANNER_API_KEY")


def test_post_aprovar_roteiro_tts_darkplanner_com_chave_grava_dados(client, tmp_path, monkeypatch):
    """DarkPlanner com chave configurada segue o fluxo normal - nao ha
    checagem de 'voz indisponivel' pra este provedor (essa checagem so'
    existe pro caminho Google, que usa cache local de preview - ver
    server.py:aprovar_roteiro)."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_dp_valido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("DARKPLANNER_API_KEY", "dpk_teste_123")

    resposta = client.post(
        "/projetos/caso_dp_valido/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "darkplanner",
            "tts_voz": "v1",
        },
    )

    assert resposta.status_code == 302
    origem_audio = json.loads(
        (projetos_dir / "caso_dp_valido" / "origem_audio.json").read_text(encoding="utf-8")
    )
    assert origem_audio == {"origem": "tts", "provedor": "darkplanner", "voz": "v1"}


def test_post_aprovar_roteiro_tts_com_chave_configurada_grava_dados(
    client, tmp_path, monkeypatch
):
    """POST com TTS valido (chave configurada) grava origem_audio.json com
    provedor e voz."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_tts_valido")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_123")

    resposta = client.post(
        "/projetos/caso_tts_valido/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "21m00Tcm4TlvDq8ikWAM",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_tts_valido"
    origem_dados = json.loads((pasta_projeto / "origem_audio.json").read_text(encoding="utf-8"))
    assert origem_dados["origem"] == "tts"
    assert origem_dados["provedor"] == "elevenlabs"
    assert origem_dados["voz"] == "21m00Tcm4TlvDq8ikWAM"


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - validacao de upload de audio
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_upload_ausente_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST com origem_audio='upload' mas sem arquivo redireciona com
    flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Envie um arquivo de audio")


def test_post_aprovar_roteiro_upload_formato_invalido_redireciona_com_flash(
    client, tmp_path, monkeypatch
):
    """POST com arquivo de formato invalido (ex: .txt, .jpg) redireciona
    com flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
            "audio_upload": (BytesIO(b"conteudo fake"), "arquivo.txt"),
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Formato de audio invalido")


def test_post_aprovar_roteiro_upload_vazio_redireciona_com_flash(client, tmp_path, monkeypatch):
    """POST com arquivo de audio vazio (0 bytes) redireciona com flash,
    nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
            "audio_upload": (BytesIO(b""), "arquivo.mp3"),
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Arquivo de audio vazio ou corrompido")


def test_post_aprovar_roteiro_upload_muito_grande_redireciona_com_flash(
    client, tmp_path, monkeypatch
):
    """POST com arquivo maior que 100MB redireciona com flash, nao 400 JSON."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_aprovar(tmp_path, "caso_teste")))

    conteudo_gigante = b"x" * (101 * 1024 * 1024)  # 101 MB

    resposta = client.post(
        "/projetos/caso_teste/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
            "audio_upload": (BytesIO(conteudo_gigante), "arquivo.mp3"),
        },
    )

    _assert_redirect_com_flash(client, resposta, "caso_teste", "Arquivo de audio maior que 100MB")


def test_post_aprovar_roteiro_upload_mp3_valido(client, tmp_path, monkeypatch):
    """POST com arquivo MP3 valido grava o arquivo e origem_audio.json."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_upload")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    conteudo_audio = b"fake mp3 data"  # Conteudo fake mas nao vazio

    resposta = client.post(
        "/projetos/caso_upload/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
            "audio_upload": (BytesIO(conteudo_audio), "narracao.mp3"),
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_upload"

    # Arquivo gravado com nome certo
    assert (pasta_projeto / "narracao_upload.mp3").exists()
    assert (pasta_projeto / "narracao_upload.mp3").read_bytes() == conteudo_audio

    # origem_audio.json registra o upload
    origem_dados = json.loads((pasta_projeto / "origem_audio.json").read_text(encoding="utf-8"))
    assert origem_dados["origem"] == "upload"
    assert origem_dados["upload_arquivo"] == "narracao_upload.mp3"


def test_post_aprovar_roteiro_upload_wav_valido(client, tmp_path, monkeypatch):
    """POST com arquivo WAV valido grava com extensao correta."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_wav")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_wav/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
            "audio_upload": (BytesIO(b"fake wav data"), "narracao.wav"),
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_wav"
    assert (pasta_projeto / "narracao_upload.wav").exists()


def test_post_aprovar_roteiro_upload_m4a_valido(client, tmp_path, monkeypatch):
    """POST com arquivo M4A valido."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_m4a")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_m4a/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "upload",
            "audio_upload": (BytesIO(b"fake m4a"), "audio.m4a"),
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_m4a"
    assert (pasta_projeto / "narracao_upload.m4a").exists()


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - origem "depois" (CLAUDE.md 5.6, Caminho C)
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_origem_depois_atualiza_status_para_aguardando_audio(
    client, tmp_path, monkeypatch
):
    """POST com origem_audio='depois' grava origem_audio.json com origem='depois'
    e atualiza job.json para status='aguardando_audio'."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_depois")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_depois/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_depois"

    origem_dados = json.loads((pasta_projeto / "origem_audio.json").read_text(encoding="utf-8"))
    assert origem_dados["origem"] == "depois"

    job_dados = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_dados["status"] == "aguardando_audio"


def test_post_aprovar_roteiro_origem_tts_dispara_etapa4(client, tmp_path, monkeypatch):
    """POST com origem_audio='tts' dispara a Etapa 4 (scripts/4_obter_audio.py,
    Sessao 8) via `_disparar_etapa4` - nao mais o status placeholder
    'aguardando_implementacao_etapa_4' de antes da Etapa 4 existir."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_etapa4")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    chamadas = []
    monkeypatch.setattr(
        server, "_disparar_etapa4", lambda projeto_id, pasta: chamadas.append((projeto_id, pasta))
    )

    resposta = client.post(
        "/projetos/caso_etapa4/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test",
        },
    )

    assert resposta.status_code == 302
    assert len(chamadas) == 1
    assert chamadas[0][0] == "caso_etapa4"
    assert chamadas[0][1] == projetos_dir / "caso_etapa4"


def test_post_aprovar_roteiro_origem_depois_nao_dispara_etapa4(client, tmp_path, monkeypatch):
    """POST com origem_audio='depois' NAO dispara a Etapa 4 - o projeto
    fica em 'aguardando_audio' ate o usuario voltar e escolher TTS/upload
    (CLAUDE.md secao 5.6, Caminho C)."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_sem_disparo")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    chamadas = []
    monkeypatch.setattr(server, "_disparar_etapa4", lambda *a, **k: chamadas.append((a, k)))

    resposta = client.post(
        "/projetos/caso_sem_disparo/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
        },
    )

    assert resposta.status_code == 302
    assert chamadas == []
    pasta_projeto = projetos_dir / "caso_sem_disparo"
    job_dados = json.loads((pasta_projeto / "job.json").read_text(encoding="utf-8"))
    assert job_dados["status"] == "aguardando_audio"


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - gravacao de roteiro_aprovado.md
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_grava_roteiro_editado_exato(client, tmp_path, monkeypatch):
    """roteiro_aprovado.md grava EXATAMENTE o texto enviado em
    roteiro_editado, nao o roteiro.md original."""
    roteiro_original = "Este eh o roteiro original gerado pela IA."
    roteiro_editado = "Este eh o roteiro EDITADO PELO USUARIO com novas secoes."
    projetos_dir = _criar_projeto_para_aprovar(
        tmp_path, "caso_edicao", roteiro_md=roteiro_original
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_edicao/aprovar_roteiro",
        data={
            "roteiro_editado": roteiro_editado,
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_edicao"

    roteiro_aprovado = (pasta_projeto / "roteiro_aprovado.md").read_text(encoding="utf-8")
    assert roteiro_aprovado == roteiro_editado
    assert "EDITADO PELO USUARIO" in roteiro_aprovado
    assert roteiro_original != roteiro_aprovado


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - status invalido -> 400
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_status_concluido_retorna_400(client, tmp_path, monkeypatch):
    """POST com projeto em status 'concluido' retorna 400."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_concluido"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta / "roteiro.md").write_text("Roteiro", encoding="utf-8")
    (pasta / "titulos_sugeridos.json").write_text(
        json.dumps({"titulos": ["T1"], "descricoes": ["D1"]}),
        encoding="utf-8",
    )
    (pasta / "job.json").write_text(
        json.dumps({"status": "concluido", "etapa_atual": "montagem"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_concluido/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo",
            "titulo_opcao": "0",
            "origem_audio": "depois",
        },
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "status_invalido"


def test_post_aprovar_roteiro_status_em_andamento_retorna_400(
    client, tmp_path, monkeypatch
):
    """POST com projeto em status 'em_andamento' retorna 400."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / "caso_em_andamento"
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta / "roteiro.md").write_text("Roteiro", encoding="utf-8")
    (pasta / "titulos_sugeridos.json").write_text(
        json.dumps({"titulos": ["T1"], "descricoes": ["D1"]}),
        encoding="utf-8",
    )
    (pasta / "job.json").write_text(
        json.dumps({"status": "em_andamento", "etapa_atual": "download"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post("/projetos/caso_em_andamento/aprovar_roteiro", data={})

    assert resposta.status_code == 400


# ---------------------------------------------------------------------------
# remover_notas_rodape() - BUG CRITICO corrigido pos-Sessao 7: as notas de
# rodape estavam sendo salvas em roteiro_aprovado.md e narradas literalmente
# pelo TTS.
# ---------------------------------------------------------------------------


def test_remover_notas_rodape_remove_nota_fonte_simples():
    texto = "O suspeito foi visto no local.[F1@04:32] Ele fugiu em seguida."
    resultado = server.remover_notas_rodape(texto)
    assert "[F1@04:32]" not in resultado
    assert resultado == "O suspeito foi visto no local. Ele fugiu em seguida."


def test_remover_notas_rodape_remove_nota_fonte_com_intervalo():
    texto = "Segundo o relato [F1@13:56-14:01] o caso teve nova reviravolta."
    resultado = server.remover_notas_rodape(texto)
    assert "[F1@13:56-14:01]" not in resultado
    assert resultado == "Segundo o relato o caso teve nova reviravolta."


def test_remover_notas_rodape_remove_nota_externa_url():
    texto = "A policia confirmou o fato [N: https://cnn.com/caso] naquele dia."
    resultado = server.remover_notas_rodape(texto)
    assert "[N:" not in resultado
    assert resultado == "A policia confirmou o fato naquele dia."


def test_remover_notas_rodape_remove_nota_externa_texto_livre():
    texto = "Detalhe adicional [N: 2 - g-p1dfP5eYg] sobre o caso."
    resultado = server.remover_notas_rodape(texto)
    assert "[N:" not in resultado
    assert resultado == "Detalhe adicional sobre o caso."


def test_remover_notas_rodape_remove_aviso():
    texto = "Apenas uma fonte confirmou isso [⚠ single-source] ate agora."
    resultado = server.remover_notas_rodape(texto)
    assert "⚠" not in resultado
    assert resultado == "Apenas uma fonte confirmou isso ate agora."


def test_remover_notas_rodape_texto_sem_notas_fica_inalterado():
    texto = "Este roteiro nao tem nenhuma marcacao de origem."
    assert server.remover_notas_rodape(texto) == texto


def test_remover_notas_rodape_nota_colada_em_pontuacao_sem_espaco_fantasma():
    texto = "Ele foi preso naquela noite.[F1@01:23] Depois liberado."
    resultado = server.remover_notas_rodape(texto)
    assert resultado == "Ele foi preso naquela noite. Depois liberado."
    assert "  " not in resultado


def test_remover_notas_rodape_multiplas_notas_no_meio_da_frase():
    texto = (
        "O caso [F1@02:10] chocou a cidade [N: https://example.com] e gerou "
        "controversia [⚠ conflict] entre as fontes."
    )
    resultado = server.remover_notas_rodape(texto)
    assert "[F1" not in resultado
    assert "[N:" not in resultado
    assert "⚠" not in resultado
    assert resultado == (
        "O caso chocou a cidade e gerou controversia entre as fontes."
    )


def test_remover_notas_rodape_string_vazia():
    assert server.remover_notas_rodape("") == ""


# ---------------------------------------------------------------------------
# remover_notas_rodape() com tags de MULTIPLAS fontes - correcao pos-Sessao
# 7.2: roteiro real gerou [F2@00:27-01:00, F1@16:00-16:06] e a tag inteira
# sobrevivia ao filtro, indo parar (bruta) em roteiro_aprovado.md.
# ---------------------------------------------------------------------------


def test_remover_notas_rodape_remove_tag_com_duas_fontes():
    texto = "O corpo foi encontrado [F1@04:32, F2@10:15] naquela manha."
    resultado = server.remover_notas_rodape(texto)
    assert "[F1" not in resultado
    assert "[F2" not in resultado
    assert resultado == "O corpo foi encontrado naquela manha."


def test_remover_notas_rodape_remove_tag_com_tres_ou_mais_fontes():
    texto = (
        "O fragmento de manta foi localizado "
        "[F1@13:56-14:01, F2@00:27-01:00, F3@05:10] na trilha."
    )
    resultado = server.remover_notas_rodape(texto)
    assert "[F1" not in resultado
    assert "[F2" not in resultado
    assert "[F3" not in resultado
    assert resultado == "O fragmento de manta foi localizado na trilha."


def test_remover_notas_rodape_tag_multipla_nao_deixa_espaco_fantasma():
    texto = "Ele foi visto no local.[F1@04:32, F2@10:15] Depois desapareceu."
    resultado = server.remover_notas_rodape(texto)
    assert resultado == "Ele foi visto no local. Depois desapareceu."
    assert "  " not in resultado


def test_remover_notas_rodape_tag_multipla_com_espacos_extras_ao_redor_da_virgula():
    texto = "Divergencia sobre o local [F1@04:32 , F2@10:15] permanece."
    resultado = server.remover_notas_rodape(texto)
    assert "[F1" not in resultado
    assert "[F2" not in resultado
    assert resultado == "Divergencia sobre o local permanece."


# ---------------------------------------------------------------------------
# remover_cabecalhos_markdown() - correcao pos-Sessao 21: o roteiro saia com
# linhas tipo "## The Woman Who Lived Alone..." que iam parar no TTS (o
# narrador lia o subtitulo como narracao, quebrando o video continuo).
# ---------------------------------------------------------------------------


def test_remover_cabecalhos_markdown_remove_cabecalho_h2():
    texto = "Paragrafo um.\n\n## The Woman Who Lived Alone\n\nParagrafo dois."
    resultado = server.remover_cabecalhos_markdown(texto)
    assert "##" not in resultado
    assert "The Woman Who Lived Alone" not in resultado
    assert resultado == "Paragrafo um.\n\nParagrafo dois."


def test_remover_cabecalhos_markdown_remove_cabecalho_h1():
    texto = "Introducao.\n\n# Titulo Principal\n\nDesenvolvimento do caso."
    resultado = server.remover_cabecalhos_markdown(texto)
    assert "#" not in resultado
    assert resultado == "Introducao.\n\nDesenvolvimento do caso."


def test_remover_cabecalhos_markdown_preserva_quebra_de_paragrafo():
    """A remocao da linha do cabecalho nao pode colar os dois paragrafos
    vizinhos num so - continua havendo UMA linha em branco entre eles."""
    texto = "Antes.\n\n## Secao\n\nDepois."
    resultado = server.remover_cabecalhos_markdown(texto)
    assert "\n\n" in resultado
    assert "\n\n\n" not in resultado


def test_remover_cabecalhos_markdown_remove_multiplos_cabecalhos():
    texto = "## Primeira secao\n\nTexto um.\n\n## Segunda secao\n\nTexto dois."
    resultado = server.remover_cabecalhos_markdown(texto)
    assert "##" not in resultado
    assert resultado == "Texto um.\n\nTexto dois."


def test_remover_cabecalhos_markdown_nao_remove_hashtag_no_meio_da_frase():
    """So' remove linha que COMECA com # seguido de espaco (ATX header) -
    nao mexe em cardinal/hashtag usado dentro do texto normal."""
    texto = "O caso ficou conhecido como #JusticaParaNancy nas redes sociais."
    resultado = server.remover_cabecalhos_markdown(texto)
    assert resultado == texto


def test_remover_cabecalhos_markdown_texto_sem_cabecalho_fica_inalterado():
    texto = "Este roteiro nao tem nenhum cabecalho markdown."
    assert server.remover_cabecalhos_markdown(texto) == texto


def test_remover_cabecalhos_markdown_string_vazia():
    assert server.remover_cabecalhos_markdown("") == ""


def test_post_aprovar_roteiro_remove_cabecalho_markdown_do_roteiro_aprovado(client, tmp_path, monkeypatch):
    """roteiro_aprovado.md nunca deve conter cabecalho markdown - o TTS
    narraria o subtitulo como se fosse parte do roteiro (bug real,
    projeto nancyGuthrieProject03: "## A Doorbell Camera and Forty-One
    Minutes" foi narrado literalmente)."""
    roteiro_original = "Texto original."
    roteiro_editado = "Abertura do caso.\n\n## A Doorbell Camera and Forty-One Minutes\n\nDesenvolvimento."
    projetos_dir = _criar_projeto_para_aprovar(
        tmp_path, "caso_cabecalho", roteiro_md=roteiro_original
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_cabecalho/aprovar_roteiro",
        data={
            "roteiro_editado": roteiro_editado,
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_cabecalho"
    roteiro_aprovado = (pasta_projeto / "roteiro_aprovado.md").read_text(encoding="utf-8")
    assert "##" not in roteiro_aprovado
    assert "A Doorbell Camera and Forty-One Minutes" not in roteiro_aprovado
    assert roteiro_aprovado == "Abertura do caso.\n\nDesenvolvimento."


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - roteiro_aprovado.md sempre sai sem notas de rodape
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_remove_notas_de_rodape_ao_salvar(
    client, tmp_path, monkeypatch
):
    """roteiro_aprovado.md nunca deve conter notas de rodape - elas seriam
    narradas literalmente pelo TTS ("F 1 arroba 04 32")."""
    roteiro_com_notas = (
        "O suspeito [F1@04:32] foi indiciado.[N: https://cnn.com/caso] "
        "Apenas uma fonte confirmou isso [⚠ single-source]."
    )
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_notas")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_notas/aprovar_roteiro",
        data={
            "roteiro_editado": roteiro_com_notas,
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_notas"
    roteiro_aprovado = (pasta_projeto / "roteiro_aprovado.md").read_text(encoding="utf-8")

    assert "[F1@04:32]" not in roteiro_aprovado
    assert "[N:" not in roteiro_aprovado
    assert "⚠" not in roteiro_aprovado
    assert "single-source" not in roteiro_aprovado


def test_post_aprovar_roteiro_remove_tag_de_nota_com_multiplas_fontes(
    client, tmp_path, monkeypatch
):
    """Tag com multiplas fontes ([F2@..., F1@...]) tambem some por inteiro
    de roteiro_aprovado.md - correcao pos-Sessao 7.2 (roteiro real gerou
    esse padrao e a tag bruta sobrevivia ao filtro anterior)."""
    roteiro_com_notas = (
        "O corpo foi encontrado [F2@00:27-01:00, F1@16:00-16:06] na trilha."
    )
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_notas_multiplas")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_notas_multiplas/aprovar_roteiro",
        data={
            "roteiro_editado": roteiro_com_notas,
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_notas_multiplas"
    roteiro_aprovado = (pasta_projeto / "roteiro_aprovado.md").read_text(encoding="utf-8")

    assert "[F1" not in roteiro_aprovado
    assert "[F2" not in roteiro_aprovado
    assert roteiro_aprovado == "O corpo foi encontrado na trilha."


def test_post_aprovar_roteiro_preserva_edicao_do_usuario_sem_notas(
    client, tmp_path, monkeypatch
):
    """Edicoes feitas pelo usuario no texto (fora das notas) sao preservadas
    integralmente - so as notas de rodape somem."""
    roteiro_editado = (
        "Texto TOTALMENTE reescrito pelo usuario [F2@10:00] com uma frase nova."
    )
    projetos_dir = _criar_projeto_para_aprovar(
        tmp_path, "caso_edicao_com_notas", roteiro_md="Roteiro original qualquer"
    )
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")

    resposta = client.post(
        "/projetos/caso_edicao_com_notas/aprovar_roteiro",
        data={
            "roteiro_editado": roteiro_editado,
            "titulo_opcao": "0",
            "origem_audio": "tts",
            "tts_provedor": "elevenlabs",
            "tts_voz": "test",
        },
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_edicao_com_notas"
    roteiro_aprovado = (pasta_projeto / "roteiro_aprovado.md").read_text(encoding="utf-8")

    assert roteiro_aprovado == "Texto TOTALMENTE reescrito pelo usuario com uma frase nova."
    assert "TOTALMENTE reescrito pelo usuario" in roteiro_aprovado
    assert "[F2" not in roteiro_aprovado


# ---------------------------------------------------------------------------
# POST /aprovar_roteiro - musica de fundo (Grupo B da sessao de UX - movido
# do formulario de Novo projeto pra este form, CLAUDE.md secao 5.8). Testes
# equivalentes aos que existiam em test_novo_e_status.py para POST /novo
# antes do bloco de musica migrar pra ca.
# ---------------------------------------------------------------------------


def test_post_aprovar_roteiro_musica_salva_em_pasta_e_atualiza_configuracao(
    client, tmp_path, monkeypatch
):
    """com_musica_fundo=on + arquivos validos em musicas[] salva os
    arquivos em entrada/musica_fundo/ e grava com_musica_fundo=true em
    entrada/configuracao_video.json (consumido depois pela Etapa 6)."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_musica_upload")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_musica_upload/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
            "com_musica_fundo": "on",
            "musicas[]": [
                (BytesIO(b"fake-audio-1"), "track1.mp3"),
                (BytesIO(b"fake-audio-2"), "track2.wav"),
            ],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_musica_upload"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"

    assert pasta_musicas.exists()
    arquivos = list(pasta_musicas.glob("*.mp3")) + list(pasta_musicas.glob("*.wav"))
    assert len(arquivos) == 2

    config_video = json.loads(
        (pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["com_musica_fundo"] is True


def test_post_aprovar_roteiro_musica_marcada_sem_arquivos_redireciona_com_flash(
    client, tmp_path, monkeypatch
):
    """com_musica_fundo=on sem nenhum arquivo em musicas[] e sem musica ja
    salva em disco redireciona com flash - roteiro NAO e aprovado (nada e
    escrito, mesma protecao das outras validacoes deste endpoint)."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_musica_ausente")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_musica_ausente/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
            "com_musica_fundo": "on",
            # Sem musicas[]
        },
    )

    _assert_redirect_com_flash(
        client, resposta, "caso_musica_ausente", "mas nao selecionou nenhum arquivo"
    )
    pasta_projeto = projetos_dir / "caso_musica_ausente"
    assert not (pasta_projeto / "roteiro_aprovado.md").exists()


def test_post_aprovar_roteiro_musica_desmarcada_ignora_uploads(client, tmp_path, monkeypatch):
    """com_musica_fundo ausente/off ignora qualquer arquivo em musicas[] -
    a pasta entrada/musica_fundo/ nao e criada e o flag fica false."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_musica_ignorada")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_musica_ignorada/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
            # com_musica_fundo esta ausente/off
            "musicas[]": [(BytesIO(b"fake-audio"), "track.mp3")],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_musica_ignorada"
    assert not (pasta_projeto / "entrada" / "musica_fundo").exists()

    config_video = json.loads(
        (pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["com_musica_fundo"] is False


def test_post_aprovar_roteiro_musica_extensao_invalida_ignorada(client, tmp_path, monkeypatch):
    """com_musica_fundo=on com 1 arquivo .txt (invalido) e 1 .mp3 (valido):
    o invalido e ignorado silenciosamente, so o .mp3 e salvo."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_musica_mista")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_musica_mista/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
            "com_musica_fundo": "on",
            "musicas[]": [
                (BytesIO(b"texto"), "documento.txt"),  # Invalido
                (BytesIO(b"audio"), "musica.mp3"),  # Valido
            ],
        },
        content_type="multipart/form-data",
    )

    assert resposta.status_code == 302
    pasta_projeto = projetos_dir / "caso_musica_mista"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"

    assert pasta_musicas.exists()
    assert len(list(pasta_musicas.glob("*.mp3"))) == 1
    assert len(list(pasta_musicas.glob("*.txt"))) == 0


def test_post_aprovar_roteiro_musica_marcada_sem_reenvio_reaproveita_arquivo_existente(
    client, tmp_path, monkeypatch
):
    """Resubmissao do form (ex: Caminho C - "decidir depois" e depois volta
    pra escolher a origem do audio de verdade) nao reenvia arquivo nenhum no
    <input type=file>, mesmo com o checkbox pre-marcado. Se ja existe musica
    salva em disco de uma aprovacao anterior, nao deve exigir reenvio."""
    projetos_dir = _criar_projeto_para_aprovar(tmp_path, "caso_musica_resubmissao")
    pasta_projeto = projetos_dir / "caso_musica_resubmissao"
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True)
    (pasta_musicas / "ja_salva.mp3").write_bytes(b"audio existente")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))

    resposta = client.post(
        "/projetos/caso_musica_resubmissao/aprovar_roteiro",
        data={
            "roteiro_editado": "Novo roteiro",
            "titulo_opcao": "0",
            "origem_audio": "depois",
            "com_musica_fundo": "on",
            # Sem musicas[] - arquivo ja esta em disco
        },
    )

    assert resposta.status_code == 302
    assert (pasta_projeto / "roteiro_aprovado.md").exists()
    config_video = json.loads(
        (pasta_projeto / "entrada" / "configuracao_video.json").read_text(encoding="utf-8")
    )
    assert config_video["com_musica_fundo"] is True
    # Arquivo existente preservado, nada foi apagado
    assert (pasta_musicas / "ja_salva.mp3").exists()
