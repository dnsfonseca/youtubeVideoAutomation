# Troubleshooting

## Erros ao rodar `iniciar.bat`

### "O 'py launcher' do Windows não foi encontrado no PATH"

**Causa:** Python instalado sem a opção "py launcher".

**Solução:** reinstale o Python 3.11 marcando "py launcher" —
https://www.python.org/downloads/release/python-31111/

### "Python 3.11 não foi encontrado nesta máquina"

**Causa:** só existe outra versão do Python instalada (o Broll Foundry
exige especificamente 3.11 por causa da compatibilidade CUDA/cuDNN do
`faster-whisper`).

**Solução:** instale o Python 3.11 do link acima — não precisa
desinstalar outras versões, o `iniciar.bat` sempre chama `py -3.11`
explicitamente.

### "AVISO: dependências faltando ou venv corrompida"

**Causa:** a criação da venv ou o `pip install` foi interrompido no
meio (conexão caiu, etc).

**Solução:**

```powershell
iniciar.bat --instalar-deps
```

### "AVISO: ffmpeg não está acessível no PATH"

**Causa:** `ffmpeg` não instalado, ou instalado mas não visível pra
sessão atual do terminal.

**Solução:**

```powershell
iniciar.bat --instalar-deps
```

Se mesmo assim continuar falhando, a cascata automática (winget →
chocolatey) não conseguiu — o próprio script imprime instrução manual:
baixar o zip em https://www.gyan.dev/ffmpeg/builds/, extrair, e
adicionar a pasta `bin` à variável de ambiente `Path` do Windows.

### "AVISO: ANTHROPIC_API_KEY não configurada em .env ou inválida"

**Causa:** `.env` não existe, está com a linha `ANTHROPIC_API_KEY=`
vazia, ou o valor não começa com `sk-ant-`.

**Solução:** copie `.env.example` pra `.env` (se ainda não fez) e
preencha `ANTHROPIC_API_KEY` com uma chave válida — ver
[CHAVES_API.md](CHAVES_API.md).

## Erros de ambiente (GPU/CUDA)

### Banner vermelho "ambiente incompatível" em todas as telas

O próprio Broll Foundry detecta o problema sozinho e mostra o motivo
exato no banner e em `/ajustes` (bloco "Ambiente detectado"). Causas
possíveis:

- **Sem GPU NVIDIA / GPU AMD ou Intel** — sem solução por software,
  precisa de uma GPU NVIDIA (qualquer GTX 1060 em diante já atende).
- **VRAM insuficiente (&lt;4GB)** — mesma solução, precisa trocar a GPU.
  Entre 4-6GB funciona com o modelo `small` do Whisper; 6GB+ é bem mais
  confortável.
- **Driver desatualizado (GPU compatível, mas CUDA &lt;12)** — atualize o
  driver em https://www.nvidia.com/drivers ou pelo GeForce
  Experience/NVIDIA App. Este é o caso mais comum — a maioria das GPUs
  dos últimos 6-8 anos já suporta CUDA 12+ com driver em dia.

Confira com `nvidia-smi` num terminal — procure a linha `CUDA Version:`
ou `CUDA UMD Version:`.

### "Library cublas64_12.dll is not found or cannot be loaded"

**Causa:** o **driver** NVIDIA sozinho não inclui as bibliotecas de
runtime CUDA (cuBLAS/cuDNN) que o `faster-whisper` carrega em tempo de
execução — isso vem à parte, via pip.

**Solução:**

```powershell
iniciar.bat --instalar-deps
```

(ou `pip install -r requirements.txt` manualmente dentro da venv). O
Broll Foundry já registra essas bibliotecas no PATH do processo
automaticamente ao rodar a transcrição — não precisa mexer em variável
de ambiente do Windows na mão.

## Erros no formulário de novo projeto

Mensagens de validação mais comuns:

- **"Nome do projeto inválido"** — use só letras, números, hífen e
  underscore, sem espaço nem acento.
- **"Já existe um projeto chamado '...'"** — escolha outro nome.
- **"Cole ao menos um link de vídeo"** / **"Um ou mais links não
  parecem ser URLs válidas do YouTube"** — confira se colou o link
  completo (não um link encurtado de outro serviço).
- **"Roteiro muito curto (mínimo 100 caracteres)"** — só aparece se
  você escolheu "já tenho um roteiro pronto" com um arquivo vazio ou
  quase vazio.
- **"Total de XMB excede o limite de 2GB"** — no caminho "vídeos
  pré-gerados", a soma de todos os arquivos de vídeo não pode passar de
  2GB. No modo de fontes separadas normal, o limite é por arquivo
  (500MB cada).
- **"Configure PROJETOS_DIR em Ajustes antes de criar um projeto"** —
  você ainda não preencheu essa pasta obrigatória.

## Provedor de TTS "escolhido mas não gera áudio"

Se você selecionou ElevenLabs, OpenAI ou Azure na tela de revisão e a
geração de áudio falhou com um erro dizendo que o provedor ainda não
está disponível: é esperado — esses três são interfaces prontas mas sem
a chamada de API real implementada ainda nesta versão. Use **Google TTS**
ou **DarkPlanner**, ou forneça seu próprio áudio. Ver
[CHAVES_API.md](CHAVES_API.md).

## Outros

### Servidor não abre em `localhost:5000`

**Causa:** porta ocupada, ou firewall bloqueando.

**Solução:**

```powershell
netstat -ano | findstr :5000
```

Se a porta estiver ocupada por outro processo, feche-o ou mude `PORTA`
no `.env`. Se for firewall, libere `python.exe`/`py.exe` no Windows
Defender.

### "Chave DarkPlanner inválida"

**Causa:** chave errada, ou a chave compartilhada foi regenerada.

**Solução:** confirme que copiou certo (começa com `dpk_`). Se
persistir, avise o Daniel — a chave compartilhada pode ter sido trocada.

### Banner amarelo "sua versão de yt-dlp tem N dias"

Não bloqueia nada, é só um aviso — mas downloads podem começar a falhar
silenciosamente se o YouTube tiver mudado algo que aquela versão não
sabe lidar. Resolve com `iniciar.bat --instalar-deps`.

### Download de vídeo-fonte falha (Etapa 1)

Geralmente é o `yt-dlp` desatualizado (ver item acima) ou o vídeo ter
sido removido/tornado privado depois que você colou o link. Confira o
log da etapa na pasta do projeto (`logs/`) pro erro exato.

### Muitos clipes gerados, montagem demorando

Normal em roteiros mais longos. Referência (GPU RTX 3070 Ti): ~2-3 min
pra 100 clipes, ~5-7 min pra 200, ~10-15 min pra 300+. Se travar por
mais de 20 minutos sem progresso na tela de status, aí sim vale
verificar o log da etapa.

### Projeto parado em "aguardando_thumbnail"

Estado normal, não é falha — o vídeo final já está pronto
(`saida/video_final.mp4`), só falta você escolher a thumbnail na tela
`/projetos/<id>/thumbnail` pra o projeto ser marcado como concluído.

### "Configure OPENAI_API_KEY em Ajustes antes de usar a composição por IA"

**Causa:** a geração de imagem da thumbnail (Etapa 7) é feita pela API
de imagens da OpenAI a partir do briefing exportável + fotos dos
sujeitos — sem `OPENAI_API_KEY` configurada em Ajustes não há como
compor a imagem de verdade.

**Solução:** configure a chave em Ajustes, ou continue sem gerar
imagem — o briefing exportável (texto) continua disponível pra colar
manualmente em qualquer outro gerador de imagem.
