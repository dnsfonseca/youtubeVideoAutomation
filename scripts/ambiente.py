"""Deteccao de ambiente NVIDIA/CUDA (CLAUDE.md secao 13 - Requisitos minimos
oficiais do produto).

Modulo autocontido, sem depender de faster-whisper nem de nenhuma outra lib
do projeto (so `subprocess`/`re` da stdlib) - precisa poder rodar mesmo
antes de "pip install -r requirements.txt" ter sido executado, porque
server.py chama isto no boot do Flask (antes de qualquer coisa pesada estar
instalada) e scripts/2_transcrever.py chama de novo no proprio inicio
(CLAUDE.md secao 18.6 - validar pre-condicoes antes de processar).

Requisitos minimos oficiais (fixados nesta sessao):
- Windows 10/11 x64
- GPU NVIDIA, Compute Capability 6.0+ (Pascal ou mais novo)
- 4 GB VRAM minimo
- Driver NVIDIA suportando CUDA 12+
- GPUs AMD/Intel e CPU-only NAO sao suportadas - refuso duro.

Nenhuma funcao aqui levanta excecao por ambiente incompativel/nvidia-smi
ausente - a checagem de robustez roda no boot do servidor e nao pode
derrubar o processo (mesmo espirito de scripts/robustez.py).
"""

import re
import subprocess

VRAM_MINIMA_MB = 4096
COMPUTE_CAPABILITY_MINIMA = 6.0
CUDA_MINIMO = 12

TIMEOUT_NVIDIA_SMI_S = 10

COMANDO_NVIDIA_SMI_QUERY = [
    "nvidia-smi",
    "--query-gpu=name,memory.total,driver_version,compute_cap",
    "--format=csv,noheader,nounits",
]

# nvidia-smi so expoe a versao maxima de CUDA que o driver instalado
# suporta ("cuda_umd_version") no cabecalho da tabela padrao, nao no modo
# --query-gpu usado acima - por isso uma segunda chamada, sem argumentos,
# e' necessaria. O rotulo mudou entre versoes do nvidia-smi: drivers mais
# antigos imprimem "CUDA Version: X.Y", drivers recentes (ex: 610.62,
# confirmado numa RTX 3070 Ti de verdade nesta sessao) imprimem
# "CUDA UMD Version: X.Y" - o regex aceita os dois.
COMANDO_NVIDIA_SMI_COMPLETO = ["nvidia-smi"]

PADRAO_CUDA_VERSION = re.compile(r"CUDA(?: UMD)? Version:\s*([\d.]+)")


def _extrair_cuda_version(saida_completa: str):
    m = PADRAO_CUDA_VERSION.search(saida_completa or "")
    return m.group(1) if m else None


def _rodar_nvidia_smi(comando):
    """Executa um comando nvidia-smi. Retorna o CompletedProcess, ou None se
    nvidia-smi nao existe ou a chamada falhar por qualquer motivo (nunca
    levanta excecao)."""
    try:
        return subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_NVIDIA_SMI_S,
        )
    except (subprocess.SubprocessError, OSError):
        return None


def detectar_gpu() -> dict:
    """Detecta a GPU NVIDIA presente via nvidia-smi.

    Retorna um dict no schema:
        {"presente": bool, "modelo": str|None, "vram_mb": int|None,
         "driver_version": str|None, "compute_capability": str|None,
         "cuda_umd_version": str|None, "erro": str|None}

    Nunca levanta excecao - qualquer falha de deteccao vira campo "erro"
    com "presente": False.
    """
    base = {
        "presente": False,
        "modelo": None,
        "vram_mb": None,
        "driver_version": None,
        "compute_capability": None,
        "cuda_umd_version": None,
        "erro": None,
    }

    resultado = _rodar_nvidia_smi(COMANDO_NVIDIA_SMI_QUERY)
    if resultado is None:
        base["erro"] = "nvidia-smi nao encontrado. Driver NVIDIA nao instalado."
        return base

    if resultado.returncode != 0 or not (resultado.stdout or "").strip():
        base["erro"] = (
            (resultado.stderr or "").strip()
            or "nvidia-smi nao retornou dados de GPU."
        )
        return base

    primeira_linha = resultado.stdout.strip().splitlines()[0]
    partes = [p.strip() for p in primeira_linha.split(",")]
    if len(partes) < 4:
        base["erro"] = f"Saida inesperada do nvidia-smi: {primeira_linha}"
        return base

    nome, vram_str, driver_version, compute_cap = partes[:4]
    try:
        vram_mb = int(float(vram_str))
    except ValueError:
        vram_mb = None

    base.update(
        {
            "presente": True,
            "modelo": nome,
            "vram_mb": vram_mb,
            "driver_version": driver_version,
            "compute_capability": compute_cap,
        }
    )

    resultado_completo = _rodar_nvidia_smi(COMANDO_NVIDIA_SMI_COMPLETO)
    if resultado_completo is not None:
        base["cuda_umd_version"] = _extrair_cuda_version(resultado_completo.stdout)

    return base


