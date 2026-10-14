"""Etapa 5 do pipeline (CLAUDE.md secao 5.7/5.8, consolidada) - substitui a
antiga cadeia de tres etapas (5_dividir_cenas.py + 6_montar_timeline.py +
7_renderizar_clipes.py) por um unico script que gera os clipes finais por
SELECAO ALEATORIA de trechos das fontes, sem deteccao de cena
(PySceneDetect), sem deduplicacao visual (pHash) e sem analise Vision.

Motivo da consolidacao (ver CLAUDE.md): testes empiricos mostraram
PySceneDetect levando 12+ minutos por video de 30min, rodando em CPU (nao
GPU), sem ganho de qualidade que compensasse a complexidade; Vision
opcional custou $0.82/video para descartar so' 5 de 82 cenas analisadas;
pHash nao agrupa duplicatas entre fontes diferentes (stock footage
compartilhado). Volta pra abordagem do projeto yt_automation (Gustavo
Xavier, GitHub) - selecao aleatoria de trechos, round-robin de fontes -
com duas protecoes adicionais que o yt_automation nao tem: margens de
seguranca no inicio/fim de cada fonte (evita intro/outro) e rastreamento
de intervalos ja usados por fonte (evita sobreposicao/duplicata dentro do
mesmo projeto).

Uso: python "scripts/5_gerar_clipes.py" <caminho_da_pasta_do_projeto>

Entrada:
- fontes/manifest_fontes.json (Etapa 1) - id/arquivo/duracao_s de cada
  fonte baixada com sucesso
- narracao_alinhamento.json (Etapa 4) - duracao_s da narracao gravada,
  que a selecao de clipes precisa cobrir
- entrada/marcas_dagua.json (formulario de Novo projeto, opcional) - mapa
  id_da_fonte -> posicao da marca d'agua a remover
- entrada/fontes_tipo_uso.json (formulario de Novo projeto, opcional -
  feature de fontes separadas) - mapa id_da_fonte -> "ambos"/"transcricao"/
  "visual". Fontes ausentes do mapa (ou arquivo inteiro ausente) sao
  tratadas como "ambos" - so' "transcricao" e' excluida da selecao de
  clipes aqui.

Saida:
- clipes/<clipe_id>.mp4 - um arquivo por clipe gerado, ja com Ken Burns e
  delogo aplicados
- clipes/indice.json - clipes renderizados com sucesso, na ordem final do
  video (contrato CLAUDE.md secao 6, consumido pela futura Etapa 8)

Este script e' autocontido (CLAUDE.md secao 9) - exceto por
scripts/robustez.py (checagem de ffmpeg no PATH) e
scripts/watermark_regions.py (coordenadas de delogo por posicao), infra
transversal (CLAUDE.md secao 18), nao logica de pipeline. As funcoes de
construcao/execucao do comando ffmpeg (Ken Burns, delogo, deteccao de
encoder GPU) foram trazidas de scripts/7_renderizar_clipes.py (removido
nesta consolidacao) sem alteracao de comportamento.
"""

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ precisa estar no sys.path para `import robustez`/`import
# watermark_regions` funcionarem tanto rodando este arquivo direto quanto
# carregado via importlib nos testes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robustez  # noqa: E402
from watermark_regions import gerar_filtro_delogo  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes - renderizacao (herdadas de 7_renderizar_clipes.py)
# ---------------------------------------------------------------------------

KEN_BURNS_PADRAO = True
LARGURA_FINAL = 1920
ALTURA_FINAL = 1080
FPS_FINAL = 30
PRESET_X264 = "veryfast"

# Zoom maximo do Ken Burns, distribuido ao longo de toda a duracao do
# clipe - nunca "vibrando" numa cena curta.
KEN_BURNS_ZOOM_MAXIMO = 1.10

# Piso minimo de frames do zoompan - evita o zoom "parar" cedo demais numa
# cena de fracoes de segundo (ver docstring de construir_filtro_ken_burns).
KEN_BURNS_FRAMES_MINIMO = 30

# Extensoes tratadas como imagem estatica (nao video) - nenhuma fonte
# atual do pipeline e' imagem (yt-dlp so' baixa video), mas o pipeline
# aceita fontes assim no futuro sem exigir mudanca de codigo.
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# h264_nvenc (GPU NVIDIA) e' muito mais rapido que libx264 (CPU) quando
# disponivel. Deteccao acontece uma vez por execucao de gerar_clipes.
ENCODER_PADRAO = "libx264"

