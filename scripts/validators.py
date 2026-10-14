"""Validadores e normalizadores de campos usados pelas telas de Ajustes e
Novo projeto.
"""

import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Nome de projeto vira nome de pasta em disco (CLAUDE.md secao 9: "Nomes de
# arquivo ASCII sem acento nem espaco") - letras/numeros ASCII, underscore e
# hifen apenas.
_PADRAO_NOME_PROJETO = re.compile(r"^[A-Za-z0-9_-]+$")

# Posicoes de marca d'agua suportadas pelo filtro delogo do ffmpeg
# (CLAUDE.md secao 5.7.1) - usado tanto para validar o POST /novo quanto
# para preencher o dropdown de cada link no template.
MARCAS_DAGUA_VALIDAS = frozenset(
    {
        "nenhuma",
        "superior_direito",
        "superior_esquerdo",
        "inferior_direito",
        "inferior_esquerdo",
        "banner_inferior",
    }
)

# Dominios aceitos como link de video do YouTube (CLAUDE.md secao 5.1 - Etapa
# 1 baixa videos-fonte do YouTube via yt-dlp). Nao valida que o video existe
# de fato (isso e' responsabilidade da Etapa 1) - so o formato da URL.
_PADRAO_URL_YOUTUBE = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/|youtu\.be/)",
    re.IGNORECASE,
)

# Modo de fontes do formulario de Novo projeto - "unificado" (default, uma
# unica lista de links usada para transcricao E clipes) ou "separado" (fontes
# de transcricao distintas das fontes visuais, feature de fontes separadas).
MODOS_FONTES_VALIDOS = frozenset({"unificado", "separado"})

# tipo_uso de cada fonte no manifest_fontes.json (feature de fontes
# separadas) - "ambos" (transcrita E usada como b-roll, comportamento do modo
# unificado), "transcricao" (so transcrita, nunca gera clipe) ou "visual" (so
# gera clipe, nunca transcrita).
TIPOS_USO_VALIDOS = frozenset({"ambos", "transcricao", "visual"})

# Extensoes aceitas para upload de fontes visuais proprias - imagem vira
# clipe com Ken Burns/pan (scripts/5_gerar_clipes.py), video segue o mesmo
# fluxo de corte das fontes do YouTube.
EXTENSOES_UPLOAD_IMAGEM = frozenset({".jpg", ".jpeg", ".png", ".webp"})
EXTENSOES_UPLOAD_VIDEO = frozenset({".mp4", ".mov", ".webm"})
EXTENSOES_UPLOAD_VALIDAS = EXTENSOES_UPLOAD_IMAGEM | EXTENSOES_UPLOAD_VIDEO

TAMANHO_MAX_UPLOAD_BYTES = 500 * 1024 * 1024

# Extensoes aceitas para upload de musica de fundo (CLAUDE.md secao 5.8) -
# mesmos formatos que scripts/6_montar_video.py ja sabe procurar em
# entrada/musica_fundo/.
EXTENSOES_UPLOAD_MUSICA = frozenset({".mp3", ".wav", ".m4a"})

# Intro/ending anexados ao video final (formulario de Novo projeto, secao
# "Intro e ending") - mesmos formatos de video aceitos que
# EXTENSOES_UPLOAD_VIDEO (fontes visuais proprias); reaproveitado em vez de
# duplicado porque validators.py ja e' compartilhado (nao e' um script
# autocontido - CLAUDE.md secao 9 nao se aplica aqui).
EXTENSOES_INTRO_ENDING_VALIDAS = EXTENSOES_UPLOAD_VIDEO

# Um clipe de intro/ending nao deve ser maior que uma fonte de video comum -
# mesmo teto que TAMANHO_MAX_UPLOAD_BYTES (500MB), arquivo bem maior que
# isso provavelmente e' engano do usuario (video inteiro em vez de so' a
# intro).
TAMANHO_MAX_INTRO_ENDING_BYTES = TAMANHO_MAX_UPLOAD_BYTES

# Tipo de projeto do formulario de Novo projeto - "pipeline_completa"
# (default, comportamento historico: download/transcricao/roteiro/audio/
# clipes/montagem) ou "videos_pre_gerados" (usuario ja tem os clipes finais
# prontos - ex: exportados do DarkPlanner Flow/Veo3, ja com audio embutido -
# so concatena, sem nenhuma das etapas anteriores).
TIPOS_PROJETO_VALIDOS = frozenset({"pipeline_completa", "videos_pre_gerados"})
TIPO_PROJETO_PADRAO = "pipeline_completa"

