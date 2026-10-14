"""Testes da Etapa 7 (scripts/7_thumbnail.py) - geracao de thumbnail.

Cobre o Grupo B (upload de sujeitos com papel declarado, sem recorte) e o
wiring do Grupo C (briefing exportavel) dentro de gerar_metadados/
regenerar_thumbnail_briefing/gerar_briefing_thumbnail - os testes PUROS do
Grupo C (scripts/thumbnail_briefing.py: montagem de prompt por template,
selecao de template, atributos por foto) vivem em
tests/test_thumbnail_briefing.py.

Sessao de simplificacao da Etapa 7 (ver HISTORICO_BUGS.md): o Grupo A
(scan de frames de cenario via ffmpeg/OpenCV) e o recorte de sujeito via
rembg saem daqui - as duas coisas foram removidas por inteiro, so'
serviam aos 5 templates de composicao via Pillow (tambem removidos).

Convencoes (CLAUDE.md secao 8):
- Nunca chama a API real da Anthropic - `cliente=` fake em toda funcao que
  chama a IA (mesmo padrao de tests/test_sincronizador_visual.py).
- `7_thumbnail.py` comeca com digito - nao e' importavel como modulo
  normal, carregado via importlib.util.spec_from_file_location (mesmo
  padrao de tests/test_montar_video.py).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
CAMINHO_SCRIPT = BASE_DIR / "scripts" / "7_thumbnail.py"

_spec = importlib.util.spec_from_file_location("thumbnail_etapa7", CAMINHO_SCRIPT)
thumb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = thumb
_spec.loader.exec_module(thumb)


# ---------------------------------------------------------------------------
# Fakes do cliente Anthropic (Grupo B) - mesmo padrao de
# tests/test_sincronizador_visual.py
# ---------------------------------------------------------------------------


class _ClienteFake:
    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if not self._respostas:
            raise AssertionError("ClienteFake: mais chamadas do que respostas configuradas")
        return self._respostas.pop(0)


class _ClienteQuebrado:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise RuntimeError("falha simulada de rede")


def _resposta_tool_use(nome_tool, dados_input, tokens_in=100, tokens_out=20):
    return {
        "content": [{"type": "tool_use", "name": nome_tool, "id": "toolu_1", "input": dados_input}],
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }


def _resposta_sem_tool_use():
    return {"content": [{"type": "text", "text": "recuso responder"}], "usage": {"input_tokens": 10, "output_tokens": 5}}


# ---------------------------------------------------------------------------
# _ler_lista_json / _ler_dict_json_ou_none
# ---------------------------------------------------------------------------


def test_ler_lista_json_arquivo_ausente_retorna_vazio(tmp_path):
    assert thumb._ler_lista_json(tmp_path / "nao_existe.json") == []


def test_ler_lista_json_malformado_retorna_vazio(tmp_path):
    caminho = tmp_path / "quebrado.json"
    caminho.write_text("{nao e json valido", encoding="utf-8")
    assert thumb._ler_lista_json(caminho) == []


def test_ler_lista_json_nao_e_lista_retorna_vazio(tmp_path):
    caminho = tmp_path / "obj.json"
    caminho.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert thumb._ler_lista_json(caminho) == []


def test_ler_dict_json_ou_none_arquivo_ausente(tmp_path):
    assert thumb._ler_dict_json_ou_none(tmp_path / "nada.json") is None


def test_ler_dict_json_ou_none_lista_retorna_none(tmp_path):
    caminho = tmp_path / "lista.json"
    caminho.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert thumb._ler_dict_json_ou_none(caminho) is None


# ---------------------------------------------------------------------------
# _ler_lista_clipes - tolera os dois formatos de clipes/indice.json
# (bug real: 5_gerar_clipes.py grava dict com envelope {"clipes": [...],
# "metadata": {...}}, nao lista pura - 7_thumbnail.py lia com
# _ler_lista_json, que so' aceita lista, e devolvia vazio mesmo com o
# projeto tendo 148 clipes de verdade)
# ---------------------------------------------------------------------------


def test_ler_lista_clipes_arquivo_ausente_retorna_vazio(tmp_path):
    assert thumb._ler_lista_clipes(tmp_path / "nao_existe.json") == []


def test_ler_lista_clipes_lista_pura_funciona(tmp_path):
    caminho = tmp_path / "indice.json"
    lista = [{"arquivo": "c.mp4", "clipe_id": "c0", "duracao_s": 5.0}]
    caminho.write_text(json.dumps(lista), encoding="utf-8")
    assert thumb._ler_lista_clipes(caminho) == lista


def test_ler_lista_clipes_formato_real_etapa5_dict_com_envelope(tmp_path):
    """Formato REAL gravado por 5_gerar_clipes.py (linha ~773) - dict com
    "clipes" e "metadata", nao lista pura."""
    caminho = tmp_path / "indice.json"
    clipes = [
        {"arquivo": "clipe001.mp4", "clipe_id": "clipe001", "duracao_s": 7.5},
        {"arquivo": "clipe002.mp4", "clipe_id": "clipe002", "duracao_s": 6.2},
    ]
    caminho.write_text(
        json.dumps({"clipes": clipes, "metadata": {"total_clipes": 2, "duracao_total_s": 13.7}}),
        encoding="utf-8",
    )
    assert thumb._ler_lista_clipes(caminho) == clipes


def test_ler_lista_clipes_dict_sem_chave_clipes_retorna_vazio(tmp_path):
    caminho = tmp_path / "indice.json"
    caminho.write_text(json.dumps({"metadata": {}}), encoding="utf-8")
    assert thumb._ler_lista_clipes(caminho) == []


def test_ler_lista_clipes_malformado_retorna_vazio(tmp_path):
    caminho = tmp_path / "quebrado.json"
    caminho.write_text("{nao e json valido", encoding="utf-8")
    assert thumb._ler_lista_clipes(caminho) == []


# ---------------------------------------------------------------------------
# _validar_pre_condicoes (CLAUDE.md secao 18.6)
# ---------------------------------------------------------------------------


def test_validar_pre_condicoes_pasta_ausente(tmp_path):
    ok, mensagem, tipo_erro = thumb._validar_pre_condicoes(tmp_path / "nao_existe")
    assert ok is False
    assert tipo_erro == "pasta_ausente"


def test_validar_pre_condicoes_clipes_ausentes(tmp_path):
    ok, mensagem, tipo_erro = thumb._validar_pre_condicoes(tmp_path)
    assert ok is False
    assert tipo_erro == "clipes_ausentes"


def test_validar_pre_condicoes_video_final_ausente(tmp_path):
    (tmp_path / "clipes").mkdir()
    (tmp_path / "clipes" / "indice.json").write_text(
        json.dumps([{"arquivo": "c.mp4", "clipe_id": "c0", "duracao_s": 5.0}]), encoding="utf-8"
    )
    ok, mensagem, tipo_erro = thumb._validar_pre_condicoes(tmp_path)
    assert ok is False
    assert tipo_erro == "video_final_ausente"


def test_validar_pre_condicoes_tudo_presente(tmp_path):
    (tmp_path / "clipes").mkdir()
    (tmp_path / "clipes" / "indice.json").write_text(
        json.dumps([{"arquivo": "c.mp4", "clipe_id": "c0", "duracao_s": 5.0}]), encoding="utf-8"
    )
    (tmp_path / "saida").mkdir()
    (tmp_path / "saida" / "video_final.mp4").touch()
    ok, mensagem, tipo_erro = thumb._validar_pre_condicoes(tmp_path)
    assert ok is True
    assert mensagem is None
    assert tipo_erro is None


def test_validar_pre_condicoes_tudo_presente_formato_real_etapa5(tmp_path):
    """Regressao do bug real: clipes/indice.json no formato que
    5_gerar_clipes.py grava de verdade (dict com envelope "clipes"/
    "metadata"), nao lista pura. Antes da correcao, _validar_pre_condicoes
    lia isso com _ler_lista_json, recebia [] do dict, e recusava com
    "clipes_ausentes" mesmo com o arquivo integro e clipes reais dentro."""
    (tmp_path / "clipes").mkdir()
    (tmp_path / "clipes" / "indice.json").write_text(
        json.dumps(
            {
                "clipes": [{"arquivo": "c.mp4", "clipe_id": "c0", "duracao_s": 5.0}],
                "metadata": {"total_clipes": 1},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "saida").mkdir()
    (tmp_path / "saida" / "video_final.mp4").touch()
    ok, mensagem, tipo_erro = thumb._validar_pre_condicoes(tmp_path)
    assert ok is True
    assert mensagem is None
    assert tipo_erro is None


# ---------------------------------------------------------------------------
# GRUPO B - atualizar_sujeito_slot / remover_sujeito_slot (cascata de 2
# slots, sem recorte nenhum - a foto original e' o que a composicao por
# IA usa direto)
# ---------------------------------------------------------------------------


def test_atualizar_sujeito_slot_grava_sujeitos_json(tmp_path):
    resultado = thumb.atualizar_sujeito_slot(tmp_path, "hero", "hero.jpg", "vitima")
    assert resultado["sucesso"] is True
    persistido = json.loads((tmp_path / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    assert persistido == {"hero": {"arquivo": "hero.jpg", "papel": "vitima"}, "secondary": None}


def test_atualizar_sujeito_slot_preserva_o_outro_slot(tmp_path):
    thumb.atualizar_sujeito_slot(tmp_path, "hero", "hero.jpg", "vitima")
    thumb.atualizar_sujeito_slot(tmp_path, "secondary", "secondary.png", "suspeito")
    persistido = json.loads((tmp_path / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    assert persistido == {
        "hero": {"arquivo": "hero.jpg", "papel": "vitima"},
        "secondary": {"arquivo": "secondary.png", "papel": "suspeito"},
    }


def test_atualizar_sujeito_slot_invalido_nao_grava(tmp_path):
    resultado = thumb.atualizar_sujeito_slot(tmp_path, "terciario", "x.jpg", "vitima")
    assert resultado == {"sucesso": False, "erro": "slot_invalido"}
    assert not (tmp_path / "thumbnail" / "sujeitos" / "sujeitos.json").exists()


def test_atualizar_sujeito_slot_papel_invalido_nao_grava(tmp_path):
    resultado = thumb.atualizar_sujeito_slot(tmp_path, "hero", "x.jpg", "vilao")
    assert resultado == {"sucesso": False, "erro": "papel_invalido"}
    assert not (tmp_path / "thumbnail" / "sujeitos" / "sujeitos.json").exists()


def test_remover_sujeito_slot_esvazia_o_slot(tmp_path):
    thumb.atualizar_sujeito_slot(tmp_path, "hero", "hero.jpg", "vitima")

    resultado = thumb.remover_sujeito_slot(tmp_path, "hero")

    assert resultado["sucesso"] is True
    assert resultado["sujeitos"]["hero"] is None
    persistido = json.loads((tmp_path / "thumbnail" / "sujeitos" / "sujeitos.json").read_text(encoding="utf-8"))
    assert persistido["hero"] is None


def test_remover_sujeito_slot_invalido(tmp_path):
    resultado = thumb.remover_sujeito_slot(tmp_path, "terciario")
    assert resultado == {"sucesso": False, "erro": "slot_invalido"}


# ---------------------------------------------------------------------------
# GRUPO D - _normalizar_thumbnail_metadados (fallbacks de enum, pura).
# `layout`/`style` saíram do schema na sessão de simplificação da Etapa 7 -
# só serviam aos templates Pillow removidos.
# ---------------------------------------------------------------------------


def test_normalizar_thumbnail_metadados_aceita_valores_validos():
    dados = {
        "subject_name": "Fulano",
        "headline": "ELE FUGIU DA POLICIA",
        "emphasis_word": "FUGIU",
        "secondary": "caso aberto",
        "accent": "amber",
        "censor": True,
        "background_prompt": "dark forest at night",
    }
    resultado = thumb._normalizar_thumbnail_metadados(dados)
    assert resultado["accent"] == "amber"
    assert resultado["emphasis_word"] == "FUGIU"
    assert resultado["censor"] is True


def test_normalizar_thumbnail_metadados_accent_invalido_cai_no_padrao():
    resultado = thumb._normalizar_thumbnail_metadados({"accent": "roxo"})
    assert resultado["accent"] == thumb.ACCENT_PADRAO == "red"


def test_normalizar_thumbnail_metadados_emphasis_word_ausente_do_headline_e_ignorada():
    resultado = thumb._normalizar_thumbnail_metadados(
        {"headline": "O CASO DO SECULO", "emphasis_word": "PALAVRA_QUE_NAO_APARECE"}
    )
    assert resultado["emphasis_word"] == ""


def test_normalizar_thumbnail_metadados_emphasis_word_vazia_fica_vazia():
    resultado = thumb._normalizar_thumbnail_metadados({"headline": "TITULO", "emphasis_word": "  "})
    assert resultado["emphasis_word"] == ""


def test_normalizar_thumbnail_metadados_campos_ausentes_nao_derruba():
    resultado = thumb._normalizar_thumbnail_metadados({})
    assert resultado["accent"] == "red"
    assert resultado["headline"] == ""
    assert resultado["emphasis_word"] == ""
    assert resultado["secondary"] == ""
    assert resultado["subject_name"] == ""
    assert resultado["censor"] is False
    assert resultado["background_prompt"] == ""
    assert "layout" not in resultado
    assert "style" not in resultado


def test_normalizar_thumbnail_metadados_dados_none_nao_derruba():
    resultado = thumb._normalizar_thumbnail_metadados(None)
    assert resultado["accent"] == "red"


# ---------------------------------------------------------------------------
# GRUPO D - gerar_metadados / metadados_desatualizados
# ---------------------------------------------------------------------------


def _resposta_metadados(thumbnail_overrides=None, tokens_in=500, tokens_out=200):
    thumbnail = {
        "subject_name": "Fulano de Tal",
        "headline": "O CASO CHOCOU A CIDADE",
        "emphasis_word": "CHOCOU",
        "secondary": "investigacao em andamento",
        "accent": "red",
        "censor": False,
        "background_prompt": "dark alley at night, police lights",
    }
    thumbnail.update(thumbnail_overrides or {})
    dados = {
        "description": "Descricao do video.",
        "tags": ["true crime", "caso real"],
        "thumbnail": thumbnail,
    }
    return _resposta_tool_use(thumb.NOME_TOOL_METADADOS, dados, tokens_in=tokens_in, tokens_out=tokens_out)


# ---------------------------------------------------------------------------
# GRUPO 3 (sessao "conceito visual", Parte 2) - `gerar_metadados`/
# `regenerar_thumbnail_briefing` chamam `headline_engine.gerar_headline`
# PRIMEIRO agora (ver docstrings em scripts/7_thumbnail.py). Um `_ClienteFake`
# com respostas enfileiradas SO' pra' `_chamar_claude_metadados` (padrao
# usado em quase todo teste deste arquivo antes desta sessao) faz o Headline
# Engine consumir/rejeitar a PRIMEIRA resposta da fila, derrubando o teste
# cedo. `_mockar_headline_engine` substitui `headline_engine.gerar_headline`
# por inteiro (mesmo padrao ja usado, e' ja' verde, por
# `test_gerar_metadados_custo_usd_estimado_exclui_o_headline_engine` e
# `test_gerar_metadados_reconciliacao_e_so_auditoria_titulo_escolhido_nunca_muda`)
# - o Headline Engine nunca toca `cliente_api.messages.create`, entao a fila
# do `_ClienteFake` fica exclusiva pra' `_chamar_claude_metadados` (e
# `reconciliar_titulos_com_headline`, quando titulo.txt existir).
# ---------------------------------------------------------------------------


def _resultado_headline_engine_fake(
    headline="HEADLINE FAKE",
    emphasis_word="",
    mechanism=None,
    withheld_fact=None,
    judge_score=None,
    nucleo_editorial_status=None,
    fallback_usado=False,
    aviso_revisao_humana=False,
    fallback_sem_julgamento=False,
    conceito_visual=None,
):
    return {
        "sucesso": True,
        "headline": headline,
        "emphasis_word": emphasis_word,
        "mechanism": mechanism,
        "withheld_fact": withheld_fact,
        "judge_score": judge_score,
        "nucleo_editorial_status": nucleo_editorial_status,
        "fallback_usado": fallback_usado,
        "aviso_revisao_humana": aviso_revisao_humana,
        "fallback_sem_julgamento": fallback_sem_julgamento,
        "conceito_visual": conceito_visual,
    }


def _mockar_headline_engine(monkeypatch, **overrides):
    """Substitui `headline_engine.gerar_headline` por um fake que nunca
    chama a API real - ver bloco de comentario acima. Devolve o dict fake
    (util quando o teste quer inspecionar o `headline`/`conceito_visual`
    usado)."""
    resultado = _resultado_headline_engine_fake(**overrides)

    def _fake(pasta_projeto, roteiro_texto, api_key=None, modelo=None, cliente=None, _custos=None):
        return resultado

    monkeypatch.setattr(thumb.headline_engine, "gerar_headline", _fake)
    return resultado


def test_gerar_metadados_roteiro_ausente_retorna_erro(tmp_path):
    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=_ClienteFake([]))
    assert resultado == {"sucesso": False, "erro": "roteiro_ausente"}


def test_gerar_metadados_roteiro_vazio_retorna_erro(tmp_path):
    (tmp_path / "roteiro_aprovado.md").write_text("   ", encoding="utf-8")
    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=_ClienteFake([]))
    assert resultado == {"sucesso": False, "erro": "roteiro_vazio"}


def test_gerar_metadados_cliente_indisponivel(tmp_path):
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso.", encoding="utf-8")
    resultado = thumb.gerar_metadados(tmp_path, api_key=None, cliente=None)
    assert resultado == {"sucesso": False, "erro": "cliente_indisponivel"}


def test_gerar_metadados_sucesso_persiste_arquivo_e_normaliza(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados({"accent": "cor_invalida"})])
    custos = []
    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente, _custos=custos)

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["thumbnail"]["accent"] == "red"  # fallback aplicado
    assert resultado["metadados"]["thumbnail"]["subject_name"] == "Fulano de Tal"
    # Sem titulo.txt/titulos_sugeridos.json neste projeto de teste - Grupo D
    # NUNCA gera titulo (sessao "titulo canonico"), so' reflete o que existe
    # no disco (nada, aqui).
    assert resultado["metadados"]["titulo_escolhido"] == ""
    assert resultado["metadados"]["titulos_alternativos"] == []
    assert len(custos) == 1 and custos[0] > 0

    caminho = tmp_path / "thumbnail" / "metadados.json"
    assert caminho.exists()
    persistido = json.loads(caminho.read_text(encoding="utf-8"))
    assert persistido == resultado["metadados"]
    assert "roteiro_hash" in persistido

    # cache_control marcado no bloco de texto do roteiro (input cacheado).
    conteudo = cliente.chamadas[0]["messages"][0]["content"]
    assert conteudo[0]["cache_control"] == {"type": "ephemeral"}


def test_gerar_metadados_persiste_custo_usd_estimado(tmp_path, monkeypatch):
    """Correcao de sessao de refinamento: antes desta correcao, o custo das
    chamadas de Grupo D (metadados) e Grupo C (briefing) era calculado e
    imediatamente descartado - `_calcular_custo_detalhado_projeto`
    (server.py) nao tinha de onde somar. Agora `metadados.json` persiste
    `custo_usd_estimado` (top-level, fora do sub-dict `thumbnail` - assim
    `thumbnail_salvar_textos` nunca apaga esse campo, ja que so' mexe em
    `metadados["thumbnail"]`)."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["custo_usd_estimado"] > 0

    persistido = json.loads((tmp_path / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["custo_usd_estimado"] == resultado["metadados"]["custo_usd_estimado"]


def test_gerar_metadados_custo_usd_estimado_exclui_o_headline_engine(tmp_path, monkeypatch):
    """O Headline Engine persiste seu PROPRIO custo em
    thumbnail/headline_engine.json (ja somado a parte por
    `_calcular_custo_detalhado_projeto`) - `metadados.json.custo_usd_estimado`
    tem que cobrir SO' Grupo D + Grupo C, nunca incluir o custo do Headline
    Engine (contaria duas vezes no total da tela de conclusao)."""
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    def _headline_engine_fake(pasta_projeto, roteiro_texto, api_key=None, modelo=None, cliente=None, _custos=None):
        # Simula custo REAL do Headline Engine registrado no _custos
        # compartilhado (mesmo contrato de scripts/headline_engine.py) - se
        # gerar_metadados indevidamente somasse isso em custo_usd_estimado,
        # o teste abaixo pegaria.
        if _custos is not None:
            _custos.append(999.0)
        return {
            "sucesso": True,
            "headline": "HEADLINE FAKE",
            "emphasis_word": "",
            "mechanism": None,
            "withheld_fact": None,
            "judge_score": None,
            "nucleo_editorial_status": None,
            "fallback_usado": False,
            "aviso_revisao_humana": False,
            "fallback_sem_julgamento": False,
        }

    monkeypatch.setattr(thumb.headline_engine, "gerar_headline", _headline_engine_fake)

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    # Bem abaixo do valor absurdo que o Headline Engine fake devolveria se
    # (por engano) fosse somado em custo_usd_estimado.
    assert resultado["metadados"]["custo_usd_estimado"] < 1.0


def test_gerar_metadados_resposta_sem_tool_use_retorna_erro(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_sem_tool_use()])
    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)
    assert resultado == {"sucesso": False, "erro": "resposta_invalida"}


