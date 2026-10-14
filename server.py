import concurrent.futures
import hashlib
import html
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import markdown
from dotenv import dotenv_values, load_dotenv, set_key
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from scripts import ambiente, marca_dagua_canal, robustez, sincronizador_visual, thumbnail_briefing, validators
from scripts.imagem import openai as imagem_openai
from scripts.labels_ui import (
    ETAPA_LABEL,
    PIPELINE_ETAPAS,
    PROVEDOR_TTS_LABEL as PROVEDOR_TTS_NOMES,
    label_etapa,
    label_provedor_tts,
    label_status,
    label_tipo_projeto,
)
from scripts.prompts import loader as prompts_loader
from scripts.tts import ProvedorTTSInvalidoError, get_provedor
from scripts.tts import preview_vozes
from scripts.warnings_traducoes import (
    WARNING_FALLBACK,
    WARNINGS_ACIONAVEIS,
    categoria_do_aviso,
)
from scripts.validators import (
    ORIGEM_MARCA_DAGUA_PROJETO_PADRAO,
    TAMANHO_MAX_INTRO_ENDING_BYTES,
    TAMANHO_MAX_MARCA_DAGUA_BYTES,
    TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES,
    TAMANHO_MAX_UPLOAD_BYTES,
    TIPO_PROJETO_PADRAO,
    chave_dedup_youtube,
    classificar_extensao_upload,
    normalizar_caminho,
    prefixo_numerico_arquivo,
    validar_arquivo_roteiro,
    validar_caminho_projetos,
    validar_extensao_intro_ending,
    validar_extensao_musica,
    validar_marca_dagua,
    validar_modo_fontes,
    validar_nome_projeto,
    validar_origem_marca_dagua_projeto,
    validar_origem_roteiro,
    validar_tipo_projeto,
    validar_tipo_uso,
    validar_url_youtube,
)
from werkzeug.utils import secure_filename

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = BASE_DIR / ".env"
VERSION_PATH = BASE_DIR / "VERSION.txt"
LICENSE_PATH = BASE_DIR / "LICENSE.txt"

# scripts/7_thumbnail.py comeca com digito - nao e' importavel como modulo
# normal (`from scripts import ...`). Carregado via importlib, mesmo padrao
# usado pelos testes (tests/test_thumbnail.py) - server.py so' chama as
# funcoes do Grupo B/D direto (atualizar_sujeito_slot, gerar_metadados,
# _normalizar_thumbnail_metadados); o script continua rodando como
# subprocess isolado (_executar_etapa7) pra gerar metadados/briefing sem
# bloquear a requisicao HTTP.
_THUMBNAIL_ETAPA7_SPEC = importlib.util.spec_from_file_location(
    "thumbnail_etapa7", BASE_DIR / "scripts" / "7_thumbnail.py"
)
thumbnail_etapa7 = importlib.util.module_from_spec(_THUMBNAIL_ETAPA7_SPEC)
sys.modules[_THUMBNAIL_ETAPA7_SPEC.name] = thumbnail_etapa7
_THUMBNAIL_ETAPA7_SPEC.loader.exec_module(thumbnail_etapa7)

IDIOMAS_SUPORTADOS = ["en-US", "en-GB", "pt-BR", "es", "de"]

# Modelos Claude oferecidos no dropdown de Ajustes (CLAUDE.md secao 7,
# ANTHROPIC_MODEL) - sonnet e' o default/melhor equilibrio custo-qualidade.
MODELOS_ANTHROPIC_SUPORTADOS = ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"]
# "google" e "darkplanner" sao os provedores implementados de verdade
# (CLAUDE.md secao 5.6 - Sessao 8 pro Google, Sessao 26 pro DarkPlanner,
# scripts/tts/google.py e scripts/tts/darkplanner.py); os demais sao stubs
# (scripts/tts/elevenlabs.py, openai.py, azure.py) que continuam listados
# aqui para a tela de revisao os mostrar desabilitados ate' serem
# implementados.
PROVEDORES_TTS = ["google", "darkplanner", "elevenlabs", "openai", "azure"]

# Provedores de TTS stub (elevenlabs/openai/azure) hoje passam pela
# validacao de "disponivel" so' com a chave presente (CLAUDE.md secao 5.6:
# a chamada real fica pra dentro do subprocess da Etapa 4, que falha la'
# com NotImplementedError - comportamento deliberado, NAO mexer aqui,
# tem suite propria cobrindo isso pra elevenlabs/azure).
#
# "openai" e' EXCECAO a partir desta sessao: OPENAI_API_KEY passou a
# tambem ser a chave do provedor de IMAGEM da Etapa 7 (scripts/imagem/
# openai.py, mesma conta OpenAI, reaproveitada de proposito). Isso cria um
# falso positivo NOVO que nao existia antes - a chave pode estar presente
# so' pra imagem, sem o usuario nunca ter pretendido usar TTS OpenAI (que
# continua tao stub quanto sempre foi). Por isso "openai" precisa de uma
# checagem A MAIS (nunca "disponivel", com ou sem chave) em todo lugar que
# decide disponibilidade de TTS - elevenlabs/azure NAO tem esse problema
# (chave propria, sem uso duplo) e continuam no comportamento antigo.
PROVEDOR_TTS_OPENAI_INDISPONIVEL_COM_CHAVE = "openai"

# Nome de exibicao de cada provedor TTS (tela de revisao - CLAUDE.md secao
# 5.5) e a variavel de .env cuja ausencia desabilita o provedor no dropdown.
# PROVEDOR_TTS_NOMES vem de scripts/labels_ui.py (import no topo do arquivo)
# - unica fonte da verdade, compartilhada com os filtros Jinja de label.
PROVEDOR_TTS_CHAVE_ENV = {
    "google": "GOOGLE_TTS_API_KEY",
    "darkplanner": "DARKPLANNER_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_TTS_KEY",
}

# Vozes conhecidas por provedor (CLAUDE.md secao 5.5 - "listas hard-coded de
# vozes conhecidas por provedor, 5-10 vozes cada"). IDs reais dos catalogos
# publicos de cada provedor - a Etapa 4 (Sessao 8) e' quem de fato chama a
# API de sintese com o ID escolhido aqui.
VOZES_TTS = {
    "elevenlabs": [
        {"id": "21m00Tcm4TlvDq8ikWAM", "nome": "Rachel"},
        {"id": "AZnzlk1XvdvUeBnXmlld", "nome": "Domi"},
        {"id": "EXAVITQu4vr4xnSDxMaL", "nome": "Bella"},
        {"id": "ErXwobaYiN019PkySvjV", "nome": "Antoni"},
        {"id": "MF3mGyEYCl7XYWbV9V6O", "nome": "Elli"},
        {"id": "TxGEqnHWrfWFTfGW9XjX", "nome": "Josh"},
        {"id": "VR6AewLTigWG4xSOukaG", "nome": "Arnold"},
    ],
    "openai": [
        {"id": "alloy", "nome": "Alloy"},
        {"id": "echo", "nome": "Echo"},
        {"id": "fable", "nome": "Fable"},
        {"id": "onyx", "nome": "Onyx"},
        {"id": "nova", "nome": "Nova"},
        {"id": "shimmer", "nome": "Shimmer"},
    ],
    "azure": [
        {"id": "en-US-GuyNeural", "nome": "Guy (en-US)"},
        {"id": "en-US-JennyNeural", "nome": "Jenny (en-US)"},
        {"id": "en-US-AriaNeural", "nome": "Aria (en-US)"},
        {"id": "en-GB-RyanNeural", "nome": "Ryan (en-GB)"},
        {"id": "pt-BR-AntonioNeural", "nome": "Antonio (pt-BR)"},
        {"id": "pt-BR-FranciscaNeural", "nome": "Francisca (pt-BR)"},
    ],
}

# Status de job.json (CLAUDE.md secao 5.5) a partir dos quais a tela de
# revisao de roteiro pode ser aberta: "aguardando_revisao" e' o caminho
# principal (logo apos a Etapa 3); "aguardando_audio" e' o retorno de um
# projeto que ja aprovou o roteiro mas escolheu "Decidir depois" a origem do
# audio (CLAUDE.md secao 5.6, Caminho C) - a home linka para a mesma tela
# nesse caso, para o usuario poder decidir a origem do audio agora.
STATUS_PERMITIDOS_REVISAO = ("aguardando_revisao", "aguardando_audio")

# Migracao leve de status antigos de job.json (CLAUDE.md - consolidacao da
# antiga cadeia de tres etapas dividir_cenas (5) -> montar_timeline (6) ->
# renderizar_clipes (7), que usava PySceneDetect + pHash + Vision opcional,
# numa unica Etapa 5 "gerar_clipes" por selecao aleatoria de trechos -
# PySceneDetect levava 12+ min/video em CPU e Vision custava $0.82/video
# para pouco ganho de qualidade). Projetos criados antes desta consolidacao
# podem ter parado num status que nao existe mais no pipeline novo. Todos
# migram para "aguardando_geracao_clipes" - o ponto de entrada da nova
# Etapa 5, que reaproveita as fontes/narracao ja existentes desses
# projetos para gerar os clipes do zero (qualquer plano/clipe antigo fica
# obsoleto e e' substituido pelo novo pipeline). Aplicada so' em memoria na
# leitura (`_ler_job_json`) - nunca reescreve o job.json no disco.
STATUS_MIGRATION = {
    "aguardando_geracao_video": "aguardando_geracao_clipes",
    "aguardando_curadoria": "aguardando_geracao_clipes",
    "aguardando_cortes_v9": "aguardando_geracao_clipes",
    "aguardando_planejamento": "aguardando_geracao_clipes",
    "aguardando_cortes": "aguardando_geracao_clipes",
    "aguardando_divisao_cenas": "aguardando_geracao_clipes",
    "aguardando_montagem_timeline": "aguardando_geracao_clipes",
    "aguardando_renderizacao": "aguardando_geracao_clipes",
}

# Migracao leve de etapa_atual antigo (bug corrigido pos-Sessao 20): ate essa
# correcao, a Etapa 3 gravava etapa_atual="revisao" no job.json ao pausar
# para revisao humana, mas PIPELINE_ETAPAS nunca teve uma etapa "revisao"
# (so' "roteiro" - ver PIPELINE_ETAPAS abaixo) - isso fazia
# _parsear_pipeline_steps nao encontrar o indice da etapa atual e marcar
# TODAS as etapas (inclusive Download/Transcricao ja concluidas) como
# "pending" na pipeline horizontal. O codigo novo grava "roteiro"; esta
# migracao so' cobre projetos que pausaram para revisao antes da correcao e
# ainda tem "revisao" gravado em disco. Aplicada so' em memoria na leitura
# (`_ler_job_json`) - nunca reescreve o job.json no disco.
ETAPA_ATUAL_MIGRATION = {
    "revisao": "roteiro",
}

# Migracao leve de proxima_etapa antigo (bug corrigido na sessao de UX pos-
# Sessao 18): ate essa correcao, _executar_etapa4 (audio) gravava
# proxima_etapa="planejamento" ao concluir - nome orfao da arquitetura
# abandonada "5_planejar_edicao.py" (removida entre Sessoes 9-11, CLAUDE.md
# secao 5.7). O nome real da etapa hoje e' "geracao_clipes"
# (PIPELINE_ETAPAS). Projeto que pausou/terminou a Etapa 4 antes da correcao
# pode ter "planejamento" gravado em disco. Aplicada so' em memoria na
# leitura (`_ler_job_json`) - nunca reescreve o job.json no disco.
PROXIMA_ETAPA_MIGRATION = {
    "planejamento": "geracao_clipes",
}

# Formatos de audio aceitos no upload de narracao propria (CLAUDE.md secao
# 5.6, Caminho B) e tamanho maximo (evita upload de arquivo absurdamente
# grande por engano).
EXTENSOES_AUDIO_VALIDAS = frozenset({".mp3", ".wav", ".m4a", ".ogg"})
TAMANHO_MAX_AUDIO_BYTES = 100 * 1024 * 1024

# Upload manual de foto do sujeito na tela de thumbnail (Grupo G, Etapa 7,
# caso 1 da cascata do Grupo C - CLAUDE.md futura secao de thumbnail).
EXTENSOES_IMAGEM_VALIDAS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# Cotacao USD->BRL usada so para exibir o custo estimado do roteiro (CLAUDE.md
# secao 7/5.5) em ambas as moedas na tela de revisao. Aproximada, editavel via
# COTACAO_USD_BRL no .env - nunca busca cotacao real online (produto local,
# sem chamada de API so pra isso).
COTACAO_USD_BRL_PADRAO = 5.20

# Notas de rodape de origem do roteiro (CLAUDE.md secao 5.4):
# [F1@04:32] ou [F1@04:32-05:10] (fonte de video, com timestamp opcional em
# intervalo), [N: url ou texto] (nota externa) e [⚠ texto] (aviso de
# single-source/conflito). Compilados uma vez no import - usados por
# renderizar_notas_rodape().
#
# Uma tag [F...] pode conter MULTIPLAS fontes separadas por virgula, ex.
# [F2@00:27-01:00, F1@16:00-16:06] (correcao pos-Sessao 7.2 - roteiro real
# gerou esse padrao e nem o badge nem o filtro de remocao reconheciam,
# entao a tag bruta ia parar no roteiro_aprovado.md e o TTS narrava ela
# literalmente). PADRAO_NOTA_FONTE casa a tag INTEIRA (com 1 ou mais
# fontes); PADRAO_FONTE_ITEM (sem ancoras `[`/`]`) e' usado para extrair
# cada fonte individual de dentro de uma tag ja casada, com seu proprio
# numero e timestamp(s).
_TS_NOTA_FONTE = r"\d{1,2}:\d{2}(?::\d{2})?"
_ITEM_NOTA_FONTE = rf"F\d+@{_TS_NOTA_FONTE}(?:-{_TS_NOTA_FONTE})?"
PADRAO_NOTA_FONTE = re.compile(
    rf"\[{_ITEM_NOTA_FONTE}(?:\s*,\s*{_ITEM_NOTA_FONTE})*\]"
)
PADRAO_FONTE_ITEM = re.compile(
    rf"F(\d+)@({_TS_NOTA_FONTE})(?:-({_TS_NOTA_FONTE}))?"
)
PADRAO_NOTA_EXTERNA = re.compile(r"\[N:\s*([^\]]+)\]")
PADRAO_AVISO = re.compile(r"\[⚠\s*([^\]]*)\]")

# Numeracao sequencial exibida nos badges de fonte quando uma tag tem mais
# de uma fonte (ex. [F2@00:27-01:00, F1@16:00-16:06] vira dois badges ①②) -
# espelha numeroCirculado() em static/revisao.js. 1-20 usa circulo unicode
# (faixa mais que suficiente para uma tag real); alem disso cai para "(N)"
# em vez de travar.
def _numero_circulado(n: int) -> str:
    if 1 <= n <= 20:
        return chr(0x2460 + (n - 1))
    return f"({n})"


# Opcoes do dropdown de marca d'agua de cada link, no formulario de Novo
# projeto (CLAUDE.md secao 5.7.1). Ordem = ordem de exibicao no <select>.
OPCOES_MARCA_DAGUA = [
    ("nenhuma", "Sem marca d'água"),
    ("superior_direito", "Marca no canto superior direito"),
    ("superior_esquerdo", "Marca no canto superior esquerdo"),
    ("inferior_direito", "Marca no canto inferior direito"),
    ("inferior_esquerdo", "Marca no canto inferior esquerdo"),
    ("banner_inferior", "Marca em banner inferior"),
]

# Opcoes do dropdown de POSICAO da marca d'agua do CANAL (sessao "Marca
# d'agua do canal aplicada ao video final") - so os 4 cantos, distinto de
# OPCOES_MARCA_DAGUA acima (remocao de marca das FONTES, 6 opcoes incluindo
# banner). Mesmas chaves que scripts/marca_dagua_canal.POSICOES_MARCA_DAGUA_CANAL.
OPCOES_MARCA_DAGUA_CANAL = [
    ("superior_direito", "Canto superior direito"),
    ("superior_esquerdo", "Canto superior esquerdo"),
    ("inferior_direito", "Canto inferior direito"),
    ("inferior_esquerdo", "Canto inferior esquerdo"),
]

# Local FIXO e global (fora de qualquer pasta de projeto) onde a marca
# d'agua do canal configurada em Ajustes fica salva - scripts/6_montar_video.py
# le o MESMO caminho (duplicado la' por ser script autocontido, CLAUDE.md
# secao 9). config/ nao e' uma pasta de projeto nem de assets do produto -
# e' configuracao do USUARIO que persiste entre reinicializacoes do servidor,
# mesmo espirito de .env (BASE_DIR/.env).
PASTA_CONFIG_GLOBAL = BASE_DIR / "config"
ARQUIVO_MARCA_DAGUA_GLOBAL = PASTA_CONFIG_GLOBAL / "marca_dagua_canal.png"
ARQUIVO_MARCA_DAGUA_GLOBAL_META = PASTA_CONFIG_GLOBAL / "marca_dagua_canal.json"

# Marcadores que identificam uma subpasta de PROJETOS_DIR como projeto do
# Broll Foundry (e nao uma pasta qualquer que o usuario tenha ali dentro).
MARCADORES_PROJETO = [
    os.path.join("entrada", "links.txt"),
    "job.json",
]

# Teto de tamanho de uma requisicao POST /novo inteira (todos os uploads
# somados) - protecao contra upload gigante travar o servidor. Validacao por
# arquivo individual (TAMANHO_MAX_UPLOAD_BYTES, 500MB) acontece depois, em
# _salvar_uploads.
MAX_CONTENT_LENGTH_BYTES = 5 * 1024 * 1024 * 1024  # 5GB

# Abaixo deste espaco livre no disco de destino, salvar um upload emite um
# aviso no log do servidor (nao bloqueia o upload - CLAUDE.md secao 18: uma
# checagem de robustez nunca deve travar o fluxo do usuario. Se o disco
# encher de verdade, o ffmpeg de uma etapa posterior falha com erro claro,
# ja' categorizado como "disco_cheio" em scripts/5_gerar_clipes.py).
LIMITE_AVISO_DISCO_LIVRE_GB = 10

# Subconjunto de variaveis editavel pela tela de ajustes (CLAUDE.md secao 7).
CAMPOS_AJUSTES = [
    "PROJETOS_DIR",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "YOUTUBE_API_KEY",
    "IDIOMA_ROTEIRO",
    "WHISPER_MODEL",
    "KEN_BURNS",
    "CLIPE_DURACAO_MIN_S",
    "CLIPE_DURACAO_MAX_S",
    "TTS_PROVEDOR_PADRAO",
    "TTS_VOZ_PADRAO",
    "GOOGLE_TTS_API_KEY",
    "DARKPLANNER_API_KEY",
    "ELEVENLABS_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_TTS_KEY",
    "AZURE_TTS_REGION",
    "LEGENDA_FONTE",
    "LEGENDA_TAMANHO",
    "LEGENDA_POSICAO",
    "LEGENDA_KARAOKE_ATIVO",
    "LEGENDA_DESTAQUE_COR_NOME",
    "MUSICA_VOLUME_BASE",
    "WEB_SEARCH_MAX",
    "COTACAO_USD_BRL",
    "GERAR_THUMBNAIL_PADRAO",
    "MARCA_DAGUA_CANAL_POSICAO",
]


def _gerar_thumbnail_padrao_ajustes() -> bool:
    """Le GERAR_THUMBNAIL_PADRAO dos Ajustes - default True (Etapa 7
    sempre rodava antes desta feature, comportamento historico
    preservado). Usado pra pre-marcar o checkbox de Novo projeto quando
    nenhum `form` sticky esta disponivel (GET normal, ou erro de
    validacao anterior a esta feature nunca ter enviado o campo)."""
    return os.environ.get("GERAR_THUMBNAIL_PADRAO", "true").strip().lower() != "false"


def _validar_png_marca_dagua(conteudo: bytes) -> tuple:
    """Valida que `conteudo` e' um PNG de verdade e detecta se tem canal
    alfa. Retorna (valido, tem_alfa, mensagem_erro_ou_None). PNG sem canal
    alfa NUNCA bloqueia o upload (CLAUDE.md secao 18: aviso, nao trava o
    fluxo) - so' o formato errado (nao-PNG/corrompido) bloqueia. Usa Pillow
    (ja' pinado em requirements.txt) pra abrir e checar `mode`/`info` -
    nunca levanta excecao pra fora desta funcao."""
    from PIL import Image
    import io

    try:
        imagem = Image.open(io.BytesIO(conteudo))
        imagem.verify()
        # `verify()` fecha o arquivo internamente - reabre pra' checar modo/alfa.
        imagem = Image.open(io.BytesIO(conteudo))
        formato = imagem.format
        tem_alfa = imagem.mode in ("RGBA", "LA") or "transparency" in imagem.info
    except Exception:
        return False, False, "Arquivo enviado nao e' um PNG valido ou esta corrompido."

    if formato != "PNG":
        return False, False, "Envie um arquivo no formato PNG."
    return True, tem_alfa, None


def _ler_metadata_marca_dagua_global() -> dict | None:
    """Le config/marca_dagua_canal.json (metadata da marca d'agua global do
    canal, configurada em Ajustes) - None se nao houver marca configurada ou
    o arquivo estiver corrompido (nunca levanta excecao)."""
    if not ARQUIVO_MARCA_DAGUA_GLOBAL.exists():
        return None
    return _ler_json_seguro(ARQUIVO_MARCA_DAGUA_GLOBAL_META)

# Estado dos jobs em execucao, em memoria. Se o servidor reiniciar, jobs em
# andamento se perdem (aceitavel para o MVP - ver CLAUDE.md secao 4).
jobs = {}

# Threads das etapas do pipeline em execucao, por projeto_id. Separado de
# `jobs` porque um objeto Thread nao e' serializavel por jsonify (GET
# /api/status/<id> so devolve `jobs[projeto_id]`). Exposto tambem para os
# testes poderem esperar a etapa terminar (thread.join()) sem precisar de
# sleep.
_threads = {}

# Linha de progresso emitida pelos scripts do pipeline via stdout, no
# formato `@PROGRESSO {json}` (CLAUDE.md secao 9).
PADRAO_PROGRESSO_JSON = re.compile(r"^@PROGRESSO\s+(\{.*\})\s*$")

# Mapa etapa concluida -> proxima etapa do pipeline, usado so para exibir
# "proxima etapa: X" na tela de status (CLAUDE.md secao 5). Etapas ainda
# nao implementadas (a partir de "corte de clipes") ficam para sessoes
# futuras.
PROXIMA_ETAPA = {
    "download": "transcricao",
}

# Ambiente NVIDIA/CUDA detectado no boot do servidor (CLAUDE.md secao 13 -
# requisitos minimos oficiais - e secao 18). Global de modulo (nao so
# app.config) porque _executar_etapa1/_executar_etapa2 rodam em threads de
# fundo sem contexto de aplicacao Flask disponivel para ler app.config.
# Recalculado a cada create_app() (mesmo espirito de BANNERS).
AMBIENTE_ATUAL = {"gpu": None, "compatibilidade": None, "modelo_recomendado": None}

FOOTPRINT_MODELO_GB = {"small": 1, "medium": 2, "large-v3": 3}


def _calcular_ambiente():
    """Deteccao de GPU/CUDA no boot do servidor (CLAUDE.md secao 13/18.2):
    nao derruba o boot se o ambiente nao atender ao minimo - so registra o
    motivo para o banner global e a tela de Ajustes explicarem ao usuario
    (ele precisa poder abrir Ajustes pra diagnosticar, mesmo com ambiente
    incompativel)."""
    gpu = ambiente.detectar_gpu()
    compatibilidade = ambiente.avaliar_compatibilidade(gpu)
    modelo_recomendado = ambiente.recomendar_modelo(gpu) if compatibilidade["atende_minimo"] else None
    return {
        "gpu": gpu,
        "compatibilidade": compatibilidade,
        "modelo_recomendado": modelo_recomendado,
    }


def _ambiente_atende_minimo() -> bool:
    compat = AMBIENTE_ATUAL.get("compatibilidade") or {}
    return bool(compat.get("atende_minimo"))


def _aviso_modelo_apertado(modelos_suportados, modelo_selecionado, vram_mb):
    """Aviso amarelo (tela de Ajustes) quando o modelo Whisper selecionado
    e' o maior que a VRAM detectada suporta - cabe, mas com pouca folga
    para outros programas (Chrome, jogos) consumindo VRAM ao mesmo tempo.

    Retorna None quando nao ha nada a avisar (modelo nao e' o maior
    suportado, ou VRAM desconhecida)."""
    if not modelos_suportados or modelo_selecionado != modelos_suportados[-1]:
        return None
    if vram_mb is None:
        return None
    footprint_gb = FOOTPRINT_MODELO_GB.get(modelo_selecionado, 2)
    vram_gb = round(vram_mb / 1024)
    return (
        f"Este modelo usa cerca de {footprint_gb}GB VRAM. Sua GPU tem "
        f"{vram_gb}GB total, o que pode causar erro se outros programas "
        "(Chrome, jogos) estiverem consumindo VRAM simultaneamente. "
        "Continue por sua conta e risco."
    )


def _contexto_ambiente_ajustes(config_dict):
    """Dados de ambiente especificos da tela de Ajustes (CLAUDE.md secao
    13): lista de modelos Whisper suportados pela GPU detectada (para
    filtrar o dropdown de WHISPER_MODEL) e o aviso amarelo de "modelo
    aperta a VRAM" para o modelo atualmente selecionado no formulario."""
    compat = AMBIENTE_ATUAL.get("compatibilidade") or {}
    modelos_whisper_suportados = compat.get("modelos_suportados") or ["small", "medium", "large-v3"]
    vram_mb = (AMBIENTE_ATUAL.get("gpu") or {}).get("vram_mb")
    modelo_selecionado = config_dict.get("WHISPER_MODEL")
    return {
        "modelos_whisper_suportados": modelos_whisper_suportados,
        "aviso_modelo_apertado": _aviso_modelo_apertado(
            modelos_whisper_suportados, modelo_selecionado, vram_mb
        ),
    }


def _calcular_banners():
    """Checagem de robustez no boot (CLAUDE.md secao 18.2): libs volateis
    desatualizadas (mais de robustez.JANELA_DIAS_AVISO dias desde o
    release da versao instalada) e presenca de ffmpeg no PATH. Roda uma
    vez por create_app() - nao a cada request - para nao bater na PyPI
    toda hora."""
    libs_desatualizadas = []
    for nome in robustez.libs_criticas():
        dias = robustez.idade_lib(nome)
        if dias is not None and dias > robustez.JANELA_DIAS_AVISO:
            libs_desatualizadas.append({"nome": nome, "dias": dias})
    return {
        "libs_desatualizadas": libs_desatualizadas,
        "ffmpeg_disponivel": robustez.ffmpeg_disponivel(),
    }


def _calcular_stats_home(projetos: list) -> dict:
    """KPIs do topo da tela inicial (home.html): total de projetos, quantos
    estao ativos (nem concluidos nem com erro), quantos concluiram no mes
    corrente e o custo estimado do mes corrente. Custo e' best-effort - soma
    custo_estimado_usd de job_metadata.json (Etapa 3) e plano_edicao.json
    (Etapa 5) quando existem; projeto sem esses arquivos so nao soma nada
    (nunca derruba a tela)."""
    total = len(projetos)
    ativos = sum(1 for p in projetos if p.get("status") not in (None, "concluido", "erro"))

    agora = datetime.now()
    concluidos_no_mes = 0
    custo_total_usd = 0.0
    projetos_dir = os.environ.get("PROJETOS_DIR", "")

    for projeto in projetos:
        criado_em = projeto.get("criado_em")
        no_mes_atual = bool(
            criado_em and criado_em.year == agora.year and criado_em.month == agora.month
        )
        if projeto.get("status") == "concluido" and no_mes_atual:
            concluidos_no_mes += 1

        if not no_mes_atual or not projetos_dir:
            continue
        pasta_projeto = Path(projetos_dir) / projeto["nome"]
        for nome_arquivo in ("job_metadata.json", "plano_edicao.json"):
            dados = _ler_json_seguro(pasta_projeto / nome_arquivo)
            if not dados:
                continue
            custo = dados.get("custo_estimado_usd")
            if custo is None:
                custo = (dados.get("metadata") or {}).get("custo_estimado_usd")
            if isinstance(custo, (int, float)):
                custo_total_usd += custo

    cotacao_usd_brl, _configurada = obter_cotacao_usd_brl()
    custo_total_brl = custo_total_usd * cotacao_usd_brl

    return {
        "total": total,
        "ativos": ativos,
        "concluidos_no_mes": concluidos_no_mes,
        "custo_total_usd": custo_total_usd,
        "custo_total_brl_formatado": f"R$ {custo_total_brl:.2f}".replace(".", ","),
    }


def _calcular_custo_detalhado_projeto(pasta_projeto: Path) -> dict:
    """Soma best-effort de todo custo estimado que ficou espalhado pelos
    artefatos de UM projeto (tela de conclusao, CLAUDE.md secao 5.9/5.85) -
    mesmo espirito best-effort de `_calcular_stats_home` (nunca derruba a
    tela por causa de um arquivo ausente ou corrompido).

    Fontes somadas (achado de sessao de refinamento: duas ficavam de fora
    ate' entao, subestimando o total real gasto no projeto):
    - job_metadata.json (Etapa 3, roteiro)
    - narracao_metadata.json (Etapa 4, TTS - 0.0 se foi upload)
    - clipes/sincronizacao_vision_log.json (Sincronizacao por IA/Vision -
      Feature A, estava de fora ate' esta correcao)
    - thumbnail/metadados.json.custo_usd_estimado (Grupo D/metadados +
      Grupo C/briefing exportavel - scripts/7_thumbnail.py so' passou a
      persistir esse campo nesta mesma correcao; projeto gerado ANTES
      dela simplesmente nao tem o campo, soma 0.0 pra ele)
    - thumbnail/headline_engine.json.custo_usd (Headline Engine)
    - thumbnail/fundo_gerado.jpg.custo.json (fundo por IA)
    - thumbnail/previews/composicao_ia.jpg.custo.json (composicao por IA)
    - qualquer outro *.custo.json dentro de thumbnail/ nao coberto pelos
      dois nomes conhecidos acima (rede de seguranca pra' nao perder
      custo se um caminho novo aparecer)

    NAO e' um total exato - "custo total" aqui e' sempre rotulado como
    estimativa, nunca como cobranca real. Retorna
    `{"total_usd": float, "itens": [{"rotulo", "usd"}, ...]}` - `itens`
    inclui so' fontes com valor > 0, na ordem em que o dinheiro e'
    gasto pelo pipeline (CLAUDE.md secao 5), pra' tela de conclusao
    detalhar por etapa ao expandir o card."""
    itens = []

    def _somar(rotulo, valor):
        if isinstance(valor, (int, float)) and valor > 0:
            itens.append({"rotulo": rotulo, "usd": round(float(valor), 4)})

    dados_roteiro = _ler_json_seguro(pasta_projeto / "job_metadata.json")
    if isinstance(dados_roteiro, dict):
        _somar("Roteiro (pesquisa + geração)", dados_roteiro.get("custo_estimado_usd"))

    dados_narracao = _ler_json_seguro(pasta_projeto / "narracao_metadata.json")
    if isinstance(dados_narracao, dict):
        _somar("Narração (TTS)", dados_narracao.get("custo_estimado_usd"))

    dados_sincronizacao = _ler_json_seguro(pasta_projeto / "clipes" / "sincronizacao_vision_log.json")
    if isinstance(dados_sincronizacao, dict):
        _somar("Sincronização de clipes por IA (Vision)", dados_sincronizacao.get("custo_usd_total"))

    pasta_thumbnail = pasta_projeto / "thumbnail"

    dados_metadados = _ler_json_seguro(pasta_thumbnail / "metadados.json")
    if isinstance(dados_metadados, dict):
        _somar("Metadados e briefing da thumbnail", dados_metadados.get("custo_usd_estimado"))

    dados_headline = _ler_json_seguro(pasta_thumbnail / "headline_engine.json")
    if isinstance(dados_headline, dict):
        _somar("Headline Engine", dados_headline.get("custo_usd"))

    caminhos_custo_conhecidos = {
        pasta_thumbnail / "fundo_gerado.jpg.custo.json": "Fundo da thumbnail gerado por IA",
        pasta_thumbnail / "previews" / "composicao_ia.jpg.custo.json": "Composição da thumbnail por IA",
    }
    for caminho_custo, rotulo in caminhos_custo_conhecidos.items():
        dados_custo = _ler_json_seguro(caminho_custo)
        if isinstance(dados_custo, dict):
            _somar(rotulo, dados_custo.get("custo_usd_estimado"))

    if pasta_thumbnail.is_dir():
        for caminho_custo in pasta_thumbnail.rglob("*.custo.json"):
            if caminho_custo in caminhos_custo_conhecidos:
                continue
            dados_custo = _ler_json_seguro(caminho_custo)
            if isinstance(dados_custo, dict):
                _somar(f"Thumbnail — {caminho_custo.name}", dados_custo.get("custo_usd_estimado"))

    total = round(sum(item["usd"] for item in itens), 4)
    return {"total_usd": total, "itens": itens}


def _processar_pares_link_marca(links_brutos: list, marcas_brutas: list) -> tuple:
    """Alinha arrays paralelos links[]/marcas_dagua[] vindos de um bloco do
    formulario de Novo projeto - descarta pares onde o link esta vazio
    (usuario adicionou uma linha e nao preencheu) sem desalinhar a marca
    d'agua dos links restantes.

    Usado tanto pelo bloco unico do modo unificado quanto pelos dois blocos
    (transcricao/visual) do modo separado - CLAUDE.md secao 5.7.1-bis.

    Retorna (links, marcas, mensagem_de_erro). `mensagem_de_erro` so' e'
    preenchida se os arrays tiverem tamanhos diferentes; nesse caso `links`
    e `marcas` voltam vazios."""
    if marcas_brutas and len(marcas_brutas) != len(links_brutos):
        return [], [], "Numero de marcas d'agua nao corresponde ao numero de links."

    links = []
    marcas = []
    pares_brutos = zip(links_brutos, marcas_brutas or ["nenhuma"] * len(links_brutos))
    for url_bruta, marca_bruta in pares_brutos:
        url_bruta = url_bruta.strip()
        if not url_bruta:
            continue
        links.append(url_bruta)
        marcas.append(marca_bruta.strip() or "nenhuma")
    return links, marcas, None


def _mesclar_fontes_separadas(links_transcricao, marcas_transcricao, links_visual, marcas_visual):
    """Deduplica URLs repetidas entre as listas de transcricao e visual do
    modo separado (CLAUDE.md secao 5.7.2) ANTES de qualquer arquivo do
    projeto ser escrito - achado real (nancyGuthrieProject03): a mesma URL
    colada nas duas listas baixava o mesmo video duas vezes
    (fonte01/fonte03), gastando tempo e disco a toa.

    Roda em cima das listas ja processadas por `_processar_pares_link_marca`
    (links validos/nao-vazios, marcas alinhadas). Uma URL que aparece nas
    duas listas (mesmo em formato diferente - youtu.be/<id> vs
    youtube.com/watch?v=<id>, reconhecido por
    `scripts.validators.chave_dedup_youtube`) vira UMA UNICA entrada com
    tipo_uso "ambos" - valor que scripts/2_transcrever.py e
    scripts/5_gerar_clipes.py ja tratam como "processar para os dois
    propositos", entao nenhum dos dois precisa de mudanca. Duplicata dentro
    da MESMA lista tambem e' deduplicada (mesmo tipo_uso, sem promover para
    "ambos").

    A numeracao de fonteNN continua 100% posicional
    (`_criar_pasta_projeto`/`scripts/1_baixar_videos.py` nao mudam) - so' a
    LISTA de entrada e' deduplicada antes de virar posicoes. Projetos ja
    existentes nunca sao tocados por isso: o dedup so' roda no momento de
    criar um projeto novo, nunca relendo/reescrevendo entrada/links.txt de
    um projeto ja criado.

    Marca d'agua da entrada mesclada: mantem a da primeira aparicao se ja
    for diferente de "nenhuma"; senao usa a da segunda aparicao (nunca
    perde uma marca d'agua real por causa da ordem de mescla).

    Retorna (links, marcas, tipo_uso_por_link) - mesma forma de listas
    paralelas que o codigo anterior produzia."""
    entradas = []
    indice_por_chave = {}

    def _adicionar(url, marca, tipo):
        chave = chave_dedup_youtube(url)
        if chave in indice_por_chave:
            entrada = entradas[indice_por_chave[chave]]
            if entrada["tipo_uso"] != tipo:
                entrada["tipo_uso"] = "ambos"
            if entrada["marca"] == "nenhuma" and marca != "nenhuma":
                entrada["marca"] = marca
            return
        indice_por_chave[chave] = len(entradas)
        entradas.append({"url": url, "marca": marca, "tipo_uso": tipo})

    for url, marca in zip(links_transcricao, marcas_transcricao):
        _adicionar(url, marca, "transcricao")
    for url, marca in zip(links_visual, marcas_visual):
        _adicionar(url, marca, "visual")

    links = [e["url"] for e in entradas]
    marcas = [e["marca"] for e in entradas]
    tipo_uso = [e["tipo_uso"] for e in entradas]
    return links, marcas, tipo_uso


