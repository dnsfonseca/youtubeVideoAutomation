"""Testes da Etapa 1 do pipeline (scripts/1_baixar_videos.py) — download dos
videos-fonte via yt-dlp (CLAUDE.md secao 5.1).

Nunca chama yt-dlp real nem faz download real de nada (CLAUDE.md secao 8):
subprocess.Popen e' sempre mockado, e os arquivos que o yt-dlp real teria
criado (mp4 + .info.json) sao simulados manualmente em tmp_path.

O nome do arquivo do script comeca com digito ("1_baixar_videos.py"), entao
nao pode ser importado com `import` normal — carregado via
importlib.util.spec_from_file_location abaixo, igual um script standalone.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "1_baixar_videos.py"

_spec = importlib.util.spec_from_file_location("baixar_videos_etapa1", CAMINHO_SCRIPT)
modulo = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = modulo
_spec.loader.exec_module(modulo)


@pytest.fixture(autouse=True)
def _ffmpeg_disponivel_por_padrao(monkeypatch):
    """Isola os testes deste arquivo da presenca real de ffmpeg no PATH da
    maquina que roda o pytest — por padrao, simula ffmpeg disponivel (o
    dev-box deste projeto nem sempre tem ffmpeg instalado). Os testes que
    exercitam especificamente o Bug 2 (ffmpeg ausente) sobrescrevem isso
    explicitamente com ffmpeg_disponivel retornando False."""
    monkeypatch.setattr(modulo.robustez, "ffmpeg_disponivel", lambda: True)


class ProcessoFake:
    """Substitui o objeto retornado por subprocess.Popen nos testes.

    stdout e' iteravel (lista de linhas, como um Popen real com text=True
    seria iterado linha a linha) e returncode fica disponivel apos wait().
    """

    def __init__(self, linhas_stdout=(), returncode=0):
        self.stdout = iter(linhas_stdout)
        self.returncode = returncode
        self.wait_chamado = False

    def wait(self):
        self.wait_chamado = True


# ---------------------------------------------------------------------------
# montar_comando_download
# ---------------------------------------------------------------------------


def test_montar_comando_download_monta_argumentos_na_ordem_certa(tmp_path):
    saida_mp4 = tmp_path / "fonte01.mp4"
    url = "https://www.youtube.com/watch?v=abc123"

    comando = modulo.montar_comando_download(url, saida_mp4)

    assert comando == [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(saida_mp4),
        "--write-info-json",
        "--no-playlist",
        "--newline",
        url,
    ]


def test_montar_comando_download_usa_sys_executable_nao_ytdlp_direto(tmp_path):
    """Regressao: yt-dlp tem que ser chamado como `python -m yt_dlp`, nunca
    como executavel/shim direto — workaround do shim .bat do pyenv-win no
    Windows (CLAUDE.md secoes 5.1 e 9)."""
    comando = modulo.montar_comando_download("https://youtu.be/xyz", tmp_path / "f.mp4")

    assert comando[0] == sys.executable
    assert comando[1:3] == ["-m", "yt_dlp"]
    assert "yt-dlp" not in comando


def test_montar_comando_download_formato_preferencial_respeita_limite_1080(tmp_path):
    comando = modulo.montar_comando_download("https://youtu.be/xyz", tmp_path / "f.mp4")
    indice_formato = comando.index("-f") + 1

    assert "height<=1080" in comando[indice_formato]


# ---------------------------------------------------------------------------
# parsear_linha_progresso — linhas tipicas de output real do yt-dlp
# (validas em formatos diferentes de ETA + linhas que nao sao de progresso)
# ---------------------------------------------------------------------------

LINHAS_PROGRESSO_VALIDAS = [
    (
        "[download]  42.3% of   15.23MiB at    1.21MiB/s ETA 00:08",
        (42.3, 8),
    ),
    (
        "[download]  99.9% of  120.00MiB at    5.00MiB/s ETA 01:23:45",
        (99.9, 1 * 3600 + 23 * 60 + 45),
    ),
    (
        "[download] 100.0% of   50.00MiB at  Unknown B/s ETA Unknown",
        (100.0, None),
    ),
    (
        "[download]   0.0% of   10.00MiB at  Unknown B/s ETA --:--",
        (0.0, None),
    ),
]

LINHAS_NAO_PROGRESSO = [
    "[youtube] Extracting URL: https://youtube.com/watch?v=xyz",
    "[Merger] Merging formats into \"video.mp4\"",
    "[download] Destination: fonte01.mp4",
    "",
    "   ",
    "WARNING: [youtube] Falling back on generic information extractor",
]


@pytest.mark.parametrize("linha, esperado", LINHAS_PROGRESSO_VALIDAS)
def test_parsear_linha_progresso_extrai_pct_e_eta_de_linhas_validas(linha, esperado):
    resultado = modulo.parsear_linha_progresso(linha)

    assert resultado == esperado


@pytest.mark.parametrize("linha", LINHAS_NAO_PROGRESSO)
def test_parsear_linha_progresso_retorna_none_para_linhas_que_nao_sao_progresso(linha):
    assert modulo.parsear_linha_progresso(linha) is None


# ---------------------------------------------------------------------------
# _velocidade_em_bytes_por_segundo / _formatar_eta_amigavel /
# _formatar_detalhe_download (Sessao de correcoes UX - MB baixado/total +
# velocidade + ETA amigavel na mensagem de progresso do download)
# ---------------------------------------------------------------------------


def test_velocidade_em_bytes_por_segundo_extrai_mib_por_segundo():
    linha = "[download]  42.3% of   15.23MiB at    1.21MiB/s ETA 00:08"
    assert modulo._velocidade_em_bytes_por_segundo(linha) == pytest.approx(1.21 * 1024**2)


def test_velocidade_em_bytes_por_segundo_retorna_none_para_unknown():
    linha = "[download] 100.0% of   50.00MiB at  Unknown B/s ETA Unknown"
    assert modulo._velocidade_em_bytes_por_segundo(linha) is None


@pytest.mark.parametrize(
    "eta_s, esperado",
    [
        (None, "..."),
        (0, "..."),
        (8, "8s"),
        (65, "1min 5s"),
        (120, "2min"),
    ],
)
def test_formatar_eta_amigavel(eta_s, esperado):
    assert modulo._formatar_eta_amigavel(eta_s) == esperado


def test_formatar_detalhe_download_sem_tamanho_cai_no_formato_basico():
    detalhe = modulo._formatar_detalhe_download(1, 2, 1, "https://youtu.be/abc", None, 50.0, None, 10)
    assert detalhe == "Baixando video 1/2 (parte 1): https://youtu.be/abc"


def test_formatar_detalhe_download_com_tamanho_e_velocidade_mostra_mb_e_eta():
    tamanho_bytes = 40.0 * 1024**2
    velocidade_bytes_s = 1.0 * 1024**2
    detalhe = modulo._formatar_detalhe_download(1, 1, 1, "https://youtu.be/abc", tamanho_bytes, 50.0, velocidade_bytes_s, 65)

    assert "20MB de 40MB" in detalhe
    assert "1.0MB/s" in detalhe
    assert "1min 5s" in detalhe


def test_formatar_detalhe_download_com_tamanho_sem_velocidade_omite_mb_por_segundo():
    tamanho_bytes = 40.0 * 1024**2
    detalhe = modulo._formatar_detalhe_download(1, 1, 1, "https://youtu.be/abc", tamanho_bytes, 25.0, None, 30)

    assert "10MB de 40MB" in detalhe
    assert "MB/s" not in detalhe


# ---------------------------------------------------------------------------
# Throttle de emissao (THROTTLE_PROGRESSO_S) - no maximo 1 @PROGRESSO por
# segundo de linhas de progresso de download reconhecidas.
# ---------------------------------------------------------------------------


def test_baixar_video_progresso_throttle_limita_emissoes_por_segundo(tmp_path, monkeypatch, capsys):
    """3 linhas de progresso chegando "no mesmo instante" (relogio parado)
    devem virar 1 emissao so - as outras duas sao suprimidas pelo throttle
    porque nao se passou THROTTLE_PROGRESSO_S entre elas."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = [_linha_progresso(p, "10.00MiB") for p in (25.0, 50.0, 75.0)]
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)
    monkeypatch.setattr(modulo.time, "monotonic", lambda: 100.0)

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    assert len(saida_capturada) == 1


