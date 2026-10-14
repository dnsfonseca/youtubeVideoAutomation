# Fluxo da aplicação

Referência de cada tela do Broll Foundry e o que ela faz. Pra um
tutorial guiado do caminho mais simples, ver
[PRIMEIRO_PROJETO.md](PRIMEIRO_PROJETO.md).

## Home (`/`)

[SCREENSHOT: home com a tabela de projetos e os cards de resumo]

No topo, 4 números-resumo: total de projetos, em andamento, concluídos
no mês, e custo estimado do mês (soma o custo de roteiro registrado em
cada projeto — some as chamadas de API pagas, então é aproximado).

Abaixo, uma busca e a tabela de projetos (nome / perfil / criado em /
estado). Clicar numa linha leva pra tela certa conforme o estado do
projeto — revisão de roteiro, tela de status, ou conclusão.

**Estados que aparecem como badge:**

| Badge | Significado |
|---|---|
| `pendente` | acabou de ser criado |
| `em_andamento` | alguma etapa automática está rodando |
| `aguardando_revisao` | roteiro pronto, esperando você revisar/aprovar |
| `aguardando_audio` | você escolheu "decidir depois" na origem do áudio |
| `aguardando_geracao_clipes` | esperando a Etapa 5 |
| `aguardando_reorganizacao` | clipes prontos, esperando você reorganizar manualmente (se ativou essa opção na criação) |
| `aguardando_legendas` | esperando a Etapa 6 |
| `aguardando_thumbnail` | vídeo final pronto, esperando você escolher a thumbnail (Etapa 7) |
| `concluido` | vídeo final pronto |
| `erro` | alguma etapa falhou — abra o projeto pra ver o detalhe do erro |

## Novo projeto (`/novo`)

[SCREENSHOT: formulário completo de novo projeto]

Campos sempre visíveis:

- **Tipo de conteúdo** (perfil, obrigatório) — dita tom, fontes
  preferidas e regras jurídicas do roteiro. Ícone "?" mostra a
  descrição de cada perfil.
- **Nome do projeto** (obrigatório) — só letras, números, hífen e
  underscore, sem espaço nem acento.
- **Tipo de projeto** (radio):
  - **Pipeline completa** (padrão) — o caminho normal, descrito abaixo.
  - **Vídeos pré-gerados** — pula direto pra montagem. Você sobe os
    arquivos de vídeo já prontos (numerados no nome do arquivo pra
    definir a ordem, ex: `1_wide_shot.mp4`, `2_close_up.mp4`,
    extensão `.mp4`/`.mov`/`.webm`, até 2GB no total), opcionalmente
    com uma legenda `.srt` já pronta pra queimar. Útil quando os clipes
    vêm de outra ferramenta (ex: cenas geradas no DarkPlanner Flow/Veo3,
    já com áudio embutido) — por isso este caminho nunca adiciona
    música de fundo por cima.

### Dentro de "Pipeline completa"

- **Origem do roteiro** (radio):
  - **Gerar via IA** (padrão) — Etapas 2 e 3 rodam normalmente.
  - **Já tenho um roteiro pronto** — sobe um arquivo `.txt`/`.md`
    (mínimo 100 caracteres). As Etapas 2 (transcrição) e 3 (geração via
    IA) **nunca rodam** pra este projeto — economiza o custo da Etapa 3
    por completo. Os links colados abaixo viram só fonte visual (b-roll),
    nunca são transcritos.
- **Modo de fontes** (radio, só aparece se a origem do roteiro for "IA"):
  - **Unificado** (padrão) — uma lista de links, cada um servindo tanto
    de transcrição quanto de b-roll. Cada link tem um dropdown pra
    escolher a posição de uma marca d'água a remover (ou "nenhuma").
  - **Separado** — três blocos distintos: fontes de transcrição (links,
    obrigatório pelo menos 1), fontes visuais por link, e fontes
    visuais por upload direto (imagem ou vídeo, até 500MB por arquivo).
    Útil quando você quer usar uma entrevista só como fonte de fatos
    mas cortar os clipes visuais de outro material.
- **Idioma do projeto** — opcional, sobrescreve o padrão configurado em
  Ajustes só pra este projeto.
- **Legendas queimadas** — checkbox, desligado por padrão. Liga o
  estilo karaokê (palavra atual destacada) queimado direto no vídeo,
  além da legenda embutida padrão (que sempre existe).
