"""Testes de scripts/labels_ui.py (traducao de strings tecnicas para labels
amigaveis - sessao de polimento pre-uso real, Grupo A)."""

from scripts import labels_ui


def test_label_status_traduz_em_andamento():
    assert labels_ui.label_status("em_andamento") == "Em andamento"


def test_label_status_traduz_concluido():
    assert labels_ui.label_status("concluido") == "Concluído"


def test_label_status_fallback_retorna_chave_se_nao_mapeada():
    assert labels_ui.label_status("chave_desconhecida") == "chave_desconhecida"


def test_label_etapa_traduz_geracao_clipes():
    assert labels_ui.label_etapa("geracao_clipes") == "Clipes"


def test_label_etapa_fallback_retorna_chave_se_nao_mapeada():
    # "planejamento" e' o nome orfao legado (CLAUDE.md, migracao
    # PROXIMA_ETAPA_MIGRATION em server.py) - nunca chega ate' aqui em
    # producao porque server.py migra pra "geracao_clipes" antes, mas o
    # filtro nao deve quebrar se receber uma chave assim mesmo.
    assert labels_ui.label_etapa("planejamento") == "planejamento"


def test_label_tipo_projeto_traduz_videos_pre_gerados():
    assert labels_ui.label_tipo_projeto("videos_pre_gerados") == "Vídeos pré-gerados"


def test_label_provedor_tts_traduz_google():
    assert labels_ui.label_provedor_tts("google") == "Google Cloud TTS"


def test_label_provedor_tts_fallback_retorna_chave_se_nao_mapeada():
    assert labels_ui.label_provedor_tts("provedor_novo") == "provedor_novo"


def test_pipeline_etapas_e_etapa_label_ficam_em_sincronia():
    # ETAPA_LABEL e' derivado de PIPELINE_ETAPAS - garante que nao
    # divergem se um dos dois for editado sem o outro.
    assert labels_ui.ETAPA_LABEL == dict(labels_ui.PIPELINE_ETAPAS)