def test_gerar_metadados_excecao_da_api_nunca_propaga(tmp_path):
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=_ClienteQuebrado())
    assert resultado == {"sucesso": False, "erro": "chamada_api_falhou"}


def test_metadados_desatualizados_sem_roteiro_ou_sem_metadados_e_true(tmp_path):
    assert thumb.metadados_desatualizados(tmp_path) is True
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    assert thumb.metadados_desatualizados(tmp_path) is True  # roteiro existe, metadados nao


def test_metadados_desatualizados_false_logo_apos_gerar(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro original.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])
    thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)
    assert thumb.metadados_desatualizados(tmp_path) is False


def test_metadados_desatualizados_true_apos_editar_roteiro(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro original.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])
    thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro EDITADO pelo humano.", encoding="utf-8")
    assert thumb.metadados_desatualizados(tmp_path) is True


def test_metadados_desatualizados_nunca_regera_sozinho(tmp_path, monkeypatch):
    """metadados_desatualizados so' LE estado - nao chama a API nem
    reescreve thumbnail/metadados.json."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro original.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])
    thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)
    conteudo_antes = (tmp_path / "thumbnail" / "metadados.json").read_text(encoding="utf-8")

    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro mudou.", encoding="utf-8")
    thumb.metadados_desatualizados(tmp_path)

    conteudo_depois = (tmp_path / "thumbnail" / "metadados.json").read_text(encoding="utf-8")
    assert conteudo_antes == conteudo_depois
    # 1 = so' a chamada de metadados (Grupo D) - o Headline Engine esta'
    # mockado por inteiro (`_mockar_headline_engine`, GRUPO 3 desta sessao)
    # e nunca toca `cliente_api.messages.create`. Sem titulo.txt neste
    # projeto de teste, reconciliar_titulos_com_headline nem chega a tentar
    # uma chamada (titulo_escolhido vazio - ver
    # test_reconciliar_titulos_sem_titulos_nao_chama_api).
    assert len(cliente.chamadas) == 1


# ---------------------------------------------------------------------------
# GRUPO C (sessao de correcao do bug do background_prompt) - reparo unico em
# gerar_metadados quando o background_prompt volta trivial (vazio ou abaixo
# de thumbnail_templates.BACKGROUND_PROMPT_MIN_CHARS), e regenerar_thumbnail_
# briefing (regeneracao parcial pedida pelo usuario - preserva title/
# description/tags).
# ---------------------------------------------------------------------------


def test_gerar_metadados_background_prompt_trivial_tenta_reparo_e_usa_se_valido(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake(
        [
            _resposta_metadados({"background_prompt": ""}),
            _resposta_metadados({"background_prompt": "a dimly lit alley with police tape, at night"}),
        ]
    )

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["thumbnail"]["background_prompt"] == "a dimly lit alley with police tape, at night"
    # 2 = 2 chamadas de metadados (trivial + reparo) - o Headline Engine
    # esta' mockado por inteiro (GRUPO 3 desta sessao). Sem titulo.txt,
    # reconciliar_titulos_com_headline nem tenta chamada.
    assert len(cliente.chamadas) == 2


def test_gerar_metadados_background_prompt_ainda_trivial_apos_reparo_persiste_mesmo_assim(tmp_path, monkeypatch):
    """Se a segunda tentativa tambem vier trivial, gerar_metadados NAO
    falha - persiste mesmo assim (mantendo o resultado da primeira
    chamada, ja que a segunda nao melhorou nada). O background_prompt
    fraco so' aparece quando o usuario tentar gerar a composicao por IA,
    nunca bloqueia esta chamada."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake(
        [
            _resposta_metadados({"background_prompt": ""}),
            _resposta_metadados({"background_prompt": "curto"}),
        ]
    )

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert not thumb.background_prompt_valido(resultado["metadados"]["thumbnail"]["background_prompt"])
    # 2 = 2 chamadas de metadados - Headline Engine mockado por inteiro.
    assert len(cliente.chamadas) == 2


