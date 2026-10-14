"""Testes das funcoes puras de slot por posicao (Feature B - reorganizacao
manual com drag livre, timeline horizontal): server.py:_migrar_slots_clipes/
_precisa_de_trim/_hash_ordem_clipes/_montar_timeline_reorganizacao/
_concatenar_com_slots. Sao a versao server.py, duplicada de proposito de
scripts/6_montar_video.py (CLAUDE.md secao 9) - tests/test_montar_video.py
cobre a versao do script. Nenhuma chamada real a ffmpeg (sempre monkeypatch
em server.subprocess.run).
"""

from unittest.mock import MagicMock

import server


# ---------------------------------------------------------------------------
# _migrar_slots_clipes
# ---------------------------------------------------------------------------


def test_migrar_slots_clipes_fallback_usa_duracao_s():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0}, {"clipe_id": "c1", "duracao_s": 6.0}]

    migrados = server._migrar_slots_clipes(clipes)

    assert migrados[0]["duracao_slot_s"] == 8.0
    assert migrados[1]["duracao_slot_s"] == 6.0
    assert migrados[0]["inicio_slot_s"] == 0.0
    assert migrados[1]["inicio_slot_s"] == 8.0


def test_migrar_slots_clipes_preserva_duracao_slot_existente():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}]

    migrados = server._migrar_slots_clipes(clipes)

    assert migrados[0]["duracao_slot_s"] == 5.0


def test_migrar_slots_clipes_nao_muta_lista_original():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0}]

    server._migrar_slots_clipes(clipes)

    assert "duracao_slot_s" not in clipes[0]


# ---------------------------------------------------------------------------
# _precisa_de_trim
# ---------------------------------------------------------------------------


def test_precisa_de_trim_false_no_fallback():
    clipes = server._migrar_slots_clipes([{"clipe_id": "c0", "duracao_s": 8.0}])
    assert server._precisa_de_trim(clipes) is False


def test_precisa_de_trim_true_apos_reordenacao_simulada():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}]
    assert server._precisa_de_trim(clipes) is True


# ---------------------------------------------------------------------------
# _hash_ordem_clipes - reforco: hash inclui campos de slot, nao so' clipe_id
# ---------------------------------------------------------------------------


def test_hash_ordem_clipes_muda_com_reordenacao_simples():
    indice_a = {"clipes": [{"clipe_id": "c0", "duracao_s": 8.0}, {"clipe_id": "c1", "duracao_s": 6.0}]}
    indice_b = {"clipes": [{"clipe_id": "c1", "duracao_s": 6.0}, {"clipe_id": "c0", "duracao_s": 8.0}]}

    assert server._hash_ordem_clipes(indice_a) != server._hash_ordem_clipes(indice_b)


def test_hash_ordem_clipes_muda_quando_slot_muda_mesmo_com_clipe_id_na_mesma_ordem():
    """Reforco obrigatorio desta sessao: o hash tem que invalidar o cache do
    preview mesmo num cenario onde a ORDEM de clipe_id nao mudou mas a
    duracao do slot de alguma posicao mudou - defesa em profundidade alem
    do caso comum (reordenar ja muda a ordem de clipe_id por si so)."""
    indice_a = {"clipes": [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 8.0}]}
    indice_b = {"clipes": [{"clipe_id": "c0", "duracao_s": 8.0, "duracao_slot_s": 5.0}]}

    assert server._hash_ordem_clipes(indice_a) != server._hash_ordem_clipes(indice_b)


def test_hash_ordem_clipes_estavel_para_mesma_entrada():
    indice = {"clipes": [{"clipe_id": "c0", "duracao_s": 8.0}]}

    assert server._hash_ordem_clipes(indice) == server._hash_ordem_clipes(indice)


def test_hash_ordem_clipes_lista_vazia_nao_levanta_excecao():
    assert server._hash_ordem_clipes({"clipes": []})
    assert server._hash_ordem_clipes({})


# ---------------------------------------------------------------------------
# _montar_timeline_reorganizacao
# ---------------------------------------------------------------------------