def test_baixar_video_progresso_throttle_deixa_passar_apos_um_segundo(tmp_path, monkeypatch, capsys):
    """Duas linhas separadas por mais de THROTTLE_PROGRESSO_S no relogio
    (mesmo com o subprocess fake entregando as linhas instantaneamente)
    geram 2 emissoes - o throttle nao suprime alem do teto configurado."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = [_linha_progresso(p, "10.00MiB") for p in (25.0, 50.0)]
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    relogio = iter([100.0, 100.0, 102.0])  # init, linha 1, linha 2
    monkeypatch.setattr(modulo.time, "monotonic", lambda: next(relogio))

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    assert len(saida_capturada) == 2


# ---------------------------------------------------------------------------
# ler_links
# ---------------------------------------------------------------------------


def test_ler_links_ignora_linhas_vazias_e_da_strip(tmp_path):
    caminho = tmp_path / "links.txt"
    caminho.write_text(
        "  https://youtu.be/aaa  \n\nhttps://youtu.be/bbb\n   \n",
        encoding="utf-8",
    )

    resultado = modulo.ler_links(caminho)

    assert resultado == ["https://youtu.be/aaa", "https://youtu.be/bbb"]


def test_ler_links_arquivo_inexistente_retorna_lista_vazia(tmp_path):
    resultado = modulo.ler_links(tmp_path / "nao_existe.txt")

    assert resultado == []


def test_ler_links_descarta_bom_utf8_da_primeira_linha(tmp_path):
    """Regressao encontrada em validacao real: editores do Windows (e o
    PowerShell com `-Encoding utf8`) costumam salvar .txt como "UTF-8 com
    BOM". Sem tratar isso, o BOM vira caractere invisivel colado na
    primeira URL (ex: "﻿https://...") e pode quebrar o link."""
    caminho = tmp_path / "links.txt"
    caminho.write_bytes(
        "﻿https://youtu.be/comBom\nhttps://youtu.be/semBom\n".encode("utf-8")
    )

    resultado = modulo.ler_links(caminho)

    assert resultado == ["https://youtu.be/comBom", "https://youtu.be/semBom"]
    assert "﻿" not in resultado[0]


# ---------------------------------------------------------------------------
# caminho_info_json
# ---------------------------------------------------------------------------


def test_caminho_info_json_troca_extensao_mantendo_a_base(tmp_path):
    saida_mp4 = tmp_path / "fonte01.mp4"

    resultado = modulo.caminho_info_json(saida_mp4)

    assert resultado == tmp_path / "fonte01.info.json"


# ---------------------------------------------------------------------------
# classificar_erro_ytdlp (Problema 4 da Sessao 3.1) — stderr tecnico do
# yt-dlp vira (categoria, mensagem_amigavel). A ordem das checagens importa
# especialmente entre "restricao_idade" e "erro_autenticacao", ja que a
# mensagem real de restricao de idade tambem contem "sign in" — ver teste
# dedicado de prioridade logo abaixo da tabela parametrizada.
# ---------------------------------------------------------------------------

CASOS_CLASSIFICAR_ERRO_YTDLP = [
    (
        "video_removido",
        'ERROR: [youtube] dQw4w9WgXcQ: This video has been removed by the uploader',
        "Este video foi removido pelo autor ou esta indisponivel.",
    ),
    (
        "video_removido",
        "ERROR: [youtube] dQw4w9WgXcQ: Video unavailable. This video is no longer "
        "available because it has been removed by the video owner",
        "Este video foi removido pelo autor ou esta indisponivel.",
    ),
    (
        "video_privado",
        "ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been "
        "granted access to this video",
        "Este video esta definido como privado e nao pode ser baixado.",
    ),
    (
        "geobloqueio",
        "ERROR: [youtube] dQw4w9WgXcQ: This video is not available in your country",
        "Este video nao esta disponivel na sua regiao (bloqueio geografico do canal).",
    ),
    (
        "restricao_idade",
        "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm your age. This video "
        "may be inappropriate for some users.",
        "Este video tem restricao de idade e requer autenticacao do YouTube pra ser baixado.",
    ),
    (
        "membership_only",
        "ERROR: [youtube] dQw4w9WgXcQ: Join this channel to get access to "
        "members-only content. This video is available to this channel's members",
        "Este video e' exclusivo pra membros pagos do canal e nao pode ser baixado.",
    ),
    (
        "link_malformado",
        "ERROR: 'foobar' is not a valid URL. Set --default-search \"ytsearch\" "
        "to search YouTube",
        "O link fornecido nao e' uma URL valida do YouTube.",
    ),
    (
        "erro_rede",
        "ERROR: Unable to connect to youtube.com: [Errno 11001] getaddrinfo failed",
        "Erro de conexao com o YouTube. Verifique sua internet e tente novamente.",
    ),
    (
        "erro_autenticacao",
        "ERROR: [youtube] dQw4w9WgXcQ: Please sign in. This helps protect our "
        "community.",
        "Este video requer login do YouTube pra ser baixado (nao suportado nesta versao).",
    ),
]


@pytest.mark.parametrize("categoria_esperada, stderr, mensagem_esperada", CASOS_CLASSIFICAR_ERRO_YTDLP)
def test_classificar_erro_ytdlp_reconhece_categorias_conhecidas(
    categoria_esperada, stderr, mensagem_esperada
):
    categoria, mensagem = modulo.classificar_erro_ytdlp(stderr)

    assert categoria == categoria_esperada
    assert mensagem == mensagem_esperada


def test_classificar_erro_ytdlp_e_case_insensitive():
    categoria, _ = modulo.classificar_erro_ytdlp(
        "ERROR: [YOUTUBE] ABC123: THIS VIDEO HAS BEEN REMOVED BY THE UPLOADER"
    )

    assert categoria == "video_removido"


def test_classificar_erro_ytdlp_restricao_idade_tem_prioridade_sobre_autenticacao_generica():
    """Regressao de ordem: a mensagem real do yt-dlp para restricao de idade
    contem "sign in" (que sozinho cairia em "erro_autenticacao"), mas a
    checagem mais especifica de restricao de idade vem primeiro na lista —
    tem que vencer, nao o generico."""
    categoria, mensagem = modulo.classificar_erro_ytdlp(
        "ERROR: Sign in to confirm your age"
    )

    assert categoria == "restricao_idade"
    assert categoria != "erro_autenticacao"
    assert "restricao de idade" in mensagem.lower() or "restrição de idade" in mensagem.lower()


def test_classificar_erro_ytdlp_fallback_para_erro_desconhecido_com_trecho_tecnico():
    stderr = "ERROR: [youtube] dQw4w9WgXcQ: HTTP Error 429: Too Many Requests" + "x" * 200

    categoria, mensagem = modulo.classificar_erro_ytdlp(stderr)

    assert categoria == "erro_desconhecido"
    trecho_esperado = stderr.strip()[:100]
    assert trecho_esperado in mensagem
    assert "Erro tecnico:" in mensagem


def test_classificar_erro_ytdlp_stderr_vazio_cai_em_erro_desconhecido():
    categoria, mensagem = modulo.classificar_erro_ytdlp("")

    assert categoria == "erro_desconhecido"
    assert "Erro tecnico:" in mensagem


# ---------------------------------------------------------------------------
# baixar_video
# ---------------------------------------------------------------------------


def test_baixar_video_sucesso_preenche_titulo_e_duracao_do_info_json(tmp_path, monkeypatch):
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")
    info_json = modulo.caminho_info_json(saida_mp4)
    info_json.write_text(
        json.dumps({"title": "Caso Real Investigado", "duration": 245.5}),
        encoding="utf-8",
    )

    processo_fake = ProcessoFake(linhas_stdout=[], returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    resultado = modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    assert resultado["sucesso"] is True
    assert resultado["titulo"] == "Caso Real Investigado"
    assert resultado["duracao_s"] == 245.5
    assert resultado["erro"] is None
    assert resultado["url"] == "https://youtu.be/abc"
    assert resultado["arquivo"] == "fonte01.mp4"


def test_baixar_video_sucesso_sem_info_json_deixa_titulo_e_duracao_none(tmp_path, monkeypatch):
    """Download pode ter sucesso (mp4 no disco, returncode 0) mesmo que o
    sidecar .info.json nao exista por algum motivo — nao pode quebrar,
    so deixa titulo/duracao_s como None."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")
    # .info.json de proposito nao criado

    processo_fake = ProcessoFake(linhas_stdout=[], returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    resultado = modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    assert resultado["sucesso"] is True
    assert resultado["titulo"] is None
    assert resultado["duracao_s"] is None
    assert resultado["erro"] is None


def test_baixar_video_emite_progresso_para_linhas_reconhecidas(tmp_path, monkeypatch, capsys):
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = [
        "[youtube] Extracting URL: https://youtu.be/abc\n",
        "[download]  50.0% of   10.00MiB at    1.00MiB/s ETA 00:05\n",
        "[Merger] Merging formats into \"video.mp4\"\n",
    ]
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out
    # Duas emissoes agora: uma para a linha de progresso de download, e uma
    # nova para a linha "[Merger]" (Problema 1 da Sessao 3.1 — a linha de
    # merge/pos-processamento tambem emite @PROGRESSO, sinalizando que o
    # arquivo final ainda esta sendo combinado).
    assert saida_capturada.count("@PROGRESSO") == 2
    ultima_linha = saida_capturada.strip().splitlines()[-1]
    payload_final = json.loads(ultima_linha[len("@PROGRESSO "):])
    assert "Processando arquivo final" in payload_final["detalhe"]


def test_baixar_video_returncode_diferente_de_zero_marca_erro_sem_excecao(tmp_path, monkeypatch):
    saida_mp4 = tmp_path / "fonte01.mp4"
    # mp4 nao chega a existir de verdade — simula falha real do yt-dlp

    processo_fake = ProcessoFake(linhas_stdout=[], returncode=1)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    resultado = modulo.baixar_video("https://youtu.be/quebrado", saida_mp4, 1, 1)

    assert resultado["sucesso"] is False
    assert resultado["erro"] is not None
    assert resultado["titulo"] is None
    assert resultado["duracao_s"] is None
    # Problema 4 da Sessao 3.1: toda falha vem classificada com categoria +
    # mensagem amigavel — aqui o stderr fake e' vazio, entao cai no
    # fallback "erro_desconhecido" (nenhuma categoria conhecida bate).
    assert resultado["tipo_erro"] == "erro_desconhecido"
    assert resultado["mensagem_usuario"] is not None


def test_baixar_video_mp4_ausente_apos_returncode_zero_marca_erro(tmp_path, monkeypatch):
    """returncode 0 mas o arquivo nao apareceu no disco (cenario raro, mas
    o script confere explicitamente) — nao pode ser tratado como sucesso."""
    saida_mp4 = tmp_path / "fonte01.mp4"

    processo_fake = ProcessoFake(linhas_stdout=[], returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    resultado = modulo.baixar_video("https://youtu.be/sumiu", saida_mp4, 1, 1)

    assert resultado["sucesso"] is False
    assert resultado["erro"] is not None
    assert resultado["tipo_erro"] == "erro_desconhecido"
    assert resultado["mensagem_usuario"] is not None


def test_baixar_video_apaga_info_json_apos_consumir_metadados(tmp_path, monkeypatch):
    """Bug 3: .info.json e' lixo intermediario do yt-dlp, nao faz parte da
    saida da etapa (CLAUDE.md secao 6) — depois de lido, tem que sumir do
    disco."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")
    info_json = modulo.caminho_info_json(saida_mp4)
    info_json.write_text(
        json.dumps({"title": "Caso Real Investigado", "duration": 245.5}),
        encoding="utf-8",
    )

    processo_fake = ProcessoFake(linhas_stdout=[], returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    resultado = modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    assert resultado["sucesso"] is True
    assert not info_json.exists()


def test_baixar_video_info_json_corrompido_nao_propaga_excecao_e_e_apagado(tmp_path, monkeypatch):
    """Caso de borda do Bug 3: .info.json presente mas com JSON invalido
    (ex: escrita interrompida pelo yt-dlp) — baixar_video nao pode
    quebrar, e o arquivo corrompido tambem tem que ser limpo do disco
    (bloco finally, nao so o caminho feliz)."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")
    info_json = modulo.caminho_info_json(saida_mp4)
    info_json.write_text("{ isso nao e um json valido ][", encoding="utf-8")

    processo_fake = ProcessoFake(linhas_stdout=[], returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    resultado = modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    assert resultado["sucesso"] is True
    assert resultado["titulo"] is None
    assert resultado["duracao_s"] is None
    assert resultado["erro"] is not None
    assert not info_json.exists()


def test_baixar_video_excecao_ao_iniciar_processo_nunca_propaga(tmp_path, monkeypatch):
    """Se subprocess.Popen levantar OSError (ex: interpretador nao
    encontrado), baixar_video NUNCA propaga excecao — sempre retorna dict
    com sucesso=False e erro preenchido (CLAUDE.md secao 5.1)."""
    saida_mp4 = tmp_path / "fonte01.mp4"

    def _levanta_oserror(*a, **k):
        raise OSError("interpretador nao encontrado")

    monkeypatch.setattr(modulo.subprocess, "Popen", _levanta_oserror)

    resultado = modulo.baixar_video("https://youtu.be/erro", saida_mp4, 1, 1)

    assert resultado["sucesso"] is False
    assert "interpretador nao encontrado" in resultado["erro"]


# ---------------------------------------------------------------------------
# Bug 2 — ffmpeg ausente do PATH: pre-condicao universal do pipeline
# (CLAUDE.md secao 18.6). baixar_todos tem que falhar ANTES de tentar
# chamar yt-dlp, nunca comecar processamento parcial.
# ---------------------------------------------------------------------------


def test_baixar_todos_com_ffmpeg_ausente_falha_sem_chamar_yt_dlp_nem_gravar_manifest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(modulo.robustez, "ffmpeg_disponivel", lambda: False)

    pasta_projeto = tmp_path / "caso_sem_ffmpeg"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\n", encoding="utf-8"
    )

    def _popen_nao_deveria_ser_chamado(*a, **k):
        pytest.fail("nao deveria chamar yt-dlp (subprocess.Popen) sem ffmpeg no PATH")

    monkeypatch.setattr(modulo.subprocess, "Popen", _popen_nao_deveria_ser_chamado)

    manifest = modulo.baixar_todos(pasta_projeto)

    assert manifest["sucesso"] is False
    assert "erro_fatal" in manifest
    assert "ffmpeg" in manifest["erro_fatal"]
    assert "PATH" in manifest["erro_fatal"]
    assert not (pasta_projeto / "fontes" / "manifest_fontes.json").exists()


def test_main_com_ffmpeg_ausente_sai_com_codigo_de_erro_diferente_de_zero(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(modulo.robustez, "ffmpeg_disponivel", lambda: False)

    pasta_projeto = tmp_path / "caso_sem_ffmpeg_main"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        modulo.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("nao deveria chamar yt-dlp sem ffmpeg no PATH"),
    )
    monkeypatch.setattr(sys, "argv", ["1_baixar_videos.py", str(pasta_projeto)])

    with pytest.raises(SystemExit) as excinfo:
        modulo.main()

    assert excinfo.value.code not in (0, None)


# ---------------------------------------------------------------------------
# baixar_todos — orquestracao de multiplos links
#
# Mocka baixar_video diretamente (em vez de subprocess.Popen) para isolar
# o teste da logica de orquestracao/numeracao/manifest de baixar_todos da
# logica interna de download de um unico link (ja coberta acima).
# ---------------------------------------------------------------------------


def test_baixar_todos_falha_de_um_link_nao_impede_os_outros(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\nhttps://youtu.be/dois\nhttps://youtu.be/tres\n",
        encoding="utf-8",
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        if indice == 2:
            return {
                "url": url,
                "arquivo": saida_mp4.name,
                "sucesso": False,
                "titulo": None,
                "duracao_s": None,
                "erro": "falha simulada no link 2",
            }
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": True,
            "titulo": f"Titulo do video {indice}",
            "duracao_s": 100.0 * indice,
            "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    manifest = modulo.baixar_todos(pasta_projeto)

    fontes = manifest["fontes"]
    assert len(fontes) == 3
    assert fontes[0]["sucesso"] is True
    assert fontes[1]["sucesso"] is False
    assert fontes[2]["sucesso"] is True

    pasta_fontes = pasta_projeto / "fontes"
    assert (pasta_fontes / "fonte01.mp4").exists()
    assert not (pasta_fontes / "fonte02.mp4").exists()
    assert (pasta_fontes / "fonte03.mp4").exists()


def test_baixar_todos_gera_manifest_com_campos_esperados(tmp_path, monkeypatch):
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\nhttps://youtu.be/dois\n",
        encoding="utf-8",
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": True,
            "titulo": "Titulo qualquer",
            "duracao_s": 60.0,
            "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    modulo.baixar_todos(pasta_projeto)

    manifest_path = pasta_projeto / "fontes" / "manifest_fontes.json"
    assert manifest_path.exists()

    manifest_lido = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest_lido["fontes"], list)
    assert len(manifest_lido["fontes"]) == 2

    chaves_esperadas = {
        "id",
        "arquivo",
        "url_original",
        "titulo",
        "duracao_s",
        "sucesso",
        "erro",
        "log_erro",
        "tipo_erro",
        "mensagem_usuario",
        "origem",
    }
    for entrada in manifest_lido["fontes"]:
        assert set(entrada.keys()) == chaves_esperadas
        assert entrada["origem"] == "youtube"

    assert manifest_lido["fontes"][0]["id"] == "fonte01"
    assert manifest_lido["fontes"][1]["id"] == "fonte02"


# ---------------------------------------------------------------------------
# Fontes visuais enviadas por upload (feature de fontes separadas -
# CLAUDE.md secao 5.7.1-bis) - ja estao em disco, nada para baixar.
# ---------------------------------------------------------------------------


def test_baixar_todos_pula_download_de_fontes_upload_e_registra_no_manifest(tmp_path, monkeypatch):
    """server.py ja copiou o upload para fontes/fonteNN.<ext> e escreveu
    entrada/fontes_upload.json antes desta etapa rodar - baixar_todos NUNCA
    deve chamar baixar_video para essas entradas, so' registra no manifest
    com origem "upload"."""
    pasta_projeto = tmp_path / "caso_com_upload"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text("https://youtu.be/um\n", encoding="utf-8")
    (pasta_projeto / "entrada" / "fontes_upload.json").write_text(
        json.dumps([{"id": "fonte02", "arquivo": "fonte02.jpg", "tipo": "imagem", "titulo": "still.jpg"}]),
        encoding="utf-8",
    )
    (pasta_projeto / "fontes").mkdir(parents=True)
    (pasta_projeto / "fontes" / "fonte02.jpg").write_bytes(b"fake-image-bytes")

    chamadas_baixar_video = []

    def _baixar_video_fake(url, saida_mp4, indice, total):
        chamadas_baixar_video.append(url)
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url, "arquivo": saida_mp4.name, "sucesso": True,
            "titulo": "Titulo", "duracao_s": 60.0, "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    manifest = modulo.baixar_todos(pasta_projeto)

    assert chamadas_baixar_video == ["https://youtu.be/um"]  # so' o link, nunca o upload
    assert manifest["sucesso"] is True

    entradas_por_id = {f["id"]: f for f in manifest["fontes"]}
    assert entradas_por_id["fonte01"]["origem"] == "youtube"
    assert entradas_por_id["fonte02"]["origem"] == "upload"
    assert entradas_por_id["fonte02"]["sucesso"] is True
    assert entradas_por_id["fonte02"]["duracao_s"] is None  # imagem nao tem duracao intrinseca
    assert entradas_por_id["fonte02"]["titulo"] == "still.jpg"


def test_baixar_todos_sem_fontes_upload_json_ignora_silenciosamente(tmp_path, monkeypatch):
    """Retrocompatibilidade: projeto sem a feature de fontes separadas (sem
    entrada/fontes_upload.json) continua funcionando exatamente como antes."""
    pasta_projeto = tmp_path / "caso_sem_upload"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text("https://youtu.be/um\n", encoding="utf-8")

    def _baixar_video_fake(url, saida_mp4, indice, total):
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url, "arquivo": saida_mp4.name, "sucesso": True,
            "titulo": "Titulo", "duracao_s": 60.0, "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    manifest = modulo.baixar_todos(pasta_projeto)

    assert manifest["sucesso"] is True
    assert len(manifest["fontes"]) == 1


def test_baixar_todos_marca_upload_ausente_em_disco_como_falha(tmp_path, monkeypatch):
    """entrada/fontes_upload.json referencia um arquivo que nao esta mais
    em disco (ex: apagado manualmente) - nao pode crashar, so' marcar essa
    fonte como falha (CLAUDE.md secao 18.4/18.6)."""
    pasta_projeto = tmp_path / "caso_upload_ausente"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text("https://youtu.be/um\n", encoding="utf-8")
    (pasta_projeto / "entrada" / "fontes_upload.json").write_text(
        json.dumps([{"id": "fonte02", "arquivo": "fonte02.jpg", "tipo": "imagem", "titulo": "still.jpg"}]),
        encoding="utf-8",
    )
    # Nao cria fontes/fonte02.jpg de proposito.

    def _baixar_video_fake(url, saida_mp4, indice, total):
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url, "arquivo": saida_mp4.name, "sucesso": True,
            "titulo": "Titulo", "duracao_s": 60.0, "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    manifest = modulo.baixar_todos(pasta_projeto)

    entradas_por_id = {f["id"]: f for f in manifest["fontes"]}
    assert entradas_por_id["fonte02"]["sucesso"] is False
    assert entradas_por_id["fonte02"]["tipo_erro"] == "arquivo_ausente"
    # A fonte01 (youtube) continua bem-sucedida - uma falha nao derruba a outra.
    assert entradas_por_id["fonte01"]["sucesso"] is True


def test_baixar_todos_numeracao_reserva_indice_mesmo_com_falha_no_meio(tmp_path, monkeypatch):
    """Regressao: um link que falha nao "pula" o numero — o proximo link
    bem-sucedido continua com o indice sequencial certo (fonte03, nao
    fonte02) (CLAUDE.md secao 5.1: 'nao ha buraco silencioso na numeracao'
    refere-se ao numero ser reservado, nao ao arquivo existir)."""
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\nhttps://youtu.be/dois\nhttps://youtu.be/tres\n",
        encoding="utf-8",
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        sucesso = indice != 2
        if sucesso:
            saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": sucesso,
            "titulo": None,
            "duracao_s": None,
            "erro": None if sucesso else "falha simulada",
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    manifest = modulo.baixar_todos(pasta_projeto)

    nomes_arquivo = [f["arquivo"] for f in manifest["fontes"]]
    assert nomes_arquivo == ["fonte01.mp4", "fonte02.mp4", "fonte03.mp4"]


def test_baixar_todos_com_lista_de_links_vazia_falha_sem_gravar_manifest(tmp_path, monkeypatch):
    """Regressao CLAUDE.md secao 18.6: links.txt vazio e' pre-condicao
    invalida — o script tem que falhar imediatamente, sem fingir que
    processou nada. Antes deste fix, gerava um manifest vazio com
    sucesso implicito, como se o projeto so nao tivesse links mesmo."""
    pasta_projeto = tmp_path / "caso_sem_links"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text("", encoding="utf-8")

    manifest = modulo.baixar_todos(pasta_projeto)

    assert manifest["fontes"] == []
    assert manifest["sucesso"] is False
    assert "erro_fatal" in manifest
    assert not (pasta_projeto / "fontes" / "manifest_fontes.json").exists()


def test_baixar_todos_com_titulo_unicode_e_emoji_no_manifest(tmp_path, monkeypatch):
    """Caso de borda de encoding (CLAUDE.md secao 9): titulo com acento e
    emoji no manifest nao pode quebrar a escrita/leitura do JSON no
    Windows."""
    pasta_projeto = tmp_path / "caso_unicode"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/emoji\n", encoding="utf-8"
    )

    titulo_unicode = "Investigação chocante 🔍 — o caso não resolvido"

    def _baixar_video_fake(url, saida_mp4, indice, total):
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": True,
            "titulo": titulo_unicode,
            "duracao_s": 30.0,
            "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    modulo.baixar_todos(pasta_projeto)

    manifest_path = pasta_projeto / "fontes" / "manifest_fontes.json"
    manifest_lido = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_lido["fontes"][0]["titulo"] == titulo_unicode