- **Vídeo em preto e branco (grayscale)** — checkbox, desligado por
  padrão. Deixa a montagem final mais lenta, porque reprocessa o vídeo
  inteiro.
- **Ajustes avançados** (recolhido por padrão):
  - **Tamanho alvo do roteiro** — presets de 5 a 60 minutos (padrão 25
    min, ~160 palavras/minuto).
  - **Sincronização inteligente com IA** — checkbox, desligado por
    padrão. Depois que os clipes são gerados (Etapa 5), a IA lê o
    roteiro, identifica os momentos-chave e reordena/troca os clipes já
    renderizados pra que o b-roll bata semanticamente com o que está
    sendo narrado (ex: fala "bicicleta", prioriza um clipe que mostra
    bicicleta). **Não gera vídeo novo**, só reorganiza o que já existe.
    Escolha até onde no vídeo aplicar (isso é o trecho que mais importa
    pra retenção): 5 min (~US$0,05), 10 min (~US$0,10, padrão), 15 min
    (~US$0,15), ou vídeo inteiro (~US$0,20+).
  - **Reorganizar clipes manualmente antes da montagem** — checkbox,
    desligado por padrão. Se ligado, o pipeline **pausa** depois da
    Etapa 5 numa tela dedicada (ver abaixo) pra você reordenar os
    clipes na mão antes de seguir pra montagem. Pode ser combinado com
    a sincronização por IA (a IA organiza primeiro, você ajusta depois)
    ou usado sozinho.

### Dentro de "Vídeos pré-gerados"

- **Arquivos de vídeo** (obrigatório, múltiplo) — nomeie começando com
  número pra controlar a ordem final (`1_...`, `2_...`).
- **Adicionar legenda queimada (SRT)** — checkbox; se marcado, sobe um
  arquivo `.srt` já pronto.

## Revisão do roteiro (`/projetos/<id>/revisar_roteiro`)

[SCREENSHOT: tela de revisão com editor, notas de rodapé e bloco de origem do áudio]

- Cabeçalho mostra o perfil do projeto e o custo real do roteiro gerado
  (ou "importado por upload" se você usou esse caminho).
- Editor com abas "Editar" e "Preview". No preview, as notas de rodapé
  viram elementos clicáveis:
  - **① Fonte** (`[F1@04:32]`) — abre um mini-player e toca o trecho
    exato do vídeo-fonte.
  - **② Externa** (`[N: url]`) — abre uma janela com a referência (não
    uma aba nova).
  - **⚠ Aviso** (`[⚠ single-source]` / `[⚠ conflict]`) — mostra o motivo
    do alerta ao passar o mouse.
  - Botão "Ignorar todas as notas" limpa a visualização. Toda marcação
    é removida automaticamente antes de virar áudio — não afeta a
    narração final.
- **Título**: 3 sugestões + opção de digitar o seu.
- **Origem do áudio da narração** (radio):
  - **Gerar automaticamente** — dropdown de provedor (só aparecem
    habilitados os que têm chave configurada em Ajustes) e de voz. Ver
    [CHAVES_API.md](CHAVES_API.md) pra saber quais provedores realmente
    funcionam hoje.
  - **Vou fornecer o áudio** — upload MP3/WAV/M4A/OGG, até 100MB.
  - **Decidir depois** — pausa o projeto (badge `aguardando_audio` na
    home); volte quando tiver decidido.
- **Música de fundo** — checkbox + upload de uma ou mais faixas (mp3/wav/m4a).
  Toca em loop sequencial por baixo da narração, com volume reduzido
  automaticamente durante a fala (ducking).
- **"Refazer roteiro com instruções"** — abre um campo de texto livre
  pra descrever o que você quer diferente, e roda a Etapa 3 inteira de
  novo (custo de API repetido, não é uma edição gratuita). Não aparece
  se o roteiro veio de upload.
- **"Cancelar projeto"** — apaga a pasta inteira do projeto. Não pode
  ser desfeito.

## Reorganizar clipes (`/projetos/<id>/reorganizar_clipes`)

Só acessível quando o projeto está no estado `aguardando_reorganizacao`
(ativado como opção avançada na criação do projeto — ver acima).

[SCREENSHOT: tela de reorganização com a timeline de clipes e o banco de miniaturas]

