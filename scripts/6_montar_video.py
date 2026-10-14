"""Etapa 6 do pipeline (nova, unificada) - monta o video final: concatena os
clipes gerados pela Etapa 5 (clipes/indice.json), faz mux com a narracao
(narracao.mp3) e, opcionalmente, musica de fundo com ducking automatico
(sidechaincompress) e loop sequencial de playlist, gera legendas (SRT sempre,
embutido como softsub no mp4 final) e queima legenda estilo "MrBeast"
(branco, contorno preto grosso, karaoke por palavra) se configurado,
exportando saida/video_final.mp4.

Uso: python "scripts/6_montar_video.py" <caminho_da_pasta_do_projeto>

Entrada:
- clipes/indice.json (Etapa 5) - lista de clipes gerados, na ordem final do
  video (contrato CLAUDE.md secao 6)
- narracao.mp3 + narracao_alinhamento.json (Etapa 4) - audio da narracao e
  timestamps por palavra ({"palavras": [{"palavra","inicio_s","fim_s"}]})
- entrada/configuracao_video.json (formulario de Novo projeto, opcional) -
  {"legendas_queimadas": bool, "com_musica_fundo": bool}. Ausente = ambos
  false (softsub sempre, sem musica, sem queimadas).
- entrada/musica_fundo/*.{mp3,wav,m4a} (upload manual do usuario, opcional) -
  pasta com uma ou mais faixas; playlist toca em ordem alfabetica e repete
  em loop sequencial ate cobrir a duracao do video. Fallback (compatibilidade
  com projetos antigos): entrada/musica_fundo.{mp3,wav,m4a}, arquivo unico.
  So' e' usada se com_musica_fundo=true E houver pelo menos uma faixa.

Saida:
- saida/video_final.mp4 - clipes concatenados + narracao (+ musica com
  ducking, se configurado) + softsub SRT sempre embutido + legenda
  queimada (ASS) se configurado
- saida/legendas.srt - arquivo avulso com o mesmo conteudo do softsub
- saida/legendas.ass - so' gerado se legendas_queimadas=true
- saida/montagem_metadata.json - resumo da montagem (contagem de clipes,
  opcoes aplicadas, tempo total)

O concat via arquivo de lista + demuxer `-f concat` e o mux em comandos
ffmpeg separados (concat -> mux -> [queimar legenda] -> softsub) e' o
mesmo padrao usado pelo projeto yt_automation (Gustavo Xavier, GitHub) -
app/assembler.py - solucao generica que qualquer engenheiro monta igual
para esse problema.

Este script e' autocontido (CLAUDE.md secao 9) - exceto por
scripts/robustez.py (checagem de ffmpeg no PATH), infra transversal
(CLAUDE.md secao 18). `_detectar_encoder_gpu`/`_params_encoder` sao
duplicados de scripts/5_gerar_clipes.py de proposito (scripts
autocontidos, sem utils compartilhado - CLAUDE.md secao 9).

Concat com duracao por SLOT (reorganizacao manual - Feature B): cada
clipe em clipes/indice.json pode ter `duracao_slot_s`/`inicio_slot_s`/
`fim_slot_s` - a duracao que a POSICAO do clipe na timeline deve ocupar,
que pode ser diferente da duracao real do arquivo (`duracao_s`) depois que
o usuario arrasta um clipe pra outra posicao na tela de reorganizacao
manual (server.py:/reordenar_clipes). `_migrar_slots_clipes` preenche esses
3 campos com fallback (`duracao_slot_s = duracao_s`, mesma semantica de
antes desta feature) quando ausentes - indice.json de projetos gerados
antes desta sessao nunca tem esses campos, entao sempre caem no fallback.
`concat_clipes` so' usa o caminho novo (filter_complex com `trim` por
posicao, via `-filter_complex_script <arquivo>` - nao `-filter_complex
"<string>"`, porque com 200+ clipes a string do filtro estoura o limite de
linha de comando do Windows) quando pelo menos um clipe tem
`duracao_slot_s` != `duracao_s` de verdade (`_precisa_de_trim`). Caso
contrario usa o caminho ORIGINAL (demuxer `-f concat` + `-c copy`, sem
reencoding) sem nenhuma alteracao - garante que todo projeto que nunca
passou pela reorganizacao manual gera o video final exatamente como antes
desta sessao.

Marca d'agua do CANAL (sessao "Marca d'agua do canal aplicada ao video
final" - scripts/marca_dagua_canal.py): overlay opcional do logo do
usuario, resolvido por `resolver_marca_dagua` (global de Ajustes, ou
sobrescrita por projeto em entrada/marca_dagua_canal.png), fundido na
MESMA passada de ffmpeg que ja queima a legenda quando as duas estao
ativas (`aplicar_marca_dagua`) - nunca uma passada de reencode extra so'
pra marca quando ja existe uma pra legenda. Sem marca configurada, o
caminho de montagem fica identico ao de antes desta sessao.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/ precisa estar no sys.path para `import robustez` funcionar tanto
# rodando este arquivo direto quanto carregado via importlib nos testes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robustez  # noqa: E402
import marca_dagua_canal  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes - encoding de video (herdadas de 5_gerar_clipes.py)
# ---------------------------------------------------------------------------

ENCODER_PADRAO = "libx264"
PRESET_X264 = "veryfast"

TIMEOUT_CONCAT_S = 300
# Caminho com trim por slot (Feature B) reencoda o video inteiro (filtro
# trim+concat nao suporta `-c copy`) - bem mais lento que o concat demuxer
# original, timeout maior para projetos longos (30-40min de narracao).
TIMEOUT_CONCAT_FILTRO_S = 1800
TIMEOUT_MUX_S = 300
TIMEOUT_QUEIMAR_LEGENDAS_S = 900
TIMEOUT_SOFTSUB_S = 180

EXTENSOES_MUSICA_VALIDAS = (".mp3", ".wav", ".m4a")

# ---------------------------------------------------------------------------
# Constantes - intro/ending anexados ao video final (sessao "Intro e ending
# anexados ao video final"). Arquivos opcionais em entrada/intro.<ext>/
# entrada/ending.<ext> (formulario de Novo projeto). Mesmos formatos
# aceitos que EXTENSOES_UPLOAD_VIDEO de scripts/validators.py - duplicado
# aqui de proposito (script autocontido, CLAUDE.md secao 9).
# ---------------------------------------------------------------------------

EXTENSOES_INTRO_ENDING_VALIDAS = (".mp4", ".mov", ".webm")
TIMEOUT_NORMALIZAR_INTRO_ENDING_S = 300
TIMEOUT_CONCAT_INTRO_ENDING_S = 300
# Tolerancia de comparacao de fps (float) contra o video ja montado - fps
# nao inteiro (23.976 vs 23.98 arredondado pelo ffprobe) nao pode reprovar
# a checagem "ja esta no padrao" por erro de arredondamento.
TOLERANCIA_FPS_INTRO_ENDING = 0.05

# ---------------------------------------------------------------------------
# Constantes - marca d'agua do CANAL aplicada ao video final (sessao "Marca
# d'agua do canal aplicada ao video final") - oposto de marcas_dagua.json
# (Etapa 5, remove marca das FONTES); aqui a marca e' do usuario, somada por
# cima do video ja montado.
# ---------------------------------------------------------------------------

# Local FIXO, global (fora de qualquer pasta de projeto - CLAUDE.md secao 9
# nao se aplica aqui: e' configuracao de produto, nao dado de projeto),
# configurado uma unica vez em Ajustes e reaproveitado por todo projeto que
# nao sobrescrever com a propria marca. Mesmo padrao de BASE_DIR/.env em
# server.py.
PASTA_CONFIG_GLOBAL = Path(__file__).resolve().parent.parent / "config"
ARQUIVO_MARCA_DAGUA_GLOBAL = PASTA_CONFIG_GLOBAL / "marca_dagua_canal.png"

# Posicao configurada em Ajustes (CAMPOS_AJUSTES) - mesmo padrao de leitura
# direta de os.environ que LEGENDA_*/MUSICA_VOLUME_BASE ja usam neste
# arquivo. Valor invalido/ausente cai no default (canto inferior direito).
MARCA_DAGUA_CANAL_POSICAO = os.environ.get("MARCA_DAGUA_CANAL_POSICAO", marca_dagua_canal.POSICAO_PADRAO)
if not marca_dagua_canal.validar_posicao(MARCA_DAGUA_CANAL_POSICAO):
    MARCA_DAGUA_CANAL_POSICAO = marca_dagua_canal.POSICAO_PADRAO

# Largura assumida quando o ffprobe da largura real do video falha (nunca
# bloqueia a montagem por isso) - 1920 e' a largura de exportacao padrao do
# produto (CLAUDE.md secao 5.8: "1080p 16:9").
LARGURA_VIDEO_PADRAO_PX = 1920

# ---------------------------------------------------------------------------
# Constantes - ducking da musica de fundo (documentado nesta sessao)
# ---------------------------------------------------------------------------

# Musica baixada pra uma fracao do volume original como base (0.18 = ~-15dB,
# default), e' comprimida ainda mais quando a narracao esta tocando
# (sidechaincompress). Configuravel via Ajustes (CLAUDE.md secao 7) - clamp
# entre 0.05 (quase mudo) e 0.50 (alto demais, compete com a voz) protege
# contra valor absurdo digitado no .env.
try:
    MUSICA_VOLUME_BASE = float(os.environ.get("MUSICA_VOLUME_BASE", "0.18"))
    MUSICA_VOLUME_BASE = max(0.05, min(0.50, MUSICA_VOLUME_BASE))
except ValueError:
    MUSICA_VOLUME_BASE = 0.18
DUCKING_THRESHOLD = 0.02  # ativa a compressao quando a narracao passa desse nivel
DUCKING_RATIO = 8  # comprime 8:1 quando ativo
DUCKING_ATTACK_MS = 5  # tempo para comecar a comprimir
DUCKING_RELEASE_MS = 200  # tempo para descomprimir depois da voz

# ---------------------------------------------------------------------------
# Constantes - playlist de musica de fundo com loop sequencial (sessao de
# correcao pos-teste real: musica mais curta que o video parava no meio e o
# resto do video ficava so' com a narracao)
# ---------------------------------------------------------------------------

TIMEOUT_MUSICA_CONCAT_S = 120
TIMEOUT_MUSICA_LOOP_S = 60
# Folga alem da duracao da narracao ao cortar o loop da musica - cobre
# pequenas diferencas entre a duracao da narracao e a duracao real do video
# concatenado (o mux final usa `-shortest`, entao um pouco de sobra aqui
# nunca aparece no video, so' evita cortar a musica curta demais).
FOLGA_MUSICA_S = 5.0

# ---------------------------------------------------------------------------
# Constantes - legenda queimada estilo "MrBeast" (branco, contorno preto
# grosso, karaoke por palavra) - substitui o antigo estilo "pill"/TikTok
# (fundo branco/texto preto), que ficava ilegivel sobre video escuro de true
# crime (sessao de correcao pos-teste real)
# ---------------------------------------------------------------------------

# Fonte, tamanho, cor de destaque, posicao vertical e karaoke on/off sao
# configuraveis via Ajustes (CLAUDE.md secao 7). Cor primaria (branca),
# contorno/sombra (preto) e espessura do contorno continuam fixos - sao o
# que garante legibilidade da legenda sobre qualquer fundo de video, nao
# viram campo editavel.

FONTES_LEGENDA_SUPORTADAS = ["Poppins Bold", "Arial Black", "Impact"]
LEGENDA_FONTE_PADRAO = os.environ.get("LEGENDA_FONTE", "Poppins Bold")
if LEGENDA_FONTE_PADRAO not in FONTES_LEGENDA_SUPORTADAS:
    LEGENDA_FONTE_PADRAO = "Poppins Bold"  # fallback silencioso (valor invalido no .env)
# LEGENDA_FONTE_BASE e' usada so' pra checar se a familia esta instalada
# (_fonte_disponivel busca substring no nome do arquivo) - primeira palavra
# do Fontname escolhido (ex: "Poppins Bold" -> "Poppins"). Limitacao
# conhecida: a checagem de substring nao distingue pesos (Regular vs Bold) -
# se so' o peso Regular estiver instalado, o ASS ainda pede "Poppins Bold" e
# o libass pode nao achar a familia exata, usando uma fonte padrao do
# sistema em vez de cair no fallback Arial Black.
LEGENDA_FONTE_BASE = LEGENDA_FONTE_PADRAO.split(" ")[0]
LEGENDA_FONTE_FALLBACK = "Arial Black"

TAMANHOS_LEGENDA_SUPORTADOS = [56, 64, 72]  # Pequeno / Padrao / Grande
try:
    LEGENDA_TAMANHO_PT = int(os.environ.get("LEGENDA_TAMANHO", "64"))
    if LEGENDA_TAMANHO_PT not in TAMANHOS_LEGENDA_SUPORTADOS:
        LEGENDA_TAMANHO_PT = 64
except ValueError:
    LEGENDA_TAMANHO_PT = 64

# Posicao vertical da legenda (distancia da borda inferior, em px @1080p).
POSICOES_LEGENDA = {
    "baixo": 140,  # padrao MrBeast
    "meio-baixo": 300,  # sobe um pouco
}
LEGENDA_MARGEM_V = POSICOES_LEGENDA.get(os.environ.get("LEGENDA_POSICAO", "baixo"), 140)

# Karaoke por palavra (tag \k) ligado/desligado - se desligado, a frase
# inteira sai em PrimaryColour, sem destaque de palavra atual.
LEGENDA_KARAOKE_ATIVO = os.environ.get("LEGENDA_KARAOKE_ATIVO", "true").lower() in ("true", "1", "sim")

MRBEAST_COR_PRIMARIA = "&H00FFFFFF"  # branco - texto ja' dito / nao destacado (fixo, legibilidade)
CORES_DESTAQUE_SUPORTADAS = {
    "amarelo": "&H0000FFFF",  # padrao MrBeast
    "verde": "&H0000FF00",
    "laranja": "&H000080FF",
    "rosa": "&H00FF00FF",
}
MRBEAST_COR_DESTAQUE = CORES_DESTAQUE_SUPORTADAS.get(
    os.environ.get("LEGENDA_DESTAQUE_COR_NOME", "amarelo"),
    CORES_DESTAQUE_SUPORTADAS["amarelo"],
)
MRBEAST_COR_CONTORNO = "&H00000000"  # preto (fixo, legibilidade)
MRBEAST_COR_SOMBRA = "&H00000000"  # preto (fixo, legibilidade)
MRBEAST_BORDER_STYLE = 1  # so' contorno + sombra (3 = caixa solida, estilo antigo)
MRBEAST_OUTLINE_ESPESSURA = 4  # fixo, legibilidade
MRBEAST_SHADOW = 2
MRBEAST_MARGEM_LR = 60

# Agrupamento de palavras em frases de legenda: fecha o grupo atual ao
# encontrar pontuacao de fim de frase, ou quando o grupo fica grande/longo
# demais mesmo sem pontuacao (narracao corrida sem pausas claras).
LEGENDA_DURACAO_MAX_S = 6.0
LEGENDA_PALAVRAS_MAX = 14

_PADRAO_FIM_FRASE = re.compile(r"[.!?…]+[\"'\)\]]*$")


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


# ---------------------------------------------------------------------------
# Leitura de entrada
# ---------------------------------------------------------------------------


def _ler_indice_clipes(pasta_projeto: Path) -> list:
    """Lista de clipes de clipes/indice.json (Etapa 5), na ordem final do
    video. Lista vazia se o arquivo nao existe, esta corrompido, ou nao tem
    clipes - nunca levanta excecao."""
    caminho = pasta_projeto / "clipes" / "indice.json"
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return dados.get("clipes") or []


def _ler_alinhamento_narracao(pasta_projeto: Path):
    caminho = pasta_projeto / "narracao_alinhamento.json"
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ler_tipo_projeto(pasta_projeto: Path) -> str:
    """Le entrada/tipo_projeto.txt ("pipeline_completa" ou
    "videos_pre_gerados" - CLAUDE.md secao 3, "Vídeos pré-gerados"). Mesma
    convencao/valores que server.py:_ler_tipo_projeto - duplicado aqui de
    proposito (script autocontido, CLAUDE.md secao 9). Ausente (projeto
    criado antes desta feature, ou pasta desconhecida) sempre significa
    "pipeline_completa" - retrocompatibilidade total."""
    caminho = pasta_projeto / "entrada" / "tipo_projeto.txt"
    if not caminho.exists():
        return "pipeline_completa"
    try:
        valor = caminho.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return "pipeline_completa"
    return valor if valor in ("pipeline_completa", "videos_pre_gerados") else "pipeline_completa"


def ler_configuracao_video(pasta_projeto: Path) -> dict:
    """Le entrada/configuracao_video.json (formulario de Novo projeto).
    Ausente/corrompido = defaults seguros (sem musica, sem legenda
    queimada, sem grayscale) - nunca levanta excecao (CLAUDE.md secao
    18.6). Campo ausente no JSON (todo projeto criado antes do grayscale)
    cai no default False - retrocompatibilidade total."""
    padrao = {
        "legendas_queimadas": False,
        "com_musica_fundo": False,
        "grayscale": False,
        # "canal" (default - usa a marca global de Ajustes se houver),
        # "outra" (upload proprio do projeto) ou "nenhuma". Ausente (todo
        # projeto criado antes desta feature) cai em "canal" - mesma
        # semantica de retrocompatibilidade descrita no formulario de Novo
        # projeto: comportamento muda so' se o usuario JA tiver configurado
        # uma marca global, e mesmo assim e' o comportamento esperado (a
        # marca do canal e' pra aparecer em todo projeto por padrao).
        "marca_dagua_projeto": "canal",
    }
    caminho = pasta_projeto / "entrada" / "configuracao_video.json"
    if not caminho.exists():
        return padrao
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return padrao
    for chave in ("legendas_queimadas", "com_musica_fundo", "grayscale"):
        if chave in dados:
            padrao[chave] = bool(dados[chave])
    valor_marca = dados.get("marca_dagua_projeto")
    if valor_marca in ("canal", "outra", "nenhuma"):
        padrao["marca_dagua_projeto"] = valor_marca
    return padrao


def descobrir_musica_upload(pasta_projeto: Path):
    """Primeiro arquivo entrada/musica_fundo.{mp3,wav,m4a} encontrado, ou
    None se o usuario nao fez upload de musica nenhuma. Formato legado
    (arquivo unico) - preservado para compatibilidade, ver
    `descobrir_playlist_musicas`."""
    pasta_entrada = pasta_projeto / "entrada"
    for extensao in EXTENSOES_MUSICA_VALIDAS:
        candidato = pasta_entrada / f"musica_fundo{extensao}"
        if candidato.exists():
            return candidato
    return None


def descobrir_playlist_musicas(pasta_projeto: Path) -> list:
    """Lista ordenada (alfabeticamente) de faixas de musica de fundo.

    Prioriza a pasta entrada/musica_fundo/ (uma ou mais faixas - a ordem
    alfabetica dos nomes de arquivo define a ordem de reproducao da
    playlist). Se a pasta nao existir ou estiver vazia, cai para o formato
    legado de arquivo unico entrada/musica_fundo.{mp3,wav,m4a}
    (`descobrir_musica_upload`). Lista vazia se nao houver musica nenhuma -
    nunca levanta excecao (CLAUDE.md secao 18.6)."""
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    if pasta_musicas.is_dir():
        try:
            musicas = sorted(
                arquivo
                for arquivo in pasta_musicas.iterdir()
                if arquivo.is_file() and arquivo.suffix.lower() in EXTENSOES_MUSICA_VALIDAS
            )
        except OSError:
            musicas = []
        if musicas:
            return musicas

    arquivo_legado = descobrir_musica_upload(pasta_projeto)
    return [arquivo_legado] if arquivo_legado else []


def _descobrir_arquivo_intro_ending(pasta_projeto: Path, papel: str):
    """Primeiro arquivo entrada/<papel>.<ext> encontrado (papel = "intro" ou
    "ending"), ou None se o usuario nao enviou nenhum (ambos opcionais -
    CLAUDE.md secao "Intro e ending anexados ao video final"). Nunca levanta
    excecao."""
    pasta_entrada = pasta_projeto / "entrada"
    for extensao in EXTENSOES_INTRO_ENDING_VALIDAS:
        candidato = pasta_entrada / f"{papel}{extensao}"
        if candidato.exists():
            return candidato
    return None


def descobrir_intro(pasta_projeto: Path):
    return _descobrir_arquivo_intro_ending(pasta_projeto, "intro")


def descobrir_ending(pasta_projeto: Path):
    return _descobrir_arquivo_intro_ending(pasta_projeto, "ending")


def resolver_marca_dagua(pasta_projeto: Path, config: dict) -> tuple:
    """Decide qual arquivo PNG de marca d'agua do CANAL usar (se algum) para
    este projeto, conforme `config["marca_dagua_projeto"]` ("canal"/"outra"/
    "nenhuma" - `ler_configuracao_video`).

    Retorna (caminho_png_ou_None, aviso_ou_None). Nunca levanta excecao
    (CLAUDE.md secao 18.6): PNG configurado mas ausente do disco vira aviso
    (nao erro fatal - a montagem segue sem marca), marca global nunca
    configurada em Ajustes (arquivo simplesmente nao existe) nao e' aviso
    nenhum, so' significa "nenhuma marca aplicada", igual a "nenhuma"
    explicito."""
    modo = config.get("marca_dagua_projeto", "canal")
    if modo not in ("canal", "outra", "nenhuma"):
        modo = "canal"

    if modo == "nenhuma":
        return None, None

    if modo == "outra":
        caminho = pasta_projeto / "entrada" / "marca_dagua_canal.png"
        if not caminho.exists():
            return None, (
                "Marca d'agua propria deste projeto nao foi encontrada em disco - "
                "video montado sem marca d'agua."
            )
        return caminho, None

    # modo == "canal": marca global configurada em Ajustes, se houver.
    if not ARQUIVO_MARCA_DAGUA_GLOBAL.exists():
        return None, None
    return ARQUIVO_MARCA_DAGUA_GLOBAL, None


# ---------------------------------------------------------------------------
# Agrupamento de palavras em frases de legenda (funcao pura)
# ---------------------------------------------------------------------------


def _expandir_palavras_multiplas(palavras: list) -> list:
    """Explode qualquer entrada de `palavras` cujo campo "palavra" contenha
    MAIS DE UM token (separado por espaco) em sub-entradas de uma palavra
    cada, interpolando `inicio_s`/`fim_s` proporcionalmente ao comprimento
    em caracteres de cada sub-palavra dentro do intervalo original do bloco.

    Necessario porque nem todo alinhamento que chega aqui e' de fato
    per-palavra apesar do nome do campo: o SRT "srt_palavra" do provedor
    DarkPlanner (scripts/tts/darkplanner.py) pode devolver blocos de varias
    palavras por timestamp (achado real de producao, projeto
    teste_srt_darkplanner: blocos de ate 9 palavras) - sem essa expansao, o
    karaoke por palavra (`gerar_dialogue_karaoke`) destaca o bloco inteiro
    de uma vez em vez de palavra por palavra, porque a tag `\\k` e' aplicada
    por ENTRADA da lista, nao por palavra de fato. Nao mexe em
    scripts/tts/darkplanner.py (Feature 1, fora de escopo desta correcao) -
    o parsing do SRT la' esta correto pro formato que o provedor devolve;
    esta funcao normaliza a granularidade aqui, no consumidor.

    HEURISTICA, nao medicao real de fala: divide o tempo proporcionalmente
    ao tamanho em caracteres de cada sub-palavra, assumindo cadencia
    aproximadamente constante dentro do bloco - nao reflete pausas/enfase
    reais. Aproximacao aceitavel para o efeito visual do karaoke, nao para
    precisao de alinhamento.

    Invariante preservado (testado): a primeira sub-palavra comeca exatamente
    em `inicio_s` do bloco original e a ultima termina exatamente em
    `fim_s` - a soma das duracoes das sub-palavras bate com a duracao
    original do bloco, sem gap nem overlap entre elas.

    Entradas que ja tem 1 palavra passam intactas (no-op) - alinhamento de
    faster-whisper (Etapas 2/4, ja per-palavra) nao e' afetado."""
    expandidas = []
    for entrada in palavras:
        texto = (entrada.get("palavra") or "").strip()
        tokens = texto.split()
        if len(tokens) <= 1:
            expandidas.append(entrada)
            continue

        inicio_bloco = entrada["inicio_s"]
        fim_bloco = entrada["fim_s"]
        duracao_bloco = fim_bloco - inicio_bloco
        total_chars = sum(len(token) for token in tokens)
        if total_chars <= 0 or duracao_bloco <= 0:
            # Sem base pra interpolar (duracao zero/negativa) - mantem como
            # uma unica entrada em vez de dividir por zero.
            expandidas.append(entrada)
            continue

        cursor_s = inicio_bloco
        ultimo_indice = len(tokens) - 1
        for indice, token in enumerate(tokens):
            inicio_token = cursor_s
            if indice == ultimo_indice:
                fim_token = fim_bloco
            else:
                fim_token = inicio_token + duracao_bloco * (len(token) / total_chars)
            expandidas.append({"palavra": token, "inicio_s": inicio_token, "fim_s": fim_token})
            cursor_s = fim_token
    return expandidas