TIMEOUT_POR_CLIPE_S = 60

# ---------------------------------------------------------------------------
# Constantes - selecao aleatoria de trechos (padrao yt_automation, com
# margens e anti-sobreposicao adicionadas - CLAUDE.md)
# ---------------------------------------------------------------------------

# Duracao alvo de cada clipe gerado, em segundos - sorteada uniformemente
# entre estes limites para cada slot da narracao.
CLIPE_DURACAO_MIN_S_PADRAO = 6.0
CLIPE_DURACAO_MAX_S_PADRAO = 10.0

# Margens de seguranca no inicio/fim de cada fonte - evita cair em
# intro/outro/patrocinio do video-fonte.
MARGEM_INICIO_S_PADRAO = 30.0
MARGEM_FIM_S_PADRAO = 30.0

# Tentativas de sortear um timestamp sem sobreposicao numa mesma fonte
# antes de considera-la saturada para o slot atual e pular pra proxima
# fonte no round-robin.
MAX_TENTATIVAS_POR_SLOT = 5

# ---------------------------------------------------------------------------
# Constantes - fontes visuais enviadas por upload (feature de fontes
# separadas)
# ---------------------------------------------------------------------------

# Video de upload com duracao <= este limite e' usado INTEIRO no clipe (nao
# so' uma janela do tamanho do slot) - e' tipicamente um b-roll curto que o
# usuario preparou pra aparecer completo, nao pra ser recortado ao acaso.
LIMITE_VIDEO_INTEIRO_UPLOAD_S = 30.0

# Duracao "de mentira" usada so' para a etapa de SELECAO de janela (nunca
# para renderizar) de fontes que nao tem janela real - imagem (loop 1, dura
# o tempo do slot inteiro) e video de upload curto (renderizado inteiro,
# ignora a janela sorteada). Suficientemente grande pra nunca esbarrar nas
# margens de seguranca nem no calculo de sobreposicao.
DURACAO_SENTINELA_SELECAO_S = 1_000_000.0


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _ler_bool_env(nome: str, padrao: bool) -> bool:
    valor = os.environ.get(nome)
    if valor is None or valor == "":
        return padrao
    return valor.strip().lower() not in ("false", "0", "nao", "não", "off")


def _ler_float_env(nome: str, padrao: float) -> float:
    valor = os.environ.get(nome)
    if valor is None or valor == "":
        return padrao
    try:
        return float(valor)
    except ValueError:
        return padrao


def config_clipes() -> dict:
    return {
        "ken_burns": _ler_bool_env("KEN_BURNS", KEN_BURNS_PADRAO),
        "clipe_duracao_min_s": _ler_float_env("CLIPE_DURACAO_MIN_S", CLIPE_DURACAO_MIN_S_PADRAO),
        "clipe_duracao_max_s": _ler_float_env("CLIPE_DURACAO_MAX_S", CLIPE_DURACAO_MAX_S_PADRAO),
        "margem_inicio_s": _ler_float_env("MARGEM_INICIO_S", MARGEM_INICIO_S_PADRAO),
        "margem_fim_s": _ler_float_env("MARGEM_FIM_S", MARGEM_FIM_S_PADRAO),
    }


# ---------------------------------------------------------------------------
# Categorizacao de erros (CLAUDE.md secao 18.5)
# ---------------------------------------------------------------------------

_CATEGORIAS_ERRO_RENDER = [
    (
        "disco_cheio",
        lambda s: "no space left on device" in s or "disk full" in s or "enospc" in s,
    ),
    (
        "fonte_corrompida",
        lambda s: "invalid data found when processing input" in s
        or "moov atom not found" in s
        or "could not open file" in s
        or "ffprobe" in s,
    ),
]


def classificar_erro_renderizacao(stderr: str) -> tuple:
    """Classifica a stderr de um ffmpeg que falhou numa categoria
    conhecida, com mensagem amigavel. Cai em "ffmpeg_falhou" (generico) se
    nada bater com uma categoria mais especifica."""
    texto = (stderr or "").lower()
    for categoria, condicao in _CATEGORIAS_ERRO_RENDER:
        if condicao(texto):
            if categoria == "disco_cheio":
                return categoria, "Disco cheio - libere espaco e tente novamente."
            if categoria == "fonte_corrompida":
                return categoria, "Video-fonte corrompido ou ilegivel."
    trecho = (stderr or "").strip().splitlines()
    trecho = " | ".join(trecho[-3:]) if trecho else "sem detalhe"
    return "ffmpeg_falhou", f"ffmpeg falhou ao renderizar o clipe. Detalhe: {trecho[:200]}"


