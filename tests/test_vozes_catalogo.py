"""Testes de validacao do catalogo de vozes (scripts/tts/vozes_catalogo.json).

Valida que o arquivo JSON existe, e bem-formado, tem todos os idiomas
suportados, e que cada voz tem os campos obrigatorios (CLAUDE.md secao 3).
"""

import json
from pathlib import Path


def _carregar_catalogo():
    """Carrega o catalogo do arquivo real."""
    caminho = Path(__file__).resolve().parent.parent / "scripts" / "tts" / "vozes_catalogo.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Validacao geral do arquivo
# ---------------------------------------------------------------------------


def test_catalogo_arquivo_existe():
    """Arquivo vozes_catalogo.json deve existir."""
    caminho = Path(__file__).resolve().parent.parent / "scripts" / "tts" / "vozes_catalogo.json"
    assert caminho.exists(), "vozes_catalogo.json nao encontrado"


def test_catalogo_json_valido():
    """Arquivo JSON deve ser valido e parsavel."""
    catalogo = _carregar_catalogo()
    assert isinstance(catalogo, dict)


def test_catalogo_tem_google():
    """Catalogo deve ter entradas para o provedor 'google'."""
    catalogo = _carregar_catalogo()
    assert "google" in catalogo
    assert isinstance(catalogo["google"], dict)


# ---------------------------------------------------------------------------
# Idiomas suportados (CLAUDE.md secao 3)
# ---------------------------------------------------------------------------


def test_catalogo_tem_idiomas_suportados():
    """Catalogo deve ter todos os idiomas obrigatorios do MVP."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    idiomas_obrigatorios = ["en-US", "en-GB", "pt-BR", "es", "de"]

    for idioma in idiomas_obrigatorios:
        assert idioma in google, f"Idioma '{idioma}' nao encontrado no catalogo"
        assert isinstance(google[idioma], list)
        assert len(google[idioma]) > 0, f"Nenhuma voz para o idioma '{idioma}'"


# ---------------------------------------------------------------------------
# Campos obrigatorios de cada voz
# ---------------------------------------------------------------------------


def test_catalogo_cada_voz_tem_campos_obrigatorios():
    """Cada voz deve ter os campos obrigatorios: id, genero, descricao,
    recomendada_para, amostra_url."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    campos_obrigatorios = {"id", "genero", "descricao", "recomendada_para", "amostra_url"}

    for idioma, vozes in google.items():
        for voz in vozes:
            campos = set(voz.keys())
            assert campos_obrigatorios.issubset(campos), (
                f"Voz '{voz.get('id', '???')}' no idioma '{idioma}' "
                f"faltam campos: {campos_obrigatorios - campos}"
            )


def test_catalogo_campo_id_valido():
    """Campo 'id' deve ser uma string nao vazia."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            assert isinstance(voz["id"], str), f"id nao e' string no idioma '{idioma}'"
            assert len(voz["id"]) > 0, f"id vazio no idioma '{idioma}'"


def test_catalogo_campo_genero_valido():
    """Campo 'genero' deve ser 'masculina' ou 'feminina'."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            genero = voz["genero"]
            assert genero in {"masculina", "feminina"}, (
                f"Genero invalido '{genero}' na voz '{voz['id']}' "
                f"({idioma}) - deve ser 'masculina' ou 'feminina'"
            )


def test_catalogo_campo_descricao_valido():
    """Campo 'descricao' deve ser uma string."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            assert isinstance(voz["descricao"], str), (
                f"Descricao nao e' string na voz '{voz['id']}' ({idioma})"
            )
            assert len(voz["descricao"]) > 0, (
                f"Descricao vazia na voz '{voz['id']}' ({idioma})"
            )


def test_catalogo_campo_recomendada_para_valido():
    """Campo 'recomendada_para' deve ser uma lista de strings (nomes de perfis)."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    perfis_validos = {"truecrime", "atualidades_narrativas", "historia"}

    for idioma, vozes in google.items():
        for voz in vozes:
            rec = voz["recomendada_para"]
            assert isinstance(rec, list), (
                f"recomendada_para nao e' lista na voz '{voz['id']}' ({idioma})"
            )
            for perfil in rec:
                assert isinstance(perfil, str), (
                    f"Elemento de recomendada_para nao e' string "
                    f"na voz '{voz['id']}' ({idioma})"
                )
                assert perfil in perfis_validos, (
                    f"Perfil invalido '{perfil}' em recomendada_para "
                    f"da voz '{voz['id']}' ({idioma})"
                )