# ---------------------------------------------------------------------------
# emitir_progresso
# ---------------------------------------------------------------------------


def test_emitir_progresso_imprime_json_valido_no_stdout(capsys):
    modulo.emitir_progresso(55.5, "Baixando video 2/4", eta_s=30)

    saida = capsys.readouterr().out.strip()
    assert saida.startswith("@PROGRESSO ")

    payload = json.loads(saida[len("@PROGRESSO "):])
    assert payload == {"pct": 55.5, "detalhe": "Baixando video 2/4", "eta_s": 30}


def test_emitir_progresso_sem_eta_omite_a_chave(capsys):
    modulo.emitir_progresso(10.0, "Iniciando")

    saida = capsys.readouterr().out.strip()
    payload = json.loads(saida[len("@PROGRESSO "):])
    assert "eta_s" not in payload


# ---------------------------------------------------------------------------
# _tamanho_em_bytes
# ---------------------------------------------------------------------------

TAMANHOS_VALIDOS = [
    (
        "[download]  42.3% of   15.23MiB at    1.21MiB/s ETA 00:08",
        15.23 * 1024**2,
    ),
    (
        "[download]   5.0% of  512.00KiB at    1.00KiB/s ETA 00:30",
        512.00 * 1024,
    ),
    (
        "[download]  10.0% of    1.50GiB at    5.00MiB/s ETA 05:00",
        1.50 * 1024**3,
    ),
]


