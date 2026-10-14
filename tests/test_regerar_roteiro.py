"""Testes de POST /projetos/<id>/regerar_roteiro (CLAUDE.md secao 5.5):

- Reexecucao da Etapa 3 com feedback do usuario
- Validacao de status (so "aguardando_revisao", nao "aguardando_audio")
- Validacao de feedback (nao pode ser vazio)
- Gravacao de entrada/feedback_regeneracao.txt
- Disparo de _disparar_etapa3 (mockado)
- Redirecionamento para /status/<id>
"""

import json
from pathlib import Path

import pytest

import server


def _criar_projeto_para_regen(tmp_path, nome, status="aguardando_revisao"):
    """Helper: cria projeto pronto pra regeneracao de roteiro."""
    projetos_dir = tmp_path / "projetos"
    pasta = projetos_dir / nome
    (pasta / "entrada").mkdir(parents=True)
    (pasta / "entrada" / "perfil.txt").write_text("truecrime", encoding="utf-8")
    (pasta / "entrada" / "links.txt").write_text("https://youtube.com/watch?v=abc\n", encoding="utf-8")

    (pasta / "roteiro.md").write_text("Roteiro original", encoding="utf-8")
    (pasta / "transcricoes").mkdir(parents=True)

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
# POST /regerar_roteiro - caminho feliz
# ---------------------------------------------------------------------------


def test_post_regerar_roteiro_com_feedback_valido(client, tmp_path, monkeypatch):
    """POST com feedback_usuario preenchido grava o feedback em
    entrada/feedback_regeneracao.txt e redireciona para /status/<id>."""
    projetos_dir = _criar_projeto_para_regen(tmp_path, "caso_regen")
    monkeypatch.setenv("PROJETOS_DIR", str(projetos_dir))
    # Mock da disparo da Etapa 3 para nao executar subprocess de verdade
    monkeypatch.setattr(server, "_disparar_etapa3", lambda *a, **k: None)

    feedback_usuario = "Por favor, reescreva o segundo paragrafo com mais detalhes sobre os motivos."

    resposta = client.post(
        "/projetos/caso_regen/regerar_roteiro",
        data={"feedback_usuario": feedback_usuario},
    )

    assert resposta.status_code == 302
    assert "/status/caso_regen" in resposta.headers["Location"]

    # Verifica que feedback foi gravado
    pasta_projeto = projetos_dir / "caso_regen"
    feedback_gravado = (pasta_projeto / "entrada" / "feedback_regeneracao.txt").read_text(
        encoding="utf-8"
    )
    assert feedback_gravado == feedback_usuario


def test_post_regerar_roteiro_dispara_etapa3(client, tmp_path, monkeypatch):
    """POST com feedback valido dispara _disparar_etapa3."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_regen(tmp_path, "caso_dispatch")))

    chamadas_etapa3 = []

    def _mock_disparar(projeto_id, pasta_projeto):
        chamadas_etapa3.append((projeto_id, pasta_projeto))

    monkeypatch.setattr(server, "_disparar_etapa3", _mock_disparar)

    resposta = client.post(
        "/projetos/caso_dispatch/regerar_roteiro",
        data={"feedback_usuario": "Refaça o roteiro"},
    )

    assert resposta.status_code == 302
    assert len(chamadas_etapa3) == 1
    projeto_id, pasta = chamadas_etapa3[0]
    assert projeto_id == "caso_dispatch"


# ---------------------------------------------------------------------------
# POST /regerar_roteiro - validacao de feedback
# ---------------------------------------------------------------------------


def test_post_regerar_roteiro_feedback_vazio_retorna_400(client, tmp_path, monkeypatch):
    """POST com feedback_usuario vazio retorna 400."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_regen(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/regerar_roteiro",
        data={"feedback_usuario": "   \n   "},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "feedback_vazio"


def test_post_regerar_roteiro_feedback_ausente_retorna_400(client, tmp_path, monkeypatch):
    """POST sem campo feedback_usuario retorna 400."""
    monkeypatch.setenv("PROJETOS_DIR", str(_criar_projeto_para_regen(tmp_path, "caso_teste")))

    resposta = client.post(
        "/projetos/caso_teste/regerar_roteiro",
        data={},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "feedback_vazio"


# ---------------------------------------------------------------------------
# POST /regerar_roteiro - validacao de status
# ---------------------------------------------------------------------------


def test_post_regerar_roteiro_status_aguardando_audio_retorna_400(
    client, tmp_path, monkeypatch
):
    """POST com status 'aguardando_audio' (nao 'aguardando_revisao') retorna 400."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_para_regen(tmp_path, "caso_audio", status="aguardando_audio")),
    )

    resposta = client.post(
        "/projetos/caso_audio/regerar_roteiro",
        data={"feedback_usuario": "Novo feedback"},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "status_invalido"


def test_post_regerar_roteiro_status_em_andamento_retorna_400(
    client, tmp_path, monkeypatch
):
    """POST com status 'em_andamento' retorna 400."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_para_regen(tmp_path, "caso_em_andamento", status="em_andamento")),
    )

    resposta = client.post(
        "/projetos/caso_em_andamento/regerar_roteiro",
        data={"feedback_usuario": "Novo feedback"},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "status_invalido"


def test_post_regerar_roteiro_status_concluido_retorna_400(client, tmp_path, monkeypatch):
    """POST com status 'concluido' retorna 400."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_para_regen(tmp_path, "caso_concluido", status="concluido")),
    )

    resposta = client.post(
        "/projetos/caso_concluido/regerar_roteiro",
        data={"feedback_usuario": "Novo feedback"},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "status_invalido"


def test_post_regerar_roteiro_status_erro_retorna_400(client, tmp_path, monkeypatch):
    """POST com status 'erro' retorna 400."""
    monkeypatch.setenv(
        "PROJETOS_DIR",
        str(_criar_projeto_para_regen(tmp_path, "caso_erro", status="erro")),
    )

    resposta = client.post(
        "/projetos/caso_erro/regerar_roteiro",
        data={"feedback_usuario": "Novo feedback"},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "status_invalido"


# ---------------------------------------------------------------------------
# POST /regerar_roteiro - projeto desconhecido
# ---------------------------------------------------------------------------


def test_post_regerar_roteiro_projeto_inexistente_retorna_400(client, monkeypatch):
    """POST com projeto que nao existe retorna 400 (status desconhecido)."""
    monkeypatch.setenv("PROJETOS_DIR", "/tmp/projetos_inexistentes")

    resposta = client.post(
        "/projetos/projeto_fantasma/regerar_roteiro",
        data={"feedback_usuario": "Feedback"},
    )

    assert resposta.status_code == 400
    corpo = resposta.get_json()
    assert corpo["erro"] == "status_invalido"