# Teto de tamanho TOTAL (soma de todos os arquivos) para o upload de videos
# pre-gerados - distinto de TAMANHO_MAX_UPLOAD_BYTES (teto POR ARQUIVO das
# fontes visuais da pipeline completa); aqui o usuario tipicamente envia
# varios clipes de uma vez, entao o teto relevante e' o total.
TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES = 2 * 1024 * 1024 * 1024

# Origem da marca d'agua do CANAL aplicada ao video final (formulario de
# Novo projeto, sessao "Marca d'agua do canal aplicada ao video final") -
# "canal" (default - usa a marca global configurada em Ajustes), "outra"
# (upload proprio deste projeto, sobrescreve a global) ou "nenhuma" (nao
# aplica marca nenhuma neste projeto, mesmo que exista uma global).
ORIGENS_MARCA_DAGUA_PROJETO_VALIDAS = frozenset({"canal", "outra", "nenhuma"})
ORIGEM_MARCA_DAGUA_PROJETO_PADRAO = "canal"

# Extensao aceita para upload de marca d'agua (global em Ajustes, ou por
# projeto) - so PNG (precisa de canal alfa para a opacidade/transparencia
# funcionar direito no overlay).
EXTENSAO_MARCA_DAGUA_VALIDA = ".png"

# Teto de tamanho para o upload de marca d'agua - um logo PNG nunca precisa
# de mais que alguns MB; bem menor que TAMANHO_MAX_UPLOAD_BYTES (fontes
# visuais de video/imagem, 500MB).
TAMANHO_MAX_MARCA_DAGUA_BYTES = 10 * 1024 * 1024

# Origem do roteiro no formulario de Novo projeto - "ia" (default,
# comportamento historico: Etapas 2+3 transcrevem e geram via Claude) ou
# "upload" (usuario fornece o texto pronto, pulando transcricao e geracao -
# feature de upload de roteiro pronto).
ORIGENS_ROTEIRO_VALIDAS = frozenset({"ia", "upload"})

# Extensoes aceitas para upload de roteiro pronto - texto simples ou
# Markdown, igual ao formato que a Etapa 3 (IA) já produz em roteiro.md.
EXTENSOES_ROTEIRO_VALIDAS = frozenset({".txt", ".md"})

# Abaixo deste tamanho, o arquivo enviado provavelmente nao e' um roteiro de
# verdade (rascunho vazio, arquivo errado) - protege contra criar um projeto
# que vai travar na revisao com quase nada pra revisar.
TAMANHO_MIN_ROTEIRO_CHARS = 100

# Duracoes oferecidas pelo dropdown de "Sincronizacao inteligente com IA"
# (formulario de Novo projeto) - segundos do INICIO da narracao a analisar
# em busca de ancoras visuais. 0 significa "video inteiro". Default 600
# (10 minutos) se o campo vier ausente/invalido.
SINCRONIZACAO_DURACOES_VALIDAS = frozenset({300, 600, 900, 0})
SINCRONIZACAO_DURACAO_PADRAO_S = 600

# Faixa aceita para o campo "Tamanho alvo do roteiro" (formulario de Novo
# projeto) - passada adiante para scripts/3_gerar_roteiro.py, que injeta o
# alvo no prompt de sistema. Default 4000 palavras / 25 min, mesmo padrao
# historico implicito no prompt de cada perfil (25.000-35.000 caracteres
# sem espacos ~ 4000-5500 palavras em portugues).
PALAVRAS_ALVO_PADRAO = 4000
PALAVRAS_ALVO_MIN = 1000
PALAVRAS_ALVO_MAX = 15000
DURACAO_ALVO_MINUTOS_PADRAO = 25
DURACAO_ALVO_MINUTOS_MIN = 5
DURACAO_ALVO_MINUTOS_MAX = 120