@pytest.mark.parametrize("linha, esperado_bytes", TAMANHOS_VALIDOS)
def test_tamanho_em_bytes_converte_unidades_diferentes_corretamente(linha, esperado_bytes):
    assert modulo._tamanho_em_bytes(linha) == pytest.approx(esperado_bytes)


TAMANHOS_SEM_PADRAO_RECONHECIDO = [
    "[download]  50.0% of  Unknown at  Unknown B/s ETA Unknown",
    "[youtube] Extracting URL: https://youtube.com/watch?v=xyz",
    "[download] Destination: fonte01.mp4",
    "",
]


@pytest.mark.parametrize("linha", TAMANHOS_SEM_PADRAO_RECONHECIDO)
def test_tamanho_em_bytes_retorna_none_para_linhas_sem_tamanho_reconhecido(linha):
    assert modulo._tamanho_em_bytes(linha) is None


# ---------------------------------------------------------------------------
# _ProgressoMultiStream — combinacao ponderada por tamanho (Bug 4)
# ---------------------------------------------------------------------------


def test_progresso_multi_stream_com_um_unico_stream_conhecido_reflete_o_proprio_percentual():
    combinador = modulo._ProgressoMultiStream()

    pct, indice = combinador.registrar(
        50.0, "[download]  50.0% of   40.00MiB at    1.00MiB/s ETA 00:10"
    )

    assert pct == pytest.approx(50.0)
    assert indice == 1


