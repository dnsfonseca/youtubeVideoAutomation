"""Fixtures compartilhadas para os testes do Broll Foundry.

Convenções (ver CLAUDE.md seção 11):
- Nunca tocar no .env real do projeto — todo teste usa um .env isolado
  criado em tmp_path via create_app(env_path=...).
- Nenhuma chamada real a API externa (Anthropic, YouTube, yt-dlp,
  faster-whisper) — o server.py ainda não integra nenhuma delas, mas a
  convenção vale desde já para os testes futuros que forem chegando
  neste conftest.
"""

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import server  # noqa: E402
from server import CAMPOS_AJUSTES, create_app  # noqa: E402


def _escrever_env(caminho: Path, **overrides):
    valores = {
        "PROJETOS_DIR": "",
    }
    valores.update(overrides)
    linhas = [f"{chave}={valor}" for chave, valor in valores.items()]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


@pytest.fixture(autouse=True)
def _limpar_jobs_em_memoria():
    """server.jobs e server._threads sao dicts globais no modulo (estado de
    job em memoria - CLAUDE.md secao 4), entao vazam entre testes que nao
    usam a mesma app Flask. Limpa antes e depois de cada teste."""
    server.jobs.clear()
    server._threads.clear()
    yield
    server.jobs.clear()
    server._threads.clear()


@pytest.fixture(autouse=True)
def _limpar_env_das_variaveis_de_ajustes(monkeypatch):
    """Remove do os.environ, antes de cada teste, todas as variáveis que
    create_app()/POST /ajustes podem ter deixado de um teste anterior.

    create_app() faz load_dotenv(..., override=True), que mexe no
    os.environ do processo inteiro (não é isolado por app). Sem essa
    limpeza, um teste que grava PROJETOS_DIR vazaria estado para o
    próximo teste que rodar depois na mesma sessão do pytest.
    monkeypatch desfaz a limpeza sozinho ao final do teste.
    """
    for campo in CAMPOS_AJUSTES:
        monkeypatch.delenv(campo, raising=False)
    yield


GPU_COMPATIVEL_PADRAO = {
    "presente": True,
    "modelo": "NVIDIA GeForce RTX 3070 Ti",
    "vram_mb": 8192,
    "driver_version": "560.94",
    "compute_capability": "8.6",
    "cuda_umd_version": "12.6",
    "erro": None,
}


@pytest.fixture
def _ambiente_compativel_padrao(monkeypatch):
    """create_app() detecta o ambiente NVIDIA/CUDA no boot (CLAUDE.md secao
    13/18), o que por padrao chamaria nvidia-smi de verdade — nenhum teste
    que cria uma app Flask pode depender de hardware real (CLAUDE.md secao
    8), ainda mais porque a maquina que roda a suite pode nao ter GPU.

    Por padrao simula uma GPU compativel (RTX 3070 Ti, 8GB VRAM, CUDA
    12.6) — os testes que exercitam o cenario de ambiente incompativel
    sobrescrevem `server.ambiente.detectar_gpu` explicitamente antes de
    chamar `criar_app(...)`, mesmo padrao de `_robustez_sem_rede` para os
    banners de lib desatualizada/ffmpeg."""
    monkeypatch.setattr(server.ambiente, "detectar_gpu", lambda: dict(GPU_COMPATIVEL_PADRAO))


@pytest.fixture
def _robustez_sem_rede(monkeypatch):
    """create_app() roda a checagem de robustez do boot (CLAUDE.md secao
    18.2), que por padrao consultaria a PyPI de verdade — nenhum teste
    que cria uma app Flask pode depender de rede real (CLAUDE.md secao
    8). Por padrao simula "sem informacao de idade" (idade_lib retorna
    None, banner nao aparece) e ffmpeg disponivel; os testes de banner
    sobrescrevem isso explicitamente via monkeypatch em server.robustez.

    NAO e' autouse de proposito: autouse aplicaria a TODO teste da suite
    (inclusive tests/test_robustez.py, que testa as funcoes reais de
    scripts/robustez.py e precisa que elas NAO estejam substituidas por
    lambda). Em vez disso, e' uma dependencia explicita de `criar_app`
    abaixo — só os testes que efetivamente criam uma app Flask (via
    `criar_app`/`app`/`client`) pagam esse isolamento.
    """
    monkeypatch.setattr(server.robustez, "idade_lib", lambda nome, timeout_s=3: None)
    monkeypatch.setattr(server.robustez, "ffmpeg_disponivel", lambda: True)


@pytest.fixture
def criar_app(
    tmp_path, _limpar_env_das_variaveis_de_ajustes, _robustez_sem_rede, _ambiente_compativel_padrao
):
    """Factory fixture: cria um app Flask isolado, com .env próprio em
    tmp_path (nunca o .env real da raiz do projeto).

    Uso: `app = criar_app()` para o .env mínimo padrão, ou
    `app = criar_app(PROJETOS_DIR=str(algum_tmp_path))` para sobrescrever
    campos específicos.
    """

    def _factory(**overrides):
        caminho_env = tmp_path / ".env"
        _escrever_env(caminho_env, **overrides)
        app = create_app(env_path=caminho_env)
        app.config.update(TESTING=True)
        return app

    return _factory


@pytest.fixture
def app(criar_app):
    """App Flask padrão, com .env mínimo (PROJETOS_DIR vazio). Para
    cenários que precisam de outros valores, use `criar_app` diretamente."""
    return criar_app()


@pytest.fixture
def client(app):
    return app.test_client()