def test_montar_timeline_reorganizacao_uma_entrada_por_posicao():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0}, {"clipe_id": "c1", "duracao_s": 6.0}]

    timeline, banco = server._montar_timeline_reorganizacao(clipes, {})

    assert len(timeline) == 2
    assert len(banco) == 2
    assert timeline[0]["posicao"] == 0
    assert timeline[1]["posicao"] == 1
    assert timeline[1]["inicio_slot_s"] == 8.0


def test_montar_timeline_reorganizacao_inclui_descricao_vision():
    clipes = [{"clipe_id": "c0", "duracao_s": 8.0}]

    timeline, _banco = server._montar_timeline_reorganizacao(clipes, {"c0": "a bicycle"})

    assert timeline[0]["descricao_vision"] == "a bicycle"
    assert timeline[0]["descricao_busca"] == "a bicycle"


def test_montar_timeline_reorganizacao_largura_proporcional_a_duracao_slot():
    clipes = [{"clipe_id": "c0", "duracao_s": 10.0}]

    timeline, _banco = server._montar_timeline_reorganizacao(clipes, {})

    assert timeline[0]["largura_px"] == 10.0 * server.PX_POR_SEGUNDO_TIMELINE


def test_montar_timeline_reorganizacao_lista_vazia():
    timeline, banco = server._montar_timeline_reorganizacao([], {})
    assert timeline == []
    assert banco == []


# ---------------------------------------------------------------------------
# _concatenar_com_slots - usado pelo preview provisorio (Feature B)
# ---------------------------------------------------------------------------


def _run_mock_sucesso_factory(comandos):
    def _run(cmd, *args, **kwargs):
        comandos.append(cmd)
        resultado = MagicMock()
        resultado.returncode = 0
        for arg in reversed(cmd):
            if isinstance(arg, str) and arg.endswith(".mp4"):
                from pathlib import Path

                Path(arg).parent.mkdir(parents=True, exist_ok=True)
                Path(arg).write_bytes(b"fake")
                break
        return resultado

    return _run


def test_concatenar_com_slots_caminho_rapido_sem_trim(tmp_path, monkeypatch):
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    (pasta_clipes / "clipe_0000.mp4").write_bytes(b"fake")

    comandos = []
    monkeypatch.setattr(server.subprocess, "run", _run_mock_sucesso_factory(comandos))

    clipes = server._migrar_slots_clipes([{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0}])
    caminho_saida = tmp_path / "preview_concat.mp4"

    ok = server._concatenar_com_slots(pasta_clipes, clipes, tmp_path / "temp", caminho_saida)

    assert ok is True
    assert len(comandos) == 1
    assert "-c" in comandos[0] and "copy" in comandos[0]
    assert not any("-filter_complex" in cmd for cmd in comandos)


def test_concatenar_com_slots_caminho_com_trim(tmp_path, monkeypatch):
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    (pasta_clipes / "clipe_0000.mp4").write_bytes(b"fake")

    comandos = []
    monkeypatch.setattr(server.subprocess, "run", _run_mock_sucesso_factory(comandos))

    clipes = server._migrar_slots_clipes(
        [{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0, "duracao_slot_s": 5.0}]
    )
    caminho_saida = tmp_path / "preview_concat.mp4"

    ok = server._concatenar_com_slots(pasta_clipes, clipes, tmp_path / "temp", caminho_saida)

    assert ok is True
    assert any("-filter_complex" in cmd for cmd in comandos)


def test_concatenar_com_slots_lista_vazia_retorna_false():
    assert server._concatenar_com_slots(None, [], None, None) is False


def test_concatenar_com_slots_falha_ffmpeg_retorna_false(tmp_path, monkeypatch):
    pasta_clipes = tmp_path / "clipes"
    pasta_clipes.mkdir()
    (pasta_clipes / "clipe_0000.mp4").write_bytes(b"fake")

    def _run_falha(cmd, *args, **kwargs):
        resultado = MagicMock()
        resultado.returncode = 1
        return resultado

    monkeypatch.setattr(server.subprocess, "run", _run_falha)

    clipes = server._migrar_slots_clipes([{"clipe_id": "c0", "arquivo": "clipe_0000.mp4", "duracao_s": 8.0}])

    ok = server._concatenar_com_slots(pasta_clipes, clipes, tmp_path / "temp", tmp_path / "saida.mp4")

    assert ok is False