Mostra a timeline atual dos clipes (com miniatura de cada um) e um
"banco" com todos os clipes disponíveis. Arraste pra reordenar — a
duração de cada posição na timeline fica fixa (não muda ao trocar qual
clipe ocupa aquela posição), então a sincronia com a narração nunca
desalinha. Tem um player de narração e uma prévia do vídeo (sem
legenda/música ainda) pra conferir o resultado antes de seguir pra
montagem.

## Thumbnail (`/projetos/<id>/thumbnail`)

Só acessível quando o projeto está no estado `aguardando_thumbnail`
(automático depois da Etapa 6 — montagem — terminar).

[SCREENSHOT: tela de thumbnail com o grid de candidatos e os 4 templates]

Mostra um grid de candidatos com rosto (detectados automaticamente nos
clipes) e de cenário, campos de texto pra headline/palavra de destaque/
secundário (pré-preenchidos por IA se `ANTHROPIC_API_KEY` estiver
configurada), e um botão pra subir uma foto própria do sujeito. Depois
de escolher/confirmar, renderiza 4 templates lado a lado — escolher um
deles salva a thumbnail final e conclui o projeto.

## Concluído (`/projetos/<id>/concluido`)

[SCREENSHOT: tela de conclusão com preview e botões de ação]

- Preview do vídeo final embutido
- Botão "Baixar vídeo final"
- Botão "Abrir pasta do projeto" (abre o Explorer direto na pasta —
  funciona só no Windows)
- Título escolhido, como cabeçalho da página

## Ajustes (`/ajustes`)

[SCREENSHOT: ajustes com o bloco de ambiente detectado no topo]

No topo, o bloco **"Ambiente detectado"**: card verde com GPU, VRAM,
driver, CUDA e modelos de Whisper suportados/recomendado, ou card
vermelho explicando o motivo se algo não bater com o mínimo exigido.

O formulário é dividido em seções recolhíveis:

- **Geral** — pasta de projetos, chave do YouTube (opcional), idioma
  padrão do roteiro, modelo do Whisper (a lista já vem filtrada pela
  VRAM da sua GPU — nunca oferece um modelo maior do que ela aguenta).
- **Anthropic** — chave, modelo do Claude, limite de buscas web por
  roteiro, cotação USD→BRL usada nas estimativas de custo.
- **TTS (narração)** — provedor e voz padrão, e uma chave por provedor
  (Google, DarkPlanner, ElevenLabs, OpenAI, Azure — ver
  [CHAVES_API.md](CHAVES_API.md) pra saber quais funcionam de verdade).
  Botão pra regerar os previews de voz.
- **Corte e montagem** — liga/desliga o Ken Burns, duração mínima/máxima
  de cada clipe.
- **Legendas** — fonte, tamanho, posição, karaokê (destaque de palavra
  ativa) e cor de destaque. Cor branca com contorno preto é fixa no
  código, não editável (garante legibilidade sobre qualquer fundo).
- **Música de fundo** — volume base (antes do ducking automático).

Salvar grava tudo no `.env` — **é preciso reiniciar o servidor** pra
algumas mudanças valerem (a própria tela avisa).

## Sobre (`/sobre`)

[SCREENSHOT: tela sobre com os perfis de conteúdo listados]

Lista cada perfil de conteúdo disponível (nome, descrição, custo
estimado por vídeo), créditos ao projeto `yt_automation` pelas
abordagens técnicas específicas reaproveitadas (ver `CLAUDE.md` seção
2), versão atual (lida de `VERSION.txt`), um modal com a licença, e um
aviso de privacidade. Também lembra que `iniciar.bat --instalar-deps`
pode pedir permissão de administrador (UAC) — normal e seguro.

## Avisos no topo de todas as telas

- **Banner amarelo, dispensável** — alguma dependência crítica
  (`yt-dlp`) está com mais de 90 dias desde o último release. Some ao
  clicar em "dispensar", mas volta na próxima sessão se continuar
  desatualizada. Resolve com `iniciar.bat --instalar-deps`.
- **Banner vermelho, `ffmpeg` ausente** — não dá pra dispensar; sem
  `ffmpeg` no PATH, quase nada funciona. Resolve com
  `iniciar.bat --instalar-deps`.
- **Banner vermelho, ambiente incompatível** — GPU ausente, VRAM baixa
  demais, ou driver com CUDA desatualizado. Não dá pra dispensar. Ver
  [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
