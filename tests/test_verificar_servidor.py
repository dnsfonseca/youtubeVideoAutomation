"""Testes de scripts/verificar_servidor.py (melhoria do fluxo do atalho
da area de trabalho - iniciar servidor + abrir navegador automatico).

Nunca abre um socket de verdade nem um navegador de verdade - socket,
urllib e webbrowser sao sempre mockados (CLAUDE.md secao 8).
"""
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import verificar_servidor as vs  # noqa: E402


def _resposta_http(payload: dict):
    """Mock de contexto de urllib.request.urlopen(...) com corpo JSON."""
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.read.return_value = json.dumps(payload).encode("utf-8")
    return fake


# ---------------------------------------------------------------------
# checar_status_porta
# ---------------------------------------------------------------------


def test_porta_livre_quando_conexao_tcp_e_recusada(monkeypatch):
    monkeypatch.setattr(vs, "_porta_aberta", lambda host, porta, timeout=2.0: False)

    assert vs.checar_status_porta("localhost", 5000) == "livre"


def test_broll_foundry_quando_assinatura_da_rota_bate(monkeypatch):
    monkeypatch.setattr(vs, "_porta_aberta", lambda host, porta, timeout=2.0: True)
    payload = {
        "versao_local": "0.1.0-mvp",
        "versao_disponivel": None,
        "mensagem": "verificacao de atualizacoes nao implementada nesta versao",
    }
    with patch.object(vs.urllib.request, "urlopen", return_value=_resposta_http(payload)):
        assert vs.checar_status_porta("localhost", 5000) == "broll_foundry"


def test_outro_servico_quando_porta_aberta_mas_json_nao_bate(monkeypatch):
    monkeypatch.setattr(vs, "_porta_aberta", lambda host, porta, timeout=2.0: True)
    payload = {"algum_campo": "de outro servico qualquer"}
    with patch.object(vs.urllib.request, "urlopen", return_value=_resposta_http(payload)):
        assert vs.checar_status_porta("localhost", 5000) == "outro_servico"


def test_outro_servico_quando_porta_aberta_mas_nao_e_http(monkeypatch):
    monkeypatch.setattr(vs, "_porta_aberta", lambda host, porta, timeout=2.0: True)
    with patch.object(
        vs.urllib.request, "urlopen", side_effect=urllib.error.URLError("conexao recusada no meio")
    ):
        assert vs.checar_status_porta("localhost", 5000) == "outro_servico"


def test_outro_servico_quando_resposta_nao_e_json_valido(monkeypatch):
    monkeypatch.setattr(vs, "_porta_aberta", lambda host, porta, timeout=2.0: True)
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.read.return_value = b"<html>nao sou json</html>"
    with patch.object(vs.urllib.request, "urlopen", return_value=fake):
        assert vs.checar_status_porta("localhost", 5000) == "outro_servico"


# ---------------------------------------------------------------------
# aguardar_pronto
# ---------------------------------------------------------------------


def test_aguardar_pronto_retorna_true_assim_que_broll_foundry_responde(monkeypatch):
    resultados = iter(["livre", "livre", "broll_foundry"])
    monkeypatch.setattr(vs, "checar_status_porta", lambda *a, **k: next(resultados))
    monkeypatch.setattr(vs.time, "sleep", lambda *_: None)

    assert vs.aguardar_pronto("localhost", 5000, timeout_total=10.0, intervalo=0.01) is True


def test_aguardar_pronto_retorna_false_apos_timeout(monkeypatch):
    monkeypatch.setattr(vs, "checar_status_porta", lambda *a, **k: "livre")
    monkeypatch.setattr(vs.time, "sleep", lambda *_: None)

    tempos = iter([0.0, 0.0, 5.0, 11.0])
    monkeypatch.setattr(vs.time, "monotonic", lambda: next(tempos))

    assert vs.aguardar_pronto("localhost", 5000, timeout_total=10.0, intervalo=0.01) is False


# ---------------------------------------------------------------------
# abrir_navegador
# ---------------------------------------------------------------------


def test_abrir_navegador_usa_url_local_correta(monkeypatch):
    chamadas = []
    monkeypatch.setattr(vs.webbrowser, "open", lambda url: chamadas.append(url))

    vs.abrir_navegador("localhost", 5000)

    assert chamadas == ["http://localhost:5000/"]


# ---------------------------------------------------------------------
# _porta_padrao
# ---------------------------------------------------------------------


def test_porta_padrao_usa_variavel_de_ambiente_se_presente(monkeypatch):
    monkeypatch.setenv("PORTA", "8080")

    assert vs._porta_padrao() == "8080"


def test_porta_padrao_cai_para_5000_sem_env_nem_dotenv(monkeypatch):
    monkeypatch.delenv("PORTA", raising=False)

    assert vs._porta_padrao() == "5000"


# ---------------------------------------------------------------------
# main() - modo checar-porta
# ---------------------------------------------------------------------


def test_main_checar_porta_retorna_0_quando_livre(monkeypatch):
    monkeypatch.setattr(vs, "checar_status_porta", lambda *a, **k: "livre")

    assert vs.main(["checar-porta", "--porta", "5000"]) == 0


def test_main_checar_porta_retorna_2_quando_ja_esta_rodando(monkeypatch):
    monkeypatch.setattr(vs, "checar_status_porta", lambda *a, **k: "broll_foundry")

    assert vs.main(["checar-porta", "--porta", "5000"]) == 2


def test_main_checar_porta_retorna_3_quando_outro_servico(monkeypatch):
    monkeypatch.setattr(vs, "checar_status_porta", lambda *a, **k: "outro_servico")

    assert vs.main(["checar-porta", "--porta", "5000"]) == 3


# ---------------------------------------------------------------------
# main() - modo aguardar-e-abrir
# ---------------------------------------------------------------------


def test_main_aguardar_e_abrir_abre_navegador_quando_fica_pronto(monkeypatch):
    monkeypatch.setattr(vs, "aguardar_pronto", lambda *a, **k: True)
    chamadas = []
    monkeypatch.setattr(vs, "abrir_navegador", lambda host, porta: chamadas.append((host, porta)))

    resultado = vs.main(["aguardar-e-abrir", "--porta", "5000", "--timeout", "1"])

    assert resultado == 0
    assert chamadas == [("localhost", "5000")]


def test_main_aguardar_e_abrir_nao_abre_navegador_em_timeout(monkeypatch):
    monkeypatch.setattr(vs, "aguardar_pronto", lambda *a, **k: False)
    chamadas = []
    monkeypatch.setattr(vs, "abrir_navegador", lambda host, porta: chamadas.append((host, porta)))

    resultado = vs.main(["aguardar-e-abrir", "--porta", "5000", "--timeout", "1"])

    assert resultado == 1
    assert chamadas == []


# ---------------------------------------------------------------------
# main() - modo abrir-navegador
# ---------------------------------------------------------------------


def test_main_abrir_navegador_chama_direto(monkeypatch):
    chamadas = []
    monkeypatch.setattr(vs, "abrir_navegador", lambda host, porta: chamadas.append((host, porta)))

    resultado = vs.main(["abrir-navegador", "--porta", "5000"])

    assert resultado == 0
    assert chamadas == [("localhost", "5000")]
