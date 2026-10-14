"""Testes de scripts/ambiente.py - deteccao de ambiente NVIDIA/CUDA e
avaliacao contra os requisitos minimos oficiais do produto (CLAUDE.md
secao 13).

Nenhum teste aqui chama nvidia-smi de verdade - subprocess.run e' sempre
mockado (CLAUDE.md secao 8), inclusive porque a maquina que roda o Claude
Code nao tem GPU.
"""

import subprocess

import pytest

from scripts import ambiente


class _ProcessoFake:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ---------------------------------------------------------------------------
# detectar_gpu
# ---------------------------------------------------------------------------


def test_detectar_gpu_com_nvidia_smi_disponivel_retorna_dados_completos(monkeypatch):
    def _run_fake(comando, **kwargs):
        if "--query-gpu=name,memory.total,driver_version,compute_cap" in comando:
            return _ProcessoFake(
                stdout="NVIDIA GeForce RTX 3070 Ti, 8192, 560.94, 8.6\n", returncode=0
            )
        return _ProcessoFake(
            stdout=(
                "+-----------------------------------------------------------------------------+\n"
                "| NVIDIA-SMI 560.94       Driver Version: 560.94       CUDA Version: 12.6     |\n"
                "+-----------------------------------------------------------------------------+\n"
            ),
            returncode=0,
        )

    monkeypatch.setattr(ambiente.subprocess, "run", _run_fake)

    resultado = ambiente.detectar_gpu()

    assert resultado == {
        "presente": True,
        "modelo": "NVIDIA GeForce RTX 3070 Ti",
        "vram_mb": 8192,
        "driver_version": "560.94",
        "compute_capability": "8.6",
        "cuda_umd_version": "12.6",
        "erro": None,
    }


def test_detectar_gpu_sem_nvidia_smi_instalado(monkeypatch):
    def _run_levanta_file_not_found(comando, **kwargs):
        raise FileNotFoundError("nvidia-smi nao encontrado")

    monkeypatch.setattr(ambiente.subprocess, "run", _run_levanta_file_not_found)

    resultado = ambiente.detectar_gpu()

    assert resultado["presente"] is False
    assert "nvidia-smi" in resultado["erro"]
    assert "nao instalado" in resultado["erro"] or "não instalado" in resultado["erro"]


def test_detectar_gpu_com_nvidia_smi_retornando_codigo_de_erro(monkeypatch):
    def _run_fake(comando, **kwargs):
        return _ProcessoFake(stdout="", stderr="No devices were found", returncode=6)

    monkeypatch.setattr(ambiente.subprocess, "run", _run_fake)

    resultado = ambiente.detectar_gpu()

    assert resultado["presente"] is False
    assert "No devices were found" in resultado["erro"]


def test_detectar_gpu_com_timeout_nao_propaga_excecao(monkeypatch):
    def _run_levanta_timeout(comando, **kwargs):
        raise subprocess.TimeoutExpired(cmd=comando, timeout=10)

    monkeypatch.setattr(ambiente.subprocess, "run", _run_levanta_timeout)

    resultado = ambiente.detectar_gpu()

    assert resultado["presente"] is False
    assert resultado["erro"]


def test_detectar_gpu_com_saida_inesperada_do_query_nao_crasha(monkeypatch):
    def _run_fake(comando, **kwargs):
        return _ProcessoFake(stdout="algo estranho sem virgulas\n", returncode=0)

    monkeypatch.setattr(ambiente.subprocess, "run", _run_fake)

    resultado = ambiente.detectar_gpu()

    assert resultado["presente"] is False
    assert resultado["erro"]


def test_detectar_gpu_com_rotulo_cuda_umd_version_driver_recente(monkeypatch):
    """Drivers NVIDIA recentes (ex: 610.62 - confirmado numa RTX 3070 Ti de
    verdade durante o desenvolvimento desta sessao) rotulam a linha como
    "CUDA UMD Version:", nao "CUDA Version:" (formato de drivers antigos) -
    o parser tem que aceitar os dois."""

    def _run_fake(comando, **kwargs):
        if "--query-gpu=name,memory.total,driver_version,compute_cap" in comando:
            return _ProcessoFake(
                stdout="NVIDIA GeForce RTX 3070 Ti, 8192, 610.62, 8.6\n", returncode=0
            )
        return _ProcessoFake(
            stdout=(
                "+-----------------------------------------------------------------------------------------+\n"
                "| NVIDIA-SMI 610.62                 KMD Version: 610.62        CUDA UMD Version: 13.3     |\n"
                "+-----------------------------------------------------------------------------------------+\n"
            ),
            returncode=0,
        )

    monkeypatch.setattr(ambiente.subprocess, "run", _run_fake)

    resultado = ambiente.detectar_gpu()

    assert resultado["cuda_umd_version"] == "13.3"
    compat = ambiente.avaliar_compatibilidade(resultado)
    assert compat["atende_minimo"] is True