def normalizar_palavras_alvo(valor: str | None) -> int:
    """Normaliza o campo `palavras_alvo` do formulario de Novo projeto para
    um inteiro dentro de [PALAVRAS_ALVO_MIN, PALAVRAS_ALVO_MAX]. Ausente/
    nao-numerico/fora da faixa cai no default de 4000 - nunca levanta
    excecao (mesmo espirito de normalizar_sincronizacao_duracao)."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return PALAVRAS_ALVO_PADRAO
    if numero < PALAVRAS_ALVO_MIN or numero > PALAVRAS_ALVO_MAX:
        return PALAVRAS_ALVO_PADRAO
    return numero


def normalizar_duracao_alvo_minutos(valor: str | None) -> int:
    """Normaliza o campo `duracao_alvo_minutos` do formulario de Novo
    projeto para um inteiro dentro de [DURACAO_ALVO_MINUTOS_MIN,
    DURACAO_ALVO_MINUTOS_MAX]. Ausente/nao-numerico/fora da faixa cai no
    default de 25 - nunca levanta excecao."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return DURACAO_ALVO_MINUTOS_PADRAO
    if numero < DURACAO_ALVO_MINUTOS_MIN or numero > DURACAO_ALVO_MINUTOS_MAX:
        return DURACAO_ALVO_MINUTOS_PADRAO
    return numero


def validar_modo_fontes(valor: str) -> bool:
    """True se `valor` e' um modo de fontes suportado pelo formulario de
    Novo projeto."""
    return valor in MODOS_FONTES_VALIDOS


def validar_tipo_uso(valor: str) -> bool:
    """True se `valor` e' um tipo_uso valido para uma fonte (manifest da
    Etapa 1)."""
    return valor in TIPOS_USO_VALIDOS


def validar_origem_roteiro(valor: str) -> bool:
    """True se `valor` e' uma origem de roteiro suportada pelo formulario de
    Novo projeto."""
    return valor in ORIGENS_ROTEIRO_VALIDAS


def validar_tipo_projeto(valor: str) -> bool:
    """True se `valor` e' um tipo de projeto suportado pelo formulario de
    Novo projeto ("pipeline_completa" ou "videos_pre_gerados")."""
    return valor in TIPOS_PROJETO_VALIDOS


def prefixo_numerico_arquivo(nome_arquivo: str) -> int:
    """Extrai o prefixo numerico do INICIO do nome de um arquivo (ex.
    '2_close_up.mp4' -> 2, '10_wide.mp4' -> 10) - usado para ordenar os
    videos pre-gerados na ordem que o usuario pretendia, ja que a ordem de
    selecao de um <input type=file multiple> no navegador nao e' garantida
    seguir ordem alfabetica/numerica (e ordenacao puramente alfabetica
    colocaria '10_wide.mp4' antes de '2_close_up.mp4').

    Arquivo sem prefixo numerico vai pro fim (numero bem grande) - nunca
    ordena antes de um arquivo numerado."""
    match = re.match(r"^(\d+)", Path(nome_arquivo).stem)
    return int(match.group(1)) if match else 10**9


def validar_arquivo_roteiro(nome_arquivo: str, texto: str) -> str | None:
    """Valida um roteiro pronto enviado por upload: extensao (.txt/.md) e
    tamanho minimo de conteudo. Retorna a mensagem de erro, ou None se
    valido. Nao decodifica o arquivo - `texto` ja deve vir decodificado pelo
    chamador (server.py precisa do texto de qualquer forma pra gravar
    roteiro.md, entao decodifica uma unica vez)."""
    if not nome_arquivo:
        return "Envie um arquivo de roteiro (.txt ou .md)."
    extensao = Path(nome_arquivo).suffix.lower()
    if extensao not in EXTENSOES_ROTEIRO_VALIDAS:
        return "Arquivo de roteiro deve ser .txt ou .md."
    if len(texto.strip()) < TAMANHO_MIN_ROTEIRO_CHARS:
        return f"Roteiro muito curto (minimo {TAMANHO_MIN_ROTEIRO_CHARS} caracteres)."
    return None


def classificar_extensao_upload(nome_arquivo: str) -> str | None:
    """Classifica um nome de arquivo enviado por upload como "imagem",
    "video", ou None se a extensao nao e' suportada. Nao valida conteudo do
    arquivo, so a extensao (protecao contra manipulacao de request e' feita
    revalidando aqui - o <input accept=...> do formulario e' so uma dica de
    UX, nao seguranca)."""
    extensao = Path(nome_arquivo).suffix.lower()
    if extensao in EXTENSOES_UPLOAD_IMAGEM:
        return "imagem"
    if extensao in EXTENSOES_UPLOAD_VIDEO:
        return "video"
    return None


