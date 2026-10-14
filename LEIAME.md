# LEIAME (arquivo legado)

> ⚠️ **Este arquivo está mantido por compatibilidade histórica e pode conter informação desatualizada.**
>
> Documentação atualizada:
> - [README.md](README.md) — ponto de entrada
> - [docs/INSTALACAO.md](docs/INSTALACAO.md) — instalação
> - [docs/PRIMEIRO_PROJETO.md](docs/PRIMEIRO_PROJETO.md) — primeiro projeto
> - [docs/](docs/) — documentação completa

---

# Broll Foundry

Ferramenta local (roda no seu Windows, nunca na nuvem) que automatiza
parte da produção de vídeos "faceless" pra YouTube: baixa vídeos-fonte,
transcreve, e (em sessões futuras) gera roteiro, narração, legendas e o
vídeo final. Ver `CLAUDE.md` pra arquitetura e decisões de produto
completas — este arquivo é só instalação e uso.

## Requisitos mínimos

**Antes de instalar, confira se sua máquina atende:**

| Requisito | Mínimo | Recomendado |
|---|---|---|
| Sistema operacional | Windows 10 x64 | Windows 11 x64 |
| GPU | NVIDIA, Compute Capability 6.0+ (Pascal ou mais novo — GTX 1060 em diante) | RTX qualquer |
| VRAM da GPU | 4 GB | 8 GB+ |
| Driver NVIDIA | Suportando CUDA 12+ | Mais recente disponível |
| RAM do sistema | 16 GB | 32 GB |
| FFmpeg | No PATH do sistema | — |

**GPUs AMD e Intel não são suportadas. Rodar só em CPU (sem GPU) não é
suportado.** A Etapa 2 (transcrição) usa `faster-whisper` em GPU CUDA —
sem uma GPU NVIDIA compatível, essa etapa não funciona, e o Broll Foundry
recusa rodar ela com uma mensagem de erro clara em vez de travar ou
demorar horas numa transcrição em CPU.

### Como conferir se sua máquina atende

Abra um terminal (PowerShell ou cmd) e rode:

```
nvidia-smi
```

Se o comando não for reconhecido, você não tem driver NVIDIA instalado
(ou não tem GPU NVIDIA) — veja "O que fazer se não atender" abaixo.

Se o comando rodar, procure a linha `CUDA Version:` (drivers mais
antigos) ou `CUDA UMD Version:` (drivers mais recentes) no topo da
tabela — é a versão máxima de CUDA que seu driver suporta. Precisa ser
**12.0 ou mais recente**. Também confira o nome da sua GPU na linha da
tabela — qualquer GTX 10xx/16xx, RTX 20xx/30xx/40xx/50xx em diante
atende o mínimo de Compute Capability.

O próprio Broll Foundry faz essa checagem sozinho toda vez que o
servidor sobe (`scripts/ambiente.py`) — se seu ambiente não atender, um
banner vermelho aparece em todas as telas explicando o motivo exato, e a
tela de Ajustes mostra o diagnóstico completo (GPU detectada, VRAM,
driver, o que está faltando).

### O que fazer se não atender

