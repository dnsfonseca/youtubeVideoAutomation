"""Testes de scripts/instalar_ffmpeg.py — cascata de instalacao do ffmpeg
no Windows (CLAUDE.md secao 18.3).

REGRA CRITICA (documentada tambem em tests/test_iniciar_bat.py, onde um
incidente real aconteceu): nenhum teste deste arquivo pode invocar
winget/choco/powershell/Start-Process -Verb RunAs de verdade, escrever no
registro do Windows de verdade, nem bloquear esperando input() real. Toda
chamada a processo externo passa por instalar_ffmpeg.rodar() (mockada em
todo teste que exercita esse caminho) e todo acesso ao registro passa por
instalar_ffmpeg.adicionar_ao_path_usuario() (sempre mockada aqui). A
fixture `_protecoes_de_seguranca` abaixo e' uma rede de seguranca autouse
que faz o teste falhar (em vez de agir de verdade) caso algum cenario
esqueca de mockar um desses pontos.
"""

import types
from pathlib import Path

import pytest

from scripts import instalar_ffmpeg


def _sequencia_booleanos(*valores):
    """Retorna uma funcao que devolve os valores de `valores`, um por
    chamada, na ordem em que instalar_ffmpeg_cascata()/tentativa_winget()
    chamam robustez.ffmpeg_disponivel() varias vezes ao longo de uma
    mesma cascata. Se chamada mais vezes do que valores fornecidos,
    repete o ultimo valor (evita IndexError mascarando a asssercao real
    do teste)."""
    pendentes = list(valores)

    def _proximo():
        if pendentes:
            return pendentes.pop(0)
        return valores[-1]

    return _proximo


@pytest.fixture(autouse=True)
def _protecoes_de_seguranca(monkeypatch):
    """Rede de seguranca valida pra todos os testes deste arquivo: garante
    que nenhum teste, mesmo por esquecimento, dispare subprocess.run real,
    grave no registro do Windows via adicionar_ao_path_usuario, ou trave
    esperando input() real. Cada teste que precisa exercitar um desses
    caminhos sobrescreve explicitamente o monkeypatch correspondente."""

    def _subprocess_run_nao_deveria_ser_chamado(*args, **kwargs):
        pytest.fail(
            "subprocess.run real foi chamado - instalar_ffmpeg.rodar() "
            "deveria estar mockado neste teste"
        )

    monkeypatch.setattr(instalar_ffmpeg.subprocess, "run", _subprocess_run_nao_deveria_ser_chamado)

    def _input_nao_deveria_ser_chamado():
        pytest.fail(
            "input() real foi chamado - confirmar_continuar_com_uac deveria "
            "estar mockado neste teste"
        )

    monkeypatch.setattr("builtins.input", _input_nao_deveria_ser_chamado)

    def _adicionar_ao_path_nao_deveria_ser_chamado(diretorio):
        pytest.fail(
            "adicionar_ao_path_usuario real foi chamado - nao pode tocar o "
            "registro do Windows em teste, deveria estar mockado"
        )

    monkeypatch.setattr(
        instalar_ffmpeg, "adicionar_ao_path_usuario", _adicionar_ao_path_nao_deveria_ser_chamado
    )


# ---------------------------------------------------------------------------
# Caminho feliz mais simples: ffmpeg ja disponivel desde o inicio
# ---------------------------------------------------------------------------


def test_cascata_quando_ffmpeg_ja_esta_disponivel_nao_tenta_nenhuma_instalacao(monkeypatch):
    monkeypatch.setattr(instalar_ffmpeg.robustez, "ffmpeg_disponivel", lambda: True)
    monkeypatch.setattr(
        instalar_ffmpeg, "tentativa_winget", lambda: pytest.fail("nao deveria tentar winget")
    )
    monkeypatch.setattr(
        instalar_ffmpeg, "tentativa_chocolatey", lambda: pytest.fail("nao deveria tentar chocolatey")
    )

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    assert resultado is True


# ---------------------------------------------------------------------------
# Cenario 1 — winget funciona e ffmpeg fica acessivel direto
# ---------------------------------------------------------------------------