# ---------------------------------------------------------------------------
# Leitura de entrada
# ---------------------------------------------------------------------------


def _ler_tipo_uso_fontes(pasta_projeto: Path) -> dict:
    """Mapa id_da_fonte -> tipo_uso, lido de entrada/fontes_tipo_uso.json
    (feature de fontes separadas). Arquivo ausente (modo unificado, ou
    projeto anterior a esta feature) retorna {} - toda fonte cai no default
    "ambos" em `_ler_manifest_fontes` (retrocompatibilidade total)."""
    caminho = pasta_projeto / "entrada" / "fontes_tipo_uso.json"
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _ler_manifest_fontes(pasta_projeto: Path) -> dict:
    """Mapa id_da_fonte -> {"caminho": Path, "duracao_s": float, "origem":
    str}, lido de fontes/manifest_fontes.json (Etapa 1). So' inclui fontes
    baixadas com sucesso E com tipo_uso "ambos" ou "visual" (default "ambos"
    se ausente do mapa de entrada/fontes_tipo_uso.json - feature de fontes
    separadas, retrocompatibilidade total com projetos sem esse arquivo)."""
    caminho = pasta_projeto / "fontes" / "manifest_fontes.json"
    if not caminho.exists():
        return {}
    try:
        manifest = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    tipo_uso_por_id = _ler_tipo_uso_fontes(pasta_projeto)
    pasta_fontes = pasta_projeto / "fontes"
    resultado = {}
    for f in manifest.get("fontes", []):
        if not (f.get("sucesso") and f.get("id") and f.get("arquivo")):
            continue
        tipo_uso = tipo_uso_por_id.get(f["id"], "ambos")
        if tipo_uso not in ("ambos", "visual"):
            continue
        resultado[f["id"]] = {
            "caminho": pasta_fontes / f["arquivo"],
            "duracao_s": float(f.get("duracao_s") or 0.0),
            "origem": f.get("origem") or "youtube",
        }
    return resultado


def _ler_marcas_dagua(pasta_projeto: Path) -> dict:
    caminho = pasta_projeto / "entrada" / "marcas_dagua.json"
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _ler_duracao_narracao(pasta_projeto: Path):
    caminho = pasta_projeto / "narracao_alinhamento.json"
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dados.get("duracao_s")


# ---------------------------------------------------------------------------
# Planejamento de slots (funcao pura)
# ---------------------------------------------------------------------------


def calcular_plano_slots(duracao_narracao_s: float, clipe_min_s: float, clipe_max_s: float, rng: random.Random) -> list:
    """Divide a timeline da narracao em slots de duracao aleatoria entre
    `clipe_min_s` e `clipe_max_s`. O ultimo slot e' trimado pra caber
    exatamente na duracao da narracao; uma sobra menor que 2s e' ignorada
    (irrelevante pro resultado final)."""
    slots = []
    tempo_atual = 0.0
    while tempo_atual < duracao_narracao_s:
        duracao_alvo = rng.uniform(clipe_min_s, clipe_max_s)
        if tempo_atual + duracao_alvo > duracao_narracao_s:
            duracao_alvo = duracao_narracao_s - tempo_atual
            if duracao_alvo < 2.0:
                break
        slots.append(
            {
                "posicao_inicio_narracao_s": round(tempo_atual, 3),
                "duracao_alvo_s": round(duracao_alvo, 3),
            }
        )
        tempo_atual += duracao_alvo
    return slots


# ---------------------------------------------------------------------------
# Selecao de janela por fonte (funcoes puras - anti-sobreposicao,
# round-robin)
# ---------------------------------------------------------------------------


def _sortear_timestamp(duracao_fonte_s: float, duracao_clipe_s: float, margem_inicio_s: float, margem_fim_s: float, rng: random.Random):
    """Sorteia um timestamp de inicio valido dentro de `duracao_fonte_s`,
    respeitando as margens de seguranca. Retorna None se a fonte e' curta
    demais pra caber um clipe de `duracao_clipe_s` com as margens."""
    inicio_minimo = margem_inicio_s
    inicio_maximo = duracao_fonte_s - margem_fim_s - duracao_clipe_s

    if inicio_maximo <= inicio_minimo:
        return None

    return rng.uniform(inicio_minimo, inicio_maximo)