def agrupar_palavras_em_frases(palavras: list, duracao_max_s: float = LEGENDA_DURACAO_MAX_S, palavras_max: int = LEGENDA_PALAVRAS_MAX) -> list:
    """Agrupa palavras com timestamp ({"palavra","inicio_s","fim_s"} -
    schema de narracao_alinhamento.json) em frases de legenda. Fecha o
    grupo atual quando a palavra termina com pontuacao de fim de frase
    (.!?…, possivelmente seguida de aspas/parenteses fechando), quando o
    grupo atinge `palavras_max` palavras, ou quando a duracao acumulada do
    grupo excede `duracao_max_s` - protege contra bloco gigante de texto
    numa narracao corrida sem pontuacao clara. Lista vazia -> [].

    Expande blocos multi-palavra (`_expandir_palavras_multiplas`) antes de
    agrupar, entao o resultado e' sempre per-palavra de verdade independente
    da granularidade de origem (Whisper ja per-palavra, DarkPlanner SRT
    pode vir em blocos - CLAUDE.md nao documenta essa integracao ainda)."""
    palavras = _expandir_palavras_multiplas(palavras)
    if not palavras:
        return []

    frases = []
    grupo = []

    def _fechar_grupo():
        frases.append(
            {
                "texto": " ".join((p.get("palavra") or "").strip() for p in grupo).strip(),
                "inicio_s": grupo[0]["inicio_s"],
                "fim_s": grupo[-1]["fim_s"],
                # Palavras originais do grupo (com timestamp individual) -
                # insumo do karaoke por palavra (gerar_dialogue_karaoke).
                "palavras": list(grupo),
            }
        )

    for palavra in palavras:
        texto = (palavra.get("palavra") or "").strip()
        if not texto:
            continue
        grupo.append(palavra)

        duracao_grupo = palavra["fim_s"] - grupo[0]["inicio_s"]
        termina_frase = bool(_PADRAO_FIM_FRASE.search(texto))
        excedeu_palavras = len(grupo) >= palavras_max
        excedeu_duracao = duracao_grupo >= duracao_max_s

        if termina_frase or excedeu_palavras or excedeu_duracao:
            _fechar_grupo()
            grupo = []

    if grupo:
        _fechar_grupo()

    return frases