def test_detectar_gpu_sem_cuda_version_na_segunda_chamada_mantem_none(monkeypatch):
    def _run_fake(comando, **kwargs):
        if "--query-gpu=name,memory.total,driver_version,compute_cap" in comando:
            return _ProcessoFake(
                stdout="NVIDIA GeForce GTX 1060, 6144, 470.00, 6.1\n", returncode=0
            )
        return _ProcessoFake(stdout="saida sem a linha de CUDA Version", returncode=0)

    monkeypatch.setattr(ambiente.subprocess, "run", _run_fake)

    resultado = ambiente.detectar_gpu()

    assert resultado["presente"] is True
    assert resultado["cuda_umd_version"] is None


# ---------------------------------------------------------------------------
# avaliar_compatibilidade
# ---------------------------------------------------------------------------


def _gpu(**overrides):
    base = {
        "presente": True,
        "modelo": "NVIDIA GeForce RTX 3070 Ti",
        "vram_mb": 8192,
        "driver_version": "560.94",
        "compute_capability": "8.6",
        "cuda_umd_version": "12.6",
        "erro": None,
    }
    base.update(overrides)
    return base


def test_avaliar_compatibilidade_ambiente_ok():
    resultado = ambiente.avaliar_compatibilidade(_gpu())

    assert resultado["atende_minimo"] is True
    assert resultado["problema"] is None
    assert resultado["modelos_suportados"] == ["small", "medium", "large-v3"]


def test_avaliar_compatibilidade_sem_gpu():
    gpu = {
        "presente": False,
        "modelo": None,
        "vram_mb": None,
        "driver_version": None,
        "compute_capability": None,
        "cuda_umd_version": None,
        "erro": "nvidia-smi nao encontrado. Driver NVIDIA nao instalado.",
    }

    resultado = ambiente.avaliar_compatibilidade(gpu)

    assert resultado["atende_minimo"] is False
    assert resultado["problema"] == "sem_gpu"
    assert resultado["modelos_suportados"] == []


def test_avaliar_compatibilidade_vram_baixa():
    resultado = ambiente.avaliar_compatibilidade(_gpu(vram_mb=2048))

    assert resultado["atende_minimo"] is False
    assert resultado["problema"] == "vram_baixa"
    assert resultado["modelos_suportados"] == []


def test_avaliar_compatibilidade_compute_capability_antiga():
    # GTX 780 - Kepler, compute capability 3.5 - abaixo do minimo (6.0).
    resultado = ambiente.avaliar_compatibilidade(
        _gpu(modelo="NVIDIA GeForce GTX 780", compute_capability="3.5")
    )

    assert resultado["atende_minimo"] is False
    assert resultado["problema"] == "compute_cap_antiga"
    assert resultado["modelos_suportados"] == []


def test_avaliar_compatibilidade_cuda_antigo():
    resultado = ambiente.avaliar_compatibilidade(_gpu(cuda_umd_version="11.8"))

    assert resultado["atende_minimo"] is False
    assert resultado["problema"] == "cuda_antigo"
    assert resultado["modelos_suportados"] == []


def test_avaliar_compatibilidade_cuda_desconhecido_nao_atende():
    resultado = ambiente.avaliar_compatibilidade(_gpu(cuda_umd_version=None))

    assert resultado["atende_minimo"] is False
    assert resultado["problema"] == "cuda_antigo"


# ---------------------------------------------------------------------------
# recomendar_modelo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vram_mb,modelo_esperado",
    [
        (4096, "small"),
        (5900, "small"),
        (6144, "medium"),
        (7900, "medium"),
        (8192, "medium"),
        (12288, "medium"),
    ],
)
def test_recomendar_modelo_por_faixa_de_vram(vram_mb, modelo_esperado):
    resultado = ambiente.recomendar_modelo(_gpu(vram_mb=vram_mb))

    assert resultado == modelo_esperado


def test_recomendar_modelo_sem_vram_conhecida_cai_para_small():
    resultado = ambiente.recomendar_modelo(_gpu(vram_mb=None))

    assert resultado == "small"


# ---------------------------------------------------------------------------
# modelos_suportados_por_vram
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vram_mb,modelos_esperados",
    [
        (2048, []),
        (4096, ["small"]),
        (5900, ["small"]),
        (6144, ["small", "medium"]),
        (7900, ["small", "medium"]),
        (8192, ["small", "medium", "large-v3"]),
        (16384, ["small", "medium", "large-v3"]),
    ],
)
def test_modelos_suportados_por_vram_por_faixa(vram_mb, modelos_esperados):
    assert ambiente.modelos_suportados_por_vram(vram_mb) == modelos_esperados


def test_modelos_suportados_por_vram_none():
    assert ambiente.modelos_suportados_por_vram(None) == []
