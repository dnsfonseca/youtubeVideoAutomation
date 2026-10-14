"""Testes do iniciar.bat --instalar-deps (CLAUDE.md secao 18.3).

iniciar.bat e' um batch file, nao um modulo Python - nao da pra importar
e chamar funcao. Os testes aqui sao PROPOSITALMENTE so asserções
estáticas sobre o conteúdo do arquivo — nunca sobem o script de verdade
via subprocess.

Isso nao e' preguica: uma tentativa anterior de rodar o script de
verdade com um PATH filtrado (removendo o diretorio esperado do
winget.exe) para forcar o caminho "winget ausente" de forma
deterministica NAO funcionou como esperado — o Windows resolveu o
winget mesmo assim (App Execution Alias tem mecanismos de resolucao que
nao dependem so do PATH herdado pelo subprocesso) e o teste ACABOU
INSTALANDO FFMPEG DE VERDADE na maquina via winget, alem de deixar um
`python server.py` real rodando em background ate ser encontrado e
morto manualmente. CLAUDE.md secao 8 proibe bater servico externo real
em teste, e isso vale a fortiori para "instalar software de verdade" e
"subir um servidor de verdade que nunca retorna sozinho" — nenhum PATH
filtrado dá garantia forte o suficiente disso nao acontecer de novo.

A cascata winget -> chocolatey -> instrucao manual (CLAUDE.md secao
18.3) mora em scripts/instalar_ffmpeg.py, nao neste .bat - la sim da
pra mockar subprocess/shutil/etc e testar cada cenario de verdade (ver
tests/test_instalar_ffmpeg.py). Os testes abaixo cobrem so o que da pra
provar com seguranca sobre o .bat em si: que ele delega pro script
Python certo, propaga o PATH descoberto pro resto da sessao, e nao muda
de comportamento sem a flag.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INICIAR_BAT = BASE_DIR / "iniciar.bat"


def _conteudo():
    return INICIAR_BAT.read_text(encoding="utf-8")


def test_arquivo_usa_quebra_de_linha_crlf_em_todo_lugar():
    """Regressao critica descoberta em teste real nesta sessao: iniciar.bat
    com quebras de linha LF-only (sem \\r) faz o parser de blocos
    parentizados do cmd.exe (`if ... ( ... )`) perder o alinhamento de
    leitura do arquivo logo apos o bloco - o cmd.exe passa a executar
    fragmentos de linhas seguintes como se fossem comandos separados
    (ex: "errorlevel" sendo rodado sozinho como comando, pedacos como
    "tlocal"/"cho"/"ho." de "endlocal"/"echo."). O bug so aparece na
    execucao real (nao da pra pegar so lendo o .bat), foi reproduzido
    de forma determinística rodando o arquivo de verdade via
    subprocess.Popen (fora da suite de testes, nunca aqui - ver aviso
    no topo deste arquivo) e desaparece por completo convertendo o
    arquivo inteiro para CRLF. Editores/ferramentas que gravam arquivo
    tendem a usar LF por padrao no Windows tambem - este teste existe
    pra pegar a regressao na proxima vez que alguem editar o .bat."""
    bruto = INICIAR_BAT.read_bytes()

    linhas_lf_sem_cr = [
        i
        for i, byte in enumerate(bruto)
        if byte == 0x0A and (i == 0 or bruto[i - 1] != 0x0D)
    ]

    assert not linhas_lf_sem_cr, (
        f"{len(linhas_lf_sem_cr)} quebra(s) de linha sem \\r encontradas em "
        "iniciar.bat - isso corrompe a execucao real do cmd.exe (ver "
        "docstring deste teste). Converta o arquivo inteiro para CRLF."
    )


def _linha_da_secao_instalar_deps():
    """Isola o bloco de texto da subrotina :instalar_deps (do label ate
    o `exit /b 0` final de sucesso) — usado pelos testes que precisam
    confirmar algo especifico dessa secao, sem falso-positivo por causa
    de comentarios em outra parte do arquivo (ex: a nota sobre
    faster-whisper/ctranslate2 no topo do script, que fala de Python
    3.11 e nao tem nada a ver com o upgrade automatico)."""
    conteudo = _conteudo()
    inicio = conteudo.index("\n:instalar_deps\n")
    return conteudo[inicio:]


def test_instalar_deps_flag_documentada_no_arquivo():
    assert "--instalar-deps" in _conteudo()


def test_topo_do_arquivo_avisa_sobre_permissao_de_administrador():
    """Documentacao proativa pedida nesta sessao: usuario final precisa
    saber, antes de rodar a flag, que UAC pode aparecer."""
    conteudo = _conteudo()
    cabecalho = conteudo.split("cd /d", 1)[0]

    assert "administrador" in cabecalho.lower()
    assert "--instalar-deps" in cabecalho


def test_instalar_deps_verifica_ffmpeg_no_path_antes_de_delegar_pro_script():
    secao = _linha_da_secao_instalar_deps()

    assert "where ffmpeg" in secao


def test_instalar_deps_delega_a_cascata_para_o_script_python():
    """A logica de winget/chocolatey/instrucao manual mora em
    scripts/instalar_ffmpeg.py (CLAUDE.md secao 18.3) - o .bat so
    invoca e confere o resultado, nunca reimplementa a cascata."""
    secao = _linha_da_secao_instalar_deps()

    assert "python scripts\\instalar_ffmpeg.py" in secao
    assert (BASE_DIR / "scripts" / "instalar_ffmpeg.py").exists()


def test_instalar_deps_propaga_path_descoberto_pelo_script_para_a_sessao_atual():
    """O script Python pode adicionar um diretorio novo ao PATH do
    usuario (registro do Windows), mas isso nao afeta o processo do
    .bat ja em execucao - por isso ele precisa ler o arquivo de hint e
    estender o proprio PATH, senao o `python server.py` desta mesma
    sessao ainda nao enxergaria o ffmpeg recem-instalado."""
    secao = _linha_da_secao_instalar_deps()

    assert "FFMPEG_PATH_HINT" in secao
    assert 'set "PATH=%PATH%;%%D"' in secao


def test_instalar_deps_para_o_script_com_erro_se_a_cascata_falhar():
    secao = _linha_da_secao_instalar_deps()

    assert "FFMPEG_RESULTADO" in secao
    assert 'if not "%FFMPEG_RESULTADO%"=="0"' in secao
    assert "exit /b 1" in secao


def test_instalar_deps_atualiza_yt_dlp_mas_nao_faster_whisper():
    """Regressao da decisao documentada em CLAUDE.md secao 18.3: upgrade
    automatico e' so pra yt-dlp (volatil contra o YouTube). faster-whisper
    fica de fora do --instalar-deps de proposito, porque um upgrade
    automatico dele pode quebrar a compatibilidade CUDA/cuDNN ja
    documentada na secao 4 - atualizacao dele e' sempre manual."""
    secao = _linha_da_secao_instalar_deps()

    assert "pip install --upgrade yt-dlp" in secao
    assert "faster-whisper" not in secao