# ---------------------------------------------------------------------------
# Protecao de custo (CLAUDE.md secao 5.6)
# ---------------------------------------------------------------------------


def test_catalogo_todas_vozes_sao_wavenet():
    """Protecao de custo: todas as vozes devem ser Wavenet (o tier permitido).
    Neural2, Chirp3-HD, Studio sao tiers mais caros que nao devem estar no MVP."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            voz_id = voz["id"]
            assert "Wavenet" in voz_id, (
                f"Voz '{voz_id}' no idioma '{idioma}' nao e' Wavenet - "
                f"verificar se e' Neural2, Chirp3-HD ou outro tier caro"
            )


def test_catalogo_nao_contem_neural2():
    """Nenhuma voz Neural2 no catalogo (custo $16/1M chars vs Wavenet $4/1M)."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            assert "Neural2" not in voz["id"], (
                f"Voz Neural2 encontrada: '{voz['id']}' ({idioma}). "
                f"Remover - so Wavenet e' permitido no MVP."
            )


def test_catalogo_nao_contem_chirp3():
    """Nenhuma voz Chirp3-HD no catalogo (custo $30/1M chars)."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            assert "Chirp3" not in voz["id"], (
                f"Voz Chirp3-HD encontrada: '{voz['id']}' ({idioma}). "
                f"Remover - so Wavenet e' permitido no MVP."
            )


def test_catalogo_nao_contem_studio():
    """Nenhuma voz Studio no catalogo (custo $160/1M chars - extremamente caro)."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        for voz in vozes:
            assert "Studio" not in voz["id"], (
                f"Voz Studio encontrada: '{voz['id']}' ({idioma}). "
                f"Remover - so Wavenet e' permitido no MVP."
            )


# ---------------------------------------------------------------------------
# Distribuicao de vozes por genero
# ---------------------------------------------------------------------------


def test_catalogo_cada_idioma_tem_vozes_masculinas_e_femininas():
    """Cada idioma deve ter pelo menos uma voz masculina e uma feminina."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        generos = {voz["genero"] for voz in vozes}
        assert "masculina" in generos, f"Idioma '{idioma}' nao tem voz masculina"
        assert "feminina" in generos, f"Idioma '{idioma}' nao tem voz feminina"


# ---------------------------------------------------------------------------
# Consistencia entre idiomas
# ---------------------------------------------------------------------------


def test_catalogo_en_us_cobertura():
    """en-US (idioma padrao do MVP) deve ter cobertura razoavel de vozes."""
    catalogo = _carregar_catalogo()
    vozes_en_us = catalogo["google"]["en-US"]

    # en-US eh o padrao, deve ter pelo menos 5 opcoes
    assert len(vozes_en_us) >= 5, (
        f"en-US tem apenas {len(vozes_en_us)} vozes - "
        f"deveria ter pelo menos 5 opcoes"
    )


def test_catalogo_ids_unicos_por_idioma():
    """Dentro de cada idioma, IDs de vozes nao devem se repetir."""
    catalogo = _carregar_catalogo()
    google = catalogo["google"]

    for idioma, vozes in google.items():
        ids = [voz["id"] for voz in vozes]
        unicos = set(ids)
        assert len(ids) == len(unicos), (
            f"Idioma '{idioma}' tem IDs duplicados: "
            f"{[id_ for id_ in ids if ids.count(id_) > 1]}"
        )
