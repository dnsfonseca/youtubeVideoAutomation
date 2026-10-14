"""Testes do provedor de imagem "openai" (scripts/imagem/openai.py) -
composicao COMPLETA da thumbnail via `gerar_composicao` (/v1/images/edits
do gpt-image-2). Nunca chama a API real (CLAUDE.md secao 8):
`requests.post` e' sempre mockado.

O modo antigo de gerar SO' o fundo (`gerar()`, /v1/images/generations,
com style/BASE_PROMPT/_recortar_centro) foi removido na sessao de
simplificacao da Etapa 7 (ver HISTORICO_BUGS.md) junto dos 5 templates de
composicao via Pillow que ele alimentava - os testes que cobriam esse
modo saem daqui."""

import base64
import json
from unittest.mock import patch

from PIL import Image

from scripts.imagem import openai as provedor_openai


class _RespostaFake:
    def __init__(self, status_code=200, corpo=None, texto=""):
        self.status_code = status_code
        self._corpo = corpo or {}
        self.text = texto

    def json(self):
        return self._corpo


def _b64_imagem(tamanho=(1536, 1024), cor=(80, 90, 100)):
    imagem = Image.new("RGB", tamanho, cor)
    import io

    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Composicao completa por IA - gerar_composicao(), /v1/images/edits
# ---------------------------------------------------------------------------


def _foto(tmp_path, nome, cor=(50, 60, 70)):
    caminho = tmp_path / nome
    Image.new("RGB", (300, 300), cor).save(caminho)
    return caminho