def test_progresso_multi_stream_pondera_por_tamanho_nao_e_media_ingenua_por_dois():
    """Regressao Bug 4: combinar dois streams de tamanhos MUITO diferentes
    tem que ponderar pelo tamanho de cada um, nao fazer media aritmetica
    simples (pct1 + pct2) / 2 — senao um stream de audio pequeno teria peso
    igual a um stream de video grande.

    Usa audio em 100% (nao um valor baixo) de proposito: o combinador tem
    um clamp monotonico (nunca deixa o pct exibido regredir abaixo do
    maior ja emitido — ver _ProgressoMultiStream.registrar) que mascararia
    a formula de ponderacao se o valor combinado cru ficasse abaixo do
    pct do video isolado (50%). Com audio en 100%, o combinado pela
    formula pura (55.5%) fica ACIMA do watermark anterior, entao o clamp
    nao interfere e o teste prova a ponderacao de verdade."""
    combinador = modulo._ProgressoMultiStream()

    combinador.registrar(50.0, "[download]  50.0% of   40.00MiB at 1.00MiB/s ETA 00:10")
    combinador.trocar_destino("fonte01.f140.m4a")
    pct_combinado, indice_stream = combinador.registrar(
        100.0, "[download] 100.0% of    5.00MiB at 1.00MiB/s ETA 00:00"
    )

    # baixado: stream de video = 40MiB * 50% = 20MiB; stream de audio =
    # 5MiB * 100% = 5MiB. combinado = (20+5) / (40+5) * 100.
    esperado = (20.0 + 5.0) / 45.0 * 100
    media_ingenua = (50.0 + 100.0) / 2

    assert pct_combinado == pytest.approx(esperado)
    assert pct_combinado != pytest.approx(media_ingenua)
    assert indice_stream == 1  # primeiro destino trocado explicitamente