def _tem_sobreposicao(inicio: float, fim: float, intervalos: list) -> bool:
    """Verifica se [inicio, fim] sobrepoe algum intervalo ja usado dessa
    fonte."""
    for ini_existente, fim_existente in intervalos:
        if inicio < fim_existente and fim > ini_existente:
            return True
    return False


def _selecionar_janela_para_slot(
    duracao_alvo_s: float,
    ordem_fontes: list,
    cursor_inicial: int,
    duracoes_fontes: dict,
    intervalos_usados: dict,
    margem_inicio_s: float,
    margem_fim_s: float,
    rng: random.Random,
):
    """Escolhe (fonte_id, inicio_s, duracao_s, proximo_cursor) pra um
    slot, percorrendo `ordem_fontes` em round-robin a partir de
    `cursor_inicial`. Cada fonte ganha ate MAX_TENTATIVAS_POR_SLOT
    tentativas de timestamp sem sobreposicao; se todas falharem (ou a
    fonte for curta demais), pula pra proxima fonte no ciclo. Se NENHUMA
    fonte do round-robin inteiro produzir janela livre, aceita
    sobreposicao na primeira candidata viavel encontrada (fallback pra
    nunca travar o pipeline - CLAUDE.md secao 18). Retorna None so' se
    nenhuma fonte tem duracao suficiente pra caber o clipe, nem ignorando
    sobreposicao."""
    total_fontes = len(ordem_fontes)
    if total_fontes == 0:
        return None

    candidata_fallback = None

    for passo in range(total_fontes):
        indice = (cursor_inicial + passo) % total_fontes
        fonte_id = ordem_fontes[indice]
        duracao_fonte = duracoes_fontes.get(fonte_id, 0.0)

        for _tentativa in range(MAX_TENTATIVAS_POR_SLOT):
            inicio = _sortear_timestamp(duracao_fonte, duracao_alvo_s, margem_inicio_s, margem_fim_s, rng)
            if inicio is None:
                break

            fim = inicio + duracao_alvo_s
            if not _tem_sobreposicao(inicio, fim, intervalos_usados.get(fonte_id, [])):
                return fonte_id, round(inicio, 3), round(duracao_alvo_s, 3), (indice + 1) % total_fontes

            if candidata_fallback is None:
                candidata_fallback = (fonte_id, round(inicio, 3), round(duracao_alvo_s, 3), (indice + 1) % total_fontes)

    return candidata_fallback


# ---------------------------------------------------------------------------
# Construcao do comando ffmpeg (funcoes puras, trazidas de
# 7_renderizar_clipes.py sem alteracao de comportamento)
# ---------------------------------------------------------------------------


def construir_filtro_ken_burns(duracao_s: float, fps: int = FPS_FINAL) -> str:
    """Filtro `zoompan` do Ken Burns, com o zoom distribuido ao longo de
    TODA a duracao do clipe.

    Approach adapted from yt_automation project (Gustavo Xavier, GitHub) -
    app/ffmpeg_cmd.py."""
    frames = max(KEN_BURNS_FRAMES_MINIMO, round(duracao_s * fps))
    return (
        "zoompan="
        f"z='min(1+{KEN_BURNS_ZOOM_MAXIMO - 1:.2f}*on/{frames},{KEN_BURNS_ZOOM_MAXIMO})':d=1:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={LARGURA_FINAL}x{ALTURA_FINAL}:fps={fps}"
    )


def construir_cadeia_filtros(marca_dagua_posicao: str | None, duracao_s: float, ken_burns: bool) -> str:
    """Monta a cadeia de filtros do ffmpeg na ordem CRITICA: delogo
    (remove a marca ANTES do zoom, senao o zoompan amplia pixel morto) ->
    scale/crop (garante 1920x1080 sempre) -> Ken Burns (se ativo, por
    ultimo)."""
    filtros = []
    filtro_delogo = gerar_filtro_delogo(marca_dagua_posicao) if marca_dagua_posicao else None
    if filtro_delogo:
        filtros.append(filtro_delogo)
    filtros.append(f"scale={LARGURA_FINAL}:{ALTURA_FINAL}:force_original_aspect_ratio=increase")
    filtros.append(f"crop={LARGURA_FINAL}:{ALTURA_FINAL}")
    filtros.append(f"fps={FPS_FINAL}")
    if ken_burns:
        filtros.append(construir_filtro_ken_burns(duracao_s))
    return ",".join(filtros)