def test_gerar_metadados_background_prompt_valido_na_primeira_nao_tenta_reparo(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])  # default do fixture ja' e' valido

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    # 1 = so' a chamada de metadados - Headline Engine mockado por inteiro.
    assert len(cliente.chamadas) == 1


def test_gerar_metadados_reparo_com_resposta_sem_tool_use_mantem_o_trivial_original(tmp_path, monkeypatch):
    """Segunda chamada (reparo) falhando (sem tool_use) nao derruba a
    primeira geracao - so' nao consegue melhorar o background_prompt."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados({"background_prompt": ""}), _resposta_sem_tool_use()])

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["thumbnail"]["background_prompt"] == ""
    # 2 = 2 chamadas de metadados (trivial + reparo sem tool_use) -
    # Headline Engine mockado por inteiro.
    assert len(cliente.chamadas) == 2


# ---------------------------------------------------------------------------
# Sessao "conceito visual" (Parte 2) - substitui o mecanismo antigo de
# `_eixo_editorial_vazio`/`evidencia_central`/`conflito`/`data_chave`
# (achado real, caso Burke Ramsey/JonBenét, "regenerar dados automaticos"
# com servidor reiniciado - ver HISTORICO_BUGS.md). O conceito visual
# (`elemento_principal`/`tipo_elemento`/etc, extraido pela Grupo A do
# Headline Engine - scripts/headline_engine.py) e' a ancora agora;
# `validar_consistencia_headline_conceito` (funcao pura) confere se ele
# veio vazio e persiste `thumbnail["conceito_visual_ausente"]` honestamente
# em qualquer caso (nunca um vazio silencioso). NAO ha' mais reparo de
# "eixo editorial" - `_reparar_thumbnail_normalizado` so' repara
# `background_prompt` trivial agora (ver bloco de testes acima).
# ---------------------------------------------------------------------------


def _resposta_metadados_eixo_preenchido(**outros_overrides):
    overrides = {
        "evidencia_central": {"tipo": "dna", "descricao": "a 1999 DNA lab report and test swab"},
        "conflito": "a 1999 DNA exclusion revisited by a 2016 TV theory",
        "data_chave": "1999",
    }
    overrides.update(outros_overrides)
    return _resposta_metadados(overrides)


def _criar_ancora_eixo_editorial(pasta_projeto):
    pasta_projeto.mkdir(parents=True, exist_ok=True)
    (pasta_projeto / "titulo.txt").write_text(
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother", encoding="utf-8"
    )
    (pasta_projeto / "job_metadata.json").write_text(
        json.dumps({"nucleo_editorial": "science cleared him, TV didn't listen"}), encoding="utf-8"
    )


def test_validar_consistencia_headline_conceito_ausente_true_sem_elemento_principal():
    assert thumb.validar_consistencia_headline_conceito({"conceito_visual": None}) == {
        "conceito_visual_ausente": True
    }
    assert thumb.validar_consistencia_headline_conceito(
        {"conceito_visual": {"elemento_principal": "", "tipo_elemento": "outro"}}
    ) == {"conceito_visual_ausente": True}
    assert thumb.validar_consistencia_headline_conceito({}) == {"conceito_visual_ausente": True}


def test_validar_consistencia_headline_conceito_ausente_false_com_elemento_principal():
    resultado = thumb.validar_consistencia_headline_conceito(
        {"conceito_visual": {"elemento_principal": "the doorbell camera", "tipo_elemento": "camera_filmagem"}}
    )
    assert resultado == {"conceito_visual_ausente": False}


def test_gerar_metadados_conceito_visual_ausente_reflete_o_headline_engine(tmp_path, monkeypatch):
    """GRUPO 3/conceito visual: `gerar_metadados` persiste
    `thumbnail["conceito_visual_ausente"]` a partir do `conceito_visual`
    que o Headline Engine devolveu - nao ha' mais chamada de reparo
    dedicada a isso (so' `background_prompt` trivial ainda tenta reparo)."""
    _mockar_headline_engine(
        monkeypatch,
        conceito_visual={
            "elemento_principal": "a sealed 1999 DNA lab envelope",
            "tipo_elemento": "documento",
            "acao_ou_momento": None,
            "revelacao": None,
            "papel_na_composicao": "apoio",
        },
    )
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    thumbnail = resultado["metadados"]["thumbnail"]
    assert thumbnail["conceito_visual"]["elemento_principal"] == "a sealed 1999 DNA lab envelope"
    assert thumbnail["conceito_visual_ausente"] is False
    # 1 = so' a chamada de metadados - Headline Engine mockado por inteiro,
    # nunca toca cliente_api.messages.create.
    assert len(cliente.chamadas) == 1


def test_gerar_metadados_conceito_visual_ausente_true_quando_headline_engine_nao_extrai_elemento(tmp_path, monkeypatch):
    """Grupo A do Headline Engine pode ter sucesso (headline valido) sem
    conseguir extrair um elemento_principal concreto - `conceito_visual_
    ausente` reflete isso honestamente, nunca esconde (CLAUDE.md secao
    18.4)."""
    _mockar_headline_engine(monkeypatch)  # default: conceito_visual=None
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["thumbnail"]["conceito_visual_ausente"] is True


def test_regenerar_thumbnail_briefing_background_prompt_trivial_tenta_reparo(tmp_path, monkeypatch):
    """Mesmo reparo unico de `gerar_metadados` (so' `background_prompt`
    trivial - a reparacao de "eixo editorial" foi removida junto dos
    campos, ver HISTORICO_BUGS.md) tambem vale pro caminho de
    `regenerar_thumbnail_briefing`."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro aprovado original.", encoding="utf-8")
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps({"title": [], "description": "", "tags": [], "thumbnail": {"headline": "ANTIGO"}}),
        encoding="utf-8",
    )
    cliente = _ClienteFake(
        [
            _resposta_metadados({"background_prompt": ""}),
            _resposta_metadados({"background_prompt": "a dimly lit alley with police tape, at night"}),
        ]
    )

    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    thumbnail = resultado["metadados"]["thumbnail"]
    assert thumbnail["background_prompt"] == "a dimly lit alley with police tape, at night"


def test_regenerar_thumbnail_briefing_roteiro_ausente_retorna_erro(tmp_path):
    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=_ClienteFake([]))
    assert resultado == {"sucesso": False, "erro": "roteiro_ausente"}


def test_regenerar_thumbnail_briefing_cliente_indisponivel(tmp_path):
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, api_key=None, cliente=None)
    assert resultado == {"sucesso": False, "erro": "cliente_indisponivel"}


def test_regenerar_thumbnail_briefing_excecao_da_api_nunca_propaga(tmp_path):
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=_ClienteQuebrado())
    assert resultado == {"sucesso": False, "erro": "chamada_api_falhou"}


def test_regenerar_thumbnail_briefing_preserva_description_tags_e_nunca_gera_titulo(tmp_path, monkeypatch):
    """Requisito central do Grupo C: regenerar o briefing (ex: pra
    corrigir um background_prompt vazio) NUNCA mexe em descricao/tags ja
    aprovados - so' o sub-dict `thumbnail` e' substituido. Sessao "titulo
    canonico": tambem nunca gera titulo nenhum - `titulo_escolhido`
    continua vindo so' de titulo.txt (aqui, ausente - projeto de teste sem
    revisao de roteiro - entao fica vazio), e uma chave `title` antiga
    (de uma geracao anterior a esta correcao) e' removida na regeneracao."""
    _mockar_headline_engine(monkeypatch, headline="NOVO HEADLINE")
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro aprovado original.", encoding="utf-8")
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    metadados_existentes = {
        "title": ["Titulo Aprovado 1", "Titulo Aprovado 2", "Titulo Aprovado 3"],
        "description": "Descricao ja aprovada pelo usuario.",
        "tags": ["tag aprovada"],
        "thumbnail": {"headline": "ANTIGO", "background_prompt": ""},
        "roteiro_hash": "hash-antigo-de-outra-versao-do-roteiro",
    }
    (pasta_thumbnail / "metadados.json").write_text(json.dumps(metadados_existentes), encoding="utf-8")

    cliente = _ClienteFake([_resposta_metadados({"headline": "NOVO HEADLINE"})])
    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["thumbnail"]["headline"] == "NOVO HEADLINE"

    persistido = json.loads((pasta_thumbnail / "metadados.json").read_text(encoding="utf-8"))
    assert "title" not in persistido
    assert persistido["titulo_escolhido"] == ""
    assert persistido["description"] == "Descricao ja aprovada pelo usuario."
    assert persistido["tags"] == ["tag aprovada"]
    assert persistido["thumbnail"]["headline"] == "NOVO HEADLINE"
    assert persistido["roteiro_hash"] == thumb._hash_roteiro("Roteiro aprovado original.")


