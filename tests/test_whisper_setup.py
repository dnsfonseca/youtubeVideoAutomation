"""Testes de scripts/whisper_setup.py - registro de DLLs cuBLAS/cuDNN no
PATH do processo, necessario pro faster-whisper carregar no Windows
(CLAUDE.md secao 4/18.9).

Extraido de scripts/2_transcrever.py na Sessao 8.1-fix e reusado por
scripts/4_obter_audio.py - nunca chama faster-whisper real (CLAUDE.md
secao 8), so exercita a logica de PATH com pastas/spec fakes.
"""

import importlib.util

import pytest

from scripts import whisper_setup


def test_registrar_dlls_cuda_fora_do_windows_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(whisper_setup.sys, "platform", "linux")
    path_original = whisper_setup.os.environ.get("PATH", "")

    whisper_setup.registrar_dlls_cuda()

    assert whisper_setup.os.environ.get("PATH", "") == path_original


def test_registrar_dlls_cuda_sem_pacote_nvidia_instalado_nao_falha(monkeypatch):
    monkeypatch.setattr(whisper_setup.sys, "platform", "win32")
    monkeypatch.setattr(importlib.util, "find_spec", lambda nome: None)
    path_original = whisper_setup.os.environ.get("PATH", "")

    whisper_setup.registrar_dlls_cuda()

    assert whisper_setup.os.environ.get("PATH", "") == path_original


def test_registrar_dlls_cuda_prepende_pastas_bin_ao_path(tmp_path, monkeypatch):
    pasta_nvidia = tmp_path / "nvidia"
    (pasta_nvidia / "cublas" / "bin").mkdir(parents=True)
    (pasta_nvidia / "cudnn" / "bin").mkdir(parents=True)

    class _SpecFake:
        submodule_search_locations = [str(pasta_nvidia)]

    monkeypatch.setattr(whisper_setup.sys, "platform", "win32")
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda nome: _SpecFake() if nome == "nvidia" else None
    )
    monkeypatch.setattr(whisper_setup.os, "environ", {"PATH": r"C:\ja_existia"})
    if hasattr(whisper_setup.os, "add_dll_directory"):
        monkeypatch.setattr(whisper_setup.os, "add_dll_directory", lambda caminho: None)

    whisper_setup.registrar_dlls_cuda()

    path_final = whisper_setup.os.environ["PATH"]
    assert str(pasta_nvidia / "cublas" / "bin") in path_final
    assert str(pasta_nvidia / "cudnn" / "bin") in path_final
    assert r"C:\ja_existia" in path_final


def test_registrar_dlls_cuda_e_idempotente(tmp_path, monkeypatch):
    pasta_nvidia = tmp_path / "nvidia"
    (pasta_nvidia / "cublas" / "bin").mkdir(parents=True)

    class _SpecFake:
        submodule_search_locations = [str(pasta_nvidia)]

    monkeypatch.setattr(whisper_setup.sys, "platform", "win32")
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda nome: _SpecFake() if nome == "nvidia" else None
    )
    monkeypatch.setattr(whisper_setup.os, "environ", {"PATH": r"C:\ja_existia"})
    if hasattr(whisper_setup.os, "add_dll_directory"):
        monkeypatch.setattr(whisper_setup.os, "add_dll_directory", lambda caminho: None)

    whisper_setup.registrar_dlls_cuda()
    whisper_setup.registrar_dlls_cuda()

    path_final = whisper_setup.os.environ["PATH"]
    assert str(pasta_nvidia / "cublas" / "bin") in path_final
    assert r"C:\ja_existia" in path_final
