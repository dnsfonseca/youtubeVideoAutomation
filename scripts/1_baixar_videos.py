"""Etapa 1 do pipeline (CLAUDE.md secao 5.1) - baixa os videos-fonte
listados em entrada/links.txt via yt-dlp.

Uso: python "scripts/1_baixar_videos.py" <caminho_da_pasta_do_projeto>

Saida:
- fontes/fonteNN.mp4 - um arquivo por link, numerado na ordem em que
  aparece em entrada/links.txt (mesmo que o download falhe, o numero e'
  reservado - nao ha "buraco" silencioso na numeracao).
- fontes/manifest_fontes.json - URL original, titulo, duracao e status
  de cada video-fonte.

Este script e' autocontido (CLAUDE.md secao 9: sem utils.py
compartilhado entre scripts/*.py) — exceto por scripts/robustez.py, que
e' infra transversal de robustez (CLAUDE.md secao 18), nao logica de
pipeline.
"""

import collections
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ precisa estar no sys.path para `import robustez` funcionar tanto
# rodando este arquivo direto (`python scripts/1_baixar_videos.py`) quanto
# carregado via importlib nos testes (spec_from_file_location nao adiciona
# a pasta do arquivo ao sys.path sozinho).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robustez  # noqa: E402

# yt-dlp e' chamado como `python -m yt_dlp` em vez do executavel
# `yt-dlp.exe`/shim `.bat` direto - contorna um problema de compatibilidade
# do shim gerado pelo pyenv-win no Windows, que pode nao encontrar o
# interpretador certo dependendo de como o PATH esta montado.
# Approach inspired by yt_automation (Gustavo Xavier, GitHub)
# for the Windows/pyenv-win shim compatibility issue.
COMANDO_PYTHON = sys.executable

FORMATO_PREFERENCIAL = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"

# Numero de linhas finais de output do yt-dlp guardadas para diagnostico
# quando um download falha (CLAUDE.md secao 18.5).
LINHAS_LOG_ERRO = 15

# Linha de progresso tipica do yt-dlp com --newline, por exemplo:
#   [download]  42.3% of   15.23MiB at    1.21MiB/s ETA 00:08
PADRAO_PROGRESSO = re.compile(
    r"\[download\]\s+(?P<pct>[\d.]+)%.*?ETA\s+(?P<eta>\S+)"
)

# yt-dlp baixa video e audio como streams/arquivos separados quando o
# formato escolhido e' "bestvideo+bestaudio" (o caso comum de
# FORMATO_PREFERENCIAL) — cada stream reporta seu proprio ciclo de 0-100%,
# o que faz o progresso "voltar pra tras" se lido ingenuamente (Bug 4).
# Estas duas linhas identificam, respectivamente, a troca de stream e o
# tamanho total de cada stream, para combinar os dois em um progresso
# unico e monotonico ponderado por tamanho.
PADRAO_DESTINO = re.compile(r"\[download\]\s+Destination:\s+(?P<destino>.+)")
PADRAO_TAMANHO = re.compile(r"of\s+~?\s*(?P<tamanho>[\d.]+)(?P<unidade>[KMGT]i?B)\b")

# Velocidade de download da mesma linha de progresso (ex: "at    1.21MiB/s")
# - ausente ("at  Unknown B/s") nao bate no regex, retorna None (Sessao de
# correcoes UX: mostrar MB baixado/total + velocidade + ETA amigavel pro
# usuario em vez de so pct+ETA cru).
PADRAO_VELOCIDADE = re.compile(r"at\s+(?P<velocidade>[\d.]+)(?P<unidade>[KMGT]i?B)/s")

# Teto de 1 emissao de @PROGRESSO por segundo durante o download de um
# stream (yt-dlp com --newline pode emitir linhas de progresso varias vezes
# por segundo) - evita floodar o polling de /api/status sem perder
# informacao relevante para o usuario.
THROTTLE_PROGRESSO_S = 1.0

