# Instalação

## Pré-requisitos

### 1. Python 3.11

Baixe em: https://www.python.org/downloads/release/python-31111/

Durante a instalação, **marque**:
- ☑ "Add python.exe to PATH"
- ☑ "py launcher" (o Broll Foundry chama sempre `py -3.11`, nunca `python`
  genérico, pra não pegar outra versão instalada na sua máquina por acidente)
- ☑ "Install for all users" (recomendado, evita problema de permissão depois)

Verifique a instalação abrindo um PowerShell:

```powershell
py -3.11 --version
```

Tem que mostrar `Python 3.11.x`. Se der erro "py não é reconhecido",
reinstale marcando "py launcher".

[SCREENSHOT: instalador do Python com as três opções marcadas]

### 2. Git (pra clonar o repositório)

Baixe em: https://git-scm.com/download/win

Pode aceitar todas as opções padrão do instalador.

### 3. GPU NVIDIA

O Broll Foundry **exige** GPU NVIDIA — a transcrição (Etapa 2) roda
`faster-whisper` em CUDA, e sem GPU compatível essa etapa não funciona.
AMD, Intel e "só CPU" não são suportados.

Confira sua placa:

1. `Win + R`, digite `dxdiag`, Enter
2. Aba "Vídeo" (ou "Display"), veja o campo "Nome"
3. Precisa ser uma GeForce GTX 10xx/16xx ou RTX 20xx em diante

[SCREENSHOT: dxdiag mostrando uma GeForce RTX detectada]

### 4. Driver NVIDIA atualizado

Baixe em: https://www.nvidia.com/download/index.aspx (ou use o
GeForce Experience / NVIDIA App se já tiver instalado).

O requisito é o **driver** suportar CUDA 12+ — a maioria das placas dos
últimos 6-8 anos já suporta, desde que o driver esteja atualizado. Se
seu driver estiver desatualizado é normalmente aí que está o problema,
não na idade da placa.

Depois de instalar/atualizar o driver, rode `nvidia-smi` num terminal e
confira a linha `CUDA Version:` (ou `CUDA UMD Version:` em drivers mais
novos) — precisa mostrar 12.0 ou mais recente. O próprio Broll Foundry
faz essa checagem sozinho toda vez que o servidor sobe e mostra um
banner vermelho se algo não bater.

## Instalação da ferramenta

### Passo 1 — Clonar o repositório

Abra o PowerShell na pasta onde quer instalar (ex: `C:\Projetos`):

```powershell
cd C:\Projetos
git clone <URL_DO_REPO_PRIVADO> broll_foundry
cd broll_foundry
```

> A URL do repositório é enviada por fora (não vai neste documento). Se
> não recebeu, peça ao Daniel.

### Passo 2 — Configurar chaves de API

**Faça isto antes do próximo passo** — a partir desta versão,
`iniciar.bat` se recusa a subir o servidor sem uma
`ANTHROPIC_API_KEY` válida configurada.

1. Copie o arquivo de exemplo:

```powershell
Copy-Item .env.example .env
```

2. Abra `.env` no bloco de notas:

```powershell
notepad .env
```

3. No mínimo, preencha:
   - `ANTHROPIC_API_KEY` — **obrigatória**. Ver [CHAVES_API.md](CHAVES_API.md).
   - `PROJETOS_DIR` — **obrigatória**. Pasta onde cada projeto de vídeo
     ganha sua própria subpasta (ex: `E:\broll` ou `C:\Projetos\broll_videos`).

O resto é opcional e já vem com valor padrão sensato — só mexa se
precisar (ver [CHAVES_API.md](CHAVES_API.md) pras chaves de TTS).

⚠️ **Nunca compartilhe seu `.env`, nunca cole o conteúdo dele no chat, e
nunca commite ele no git** (o `.gitignore` já bloqueia isso, mas vale o
cuidado extra).

[SCREENSHOT: .env aberto no notepad com ANTHROPIC_API_KEY preenchida]

### Passo 3 — Instalar dependências e primeira execução

```powershell
.\iniciar.bat --instalar-deps
```

Isso vai, nesta ordem:

1. Criar o ambiente virtual Python (`venv\`) e instalar tudo de
   `requirements.txt`
2. Instalar o `ffmpeg` no sistema, se ainda não estiver no PATH (tenta
   `winget` primeiro; se não der certo, tenta `chocolatey` — e aí o
   Windows **pode pedir permissão de administrador via UAC**, isso é
   normal e seguro, o próprio script avisa antes de pedir)
3. Atualizar o `yt-dlp` pra versão mais recente (ele quebra com
   frequência porque o YouTube muda a extração; `iniciar.bat --instalar-deps`
   é a forma de manter ele em dia sem precisar lembrar do comando)
4. Criar um atalho "Broll Foundry" na sua área de trabalho
5. Validar que tudo está pronto (dependências Python, `ffmpeg` no PATH,
   `ANTHROPIC_API_KEY` preenchida) e, se sim, **subir o servidor** —
   você não precisa rodar `iniciar.bat` de novo separadamente

[SCREENSHOT: terminal rodando iniciar.bat --instalar-deps]

Duração: 5-15 minutos dependendo da sua conexão.

O servidor sobe em: http://localhost:5000

[SCREENSHOT: navegador aberto na tela inicial do Broll Foundry]

Rode `iniciar.bat --instalar-deps` de novo sempre que atualizar o
repositório (`git pull`) — dependências podem ter mudado.

> **Geração de thumbnail (Etapa 7):** a composição da imagem final é
> feita pela API de imagens da OpenAI a partir do briefing exportável
> gerado pelo Claude + as fotos dos sujeitos enviadas — exige
> `OPENAI_API_KEY` configurada em Ajustes (tem custo por imagem gerada).
> Sem a chave, o projeto ainda gera o briefing em texto (que continua
> disponível pra colar manualmente em qualquer outro gerador de
> imagem), só não produz a imagem automaticamente.

### Passo 4 — Próximas vezes

Nas execuções seguintes, não precisa mais da flag — dê duplo-clique no
atalho "Broll Foundry" criado na área de trabalho, ou pelo terminal:

```powershell
.\iniciar.bat
```

## Validação pós-instalação

Você deve conseguir:

1. ✅ Abrir http://localhost:5000 no navegador e ver a home (lista de
   projetos vazia)
2. ✅ Abrir `/ajustes` sem erro e ver o bloco "Ambiente detectado" no
   topo confirmando sua GPU (card verde) — se aparecer um card vermelho
   de ambiente incompatível, ver [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
3. ✅ Ver `ANTHROPIC_API_KEY` já preenchida em Ajustes (o valor real não
   aparece por segurança, mas o campo não deve estar vazio)
4. ✅ Nenhum banner vermelho persistente no topo da página (ffmpeg
   ausente ou ambiente incompatível)

Se qualquer passo falhar, ver [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Atualizações futuras

Pra pegar novas versões do Broll Foundry:

```powershell
cd C:\Projetos\broll_foundry
git pull
.\iniciar.bat --instalar-deps
```

Sempre rode `--instalar-deps` depois de um `git pull` — dependências e
requisitos de sistema podem ter mudado.
