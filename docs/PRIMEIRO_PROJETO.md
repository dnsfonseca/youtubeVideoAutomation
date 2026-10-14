# Seu primeiro projeto

Tutorial ponta a ponta do caminho mais simples: baixar vídeos-fonte do
YouTube, deixar a IA escrever o roteiro, e chegar num MP4 pronto pra
upload. Pra outros caminhos (upload de roteiro pronto, vídeos já
prontos, sincronização por IA, reorganização manual), ver
[FLUXO_APLICACAO.md](FLUXO_APLICACAO.md).

Duração estimada: 20-40 minutos, a maior parte esperando o pipeline
rodar sozinho.

## Antes de começar

- Ferramenta instalada e rodando ([INSTALACAO.md](INSTALACAO.md))
- `ANTHROPIC_API_KEY` configurada
- Pelo menos uma chave de TTS configurada (Google TTS ou DarkPlanner) —
  **ou** esteja preparado pra gravar/fornecer seu próprio áudio depois
- 1-3 links de vídeos do YouTube sobre o mesmo tema, que vão servir de
  fonte (transcrição + b-roll)

## Passo 1 — Criar o projeto

1. Abra http://localhost:5000
2. Clique em "Novo projeto"

[SCREENSHOT: home com o botão "Novo projeto" em destaque]

3. Preencha:
   - **Tipo de conteúdo** — o perfil que molda tom e regras do roteiro
     (True Crime, Atualidades Narrativas, História). Clique no ícone "?"
     ao lado pra ver a descrição de cada um.
   - **Nome do projeto** — identificador único, só letras, números,
     hífen e underscore, sem espaço nem acento (ex: `caso_fulano_2026`).
   - **Tipo de projeto** — deixe em "Pipeline completa" (padrão). A
     opção "Vídeos pré-gerados" é pra quando você já tem os clipes
     finais prontos de outra ferramenta — ver
     [FLUXO_APLICACAO.md](FLUXO_APLICACAO.md).
   - **Origem do roteiro** — deixe em "Gerar via IA" (padrão).
   - **Modo de fontes** — deixe em "Unificado" (padrão): uma lista só
     de links, cada um servindo tanto de transcrição quanto de b-roll.
   - **Links dos vídeos-fonte** — cole um por linha. Se algum vídeo tem
     marca d'água/logo que você quer remover dos clipes, escolha a
     posição no dropdown ao lado do link (canto, banner inferior etc).
     Marcas centrais grandes (Getty, Shutterstock) não são removíveis —
     evite fonte com esse tipo de marca.

[SCREENSHOT: formulário de novo projeto preenchido, com dois links colados]

4. Deixe os "Ajustes avançados" fechados por enquanto (tamanho do
   roteiro, sincronização por IA, reorganização manual — ver
   [FLUXO_APLICACAO.md](FLUXO_APLICACAO.md) quando quiser explorar).
5. Clique em "Criar projeto".

## Passo 2 — Download e transcrição (automático)

O sistema baixa cada vídeo-fonte e transcreve na sua GPU, sem precisar
fazer nada.

- Download: 1-5 min por vídeo, depende do tamanho
- Transcrição: 1-3 min por vídeo com uma GPU de referência (RTX 3070 Ti)

[SCREENSHOT: tela de status com a barra de etapas mostrando 1 e 2 em andamento]

## Passo 3 — Roteiro gerado, hora de revisar

Quando a Etapa 3 termina, você cai automaticamente na tela de revisão.

[SCREENSHOT: tela de revisão do roteiro, com o editor e as notas de rodapé]

O que fazer aqui:

1. **Leia o roteiro.** As notas de rodapé (`[F1@04:32]`, `[N: url]`,
   `[⚠ aviso]`) são clicáveis — clique numa nota de fonte pra tocar o
   trecho exato do vídeo-fonte que embasou aquela frase, ou numa nota
   externa pra ver a referência. Isso é a proteção contra erro factual
   do modelo — vale a pena checar pelo menos os avisos `⚠`.
