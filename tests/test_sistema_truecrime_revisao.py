"""Testes da revisao editorial do sistema.md do perfil truecrime (Bloco C,
Sessao 7.2 - CLAUDE.md secao 3.1): 4 novas secoes adicionadas a pedido de
avaliacao de IA especialista em roteiro de True Crime (balanco entre rigor
e narrativa, resolucao narrativa de conflitos, anti-redundancia, estrutura
de retencao YouTube). O problema #1 da avaliacao (tags de citacao) foi
propositalmente ignorado - ja resolvido pelo sistema de badges (Bloco A).

Confirma so que as secoes foram adicionadas e que a montagem de prompt via
loader continua funcionando (interpolacao de placeholders, outros perfis
intocados) - nao testa qualidade editorial do texto em si (isso exige
avaliacao humana/IA, fora do escopo de teste automatizado)."""

from pathlib import Path

from scripts.prompts import loader

SISTEMA_TRUECRIME_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "prompts"
    / "perfis"
    / "truecrime"
    / "sistema.md"
)


def _ler_sistema_truecrime() -> str:
    return SISTEMA_TRUECRIME_PATH.read_text(encoding="utf-8")


def test_sistema_truecrime_contem_secao_balanco_rigor_narrativa():
    texto = _ler_sistema_truecrime()
    assert "Balanço entre rigor e narrativa" in texto
    assert "laudo pericial" in texto


def test_sistema_truecrime_contem_secao_resolucao_narrativa_conflitos():
    """Reforcada pos-Sessao 7.2 apos roteiro real (Lily & Jack) narrar DUAS
    versoes conflitantes no mesmo paragrafo - a secao agora e' explicita
    (regra absoluta) e traz exemplo ruim concreto."""
    texto = _ler_sistema_truecrime()
    assert "Resolução narrativa de conflitos entre fontes" in texto
    assert "ESCOLHA UMA versão pra usar no texto narrado" in texto
    assert "REGRA ABSOLUTA" in texto
    assert "NUNCA descreva as duas" in texto
    assert "Exemplo RUIM (proibido)" in texto


def test_sistema_truecrime_contem_secao_anti_redundancia():
    texto = _ler_sistema_truecrime()
    assert "Anti-redundância" in texto
    assert "até 2 vezes" in texto


def test_sistema_truecrime_contem_secao_estrutura_retencao_youtube():
    texto = _ler_sistema_truecrime()
    assert "Estrutura de retenção YouTube" in texto
    assert "Hook de abertura" in texto
    assert "CTA final" in texto
    assert "Pergunta de engajamento" in texto


def test_sistema_truecrime_novas_secoes_nao_duplicam_bloco_juridico():
    """As novas secoes ficam fora do {BLOCO_JURIDICO}/juridico_*.md - nao
    foram inseridas por engano dentro do bloco jurídico interpolado."""
    texto = _ler_sistema_truecrime()
    indice_bloco_juridico = texto.index("{BLOCO_JURIDICO}")
    indice_balanco = texto.index("Balanço entre rigor e narrativa")
    assert indice_balanco < indice_bloco_juridico


def test_loader_monta_prompt_truecrime_apos_revisao_sem_erro():
    prompt = loader.montar_prompt("truecrime", "en-US", web_search_max=4)

    assert isinstance(prompt, str)
    assert "{WEB_SEARCH_MAX}" not in prompt
    assert "4 buscas" in prompt or "limite: 4" in prompt.lower()
    assert "Estrutura de retenção YouTube" in prompt
    assert "Anti-redundância" in prompt


def test_loader_monta_prompt_truecrime_interpola_web_search_max_default():
    """Sem web_search_max explicito, cai no fallback do loader - garante que
    a revisao nao quebrou a interpolacao de {WEB_SEARCH_MAX}."""
    prompt = loader.montar_prompt("truecrime", "en-US")
    assert "{WEB_SEARCH_MAX}" not in prompt


def test_loader_outros_perfis_nao_afetados_pela_revisao_truecrime():
    """atualidades_narrativas e historia nao foram tocados nesta revisao -
    continuam montando prompt normalmente."""
    prompt_atualidades = loader.montar_prompt("atualidades_narrativas", "en-US")
    prompt_historia = loader.montar_prompt("historia", "en-US")

    assert isinstance(prompt_atualidades, str) and prompt_atualidades.strip()
    assert isinstance(prompt_historia, str) and prompt_historia.strip()
    assert "{WEB_SEARCH_MAX}" not in prompt_atualidades
    assert "{WEB_SEARCH_MAX}" not in prompt_historia