def test_cascata_com_winget_funcionando_direto_retorna_true_sem_tentar_chocolatey(monkeypatch):
    monkeypatch.setattr(
        instalar_ffmpeg.robustez, "ffmpeg_disponivel", _sequencia_booleanos(False, True)
    )
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: True)
    monkeypatch.setattr(instalar_ffmpeg, "rodar", lambda comando: types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(
        instalar_ffmpeg, "tentativa_chocolatey", lambda: pytest.fail("nao deveria tentar chocolatey")
    )

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    assert resultado is True


# ---------------------------------------------------------------------------
# Cenario 2 — winget instala mas ffmpeg nao fica no PATH; busca encontra e
# corrige o PATH
# ---------------------------------------------------------------------------


def test_cascata_com_winget_instalado_fora_do_path_busca_encontra_e_ajusta_path(monkeypatch):
    monkeypatch.setattr(
        instalar_ffmpeg.robustez, "ffmpeg_disponivel", _sequencia_booleanos(False, False, True)
    )
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: True)
    monkeypatch.setattr(instalar_ffmpeg, "rodar", lambda comando: types.SimpleNamespace(returncode=0))

    caminho_encontrado = Path(
        "C:/Users/fake/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_x/ffmpeg-x/bin/ffmpeg.exe"
    )
    monkeypatch.setattr(
        instalar_ffmpeg, "buscar_ffmpeg_em_winget_packages", lambda: caminho_encontrado
    )

    chamadas_adicionar_path = []

    def _adicionar_ao_path_fake(diretorio):
        chamadas_adicionar_path.append(diretorio)

    monkeypatch.setattr(instalar_ffmpeg, "adicionar_ao_path_usuario", _adicionar_ao_path_fake)
    monkeypatch.setattr(
        instalar_ffmpeg, "tentativa_chocolatey", lambda: pytest.fail("nao deveria tentar chocolatey")
    )

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    assert resultado is True
    assert chamadas_adicionar_path == [caminho_encontrado.parent]


# ---------------------------------------------------------------------------
# Cenario 3 — winget instala, ffmpeg nao fica no PATH, busca NAO encontra
# -> cai pra chocolatey
# ---------------------------------------------------------------------------