def _fonte_eh_imagem(caminho_fonte: Path) -> bool:
    return caminho_fonte.suffix.lower() in EXTENSOES_IMAGEM


def _metadata_selecao_fonte(dados_fonte: dict) -> tuple:
    """Decide como uma fonte participa da selecao de janela por slot
    (feature de fontes separadas - fontes visuais proprias do usuario nao
    tem "trecho aleatorio" fazendo sentido do mesmo jeito que um video-fonte
    longo do YouTube).

    Retorna (duracao_para_selecao_s, usar_fonte_inteira):
    - Imagem: duracao "de mentira" (DURACAO_SENTINELA_SELECAO_S) para nunca
      esbarrar em margem/sobreposicao - a duracao REAL do clipe renderizado
      e' a do slot (o `-loop 1 -t <duracao_do_slot>` do ffmpeg cuida disso,
      sem precisar de override aqui). `usar_fonte_inteira=False`.
    - Video de upload com duracao <= LIMITE_VIDEO_INTEIRO_UPLOAD_S: mesma
      duracao "de mentira" para a selecao (garante que a fonte e' sempre
      elegivel, ignorando margens), mas `usar_fonte_inteira=True` - quem
      chama tem que sobrescrever inicio_s=0.0 e duracao_s=duracao_real antes
      de renderizar.
    - Qualquer outra fonte (video do YouTube, ou video de upload longo):
      comportamento inalterado - duracao real, janela aleatoria normal.
    """
    caminho = dados_fonte["caminho"]
    duracao_real = dados_fonte["duracao_s"]

    if _fonte_eh_imagem(caminho):
        return DURACAO_SENTINELA_SELECAO_S, False

    usar_fonte_inteira = (
        dados_fonte.get("origem") == "upload" and 0 < duracao_real <= LIMITE_VIDEO_INTEIRO_UPLOAD_S
    )
    if usar_fonte_inteira:
        return DURACAO_SENTINELA_SELECAO_S, True

    return duracao_real, False


def _params_encoder(encoder: str) -> list:
    """Parametros de encoding especificos do encoder escolhido. `h264_nvenc`
    (GPU NVIDIA) troca preset/CRF de libx264 pelos equivalentes NVENC -
    `-preset p4` (equilibrio velocidade/qualidade), `-tune hq`, `-rc vbr` +
    `-cq 23` (qualidade constante, 18-28 e' a faixa tipica)."""
    if encoder == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "23",
            "-pix_fmt", "yuv420p",
        ]
    return [
        "-c:v", "libx264",
        "-preset", PRESET_X264,
        "-pix_fmt", "yuv420p",
    ]


def construir_comando_ffmpeg(
    caminho_fonte: Path,
    inicio_s: float,
    duracao_s: float,
    caminho_saida: Path,
    marca_dagua_posicao: str | None = None,
    ken_burns: bool = True,
    encoder: str = ENCODER_PADRAO,
    eh_imagem: bool = False,
) -> list:
    """Monta o comando ffmpeg de renderizacao de um unico clipe (funcao
    pura, sem subprocess). `-ss` sempre ANTES de `-i` (seek rapido - pula
    direto no timestamp em vez de decodificar desde o inicio)."""
    filtro_video = construir_cadeia_filtros(marca_dagua_posicao, duracao_s, ken_burns)
    comando = ["ffmpeg", "-hide_banner", "-y"]
    if eh_imagem:
        comando += ["-loop", "1", "-t", f"{duracao_s:.3f}", "-i", str(caminho_fonte)]
    else:
        comando += ["-ss", f"{inicio_s:.3f}", "-t", f"{duracao_s:.3f}", "-i", str(caminho_fonte)]
    comando += ["-an", "-vf", filtro_video, *_params_encoder(encoder), str(caminho_saida)]
    return comando