def validar_extensao_musica(nome_arquivo: str) -> bool:
    """True se `nome_arquivo` tem uma extensao aceita para upload de musica
    de fundo (.mp3/.wav/.m4a) - nunca confia no `accept=` do <input>, que e'
    so' dica de UX."""
    return Path(nome_arquivo).suffix.lower() in EXTENSOES_UPLOAD_MUSICA


def validar_extensao_intro_ending(nome_arquivo: str) -> bool:
    """True se `nome_arquivo` tem uma extensao de video aceita para
    intro/ending (secao "Intro e ending anexados ao video final") - nunca
    confia no `accept=` do <input>, que e' so' dica de UX."""
    return Path(nome_arquivo).suffix.lower() in EXTENSOES_INTRO_ENDING_VALIDAS


def validar_video_legivel_ffprobe(caminho: Path) -> tuple[bool, float, str | None]:
    """Confirma que `caminho` e' um arquivo de video legivel pelo ffmpeg
    (stream de video decodificavel, duracao > 0) via ffprobe - usado pra
    avisar CEDO no formulario de Novo projeto (upload de intro/ending) em
    vez de so' descobrir um arquivo corrompido/ilegivel na montagem final
    (CLAUDE.md secao 18.6 - validar pre-condicao antes de fingir
    processar). Retorna (True, duracao_s, None) se legivel, ou
    (False, 0.0, mensagem_de_erro) caso contrario - nunca levanta excecao:
    ffprobe ausente do PATH tambem vira erro claro em vez de deixar o
    upload seguir silenciosamente com um arquivo nunca verificado."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1",
                str(caminho),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, 0.0, f"Nao foi possivel validar o arquivo de video (ffprobe indisponivel: {exc})."

    saida = resultado.stdout or ""
    if resultado.returncode != 0 or "codec_type=video" not in saida:
        return False, 0.0, "Arquivo de video ilegivel, corrompido ou sem faixa de video."

    duracao_match = re.search(r"duration=([\d.]+)", saida)
    if not duracao_match:
        return False, 0.0, "Nao foi possivel ler a duracao do arquivo de video."
    try:
        duracao_s = float(duracao_match.group(1))
    except ValueError:
        return False, 0.0, "Duracao do arquivo de video invalida."
    if duracao_s <= 0:
        return False, 0.0, "Arquivo de video com duracao zero."

    return True, round(duracao_s, 3), None


def validar_nome_projeto(nome: str) -> tuple[bool, str]:
    """Valida um nome de projeto digitado no formulario de Novo projeto.

    Retorna (True, nome) se valido, ou (False, mensagem_de_erro) caso
    contrario. Nao levanta excecao.
    """
    if not nome:
        return False, "Informe um nome para o projeto."
    if not _PADRAO_NOME_PROJETO.match(nome):
        return False, (
            "Nome do projeto invalido - use apenas letras, numeros, "
            "hifen e underscore, sem espacos nem acentos."
        )
    return True, nome


def normalizar_caminho(valor_bruto: str) -> str:
    """Limpa e normaliza um caminho de pasta digitado/colado pelo usuario.

    Remove espacos nas pontas, aspas envolventes (o Explorer as vezes cola
    o caminho entre aspas ao copiar "Copiar como caminho"), e resolve o
    resultado via pathlib para eliminar barra final, `.`/`..` e uniformizar
    os separadores para o padrao do SO.
    """
    valor = valor_bruto.strip()
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
        valor = valor[1:-1].strip()
    return str(Path(valor).resolve())


def validar_caminho_projetos(caminho: str) -> tuple[bool, str]:
    """Valida (e garante) que `caminho` pode ser usado como PROJETOS_DIR.

    Verifica se o drive/raiz existe, cria a pasta se ainda nao existir, e
    confirma permissao de escrita criando e apagando um arquivo de teste.

    Retorna (True, caminho_normalizado) se tudo ok, ou (False, mensagem_de_erro)
    caso contrario. Nao levanta excecao - todo erro esperado vira mensagem.
    """
    caminho_path = Path(caminho)

    raiz = Path(caminho_path.anchor) if caminho_path.anchor else None
    if raiz is None or not raiz.exists():
        return False, f"O drive/raiz '{caminho_path.anchor or caminho}' nao existe."

    try:
        caminho_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Nao foi possivel criar a pasta '{caminho_path}': {exc}"

    arquivo_teste = caminho_path / ".permtest"
    try:
        arquivo_teste.write_text("teste", encoding="utf-8")
        arquivo_teste.unlink()
    except OSError as exc:
        return False, f"Sem permissao de escrita em '{caminho_path}': {exc}"

    return True, str(caminho_path)


def validar_marca_dagua(valor: str) -> bool:
    """True se `valor` e' uma das posicoes de marca d'agua suportadas
    (CLAUDE.md secao 5.7.1), incluindo "nenhuma"."""
    return valor in MARCAS_DAGUA_VALIDAS


def validar_origem_marca_dagua_projeto(valor: str) -> bool:
    """True se `valor` e' uma origem valida de marca d'agua do canal para o
    formulario de Novo projeto ("canal"/"outra"/"nenhuma")."""
    return valor in ORIGENS_MARCA_DAGUA_PROJETO_VALIDAS


def validar_url_youtube(url: str) -> bool:
    """Valida (superficialmente, so o formato) se `url` parece um link de
    video do YouTube - dominios youtube.com ou youtu.be, com esquema http(s).
    Nao confirma que o video existe; isso e' responsabilidade da Etapa 1
    (scripts/1_baixar_videos.py) via yt-dlp."""
    return bool(_PADRAO_URL_YOUTUBE.match(url.strip()))


# ID de video do YouTube: 11 caracteres alfanumericos/hifen/underscore -
# formato estavel usado em toda URL de video (watch?v=, youtu.be/, shorts/,
# embed/, live/).
_PADRAO_ID_YOUTUBE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def chave_dedup_youtube(url: str) -> str:
    """Chave de deduplicacao para uma URL de video do YouTube (CLAUDE.md
    secao 5.7.2 - modo de fontes separadas: a mesma URL pode aparecer nas
    listas de transcricao E visual, em formatos diferentes apontando pro
    mesmo video - youtu.be/<id>, youtube.com/watch?v=<id>, .../shorts/<id>,
    com ou sem www./m., com ou sem parametros extras como timestamp ou
    playlist).

    Extrai so' o ID do video quando reconhece um formato conhecido de URL do
    YouTube - duas URLs com o mesmo ID sao o MESMO video, mesmo com
    dominio/parametros diferentes. Se nao reconhecer o formato (dominio
    diferente, link malformado, ID em posicao inesperada), cai para a URL
    inteira normalizada (minusculas, sem espaco nas pontas) - nunca lanca
    excecao, e nunca arrisca fundir duas URLs que nao tem certeza de serem o
    mesmo video (prefere baixar duas vezes a fundir errado)."""
    bruta = (url or "").strip()
    if not bruta:
        return ""
    try:
        partes = urlparse(bruta)
    except ValueError:
        return bruta.lower()

    host = (partes.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]

    candidato_id = None
    if host == "youtu.be":
        candidato_id = partes.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        segmentos = [s for s in partes.path.split("/") if s]
        if partes.path.startswith("/watch"):
            valores = parse_qs(partes.query).get("v")
            candidato_id = valores[0] if valores else None
        elif segmentos and segmentos[0] in ("shorts", "embed", "live") and len(segmentos) >= 2:
            candidato_id = segmentos[1]

    if candidato_id and _PADRAO_ID_YOUTUBE.match(candidato_id):
        return f"youtube:{candidato_id}"

    return bruta.lower()


def normalizar_sincronizacao_duracao(valor: str | None) -> int:
    """Normaliza o campo `sincronizacao_duracao` do dropdown de
    Sincronizacao inteligente (formulario de Novo projeto) para um inteiro
    valido em SINCRONIZACAO_DURACOES_VALIDAS. Ausente/nao-numerico/fora da
    lista (protecao contra manipulacao de request, o <select> so oferece as
    opcoes validas) cai no default de 600s - nunca levanta excecao."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return SINCRONIZACAO_DURACAO_PADRAO_S
    if numero not in SINCRONIZACAO_DURACOES_VALIDAS:
        return SINCRONIZACAO_DURACAO_PADRAO_S
    return numero