def test_cascata_com_winget_instalado_e_busca_sem_sucesso_cai_para_chocolatey(monkeypatch):
    monkeypatch.setattr(
        instalar_ffmpeg.robustez, "ffmpeg_disponivel", _sequencia_booleanos(False, False)
    )
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: True)
    monkeypatch.setattr(instalar_ffmpeg, "rodar", lambda comando: types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(instalar_ffmpeg, "buscar_ffmpeg_em_winget_packages", lambda: None)

    chocolatey_chamado = {"valor": False}

    def _tentativa_chocolatey_fake():
        chocolatey_chamado["valor"] = True
        return True

    monkeypatch.setattr(instalar_ffmpeg, "tentativa_chocolatey", _tentativa_chocolatey_fake)

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    assert resultado is True
    assert chocolatey_chamado["valor"] is True


# ---------------------------------------------------------------------------
# Cenario 4 — chocolatey ja instalado nao deve pedir confirmacao de UAC
# ---------------------------------------------------------------------------


def test_tentativa_chocolatey_ja_instalado_nao_pede_confirmacao_de_uac(monkeypatch):
    monkeypatch.setattr(instalar_ffmpeg, "chocolatey_disponivel", lambda: True)
    monkeypatch.setattr(
        instalar_ffmpeg,
        "confirmar_continuar_com_uac",
        lambda: pytest.fail(
            "nao deveria pedir confirmacao de UAC quando chocolatey ja esta instalado"
        ),
    )

    elevado_chamado = {"valor": False}

    def _instalar_elevado_fake():
        elevado_chamado["valor"] = True
        return True

    monkeypatch.setattr(instalar_ffmpeg, "instalar_chocolatey_e_ffmpeg_elevado", _instalar_elevado_fake)
    monkeypatch.setattr(instalar_ffmpeg.robustez, "ffmpeg_disponivel", lambda: True)

    resultado = instalar_ffmpeg.tentativa_chocolatey()

    assert resultado is True
    assert elevado_chamado["valor"] is True


# ---------------------------------------------------------------------------
# Cenario 5 — chocolatey nao instalado, usuario aceita UAC
# ---------------------------------------------------------------------------


def test_tentativa_chocolatey_nao_instalado_com_uac_aceito_instala_com_sucesso(monkeypatch):
    monkeypatch.setattr(instalar_ffmpeg, "chocolatey_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "confirmar_continuar_com_uac", lambda: True)
    monkeypatch.setattr(instalar_ffmpeg, "instalar_chocolatey_e_ffmpeg_elevado", lambda: True)
    monkeypatch.setattr(instalar_ffmpeg.robustez, "ffmpeg_disponivel", lambda: True)

    resultado = instalar_ffmpeg.tentativa_chocolatey()

    assert resultado is True


# ---------------------------------------------------------------------------
# Cenario 6 — chocolatey nao instalado, usuario nega UAC
# ---------------------------------------------------------------------------


def test_tentativa_chocolatey_nao_instalado_com_uac_negado_nao_instala_nada(monkeypatch):
    monkeypatch.setattr(instalar_ffmpeg, "chocolatey_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "confirmar_continuar_com_uac", lambda: False)
    monkeypatch.setattr(
        instalar_ffmpeg,
        "instalar_chocolatey_e_ffmpeg_elevado",
        lambda: pytest.fail("nao deveria instalar chocolatey elevado se o usuario negou o UAC"),
    )

    resultado = instalar_ffmpeg.tentativa_chocolatey()

    assert resultado is False


def test_cascata_completa_com_uac_negado_termina_mostrando_instrucao_manual(monkeypatch):
    """Cenario 6, ponta a ponta: winget indisponivel, chocolatey nao
    instalado e usuario nega o UAC -> cascata inteira cai pra instrucao
    manual (nao trava, nao insiste, nao finge sucesso)."""
    monkeypatch.setattr(instalar_ffmpeg.robustez, "ffmpeg_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "chocolatey_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "confirmar_continuar_com_uac", lambda: False)
    monkeypatch.setattr(
        instalar_ffmpeg,
        "instalar_chocolatey_e_ffmpeg_elevado",
        lambda: pytest.fail("nao deveria instalar chocolatey elevado se o usuario negou o UAC"),
    )

    instrucao_manual_chamada = {"valor": False}

    def _mostrar_instrucao_manual_fake():
        instrucao_manual_chamada["valor"] = True

    monkeypatch.setattr(instalar_ffmpeg, "mostrar_instrucao_manual", _mostrar_instrucao_manual_fake)

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    assert resultado is False
    assert instrucao_manual_chamada["valor"] is True


# ---------------------------------------------------------------------------
# Cenario 7 — winget nao disponivel no sistema
# ---------------------------------------------------------------------------


def test_tentativa_winget_quando_winget_nao_esta_disponivel_nao_chama_rodar(monkeypatch):
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: False)
    monkeypatch.setattr(
        instalar_ffmpeg, "rodar", lambda comando: pytest.fail("nao deveria chamar rodar()")
    )
    monkeypatch.setattr(
        instalar_ffmpeg,
        "instalar_via_winget",
        lambda: pytest.fail("nao deveria chamar instalar_via_winget()"),
    )

    resultado = instalar_ffmpeg.tentativa_winget()

    assert resultado is False


def test_cascata_pula_direto_para_chocolatey_quando_winget_nao_esta_disponivel(monkeypatch):
    monkeypatch.setattr(instalar_ffmpeg.robustez, "ffmpeg_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: False)
    monkeypatch.setattr(
        instalar_ffmpeg, "rodar", lambda comando: pytest.fail("nao deveria chamar rodar() para winget")
    )

    chocolatey_chamado = {"valor": False}

    def _tentativa_chocolatey_fake():
        chocolatey_chamado["valor"] = True
        return True

    monkeypatch.setattr(instalar_ffmpeg, "tentativa_chocolatey", _tentativa_chocolatey_fake)

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    assert resultado is True
    assert chocolatey_chamado["valor"] is True


# ---------------------------------------------------------------------------
# Cenario 8 — tudo falha (winget instala mas retorna erro, chocolatey nao
# instalado e UAC negado) -> cascata retorna False e mostra instrucao manual
# ---------------------------------------------------------------------------


def test_cascata_com_tudo_falhando_retorna_false_e_mostra_instrucao_manual(monkeypatch, capsys):
    monkeypatch.setattr(instalar_ffmpeg.robustez, "ffmpeg_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "winget_disponivel", lambda: True)
    # winget "roda" mas falha (returncode != 0) - instalar_via_winget()
    # deve reportar False sem propagar excecao nem checar ffmpeg de novo.
    monkeypatch.setattr(instalar_ffmpeg, "rodar", lambda comando: types.SimpleNamespace(returncode=1))
    monkeypatch.setattr(instalar_ffmpeg, "chocolatey_disponivel", lambda: False)
    monkeypatch.setattr(instalar_ffmpeg, "confirmar_continuar_com_uac", lambda: False)
    monkeypatch.setattr(
        instalar_ffmpeg,
        "instalar_chocolatey_e_ffmpeg_elevado",
        lambda: pytest.fail("nao deveria instalar chocolatey elevado se o usuario negou o UAC"),
    )

    resultado = instalar_ffmpeg.instalar_ffmpeg_cascata()

    saida = capsys.readouterr().out
    assert resultado is False
    assert "gyan.dev/ffmpeg/builds" in saida