# ---------------------------------------------------------------------------
# Legendas - SRT (softsub, sempre gerado)
# ---------------------------------------------------------------------------


def _formatar_timestamp_srt(segundos: float) -> str:
    total_ms = max(0, round(segundos * 1000))
    horas, resto = divmod(total_ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segs, ms = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segs:02d},{ms:03d}"


def gerar_srt(alinhamento: dict, caminho_saida: Path, offset_s: float = 0.0) -> Path:
    """`offset_s`: desloca todos os timestamps pra frente (sessao "Intro e
    ending anexados ao video final", GRUPO E) - usado quando uma intro foi
    anexada ANTES deste SRT ser embutido como softsub (`adicionar_softsub`),
    para o timestamp de cada legenda bater com a posicao real da narracao
    no video FINAL (com intro). Default 0.0 preserva o comportamento
    historico (softsub sem intro, ou geracao antecipada de
    saida/legendas.srt antes de saber se ha intro - CLAUDE.md secao
    5.86-bis)."""
    palavras = (alinhamento or {}).get("palavras") or []
    frases = agrupar_palavras_em_frases(palavras)

    linhas = []
    for indice, frase in enumerate(frases, start=1):
        linhas.append(str(indice))
        linhas.append(
            f"{_formatar_timestamp_srt(frase['inicio_s'] + offset_s)} --> "
            f"{_formatar_timestamp_srt(frase['fim_s'] + offset_s)}"
        )
        linhas.append(frase["texto"])
        linhas.append("")

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_saida.write_text("\n".join(linhas), encoding="utf-8")
    return caminho_saida


# ---------------------------------------------------------------------------
# Legendas - ASS estilo "MrBeast" (queimada, opcional, karaoke por palavra)
# ---------------------------------------------------------------------------


def _fonte_disponivel(nome: str) -> bool:
    """Verifica se ha uma fonte com `nome` no arquivo instalada no sistema
    (Windows - CLAUDE.md secao 13, produto e' Windows-only). Nunca levanta
    excecao - qualquer problema de acesso a disco vira "fonte nao
    encontrada", ativando o fallback seguro em `escolher_fonte_legenda`."""
    if os.name != "nt":
        return False
    pastas = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
    ]
    for pasta in pastas:
        try:
            if not pasta.exists():
                continue
            for arquivo in pasta.iterdir():
                if nome.lower() in arquivo.name.lower():
                    return True
        except OSError:
            continue
    return False


def escolher_fonte_legenda() -> str:
    return LEGENDA_FONTE_PADRAO if _fonte_disponivel(LEGENDA_FONTE_BASE) else LEGENDA_FONTE_FALLBACK


def _formatar_timestamp_ass(segundos: float) -> str:
    total_cs = max(0, round(segundos * 100))
    horas, resto = divmod(total_cs, 360_000)
    minutos, resto = divmod(resto, 6_000)
    segs, cs = divmod(resto, 100)
    return f"{horas:d}:{minutos:02d}:{segs:02d}.{cs:02d}"


def _escapar_texto_ass(texto: str) -> str:
    """Escapa caracteres que o parser de override tags do ASS interpretaria
    como inicio/fim de tag (`{`/`}`) ou quebra de linha forcada, pra texto de
    palavra nunca ser confundido com uma tag `{\\k...}` de verdade."""
    return texto.replace("\n", "\\N").replace("{", "(").replace("}", ")")


def gerar_dialogue_karaoke(frase: dict) -> str:
    """Gera o campo Text de uma linha Dialogue com karaoke palavra-a-palavra
    (tag `\\k<centesimos>` - CLAUDE.md secao de correcao pos-teste real,
    estilo MrBeast: palavra atual destacada em SecondaryColour, o resto em
    PrimaryColour).

    `frase` e' um item de `agrupar_palavras_em_frases` (tem que ter a chave
    "palavras" com a lista de palavras originais, cada uma com
    "palavra"/"inicio_s"/"fim_s"). Se a lista vier vazia ou ausente - nao
    deveria acontecer dado o contrato de narracao_alinhamento.json, mas
    defensivo por seguranca (CLAUDE.md secao 18.6) - cai para o texto puro
    da frase sem karaoke. Tambem cai pro texto puro (sem tags \\k) se
    LEGENDA_KARAOKE_ATIVO estiver desligado nos Ajustes."""
    palavras = frase.get("palavras") or []
    if not palavras:
        return _escapar_texto_ass(frase["texto"])

    if not LEGENDA_KARAOKE_ATIVO:
        textos = [_escapar_texto_ass((p.get("palavra") or "").strip()) for p in palavras]
        return " ".join(texto for texto in textos if texto)

    partes = []
    for palavra in palavras:
        texto = _escapar_texto_ass((palavra.get("palavra") or "").strip())
        if not texto:
            continue
        duracao_cs = max(0, round((palavra["fim_s"] - palavra["inicio_s"]) * 100))
        partes.append(f"{{\\k{duracao_cs}}}{texto}")
    return " ".join(partes)


def gerar_ass_estilo_mrbeast(alinhamento: dict, caminho_saida: Path, fonte: str | None = None) -> Path:
    """Gera legenda queimada estilo "MrBeast": texto branco, contorno preto
    grosso, karaoke por palavra (palavra atual destacada em amarelo).
    `BorderStyle=1` faz o libass desenhar so' contorno + sombra (sem caixa
    de fundo) - substitui o antigo estilo "pill" (fundo branco/texto preto),
    que ficava ilegivel sobre video escuro de true crime."""
    fonte_usada = fonte or escolher_fonte_legenda()
    palavras = (alinhamento or {}).get("palavras") or []
    frases = agrupar_palavras_em_frases(palavras)

    cabecalho = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: MrBeastStyle,{fonte_usada},{LEGENDA_TAMANHO_PT},{MRBEAST_COR_PRIMARIA},{MRBEAST_COR_DESTAQUE},"
        f"{MRBEAST_COR_CONTORNO},{MRBEAST_COR_SOMBRA},1,0,0,0,100,100,0,0,{MRBEAST_BORDER_STYLE},"
        f"{MRBEAST_OUTLINE_ESPESSURA},{MRBEAST_SHADOW},2,{MRBEAST_MARGEM_LR},{MRBEAST_MARGEM_LR},{LEGENDA_MARGEM_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    linhas_eventos = []
    for frase in frases:
        texto_karaoke = gerar_dialogue_karaoke(frase)
        linhas_eventos.append(
            f"Dialogue: 0,{_formatar_timestamp_ass(frase['inicio_s'])},{_formatar_timestamp_ass(frase['fim_s'])},"
            f"MrBeastStyle,,0,0,0,,{{\\an2}}{texto_karaoke}"
        )

    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_saida.write_text(cabecalho + "\n".join(linhas_eventos) + "\n", encoding="utf-8")
    return caminho_saida


# ---------------------------------------------------------------------------
# Categorizacao de erros de ffmpeg (CLAUDE.md secao 18.5)
# ---------------------------------------------------------------------------

_CATEGORIAS_ERRO_FFMPEG = [
    (
        "disco_cheio",
        lambda s: "no space left on device" in s or "disk full" in s or "enospc" in s,
    ),
    (
        "fonte_corrompida",
        lambda s: "invalid data found when processing input" in s
        or "moov atom not found" in s
        or "could not open file" in s,
    ),
]


def classificar_erro_ffmpeg(stderr: str) -> tuple:
    texto = (stderr or "").lower()
    for categoria, condicao in _CATEGORIAS_ERRO_FFMPEG:
        if condicao(texto):
            if categoria == "disco_cheio":
                return categoria, "Disco cheio - libere espaco e tente novamente."
            if categoria == "fonte_corrompida":
                return categoria, "Um dos clipes de video ou arquivos de audio esta corrompido ou ilegivel."
    trecho = (stderr or "").strip().splitlines()
    trecho = " | ".join(trecho[-3:]) if trecho else "sem detalhe"
    return "ffmpeg_falhou", f"ffmpeg falhou na montagem do video. Detalhe: {trecho[:200]}"