def test_sem_flag_comportamento_nao_muda():
    """CLAUDE.md secao 18.3: sem a flag, o fluxo continua identico ao de
    sempre — o bloco de --instalar-deps so roda dentro do `if /i
    "%~1"=="--instalar-deps"`, nunca incondicionalmente."""
    conteudo = _conteudo()

    assert 'if /i "%~1"=="--instalar-deps"' in conteudo


def _secao_validacoes_pre_boot():
    """Isola o bloco entre o fim do tratamento da flag --instalar-deps e
    o "python server.py" - onde moram as validacoes de saude adicionadas
    nesta sessao (venv, ffmpeg, ANTHROPIC_API_KEY)."""
    conteudo = _conteudo()
    inicio = conteudo.index("rem Valida saude da venv")
    fim = conteudo.index("python server.py")
    return conteudo[inicio:fim]


def test_valida_saude_da_venv_antes_de_subir_servidor():
    secao = _secao_validacoes_pre_boot()

    assert "import flask, anthropic, faster_whisper, requests" in secao
    assert "--instalar-deps" in secao


def test_valida_ffmpeg_no_path_antes_de_subir_servidor():
    secao = _secao_validacoes_pre_boot()

    assert "where ffmpeg" in secao
    assert "--instalar-deps" in secao


def test_valida_anthropic_api_key_antes_de_subir_servidor():
    secao = _secao_validacoes_pre_boot()

    assert "ANTHROPIC_API_KEY" in secao
    assert "sk-ant" in secao
    assert "console.anthropic.com" in secao


def test_validacoes_pre_boot_rodam_mesmo_sem_a_flag():
    """As tres validacoes novas (venv/ffmpeg/chave) ficam FORA do bloco
    condicional da flag --instalar-deps - elas sempre rodam antes de
    "python server.py", com ou sem a flag (pedido explicito da sessao:
    "so adiciona validacoes", preservando o resto do comportamento)."""
    conteudo = _conteudo()

    bloco_flag_inicio = conteudo.index('if /i "%~1"=="--instalar-deps"')
    bloco_flag_fim = conteudo.index("rem Valida saude da venv")
    bloco_flag = conteudo[bloco_flag_inicio:bloco_flag_fim]

    assert "import flask" not in bloco_flag
    assert "where ffmpeg" not in bloco_flag