def _detectar_encoder_gpu() -> str:
    """Retorna 'h264_nvenc' se o ffmpeg instalado suportar o encoder NVENC
    da NVIDIA, senao 'libx264' (CPU, sempre disponivel). Nunca levanta
    excecao - qualquer problema (ffmpeg ausente, timeout, saida
    inesperada) cai no fallback seguro (libx264)."""
    try:
        resultado = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "h264_nvenc" in (resultado.stdout or ""):
            return "h264_nvenc"
    except (subprocess.SubprocessError, OSError):
        pass
    return ENCODER_PADRAO


# ---------------------------------------------------------------------------
# Pre-condicoes (CLAUDE.md secao 18.6)
# ---------------------------------------------------------------------------


def _validar_pre_condicoes(pasta_projeto: Path, fontes_disponiveis: dict, duracao_narracao):
    ok_ffmpeg, mensagem_ffmpeg = robustez.validar_pre_condicoes_pipeline()
    if not ok_ffmpeg:
        return False, mensagem_ffmpeg, "ffmpeg_ausente"

    if not fontes_disponiveis:
        return (
            False,
            "fontes/manifest_fontes.json nao encontrado ou sem nenhum video-fonte baixado com sucesso. "
            "Rode a Etapa 1 (download) antes desta etapa.",
            "fontes_ausentes",
        )

    if duracao_narracao is None:
        return (
            False,
            "narracao_alinhamento.json nao encontrado. Rode a Etapa 4 (audio) antes desta etapa.",
            "narracao_ausente",
        )

    if duracao_narracao <= 0:
        return False, "Duracao da narracao invalida (<= 0).", "narracao_invalida"

    return True, None, None


# ---------------------------------------------------------------------------
# Renderizacao de um clipe (funcoes trazidas de 7_renderizar_clipes.py)
# ---------------------------------------------------------------------------


def _rodar_ffmpeg(comando):
    """Roda um comando ffmpeg ja montado. Retorna (True, None, None) em
    sucesso, ou (False, tipo_erro, mensagem_usuario) caso contrario. Nunca
    levanta excecao."""
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_POR_CLIPE_S,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout_clipe", f"Renderizacao excedeu o tempo limite de {TIMEOUT_POR_CLIPE_S}s."
    except OSError as exc:
        return False, "erro_desconhecido", f"Falha ao executar ffmpeg: {exc}"

    caminho_saida = Path(comando[-1])
    if resultado.returncode != 0 or not caminho_saida.exists():
        stderr_tail = "\n".join((resultado.stderr or "").strip().splitlines()[-15:])
        tipo_erro, mensagem_usuario = classificar_erro_renderizacao(stderr_tail)
        return False, tipo_erro, mensagem_usuario

    return True, None, None


def _renderizar_clipe(
    caminho_fonte,
    inicio_s,
    duracao_s,
    caminho_saida,
    marca_dagua_posicao,
    ken_burns,
    encoder=ENCODER_PADRAO,
):
    """Roda o ffmpeg de um unico clipe. Retorna (sucesso, tipo_erro,
    mensagem_usuario, encoder_usado). Nunca levanta excecao.

    Fallback automatico: se o encoder pedido e' `h264_nvenc` e a
    renderizacao falha (driver antigo, GPU ocupada, sem GPU fisica em
    runtime apesar da deteccao previa), tenta de novo com `libx264` antes
    de desistir do clipe."""
    if duracao_s <= 0:
        return False, "erro_desconhecido", "Janela de corte invalida (duracao <= 0).", encoder

    eh_imagem = _fonte_eh_imagem(caminho_fonte)
    comando = construir_comando_ffmpeg(
        caminho_fonte, inicio_s, duracao_s, caminho_saida, marca_dagua_posicao, ken_burns, encoder, eh_imagem
    )
    sucesso, tipo_erro, mensagem_usuario = _rodar_ffmpeg(comando)

    if not sucesso and encoder == "h264_nvenc":
        comando_fallback = construir_comando_ffmpeg(
            caminho_fonte, inicio_s, duracao_s, caminho_saida, marca_dagua_posicao, ken_burns, "libx264", eh_imagem
        )
        sucesso, tipo_erro, mensagem_usuario = _rodar_ffmpeg(comando_fallback)
        if sucesso:
            encoder = "libx264"

    return sucesso, tipo_erro, mensagem_usuario, encoder


# ---------------------------------------------------------------------------
# Orquestracao principal
# ---------------------------------------------------------------------------