2. **Edite se precisar**, direto no editor de texto.
3. **Escolha um título** entre as 3 sugestões, ou digite o seu.
4. **Escolha a origem do áudio da narração:**
   - **Gerar automaticamente** — escolha o provedor (só aparecem
     habilitados os que têm chave configurada) e a voz. Use **Google**
     ou **DarkPlanner** — são os únicos que realmente geram áudio nesta
     versão (ver [CHAVES_API.md](CHAVES_API.md)).
   - **Vou fornecer o áudio** — suba um MP3/WAV/M4A/OGG seu (até 100MB).
   - **Decidir depois** — pausa o projeto aqui; você volta mais tarde
     pela home (o projeto aparece com um badge indicando que está
     esperando a definição do áudio).
5. Opcionalmente, ative **música de fundo** nesta mesma tela (upload de
   uma ou mais faixas — toca em loop por baixo da narração, com volume
   reduzido automaticamente durante a fala).

Se o roteiro precisar de ajuste maior que uma edição manual, use
"Refazer roteiro com instruções" — descreva o que quer diferente e o
sistema roda a Etapa 3 de novo do zero (isso **gasta a mesma API de
novo**, não é gratuito).

Clique em "Aprovar" quando estiver satisfeito.

## Passo 4 — Áudio, clipes e montagem (automático)

Depois de aprovar, o pipeline continua sozinho:

1. **Narração** é gerada (ou seu áudio enviado é processado)
2. **Clipes visuais** são cortados dos vídeos-fonte — trechos
   aleatórios com Ken Burns e remoção de marca d'água aplicados,
   respeitando margens de segurança no início/fim de cada fonte pra não
   cair em intro/patrocínio. Zero custo de API aqui, só ffmpeg local
   (~2-5 min com GPU).
3. **Montagem final** — concatena os clipes, adiciona a narração, gera
   as legendas (sempre embutidas como softsub; queimadas no vídeo só se
   você marcou essa opção na criação do projeto), e adiciona música de
   fundo se configurada.

[SCREENSHOT: tela de status mostrando as etapas 5 e 6 progredindo]

## Passo 5 — Escolher a thumbnail

Assim que a montagem termina, o sistema já escaneia os clipes em busca
de rostos e cenários pra sugerir uma thumbnail — o projeto pausa em
`aguardando_thumbnail` e você cai na tela de thumbnail automaticamente.

[SCREENSHOT: tela de thumbnail com o grid de candidatos e os 4 templates]

1. Escolha um candidato com rosto no grid (ou suba sua própria foto).
2. Ajuste os textos sugeridos (headline, palavra de destaque) se
   quiser — eles já vêm pré-preenchidos pela IA se você tem
   `ANTHROPIC_API_KEY` configurada.
3. Clique em "Renderizar" pra ver os 4 templates prontos lado a lado.
4. Clique no template que preferir — isso salva a thumbnail final e
   conclui o projeto.

Sem `ANTHROPIC_API_KEY` configurada, os textos não vêm pré-preenchidos
e o candidato com rosto não é identificado automaticamente, mas o
vídeo já está pronto do mesmo jeito — você escolhe tudo manualmente
nesta tela.

## Passo 6 — Baixar o vídeo final

[SCREENSHOT: tela de conclusão com preview embutido e botão de download]

Na tela final você tem:

- Preview do vídeo embutido no navegador
- Botão **"Baixar vídeo final"**
- Botão **"Abrir pasta do projeto"** (abre o Explorer direto na pasta)
- O título escolhido, pra copiar pro YouTube

Duração típica do vídeo final: 15-30 minutos, ~500MB-1.5GB.

## Quanto custou

Pra um roteiro de ~25 minutos, com Google TTS e sem sincronização por
IA: **~R$5,50-6,50** no total, mais ~R$0,25-0,50 da geração de
thumbnail (Etapa 7, se `ANTHROPIC_API_KEY` estiver configurada). Ver
[CUSTOS.md](CUSTOS.md) pro detalhamento completo (inclusive o que muda
usando DarkPlanner, upload de áudio próprio, ou sincronização por IA).