def _avisar_se_disco_pouco_livre(caminho: Path):
    """Loga um warning (nunca bloqueia) se o disco onde `caminho` mora tiver
    menos que LIMITE_AVISO_DISCO_LIVRE_GB de espaco livre - CLAUDE.md secao
    18 (uma checagem de robustez nunca pode travar o fluxo do usuario). Se o
    disco encher de verdade, a etapa de ffmpeg que falhar categoriza o erro
    como "disco_cheio" (scripts/5_gerar_clipes.py) - aqui e' so' um aviso
    antecipado."""
    try:
        livre_bytes = shutil.disk_usage(caminho).free
    except OSError:
        return
    livre_gb = livre_bytes / (1024**3)
    if livre_gb < LIMITE_AVISO_DISCO_LIVRE_GB:
        logging.getLogger(__name__).warning(
            "Disco com pouco espaco livre (%.1f GB) ao salvar upload em %s.",
            livre_gb,
            caminho,
        )


def _validar_uploads(arquivos: list) -> tuple:
    """Valida arquivos enviados via uploads[] (feature de fontes separadas -
    CLAUDE.md secao 5.7.1-bis) SEM escrever nada em disco: extensao
    suportada (scripts/validators.py:classificar_extensao_upload - nunca
    confia no `accept=` do <input>, que e' so' dica de UX) e tamanho
    (TAMANHO_MAX_UPLOAD_BYTES, 500MB por arquivo).

    Um unico arquivo invalido rejeita a lista inteira (mesmo padrao das
    outras validacoes desta rota - nunca cria projeto parcialmente
    configurado). Retorna (lista_de_tuplas_validadas, mensagem_de_erro) onde
    cada tupla e' (FileStorage, nome_seguro, tipo, nome_original)."""
    validados = []
    for arquivo in arquivos:
        if not arquivo or not arquivo.filename:
            continue
        nome_original = arquivo.filename
        nome_seguro = secure_filename(nome_original)
        if not nome_seguro:
            return [], f"Nome de arquivo de upload invalido: '{nome_original}'."

        tipo = classificar_extensao_upload(nome_seguro)
        if tipo is None:
            return [], f"Extensao nao suportada em '{nome_original}'."

        arquivo.seek(0, os.SEEK_END)
        tamanho_bytes = arquivo.tell()
        arquivo.seek(0)
        if tamanho_bytes > TAMANHO_MAX_UPLOAD_BYTES:
            limite_mb = TAMANHO_MAX_UPLOAD_BYTES // (1024 * 1024)
            return [], f"'{nome_original}' excede o limite de {limite_mb}MB por arquivo."

        validados.append((arquivo, nome_seguro, tipo, nome_original))
    return validados, None


def _salvar_uploads(pasta_projeto: Path, uploads_validados: list, indice_inicial: int) -> list:
    """Salva uploads ja validados (`_validar_uploads`) direto em
    fontes/fonteNN.<ext>, continuando a numeracao sequencial a partir de
    `indice_inicial` (1 + quantidade de links do projeto - mesma convencao
    de numeracao que scripts/1_baixar_videos.py usa pros links do YouTube).
    Evita qualquer logica de resolucao de caminho nova em scripts/5_gerar_clipes.py:
    a fonte de upload fica indistinguivel de uma fonte baixada, em termos de
    onde o arquivo mora.

    Retorna a lista de entradas prontas para entrada/fontes_upload.json
    (consumida por scripts/1_baixar_videos.py)."""
    pasta_fontes = pasta_projeto / "fontes"
    pasta_fontes.mkdir(parents=True, exist_ok=True)
    if uploads_validados:
        _avisar_se_disco_pouco_livre(pasta_fontes)

    entradas = []
    for offset, (arquivo, nome_seguro, tipo, nome_original) in enumerate(uploads_validados):
        indice = indice_inicial + offset
        extensao = Path(nome_seguro).suffix.lower()
        id_fonte = f"fonte{indice:02d}"
        nome_arquivo_final = f"{id_fonte}{extensao}"
        arquivo.save(str(pasta_fontes / nome_arquivo_final))
        entradas.append(
            {"id": id_fonte, "arquivo": nome_arquivo_final, "tipo": tipo, "titulo": nome_original}
        )
    return entradas


def _validar_uploads_musica(arquivos: list) -> tuple:
    """Valida arquivos enviados via musicas[] (formulario de Novo projeto,
    CLAUDE.md secao 5.8 - musica de fundo) SEM escrever nada em disco:
    extensao suportada (.mp3/.wav/.m4a) e tamanho (TAMANHO_MAX_UPLOAD_BYTES,
    mesmo teto por arquivo que os uploads de fonte visual). Arquivo com
    extensao invalida e' ignorado silenciosamente (nao rejeita a lista
    inteira) - musica de fundo e' um extra opcional, nao vale travar a
    criacao do projeto por um arquivo errado quando outros sao validos.

    Retorna (lista_de_tuplas_validadas, mensagem_de_erro) onde cada tupla e'
    (FileStorage, nome_seguro). mensagem_de_erro so' e' preenchida por
    arquivo grande demais - isso sim rejeita a lista inteira (evita upload
    parcial silencioso de uma playlist)."""
    validados = []
    for arquivo in arquivos:
        if not arquivo or not arquivo.filename:
            continue
        nome_original = arquivo.filename
        if not validar_extensao_musica(nome_original):
            continue
        nome_seguro = secure_filename(nome_original)
        if not nome_seguro:
            continue

        arquivo.seek(0, os.SEEK_END)
        tamanho_bytes = arquivo.tell()
        arquivo.seek(0)
        if tamanho_bytes > TAMANHO_MAX_UPLOAD_BYTES:
            limite_mb = TAMANHO_MAX_UPLOAD_BYTES // (1024 * 1024)
            return [], f"'{nome_original}' excede o limite de {limite_mb}MB por arquivo."

        validados.append((arquivo, nome_seguro))
    return validados, None


def _salvar_musicas(pasta_projeto: Path, musicas_validadas: list) -> None:
    """Salva uploads ja validados (`_validar_uploads_musica`) em
    entrada/musica_fundo/<nome_seguro> - mesma pasta que
    scripts/6_montar_video.py ja sabe ler (ordem alfabetica de nome de
    arquivo define a ordem da playlist, CLAUDE.md secao 5.8)."""
    pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
    pasta_musicas.mkdir(parents=True, exist_ok=True)
    if musicas_validadas:
        _avisar_se_disco_pouco_livre(pasta_musicas)
    for arquivo, nome_seguro in musicas_validadas:
        arquivo.save(str(pasta_musicas / nome_seguro))


# ---------------------------------------------------------------------------
# Tipo de projeto "videos_pre_gerados" (CLAUDE.md secao 3, "Vídeos
# pré-gerados") - caminho paralelo e' mais simples que a pipeline completa:
# usuario ja tem os clipes finais prontos (ex: exportados do DarkPlanner
# Flow/Veo3, ja com audio embutido - narracao/efeitos/musica), so precisa
# concatenar. Nao ha download, transcricao, roteiro, TTS nem geracao de
# clipe algum - so upload direto + Etapa 6 (montagem, com um caminho
# dedicado dentro dela - ver scripts/6_montar_video.py).
# ---------------------------------------------------------------------------


def _validar_uploads_videos_pre_gerados(arquivos: list) -> tuple:
    """Valida arquivos enviados via videos_pre_gerados[] (formulario de
    Novo projeto): extensao suportada (mesma restricao tecnica de
    classificar_extensao_upload - so' "video", imagem nao faz sentido aqui,
    isto nao e' Ken Burns) e tamanho TOTAL somado
    (TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES, 2GB - distinto do teto POR
    ARQUIVO usado pelas fontes visuais da pipeline completa, porque aqui o
    usuario tipicamente envia varios clipes de uma vez).

    Retorna (lista_ordenada_de_tuplas, mensagem_de_erro) onde cada tupla e'
    (FileStorage, nome_seguro, nome_original), ja ORDENADA pelo prefixo
    numerico do nome original (`prefixo_numerico_arquivo` - CLAUDE.md,
    "Sort natural por prefixo numerico"). Um unico arquivo invalido (ou o
    total excedendo 2GB) rejeita a lista inteira - nunca cria projeto
    parcialmente configurado."""
    candidatos = []
    tamanho_total_bytes = 0
    for arquivo in arquivos:
        if not arquivo or not arquivo.filename:
            continue
        nome_original = arquivo.filename
        nome_seguro = secure_filename(nome_original)
        if not nome_seguro:
            return [], f"Nome de arquivo invalido: '{nome_original}'."

        tipo = classificar_extensao_upload(nome_seguro)
        if tipo != "video":
            return [], f"'{nome_original}' nao e' um formato de video suportado (.mp4/.mov/.webm)."

        arquivo.seek(0, os.SEEK_END)
        tamanho_bytes = arquivo.tell()
        arquivo.seek(0)
        tamanho_total_bytes += tamanho_bytes

        candidatos.append((arquivo, nome_seguro, nome_original))

    if tamanho_total_bytes > TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES:
        limite_gb = TAMANHO_MAX_TOTAL_VIDEOS_PRE_GERADOS_BYTES / (1024 * 1024 * 1024)
        total_mb = tamanho_total_bytes / (1024 * 1024)
        return [], f"Total de {total_mb:.0f}MB excede o limite de {limite_gb:.0f}GB."

    candidatos.sort(key=lambda item: prefixo_numerico_arquivo(item[2]))
    return candidatos, None


# ---------------------------------------------------------------------------
# Intro/ending anexados ao video final (sessao "Intro e ending anexados ao
# video final", GRUPO A) - upload opcional no formulario de Novo projeto,
# compartilhado entre pipeline completa e "videos_pre_gerados" (CLAUDE.md
# secao 3, disponivel em todos os tipos de projeto).
# ---------------------------------------------------------------------------


def _validar_e_preparar_upload_intro_ending(arquivo, papel: str) -> tuple:
    """Valida um upload de intro/ending (`papel` = "intro" ou "ending",
    ambos opcionais): extensao de video suportada, tamanho, e legibilidade
    real via ffprobe (GRUPO A - "validar que e' video legivel... e avisar
    cedo, nao descobrir isso so' na montagem"). Retorna
    (caminho_temporario_ou_None, mensagem_erro_ou_None) - `arquivo` ausente
    (campo opcional nao preenchido) retorna (None, None), nunca erro.

    Salva num arquivo TEMPORARIO fora de qualquer projeto - nenhum projeto
    existe ainda neste ponto da validacao (CLAUDE.md - `pasta_projeto` so'
    e' criada depois que toda a validacao passa) e o ffprobe precisa de um
    caminho real em disco, nao bytes em memoria. O CHAMADOR e' responsavel
    por mover o arquivo temporario pra dentro do projeto em caso de
    sucesso (`_criar_pasta_projeto`/`_criar_pasta_projeto_videos_pre_gerados`)
    ou apagar em caso de erro/desistencia (`_descartar_temp_intro_ending`)."""
    if arquivo is None or not arquivo.filename:
        return None, None

    if not validar_extensao_intro_ending(arquivo.filename):
        return None, f"Arquivo de {papel} precisa ser um video .mp4/.mov/.webm."

    arquivo.seek(0, os.SEEK_END)
    tamanho_bytes = arquivo.tell()
    arquivo.seek(0)
    if tamanho_bytes > TAMANHO_MAX_INTRO_ENDING_BYTES:
        limite_mb = TAMANHO_MAX_INTRO_ENDING_BYTES // (1024 * 1024)
        return None, f"Arquivo de {papel} excede o limite de {limite_mb}MB."

    extensao = Path(secure_filename(arquivo.filename) or arquivo.filename).suffix.lower()
    descritor, caminho_temp_str = tempfile.mkstemp(suffix=extensao, prefix=f"broll_{papel}_")
    os.close(descritor)
    caminho_temp = Path(caminho_temp_str)
    arquivo.save(str(caminho_temp))
    arquivo.seek(0)

    legivel, _duracao_s, mensagem_erro = validators.validar_video_legivel_ffprobe(caminho_temp)
    if not legivel:
        caminho_temp.unlink(missing_ok=True)
        return None, f"Arquivo de {papel} invalido: {mensagem_erro}"

    return caminho_temp, None


def _descartar_temp_intro_ending(caminho_temp) -> None:
    """Remove um arquivo temporario de intro/ending nao aproveitado (POST
    invalido por outro motivo, ou desistencia). Idempotente - `caminho_temp`
    None (campo nao preenchido, ou ja consumido/movido) e' um no-op seguro,
    nunca levanta excecao."""
    if caminho_temp is None:
        return
    try:
        Path(caminho_temp).unlink(missing_ok=True)
    except OSError:
        pass


def _salvar_intro_ending(pasta_projeto: Path, caminho_temp_intro, caminho_temp_ending) -> None:
    """Move os arquivos temporarios ja validados
    (`_validar_e_preparar_upload_intro_ending`) para dentro do projeto -
    entrada/intro.<ext>/entrada/ending.<ext> (mesma extensao do upload
    original, preservada no nome do arquivo temporario). Ambos opcionais -
    `None` e' um no-op silencioso para o que nao foi enviado."""
    for caminho_temp, papel in ((caminho_temp_intro, "intro"), (caminho_temp_ending, "ending")):
        if caminho_temp is None:
            continue
        extensao = Path(caminho_temp).suffix.lower()
        shutil.move(str(caminho_temp), str(pasta_projeto / "entrada" / f"{papel}{extensao}"))


def _descobrir_intro_ending_info(pasta_projeto: Path) -> dict:
    """Descobre se o projeto tem intro/ending configurados
    (entrada/intro.<ext>/entrada/ending.<ext>) - so' para exibicao na tela
    de reorganizacao de clipes (blocos fixos nas pontas da timeline, secao
    "Intro e ending anexados ao video final", GRUPO F). Retorna
    {"intro": info_ou_None, "ending": info_ou_None}, `info` =
    {"nome_arquivo", "duracao_formatada"}. Nunca levanta excecao; ausencia
    de um ou dos dois e' o caso comum (ambos opcionais)."""
    pasta_entrada = pasta_projeto / "entrada"
    resultado = {}
    for papel in ("intro", "ending"):
        encontrado = None
        for extensao in validators.EXTENSOES_INTRO_ENDING_VALIDAS:
            candidato = pasta_entrada / f"{papel}{extensao}"
            if candidato.exists():
                encontrado = candidato
                break
        if encontrado is None:
            resultado[papel] = None
            continue
        duracao_s = _obter_duracao_video_ffprobe(encontrado)
        resultado[papel] = {
            "nome_arquivo": encontrado.name,
            "duracao_formatada": _formatar_duracao_s(duracao_s) if duracao_s else None,
        }
    return resultado


def _obter_duracao_video_ffprobe(caminho: Path) -> float:
    """Duracao real do arquivo de video via ffprobe. Usada so' para
    preencher `duracao_s` em clipes/indice.json (informativo/planejamento -
    o concat via demuxer `-c copy` nao depende deste valor estar certo);
    qualquer falha (ffprobe ausente, saida nao numerica) vira 0.0 em vez de
    derrubar a criacao do projeto - a montagem final nao usa este campo
    para cortar nada."""
    try:
        resultado = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(caminho),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return round(float(resultado.stdout.strip()), 3)
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


def _salvar_videos_pre_gerados(pasta_projeto: Path, uploads_ordenados: list) -> list:
    """Salva os videos ja validados/ordenados (`_validar_uploads_videos_pre_gerados`)
    em clipes/clipe_NNNN.mp4 (numeracao sequencial na ordem final da
    timeline - mesma convencao de nome que scripts/5_gerar_clipes.py usa
    para a pipeline completa) e retorna as entradas prontas para
    clipes/indice.json."""
    pasta_clipes = pasta_projeto / "clipes"
    pasta_clipes.mkdir(parents=True, exist_ok=True)
    _avisar_se_disco_pouco_livre(pasta_clipes)

    indice_clipes = []
    for posicao, (arquivo, nome_seguro, nome_original) in enumerate(uploads_ordenados):
        clipe_id = f"clipe_{posicao:04d}"
        extensao = Path(nome_seguro).suffix.lower()
        nome_arquivo_final = f"{clipe_id}{extensao}"
        caminho_destino = pasta_clipes / nome_arquivo_final
        arquivo.save(str(caminho_destino))
        indice_clipes.append(
            {
                "clipe_id": clipe_id,
                "arquivo": nome_arquivo_final,
                "arquivo_original": nome_original,
                "duracao_s": _obter_duracao_video_ffprobe(caminho_destino),
            }
        )
    return indice_clipes