def test_gerar_composicao_sem_chave_retorna_falha_sem_chamar_requests(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    foto = _foto(tmp_path, "hero.jpg")

    with patch("scripts.imagem.openai.requests.post") as mock_post:
        resultado = provedor_openai.gerar_composicao("briefing qualquer", [foto], tmp_path / "saida.jpg")
        mock_post.assert_not_called()

    assert resultado["sucesso"] is False
    assert resultado["erro_tipo"] == "sem_chave"


def test_gerar_composicao_sem_fotos_retorna_falha_sem_chamar_requests(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    with patch("scripts.imagem.openai.requests.post") as mock_post:
        resultado = provedor_openai.gerar_composicao("briefing qualquer", [], tmp_path / "saida.jpg")
        mock_post.assert_not_called()

    assert resultado["sucesso"] is False
    assert resultado["erro_tipo"] == "sem_fotos"


def test_gerar_composicao_briefing_vazio_retorna_falha_sem_chamar_requests(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")

    with patch("scripts.imagem.openai.requests.post") as mock_post:
        resultado = provedor_openai.gerar_composicao("   ", [foto], tmp_path / "saida.jpg")
        mock_post.assert_not_called()

    assert resultado["sucesso"] is False
    assert resultado["erro_tipo"] == "briefing_ausente"


def test_gerar_composicao_monta_array_de_imagens_na_ordem_recebida(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    hero = _foto(tmp_path, "hero.jpg", cor=(10, 10, 10))
    secondary = _foto(tmp_path, "secondary.jpg", cor=(20, 20, 20))
    resposta = _RespostaFake(status_code=200, corpo={"data": [{"b64_json": _b64_imagem()}]})

    with patch("scripts.imagem.openai.requests.post", return_value=resposta) as mock_post:
        resultado = provedor_openai.gerar_composicao(
            "Create a thumbnail with these two people.", [hero, secondary], tmp_path / "composicao.jpg"
        )

    assert resultado["sucesso"] is True
    assert mock_post.call_count == 1
    chamada = mock_post.call_args
    assert chamada.args[0] == provedor_openai.BASE_URL_EDITS
    arquivos_enviados = chamada.kwargs["files"]
    # Duas entradas "image[]", hero PRIMEIRO, secondary DEPOIS - a ordem
    # recebida por gerar_composicao nunca e' reordenada internamente.
    assert [nome for nome, _ in arquivos_enviados] == ["image[]", "image[]"]
    assert arquivos_enviados[0][1][0] == "hero.jpg"
    assert arquivos_enviados[1][1][0] == "secondary.jpg"
    # O prompt enviado pra API ganha a instrucao de area segura anexada
    # (corte 3:2 -> 16:9) - o briefing original continua no comeco intacto.
    prompt_enviado = chamada.kwargs["data"]["prompt"]
    assert prompt_enviado.startswith("Create a thumbnail with these two people.")
    assert provedor_openai.INSTRUCAO_AREA_SEGURA_16_9 in prompt_enviado
    assert chamada.kwargs["data"]["model"] == provedor_openai.MODEL_ID
    # input_fidelity nunca e' enviado - nao e' ajustavel no gpt-image-2.
    assert "input_fidelity" not in chamada.kwargs["data"]


def test_gerar_composicao_instrucao_area_segura_nunca_altera_briefing_recebido(monkeypatch, tmp_path):
    """A instrucao de area segura (corte 3:2 -> 16:9) e' anexada so' no
    prompt mandado pra API - a string `briefing_completo` recebida pelo
    chamador (que e' o mesmo texto persistido em thumbnail/metadados.json,
    usado tambem pro caminho manual de copiar/colar) nunca e' mutada."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")
    resposta = _RespostaFake(status_code=200, corpo={"data": [{"b64_json": _b64_imagem()}]})
    briefing_original = "Briefing exportavel original, sem nenhuma mencao a area segura."

    with patch("scripts.imagem.openai.requests.post", return_value=resposta) as mock_post:
        resultado = provedor_openai.gerar_composicao(briefing_original, [foto], tmp_path / "composicao.jpg")

    assert resultado["sucesso"] is True
    # O argumento recebido pela funcao continua intacto - nao mutado in-place.
    assert briefing_original == "Briefing exportavel original, sem nenhuma mencao a area segura."
    prompt_enviado = mock_post.call_args.kwargs["data"]["prompt"]
    assert prompt_enviado.startswith(briefing_original)
    assert provedor_openai.INSTRUCAO_AREA_SEGURA_16_9 in prompt_enviado
    assert "16:9" in provedor_openai.INSTRUCAO_AREA_SEGURA_16_9


def test_gerar_composicao_um_sujeito_so_nao_quebra_a_chamada(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    hero = _foto(tmp_path, "hero.jpg")
    resposta = _RespostaFake(status_code=200, corpo={"data": [{"b64_json": _b64_imagem()}]})

    with patch("scripts.imagem.openai.requests.post", return_value=resposta) as mock_post:
        resultado = provedor_openai.gerar_composicao("briefing", [hero], tmp_path / "composicao.jpg")

    assert resultado["sucesso"] is True
    arquivos_enviados = mock_post.call_args.kwargs["files"]
    assert len(arquivos_enviados) == 1
    assert arquivos_enviados[0][1][0] == "hero.jpg"


def test_gerar_composicao_content_policy_violation_captura_motivo_real_sem_excecao(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")
    resposta = _RespostaFake(
        status_code=400,
        corpo={"error": {"code": "content_policy_violation", "message": "Your request was rejected by the safety system."}},
        texto='{"error": {"code": "content_policy_violation", "message": "Your request was rejected by the safety system."}}',
    )

    with patch("scripts.imagem.openai.requests.post", return_value=resposta):
        resultado = provedor_openai.gerar_composicao("briefing", [foto], tmp_path / "composicao.jpg")

    assert resultado["sucesso"] is False
    assert resultado["erro_tipo"] == "content_policy_violation"
    assert "safety system" in resultado["erro_mensagem"]
    assert resultado["status_http"] == 400
    assert not (tmp_path / "composicao.jpg").exists()


def test_gerar_composicao_falha_de_rede_captura_motivo_sem_excecao(monkeypatch, tmp_path):
    import requests

    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")

    with patch("scripts.imagem.openai.requests.post", side_effect=requests.ConnectionError("boom")):
        resultado = provedor_openai.gerar_composicao("briefing", [foto], tmp_path / "composicao.jpg")

    assert resultado["sucesso"] is False
    assert resultado["erro_tipo"] == "erro_rede"
    assert "boom" in resultado["erro_mensagem"]


def test_gerar_composicao_resposta_sem_imagem_captura_motivo_sem_excecao(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")
    resposta = _RespostaFake(status_code=200, corpo={"data": [{}]})

    with patch("scripts.imagem.openai.requests.post", return_value=resposta):
        resultado = provedor_openai.gerar_composicao("briefing", [foto], tmp_path / "composicao.jpg")

    assert resultado["sucesso"] is False
    assert resultado["erro_tipo"] == "resposta_sem_imagem"


def test_gerar_composicao_sucesso_persiste_status_e_custo_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")
    resposta = _RespostaFake(status_code=200, corpo={"data": [{"b64_json": _b64_imagem()}]})
    saida = tmp_path / "composicao.jpg"

    with patch("scripts.imagem.openai.requests.post", return_value=resposta):
        resultado = provedor_openai.gerar_composicao("briefing", [foto], saida)

    assert resultado["sucesso"] is True
    assert saida.exists()

    status_disco = provedor_openai.ler_status_composicao(saida.parent)
    assert status_disco["sucesso"] is True

    caminho_custo = tmp_path / f"{saida.name}.custo.json"
    assert caminho_custo.exists()


def test_gerar_composicao_nunca_recorta_nem_redimensiona_a_imagem_devolvida(monkeypatch, tmp_path):
    """Correcao real (item 1): a imagem devolvida pela API vinha sendo
    recortada de 1536x1024 (3:2) pro 16:9 do canvas de thumbnail, cortando
    texto que o modelo posiciona perto das bordas. `gerar_composicao` tem
    que gravar exatamente os bytes recebidos, na resolucao que vieram -
    sem crop, sem resize, sem conversao de proporcao."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")
    bytes_originais = base64.b64decode(_b64_imagem(tamanho=(1536, 1024)))
    resposta = _RespostaFake(status_code=200, corpo={"data": [{"b64_json": base64.b64encode(bytes_originais).decode("ascii")}]})
    saida = tmp_path / "composicao.jpg"

    with patch("scripts.imagem.openai.requests.post", return_value=resposta):
        resultado = provedor_openai.gerar_composicao("briefing", [foto], saida)

    assert resultado["sucesso"] is True
    assert saida.read_bytes() == bytes_originais
    with Image.open(saida) as imagem_salva:
        assert imagem_salva.size == (1536, 1024)


def test_gerar_composicao_falha_persiste_status_de_erro(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    foto = _foto(tmp_path, "hero.jpg")
    resposta = _RespostaFake(status_code=400, corpo={"error": {"code": "content_policy_violation", "message": "recusado"}})
    saida = tmp_path / "composicao.jpg"

    with patch("scripts.imagem.openai.requests.post", return_value=resposta):
        provedor_openai.gerar_composicao("briefing", [foto], saida)

    status_disco = provedor_openai.ler_status_composicao(saida.parent)
    assert status_disco["sucesso"] is False
    assert status_disco["erro_tipo"] == "content_policy_violation"