def gerar_clipes(pasta_projeto: Path, seed=None) -> dict:
    """Gera clipes de video por selecao aleatoria de trechos das fontes.

    Substitui a antiga cadeia Etapa 5 (deteccao de cena) + Etapa 6
    (montagem de timeline) + Etapa 7 (renderizacao) por uma unica etapa
    mais simples e rapida - zero custo de API, so' ffmpeg local.

    `seed` torna o resultado reproduzivel (usado pelos testes) - None
    (default) usa entropia real do sistema."""
    inicio_total = time.monotonic()
    inicio_fase = time.monotonic()

    fontes_disponiveis = _ler_manifest_fontes(pasta_projeto)
    marcas_dagua = _ler_marcas_dagua(pasta_projeto)
    duracao_narracao = _ler_duracao_narracao(pasta_projeto)

    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes(
        pasta_projeto, fontes_disponiveis, duracao_narracao
    )
    if not ok_precondicoes:
        emitir_progresso(
            0.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro
        )
        return {"clipes": [], "sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    config = config_clipes()
    tempo_leitura_config_s = time.monotonic() - inicio_fase
    emitir_progresso(5.0, "Lendo configuracao...")

    emitir_progresso(10.0, "Detectando encoder GPU...")
    encoder = _detectar_encoder_gpu()

    rng = random.Random(seed)

    inicio_fase = time.monotonic()
    plano_slots = calcular_plano_slots(
        duracao_narracao, config["clipe_duracao_min_s"], config["clipe_duracao_max_s"], rng
    )
    total_slots = len(plano_slots)
    emitir_progresso(15.0, f"Planejando {total_slots} slot(s)...")

    fontes_ids = list(fontes_disponiveis.keys())
    ordem_fontes = list(fontes_ids)
    rng.shuffle(ordem_fontes)
    duracoes_fontes = {}
    fontes_uso_completo = {}
    for fonte_id, dados in fontes_disponiveis.items():
        duracao_selecao, usar_fonte_inteira = _metadata_selecao_fonte(dados)
        duracoes_fontes[fonte_id] = duracao_selecao
        if usar_fonte_inteira:
            fontes_uso_completo[fonte_id] = dados["duracao_s"]
    intervalos_usados = {fonte_id: [] for fonte_id in fontes_ids}
    tempo_planejamento_slots_s = time.monotonic() - inicio_fase

    if not plano_slots:
        mensagem = "Nao foi possivel planejar nenhum slot a partir da duracao da narracao."
        emitir_progresso(0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="plano_vazio", mensagem_usuario=mensagem)
        return {"clipes": [], "sucesso": False, "erro_fatal": mensagem, "tipo_erro": "plano_vazio"}

    pasta_clipes = pasta_projeto / "clipes"
    pasta_clipes.mkdir(parents=True, exist_ok=True)

    inicio_fase = time.monotonic()
    cursor = 0
    resultados = []

    for indice, slot in enumerate(plano_slots):
        pct = 20.0 + (indice / total_slots) * 75.0
        emitir_progresso(pct, f"Renderizando clipe {indice + 1}/{total_slots}...")

        janela = _selecionar_janela_para_slot(
            slot["duracao_alvo_s"],
            ordem_fontes,
            cursor,
            duracoes_fontes,
            intervalos_usados,
            config["margem_inicio_s"],
            config["margem_fim_s"],
            rng,
        )
        if janela is None:
            resultados.append(
                {
                    "sucesso": False,
                    "tipo_erro": "fonte_indisponivel",
                    "mensagem_usuario": f"Nenhuma fonte com duracao suficiente para o slot {indice} - clipe pulado.",
                }
            )
            continue

        fonte_id, inicio_s, duracao_s, cursor = janela
        if fonte_id in fontes_uso_completo:
            # Video de upload curto (CLAUDE.md 5.7.1-bis) - ignora a janela
            # sorteada (que usou a duracao sentinela so' para passar pelas
            # margens) e renderiza a fonte inteira, do inicio ao fim.
            inicio_s = 0.0
            duracao_s = fontes_uso_completo[fonte_id]
        caminho_fonte = fontes_disponiveis[fonte_id]["caminho"]
        marca_posicao = marcas_dagua.get(fonte_id) or "nenhuma"
        clipe_id = f"clipe_{indice:04d}"
        nome_arquivo = f"{clipe_id}.mp4"
        caminho_saida = pasta_clipes / nome_arquivo

        if not caminho_fonte.exists():
            resultados.append(
                {
                    "sucesso": False,
                    "tipo_erro": "fonte_ausente",
                    "mensagem_usuario": f"Video-fonte '{fonte_id}' nao encontrado em disco - clipe pulado.",
                }
            )
            continue

        sucesso, tipo_erro_clipe, mensagem_erro_clipe, encoder_usado_clipe = _renderizar_clipe(
            caminho_fonte, inicio_s, duracao_s, caminho_saida, marca_posicao, config["ken_burns"], encoder
        )

        entrada_indice = {
            "arquivo": nome_arquivo,
            "clipe_id": clipe_id,
            "fonte_original": fonte_id,
            "inicio_fonte_s": inicio_s,
            "duracao_s": duracao_s,
            "marca_dagua_removida": marca_posicao,
            "encoder": encoder_usado_clipe,
            "sucesso": sucesso,
        }
        if not sucesso:
            entrada_indice["tipo_erro"] = tipo_erro_clipe
            entrada_indice["mensagem_usuario"] = mensagem_erro_clipe
        else:
            intervalos_usados.setdefault(fonte_id, []).append((inicio_s, inicio_s + duracao_s))
        resultados.append(entrada_indice)

    tempo_renderizacao_clipes_s = time.monotonic() - inicio_fase

    clipes_ok = [r for r in resultados if r["sucesso"]]
    clipes_falhos = [r for r in resultados if not r["sucesso"]]

    clipes_para_indice = [
        {
            "arquivo": c["arquivo"],
            "clipe_id": c["clipe_id"],
            "fonte_original": c["fonte_original"],
            "inicio_fonte_s": c["inicio_fonte_s"],
            "duracao_s": c["duracao_s"],
            "marca_dagua_removida": c["marca_dagua_removida"],
            "encoder": c["encoder"],
        }
        for c in clipes_ok
    ]

    tempo_total_s = time.monotonic() - inicio_total

    indice_json = {
        "clipes": clipes_para_indice,
        "metadata": {
            "total_clipes": len(clipes_para_indice),
            "duracao_total_s": round(sum(c["duracao_s"] for c in clipes_para_indice), 3),
            "duracao_narracao_s": duracao_narracao,
            "ken_burns_aplicado": config["ken_burns"],
            "encoder_usado": encoder,
            "total_slots_planejados": total_slots,
            "tempos_por_fase": {
                "leitura_config_s": round(tempo_leitura_config_s, 3),
                "planejamento_slots_s": round(tempo_planejamento_slots_s, 3),
                "renderizacao_clipes_s": round(tempo_renderizacao_clipes_s, 3),
                "total_s": round(tempo_total_s, 3),
            },
            "data_geracao": datetime.now(timezone.utc).isoformat(),
        },
    }
    (pasta_clipes / "indice.json").write_text(
        json.dumps(indice_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if clipes_ok and not clipes_falhos:
        emitir_progresso(
            100.0, f"Concluido: {len(clipes_ok)} clipe(s) gerado(s)", sucesso=True, total_clipes=len(clipes_ok)
        )
    elif clipes_ok:
        avisos = [
            f"{c.get('arquivo') or 'slot'}: {c.get('mensagem_usuario') or c.get('tipo_erro')}"
            for c in clipes_falhos
        ]
        emitir_progresso(
            100.0,
            f"Concluido com {len(clipes_ok)} de {total_slots} clipes gerados",
            sucesso=True,
            avisos=avisos,
        )
    else:
        mensagens_unicas = list(
            dict.fromkeys(c.get("mensagem_usuario") for c in clipes_falhos if c.get("mensagem_usuario"))
        )
        mensagem_usuario = " | ".join(mensagens_unicas) if mensagens_unicas else "Nenhum clipe foi gerado com sucesso."
        emitir_progresso(
            100.0,
            "ERRO: nenhum clipe gerado",
            sucesso=False,
            mensagem_usuario=mensagem_usuario,
            tipo_erro=clipes_falhos[0].get("tipo_erro") if clipes_falhos else "erro_desconhecido",
            erros=[c.get("mensagem_usuario") for c in clipes_falhos],
        )

    return {
        "clipes": clipes_ok,
        "sucesso": bool(clipes_ok),
        "total": total_slots,
        "sucessos": len(clipes_ok),
    }


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/5_gerar_clipes.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    resultado = gerar_clipes(pasta_projeto)

    if not resultado.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