def _criar_pasta_projeto_videos_pre_gerados(
    pasta_projeto: Path,
    perfil: str,
    indice_clipes: list,
    legendas_queimadas: bool,
    arquivo_srt=None,
    marca_dagua_projeto: str = ORIGEM_MARCA_DAGUA_PROJETO_PADRAO,
    arquivo_marca_dagua=None,
    caminho_temp_intro=None,
    caminho_temp_ending=None,
):
    """Cria a estrutura de marcadores do tipo de projeto "videos_pre_gerados"
    (CLAUDE.md secao 3): entrada/perfil.txt (mesmo campo da pipeline
    completa, so' pra badge/consistencia de tela), entrada/tipo_projeto.txt
    = "videos_pre_gerados" (lido por `_ler_tipo_projeto` e por
    scripts/6_montar_video.py - mesma convencao de
    entrada/origem_roteiro.txt), clipes/indice.json (ja na ordem final,
    consumido por scripts/6_montar_video.py), entrada/configuracao_video.json
    (`legendas_queimadas` + `marca_dagua_projeto` - sem musica, sem
    grayscale, sem reorganizacao manual: usuario confirmou que os clipes ja
    vem com audio embutido, musica por cima competiria com ele), e job.json
    inicial. `arquivo_marca_dagua` (FileStorage), se informado, e' salvo em
    entrada/marca_dagua_canal.png (secao "Marca d'agua do canal aplicada ao
    video final" - GRUPO D, este tipo de projeto usa o MESMO campo/arquivo
    que a pipeline completa). `caminho_temp_intro`/`caminho_temp_ending`
    (Path, ja' validados por `_validar_e_preparar_upload_intro_ending`), se
    informados, sao movidos para entrada/intro.<ext>/entrada/ending.<ext>
    (secao "Intro e ending anexados ao video final" - GRUPO A/G, este tipo
    de projeto usa o MESMO campo que a pipeline completa)."""
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "perfil.txt").write_text(perfil, encoding="utf-8")
    (pasta_projeto / "entrada" / "tipo_projeto.txt").write_text("videos_pre_gerados", encoding="utf-8")

    if marca_dagua_projeto == "outra" and arquivo_marca_dagua is not None and arquivo_marca_dagua.filename:
        # `seek(0)`: o conteudo ja foi lido pra validacao (_validar_png_marca_dagua)
        # antes de chegar aqui - sem isso `.save()` gravaria um arquivo vazio.
        arquivo_marca_dagua.seek(0)
        arquivo_marca_dagua.save(str(pasta_projeto / "entrada" / "marca_dagua_canal.png"))

    _salvar_intro_ending(pasta_projeto, caminho_temp_intro, caminho_temp_ending)

    (pasta_projeto / "clipes").mkdir(parents=True, exist_ok=True)
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "tipo_projeto": "videos_pre_gerados",
                    "total_clipes": len(indice_clipes),
                    "data_geracao": datetime.now(timezone.utc).isoformat(),
                },
                "clipes": indice_clipes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(
            {
                "legendas_queimadas": legendas_queimadas,
                "com_musica_fundo": False,
                "marca_dagua_projeto": marca_dagua_projeto,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if arquivo_srt is not None and arquivo_srt.filename:
        arquivo_srt.save(str(pasta_projeto / "entrada" / "legenda_importada.srt"))

    job_inicial = {
        "projeto_id": pasta_projeto.name,
        "nome": pasta_projeto.name,
        "perfil": perfil,
        "tipo_projeto": "videos_pre_gerados",
        "idioma": None,
        "estrategia_corte": None,
        "status": "pendente",
        "etapa_atual": "montagem",
        "proxima_etapa": None,
        "data_criacao": datetime.now().isoformat(),
    }
    (pasta_projeto / "job.json").write_text(
        json.dumps(job_inicial, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _form_padrao_novo_projeto(
    nome: str,
    perfil: str,
    tipo_projeto: str,
    com_legenda_srt: bool = False,
    marca_dagua_projeto: str = ORIGEM_MARCA_DAGUA_PROJETO_PADRAO,
) -> dict:
    """Contexto `form` completo para re-renderizar novo_projeto.html num
    erro do caminho "videos_pre_gerados" - o template acessa varios campos
    do formulario da pipeline completa (form.modo_fontes, form.pares, etc,
    mesmo fora deste caminho) incondicionalmente via Jinja, entao precisa de
    TODOS eles presentes (com defaults neutros) pra nao levantar
    `UndefinedError` no filtro `| int` de palavras_alvo."""
    return {
        "nome": nome,
        "perfil": perfil,
        "tipo_projeto": tipo_projeto,
        "com_legenda_srt": com_legenda_srt,
        "modo_fontes": "unificado",
        "origem_roteiro": "ia",
        "pares": [],
        "pares_transcricao": [],
        "pares_visual": [],
        "legendas_queimadas": False,
        "sincronizacao_ia_ativa": False,
        "sincronizacao_duracao_s": 600,
        "reorganizacao_manual_ativa": False,
        "palavras_alvo": 4000,
        "grayscale": False,
        "gerar_thumbnail": True,
        "marca_dagua_projeto": marca_dagua_projeto,
    }


def _tratar_novo_projeto_videos_pre_gerados(nome: str, perfil: str, perfis_disponiveis: list):
    """Trata o POST /novo quando tipo_projeto=videos_pre_gerados - chamada
    direto pela rota /novo (server.py) antes de qualquer validacao de
    links/roteiro/marca d'agua, que nao se aplicam aqui. Valida nome/perfil/
    uploads/SRT, cria a estrutura de projeto
    (`_salvar_videos_pre_gerados` + `_criar_pasta_projeto_videos_pre_gerados`)
    e dispara a Etapa 6 direto (`_disparar_etapa6`), sem passar por nenhuma
    das Etapas 1-5."""
    erro = None
    nomes_perfis_validos = {p["nome"] for p in perfis_disponiveis}

    valido_nome, resultado_nome = validar_nome_projeto(nome)
    if not valido_nome:
        erro = {"mensagem": resultado_nome, "tipo": "nome_invalido", "campos": ["nome"]}
    elif not perfil:
        erro = {
            "mensagem": "Selecione o tipo de conteudo do video.",
            "tipo": "perfil_ausente",
            "campos": ["perfil"],
        }
    elif perfil not in nomes_perfis_validos:
        # Protecao contra manipulacao de request - o <select> so oferece
        # perfis validos.
        erro = {
            "mensagem": f"O tipo de conteudo '{perfil}' nao e' valido.",
            "tipo": "perfil_invalido",
            "campos": ["perfil"],
        }

    uploads_ordenados = []
    if not erro:
        arquivos = request.files.getlist("videos_pre_gerados[]")
        if not any(arquivo and arquivo.filename for arquivo in arquivos):
            erro = {
                "mensagem": "Selecione ao menos 1 arquivo de video.",
                "tipo": "videos_pre_gerados_vazio",
                "campos": ["videos_pre_gerados"],
            }
        else:
            uploads_ordenados, erro_upload = _validar_uploads_videos_pre_gerados(arquivos)
            if erro_upload:
                erro = {"mensagem": erro_upload, "tipo": "upload_invalido", "campos": ["videos_pre_gerados"]}

    legendas_queimadas = request.form.get("com_legenda_srt") == "on"
    arquivo_srt = request.files.get("arquivo_srt")
    if not erro and legendas_queimadas and (not arquivo_srt or not arquivo_srt.filename):
        erro = {
            "mensagem": "Envie um arquivo .srt para a legenda queimada, ou desmarque a opcao.",
            "tipo": "srt_ausente",
            "campos": ["arquivo_srt"],
        }

    marca_dagua_projeto = (request.form.get("marca_dagua_projeto") or ORIGEM_MARCA_DAGUA_PROJETO_PADRAO).strip()
    if not erro and not validar_origem_marca_dagua_projeto(marca_dagua_projeto):
        # Protecao contra manipulacao de request - o <input type="radio">
        # do formulario so oferece "canal"/"outra"/"nenhuma".
        erro = {
            "mensagem": f"Origem de marca d'agua '{marca_dagua_projeto}' nao e' valida.",
            "tipo": "marca_dagua_projeto_invalida",
            "campos": [],
        }
    arquivo_marca_dagua = request.files.get("marca_dagua_arquivo")
    if not erro and marca_dagua_projeto == "outra":
        if not arquivo_marca_dagua or not arquivo_marca_dagua.filename:
            erro = {
                "mensagem": "Envie um arquivo PNG para a marca d'agua, ou escolha outra opcao.",
                "tipo": "marca_dagua_arquivo_ausente",
                "campos": ["marca_dagua_arquivo"],
            }
        elif Path(arquivo_marca_dagua.filename).suffix.lower() != ".png":
            erro = {
                "mensagem": "A marca d'agua precisa ser um arquivo PNG.",
                "tipo": "marca_dagua_extensao_invalida",
                "campos": ["marca_dagua_arquivo"],
            }
        else:
            conteudo_marca = arquivo_marca_dagua.read()
            arquivo_marca_dagua.seek(0)
            valido_png, _tem_alfa, mensagem_png = _validar_png_marca_dagua(conteudo_marca)
            if not valido_png:
                erro = {"mensagem": mensagem_png, "tipo": "marca_dagua_png_invalido", "campos": ["marca_dagua_arquivo"]}

    # Intro/ending anexados ao video final (secao "Intro e ending anexados
    # ao video final", GRUPO A/G) - campo compartilhado com a pipeline
    # completa, disponivel tambem em "videos pre-gerados" (CLAUDE.md secao
    # 3). Salva em arquivo TEMPORARIO (nenhum projeto existe ainda neste
    # ponto) para validar via ffprobe - `_criar_pasta_projeto_videos_pre_gerados`
    # move pra dentro do projeto so' depois que TODA a validacao passa.
    caminho_temp_intro, caminho_temp_ending = None, None
    if not erro:
        caminho_temp_intro, erro_intro_msg = _validar_e_preparar_upload_intro_ending(
            request.files.get("intro_arquivo"), "intro"
        )
        if erro_intro_msg:
            erro = {"mensagem": erro_intro_msg, "tipo": "intro_invalido", "campos": ["intro_arquivo"]}
    if not erro:
        caminho_temp_ending, erro_ending_msg = _validar_e_preparar_upload_intro_ending(
            request.files.get("ending_arquivo"), "ending"
        )
        if erro_ending_msg:
            erro = {"mensagem": erro_ending_msg, "tipo": "ending_invalido", "campos": ["ending_arquivo"]}

    pasta_projeto = None
    if not erro:
        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        if not projetos_dir:
            erro = {
                "mensagem": "Configure PROJETOS_DIR em Ajustes antes de criar um projeto.",
                "tipo": "projetos_dir_ausente",
                "campos": [],
            }
        else:
            pasta_projeto = Path(projetos_dir) / nome
            if pasta_projeto.exists():
                erro = {
                    "mensagem": f"Ja existe um projeto chamado '{nome}'.",
                    "tipo": "nome_duplicado",
                    "campos": ["nome"],
                }

    if erro:
        _descartar_temp_intro_ending(caminho_temp_intro)
        _descartar_temp_intro_ending(caminho_temp_ending)
        status_code = 400 if erro["tipo"] in ("perfil_invalido", "marca_dagua_projeto_invalida") else 200
        return (
            render_template(
                "novo_projeto.html",
                idiomas=IDIOMAS_SUPORTADOS,
                perfis=perfis_disponiveis,
                opcoes_marca_dagua=OPCOES_MARCA_DAGUA,
                erro=erro,
                form=_form_padrao_novo_projeto(nome, perfil, "videos_pre_gerados", legendas_queimadas, marca_dagua_projeto),
                gerar_thumbnail_padrao_ajustes=_gerar_thumbnail_padrao_ajustes(),
                tem_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
                tem_marca_dagua_canal_global=ARQUIVO_MARCA_DAGUA_GLOBAL.exists(),
            ),
            status_code,
        )

    indice_clipes = _salvar_videos_pre_gerados(pasta_projeto, uploads_ordenados)
    _criar_pasta_projeto_videos_pre_gerados(
        pasta_projeto, perfil, indice_clipes, legendas_queimadas, arquivo_srt,
        marca_dagua_projeto, arquivo_marca_dagua,
        caminho_temp_intro, caminho_temp_ending,
    )

    _disparar_etapa6(nome, pasta_projeto)
    return redirect(url_for("status", projeto_id=nome))


def _criar_pasta_projeto(
    pasta_projeto: Path,
    links: list,
    idioma: str,
    estrategia_corte: str,
    perfil: str,
    marcas_dagua: list | None = None,
    configuracao_video: dict | None = None,
    tipo_uso_por_link: list | None = None,
    fontes_upload: list | None = None,
    origem_roteiro: str = "ia",
    roteiro_texto: str | None = None,
    arquivo_marca_dagua=None,
    caminho_temp_intro=None,
    caminho_temp_ending=None,
):
    """Cria a estrutura de marcadores da Etapa 1 (CLAUDE.md secoes 5.1 e 6):
    entrada/links.txt com os links colados no formulario, entrada/perfil.txt
    com o perfil de conteudo escolhido (CLAUDE.md secao 3.1 - obrigatorio),
    entrada/marcas_dagua.json com a posicao de marca d'agua escolhida por
    link (CLAUDE.md secao 5.7.1 - mapa fonteNN -> posicao, mesma numeracao
    sequencial que scripts/1_baixar_videos.py usa para nomear fontes/fonteNN.mp4),
    entrada/fontes_tipo_uso.json com o tipo_uso de cada fonte (feature de
    fontes separadas, CLAUDE.md secao 5.7.1-bis - mapa fonteNN -> "ambos"/
    "transcricao"/"visual", lido por scripts/2_transcrever.py e
    scripts/5_gerar_clipes.py), entrada/fontes_upload.json com as fontes
    visuais enviadas por upload (se houver - consumido por
    scripts/1_baixar_videos.py), entrada/configuracao_video.json com as
    opcoes da Etapa 6 (legendas queimadas, musica de fundo, marca d'agua
    do canal - consumido por scripts/6_montar_video.py), e job.json
    inicial com o estado antes de qualquer etapa rodar. `arquivo_marca_dagua`
    (FileStorage), se `configuracao_video["marca_dagua_projeto"] == "outra"`,
    e' salvo em entrada/marca_dagua_canal.png (secao "Marca d'agua do canal
    aplicada ao video final").

    `marcas_dagua` e `tipo_uso_por_link`, se informados, sao listas na MESMA
    ORDEM de `links` (marcas_dagua[i]/tipo_uso_por_link[i] correspondem a
    links[i]) - None ou lista vazia grava "nenhuma"/"ambos" para todo link
    (modo unificado - retrocompatibilidade total com projetos criados antes
    da feature de fontes separadas)."""
    (pasta_projeto / "entrada").mkdir(parents=True)
    (pasta_projeto / "entrada" / "links.txt").write_text(
        "\n".join(links) + "\n", encoding="utf-8"
    )
    (pasta_projeto / "entrada" / "perfil.txt").write_text(perfil, encoding="utf-8")

    if (configuracao_video or {}).get("marca_dagua_projeto") == "outra" and arquivo_marca_dagua is not None and arquivo_marca_dagua.filename:
        # `seek(0)`: o conteudo ja foi lido pra validacao (_validar_png_marca_dagua)
        # antes de chegar aqui - sem isso `.save()` gravaria um arquivo vazio.
        arquivo_marca_dagua.seek(0)
        arquivo_marca_dagua.save(str(pasta_projeto / "entrada" / "marca_dagua_canal.png"))

    _salvar_intro_ending(pasta_projeto, caminho_temp_intro, caminho_temp_ending)

    mapa_marcas_dagua = {
        f"fonte{indice:02d}": (marcas_dagua[indice - 1] if marcas_dagua else "nenhuma")
        for indice in range(1, len(links) + 1)
    }
    (pasta_projeto / "entrada" / "marcas_dagua.json").write_text(
        json.dumps(mapa_marcas_dagua, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    mapa_tipo_uso = {
        f"fonte{indice:02d}": (tipo_uso_por_link[indice - 1] if tipo_uso_por_link else "ambos")
        for indice in range(1, len(links) + 1)
    }
    for entrada_upload in fontes_upload or []:
        mapa_tipo_uso[entrada_upload["id"]] = "visual"
    (pasta_projeto / "entrada" / "fontes_tipo_uso.json").write_text(
        json.dumps(mapa_tipo_uso, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if fontes_upload:
        (pasta_projeto / "entrada" / "fontes_upload.json").write_text(
            json.dumps(fontes_upload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (pasta_projeto / "entrada" / "origem_roteiro.txt").write_text(origem_roteiro, encoding="utf-8")

    if origem_roteiro == "upload" and roteiro_texto is not None:
        # Roteiro pronto fornecido pelo usuario (feature de upload de
        # roteiro) - grava direto em roteiro.md, no mesmo lugar/formato que
        # scripts/3_gerar_roteiro.py grava quando gera via IA, para que
        # /revisar_roteiro nao precise saber a origem pra exibir o texto.
        # Etapas 2 (transcricao) e 3 (geracao) nunca rodam para este projeto
        # (ver server.py:_encadear_etapa2) - nao ha nada a transcrever para
        # alimentar uma geracao que nao vai acontecer.
        (pasta_projeto / "roteiro.md").write_text(roteiro_texto, encoding="utf-8")
        (pasta_projeto / "job_metadata.json").write_text(
            json.dumps(
                {"origem_roteiro": "upload", "caracteres": len(roteiro_texto)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
        json.dumps(
            configuracao_video or {"legendas_queimadas": False, "com_musica_fundo": False},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    job_inicial = {
        "projeto_id": pasta_projeto.name,
        "nome": pasta_projeto.name,
        "perfil": perfil,
        "idioma": idioma or None,
        "estrategia_corte": estrategia_corte or None,
        "status": "pendente",
        "etapa_atual": "download",
        "proxima_etapa": None,
        "data_criacao": datetime.now().isoformat(),
    }
    (pasta_projeto / "job.json").write_text(
        json.dumps(job_inicial, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _persistir_job(pasta_projeto: Path, **campos):
    """Le o job.json existente (se houver), aplica `campos` por cima e grava
    de volta no disco - usado nas transicoes de estado do pipeline (Sessao
    4: inicio/conclusao/erro da etapa), nunca a cada `@PROGRESSO` (custoso
    em I/O). Preserva campos gravados em transicoes anteriores (ex: nome,
    idioma, data_criacao) que nao estao em `campos`."""
    caminho = pasta_projeto / "job.json"
    atual = {}
    if caminho.exists():
        try:
            atual = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            atual = {}
    atual.update(campos)
    caminho.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    return atual


def _ler_job_json(pasta_projeto):
    """Le job.json do disco. Retorna None se a pasta nao existe, o arquivo
    nao existe, ou o conteudo esta corrompido - a tela de status trata None
    como "sem dados persistidos", nunca crasha (Sessao 4).

    Aplica STATUS_MIGRATION so' em memoria (nunca reescreve o disco) -
    projetos criados antes da refatoracao do pipeline (CLAUDE.md secao
    5.7/5.8) podem ter um status que nao existe mais."""
    if pasta_projeto is None:
        return None
    caminho = pasta_projeto / "job.json"
    if not caminho.exists():
        return None
    try:
        job = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    status_migrado = STATUS_MIGRATION.get(job.get("status"))
    if status_migrado:
        job["status"] = status_migrado

    etapa_migrada = ETAPA_ATUAL_MIGRATION.get(job.get("etapa_atual"))
    if etapa_migrada:
        job["etapa_atual"] = etapa_migrada

    proxima_etapa_migrada = PROXIMA_ETAPA_MIGRATION.get(job.get("proxima_etapa"))
    if proxima_etapa_migrada:
        job["proxima_etapa"] = proxima_etapa_migrada

    return job


# Correcao (item 4 da sessao de correcoes de composicao/interface):
# job.json corrompido/ausente fazia a tela de status mostrar "Projeto sem
# dados persistidos" com a pipeline inteira vazia, MESMO com artefatos
# reais em disco (ex: saida/video_final.mp4 de 1.3GB, roteiro_aprovado.md,
# narracao.mp3) - o usuario nao tinha como saber que dava pra recuperar o
# projeto sem abrir a pasta manualmente. `_detectar_estagio_por_artefatos`
# infere o estagio mais avancado que os artefatos em disco PROVAM ter sido
# concluido, na ordem de dependencia do pipeline (CLAUDE.md secao 6) -
# cada estagio devolvido aqui corresponde a um status REAL que alguma
# rota do produto ja sabe reabrir (aguardando_revisao/aguardando_audio/
# aguardando_reorganizacao/aguardando_thumbnail/concluido) - nunca inventa
# um status novo que nenhuma tela saiba tratar. Para quando o primeiro elo
# da cadeia falta (mesmo espirito de "nunca falso negativo escondido" da
# secao 18: melhor nao reconstruir do que reconstruir errado).


def _detectar_estagio_por_artefatos(pasta_projeto) -> str | None:
    """Ve ESTAGIO_RECONSTRUCAO_PARA_JOB abaixo - usado pela rota
    `reconstruir_estado`. Percorre do estagio mais avancado pro menos
    avancado e devolve o primeiro cujos artefatos batem - None se nem o
    roteiro (o artefato mais cedo desta cadeia) existir."""
    pasta_projeto = Path(pasta_projeto) if pasta_projeto else None
    if pasta_projeto is None or not pasta_projeto.is_dir():
        return None

    if (pasta_projeto / "thumbnail" / "final.jpg").is_file():
        return "concluido"
    if (pasta_projeto / "saida" / "video_final.mp4").is_file():
        return "aguardando_thumbnail"
    indice_clipes = _ler_json_seguro(pasta_projeto / "clipes" / "indice.json") or {}
    if indice_clipes.get("clipes"):
        return "aguardando_reorganizacao"
    if (pasta_projeto / "roteiro_aprovado.md").is_file():
        # Cobre tanto o caso normal (audio ainda nao gerado) quanto o
        # caso raro em que narracao.mp3 ja existe mas os clipes ainda nao
        # foram gerados (etapa 4 encadeia direto na 5, sem pausa real do
        # produto nesse instante - nao ha um status "aguardando_
        # geracao_clipes" de verdade pra reabrir, entao reconstruir uma
        # etapa atras - reescolher a origem do audio - e' o mais seguro).
        return "aguardando_audio"
    if (pasta_projeto / "roteiro.md").is_file():
        return "aguardando_revisao"
    return None


ESTAGIO_RECONSTRUCAO_PARA_JOB = {
    "aguardando_revisao": {"status": "aguardando_revisao", "etapa_atual": "roteiro", "proxima_etapa": None},
    "aguardando_audio": {"status": "aguardando_audio", "etapa_atual": "audio", "proxima_etapa": None},
    "aguardando_reorganizacao": {
        "status": "aguardando_reorganizacao", "etapa_atual": "geracao_clipes", "proxima_etapa": "montagem",
    },
    "aguardando_thumbnail": {"status": "aguardando_thumbnail", "etapa_atual": "thumbnail", "proxima_etapa": None},
    "concluido": {"status": "concluido", "etapa_atual": "thumbnail", "proxima_etapa": None},
}


def _data_criacao_projeto(caminho: str):
    """Data de criacao de um projeto, para ordenar a lista da home (mais
    recentes primeiro) - correcao de UX: a lista era ordenada
    alfabeticamente, o que escondia projetos recem-criados no meio dela.

    Prioridade 1: job.json/data_criacao (grava o instante exato da
    criacao no momento do POST /novo - mais confiavel que o timestamp do
    filesystem, que pode mudar se a pasta for movida ou copiada).
    Prioridade 2 (fallback, se job.json nao existe ou nao tem o campo):
    timestamp de criacao da pasta no filesystem (os.path.getctime).
    Se as duas falharem (job.json corrompido/ausente E getctime
    inacessivel - edge case raro), retorna None; listar_projetos() joga
    esses projetos pro fim da lista em vez de deixar a ordenacao
    quebrar."""
    job = _ler_job_json(Path(caminho))
    data_criacao_raw = (job or {}).get("data_criacao")
    if data_criacao_raw:
        try:
            return datetime.fromisoformat(data_criacao_raw)
        except (TypeError, ValueError):
            pass
    try:
        return datetime.fromtimestamp(os.path.getctime(caminho))
    except OSError:
        return None


def _ler_json_seguro(caminho: Path):
    """Le e desserializa um arquivo JSON qualquer da pasta do projeto,
    devolvendo None se o arquivo nao existe ou esta corrompido - mesmo
    espirito de tolerancia a falta de dados de `_ler_job_json`, generico
    para os demais artefatos da tela de revisao (titulos_sugeridos.json,
    job_metadata.json)."""
    if caminho is None or not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ler_perfil_projeto(pasta_projeto):
    if pasta_projeto is None:
        return ""
    caminho = pasta_projeto / "entrada" / "perfil.txt"
    if not caminho.exists():
        return ""
    try:
        return caminho.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _ler_origem_roteiro(pasta_projeto) -> str:
    """Le entrada/origem_roteiro.txt ("ia" ou "upload" - feature de upload
    de roteiro pronto). Ausente (projeto criado antes desta feature, ou
    pasta desconhecida) sempre significa "ia" - comportamento historico
    preservado."""
    if pasta_projeto is None:
        return "ia"
    caminho = pasta_projeto / "entrada" / "origem_roteiro.txt"
    if not caminho.exists():
        return "ia"
    try:
        valor = caminho.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return "ia"
    return valor if valor in ("ia", "upload") else "ia"


def _ler_tipo_projeto(pasta_projeto) -> str:
    """Le entrada/tipo_projeto.txt ("pipeline_completa" ou
    "videos_pre_gerados" - feature de projeto com clipes ja prontos).
    Mesma convencao de `_ler_origem_roteiro`: ausente (projeto criado antes
    desta feature, ou pasta desconhecida) sempre significa
    "pipeline_completa" - comportamento historico preservado, nenhum
    projeto antigo precisa de migracao."""
    if pasta_projeto is None:
        return TIPO_PROJETO_PADRAO
    caminho = pasta_projeto / "entrada" / "tipo_projeto.txt"
    if not caminho.exists():
        return TIPO_PROJETO_PADRAO
    try:
        valor = caminho.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return TIPO_PROJETO_PADRAO
    return valor if validar_tipo_projeto(valor) else TIPO_PROJETO_PADRAO


def _ler_configuracao_video(pasta_projeto) -> dict:
    """Le entrada/configuracao_video.json (formulario de Novo projeto).
    Ausente/corrompido/campos ausentes = defaults seguros que preservam o
    comportamento historico (sem legenda queimada, sem musica, Feature A/B
    desligadas, thumbnail ligada) - nunca levanta excecao (CLAUDE.md secao
    18.6). Projetos criados antes das Features A/B
    (sincronizacao_ia_ativa/reorganizacao_manual_ativa) ou antes da Etapa
    7 opcional (`gerar_thumbnail`) sempre caem nesses defaults, garantindo
    retrocompatibilidade total - em particular, `gerar_thumbnail` ausente
    (todo projeto criado antes desta feature) sempre vale True, o
    comportamento historico (Etapa 7 sempre rodava)."""
    padrao = {
        "legendas_queimadas": False,
        "com_musica_fundo": False,
        "sincronizacao_ia_ativa": False,
        "sincronizacao_duracao_s": validators.SINCRONIZACAO_DURACAO_PADRAO_S,
        "reorganizacao_manual_ativa": False,
        "palavras_alvo": validators.PALAVRAS_ALVO_PADRAO,
        "duracao_alvo_minutos": validators.DURACAO_ALVO_MINUTOS_PADRAO,
        "grayscale": False,
        "gerar_thumbnail": True,
    }
    if pasta_projeto is None:
        return padrao
    dados = _ler_json_seguro(pasta_projeto / "entrada" / "configuracao_video.json")
    if not isinstance(dados, dict):
        return padrao
    for chave in (
        "legendas_queimadas",
        "com_musica_fundo",
        "sincronizacao_ia_ativa",
        "reorganizacao_manual_ativa",
        "grayscale",
        "gerar_thumbnail",
    ):
        if chave in dados:
            padrao[chave] = bool(dados[chave])
    if "sincronizacao_duracao_s" in dados:
        padrao["sincronizacao_duracao_s"] = validators.normalizar_sincronizacao_duracao(
            dados["sincronizacao_duracao_s"]
        )
    if "palavras_alvo" in dados:
        padrao["palavras_alvo"] = validators.normalizar_palavras_alvo(dados["palavras_alvo"])
    if "duracao_alvo_minutos" in dados:
        padrao["duracao_alvo_minutos"] = validators.normalizar_duracao_alvo_minutos(dados["duracao_alvo_minutos"])
    return padrao


def _mmss_para_segundos(timestamp: str) -> int:
    """Converte "mm:ss" ou "hh:mm:ss" (formato emitido por
    scripts/3_gerar_roteiro.py:_formatar_timestamp) em segundos totais -
    usado para posicionar o mini-player de video no <video currentTime=...>
    quando o usuario clica numa nota de rodape [F<n>@mm:ss]."""
    partes = [int(p) for p in timestamp.split(":")]
    if len(partes) == 3:
        horas, minutos, segundos = partes
    else:
        horas = 0
        minutos, segundos = partes
    return horas * 3600 + minutos * 60 + segundos


def renderizar_notas_rodape(texto: str, projeto_id: str) -> str:
    """Converte o roteiro em markdown (com notas de rodape de origem,
    CLAUDE.md secao 5.4) em HTML de preview para a tela de revisao (CLAUDE.md
    secao 5.5): [F<n>@mm:ss] vira link clicavel que abre o mini-player de
    video da fonte n no timestamp certo; [N: url] vira link externo (nova
    aba) se o conteudo parecer uma URL, senao vira um span com o texto da
    nota; [⚠ ...] vira span com destaque visual de aviso.

    Uma tag [F...] com multiplas fontes separadas por virgula (ex.
    [F1@04:32, F2@10:15], correcao pos-Sessao 7.2) vira multiplos links
    sequenciais (①②③...), um por fonte, cada um com seu proprio timestamp -
    sem isso a tag inteira ficava bruta no preview e sobrevivia ao filtro
    de remocao, e o TTS narraria ela literalmente.

    Escapa o texto ANTES de aplicar as substituicoes (nenhum dos padroes usa
    os caracteres que o html.escape() mexe - &, <, >, aspas - entao a ordem
    e' segura) para nunca permitir que conteudo do roteiro gerado pela IA
    injete HTML/JS na pagina. Paragrafos (linhas separadas por linha em
    branco) viram <p> - o roteiro gerado nao usa cabecalhos/listas markdown,
    entao nao ha necessidade de um parser markdown completo aqui (CLAUDE.md
    - so vanilla, sem bibliotecas JS/Python de markdown alem da ja usada em
    /sobre para os perfis)."""
    if not texto:
        return ""

    texto_escapado = html.escape(texto)

    def _sub_nota_fonte(m):
        tag_completa = m.group(0)
        itens = list(PADRAO_FONTE_ITEM.finditer(tag_completa))

        if len(itens) <= 1:
            # Tag com fonte unica - comportamento preservado sem regressao
            # (texto do link continua sendo a tag bruta, ex. "[F1@04:32]").
            item = itens[0]
            numero_fonte = item.group(1)
            inicio = item.group(2)
            segundos = _mmss_para_segundos(inicio)
            fonte_id = f"fonte{int(numero_fonte):02d}"
            return (
                f'<a href="#" class="nota-fonte" data-projeto-id="{html.escape(projeto_id)}" '
                f'data-fonte="{fonte_id}" data-inicio="{segundos}" data-tempo="{segundos}">'
                f'{tag_completa}</a>'
            )

        # Tag com multiplas fontes - cada fonte vira badge separado,
        # sequencial (①②③...), cada um preservando seu proprio timestamp e
        # apontando pro video correto ao clicar.
        badges = []
        for indice, item in enumerate(itens, start=1):
            numero_fonte = item.group(1)
            inicio = item.group(2)
            fim = item.group(3)
            segundos_inicio = _mmss_para_segundos(inicio)
            fonte_id = f"fonte{int(numero_fonte):02d}"
            atributo_fim = ""
            if fim:
                atributo_fim = f'data-fim="{_mmss_para_segundos(fim)}" '
            badges.append(
                f'<a href="#" class="nota-fonte" data-projeto-id="{html.escape(projeto_id)}" '
                f'data-fonte="{fonte_id}" data-inicio="{segundos_inicio}" {atributo_fim}'
                f'data-tempo="{segundos_inicio}">{_numero_circulado(indice)}</a>'
            )
        return "".join(badges)

    def _sub_nota_externa(m):
        conteudo = m.group(1).strip()
        if conteudo.lower().startswith(("http://", "https://")):
            return f'<a href="{conteudo}" target="_blank" rel="noopener" class="nota-externa">{m.group(0)}</a>'
        return f'<span class="nota-externa-texto" title="{conteudo}">{m.group(0)}</span>'

    def _sub_aviso(m):
        categoria = categoria_do_aviso(m.group(1))
        traducao = WARNINGS_ACIONAVEIS.get(categoria, WARNING_FALLBACK)
        return (
            f'<span class="nota-aviso abrir-modal-aviso" '
            f'data-categoria="{html.escape(categoria)}" '
            f'title="{html.escape(traducao["titulo"])}">{m.group(0)}</span>'
        )

    texto_escapado = PADRAO_NOTA_FONTE.sub(_sub_nota_fonte, texto_escapado)
    texto_escapado = PADRAO_NOTA_EXTERNA.sub(_sub_nota_externa, texto_escapado)
    texto_escapado = PADRAO_AVISO.sub(_sub_aviso, texto_escapado)

    paragrafos = [p.strip() for p in texto_escapado.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{p}</p>" for p in paragrafos)


def remover_notas_rodape(texto: str) -> str:
    """Remove as notas de rodape de origem (CLAUDE.md secao 5.4) do roteiro
    antes de gravar roteiro_aprovado.md - sem isso o TTS narraria as
    notacoes literalmente ("F 1 arroba 04 32"). BUG CRITICO corrigido pos-
    Sessao 7: o roteiro aprovado estava sendo salvo com as notas intactas.

    Reusa os mesmos padroes compilados de renderizar_notas_rodape() (fonte
    unica da verdade sobre o que conta como nota) - PADRAO_NOTA_FONTE ja
    cobre `[F1@04:32]`, `[F1@13:56-14:01]` (grupo de fim de intervalo
    opcional) e tags com multiplas fontes separadas por virgula, ex.
    `[F1@04:32, F2@10:15]` - a tag inteira e' removida de uma vez, nunca
    fonte por fonte (correcao pos-Sessao 7.2)."""
    if not texto:
        return texto

    sem_notas = PADRAO_NOTA_FONTE.sub("", texto)
    sem_notas = PADRAO_NOTA_EXTERNA.sub("", sem_notas)
    sem_notas = PADRAO_AVISO.sub("", sem_notas)

    # Colapsa espacos/tabs duplicados deixados pela remocao (nota colada em
    # pontuacao sem espaco antes nao gera espaco fantasma; nota cercada de
    # espaco dos dois lados deixa dois espacos, aqui reduzidos a um) sem
    # mexer em quebras de linha/paragrafos.
    sem_notas = re.sub(r"[ \t]{2,}", " ", sem_notas)
    sem_notas = re.sub(r"[ \t]+\n", "\n", sem_notas)
    sem_notas = re.sub(r"\n[ \t]+", "\n", sem_notas)
    # Nota seguida de pontuacao ("isso [⚠ ...]. Frase") deixa um espaco
    # fantasma antes da pontuacao - remove tambem esse caso.
    sem_notas = re.sub(r" ([.,;:!?])", r"\1", sem_notas)
    return sem_notas.strip()


PADRAO_CABECALHO_MARKDOWN = re.compile(r"^#{1,6}[ \t]+.*$", re.MULTILINE)


def remover_cabecalhos_markdown(texto: str) -> str:
    """Remove cabecalhos markdown ATX ("## Titulo de secao") do roteiro
    antes de gravar roteiro_aprovado.md - bug corrigido pos-Sessao 21:
    o prompt do perfil truecrime autorizava "eventualmente um subtitulo"
    (brecha ja removida em scripts/prompts/perfis/truecrime/sistema.md),
    e o roteiro saia com linhas tipo "## The Woman Who Lived Alone in the
    Foothills" que iam direto pro TTS - o narrador lia o subtitulo como
    narracao (video e' continuo, sem edicao de secoes/cortes de cena
    marcados).

    So' remove a LINHA do cabecalho (o texto do titulo em si nunca deveria
    ser narrado) - preserva a quebra de paragrafo ao redor colapsando as
    linhas em branco extras que a remocao deixa para uma unica linha em
    branco, nunca zero (texto continua legivel, sem colar dois paragrafos
    num so)."""
    if not texto:
        return texto

    sem_cabecalhos = PADRAO_CABECALHO_MARKDOWN.sub("", texto)
    sem_cabecalhos = re.sub(r"\n{3,}", "\n\n", sem_cabecalhos)
    return sem_cabecalhos.strip()


def obter_cotacao_usd_brl():
    """Le COTACAO_USD_BRL do ambiente (CLAUDE.md secao 7) para exibir o custo
    estimado do roteiro em BRL alem de USD na tela de revisao. Retorna
    (cotacao: float, configurada: bool) - configurada=False quando a
    variavel esta ausente/invalida e o default foi usado, para a tela poder
    avisar "Cotação estimada" nesse caso."""
    valor = os.environ.get("COTACAO_USD_BRL")
    if not valor:
        return COTACAO_USD_BRL_PADRAO, False
    try:
        return float(valor), True
    except ValueError:
        return COTACAO_USD_BRL_PADRAO, False


def _ler_links_projeto(pasta_projeto):
    if pasta_projeto is None:
        return []
    caminho = pasta_projeto / "entrada" / "links.txt"
    if not caminho.exists():
        return []
    try:
        linhas = caminho.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    return [linha.strip() for linha in linhas if linha.strip()]


def _ler_manifest_fontes(pasta_projeto):
    if pasta_projeto is None:
        return []
    caminho = pasta_projeto / "fontes" / "manifest_fontes.json"
    if not caminho.exists():
        return []
    try:
        manifest = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return manifest.get("fontes", [])


def _calcular_resumo_fontes(pasta_projeto: Path, total_solicitado: int) -> dict:
    fontes = _ler_manifest_fontes(pasta_projeto)
    total_baixado = sum(1 for f in fontes if f.get("sucesso"))
    duracao_total = sum(f.get("duracao_s") or 0 for f in fontes if f.get("sucesso"))
    return {
        "total_solicitado": total_solicitado,
        "total_baixado": total_baixado,
        "total_falhado": total_solicitado - total_baixado,
        "duracao_total_s": duracao_total,
    }


def _tipo_erro_predominante(pasta_projeto: Path):
    """Categoria de erro pra persistir no job.json quando a etapa falha por
    completo. Se as fontes falhadas tiverem categorias diferentes, junta as
    categorias unicas - a mensagem amigavel (mensagem_usuario) continua
    sendo o texto principal mostrado ao usuario."""
    fontes = _ler_manifest_fontes(pasta_projeto)
    tipos = sorted({f.get("tipo_erro") for f in fontes if not f.get("sucesso") and f.get("tipo_erro")})
    if not tipos:
        return None
    return tipos[0] if len(tipos) == 1 else ",".join(tipos)


def _formatar_data_iso(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return None


def _formatar_duracao_s(segundos):
    if not segundos:
        return None
    segundos = int(segundos)
    minutos, s = divmod(segundos, 60)
    if minutos:
        return f"{minutos}min {s}s"
    return f"{s}s"


def _formatar_mmss(segundos):
    """Formato mm:ss (minutos SEM cap em 59 - ex: 3661s -> "61:01") usado
    para todo TIMESTAMP (instante especifico na narracao) na tela de
    reorganizacao manual (Feature B, sessao de correcoes UX GRUPO B/C):
    rodape de cada card da timeline E coluna de tempo da tabela de swaps
    da Feature A. Uma unica funcao para os dois lugares - evitar dois
    formatos de tempo diferentes na mesma tela (`_formatar_duracao_s`,
    "Nmin Ss", continua reservado para exibir DURACOES totais, ex. o
    resumo "N clipe(s) na timeline, X de video" - conceito diferente de
    timestamp). None/negativo -> "00:00" (nunca None - a UI sempre precisa
    de um texto para renderizar, diferente de `_formatar_duracao_s`)."""
    if segundos is None or segundos < 0:
        segundos = 0
    segundos_int = int(round(segundos))
    minutos, s = divmod(segundos_int, 60)
    return f"{minutos:02d}:{s:02d}"


TIPO_USO_ROTULOS = {
    "ambos": "Transcrição + clipes",
    "transcricao": "Só transcrição",
    "visual": "Só clipes",
}


def _fontes_baixadas_com_origem(pasta_projeto):
    """Fontes com sucesso do manifest, com duracao formatada, origem
    (youtube/upload - CLAUDE.md secao 5.7.2), link original e tipo de uso
    (CLAUDE.md secao 5.7.2). Reaproveitado pela rota /status (render
    inicial) e /api/status (polling) para os dois mostrarem o mesmo bloco
    "Arquivos baixados". `origem` ja vem gravada no manifest desde a
    Sessao 18 (1_baixar_videos.py) - projetos anteriores a essa feature
    nao tem a chave, default "youtube" preserva o comportamento de sempre
    (so' existia download via yt-dlp). O manifest grava o link em
    `url_original` (nao `url`) - `fonte["url"]` e' derivado aqui pra tela
    de leitura consumir um nome de campo estavel. `tipo_uso` vem de
    entrada/fontes_tipo_uso.json (mapa fonteNN -> ambos/transcricao/visual,
    CLAUDE.md secao 5.7.2); fonte ausente do mapa (ou arquivo inteiro
    ausente) e' "ambos", mesmo default que scripts/2_transcrever.py e
    scripts/5_gerar_clipes.py usam."""
    fontes = _ler_manifest_fontes(pasta_projeto)
    fontes_baixadas = [f for f in fontes if f.get("sucesso")]
    mapa_tipo_uso = {}
    caminho_tipo_uso = pasta_projeto / "entrada" / "fontes_tipo_uso.json" if pasta_projeto is not None else None
    if caminho_tipo_uso is not None and caminho_tipo_uso.exists():
        try:
            mapa_tipo_uso = json.loads(caminho_tipo_uso.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            mapa_tipo_uso = {}
    for fonte in fontes_baixadas:
        fonte["duracao_formatada"] = _formatar_duracao_s(fonte.get("duracao_s"))
        fonte.setdefault("origem", "youtube")
        fonte["url"] = fonte.get("url_original") or fonte.get("url")
        tipo_uso = mapa_tipo_uso.get(fonte.get("id"), "ambos")
        fonte["tipo_uso"] = tipo_uso
        fonte["tipo_uso_rotulo"] = TIPO_USO_ROTULOS.get(tipo_uso, tipo_uso)

    if fontes_baixadas:
        mensagem_arquivos = None
    elif fontes:
        mensagem_arquivos = "Nenhum arquivo baixado com sucesso."
    else:
        mensagem_arquivos = "Nenhum arquivo baixado ainda."

    return fontes_baixadas, mensagem_arquivos


def _ler_transcricoes_projeto(pasta_projeto) -> list:
    """Le transcricoes/*.json (CLAUDE.md secao 5.2) e devolve uma lista
    ordenada por nome de arquivo-fonte, cada entrada com o texto completo
    (segmentos concatenados) pronto pra exibir na tela somente-leitura da
    etapa "Transcricao" (`ver_etapa_pipeline`). So' o texto - os
    timestamps por palavra (`palavras`) nao interessam aqui, ja tem uso
    proprio na Etapa 3 (notas de rodape) e no alinhamento de audio."""
    pasta_transcricoes = Path(pasta_projeto) / "transcricoes" if pasta_projeto else None
    if pasta_transcricoes is None or not pasta_transcricoes.is_dir():
        return []
    resultado = []
    for caminho in sorted(pasta_transcricoes.glob("*.json")):
        dados = _ler_json_seguro(caminho)
        if not isinstance(dados, dict):
            continue
        segmentos = dados.get("segmentos") or []
        texto = " ".join(str(seg.get("text") or "").strip() for seg in segmentos).strip()
        resultado.append(
            {
                "arquivo": dados.get("arquivo") or caminho.stem,
                "idioma": dados.get("idioma"),
                "duracao_formatada": _formatar_duracao_s(dados.get("duracao_s")),
                "texto": texto,
            }
        )
    return resultado


def _ler_clipes_indice_para_exibicao(pasta_projeto) -> list:
    """Le clipes/indice.json (CLAUDE.md secao 5.7) na ordem final do video
    e devolve uma lista pronta pra' tela somente-leitura da etapa "Clipes"
    (`ver_etapa_pipeline`) - miniatura via thumb_clipe (gerada sob
    demanda, mesma rota que a tela de reorganizacao manual ja usa),
    duracao formatada e a fonte original de cada clipe."""
    indice = _ler_json_seguro(Path(pasta_projeto) / "clipes" / "indice.json") if pasta_projeto else None
    clipes = (indice or {}).get("clipes") or []
    return [
        {
            "clipe_id": c.get("clipe_id"),
            "fonte_original": c.get("fonte_original"),
            "duracao_formatada": _formatar_duracao_s(c.get("duracao_s")),
            "marca_dagua_removida": c.get("marca_dagua_removida"),
        }
        for c in clipes
        if c.get("clipe_id")
    ]


# PIPELINE_ETAPAS vem de scripts/labels_ui.py (import no topo do arquivo) -
# unica fonte da verdade pra ordem das etapas + label amigavel de cada uma
# (label_etapa), compartilhada com os filtros Jinja de label.


def _mensagem_proxima_etapa(status: str, proxima_etapa: str | None) -> str | None:
    """Frase amigavel exibida na tela de status quando uma etapa acaba de
    concluir (GRUPO A da sessao de correcoes UX). Antes desta correcao,
    templates/status.html tinha o texto "Download completo, proxima etapa:
    transcricao." HARDCODED - aparecia sempre que `proxima_etapa` fosse
    truthy, inclusive apos a Etapa 5 (aguardando_reorganizacao/
    aguardando_legendas, onde a proxima etapa real e' "montagem"). Retorna
    None quando nao ha proxima etapa a anunciar (mesma condicao que o
    template usa para ocultar o paragrafo)."""
    if not proxima_etapa:
        return None
    rotulo = label_etapa(proxima_etapa)
    if status == "aguardando_reorganizacao":
        # Estado de pausa manual (Feature B) - a proxima etapa so' acontece
        # depois que o usuario reorganizar e confirmar, nao automaticamente.
        return f"Clipes prontos - aguardando reorganização manual. Depois: {rotulo}."
    return f"Próxima etapa: {rotulo}."


# Nem toda etapa persiste quanto tempo levou pra processar - so' as quatro
# abaixo gravam isso hoje (arquivo relativo a pasta do projeto + caminho de
# chaves ate' o numero). download (1_baixar_videos.py) e transcricao
# (2_transcrever.py) nao gravam tempo total algum, entao ficam de fora e a
# pipeline horizontal mostra "-" pra elas quando concluidas (melhor esforco,
# nao inventa coleta de dado nova so' pro visual).
ETAPA_ARQUIVO_DURACAO = {
    "roteiro": ("job_metadata.json", ("tempo_geracao_s",)),
    "audio": ("narracao_metadata.json", ("tempo_geracao_s",)),
    "geracao_clipes": ("clipes/indice.json", ("metadata", "tempos_por_fase", "total_s")),
    "montagem": ("saida/montagem_metadata.json", ("tempo_total_s",)),
}


def _duracao_etapa_concluida(nome_etapa: str, pasta_projeto) -> str:
    """Duracao real (formatada) de uma etapa ja concluida, lida do metadata
    JSON que aquela etapa grava no disco - ver ETAPA_ARQUIVO_DURACAO. Devolve
    "-" quando a etapa nao grava duracao, o arquivo nao existe/esta
    corrompido, ou pasta_projeto e' desconhecida."""
    entrada = ETAPA_ARQUIVO_DURACAO.get(nome_etapa)
    if entrada is None or pasta_projeto is None:
        return "-"
    nome_arquivo, caminho_chaves = entrada
    dados = _ler_json_seguro(Path(pasta_projeto) / nome_arquivo)
    valor = dados
    for chave in caminho_chaves:
        if not isinstance(valor, dict):
            return "-"
        valor = valor.get(chave)
    if not isinstance(valor, (int, float)):
        return "-"
    return _formatar_duracao_s(valor) or "-"


# Etapas do pipeline horizontal que tem tela navegavel de verdade pra
# revisitar (refinamento "pipeline clicavel"). Nao ha etapa "concluido"
# separada em PIPELINE_ETAPAS - a tela /concluido so' e' alcancada quando
# o job inteiro chega a status "concluido", momento em que a ULTIMA etapa
# da lista ("thumbnail", desde a Etapa 7) e' quem fica marcada "done" (ver
# _parsear_pipeline_steps abaixo: e' a unica forma dela virar "done", ja
# que nao existe indice depois pra cair no ramo "indice < indice_atual").
# "montagem" nao e' mais a ultima etapa (thumbnail roda depois dela agora),
# mas continua com tela propria (preview do video final).
#
# "download"/"transcricao"/"audio"/"geracao_clipes" ganharam tela propria
# de revisita numa sessao seguinte (item 3 - "telas de pipeline em projeto
# concluido" - antes dessas quatro nunca eram clicaveis, o pipeline
# horizontal so' reabria roteiro/montagem/thumbnail). Todas as quatro
# reaproveitam a MESMA rota/template genericos (`ver_etapa_pipeline` /
# pipeline_etapa_detalhe.html), somente leitura, sem excecao de status
# como roteiro/thumbnail tem - clicavel assim que a etapa estiver "done",
# independente do job inteiro ja ter concluido ou nao (mesmo espirito
# permissivo de "roteiro" abaixo).
ETAPAS_COM_TELA = {"download", "transcricao", "roteiro", "audio", "geracao_clipes", "montagem", "thumbnail"}


def _determinar_click(nome_step: str, estado_passo: str, status_geral, projeto_id: str):
    """Decide se um step do pipeline horizontal vira link clicavel pra
    revisitar a tela correspondente em modo leitura, e qual URL usar.
    Retorna (clicavel: bool, url: str | None).

    Regras (refinamento "pipeline clicavel"):
    - "download"/"transcricao"/"audio"/"geracao_clipes" concluidas ->
      reabrem /projetos/<id>/pipeline/<etapa> (ver_etapa_pipeline),
      somente leitura, sem excecao de status - clicavel assim que a
      propria etapa estiver "done", mesmo que o job inteiro ainda esteja
      rodando uma etapa posterior (item 3 da sessao de correcoes de
      composicao/interface).
    - "roteiro" concluido (pipeline ja avancou pra alem da revisao) ->
      reabre /revisar_roteiro em modo=readonly (mostra roteiro_aprovado.md,
      botoes de edicao desabilitados).
    - "roteiro" aguardando revisao (estado "waiting") -> aponta pra
      /revisar_roteiro normal, e' a propria tela de aprovacao ainda ativa.
    - "montagem" concluida -> so' acontece quando o job inteiro esta
      status=="concluido" (ver comentario de ETAPAS_COM_TELA acima) ->
      aponta pra /concluido.
    - "thumbnail" concluida (job inteiro status=="concluido") -> reabre
      /projetos/<id>/thumbnail em modo=readonly (mostra o sujeito/grid
      escolhidos, sem nenhum controle de edicao) - ANTES apontava pra
      /concluido igual "montagem", o que fazia as duas etapas levarem
      pro mesmo lugar e dava a impressao de que so' "Roteiro" tinha tela
      propria de revisita.
    - "thumbnail" aguardando escolha (estado "waiting") -> aponta pra
      /projetos/<id>/thumbnail normal, e' a propria tela de escolha
      ainda ativa.
    - Qualquer outro estado (running/pending/failed) nunca e' clicavel -
      nada pronto pra reabrir, ou o usuario ja esta na tela ativa.
    """
    if nome_step not in ETAPAS_COM_TELA:
        return False, None

    if nome_step in ("download", "transcricao", "audio", "geracao_clipes"):
        if estado_passo == "done":
            return True, url_for("ver_etapa_pipeline", projeto_id=projeto_id, etapa=nome_step)
        return False, None

    if nome_step == "roteiro":
        if estado_passo == "done":
            return True, url_for("revisar_roteiro", projeto_id=projeto_id, modo="readonly")
        if estado_passo == "waiting":
            return True, url_for("revisar_roteiro", projeto_id=projeto_id)
        return False, None

    if nome_step == "montagem":
        if estado_passo == "done" and status_geral == "concluido":
            return True, url_for("concluido", projeto_id=projeto_id)
        return False, None

    if nome_step == "thumbnail":
        if estado_passo == "done" and status_geral == "concluido":
            return True, url_for("tela_thumbnail", projeto_id=projeto_id, modo="readonly")
        if estado_passo == "waiting":
            return True, url_for("tela_thumbnail", projeto_id=projeto_id)
        return False, None

    return False, None


def _parsear_pipeline_steps(estado: dict, pasta_projeto=None, projeto_id=None) -> list:
    """Deriva o estado visual (pending/running/waiting/done/failed) de cada
    etapa do pipeline (secao 5 do CLAUDE.md) a partir do `estado` ja
    montado por _montar_estado_status - sem nenhuma fonte de dado nova,
    so' reaproveita etapa/status/pct que a tela de status ja tinha. Usado
    pelo painel de pipeline horizontal (status.html, revisao_roteiro.html e
    concluido.html).

    `projeto_id`: se informado, cada passo tambem ganha `clicavel`/`url`
    (ver _determinar_click) pra virar link navegavel no pipeline
    horizontal. Se None (nenhum chamador hoje omite, mas mantem
    retrocompatibilidade), todo passo vem com clicavel=False.

    `pasta_projeto`: alem de alimentar `_duracao_etapa_concluida`, tambem
    decide se o circulo "thumbnail" aparece na lista - projeto com
    `gerar_thumbnail=False` (Grupo C, Etapa 7 opcional) nunca passa por
    ela, entao o passo e' filtrado do RETORNO aqui (a constante global
    PIPELINE_ETAPAS nunca e' alterada - so' esta funcao decide o que
    mostrar pra este projeto especifico). "thumbnail" e' sempre o
    ULTIMO item de PIPELINE_ETAPAS, entao filtra-lo nunca deixa buraco
    na numeracao (`numero`) dos passos anteriores. Sem `pasta_projeto`
    (None), cai no comportamento historico (thumbnail sempre aparece) -
    mesmo espirito de retrocompatibilidade de `_ler_configuracao_video`."""
    etapa_atual = estado.get("etapa")
    status_atual = estado.get("status")
    nomes_etapas = [nome for nome, _rotulo in PIPELINE_ETAPAS]
    indice_atual = nomes_etapas.index(etapa_atual) if etapa_atual in nomes_etapas else -1

    passos = []
    for indice, (nome, rotulo) in enumerate(PIPELINE_ETAPAS):
        if status_atual == "concluido":
            estado_passo = "done"
        elif indice < indice_atual:
            estado_passo = "done"
        elif indice > indice_atual:
            estado_passo = "pending"
        else:
            # indice == indice_atual: a etapa que o job.json aponta agora.
            if status_atual == "erro":
                estado_passo = "failed"
            elif status_atual and status_atual.startswith("aguardando"):
                estado_passo = "waiting"
            elif status_atual in ("em_andamento", "pendente", "iniciado"):
                estado_passo = "running"
            else:
                estado_passo = "pending"
        if estado_passo == "done":
            duracao = _duracao_etapa_concluida(nome, pasta_projeto)
        elif estado_passo == "running":
            duracao = "atual"
        else:
            duracao = "-"
        if projeto_id is not None:
            clicavel, url = _determinar_click(nome, estado_passo, status_atual, projeto_id)
        else:
            clicavel, url = False, None
        passos.append(
            {
                "nome": nome,
                "rotulo": rotulo,
                "numero": indice + 1,
                "estado": estado_passo,
                "pct": estado.get("pct") if estado_passo == "running" else (100 if estado_passo == "done" else 0),
                "duracao": duracao,
                "clicavel": clicavel,
                "url": url,
            }
        )
    if pasta_projeto is not None and not _ler_configuracao_video(pasta_projeto)["gerar_thumbnail"]:
        passos = [passo for passo in passos if passo["nome"] != "thumbnail"]
    return passos


def _listar_artefatos(pasta_projeto) -> list:
    """Lista simples dos principais arquivos gerados por um projeto
    (saida/, clipes/, fontes/, roteiro_aprovado.md) para a coluna
    "Artefatos" da tela de status - so' o que existir de fato no disco,
    sem tentar reconstruir o pipeline inteiro."""
    if pasta_projeto is None or not Path(pasta_projeto).is_dir():
        return []
    candidatos = [
        pasta_projeto / "saida" / "video_final.mp4",
        pasta_projeto / "roteiro_aprovado.md",
        pasta_projeto / "narracao.mp3",
        pasta_projeto / "legendas" / "legenda.ass",
    ]
    artefatos = []
    for caminho in candidatos:
        try:
            if caminho.is_file():
                tamanho_mb = caminho.stat().st_size / (1024 * 1024)
                artefatos.append({"nome": caminho.name, "tamanho": f"{tamanho_mb:.1f} MB"})
        except OSError:
            continue
    return artefatos


def _montar_estado_status(job_memoria, job_disco):
    """Une o job em memoria (dados dinamicos de uma execucao ativa) com o
    job.json persistido no disco (dados finais/historicos), preferindo o
    job em memoria quando presente. Isso garante que a tela de status nunca
    fica so com "-" pra um projeto historico so porque o servidor
    reiniciou (Sessao 4) - e que uma execucao ativa continua mostrando
    progresso ao vivo (job em memoria) sem esperar o proximo write em
    disco."""
    disco = job_disco or {}

    if job_memoria is not None:
        status = job_memoria.get("status")
        etapa = job_memoria.get("etapa")
        pct = job_memoria.get("pct") or 0.0
        detalhe = job_memoria.get("detalhe")
        proxima_etapa = job_memoria.get("proxima_etapa")
        mensagem_usuario = job_memoria.get("erro")
        log = job_memoria.get("log") or []
        etapa7_falhou = bool(job_memoria.get("etapa7_falhou"))
    else:
        status = disco.get("status")
        etapa = disco.get("etapa_atual") or disco.get("etapa")
        pct = 100.0 if status in ("concluido", "erro") else 0.0
        detalhe = None
        proxima_etapa = disco.get("proxima_etapa")
        mensagem_usuario = disco.get("mensagem_usuario")
        log = None
        etapa7_falhou = bool(disco.get("etapa7_falhou"))

    return {
        "em_memoria": job_memoria is not None,
        "tem_dados": job_memoria is not None or job_disco is not None,
        "status": status,
        "etapa": etapa,
        "pct": pct,
        "detalhe": detalhe,
        "proxima_etapa": proxima_etapa,
        "proxima_etapa_mensagem": _mensagem_proxima_etapa(status, proxima_etapa),
        "mensagem_usuario": mensagem_usuario,
        "log": log,
        "log_persistido": disco.get("log_erro"),
        "data_criacao": _formatar_data_iso(disco.get("data_criacao") or disco.get("criado_em")),
        "data_fim": _formatar_data_iso(disco.get("data_fim")),
        "resumo_fontes": disco.get("resumo_fontes"),
        # Etapa 7 "nunca falha o job" (fica em aguardando_thumbnail mesmo
        # se o subprocess quebrar), mas isso NAO pode significar esconder
        # que a geracao automatica nao rodou - este flag distingue
        # "pronto pra revisao" de "gerar candidatos falhou, complete a
        # mao ou tente de novo" (correcao pos-Sessao 21, ver
        # _executar_etapa7).
        "etapa7_falhou": etapa7_falhou,
    }


def _consumir_progresso_subprocess(processo, job):
    """Le stdout de um subprocess de etapa do pipeline linha a linha,
    atualizando `job` a cada `@PROGRESSO {...}` emitida (CLAUDE.md secao 9)
    - compartilhado entre todas as etapas disparadas via subprocess
    (_executar_etapa1, _executar_etapa2, ...). Bloqueia ate o subprocess
    terminar (chama `processo.wait()` no final)."""
    for linha in processo.stdout:
        linha = linha.rstrip("\n")
        if not linha:
            continue

        m = PADRAO_PROGRESSO_JSON.match(linha)
        if m is None:
            job["log"].append(linha)
            continue

        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            job["log"].append(linha)
            continue

        job["pct"] = payload.get("pct", job["pct"])
        job["detalhe"] = payload.get("detalhe", job["detalhe"])
        job["eta_s"] = payload.get("eta_s")
        if "avisos" in payload:
            job["avisos"] = payload["avisos"]
        if "erros" in payload:
            job["erros"] = payload["erros"]
        if "mensagem_usuario" in payload:
            job["mensagem_usuario"] = payload["mensagem_usuario"]
        if "tipo_erro" in payload:
            job["tipo_erro"] = payload["tipo_erro"]
        job["log"].append(job["detalhe"])

    processo.wait()


def _job_inicial_etapa2():
    return {
        "etapa": "transcricao",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Iniciando transcricao dos videos-fonte...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }


def _job_inicial_etapa3():
    return {
        "etapa": "roteiro",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Iniciando geracao do roteiro...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }


def _executar_etapa1(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/1_baixar_videos.py como subprocess, atualizando
    `jobs[projeto_id]` a cada linha `@PROGRESSO {...}` emitida (CLAUDE.md
    secao 9). Pensado para rodar numa thread de fundo - ver
    `_disparar_etapa1` - para nao bloquear a requisicao POST /novo nem o
    polling de GET /api/status/<id>.

    Se a Etapa 1 concluir com sucesso, dispara a Etapa 2 (transcricao) em
    seguida, na MESMA thread - fluxo continuo download -> transcricao sem
    intervencao do usuario (CLAUDE.md secao 4). Se a Etapa 1 falhar, o
    pipeline para ali - a Etapa 2 nunca roda sobre fontes que nao existem."""
    script = BASE_DIR / "scripts" / "1_baixar_videos.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]
    total_solicitado = len(_ler_links_projeto(pasta_projeto))

    _persistir_job(
        pasta_projeto,
        status="em_andamento",
        etapa_atual="download",
        data_inicio_execucao=datetime.now().isoformat(),
    )

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        job["status"] = "erro"
        job["erro"] = f"Falha ao iniciar a etapa de download: {exc}"
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="download",
            data_fim=datetime.now().isoformat(),
            tipo_erro="falha_ao_iniciar",
            mensagem_usuario=job["erro"],
            log_erro=job["erro"],
            resumo_fontes=_calcular_resumo_fontes(pasta_projeto, total_solicitado),
        )
        return

    _consumir_progresso_subprocess(processo, job)

    resumo_fontes = _calcular_resumo_fontes(pasta_projeto, total_solicitado)

    if processo.returncode == 0:
        job["status"] = "concluido"
        job["proxima_etapa"] = PROXIMA_ETAPA.get(job["etapa"])
        _persistir_job(
            pasta_projeto,
            status="concluido",
            etapa_atual="download",
            proxima_etapa=job["proxima_etapa"],
            data_fim=datetime.now().isoformat(),
            resumo_fontes=resumo_fontes,
            # Limpa campos de erro de uma tentativa anterior que pode ter
            # falhado (job.json e' um merge por cima do que ja existe em
            # disco, _persistir_job nao apaga chaves sozinho) - sem isso, um
            # sucesso apos retry mostraria mensagem_usuario/tipo_erro
            # obsoletos junto de status "concluido" (achado real rodando o
            # pipeline de ponta a ponta na Sessao 4).
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )
        _encadear_etapa2(projeto_id, pasta_projeto)
    else:
        job["status"] = "erro"
        # mensagem_usuario (Problema 4 da Sessao 3.1) e' a mensagem amigavel
        # classificada pelo script - preferida sobre o "detalhe" tecnico
        # bruto (ex: "ERRO: nenhum video baixado") como texto principal na
        # tela de status.
        job["erro"] = job.get("mensagem_usuario") or job.get("detalhe") or "Etapa de download falhou."
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="download",
            data_fim=datetime.now().isoformat(),
            tipo_erro=_tipo_erro_predominante(pasta_projeto),
            mensagem_usuario=job["erro"],
            log_erro="\n".join(job["log"][-40:]),
            resumo_fontes=resumo_fontes,
        )


def _disparar_etapa1(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = {
        "etapa": "download",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Iniciando download dos videos-fonte...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "proxima_etapa": None,
    }
    thread = threading.Thread(
        target=_executar_etapa1, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


def _encadear_etapa2(projeto_id: str, pasta_projeto: Path):
    """Dispara a Etapa 2 logo apos a Etapa 1 concluir com sucesso, na
    MESMA thread (fluxo continuo download -> transcricao, CLAUDE.md secao
    4). Funcao separada de `_executar_etapa1` de proposito - os testes
    isolam o comportamento de uma etapa por vez fazendo monkeypatch desta
    funcao inteira (reset do job + execucao), em vez de so
    `_executar_etapa2` (o que deixaria o reset do job acontecer mesmo com
    a execucao mockada).

    Excecao (feature de upload de roteiro pronto): se o projeto foi criado
    com origem_roteiro=upload, as Etapas 2 (transcricao) e 3 (geracao via
    IA) nunca rodam - o roteiro ja esta em disco (gravado por
    `_criar_pasta_projeto` na hora da criacao do projeto) e nao ha nenhuma
    transcricao pra alimentar uma geracao que nao vai acontecer. Pula direto
    para "aguardando_revisao"."""
    if _ler_origem_roteiro(pasta_projeto) == "upload":
        _pular_para_revisao_roteiro_importado(projeto_id, pasta_projeto)
        return
    jobs[projeto_id] = _job_inicial_etapa2()
    _executar_etapa2(projeto_id, pasta_projeto)


def _pular_para_revisao_roteiro_importado(projeto_id: str, pasta_projeto: Path):
    """Leva o job direto para "aguardando_revisao" sem rodar as Etapas 2/3
    (feature de upload de roteiro pronto - ver `_encadear_etapa2`). Espelha
    os mesmos campos que `_executar_etapa3` grava no sucesso, para que
    /revisar_roteiro e o pipeline horizontal vejam exatamente o mesmo
    formato de estado nos dois casos (roteiro via IA ou via upload)."""
    jobs[projeto_id] = {
        "etapa": "roteiro",
        "status": "aguardando_revisao",
        "pct": 100.0,
        "detalhe": "Roteiro fornecido pelo usuario - transcricao e geracao via IA puladas.",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }
    _persistir_job(
        pasta_projeto,
        status="aguardando_revisao",
        etapa_atual="roteiro",
        data_fim=datetime.now().isoformat(),
        tipo_erro=None,
        mensagem_usuario=None,
        log_erro=None,
    )


def _executar_etapa2(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/2_transcrever.py como subprocess, atualizando
    `jobs[projeto_id]` a cada linha `@PROGRESSO {...}` emitida - mesmo
    padrao de `_executar_etapa1`. Chamada tanto automaticamente por
    `_executar_etapa1` (fluxo continuo download -> transcricao) quanto pelo
    disparo manual `_disparar_etapa2` (POST /projetos/<id>/transcrever)."""
    script = BASE_DIR / "scripts" / "2_transcrever.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]

    _persistir_job(
        pasta_projeto,
        status="em_andamento",
        etapa_atual="transcricao",
        data_inicio_transcricao=datetime.now().isoformat(),
    )

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        job["status"] = "erro"
        job["erro"] = f"Falha ao iniciar a etapa de transcricao: {exc}"
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="transcricao",
            data_fim=datetime.now().isoformat(),
            tipo_erro="falha_ao_iniciar",
            mensagem_usuario=job["erro"],
            log_erro=job["erro"],
        )
        return

    _consumir_progresso_subprocess(processo, job)

    if processo.returncode == 0:
        job["status"] = "concluido"
        job["proxima_etapa"] = PROXIMA_ETAPA.get(job["etapa"])
        _persistir_job(
            pasta_projeto,
            status="concluido",
            etapa_atual="transcricao",
            proxima_etapa=job["proxima_etapa"],
            data_fim=datetime.now().isoformat(),
            # Idem etapa1: limpa erro de uma tentativa anterior (ex: retry
            # manual via POST /projetos/<id>/transcrever apos corrigir o
            # ambiente) para nao mostrar mensagem_usuario/tipo_erro
            # obsoletos junto de status "concluido".
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )
        _encadear_etapa3(projeto_id, pasta_projeto)
    else:
        job["status"] = "erro"
        job["erro"] = job.get("mensagem_usuario") or job.get("detalhe") or "Etapa de transcricao falhou."
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="transcricao",
            data_fim=datetime.now().isoformat(),
            tipo_erro=job.get("tipo_erro"),
            mensagem_usuario=job["erro"],
            log_erro="\n".join(job["log"][-40:]),
        )


def _disparar_etapa2(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = _job_inicial_etapa2()
    thread = threading.Thread(
        target=_executar_etapa2, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


def _encadear_etapa3(projeto_id: str, pasta_projeto: Path):
    """Dispara a Etapa 3 (geracao de roteiro) logo apos a Etapa 2 concluir
    com sucesso, na MESMA thread (fluxo continuo download -> transcricao
    -> roteiro, CLAUDE.md secao 4). Funcao separada de `_executar_etapa2`
    de proposito - mesmo espirito de `_encadear_etapa2`: os testes que
    querem isolar o comportamento da Etapa 2 sozinha fazem monkeypatch
    desta funcao inteira, em vez de so `_executar_etapa3`."""
    jobs[projeto_id] = _job_inicial_etapa3()
    _executar_etapa3(projeto_id, pasta_projeto)


def _executar_etapa3(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/3_gerar_roteiro.py como subprocess, atualizando
    `jobs[projeto_id]` a cada linha `@PROGRESSO {...}` emitida - mesmo
    padrao de `_executar_etapa1`/`_executar_etapa2`. Chamada tanto
    automaticamente por `_executar_etapa2` (fluxo continuo transcricao ->
    roteiro) quanto pelo disparo manual `_disparar_etapa3` (POST
    /projetos/<id>/gerar_roteiro).

    Ao concluir com sucesso, o job NAO fica "concluido" - fica
    "aguardando_revisao" (CLAUDE.md secao 5.3: a Etapa 3 sempre pausa o
    pipeline para revisao humana do roteiro antes de prosseguir)."""
    script = BASE_DIR / "scripts" / "3_gerar_roteiro.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]

    _persistir_job(
        pasta_projeto,
        status="em_andamento",
        etapa_atual="roteiro",
        data_inicio_roteiro=datetime.now().isoformat(),
    )

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        job["status"] = "erro"
        job["erro"] = f"Falha ao iniciar a etapa de geracao de roteiro: {exc}"
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="roteiro",
            data_fim=datetime.now().isoformat(),
            tipo_erro="falha_ao_iniciar",
            mensagem_usuario=job["erro"],
            log_erro=job["erro"],
        )
        return

    _consumir_progresso_subprocess(processo, job)

    if processo.returncode == 0:
        job["status"] = "aguardando_revisao"
        job["etapa"] = "roteiro"
        job["proxima_etapa"] = None
        _persistir_job(
            pasta_projeto,
            status="aguardando_revisao",
            etapa_atual="roteiro",
            data_fim=datetime.now().isoformat(),
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )
    else:
        job["status"] = "erro"
        job["erro"] = job.get("mensagem_usuario") or job.get("detalhe") or "Etapa de geracao de roteiro falhou."
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="roteiro",
            data_fim=datetime.now().isoformat(),
            tipo_erro=job.get("tipo_erro"),
            mensagem_usuario=job["erro"],
            log_erro="\n".join(job["log"][-40:]),
        )


def _disparar_etapa3(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = _job_inicial_etapa3()
    thread = threading.Thread(
        target=_executar_etapa3, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


def _job_inicial_etapa4():
    return {
        "etapa": "audio",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Iniciando obtencao do audio da narracao...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }


def _executar_etapa4(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/4_obter_audio.py como subprocess, atualizando
    `jobs[projeto_id]` a cada linha `@PROGRESSO {...}` emitida - mesmo
    padrao de `_executar_etapa1`/`_executar_etapa2`/`_executar_etapa3`.
    Disparada por POST /projetos/<id>/aprovar_roteiro (quando a origem do
    audio nao e' "depois") ou pelo retry manual POST
    /projetos/<id>/gerar_audio.

    Se a Etapa 4 concluir com sucesso, dispara a Etapa 5 (planejamento de
    edicao) em seguida, na MESMA thread - mesmo fluxo continuo de
    _executar_etapa1/_executar_etapa2 (CLAUDE.md secao 4). Se a Etapa 4
    falhar, o pipeline para ali - a Etapa 5 nunca roda sem narracao."""
    script = BASE_DIR / "scripts" / "4_obter_audio.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]

    _persistir_job(
        pasta_projeto,
        status="em_andamento",
        etapa_atual="audio",
        data_inicio_audio=datetime.now().isoformat(),
    )

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        job["status"] = "erro"
        job["erro"] = f"Falha ao iniciar a etapa de audio: {exc}"
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="audio",
            data_fim=datetime.now().isoformat(),
            tipo_erro="falha_ao_iniciar",
            mensagem_usuario=job["erro"],
            log_erro=job["erro"],
        )
        return

    _consumir_progresso_subprocess(processo, job)

    if processo.returncode == 0:
        job["status"] = "concluido"
        job["proxima_etapa"] = "geracao_clipes"
        _persistir_job(
            pasta_projeto,
            status="concluido",
            etapa_atual="audio",
            proxima_etapa="geracao_clipes",
            data_fim=datetime.now().isoformat(),
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )
        _encadear_etapa5(projeto_id, pasta_projeto)
    else:
        job["status"] = "erro"
        job["erro"] = job.get("mensagem_usuario") or job.get("detalhe") or "Etapa de audio falhou."
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="audio",
            data_fim=datetime.now().isoformat(),
            tipo_erro=job.get("tipo_erro"),
            mensagem_usuario=job["erro"],
            log_erro="\n".join(job["log"][-40:]),
        )


def _disparar_etapa4(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = _job_inicial_etapa4()
    thread = threading.Thread(
        target=_executar_etapa4, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


def _job_inicial_etapa5():
    return {
        "etapa": "geracao_clipes",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Iniciando geracao de clipes...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }


def _encadear_etapa5(projeto_id: str, pasta_projeto: Path):
    """Dispara a Etapa 5 (geracao de clipes por selecao aleatoria de
    trechos) logo apos a Etapa 4 (audio da narracao) concluir com sucesso,
    na MESMA thread (fluxo continuo audio -> geracao de clipes, CLAUDE.md
    secao 4). Funcao separada de `_executar_etapa4` de proposito - mesmo
    espirito de `_encadear_etapa2`/`_encadear_etapa3`: os testes que
    querem isolar o comportamento da Etapa 4 sozinha fazem monkeypatch
    desta funcao inteira, em vez de so `_executar_etapa5`."""
    jobs[projeto_id] = _job_inicial_etapa5()
    _executar_etapa5(projeto_id, pasta_projeto)


def _executar_etapa5(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/5_gerar_clipes.py como subprocess, atualizando
    `jobs[projeto_id]` a cada linha `@PROGRESSO {...}` emitida - mesmo
    padrao de `_executar_etapa1`/.../`_executar_etapa4`. Chamada tanto
    automaticamente por `_executar_etapa4` (fluxo continuo audio ->
    geracao de clipes) quanto pelo disparo manual `_disparar_etapa5` (POST
    /projetos/<id>/gerar_clipes).

    Esta etapa consolida a antiga cadeia dividir_cenas (5) ->
    montar_timeline (6) -> renderizar_clipes (7) num unico script - sem
    deteccao de cena, dedupe visual nem Vision (ver CLAUDE.md). Ao
    concluir com sucesso, o job fica `aguardando_legendas` e a Etapa 6
    (montagem final - scripts/6_montar_video.py) e' disparada em seguida,
    na MESMA thread (fluxo continuo, mesmo padrao de
    _executar_etapa1/.../_executar_etapa4)."""
    script = BASE_DIR / "scripts" / "5_gerar_clipes.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]

    _persistir_job(
        pasta_projeto,
        status="em_andamento",
        etapa_atual="geracao_clipes",
        data_inicio_geracao_clipes=datetime.now().isoformat(),
    )

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        job["status"] = "erro"
        job["erro"] = f"Falha ao iniciar a etapa de geracao de clipes: {exc}"
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="geracao_clipes",
            data_fim=datetime.now().isoformat(),
            tipo_erro="falha_ao_iniciar",
            mensagem_usuario=job["erro"],
            log_erro=job["erro"],
        )
        return

    _consumir_progresso_subprocess(processo, job)

    if processo.returncode == 0:
        job["status"] = "aguardando_legendas"
        job["etapa"] = "legendas"
        job["proxima_etapa"] = "montagem"
        _persistir_job(
            pasta_projeto,
            status="aguardando_legendas",
            etapa_atual="legendas",
            proxima_etapa="montagem",
            data_fim=datetime.now().isoformat(),
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )
        _apos_etapa5_sucesso(projeto_id, pasta_projeto)
    else:
        job["status"] = "erro"
        job["erro"] = job.get("mensagem_usuario") or job.get("detalhe") or "Etapa de geracao de clipes falhou."
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="geracao_clipes",
            data_fim=datetime.now().isoformat(),
            tipo_erro=job.get("tipo_erro"),
            mensagem_usuario=job["erro"],
            log_erro="\n".join(job["log"][-40:]),
        )


def _disparar_etapa5(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = _job_inicial_etapa5()
    thread = threading.Thread(
        target=_executar_etapa5, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


def _job_inicial_etapa6():
    return {
        "etapa": "montagem",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Iniciando montagem do video final...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }


def _executar_etapa6(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/6_montar_video.py como subprocess, atualizando
    `jobs[projeto_id]` a cada linha `@PROGRESSO {...}` emitida - mesmo
    padrao das etapas anteriores. Chamada automaticamente por
    `_executar_etapa5` (fluxo continuo geracao de clipes -> montagem) ou
    pelo disparo manual `_disparar_etapa6` (POST /projetos/<id>/montar_video).

    Em sucesso, encadeia direto na Etapa 7 (preparacao de thumbnail,
    `_encadear_etapa7`) na MESMA thread - mesmo espirito do encadeamento
    geracao de clipes -> montagem. O job so' chega a `concluido` depois
    que o usuario confirma um template na tela de thumbnail (Grupo G)."""
    script = BASE_DIR / "scripts" / "6_montar_video.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]

    _persistir_job(
        pasta_projeto,
        status="em_andamento",
        etapa_atual="montagem",
        data_inicio_montagem=datetime.now().isoformat(),
    )

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        job["status"] = "erro"
        job["erro"] = f"Falha ao iniciar a etapa de montagem: {exc}"
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="montagem",
            data_fim=datetime.now().isoformat(),
            tipo_erro="falha_ao_iniciar",
            mensagem_usuario=job["erro"],
            log_erro=job["erro"],
        )
        return

    _consumir_progresso_subprocess(processo, job)

    if processo.returncode == 0:
        if _ler_configuracao_video(pasta_projeto)["gerar_thumbnail"]:
            _encadear_etapa7(projeto_id, pasta_projeto)
        else:
            _pular_etapa7_e_concluir(projeto_id, pasta_projeto)
    else:
        job["status"] = "erro"
        job["erro"] = job.get("mensagem_usuario") or job.get("detalhe") or "Etapa de montagem do video falhou."
        _persistir_job(
            pasta_projeto,
            status="erro",
            etapa_atual="montagem",
            data_fim=datetime.now().isoformat(),
            tipo_erro=job.get("tipo_erro"),
            mensagem_usuario=job["erro"],
            log_erro="\n".join(job["log"][-40:]),
        )


def _pular_etapa7_e_concluir(projeto_id: str, pasta_projeto: Path):
    """Etapa 7 (thumbnail) desativada por projeto
    (entrada/configuracao_video.json `gerar_thumbnail=False`, Grupo C) -
    pula direto pra "concluido" ao inves de passar por
    "aguardando_thumbnail". Usa o MESMO par status/etapa_atual="concluido"
    que projetos criados ANTES da Etapa 7 existir usam (ver
    STATUS_MIGRATION/ETAPA_ATUAL_MIGRATION - "concluido" e' valor terminal
    valido de proposito, nunca precisou de chave de migracao) -
    `_parsear_pipeline_steps` ja marca toda PIPELINE_ETAPAS como "done"
    nesse status, e filtra o circulo "thumbnail" da lista quando
    `gerar_thumbnail=False` (ver `_parsear_pipeline_steps`)."""
    jobs[projeto_id] = {
        "etapa": "concluido",
        "status": "concluido",
        "pct": 100.0,
        "detalhe": "Concluido - thumbnail desativada para este projeto.",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
    }
    _persistir_job(
        pasta_projeto,
        status="concluido",
        etapa_atual="concluido",
        proxima_etapa=None,
        data_fim=datetime.now().isoformat(),
        tipo_erro=None,
        mensagem_usuario=None,
        log_erro=None,
    )


def _encadear_etapa6(projeto_id: str, pasta_projeto: Path):
    """Dispara a Etapa 6 (montagem final do video) logo apos a Etapa 5
    (geracao de clipes) concluir com sucesso, na MESMA thread - mesmo
    espirito de `_encadear_etapa5`: funcao separada para os testes poderem
    isolar o comportamento da Etapa 5 sozinha via monkeypatch."""
    jobs[projeto_id] = _job_inicial_etapa6()
    _executar_etapa6(projeto_id, pasta_projeto)


def _disparar_etapa6(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = _job_inicial_etapa6()
    thread = threading.Thread(
        target=_executar_etapa6, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


def _job_inicial_etapa7():
    return {
        "etapa": "thumbnail",
        "status": "em_andamento",
        "pct": 0.0,
        "detalhe": "Preparando candidatos de thumbnail...",
        "eta_s": None,
        "log": [],
        "avisos": [],
        "erros": [],
        "erro": None,
        "mensagem_usuario": None,
        "tipo_erro": None,
        "proxima_etapa": None,
        "etapa7_falhou": False,
    }


def _executar_etapa7(projeto_id: str, pasta_projeto: Path):
    """Roda scripts/7_thumbnail.py como subprocess (Grupos A/B/C/D -
    candidatos com rosto/cenario via Haar cascade, identificacao por
    Vision, metadados via IA) - mesmo padrao de consumo de `@PROGRESSO`
    das etapas anteriores. Chamada automaticamente por `_executar_etapa6`
    quando a montagem final termina com sucesso.

    DIFERENTE das etapas anteriores: falha aqui NUNCA vira status="erro"
    (o job sempre termina em "aguardando_thumbnail", nunca trava o
    pipeline - o video final ja esta pronto e o usuario sempre pode
    completar a thumbnail a mao - upload de foto propria, digitar o
    texto - se a geracao automatica falhar ou nao rodar, ex: sem
    ANTHROPIC_API_KEY configurada).

    Bug corrigido pos-Sessao 21: essa regra de "nunca falhar o job" tinha
    virado "esconder que a etapa nao rodou" - `job["status"]` era gravado
    como "aguardando_thumbnail" incondicionalmente, mesmo quando o
    subprocess saia com returncode != 0 (caso real: ModuleNotFoundError
    do import quebrado em scripts/7_thumbnail.py rodando como subprocess -
    ver correcao la). A tela de revisao ficava com grids vazios sem
    explicacao nenhuma. Agora o resultado do subprocess (`processo.
    returncode`) e' checado: falha vira `job["etapa7_falhou"] = True` +
    `mensagem_usuario`/`tipo_erro`/`log_erro` preenchidos (stderr esta no
    proprio job["log"], porque o subprocess roda com stderr=STDOUT) -
    "nunca falhar o job" continua valendo (status fica
    "aguardando_thumbnail", o usuario chega na tela de revisao normal),
    mas a falha nunca fica escondida (ver templates/status.html e
    templates/thumbnail.html, que leem esse flag)."""
    script = BASE_DIR / "scripts" / "7_thumbnail.py"
    comando = [sys.executable, str(script), str(pasta_projeto)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    job = jobs[projeto_id]
    falhou = False
    mensagem_falha = None

    try:
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        _consumir_progresso_subprocess(processo, job)
        if processo.returncode != 0:
            falhou = True
            mensagem_falha = (
                job.get("mensagem_usuario")
                or job.get("detalhe")
                or f"scripts/7_thumbnail.py terminou com codigo {processo.returncode}."
            )
    except OSError as exc:
        falhou = True
        mensagem_falha = f"Falha ao iniciar a preparacao da thumbnail: {exc}"
        job["log"].append(mensagem_falha)

    job["status"] = "aguardando_thumbnail"
    job["etapa"] = "thumbnail"
    job["proxima_etapa"] = None
    job["etapa7_falhou"] = falhou
    if falhou:
        job["erro"] = mensagem_falha
        job["mensagem_usuario"] = mensagem_falha
        job["tipo_erro"] = job.get("tipo_erro") or "etapa7_falhou"
        job["detalhe"] = (
            "A preparacao automatica da thumbnail falhou. Revise manualmente ou tente novamente."
        )
    _persistir_job(
        pasta_projeto,
        status="aguardando_thumbnail",
        etapa_atual="thumbnail",
        proxima_etapa=None,
        data_fim=datetime.now().isoformat(),
        etapa7_falhou=falhou,
        tipo_erro=job.get("tipo_erro") if falhou else None,
        mensagem_usuario=mensagem_falha if falhou else None,
        log_erro="\n".join(job["log"][-40:]) if falhou else None,
    )


def _encadear_etapa7(projeto_id: str, pasta_projeto: Path):
    """Dispara a Etapa 7 (preparacao de thumbnail) logo apos a Etapa 6
    (montagem) concluir com sucesso, na MESMA thread - mesmo espirito de
    `_encadear_etapa6`."""
    jobs[projeto_id] = _job_inicial_etapa7()
    _executar_etapa7(projeto_id, pasta_projeto)


def _disparar_etapa7(projeto_id: str, pasta_projeto: Path) -> threading.Thread:
    jobs[projeto_id] = _job_inicial_etapa7()
    thread = threading.Thread(
        target=_executar_etapa7, args=(projeto_id, pasta_projeto), daemon=True
    )
    _threads[projeto_id] = thread
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Sincronizacao inteligente com IA (Feature A) e reorganizacao manual de
# clipes (Feature B) - ambas opt-in por projeto (entrada/configuracao_video.json),
# rodam entre a Etapa 5 (geracao de clipes) e a Etapa 6 (montagem final).
# ---------------------------------------------------------------------------


def _executar_sincronizacao_ia(projeto_id: str, pasta_projeto: Path, duracao_alvo_s: float):
    """Roda a Feature A (scripts.sincronizador_visual.sincronizar_projeto)
    dentro da MESMA thread de background da Etapa 5 - nao e' um subprocess
    (motivo no docstring do modulo sincronizador_visual: reusar a thread
    evita reimplementar o parsing de @PROGRESSO so' para este passo
    opcional). Nunca falha a Etapa 5, ja concluida com sucesso: qualquer
    problema (chave ausente, chamada de API com erro) e' so' registrado no
    log do job, sem interromper o fluxo para a Etapa 6 (ou para a pausa de
    reorganizacao manual - CLAUDE.md/Veo3 "nunca falhar o video inteiro por
    causa de uma cena").

    Atualiza `job["detalhe"]` no inicio e no fim (Grupo C/G3 - antes desta
    correcao, `detalhe` ficava parado no texto da Etapa 5 durante toda essa
    janela, que pode levar dezenas de segundos com a Feature A ativa -
    chamadas Vision - dando a impressao de tela travada mesmo com o
    polling funcionando)."""
    job = jobs.get(projeto_id)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if job is not None:
            job.setdefault("log", []).append(
                "Sincronizacao com IA pulada: ANTHROPIC_API_KEY nao configurada."
            )
        return

    if job is not None:
        job.setdefault("log", []).append("Sincronizando clipes com IA (Feature A)...")
        job["detalhe"] = "Sincronizando clipes com IA (Feature A)..."

    modelo = os.environ.get("ANTHROPIC_MODEL") or sincronizador_visual.MODELO_PADRAO
    try:
        resultado = sincronizador_visual.sincronizar_projeto(pasta_projeto, api_key, duracao_alvo_s, modelo)
    except Exception as exc:  # Feature A nunca derruba o pipeline principal
        resultado = {"sucesso": False, "erro": str(exc)}

    if job is None:
        return
    if resultado.get("sucesso"):
        mensagem = (
            f"Sincronizacao com IA: {resultado.get('swaps_aplicados', 0)} swap(s) aplicado(s) "
            f"({resultado.get('ancoras_encontradas', 0)} ancora(s) encontrada(s)), "
            f"custo ~${resultado.get('custo_usd_total', 0.0):.4f}."
        )
    else:
        mensagem = f"Sincronizacao com IA falhou (video segue normalmente): {resultado.get('erro')}"
    job.setdefault("log", []).append(mensagem)
    job["detalhe"] = mensagem


def _gerar_thumbnails_clipes(pasta_projeto: Path, max_workers: int = 8) -> int:
    """Gera (ou reusa, se ja existir) uma thumbnail JPG por clipe em
    clipes/thumbs/<clipe_id>.jpg - usado pela tela de reorganizacao manual
    (Feature B). Paralelizado com ThreadPoolExecutor: cada tarefa so espera
    um subprocess ffmpeg terminar (I/O-bound, GIL liberado durante a
    espera) - ThreadPoolExecutor e' apropriado aqui; ProcessPoolExecutor
    pagaria overhead de serializar Path entre processos sem ganho real, ja
    que o trabalho pesado roda fora do processo Python de qualquer forma
    (extrair_frame_clipe so chama subprocess.run). Retorna quantas
    thumbnails foram geradas (exclui as que ja existiam). Nunca levanta
    excecao - clipe sem thumbnail gerada aqui e' gerado sob demanda pela
    rota /thumb_clipe."""
    indice = _ler_json_seguro(pasta_projeto / "clipes" / "indice.json") or {}
    clipes = indice.get("clipes") or []
    pasta_clipes = pasta_projeto / "clipes"
    pasta_thumbs = pasta_clipes / "thumbs"

    pendentes = []
    for clipe in clipes:
        clipe_id = clipe.get("clipe_id")
        arquivo = clipe.get("arquivo")
        if not clipe_id or not arquivo:
            continue
        caminho_thumb = pasta_thumbs / f"{clipe_id}.jpg"
        if caminho_thumb.exists():
            continue
        pendentes.append((pasta_clipes / arquivo, caminho_thumb))

    if not pendentes:
        return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        resultados = list(
            executor.map(lambda par: sincronizador_visual.extrair_frame_clipe(par[0], par[1]), pendentes)
        )
    return sum(1 for ok in resultados if ok)


def _gerar_thumbnails_clipes_em_background(pasta_projeto: Path):
    """Dispara `_gerar_thumbnails_clipes` numa thread daemon separada -
    Feature B nao precisa esperar as thumbnails prontas para pausar em
    `aguardando_reorganizacao` (o usuario pode demorar minutos para abrir a
    tela; qualquer thumbnail que ainda nao exista quando ele abrir e'
    gerada sob demanda pela rota /thumb_clipe)."""
    thread = threading.Thread(target=_gerar_thumbnails_clipes, args=(pasta_projeto,), daemon=True)
    thread.start()


def _apos_etapa5_sucesso(projeto_id: str, pasta_projeto: Path):
    """Decide o que acontece entre a Etapa 5 (geracao de clipes) e a Etapa
    6 (montagem final): Feature A (sincronizacao inteligente com IA) e/ou
    Feature B (reorganizacao manual de clipes), ambas opt-in por projeto
    via entrada/configuracao_video.json. Chamada por `_executar_etapa5` no
    lugar de `_encadear_etapa6` direto - funcao isolada de proposito (mesmo
    espirito de `_encadear_etapaN`: permite que os testes monkeypatchem so
    este passo, sem precisar mockar a Etapa 5 inteira).

    Comportamento default (ambas as features desligadas - inclusive todo
    projeto criado antes delas, onde configuracao_video.json esta ausente
    ou sem os campos novos): chama `_encadear_etapa6` direto, SEM tocar no
    job/estado ja persistido por `_executar_etapa5` logo antes desta
    chamada - identico a como o pipeline se comportava antes desta
    feature (CLAUDE.md - nao alterar comportamento default)."""
    config = _ler_configuracao_video(pasta_projeto)

    if config["sincronizacao_ia_ativa"]:
        _executar_sincronizacao_ia(projeto_id, pasta_projeto, config["sincronizacao_duracao_s"])

    if config["reorganizacao_manual_ativa"]:
        _gerar_thumbnails_clipes_em_background(pasta_projeto)
        job = jobs.get(projeto_id)
        if job is not None:
            job["status"] = "aguardando_reorganizacao"
            job["etapa"] = "geracao_clipes"
            job["proxima_etapa"] = "montagem"
            job["detalhe"] = "Clipes prontos - aguardando reorganizacao manual."
        _persistir_job(
            pasta_projeto,
            status="aguardando_reorganizacao",
            etapa_atual="geracao_clipes",
            proxima_etapa="montagem",
            data_fim=datetime.now().isoformat(),
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )
        return

    _encadear_etapa6(projeto_id, pasta_projeto)


# ---------------------------------------------------------------------------
# Slots por posicao (Feature B - reorganizacao manual com drag livre,
# timeline horizontal). Duplicado de proposito de
# scripts/6_montar_video.py:_migrar_slots_clipes/_precisa_de_trim/
# construir_filtro_complexo_trim (CLAUDE.md secao 9 - sem utils
# compartilhado entre scripts/server.py).
# ---------------------------------------------------------------------------


def _migrar_slots_clipes(clipes: list) -> list:
    """Retorna uma NOVA lista de clipes com duracao_slot_s/inicio_slot_s/
    fim_slot_s sempre presentes. Preserva duracao_slot_s se ja existir
    (gravado por /reordenar_clipes apos um drag); senao cai no fallback
    duracao_slot_s = duracao_s, reproduzindo a semantica de antes desta
    feature - todo indice.json de projeto anterior a esta sessao (ou que
    nunca passou por um drag) cai neste fallback em 100% dos clipes.
    inicio_slot_s/fim_slot_s NUNCA sao lidos do disco - sempre recalculados
    como soma cumulativa de duracao_slot_s na ordem ATUAL da lista (a ordem
    da lista e' a ordem da timeline)."""
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
    """True se algum clipe ocupa hoje uma posicao (slot) de duracao
    diferente da duracao real do proprio arquivo - so' acontece depois de
    uma reorganizacao manual. Projeto que nunca passou pela tela de
    reorganizacao: sempre False."""
    return any(
        abs((clipe.get("duracao_slot_s") or 0.0) - (clipe.get("duracao_s") or 0.0)) > tolerancia_s
        for clipe in clipes_migrados
    )


def _construir_filtro_complexo_trim(clipes_migrados: list) -> str:
    """String do filtro (trim de cada posicao pro seu duracao_slot_s +
    concat) para `-filter_complex`. Ver nota em
    scripts/6_montar_video.py:construir_filtro_complexo_trim sobre por que
    NAO usa `-filter_complex_script` (indisponivel no build de ffmpeg deste
    produto) - por isso o chamador sempre processa em lotes pequenos
    (`_TAMANHO_LOTE_PREVIEW`)."""
    rotulos = [f"v{i}" for i in range(len(clipes_migrados))]
    partes = [
        f"[{i}:v]trim=duration={clipe['duracao_slot_s']:.3f},setpts=PTS-STARTPTS[{rotulo}]"
        for i, (clipe, rotulo) in enumerate(zip(clipes_migrados, rotulos))
    ]
    entradas_concat = "".join(f"[{rotulo}]" for rotulo in rotulos)
    partes.append(f"{entradas_concat}concat=n={len(rotulos)}:v=1:a=0[outv]")
    return ";".join(partes)


_TAMANHO_LOTE_PREVIEW = 40


def _concatenar_com_slots(pasta_clipes: Path, clipes_migrados: list, pasta_temp: Path, caminho_saida: Path) -> bool:
    """Concatena clipes respeitando a duracao de SLOT de cada posicao
    (nao a duracao real do arquivo) - usado pelo preview provisorio
    (Feature B) para refletir corretamente uma reorganizacao manual feita
    via drag. Caminho rapido (`-c copy`, identico a antes desta sessao)
    quando nenhum clipe precisa ser cortado; caminho com `trim` (reencode,
    em lotes pequenos - mesmo motivo de scripts/6_montar_video.py) quando
    algum drag colocou um clipe numa posicao de duracao diferente da dele.
    Nunca levanta excecao."""
    if not clipes_migrados:
        return False

    try:
        pasta_temp.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    if not _precisa_de_trim(clipes_migrados):
        caminho_lista = pasta_temp / "preview_concat_list.txt"
        try:
            linhas = [f"file '{(pasta_clipes / clipe['arquivo']).resolve().as_posix()}'" for clipe in clipes_migrados]
            caminho_lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        except (OSError, KeyError):
            return False
        try:
            resultado = subprocess.run(
                ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(caminho_lista), "-c", "copy", str(caminho_saida)],
                capture_output=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        return resultado.returncode == 0 and caminho_saida.exists()

    lotes = [clipes_migrados[i : i + _TAMANHO_LOTE_PREVIEW] for i in range(0, len(clipes_migrados), _TAMANHO_LOTE_PREVIEW)]
    caminhos_lotes = []
    for indice_lote, lote in enumerate(lotes):
        caminho_lote = pasta_temp / f"preview_filter_lote_{indice_lote:03d}.mp4"
        comando = ["ffmpeg", "-hide_banner", "-y"]
        for clipe in lote:
            comando += ["-i", str((pasta_clipes / clipe["arquivo"]).resolve())]
        comando += [
            "-filter_complex", _construir_filtro_complexo_trim(lote),
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            str(caminho_lote),
        ]
        try:
            resultado = subprocess.run(comando, capture_output=True, timeout=300)
        except (subprocess.TimeoutExpired, OSError):
            return False
        if resultado.returncode != 0 or not caminho_lote.exists():
            return False
        caminhos_lotes.append(caminho_lote)

    if len(caminhos_lotes) == 1:
        try:
            caminhos_lotes[0].replace(caminho_saida)
        except OSError:
            return False
        return caminho_saida.exists()

    caminho_lista_lotes = pasta_temp / "preview_concat_lotes_list.txt"
    try:
        linhas = [f"file '{caminho.resolve().as_posix()}'" for caminho in caminhos_lotes]
        caminho_lista_lotes.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    except OSError:
        return False
    try:
        resultado = subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(caminho_lista_lotes), "-c", "copy", str(caminho_saida)],
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return resultado.returncode == 0 and caminho_saida.exists()


def _hash_ordem_clipes(indice: dict) -> str:
    """Hash estavel da timeline atual - clipe_id de cada posicao MAIS os
    campos de slot (duracao_slot_s/inicio_slot_s) de cada posicao - usado
    para decidir se o preview provisorio (Feature B) esta desatualizado em
    relacao ao indice.json. Incluir os campos de slot (nao so' clipe_id) e'
    defesa em profundidade: hoje a ordem de clipe_id ja muda em qualquer
    reordenacao (o hash ja invalidaria so' com isso), mas se uma acao
    futura mudar a duracao de um slot sem mudar a ordem dos clipe_id, o
    cache do preview continua correto sem precisar tocar aqui de novo."""
    clipes_migrados = _migrar_slots_clipes(indice.get("clipes") or [])
    partes = [
        f"{clipe.get('clipe_id', '')}:{clipe['duracao_slot_s']:.3f}:{clipe['inicio_slot_s']:.3f}"
        for clipe in clipes_migrados
    ]
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


def _gerar_preview_video(pasta_projeto: Path, indice: dict) -> bool:
    """Gera preview.mp4: concat dos clipes na ordem ATUAL do indice
    (respeitando a duracao de SLOT de cada posicao - `_concatenar_com_slots`,
    Feature B) + mux com a narracao - sem legendas nem musica de fundo
    (preview serve so' para conferir a SEQUENCIA de clipes contra a
    narracao antes da montagem final de verdade, nao e' o video final).
    Mesmo padrao ffmpeg (concat + mux) de scripts/6_montar_video.py,
    duplicado aqui de proposito (CLAUDE.md secao 9) - roda direto no
    processo do servidor a pedido de uma rota, nao via subprocess de uma
    etapa numerada do pipeline. Nunca levanta excecao."""
    clipes = indice.get("clipes") or []
    if not clipes:
        return False

    pasta_clipes = pasta_projeto / "clipes"
    pasta_temp = pasta_projeto / "temp"

    clipes_migrados = _migrar_slots_clipes(clipes)
    caminho_concat = pasta_temp / "preview_concat.mp4"
    if not _concatenar_com_slots(pasta_clipes, clipes_migrados, pasta_temp, caminho_concat):
        return False

    caminho_narracao = pasta_projeto / "narracao.mp3"
    caminho_preview = pasta_projeto / "preview.mp4"
    if not caminho_narracao.exists():
        try:
            shutil.copyfile(caminho_concat, caminho_preview)
        except OSError:
            return False
        return True

    try:
        resultado_mux = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-y",
                "-i", str(caminho_concat),
                "-i", str(caminho_narracao),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                str(caminho_preview),
            ],
            capture_output=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return resultado_mux.returncode == 0 and caminho_preview.exists()


# Pixels por segundo de narracao na timeline horizontal (Feature B) -
# compartilhado (em espirito - JS tem sua propria copia da constante,
# CLAUDE.md secao 9) com a largura calculada aqui pro template e o cursor
# calculado em JS a partir do tempo do player de audio.
PX_POR_SEGUNDO_TIMELINE = 10
LARGURA_MINIMA_TIMELINE_PX = 24

# Tolerancia (segundos) entre a soma das duracoes de slot da timeline e a
# duracao real da narracao antes de avisar o usuario que os timestamps
# exibidos na tela de reorganizacao podem estar incorretos (sessao de
# correcoes UX GRUPO A).
TOLERANCIA_DIVERGENCIA_NARRACAO_S = 2.0

# Intervalo (segundos) das marcas da regua acima da timeline (GRUPO C).
INTERVALO_REGUA_S = 30.0


def _duracao_padrao_clipe_s() -> float:
    """Duracao (s) usada como fallback de POSICAO quando um clipe do
    indice.json nao tem `duracao_slot_s` nem `duracao_s` validos (GRUPO A -
    nunca deveria acontecer em indice.json gerado pela Etapa 5, mas a tela
    de reorganizacao precisa de *algum* numero para nao quebrar o calculo
    das posicoes seguintes). Media de CLIPE_DURACAO_MIN_S/MAX_S (CLAUDE.md
    secao 7, defaults 6.0/10.0) - a mesma faixa que a Etapa 5 sorteia para
    clipes novos, entao e' a melhor estimativa disponivel sem tocar
    ffmpeg/disco."""

    def _float_env(nome, default):
        valor = os.environ.get(nome)
        if not valor:
            return default
        try:
            return float(valor)
        except ValueError:
            return default

    minimo = _float_env("CLIPE_DURACAO_MIN_S", 6.0)
    maximo = _float_env("CLIPE_DURACAO_MAX_S", 10.0)
    return (minimo + maximo) / 2


def _montar_timeline_reorganizacao(clipes: list, descricoes_vision: dict, duracao_padrao_s: float = 8.0) -> tuple:
    """Monta (timeline, banco) para a tela de reorganizacao manual (Feature
    B - timeline horizontal com drag livre): `timeline` tem uma entrada por
    POSICAO (na ordem de clipes/indice.json, com duracao_slot_s/
    inicio_slot_s/fim_slot_s - `_migrar_slots_clipes`). `banco` e' a MESMA
    lista (cada posicao tem exatamente um clipe fisico distinto - a Etapa 5
    nunca gera clipe_id repetido, e reordenar so' permuta a lista, nunca
    duplica um clipe em duas posicoes), so' com layout de grid em vez de
    timeline - sem necessidade de dedupe.

    GRUPO A (sessao de correcoes UX): antes desta sessao, uma posicao sem
    `duracao_slot_s` nem `duracao_s` validos virava silenciosamente 0.0 em
    `_migrar_slots_clipes` - toda posicao seguinte ficava com timestamp
    inventado sem o usuario saber. Aqui, ANTES de migrar os slots, toda
    posicao sem duracao valida recebe `duracao_padrao_s` explicitamente e e'
    marcada `duracao_aproximada: True` - o template usa essa marca para
    avisar a partir de qual posicao os tempos sao estimativas."""
    clipes_com_fallback = []
    posicoes_aproximadas = set()
    for posicao, clipe in enumerate(clipes):
        tem_duracao_valida = bool(clipe.get("duracao_slot_s")) or bool(clipe.get("duracao_s"))
        if tem_duracao_valida:
            clipes_com_fallback.append(clipe)
            continue
        novo = dict(clipe)
        novo["duracao_slot_s"] = duracao_padrao_s
        clipes_com_fallback.append(novo)
        posicoes_aproximadas.add(posicao)

    clipes_migrados = _migrar_slots_clipes(clipes_com_fallback)
    timeline = []
    for posicao, clipe in enumerate(clipes_migrados):
        clipe_id = clipe.get("clipe_id")
        descricao = descricoes_vision.get(clipe_id, "")
        timeline.append(
            {
                "posicao": posicao,
                "clipe_id": clipe_id,
                "duracao_slot_s": clipe["duracao_slot_s"],
                "inicio_slot_s": clipe["inicio_slot_s"],
                "fim_slot_s": clipe["fim_slot_s"],
                "largura_px": max(
                    LARGURA_MINIMA_TIMELINE_PX, round(clipe["duracao_slot_s"] * PX_POR_SEGUNDO_TIMELINE)
                ),
                "tempo_formatado": _formatar_mmss(clipe["inicio_slot_s"]),
                "duracao_aproximada": posicao in posicoes_aproximadas,
                "descricao_vision": descricao,
                "descricao_busca": (descricao or "").lower(),
            }
        )
    return timeline, timeline


def _primeira_posicao_aproximada(timeline: list):
    """Menor `posicao` marcada `duracao_aproximada` (GRUPO A) - None se
    nenhuma posicao usou o fallback. Usado pelo template para avisar
    "tempos aproximados a partir da posicao N"."""
    for entrada in timeline:
        if entrada.get("duracao_aproximada"):
            return entrada["posicao"]
    return None


def _checar_divergencia_narracao(duracao_timeline_s: float, duracao_narracao_s):
    """GRUPO A: compara a duracao somada das posicoes da timeline com a
    duracao real da narracao (`clipes/indice.json:metadata.duracao_narracao_s`,
    gravado pela Etapa 5). `duracao_narracao_s` ausente/0 (indice.json de
    projeto anterior a essa metadata, ou sem narracao ainda) -> None, sem
    aviso (nao ha' o que comparar). Divergencia dentro de
    `TOLERANCIA_DIVERGENCIA_NARRACAO_S` -> None. Retorna a mensagem de aviso
    (str) ou None."""
    if not duracao_narracao_s:
        return None
    diferenca = abs((duracao_timeline_s or 0.0) - duracao_narracao_s)
    if diferenca <= TOLERANCIA_DIVERGENCIA_NARRACAO_S:
        return None
    return (
        f"A soma das duracoes dos clipes ({_formatar_mmss(duracao_timeline_s)}) diverge da duracao "
        f"real da narracao ({_formatar_mmss(duracao_narracao_s)}) em {diferenca:.1f}s - os "
        "timestamps abaixo podem nao refletir o audio real."
    )


def _duracao_narracao_do_projeto(pasta_projeto: Path, indice: dict):
    """Duracao (s) real da narracao, para `_checar_divergencia_narracao`.
    Fonte preferida: `clipes/indice.json:metadata.duracao_narracao_s`
    (gravada pela Etapa 5 - CLAUDE.md secao 5.7). Fallback:
    `narracao_alinhamento.json:duracao_s` (Etapa 4), para projetos cujo
    indice.json e' anterior a essa metadata. None se nenhuma das duas
    existir."""
    duracao = (indice.get("metadata") or {}).get("duracao_narracao_s")
    if duracao:
        return duracao
    alinhamento = _ler_json_seguro(pasta_projeto / "narracao_alinhamento.json") or {}
    return alinhamento.get("duracao_s")


def _montar_linhas_swap(swaps_aplicados: list, timeline: list) -> list:
    """Enriquece cada swap do log da Feature A (`sincronizacao_vision_log.json`)
    com a POSICAO ATUAL do clipe na timeline (GRUPO B, sessao de correcoes
    UX) - NUNCA usa `bloco_destino`/`posicao_s` do log, que sao um snapshot
    de quando a sincronizacao rodou e ficam errados assim que o usuario
    arrasta um clipe manualmente (Feature B). Resolve sempre pelo
    `clipe_id` contra a timeline corrente.

    Se o mesmo `clipe_id` aparecer em mais de uma posicao (nao deveria
    acontecer - `_montar_timeline_reorganizacao` nunca duplica clipe_id -
    mas a funcao nao confia nisso), resolve para a PRIMEIRA posicao
    (menor indice) e marca `outras_ocorrencias` (int) com a contagem das
    demais, para o template avisar em vez de apontar pro lugar errado em
    silencio. `posicao`/`tempo_formatado` ficam None se o clipe_id do swap
    nao existir mais na timeline atual."""
    posicoes_por_clipe: dict = {}
    for entrada in timeline:
        posicoes_por_clipe.setdefault(entrada["clipe_id"], []).append(entrada["posicao"])

    linhas = []
    for swap in swaps_aplicados or []:
        clipe_id = swap.get("clipe_id")
        posicoes = sorted(posicoes_por_clipe.get(clipe_id, []))
        if posicoes:
            posicao = posicoes[0]
            tempo_formatado = timeline[posicao]["tempo_formatado"]
        else:
            posicao = None
            tempo_formatado = None
        linhas.append(
            {
                **swap,
                "posicao": posicao,
                "tempo_formatado": tempo_formatado,
                "outras_ocorrencias": max(0, len(posicoes) - 1),
            }
        )
    return linhas


def _montar_regua_tempo(duracao_total_s: float, px_por_segundo: float, intervalo_s: float = INTERVALO_REGUA_S) -> list:
    """Marcas da regua de tempo acima da timeline (GRUPO C) a cada
    `intervalo_s` segundos, da posicao 0 ate `duracao_total_s` (inclusive).
    Lista vazia se a timeline nao tem duracao (projeto sem clipes)."""
    if not duracao_total_s or duracao_total_s <= 0:
        return []
    marcas = []
    tempo = 0.0
    while tempo <= duracao_total_s + 0.001:
        marcas.append({"tempo_formatado": _formatar_mmss(tempo), "left_px": round(tempo * px_por_segundo)})
        tempo += intervalo_s
    return marcas


def create_app(env_path=None):
    env_path = Path(env_path) if env_path else DEFAULT_ENV_PATH
    if env_path.exists():
        load_dotenv(env_path, override=True)

    app = Flask(__name__)
    # Chave fixa (nao secreta de verdade) so' para assinar o cookie de sessao
    # usado por flash() - app e' local/single-user (CLAUDE.md secao 1), sem
    # dado sensivel trafegando em sessao.
    app.secret_key = "broll-foundry-local-flash"
    app.config["ENV_PATH"] = env_path
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_BYTES
    app.config["BANNERS"] = _calcular_banners()
    app.config["AMBIENTE"] = _calcular_ambiente()

    # Filtros Jinja de label amigavel (scripts/labels_ui.py) - so' para
    # EXIBICAO nos templates, nunca usar em logica/comparacao de string.
    app.jinja_env.filters["label_status"] = label_status
    app.jinja_env.filters["label_etapa"] = label_etapa
    app.jinja_env.filters["label_tipo_projeto"] = label_tipo_projeto
    app.jinja_env.filters["label_provedor_tts"] = label_provedor_tts
    AMBIENTE_ATUAL.clear()
    AMBIENTE_ATUAL.update(app.config["AMBIENTE"])

    @app.context_processor
    def _injetar_banners():
        banners = app.config.get(
            "BANNERS", {"libs_desatualizadas": [], "ffmpeg_disponivel": True}
        )
        dispensados_raw = request.cookies.get("banners_dispensados", "")
        dispensados = set(filter(None, dispensados_raw.split(",")))
        libs_visiveis = [
            lib
            for lib in banners["libs_desatualizadas"]
            if lib["nome"] not in dispensados
        ]
        ambiente_atual = app.config.get("AMBIENTE") or {}
        compatibilidade = ambiente_atual.get("compatibilidade") or {}
        return {
            "banner_libs_desatualizadas": libs_visiveis,
            # Banner de ffmpeg ausente e' sempre visivel (nao-dispensavel,
            # CLAUDE.md secao 18.2) - bloqueia o pipeline de verdade, ao
            # contrario de uma lib so velha.
            "banner_ffmpeg_ausente": not banners["ffmpeg_disponivel"],
            # Banner de ambiente NVIDIA/CUDA incompativel (CLAUDE.md secao
            # 13/18) - tambem nao-dispensavel: bloqueia a Etapa 2 de
            # verdade, o usuario precisa ver isso em toda pagina ate
            # corrigir o ambiente.
            "banner_ambiente_incompativel": not compatibilidade.get("atende_minimo", True),
            "ambiente_gpu": ambiente_atual.get("gpu") or {},
            "ambiente_compatibilidade": compatibilidade,
            "ambiente_modelo_recomendado": ambiente_atual.get("modelo_recomendado"),
            "ambiente_versao": _ler_versao(),
        }

    @app.route("/banner/dispensar/<nome_lib>", methods=["POST"])
    def dispensar_banner(nome_lib):
        destino = request.referrer or url_for("home")
        resposta = redirect(destino)
        dispensados_raw = request.cookies.get("banners_dispensados", "")
        dispensados = set(filter(None, dispensados_raw.split(",")))
        dispensados.add(nome_lib)
        resposta.set_cookie("banners_dispensados", ",".join(sorted(dispensados)))
        return resposta

    def eh_pasta_de_projeto(caminho):
        if not os.path.isdir(caminho):
            return False
        return any(
            os.path.isfile(os.path.join(caminho, marcador))
            for marcador in MARCADORES_PROJETO
        )

    def listar_projetos():
        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        if not projetos_dir or not os.path.isdir(projetos_dir):
            return []
        projetos = []
        for nome in os.listdir(projetos_dir):
            caminho = os.path.join(projetos_dir, nome)
            if not eh_pasta_de_projeto(caminho):
                continue
            criado_em = _data_criacao_projeto(caminho)
            job_disco = _ler_job_json(Path(caminho))
            status_projeto = (job_disco or {}).get("status")
            perfil_nome = _ler_perfil_projeto(Path(caminho))
            projetos.append(
                {
                    "nome": nome,
                    "criado_em": criado_em,
                    "status": status_projeto,
                    "perfil": perfil_nome,
                }
            )
        # Mais recentes primeiro. Projetos com data desconhecida (edge case
        # raro - ver _data_criacao_projeto) vao pro fim da lista, nunca pro
        # topo (nao teria sentido mostrar um projeto de data incerta antes
        # de projetos com data confirmada).
        return sorted(
            projetos,
            key=lambda p: (
                p["criado_em"] is None,
                -p["criado_em"].timestamp() if p["criado_em"] else 0,
            ),
        )

    @app.route("/")
    def home():
        projetos = listar_projetos()
        return render_template(
            "home.html",
            projetos=projetos,
            stats=_calcular_stats_home(projetos),
            mensagem=request.args.get("mensagem"),
        )

    @app.route("/ajustes", methods=["GET", "POST"])
    def ajustes():
        salvo = False
        erro = None
        if request.method == "POST":
            valores_form = {
                campo: request.form.get(campo, "") for campo in CAMPOS_AJUSTES
            }

            caminho_bruto = valores_form.get("PROJETOS_DIR", "").strip()
            if caminho_bruto:
                caminho_normalizado = normalizar_caminho(caminho_bruto)
                valido, resultado = validar_caminho_projetos(caminho_normalizado)
                if not valido:
                    erro = resultado
                else:
                    valores_form["PROJETOS_DIR"] = resultado

            if erro:
                # Mantem na tela os valores que o usuario acabou de digitar
                # (mesmo os que nao foram gravados), em vez de voltar aos
                # valores antigos do .env - evita o usuario perder o que
                # tinha preenchido so por causa do PROJETOS_DIR invalido.
                return render_template(
                    "ajustes.html",
                    config=valores_form,
                    idiomas=IDIOMAS_SUPORTADOS,
                    modelos_anthropic=MODELOS_ANTHROPIC_SUPORTADOS,
                    provedores_tts=PROVEDORES_TTS,
                    opcoes_marca_dagua_canal=OPCOES_MARCA_DAGUA_CANAL,
                    marca_dagua_canal_meta=_ler_metadata_marca_dagua_global(),
                    salvo=False,
                    erro=erro,
                    **_contexto_ambiente_ajustes(valores_form),
                )

            for campo, valor in valores_form.items():
                set_key(str(app.config["ENV_PATH"]), campo, valor)
                os.environ[campo] = valor
            salvo = True
        config_atual = dotenv_values(app.config["ENV_PATH"])
        return render_template(
            "ajustes.html",
            config=config_atual,
            idiomas=IDIOMAS_SUPORTADOS,
            modelos_anthropic=MODELOS_ANTHROPIC_SUPORTADOS,
            provedores_tts=PROVEDORES_TTS,
            opcoes_marca_dagua_canal=OPCOES_MARCA_DAGUA_CANAL,
            marca_dagua_canal_meta=_ler_metadata_marca_dagua_global(),
            salvo=salvo,
            erro=erro,
            **_contexto_ambiente_ajustes(config_atual),
        )

    @app.route("/ajustes/marca_dagua/arquivo")
    def ajustes_marca_dagua_arquivo():
        """Serve o PNG da marca d'agua GLOBAL do canal (preview na tela de
        Ajustes) - 404 se nenhuma marca estiver configurada."""
        if not ARQUIVO_MARCA_DAGUA_GLOBAL.exists():
            abort(404)
        return send_from_directory(str(PASTA_CONFIG_GLOBAL), ARQUIVO_MARCA_DAGUA_GLOBAL.name)

    @app.route("/ajustes/marca_dagua/upload", methods=["POST"])
    def ajustes_marca_dagua_upload():
        """Upload da marca d'agua GLOBAL do canal (secao "Marca d'agua do
        canal aplicada ao video final") - rota AJAX separada do form
        principal de Ajustes (que so' tem campos de texto), mesmo padrao do
        upload de sujeito da Etapa 7 (thumbnail_upload_sujeito). Arquivo
        salvo em local FIXO fora de qualquer projeto (PASTA_CONFIG_GLOBAL) -
        reaproveitado por todo projeto que nao sobrescrever com a propria
        marca (CLAUDE.md - configuracao_video.json marca_dagua_projeto)."""
        arquivo = request.files.get("arquivo")
        if arquivo is None or not arquivo.filename:
            return jsonify({"erro": "arquivo_ausente", "mensagem": "Envie um arquivo PNG."}), 400

        extensao = Path(arquivo.filename).suffix.lower()
        if extensao != ".png":
            return jsonify({"erro": "extensao_invalida", "mensagem": "A marca d'agua precisa ser um arquivo PNG."}), 400

        conteudo = arquivo.read()
        if not conteudo:
            return jsonify({"erro": "arquivo_vazio", "mensagem": "Arquivo vazio ou corrompido."}), 400
        if len(conteudo) > TAMANHO_MAX_MARCA_DAGUA_BYTES:
            return jsonify({"erro": "arquivo_grande", "mensagem": "Arquivo maior que o limite permitido (10MB)."}), 400

        valido, tem_alfa, mensagem_erro = _validar_png_marca_dagua(conteudo)
        if not valido:
            return jsonify({"erro": "png_invalido", "mensagem": mensagem_erro}), 400

        PASTA_CONFIG_GLOBAL.mkdir(parents=True, exist_ok=True)
        ARQUIVO_MARCA_DAGUA_GLOBAL.write_bytes(conteudo)
        metadata = {
            "nome_original": secure_filename(arquivo.filename) or "marca_dagua.png",
            "tem_alfa": tem_alfa,
            "data_upload": datetime.now(timezone.utc).isoformat(),
        }
        ARQUIVO_MARCA_DAGUA_GLOBAL_META.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        aviso = None if tem_alfa else "Este PNG nao tem canal alfa (transparencia) - a marca aparecera sobre um fundo opaco."
        return jsonify({"sucesso": True, "tem_alfa": tem_alfa, "aviso": aviso, "nome_original": metadata["nome_original"]})

    @app.route("/ajustes/marca_dagua/remover", methods=["POST"])
    def ajustes_marca_dagua_remover():
        """Remove a marca d'agua GLOBAL do canal (arquivo + metadata). Nao
        levanta erro se ja nao existir (idempotente - botao "Remover" pode
        ser clicado mais de uma vez em cliques rapidos sem quebrar)."""
        for caminho in (ARQUIVO_MARCA_DAGUA_GLOBAL, ARQUIVO_MARCA_DAGUA_GLOBAL_META):
            try:
                caminho.unlink(missing_ok=True)
            except OSError:
                pass
        return jsonify({"sucesso": True})

    @app.route("/novo", methods=["GET", "POST"])
    def novo():
        perfis_disponiveis = prompts_loader.listar_perfis()
        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            perfil = request.form.get("perfil", "").strip()

            # Tipo de projeto (CLAUDE.md secao 3, "Vídeos pré-gerados") -
            # "pipeline_completa" (default, todo o resto desta rota) ou
            # "videos_pre_gerados" (caminho totalmente separado, sem
            # download/transcricao/roteiro/audio/clipes - so upload +
            # montagem). Verificado ANTES de qualquer outro campo porque os
            # dois caminhos nao compartilham o resto da validacao.
            tipo_projeto = request.form.get("tipo_projeto", TIPO_PROJETO_PADRAO).strip() or TIPO_PROJETO_PADRAO
            if not validar_tipo_projeto(tipo_projeto):
                # Protecao contra manipulacao de request - o <input
                # type="radio"> do formulario so oferece os dois valores
                # validos.
                return (
                    render_template(
                        "novo_projeto.html",
                        idiomas=IDIOMAS_SUPORTADOS,
                        perfis=perfis_disponiveis,
                        opcoes_marca_dagua=OPCOES_MARCA_DAGUA,
                        gerar_thumbnail_padrao_ajustes=_gerar_thumbnail_padrao_ajustes(),
                        tem_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
                        tem_marca_dagua_canal_global=ARQUIVO_MARCA_DAGUA_GLOBAL.exists(),
                        erro={
                            "mensagem": f"Tipo de projeto '{tipo_projeto}' nao e' valido.",
                            "tipo": "tipo_projeto_invalido",
                            "campos": [],
                        },
                        form=_form_padrao_novo_projeto(nome, perfil, tipo_projeto),
                    ),
                    400,
                )
            if tipo_projeto == "videos_pre_gerados":
                return _tratar_novo_projeto_videos_pre_gerados(nome, perfil, perfis_disponiveis)

            # Overrides por projeto (idioma, estrategia de corte) - vazio
            # significa "usar o padrao dos ajustes" (CLAUDE.md secao 7).
            idioma = request.form.get("idioma", "").strip()
            estrategia_corte = request.form.get("estrategia_corte", "").strip()

            # Marca d'agua do canal (secao "Marca d'agua do canal aplicada
            # ao video final") - "canal"/"outra"/"nenhuma", campo
            # compartilhado entre os dois tipos de projeto (ver
            # novo_projeto.html). Validado logo abaixo, junto dos outros
            # radios do formulario.
            marca_dagua_projeto = (request.form.get("marca_dagua_projeto") or ORIGEM_MARCA_DAGUA_PROJETO_PADRAO).strip()
            arquivo_marca_dagua = request.files.get("marca_dagua_arquivo")

            # Opcoes da Etapa 6 (CLAUDE.md - montagem final): checkboxes do
            # formulario, gravadas em entrada/configuracao_video.json.
            configuracao_video = {
                "legendas_queimadas": request.form.get("legendas_queimadas") == "on",
                "marca_dagua_projeto": marca_dagua_projeto,
                # Musica de fundo saiu do formulario de Novo projeto e mora
                # agora na tela de revisao (Grupo B da sessao de UX - CLAUDE.md
                # secao 5.8) - aprovar_roteiro atualiza este campo depois.
                "com_musica_fundo": False,
                # Ajustes avancados opcionais - sincronizacao inteligente com
                # IA (Feature A) e reorganizacao manual de clipes (Feature
                # B), independentes entre si. Ambas desligadas por padrao -
                # comportamento identico ao historico quando nenhuma e'
                # marcada (CLAUDE.md - nao alterar comportamento default).
                "sincronizacao_ia_ativa": request.form.get("sincronizacao_ia_ativa") == "on",
                "sincronizacao_duracao_s": validators.normalizar_sincronizacao_duracao(
                    request.form.get("sincronizacao_duracao")
                ),
                "reorganizacao_manual_ativa": request.form.get("reorganizacao_manual_ativa") == "on",
                # Tamanho alvo do roteiro (secao "Investigar por que roteiro
                # fica curto") - passado adiante para scripts/3_gerar_roteiro.py,
                # que injeta o alvo no prompt de sistema. Sem efeito quando
                # origem_roteiro == "upload" (nao ha geracao via IA nesse
                # modo - o campo fica gravado mesmo assim por simplicidade,
                # so' nao e' consultado).
                "palavras_alvo": validators.normalizar_palavras_alvo(request.form.get("palavras_alvo")),
                "duracao_alvo_minutos": validators.normalizar_duracao_alvo_minutos(
                    request.form.get("duracao_alvo_minutos")
                ),
                # Preto-e-branco (secao "Grayscale" da sessao de correcoes
                # UX) - desligado por padrao, identico ao comportamento
                # historico quando nao marcado.
                "grayscale": request.form.get("grayscale") == "on",
                # Etapa 7 opcional (thumbnail) - checkbox do formulario vem
                # marcada por padrao (ver novo_projeto.html:
                # gerar_thumbnail_marcado), refletindo GERAR_THUMBNAIL_PADRAO
                # dos Ajustes. Projeto criado antes desta feature nunca passa
                # por aqui - cai no default True de _ler_configuracao_video.
                "gerar_thumbnail": request.form.get("gerar_thumbnail") == "on",
            }

            # Modo de fontes (CLAUDE.md secao 5.7.1-bis - feature de fontes
            # separadas): "unificado" (default, comportamento historico - uma
            # unica lista de links usada para transcricao E clipes) ou
            # "separado" (fontes de transcricao distintas das visuais, com
            # opcao de upload proprio para as visuais).
            modo_fontes = request.form.get("modo_fontes", "unificado").strip() or "unificado"

            # Origem do roteiro (feature de upload de roteiro pronto): "ia"
            # (default, comportamento historico) ou "upload" (usuario
            # fornece o texto pronto - pula transcricao e geracao via IA,
            # CLAUDE.md - todo link vira fonte visual, nunca ha fonte de
            # transcricao nesse modo, entao "separado" nao faz sentido aqui).
            origem_roteiro = request.form.get("origem_roteiro", "ia").strip() or "ia"
            if origem_roteiro == "upload":
                modo_fontes = "unificado"
            roteiro_texto = None

            erro = None
            links = []
            marcas_dagua = []
            tipo_uso_por_link = []
            uploads_validados = []
            pares_transcricao = []
            pares_visual = []

            if not validar_origem_roteiro(origem_roteiro):
                # Protecao contra manipulacao de request - o <input
                # type="radio"> do formulario so oferece "ia"/"upload".
                erro = {
                    "mensagem": f"Origem de roteiro '{origem_roteiro}' nao e' valida.",
                    "tipo": "origem_roteiro_invalida",
                    "campos": [],
                }
            elif not validar_modo_fontes(modo_fontes):
                # Protecao contra manipulacao de request - o <input
                # type="radio"> do formulario so oferece "unificado"/"separado".
                erro = {
                    "mensagem": f"Modo de fontes '{modo_fontes}' nao e' valido.",
                    "tipo": "modo_fontes_invalido",
                    "campos": [],
                }
            elif not validar_origem_marca_dagua_projeto(marca_dagua_projeto):
                # Protecao contra manipulacao de request - o <input
                # type="radio"> do formulario so oferece "canal"/"outra"/"nenhuma".
                erro = {
                    "mensagem": f"Origem de marca d'agua '{marca_dagua_projeto}' nao e' valida.",
                    "tipo": "marca_dagua_projeto_invalida",
                    "campos": [],
                }
            elif marca_dagua_projeto == "outra" and (not arquivo_marca_dagua or not arquivo_marca_dagua.filename):
                erro = {
                    "mensagem": "Envie um arquivo PNG para a marca d'agua, ou escolha outra opcao.",
                    "tipo": "marca_dagua_arquivo_ausente",
                    "campos": ["marca_dagua_arquivo"],
                }
            elif marca_dagua_projeto == "outra" and Path(arquivo_marca_dagua.filename).suffix.lower() != ".png":
                erro = {
                    "mensagem": "A marca d'agua precisa ser um arquivo PNG.",
                    "tipo": "marca_dagua_extensao_invalida",
                    "campos": ["marca_dagua_arquivo"],
                }
            elif marca_dagua_projeto == "outra":
                _conteudo_marca = arquivo_marca_dagua.read()
                arquivo_marca_dagua.seek(0)
                _valido_png, _tem_alfa_marca, _mensagem_png = _validar_png_marca_dagua(_conteudo_marca)
                if not _valido_png:
                    erro = {"mensagem": _mensagem_png, "tipo": "marca_dagua_png_invalido", "campos": ["marca_dagua_arquivo"]}

            # Intro/ending anexados ao video final (secao "Intro e ending
            # anexados ao video final", GRUPO A) - upload em arquivo
            # TEMPORARIO (nenhum projeto existe ainda neste ponto da
            # validacao) para checar legibilidade real via ffprobe;
            # _criar_pasta_projeto move pra dentro do projeto so' depois
            # que toda a validacao abaixo passa.
            caminho_temp_intro, caminho_temp_ending = None, None
            if not erro:
                caminho_temp_intro, _erro_intro_msg = _validar_e_preparar_upload_intro_ending(
                    request.files.get("intro_arquivo"), "intro"
                )
                if _erro_intro_msg:
                    erro = {"mensagem": _erro_intro_msg, "tipo": "intro_invalido", "campos": ["intro_arquivo"]}
            if not erro:
                caminho_temp_ending, _erro_ending_msg = _validar_e_preparar_upload_intro_ending(
                    request.files.get("ending_arquivo"), "ending"
                )
                if _erro_ending_msg:
                    erro = {"mensagem": _erro_ending_msg, "tipo": "ending_invalido", "campos": ["ending_arquivo"]}

            if not erro and modo_fontes == "separado":
                links_transcricao, marcas_transcricao, erro_transcricao = _processar_pares_link_marca(
                    request.form.getlist("links_transcricao[]"),
                    request.form.getlist("marcas_dagua_transcricao[]"),
                )
                links_visual, marcas_visual, erro_visual = _processar_pares_link_marca(
                    request.form.getlist("links_visual[]"),
                    request.form.getlist("marcas_dagua_visual[]"),
                )
                pares_transcricao = [
                    {"url": url, "marca": marca} for url, marca in zip(links_transcricao, marcas_transcricao)
                ]
                pares_visual = [
                    {"url": url, "marca": marca} for url, marca in zip(links_visual, marcas_visual)
                ]

                if erro_transcricao or erro_visual:
                    erro = {
                        "mensagem": erro_transcricao or erro_visual,
                        "tipo": "marcas_dagua_desalinhadas",
                        "campos": ["links"],
                    }
                else:
                    uploads_validados, erro_upload = _validar_uploads(request.files.getlist("uploads[]"))
                    if erro_upload:
                        erro = {"mensagem": erro_upload, "tipo": "upload_invalido", "campos": ["uploads"]}
                    elif not links_transcricao:
                        erro = {
                            "mensagem": "Cole ao menos um link de video para transcricao.",
                            "tipo": "transcricao_vazia",
                            "campos": ["links_transcricao"],
                        }
                    elif not links_visual and not uploads_validados:
                        erro = {
                            "mensagem": "Adicione ao menos uma fonte visual - um link ou um arquivo de upload.",
                            "tipo": "visual_vazio",
                            "campos": ["links_visual", "uploads"],
                        }
                    else:
                        links, marcas_dagua, tipo_uso_por_link = _mesclar_fontes_separadas(
                            links_transcricao, marcas_transcricao, links_visual, marcas_visual
                        )
            elif not erro:
                # `elif not erro` (nao `else`) - preserva o curto-circuito da
                # cadeia if/elif de validacao acima (origem_roteiro/
                # modo_fontes/marca_dagua_projeto): se qualquer uma daquelas
                # ja tiver marcado `erro`, este bloco de processamento de
                # links NUNCA deve rodar, exatamente como no `elif` original
                # que ligava esta etapa a validacao.
                # Modo unificado (default) - comportamento identico ao que
                # ja existia antes da feature de fontes separadas. Links +
                # marca d'agua por link (CLAUDE.md secao 5.7.1): o
                # formulario atual manda arrays paralelos
                # links[]/marcas_dagua[] (uma linha dinamica por link, cada
                # uma com seu dropdown de posicao). Retrocompatibilidade: um
                # POST direto com o campo unico "links" (textarea antiga,
                # uma URL por linha, sem marca d'agua) ainda e' aceito - vira
                # "nenhuma" para todo link.
                links_brutos = request.form.getlist("links[]")
                if links_brutos:
                    links, marcas_dagua, erro_links = _processar_pares_link_marca(
                        links_brutos, request.form.getlist("marcas_dagua[]")
                    )
                    if erro_links:
                        erro = {
                            "mensagem": erro_links,
                            "tipo": "marcas_dagua_desalinhadas",
                            "campos": ["links"],
                        }
                else:
                    links = [
                        linha.strip()
                        for linha in request.form.get("links", "").splitlines()
                        if linha.strip()
                    ]
                    marcas_dagua = ["nenhuma"] * len(links)
                tipo_uso_por_link = ["ambos"] * len(links)

            if origem_roteiro == "upload" and not erro:
                # Sem geracao via IA, nao ha porque transcrever nada - todo
                # link vira fonte visual (2_transcrever.py ja pula fontes
                # "visual", CLAUDE.md secao 5.7.2), mesmo que o modo de
                # fontes tivesse marcado "ambos"/"transcricao".
                tipo_uso_por_link = ["visual"] * len(links)

            nomes_perfis_validos = {p["nome"] for p in perfis_disponiveis}

            # Struct rica em vez de string simples (nao so a mensagem, mas
            # tambem uma categoria e os campos afetados) - permite extensoes
            # futuras (destacar o campo com erro, telemetria, etc) sem
            # quebrar o contrato do template (CLAUDE.md - correcao de UX,
            # Problema 3).
            if not erro:
                valido_nome, resultado_nome = validar_nome_projeto(nome)
                if not valido_nome:
                    erro = {"mensagem": resultado_nome, "tipo": "nome_invalido", "campos": ["nome"]}
                elif not perfil:
                    erro = {
                        "mensagem": "Selecione o tipo de conteudo do video.",
                        "tipo": "perfil_ausente",
                        "campos": ["perfil"],
                    }
                elif perfil not in nomes_perfis_validos:
                    # Protecao contra manipulacao de request (POST direto com
                    # um valor de perfil que nao existe em disco) - nunca
                    # confiar so na validacao client-side do <select>.
                    erro = {
                        "mensagem": f"O tipo de conteudo '{perfil}' nao e' valido.",
                        "tipo": "perfil_invalido",
                        "campos": ["perfil"],
                    }
                elif configuracao_video["gerar_thumbnail"] and not os.environ.get("OPENAI_API_KEY"):
                    # GRUPO C (simplificacao da Etapa 7 - CLAUDE.md): a
                    # geracao de thumbnail hoje SO' produz imagem de verdade
                    # via composicao pela OpenAI (gerar_composicao,
                    # scripts/imagem/openai.py) - sem OPENAI_API_KEY nao ha'
                    # como nunca produzir uma thumbnail de verdade neste
                    # projeto, entao a marcacao e' bloqueada aqui, antes de
                    # gastar nenhum recurso do pipeline. Projeto ja existente
                    # com a flag ligada e sem chave (ex: criado antes desta
                    # checagem, ou pelo caminho videos_pre_gerados, que nao
                    # tem este checkbox) nao quebra - a Etapa 7 so' informa a
                    # ausencia da chave na tela, o briefing continua
                    # disponivel pra uso externo (thumbnail.html).
                    erro = {
                        "mensagem": "A geracao de thumbnail exige chave da OpenAI configurada em Ajustes.",
                        "tipo": "thumbnail_sem_chave_openai",
                        "campos": ["gerar_thumbnail"],
                    }
                elif not links:
                    erro = {
                        "mensagem": "Cole ao menos um link de video.",
                        "tipo": "links_vazio",
                        "campos": ["links"],
                    }
                elif any(not validar_url_youtube(url) for url in links):
                    erro = {
                        "mensagem": "Um ou mais links nao parecem ser URLs validas do YouTube.",
                        "tipo": "url_invalida",
                        "campos": ["links"],
                    }
                elif any(not validar_marca_dagua(marca) for marca in marcas_dagua):
                    # Protecao contra manipulacao de request - o <select> so
                    # oferece as opcoes validas de OPCOES_MARCA_DAGUA.
                    erro = {
                        "mensagem": "Uma das opcoes de marca d'agua selecionadas nao e' valida.",
                        "tipo": "marca_dagua_invalida",
                        "campos": ["links"],
                    }
                elif origem_roteiro == "upload":
                    arquivo_roteiro = request.files.get("arquivo_roteiro")
                    if not arquivo_roteiro or not arquivo_roteiro.filename:
                        erro = {
                            "mensagem": "Envie um arquivo de roteiro (.txt ou .md).",
                            "tipo": "roteiro_upload_ausente",
                            "campos": ["arquivo_roteiro"],
                        }
                    else:
                        roteiro_texto = arquivo_roteiro.read().decode("utf-8", errors="replace")
                        erro_roteiro = validar_arquivo_roteiro(arquivo_roteiro.filename, roteiro_texto)
                        if erro_roteiro:
                            roteiro_texto = None
                            erro = {
                                "mensagem": erro_roteiro,
                                "tipo": "roteiro_upload_invalido",
                                "campos": ["arquivo_roteiro"],
                            }

            pasta_projeto = None
            if not erro:
                projetos_dir = os.environ.get("PROJETOS_DIR", "")
                if not projetos_dir:
                    erro = {
                        "mensagem": "Configure PROJETOS_DIR em Ajustes antes de criar um projeto.",
                        "tipo": "projetos_dir_ausente",
                        "campos": [],
                    }
                else:
                    pasta_projeto = Path(projetos_dir) / nome
                    if pasta_projeto.exists():
                        erro = {
                            "mensagem": f"Ja existe um projeto chamado '{nome}'.",
                            "tipo": "nome_duplicado",
                            "campos": ["nome"],
                        }

            if erro:
                _descartar_temp_intro_ending(caminho_temp_intro)
                _descartar_temp_intro_ending(caminho_temp_ending)
                # Erros que so acontecem por manipulacao direta do request
                # (nao alcancaveis pela UI normal, que sempre manda arrays
                # alinhados e opcoes validas do <select>) retornam 400, igual
                # ja acontecia para perfil_invalido.
                status_code = (
                    400
                    if erro["tipo"] in (
                        "perfil_invalido",
                        "marcas_dagua_desalinhadas",
                        "marca_dagua_invalida",
                        "modo_fontes_invalido",
                        "origem_roteiro_invalida",
                        "marca_dagua_projeto_invalida",
                    )
                    else 200
                )
                return render_template(
                    "novo_projeto.html",
                    idiomas=IDIOMAS_SUPORTADOS,
                    perfis=perfis_disponiveis,
                    opcoes_marca_dagua=OPCOES_MARCA_DAGUA,
                    gerar_thumbnail_padrao_ajustes=_gerar_thumbnail_padrao_ajustes(),
                    tem_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
                    tem_marca_dagua_canal_global=ARQUIVO_MARCA_DAGUA_GLOBAL.exists(),
                    erro=erro,
                    form={
                        "nome": nome,
                        "perfil": perfil,
                        "modo_fontes": modo_fontes,
                        "origem_roteiro": origem_roteiro,
                        "pares": (
                            [{"url": url, "marca": marca} for url, marca in zip(links, marcas_dagua)]
                            if modo_fontes != "separado"
                            else []
                        ),
                        "pares_transcricao": pares_transcricao,
                        "pares_visual": pares_visual,
                        "legendas_queimadas": configuracao_video["legendas_queimadas"],
                        "sincronizacao_ia_ativa": configuracao_video["sincronizacao_ia_ativa"],
                        "sincronizacao_duracao_s": configuracao_video["sincronizacao_duracao_s"],
                        "reorganizacao_manual_ativa": configuracao_video["reorganizacao_manual_ativa"],
                        "palavras_alvo": configuracao_video["palavras_alvo"],
                        "duracao_alvo_minutos": configuracao_video["duracao_alvo_minutos"],
                        "gerar_thumbnail": configuracao_video["gerar_thumbnail"],
                        "marca_dagua_projeto": marca_dagua_projeto,
                    },
                ), status_code

            fontes_upload_entradas = []
            if uploads_validados:
                fontes_upload_entradas = _salvar_uploads(pasta_projeto, uploads_validados, len(links) + 1)

            _criar_pasta_projeto(
                pasta_projeto,
                links,
                idioma,
                estrategia_corte,
                perfil,
                marcas_dagua,
                configuracao_video,
                tipo_uso_por_link,
                fontes_upload_entradas,
                origem_roteiro,
                roteiro_texto,
                arquivo_marca_dagua,
                caminho_temp_intro,
                caminho_temp_ending,
            )

            _disparar_etapa1(nome, pasta_projeto)
            return redirect(url_for("status", projeto_id=nome))
        return render_template(
            "novo_projeto.html",
            idiomas=IDIOMAS_SUPORTADOS,
            perfis=perfis_disponiveis,
            opcoes_marca_dagua=OPCOES_MARCA_DAGUA,
            gerar_thumbnail_padrao_ajustes=_gerar_thumbnail_padrao_ajustes(),
            tem_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
            tem_marca_dagua_canal_global=ARQUIVO_MARCA_DAGUA_GLOBAL.exists(),
        )

    @app.route("/status/<projeto_id>")
    def status(projeto_id):
        job = jobs.get(projeto_id)

        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        pasta_projeto = Path(projetos_dir) / projeto_id if projetos_dir else None

        job_disco = _ler_job_json(pasta_projeto)
        links = _ler_links_projeto(pasta_projeto)
        fontes_baixadas, mensagem_arquivos = _fontes_baixadas_com_origem(pasta_projeto)

        estado = _montar_estado_status(job, job_disco)

        # Item 4 (sessao de correcoes de composicao/interface): so' tenta
        # inferir um estagio reconstruivel quando job.json de fato nao
        # deu pra ler (`nao tem_dados`) - projeto com job.json legivel
        # nunca oferece esse botao, mesmo que o status atual pareca
        # estranho (reconstrucao e' so' pra' quando o dado real sumiu).
        estagio_reconstruivel = None if estado["tem_dados"] else _detectar_estagio_por_artefatos(pasta_projeto)

        return render_template(
            "status.html",
            projeto_id=projeto_id,
            job=job,
            estado=estado,
            links=links,
            fontes_baixadas=fontes_baixadas,
            mensagem_arquivos=mensagem_arquivos,
            aviso=request.args.get("aviso"),
            pipeline_steps=_parsear_pipeline_steps(estado, pasta_projeto, projeto_id),
            artefatos=_listar_artefatos(pasta_projeto),
            estagio_reconstruivel=estagio_reconstruivel,
        )

    @app.route("/projetos/<projeto_id>/reconstruir_estado", methods=["POST"])
    def reconstruir_estado(projeto_id):
        """Reconstroi job.json a partir dos artefatos em disco quando o
        arquivo esta ausente/corrompido - correcao real (item 4): projeto
        com saida/video_final.mp4 de 1.3GB + roteiro_aprovado.md +
        narracao.mp3 em disco mostrava "Projeto sem dados persistidos" e
        pipeline inteira vazia so' porque job.json nao dava pra ler, sem
        nenhuma forma de recuperar pela propria tela.

        So' escreve um status que alguma rota do produto ja sabe reabrir
        de verdade (`_detectar_estagio_por_artefatos`/
        ESTAGIO_RECONSTRUCAO_PARA_JOB) - nunca inventa um estado novo.
        Recusa com 400 se job.json ja estiver legivel (reconstrucao nao e'
        necessaria) ou se nenhum artefato reconhecivel existir (nada
        seguro a reconstruir)."""
        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        pasta_projeto = Path(projetos_dir) / projeto_id if projetos_dir else None
        if pasta_projeto is None or not pasta_projeto.is_dir():
            return jsonify({"erro": "projeto_nao_encontrado"}), 404

        if _ler_job_json(pasta_projeto) is not None:
            return (
                jsonify(
                    {
                        "erro": "job_json_valido",
                        "mensagem": "job.json já está legível — reconstrução não é necessária.",
                    }
                ),
                400,
            )

        estagio = _detectar_estagio_por_artefatos(pasta_projeto)
        if estagio is None:
            return (
                jsonify(
                    {
                        "erro": "nada_para_reconstruir",
                        "mensagem": "Nenhum artefato reconhecível encontrado em disco para reconstruir o estado.",
                    }
                ),
                400,
            )

        campos = dict(ESTAGIO_RECONSTRUCAO_PARA_JOB[estagio])
        if estagio == "concluido":
            campos["data_fim"] = datetime.now().isoformat()
        _persistir_job(pasta_projeto, **campos)
        jobs.pop(projeto_id, None)

        destino = url_for("concluido" if estagio == "concluido" else "status", projeto_id=projeto_id)
        return jsonify({"sucesso": True, "estagio": estagio, "redirect": destino})

    @app.route("/projetos/<projeto_id>/transcrever", methods=["POST"])
    def transcrever(projeto_id):
        """Dispara a Etapa 2 (transcricao) manualmente para um projeto que
        ja tem a Etapa 1 concluida - usado para retentativas (ex: usuario
        corrigiu o ambiente NVIDIA/CUDA e quer tentar de novo) ou fluxos
        futuros onde a transcricao nao acontece automaticamente. O fluxo
        principal (download -> transcricao continuo) e' disparado por
        `_executar_etapa1`, nao por esta rota."""
        if not _ambiente_atende_minimo():
            compat = AMBIENTE_ATUAL.get("compatibilidade") or {}
            return (
                jsonify(
                    {
                        "erro": "ambiente_incompativel",
                        "mensagem": compat.get("mensagem")
                        or "Ambiente nao atende aos requisitos minimos do Broll Foundry.",
                    }
                ),
                400,
            )

        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        if not projetos_dir:
            return (
                jsonify({"erro": "projetos_dir_ausente", "mensagem": "PROJETOS_DIR nao configurado."}),
                400,
            )

        pasta_projeto = Path(projetos_dir) / projeto_id
        fontes = _ler_manifest_fontes(pasta_projeto)
        etapa1_concluida = any(f.get("sucesso") for f in fontes)
        if not etapa1_concluida:
            return (
                jsonify(
                    {
                        "erro": "etapa1_nao_concluida",
                        "mensagem": "A etapa de download ainda nao foi concluida com sucesso "
                        "para este projeto.",
                    }
                ),
                400,
            )

        _disparar_etapa2(projeto_id, pasta_projeto)
        return jsonify({"status": "iniciado", "projeto_id": projeto_id}), 202

    @app.route("/projetos/<projeto_id>/gerar_roteiro", methods=["POST"])
    def gerar_roteiro_rota(projeto_id):
        """Dispara a Etapa 3 (geracao de roteiro) manualmente para um
        projeto que ja tem a Etapa 2 concluida - usado para retentativas
        (ex: chave da API estava ausente/invalida na primeira tentativa) ou
        fluxos onde a geracao automatica nao aconteceu. O fluxo principal
        (transcricao -> roteiro continuo) e' disparado por
        `_executar_etapa2`, nao por esta rota."""
        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        if not projetos_dir:
            return (
                jsonify({"erro": "projetos_dir_ausente", "mensagem": "PROJETOS_DIR nao configurado."}),
                400,
            )

        pasta_projeto = Path(projetos_dir) / projeto_id
        pasta_transcricoes = pasta_projeto / "transcricoes"
        etapa2_concluida = pasta_transcricoes.is_dir() and any(pasta_transcricoes.glob("*.json"))
        if not etapa2_concluida:
            return (
                jsonify(
                    {
                        "erro": "etapa2_nao_concluida",
                        "mensagem": "A etapa de transcricao ainda nao foi concluida com sucesso "
                        "para este projeto.",
                    }
                ),
                400,
            )

        if not os.environ.get("ANTHROPIC_API_KEY"):
            return (
                jsonify(
                    {
                        "erro": "chave_ausente",
                        "mensagem": "Configure ANTHROPIC_API_KEY em Ajustes antes de gerar o roteiro.",
                    }
                ),
                400,
            )

        _disparar_etapa3(projeto_id, pasta_projeto)
        return jsonify({"status": "iniciado", "projeto_id": projeto_id}), 202

    def _pasta_projeto_ou_none(projeto_id):
        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        return Path(projetos_dir) / projeto_id if projetos_dir else None

    @app.route("/projetos/<projeto_id>/revisar_roteiro")
    def revisar_roteiro(projeto_id):
        """Tela de revisao completa (CLAUDE.md secao 5.5): editor do
        roteiro, preview com notas de rodape clicaveis, escolha de titulo
        e origem do audio da narracao.

        So abre para projetos em STATUS_PERMITIDOS_REVISAO - qualquer outro
        status redireciona para /status/<id> com um aviso explicando por
        que (ex: usuario acessou a URL direto num projeto que ja passou
        dessa etapa). Projetos em "aguardando_audio" (CLAUDE.md secao 5.6,
        Caminho C - "decidir depois") reabrem a tela a partir do
        roteiro_aprovado.md e do titulo.txt ja gravados, permitindo so
        completar a escolha de origem do audio.

        Excecao (refinamento "pipeline clicavel"): `?modo=readonly` reabre
        a tela mesmo com status fora de STATUS_PERMITIDOS_REVISAO, DESDE
        QUE `roteiro_aprovado.md` ja exista em disco (etapa "Roteiro" do
        pipeline horizontal marcada "done" - CLAUDE.md/_determinar_click).
        Mostra o roteiro ja aprovado com todos os controles de
        edicao/acao desabilitados no template - nunca reativa o fluxo de
        aprovacao/regeracao/cancelamento, que continuam protegidos no
        backend pelas checagens de STATUS_PERMITIDOS_REVISAO em
        aprovar_roteiro/regerar_roteiro/cancelar_projeto (essas rotas ja
        rejeitam com 400 fora dessa janela, independente de modo)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")

        modo_readonly = False
        if status_atual not in STATUS_PERMITIDOS_REVISAO:
            caminho_roteiro_aprovado = pasta_projeto / "roteiro_aprovado.md" if pasta_projeto else None
            pode_reabrir_readonly = (
                request.args.get("modo") == "readonly"
                and caminho_roteiro_aprovado is not None
                and caminho_roteiro_aprovado.exists()
            )
            if not pode_reabrir_readonly:
                aviso = (
                    f"Projeto '{projeto_id}' nao esta aguardando revisao de roteiro "
                    f"(status atual: {status_atual or 'desconhecido'})."
                )
                return redirect(url_for("status", projeto_id=projeto_id, aviso=aviso))
            modo_readonly = True

        aguardando_audio = status_atual == "aguardando_audio"
        roteiro_importado = _ler_origem_roteiro(pasta_projeto) == "upload"

        caminho_roteiro = pasta_projeto / ("roteiro_aprovado.md" if (aguardando_audio or modo_readonly) else "roteiro.md")
        roteiro_md = caminho_roteiro.read_text(encoding="utf-8") if caminho_roteiro.exists() else ""

        titulos_sugeridos = _ler_json_seguro(pasta_projeto / "titulos_sugeridos.json") or {
            "titulos": [],
            "descricoes": [],
        }
        job_metadata = _ler_json_seguro(pasta_projeto / "job_metadata.json") or {}

        titulo_ja_escolhido = None
        caminho_titulo = pasta_projeto / "titulo.txt"
        if (aguardando_audio or modo_readonly) and caminho_titulo.exists():
            titulo_ja_escolhido = caminho_titulo.read_text(encoding="utf-8").strip()

        perfil_nome = _ler_perfil_projeto(pasta_projeto)
        perfil = next(
            (p for p in prompts_loader.listar_perfis_detalhado() if p["nome"] == perfil_nome), None
        )

        tts_disponiveis = {
            provedor: provedor != PROVEDOR_TTS_OPENAI_INDISPONIVEL_COM_CHAVE and bool(os.environ.get(chave_env))
            for provedor, chave_env in PROVEDOR_TTS_CHAVE_ENV.items()
        }

        cotacao_usd_brl, cotacao_configurada = obter_cotacao_usd_brl()

        # Idioma usado para popular o dropdown de vozes curadas (GET
        # /api/vozes/<provedor>/<idioma>, CLAUDE.md secao 5.6): prioriza o
        # idioma que a Etapa 3 de fato usou pra gerar ESTE roteiro
        # (job_metadata.idioma) sobre o IDIOMA_ROTEIRO atual dos Ajustes,
        # que pode ter mudado desde a geracao.
        idioma_roteiro = job_metadata.get("idioma") or os.environ.get("IDIOMA_ROTEIRO") or IDIOMAS_SUPORTADOS[0]

        estado = _montar_estado_status(jobs.get(projeto_id), job_disco)
        com_musica_fundo_marcado = _ler_configuracao_video(pasta_projeto)["com_musica_fundo"]

        return render_template(
            "revisao_roteiro.html",
            projeto_id=projeto_id,
            pipeline_steps=_parsear_pipeline_steps(estado, pasta_projeto, projeto_id),
            com_musica_fundo_marcado=com_musica_fundo_marcado,
            roteiro_md=roteiro_md,
            roteiro_preview_html=renderizar_notas_rodape(roteiro_md, projeto_id),
            titulos_sugeridos=titulos_sugeridos,
            titulo_ja_escolhido=titulo_ja_escolhido,
            job_metadata=job_metadata,
            cotacao_usd_brl=cotacao_usd_brl,
            cotacao_configurada=cotacao_configurada,
            avisos_traducoes=WARNINGS_ACIONAVEIS,
            aviso_fallback=WARNING_FALLBACK,
            perfil=perfil,
            aguardando_audio=aguardando_audio,
            roteiro_importado=roteiro_importado,
            modo_readonly=modo_readonly,
            projeto_concluido=status_atual == "concluido",
            provedores_tts=PROVEDORES_TTS,
            provedor_tts_nomes=PROVEDOR_TTS_NOMES,
            tts_disponiveis=tts_disponiveis,
            openai_chave_presente=bool(os.environ.get(PROVEDOR_TTS_CHAVE_ENV["openai"])),
            algum_tts_configurado=any(tts_disponiveis.values()),
            vozes_por_provedor=VOZES_TTS,
            idioma_roteiro=idioma_roteiro,
        )

    ETAPAS_PIPELINE_SOMENTE_LEITURA = {"download", "transcricao", "audio", "geracao_clipes"}

    @app.route("/projetos/<projeto_id>/pipeline/<etapa>")
    def ver_etapa_pipeline(projeto_id, etapa):
        """Tela generica somente-leitura pra revisitar o que uma etapa do
        pipeline PRODUZIU, pra download/transcricao/audio/geracao_clipes -
        as 4 etapas que nunca tiveram tela dedicada (item 3 da sessao de
        correcoes de composicao/interface: "essas telas abrem vazias").
        roteiro/montagem/thumbnail continuam com suas proprias telas
        completas (revisar_roteiro/concluido/tela_thumbnail) - nunca
        passam por aqui.

        Sem excecao de status como revisar_roteiro/tela_thumbnail tem:
        aberta sempre que a etapa pedida existir no pipeline, mostrando o
        que houver em disco (mesmo se vazio) - _determinar_click so' cria
        o link quando a etapa ja esta "done", mas a rota em si nao
        recusa por status, so' por nome de etapa invalido."""
        if etapa not in ETAPAS_PIPELINE_SOMENTE_LEITURA:
            abort(404)

        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None or not pasta_projeto.is_dir():
            abort(404)

        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")
        estado = _montar_estado_status(jobs.get(projeto_id), job_disco)

        contexto = {}
        if etapa == "download":
            contexto["links"] = _ler_links_projeto(pasta_projeto)
            fontes_baixadas, mensagem_arquivos = _fontes_baixadas_com_origem(pasta_projeto)
            contexto["fontes_baixadas"] = fontes_baixadas
            contexto["mensagem_arquivos"] = mensagem_arquivos
        elif etapa == "transcricao":
            contexto["transcricoes"] = _ler_transcricoes_projeto(pasta_projeto)
        elif etapa == "audio":
            contexto["audio_disponivel"] = (pasta_projeto / "narracao.mp3").is_file()
            origem_audio = _ler_json_seguro(pasta_projeto / "origem_audio.json") or {}
            contexto["origem_audio"] = origem_audio.get("origem")
        elif etapa == "geracao_clipes":
            contexto["clipes"] = _ler_clipes_indice_para_exibicao(pasta_projeto)

        return render_template(
            "pipeline_etapa_detalhe.html",
            projeto_id=projeto_id,
            etapa=etapa,
            rotulo_etapa=ETAPA_LABEL.get(etapa, etapa),
            projeto_concluido=status_atual == "concluido",
            pipeline_steps=_parsear_pipeline_steps(estado, pasta_projeto, projeto_id),
            **contexto,
        )

    @app.route("/projetos/<projeto_id>/fontes/<nome_arquivo>")
    def servir_arquivo_fonte(projeto_id, nome_arquivo):
        """Serve um MP4 de fontes/ da pasta do projeto - usado pelo
        mini-player de video da tela de revisao (CLAUDE.md secao 5.5) para
        tocar o trecho da fonte referenciado numa nota de rodape [F<n>@mm:ss].

        Protecao contra path traversal: `nome_arquivo` e' reduzido ao seu
        basename antes de qualquer uso - um valor como "../../.env" vira
        ".env", que nao existe dentro de fontes/ do projeto, entao a rota
        responde 404 em vez de vazar arquivo de fora da pasta esperada."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        pasta_fontes = pasta_projeto / "fontes"
        nome_seguro = os.path.basename(nome_arquivo)
        if not nome_seguro or nome_seguro != nome_arquivo:
            abort(404)

        caminho_arquivo = pasta_fontes / nome_seguro
        if not caminho_arquivo.is_file():
            abort(404)

        return send_from_directory(str(pasta_fontes), nome_seguro)

    @app.route("/projetos/<projeto_id>/aprovar_roteiro", methods=["POST"])
    def aprovar_roteiro(projeto_id):
        """Grava as escolhas da tela de revisao (CLAUDE.md secao 5.5) e
        avanca o projeto para a etapa de audio - ou, se o usuario escolheu
        "Decidir depois", pausa em `aguardando_audio` (CLAUDE.md secao 5.6,
        Caminho C).

        Quando a origem do audio nao e' "depois", dispara a Etapa 4
        (scripts/4_obter_audio.py, CLAUDE.md secao 5.6) via
        `_disparar_etapa4` - mesmo padrao de `_disparar_etapa1/2/3`."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")
        if status_atual not in STATUS_PERMITIDOS_REVISAO:
            return (
                jsonify(
                    {
                        "erro": "status_invalido",
                        "mensagem": f"Projeto nao esta aguardando revisao de roteiro "
                        f"(status atual: {status_atual or 'desconhecido'}).",
                    }
                ),
                400,
            )

        roteiro_editado = request.form.get("roteiro_editado", "").strip()
        if not roteiro_editado:
            flash("O roteiro nao pode ficar vazio.", "erro")
            return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))

        titulos_sugeridos = _ler_json_seguro(pasta_projeto / "titulos_sugeridos.json") or {}
        titulos = titulos_sugeridos.get("titulos", [])
        titulo_opcao = request.form.get("titulo_opcao", "")
        titulo_custom = request.form.get("titulo_custom", "").strip()

        titulo_escolhido = None
        if titulo_opcao == "custom":
            titulo_escolhido = titulo_custom
        elif titulo_opcao.isdigit() and 0 <= int(titulo_opcao) < len(titulos):
            titulo_escolhido = titulos[int(titulo_opcao)]

        if not titulo_escolhido:
            flash("Escolha ou digite um titulo.", "erro")
            return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))

        origem_audio = request.form.get("origem_audio", "")
        if origem_audio not in ("tts", "upload", "depois"):
            flash("Selecione a origem do audio antes de aprovar o roteiro.", "erro")
            return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))

        origem_audio_dados = {"origem": origem_audio}

        if origem_audio == "tts":
            provedor = request.form.get("tts_provedor", "")
            voz = request.form.get("tts_voz", "")
            if provedor not in PROVEDORES_TTS:
                flash("Selecione um provedor de TTS valido.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            if provedor == PROVEDOR_TTS_OPENAI_INDISPONIVEL_COM_CHAVE:
                # OPENAI_API_KEY pode estar presente so' porque o provedor de
                # imagem da thumbnail (Etapa 7) usa a mesma chave - checar
                # isso ANTES da chave, senao a mensagem confundiria
                # ("configure a chave" quando ela ja esta configurada, so'
                # que pra outra finalidade). elevenlabs/azure NAO passam por
                # aqui - comportamento deles preservado (CLAUDE.md secao 5.6).
                flash(f"Provedor de TTS '{provedor}' ainda nao esta implementado nesta versao.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            chave_env = PROVEDOR_TTS_CHAVE_ENV[provedor]
            if not os.environ.get(chave_env):
                flash(f"Configure {chave_env} em Ajustes antes de usar este provedor.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            if not voz:
                flash("Selecione uma voz.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            if provedor == "google":
                # Voz marcada indisponivel por uma falha anterior de
                # geracao de preview (scripts/tts/preview_vozes.py) -
                # bloqueia aqui tambem, nao so' no JS da tela de revisao
                # (static/preview_voz.js), porque o backend nunca confia
                # so' na validacao do cliente.
                indisponiveis = preview_vozes.carregar_indisponiveis()
                if voz in indisponiveis:
                    flash(
                        f"A voz selecionada esta marcada como indisponivel "
                        f"({indisponiveis[voz]}). Escolha outra.",
                        "erro",
                    )
                    return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            origem_audio_dados["provedor"] = provedor
            origem_audio_dados["voz"] = voz

        elif origem_audio == "upload":
            arquivo = request.files.get("audio_upload")
            if arquivo is None or not arquivo.filename:
                flash("Envie um arquivo de audio.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            extensao = Path(arquivo.filename).suffix.lower()
            if extensao not in EXTENSOES_AUDIO_VALIDAS:
                flash("Formato de audio invalido. Use MP3, WAV, M4A ou OGG.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            conteudo = arquivo.read()
            if not conteudo:
                flash("Arquivo de audio vazio ou corrompido.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            if len(conteudo) > TAMANHO_MAX_AUDIO_BYTES:
                flash("Arquivo de audio maior que 100MB.", "erro")
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            nome_arquivo_audio = f"narracao_upload{extensao}"
            (pasta_projeto / nome_arquivo_audio).write_bytes(conteudo)
            origem_audio_dados["upload_arquivo"] = nome_arquivo_audio

        # Musica de fundo (Grupo B da sessao de UX - movido de
        # novo_projeto.html pra este form, CLAUDE.md secao 5.8). Resubmissao
        # deste form (ex: Caminho C "decidir depois" -> volta depois pra
        # escolher a origem do audio de verdade) nao reenvia arquivo nenhum
        # no <input type=file> mesmo com o checkbox pre-marcado - so' exige
        # selecionar arquivo se ainda nao existe musica salva em disco pra
        # este projeto.
        pasta_musicas = pasta_projeto / "entrada" / "musica_fundo"
        com_musica_fundo = request.form.get("com_musica_fundo") == "on"
        musicas_validadas = []
        if com_musica_fundo:
            algum_arquivo_enviado = any(
                arquivo and arquivo.filename for arquivo in request.files.getlist("musicas[]")
            )
            if algum_arquivo_enviado:
                musicas_validadas, erro_musica = _validar_uploads_musica(request.files.getlist("musicas[]"))
                if erro_musica:
                    flash(erro_musica, "erro")
                    return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
                if not musicas_validadas:
                    flash(
                        'Voce marcou "usar musica de fundo" mas nenhum arquivo valido '
                        "foi selecionado (.mp3, .wav ou .m4a).",
                        "erro",
                    )
                    return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))
            elif not pasta_musicas.exists() or not any(pasta_musicas.iterdir()):
                flash(
                    'Voce marcou "usar musica de fundo" mas nao selecionou nenhum '
                    "arquivo (.mp3, .wav ou .m4a).",
                    "erro",
                )
                return redirect(url_for("revisar_roteiro", projeto_id=projeto_id))

        roteiro_sem_notas = remover_notas_rodape(roteiro_editado)
        roteiro_sem_notas = remover_cabecalhos_markdown(roteiro_sem_notas)
        (pasta_projeto / "roteiro_aprovado.md").write_text(roteiro_sem_notas, encoding="utf-8")
        (pasta_projeto / "titulo.txt").write_text(titulo_escolhido, encoding="utf-8")
        (pasta_projeto / "origem_audio.json").write_text(
            json.dumps(origem_audio_dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if musicas_validadas:
            _salvar_musicas(pasta_projeto, musicas_validadas)
        config_video = _ler_configuracao_video(pasta_projeto)
        config_video["com_musica_fundo"] = com_musica_fundo
        (pasta_projeto / "entrada" / "configuracao_video.json").write_text(
            json.dumps(config_video, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if origem_audio == "depois":
            _persistir_job(pasta_projeto, status="aguardando_audio", etapa_atual="audio")
        else:
            _disparar_etapa4(projeto_id, pasta_projeto)

        return redirect(url_for("status", projeto_id=projeto_id))

    @app.route("/projetos/<projeto_id>/gerar_audio", methods=["POST"])
    def gerar_audio_rota(projeto_id):
        """Dispara a Etapa 4 (obtencao de audio) manualmente - retry apos
        falha (ex: chave TTS ausente/invalida na primeira tentativa) ou
        fluxo "decidir depois" (CLAUDE.md secao 5.6, Caminho C) apos o
        usuario completar a escolha de origem do audio na tela de revisao.
        O fluxo principal (aprovar roteiro -> audio, quando a origem ja' foi
        escolhida na hora de aprovar) e' disparado por `aprovar_roteiro`,
        nao por esta rota."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)

        if pasta_projeto is None or not (pasta_projeto / "roteiro_aprovado.md").exists():
            return (
                jsonify(
                    {
                        "erro": "etapa3_nao_concluida",
                        "mensagem": "Aprove o roteiro antes de gerar o audio.",
                    }
                ),
                400,
            )

        origem_audio = _ler_json_seguro(pasta_projeto / "origem_audio.json")
        if not origem_audio or origem_audio.get("origem") not in ("tts", "upload"):
            return (
                jsonify(
                    {
                        "erro": "origem_audio_nao_definida",
                        "mensagem": "Escolha a origem do audio na tela de revisao antes de gerar.",
                    }
                ),
                400,
            )

        if origem_audio.get("origem") == "tts":
            provedor = origem_audio.get("provedor")
            if provedor == PROVEDOR_TTS_OPENAI_INDISPONIVEL_COM_CHAVE:
                # Mesma ordem de checagem de POST /aprovar_roteiro: barrar
                # ANTES da checagem de chave, senao OPENAI_API_KEY presente
                # so' por causa do provedor de imagem da thumbnail passaria
                # pela checagem de chave e so' falharia depois, dentro do
                # subprocess, com NotImplementedError cru. elevenlabs/azure
                # NAO passam por aqui - comportamento deles preservado.
                return (
                    jsonify(
                        {
                            "erro": "provedor_nao_implementado",
                            "mensagem": f"Provedor de TTS '{provedor}' ainda nao esta implementado nesta versao.",
                        }
                    ),
                    400,
                )
            chave_env = PROVEDOR_TTS_CHAVE_ENV.get(provedor)
            if not chave_env or not os.environ.get(chave_env):
                return (
                    jsonify(
                        {
                            "erro": "chave_ausente",
                            "mensagem": f"Configure {chave_env or 'a chave do provedor'} "
                            "em Ajustes antes de gerar o audio.",
                        }
                    ),
                    400,
                )

        _disparar_etapa4(projeto_id, pasta_projeto)
        return jsonify({"status": "iniciado", "projeto_id": projeto_id}), 202

    @app.route("/projetos/<projeto_id>/gerar_clipes", methods=["POST"])
    def gerar_clipes_rota(projeto_id):
        """Dispara a Etapa 5 (geracao de clipes por selecao aleatoria de
        trechos) manualmente - retry apos falha. O fluxo principal (audio
        -> geracao de clipes continuo) e' disparado por `_executar_etapa4`,
        nao por esta rota."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)

        if pasta_projeto is None or not (pasta_projeto / "narracao.mp3").exists():
            return (
                jsonify(
                    {
                        "erro": "etapa4_nao_concluida",
                        "mensagem": "Obtenha o audio da narracao antes de gerar os clipes.",
                    }
                ),
                400,
            )

        _disparar_etapa5(projeto_id, pasta_projeto)
        return jsonify({"status": "iniciado", "projeto_id": projeto_id}), 202

    @app.route("/projetos/<projeto_id>/montar_video", methods=["POST"])
    def montar_video_rota(projeto_id):
        """Dispara a Etapa 6 (montagem final do video) manualmente - retry
        apos falha. O fluxo principal (geracao de clipes -> montagem
        continua) e' disparado por `_executar_etapa5`, nao por esta rota."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)

        if pasta_projeto is None or not (pasta_projeto / "clipes" / "indice.json").exists():
            return (
                jsonify(
                    {
                        "erro": "etapa5_nao_concluida",
                        "mensagem": "Gere os clipes antes de montar o video final.",
                    }
                ),
                400,
            )

        _disparar_etapa6(projeto_id, pasta_projeto)
        return jsonify({"status": "iniciado", "projeto_id": projeto_id}), 202

    @app.route("/projetos/<projeto_id>/sincronizar_clipes", methods=["POST"])
    def sincronizar_clipes_rota(projeto_id):
        """Dispara a Feature A (sincronizacao inteligente com IA) manualmente
        - retry, ou execucao avulsa para um projeto que tinha a feature
        desligada na criacao. Roda SINCRONAMENTE na requisicao (nao dispara
        thread) porque o fluxo automatico (`_apos_etapa5_sucesso`) ja cobre
        o caso comum em background - esta rota e' so' para o usuario pedir
        explicitamente, e o resultado (swaps aplicados) e' util devolver
        direto na resposta."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None or not (pasta_projeto / "clipes" / "indice.json").exists():
            return (
                jsonify(
                    {
                        "erro": "etapa5_nao_concluida",
                        "mensagem": "Gere os clipes antes de sincronizar com IA.",
                    }
                ),
                400,
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return (
                jsonify(
                    {
                        "erro": "chave_ausente",
                        "mensagem": "Configure ANTHROPIC_API_KEY em Ajustes antes de sincronizar.",
                    }
                ),
                400,
            )

        config = _ler_configuracao_video(pasta_projeto)
        modelo = os.environ.get("ANTHROPIC_MODEL") or sincronizador_visual.MODELO_PADRAO
        resultado = sincronizador_visual.sincronizar_projeto(
            pasta_projeto, api_key, config["sincronizacao_duracao_s"], modelo
        )
        return jsonify(resultado), (200 if resultado.get("sucesso") else 502)

    @app.route("/projetos/<projeto_id>/reorganizar_clipes")
    def reorganizar_clipes(projeto_id):
        """Tela de reorganizacao manual de clipes (Feature B, CLAUDE.md -
        sincronizacao/reorganizacao). So' abre para projetos pausados em
        `aguardando_reorganizacao` - qualquer outro status redireciona para
        /status/<id> com aviso, mesmo padrao de `revisar_roteiro`."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")
        if status_atual != "aguardando_reorganizacao":
            aviso = (
                f"Projeto '{projeto_id}' nao esta aguardando reorganizacao de clipes "
                f"(status atual: {status_atual or 'desconhecido'})."
            )
            return redirect(url_for("status", projeto_id=projeto_id, aviso=aviso))

        indice = _ler_json_seguro(pasta_projeto / "clipes" / "indice.json") or {"clipes": []}
        clipes_brutos = indice.get("clipes") or []
        # Descricoes Vision (Feature A, se rodou) sao um cache separado
        # (clipes/descricoes_vision.json) - nunca gravadas dentro de
        # indice.json - entao sao mescladas aqui so' para a tela exibir e
        # permitir a busca por descricao no banco de clipes.
        descricoes_vision = _ler_json_seguro(pasta_projeto / "clipes" / "descricoes_vision.json") or {}
        timeline, banco = _montar_timeline_reorganizacao(clipes_brutos, descricoes_vision, _duracao_padrao_clipe_s())

        estado = _montar_estado_status(jobs.get(projeto_id), job_disco)
        duracao_total_s = timeline[-1]["fim_slot_s"] if timeline else 0.0

        # GRUPO A (sessao de correcoes UX): avisa se alguma posicao usou
        # duracao aproximada (fallback, _montar_timeline_reorganizacao) e/ou
        # se a soma das duracoes diverge da duracao real da narracao - sem
        # isso o usuario audita os swaps da Feature A contra numeros
        # inventados sem saber.
        posicao_aproximada_a_partir_de = _primeira_posicao_aproximada(timeline)
        duracao_narracao_s = _duracao_narracao_do_projeto(pasta_projeto, indice)
        aviso_divergencia_narracao = _checar_divergencia_narracao(duracao_total_s, duracao_narracao_s)

        # Resultado da Feature A (sincronizacao com IA), se rodou antes desta
        # pausa - GRUPO B da sessao de correcoes UX (CLAUDE.md - antes desta
        # sessao o resultado so' existia como uma linha de resumo no log
        # efemero do job, nunca em disco nem visivel nesta tela). As linhas
        # da tabela sao enriquecidas com a posicao ATUAL de cada swap na
        # timeline (`_montar_linhas_swap` - nunca confia em
        # bloco_destino/posicao_s do log, que ficam desatualizados apos uma
        # reorganizacao manual).
        sincronizacao_log = _ler_json_seguro(pasta_projeto / "clipes" / "sincronizacao_vision_log.json")
        if sincronizacao_log:
            sincronizacao_log = {
                **sincronizacao_log,
                "swaps_aplicados": _montar_linhas_swap(sincronizacao_log.get("swaps_aplicados"), timeline),
            }
        cotacao_usd_brl, _cotacao_configurada = obter_cotacao_usd_brl()
        intro_ending = _descobrir_intro_ending_info(pasta_projeto)

        return render_template(
            "reorganizar_clipes.html",
            projeto_id=projeto_id,
            timeline=timeline,
            banco=banco,
            duracao_total_formatada=_formatar_duracao_s(duracao_total_s) or "0s",
            px_por_segundo=PX_POR_SEGUNDO_TIMELINE,
            regua_marcas=_montar_regua_tempo(duracao_total_s, PX_POR_SEGUNDO_TIMELINE),
            posicao_aproximada_a_partir_de=posicao_aproximada_a_partir_de,
            aviso_divergencia_narracao=aviso_divergencia_narracao,
            pipeline_steps=_parsear_pipeline_steps(estado, pasta_projeto, projeto_id),
            sincronizacao_log=sincronizacao_log,
            intro_info=intro_ending["intro"],
            ending_info=intro_ending["ending"],
            cotacao_usd_brl=cotacao_usd_brl,
        )

    @app.route("/projetos/<projeto_id>/reordenar_clipes", methods=["POST"])
    def reordenar_clipes(projeto_id):
        """Move um clipe de uma posicao (`origem`) para outra (`destino`) em
        clipes/indice.json (Feature B - timeline horizontal com drag livre).
        So' aceita quando o projeto esta pausado em
        `aguardando_reorganizacao`.

        Diferente do antigo /swap_clipes (troca 2-a-2, removido nesta sessao
        - trocava os dicts inteiros, entao a duracao de cada posicao viajava
        junto com o clipe e podia dessincronizar a narracao de tudo que
        vinha depois): aqui e' um INSERT (pop + insert), e a duracao de cada
        POSICAO (duracao_slot_s) e' sempre recapturada ANTES do movimento
        (na ordem atual da lista) e reaplicada por indice de posicao DEPOIS
        - nunca viaja junto com o dict do clipe que se move. E' isso que
        permite arrastar livremente sem dessincronizar a narracao.

        Body JSON: `{"origem": int, "destino": int}` - indices na lista
        `clipes/indice.json:clipes` (ordem da timeline)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        if (job_disco or {}).get("status") != "aguardando_reorganizacao":
            return (
                jsonify(
                    {
                        "erro": "status_invalido",
                        "mensagem": "Projeto nao esta aguardando reorganizacao de clipes.",
                    }
                ),
                400,
            )

        dados = request.get_json(silent=True) or {}
        try:
            origem = int(dados.get("origem"))
            destino = int(dados.get("destino"))
        except (TypeError, ValueError):
            return jsonify({"erro": "indices_invalidos", "mensagem": "origem/destino devem ser inteiros."}), 400

        caminho_indice = pasta_projeto / "clipes" / "indice.json"
        indice = _ler_json_seguro(caminho_indice)
        if not indice or not isinstance(indice.get("clipes"), list):
            return jsonify({"erro": "indice_ausente", "mensagem": "clipes/indice.json nao encontrado."}), 400

        clipes = _migrar_slots_clipes(indice["clipes"])
        total = len(clipes)
        if not (0 <= origem < total) or not (0 <= destino < total):
            return (
                jsonify({"erro": "indices_fora_do_intervalo", "mensagem": "origem/destino fora do intervalo de clipes."}),
                400,
            )

        if origem != destino:
            duracoes_por_posicao = [clipe["duracao_slot_s"] for clipe in clipes]
            clipe_movido = clipes.pop(origem)
            clipes.insert(destino, clipe_movido)
            for posicao, clipe in enumerate(clipes):
                clipe["duracao_slot_s"] = duracoes_por_posicao[posicao]
            clipes = _migrar_slots_clipes(clipes)  # recalcula inicio_slot_s/fim_slot_s cumulativos

        indice["clipes"] = clipes
        try:
            caminho_indice.write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return jsonify({"erro": "falha_ao_gravar", "mensagem": str(exc)}), 500

        return jsonify({"sucesso": True})

    @app.route("/projetos/<projeto_id>/gerar_thumbnail", methods=["POST"])
    def gerar_thumbnail_rota(projeto_id):
        """Dispara (ou re-dispara) a Etapa 7 manualmente - retry apos falha
        (`job.etapa7_falhou`, ver `_executar_etapa7`) ou geracao avulsa
        quando pulada na criacao (`gerar_thumbnail=False`). Ao contrario
        das outras rotas de retry manual (montar_video_rota etc), aceita
        rodar mesmo com o projeto ja em "aguardando_thumbnail" - e'
        exatamente esse o status que uma falha de etapa 7 deixa o projeto,
        entao a rota nao pode exigir um status diferente pra permitir o
        retry (CLAUDE.md - correcao pos-Sessao 21)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None or not (pasta_projeto / "saida" / "video_final.mp4").exists():
            return (
                jsonify(
                    {
                        "erro": "etapa6_nao_concluida",
                        "mensagem": "Monte o video final antes de gerar a thumbnail.",
                    }
                ),
                400,
            )

        _disparar_etapa7(projeto_id, pasta_projeto)
        return jsonify({"status": "iniciado", "projeto_id": projeto_id}), 202

    # Composicoes acumuladas por IA (Grupo D/E, simplificacao da Etapa 7 -
    # CLAUDE.md/HISTORICO_BUGS.md): cada geracao pela OpenAI custa dinheiro
    # de verdade, entao nunca mais sobrescreve a anterior - grava com nome
    # sequencial em thumbnail/previews/ e todas ficam disponiveis pra' o
    # usuario comparar/escolher/excluir. `_listar_composicoes_thumbnail` e'
    # a UNICA fonte de verdade de quais arquivos existem - usada tanto pro
    # GET popular o grid (mesmo sem geracao nesta sessao) quanto pelas
    # rotas de escolher/excluir validarem o nome recebido do cliente (nunca
    # confiar em nome de arquivo vindo do JS sem checar contra o disco).
    _REGEX_COMPOSICAO_IA = re.compile(r"^composicao_ia_(\d+)\.jpg$")

    def _listar_composicoes_thumbnail(pasta_thumbnail: Path) -> list:
        pasta_previews = pasta_thumbnail / "previews"
        if not pasta_previews.is_dir():
            return []
        indexados = []
        for caminho in pasta_previews.iterdir():
            correspondencia = _REGEX_COMPOSICAO_IA.match(caminho.name)
            if correspondencia:
                indexados.append((int(correspondencia.group(1)), caminho.name))
        indexados.sort()
        return [nome for _, nome in indexados]

    def _proximo_arquivo_composicao(pasta_thumbnail: Path) -> str:
        maior_indice = 0
        for nome in _listar_composicoes_thumbnail(pasta_thumbnail):
            correspondencia = _REGEX_COMPOSICAO_IA.match(nome)
            if correspondencia:
                maior_indice = max(maior_indice, int(correspondencia.group(1)))
        return f"composicao_ia_{maior_indice + 1:02d}.jpg"

    # Fase 1 (correcao do estado do briefing): fingerprint deterministico
    # do estado ATUAL de sujeitos.json - fonte de verdade pra' decidir se
    # um briefing persistido (`thumbnail.briefing_completo`) ainda
    # corresponde aos sujeitos de verdade, substituindo a dependencia da
    # flag `briefing_desatualizado` (que so' e' setada explicitamente por
    # `thumbnail_atualizar_papel_sujeito` - upload de sujeito NOVO nunca
    # setava nada, achado real do caso Nancy Guthrie). A flag continua
    # existindo e sendo setada (consumida pelo banner da tela), mas nunca
    # e' mais a UNICA defesa.
    def _fingerprint_sujeitos_atual(pasta_projeto: Path) -> str:
        sujeitos = _ler_json_seguro(pasta_projeto / "thumbnail" / "sujeitos" / "sujeitos.json") or {}
        return thumbnail_briefing.calcular_fingerprint_sujeitos(sujeitos)

    def _briefing_stale(textos: dict, pasta_projeto: Path) -> bool:
        """True quando `textos.briefing_completo` (thumbnail/metadados.json)
        nao corresponde mais ao estado ATUAL de sujeitos.json. Sem briefing
        nenhum gerado ainda, nao ha' o que ficar obsoleto -> False.
        Briefing persistido SEM fingerprint (legado - gerado antes desta
        protecao existir, ou metadados.json editado por fora) e' tratado
        como stale por padrao - nunca confiavel sem o fingerprint pra'
        comparar."""
        if not (textos.get("briefing_completo") or "").strip():
            return False
        fingerprint_salvo = textos.get("briefing_subjects_fingerprint")
        if not fingerprint_salvo:
            return True
        return fingerprint_salvo != _fingerprint_sujeitos_atual(pasta_projeto)

    @app.route("/projetos/<projeto_id>/thumbnail")
    def tela_thumbnail(projeto_id):
        """Tela de revisao da thumbnail (Grupo G, Etapa 7). So' abre para
        projetos pausados em `aguardando_thumbnail` - mesmo padrao de
        `revisar_roteiro`/`reorganizar_clipes`.

        Excecao (refinamento "pipeline clicavel", mesmo espirito de
        `revisar_roteiro`): `?modo=readonly` reabre a tela mesmo com
        status fora de "aguardando_thumbnail", DESDE QUE a pasta
        `thumbnail/` ja exista em disco (etapa "Thumbnail" do pipeline
        horizontal marcada "done" - CLAUDE.md/_determinar_click). Mostra
        os sujeitos/textos ja resolvidos com todos os controles de
        edicao/upload/renderizacao omitidos no template - as rotas de
        mutacao (upload_sujeito/remover_sujeito/gerar_briefing/
        salvar_textos/renderizar/escolher_template) continuam protegidas
        no backend pela mesma checagem de status, independente de modo."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")

        modo_readonly = False
        if status_atual != "aguardando_thumbnail":
            pasta_thumbnail_existente = pasta_projeto / "thumbnail" if pasta_projeto else None
            pode_reabrir_readonly = (
                request.args.get("modo") == "readonly"
                and pasta_thumbnail_existente is not None
                and pasta_thumbnail_existente.is_dir()
            )
            if not pode_reabrir_readonly:
                aviso = (
                    f"Projeto '{projeto_id}' nao esta aguardando revisao de thumbnail "
                    f"(status atual: {status_atual or 'desconhecido'})."
                )
                return redirect(url_for("status", projeto_id=projeto_id, aviso=aviso))
            modo_readonly = True

        pasta_thumbnail = pasta_projeto / "thumbnail"
        sujeitos_declarados = _ler_json_seguro(pasta_thumbnail / "sujeitos" / "sujeitos.json") or {}
        metadados = _ler_json_seguro(pasta_thumbnail / "metadados.json") or {}
        textos = metadados.get("thumbnail") or {}

        hero_papel = (sujeitos_declarados.get("hero") or {}).get("papel")
        secondary_papel = (sujeitos_declarados.get("secondary") or {}).get("papel")
        templates_elegiveis_atual = list(thumbnail_briefing.templates_elegiveis(hero_papel, secondary_papel))
        # Sugestao do sistema pra' pre-selecionar o dropdown (Grupo F): o
        # template que a ULTIMA geracao de briefing de fato escolheu
        # (`briefing_template`, resultado real do juiz/heuristica de
        # `thumbnail_briefing.selecionar_template`) SE ainda for elegivel
        # pro estado ATUAL de sujeitos - nunca chama a API so' pra' calcular
        # uma sugestao de exibicao. Correcao de bug real (ver
        # HISTORICO_BUGS.md): antes, `briefing_template` era usado sem essa
        # checagem - um briefing gerado automaticamente ANTES de qualquer
        # foto ser enviada grava "EVIDENCE_SCENE" em metadados.json, e esse
        # valor stale continuava aparecendo como "sugerido pelo sistema"
        # mesmo depois do usuario enviar 2 fotos que tornavam outro
        # template elegivel (e EVIDENCE_SCENE inelegivel) - achado real em
        # teste, thumbnail saiu sem nenhum rosto apesar das fotos
        # disponiveis. Templates elegiveis empatados usam a ordem de
        # desempate EXPLICITA de `template_preferido`, nunca a ordem
        # implicita da tupla que `templates_elegiveis` devolveu.
        briefing_template_salvo = textos.get("briefing_template")
        if briefing_template_salvo in templates_elegiveis_atual:
            template_sugerido = briefing_template_salvo
        else:
            template_sugerido = thumbnail_briefing.template_preferido(templates_elegiveis_atual) or "EVIDENCE_SCENE"

        # Mensagem de indisponibilidade CONTEXTUAL (Fase 1 - correcao da
        # mensagem de indisponibilidade): nunca o texto estatico de
        # `MOTIVO_CURTO_INDISPONIVEL` sozinho - ver docstring de
        # `thumbnail_briefing.motivo_indisponibilidade`.
        templates_motivo_curto_atual = thumbnail_briefing.motivos_indisponibilidade(hero_papel, secondary_papel)

        # Staleness real do briefing (Fase 1 - correcao do estado do
        # briefing): fingerprint e' a fonte de verdade; a flag legada
        # continua sendo consultada tambem (nunca e' a UNICA defesa, mas
        # nunca ignorada de proposito).
        briefing_stale = _briefing_stale(textos, pasta_projeto)

        # Grid persistente (Grupo E): populado direto do disco, nunca
        # depende de uma geracao ter acontecido nesta sessao de pagina.
        composicoes = [
            {
                "arquivo": nome,
                "url": url_for("thumbnail_imagem", projeto_id=projeto_id, subpasta="previews", arquivo=nome),
            }
            for nome in _listar_composicoes_thumbnail(pasta_thumbnail)
        ]

        estado = _montar_estado_status(jobs.get(projeto_id), job_disco)

        return render_template(
            "thumbnail.html",
            projeto_id=projeto_id,
            sujeitos_declarados=sujeitos_declarados,
            papeis_sujeito_validos=list(thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS),
            tem_sujeito=bool(sujeitos_declarados.get("hero") or sujeitos_declarados.get("secondary")),
            modo_readonly=modo_readonly,
            projeto_concluido=status_atual == "concluido",
            thumbnail_final_disponivel=(pasta_thumbnail / "final.jpg").is_file(),
            textos=textos,
            templates_disponiveis=list(thumbnail_briefing.TEMPLATES_VALIDOS),
            templates_elegiveis_atual=templates_elegiveis_atual,
            templates_nomes=thumbnail_briefing.NOME_EXIBICAO_TEMPLATE,
            templates_descricoes=thumbnail_briefing.DESCRICAO_AMIGAVEL_TEMPLATE,
            templates_motivo_curto=templates_motivo_curto_atual,
            template_sugerido=template_sugerido,
            briefing_stale=briefing_stale,
            composicoes=composicoes,
            pipeline_steps=_parsear_pipeline_steps(estado, pasta_projeto, projeto_id),
            tem_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
            etapa7_falhou=estado.get("etapa7_falhou"),
            etapa7_mensagem=estado.get("mensagem_usuario"),
        )

    @app.route("/projetos/<projeto_id>/thumbnail/imagem/<subpasta>/<arquivo>")
    def thumbnail_imagem(projeto_id, subpasta, arquivo):
        """Serve imagens da Etapa 7 (composicoes acumuladas em
        thumbnail/previews/) - mesma protecao contra path traversal de
        `thumb_clipe`/`servir_arquivo_fonte`: `subpasta` e `arquivo` sao
        reduzidos ao basename antes de qualquer uso, e `subpasta` so'
        aceita os nomes conhecidos (nunca um caminho arbitrario).
        "candidatos_cena"/"candidatos_rosto" sairam da lista na sessao de
        simplificacao da Etapa 7 - nao existe mais scan de cenario nem
        identificacao de rosto (ver docstring de scripts/7_thumbnail.py)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        subpasta_segura = os.path.basename(subpasta)
        arquivo_seguro = os.path.basename(arquivo)
        if not subpasta_segura or subpasta_segura != subpasta or not arquivo_seguro or arquivo_seguro != arquivo:
            abort(404)
        if subpasta_segura not in {"previews"}:
            abort(404)

        pasta_destino = pasta_projeto / "thumbnail" / subpasta_segura
        if not (pasta_destino / arquivo_seguro).exists():
            abort(404)
        return send_from_directory(str(pasta_destino), arquivo_seguro)

    @app.route("/projetos/<projeto_id>/thumbnail/arquivo/<nome>")
    def thumbnail_arquivo_raiz(projeto_id, nome):
        """Serve os arquivos que ficam direto em thumbnail/ - hoje so'
        `final.jpg` (a thumbnail escolhida) - lista fechada de nomes
        aceitos, mesma protecao de path traversal das rotas irmas."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        nomes_aceitos = {"final.jpg"}
        nome_seguro = os.path.basename(nome)
        if not nome_seguro or nome_seguro != nome or nome_seguro not in nomes_aceitos:
            abort(404)

        pasta_thumbnail = pasta_projeto / "thumbnail"
        if not (pasta_thumbnail / nome_seguro).exists():
            abort(404)
        return send_from_directory(str(pasta_thumbnail), nome_seguro)

    @app.route("/projetos/<projeto_id>/thumbnail/sujeito_original/<slot>")
    def thumbnail_sujeito_original(projeto_id, slot):
        """GRUPO C: serve a foto ORIGINAL (sem recorte nenhum) enviada pra'
        um slot - usada pro preview/botao "baixar" da tela, e e' a MESMA
        foto que `imagem_openai.gerar_composicao` manda pro endpoint
        /v1/images/edits. `slot` so' aceita "hero"/"secondary"
        (thumbnail_etapa7.SLOTS_SUJEITO); o nome do arquivo real e' lido de
        sujeitos.json - nunca aceito direto da URL (evita path traversal
        por construcao, nao so' por basename)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)
        if slot not in thumbnail_etapa7.SLOTS_SUJEITO:
            abort(404)

        sujeitos = _ler_json_seguro(pasta_projeto / "thumbnail" / "sujeitos" / "sujeitos.json") or {}
        info = sujeitos.get(slot)
        if not info or not info.get("arquivo"):
            abort(404)

        nome_seguro = os.path.basename(info["arquivo"])
        pasta_sujeitos = pasta_projeto / "thumbnail" / "sujeitos"
        if not nome_seguro or not (pasta_sujeitos / nome_seguro).exists():
            abort(404)
        return send_from_directory(str(pasta_sujeitos), nome_seguro)

    def _recusar_thumbnail_fora_de_revisao(pasta_projeto):
        """Guarda compartilhada pelas rotas de mutacao do Grupo G
        (upload_sujeito/remover_sujeito/gerar_briefing/salvar_textos/
        renderizar/escolher_template): mesmo espirito do guard de
        STATUS_PERMITIDOS_REVISAO no roteiro (server.py:aprovar_roteiro/
        cancelar_projeto) - nunca deixar um projeto ja concluido (ou em
        qualquer outro status) ser alterado so' porque a URL foi chamada
        direto, mesmo que a tela nao renderize mais os controles em
        modo=readonly. Retorna a tupla de erro (response, 400) pra dar
        `return` direto no chamador, ou None se a acao pode prosseguir."""
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")
        if status_atual != "aguardando_thumbnail":
            return (
                jsonify(
                    {
                        "erro": "status_invalido",
                        "mensagem": f"Projeto nao esta aguardando revisao de thumbnail "
                        f"(status atual: {status_atual or 'desconhecido'}).",
                    }
                ),
                400,
            )
        return None

    @app.route("/projetos/<projeto_id>/thumbnail/upload_sujeito", methods=["POST"])
    def thumbnail_upload_sujeito(projeto_id):
        """GRUPO B (reconstrucao desta sessao - ver docstring de scripts/
        7_thumbnail.py): upload de um dos dois slots de sujeito (hero -
        "Sujeito principal" - ou secondary - "Sujeito secundario"), cada
        um com PAPEL declarado obrigatorio (thumbnail_etapa7.
        PAPEIS_SUJEITO_VALIDOS). Substitui a rota antiga (upload unico, sem
        papel, sem slot, decidia automaticamente por Vision sobre frames de
        CLIPE - removida por escolher errado em teste real, projeto
        NancyGuthrieProject01). Body multipart: `foto` + campos de form
        `slot` e `papel`. Sem recorte nenhum - a foto original salva em
        thumbnail/sujeitos/ e' o que a composicao por IA usa direto."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        slot = request.form.get("slot")
        papel = request.form.get("papel")
        if slot not in thumbnail_etapa7.SLOTS_SUJEITO:
            return jsonify({"erro": "slot_invalido", "mensagem": "slot precisa ser 'hero' ou 'secondary'."}), 400
        if papel not in thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS:
            return jsonify({"erro": "papel_invalido", "mensagem": "Escolha um papel valido para a foto."}), 400

        arquivo = request.files.get("foto")
        if arquivo is None or not arquivo.filename:
            return jsonify({"erro": "arquivo_ausente", "mensagem": "Envie uma foto."}), 400
        extensao = Path(arquivo.filename).suffix.lower()
        if extensao not in EXTENSOES_IMAGEM_VALIDAS:
            return jsonify({"erro": "extensao_invalida", "mensagem": "Use JPG, PNG ou WEBP."}), 400

        conteudo = arquivo.read()
        if not conteudo:
            return jsonify({"erro": "arquivo_vazio", "mensagem": "Arquivo de foto vazio ou corrompido."}), 400
        if len(conteudo) > TAMANHO_MAX_UPLOAD_BYTES:
            return jsonify({"erro": "arquivo_grande", "mensagem": "Foto maior que o limite permitido."}), 400

        pasta_sujeitos = pasta_projeto / "thumbnail" / "sujeitos"
        pasta_sujeitos.mkdir(parents=True, exist_ok=True)
        nome_arquivo = f"{slot}{extensao}"
        (pasta_sujeitos / nome_arquivo).write_bytes(conteudo)

        resultado_slot = thumbnail_etapa7.atualizar_sujeito_slot(pasta_projeto, slot, nome_arquivo, papel)
        if not resultado_slot.get("sucesso"):
            return jsonify(resultado_slot), 400

        return jsonify({"sucesso": True, "slot": slot, "papel": papel, "arquivo": nome_arquivo})

    @app.route("/projetos/<projeto_id>/thumbnail/remover_sujeito", methods=["POST"])
    def thumbnail_remover_sujeito(projeto_id):
        """GRUPO B: esvazia um slot (Body JSON `{"slot": "hero"|"secondary"}`).
        O arquivo original enviado fica orfao em disco de proposito - nunca
        deletamos upload do usuario sem pedido explicito - so' para de
        aparecer em sujeitos.json."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        dados = request.get_json(silent=True) or {}
        slot = dados.get("slot")
        if slot not in thumbnail_etapa7.SLOTS_SUJEITO:
            return jsonify({"erro": "slot_invalido", "mensagem": "slot precisa ser 'hero' ou 'secondary'."}), 400

        resultado = thumbnail_etapa7.remover_sujeito_slot(pasta_projeto, slot)
        if not resultado.get("sucesso"):
            return jsonify(resultado), 400

        return jsonify({"sucesso": True})

    @app.route("/projetos/<projeto_id>/thumbnail/atualizar_papel_sujeito", methods=["POST"])
    def thumbnail_atualizar_papel_sujeito(projeto_id):
        """Correcao de bug (ver HISTORICO_BUGS.md): trocar o papel no
        dropdown de um slot que JA tem foto enviada nao persistia nada -
        so' era lido/enviado de novo por `uploadSujeito` no proximo
        upload, entao o dropdown ficava divergente do papel de verdade
        gravado em sujeitos.json (que so' o texto ao lado da miniatura,
        renderizado a partir do disco, refletia). Esta rota persiste SO'
        o papel, reaproveitando o `arquivo` ja salvo em thumbnail/
        sujeitos/ - nunca exige reenvio da foto. Body JSON
        `{"slot": "hero"|"secondary", "papel": "..."}`.

        Slot sem foto ainda: nada pra' persistir (o valor escolhido so'
        passa a valer no proximo upload, que ja manda o dropdown atual -
        thumbnail.js:uploadSujeito) - devolve `persistido: false` sem
        erro, pra' o frontend saber que nao ha' nada mais a sincronizar.

        Papel mudou o SIGNIFICADO do sujeito - um briefing ja gerado pode
        estar descrevendo a pessoa errada (ex: "vitima" virou "suspeito"
        mas o texto continua chamando de vitima). Nunca chamamos a API de
        novo sozinhos aqui (mesmo espirito de upload_sujeito/
        remover_sujeito - custaria dinheiro real sem o usuario pedir):
        so' marcamos `thumbnail.briefing_desatualizado=True` em
        metadados.json quando ja existia um briefing gerado, pro banner
        da tela avisar e o usuario regerar pelo botao explicito ja
        existente ("Gerar / regenerar briefing", que le sujeitos.json do
        disco de novo e automaticamente pega o papel novo)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        dados = request.get_json(silent=True) or {}
        slot = dados.get("slot")
        papel = dados.get("papel")
        if slot not in thumbnail_etapa7.SLOTS_SUJEITO:
            return jsonify({"erro": "slot_invalido", "mensagem": "slot precisa ser 'hero' ou 'secondary'."}), 400
        if papel not in thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS:
            return jsonify({"erro": "papel_invalido", "mensagem": "Escolha um papel valido para a foto."}), 400

        pasta_thumbnail = pasta_projeto / "thumbnail"
        sujeitos_atuais = _ler_json_seguro(pasta_thumbnail / "sujeitos" / "sujeitos.json") or {}
        info_slot = sujeitos_atuais.get(slot)
        if not info_slot or not info_slot.get("arquivo"):
            return jsonify(
                {
                    "sucesso": True,
                    "persistido": False,
                    "mensagem": "Nenhuma foto enviada ainda para este slot — o papel escolhido será usado no próximo upload.",
                }
            )

        resultado_slot = thumbnail_etapa7.atualizar_sujeito_slot(pasta_projeto, slot, info_slot["arquivo"], papel)
        if not resultado_slot.get("sucesso"):
            return jsonify(resultado_slot), 400

        caminho_metadados = pasta_thumbnail / "metadados.json"
        metadados = _ler_json_seguro(caminho_metadados)
        if metadados is not None and (metadados.get("thumbnail") or {}).get("briefing_completo"):
            metadados.setdefault("thumbnail", {})["briefing_desatualizado"] = True
            caminho_metadados.write_text(json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8")

        dados_atualizados = resultado_slot["sujeitos"]
        hero_papel = (dados_atualizados.get("hero") or {}).get("papel")
        secondary_papel = (dados_atualizados.get("secondary") or {}).get("papel")
        templates_elegiveis_atual = list(thumbnail_briefing.templates_elegiveis(hero_papel, secondary_papel))
        template_sugerido = thumbnail_briefing.template_preferido(templates_elegiveis_atual) or "EVIDENCE_SCENE"
        templates_motivo_curto_atual = thumbnail_briefing.motivos_indisponibilidade(hero_papel, secondary_papel)

        return jsonify(
            {
                "sucesso": True,
                "persistido": True,
                "slot": slot,
                "papel": papel,
                "templates_elegiveis": templates_elegiveis_atual,
                "template_sugerido": template_sugerido,
                "templates_motivo_curto": templates_motivo_curto_atual,
            }
        )

    @app.route("/projetos/<projeto_id>/thumbnail/gerar_briefing", methods=["POST"])
    def thumbnail_gerar_briefing(projeto_id):
        """GRUPO C: regera `thumbnail.briefing_completo` a partir do que ja
        esta' em disco (thumbnail/metadados.json + thumbnail/sujeitos/
        sujeitos.json), sem gastar uma chamada nova de Grupo D/Headline
        Engine. Chamavel a qualquer momento na tela - em particular depois
        que o usuario troca um upload de sujeito, o que
        `thumbnail_upload_sujeito`/`thumbnail_remover_sujeito` NAO fazem
        sozinhos (custaria uma chamada de API a cada upload, sem o usuario
        pedir - o botao "Gerar briefing" da tela e' a acao explicita).
        Funciona sem ANTHROPIC_API_KEY (fallback deterministico em toda
        etapa interna que chamaria API - scripts/thumbnail_briefing.py).

        Body JSON opcional `{"template": "ARROW_TRIO"}` (Grupo F - escolha
        manual do template na tela): forca esse template especifico em vez
        de deixar a IA escolher entre os elegiveis - repassado direto pra'
        `thumbnail_briefing.gerar_briefing_completo` como `template_forcado`,
        que ja ignora valores fora do conjunto elegivel pro estado atual de
        sujeitos (nunca confia so' no frontend)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        dados = request.get_json(silent=True) or {}
        template_forcado = dados.get("template")
        if template_forcado not in thumbnail_briefing.TEMPLATES_VALIDOS:
            template_forcado = None

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        modelo = os.environ.get("ANTHROPIC_MODEL") or thumbnail_etapa7.MODELO_PADRAO
        resultado = thumbnail_etapa7.gerar_briefing_thumbnail(
            pasta_projeto, api_key, modelo, template_forcado=template_forcado
        )
        if not resultado.get("sucesso"):
            return jsonify(resultado), 400
        return jsonify(resultado)

    @app.route("/projetos/<projeto_id>/thumbnail/gerar_composicao_ia", methods=["POST"])
    def thumbnail_gerar_composicao_ia(projeto_id):
        """Manda o briefing exportavel (thumbnail/metadados.json.thumbnail.
        briefing_completo) + as fotos ORIGINAIS dos sujeitos
        (thumbnail/sujeitos/*, hero antes de secondary) pro endpoint
        /v1/images/edits do gpt-image-2 (scripts/imagem/openai.
        gerar_composicao). Acao SEMPRE explicita - nunca chamada
        automaticamente por nenhuma outra rota (cada clique custa uma
        chamada de API real).

        Body JSON opcional `{"briefing_completo": "..."}`: se o usuario
        editou o texto na tela (Grupo B - o briefing e' o unico campo de
        texto editavel), esse valor e' persistido em
        thumbnail/metadados.json ANTES de gerar, pra' nao perder a edicao
        e pra' a proxima geracao/recarregamento de pagina continuar
        mostrando o texto editado. Sem o campo (ou vazio), usa o que ja
        esta' salvo em disco.

        GRUPO D (simplificacao da Etapa 7 - CLAUDE.md): cada geracao grava
        num arquivo SEQUENCIAL (composicao_ia_01.jpg, _02.jpg, ...) em vez
        de sobrescrever a anterior - cada chamada custa dinheiro de
        verdade, o usuario compara as composicoes acumuladas e escolhe
        (ou exclui as que nao prestam) na tela. Resultado (sucesso ou
        falha, com motivo real - nunca generico) tambem e' salvo em
        thumbnail/composicao_status.json por `gerar_composicao`."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        if not os.environ.get("OPENAI_API_KEY"):
            return (
                jsonify(
                    {
                        "sucesso": False,
                        "erro_tipo": "sem_chave",
                        "mensagem": "Configure OPENAI_API_KEY em Ajustes antes de usar a composição por IA.",
                    }
                ),
                400,
            )

        pasta_thumbnail = pasta_projeto / "thumbnail"
        metadados = _ler_json_seguro(pasta_thumbnail / "metadados.json") or {}
        metadados.setdefault("thumbnail", {})

        dados = request.get_json(silent=True) or {}
        briefing_editado = dados.get("briefing_completo")
        if isinstance(briefing_editado, str) and briefing_editado.strip():
            metadados["thumbnail"]["briefing_completo"] = briefing_editado
            pasta_thumbnail.mkdir(parents=True, exist_ok=True)
            (pasta_thumbnail / "metadados.json").write_text(
                json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        briefing_completo = (metadados.get("thumbnail") or {}).get("briefing_completo") or ""
        briefing_completo = briefing_completo.strip()
        if not briefing_completo:
            return (
                jsonify(
                    {
                        "sucesso": False,
                        "erro_tipo": "briefing_ausente",
                        "mensagem": "Gere o briefing exportável antes de tentar a composição por IA.",
                    }
                ),
                400,
            )

        # Fase 1 (correcao do estado do briefing - caso real Nancy Guthrie):
        # ESTE e' o ponto onde o defeito acontecia - upload de sujeito
        # novo nunca marcava `briefing_desatualizado`, entao um briefing de
        # EVIDENCE_SCENE gerado automaticamente ANTES de qualquer sujeito
        # existir continuava sendo mandado pra' composicao por IA depois do
        # usuario enviar fotos. A checagem e' pelo FINGERPRINT (fonte de
        # verdade), nunca so' a flag legada - bloqueia em vez de regerar
        # sozinha (mesmo espirito de `thumbnail_atualizar_papel_sujeito`:
        # nunca chamar a API de novo sem o usuario pedir, custa dinheiro
        # real). O usuario resolve clicando em "Gerar / regenerar briefing"
        # (acao explicita ja existente na tela) antes de tentar de novo.
        if _briefing_stale(metadados.get("thumbnail") or {}, pasta_projeto):
            return (
                jsonify(
                    {
                        "sucesso": False,
                        "erro_tipo": "briefing_desatualizado",
                        "mensagem": "Os sujeitos mudaram (foto ou papel) desde que este briefing foi gerado — "
                        "o texto atual pode descrever a pessoa errada. Clique em \"Gerar / regenerar briefing\" "
                        "antes de tentar a composição por IA de novo.",
                    }
                ),
                400,
            )

        sujeitos = _ler_json_seguro(pasta_thumbnail / "sujeitos" / "sujeitos.json") or {}
        caminhos_fotos = []
        for slot in thumbnail_etapa7.SLOTS_SUJEITO:  # ("hero", "secondary") - ordem importa
            info = sujeitos.get(slot)
            if not info or not info.get("arquivo"):
                continue
            caminho_foto = pasta_thumbnail / "sujeitos" / os.path.basename(info["arquivo"])
            if caminho_foto.exists():
                caminhos_fotos.append(caminho_foto)

        nome_arquivo = _proximo_arquivo_composicao(pasta_thumbnail)
        resultado = imagem_openai.gerar_composicao(
            briefing_completo,
            caminhos_fotos,
            pasta_thumbnail / "previews" / nome_arquivo,
        )
        if not resultado.get("sucesso"):
            resultado["mensagem"] = resultado.get("erro_mensagem") or "Falha ao gerar a composição por IA."
            return jsonify(resultado), 400

        resultado["arquivo"] = nome_arquivo
        resultado["preview_url"] = url_for(
            "thumbnail_imagem", projeto_id=projeto_id, subpasta="previews", arquivo=nome_arquivo
        )
        return jsonify(resultado)

    @app.route("/projetos/<projeto_id>/thumbnail/excluir_composicao", methods=["POST"])
    def thumbnail_excluir_composicao(projeto_id):
        """GRUPO D: descarta uma composicao acumulada que nao presta (Body
        JSON `{"arquivo": "composicao_ia_02.jpg"}`). `arquivo` e' validado
        contra `_listar_composicoes_thumbnail` (nunca confia em nome vindo
        do cliente sem checar contra o disco) - nunca deleta nada fora do
        padrao `composicao_ia_NN.jpg`."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        pasta_thumbnail = pasta_projeto / "thumbnail"
        dados = request.get_json(silent=True) or {}
        nome_arquivo = os.path.basename(dados.get("arquivo") or "")
        if not nome_arquivo or nome_arquivo not in _listar_composicoes_thumbnail(pasta_thumbnail):
            return jsonify({"erro": "composicao_invalida", "mensagem": "Composição não encontrada."}), 400

        (pasta_thumbnail / "previews" / nome_arquivo).unlink(missing_ok=True)
        return jsonify({"sucesso": True, "composicoes": _listar_composicoes_thumbnail(pasta_thumbnail)})

    @app.route("/projetos/<projeto_id>/thumbnail/salvar_briefing", methods=["POST"])
    def thumbnail_salvar_briefing(projeto_id):
        """GRUPO B (simplificacao da Etapa 7 - CLAUDE.md/HISTORICO_BUGS.md):
        o briefing exportavel e' o UNICO campo de texto editavel da tela -
        "o Claude gera o briefing, o usuario edita se quiser". Body JSON
        `{"briefing_completo": "..."}`, persistido direto em
        thumbnail/metadados.json.thumbnail.briefing_completo - nenhum outro
        campo do bloco `thumbnail` e' tocado por esta rota."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        dados = request.get_json(silent=True) or {}
        briefing_completo = dados.get("briefing_completo")
        if not isinstance(briefing_completo, str):
            return jsonify({"erro": "briefing_invalido", "mensagem": "briefing_completo precisa ser texto."}), 400

        pasta_thumbnail = pasta_projeto / "thumbnail"
        metadados = _ler_json_seguro(pasta_thumbnail / "metadados.json") or {}
        metadados.setdefault("thumbnail", {})
        metadados["thumbnail"]["briefing_completo"] = briefing_completo

        pasta_thumbnail.mkdir(parents=True, exist_ok=True)
        (pasta_thumbnail / "metadados.json").write_text(
            json.dumps(metadados, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return jsonify({"sucesso": True, "thumbnail": metadados["thumbnail"]})

    @app.route("/projetos/<projeto_id>/thumbnail/regenerar_metadados", methods=["POST"])
    def thumbnail_regenerar_metadados(projeto_id):
        """Botao "Regenerar dados automáticos" da tela - regera SOMENTE o
        bloco `thumbnail` (headline/emphasis_word/secondary/accent/censor/
        subject_name/background_prompt) via nova chamada a' IA (incluindo
        o Headline Engine e a selecao automatica de template do Grupo C),
        preservando title/description/tags e qualquer edicao humana
        anterior desses campos
        (`thumbnail_etapa7.regenerar_thumbnail_briefing`). Tambem
        regenera `thumbnail.briefing_completo` a partir dos dados novos -
        a tela substitui o texto do briefing pelo resultado."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return (
                jsonify({
                    "erro": "sem_chave_anthropic",
                    "mensagem": "Configure ANTHROPIC_API_KEY em Ajustes antes de regenerar.",
                }),
                400,
            )

        modelo = os.environ.get("ANTHROPIC_MODEL") or thumbnail_etapa7.MODELO_PADRAO
        resultado = thumbnail_etapa7.regenerar_thumbnail_briefing(pasta_projeto, api_key, modelo)
        if not resultado.get("sucesso"):
            return jsonify(resultado), 400
        return jsonify(resultado)

    @app.route("/projetos/<projeto_id>/thumbnail/escolher_composicao", methods=["POST"])
    def thumbnail_escolher_composicao(projeto_id):
        """Clicar numa composicao acumulada salva thumbnail/final.jpg e
        conclui o job (unica forma do job chegar em "concluido" desde a
        Etapa 7 - ver `_executar_etapa6`/`_executar_etapa7`). Body JSON
        `{"arquivo": "composicao_ia_02.jpg"}` - validado contra
        `_listar_composicoes_thumbnail` (nunca confia em nome vindo do
        cliente sem checar contra o disco)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            return jsonify({"erro": "projeto_nao_encontrado"}), 404
        erro = _recusar_thumbnail_fora_de_revisao(pasta_projeto)
        if erro is not None:
            return erro

        pasta_thumbnail = pasta_projeto / "thumbnail"
        dados = request.get_json(silent=True) or {}
        nome_arquivo = os.path.basename(dados.get("arquivo") or "")
        if not nome_arquivo or nome_arquivo not in _listar_composicoes_thumbnail(pasta_thumbnail):
            return jsonify({"erro": "composicao_invalida", "mensagem": "Composição não encontrada."}), 400

        caminho_preview = pasta_thumbnail / "previews" / nome_arquivo
        caminho_final = pasta_thumbnail / "final.jpg"
        shutil.copyfile(caminho_preview, caminho_final)

        job = jobs.get(projeto_id)
        if job is not None:
            job["status"] = "concluido"
            job["etapa"] = "thumbnail"
            job["proxima_etapa"] = None
        _persistir_job(
            pasta_projeto,
            status="concluido",
            etapa_atual="thumbnail",
            proxima_etapa=None,
            data_fim=datetime.now().isoformat(),
            tipo_erro=None,
            mensagem_usuario=None,
            log_erro=None,
        )

        return jsonify({"sucesso": True, "redirect": url_for("concluido", projeto_id=projeto_id)})

    @app.route("/projetos/<projeto_id>/thumb_clipe/<clipe_id>")
    def thumb_clipe(projeto_id, clipe_id):
        """Serve (gerando sob demanda se ainda nao existir - ver
        `_gerar_thumbnails_clipes_em_background`) a thumbnail JPG de um
        clipe - grid de banco de clipes da tela de reorganizacao manual
        (Feature B). Mesma protecao contra path traversal de
        `servir_arquivo_fonte`: `clipe_id` e' reduzido ao basename antes de
        qualquer uso."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        clipe_id_seguro = os.path.basename(clipe_id)
        if not clipe_id_seguro or clipe_id_seguro != clipe_id:
            abort(404)

        pasta_thumbs = pasta_projeto / "clipes" / "thumbs"
        caminho_thumb = pasta_thumbs / f"{clipe_id_seguro}.jpg"
        if not caminho_thumb.exists():
            caminho_clipe = pasta_projeto / "clipes" / f"{clipe_id_seguro}.mp4"
            if not caminho_clipe.exists() or not sincronizador_visual.extrair_frame_clipe(
                caminho_clipe, caminho_thumb
            ):
                abort(404)

        return send_from_directory(str(pasta_thumbs), f"{clipe_id_seguro}.jpg")

    @app.route("/projetos/<projeto_id>/narracao_audio")
    def narracao_audio(projeto_id):
        """Serve narracao.mp3 puro (sem video) - player de preview TTS da
        tela de reorganizacao manual (Feature B), cursor sincronizado com a
        timeline via inicio_slot_s/fim_slot_s de cada posicao (JS)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)
        if not (pasta_projeto / "narracao.mp3").exists():
            abort(404)
        return send_from_directory(str(pasta_projeto), "narracao.mp3")

    @app.route("/projetos/<projeto_id>/preview_video")
    def preview_video(projeto_id):
        """Preview provisorio (concat + narracao, sem legendas/musica) da
        ordem ATUAL dos clipes - tela de reorganizacao manual (Feature B).
        Gerado sob demanda e cacheado em preview.mp4 + temp/preview_hash.txt
        (`_hash_ordem_clipes`) - so regenera se a ordem dos clipes mudou
        desde o ultimo preview (ex: apos um swap)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        indice = _ler_json_seguro(pasta_projeto / "clipes" / "indice.json")
        if not indice or not indice.get("clipes"):
            abort(404)

        hash_atual = _hash_ordem_clipes(indice)
        caminho_hash = pasta_projeto / "temp" / "preview_hash.txt"
        caminho_preview = pasta_projeto / "preview.mp4"

        hash_anterior = None
        if caminho_hash.exists():
            try:
                hash_anterior = caminho_hash.read_text(encoding="utf-8").strip()
            except OSError:
                hash_anterior = None

        if not caminho_preview.exists() or hash_anterior != hash_atual:
            if not _gerar_preview_video(pasta_projeto, indice):
                abort(404)
            try:
                caminho_hash.parent.mkdir(parents=True, exist_ok=True)
                caminho_hash.write_text(hash_atual, encoding="utf-8")
            except OSError:
                pass

        return send_from_directory(str(pasta_projeto), "preview.mp4")

    @app.route("/projetos/<projeto_id>/concluido")
    def concluido(projeto_id):
        """Tela de conclusao (CLAUDE.md secao 5.9): reune tudo que o
        projeto produziu - video final, thumbnail escolhida, titulos
        sugeridos/descricao/tags (Etapa 7 Grupo D), e dados do projeto
        (perfil/duracao/custo). Somente leitura - nenhuma acao de mutacao
        aqui, trocar thumbnail ou regerar briefing continua sendo so' na
        Etapa 7 (`/thumbnail`), quantas vezes o usuario quiser. Todo campo
        e' best-effort: projeto antigo sem thumbnail/tags/descricao
        simplesmente nao renderiza aquela secao, nunca quebra a tela."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        caminho_video = pasta_projeto / "saida" / "video_final.mp4"
        # Titulo canonico (sessao "titulo canonico - Burke Ramsey"):
        # titulo.txt e' a UNICA fonte de verdade do titulo do projeto -
        # gravado uma vez em /aprovar_roteiro a partir da escolha do
        # usuario na revisao (CLAUDE.md secao 5.5), nunca reescrito por
        # nenhuma etapa posterior. Esta tela NUNCA gera nem exibe um
        # conjunto de titulos concorrente - as outras 2 opcoes que o
        # usuario NAO escolheu (titulos_sugeridos.json, Etapa 3) aparecem
        # so' como referencia, claramente marcadas como nao utilizadas.
        caminho_titulo = pasta_projeto / "titulo.txt"
        titulo = caminho_titulo.read_text(encoding="utf-8").strip() if caminho_titulo.exists() else None

        thumbnail_disponivel = (pasta_projeto / "thumbnail" / "final.jpg").is_file()

        titulos_sugeridos_etapa3 = _ler_json_seguro(pasta_projeto / "titulos_sugeridos.json") or {}
        titulos_alternativos = [
            str(t).strip()
            for t in (titulos_sugeridos_etapa3.get("titulos") or [])
            if str(t).strip() and str(t).strip() != (titulo or "")
        ]

        metadados = _ler_json_seguro(pasta_projeto / "thumbnail" / "metadados.json") or {}
        descricao = str(metadados.get("description") or "").strip()
        tags = [str(t) for t in (metadados.get("tags") or []) if str(t).strip()]

        job_disco = _ler_job_json(pasta_projeto)
        perfil = (job_disco or {}).get("perfil")

        # Duracao do VIDEO FINAL - nao confundir com `tempo_total_s` de
        # montagem_metadata.json, que e' tempo de PROCESSAMENTO da Etapa 6
        # (achado real de sessao de refinamento: a tela mostrava "5:02"
        # rotulado "Duracao" quando o video tinha ~25min de fato, porque
        # lia `tempo_total_s`). Cascata: `duracao_video_s` persistido pela
        # Etapa 6 (scripts/6_montar_video.py, via ffprobe no momento da
        # montagem) -> ffprobe direto em saida/video_final.mp4 (cobre
        # projeto montado antes desta correcao existir) -> duracao da
        # narracao como ultimo recurso (aproximacao, video real pode
        # divergir por folga entre clipes).
        duracao_s = None
        montagem_metadata = _ler_json_seguro(pasta_projeto / "saida" / "montagem_metadata.json")
        if isinstance(montagem_metadata, dict) and isinstance(montagem_metadata.get("duracao_video_s"), (int, float)):
            duracao_s = montagem_metadata["duracao_video_s"]
        if not duracao_s and caminho_video.is_file():
            duracao_ffprobe = _obter_duracao_video_ffprobe(caminho_video)
            if duracao_ffprobe:
                duracao_s = duracao_ffprobe
        if not duracao_s:
            alinhamento = _ler_json_seguro(pasta_projeto / "narracao_alinhamento.json")
            if isinstance(alinhamento, dict) and isinstance(alinhamento.get("duracao_s"), (int, float)):
                duracao_s = alinhamento["duracao_s"]

        tempo_processamento_s = None
        if isinstance(montagem_metadata, dict) and isinstance(montagem_metadata.get("tempo_total_s"), (int, float)):
            tempo_processamento_s = montagem_metadata["tempo_total_s"]

        estado = _montar_estado_status(jobs.get(projeto_id), job_disco)

        return render_template(
            "concluido.html",
            projeto_id=projeto_id,
            titulo=titulo,
            video_disponivel=caminho_video.is_file(),
            thumbnail_disponivel=thumbnail_disponivel,
            titulos_alternativos=titulos_alternativos,
            descricao=descricao,
            tags=tags,
            perfil=perfil,
            duracao_s=duracao_s,
            tempo_processamento_s=tempo_processamento_s,
            custo_detalhado=_calcular_custo_detalhado_projeto(pasta_projeto),
            pipeline_steps=_parsear_pipeline_steps(estado, pasta_projeto, projeto_id),
        )

    @app.route("/projetos/<projeto_id>/saida/<nome_arquivo>")
    def servir_arquivo_saida(projeto_id, nome_arquivo):
        """Serve um arquivo de saida/ da pasta do projeto (video final,
        legendas avulsas) - usado pelo preview/download da tela de
        conclusao. Mesma protecao contra path traversal de
        `servir_arquivo_fonte`: `nome_arquivo` e' reduzido ao basename
        antes de qualquer uso."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None:
            abort(404)

        pasta_saida = pasta_projeto / "saida"
        nome_seguro = os.path.basename(nome_arquivo)
        if not nome_seguro or nome_seguro != nome_arquivo:
            abort(404)

        caminho_arquivo = pasta_saida / nome_seguro
        if not caminho_arquivo.is_file():
            abort(404)

        return send_from_directory(str(pasta_saida), nome_seguro)

    @app.route("/projetos/<projeto_id>/abrir_pasta", methods=["POST"])
    def abrir_pasta_projeto(projeto_id):
        """Abre a pasta do projeto no Explorer do Windows (CLAUDE.md secao
        5.11) - produto local, roda so' na maquina do proprio usuario, sem
        risco de abrir pasta de outra pessoa. Sem efeito (200 silencioso)
        em plataformas sem `os.startfile` (nao-Windows)."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        if pasta_projeto is None or not pasta_projeto.exists():
            abort(404)

        if hasattr(os, "startfile"):
            os.startfile(str(pasta_projeto))  # noqa: S606 - produto Windows-only, CLAUDE.md secao 13
        return jsonify({"status": "ok"})

    @app.route("/api/vozes/<provedor>/<idioma>")
    def api_vozes(provedor, idioma):
        """Lista as vozes curadas de `provedor` para `idioma` (CLAUDE.md
        secao 5.6/5.5) - usado pelo dropdown de voz da tela de revisao para
        popular as opcoes dinamicamente, com descricao e badge de
        recomendacao por perfil. 404 se o provedor nao existir; lista vazia
        (nunca 404) se o idioma nao tiver vozes curadas para esse provedor."""
        if provedor not in PROVEDORES_TTS:
            abort(404)
        try:
            instancia = get_provedor(provedor)
        except ProvedorTTSInvalidoError:
            abort(404)
        return jsonify(instancia.listar_vozes(idioma))

    @app.route("/api/preview_voz/<voz_id>")
    def api_preview_voz(voz_id):
        """Retorna a URL do preview MP3 de `voz_id` (CLAUDE.md secao 5.6).

        Provedor "google" (default, retrocompativel - sem `?provedor=` na
        query string): gera sob demanda na primeira selecao e serve do
        cache (static/previews_vozes/<idioma>/<voz_id>.mp3) depois. So
        recebe o voz_id - o idioma e' resolvido pelo proprio catalogo
        curado (scripts/tts/preview_vozes.py:buscar_idioma_da_voz), nunca
        por parametro do cliente.

        Provedor "darkplanner" (`?provedor=darkplanner`): a API ja devolve
        um preview_url pronto por voz (scripts/tts/darkplanner.py -
        campo `amostra_url`) - devolvido direto ao cliente, sem sintese
        nem cache local. Se o CDN da ElevenLabs bloquear a requisicao do
        navegador (referer/CORS), isso e' um erro de carregamento do
        proprio elemento <audio> no cliente (ver static/preview_voz.js),
        nao afeta esta rota nem bloqueia a geracao real do audio.

        Voz ja marcada indisponivel (falha anterior, so' se aplica ao
        provedor "google") responde direto sem nova tentativa de sintese.
        Nunca 500 - falha vira {"disponivel": false, "erro": "..."}."""
        provedor_nome = request.args.get("provedor", "google")

        if provedor_nome == "darkplanner":
            try:
                instancia = get_provedor("darkplanner")
            except ProvedorTTSInvalidoError:
                abort(404)
            voz = next((v for v in instancia.listar_vozes("") if v.get("id") == voz_id), None)
            if voz is None or not voz.get("amostra_url"):
                return jsonify({"disponivel": False, "url": None, "erro": "Preview indisponivel para esta voz."})
            return jsonify({"disponivel": True, "url": voz["amostra_url"], "erro": None})

        indisponiveis = preview_vozes.carregar_indisponiveis()
        if voz_id in indisponiveis:
            return jsonify({"disponivel": False, "url": None, "erro": indisponiveis[voz_id]})

        idioma = preview_vozes.buscar_idioma_da_voz(voz_id)
        if idioma is None:
            return (
                jsonify({"disponivel": False, "url": None, "erro": "Voz nao encontrada no catalogo curado."}),
                404,
            )

        resultado = preview_vozes.gerar_preview(voz_id, idioma)
        if not resultado["sucesso"]:
            return jsonify({"disponivel": False, "url": None, "erro": resultado["erro"]})

        url = url_for("static", filename=f"previews_vozes/{idioma}/{voz_id}.mp3")
        return jsonify({"disponivel": True, "url": url, "erro": None})

    @app.route("/api/regerar_previews_vozes", methods=["POST"])
    def api_regerar_previews_vozes():
        """Apaga o cache de previews inteiro e regenera tudo (botao
        "Regerar todos os previews" em Ajustes, secao TTS) - util depois
        de trocar o trecho de preview ou pra tentar de novo vozes que
        falharam antes."""
        resultado = preview_vozes.regerar_todos_previews()
        return jsonify(resultado)

    @app.route("/projetos/<projeto_id>/regerar_roteiro", methods=["POST"])
    def regerar_roteiro(projeto_id):
        """Reroda a Etapa 3 com feedback adicional do usuario (CLAUDE.md
        secao 5.5, botao "Refazer roteiro com instrucoes") - grava o
        feedback em entrada/feedback_regeneracao.txt (lido e injetado no
        prompt por scripts/3_gerar_roteiro.py, que apaga o arquivo apos
        sucesso) e dispara a Etapa 3 de novo."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")
        if status_atual != "aguardando_revisao":
            return (
                jsonify(
                    {
                        "erro": "status_invalido",
                        "mensagem": f"Projeto nao esta aguardando revisao de roteiro "
                        f"(status atual: {status_atual or 'desconhecido'}).",
                    }
                ),
                400,
            )
        if _ler_origem_roteiro(pasta_projeto) == "upload":
            return (
                jsonify(
                    {
                        "erro": "roteiro_importado",
                        "mensagem": "Este roteiro foi fornecido por upload - nao ha geracao via IA para refazer.",
                    }
                ),
                400,
            )

        feedback = request.form.get("feedback_usuario", "").strip()
        if not feedback:
            return (
                jsonify({"erro": "feedback_vazio", "mensagem": "Descreva o que deve mudar no roteiro."}),
                400,
            )

        (pasta_projeto / "entrada" / "feedback_regeneracao.txt").write_text(feedback, encoding="utf-8")

        _disparar_etapa3(projeto_id, pasta_projeto)
        return redirect(url_for("status", projeto_id=projeto_id))

    @app.route("/projetos/<projeto_id>/cancelar_projeto", methods=["POST"])
    def cancelar_projeto(projeto_id):
        """Apaga a pasta inteira do projeto (CLAUDE.md secao 5.5, botao
        "Cancelar projeto") - so permitido em status onde nao ha subprocess
        ativo (aguardando revisao/audio), para nunca apagar a pasta de um
        projeto com uma etapa rodando de verdade em outra thread."""
        pasta_projeto = _pasta_projeto_ou_none(projeto_id)
        job_disco = _ler_job_json(pasta_projeto)
        status_atual = (job_disco or {}).get("status")
        if status_atual not in STATUS_PERMITIDOS_REVISAO:
            return (
                jsonify(
                    {
                        "erro": "status_invalido",
                        "mensagem": f"Projeto nao pode ser cancelado neste status "
                        f"(status atual: {status_atual or 'desconhecido'}).",
                    }
                ),
                400,
            )

        try:
            shutil.rmtree(pasta_projeto)
        except OSError as exc:
            return (
                jsonify(
                    {
                        "erro": "falha_ao_apagar",
                        "mensagem": f"Nao foi possivel apagar a pasta do projeto: {exc}",
                    }
                ),
                500,
            )

        jobs.pop(projeto_id, None)
        return redirect(url_for("home", mensagem=f"Projeto {projeto_id} apagado"))

    @app.route("/api/status/<projeto_id>")
    def api_status(projeto_id):
        job = jobs.get(projeto_id)
        if job is None:
            return (
                jsonify(
                    {
                        "status": "nao_encontrado",
                        "detalhe": "Nenhum job em andamento para este projeto nesta sessao do servidor.",
                    }
                ),
                404,
            )

        projetos_dir = os.environ.get("PROJETOS_DIR", "")
        pasta_projeto = Path(projetos_dir) / projeto_id if projetos_dir else None
        job_disco = _ler_job_json(pasta_projeto)
        estado = _montar_estado_status(job, job_disco)
        fontes_baixadas, _mensagem_arquivos = _fontes_baixadas_com_origem(pasta_projeto)

        resposta = dict(job)
        resposta["pipeline_steps"] = _parsear_pipeline_steps(estado, pasta_projeto, projeto_id)
        resposta["arquivos_baixados"] = fontes_baixadas
        resposta["artefatos"] = _listar_artefatos(pasta_projeto)
        resposta["proxima_etapa_mensagem"] = estado.get("proxima_etapa_mensagem")
        # Labels amigaveis para exibicao (scripts/labels_ui.py) - "etapa"/
        # "status" originais sao preservados, o frontend continua usando
        # essas chaves tecnicas pra logica (statusEmAndamento, etc).
        if resposta.get("etapa"):
            resposta["etapa_label"] = label_etapa(resposta["etapa"])
        if resposta.get("status"):
            resposta["status_label"] = label_status(resposta["status"])
        return jsonify(resposta)

    @app.route("/sobre")
    def sobre():
        versao = _ler_versao()
        licenca = LICENSE_PATH.read_text(encoding="utf-8") if LICENSE_PATH.exists() else ""
        perfis = prompts_loader.listar_perfis_detalhado()
        for perfil in perfis:
            perfil["descricao_longa_html"] = markdown.markdown(perfil["descricao_longa_md"])
        return render_template("sobre.html", versao=versao, licenca=licenca, perfis=perfis)

    @app.route("/verificar_atualizacao")
    def verificar_atualizacao():
        return jsonify(
            {
                "versao_local": _ler_versao(),
                "versao_disponivel": None,
                "mensagem": "verificacao de atualizacoes nao implementada nesta versao",
            }
        )

    return app


def _ler_versao():
    if VERSION_PATH.exists():
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    return "desconhecida"


if __name__ == "__main__":
    app = create_app()
    porta = int(os.environ.get("PORTA", "5000"))
    app.run(host="0.0.0.0", port=porta, debug=False)