def _rodar_ffmpeg(comando: list, timeout_s: int, caminho_saida: Path):
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
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout_ffmpeg", f"Etapa de montagem excedeu o tempo limite de {timeout_s}s."
    except OSError as exc:
        return False, "erro_desconhecido", f"Falha ao executar ffmpeg: {exc}"

    if resultado.returncode != 0 or not caminho_saida.exists():
        stderr_tail = "\n".join((resultado.stderr or "").strip().splitlines()[-15:])
        tipo_erro, mensagem_usuario = classificar_erro_ffmpeg(stderr_tail)
        return False, tipo_erro, mensagem_usuario

    return True, None, None


# ---------------------------------------------------------------------------
# Encoder GPU (duplicado de 5_gerar_clipes.py - CLAUDE.md secao 9)
# ---------------------------------------------------------------------------


def _params_encoder(encoder: str) -> list:
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


def _detectar_encoder_gpu() -> str:
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


def _obter_duracao_video_via_ffprobe(caminho: Path):
    """Duracao em segundos do video FINAL (nao confundir com
    `tempo_total_s` do metadata, que e' tempo de PROCESSAMENTO da
    montagem - achado real de sessao de refinamento: a tela de conclusao
    exibia `tempo_total_s` rotulado "Duracao" e mostrava ~5min quando o
    video tinha ~25min de fato). None se ffprobe estiver ausente ou o
    arquivo estiver corrompido - nunca levanta excecao (CLAUDE.md secao
    18.5). Mesma abordagem de `obter_duracao_via_ffprobe` em
    1_baixar_videos.py, duplicada aqui por design (CLAUDE.md secao 9 -
    scripts sao autocontidos, sem utils.py compartilhado)."""
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
        return round(float(resultado.stdout.strip()), 3)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def _obter_largura_video_via_ffprobe(caminho: Path):
    """Largura real (em pixels) do video em `caminho`, usada para calcular a
    escala/margem da marca d'agua do canal proporcionalmente (nunca assume
    1920 fixo - "videos_pre_gerados", CLAUDE.md secao 3, pode ter outra
    resolucao). None se ffprobe estiver ausente ou o arquivo corrompido -
    nunca levanta excecao (CLAUDE.md secao 18.5); o chamador cai em
    LARGURA_VIDEO_PADRAO_PX nesse caso."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(caminho),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if resultado.returncode != 0:
            return None
        return int(resultado.stdout.strip().splitlines()[0])
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        return None


def _obter_specs_video_via_ffprobe(caminho: Path):
    """Largura/altura/fps/pix_fmt/codec do primeiro stream de video de
    `caminho` (sessao "Intro e ending anexados ao video final", GRUPO B) -
    usado para normalizar intro/ending exatamente contra o video JA
    montado (nunca assume 1920x1080/30fps fixo - "videos_pre_gerados",
    CLAUDE.md secao 3, pode ter qualquer resolucao/fps). None se ffprobe
    estiver ausente ou o arquivo corrompido - nunca levanta excecao
    (CLAUDE.md secao 18.5); o chamador trata isso como "nao da pra saber o
    padrao alvo", nunca assume um default."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,pix_fmt,codec_name",
                "-of", "csv=p=0",
                str(caminho),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if resultado.returncode != 0:
            return None
        partes = resultado.stdout.strip().splitlines()[0].split(",")
        if len(partes) < 5:
            return None
        largura, altura, fps_bruto, pix_fmt, codec = partes[0], partes[1], partes[2], partes[3], partes[4]
        if "/" in fps_bruto:
            numerador, denominador = fps_bruto.split("/")
            fps = float(numerador) / float(denominador) if float(denominador) else 0.0
        else:
            fps = float(fps_bruto)
        return {
            "largura": int(largura),
            "altura": int(altura),
            "fps": round(fps, 3),
            "pix_fmt": pix_fmt,
            "codec": codec,
        }
    except (subprocess.SubprocessError, OSError, ValueError, IndexError, ZeroDivisionError):
        return None


def _tem_audio_via_ffprobe(caminho: Path) -> bool:
    """True se `caminho` tem pelo menos um stream de audio - usado pra
    decidir se a normalizacao de intro/ending (GRUPO B) preserva o audio
    original ou gera silencio (`anullsrc`) no lugar (GRUPO D: "se a intro
    nao tiver audio, define-se silencio nesse trecho, nunca narracao
    antecipada"). Qualquer falha do ffprobe vira False (sem audio) - mais
    seguro gerar silencio de sobra do que assumir audio que nao existe e
    quebrar o comando de normalizacao."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(caminho),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return resultado.returncode == 0 and bool(resultado.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return False


# ---------------------------------------------------------------------------
# Concat dos clipes (ffmpeg concat demuxer, sem reencoding)
# ---------------------------------------------------------------------------


def _escrever_lista_concat(indice_clipes: list, pasta_clipes: Path, caminho_lista: Path) -> Path:
    caminho_lista.parent.mkdir(parents=True, exist_ok=True)
    linhas = [f"file '{(pasta_clipes / clipe['arquivo']).resolve().as_posix()}'" for clipe in indice_clipes]
    caminho_lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho_lista


def construir_comando_concat(caminho_lista: Path, caminho_saida: Path) -> list:
    """Approach adapted from yt_automation project (Gustavo Xavier, GitHub)
    - app/ffmpeg_cmd.py: lista de arquivos em texto + demuxer `concat` com
    `-c copy` (sem reencoding, muito mais rapido)."""
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(caminho_lista),
        "-c", "copy",
        str(caminho_saida),
    ]


# ---------------------------------------------------------------------------
# Slots por posicao (Feature B - reorganizacao manual com drag livre) -
# `_migrar_slots_clipes` e' a UNICA funcao que decide os valores de
# duracao_slot_s/inicio_slot_s/fim_slot_s usados pelo concat - nunca confia
# em inicio_slot_s/fim_slot_s eventualmente persistidos no indice.json,
# sempre recalcula como soma cumulativa de duracao_slot_s na ordem ATUAL da
# lista (a ordem da lista E' a ordem da timeline).
# ---------------------------------------------------------------------------


def _migrar_slots_clipes(clipes: list) -> list:
    """Retorna uma NOVA lista de clipes (nao muta a entrada) com
    duracao_slot_s/inicio_slot_s/fim_slot_s sempre presentes. Se um clipe ja
    tem duracao_slot_s, o valor e' preservado (server.py:/reordenar_clipes
    e' quem grava esse valor apos um drag). Se nao tem (todo indice.json de
    projeto gerado antes desta sessao), o fallback e' a propria duracao_s -
    reproduz exatamente a semantica de antes desta feature (posicao == soma
    cumulativa de duracao_s), entao um projeto que nunca passou pela tela de
    reorganizacao manual sempre cai neste fallback em TODOS os clipes."""
    resultado = []
    acumulado = 0.0
    for clipe in clipes:
        novo = dict(clipe)
        duracao_slot = novo.get("duracao_slot_s")
        if duracao_slot is None:
            duracao_slot = novo.get("duracao_s") or 0.0
        duracao_slot = round(float(duracao_slot), 3)
        novo["duracao_slot_s"] = duracao_slot
        novo["inicio_slot_s"] = round(acumulado, 3)
        acumulado += duracao_slot
        novo["fim_slot_s"] = round(acumulado, 3)
        resultado.append(novo)
    return resultado


def _precisa_de_trim(clipes_migrados: list, tolerancia_s: float = 0.01) -> bool:
    """True se algum clipe precisa ser cortado (`trim`) porque a duracao do
    SLOT que ele ocupa hoje e' diferente da duracao real do arquivo - so'
    acontece depois de uma reorganizacao manual que colocou um clipe numa
    posicao com slot de duracao diferente da dele. Projeto que nunca passou
    pela tela de reorganizacao manual: sempre False (duracao_slot_s ==
    duracao_s em todo clipe, fallback de `_migrar_slots_clipes`)."""
    return any(
        abs((clipe.get("duracao_slot_s") or 0.0) - (clipe.get("duracao_s") or 0.0)) > tolerancia_s
        for clipe in clipes_migrados
    )


def construir_filtro_complexo_trim(clipes_migrados: list, grayscale: bool = False) -> str:
    """Monta a STRING do grafo de filtros (trim de cada posicao pro seu
    duracao_slot_s + concat [+ hue=s=0 se `grayscale`]), para
    `-filter_complex`. `trim=duration=X` nunca ESTENDE um clipe alem da
    duracao real do arquivo (so' corta) - se duracao_slot_s for maior que a
    duracao real do input (fonte curta usada inteira - CLAUDE.md secao 5.7),
    o trim e' um no-op e o clipe sai com a duracao real dele mesmo, igual ao
    comportamento ORIGINAL (sem trim nenhum) nesse caso.

    `grayscale`: adiciona `hue=s=0` (satura zero, preto-e-branco) na cadeia
    de filtro de CADA clipe antes do concat - unico jeito de aplicar um
    filtro de video a todos os clipes de uma vez neste pipeline, ja' que
    tanto `concat_clipes` (caminho -c copy) quanto `construir_comando_mux`
    (`-c:v copy`) nunca reencodam o video (ver `concat_clipes` abaixo).

    NOTA (achado empirico desta sessao): a ideia original era usar
    `-filter_complex_script <arquivo>` em vez de `-filter_complex
    "<string>"` pra nao estourar o limite de linha de comando do Windows
    com muitos clipes. Descartado: o build de ffmpeg que este produto
    instala/recomenda (Gyan.FFmpeg "essentials", CLAUDE.md secao 18.3) NAO
    tem essa opcao (`Unrecognized option 'filter_complex_script'`, testado
    de verdade). Alem disso, mesmo COM `-filter_complex_script`, os `-i`
    (um por clipe, obrigatorio - filter_complex referencia input por
    indice) sozinhos ja estouram o limite (`[WinError 206]`, testado com um
    projeto real de 262 clipes). A solucao real e' `TAMANHO_LOTE_FILTRO_TRIM`
    abaixo: processar em lotes pequenos, onde a string do filtro de um lote
    e' curta o bastante pra `-filter_complex` direto nunca ser risco."""
    rotulos = [f"v{i}" for i in range(len(clipes_migrados))]
    filtro_extra = ",hue=s=0" if grayscale else ""
    partes = [
        f"[{i}:v]trim=duration={clipe['duracao_slot_s']:.3f},setpts=PTS-STARTPTS{filtro_extra}[{rotulo}]"
        for i, (clipe, rotulo) in enumerate(zip(clipes_migrados, rotulos))
    ]
    entradas_concat = "".join(f"[{rotulo}]" for rotulo in rotulos)
    partes.append(f"{entradas_concat}concat=n={len(rotulos)}:v=1:a=0[outv]")
    return ";".join(partes)


def construir_comando_concat_filtro(
    clipes_migrados: list,
    pasta_clipes: Path,
    caminho_saida: Path,
    encoder: str = ENCODER_PADRAO,
    grayscale: bool = False,
) -> list:
    """Um `-i` por clipe (inevitavel - filter_complex referencia inputs por
    indice) + `-filter_complex` (grafo de trim+concat[+grayscale], ver
    `construir_filtro_complexo_trim`) + reencoding (trim/concat via filtro
    nao aceita `-c copy`)."""
    comando = ["ffmpeg", "-hide_banner", "-y"]
    for clipe in clipes_migrados:
        comando += ["-i", str((pasta_clipes / clipe["arquivo"]).resolve())]
    comando += [
        "-filter_complex", construir_filtro_complexo_trim(clipes_migrados, grayscale),
        "-map", "[outv]",
        *_params_encoder(encoder),
        str(caminho_saida),
    ]
    return comando


# Cada clipe do lote precisa do seu proprio `-i <caminho absoluto>` na linha
# de comando (filter_complex referencia inputs por indice, nao tem como
# apontar pra um arquivo de lista) - com projeto grande (200+ clipes) e path
# absoluto longo (pasta de projeto aninhada), so' os `-i` já estouram o
# limite de linha de comando do Windows (CreateProcess, ~32767 caracteres)
# num unico comando com TODOS os clipes. Validado empiricamente com um
# projeto real de 262 clipes: falhou com `[WinError 206] O nome do arquivo
# ou a extensao e' muito grande`. Solucao: processa em LOTES pequenos (cada
# lote e' um comando ffmpeg com poucos `-i`, resultado reencodado em
# concat_filter_lote_NNN.mp4) e depois junta os lotes com o concat demuxer
# `-c copy` de sempre (lotes ja' tem o MESMO codec/resolucao/fps entre si -
# juncao sem reencoding e' segura). Batch de 40 tambem mantem a STRING do
# filtro pequena o bastante pra nunca precisar de `-filter_complex_script`
# (indisponivel no build de ffmpeg deste produto - ver
# `construir_filtro_complexo_trim`).
TAMANHO_LOTE_FILTRO_TRIM = 40


def _dividir_em_lotes(lista: list, tamanho: int) -> list:
    return [lista[i : i + tamanho] for i in range(0, len(lista), tamanho)]


def _escrever_lista_concat_arquivos(caminhos: list, caminho_lista: Path) -> Path:
    """Mesmo formato de `_escrever_lista_concat`, mas recebe uma lista de
    `Path` absolutos prontos (saida dos lotes reencodados) em vez de dicts
    de clipe + pasta base."""
    caminho_lista.parent.mkdir(parents=True, exist_ok=True)
    linhas = [f"file '{Path(caminho).resolve().as_posix()}'" for caminho in caminhos]
    caminho_lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho_lista


def _renderizar_lote_com_trim(lote: list, pasta_clipes: Path, pasta_temp: Path, indice_lote: int, grayscale: bool = False):
    """Roda um lote pequeno de clipes pelo caminho filter_complex (trim +
    concat [+ grayscale]), com fallback de encoder GPU->CPU (mesmo espirito
    de `queimar_legendas`). Retorna (caminho_saida, None, None) em sucesso ou
    (None, tipo_erro, mensagem) em falha."""
    pasta_temp.mkdir(parents=True, exist_ok=True)
    caminho_saida_lote = pasta_temp / f"concat_filter_lote_{indice_lote:03d}.mp4"

    encoder = _detectar_encoder_gpu()
    comando = construir_comando_concat_filtro(lote, pasta_clipes, caminho_saida_lote, encoder, grayscale)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_CONCAT_FILTRO_S, caminho_saida_lote)
    if not sucesso and encoder == "h264_nvenc":
        comando_fallback = construir_comando_concat_filtro(lote, pasta_clipes, caminho_saida_lote, "libx264", grayscale)
        sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_fallback, TIMEOUT_CONCAT_FILTRO_S, caminho_saida_lote)
    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida_lote, None, None