def test_regenerar_thumbnail_briefing_soma_custo_em_cima_do_ja_existente(tmp_path, monkeypatch):
    """Regeneracao parcial gasta dinheiro NOVO em cima do que a geracao
    original ja custou - custo_usd_estimado tem que ACUMULAR (soma), nunca
    substituir o valor anterior (correcao de sessao de refinamento)."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro aprovado original.", encoding="utf-8")
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    metadados_existentes = {
        "titulo_escolhido": "Titulo Aprovado",
        "description": "Descricao.",
        "tags": ["tag"],
        "thumbnail": {"headline": "ANTIGO"},
        "custo_usd_estimado": 0.5,
    }
    (pasta_thumbnail / "metadados.json").write_text(json.dumps(metadados_existentes), encoding="utf-8")

    cliente = _ClienteFake([_resposta_metadados({"headline": "NOVO HEADLINE"})])
    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["custo_usd_estimado"] > 0.5

    persistido = json.loads((pasta_thumbnail / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["custo_usd_estimado"] == resultado["metadados"]["custo_usd_estimado"]


def test_regenerar_thumbnail_briefing_sem_metadados_previos_usa_defaults_vazios(tmp_path, monkeypatch):
    """Chamar 'regenerar' sem nenhum gerar_metadados anterior (caso raro -
    o botao so' aparece depois da Etapa 7 rodar) nunca quebra."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    persistido = json.loads((tmp_path / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["titulo_escolhido"] == ""
    assert persistido["titulos_alternativos"] == []
    assert persistido["description"] == ""
    assert persistido["tags"] == []


# ---------------------------------------------------------------------------
# reconciliar_titulos_com_headline - coordenacao entre titulo e headline
# (sessao "MELHORIA - COORDENACAO ENTRE TITULO E HEADLINE"). Testes puros da
# funcao (sem passar por gerar_metadados/regenerar_thumbnail_briefing) mais
# testes de wiring logo abaixo.
# ---------------------------------------------------------------------------


def _resposta_titulos_reconciliados(titles_com_scores, tokens_in=200, tokens_out=80):
    return _resposta_tool_use(
        thumb.NOME_TOOL_TITULOS_HEADLINE, {"titles": titles_com_scores}, tokens_in=tokens_in, tokens_out=tokens_out
    )


def test_reconciliar_titulos_sem_titulos_nao_chama_api(tmp_path):
    cliente = _ClienteFake([])
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", [], "HEADLINE QUALQUER", "fato", "palavra", "en-US"
    )
    assert titulos == []
    assert auditoria["executado"] is False
    assert cliente.chamadas == []