- **Driver desatualizado (GPU compatível, mas CUDA < 12):** atualize o
  driver NVIDIA em [nvidia.com/drivers](https://www.nvidia.com/drivers)
  (ou GeForce Experience/NVIDIA App). A maioria das GPUs dos últimos 8
  anos já suporta CUDA 12+ com o driver atualizado — o problema quase
  sempre é só driver velho, não hardware velho.
- **GPU muito antiga (Compute Capability < 6.0) ou sem GPU NVIDIA:**
  não tem solução por software — é preciso uma GPU NVIDIA compatível
  (qualquer GTX 1060 ou mais nova, incluindo modelos usados baratos,
  já atende o mínimo).
- **VRAM insuficiente (< 4GB):** mesma solução — GPU precisa ser
  trocada. Entre 4-6GB você consegue rodar (modelo `small` do Whisper),
  mas 6GB+ é bem mais confortável.
- **GPU AMD ou Intel:** sem suporte nesta versão. `faster-whisper`
  depende de CUDA (tecnologia exclusiva NVIDIA); suporte a outras GPUs
  não está no roadmap do MVP.

### Problema comum mesmo com ambiente compatível: DLL de CUDA ausente

Se o `nvidia-smi` mostra tudo certo mas a Etapa 2 falha com uma mensagem
tipo `Library cublas64_12.dll is not found or cannot be loaded`, é
porque o **driver** NVIDIA sozinho não inclui as bibliotecas de runtime
CUDA (cuBLAS/cuDNN) que o `faster-whisper` precisa em tempo de execução
— isso é instalado à parte via pip (`nvidia-cublas-cu12` e
`nvidia-cudnn-cu12`, já listados em `requirements.txt`). Rode
`iniciar.bat --instalar-deps` (ou `pip install -r requirements.txt`
manualmente dentro do venv) pra garantir que esses pacotes estão
instalados. O Broll Foundry já registra as pastas dessas bibliotecas no
`PATH` do processo automaticamente ao rodar a Etapa 2 — não precisa
mexer em variáveis de ambiente do Windows manualmente.

## Instalação

1. Instale Python 3.11 (verifique com `python --version`).
2. Copie `.env.example` para `.env` e preencha `PROJETOS_DIR` (pasta
   onde cada projeto de vídeo vai ganhar sua própria subpasta) — as
   demais variáveis são opcionais e têm valor padrão.
3. Rode `iniciar.bat` — ele cria o ambiente virtual (`venv`), instala as
   dependências (`requirements.txt`), e sobe o servidor Flask local.
   - Use `iniciar.bat --instalar-deps` de vez em quando pra manter
     `ffmpeg` e `yt-dlp` atualizados automaticamente (detalhes em
     `CLAUDE.md` seção 18.3).
4. Abra `http://localhost:5000` no navegador (porta configurável via
   `PORTA` no `.env`).

## Uso

1. Tela **Ajustes** (`/ajustes`) — confira o bloco "Ambiente detectado"
   no topo pra confirmar que sua GPU foi reconhecida corretamente, e
   preencha `PROJETOS_DIR` no mínimo.
2. Tela **Novo projeto** (`/novo`) — cole os links dos vídeos-fonte do
   YouTube (um por linha) e dê um nome ao projeto.
3. O pipeline roda sozinho: download dos vídeos (Etapa 1) seguido
   automaticamente de transcrição via GPU (Etapa 2). Acompanhe o
   progresso na tela de status.
4. Depois da transcrição, a IA gera o roteiro (Etapa 3) e o projeto pausa
   na tela de revisão (`/projetos/<id>/revisar_roteiro`) — edite o texto,
   escolha o título, e decida a origem do áudio da narração (gerar via
   TTS ou enviar um áudio próprio). Ver "Configurar narração (TTS)"
   abaixo.
5. Depois que o áudio da narração é obtido, o pipeline continua sozinho:
   geração dos clipes (Etapa 5 — seleciona trechos aleatórios dos
   vídeos-fonte, respeitando margens de segurança no início/fim de cada
   fonte e evitando sobreposição entre clipes da mesma fonte, e aplica
   remoção de marca d'água + Ken Burns via ffmpeg). Zero custo de API —
   só ffmpeg local, tipicamente ~2-5 minutos com GPU.
6. Legendas queimadas e montagem do vídeo final chegam em uma sessão
   futura de desenvolvimento — ver `CLAUDE.md` seção 3 para o escopo
   completo do produto.

A duração de cada clipe (`CLIPE_DURACAO_MIN_S`/`CLIPE_DURACAO_MAX_S`,
padrão 6-10s) e as margens de segurança no início/fim de cada vídeo-fonte
(`MARGEM_INICIO_S`/`MARGEM_FIM_S`, padrão 30s nos dois casos) são
configuráveis no `.env`.

## Configurar narração (TTS)

O Broll Foundry pode gerar a narração automaticamente via **Google Cloud
Text-to-Speech** (provedor principal, implementado nesta versão) ou usar
um áudio gravado por você mesmo (upload na tela de revisão — nesse caso
nenhuma chave é necessária). ElevenLabs, OpenAI e Azure aparecem como
opções na tela mas ainda não estão implementados — ficam desabilitados.

**Como criar a chave do Google Cloud TTS:**

1. Acesse [console.cloud.google.com](https://console.cloud.google.com) e
   crie (ou selecione) um projeto.
2. Ative a API "Cloud Text-to-Speech API" nesse projeto.
3. Em "Credenciais", crie uma chave de API e copie o valor.
4. Cole a chave em **Ajustes** (`/ajustes`, seção "TTS") no campo
   "Chave Google Cloud TTS", ou diretamente em `GOOGLE_TTS_API_KEY` no
   `.env`.

**Alerta de billing (recomendado):** o Google Cloud cobra por caractere
sintetizado. Configure um orçamento com alerta em "Faturamento" →
"Orçamentos e alertas" no Console — evita surpresa se algum roteiro muito
longo for sintetizado por engano.

**Custo aproximado:** o Broll Foundry usa exclusivamente o tier Wavenet
($4,00 por 1 milhão de caracteres — nunca os tiers mais caros Neural2,
Chirp3-HD ou Studio, por proteção de custo). Um roteiro de ~25.000
caracteres (vídeo de 15-20min) custa aproximadamente **$0,10** (~R$0,52
na cotação padrão). O custo real de cada geração aparece em
`narracao_metadata.json` na pasta do projeto, e no log
`logs/tts_calls.log`.

**Vozes recomendadas por idioma:** cada voz Wavenet tem uma descrição
curada (tom, uso recomendado) exibida no próprio dropdown da tela de
revisão — a lista completa fica em
`scripts/tts/vozes_catalogo.json`. Vozes marcadas "★ Recomendada" no
dropdown combinam com o perfil de conteúdo ativo do projeto (true crime,
atualidades narrativas, história).

## Custos de operação

Etapas 1, 2 e 5 (download, transcrição e geração dos clipes) são
gratuitas — rodam inteiramente local, sem chamada de API paga. Só a
Etapa 3 (roteiro via Claude) e a Etapa 4 (narração via TTS) têm custo por
vídeo — ver `CLAUDE.md` seção 11 para a tabela completa, e "Configurar
narração (TTS)" acima para o custo aproximado do áudio.

### Custo por roteiro (`WEB_SEARCH_MAX`, ajustável em Ajustes)

Com `WEB_SEARCH_MAX=5` (padrão desde a Sessão 22): ~R$ 5-6 por roteiro.
Com `WEB_SEARCH_MAX=2` (mínimo econômico): ~R$ 3-4 por roteiro.

Aumente o valor se os roteiros ficarem desatualizados em relação a
desenvolvimentos recentes de um caso. Reduza pra economizar em temas
evergreen (história antiga, por exemplo), onde frescor de dados importa
pouco.

## Privacidade

Produto 100% local. Seus vídeos, transcrições e chaves de API ficam
somente na sua máquina — nada é enviado para servidores do Broll Foundry
(não existem).