def concat_clipes(pasta_projeto: Path, indice_clipes: list, grayscale: bool = False):
    """`grayscale`: forca o caminho filter_complex batelado (ver
    `_renderizar_lote_com_trim`/`TAMANHO_LOTE_FILTRO_TRIM`) mesmo quando
    nenhum clipe precisa de trim - e' o UNICO ponto do pipeline onde um
    filtro de video pode ser aplicado a TODOS os clipes de uma vez (concat
    -c copy e mux -c:v copy nunca reencodam - ver `construir_comando_mux`).
    Troca deliberada (secao "Grayscale" da sessao de correcoes UX): projeto
    com grayscale=True mas SEM reorganizacao manual perde o ganho de
    velocidade do caminho -c copy puro (reencoda tudo em vez de so' copiar
    o stream), mas e' o unico jeito de aplicar `hue=s=0` sem uma etapa de
    reencode dedicada so' pra isso. Projeto com grayscale=False (default -
    todo projeto ate esta sessao) segue exatamente como antes."""
    pasta_temp = pasta_projeto / "temp"
    pasta_clipes = pasta_projeto / "clipes"
    caminho_saida = pasta_temp / "video_concat.mp4"

    clipes_migrados = _migrar_slots_clipes(indice_clipes)

    if not _precisa_de_trim(clipes_migrados) and not grayscale:
        # Caminho ORIGINAL, inalterado (CLAUDE.md - preservar comportamento
        # default): nenhum clipe foi reorganizado para uma posicao de
        # duracao diferente da dele E grayscale nao foi pedido, entao
        # concat demuxer + `-c copy` (sem reencoding) continua identico a
        # antes desta sessao.
        caminho_lista = pasta_temp / "concat_list.txt"
        _escrever_lista_concat(indice_clipes, pasta_clipes, caminho_lista)
        comando = construir_comando_concat(caminho_lista, caminho_saida)
        sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_CONCAT_S, caminho_saida)
        if not sucesso:
            return None, tipo_erro, mensagem
        return caminho_saida, None, None

    # Caminho com trim por slot (Feature B): pelo menos um clipe ocupa hoje
    # uma posicao com duracao diferente da dele - concat via filter_complex
    # (trim por posicao + concat) em lotes pequenos, nao demuxer -c copy
    # direto (ver TAMANHO_LOTE_FILTRO_TRIM acima).
    lotes = _dividir_em_lotes(clipes_migrados, TAMANHO_LOTE_FILTRO_TRIM)
    caminhos_lotes = []
    for indice_lote, lote in enumerate(lotes):
        caminho_lote, tipo_erro, mensagem = _renderizar_lote_com_trim(
            lote, pasta_clipes, pasta_temp, indice_lote, grayscale
        )
        if caminho_lote is None:
            return None, tipo_erro, mensagem
        caminhos_lotes.append(caminho_lote)

    if len(caminhos_lotes) == 1:
        caminho_saida.parent.mkdir(parents=True, exist_ok=True)
        caminhos_lotes[0].replace(caminho_saida)
        return caminho_saida, None, None

    caminho_lista_lotes = pasta_temp / "concat_lotes_list.txt"
    _escrever_lista_concat_arquivos(caminhos_lotes, caminho_lista_lotes)
    comando_final = construir_comando_concat(caminho_lista_lotes, caminho_saida)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_final, TIMEOUT_CONCAT_S, caminho_saida)
    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida, None, None


# ---------------------------------------------------------------------------
# Playlist de musica de fundo - concat + loop sequencial ate cobrir a
# duracao do video (sessao de correcao pos-teste real: musica mais curta que
# o video parava no meio, resto do video ficava so' com a narracao)
# ---------------------------------------------------------------------------


def _escrever_lista_concat_musicas(musicas: list, caminho_lista: Path) -> Path:
    caminho_lista.parent.mkdir(parents=True, exist_ok=True)
    linhas = [f"file '{musica.resolve().as_posix()}'" for musica in musicas]
    caminho_lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho_lista


def construir_comando_concat_musicas(caminho_lista: Path, caminho_saida: Path) -> list:
    """Mesmo padrao de `construir_comando_concat` (lista de arquivos +
    demuxer `concat`), aplicado as faixas de musica em vez dos clipes de
    video - concatena a playlist inteira numa unica faixa, na ordem dada."""
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(caminho_lista),
        "-c", "copy",
        str(caminho_saida),
    ]


def construir_comando_loop_musica(faixa_concat: Path, duracao_alvo_s: float, caminho_saida: Path) -> list:
    """`-stream_loop -1` repete a faixa concatenada indefinidamente; `-t`
    corta exatamente na duracao alvo - e' o loop sequencial (m1 -> m2 -> m3
    -> m1 -> ...) que substitui a musica parar no meio de um video mais
    longo que a playlist."""
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-stream_loop", "-1",
        "-i", str(faixa_concat),
        "-t", f"{duracao_alvo_s:.3f}",
        "-c", "copy",
        str(caminho_saida),
    ]


def preparar_faixa_musica_playlist(musicas: list, duracao_alvo_s: float, pasta_projeto: Path):
    """Concatena a playlist de musicas (ordem dada em `musicas`) e faz loop
    sequencial ate cobrir `duracao_alvo_s`. Retorna (caminho, None, None) em
    sucesso, ou (None, tipo_erro, mensagem_usuario) caso contrario - nunca
    levanta excecao, mesmo padrao das outras funcoes de etapa deste arquivo
    (usa `_rodar_ffmpeg`, CLAUDE.md secao 18.4/18.5)."""
    pasta_temp = pasta_projeto / "temp"
    caminho_lista = pasta_temp / "musica_concat_list.txt"
    faixa_concat = pasta_temp / "musica_concat.mp3"
    faixa_final = pasta_temp / "musica_playlist_final.mp3"

    _escrever_lista_concat_musicas(musicas, caminho_lista)
    comando_concat = construir_comando_concat_musicas(caminho_lista, faixa_concat)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_concat, TIMEOUT_MUSICA_CONCAT_S, faixa_concat)
    if not sucesso:
        return None, tipo_erro, mensagem

    comando_loop = construir_comando_loop_musica(faixa_concat, duracao_alvo_s, faixa_final)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_loop, TIMEOUT_MUSICA_LOOP_S, faixa_final)
    if not sucesso:
        return None, tipo_erro, mensagem

    return faixa_final, None, None


# ---------------------------------------------------------------------------
# Mux com narracao + musica de fundo opcional (ducking)
# ---------------------------------------------------------------------------


def construir_filtro_ducking() -> str:
    """`sidechaincompress` comprime a musica (segundo input do filtro)
    usando a narracao (primeiro input) como referencia de nivel - a musica
    "abaixa" automaticamente enquanto a narracao esta tocando."""
    return (
        f"[2:a]volume={MUSICA_VOLUME_BASE}[music_base];"
        f"[music_base][1:a]sidechaincompress=threshold={DUCKING_THRESHOLD}:ratio={DUCKING_RATIO}:"
        f"attack={DUCKING_ATTACK_MS}:release={DUCKING_RELEASE_MS}[music_ducked];"
        "[1:a][music_ducked]amix=inputs=2:duration=first:dropout_transition=2[audio_out]"
    )


def construir_comando_mux(video_concat: Path, narracao_path: Path, caminho_saida: Path, musica_path=None) -> list:
    comando = ["ffmpeg", "-hide_banner", "-y", "-i", str(video_concat), "-i", str(narracao_path)]
    if musica_path is not None:
        comando += [
            "-i", str(musica_path),
            "-filter_complex", construir_filtro_ducking(),
            "-map", "0:v", "-map", "[audio_out]",
        ]
    else:
        comando += ["-map", "0:v", "-map", "1:a"]
    comando += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(caminho_saida)]
    return comando


def mux_audio(video_concat: Path, narracao_path: Path, pasta_projeto: Path, musica_path=None):
    caminho_saida = pasta_projeto / "temp" / "video_com_audio.mp4"
    comando = construir_comando_mux(video_concat, narracao_path, caminho_saida, musica_path)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_MUX_S, caminho_saida)
    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida, None, None


# ---------------------------------------------------------------------------
# Queimar legendas (ASS, opcional)
# ---------------------------------------------------------------------------


def _escapar_caminho_filtro_ffmpeg(caminho: Path) -> str:
    """Escapa um Path do Windows para uso dentro de um filtro `ass=` do
    ffmpeg: troca `\\` por `/` (o parser de filtro usa `:` como separador
    de opcao - barra invertida do Windows quebra o parsing) e escapa `:`
    (usado pela letra de unidade, ex. `C:`) com `\\:`."""
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def construir_comando_queimar_legendas(video_path: Path, ass_path: Path, caminho_saida: Path, encoder: str = ENCODER_PADRAO) -> list:
    ass_escapado = _escapar_caminho_filtro_ffmpeg(ass_path)
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video_path),
        "-vf", f"ass='{ass_escapado}'",
        "-c:a", "copy",
        *_params_encoder(encoder),
        str(caminho_saida),
    ]