# Linhas que indicam que o yt-dlp esta em pos-processamento (merge de video +
# audio via ffmpeg, remocao dos arquivos temporarios de cada stream) - a
# etapa que acontece DEPOIS do download em si chegar a 100%, e' onde o
# arquivo final de verdade fica pronto (Problema 1 da Sessao 3.1: a barra
# nao pode chegar a 100% antes disso).
PADRAO_POS_PROCESSAMENTO = re.compile(
    r"\[Merger\]|Merging formats|Deleting original file|\[ffmpeg\]", re.IGNORECASE
)

# Enquanto o download de um video individual esta em andamento, o percentual
# combinado exibido nunca ultrapassa este teto - reserva os pontos
# percentuais finais da "fatia" deste video (entre este teto e o inicio do
# proximo video) para o pos-processamento (merge do ffmpeg + escrita do
# arquivo final), que so e' confirmado como concluido depois que
# `processo.wait()` retorna e o arquivo existe de fato no disco.
LIMITE_PCT_DOWNLOAD_STREAM = 95.0

# Percentual (dentro da fatia deste video) usado para sinalizar
# pos-processamento em andamento (merge/finalizacao), sempre abaixo de 100%
# do proprio video - CLAUDE.md secao 18.4 (nunca reportar sucesso antes da
# hora).
FRACAO_PCT_POS_PROCESSAMENTO = 0.99

# ---------------------------------------------------------------------------
# Categorizacao de erros do yt-dlp (Problema 4 da Sessao 3.1): stderr bruto
# do yt-dlp e' tecnico demais pro usuario final entender por que um link
# falhou. Cada entrada e' (categoria, funcao_de_deteccao, mensagem_amigavel).
# A ordem importa - checagens mais especificas vem antes de genericas (ex:
# restricao de idade tambem contem "sign in", mas tem que ser classificada
# como "restricao_idade", nao cair no generico "erro_autenticacao").
# ---------------------------------------------------------------------------

_CATEGORIAS_ERRO_YTDLP = [
    (
        "video_removido",
        lambda s: "this video has been removed" in s
        or ("video unavailable" in s and "removed" in s),
        "Este video foi removido pelo autor ou esta indisponivel.",
    ),
    (
        "video_privado",
        lambda s: "private video" in s or "this video is private" in s,
        "Este video esta definido como privado e nao pode ser baixado.",
    ),
    (
        "geobloqueio",
        lambda s: "not available in your country" in s
        or "geo restricted" in s
        or "geo-restricted" in s
        or "blocked in your country" in s,
        "Este video nao esta disponivel na sua regiao (bloqueio geografico do canal).",
    ),
    (
        "restricao_idade",
        lambda s: "age restricted" in s
        or "age-restricted" in s
        or "sign in to confirm your age" in s,
        "Este video tem restricao de idade e requer autenticacao do YouTube pra ser baixado.",
    ),
    (
        "membership_only",
        lambda s: "members-only" in s
        or "this video is available to this channel's members" in s,
        "Este video e' exclusivo pra membros pagos do canal e nao pode ser baixado.",
    ),
    (
        "link_malformado",
        lambda s: "is not a valid url" in s
        or "unable to extract" in s
        or "invalid url" in s,
        "O link fornecido nao e' uma URL valida do YouTube.",
    ),
    (
        "erro_rede",
        lambda s: "unable to connect" in s
        or "connection refused" in s
        or "network is unreachable" in s
        or "timed out" in s
        or "timeout" in s,
        "Erro de conexao com o YouTube. Verifique sua internet e tente novamente.",
    ),
    (
        "erro_autenticacao",
        lambda s: "login required" in s or "sign in" in s,
        "Este video requer login do YouTube pra ser baixado (nao suportado nesta versao).",
    ),
]