def test_reconciliar_titulos_sem_headline_nao_chama_api(tmp_path):
    cliente = _ClienteFake([])
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", ["Titulo 1", "Titulo 2", "Titulo 3"], "", "fato", "palavra", "en-US"
    )
    assert titulos == ["Titulo 1", "Titulo 2", "Titulo 3"]
    assert auditoria["executado"] is False
    assert cliente.chamadas == []


def test_reconciliar_titulos_sem_cliente_preserva_titulos(tmp_path):
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        None, "modelo", ["Titulo 1"], "HEADLINE", "fato", "palavra", "en-US"
    )
    assert titulos == ["Titulo 1"]
    assert auditoria["executado"] is False


def test_reconciliar_titulos_excecao_da_api_preserva_titulos_originais(tmp_path):
    titulos_originais = ["Titulo 1", "Titulo 2", "Titulo 3"]
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        _ClienteQuebrado(), "modelo", titulos_originais, "HEADLINE", "fato", "palavra", "en-US"
    )
    assert titulos == titulos_originais
    assert auditoria["executado"] is False
    assert "erro" in auditoria


def test_reconciliar_titulos_resposta_sem_tool_use_preserva_originais(tmp_path):
    titulos_originais = ["Titulo 1", "Titulo 2", "Titulo 3"]
    cliente = _ClienteFake([_resposta_sem_tool_use()])
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", titulos_originais, "HEADLINE", "fato", "palavra", "en-US"
    )
    assert titulos == titulos_originais
    assert auditoria["erro"] == "resposta_invalida"


def test_reconciliar_titulos_ja_complementares_voltam_inalterados(tmp_path):
    """Titulo que o juiz devolve EXATAMENTE igual (score 2) - a funcao
    nunca deveria forcar mudanca nenhuma quando a resposta ja preserva."""
    titulos_originais = ["Titulo direto", "Titulo com autoridade", "Titulo com obstaculo"]
    cliente = _ClienteFake(
        [
            _resposta_titulos_reconciliados(
                [
                    {"title": "Titulo direto", "complementarity_score": 2, "motivo": "ok"},
                    {"title": "Titulo com autoridade", "complementarity_score": 2, "motivo": "ok"},
                    {"title": "Titulo com obstaculo", "complementarity_score": 2, "motivo": "ok"},
                ]
            )
        ]
    )
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", titulos_originais, "THE MARK ON HIS WRIST", "he had a distinctive wrist tattoo",
        "MARK", "en-US",
    )
    assert titulos == titulos_originais
    assert auditoria["alterado"] is False
    assert all(s["complementarity_score"] == 2 for s in auditoria["scores"])


def test_reconciliar_titulos_reescreve_apenas_o_titulo_conflitante(tmp_path):
    """Reproduz o achado real da sessao: um titulo revelava o proprio
    elemento visual (tattoo/wrist) usado pelo headline como lacuna."""
    titulos_originais = [
        "Nancy Guthrie: What the Wrist Tattoo Actually Reveals",
        "The 41 Minutes No One Can Explain",
        "Why Hasn't Anyone Been Arrested",
    ]
    cliente = _ClienteFake(
        [
            _resposta_titulos_reconciliados(
                [
                    {
                        "title": "Nancy Guthrie: What Investigators Still Can't Explain",
                        "complementarity_score": 2,
                        "motivo": "reescrito - o titulo original revelava a marca no pulso, o mesmo elemento do headline",
                    },
                    {"title": "The 41 Minutes No One Can Explain", "complementarity_score": 2, "motivo": "ja complementar"},
                    {"title": "Why Hasn't Anyone Been Arrested", "complementarity_score": 1, "motivo": "conexao fraca"},
                ]
            )
        ]
    )
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", titulos_originais, "THE MARK ON HIS WRIST", "he had a distinctive wrist tattoo",
        "MARK", "en-US",
    )
    assert titulos[0] != titulos_originais[0]
    assert "tattoo" not in titulos[0].lower() and "wrist" not in titulos[0].lower()
    assert titulos[1:] == titulos_originais[1:]
    assert auditoria["alterado"] is True
    assert auditoria["titulos_originais"] == titulos_originais


def test_reconciliar_titulos_resposta_incompleta_preenche_com_originais(tmp_path):
    titulos_originais = ["Titulo 1", "Titulo 2", "Titulo 3"]
    cliente = _ClienteFake([_resposta_titulos_reconciliados([{"title": "Titulo 1 novo", "complementarity_score": 2, "motivo": "ok"}])])
    titulos, auditoria = thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", titulos_originais, "HEADLINE", "fato", "palavra", "en-US"
    )
    assert len(titulos) == 3
    assert titulos[1] == "Titulo 2"
    assert titulos[2] == "Titulo 3"


def test_reconciliar_titulos_idioma_e_headline_vao_na_entrada(tmp_path):
    cliente = _ClienteFake(
        [_resposta_titulos_reconciliados([{"title": "T1", "complementarity_score": 2, "motivo": "ok"}])]
    )
    thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", ["Titulo 1"], "HEADLINE FINAL", "fato retido", "palavra", "pt-BR"
    )
    entrada = cliente.chamadas[0]["messages"][0]["content"]
    assert "pt-BR" in entrada
    assert "HEADLINE FINAL" in entrada
    assert "fato retido" in entrada


def test_reconciliar_titulos_persiste_custo(tmp_path):
    custos = []
    cliente = _ClienteFake(
        [_resposta_titulos_reconciliados([{"title": "T1", "complementarity_score": 2, "motivo": "ok"}])]
    )
    thumb.reconciliar_titulos_com_headline(
        cliente, "modelo", ["Titulo 1"], "HEADLINE", "fato", "palavra", "en-US", custos
    )
    assert len(custos) == 1 and custos[0] > 0


# ---------------------------------------------------------------------------
# Wiring: gerar_metadados/regenerar_thumbnail_briefing persistem
# titulo_headline_reconciliacao e usam os titulos reconciliados.
# ---------------------------------------------------------------------------