def queimar_legendas(video_path: Path, ass_path: Path, pasta_projeto: Path, encoder: str = ENCODER_PADRAO):
    """Reencoda o video com a legenda ASS queimada. Fallback automatico
    para `libx264` se `h264_nvenc` falhar em runtime (mesmo espirito de
    `_renderizar_clipe` em 5_gerar_clipes.py)."""
    caminho_saida = pasta_projeto / "temp" / "video_com_legendas.mp4"
    comando = construir_comando_queimar_legendas(video_path, ass_path, caminho_saida, encoder)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_QUEIMAR_LEGENDAS_S, caminho_saida)

    if not sucesso and encoder == "h264_nvenc":
        comando_fallback = construir_comando_queimar_legendas(video_path, ass_path, caminho_saida, "libx264")
        sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_fallback, TIMEOUT_QUEIMAR_LEGENDAS_S, caminho_saida)

    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida, None, None


def construir_comando_queimar_srt(
    video_path: Path, srt_path: Path, caminho_saida: Path, encoder: str = ENCODER_PADRAO
) -> list:
    """Queima um SRT puro (sem estilo karaoke) direto no video via filtro
    `subtitles=` - distinto de `construir_comando_queimar_legendas` (filtro
    `ass=`, estilo "MrBeast" com destaque por palavra), que precisa de
    timestamps por palavra que o tipo de projeto videos_pre_gerados nao tem
    (a legenda aqui e' importada pronta pelo usuario, nao gerada de
    alinhamento)."""
    srt_escapado = _escapar_caminho_filtro_ffmpeg(srt_path)
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video_path),
        "-vf", f"subtitles='{srt_escapado}'",
        "-c:a", "copy",
        *_params_encoder(encoder),
        str(caminho_saida),
    ]


def queimar_srt_importado(video_path: Path, srt_path: Path, pasta_projeto: Path, encoder: str = ENCODER_PADRAO):
    """Queima o SRT importado pelo usuario (tipo de projeto
    videos_pre_gerados, formulario de Novo projeto) no video concatenado.
    Fallback automatico para `libx264` se `h264_nvenc` falhar em runtime
    (mesmo espirito de `queimar_legendas`)."""
    caminho_saida = pasta_projeto / "temp" / "video_com_srt_importado.mp4"
    comando = construir_comando_queimar_srt(video_path, srt_path, caminho_saida, encoder)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_QUEIMAR_LEGENDAS_S, caminho_saida)

    if not sucesso and encoder == "h264_nvenc":
        comando_fallback = construir_comando_queimar_srt(video_path, srt_path, caminho_saida, "libx264")
        sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_fallback, TIMEOUT_QUEIMAR_LEGENDAS_S, caminho_saida)

    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida, None, None


# ---------------------------------------------------------------------------
# Marca d'agua do canal (overlay, opcional) - fundida na MESMA passada que
# queima a legenda quando as duas estao ativas, para nunca reencodar o video
# inteiro (1,4GB+) duas vezes. Quando so a marca esta ativa (sem legenda
# queimada), esta e' a UNICA passada de reencode do pipeline - antes desta
# feature nao existia nenhuma nesse caso (concat/mux/softsub sao todos
# `-c copy`/`-c:v copy`).
# ---------------------------------------------------------------------------


def construir_filtro_marca_dagua(legenda_path: Path | None, modo_legenda: str, largura_video: int, posicao: str) -> str:
    """Monta a string do filter_complex combinando (opcionalmente) a queima
    de legenda - `ass=` (estilo MrBeast, pipeline_completa) ou `subtitles=`
    (SRT importado puro, videos_pre_gerados) conforme `modo_legenda` - com o
    overlay da marca d'agua do canal (input [1:v], PNG).

    `format=rgba` garante canal alfa mesmo se o PNG nao tiver um (opaco) -
    sem isso `colorchannelmixer=aa=...` nao teria canal alfa pra multiplicar
    e a opacidade de 40% nao teria efeito nenhum."""
    x_expr, y_expr = marca_dagua_canal.gerar_overlay_xy(posicao, largura_video)
    largura_marca = marca_dagua_canal.calcular_largura_marca_px(largura_video)

    partes = []
    rotulo_video = "0:v"
    if legenda_path is not None:
        filtro_legenda = "ass" if modo_legenda == "ass" else "subtitles"
        escapado = _escapar_caminho_filtro_ffmpeg(legenda_path)
        partes.append(f"[0:v]{filtro_legenda}='{escapado}'[vleg]")
        rotulo_video = "vleg"

    partes.append(
        f"[1:v]format=rgba,scale={largura_marca}:-1,colorchannelmixer=aa={marca_dagua_canal.OPACIDADE}[wm]"
    )
    partes.append(f"[{rotulo_video}][wm]overlay={x_expr}:{y_expr}:format=auto[outv]")
    return ";".join(partes)


def construir_comando_marca_dagua(
    video_path: Path,
    marca_path: Path,
    caminho_saida: Path,
    legenda_path: Path | None = None,
    modo_legenda: str = "ass",
    largura_video: int = LARGURA_VIDEO_PADRAO_PX,
    posicao: str = marca_dagua_canal.POSICAO_PADRAO,
    encoder: str = ENCODER_PADRAO,
) -> list:
    filtro = construir_filtro_marca_dagua(legenda_path, modo_legenda, largura_video, posicao)
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video_path),
        "-i", str(marca_path),
        "-filter_complex", filtro,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:a", "copy",
        *_params_encoder(encoder),
        str(caminho_saida),
    ]


def aplicar_marca_dagua(
    video_path: Path,
    marca_path: Path,
    pasta_projeto: Path,
    legenda_path: Path | None = None,
    modo_legenda: str = "ass",
    largura_video: int = LARGURA_VIDEO_PADRAO_PX,
    posicao: str = marca_dagua_canal.POSICAO_PADRAO,
    encoder: str = ENCODER_PADRAO,
):
    """Reencoda o video com a marca d'agua do canal aplicada (e a legenda
    junto, se `legenda_path` for informado - mesma passada). Fallback
    automatico para `libx264` se `h264_nvenc` falhar em runtime (mesmo
    espirito de `queimar_legendas`). Retorna (caminho, None, None) em
    sucesso, ou (None, tipo_erro, mensagem_usuario) - o motivo REAL do
    ffmpeg (CLAUDE.md secao 18.5), nunca uma mensagem generica."""
    caminho_saida = pasta_projeto / "temp" / "video_com_marca_dagua.mp4"
    comando = construir_comando_marca_dagua(
        video_path, marca_path, caminho_saida, legenda_path, modo_legenda, largura_video, posicao, encoder
    )
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_QUEIMAR_LEGENDAS_S, caminho_saida)

    if not sucesso and encoder == "h264_nvenc":
        comando_fallback = construir_comando_marca_dagua(
            video_path, marca_path, caminho_saida, legenda_path, modo_legenda, largura_video, posicao, "libx264"
        )
        sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_fallback, TIMEOUT_QUEIMAR_LEGENDAS_S, caminho_saida)

    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida, None, None


# ---------------------------------------------------------------------------
# Intro/ending anexados ao video final (sessao "Intro e ending anexados ao
# video final") - GRUPO B (normalizacao) + GRUPO C (concatenacao). Rodam
# como o ULTIMO passo de montagem de video, depois de narracao/musica/
# legenda queimada/marca d'agua ja resolvidas (secao 1.2 da analise desta
# sessao): intro/ending nunca participam da selecao aleatoria de clipes nem
# da sincronizacao com a narracao (GRUPO C da especificacao), e a legenda
# queimada nunca aparece neles porque ja foi queimada nos pixels do video
# ANTES de intro/ending existirem no arquivo.
# ---------------------------------------------------------------------------


def _video_ja_no_padrao(specs: dict | None, largura: int, altura: int, fps: float) -> bool:
    """True se `specs` (de `_obter_specs_video_via_ffprobe`) ja bate
    exatamente com o padrao alvo (resolucao/fps/pix_fmt/codec h264) - nesse
    caso a normalizacao pula o filtro de escala/pad/fps caro (GRUPO B: "se
    ja estiverem no padrao, pular a normalizacao"). `specs` None (ffprobe
    falhou) sempre reprova - mais seguro reencodar de mais do que arriscar
    um `-c:v copy` que quebra o concat final."""
    if specs is None:
        return False
    return (
        specs["largura"] == largura
        and specs["altura"] == altura
        and abs(specs["fps"] - fps) <= TOLERANCIA_FPS_INTRO_ENDING
        and specs["pix_fmt"] == "yuv420p"
        and specs["codec"] == "h264"
    )


def construir_comando_normalizar_intro_ending(
    caminho_entrada: Path,
    caminho_saida: Path,
    largura: int,
    altura: int,
    fps: float,
    tem_audio: bool,
    duracao_s: float,
    pular_filtro_escala: bool,
    marca_path: Path | None,
    posicao_marca: str,
    encoder: str,
) -> list:
    """Monta o comando ffmpeg que normaliza um arquivo de intro/ending para
    o MESMO codec/resolucao/fps/pix_fmt do video ja montado (GRUPO B) e,
    se `marca_path` for informado, aplica a MESMA marca d'agua do canal por
    cima (para consistencia de canal - GRUPO E). Sem audio original
    (`tem_audio=False`), gera silencio (`anullsrc`) com a duracao do
    arquivo - GRUPO D ("se a intro nao tiver audio, define-se silencio
    nesse trecho"). O audio e' SEMPRE reencodado para AAC (barato, mesmo
    quando `pular_filtro_escala=True`) porque o concat final (GRUPO C) usa
    `-c copy` e precisa do MESMO codec de audio nos 3 segmentos - so o
    filtro de VIDEO e' de fato pulado quando ja bate com o padrao e nenhuma
    marca d'agua precisa ser desenhada por cima."""
    comando = ["ffmpeg", "-hide_banner", "-y", "-i", str(caminho_entrada)]
    proximo_indice_input = 1

    indice_audio_silencioso = None
    if not tem_audio:
        comando += [
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:d={max(duracao_s, 0.01):.3f}",
        ]
        indice_audio_silencioso = proximo_indice_input
        proximo_indice_input += 1

    indice_marca = None
    if marca_path is not None:
        comando += ["-i", str(marca_path)]
        indice_marca = proximo_indice_input
        proximo_indice_input += 1

    filtro_escala = (
        f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
        f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps:.3f},format=yuv420p"
    )

    partes_filtro = []
    rotulo_video = "0:v"
    if not pular_filtro_escala:
        partes_filtro.append(f"[0:v]{filtro_escala}[vnorm]")
        rotulo_video = "vnorm"

    if indice_marca is not None:
        x_expr, y_expr = marca_dagua_canal.gerar_overlay_xy(posicao_marca, largura)
        largura_marca = marca_dagua_canal.calcular_largura_marca_px(largura)
        partes_filtro.append(
            f"[{indice_marca}:v]format=rgba,scale={largura_marca}:-1,"
            f"colorchannelmixer=aa={marca_dagua_canal.OPACIDADE}[wm]"
        )
        partes_filtro.append(f"[{rotulo_video}][wm]overlay={x_expr}:{y_expr}:format=auto[voutfinal]")
        rotulo_video = "voutfinal"

    if partes_filtro:
        comando += ["-filter_complex", ";".join(partes_filtro), "-map", f"[{rotulo_video}]"]
    else:
        comando += ["-map", "0:v"]

    comando += ["-map", f"{indice_audio_silencioso}:a" if not tem_audio else "0:a"]
    comando += ["-c:a", "aac", "-b:a", "192k"]

    if pular_filtro_escala and not partes_filtro:
        comando += ["-c:v", "copy"]
    else:
        comando += _params_encoder(encoder)

    comando += ["-shortest", str(caminho_saida)]
    return comando


