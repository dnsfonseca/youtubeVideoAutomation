"""Traducoes de strings tecnicas (status/etapa/provedor/tipo de projeto)
para labels amigaveis exibidos ao usuario na UI.

Modulo autocontido (sem depender de server.py) para poder ser importado
tanto por server.py (registro dos filtros Jinja) quanto por testes
isolados. Os dicts aqui sao a UNICA fonte da verdade para esses labels -
nao duplicar em templates/JS.

IMPORTANTE: usar so' para EXIBICAO. Nunca usar o resultado destas funcoes
em comparacao logica (if status == label_status(...) etc.) - a logica
interna do pipeline continua comparando as chaves tecnicas originais
("em_andamento", "geracao_clipes", etc), nunca os labels traduzidos.
"""

STATUS_LABEL = {
    "pendente": "Pendente",
    "em_andamento": "Em andamento",
    "aguardando_revisao": "Aguardando revisão",
    "aguardando_audio": "Aguardando áudio",
    "aguardando_geracao_clipes": "Gerando clipes",
    "aguardando_legendas": "Aguardando legendas",
    "aguardando_reorganizacao": "Aguardando reorganização",
    "aguardando_thumbnail": "Aguardando thumbnail",
    "concluido": "Concluído",
    "erro": "Erro",
    "falhou": "Falhou",
}

# Ordem das etapas do pipeline (usada tambem pela barra horizontal em
# server.py:_parsear_pipeline_steps para achar o indice da etapa atual) +
# label amigavel de cada uma.
PIPELINE_ETAPAS = (
    ("download", "Download"),
    ("transcricao", "Transcrição"),
    ("roteiro", "Roteiro + Revisão"),
    ("audio", "Áudio"),
    ("geracao_clipes", "Clipes"),
    ("montagem", "Montagem"),
    ("thumbnail", "Thumbnail"),
)

ETAPA_LABEL = dict(PIPELINE_ETAPAS)

# Nome de exibicao de cada provedor TTS (tela de revisao - CLAUDE.md secao
# 5.5 - e dropdown de padrao em Ajustes).
PROVEDOR_TTS_LABEL = {
    "google": "Google Cloud TTS",
    "darkplanner": "DarkPlanner (ElevenLabs)",
    "elevenlabs": "ElevenLabs",
    "openai": "OpenAI",
    "azure": "Azure",
}

TIPO_PROJETO_LABEL = {
    "pipeline_completa": "Pipeline completa",
    "videos_pre_gerados": "Vídeos pré-gerados",
}


def label_status(chave: str) -> str:
    return STATUS_LABEL.get(chave, chave)


def label_etapa(chave: str) -> str:
    return ETAPA_LABEL.get(chave, chave)


def label_tipo_projeto(chave: str) -> str:
    return TIPO_PROJETO_LABEL.get(chave, chave)


def label_provedor_tts(chave: str) -> str:
    return PROVEDOR_TTS_LABEL.get(chave, chave)
