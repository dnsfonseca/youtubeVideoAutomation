@echo off
setlocal
title Broll Foundry

rem Este script instala dependencias do sistema (ffmpeg) quando rodado
rem com a flag --instalar-deps (ver CLAUDE.md secao 18.3). A cascata de
rem instalacao do ffmpeg tenta winget primeiro; se isso nao deixar o
rem ffmpeg acessivel, tenta chocolatey - e chocolatey PODE solicitar
rem permissao de administrador ao Windows (janela de UAC). O script
rem sempre avisa antes de pedir essa permissao. Sem a flag, o
rem comportamento e' identico ao de sempre (nunca pede admin).

cd /d "%~dp0"

rem Se o projeto foi movido/renomeado depois que o atalho da area de
rem trabalho foi criado, o Windows normalmente ja recusa abrir um
rem atalho cujo alvo nao existe mais (erro do proprio Explorer, antes
rem deste script sequer rodar). Esta checagem cobre o caso relacionado
rem que o .bat consegue detectar: rodar a partir de uma pasta que nao
rem tem mais os arquivos do projeto do lado (copia parcial, iniciar.bat
rem isolado de uma copia antiga, etc) - mensagem clara em vez de um
rem traceback do Python mais na frente.
if not exist "%~dp0server.py" (
    echo.
    echo ERRO: server.py nao foi encontrado em "%~dp0".
    echo Isso normalmente acontece quando a pasta do projeto Broll
    echo Foundry foi movida ou renomeada depois que o atalho da area
    echo de trabalho foi criado.
    echo Apague o atalho antigo em Area de Trabalho e rode
    echo "iniciar.bat --instalar-deps" a partir da pasta correta do
    echo projeto para recriar o atalho.
    echo.
    pause
    exit /b 1
)

echo Broll Foundry
echo.

rem Usa sempre o Python 3.11 explicitamente via "py -3.11", nunca o
rem "python" generico do PATH (que pode apontar para outra versao
rem instalada na maquina - faster-whisper/ctranslate2 exigem 3.11).
set PYTHON_311=py -3.11

where py >nul 2>nul
if errorlevel 1 (
    echo O "py launcher" do Windows nao foi encontrado no PATH.
    echo Reinstale o Python 3.11 marcando a opcao "py launcher" no instalador.
    pause
    exit /b 1
)

%PYTHON_311% --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 nao foi encontrado nesta maquina ^(via "py -3.11"^).
    echo Instale o Python 3.11 antes de continuar: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo Primeira execucao: criando ambiente virtual com Python 3.11...
    %PYTHON_311% -m venv venv
    if errorlevel 1 (
        echo Falha ao criar a venv.
        pause
        exit /b 1
    )

    call venv\Scripts\activate.bat

    echo Instalando dependencias de requirements.txt...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Falha ao instalar dependencias.
        pause
        exit /b 1
    )
) else (
    call venv\Scripts\activate.bat
)

rem Pega venv ausente/corrompida cedo (pasta existe mas o interpretador
rem sumiu - copia parcial, disco cheio no meio do "python -m venv", etc)
rem com mensagem clara em vez de deixar o restante do script falhar
rem com erro generico do Windows ("python" nao reconhecido) mais na
rem frente. Item registrado em MELHORIAS_PENDENTES.md.
if not exist "venv\Scripts\python.exe" (
    echo.
    echo ERRO: ambiente virtual Python parece ausente ou corrompido
    echo ^(venv\Scripts\python.exe nao encontrado^).
    echo Execute: iniciar.bat --instalar-deps
    echo Se o problema persistir, apague a pasta "venv" e rode
    echo novamente.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo AVISO: arquivo .env nao encontrado. Copie .env.example para .env
    echo e preencha ANTHROPIC_API_KEY e PROJETOS_DIR antes de usar.
)