def normalizar_intro_ending(
    caminho_entrada: Path,
    pasta_projeto: Path,
    papel: str,
    largura: int,
    altura: int,
    fps: float,
    marca_path: Path | None,
    posicao_marca: str,
    encoder: str,
):
    """Normaliza um arquivo de intro/ending (`papel` = "intro" ou "ending")
    para o padrao do video ja montado. Retorna
    (caminho_normalizado_ou_None, duracao_s, aviso_ou_None) - falha em
    QUALQUER ponto (ffprobe, ffmpeg) nunca levanta excecao e nunca derruba
    a montagem inteira (GRUPO B: "falha na normalizacao nao derruba o
    video final") - o chamador (`anexar_intro_ending`) simplesmente ignora
    este arquivo e segue sem ele, registrando o motivo REAL em `aviso`
    (CLAUDE.md secao 18.4/18.5)."""
    duracao_s = _obter_duracao_video_via_ffprobe(caminho_entrada)
    if not duracao_s or duracao_s <= 0:
        return None, 0.0, f"Nao foi possivel ler a duracao do arquivo de {papel} - ignorado na montagem."

    specs = _obter_specs_video_via_ffprobe(caminho_entrada)
    tem_audio = _tem_audio_via_ffprobe(caminho_entrada)
    pular_filtro_escala = _video_ja_no_padrao(specs, largura, altura, fps)

    caminho_saida = pasta_projeto / "temp" / f"{papel}_normalizado.mp4"
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    comando = construir_comando_normalizar_intro_ending(
        caminho_entrada, caminho_saida, largura, altura, fps, tem_audio, duracao_s,
        pular_filtro_escala, marca_path, posicao_marca, encoder,
    )
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_NORMALIZAR_INTRO_ENDING_S, caminho_saida)

    if not sucesso and encoder == "h264_nvenc":
        comando_fallback = construir_comando_normalizar_intro_ending(
            caminho_entrada, caminho_saida, largura, altura, fps, tem_audio, duracao_s,
            pular_filtro_escala, marca_path, posicao_marca, "libx264",
        )
        sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando_fallback, TIMEOUT_NORMALIZAR_INTRO_ENDING_S, caminho_saida)

    if not sucesso:
        return None, 0.0, f"Falha ao normalizar {papel} ({tipo_erro}): {mensagem}"

    duracao_normalizada_s = _obter_duracao_video_via_ffprobe(caminho_saida) or duracao_s
    return caminho_saida, duracao_normalizada_s, None


def anexar_intro_ending(
    pasta_projeto: Path,
    video_pronto: Path,
    marca_path: Path | None,
    posicao_marca: str,
    encoder: str,
) -> dict:
    """Ponto de entrada do GRUPO C: anexa intro (inicio) e ending (fim) -
    entrada/intro.<ext>/entrada/ending.<ext>, ambos opcionais
    (`descobrir_intro`/`descobrir_ending`) - ao `video_pronto` (video ja
    com narracao/musica/legenda queimada/marca d'agua aplicados). A MESMA
    marca d'agua do canal (se configurada) e' tambem aplicada sobre
    intro/ending, para consistencia de canal (GRUPO E).

    Retorna um dict {"video", "duracao_intro_s", "intro_aplicada",
    "ending_aplicada", "avisos"}. Sem intro nem ending configurados,
    retorna `video_pronto` sem nenhuma alteracao (zero custo, zero risco de
    regressao para todo projeto que nunca usou esta feature). Falha em
    QUALQUER ponto (normalizacao ou concat final) nunca derruba a montagem
    - o pipeline segue com o `video_pronto` original (ou so' com o lado que
    deu certo), registrando o motivo real em `avisos` (CLAUDE.md secao
    18.4)."""
    caminho_intro = descobrir_intro(pasta_projeto)
    caminho_ending = descobrir_ending(pasta_projeto)

    resultado_sem_alteracao = {
        "video": video_pronto,
        "duracao_intro_s": 0.0,
        "intro_aplicada": False,
        "ending_aplicada": False,
        "avisos": [],
    }

    if caminho_intro is None and caminho_ending is None:
        return resultado_sem_alteracao

    specs_alvo = _obter_specs_video_via_ffprobe(video_pronto)
    if specs_alvo is None:
        return {
            **resultado_sem_alteracao,
            "avisos": ["Nao foi possivel ler as especificacoes do video montado - intro/ending ignorados."],
        }

    avisos = []
    segmentos = []
    duracao_intro_s = 0.0
    intro_aplicada = False
    ending_aplicada = False

    if caminho_intro is not None:
        intro_normalizada, duracao_normalizada, aviso = normalizar_intro_ending(
            caminho_intro, pasta_projeto, "intro",
            specs_alvo["largura"], specs_alvo["altura"], specs_alvo["fps"],
            marca_path, posicao_marca, encoder,
        )
        if aviso:
            avisos.append(aviso)
        if intro_normalizada is not None:
            segmentos.append(intro_normalizada)
            duracao_intro_s = duracao_normalizada
            intro_aplicada = True

    segmentos.append(video_pronto)

    if caminho_ending is not None:
        ending_normalizada, _duracao_ending, aviso = normalizar_intro_ending(
            caminho_ending, pasta_projeto, "ending",
            specs_alvo["largura"], specs_alvo["altura"], specs_alvo["fps"],
            marca_path, posicao_marca, encoder,
        )
        if aviso:
            avisos.append(aviso)
        if ending_normalizada is not None:
            segmentos.append(ending_normalizada)
            ending_aplicada = True

    if not intro_aplicada and not ending_aplicada:
        # Normalizacao falhou dos dois lados (ou do unico configurado) -
        # video segue exatamente como antes desta feature, so' com os
        # avisos do motivo real.
        return {**resultado_sem_alteracao, "avisos": avisos}

    caminho_lista = pasta_projeto / "temp" / "concat_intro_ending_list.txt"
    caminho_saida = pasta_projeto / "temp" / "video_com_intro_ending.mp4"
    _escrever_lista_concat_arquivos(segmentos, caminho_lista)
    comando = construir_comando_concat(caminho_lista, caminho_saida)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_CONCAT_INTRO_ENDING_S, caminho_saida)

    if not sucesso:
        avisos.append(f"Falha ao concatenar intro/ending com o video ({tipo_erro}): {mensagem}")
        return {**resultado_sem_alteracao, "avisos": avisos}

    return {
        "video": caminho_saida,
        "duracao_intro_s": duracao_intro_s,
        "intro_aplicada": intro_aplicada,
        "ending_aplicada": ending_aplicada,
        "avisos": avisos,
    }


# ---------------------------------------------------------------------------
# Softsub SRT embutido (sempre, ultimo passo)
# ---------------------------------------------------------------------------


def construir_comando_softsub(video_path: Path, srt_path: Path, caminho_saida: Path) -> list:
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video_path),
        "-i", str(srt_path),
        "-map", "0", "-map", "1",
        "-c:v", "copy", "-c:a", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=por",
        "-metadata:s:s:0", "title=Português",
        str(caminho_saida),
    ]


def adicionar_softsub(video_path: Path, srt_path: Path, pasta_projeto: Path):
    caminho_saida = pasta_projeto / "saida" / "video_final.mp4"
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    comando = construir_comando_softsub(video_path, srt_path, caminho_saida)
    sucesso, tipo_erro, mensagem = _rodar_ffmpeg(comando, TIMEOUT_SOFTSUB_S, caminho_saida)
    if not sucesso:
        return None, tipo_erro, mensagem
    return caminho_saida, None, None


# ---------------------------------------------------------------------------
# Pre-condicoes (CLAUDE.md secao 18.6)
# ---------------------------------------------------------------------------


def _validar_pre_condicoes(pasta_projeto: Path, clipes: list, alinhamento):
    ok_ffmpeg, mensagem_ffmpeg = robustez.validar_pre_condicoes_pipeline()
    if not ok_ffmpeg:
        return False, mensagem_ffmpeg, "ffmpeg_ausente"

    if not clipes:
        return (
            False,
            "clipes/indice.json nao encontrado ou sem nenhum clipe gerado. "
            "Rode a Etapa 5 (geracao de clipes) antes desta etapa.",
            "clipes_ausentes",
        )

    if alinhamento is None:
        return (
            False,
            "narracao_alinhamento.json nao encontrado. Rode a Etapa 4 (audio) antes desta etapa.",
            "narracao_ausente",
        )

    if not (pasta_projeto / "narracao.mp3").exists():
        return False, "narracao.mp3 nao encontrado. Rode a Etapa 4 (audio) antes desta etapa.", "narracao_ausente"

    return True, None, None


# ---------------------------------------------------------------------------
# Orquestracao principal
# ---------------------------------------------------------------------------