def test_progresso_multi_stream_sem_tamanho_conhecido_cai_de_volta_pro_percentual_isolado():
    """Sem PADRAO_TAMANHO reconhecido na linha (ex: "of Unknown"), o
    combinador nao tem como ponderar por tamanho — cai de volta pro
    percentual do proprio stream, tratado com peso 1."""
    combinador = modulo._ProgressoMultiStream()

    pct, _ = combinador.registrar(
        33.0, "[download]  33.0% of  Unknown at  Unknown B/s ETA Unknown"
    )

    assert pct == pytest.approx(33.0)


def test_progresso_multi_stream_trocar_destino_incrementa_indice_para_destino_novo():
    combinador = modulo._ProgressoMultiStream()

    combinador.trocar_destino("fonte01.f137.mp4")
    _, indice_video = combinador.registrar(
        10.0, "[download]  10.0% of   40.00MiB at 1.00MiB/s ETA 00:10"
    )

    combinador.trocar_destino("fonte01.f140.m4a")
    _, indice_audio = combinador.registrar(
        10.0, "[download]  10.0% of    5.00MiB at 1.00MiB/s ETA 00:02"
    )

    assert indice_video == 1
    assert indice_audio == 2


def test_progresso_multi_stream_trocar_destino_mantem_indice_se_destino_se_repetir():
    combinador = modulo._ProgressoMultiStream()

    combinador.trocar_destino("fonte01.f137.mp4")
    combinador.trocar_destino("fonte01.f140.m4a")
    combinador.trocar_destino("fonte01.f137.mp4")  # volta pro primeiro destino

    _, indice = combinador.registrar(
        10.0, "[download]  10.0% of   40.00MiB at 1.00MiB/s ETA 00:10"
    )

    assert indice == 1


# ---------------------------------------------------------------------------
# baixar_video — progresso combinado de multiplos streams (video + audio)
# integrado de ponta a ponta via output simulado do yt-dlp (Bug 4)
# ---------------------------------------------------------------------------


def _linha_progresso(pct, tamanho_str, eta="00:10"):
    return f"[download]  {pct:.1f}% of   {tamanho_str} at    1.00MiB/s ETA {eta}\n"