rem Verifica se a porta configurada ja esta em uso ANTES de tentar
rem subir o servidor - evita abrir uma segunda instancia por engano
rem quando o usuario ja tem o Broll Foundry rodando em outra janela
rem (ex: clicou no atalho de novo). scripts\verificar_servidor.py
rem distingue "porta livre", "Broll Foundry ja rodando" (confirma
rem checando a assinatura da rota /verificar_atualizacao, CLAUDE.md
rem secao 16 - nunca so' "algo respondeu") e "outro processo ocupando
rem a porta" - so precisa de Python + biblioteca padrao, roda mesmo
rem se o resto do venv ainda nao tiver as dependencias instaladas.
python scripts\verificar_servidor.py checar-porta
set "PORTA_STATUS=%errorlevel%"
if "%PORTA_STATUS%"=="2" (
    echo Abrindo o navegador na instancia ja em execucao...
    python scripts\verificar_servidor.py abrir-navegador
    goto :fim
)
if "%PORTA_STATUS%"=="3" (
    echo.
    echo ERRO: a porta configurada para o Broll Foundry ja esta em uso
    echo por outro processo que nao parece ser esta aplicacao.
    echo Feche o processo que esta usando a porta, ou mude a variavel
    echo PORTA em .env, e rode novamente.
    echo.
    pause
    exit /b 1
)

rem CLAUDE.md secao 18.3 — "iniciar.bat --instalar-deps" faz tudo que a
rem maquina precisa para rodar a ferramenta: instala/verifica ffmpeg no
rem sistema e atualiza as dependencias Python volateis (contra APIs
rem externas que mudam sem aviso - ver CLAUDE.md secao 18). Sem a flag,
rem o comportamento continua identico ao de sempre (so ativa a venv e
rem sobe o servidor). Rodar esta flag manualmente de vez em quando
rem mantem tudo atualizado sem o usuario precisar lembrar comandos.
if /i "%~1"=="--instalar-deps" (
    call :instalar_deps
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

rem Valida saude da venv checando modulos criticos - pega o caso de venv
rem criada mas com "pip install" incompleto (conexao caiu no meio, etc).
python -c "import flask, anthropic, faster_whisper, requests" >nul 2>nul
if errorlevel 1 (
    echo.
    echo AVISO: dependencias faltando ou venv corrompida.
    echo Execute: iniciar.bat --instalar-deps
    echo.
    pause
    exit /b 1
)

rem Valida que o ffmpeg esta acessivel no PATH desta sessao - sem ele a
rem Etapa 1 (baixar) e a Etapa 5/6 (clipes/montagem) falham no meio do
rem pipeline em vez de avisar antes de comecar.
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo AVISO: ffmpeg nao esta acessivel no PATH.
    echo Execute: iniciar.bat --instalar-deps
    echo.
    pause
    exit /b 1
)

rem Valida se ANTHROPIC_API_KEY foi preenchida - e' a unica chave
rem obrigatoria do produto (CLAUDE.md secao 7). As demais sao opcionais.
python -c "from dotenv import load_dotenv; import os; load_dotenv(); k=os.environ.get('ANTHROPIC_API_KEY',''); exit(0 if k and k.startswith('sk-ant') else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo AVISO: ANTHROPIC_API_KEY nao configurada em .env ou invalida.
    echo Obtenha uma chave em https://console.anthropic.com/ e adicione a .env
    echo.
    pause
    exit /b 1
)

rem Abre o navegador automaticamente assim que o servidor Flask
rem comecar a responder de verdade - nunca com espera fixa (o tempo
rem de boot varia por maquina: carregamento de libs, antivirus
rem escaneando, etc). Roda em segundo plano dentro da MESMA sessao de
rem console (sem novo terminal, sem processo desacoplado do atalho) -
rem so' faz polling e abre o navegador; quem continua sendo o
rem servidor de verdade, preso ao terminal, e' o "python server.py"
rem logo abaixo. Se o terminal for fechado antes do polling terminar,
rem este processo auxiliar morre junto (nunca fica orfao rodando).
start "" /B python scripts\verificar_servidor.py aguardar-e-abrir

python server.py

:fim
endlocal
goto :eof


:instalar_deps
echo.
echo === iniciar.bat --instalar-deps ===
echo.

where ffmpeg >nul 2>nul
if not errorlevel 1 (
    echo ffmpeg ja esta no PATH. Nada a fazer para o ffmpeg.
    goto :atualizar_libs_python
)

rem A cascata winget -^> chocolatey -^> instrucao manual mora em
rem scripts/instalar_ffmpeg.py (Python, nao batch) porque precisa de
rem logica que o .bat nao faz bem: busca recursiva de arquivo, escrita
rem no registro do Windows para persistir o PATH, e elevacao via UAC
rem quando cai pra chocolatey. Ver CLAUDE.md secao 18.3.
rem
rem O script avisa via arquivo temporario (FFMPEG_PATH_HINT) se ele
rem proprio adicionou um diretorio novo ao PATH - assim esta sessao do
rem .bat tambem enxerga o ffmpeg sem precisar abrir um terminal novo
rem (o registro do Windows so vale pra terminais futuros).
set "FFMPEG_PATH_HINT=%TEMP%\broll_foundry_ffmpeg_path_hint.txt"
if exist "%FFMPEG_PATH_HINT%" del "%FFMPEG_PATH_HINT%" >nul 2>nul

python scripts\instalar_ffmpeg.py
set "FFMPEG_RESULTADO=%errorlevel%"

if exist "%FFMPEG_PATH_HINT%" (
    for /f "usebackq delims=" %%D in ("%FFMPEG_PATH_HINT%") do set "PATH=%PATH%;%%D"
    del "%FFMPEG_PATH_HINT%" >nul 2>nul
)

if not "%FFMPEG_RESULTADO%"=="0" (
    echo.
    echo Nao foi possivel deixar o ffmpeg pronto para uso automaticamente.
    echo Siga a instrucao manual mostrada acima, depois rode
    echo "iniciar.bat --instalar-deps" novamente.
    exit /b 1
)

:atualizar_libs_python
echo.
echo Atualizando dependencias Python volateis (yt-dlp)...
pip install --upgrade yt-dlp
if errorlevel 1 (
    echo Falha ao atualizar yt-dlp. Verifique sua conexao e tente de novo.
    exit /b 1
)

echo.
echo Dependencias verificadas/atualizadas.
echo.

rem Cria atalho na area de trabalho (nao trava a instalacao se falhar -
rem so' avisa e segue, ver scripts/criar_atalho.py).
echo Criando atalho na area de trabalho...
python scripts\criar_atalho.py
echo.

exit /b 0