def _montar_video_pipeline_completa(pasta_projeto: Path) -> dict:
    """Monta o video final do tipo de projeto "pipeline_completa" (default,
    comportamento historico): concat dos clipes + mux com narracao (e
    musica opcional) + legendas (SRT sempre, ASS queimado se configurado).
    Nunca levanta excecao - qualquer falha vira `{"sucesso": False, ...}`
    com `tipo_erro`/`erro_fatal` (CLAUDE.md secao 18.4)."""
    inicio_total = time.monotonic()

    clipes = _ler_indice_clipes(pasta_projeto)
    alinhamento = _ler_alinhamento_narracao(pasta_projeto)

    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes(pasta_projeto, clipes, alinhamento)
    if not ok_precondicoes:
        emitir_progresso(0.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    config = ler_configuracao_video(pasta_projeto)

    emitir_progresso(5.0, "Gerando legendas (SRT)...")
    srt_path = gerar_srt(alinhamento, pasta_projeto / "saida" / "legendas.srt")

    ass_path = None
    fonte_usada = None
    if config["legendas_queimadas"]:
        emitir_progresso(10.0, "Gerando legendas (estilo queimado)...")
        fonte_usada = escolher_fonte_legenda()
        ass_path = gerar_ass_estilo_mrbeast(alinhamento, pasta_projeto / "saida" / "legendas.ass", fonte_usada)

    emitir_progresso(20.0, f"Concatenando {len(clipes)} clipe(s)...")
    video_concat, tipo_erro, mensagem_erro = concat_clipes(pasta_projeto, clipes, config["grayscale"])
    if video_concat is None:
        emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    musica_path = None
    if config["com_musica_fundo"]:
        musicas = descobrir_playlist_musicas(pasta_projeto)
        if musicas:
            duracao_narracao_s = (alinhamento or {}).get("duracao_s") or 0.0
            duracao_alvo_musica_s = duracao_narracao_s + FOLGA_MUSICA_S
            emitir_progresso(
                40.0,
                f"Preparando playlist de musica ({len(musicas)} faixa(s), loop sequencial)...",
            )
            musica_path, tipo_erro, mensagem_erro = preparar_faixa_musica_playlist(
                musicas, duracao_alvo_musica_s, pasta_projeto
            )
            if musica_path is None:
                emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
                return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    emitir_progresso(45.0, "Adicionando narracao e musica de fundo..." if musica_path else "Adicionando narracao...")
    video_com_audio, tipo_erro, mensagem_erro = mux_audio(
        video_concat, pasta_projeto / "narracao.mp3", pasta_projeto, musica_path
    )
    if video_com_audio is None:
        emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    marca_path, aviso_marca = resolver_marca_dagua(pasta_projeto, config)
    # Calculado incondicionalmente (nao so' dentro do `if` abaixo) porque a
    # normalizacao de intro/ending (GRUPO B) pode precisar reencodar mesmo
    # quando este projeto nao usa legenda queimada nem marca d'agua.
    encoder = _detectar_encoder_gpu()

    video_atual = video_com_audio
    if ass_path is not None or marca_path is not None:
        if marca_path is None:
            # Caminho ORIGINAL, inalterado: so' legenda queimada, sem marca
            # d'agua nenhuma configurada/resolvida para este projeto.
            emitir_progresso(65.0, "Queimando legendas no video...")
            video_queimado, tipo_erro, mensagem_erro = queimar_legendas(video_atual, ass_path, pasta_projeto, encoder)
            if video_queimado is None:
                emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
                return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}
            video_atual = video_queimado
        else:
            # Marca d'agua configurada (com ou sem legenda queimada junto) -
            # uma UNICA passada de reencode (`aplicar_marca_dagua`) funde as
            # duas, nunca reencoda o video duas vezes.
            emitir_progresso(
                65.0,
                "Queimando legendas e marca d'agua no video..." if ass_path is not None else "Aplicando marca d'agua no video...",
            )
            largura_video = _obter_largura_video_via_ffprobe(video_atual) or LARGURA_VIDEO_PADRAO_PX
            video_queimado, tipo_erro_marca, mensagem_erro_marca = aplicar_marca_dagua(
                video_atual, marca_path, pasta_projeto, ass_path, "ass",
                largura_video, MARCA_DAGUA_CANAL_POSICAO, encoder,
            )
            if video_queimado is None:
                # Falha no overlay nunca derruba o video inteiro (CLAUDE.md
                # secao 18.4/GRUPO E desta sessao) - registra o motivo REAL
                # e tenta seguir so' com a legenda (se havia), ou sem
                # nenhuma das duas.
                aviso_marca = f"Falha ao aplicar marca d'agua ({tipo_erro_marca}): {mensagem_erro_marca}"
                if ass_path is not None:
                    video_queimado, tipo_erro, mensagem_erro = queimar_legendas(video_atual, ass_path, pasta_projeto, encoder)
                    if video_queimado is None:
                        emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
                        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}
                else:
                    video_queimado = video_atual
            video_atual = video_queimado

    emitir_progresso(85.0, "Anexando intro/ending, se configurados...")
    resultado_intro_ending = anexar_intro_ending(
        pasta_projeto, video_atual, marca_path, MARCA_DAGUA_CANAL_POSICAO, encoder
    )
    video_atual = resultado_intro_ending["video"]
    duracao_intro_s = resultado_intro_ending["duracao_intro_s"]
    avisos_intro_ending = resultado_intro_ending["avisos"]

    if duracao_intro_s > 0:
        # Intro foi de fato prependida ao video - o softsub (proximo passo)
        # e' embutido no video JA com a intro, entao a legenda precisa do
        # mesmo deslocamento pra bater com a posicao real da narracao
        # (GRUPO E: legenda queimada nunca precisa disso, ja foi queimada
        # antes da intro existir - so' o softsub, que e' sempre o ultimo
        # passo). Sobrescreve saida/legendas.srt (gerado cedo, sem
        # deslocamento, no inicio desta funcao) com a versao final.
        srt_path = gerar_srt(alinhamento, pasta_projeto / "saida" / "legendas.srt", offset_s=duracao_intro_s)

    emitir_progresso(90.0, "Finalizando (legenda embutida)...")
    video_final, tipo_erro, mensagem_erro = adicionar_softsub(video_atual, srt_path, pasta_projeto)
    if video_final is None:
        emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    metadata = {
        "total_clipes": len(clipes),
        "legendas_queimadas": config["legendas_queimadas"],
        "com_musica_fundo": musica_path is not None,
        "grayscale": config["grayscale"],
        "fonte_legenda": fonte_usada,
        "marca_dagua_aplicada": marca_path is not None and aviso_marca is None,
        "marca_dagua_origem": config["marca_dagua_projeto"],
        "marca_dagua_posicao": MARCA_DAGUA_CANAL_POSICAO if marca_path is not None else None,
        "marca_dagua_aviso": aviso_marca,
        "intro_aplicada": resultado_intro_ending["intro_aplicada"],
        "ending_aplicada": resultado_intro_ending["ending_aplicada"],
        "duracao_intro_s": duracao_intro_s,
        "intro_ending_avisos": avisos_intro_ending,
        "duracao_video_s": _obter_duracao_video_via_ffprobe(video_final),
        "tempo_total_s": round(time.monotonic() - inicio_total, 3),
        "data_geracao": datetime.now(timezone.utc).isoformat(),
    }
    (pasta_projeto / "saida" / "montagem_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    avisos_finais = ([aviso_marca] if aviso_marca else []) + avisos_intro_ending
    emitir_progresso(
        100.0, "Concluido: video final montado", sucesso=True, video_final=str(video_final),
        avisos=avisos_finais,
    )
    return {"sucesso": True, "video_final": str(video_final)}


# ---------------------------------------------------------------------------
# Montagem do tipo de projeto "videos_pre_gerados" (CLAUDE.md secao 3) -
# usuario ja tem os clipes finais prontos (ex: exportados do DarkPlanner
# Flow/Veo3, ja com audio embutido - narracao/efeitos/musica). So concatena
# (`concat_clipes`, reaproveitada sem alteracao - o `-c copy` do caminho
# original ja preserva qualquer stream de audio embutido em cada clipe,
# contanto que os clipes sejam uniformes em codec/resolucao/fps entre si) e
# queima um SRT importado se configurado. NUNCA chama `mux_audio`: os
# clipes ja tem audio, sobrepor narracao/musica bagunçaria o som. Sem
# reorganizacao manual (Feature B), sem sincronizacao com IA (Feature A),
# sem grayscale - nenhuma dessas opcoes se aplica a este tipo de projeto.
# ---------------------------------------------------------------------------


def _validar_pre_condicoes_videos_pre_gerados(pasta_projeto: Path, clipes: list):
    ok_ffmpeg, mensagem_ffmpeg = robustez.validar_pre_condicoes_pipeline()
    if not ok_ffmpeg:
        return False, mensagem_ffmpeg, "ffmpeg_ausente"

    if not clipes:
        return (
            False,
            "clipes/indice.json nao encontrado ou sem nenhum video enviado.",
            "clipes_ausentes",
        )

    return True, None, None


def montar_video_videos_pre_gerados(pasta_projeto: Path) -> dict:
    """Monta o video final do tipo de projeto "videos_pre_gerados": so'
    concatena os clipes enviados pelo usuario e, se ele importou um SRT E
    marcou "legendas_queimadas", queima essa legenda no video. Nunca
    levanta excecao - qualquer falha vira `{"sucesso": False, ...}`
    (CLAUDE.md secao 18.4)."""
    inicio_total = time.monotonic()

    clipes = _ler_indice_clipes(pasta_projeto)
    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes_videos_pre_gerados(pasta_projeto, clipes)
    if not ok_precondicoes:
        emitir_progresso(0.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    config = ler_configuracao_video(pasta_projeto)
    srt_importado = pasta_projeto / "entrada" / "legenda_importada.srt"
    tem_srt_importado = srt_importado.exists()

    emitir_progresso(20.0, f"Concatenando {len(clipes)} video(s)...")
    video_concat, tipo_erro, mensagem_erro = concat_clipes(pasta_projeto, clipes)
    if video_concat is None:
        emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    legenda_path = srt_importado if (config["legendas_queimadas"] and tem_srt_importado) else None
    marca_path, aviso_marca = resolver_marca_dagua(pasta_projeto, config)
    # Calculado incondicionalmente pelo mesmo motivo de
    # `_montar_video_pipeline_completa`: a normalizacao de intro/ending
    # pode precisar reencodar mesmo sem legenda/marca d'agua.
    encoder = _detectar_encoder_gpu()

    video_atual = video_concat
    if legenda_path is not None or marca_path is not None:
        if marca_path is None:
            # Caminho ORIGINAL, inalterado.
            emitir_progresso(70.0, "Queimando legenda importada no video...")
            video_queimado, tipo_erro, mensagem_erro = queimar_srt_importado(
                video_atual, legenda_path, pasta_projeto, encoder
            )
            if video_queimado is None:
                emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
                return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}
            video_atual = video_queimado
        else:
            emitir_progresso(
                70.0,
                "Queimando legenda e marca d'agua no video..." if legenda_path is not None else "Aplicando marca d'agua no video...",
            )
            largura_video = _obter_largura_video_via_ffprobe(video_atual) or LARGURA_VIDEO_PADRAO_PX
            video_queimado, tipo_erro_marca, mensagem_erro_marca = aplicar_marca_dagua(
                video_atual, marca_path, pasta_projeto, legenda_path, "srt",
                largura_video, MARCA_DAGUA_CANAL_POSICAO, encoder,
            )
            if video_queimado is None:
                aviso_marca = f"Falha ao aplicar marca d'agua ({tipo_erro_marca}): {mensagem_erro_marca}"
                if legenda_path is not None:
                    video_queimado, tipo_erro, mensagem_erro = queimar_srt_importado(
                        video_atual, legenda_path, pasta_projeto, encoder
                    )
                    if video_queimado is None:
                        emitir_progresso(100.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro)
                        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}
                else:
                    video_queimado = video_atual
            video_atual = video_queimado

    emitir_progresso(85.0, "Anexando intro/ending, se configurados...")
    # Sem narracao/softsub neste tipo de projeto (docstring desta funcao) -
    # nenhuma logica de deslocamento de timing e' necessaria aqui, so'
    # normalizacao + concatenacao (confirmado - secao 1.5/Grupo D).
    resultado_intro_ending = anexar_intro_ending(
        pasta_projeto, video_atual, marca_path, MARCA_DAGUA_CANAL_POSICAO, encoder
    )
    video_atual = resultado_intro_ending["video"]
    avisos_intro_ending = resultado_intro_ending["avisos"]

    emitir_progresso(90.0, "Finalizando...")
    caminho_saida = pasta_projeto / "saida" / "video_final.mp4"
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    video_atual.replace(caminho_saida)

    if tem_srt_importado:
        (pasta_projeto / "saida" / "legendas.srt").write_bytes(srt_importado.read_bytes())

    metadata = {
        "tipo_projeto": "videos_pre_gerados",
        "total_clipes": len(clipes),
        "legendas_queimadas": bool(config["legendas_queimadas"] and tem_srt_importado),
        "marca_dagua_aplicada": marca_path is not None and aviso_marca is None,
        "marca_dagua_origem": config["marca_dagua_projeto"],
        "marca_dagua_posicao": MARCA_DAGUA_CANAL_POSICAO if marca_path is not None else None,
        "marca_dagua_aviso": aviso_marca,
        "intro_aplicada": resultado_intro_ending["intro_aplicada"],
        "ending_aplicada": resultado_intro_ending["ending_aplicada"],
        "intro_ending_avisos": avisos_intro_ending,
        "duracao_video_s": _obter_duracao_video_via_ffprobe(caminho_saida),
        "tempo_total_s": round(time.monotonic() - inicio_total, 3),
        "data_geracao": datetime.now(timezone.utc).isoformat(),
    }
    (pasta_projeto / "saida" / "montagem_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    avisos_finais = ([aviso_marca] if aviso_marca else []) + avisos_intro_ending
    emitir_progresso(
        100.0, "Concluido: video final montado", sucesso=True, video_final=str(caminho_saida),
        avisos=avisos_finais,
    )
    return {"sucesso": True, "video_final": str(caminho_saida)}


def montar_video(pasta_projeto: Path) -> dict:
    """Ponto de entrada da Etapa 6 - despacha para o caminho de montagem
    certo conforme entrada/tipo_projeto.txt (CLAUDE.md secao 3):
    "pipeline_completa" (default, `_montar_video_pipeline_completa`) ou
    "videos_pre_gerados" (`montar_video_videos_pre_gerados`). Projeto criado
    antes desta feature (sem o marcador) sempre cai em "pipeline_completa" -
    retrocompatibilidade total, nenhuma migracao necessaria."""
    if _ler_tipo_projeto(pasta_projeto) == "videos_pre_gerados":
        return montar_video_videos_pre_gerados(pasta_projeto)
    return _montar_video_pipeline_completa(pasta_projeto)


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/6_montar_video.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    resultado = montar_video(pasta_projeto)

    if not resultado.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
