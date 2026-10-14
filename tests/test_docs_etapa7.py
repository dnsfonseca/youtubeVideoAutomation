"""Testes de regressao pra documentacao da Etapa 7 (thumbnail,
scripts/7_thumbnail.py). Nao testam prosa/redacao - so' garantem que o
README nao volta a descrever o pipeline como se tivesse só 6 etapas (sem
a thumbnail).

`opencv-python` saiu de requirements.txt por inteiro na sessao de
simplificacao da Etapa 7 (removeu o scan de cenario que o usava) - o
teste de pin exato que existia aqui (`test_requirements_pina_opencv_com_
igual_igual`) foi removido junto, nunca teve sentido testar o pin de uma
dependencia que nao existe mais."""
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
README_MD = BASE_DIR / "README.md"


def test_readme_nao_descreve_pipeline_com_apenas_6_etapas():
    """O README lista as etapas do pipeline como um passo-a-passo
    numerado. Precisa ter pelo menos 7 itens (a Etapa 7 - thumbnail -
    faz parte do pipeline) e mencionar thumbnail explicitamente."""
    conteudo = README_MD.read_text(encoding="utf-8")

    itens_numerados = re.findall(r"^\d+\.\s", conteudo, re.MULTILINE)
    assert len(itens_numerados) >= 7, (
        f"README descreve o pipeline com só {len(itens_numerados)} passo(s) "
        "numerado(s) - a Etapa 7 (thumbnail) parece ter ficado de fora"
    )

    assert "thumbnail" in conteudo.lower(), (
        "README nao menciona 'thumbnail' em lugar nenhum - a Etapa 7 "
        "precisa aparecer na descricao do pipeline"
    )