def _linhas_download_video_e_audio():
    """Simula o output real do yt-dlp baixando formato "bestvideo+bestaudio":
    uma linha "Destination:" anuncia CADA stream antes das linhas de
    progresso dele (inclusive o primeiro, o de video) — omitir a
    "Destination:" do primeiro stream faria ele cair no destino-fallback
    "stream-1" do combinador, que por coincidencia tambem recebe indice 1
    igual o primeiro destino registrado explicitamente, mascarando a
    numeracao de partes."""
    return (
        ["[download] Destination: fonte01.f137.mp4\n"]
        + [_linha_progresso(p, "40.00MiB") for p in (25.0, 50.0, 75.0, 100.0)]
        + ["[download] Destination: fonte01.f140.m4a\n"]
        + [_linha_progresso(p, "5.00MiB") for p in (0.0, 50.0, 100.0)]
    )


def _desligar_throttle_progresso(monkeypatch):
    """Substitui time.monotonic por um relogio falso que sempre avanca mais
    que THROTTLE_PROGRESSO_S entre chamadas - neutraliza o throttle de
    emissao (Sessao de correcoes UX) nos testes que verificam o valor exato
    emitido em CADA linha de progresso reconhecida, sem relacao nenhuma com
    o throttle em si (que tem sua propria suite, ver
    test_baixar_video_progresso_throttle_limita_emissoes_por_segundo)."""
    contador = iter(range(0, 100000, 2))
    monkeypatch.setattr(modulo.time, "monotonic", lambda: next(contador))


def test_baixar_video_progresso_multi_stream_sinaliza_troca_de_stream_no_detalhe(
    tmp_path, monkeypatch, capsys
):
    """Regressao Bug 4: quando o yt-dlp troca de stream (video -> audio,
    linha "Destination:" no meio do output), o "detalhe" emitido em
    @PROGRESSO tem que indicar a troca (numero da parte), pra tela de
    status nao parecer que o download "reiniciou do zero"."""
    _desligar_throttle_progresso(monkeypatch)
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = _linhas_download_video_e_audio()
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    payloads = [json.loads(linha[len("@PROGRESSO "):]) for linha in saida_capturada]

    assert len(payloads) == 7  # 4 linhas de video + 3 linhas de audio

    # O detalhe agora inclui MB baixado (que varia a cada linha dentro do
    # mesmo stream - Sessao de correcoes UX), entao a identidade de stream
    # e' verificada pelo marcador "(parte N)" em vez do texto inteiro ser
    # identico dentro de cada grupo.
    detalhes_video = [p["detalhe"] for p in payloads[:4]]
    detalhes_audio = [p["detalhe"] for p in payloads[4:]]
    assert all("(parte 1)" in d for d in detalhes_video)
    assert all("(parte 2)" in d for d in detalhes_audio)


def test_baixar_video_progresso_multi_stream_pondera_por_tamanho_dos_dois_streams(
    tmp_path, monkeypatch, capsys
):
    """Confere os valores exatos de pct combinado emitidos, calculados a
    mao com a mesma ponderacao por tamanho de _ProgressoMultiStream —
    prova que baixar_video usa o combinador (nao o percentual cru de cada
    stream isolado).

    Neste cenario (video termina em 100%, DEPOIS o audio comeca do zero),
    a formula pura de ponderacao cairia pra ~88.9%/94.4% antes de voltar
    a 100% — o clamp monotonico do combinador (nunca regride abaixo do
    maior valor ja emitido) mantem tudo em 100% durante o audio inteiro
    NO VALOR CRU do combinador. Esse valor cru, porem, e' em seguida
    limitado a LIMITE_PCT_DOWNLOAD_STREAM (95.0) antes de virar pct_total
    exibido — a barra de progresso do download em si nunca pode bater
    100% antes do pos-processamento (merge do ffmpeg) confirmar o arquivo
    final pronto (Problema 1 da Sessao 3.1). Por isso os valores esperados
    abaixo saturam em 95.0, nao em 100.0 (ver
    test_baixar_video_progresso_multi_stream_sequencia_completa_e_nao_decrescente
    logo abaixo, que prova a monotonicidade em si, e
    test_baixar_video_nunca_emite_pct_100_quando_e_o_video_final_da_lista,
    que prova especificamente que o 100.0 cru nunca vaza pro pct exibido)."""
    _desligar_throttle_progresso(monkeypatch)
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = _linhas_download_video_e_audio()
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    pcts = [
        json.loads(linha[len("@PROGRESSO "):])["pct"] for linha in saida_capturada
    ]

    # video isolado (unico stream conhecido ate aqui): pct combinado ==
    # percentual do proprio stream, exceto o ultimo valor (100.0 cru), que
    # e' limitado ao teto de exibicao de 95.0.
    assert pcts[:4] == [25.0, 50.0, 75.0, 95.0]

    # audio: combinado_cru = (baixado_video_final + baixado_audio) / (40+5) * 100,
    # que fica em 100.0 (clamp monotonico do combinador), mas o teto de
    # exibicao (95.0) limita o valor exibido antes do pos-processamento.
    esperados_audio_crus = [
        max(round((40.0 + 5.0 * p / 100) / 45.0 * 100, 1), 100.0)
        for p in (0.0, 50.0, 100.0)
    ]
    assert esperados_audio_crus == [100.0, 100.0, 100.0]  # documenta o valor cru
    esperados_audio_exibidos = [min(v, 95.0) for v in esperados_audio_crus]
    assert esperados_audio_exibidos == [95.0, 95.0, 95.0]
    assert pcts[4:] == esperados_audio_exibidos