def classificar_erro_ytdlp(stderr: str) -> tuple:
    """Classifica o stderr capturado do yt-dlp numa categoria conhecida de
    falha, com mensagem amigavel pro usuario final (Problema 4 da Sessao
    3.1 - "nenhum video baixado" sozinho nao explica nada).

    Retorna (categoria, mensagem_amigavel). Cai em "erro_desconhecido" com
    um trecho tecnico do stderr se nada bater com nenhuma categoria
    conhecida."""
    texto = stderr or ""
    stderr_lower = texto.lower()
    for categoria, condicao, mensagem in _CATEGORIAS_ERRO_YTDLP:
        if condicao(stderr_lower):
            return categoria, mensagem
    # Nenhuma categoria conhecida bateu - prefere a ultima linha que comeca
    # com "ERROR" (a mensagem de erro de fato do yt-dlp) em vez dos
    # primeiros 100 caracteres do log inteiro, que normalmente sao so ruido
    # informativo ("Extracting URL...", warnings de JS runtime, etc) e
    # cortariam a mensagem util antes dela aparecer. Descoberto testando
    # contra um ID de video real invalido (Sessao 3.1).
    linhas_erro = [
        linha.strip() for linha in texto.splitlines() if linha.strip().upper().startswith("ERROR")
    ]
    trecho_base = linhas_erro[-1] if linhas_erro else texto.strip()
    trecho = trecho_base[:100]
    return "erro_desconhecido", f"Nao foi possivel baixar este video. Erro tecnico: {trecho}"


_UNIDADES_BYTES = {
    "B": 1,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "TiB": 1024**4,
}


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


def ler_fontes_upload(pasta_projeto: Path) -> list:
    """Le entrada/fontes_upload.json (feature de fontes separadas -
    CLAUDE.md secao 5.7.1-bis) - lista de fontes visuais que o usuario
    enviou por upload no formulario de Novo projeto, ja salvas em
    fontes/fonteNN.<ext> pelo server.py ANTES desta etapa rodar (nao ha
    nada para baixar). Arquivo ausente (modo unificado, ou projeto criado
    antes desta feature existir) retorna lista vazia - retrocompatibilidade
    total."""
    caminho = pasta_projeto / "entrada" / "fontes_upload.json"
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return dados if isinstance(dados, list) else []


