# Broll Foundry

*Atualizado após Sessão 18 (31/08/2026) — ver `HISTORICO_BUGS.md` pro
histórico completo de sessões e `prompt_abertura.md` pro roteiro de
sessões futuras.*

Documento de referência do projeto. O Codex lê este arquivo em toda
sessão nova; ele é a fonte da verdade sobre arquitetura, convenções e
decisões já tomadas. Não repetir informação viva daqui em prompts de
sessão; referenciar por seção quando necessário.

## 1. Contexto e propósito

Servidor Flask local (roda no Windows do usuário, nunca na nuvem) que
automatiza a produção de vídeos "faceless" de true crime pra publicação
no YouTube. O usuário cola links de vídeos-fonte, revisa o roteiro
gerado pela IA, e recebe um MP4 pronto pra upload — com narração
sintetizada, legendas queimadas, e b-roll cortado sob a narração.

Este é a evolução do projeto originalmente chamado `broll_alfa`. A
fundação criada lá (Flask + templates + tela de ajustes + tema escuro +
detecção de projetos por marcador) é preservada e serve como base. O
que muda: o pipeline agora vai até o vídeo final entregável, não só até
os clipes cortados.

## 2. Posição do produto vs. alternativas

Existe uma ferramenta similar publicada por um conhecido do usuário
(repositório `yt_automation`, Python + FastAPI + React). Ela faz
download + corte aleatório + Ken Burns + concat + mux. O usuário terá
acesso ao código dela, mas construir Broll Foundry como produto próprio
foi decisão consciente por três razões:

1. Independência técnica (não depender de manutenção alheia)
2. Escopo mais amplo (roteiro, TTS, legendas, curadoria semântica,
   título — coisas que a outra ferramenta não faz)
3. Possibilidade futura de comercialização

**Postura sobre reaproveitamento de código:** Postura 2 (Estudo com
reaproveitamento de trechos técnicos genéricos). O Codex deve
escrever todo o código do zero, mas quando encontrar problemas técnicos
específicos que a `yt_automation` resolveu com soluções que qualquer
engenheiro competente faria igual (comando exato de `ffmpeg` pra Ken
Burns, workaround do shim `.bat` do pyenv-win chamando `yt-dlp` como
`python -m yt_dlp`, regex de parsing de progresso do yt-dlp, filtro
`zoompan` específico), a solução específica pode ser reproduzida
sempre com crédito explícito em comentário no código:

```python
# Approach inspired by yt_automation (Gustavo Xavier, GitHub)
# for the Windows/pyenv-win shim compatibility issue.
```

**NÃO copiar** blocos de código maiores que 5-10 linhas mesmo com
crédito. NÃO reproduzir a arquitetura de módulos dele (FastAPI +
WebSocket + React) — Broll Foundry usa Flask + polling + templates HTML
puros, é escolha técnica diferente e deliberada. NÃO usar os mesmos
nomes de classes/módulos dele (`clip_processor`, `assembler`,
`timeline_builder`) — nomear diferente pra deixar claro que é
implementação separada.

## 3. Escopo do produto

**Dentro:**

- Baixar vídeos-fonte do YouTube via `yt-dlp` a partir de links colados
- Transcrever cada vídeo com `faster-whisper` local em GPU
- Gerar roteiro adaptado no idioma configurado (padrão `en-US`, opções
  `en-GB`, `pt-BR`, `es`, `de`) via API do Codex com busca web e notas
  de rodapé de origem — ver seção 5.3 e 5.4
- **Sistema de perfis por tópico** — o roteiro é moldado pelo perfil
  escolhido no formulário de novo projeto. Três perfis no MVP:
  `truecrime`, `atualidades_narrativas`, `historia`. Cada perfil define
  prompt do sistema específico, fontes preferidas, tom, e configurações
  padrão (uso de Veo3, ativação de regras jurídicas, etc). Ver
  seção 3.1.
- **Explicação dos perfis dentro da aplicação** — o formulário de novo
  projeto tem ícone de info ao lado do dropdown de perfil que abre
  tooltip explicando "pra que serve cada um", "bom pra", tom, e custo
  estimado por vídeo. Tela `/sobre` traz descrição longa de cada
  perfil. Tela de revisão mostra badge do perfil ativo no header.
- Pausar o job pra revisão humana do roteiro em editor web
- Gerar 3 sugestões de título no idioma do roteiro
- Gerar áudio (TTS) via provedor configurável **OU** aceitar upload de
  áudio próprio (gravado pelo usuário) — decisão feita por projeto na
  tela de revisão. Ver seção 5.6.
- Provedores TTS suportados (todos opcionais — usuário configura só os
  que quer usar): Google, DarkPlanner, ElevenLabs, OpenAI, Azure — ver
  seção 5.6 pra quais geram áudio de verdade hoje. Arquitetura
  desacoplada, adicionar provedor novo é módulo separado.
- Cortar clipes dos vídeos-fonte em janelas de 5-10s
- **Remoção de marca d'água opcional por vídeo-fonte** — no formulário
  de novo projeto, cada link tem dropdown com 6 opções de posição
  (nenhuma, 4 cantos, banner inferior). Aplicado via filtro `delogo`
  do ffmpeg durante o corte. Ver seção 5.7.
- **Geração de cenas por IA via Veo3** (Google) — **planejado, ainda não
  implementado.** Não existe nem scaffolding de prompt hoje (removido
  numa sessão de limpeza pós-Sessão 18) nem geração de cena real nem
  chamada à API do Google Veo3 em nenhum lugar do código. Ver seção 5.75
  e `MELHORIAS_PENDENTES.md`.
- ~~Fazer curadoria semântica~~ **removido na Sessão 11** — substituído
  por seleção aleatória de trechos com round-robin de fontes (mais
  barato, mais rápido, sem perda de qualidade percebida). Ver seção 5.7
- Aplicar Ken Burns (zoom lento) em cada clipe
- Gerar legendas queimadas no vídeo com estilo customizado (fonte,
  tamanho, cor, contorno, posição, destaque de palavra ativa)
- Concatenar clipes + mux com narração + burn de legendas
- Exportar MP4 1080p 16:9 pronto pra upload
- Tela de ajustes com todas as configurações persistentes
- Detecção robusta de projetos por marcador (`entrada/links.txt` ou
  `job.json`) — herdado do broll_alfa
- Suíte de testes automatizada obrigatória (ver seção 8)

**Fora do escopo do MVP:**

- Dashboard de tendências (Google Trends + YouTube trending + Reddit)
  → fica pra v2
- Análise de performance de vídeos publicados via YouTube Analytics API
  → v2
- Versão vertical 9:16 pra YouTube Shorts → v2
- Thumbnail (decisão anterior mantida: editor cria manualmente no Canva)
- Publicação automática no YouTube (upload manual pelo usuário)
- Interface multilíngue (a UI fica em português; só o conteúdo
  produzido muda de idioma)

## 3.1 Sistema de perfis — desenho técnico

Um perfil é um diretório em `scripts/prompts/perfis/<nome>/` contendo:

```
scripts/prompts/perfis/truecrime/
  config.py                  # dict Python com metadados e defaults
  sistema.md                 # prompt do sistema pra este perfil (com placeholders)
  fontes_preferidas.py       # dict {idioma: [lista de veículos]}
  juridico_en_us.md          # bloco jurídico injetado no prompt
  juridico_en_gb.md
  juridico_pt_br.md
  juridico_es.md
  juridico_de.md
  descricao_curta.txt        # 1 linha, aparece na tela de novo projeto
  descricao_longa.md         # markdown, aparece no /sobre
```

**Nota (sessão de limpeza pós-Sessão 18):** o scaffolding de prompt do
Veo3 que existia aqui (`veo3_estilo.md`, `veo3_linguagem_segura.md` por
perfil, campo `usa_veo3_padrao` em `config.py`, parâmetro `opcoes_veo3`
no loader) foi removido — não tinha geração de cena real por trás e
ficou sem manutenção. Ver seção 5.75 e `MELHORIAS_PENDENTES.md`
("Integração Veo3 pra geração de b-roll adicional") para o estado atual
e o que uma implementação futura precisaria construir do zero.

**`config.py` de cada perfil contém no mínimo:**

```python
CONFIG = {
    "nome_exibicao": "True Crime",
    "descricao_uma_linha": "Casos criminais reais com rigor factual",
    "usa_juridico": True,             # ativa bloco juridico_<idioma>.md
    "tom_padrao": "investigativo",     # meta pro prompt
    "exige_notas_rodape": True,        # todos exigem no MVP
    "cuidado_temporal": False,         # ver perfis atualidades e historia
    "custo_estimado_por_video_usd": (3, 15),  # (mínimo, máximo típico)
}
```

**Loader dinâmico** em `scripts/prompts/loader.py` recebe (perfil,
idioma) e monta o prompt final lendo `sistema.md` do perfil e
injetando placeholders com o bloco jurídico (se ativado), as fontes
preferidas, o idioma, etc.

**Perfis no MVP:**

- **`truecrime`** — casos criminais reais. Tom investigativo, regras
  jurídicas por idioma, fontes jornalísticas, revisão factual crítica.
- **`atualidades_narrativas`** — notícias e eventos com narrativa
  envolvente ancorada em fatos verificados. Tom sério e envolvente,
  sem tabloidismo (ver 3.2).
- **`historia`** — histórias históricas e filosofia contextualizada
  historicamente (Segunda Guerra, história antiga, história das
  ideias). Fontes acadêmicas e museológicas. Tom narrativo imersivo.

**Testes:** cada perfil obriga ter todos os arquivos requeridos.
Faltar um levanta erro claro na inicialização do servidor, não no meio
do pipeline.

**Adicionar perfil novo pós-MVP:** só criar novo diretório em
`scripts/prompts/perfis/<novo_nome>/` com os arquivos obrigatórios.
Nenhum código do pipeline precisa mudar.

## 3.2 Cuidado editorial sobre o perfil `atualidades_narrativas`

O nicho de notícias com narrativa dramática opera numa faixa perigosa.
Este perfil foi desenhado deliberadamente pra evitar deriva pra
tabloidismo puro, pelos seguintes motivos concretos:

- **Sensacionalismo vira desinformação com facilidade.** O Codex, com
  prompt pedindo "tom dramático", eventualmente distorce fatos
  ("milhares" quando foram "centenas", "governo esconde" quando é
  "governo não comentou ainda"). O prompt do perfil proíbe esse tipo
  de intensificação.
- **YouTube pune tabloidismo em revisão de monetização.** Community
  Guidelines endureceu contra "misleading metadata" e "sensationalized
  content". Perfil desenhado pra performar bem sem entrar nessa faixa.
- **Peso ético de monetizar drama de vítimas reais** (desastres,
  atentados, crimes coletivos). Perfil respeita gravidade dos temas.

**O prompt do sistema deste perfil proíbe:**

- Palavras "chocante", "revelador", "verdade oculta", "ninguém está
  contando" e correlatos
- Ganchos de urgência sem base factual
- Intensificação de números
- Especulação apresentada como fato

**E incentiva:**

- Abertura com gancho narrativo forte (fato mais impactante do caso,
  apresentado sem exagero)
- Ritmo de storytelling (tensão, virada, resolução)
- Tom sério e grave quando o tema pede
- Contexto histórico e humano dos envolvidos

**Se um futuro usuário quiser um perfil tabloide puro** (Sabor 3 sem
freios), isso seria perfil separado (`noticias_dramaticas`) com aviso
ainda mais forte no AGENTS.md sobre riscos. Não implementar sem
discussão explícita.

## 4. Arquitetura de alto nível

```
Navegador do usuário (LAN)
        │
        │ HTTP porta 5000
        ▼
  server.py (Flask)
        │
        │ subprocess (uma etapa = um script autocontido)
        ▼
  scripts/*.py  ────►  faster-whisper (GPU local)
        │       ────►  yt-dlp (via python -m yt_dlp)
        │       ────►  ffmpeg (CLI)
        │       ────►  API do Codex (HTTPS)
        │       ────►  API do TTS (HTTPS, provedor configurável)
        │       ────►  YouTube Data API v3 (opcional)
        │       ────►  Google Veo3 API (opcional, decidido por projeto)
        ▼
  {PROJETOS_DIR}/{nome_projeto}/
```

Uma pasta por projeto, dentro do diretório-raiz configurável.
Comunicação script → servidor por stdout com convenção
`@PROGRESSO {json}` (padrão herdado do broll_alfa).

Estado de job em memória; jobs em andamento se perdem se o servidor
reiniciar (aceitável pro alfa). Listagem de projetos no disco por
detecção de marcador, não por estado de job.

## 5. Pipeline: as etapas

Cada etapa é um script autocontido em `scripts/`, executado pelo
`server.py` via `subprocess`.

### 5.1 — `1_baixar_videos.py`

Entrada: `entrada/links.txt` (um link por linha).
Saída: `fontes/fonteNN.mp4` + `fontes/manifest_fontes.json` (URL
original, título no YouTube, duração, id do arquivo local).

Usa `yt-dlp` chamado como `python -m yt_dlp` (workaround do shim `.bat`
do pyenv-win — abordagem inspirada em `yt_automation`, dar crédito no
código). Formato preferencial:
`bestvideo[height<=1080]+bestaudio/best[height<=1080]/best`.

Emite `@PROGRESSO` por vídeo baixado, com ETA calculado pelo output
do yt-dlp parseado.

### 5.2 — `2_transcrever.py`

Entrada: `fontes/*.mp4` + `fontes/manifest_fontes.json`.
Saída: `transcricoes/fonteNN.json` — cada uma com segmentos e timestamps
por palavra:

```json
{
  "arquivo": "fonte01.mp4",
  "duracao_s": 1247.3,
  "idioma": "en",
  "segmentos": [
    {
      "start": 0.0,
      "end": 4.2,
      "text": "Tonight we're going to talk about...",
      "palavras": [
        {"start": 0.0, "end": 0.3, "word": "Tonight"}
      ]
    }
  ]
}
```

`faster-whisper` (biblioteca `faster-whisper`, não `whisper` original),
modelo default `medium` configurável, `device="cuda"`,
`compute_type="float16"`. Emite `@PROGRESSO` a cada segmento.

**Implementado na Sessão 4** como `scripts/2_transcrever.py`. Requer
CUDA 12+ (mínimo oficial — seção 13; CUDA 11 não é mais suportado, ao
contrário do que uma versão anterior desta seção previa). Timeout duro
de 60 minutos por vídeo. Ver seção 18.9 para o comportamento de detecção
de ambiente e categorização de erro.

Idioma detectado automaticamente por vídeo — não forçar tradução na
transcrição (perde precisão). Roteiro (etapa 3) fica no idioma alvo
independente do idioma da transcrição.

### 5.3 — `3_gerar_roteiro.py`

Entrada: `transcricoes/*.json` + `fontes/manifest_fontes.json`.
Saída: `roteiro.md` + `titulos_sugeridos.json` +
`job_metadata.json` (estimativa de tempo/quantidade das próximas
etapas, pra tela de revisão).

Chama API do Codex (`Codex-sonnet-5` padrão, configurável) com:
- Todas as transcrições dos vídeos-fonte como contexto principal
- Ferramenta server-side `web_search_20250305` habilitada (custo à
  parte: $10 por 1000 buscas, tokens normais adicionais) — resolvida
  automaticamente pela Anthropic dentro da mesma resposta, sem loop
  manual
- Ferramenta `youtube_top_titles` (client-side, `scripts/tools/youtube.py`
  — chama YouTube Data API v3 de verdade, se `YOUTUBE_API_KEY`
  configurada — filtro `relevanceLanguage` conforme idioma alvo)
- Prompt do sistema montado por `scripts/prompts/loader.montar_prompt(perfil, idioma)`
  (AGENTS.md seção 3.1 — não um arquivo fixo `roteiro.md`; o bloco
  jurídico e as fontes preferidas já vêm injetados pelo loader
  conforme o perfil ativo do projeto)

Formato de saída forçado com `tool_choice` estruturado, numa segunda
chamada à API após uma fase de pesquisa (a fase 1 deixa o modelo usar
`web_search`/`youtube_top_titles` livremente; a fase 2 força a saída
via `tool_choice={"type": "tool", "name": "entregar_roteiro"}`).

Após esta etapa, job pausa em `aguardando_revisao` (`etapa_atual`
grava `"revisao"` no `job.json`). A tela de revisão completa (edição
do roteiro, escolha de título, origem do áudio — seção 5.5) é a
Sessão 7; por enquanto `/projetos/{id}/revisar_roteiro` é um stub que
só mostra o roteiro bruto gerado.

**Implementado na Sessão 6** como `scripts/3_gerar_roteiro.py` +
`scripts/tools/youtube.py`. Exigiu subir o pin de `anthropic` no
`requirements.txt` de `0.40.0` para `0.69.0` — a versão anterior é de
antes da tool `web_search_20250305` e do campo
`Usage.server_tool_use` existirem no SDK. `server.py` encadeia
automaticamente transcrição → roteiro (mesmo padrão de download →
transcrição da Sessão 4) e expõe `POST /projetos/{id}/gerar_roteiro`
para retry manual.

### 5.4 — Regras não-negociáveis do prompt de roteiro

O prompt em `scripts/prompts/roteiro.md` é editável, mas as regras
abaixo são fixas e testáveis:

1. Roteiro **original em estrutura** — não colar frases nem seguir
   estrutura de nenhum dos vídeos-fonte nem de nenhuma notícia
2. Roteiro escrito **integralmente no idioma alvo** independente do
   idioma dos vídeos-fonte
3. Toda afirmação factual (nome, data, número, cargo, sentença,
   parentesco, sequência de eventos) sai com nota de rodapé:
   `[F1@04:32]` (vídeo-fonte 1, minuto 4:32) ou `[N: cnn.com/…]`
4. Afirmação em apenas UMA fonte → marca `[⚠ single-source]`
5. Contradição entre fontes → descrever a divergência, não escolher;
   marcar `[⚠ conflict]`
6. Nunca inventar detalhe. Falta contexto → texto mais curto, não
   mais completo
7. **Distinções jurídicas por idioma** (tabela injetada dinamicamente
   conforme `IDIOMA_ROTEIRO`):
   - **en-US:** `suspect` ≠ `person of interest` ≠ `arrested` ≠
     `charged` ≠ `indicted` ≠ `defendant` ≠ `convicted`
   - **en-GB:** `suspect` ≠ `arrested` ≠ `charged` ≠ `defendant` ≠
     `convicted` ≠ `sentenced`
   - **pt-BR:** `suspeito` ≠ `investigado` ≠ `indiciado` ≠
     `denunciado` ≠ `réu` ≠ `condenado`
   - **es:** `sospechoso` ≠ `investigado` ≠ `imputado` ≠ `procesado` ≠
     `acusado` ≠ `condenado`
   - **de:** `Verdächtiger` ≠ `Beschuldigter` ≠ `Angeschuldigter` ≠
     `Angeklagter` ≠ `Verurteilter`
8. 3 sugestões de título variando ângulo (factual, emocional, pergunta),
   idioma alvo, sem mentir sobre conteúdo

### 5.5 — Tela de revisão (implementada no server.py, não script)

Rota `/projetos/{id}/revisar_roteiro` mostra:

- Editor de texto com o `roteiro.md` (edição livre)
- 3 sugestões de título como radio buttons + campo pra digitar próprio
- Notas de rodapé de origem renderizadas como links clicáveis:
  - `[F1@04:32]` → mini-player toca trecho do vídeo-fonte 1 em 4:32
  - `[N: url]` → abre modal com a referência
  - `[⚠ ...]` → destaque visual amarelo
- **Bloco "Origem do áudio da narração"** com três opções em radio:
  - **"Gerar automaticamente"** (padrão se pelo menos uma chave TTS
    configurada; oculto se nenhuma chave TTS configurada)
    - Sub-dropdown: provedor (Google / DarkPlanner / ElevenLabs / OpenAI /
      Azure — só os configurados aparecem habilitados; outros aparecem
      cinza com tooltip "configurar chave em Ajustes")
    - Sub-dropdown: voz (opções dinâmicas conforme provedor escolhido)
  - **"Vou fornecer o áudio"** — upload de arquivo MP3/WAV/M4A/OGG
  - **"Decidir depois"** — pausa o projeto após aprovar roteiro