def test_instalar_deps_cria_atalho_na_area_de_trabalho():
    secao = _linha_da_secao_instalar_deps()

    assert "python scripts\\criar_atalho.py" in secao
    assert (BASE_DIR / "scripts" / "criar_atalho.py").exists()


def test_detecta_projeto_movido_ou_renomeado_antes_de_qualquer_outra_coisa():
    """Melhoria do fluxo do atalho: se iniciar.bat estiver rodando de uma
    pasta sem os arquivos do projeto do lado (copia parcial, pasta
    movida), mostra mensagem clara em vez de deixar o script falhar mais
    na frente com erro generico. Precisa vir logo apos o "cd /d", antes
    de qualquer outra checagem."""
    conteudo = _conteudo()

    cd_pos = conteudo.index('cd /d "%~dp0"')
    checagem_pos = conteudo.index('if not exist "%~dp0server.py"')
    py_check_pos = conteudo.index("where py >nul")

    assert cd_pos < checagem_pos < py_check_pos
    assert "--instalar-deps" in conteudo[checagem_pos:py_check_pos]


def test_detecta_venv_com_python_exe_ausente():
    """Item de MELHORIAS_PENDENTES.md: venv pode existir (activate.bat
    presente) mas estar corrompida (python.exe ausente). Checagem tem
    que vir depois do bloco que cria/ativa a venv e antes das validacoes
    de saude que dependem de rodar "python" de verdade."""
    conteudo = _conteudo()

    ativacao_pos = conteudo.index("call venv\\Scripts\\activate.bat\n)")
    checagem_pos = conteudo.index('if not exist "venv\\Scripts\\python.exe"')
    porta_check_pos = conteudo.index("verificar_servidor.py checar-porta")

    assert ativacao_pos < checagem_pos < porta_check_pos
    assert "--instalar-deps" in conteudo[checagem_pos : checagem_pos + 400]


def _secao_checagem_de_porta():
    conteudo = _conteudo()
    inicio = conteudo.index("rem Verifica se a porta configurada ja esta em uso")
    fim = conteudo.index("rem CLAUDE.md secao 18.3")
    return conteudo[inicio:fim]


def test_checa_porta_antes_de_subir_servidor_e_antes_do_flag_instalar_deps():
    """A checagem de porta ja em uso roda ANTES do tratamento da flag
    --instalar-deps e antes das validacoes de ffmpeg/API key - assim o
    caso "Broll Foundry ja esta rodando" nao fica bloqueado por uma
    validacao irrelevante nesta sessao especifica do terminal."""
    conteudo = _conteudo()

    porta_pos = conteudo.index("verificar_servidor.py checar-porta")
    flag_pos = conteudo.index('if /i "%~1"=="--instalar-deps"')
    ffmpeg_pos = conteudo.index("where ffmpeg >nul 2>nul", flag_pos)

    assert porta_pos < flag_pos < ffmpeg_pos


def test_porta_ja_em_uso_pelo_broll_foundry_abre_navegador_sem_subir_outro_servidor():
    secao = _secao_checagem_de_porta()

    assert 'if "%PORTA_STATUS%"=="2"' in secao
    assert "verificar_servidor.py abrir-navegador" in secao
    assert "goto :fim" in secao
    assert ":fim" in _conteudo()


def test_porta_ocupada_por_outro_processo_avisa_e_para_sem_matar_nada():
    secao = _secao_checagem_de_porta()

    assert 'if "%PORTA_STATUS%"=="3"' in secao
    assert "exit /b 1" in secao
    # nunca mata/substitui o processo existente - so avisa e sai
    assert "taskkill" not in secao.lower()


def test_abre_navegador_automaticamente_com_polling_em_segundo_plano_no_mesmo_console():
    """Nunca com espera fixa (sem "timeout /t N" como sincronizacao) e
    nunca desacoplado do terminal (sem "start" com titulo de janela nova
    - so' "start \"\" /B" dentro da mesma sessao de console)."""
    conteudo = _conteudo()

    antes_do_servidor = conteudo[: conteudo.index("python server.py\n\n:fim")]
    trecho_navegador = antes_do_servidor[
        antes_do_servidor.index("rem Abre o navegador automaticamente") :
    ]

    assert 'start "" /B python scripts\\verificar_servidor.py aguardar-e-abrir' in trecho_navegador


def test_servidor_continua_rodando_em_foreground_preso_ao_terminal():
    """python server.py continua sendo chamado direto (sem "start" nem
    "call" desacoplando), preservando o comportamento de sempre: fechar
    o terminal encerra o servidor."""
    conteudo = _conteudo()

    assert "\npython server.py\n" in conteudo
    assert 'start "" /B python server.py' not in conteudo
    assert 'start "Broll Foundry Servidor"' not in conteudo