def obter_duracao_via_ffprobe(caminho: Path):
    """Duracao em segundos de um arquivo de video via ffprobe, ou None se
    nao for possivel determinar (ffprobe ausente, arquivo corrompido,
    timeout) - nunca levanta excecao (CLAUDE.md secao 18.5)."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(caminho),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if resultado.returncode != 0:
            return None
        return float(resultado.stdout.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def ler_links(caminho_links: Path) -> list:
    if not caminho_links.exists():
        return []
    # "utf-8-sig" descarta um BOM inicial se existir (comum em arquivos
    # .txt salvos por editores do Windows como "UTF-8") e e' identico a
    # "utf-8" se nao existir — sem isso, o BOM vaza como caractere
    # invisivel colado na primeira URL do arquivo (CLAUDE.md secao 9).
    linhas = caminho_links.read_text(encoding="utf-8-sig").splitlines()
    return [linha.strip() for linha in linhas if linha.strip()]


def _eta_para_segundos(eta_str: str):
    if eta_str in ("Unknown", "--:--", ""):
        return None
    try:
        partes = [int(p) for p in eta_str.split(":")]
    except ValueError:
        return None
    segundos = 0
    for parte in partes:
        segundos = segundos * 60 + parte
    return segundos


def parsear_linha_progresso(linha: str):
    """Extrai (pct, eta_s) de uma linha de output do yt-dlp.

    Retorna None se a linha nao for uma linha de progresso de download
    reconhecida (yt-dlp emite muitas outras linhas: extracao de info,
    merge, avisos, etc - todas ignoradas aqui).
    """
    m = PADRAO_PROGRESSO.search(linha)
    if not m:
        return None
    pct = float(m.group("pct"))
    eta_s = _eta_para_segundos(m.group("eta"))
    return pct, eta_s


def _tamanho_em_bytes(linha: str):
    """Extrai o tamanho total do stream de uma linha de progresso (ex:
    "of 15.23MiB"), em bytes. Retorna None se a linha nao trouxer tamanho
    reconhecido (ex: "of Unknown")."""
    m = PADRAO_TAMANHO.search(linha)
    if not m:
        return None
    multiplicador = _UNIDADES_BYTES.get(m.group("unidade"))
    if multiplicador is None:
        return None
    return float(m.group("tamanho")) * multiplicador


def _velocidade_em_bytes_por_segundo(linha: str):
    """Extrai a velocidade de download de uma linha de progresso (ex: "at
    1.21MiB/s"), em bytes/s. Retorna None se a linha nao trouxer velocidade
    reconhecida (ex: "at Unknown B/s", quando o yt-dlp ainda nao tem dado
    suficiente pra calcular)."""
    m = PADRAO_VELOCIDADE.search(linha)
    if not m:
        return None
    multiplicador = _UNIDADES_BYTES.get(m.group("unidade"))
    if multiplicador is None:
        return None
    return float(m.group("velocidade")) * multiplicador


def _formatar_eta_amigavel(eta_s) -> str:
    if not eta_s or eta_s <= 0:
        return "..."
    if eta_s < 60:
        return f"{int(eta_s)}s"
    minutos, segundos = divmod(int(eta_s), 60)
    if segundos == 0:
        return f"{minutos}min"
    return f"{minutos}min {segundos}s"


def _formatar_detalhe_download(indice, total, indice_stream, url, tamanho_bytes, pct_stream, velocidade_bytes_s, eta_s):
    """Mensagem legivel de progresso de download (Sessao de correcoes UX):
    quando o tamanho do stream atual e' conhecido, mostra MB baixado/total,
    velocidade e ETA amigavel; sem essa informacao (yt-dlp ainda nao a
    reportou), cai no formato basico de sempre."""
    base = f"Baixando video {indice}/{total} (parte {indice_stream})"
    if not tamanho_bytes:
        return f"{base}: {url}"
    mb_baixado = tamanho_bytes * pct_stream / 100 / (1024 * 1024)
    mb_total = tamanho_bytes / (1024 * 1024)
    eta_str = _formatar_eta_amigavel(eta_s)
    if velocidade_bytes_s:
        velocidade_mb_s = velocidade_bytes_s / (1024 * 1024)
        return (
            f"{base} — {mb_baixado:.0f}MB de {mb_total:.0f}MB "
            f"({velocidade_mb_s:.1f}MB/s, {eta_str} restantes)"
        )
    return f"{base} — {mb_baixado:.0f}MB de {mb_total:.0f}MB ({eta_str} restantes)"


class _ProgressoMultiStream:
    """Combina o progresso de multiplos streams (video + audio) de um
    unico download do yt-dlp num percentual unico e monotonico, ponderado
    por tamanho de cada stream quando disponivel (Bug 4 — CLAUDE.md secao
    5.1). Sem tamanho conhecido, cai de volta para o percentual do stream
    atual isolado."""

    def __init__(self):
        self._destino_atual = "stream-1"
        self._indice_por_destino = {}
        self._progresso_por_destino = {}
        self._maior_pct_emitido = 0.0

    def trocar_destino(self, destino: str):
        self._destino_atual = destino
        if destino not in self._indice_por_destino:
            self._indice_por_destino[destino] = len(self._indice_por_destino) + 1

    def registrar(self, pct_stream: float, linha: str):
        tamanho_bytes = _tamanho_em_bytes(linha)
        if tamanho_bytes:
            baixado = tamanho_bytes * pct_stream / 100
            self._progresso_por_destino[self._destino_atual] = (baixado, tamanho_bytes)
        else:
            # Sem tamanho conhecido: pondera esse stream como "peso 1",
            # tratando pct_stream como se fosse o unico stream visto ate
            # agora. Menos preciso, mas nunca regressivo.
            self._progresso_por_destino[self._destino_atual] = (pct_stream, 100.0)

        baixado_total = sum(b for b, _ in self._progresso_por_destino.values())
        tamanho_total = sum(t for _, t in self._progresso_por_destino.values())
        pct_combinado = (baixado_total / tamanho_total * 100) if tamanho_total else pct_stream

        # Clamp monotonico: o tamanho de um stream novo so entra no total
        # conhecido quando a primeira linha dele chega, o que pode diluir
        # o percentual combinado (ex: video termina em 100%, audio comeca
        # e o denominador cresce antes do numerador acompanhar). O usuario
        # nunca pode ver o progresso "voltar pra tras" (Bug 4), entao o
        # valor exibido nunca cai abaixo do maior ja emitido nesta chamada.
        pct_combinado = max(pct_combinado, self._maior_pct_emitido)
        self._maior_pct_emitido = pct_combinado

        indice_stream = self._indice_por_destino.get(self._destino_atual, 1)
        return pct_combinado, indice_stream


def montar_comando_download(url: str, saida_mp4: Path) -> list:
    return [
        COMANDO_PYTHON,
        "-m",
        "yt_dlp",
        "-f",
        FORMATO_PREFERENCIAL,
        "--merge-output-format",
        "mp4",
        "-o",
        str(saida_mp4),
        "--write-info-json",
        "--no-playlist",
        "--newline",
        url,
    ]


def caminho_info_json(saida_mp4: Path) -> Path:
    return saida_mp4.with_suffix(".info.json")


def _montar_env():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def baixar_video(url: str, saida_mp4: Path, indice: int, total: int) -> dict:
    """Baixa um video-fonte. Nunca levanta excecao - qualquer falha vira
    campo "erro" no dict de retorno, pra nao derrubar o download dos
    outros links da lista (CLAUDE.md secao 5.1)."""
    resultado = {
        "url": url,
        "arquivo": saida_mp4.name,
        "sucesso": False,
        "titulo": None,
        "duracao_s": None,
        "erro": None,
        "log_erro": None,
        "tipo_erro": None,
        "mensagem_usuario": None,
    }

    comando = montar_comando_download(url, saida_mp4)
    ultimas_linhas = collections.deque(maxlen=LINHAS_LOG_ERRO)
    combinador = _ProgressoMultiStream()
    # Maior pct_total ja emitido para ESTE video - garante que a mensagem de
    # pos-processamento (que usa uma formula independente do combinador de
    # streams) nunca regride em relacao ao ultimo valor de download emitido.
    maior_pct_emitido = 0.0
    # Throttle de emissao (THROTTLE_PROGRESSO_S) - inicializado no passado
    # para garantir que a primeira linha de progresso reconhecida sempre
    # emita, independente de quando o loop comeca a rodar de verdade.
    ultimo_emit_monotonic = time.monotonic() - THROTTLE_PROGRESSO_S
    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_montar_env(),
        )
        for linha in processo.stdout:
            ultimas_linhas.append(linha.rstrip("\n"))

            m_destino = PADRAO_DESTINO.search(linha)
            if m_destino:
                combinador.trocar_destino(m_destino.group("destino").strip())
                continue

            if PADRAO_POS_PROCESSAMENTO.search(linha):
                pct_pos = ((indice - 1) + FRACAO_PCT_POS_PROCESSAMENTO) / total * 100
                pct_pos = max(pct_pos, maior_pct_emitido)
                maior_pct_emitido = pct_pos
                emitir_progresso(
                    pct_pos,
                    f"Processando arquivo final {indice}/{total} "
                    "(combinando video e audio)...",
                )
                continue

            progresso = parsear_linha_progresso(linha)
            if progresso is None:
                continue
            pct_stream, eta_s = progresso
            pct_combinado, indice_stream = combinador.registrar(pct_stream, linha)
            # Nunca deixa o download em si (antes do merge/pos-processamento
            # do yt-dlp) reportar a fatia inteira deste video - senao, no
            # ultimo video da lista, pct_total bateria 100.0 antes do
            # arquivo final estar pronto de verdade (Problema 1 da Sessao
            # 3.1).
            pct_combinado_exibido = min(pct_combinado, LIMITE_PCT_DOWNLOAD_STREAM)
            pct_total = ((indice - 1) + pct_combinado_exibido / 100) / total * 100
            pct_total = max(pct_total, maior_pct_emitido)
            maior_pct_emitido = pct_total

            # O clamp monotonico acima (maior_pct_emitido) e' mantido em
            # TODA linha reconhecida, mesmo quando o throttle abaixo decide
            # nao emitir esta - senao a proxima emissao poderia usar um
            # ponto de partida desatualizado.
            agora = time.monotonic()
            if agora - ultimo_emit_monotonic < THROTTLE_PROGRESSO_S:
                continue
            ultimo_emit_monotonic = agora

            tamanho_bytes = _tamanho_em_bytes(linha)
            velocidade_bytes_s = _velocidade_em_bytes_por_segundo(linha)
            detalhe = _formatar_detalhe_download(
                indice, total, indice_stream, url, tamanho_bytes, pct_stream, velocidade_bytes_s, eta_s
            )
            emitir_progresso(pct_total, detalhe, eta_s=eta_s)
        processo.wait()

        if processo.returncode != 0 or not saida_mp4.exists():
            resultado["erro"] = f"yt-dlp saiu com codigo {processo.returncode}"
            resultado["log_erro"] = "\n".join(ultimas_linhas)
            categoria, mensagem = classificar_erro_ytdlp(resultado["log_erro"])
            resultado["tipo_erro"] = categoria
            resultado["mensagem_usuario"] = mensagem
            return resultado
    except OSError as exc:
        resultado["erro"] = f"Falha ao executar yt-dlp: {exc}"
        resultado["log_erro"] = "\n".join(ultimas_linhas)
        categoria, mensagem = classificar_erro_ytdlp(resultado["log_erro"] or str(exc))
        resultado["tipo_erro"] = categoria
        resultado["mensagem_usuario"] = mensagem
        return resultado

    resultado["sucesso"] = True

    info_json = caminho_info_json(saida_mp4)
    if info_json.exists():
        try:
            info = json.loads(info_json.read_text(encoding="utf-8"))
            resultado["titulo"] = info.get("title")
            resultado["duracao_s"] = info.get("duration")
        except (OSError, json.JSONDecodeError) as exc:
            resultado["erro"] = f"Download concluido, mas falha ao ler metadados: {exc}"
        finally:
            # .info.json e' lixo intermediario depois de consumido — nao
            # faz parte da saida da etapa (CLAUDE.md secao 6).
            try:
                info_json.unlink()
            except OSError:
                pass

    return resultado


def _validar_pre_condicoes(pasta_projeto: Path):
    """Valida tudo que este script precisa ANTES de comecar a processar
    qualquer link (CLAUDE.md secao 18.6): nunca comeca processamento
    parcial de um input invalido.

    Retorna (True, None) se pode prosseguir, ou (False, mensagem_de_erro)
    caso contrario."""
    ok, mensagem = robustez.validar_pre_condicoes_pipeline()
    if not ok:
        return False, mensagem

    entrada_links = pasta_projeto / "entrada" / "links.txt"
    if not ler_links(entrada_links):
        return False, f"entrada/links.txt nao encontrado ou vazio em {entrada_links}"

    return True, None


def baixar_todos(pasta_projeto: Path) -> dict:
    ok_precondicoes, mensagem_erro = _validar_pre_condicoes(pasta_projeto)
    if not ok_precondicoes:
        emitir_progresso(0.0, f"ERRO: {mensagem_erro}", sucesso=False)
        return {"fontes": [], "sucesso": False, "erro_fatal": mensagem_erro}

    entrada_links = pasta_projeto / "entrada" / "links.txt"
    pasta_fontes = pasta_projeto / "fontes"
    pasta_fontes.mkdir(parents=True, exist_ok=True)

    links = ler_links(entrada_links)
    total = len(links)
    manifest = {"fontes": []}

    for indice, url in enumerate(links, start=1):
        nome_arquivo = f"fonte{indice:02d}.mp4"
        saida_mp4 = pasta_fontes / nome_arquivo

        emitir_progresso(
            (indice - 1) / total * 100,
            f"Processando {indice}/{total}: {url}",
        )

        try:
            resultado = baixar_video(url, saida_mp4, indice, total)
        except Exception as exc:  # nunca deve acontecer (baixar_video trata
            # os proprios erros), mas um link nunca pode derrubar os outros.
            categoria, mensagem = classificar_erro_ytdlp(str(exc))
            resultado = {
                "url": url,
                "arquivo": nome_arquivo,
                "sucesso": False,
                "titulo": None,
                "duracao_s": None,
                "erro": f"Erro inesperado: {exc}",
                "log_erro": None,
                "tipo_erro": categoria,
                "mensagem_usuario": mensagem,
            }

        manifest["fontes"].append(
            {
                "id": f"fonte{indice:02d}",
                "arquivo": nome_arquivo,
                "url_original": url,
                "titulo": resultado["titulo"],
                "duracao_s": resultado["duracao_s"],
                "sucesso": resultado["sucesso"],
                "erro": resultado["erro"],
                "log_erro": resultado.get("log_erro"),
                "tipo_erro": resultado.get("tipo_erro"),
                "mensagem_usuario": resultado.get("mensagem_usuario"),
                "origem": "youtube",
            }
        )

    # Fontes visuais enviadas por upload (feature de fontes separadas) - ja
    # estao em disco em fontes/fonteNN.<ext> (server.py copiou no momento da
    # criacao do projeto), entao nao ha nada para baixar aqui. So' registra
    # cada uma no manifest, com duracao obtida via ffprobe para video (imagem
    # nao tem duracao intrinseca - fica None, a Etapa 5 decide a duracao do
    # clipe pela janela de narracao). Lista vazia (modo unificado, ou projeto
    # anterior a esta feature) nao muda nada abaixo.
    for item in ler_fontes_upload(pasta_projeto):
        id_fonte = item.get("id")
        nome_arquivo_upload = item.get("arquivo")
        if not id_fonte or not nome_arquivo_upload:
            continue
        tipo_upload = item.get("tipo")
        caminho_arquivo = pasta_fontes / nome_arquivo_upload
        existe = caminho_arquivo.exists()
        duracao_s = obter_duracao_via_ffprobe(caminho_arquivo) if (tipo_upload == "video" and existe) else None
        manifest["fontes"].append(
            {
                "id": id_fonte,
                "arquivo": nome_arquivo_upload,
                "url_original": None,
                "titulo": item.get("titulo") or nome_arquivo_upload,
                "duracao_s": duracao_s,
                "sucesso": existe,
                "erro": None if existe else "Arquivo enviado por upload nao encontrado em disco.",
                "log_erro": None,
                "tipo_erro": None if existe else "arquivo_ausente",
                "mensagem_usuario": (
                    None if existe else f"Arquivo enviado '{nome_arquivo_upload}' nao foi encontrado."
                ),
                "origem": "upload",
            }
        )

    total_geral = len(manifest["fontes"])
    sucessos = sum(1 for f in manifest["fontes"] if f["sucesso"])

    # Grava o manifest ANTES de emitir o @PROGRESSO final com pct=100.0 -
    # pct=100.0 so pode significar "tudo realmente pronto: streams baixados,
    # merge feito, arquivo final no lugar certo E manifest atualizado"
    # (CLAUDE.md secao 18.4 / Problema 1 da Sessao 3.1).
    manifest_path = pasta_fontes / "manifest_fontes.json"

    if sucessos == total_geral:
        manifest["sucesso"] = True
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        emitir_progresso(
            100.0, f"{sucessos} video(s) baixado(s) com sucesso", sucesso=True
        )
    elif sucessos == 0:
        manifest["sucesso"] = False
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        falhas = [f for f in manifest["fontes"] if not f["sucesso"]]
        erros = [f["erro"] for f in falhas if f["erro"]]
        mensagens_unicas = list(
            dict.fromkeys(f["mensagem_usuario"] for f in falhas if f.get("mensagem_usuario"))
        )
        mensagem_usuario = (
            " | ".join(mensagens_unicas)
            if mensagens_unicas
            else "Nao foi possivel baixar nenhum video."
        )
        emitir_progresso(
            100.0,
            "ERRO: nenhum video baixado",
            sucesso=False,
            erros=erros,
            mensagem_usuario=mensagem_usuario,
        )
    else:
        manifest["sucesso"] = True
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        falhas = [f for f in manifest["fontes"] if not f["sucesso"]]
        avisos = [f"{f['id']}: {f['mensagem_usuario'] or f['erro']}" for f in falhas]
        tipos_erro = sorted({f["tipo_erro"] for f in falhas if f.get("tipo_erro")})
        emitir_progresso(
            100.0,
            f"Concluido com {sucessos} de {total_geral} sucessos",
            sucesso=True,
            avisos=avisos,
            tipos_erro=tipos_erro,
        )

    return manifest


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/1_baixar_videos.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    manifest = baixar_todos(pasta_projeto)

    if not manifest.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