def test_baixar_video_progresso_multi_stream_sequencia_completa_e_nao_decrescente(
    tmp_path, monkeypatch, capsys
):
    """Regressao Bug 4 (CLAUDE.md secao 5.1): o percentual emitido nunca
    pode "voltar pra tras" pro usuario, nem quando o yt-dlp troca do
    stream de video pro de audio no meio do download."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = _linhas_download_video_e_audio()
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    pcts = [
        json.loads(linha[len("@PROGRESSO "):])["pct"] for linha in saida_capturada
    ]

    for anterior, atual in zip(pcts, pcts[1:]):
        assert atual >= anterior, (
            f"pct regrediu de {anterior} para {atual} na sequencia {pcts} — "
            "o clamp monotonico de _ProgressoMultiStream deveria impedir "
            "isso mesmo quando a troca de stream (video 100% -> audio 0%) "
            "diluiria o percentual combinado cru."
        )


def test_baixar_video_nunca_emite_pct_100_quando_e_o_video_final_da_lista(
    tmp_path, monkeypatch, capsys
):
    """Teste novo (Problema 1 da Sessao 3.1): mesmo quando este e' o UNICO/
    ultimo video da lista (indice=1, total=1) — o cenario onde o bug
    aparecia de verdade, pois pct_total = pct_combinado diretamente — a
    barra nunca pode bater 100.0 antes do arquivo final estar pronto. O
    verdadeiro 100.0 so e' emitido em baixar_todos(), depois do manifest
    gravado (ver secao "baixar_todos — mensagens de erro amigaveis e
    ordem de gravacao do manifest" abaixo)."""
    saida_mp4 = tmp_path / "fonte01.mp4"
    saida_mp4.write_bytes(b"conteudo de video falso")

    linhas = (
        [_linha_progresso(p, "10.00MiB") for p in (25.0, 50.0, 100.0)]
        + ["[Merger] Merging formats into \"video.mp4\"\n"]
    )
    processo_fake = ProcessoFake(linhas_stdout=linhas, returncode=0)
    monkeypatch.setattr(modulo.subprocess, "Popen", lambda *a, **k: processo_fake)

    modulo.baixar_video("https://youtu.be/abc", saida_mp4, 1, 1)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    pcts = [
        json.loads(linha[len("@PROGRESSO "):])["pct"] for linha in saida_capturada
    ]

    for anterior, atual in zip(pcts, pcts[1:]):
        assert atual >= anterior, f"pct regrediu na sequencia {pcts}"

    assert 100.0 not in pcts, (
        f"baixar_video nao deveria emitir pct=100.0 quando e' o unico/ultimo "
        f"video da lista — sequencia emitida: {pcts}. O verdadeiro 100.0 so "
        "pode vir de baixar_todos(), depois do manifest gravado."
    )


# ---------------------------------------------------------------------------
# baixar_todos — mensagens de erro amigaveis e ordem de gravacao do manifest
# (Problemas 1 e 4 da Sessao 3.1)
# ---------------------------------------------------------------------------


def test_baixar_todos_grava_manifest_antes_de_emitir_progresso_final_100(
    tmp_path, monkeypatch, capsys
):
    """Regressao Problema 1 da Sessao 3.1: pct=100.0 so pode significar
    "tudo realmente pronto" — inclusive o manifest ja gravado em disco. A
    chamada de baixar_todos e' sincrona, entao por ora que ela retorna o
    manifest ja tem que existir com o conteudo final correto (mesma
    garantia que o codigo de producao documenta: grava o manifest ANTES
    de emitir o @PROGRESSO final)."""
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\n", encoding="utf-8"
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": True,
            "titulo": "Titulo qualquer",
            "duracao_s": 60.0,
            "erro": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    modulo.baixar_todos(pasta_projeto)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    payloads = [json.loads(linha[len("@PROGRESSO "):]) for linha in saida_capturada]
    payload_final = payloads[-1]
    assert payload_final["pct"] == 100.0
    assert payload_final["sucesso"] is True

    manifest_path = pasta_projeto / "fontes" / "manifest_fontes.json"
    assert manifest_path.exists()
    manifest_lido = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_lido["sucesso"] is True
    assert manifest_lido["fontes"][0]["sucesso"] is True


def test_baixar_todos_falha_total_com_mesma_categoria_usa_mensagem_unica(
    tmp_path, monkeypatch, capsys
):
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\nhttps://youtu.be/dois\n",
        encoding="utf-8",
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": False,
            "titulo": None,
            "duracao_s": None,
            "erro": "yt-dlp saiu com codigo 1",
            "log_erro": None,
            "tipo_erro": "video_removido",
            "mensagem_usuario": "Este video foi removido pelo autor ou esta indisponivel.",
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    modulo.baixar_todos(pasta_projeto)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    payloads = [json.loads(linha[len("@PROGRESSO "):]) for linha in saida_capturada]
    payload_final = payloads[-1]

    assert payload_final["sucesso"] is False
    assert (
        payload_final["mensagem_usuario"]
        == "Este video foi removido pelo autor ou esta indisponivel."
    )


def test_baixar_todos_falha_total_com_categorias_diferentes_concatena_mensagens(
    tmp_path, monkeypatch, capsys
):
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\nhttps://youtu.be/dois\n",
        encoding="utf-8",
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        if indice == 1:
            tipo_erro, mensagem = (
                "video_removido",
                "Este video foi removido pelo autor ou esta indisponivel.",
            )
        else:
            tipo_erro, mensagem = (
                "video_privado",
                "Este video esta definido como privado e nao pode ser baixado.",
            )
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": False,
            "titulo": None,
            "duracao_s": None,
            "erro": "yt-dlp saiu com codigo 1",
            "log_erro": None,
            "tipo_erro": tipo_erro,
            "mensagem_usuario": mensagem,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    modulo.baixar_todos(pasta_projeto)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    payloads = [json.loads(linha[len("@PROGRESSO "):]) for linha in saida_capturada]
    payload_final = payloads[-1]

    assert payload_final["sucesso"] is False
    assert " | " in payload_final["mensagem_usuario"]
    assert "removido" in payload_final["mensagem_usuario"]
    assert "privado" in payload_final["mensagem_usuario"]


def test_baixar_todos_falha_parcial_inclui_tipos_erro_no_progresso_final(
    tmp_path, monkeypatch, capsys
):
    pasta_projeto = tmp_path / "caso_teste"
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "https://youtu.be/um\nhttps://youtu.be/dois\nhttps://youtu.be/tres\n",
        encoding="utf-8",
    )

    def _baixar_video_fake(url, saida_mp4, indice, total):
        if indice == 2:
            return {
                "url": url,
                "arquivo": saida_mp4.name,
                "sucesso": False,
                "titulo": None,
                "duracao_s": None,
                "erro": "yt-dlp saiu com codigo 1",
                "log_erro": None,
                "tipo_erro": "geobloqueio",
                "mensagem_usuario": (
                    "Este video nao esta disponivel na sua regiao "
                    "(bloqueio geografico do canal)."
                ),
            }
        saida_mp4.write_bytes(b"conteudo de video falso")
        return {
            "url": url,
            "arquivo": saida_mp4.name,
            "sucesso": True,
            "titulo": f"Titulo do video {indice}",
            "duracao_s": 100.0 * indice,
            "erro": None,
            "log_erro": None,
            "tipo_erro": None,
            "mensagem_usuario": None,
        }

    monkeypatch.setattr(modulo, "baixar_video", _baixar_video_fake)

    modulo.baixar_todos(pasta_projeto)

    saida_capturada = capsys.readouterr().out.strip().splitlines()
    payloads = [json.loads(linha[len("@PROGRESSO "):]) for linha in saida_capturada]
    payload_final = payloads[-1]

    assert payload_final["sucesso"] is True  # falha parcial nao derruba o job inteiro
    assert payload_final["tipos_erro"] == ["geobloqueio"]
    assert any("bloqueio geografico" in aviso for aviso in payload_final["avisos"])
