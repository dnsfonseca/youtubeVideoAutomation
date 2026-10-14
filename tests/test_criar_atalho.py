"""Testes de scripts/criar_atalho.py.

Nunca cria atalho de verdade nem toca a area de trabalho real do usuario
que roda a suite - win32com e' sempre mockado (CLAUDE.md secao 8: nunca
bater sistema externo real em teste, e isso vale a fortiori para "gravar
arquivo na area de trabalho do usuario que esta rodando o pytest").
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import criar_atalho  # noqa: E402


def test_falha_com_mensagem_clara_se_pywin32_ausente(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _import_bloqueando_win32com(name, *args, **kwargs):
        if name == "win32com.client":
            raise ImportError("No module named 'win32com'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_bloqueando_win32com)

    assert criar_atalho.criar_atalho_windows() is False


def test_falha_se_iniciar_bat_nao_existir(monkeypatch, tmp_path):
    fake_win32com_client = MagicMock()
    monkeypatch.setitem(sys.modules, "win32com.client", fake_win32com_client)

    caminho_falso = tmp_path / "scripts" / "criar_atalho.py"
    caminho_falso.parent.mkdir(parents=True)
    caminho_falso.write_text("", encoding="utf-8")

    monkeypatch.setattr(criar_atalho, "__file__", str(caminho_falso))

    assert criar_atalho.criar_atalho_windows() is False


def test_cria_atalho_com_sucesso_quando_tudo_disponivel(monkeypatch, tmp_path):
    projeto_raiz = tmp_path / "broll_foundry"
    scripts_dir = projeto_raiz / "scripts"
    scripts_dir.mkdir(parents=True)
    (projeto_raiz / "iniciar.bat").write_text("@echo off", encoding="utf-8")

    monkeypatch.setattr(criar_atalho, "__file__", str(scripts_dir / "criar_atalho.py"))

    fake_shortcut = MagicMock()
    fake_shell = MagicMock()
    fake_shell.CreateShortCut.return_value = fake_shortcut
    fake_win32com_client = MagicMock()
    fake_win32com_client.Dispatch.return_value = fake_shell

    fake_win32com = MagicMock()
    fake_win32com.client = fake_win32com_client
    monkeypatch.setitem(sys.modules, "win32com", fake_win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", fake_win32com_client)

    resultado = criar_atalho.criar_atalho_windows()

    assert resultado is True
    fake_shortcut.save.assert_called_once()
    assert fake_shortcut.Targetpath == str(projeto_raiz / "iniciar.bat")