- Botão "Aprovar" (texto muda conforme escolhas: menciona "gerar
  áudio", "usar áudio enviado" ou "pausar")
- Botão "Refazer roteiro com instruções"
- Botão "Cancelar projeto"

Ação do "Aprovar" grava `roteiro_aprovado.md`, `titulo.txt`,
`origem_audio.json` (com o que foi escolhido), e dispara etapa 4 (ou
para no estado `AGUARDANDO_AUDIO` se opção foi "decidir depois").

### 5.6 — `4_obter_audio.py` (TTS ou upload)

Entrada: `roteiro_aprovado.md` + configuração da tela de revisão
gravada em `origem_audio.json` (indica se é `tts` ou `upload`).
Saída: `narracao.mp3` + `narracao_alinhamento.json` (timestamps por
palavra pra alinhamento de legenda depois) + `origem_audio.json`
preservado (etapas seguintes consultam pra saber a origem).

**Três caminhos possíveis, decididos na tela de revisão:**

**Caminho A — Gerar via TTS:**
Arquitetura desacoplada: `scripts/tts/` com um módulo por provedor
implementando interface comum (`sintetizar`/`validar_configuracao`),
registrados em `scripts/tts/__init__.py:get_provedor(nome)`.

**Estado real da implementação (pós-Sessão 8):**
- `tts/google.py` — **implementado e é o provedor padrão/principal.**
  Não retorna alinhamento por palavra nativo, então `4_obter_audio.py`
  roda `faster-whisper` em cima do áudio gerado pra produzir o
  alinhamento (mesma lógica de DLL CUDA da Etapa 2, extraída pra
  `scripts/whisper_setup.py` compartilhado)
- `tts/darkplanner.py` — **implementado** (Sessão 26): vozes ElevenLabs
  via revenda/plano PRO já pago do usuário (app.darkplanner.com.br), API
  assíncrona (job com polling). Se o provedor retornar alinhamento por
  palavra nativo, `4_obter_audio.py` usa direto; senão cai no mesmo
  caminho do Whisper local que o Google usa
- `tts/elevenlabs.py`, `tts/openai.py`, `tts/azure.py` — **stubs**:
  interface implementada (`sintetizar`/`validar_configuracao` existem e
  são chamáveis), mas a chamada de API real não foi construída ainda.
  Escolher um destes na tela de revisão levanta erro claro indicando que
  o provedor ainda não está disponível

Escolha via dropdown na tela de revisão (não no `.env` — decisão por
projeto). O dropdown mostra só provedores com chave configurada; os
outros aparecem desabilitados com tooltip "configurar chave em Ajustes".
Completar ElevenLabs/OpenAI/Azure é trabalho futuro, não bloqueia o
MVP porque Google TTS e DarkPlanner cobrem o caminho principal.

**Caminho B — Upload de áudio próprio:**
Usuário grava por fora (voz própria no microfone, outra ferramenta de
TTS, editor de áudio) e sobe MP3/WAV/M4A/OGG pela tela de revisão.
Validação: formato válido, duração razoável (não pode ser 3 segundos
nem 3 horas), não corrompido. Roda `faster-whisper` em cima do áudio
pra extrair alinhamento e transcrição forçada. Isso último importa:
ver seção 5.8 sobre legenda.

**Caminho C — Pausar sem definir origem:**
Job entra em estado `AGUARDANDO_AUDIO` e para. Usuário pode voltar
depois pela home (o projeto aparece com badge "aguardando áudio") e
escolher A ou B então. Útil pra separar aprovação do roteiro de
gravação do áudio em momentos diferentes.

Nenhuma chave de TTS é obrigatória globalmente. Se o usuário só usa
upload, não precisa configurar chave nenhuma. Se tenta gerar TTS sem
chave do provedor escolhido, erro claro na tela: "Configure
ELEVENLABS_API_KEY em Ajustes antes de usar este provedor".

### 5.7 — `5_gerar_clipes.py` (Etapa 5 — geração de clipes)

**Histórico da seção (ler antes de mexer nesta etapa):** entre as
Sessões 9 e 11 o projeto passou por duas arquiteturas mais elaboradas
que foram abandonadas — primeiro corte por janela fixa com curadoria
semântica via IA, depois detecção de cena real (`PySceneDetect`) com
análise visual opcional via Codex Vision e deduplicação por pHash
(arquitetura de 3 scripts: `5_dividir_cenas.py` +
`6_montar_timeline.py` + `7_renderizar_clipes.py`). Ambas foram
descartadas por resultado ruim: detecção de cena levava 12+ minutos por
vídeo de 30min rodando em CPU sem ganho de qualidade que compensasse a
complexidade; Vision custou $0.82/vídeo pra descartar só 5 de 82 cenas
analisadas; pHash não agrupa duplicata entre fontes diferentes (stock
footage compartilhado entre canais). Ver `HISTORICO_BUGS.md` (Sessões
9.4, 10-10.4, 11) pra detalhe completo do que foi tentado e por quê não
vingou. A Sessão 11 consolidou tudo num único script que volta pra
seleção aleatória de trechos com round-robin de fontes — abordagem do
projeto `yt_automation` (Gustavo Xavier, GitHub) — com duas proteções
adicionais que o `yt_automation` não tem: margens de segurança no
início/fim de cada fonte (evita intro/outro do canal) e rastreamento de
intervalos já usados por fonte (evita sobreposição/duplicata dentro do
mesmo projeto). **Não reintroduzir detecção de cena/Vision/pHash sem
motivo novo e validado — já foi tentado duas vezes.**

Entrada:
- `fontes/manifest_fontes.json` (Etapa 1) — id/arquivo/duração de cada
  fonte baixada ou enviada por upload com sucesso
- `narracao_alinhamento.json` (Etapa 4) — duração da narração, que a
  seleção de clipes precisa cobrir
- `entrada/marcas_dagua.json` (formulário de Novo projeto, opcional) —
  mapa fonte → posição da marca d'água a remover (ver seção 5.7.1)
- `entrada/fontes_tipo_uso.json` (formulário de Novo projeto, opcional
  — modo de fontes separadas, seção 5.7.2) — mapa fonte →
  `"ambos"`/`"transcricao"`/`"visual"`. Fonte ausente do mapa (ou
  arquivo inteiro ausente) é tratada como `"ambos"`; só `"transcricao"`
  é excluída da seleção de clipes aqui (fonte usada só como texto pra
  narração, nunca aparece visualmente)

Saída:
- `clipes/<clipe_id>.mp4` — um arquivo por clipe gerado, já com Ken
  Burns e delogo aplicados
- `clipes/indice.json` — clipes renderizados com sucesso, na ordem
  final do vídeo (consumido pela Etapa 6)

**Seleção de trechos:** duração alvo de cada clipe sorteada
uniformemente entre `CLIPE_DURACAO_MIN_S`/`CLIPE_DURACAO_MAX_S` (default 6-10s),
percorrendo as fontes em round-robin a partir de um cursor que avança a
cada clipe. Se a fonte do round-robin não tiver janela livre suficiente
(já usada, ou dentro da margem de segurança de início/fim), tenta a
próxima fonte no round-robin inteiro antes de aceitar um fallback
degradado. Não há mais estratégia configurável de corte (`fronteira`/
`aleatória`) nem sorteio de pontos de corte — só esta seleção aleatória
com round-robin.

Ken Burns aplicado via `zoompan` do ffmpeg (abordagem inspirada em
`yt_automation`, dar crédito no código do filtro específico). Encoder
GPU (`h264_nvenc`) detectado automaticamente e usado se disponível,
com fallback pra `libx264 preset veryfast pix_fmt yuv420p` se o ffmpeg
instalado não suportar NVENC ou se o encode com NVENC falhar.

Corte com `-ss` sempre DEPOIS de `-i`, nunca antes com `-c copy`. Emite
`@PROGRESSO`.

### 5.7.1 — Remoção de marca d'água

Muitos vídeos-fonte (canais de notícia, canais de true crime, material
de agência) têm marca d'água — logo do canal, ticker, timestamp — que
aparece nos clipes cortados se nada for feito. Ferramenta oferece
remoção via `delogo` do ffmpeg pra as 5 posições mais comuns.

**Configuração pelo usuário:** no formulário de novo projeto, cada
link colado ganha um dropdown ao lado com 6 opções:
- `nenhuma` (padrão) — não aplica delogo
- `superior_direito` — canto superior direito (mais comum)
- `superior_esquerdo`
- `inferior_direito`
- `inferior_esquerdo`
- `banner_inferior` — faixa horizontal na base (ticker)

Cada escolha vira uma entrada em `entrada/marcas_dagua.json`:

```json
{
  "fonte01": "superior_direito",
  "fonte02": "nenhuma",
  "fonte03": "banner_inferior"
}
```

**Coordenadas por posição** (assumindo vídeo 1920×1080; se resolução
diferente, escalar proporcionalmente antes de aplicar):

- `superior_direito`: `delogo=x=1620:y=30:w=270:h=110`
- `superior_esquerdo`: `delogo=x=30:y=30:w=270:h=110`
- `inferior_direito`: `delogo=x=1620:y=940:w=270:h=110`
- `inferior_esquerdo`: `delogo=x=30:y=940:w=270:h=110`
- `banner_inferior`: `delogo=x=0:y=980:w=1920:h=100`

Estes são pontos de partida — se resultado ficar ruim em algum canal
específico, ajustar as constantes num arquivo `scripts/watermark_regions.py`
que centraliza os valores.

Aplicado pela Etapa 5 (`5_gerar_clipes.py`, seção 5.7) diretamente no
lookup de `entrada/marcas_dagua.json` durante a geração de cada clipe —
não há mais etapa separada de planejamento fazendo esse lookup antes.

**Limitação explícita:** watermarks centrais grandes (Getty,
Shutterstock, "SAMPLE" atravessando o frame) NÃO são removíveis por
esta abordagem. Precisariam de inpainting com IA (outra ordem de
complexidade e custo). O formulário mostra aviso: "Marcas centrais
grandes (Getty, Shutterstock, licenciamento) não podem ser removidas —
use apenas material sem restrição de licença."

**Detecção automática NÃO é escopo do MVP.** Tentar identificar
automaticamente onde está a marca em cada vídeo é análise de vários
frames pra achar região estática, funciona mal em prática, e falso
positivo (borrar cara achando que é logo) é péssimo resultado.
Configuração manual pelo usuário é a solução realista.

### 5.7.2 — Modo de fontes separadas (Sessão 18)

Feature opcional no formulário de Novo projeto: permite tratar fontes
de vídeo de forma assimétrica — uma fonte pode servir só pra narração
(texto/áudio original vira contexto do roteiro, nunca aparece
visualmente), só pra imagem (b-roll puro, nunca transcrita), ou ambos
(comportamento padrão de sempre). Útil quando o usuário quer usar uma
entrevista/podcast só como fonte de fatos mas cortar os clipes visuais
de outro material (arquivo de imagens, b-roll genérico).

**`entrada/fontes_tipo_uso.json`** — mapa `id_da_fonte` →
`"ambos"` | `"transcricao"` | `"visual"`. Fonte ausente do mapa (ou
arquivo inteiro ausente — todo projeto anterior a esta feature) é
tratada como `"ambos"`, preservando o comportamento antigo por completo.
Consultado por:
- `2_transcrever.py` — pula fontes `"visual"` (nunca transcreve b-roll
  puro)
- `5_gerar_clipes.py` — pula fontes `"transcricao"` na seleção de
  clipes (nunca corta vídeo de uma fonte que só serve pra contexto)

**`entrada/fontes_upload.json`** — lista de fontes visuais enviadas
direto pelo usuário no formulário (não baixadas via yt-dlp). O
`server.py` já salva o arquivo em `fontes/fonteNN.<ext>` antes de
`1_baixar_videos.py` rodar; o script só lê esta lista e registra as
entradas no `manifest_fontes.json` com `"origem": "upload"` (vs.
`"origem": "youtube"` pras baixadas normalmente). Fontes de upload
nunca são transcritas automaticamente, mesmo que o mapa de tipo de uso
diga `"ambos"` — não fazem sentido como fonte de narração sem contexto
de onde vieram.

Arquivo ausente em qualquer um dos dois casos = modo unificado de
sempre, retrocompatibilidade total com projetos criados antes da
Sessão 18.

### 5.75 — Enriquecimento por Veo3 (Google) — NÃO IMPLEMENTADO

**Estado real (importante não confundir com o resto do pipeline, que é
tudo implementado e testado):** nada desta feature existe hoje. O
scaffolding de prompt que chegou a existir (bloco `veo3_estilo.md`/
`veo3_linguagem_segura.md` por perfil, checkbox na tela de revisão,
`opcoes_veo3.json`, campo `veo3_sera_oferecido` no `job_metadata.json`)
foi removido numa sessão de limpeza de Ajustes (pós-Sessão 18) por não
ter geração de cena real por trás e ter ficado sem manutenção — ver
`MELHORIAS_PENDENTES.md` ("Integração Veo3 pra geração de b-roll
adicional"). **Não existe geração de cena real nem scaffolding de
prompt: não há `scripts/veo3/`, não há `5b_enriquecer_veo3.py`, não há
chamada à API do Google Veo3 em lugar nenhum do código.**

O desenho abaixo é o que foi planejado e ainda não construído — mantido
aqui como especificação de referência pra quando a implementação
acontecer do zero (não a partir do scaffolding removido), não como
descrição do estado atual:

1. **Análise de gaps.** Chamar API do Codex com a narração alinhada e
   o índice de clipes reais pra identificar os N momentos onde a
   cobertura visual é mais fraca. N = quantidade máxima escolhida pelo
   usuário (3/5/8/12).
2. **Geração de prompts.** Pra cada gap, gerar um prompt de Veo3 com
   linguagem visual característica do perfil ativo e substituições
   aprendidas pra evitar rejeição do Google (a construir — não existe
   mais o `veo3_estilo.md`/`veo3_linguagem_segura.md` que cobria isso).
3. **Cache lookup.** Prompt hasheado (SHA256); cache global em
   `~/broll_foundry_cache/veo3/<hash>.mp4` compartilhado entre
   projetos.
4. **Geração via API do Google Veo3.** Endpoint assíncrono com polling;
   qualidade `veo3-fast` ($0.15/s) ou `veo3` ($0.35-0.75/s).
5. **Tratamento de falha.** Reformular o prompt uma vez se rejeitado;
   se falhar de novo, manter o clipe real já alocado pra esse momento —
   nunca falhar o vídeo inteiro por causa de uma cena Veo3.
6. **Registro final.** Cenas geradas entram em `clipes/indice.json` com
   `origem: veo3`, tratadas como clipes reais dali em diante. Ken Burns
   NÃO se aplica a elas (já têm movimento de câmera embutido).

### 5.8 — `6_montar_video.py` (Etapa 6 — montagem final)

Consolidou o que originalmente seria dividido em legendas + montagem
(seções antigas "7_gerar_legendas.py" e "8_montar_video.py") num único
script: concat dos clipes, mux com a narração, geração de legendas, e
mux de música de fundo opcional — tudo numa etapa.

Entrada: `clipes/*.mp4` + `clipes/indice.json` (Etapa 5) +
`narracao.mp3` + `narracao_alinhamento.json` (Etapa 4) +
`origem_audio.json` + `entrada/musica_fundo/` (opcional, ver abaixo) +
opções de montagem (`legendas_queimadas`/`com_musica_fundo`, default
ambos `false` — softsub sempre, sem música, sem queima).

Saída:
- `saida/video_final.mp4` — 1080p 16:9, H.264 + AAC, clipes
  concatenados + narração (+ música com ducking se ativado)
- `saida/legendas.srt` — sempre gerado, embutido como softsub no MP4
  final
- `saida/legendas.ass` — só gerado se `legendas_queimadas=true`
  (estilo "MrBeast", ver abaixo)
- `saida/montagem_metadata.json` — resumo da montagem (contagem de
  clipes, duração, opções usadas)

**Texto da legenda** segue a mesma regra condicional da Etapa 4:
- Se `origem_audio.origem == "tts"`: usa `roteiro_aprovado.md` (legenda
  perfeita ao roteiro)
- Se `origem_audio.origem == "upload"`: usa a transcrição de
  `narracao_alinhamento.json` (legenda fiel ao que foi realmente
  falado, inclusive desvio do roteiro escrito)

**Legenda queimada estilo "MrBeast"** (Sessão 13, opcional via
`legendas_queimadas=true`): karaoke por palavra — palavra atual
destacada, resto em cor secundária — formato ASS/SSA. Limitação
conhecida: a caixa atrás da palavra destacada é retangular, sem cantos
arredondados (filtro `subtitles` do ffmpeg não suporta — ver
`MELHORIAS_PENDENTES.md`).

**Música de fundo** (opcional, `com_musica_fundo=true`): playlist em
`entrada/musica_fundo/` (uma ou mais faixas, ordem alfabética, repete
em loop sequencial até cobrir a duração da narração) com ducking
automático via `sidechaincompress` — volume da música cai quando há
narração. Formato legado de arquivo único
(`entrada/musica_fundo.{mp3,wav,m4a}`) ainda suportado por
retrocompatibilidade se a pasta não existir.

Emite `@PROGRESSO` calculado do output do ffmpeg (parseando linhas
`frame=NNN time=HH:MM:SS`).

### 5.9 — Tela de conclusão

Rota `/projetos/{id}/concluido` mostra:

- Preview do vídeo final embarcado
- Botão de download
- Link "abrir pasta do projeto no Explorer"
- Título escolhido (facilita copiar pro YouTube)

## 6. Contratos de dados entre etapas

Arquivos vivos por projeto:

```
{PROJETOS_DIR}/{nome_projeto}/
  job.json                    # estado + histórico (inclui perfil ativo)
  entrada/
    links.txt                 # input do usuário (URLs a baixar via yt-dlp)
    marcas_dagua.json         # mapa fonteNN → posição (nenhuma/superior_direito/etc)
    perfil.txt                # perfil escolhido no formulário (obrigatório)
    idioma.txt                # opcional, override do default
    fontes_tipo_uso.json      # opcional (secao 5.7.2) - mapa fonteNN → ambos/transcricao/visual
    fontes_upload.json        # opcional (secao 5.7.2) - fontes visuais enviadas direto
    musica_fundo/             # opcional (secao 5.8) - playlist de faixas pra musica de fundo
  fontes/
    fonte01.mp4
    manifest_fontes.json      # inclui origem: youtube | upload por fonte
  transcricoes/
    fonte01.json
  roteiro.md                  # gerado pela IA
  titulos_sugeridos.json
  job_metadata.json           # estimativas pra tela de revisão
  titulo.txt                  # escolhido pelo humano
  roteiro_aprovado.md         # após edição humana
  origem_audio.json           # tts | upload | pausar
  narracao.mp3
  narracao_alinhamento.json
  clipes/
    <clipe_id>.mp4            # Ken Burns + delogo ja aplicados (Etapa 5, secao 5.7)
    indice.json               # clipes na ordem final do video, consumido pela Etapa 6
  saida/
    video_final.mp4           # 1080p 16:9, H.264 + AAC
    legendas.srt              # sempre gerado (softsub embutido no mp4)
    legendas.ass              # so' se legendas_queimadas=true (estilo MrBeast)
    montagem_metadata.json    # resumo da montagem (Etapa 6)
  logs/
    etapa1_download.log
    ...
```

O `roteiro.md` (gerado pela IA) e o `roteiro_aprovado.md` (versão final
editada pelo humano) são separados. Preservar os dois pra auditoria.

Não existem mais `plano_edicao.json`, `clipes_veo3/`, `montagem/plano.json`,
`legendas/legenda.ass` nem `opcoes_veo3.json` — eram contratos de
arquiteturas de pipeline já abandonadas (ver seção 5.7 pro histórico de
detecção de cena/Veo3 enrichment).

## 7. Configuração — `.env` e tela de ajustes

| Variável | Obrigatória? | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | sim | Chave API Codex |
| `ANTHROPIC_MODEL` | não | Default `Codex-sonnet-5` |
| `IDIOMA_ROTEIRO` | não | Default `en-US`. Opções: `en-US`, `en-GB`, `pt-BR`, `es`, `de` |
| `TTS_PROVEDOR_PADRAO` | não | Default vazio (sem padrão). Se preenchido, pré-seleciona na tela de revisão. Opções: `google`/`darkplanner` (implementados), `elevenlabs`/`openai`/`azure` (stubs, não geram áudio de verdade ainda — seção 5.6) |
| `TTS_VOZ_PADRAO` | não | Voz padrão pré-selecionada na tela de revisão |
| `GOOGLE_TTS_API_KEY` | não | Chave do Google Cloud TTS. Só necessária se o projeto usa TTS (não upload) |
| `DARKPLANNER_API_KEY` | não | Chave da API DarkPlanner (vozes ElevenLabs via revenda/plano PRO já pago) — provedor implementado, seção 5.6 |
| `ELEVENLABS_API_KEY` / `OPENAI_API_KEY` / `AZURE_TTS_KEY` / `AZURE_TTS_REGION` | não | Reservadas pros provedores stub — não têm efeito ainda porque a chamada de API real não foi implementada (seção 5.6) |
| `YOUTUBE_API_KEY` | não | Se ausente, YouTube tool desliga sozinha |
| `PROJETOS_DIR` | sim | Onde cada projeto ganha subpasta |
| `PORTA` | não | Default `5000` |
| `WHISPER_MODEL` | não | Default `medium`. Opções: `small`, `medium`, `large-v3` |
| `WHISPER_DEVICE` | não | Default `cuda` |
| `CLIPE_DURACAO_MIN_S` | não | Default `6.0`. Duração mínima de cada clipe sorteado na Etapa 5 |
| `CLIPE_DURACAO_MAX_S` | não | Default `10.0`. Duração máxima de cada clipe sorteado na Etapa 5 |
| `MARGEM_INICIO_S` / `MARGEM_FIM_S` | não | Default `30` nos dois — margem de segurança no início/fim de cada vídeo-fonte na seleção de clipes (seção 5.7) |
| `LEGENDA_FONTE` | não | Default `Poppins Bold`. Opções: `Poppins Bold`, `Arial Black`, `Impact` |
| `LEGENDA_TAMANHO` | não | Default `64`. Opções: `56`, `64`, `72` |
| `LEGENDA_POSICAO` | não | Default `baixo`. Opções: `baixo`, `meio-baixo` |
| `LEGENDA_KARAOKE_ATIVO` | não | Default `true`. Destaque de palavra ativa (estilo karaokê); cor primária (branco) e contorno (preto) são fixos no código, não configuráveis |
| `LEGENDA_DESTAQUE_COR_NOME` | não | Default `amarelo`. Opções: `amarelo`, `verde`, `laranja`, `rosa`. Só tem efeito com `LEGENDA_KARAOKE_ATIVO` ligado |
| `MUSICA_VOLUME_BASE` | não | Default `0.18`. Volume base da música de fundo antes do ducking automático |
| `WEB_SEARCH_MAX` | não | Default `5` — teto por chamada de roteiro (elevado de 2 na Sessão 22: 2 buscas se mostraram insuficientes em teste real, roteiro não refletiu desenvolvimento recente de um caso) |
| `COTACAO_USD_BRL` | não | Default `5.20`. Usada só pra exibir estimativa de custo em reais na tela de revisão |
| `KEN_BURNS` | não | Default `true`. Aplica só a clipes reais gerados pela Etapa 5 |
| `DRY_RUN_API` | não | Default `false`. Se `true`, monta o prompt da Etapa 3 mas não chama a Anthropic API de verdade — grava em `dry_run_output.md` |

Removidas desta tabela por não corresponderem a nenhum código real:
`ESTRATEGIA_CORTE`, `CLIPE_MIN_S`, `CLIPE_MAX_S`, `CLIPE_TOLERANCIA_S`
(a Etapa 5 não tem mais estratégia configurável de corte — seção 5.7),
`VEO3_QUALIDADE_PADRAO`/`VEO3_QUANTIDADE_PADRAO`/`VEO3_CACHE_DIR`/`GOOGLE_API_KEY`
(documentavam a implementação de Veo3, nunca construída — seção 5.75,
sem leitura de env var nenhuma no código hoje), `CURADORIA_SEMANTICA`
(obsoleta desde a Sessão 11, não é mais lida nem persistida pela tela de
Ajustes) e `LEGENDA_COR`/`LEGENDA_CONTORNO_COR`/`LEGENDA_CONTORNO_ESPESSURA`/
`LEGENDA_DESTAQUE_PALAVRA`/`LEGENDA_DESTAQUE_COR` (nomes antigos — ver
`LEGENDA_KARAOKE_ATIVO`/`LEGENDA_DESTAQUE_COR_NOME` acima).

**Tela de ajustes (`/ajustes`)** edita subset via formulário e persiste
no `.env`. Editável pela tela: PROJETOS_DIR, ANTHROPIC_API_KEY,
ANTHROPIC_MODEL, IDIOMA_ROTEIRO, WHISPER_MODEL, KEN_BURNS,
CLIPE_DURACAO_MIN_S, CLIPE_DURACAO_MAX_S, TTS_PROVEDOR_PADRAO,
TTS_VOZ_PADRAO, GOOGLE_TTS_API_KEY, DARKPLANNER_API_KEY,
ELEVENLABS_API_KEY, OPENAI_API_KEY, AZURE_TTS_KEY, AZURE_TTS_REGION,
YOUTUBE_API_KEY, WEB_SEARCH_MAX, COTACAO_USD_BRL, MUSICA_VOLUME_BASE, e
todos os `LEGENDA_*`. Resto só editando `.env`.

Override por projeto na tela de revisão: origem do áudio (TTS/upload/
pausar), se TTS provedor e voz específicos, e música de fundo. Override
por projeto no formulário de novo projeto: perfil de conteúdo
(obrigatório), idioma (opcional), marca d'água por fonte (opcional),
tipo de uso por fonte e upload direto de mídia visual (opcional — modo
de fontes separadas, seção 5.7.2).

## 8. Testes

Toda função nova vem com teste. Nenhuma etapa é considerada pronta sem
`pytest` verde. Enforçado por:

1. `AGENTS.md` (regra explícita aqui)
2. Subagentes `test-writer` e `test-runner` em `.Codex/agents/` —
   ver arquivos
3. Hook `PostToolUse` opcional em `.Codex/hooks/`

**Convenções:**

- `tests/conftest.py` com fixtures compartilhadas
- Nunca chamar API real do Codex/TTS/YouTube em teste — mockar
- Nunca chamar yt-dlp ou faster-whisper real em teste — mockar com
  fixture de output real capturado
- Testes de integração ponta-a-ponta usam áudio/vídeo sintético
  (`ffmpeg -f lavfi`, `testsrc`) — validam costura, sem material real
  nem chaves
- Marcar testes lentos (>1s) com `@pytest.mark.slow`
- Cobertura alvo: 70% em scripts, 90% em funções puras (parsers,
  calculadoras de janela, validadores de schema, alocador semântico)

## 9. Convenções do projeto

**Cada script em `scripts/` é autocontido.** Sem `utils.py`
compartilhado. Funções comuns duplicadas nos scripts que precisam.
Facilita depurar isolado; obriga corrigir bug em todos os lugares.

**Convenção `@PROGRESSO {json}`:** stdout do script imprime
`@PROGRESSO {"pct": 45.0, "eta_s": 120, "detalhe": "..."}`. `server.py`
intercepta e atualiza job.

**`iniciar_etapa(nome, etapa, **extra)`:** dict de defaults com
`.update(extra)`, nunca passar kwargs direto (colisão com defaults
tipo `erro=None`).

**Windows em mente:**
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` topo
  de todo script
- No `subprocess.Popen`, forçar env: `PYTHONIOENCODING=utf-8`,
  `PYTHONUTF8=1`, `PYTHONUNBUFFERED=1`
- Nomes de arquivo ASCII sem acento nem espaço

**`ffmpeg -ss` DEPOIS de `-i`.** Nunca antes com `-c copy`.

**`yt-dlp` sempre via `python -m yt_dlp`**, nunca como CLI direto.
(Abordagem inspirada em `yt_automation`, dar crédito no código.)

**Nenhum print colorido, nenhum spinner ANSI.** Só `@PROGRESSO`.

## 10. Estrutura de pastas do projeto de código

```
broll_foundry/
  server.py                   # Flask, roteia, dispara subprocess
  requirements.txt
  .env.example                # sem valores reais, com comentários
  iniciar.bat                 # cria venv, instala, roda server
  LEIAME.md                   # instalação + uso pro usuário final
  AGENTS.md                   # este arquivo
  MIGRACAO.md                 # registro histórico da migração do broll_alfa
  prompt_abertura.md          # roteiro de sessões (histórico + próximas)
  HISTORICO_BUGS.md           # log cronológico de bugs/decisões por sessão
  MELHORIAS_PENDENTES.md      # backlog vivo de pendências
  VERSION.txt                 # versão semântica (ver seção 16)
  LICENSE.txt                 # licença atual (ver seção 16)
  scripts/
    robustez.py                 # infra transversal (secao 18) - libs volateis, ffmpeg
    ambiente.py                  # infra transversal (secao 13/18.9) - deteccao NVIDIA/CUDA
    whisper_setup.py             # registro de DLLs CUDA compartilhado (2_transcrever + 4_obter_audio)
    validators.py                # validadores/normalizadores compartilhados por telas
    instalar_ffmpeg.py           # cascata de instalacao do ffmpeg (secao 18.3)
    watermark_regions.py         # coordenadas de delogo por posicao (secao 5.7.1)
    warnings_traducoes.py        # traducao de avisos exibidos ao usuario
    erros.py                     # DEAD CODE - ver MELHORIAS_PENDENTES.md, referencia arquitetura removida
    1_baixar_videos.py
    2_transcrever.py
    3_gerar_roteiro.py
    4_obter_audio.py
    5_gerar_clipes.py            # geracao de clipes por selecao aleatoria (secao 5.7)
    6_montar_video.py            # concat + mux + legendas + musica (secao 5.8)
    tools/
      __init__.py
      youtube.py                # tool youtube_top_titles (secao 5.3) - infra transversal
    tts/
      __init__.py
      base.py                  # interface comum ProvedorTTS
      erros.py
      google.py                # implementado - provedor padrao (secao 5.6)
      darkplanner.py           # implementado - vozes ElevenLabs via revenda (secao 5.6)
      elevenlabs.py            # stub - interface pronta, sem chamada de API real
      openai.py                # stub
      azure.py                 # stub
      vozes_catalogo.json
    prompts/
      __init__.py
      erros.py
      loader.py             # monta prompt final por perfil+idioma
      perfis/
        truecrime/
          config.py
          sistema.md
          fontes_preferidas.py
          juridico_en_us.md
          juridico_en_gb.md
          juridico_pt_br.md
          juridico_es.md
          juridico_de.md
          descricao_curta.txt
          descricao_longa.md
        atualidades_narrativas/
          config.py
          sistema.md
          fontes_preferidas.py
          descricao_curta.txt
          descricao_longa.md
        historia/
          config.py
          sistema.md
          fontes_preferidas.py
          descricao_curta.txt
          descricao_longa.md
  templates/
    base.html
    home.html
    ajustes.html
    novo_projeto.html
    status.html
    _pipeline_horizontal.html  # partial reutilizado (Sessao 16/17) - barra de etapas clicavel
    revisao_roteiro.html
    concluido.html
    sobre.html                # tela "sobre" (ver seção 16)
  static/
    design_system.css         # design system Nocturne (Sessao 14, substituiu o tema escuro antigo)
    style.css
    ajustes.js
    novo_projeto.js
    status.js                 # polling do estado
    revisao.js                # editor + player de trecho de fonte
  tests/
    conftest.py
    test_*.py
  .Codex/
    agents/
      test-runner.md
      test-writer.md
```

Não existem mais `scripts/5_planejar_edicao.py`, `5b_enriquecer_veo3.py`,
`6_cortar_clipes.py`, `7_gerar_legendas.py`, `8_montar_video.py`,
`scripts/veo3/`, `scripts/detector_cenas.py`, `scripts/analisador_visual.py`
nem `scripts/deduplicador_visual.py` — arquiteturas de pipeline
abandonadas entre as Sessões 9 e 11 (ver seção 5.7 e `HISTORICO_BUGS.md`).
`templates/revisar_roteiro_stub.html` (stub temporário da Sessão 6) também
não existe mais — substituído por `revisao_roteiro.html` já na Sessão 7.

## 11. APIs externas — resumo de custo

**Anthropic Messages API.** `Codex-sonnet-5` padrão. Web search
$10/1000 buscas + tokens. Custo estimado por vídeo (Etapa 3, roteiro):
$0.10-0.50. A Etapa 5 (geração de clipes) não chama API nenhuma — seleção
aleatória local via ffmpeg (seção 5.7) — não há mais custo de "curadoria
semântica" separado.

**Google Cloud TTS.** Provedor implementado e padrão hoje (seção 5.6).
Cobrado por caractere convertido; tier `Wavenet` é o único permitido
(`GOOGLE_TTS_TIER_PERMITIDO`). Roteiro de 15-20 min ~15-25k caracteres —
custo tipicamente abaixo de $1/vídeo.

**DarkPlanner.** Provedor implementado (seção 5.6) — vozes ElevenLabs
via revenda/plano PRO já pago do usuário. Sem custo adicional por
vídeo, é chave compartilhada de plano fixo.

**ElevenLabs / OpenAI TTS / Azure.** **Stubs, sem chamada de API real
ainda** (seção 5.6) — os custos abaixo são estimativas de referência pra
quando forem implementados, não custo real hoje:
- ElevenLabs: cobra por caractere, ~$2-8/vídeo dependendo do plano.
  **Plano tem que permitir uso comercial** quando implementado — nunca
  usar plano gratuito/Starter pra conteúdo monetizado
- OpenAI TTS: ~$0.015/1000 caracteres, ~$0.25-0.40/vídeo

**YouTube Data API v3.** Grátis. 10.000 unidades/dia. Uma busca = 100
unidades. Sobra pra 100 projetos/dia.

**Google Veo3.** **Não implementado ainda** (seção 5.75) — nem
scaffolding de prompt existe hoje, sem chamada de API real, portanto
sem custo real hoje. Estimativas abaixo são de referência pra quando a
Etapa 5.75 for construída:
- `veo3-fast`: ~$0.15/s de vídeo gerado
- `veo3` (padrão): ~$0.35-0.75/s
- 5 cenas de 8s em `veo3-fast`: ~$6/vídeo. 8 cenas em `veo3` padrão:
  ~$22-48/vídeo

**Estimativa mensal em uso realista hoje (1 vídeo/dia, sem Veo3 e sem
provedores TTS stub):**
- Codex API: ~$3-15/mês (só Etapa 3, sem custo de curadoria separado)
- Google TTS: ~$0-30/mês, ou $0 se usar upload de voz própria
- YouTube API: $0
- **Total: ~$3-45/mês** no estado atual do produto

A estimativa de "até ~$1800/mês" de versões anteriores deste documento
assumia ElevenLabs Creator diário + Veo3 em uso pesado — nenhum dos dois
está implementado hoje, então não reflete custo real possível ainda.
Reavaliar esta seção quando ElevenLabs/OpenAI/Azure e Veo3 saírem do
estágio de stub/scaffolding.

## 12. Posições firmes do projeto (não renegociar)

**Chaves de API:** nunca pedir/receber/manusear no chat. Só orientar
`.env` local.

**Automação de navegador contra ToS:** não construir/integrar/operar.
Vale pra YouTube, ElevenLabs, qualquer serviço. Risco de suspensão.

**Revisão humana do roteiro:** não sugerir/implementar automação que
pule ou reduza. É a mitigação do risco factual do modelo. Mesmo com
web search e prompt melhor do mundo, Codex ocasionalmente confunde
detalhe factual em caso criminal real (troca de nome, confusão
indiciado/condenado). A revisão é a proteção.

**Extensão de escopo:** dashboard de tendências, música de fundo,
Shorts, thumbnail — se surgir pedido durante MVP, lembrar que ficaram
deliberadamente pra v2. Não implementar "de surpresa".

**Reprodução de código do yt_automation:** postura 2 (ver seção 2).
Estudo com reaproveitamento de trechos técnicos específicos com
crédito. Nunca fork disfarçado.

## 13. Requisitos mínimos oficiais e hardware alvo

**Requisitos mínimos oficiais do produto** (fixados na Sessão 4 — o
Broll Foundry refusa duro se a máquina não atender):

- Windows 10 ou 11 x64
- GPU NVIDIA com CUDA Compute Capability 6.0+ (Pascal ou mais novo —
  GTX 1060+ / RTX qualquer)
- 4 GB VRAM mínimo, 6 GB recomendado, 8 GB+ ideal
- Driver NVIDIA suportando CUDA 12+ (o driver pode ter CUDA 13+, o
  requisito é só o mínimo)
- 16 GB RAM sistema mínimo, 32 GB recomendado
- FFmpeg no PATH (já validado desde a Sessão 2/3 — seção 18.3)

GPUs AMD e Intel **não são suportadas**. CPU-only **não é suportado**.
`scripts/ambiente.py` detecta o ambiente via `nvidia-smi` e recusa a
Etapa 2 (transcrição) com mensagem clara se o mínimo não for atendido —
ver seção 18.9.

**Nota técnica importante:** o requisito "driver suportando CUDA 12+" é
sobre o *driver*, não sobre o CUDA Toolkit completo. O driver sozinho
**não** inclui as bibliotecas de runtime cuBLAS/cuDNN que o `ctranslate2`
(usado pelo `faster-whisper`) carrega em tempo de execução — sem elas, a
Etapa 2 falha com algo como `Library cublas64_12.dll is not found or
cannot be loaded`, mesmo em GPU compatível (confirmado numa RTX 3070 Ti
de verdade na Sessão 4). `requirements.txt` inclui `nvidia-cublas-cu12`
e `nvidia-cudnn-cu12` para isso, e `scripts/2_transcrever.py` registra as
pastas `bin/` desses pacotes no `PATH` do processo automaticamente
(`_registrar_dlls_cuda_do_venv`) antes de importar `faster-whisper`.

**Máquina de desenvolvimento de referência:**

- CPU: AMD Ryzen 7 5700X
- RAM: 32 GB
- GPU: NVIDIA RTX 3070 Ti 8GB VRAM
- OS: Windows

Implicações:
- `faster-whisper` `medium` em `float16`: ~1.5GB VRAM, ~2-3 min pra 30min de áudio
- `ffmpeg` reencodando `libx264 preset veryfast`: CPU-bound, ~2x tempo real
- Rodar Whisper GPU + ffmpeg CPU + Flask + TTS API: ok, não competem

## 14. Estimativa de tempo pro usuário antes de aprovar roteiro

A tela de revisão mostra, antes do botão "aprovar":

- Quantos vídeos-fonte foram baixados + duração total
- Estimativa de tempo pra gerar áudio TTS (medir 1x, salvar constante)
- Estimativa de N clipes finais (regra de três com `CLIPE_DURACAO_MAX_S`)
- Estimativa de tempo de cada etapa restante

Objetivo: fazer o humano revisar com atenção sabendo que aprovar
dispara processo de 15-30 minutos.

## 15. Retrabalho visual — histórico (concluído na Sessão 14)

**Status: concluído.** Esta seção documentava um retrabalho visual
*planejado* pra uma futura "Sessão 16". Na prática, o retrabalho
aconteceu antes disso, na Sessão 14 — o tema escuro Codex.ai-style
original foi substituído pelo design system **Nocturne**
(`static/design_system.css`), com refinamentos adicionais nas Sessões
15 (polish geral) e 16/17 (pipeline horizontal sticky + clicável).
Mantido aqui só como registro histórico da referência estética usada:

- `.Codex/referencias/visual_ref_zebeyond.png` — SaaS moderno com fundo
  preto profundo, acento verde neon, cards translúcidos com borda sutil,
  halo de luz vazando de canto, tipografia leve em tamanhos generosos —
  usado como ponto de partida, não copiado de perto (risco de identidade
  visual próxima demais de produto de terceiro).

Pendências visuais que restaram são tratadas como itens normais de
polish em `MELHORIAS_PENDENTES.md`, não como uma sessão dedicada
separada.

## 16. Preparação pra licenciamento futuro

O produto começa "uso pessoal apenas" mas com estrutura pronta pra
virar comercializado sem retrabalho. Quatro coisas ficam desde já:

**Arquivo `VERSION.txt` na raiz.** Convenção `MAJOR.MINOR.PATCH`.
Começa em `0.1.0-mvp`. Incrementa manualmente conforme o produto
evolui. Só rastreabilidade — nenhum sistema automatizado depende
dele por enquanto.

**Arquivo `LICENSE.txt` na raiz.** Texto por enquanto:
"Broll Foundry - Uso pessoal apenas. Não redistribuir. Todos os
direitos reservados. © [ano] [nome do autor]." Se um dia decidir
vender, troca por licença comercial escrita por advogado. Se decidir
open source, troca por MIT/Apache. Deixa o slot explícito desde o
começo.

**Tela `/sobre`.** Simples, uma rota nova. Mostra:
- Nome do produto (Broll Foundry) + versão lida do VERSION.txt
- Link "ver licença" que abre modal com o conteúdo do LICENSE.txt
- Aviso: "Produto local. Seus dados, seus vídeos e suas chaves de API
  ficam somente na sua máquina."
- **Seção "Perfis de conteúdo"** — para cada perfil disponível, mostra
  nome de exibição, descrição longa (do `descricao_longa.md`), custo
  estimado por vídeo. Renderiza dinamicamente lendo os arquivos de
  perfil — adicionar perfil novo aparece aqui sem tocar em HTML
- Créditos: menção honesta ao `yt_automation` (Gustavo Xavier) pelas
  abordagens técnicas específicas reproduzidas com crédito no código
- Link no rodapé de todas as páginas ("sobre") leva pra esta tela

**Rota stub `/verificar_atualizacao`.** Retorna hoje:
```json
{"versao_local": "<lido do VERSION.txt>", "versao_disponivel": null,
 "mensagem": "verificação de atualizações não implementada nesta versão"}
```
No futuro, quando houver servidor de releases, esta rota passa a
consultar. O código já espera essa estrutura de resposta — adição
futura não muda contrato.

**O que NÃO vai no MVP** (nem preparação):
- Sistema de licença/ativação online — decisão de arquitetura pesada,
  fica pra se/quando comercializar de verdade (não antes de 100+
  clientes pagantes potenciais mapeados)
- Empacotamento como .exe (PyInstaller/Nuitka) — não protege código
  Python de forma significativa, decisão pra se/quando fizer sentido
- Check-for-updates automático (só a rota stub existe)

## 17. Comercialização futura (nota estratégica)

Se o produto evoluir pra comercialização, decisões já tomadas:

**Modelo: distribuição local, não SaaS.** Usuário instala na máquina
dele, configura próprias chaves de API, roda 100% local. Sem
infraestrutura recorrente do vendedor. Motivos: custo operacional de
SaaS com GPU + APIs seria proibitivo pra developer solo, público-alvo
(criadores de conteúdo) valoriza "seus dados na sua máquina", e
concorrência SaaS tem VC-backing.

**Faseamento de comercialização (não decidir antes de tempo):**

*Fase 1 (agora até produzir 20-30 vídeos com o produto):* não vende.
Foca em usar e amadurecer. Repositório privado.

*Fase 2 (se quiser começar a vender):* registro de marca do nome no
INPI (~R$355), registro de software no INPI opcional (~R$185),
contrato de licença escrito por advogado (~R$500-1000 uma vez),
venda via Gumroad/Lemon Squeezy como zip com PyInstaller. Preço
~$50-150 uma vez ou $10-20/mês. Aceita que pirataria existe — foca
em vender pra quem valoriza suporte e atualizações.

*Fase 3 (se virar negócio real com 100+ clientes pagantes):*
licenciamento profissional via serviço tipo Keygen/Cryptolens,
empacotamento robusto, possível reescrita de partes críticas.
Não faz sentido antes desse volume.

**Verdades técnicas importantes sobre proteção de código Python:**

- PyInstaller/Nuitka **não** protegem contra engenharia reversa
  determinada — só dificultam pra usuário casual
- Ativação online única é ilusão de segurança: quem quer piratear,
  pirateia
- Patente de software não existe no Brasil pra este tipo de produto
- Direito autoral é automático no Brasil (não precisa registrar pra
  ter direito; registrar só ajuda em disputa)
- Marca (nome do produto) — esta sim vale registrar quando
  comercializar

Arquitetura desacoplada de TTS + prompt editável + `.env` bem
documentado = facilita personalização por comprador. Preparação já
existe na seção 16.

## 18. Robustez contra dependências externas voláteis

Descoberto em teste real da Etapa 1 (Sessão 2): dependências que
interagem com serviços externos (YouTube, APIs de plataforma) mudam
com frequência. Versão pinada exata do `yt-dlp` que era atual em Jan
2026 quebrou em 9 meses porque o YouTube mudou mecânica de extração.
Sintoma: script "funciona" (não crasha) mas todos os downloads falham
silenciosamente, e reporta 100% ao usuário.

Isso é falha de design, não bug pontual. Vale pra qualquer dependência
externa volátil que a ferramenta usa: `yt-dlp`, potencialmente
`faster-whisper` (se OpenAI mudar formato), APIs do Codex/ElevenLabs/
OpenAI/Azure/Google Veo3/YouTube Data.

**Princípios que valem pra qualquer script novo do pipeline:**

### 18.1 Pinning estratégico no `requirements.txt`

- Bibliotecas estáveis (Flask, pytest, python-dotenv, requests,
  Pillow): pinar versão exata (`==`)
- Bibliotecas voláteis contra APIs externas (`yt-dlp` principalmente;
  reavaliar `faster-whisper` conforme o produto amadurece): pinar
  versão MÍNIMA (`>=`) pra `pip install -r requirements.txt` sempre
  pegar a mais nova
- Documentar essa distinção em comentário no próprio
  `requirements.txt`

### 18.2 Check de idade de dependência crítica no boot

O `server.py` verifica, ao subir, se dependências voláteis conhecidas
estão razoavelmente atuais (janela de 90 dias desde release da versão
instalada). Se velha demais, banner amarelo no topo de todas as
páginas via `base.html`: "Sua versão de `<lib>` tem X dias. Comandos
podem falhar. Atualize com: `pip install --upgrade <lib>`".

Banner é dispensável (botão fechar, persiste decisão em cookie de
sessão) mas volta se a lib continuar velha na próxima sessão. Não
bloqueia uso — apenas informa antes de o usuário perder tempo.

Lista de libs monitoradas fica em `scripts/robustez.py` (função
`libs_criticas()`), começa com `yt-dlp` e cresce conforme necessário.

### 18.3 Flag `--instalar-deps` no `iniciar.bat`

Nota de implementação (Sessão 2.5): a flag saiu maior do que o esboço
original desta seção — em vez de só `pip install --upgrade`, ela cobre
toda dependência de sistema que a etapa 1 (download) descobriu faltando
em teste real, então o nome virou `--instalar-deps` em vez de
`--atualizar`.

**Correção da Sessão 3 (descoberta em teste real com o usuário):** a
primeira versão desta seção assumia que `winget install --id
Gyan.FFmpeg` deixava o `ffmpeg` pronto pra uso sozinho. Não deixa — o
pacote do Gyan distribuído pelo winget é **portable** (um .zip
extraído, não um instalador MSI), então o winget registra o pacote
como instalado mas **não adiciona a pasta `bin` ao PATH**. Sintoma real:
"instalação bem-sucedida" seguida de `ffmpeg -version` continuando a
falhar — exatamente o antipadrão da seção 18.4 (sucesso reportado que
não é sucesso de verdade), só que no instalador de dependência do
sistema em vez de num script do pipeline.

**Fluxo corrigido, em cascata (do menos pro mais invasivo):**

A cascata inteira mora em `scripts/instalar_ffmpeg.py` (Python, não
batch) — a lógica de busca recursiva de arquivo, escrita no registro do
Windows e elevação via UAC é inviável de fazer bem em batch puro. O
`iniciar.bat` só verifica `where ffmpeg` antes de delegar, invoca o
script, e depois lê um arquivo de hint (`FFMPEG_PATH_HINT`) que o
script grava quando ele mesmo adiciona um diretório novo ao PATH — isso
deixa a **sessão atual do `.bat`** com `ffmpeg` utilizável mesmo sem
reabrir o terminal (o registro do Windows por si só só vale pra
terminais futuros).

1. **Tentativa 1 — winget.** Roda `winget install --id Gyan.FFmpeg`.
   Confere `ffmpeg` no PATH depois. Se não apareceu (caso do pacote
   portable), procura `ffmpeg.exe` recursivamente em
   `%LOCALAPPDATA%\Microsoft\WinGet\Packages\` e, se encontrar, grava o
   diretório no PATH do usuário via registro do Windows
   (`HKCU\Environment`) e valida de novo. `winget` ausente no sistema
   pula esta tentativa inteira, direto pra 2.
2. **Tentativa 2 — chocolatey (requer admin).** Se chocolatey não
   estiver instalado, mostra um aviso explícito ANTES de disparar UAC
   ("o Windows vai pedir permissão de administrador, isso é normal e
   seguro") e espera confirmação do usuário. Instala chocolatey (se
   preciso) e `choco install ffmpeg -y` numa única sessão elevada (um
   só prompt de UAC, não dois). Se o usuário negar o UAC ou a instalação
   falhar, cai pra 3.
3. **Tentativa 3 — instrução manual.** Último recurso: imprime passo a
   passo completo (baixar zip do Gyan, extrair, editar variável de
   ambiente Path manualmente) e para o script com código de saída != 0.
   Nunca falha silenciosamente.

Depois da cascata (ou se `ffmpeg` já estava no PATH), roda:

- `pip install --upgrade` nas libs voláteis — hoje só `yt-dlp`
  (`scripts/robustez.py:libs_criticas()` é a lista única, usada tanto
  aqui quanto no banner do `server.py`). `faster-whisper` fica de fora
  propositalmente: não é volátil contra API externa como o `yt-dlp` é
  contra o YouTube, e um upgrade automático dele pode quebrar a
  compatibilidade CUDA/cuDNN já documentada na seção 4 — atualização
  dele continua manual, a critério do usuário.
- Só depois disso sobe o servidor (igual ao fluxo sem a flag).

Comportamento sem a flag continua idêntico ao de sempre — nunca pede
UAC, nunca toca em PATH. Usuário roda a flag manualmente de vez em
quando pra manter tudo atualizado sem precisar lembrar comandos de
pip/winget/choco.

**Regra de teste crítica (violada uma vez, não repetir):** uma tentativa
anterior de testar a cascata via subprocess real acabou instalando
`ffmpeg` de verdade numa máquina de dev via `winget`, além de deixar um
`python server.py` real rodando em background. Testes desta cascata são
sempre mockados (`scripts/instalar_ffmpeg.py` isola cada tentativa em
função própria justamente pra poder mockar `subprocess.run`,
`shutil.which` etc.) ou, no caso do `.bat` em si, puramente estáticos
sobre o texto do arquivo — nunca invocam `winget install`, `choco
install` ou `Start-Process -Verb RunAs` de verdade.

**Achado crítico da Sessão 3 sobre o `.bat` em si: quebra de linha tem
que ser CRLF, sempre.** Validando a correção acima numa execução real
(fora da suite de testes — `subprocess.Popen` direto, nunca em teste
automatizado), `iniciar.bat` com quebras de linha LF-only (sem `\r`,
que é o que ferramentas de edição no Windows costumam gravar por
padrão) corrompe a execução: o parser de blocos parentizados do
`cmd.exe` (`if ... ( ... )`) perde o alinhamento de leitura do arquivo
logo depois de um bloco desses, e passa a executar fragmentos de linhas
seguintes como comandos soltos (sintoma visto de verdade: `errorlevel`
rodando sozinho como comando, pedaços tipo `tlocal`/`cho`/`ho.` de
`endlocal`/`echo.`). O bug não aparece lendo o arquivo — só na execução
real — e desaparece por completo convertendo o arquivo inteiro pra
CRLF. `tests/test_iniciar_bat.py` tem um teste estático
(`test_arquivo_usa_quebra_de_linha_crlf_em_todo_lugar`) que falha se
qualquer edição futura reintroduzir uma quebra LF-only no arquivo — não
remover esse teste, e rodar `pytest` depois de qualquer edição manual
em `iniciar.bat` antes de considerar a mudança pronta.

### 18.4 Todo script do pipeline reporta sucesso E falha honestamente

**Antipadrão a evitar** (descoberto em `1_baixar_videos.py` v1):

```
@PROGRESSO {"pct": 100.0, "detalhe": "Concluído"}
```

...quando na verdade 0 de N downloads deram certo. Isso engana o
usuário que acha que funcionou.

**Padrão correto:**

- Se todos os itens foram processados com sucesso:
  `{"pct": 100.0, "detalhe": "N vídeos baixados com sucesso", "sucesso": true}`
- Se alguns falharam:
  `{"pct": 100.0, "detalhe": "Concluído com X de Y sucessos", "sucesso": true, "avisos": [...]}`
- Se todos falharam:
  `{"pct": 100.0, "detalhe": "ERRO: nenhum item processado", "sucesso": false, "erros": [...]}`
- Nas linhas intermediárias, incluir contagem: `"Processando 3/10..."`

Todo script que processa múltiplos itens deve seguir esse padrão. O
`server.py`, ao ler `@PROGRESSO`, checa o campo `sucesso` e decide se
avança pra próxima etapa ou para o pipeline com erro visível pro
usuário.

### 18.5 Todo script captura stderr de subprocess e inclui em log/manifest

**Antipadrão:** `"erro": "yt-dlp saiu com codigo 1"`. Sem info do que
deu errado, impossível debugar.

**Padrão:** capturar as últimas 15 linhas de stderr do subprocess,
incluir em campo `log_erro` no manifest, e imprimir no `@PROGRESSO`
como `detalhe_erro` pra aparecer na tela do usuário. Vale pra qualquer
subprocess: `yt-dlp`, `ffmpeg`, `faster-whisper` CLI se usado.

### 18.6 Todo script valida input antes de fingir processar

**Antipadrão:** script recebe pasta sem `entrada/links.txt`, completa
silenciosamente com 100%, deixando manifest vazio.

**Padrão:** validar toda pré-condição no início da execução. Se falta
input obrigatório (arquivo esperado ausente, vazio, malformado),
falhar imediatamente com:
- Exit code != 0
- `@PROGRESSO {"pct": 0, "detalhe": "ERRO: <descrição específica>", "sucesso": false}`

Nunca começar processamento parcial de um input inválido.

### 18.7 Validação em cascata continua valendo

Cada script tem que verificar que os artefatos que ele consome
(gerados por script anterior) existem e estão bem-formados. Não
assumir que "se script anterior terminou, output tá ok" — verificar
explicitamente. Ex: `2_transcrever.py` verifica que
`fontes/manifest_fontes.json` existe e tem pelo menos um vídeo com
`sucesso: true`, senão erro claro em vez de rodar Whisper em vídeos
falhados.

### 18.8 Testes têm que cobrir os cenários de falha, não só sucesso

Toda função nova (por AGENTS.md seção 8) tem que ter teste que cobre:
- Caminho feliz
- Input vazio / ausente
- Falha do subprocess externo (mockada com exit code != 0 + stderr)
- Falha parcial (alguns itens ok, outros não)
- Timeouts (se aplicável)

Não aceitar "tá tudo testado" quando os testes só cobrem happy path.
Bug de silenciar falha em `1_baixar_videos.py` v1 passou porque os
testes só mockavam sucesso.

### 18.9 Detecção de ambiente NVIDIA/CUDA (Sessão 4)

`scripts/ambiente.py` é módulo autocontido (sem depender de
`faster-whisper` nem de nenhuma outra lib pesada do projeto — só
`subprocess`/`re` da stdlib), pra poder rodar mesmo antes do
`pip install -r requirements.txt` ter sido executado. Três funções:

- `detectar_gpu()` — roda `nvidia-smi` (duas chamadas: uma
  `--query-gpu=...` estruturada pra nome/VRAM/driver/compute capability,
  outra sem argumentos só pra extrair a linha `CUDA Version:`/
  `CUDA UMD Version:` do cabeçalho — o rótulo mudou entre versões do
  driver, o parser aceita os dois). Nunca levanta exceção — GPU ausente
  vira `{"presente": False, "erro": "..."}`.
- `avaliar_compatibilidade(gpu)` — compara contra os mínimos oficiais
  (seção 13) e retorna `atende_minimo`, `problema` (categoria:
  `sem_gpu`/`vram_baixa`/`compute_cap_antiga`/`cuda_antigo`/`None`),
  `mensagem` amigável, e `modelos_suportados` (lista, vazia se não
  atende).
- `recomendar_modelo(gpu)` — melhor modelo default do faster-whisper pra
  VRAM detectada (`small` abaixo de 6GB, `medium` a partir de 6GB —
  nunca recomenda `large-v3` automaticamente, mesmo em GPU de sobra).

**Comportamento no boot do `server.py`:** a checagem roda uma vez por
`create_app()` (mesmo padrão do `_calcular_banners()` de robustez —
AGENTS.md seção 18.2), guardada num global de módulo `AMBIENTE_ATUAL`
(não só `app.config`, porque as threads de fundo das etapas do pipeline
não têm contexto de aplicação Flask disponível). **Ambiente
incompatível NUNCA derruba o boot** — o usuário precisa poder abrir
Ajustes pra diagnosticar o problema. Em vez disso:
- Banner vermelho persistente (`banner_ambiente_incompativel`) em TODAS
  as páginas, mesmo padrão não-dispensável do banner de ffmpeg ausente.
- Bloco "Ambiente detectado" no topo de `/ajustes`, com detalhe completo
  (GPU, VRAM, driver, modelos suportados, recomendado) ou o motivo da
  incompatibilidade.
- O dropdown de `WHISPER_MODEL` em Ajustes só lista os modelos que a
  VRAM detectada suporta de verdade — nunca oferece `large-v3` numa GPU
  de 4GB. Se o modelo selecionado for o maior que a VRAM comporta,
  aviso amarelo explicando a folga apertada.
- `POST /projetos/<id>/transcrever` (disparo manual/retry da Etapa 2)
  recusa com HTTP 400 se o ambiente não atender ao mínimo, antes de
  gastar tempo subindo um subprocess fadado a falhar.

**`scripts/2_transcrever.py` faz a MESMA checagem de novo, sozinho**,
como pré-condição (`_validar_pre_condicoes`, mesmo espírito da seção
18.6) — importante porque o script roda como processo independente e
não pode confiar que quem o chamou já validou o ambiente. Ambiente
incompatível vira `tipo_erro: "gpu_indisponivel"` no `@PROGRESSO` final,
antes mesmo de tentar carregar o modelo Whisper (evita gastar tempo
baixando/carregando um modelo de vários GB só pra falhar na hora de
transcrever).

**Achado real de hardware (Sessão 4, testado numa RTX 3070 Ti de
verdade):** ter o *driver* com CUDA 12+ não é suficiente — o
`ctranslate2` (usado pelo `faster-whisper`) carrega bibliotecas de
runtime cuBLAS/cuDNN em tempo de execução (lazy, só na primeira chamada
de `model.transcribe(...)`, não na construção do `WhisperModel`), que
não vêm com o driver. Sem os pacotes `nvidia-cublas-cu12`/
`nvidia-cudnn-cu12` (já em `requirements.txt`) **e** sem essas pastas
`bin/` no `PATH` do processo, a Etapa 2 falha com algo como `Library
cublas64_12.dll is not found or cannot be loaded` mesmo em GPU
plenamente compatível. `os.add_dll_directory` sozinho **não** resolveu
na prática (o carregamento é lazy e não respeitou os diretórios
registrados por essa API) — o que funcionou de verdade foi prepender ao
`PATH` do processo (`_registrar_dlls_cuda_do_venv()`, chamada no topo de
`scripts/2_transcrever.py` antes de importar `faster_whisper`).
`classificar_erro_transcricao` também reconhece essa mensagem exata
como `gpu_indisponivel` (defesa em profundidade, caso os pacotes não
estejam instalados por algum motivo).
