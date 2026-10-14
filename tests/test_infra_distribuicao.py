"""Testes de infraestrutura de distribuicao (sessao de documentacao
pre-distribuicao a amigos): .gitignore, coerencia de .env.example e
requirements.txt com o codigo real, e existencia dos documentos novos.

Nao testa CONTEUDO detalhado de prosa dos docs (isso e' revisao humana) -
so' garante que os arquivos existem e que os contratos mecanicos (env
vars documentadas, deps declaradas) nao regridem silenciosamente no
futuro.
"""
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs"


def _gitignore():
    return (BASE_DIR / ".gitignore").read_text(encoding="utf-8")


def test_gitignore_ignora_env():
    conteudo = _gitignore()
    assert re.search(r"^\.env$", conteudo, re.MULTILINE)


def test_gitignore_ignora_venv():
    assert "venv/" in _gitignore()


def test_gitignore_ignora_projetos():
    assert "projetos/" in _gitignore()


def test_gitignore_ignora_pycache_e_pytest_cache():
    conteudo = _gitignore()
    assert "__pycache__/" in conteudo
    assert ".pytest_cache/" in conteudo


def _env_vars_referenciadas_no_codigo():
    """Reproduz a auditoria da Fase 1: toda env var lida via
    os.environ.get/os.getenv/_ler_*_env em server.py e scripts/*.py."""
    padroes = [
        re.compile(r"os\.environ\.get\(\s*['\"]([A-Z_]+)['\"]"),
        re.compile(r"os\.getenv\(\s*['\"]([A-Z_]+)['\"]"),
        re.compile(r"_ler_[a-z_]*env\(\s*['\"]([A-Z_]+)['\"]"),
    ]
    encontradas = set()
    arquivos = [BASE_DIR / "server.py"] + list((BASE_DIR / "scripts").rglob("*.py"))
    ignoradas = {"PATH", "LOCALAPPDATA", "WINDIR", "TEMP", "TMP", "FFMPEG_PATH_HINT"}
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        for padrao in padroes:
            encontradas.update(padrao.findall(texto))
    return encontradas - ignoradas


def test_env_example_tem_todas_variaveis_referenciadas():
    env_example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    faltando = [
        var for var in _env_vars_referenciadas_no_codigo() if var not in env_example
    ]
    assert not faltando, (
        f"Variaveis lidas no codigo mas ausentes de .env.example: {faltando}"
    )


def test_requirements_tem_todas_dependencias_importadas():
    """Reproduz a auditoria 1.1 da Fase 1 - todo import de topo-de-arquivo
    OU lazy-import (dentro de funcao) de biblioteca externa precisa estar
    declarado em requirements.txt (por nome de distribuicao pip, nao de
    modulo - por isso o mapa manual abaixo)."""
    requirements = (BASE_DIR / "requirements.txt").read_text(encoding="utf-8").lower()

    mapa_modulo_para_pacote = {
        "flask": "flask",
        "dotenv": "python-dotenv",
        "anthropic": "anthropic",
        "requests": "requests",
        "markdown": "markdown",
        "faster_whisper": "faster-whisper",
        "yt_dlp": "yt-dlp",
        "pytest": "pytest",
        "win32com": "pywin32",
    }

    padrao_import = re.compile(
        r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE
    )
    arquivos = [BASE_DIR / "server.py"] + list((BASE_DIR / "scripts").rglob("*.py"))
    modulos_usados = set()
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        modulos_usados.update(padrao_import.findall(texto))

    faltando = []
    for modulo, pacote in mapa_modulo_para_pacote.items():
        if modulo in modulos_usados and pacote.lower() not in requirements:
            faltando.append(pacote)

    assert not faltando, f"Pacotes usados mas ausentes de requirements.txt: {faltando}"


def test_pywin32_declarado_para_criar_atalho():
    requirements = (BASE_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert "pywin32" in requirements


def test_readme_existe():
    assert (BASE_DIR / "README.md").exists()


def test_leiame_avisa_que_esta_desatualizado_e_aponta_pro_readme():
    conteudo = (BASE_DIR / "LEIAME.md").read_text(encoding="utf-8")
    assert "README.md" in conteudo
    assert "desatualizada" in conteudo.lower() or "legado" in conteudo.lower()


def test_docs_instalacao_existe():
    assert (DOCS_DIR / "INSTALACAO.md").exists()


def test_docs_primeiro_projeto_existe():
    assert (DOCS_DIR / "PRIMEIRO_PROJETO.md").exists()


def test_docs_fluxo_aplicacao_existe():
    assert (DOCS_DIR / "FLUXO_APLICACAO.md").exists()


def test_docs_chaves_api_existe():
    assert (DOCS_DIR / "CHAVES_API.md").exists()


def test_docs_troubleshooting_existe():
    assert (DOCS_DIR / "TROUBLESHOOTING.md").exists()


def test_docs_custos_existe():
    assert (DOCS_DIR / "CUSTOS.md").exists()


def test_criar_atalho_script_existe():
    assert (BASE_DIR / "scripts" / "criar_atalho.py").exists()


def test_docs_nao_mencionam_placeholder_de_url_do_repo_sem_aviso():
    """docs/INSTALACAO.md precisa de um placeholder pro link do repo git
    (o Daniel preenche depois) - so' confere que existe ALGUM marcador
    reconhecivel, nao que ja tenha a URL real (que nao existe ainda,
    projeto nem e' repo git hoje)."""
    instalacao = (DOCS_DIR / "INSTALACAO.md").read_text(encoding="utf-8")
    assert "<URL_DO_REPO" in instalacao or "URL_DO_REPO" in instalacao