def _compute_cap_float(valor):
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _cuda_major(valor):
    if valor is None:
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def modelos_suportados_por_vram(vram_mb) -> list:
    """Modelos do faster-whisper suportados por uma GPU com `vram_mb` MB de
    VRAM total (CLAUDE.md secao 13 - faixas de VRAM por modelo)."""
    if vram_mb is None or vram_mb < VRAM_MINIMA_MB:
        return []
    if vram_mb < 6144:
        return ["small"]
    if vram_mb < 8192:
        return ["small", "medium"]
    return ["small", "medium", "large-v3"]


def recomendar_modelo(gpu: dict) -> str:
    """Melhor modelo default do faster-whisper para a GPU detectada.

    8 GB+ recomenda "medium" (nao "large-v3") de proposito - fica no
    meio-termo de performance/qualidade; o usuario pode escolher
    manualmente large-v3 se quiser (CLAUDE.md secao 13)."""
    vram_mb = gpu.get("vram_mb")
    if vram_mb is not None and vram_mb >= 6144:
        return "medium"
    return "small"


def avaliar_compatibilidade(gpu: dict) -> dict:
    """Avalia se a GPU detectada atende aos requisitos minimos oficiais do
    produto (CLAUDE.md secao 13).

    Retorna:
        {"atende_minimo": bool, "problema": str|None, "mensagem": str,
         "modelos_suportados": list}
    """
    if not gpu.get("presente"):
        return {
            "atende_minimo": False,
            "problema": "sem_gpu",
            "mensagem": gpu.get("erro")
            or "Nenhuma GPU NVIDIA detectada. O Broll Foundry requer GPU "
            "NVIDIA com 4GB+ VRAM e driver CUDA 12+.",
            "modelos_suportados": [],
        }

    modelo_gpu = gpu.get("modelo") or "GPU detectada"
    vram_mb = gpu.get("vram_mb")

    if vram_mb is None or vram_mb < VRAM_MINIMA_MB:
        return {
            "atende_minimo": False,
            "problema": "vram_baixa",
            "mensagem": (
                f"{modelo_gpu} tem {vram_mb if vram_mb is not None else '?'} MB "
                f"de VRAM - o minimo exigido e' {VRAM_MINIMA_MB} MB (4 GB)."
            ),
            "modelos_suportados": [],
        }

    compute_cap = _compute_cap_float(gpu.get("compute_capability"))
    if compute_cap is None or compute_cap < COMPUTE_CAPABILITY_MINIMA:
        return {
            "atende_minimo": False,
            "problema": "compute_cap_antiga",
            "mensagem": (
                f"{modelo_gpu} tem Compute Capability "
                f"{gpu.get('compute_capability') or '?'} - o minimo exigido "
                f"e' {COMPUTE_CAPABILITY_MINIMA} (Pascal ou mais novo)."
            ),
            "modelos_suportados": [],
        }

    cuda_major = _cuda_major(gpu.get("cuda_umd_version"))
    if cuda_major is None or cuda_major < CUDA_MINIMO:
        return {
            "atende_minimo": False,
            "problema": "cuda_antigo",
            "mensagem": (
                f"Driver da {modelo_gpu} suporta CUDA "
                f"{gpu.get('cuda_umd_version') or 'desconhecido'} - o minimo "
                f"exigido e' CUDA {CUDA_MINIMO}. Atualize o driver NVIDIA."
            ),
            "modelos_suportados": [],
        }

    return {
        "atende_minimo": True,
        "problema": None,
        "mensagem": f"Ambiente compativel: {modelo_gpu} ({vram_mb} MB VRAM).",
        "modelos_suportados": modelos_suportados_por_vram(vram_mb),
    }