def test_gerar_metadados_reconciliacao_e_so_auditoria_titulo_escolhido_nunca_muda(tmp_path):
    """Sessao "titulo canonico": a reconciliacao roda sobre `[titulo_escolhido]`
    (nunca sobre titulos gerados pelo Grupo D, que nao existem mais) e o
    resultado e' SOMENTE auditoria - mesmo quando a IA de reconciliacao
    devolve um titulo "reescrito" com score alto, `titulo_escolhido`
    persistido tem que continuar EXATAMENTE o que estava em titulo.txt.
    Nenhuma etapa pode substituir a escolha do usuario em silencio (Regra 4/7
    do pedido "titulo canonico")."""
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    (tmp_path / "titulo.txt").write_text(
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother", encoding="utf-8"
    )

    def _headline_engine_fake(pasta_projeto, roteiro_texto, api_key=None, modelo=None, cliente=None, _custos=None):
        return {
            "sucesso": True,
            "headline": "THE MARK ON HIS WRIST",
            "emphasis_word": "MARK",
            "mechanism": "identity",
            "withheld_fact": "he had a distinctive wrist tattoo",
            "judge_score": 10,
            "nucleo_editorial_status": "ok",
            "fallback_usado": False,
            "aviso_revisao_humana": False,
            "fallback_sem_julgamento": False,
        }

    cliente = _ClienteFake(
        [
            # Eixo editorial PREENCHIDO de proposito - evita que
            # _reparar_thumbnail_normalizado consuma a resposta seguinte
            # (que e' da reconciliacao, nao de um reparo de Grupo D).
            _resposta_metadados_eixo_preenchido(headline="rascunho descartado"),
            # A IA de reconciliacao "reescreve" o titulo - o wiring tem que
            # IGNORAR esse texto reescrito pra' persistencia, so' guardar a
            # auditoria.
            _resposta_titulos_reconciliados(
                [{"title": "Titulo Reescrito Pela IA", "complementarity_score": 2, "motivo": "reescrito"}]
            ),
        ]
    )
    import unittest.mock as mock

    with mock.patch.object(thumb.headline_engine, "gerar_headline", _headline_engine_fake):
        resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    # Titulo canonico intacto - NUNCA o texto "reescrito" pela reconciliacao.
    assert resultado["metadados"]["titulo_escolhido"] == (
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother"
    )

    reconciliacao = resultado["metadados"]["titulo_headline_reconciliacao"]
    assert reconciliacao["executado"] is True
    # A auditoria RECEBEU titulo_escolhido (nao uma lista de 3 titulos
    # gerados) - confirma que a reconciliacao opera sobre a fonte unica de
    # verdade, nao sobre um conjunto concorrente.
    assert reconciliacao["titulos_originais"] == [
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother"
    ]

    persistido = json.loads((tmp_path / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["titulo_escolhido"] == resultado["metadados"]["titulo_escolhido"]
    assert persistido["titulo_headline_reconciliacao"] == reconciliacao


def test_regenerar_thumbnail_briefing_nunca_substitui_titulo_escolhido_por_headline_novo(tmp_path):
    """Achado real que motivou a sessao anterior (Grupo E, "coordenacao
    titulo/headline"): 'Regenerar dados automaticos' troca o headline, e a
    reconciliacao pode sinalizar colisao - mas isso NUNCA pode virar uma
    substituicao silenciosa do titulo que o usuario escolheu na revisao
    (sessao "titulo canonico", Regra 4/7 do pedido). titulo_escolhido vem
    sempre de titulo.txt, nunca do metadados.json antigo nem da IA."""
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro aprovado original.", encoding="utf-8")
    (tmp_path / "titulo.txt").write_text(
        "Nancy Guthrie: What the Wrist Tattoo Actually Reveals", encoding="utf-8"
    )
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    metadados_existentes = {
        "titulo_escolhido": "Nancy Guthrie: What the Wrist Tattoo Actually Reveals",
        "description": "Descricao ja aprovada.",
        "tags": ["tag"],
        "thumbnail": {"headline": "ANTIGO"},
    }
    (pasta_thumbnail / "metadados.json").write_text(json.dumps(metadados_existentes), encoding="utf-8")

    def _headline_engine_fake(pasta_projeto, roteiro_texto, api_key=None, modelo=None, cliente=None, _custos=None):
        return {
            "sucesso": True,
            "headline": "THE MARK ON HIS WRIST",
            "emphasis_word": "MARK",
            "mechanism": "identity",
            "withheld_fact": "he had a distinctive wrist tattoo",
            "judge_score": 10,
            "nucleo_editorial_status": "ok",
            "fallback_usado": False,
            "aviso_revisao_humana": False,
            "fallback_sem_julgamento": False,
        }

    cliente = _ClienteFake(
        [
            # Eixo editorial PREENCHIDO - evita que _reparar_thumbnail_
            # normalizado consuma a resposta seguinte (da reconciliacao).
            _resposta_metadados_eixo_preenchido(),
            _resposta_titulos_reconciliados(
                [
                    {
                        "title": "Nancy Guthrie: What Investigators Still Can't Explain",
                        "complementarity_score": 2,
                        "motivo": "reescrito - titulo original colide com o headline",
                    }
                ]
            ),
        ]
    )
    import unittest.mock as mock

    with mock.patch.object(thumb.headline_engine, "gerar_headline", _headline_engine_fake):
        resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    persistido = json.loads((pasta_thumbnail / "metadados.json").read_text(encoding="utf-8"))
    # titulo_escolhido permanece EXATAMENTE o de titulo.txt, mesmo com a
    # reconciliacao sinalizando colisao/reescrita.
    assert persistido["titulo_escolhido"] == "Nancy Guthrie: What the Wrist Tattoo Actually Reveals"
    assert persistido["titulo_headline_reconciliacao"]["executado"] is True


def test_regenerar_thumbnail_briefing_projeto_antigo_sem_titulo_txt_usa_fallback_persistido(tmp_path, monkeypatch):
    """Validacao 8 do pedido "titulo canonico": projeto antigo (gerado
    antes de titulo.txt existir de verdade no disco, ou com o arquivo
    removido por algum motivo externo) mas que JA tem `titulo_escolhido`
    persistido de uma geracao anterior nunca perde essa selecao so' porque
    titulo.txt sumiu - o fallback e' pro ultimo valor persistido, NUNCA pra
    string vazia quando ha' algo salvo pra recuperar."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro aprovado original.", encoding="utf-8")
    # Sem titulo.txt de proposito - so' o metadados.json de uma geracao
    # anterior com titulo_escolhido ja persistido.
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(
            {
                "titulo_escolhido": "Titulo Ja Persistido De Uma Geracao Anterior",
                "description": "Descricao.",
                "tags": ["tag"],
                "thumbnail": {"headline": "ANTIGO"},
            }
        ),
        encoding="utf-8",
    )

    cliente = _ClienteFake([_resposta_metadados()])
    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    persistido = json.loads((pasta_thumbnail / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["titulo_escolhido"] == "Titulo Ja Persistido De Uma Geracao Anterior"


# ---------------------------------------------------------------------------
# gerar_thumbnail_candidatos (orquestracao do `python scripts/7_thumbnail.py`)
#
# Sessao de simplificacao da Etapa 7: nao ha' mais scan de cenario nem
# resolucao de sujeito aqui - so' dispara gerar_metadados (Grupo D, que ja'
# dispara o briefing do Grupo C automaticamente) se ANTHROPIC_API_KEY
# estiver configurada. Os testes puros do briefing
# (scripts/thumbnail_briefing.py) vivem em tests/test_thumbnail_briefing.py.
# ---------------------------------------------------------------------------


def _fixture_precondicoes_etapa7_ok(pasta_projeto):
    (pasta_projeto / "clipes").mkdir()
    (pasta_projeto / "clipes" / "indice.json").write_text(
        json.dumps([{"arquivo": "c.mp4", "clipe_id": "c0", "duracao_s": 5.0}]), encoding="utf-8"
    )
    (pasta_projeto / "saida").mkdir()
    (pasta_projeto / "saida" / "video_final.mp4").touch()


def test_gerar_thumbnail_candidatos_sem_chave_anthropic_ainda_assim_sucede(tmp_path, monkeypatch):
    """Sem ANTHROPIC_API_KEY, gerar_metadados (Grupo D) nunca roda - mas o
    ponto de entrada nunca falha por causa disso (CLAUDE.md secao 18.4),
    so' segue sem metadados/briefing."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _fixture_precondicoes_etapa7_ok(tmp_path)

    resultado = thumb.gerar_thumbnail_candidatos(tmp_path)

    assert resultado["sucesso"] is True
    assert not (tmp_path / "thumbnail" / "metadados.json").exists()


def test_gerar_thumbnail_candidatos_precondicao_falha_nao_gera_nada(tmp_path):
    resultado = thumb.gerar_thumbnail_candidatos(tmp_path)
    assert resultado["sucesso"] is False
    assert resultado["tipo_erro"] == "clipes_ausentes"


def test_gerar_thumbnail_candidatos_com_chave_dispara_gerar_metadados(tmp_path, monkeypatch):
    """Com ANTHROPIC_API_KEY configurada e o roteiro desatualizado (aqui,
    ausente de metadados.json - primeira geracao), gerar_thumbnail_candidatos
    chama gerar_metadados (Grupo D, que ja dispara o briefing do Grupo C
    automaticamente) - nunca chama API real, injeta cliente fake."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    _fixture_precondicoes_etapa7_ok(tmp_path)
    (tmp_path / "roteiro_aprovado.md").write_text("Um caso de investigacao.", encoding="utf-8")

    chamadas = []

    def _gerar_metadados_fake(pasta_projeto, api_key, modelo):
        chamadas.append((pasta_projeto, api_key, modelo))
        return {"sucesso": True, "metadados": {}}

    monkeypatch.setattr(thumb, "gerar_metadados", _gerar_metadados_fake)

    resultado = thumb.gerar_thumbnail_candidatos(tmp_path)

    assert resultado["sucesso"] is True
    assert len(chamadas) == 1
    assert chamadas[0][0] == tmp_path


def test_gerar_metadados_persiste_briefing_completo_sem_sujeitos(tmp_path, monkeypatch):
    """Sem nenhuma foto enviada, gerar_metadados ainda assim produz um
    briefing_completo (template EVIDENCE_SCENE, unico elegivel sem fotos) -
    Grupo C funciona mesmo no caminho mais comum (primeira geracao, antes
    de qualquer upload)."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Um caso de investigacao.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    thumbnail = resultado["metadados"]["thumbnail"]
    assert thumbnail.get("briefing_completo")
    assert thumbnail.get("briefing_template") == "EVIDENCE_SCENE"
    persistido = json.loads((tmp_path / "thumbnail" / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["thumbnail"]["briefing_completo"] == thumbnail["briefing_completo"]


def test_gerar_metadados_briefing_nunca_chama_api_real_quando_cliente_fake_e_injetado(tmp_path, monkeypatch):
    """Regressao critica (CLAUDE.md secao 8): o wiring do Grupo C dentro de
    gerar_metadados tem que reaproveitar o MESMO cliente fake injetado via
    `cliente=`, nunca reconstruir um cliente novo so' a partir da api_key -
    sem isso, um teste que passa uma api_key falsa acabaria tentando uma
    chamada de rede de verdade dentro de thumbnail_briefing. GRUPO 3
    (sessao "conceito visual", Parte 2): o Headline Engine e' mockado
    explicitamente aqui (em vez de deixar o cliente fake absorvê-lo) -
    exatamente pra' garantir que essa garantia continue cobrindo a chamada
    NOVA que o Headline Engine v2 adicionou, nao so' o Grupo C/D de sempre."""
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Um caso qualquer.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.gerar_metadados(tmp_path, "chave-completamente-falsa-nao-existe", cliente=cliente)

    assert resultado["sucesso"] is True
    # Sem sujeitos.json, templates_elegiveis == ("EVIDENCE_SCENE",) - unico
    # elegivel, selecionar_template nem chama a API (ver
    # tests/test_thumbnail_briefing.py) - entao nenhuma chamada extra e'
    # esperada alem da ja contabilizada pelo teste (so' a de metadados,
    # Grupo D - o Headline Engine esta' mockado por inteiro), satisfeita
    # pelo _ClienteFake sem sobrar nem faltar resposta - se o codigo tivesse
    # tentado construir um cliente real, o teste teria travado tentando
    # rede ou levantado erro de autenticacao, nunca chegando em
    # sucesso=True aqui.
    assert len(cliente.chamadas) == 1


def test_regenerar_thumbnail_briefing_tambem_gera_briefing_completo(tmp_path, monkeypatch):
    _mockar_headline_engine(monkeypatch)
    (tmp_path / "roteiro_aprovado.md").write_text("Roteiro.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    resultado = thumb.regenerar_thumbnail_briefing(tmp_path, "fake-key", cliente=cliente)

    assert resultado["sucesso"] is True
    assert resultado["thumbnail"].get("briefing_completo")


def test_gerar_briefing_thumbnail_sem_metadados_retorna_erro(tmp_path):
    resultado = thumb.gerar_briefing_thumbnail(tmp_path, "fake-key")
    assert resultado == {"sucesso": False, "erro": "metadados_ausentes"}


def test_gerar_briefing_thumbnail_acumula_custo_sobre_o_ja_existente(tmp_path, monkeypatch):
    """Correcao de sessao de refinamento: cada regeneracao dedicada do
    briefing (botao "Gerar/regenerar briefing" da tela) gasta dinheiro
    NOVO - custo_usd_estimado precisa SOMAR sobre o que ja estava
    persistido, mesma logica de regenerar_thumbnail_briefing."""
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps({"titulo_escolhido": "Titulo Aprovado", "thumbnail": {"headline": "H"}, "custo_usd_estimado": 0.3}),
        encoding="utf-8",
    )

    def _briefing_fake(pasta_projeto, api_key, modelo, cliente=None, _custos=None, template_forcado=None):
        if _custos is not None:
            _custos.append(0.02)
        return {"sucesso": True, "briefing_completo": "prompt fake", "template_escolhido": "EVIDENCE_SCENE"}

    monkeypatch.setattr(thumb.thumbnail_briefing, "gerar_briefing_completo", _briefing_fake)

    resultado = thumb.gerar_briefing_thumbnail(tmp_path, "fake-key")

    assert resultado["sucesso"] is True
    assert resultado["metadados"]["custo_usd_estimado"] == pytest.approx(0.32)
    persistido = json.loads((pasta_thumbnail / "metadados.json").read_text(encoding="utf-8"))
    assert persistido["custo_usd_estimado"] == pytest.approx(0.32)


def test_gerar_briefing_thumbnail_regenera_so_o_briefing_sem_chamar_grupo_d(tmp_path, monkeypatch):
    pasta_thumbnail = tmp_path / "thumbnail"
    pasta_thumbnail.mkdir()
    (pasta_thumbnail / "metadados.json").write_text(
        json.dumps(
            {
                "titulo_escolhido": "Titulo Aprovado",
                "thumbnail": {"headline": "HEADLINE", "emphasis_word": "HEADLINE"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    resultado = thumb.gerar_briefing_thumbnail(tmp_path, api_key=None)

    assert resultado["sucesso"] is True
    assert resultado["thumbnail"]["briefing_completo"]
    # titulo_escolhido preservado - gerar_briefing_thumbnail nunca chama o
    # Grupo D nem gera titulo de novo.
    assert resultado["metadados"]["titulo_escolhido"] == "Titulo Aprovado"


# ---------------------------------------------------------------------------
# Sessao "conceito visual" (Parte 2): `_normalizar_evidencia_central` e os
# campos `evidencia_central`/`conflito`/`data_chave` em `_normalizar_
# thumbnail_metadados` foram removidos por inteiro (ver HISTORICO_BUGS.md) -
# sem substituto 1:1 (a normalizacao em si nao existe mais). Cobertura de
# "campos ausentes nunca derruba" ja e' garantida por
# `test_normalizar_thumbnail_metadados_campos_ausentes_nao_derruba` acima
# (que testa os campos REAIS de hoje).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Problema 2 do pedido: `_ler_eixo_editorial_base` / ancoragem no titulo +
# nucleo_editorial injetada na chamada de Grupo D.
# ---------------------------------------------------------------------------


def test_ler_eixo_editorial_base_projeto_sem_arquivos_devolve_vazio(tmp_path):
    resultado = thumb._ler_eixo_editorial_base(tmp_path)
    assert resultado == {"nucleo_editorial": "", "titulo_aprovado": ""}


def test_ler_eixo_editorial_base_le_titulo_e_nucleo_editorial(tmp_path):
    (tmp_path / "titulo.txt").write_text(
        "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother", encoding="utf-8"
    )
    (tmp_path / "job_metadata.json").write_text(
        json.dumps({"nucleo_editorial": "DNA exclusion vs renewed suspicion"}), encoding="utf-8"
    )
    resultado = thumb._ler_eixo_editorial_base(tmp_path)
    assert resultado["titulo_aprovado"].startswith("Burke Ramsey")
    assert resultado["nucleo_editorial"] == "DNA exclusion vs renewed suspicion"


# ---------------------------------------------------------------------------
# Sessao "titulo canonico" (achado real, projeto Burke Ramsey/JonBenét):
# `_ler_titulos_alternativos` - as opcoes da Etapa 3 NAO escolhidas pelo
# usuario, nunca tratadas como titulo candidato a substituir a escolha.
# ---------------------------------------------------------------------------


def test_ler_titulos_alternativos_sem_arquivo_devolve_vazio(tmp_path):
    assert thumb._ler_titulos_alternativos(tmp_path, "Qualquer Titulo") == []


def test_ler_titulos_alternativos_exclui_o_titulo_escolhido(tmp_path):
    (tmp_path / "titulos_sugeridos.json").write_text(
        json.dumps(
            {
                "titulos": [
                    "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother",
                    "The DNA Exclusion CBS Never Reckoned With: Burke Ramsey's Story",
                    "Why Did a Network Suggest Burke Ramsey Was a Suspect After Science Had Already Cleared Him?",
                ]
            }
        ),
        encoding="utf-8",
    )
    resultado = thumb._ler_titulos_alternativos(
        tmp_path, "Burke Ramsey: What the 1999 DNA Test Really Proved About JonBenét's Brother"
    )
    assert resultado == [
        "The DNA Exclusion CBS Never Reckoned With: Burke Ramsey's Story",
        "Why Did a Network Suggest Burke Ramsey Was a Suspect After Science Had Already Cleared Him?",
    ]


def test_ler_titulos_alternativos_titulo_custom_nao_bate_com_nenhuma_opcao(tmp_path):
    """Usuario digitou um titulo customizado na revisao (nao veio de
    nenhuma das 3 sugestoes) - as 3 opcoes originais continuam todas como
    alternativas, nenhuma e' excluida por engano."""
    (tmp_path / "titulos_sugeridos.json").write_text(
        json.dumps({"titulos": ["Titulo 1", "Titulo 2", "Titulo 3"]}), encoding="utf-8"
    )
    resultado = thumb._ler_titulos_alternativos(tmp_path, "Titulo Totalmente Customizado")
    assert resultado == ["Titulo 1", "Titulo 2", "Titulo 3"]


def test_ler_titulos_alternativos_json_malformado_nunca_levanta_excecao(tmp_path):
    (tmp_path / "titulos_sugeridos.json").write_text("{ isso nao e' json valido", encoding="utf-8")
    assert thumb._ler_titulos_alternativos(tmp_path, "Titulo") == []


def test_gerar_metadados_injeta_titulo_nucleo_e_elemento_principal_na_chamada(tmp_path, monkeypatch):
    """GRUPO 2/3 (sessao "conceito visual", Parte 2): `elemento_principal`
    (extraido pela Grupo A do Headline Engine, que roda ANTES desta
    chamada agora) e' o terceiro argumento de ancoragem, junto de
    titulo_aprovado/nucleo_editorial (ver `_chamar_claude_metadados`,
    scripts/7_thumbnail.py) - substitui o antigo `evidencia_central`/
    `conflito`/`data_chave` injetados de volta como cabecalho no roteiro."""
    _mockar_headline_engine(
        monkeypatch,
        conceito_visual={
            "elemento_principal": "O ELEMENTO PRINCIPAL",
            "tipo_elemento": "objeto",
            "acao_ou_momento": None,
            "revelacao": None,
            "papel_na_composicao": "apoio",
        },
    )
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    (tmp_path / "titulo.txt").write_text("O TITULO APROVADO", encoding="utf-8")
    (tmp_path / "job_metadata.json").write_text(
        json.dumps({"nucleo_editorial": "O NUCLEO EDITORIAL"}), encoding="utf-8"
    )
    cliente = _ClienteFake([_resposta_metadados()])

    thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    texto_enviado = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert "O TITULO APROVADO" in texto_enviado
    assert "O NUCLEO EDITORIAL" in texto_enviado
    assert "O ELEMENTO PRINCIPAL" in texto_enviado
    assert "Era uma vez um caso real." in texto_enviado


def test_gerar_metadados_sem_titulo_nem_job_metadata_nao_injeta_bloco_vazio(tmp_path, monkeypatch):
    """Projeto antigo (validacao 9 do pedido) - sem titulo.txt/
    job_metadata.json e sem elemento_principal (Grupo A tambem sem
    conceito_visual, default do mock), a chamada nunca inclui um bloco de
    ancoragem vazio/quebrado, so' o roteiro como sempre."""
    _mockar_headline_engine(monkeypatch)  # conceito_visual=None por padrao
    (tmp_path / "roteiro_aprovado.md").write_text("Era uma vez um caso real.", encoding="utf-8")
    cliente = _ClienteFake([_resposta_metadados()])

    thumb.gerar_metadados(tmp_path, "fake-key", cliente=cliente)

    texto_enviado = cliente.chamadas[0]["messages"][0]["content"][0]["text"]
    assert texto_enviado == "Roteiro aprovado:\n\nEra uma vez um caso real."


# ---------------------------------------------------------------------------
# Sessao "conceito visual" (Parte 2) - `_montar_roteiro_com_eixo_editorial`/
# `_aplicar_headline_engine` (mecanismo circular de injetar evidencia_
# central/conflito/data_chave de volta como cabecalho no roteiro entregue
# ao Headline Engine) foram removidos por inteiro (ver HISTORICO_BUGS.md).
# `_mesclar_headline_em_thumbnail` (codigo puro) e' o substituto: so' mescla
# o resultado JA PRONTO de `headline_engine.gerar_headline` (chamado ANTES,
# com o roteiro cru) no dict de thumbnail normalizado.
# ---------------------------------------------------------------------------


def test_mesclar_headline_em_thumbnail_sucesso_sobrescreve_campos_incluindo_conceito_visual():
    resultado_headline = {
        "sucesso": True,
        "headline": "THE MARK ON HIS WRIST",
        "emphasis_word": "MARK",
        "mechanism": "identity",
        "withheld_fact": "he had a distinctive wrist tattoo",
        "judge_score": 10,
        "nucleo_editorial_status": "ok",
        "fallback_usado": False,
        "aviso_revisao_humana": False,
        "fallback_sem_julgamento": False,
        "conceito_visual": {"elemento_principal": "the doorbell camera", "tipo_elemento": "camera_filmagem"},
    }
    thumbnail_normalizado = {"headline": "rascunho descartado", "emphasis_word": "", "background_prompt": "x"}

    resultado = thumb._mesclar_headline_em_thumbnail(thumbnail_normalizado, resultado_headline)

    assert resultado["headline"] == "THE MARK ON HIS WRIST"
    assert resultado["emphasis_word"] == "MARK"
    assert resultado["conceito_visual"]["elemento_principal"] == "the doorbell camera"
    assert resultado["background_prompt"] == "x"  # campo nao tocado pelo merge preservado


def test_mesclar_headline_em_thumbnail_falha_preserva_headline_existente_e_conceito_none():
    """Headline Engine indisponivel/falhou na primeira chamada nunca apaga
    o headline que ja veio da chamada unica de metadados - CLAUDE.md secao
    18.4."""
    thumbnail_normalizado = {"headline": "HEADLINE DA CHAMADA UNICA", "emphasis_word": "UNICA"}

    resultado = thumb._mesclar_headline_em_thumbnail(
        thumbnail_normalizado, {"sucesso": False, "erro": "cliente_indisponivel"}
    )

    assert resultado["headline"] == "HEADLINE DA CHAMADA UNICA"
    assert resultado["emphasis_word"] == "UNICA"
    assert resultado["conceito_visual"] is None
    assert resultado["mechanism"] is None


def test_schema_metadados_nao_exige_mais_evidencia_central_conflito_e_data_chave():
    """GRUPO 2 (sessao "conceito visual", Parte 2): os 3 campos antigos
    saem do schema por inteiro - `background_prompt` continua exigido, mas
    sem os campos de eixo editorial que o Grupo A do Headline Engine
    (conceito visual) substituiu."""
    propriedades_thumbnail = thumb.SCHEMA_METADADOS["input_schema"]["properties"]["thumbnail"]
    for campo in ("evidencia_central", "conflito", "data_chave"):
        assert campo not in propriedades_thumbnail["properties"]
        assert campo not in propriedades_thumbnail["required"]
    assert "background_prompt" in propriedades_thumbnail["properties"]
    assert "background_prompt" in propriedades_thumbnail["required"]


def test_prompt_metadados_thumbnail_contem_regra_fundamental_ancorada_no_elemento_principal():
    """Contrato do prompt - garante que a instrucao de ancoragem no
    conceito visual (`elemento_principal`, extraido pela Grupo A do
    Headline Engine - substitui o antigo eixo editorial de 3 campos) e a
    proibicao de usar detalhe chamativo mas irrelevante nao sejam removidas
    silenciosamente numa edicao futura do arquivo .md."""
    texto = thumb._PROMPT_METADADOS_PATH.read_text(encoding="utf-8")
    assert "REGRA FUNDAMENTAL" in texto
    assert "elemento_principal" in texto
    assert "evidencia_central" not in texto
    assert "conflito" not in texto
    assert "data_chave" not in texto
