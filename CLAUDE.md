# Broll Foundry

*Atualizado após Sessão 21 (04/09/2026) — ver `HISTORICO_BUGS.md` pro
histórico completo de sessões e `prompt_abertura.md` pro roteiro de
sessões futuras.*

Documento de referência do projeto. O Claude Code lê este arquivo em toda
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
reaproveitamento de trechos técnicos genéricos). O Claude Code deve
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
  `en-GB`, `pt-BR`, `es`, `de`) via API do Claude com busca web e notas
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

- **Sensacionalismo vira desinformação com facilidade.** O Claude, com
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
ainda mais forte no CLAUDE.md sobre riscos. Não implementar sem
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
        │       ────►  API do Claude (HTTPS)
        │       ────►  API do TTS (HTTPS, provedor configurável)
        │       ────►  YouTube Data API v3 (opcional)
        │       ────►  Google Veo3 API (opcional, decidido por projeto)
        │       ────►  OpenCV + rembg (deteccao de rosto e remocao de
        │                fundo pra thumbnail, 100% local — Etapa 7)
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

Chama API do Claude (`claude-sonnet-5` padrão, configurável) com:
- Todas as transcrições dos vídeos-fonte como contexto principal
- Ferramenta server-side `web_search_20250305` habilitada (custo à
  parte: $10 por 1000 buscas, tokens normais adicionais) — resolvida
  automaticamente pela Anthropic dentro da mesma resposta, sem loop
  manual
- Ferramenta `youtube_top_titles` (client-side, `scripts/tools/youtube.py`
  — chama YouTube Data API v3 de verdade, se `YOUTUBE_API_KEY`
  configurada — filtro `relevanceLanguage` conforme idioma alvo)
- Prompt do sistema montado por `scripts/prompts/loader.montar_prompt(perfil, idioma)`
  (CLAUDE.md seção 3.1 — não um arquivo fixo `roteiro.md`; o bloco
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

### 5.4.1 — Validações pós-geração (Grupos A/B/C, não bloqueantes)

Padrão observado em produção: instrução de prompt (`sistema.md`) funciona
bem para uma decisão discreta antes de escrever (ex: a pergunta-promessa,
seção 5.4 regra 0), mas falha em pedir vigilância contínua ao longo de um
roteiro de 25-35k caracteres (nome próprio grafado errado por legenda
automática, número repetido sem re-derivar na segunda menção). A correção
para esse tipo de falha entra em **código, depois da geração**, nunca
adicionando mais regras a `sistema.md` — regras demais competem por
atenção com a Regra 0 (seção 5.4) e a estrutura por dívida que já
funcionam bem. Implementado em `scripts/3_gerar_roteiro.py`, roda sobre o
`roteiro_md` final (pós-expansão do Grupo E), grava avisos em
`job_metadata.json`, e **nunca bloqueia a geração nem corrige nada
sozinho** — a decisão fica com o humano na tela de revisão (seção 5.5,
CLAUDE.md seção 12).

- **Grupo A — nome não corroborado pelo resumo de pesquisa**
  (`detectar_nomes_suspeitos`): candidatos a nome próprio no roteiro
  (sequências de 2+ palavras capitalizadas, exceto títulos markdown e
  stopwords de início de frase) são comparados contra um corpus de texto
  construído a partir do resumo estruturado da fase 1 de pesquisa
  (`pessoas_envolvidas`, `fatos_verificados`, `cronologia`,
  `conflitos_entre_fontes`, `observacoes_editoriais`). **Atenção — não
  confundir com checagem factual/documental:** o corpus é o que o
  **próprio modelo** produziu resumindo sua pesquisa, não texto de fonte
  independente auditado por fora. A API de web search da Anthropic não
  expõe o texto bruto das páginas encontradas (`encrypted_content`,
  opaco) nem ele é persistido em lugar nenhum hoje, então o resumo
  estruturado é a aproximação mais fiel disponível sem adicionar fetch de
  página externo — mas continua sendo autorrelato do modelo, não uma
  fonte externa verificada. Por isso o texto exibido na tela (banner) é
  literal e deliberadamente modesto: **"Nome não corroborado pelo resumo
  de pesquisa; confirme em fonte escrita antes de aprovar."** — nunca
  linguagem que prometa auditoria documental. Nome ausente do corpus E
  sustentado só por nota de transcrição `[F#@mm:ss]` (sem nenhum
  `[N: ...]` junto) vira nível `alto` (único nível que aparece em
  destaque na tela); ausente do corpus mas sem nota ou com nota ambígua
  vira `medio` (fica só em `job_metadata.json`, não renderiza banner).
  Lugar/instituição (lista curta de palavras-chave) nunca é sinalizado.
- **Grupo B — título possivelmente divergente do núcleo editorial**
  (`detectar_titulos_divergentes`): `SCHEMA_SAIDA` ganhou o campo
  `nucleo_editorial` (2-8 palavras, gerado junto da pergunta-promessa —
  mais compacto que ela, pensado para orientar título). Título sem
  nenhum termo significativo em comum com o núcleo entra num aviso
  lexical simples (sem chamada de API extra). Primeira versão
  deliberadamente **só sinaliza, nunca regera** — regenerar por
  heurística lexical descartaria títulos bons; se o aviso se mostrar útil
  no uso real, uma sessão futura pode adicionar avaliação/regeração por
  chamada curta e estruturada.
  **Validação com reparo, nunca invalidação (Correção 1, sessão
  pré-thumbnail):** `nucleo_editorial` é obrigatório no schema, mas
  `_validar_saida_estruturada` **não** o verifica — um roteiro que
  custou dinheiro de API e saiu bom nunca é descartado por causa de um
  campo de metadado. Em vez disso, `_nucleo_editorial_valido` (string
  não vazia, 2-8 palavras) roda depois da validação principal; se
  inválido/ausente, UMA chamada curta e forçada (`entregar_nucleo_
  editorial`) tenta reparar só esse campo a partir da `pergunta_
  promessa` já aprovada — nunca regera o roteiro. `job_metadata.json`
  grava `nucleo_editorial_status`: `"ok"` (veio válido de saída),
  `"reparado"` (reparo funcionou) ou `"ausente"` (reparo falhou/indisponível
  — nunca silencioso: quando a Etapa 7/tela de thumbnail (seção 5.85)
  for construída para consumir `nucleo_editorial`, ela deve checar este
  status e avisar explicitamente que entrou em modo fallback — headline
  derivado da `pergunta_promessa` longa em vez do núcleo compacto).
- **Grupo C — número de duração citado sem derivação próxima**
  (`detectar_numeros_sem_derivacao`): escopo mínimo deliberado — só
  números de duração/janela temporal (nunca contagem/valor/distância
  genérico). Frase com número de duração cujas 2 frases anteriores (+ a
  própria) não contêm marcador de derivação (registros, horários,
  "based on"/"according to" e equivalentes em pt/es/de) entra no aviso.
  Cobertura de números por extenso limitada a inglês (idioma padrão do
  produto) — números por extenso em outros idiomas não são detectados
  (falso negativo silencioso, nunca falso positivo). Configurável via
  `VALIDACAO_NUMEROS_ATIVA` (seção 7) — desligar se gerar ruído demais.

Todos os 3 grupos são "aceitáveis com falso positivo, nunca com falso
negativo escondido" (mesmo espírito da seção 18) — bloquear geração por
causa de um falso positivo custaria mais do que vale, então nenhum dos
três impede aprovar o roteiro.

**Contagem de palavras narradas — uma única régua (Correção 3, sessão
pré-thumbnail):** `contar_palavras_narradas()` (`scripts/3_gerar_
roteiro.py`) é a **única** função canônica dessa métrica — usada pra
`ratio_tamanho`, decisão de expansão (Grupo E) e justificativa forçada.
A tela de revisão (`templates/revisao_roteiro.html`) exibe o valor
**persistido** em `job_metadata.palavras_narradas`, renderizado pelo
servidor — nunca recalcula (nem em JS no template, nem de novo no
`server.py`). `static/revisao.js` mantém só um contador de **caracteres**
live enquanto o usuário edita (`atualizarContador`, isso não tem métrica
canônica conflitante). Projeto sem `palavras_narradas` em
`job_metadata.json` (gerado antes desta métrica existir, ou roteiro
importado por upload) simplesmente omite esse trecho do contador — nunca
recalcula como fallback.

### 5.5 — Tela de revisão (implementada no server.py, não script)

Rota `/projetos/{id}/revisar_roteiro` mostra:

- Banners não-bloqueantes dos Grupos A/B/C (seção 5.4.1), quando
  aplicável — nome próprio sem confirmação (só nível `alto`), título
  possivelmente divergente do núcleo editorial, número de duração sem
  derivação próxima. Nenhum aviso → nenhum banner renderizado.
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
análise visual opcional via Claude Vision e deduplicação por pHash
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

1. **Análise de gaps.** Chamar API do Claude com a narração alinhada e
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

### 5.85 — `7_thumbnail.py` (Etapa 7 — geração de thumbnail)

Roda automaticamente depois da Etapa 6, com o processo do ffmpeg já
encerrado (não concorre por CPU). Entrada: `saida/video_final.mp4` (Etapa
6) + `roteiro_aprovado.md`. Saída: pasta `thumbnail/` com fotos de
sujeito enviadas, metadados/briefing e a thumbnail final escolhida pelo
usuário.

**Simplificação (sessão pós-Sessão 29).** Os 5 templates de composição
via Pillow (`scripts/thumbnail_templates.py`) foram **removidos por
inteiro** — resultado muito abaixo das referências reais do nicho em
teste real. Foram junto: o scan de frames de CENÁRIO
(`thumbnail/candidatos_cena/`, só alimentava o fundo dos templates) e o
recorte de sujeito via `rembg`/`opencv-python` (só produzia o PNG com
fundo removido que os templates colavam — a composição por IA manda a
foto ORIGINAL, sem recorte, direto pro modelo). O caminho validado e
único que resta: o Claude gera o **briefing exportável** (Grupo C), o
usuário edita o texto se quiser, e a **OpenAI compõe a thumbnail
completa** a partir do briefing + fotos dos sujeitos (Grupo H) — mesma
reconstrução da sessão pós-Sessão 26 preservada (upload de até 2 fotos
**declarando o papel de cada uma**, Vision nunca decide identidade, só
descreve atributos de uma foto cujo papel já é conhecido).

- **Grupo B — upload de sujeitos com papel declarado.** Dois slots
  (`hero`/`secondary`, o segundo opcional) em
  `thumbnail/sujeitos/sujeitos.json` (`{"hero": {"arquivo", "papel"},
  "secondary": {...}|null}`), cada um com papel obrigatório dentre
  `thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS` (vítima/suspeito/condenado/
  investigador/testemunha/outro). Sem recorte nenhum — a foto original
  salva em `thumbnail/sujeitos/` é o que a composição por IA usa direto
  (`atualizar_sujeito_slot`/`remover_sujeito_slot`, sem estado derivado
  em disco além do próprio `sujeitos.json`).
- **Grupo C — briefing exportável.** `scripts/thumbnail_briefing.py`
  monta `thumbnail.briefing_completo` — um prompt em INGLÊS pronto pra
  colar em qualquer gerador de imagem, combinando o headline vencedor +
  o **conceito visual** (ambos do Headline Engine — seção 5.86),
  papéis/atributos dos sujeitos enviados (atributos vêm de UMA chamada
  Vision leve por foto — framing/expressão/gênero/faixa etária, **nunca
  decide identidade**, com fallback determinístico por papel sem chave)
  e um dos **6 templates de composição** — escolhido por chamada
  dedicada com enum fechado ao subconjunto que os papéis disponíveis
  permitem (`templates_elegiveis`), recebendo o conceito visual como
  contexto adicional na mesma chamada (GRUPO H — zero chamadas novas),
  ou **forçado manualmente pelo usuário** na tela (`template_forcado` em
  `selecionar_template`/`gerar_briefing_completo` — ignorado em silêncio
  se fora do conjunto elegível pro estado atual de sujeitos, nunca confia
  só no frontend). Fallback determinístico `EVIDENCE_SCENE` se a chamada
  de seleção falhar. Os 6 templates — `ARROW_TRIO` (dois sujeitos + seta,
  relação de acusação), `PROFILE_ISOLATION` (um sujeito, local do caso),
  `EVIDENCE_SCENE` (sem sujeito em destaque), `DUOTONE_DOSSIER` (retrato
  + grid opcional de evidência), `INVESTIGATOR_UPDATE` (vítima/sujeito +
  investigador, bom pra atualização de caso) e `DUAL_PORTRAIT` (dois
  sujeitos sem relação de acusação/autoridade/mesmo papel entre eles,
  ex: vítima + familiar) — texto completo de cada
  `montar_prompt_<template>` em `scripts/thumbnail_briefing.py`, não
  duplicado aqui. Todos os 6 chamam `montar_clausula_conceito_visual`
  (seção 5.86) pra incorporar o conceito — cada um com sua própria
  estética de composição, nunca o mesmo texto duas vezes.

  **Elegibilidade por PAPEL — `EVIDENCE_SCENE` nunca elegível com foto
  enviada (correção da sessão de simplificação).** `templates_elegiveis`
  decide por CATEGORIA de papel (vítima/suspeito-condenado/investigador),
  nunca só por hero/secondary presentes. Tabela: sem hero, só
  `EVIDENCE_SCENE` (único caso sem foto nenhuma pra aproveitar); só hero,
  `PROFILE_ISOLATION`/`DUOTONE_DOSSIER`; vítima+investigador trava em
  `INVESTIGATOR_UPDATE` (único elegível de propósito — não há ambiguidade
  genuína, nem chama a API); vítima+suspeito/condenado oferece
  `ARROW_TRIO`/`DUOTONE_DOSSIER` (seta de acusação); hero e secondary com
  o MESMO papel (ex: duas vítimas do mesmo autor) trava em
  `DUOTONE_DOSSIER` com grid ativado (só faz sentido representando
  MÚLTIPLOS sujeitos do mesmo papel); combinação sem relação clara (ex:
  testemunha+outro) cai no retrato solo do hero
  (`PROFILE_ISOLATION`/`DUOTONE_DOSSIER`). `EVIDENCE_SCENE` **nunca**
  aparece em nenhuma tabela onde `hero_papel` existe — achado real: um par
  vítima+investigador chegou a ter `EVIDENCE_SCENE` elegível e escolhido,
  e a thumbnail saiu sem nenhum dos dois rostos apesar das fotos
  disponíveis. Papel cru (PT-BR) nunca entra em texto de prompt em
  inglês — `_papel_em_ingles` traduz em toda frase que menciona o papel
  diretamente.

  A linha GRANDE de `ARROW_TRIO`/`PROFILE_ISOLATION`/`EVIDENCE_SCENE`/
  `DUOTONE_DOSSIER`/`DUAL_PORTRAIT` (via `_linha_pequena_e_grande` — 5 dos
  6 templates; `INVESTIGATOR_UPDATE` é o único que não usa esse helper,
  pendência registrada em `MELHORIAS_PENDENTES.md`) é sempre o headline do
  Headline Engine, nunca `subject_name`/nome do caso — headline
  ausente/vazio faz `gerar_briefing_completo` devolver `{"sucesso": False,
  "erro": "headline_ausente"}` (a rota dedicada
  `/thumbnail/gerar_briefing` repassa esse erro pra tela em vez de fingir
  sucesso com um briefing incompleto). Regra de segurança: a tarja de
  censura de rosto (só no
  `ARROW_TRIO`) só é aplicada quando `thumbnail.censor=True` **E** o papel
  do secondary é suspeito/condenado — nunca para vítima/investigador/
  testemunha/outro, mesmo com `censor=True`. Regra de conteúdo: as
  descrições de pessoa (`descrever_pessoa_para_prompt`) nunca contêm nome
  próprio — só papel + atributos visuais genéricos; o nome real só entra
  no texto tipográfico do prompt (`subject_name`/`headline`), nunca como
  instrução de geração de rosto. Funciona **100% sem nenhuma API de
  imagem configurada** — é a entrega que sempre funciona pra uso externo
  (copiar/colar em qualquer outro gerador). Persiste
  `thumbnail/briefing.json` (auditoria completa: template escolhido +
  motivo, atributos por foto, decisão de censura, texto final).
- **Grupo D — metadados.** Chamada única (não-streaming, `tool_choice`
  forçado) usando `roteiro_aprovado.md` como input, produz descrição,
  tags, e o briefing de composição da thumbnail (`subject_name`,
  `headline`, `emphasis_word`, `secondary`, `accent`, `censor`,
  `background_prompt` — `layout`/`style` saíram do schema na sessão de
  simplificação, só serviam aos templates Pillow removidos). **Ordem
  (sessão "conceito visual" — seção 5.86): o Headline Engine roda
  PRIMEIRO agora**, antes desta chamada — `headline_engine.gerar_headline`
  produz o `headline` e o conceito visual; o `elemento_principal`
  extraído vira a âncora obrigatória do `background_prompt` desta chamada
  (`elemento_principal` passado pra `_chamar_claude_metadados`).
  `headline`/`emphasis_word` que vêm desta chamada única servem só de
  FALLBACK — `_mesclar_headline_em_thumbnail` sobrescreve com o resultado
  do Headline Engine quando ele teve sucesso, senão preserva o que veio
  daqui (CLAUDE.md seção 18.4). **Nunca
  gera título** (sessão "título canônico", achado real Burke
  Ramsey/JonBenét — ver `HISTORICO_BUGS.md`): o título do vídeo já foi
  escolhido pelo usuário na revisão do roteiro (Etapa 3/seção 5.5) e é a
  única fonte de verdade downstream. `thumbnail/metadados.json` persiste
  `titulo_escolhido` (lido de `titulo.txt`, nunca gerado) e
  `titulos_alternativos` (as outras 2 opções de `titulos_sugeridos.json`
  não escolhidas pelo usuário — só referência editorial, nunca
  candidatas a substituir a escolha). `reconciliar_titulos_com_headline`
  roda sobre `titulo_escolhido` contra o headline final só como
  AUDITORIA (`titulo_headline_reconciliacao`) — nunca sobrescreve o
  título, que é soberano. Persiste `thumbnail/metadados.json` com hash
  do roteiro usado, e em seguida já dispara o Grupo C automaticamente
  (`_aplicar_briefing_grupo_c`) — o briefing nasce junto dos metadados,
  mesmo que ainda sem fotos (usa `EVIDENCE_SCENE`). Rota dedicada
  `/projetos/{id}/thumbnail/gerar_briefing` (`gerar_briefing_thumbnail`,
  aceita `template` opcional) reroda só o Grupo C a qualquer momento, sem
  gastar uma chamada nova de Grupo D — usada depois que o usuário troca
  um upload de sujeito ou escolhe outro template manualmente.
- **Grupo G — tela de revisão.** `/projetos/{id}/thumbnail`: dois slots
  de upload de sujeito com papel, bloco de briefing exportável — **único
  campo de texto editável da tela** (textarea + seletor manual de
  template, pré-selecionado com a sugestão do sistema e indicado como tal
  + copiar + download das fotos + botão "Regenerar dados automáticos"
  pra refazer headline/subject_name/etc via nova chamada). Não há mais
  campos estruturados separados (headline/accent/layout/style/censor)
  editáveis na tela — só o texto do briefing.

**Grupo H — composição completa por IA.**
`scripts/imagem/openai.gerar_composicao(briefing_completo, caminhos_fotos,
output_path)` manda `thumbnail.briefing_completo` (Grupo C, com edição
manual do usuário se houver) + as fotos ORIGINAIS dos sujeitos
(`thumbnail/sujeitos/*`, sem recorte nenhum) como `image[]` pro endpoint
`/v1/images/edits` do `gpt-image-2`, na ordem hero-primeiro/
secondary-depois. `input_fidelity` NUNCA é enviado — não é um parâmetro
ajustável nesse modelo especificamente (a API processa toda imagem de
entrada em alta fidelidade automática) — é isso que **preserva** o rosto
da foto anexada, e é também o que **mais aciona a recusa por moderação de
deepfake** (`gpt-image-2` tem sistema de segurança reforçado contra
imagens fotorrealistas de pessoa real identificável). Pede `size`
customizado `"1536x864"` (16:9 exato — a API aceita `size` customizado no
`gpt-image-2`, ambas as dimensões múltiplas de 16, proporção entre 1:3 e
3:1) e nunca recorta/redimensiona os bytes devolvidos — a imagem final
nasce 16:9 nativa. `INSTRUCAO_AREA_SEGURA_16_9` continua anexada ao
prompt só na chamada de API (nunca ao `briefing_completo` persistido) pra
pedir margem generosa nas bordas pro headline/texto. Toda falha (sem
chave, sem fotos, sem briefing, rede, recusa de moderação, resposta sem
imagem) devolve `erro_tipo`/`erro_mensagem`/`status_http` REAIS (nunca
string genérica) e persiste em `thumbnail/composicao_status.json`
(`ler_status_composicao`) — sobrevive a um recarregamento de página.

**Composições acumulam, nunca se sobrescrevem (Grupo D/E da sessão de
simplificação).** Cada clique em "Gerar thumbnail pela OpenAI" (ação
sempre explícita, botão só habilitado com `OPENAI_API_KEY` configurada,
nunca automática — cada clique custa uma chamada real) grava num arquivo
SEQUENCIAL em `thumbnail/previews/` (`composicao_ia_01.jpg`, `_02.jpg`,
...) — `server.py:_proximo_arquivo_composicao`/
`_listar_composicoes_thumbnail` (única fonte de verdade de quais arquivos
existem, usada tanto pro `GET /thumbnail` popular o grid — mesmo sem
geração nesta sessão de página — quanto pelas rotas de escolher/excluir
validarem o nome recebido do cliente contra o disco). Rota
`POST /thumbnail/excluir_composicao` descarta uma composição que não
presta; `POST /thumbnail/escolher_composicao` (Body `{"arquivo": ...}`)
copia a escolhida pra `thumbnail/final.jpg` e conclui o job — substitui a
antiga `escolher_template`, que validava contra nomes de template Pillow
fixos.

**Nunca falha o pipeline por falta de `ANTHROPIC_API_KEY`** (mesmo
espírito da seção 18.4): sem a chave, os Grupos C e D caem em fallback
determinístico (nunca bloqueiam) e o projeto pausa em
`aguardando_thumbnail` com o vídeo final já pronto, esperando escolha
manual na tela do Grupo G. **`OPENAI_API_KEY` é obrigatória pra marcar
"Gerar thumbnail" no formulário de Novo projeto** (validado em
`server.py:/novo`, checkbox desabilitado no client sem a chave) — sem
ela, o Grupo H nunca produziria imagem nenhuma. Projeto já existente com
a flag ligada e sem chave (ex: criado antes desta checagem, ou pelo
caminho `videos_pre_gerados`, que não tem este checkbox) não quebra: a
Etapa 7 só informa a ausência da chave na tela, e o briefing continua
disponível pra uso externo.

**Validação pós-geração por Vision** (conferir automaticamente se a
composição bate com o template pedido) **continua PLANEJADA, NÃO
IMPLEMENTADA** — ver `MELHORIAS_PENDENTES.md`.

### 5.86 — Headline Engine v2 + conceito visual (`scripts/headline_engine.py`)

Substitui a geração do `headline` da thumbnail, que até a v1 saía na
MESMA chamada de `entregar_metadados` (Grupo D acima) junto de
`subject_name`/descrição/tags. Diagnóstico que motivou a v1: preencher o
headline no mesmo turno que campos factuais do caso faz o modelo aplicar
viés de sumarização e devolver o fato mais saliente em vez de uma lacuna
de curiosidade. Diagnóstico que motivou a v2 (caso real
jonBenetRamsey01/Burke Ramsey): a v1 perguntava "qual headline descreve
melhor o conteúdo" — mesmo com few-shot contrastivo, os 6 candidatos
convergiam em reformulações da MESMA ideia em vez de ângulos
genuinamente distintos. A pergunta certa é outra: "qual elemento pode
ser PARCIALMENTE revelado pra criar a maior curiosidade restante" — quase
nunca é a conclusão central do vídeo (revelar a conclusão fecha a
curiosidade antes do clique). Pesquisa sobre 8.977 experimentos reais de
headline (Aubin Le Quéré & Matias, *Scientific Reports* 15:994, 2025)
mostra relação curvilinear entre concretude e taxa de clique — vago
demais ("THE TRUTH REVEALED") e concreto demais performam pior que o
meio do caminho, por isso o juiz (Grupo C(juiz) abaixo) pesa "abre
lacuna" e "ancorado neste caso" igualmente.

`gerar_metadados` e `regenerar_thumbnail_briefing` (`scripts/
7_thumbnail.py`) chamam `headline_engine.gerar_headline(...)` **ANTES**
da chamada única de metadados agora (seção 5.85, Grupo D — ordem
invertida na sessão "conceito visual"), passando o `elemento_principal`
extraído como âncora obrigatória do `background_prompt` daquela chamada.
`headline`/`emphasis_word` que vêm da chamada única de metadados servem
só de FALLBACK — `_mesclar_headline_em_thumbnail` sobrescreve com o
resultado do Headline Engine quando ele teve sucesso, senão preserva o
que veio de lá (CLAUDE.md seção 18.4).

- **Grupo A — extração editorial** (`extrair_payload_editorial`).
  Chamada dedicada, tool forçada, isola o `payload` (o elemento certo pra
  revelar em parte) da `conclusao_central` (o que o vídeo conclui — nunca
  revelada nem em parte), a partir do `nucleo_editorial`/`pergunta_
  promessa`/título aprovado/roteiro completo. Prompt em `scripts/prompts/
  headline_engine_payload.md`. Falha cai em `_payload_fallback` (deriva
  do núcleo editorial, marcado `fallback: True`) — nunca bloqueia o
  pipeline.

  **Conceito visual (camada nova, MESMA chamada — zero custo de API
  extra).** A mesma resposta também entrega `elemento_principal` (o
  elemento visual concreto que a thumbnail precisa mostrar —
  `camera_filmagem` existe como tipo separado de `objeto` de propósito:
  achado real do caso da câmera de campainha/tatuagem no pulso, sem essa
  categoria explícita a câmera colapsava em "objeto" genérico e a
  composição perdia a cena inteira em cima dela), `tipo_elemento`
  (enum: `pessoa`/`objeto`/`documento`/`camera_filmagem`/`local`/`outro`),
  `acao_ou_momento` (opcional), `revelacao` (opcional, só faz sentido com
  `acao_ou_momento` preenchido — `_normalizar_conceito_visual` zera os
  dois juntos se um estiver vazio, nunca persiste uma revelação órfã) e
  `papel_na_composicao` (`dominante`/`apoio`). Substitui por inteiro o
  mecanismo antigo de `evidencia_central`/`conflito`/`data_chave` (que
  vivia no Grupo D — `scripts/7_thumbnail.py` — e era injetado de volta
  como cabeçalho no roteiro entregue ao Headline Engine, dependência
  circular removida na sessão "conceito visual"). Validado empiricamente
  contra a API real no caso Nancy Guthrie — recuperou corretamente
  "the doorbell camera and the suspect's wrist as he reaches to block the
  lens" / "the masked figure reaching up with a branch to block the
  doorbell camera lens" / "the blocking motion rotates his wrist into
  frame, exposing a tattoo on the underside of his right wrist" a partir
  só do roteiro, sem cabeçalho nenhum.
- **Grupo B — candidatos por mecanismo** (`gerar_candidatos_headline`).
  Chamada dedicada, tool forçada, recebe o `payload_editorial` inteiro da
  Grupo A e pede 6 candidatos (`headline`/`mechanism`/`withheld_fact`/
  `emphasis_word`) com mecanismos DIFERENTES (tempo/número/objeto/
  informação_retida/contradição/reversão/consequência/institucional/
  evidência/mistério_aberto — pelo menos 4 distintos entre os 6, pedido no
  prompt, nunca um gate de código). Prompt em `scripts/prompts/
  headline_engine_candidatos.md`.
- **Grupo B(filtros) — filtros determinísticos de FORMATO**
  (`filtrar_candidatos_deterministicos`). Roda em código, sem chamada de
  API: mais de 6 palavras, substring/alta sobreposição de tokens (>60%)
  com o título aprovado, não cabe na área segura (320px, quebrando em até
  2 linhas) medida com a fonte real (Anton-Regular.ttf + `textbbox`,
  nunca estimativa — helpers de fonte duplicados dentro do próprio
  `headline_engine.py`), `emphasis_word` que não aparece literalmente no
  headline, termo da lista de risco configurável (`HEADLINE_TERMOS_
  RISCO`, `.env` — lista NÃO deriva do roteiro nem de nada publicado pelo
  YouTube, é só proteção editorial). Candidato eliminado é persistido com
  o motivo, nunca descartado em silêncio.
- **Grupo C(rejeição) — filtros determinísticos SEMÂNTICOS**
  (`filtrar_candidatos_semanticos`). Rodam depois dos filtros de formato,
  ainda antes do juiz: eliminam pergunta respondível com sim/não ("DNA
  excluded him?"), candidato sem mecanismo identificável, candidato
  sustentado só por palavra genérica de risco (SHOCKING/BOMBSHELL/TRUTH/
  SECRET) sem termo concreto, e candidato cujo `withheld_fact` não
  compartilha nenhum termo com o payload/fatos extraídos da Grupo A
  (afirmação não sustentada). Cobertura deliberadamente em inglês (mesmo
  espírito da seção 5.4.1 Grupo C — falso negativo silencioso em outros
  idiomas, nunca falso positivo).
- **Grupo C(juiz) — juiz** (`julgar_candidatos`). Chamada separada, só
  avalia — nunca reescreve nem sugere. Rubrica de **7 critérios** (0-2
  cada, `scripts/prompts/headline_engine_juiz.md`): `opens_gap`,
  `anchored_to_case`, `not_title_repeat`, `not_revealing`, `answer_leak`
  (novo na v2 — olha título+headline JUNTOS contra a `conclusao_central`
  do caso inteiro, mais forte que `not_revealing` sozinho), `concise_
  impact`, `visualizable`. Vence quem tem `opens_gap`≥1 E `anchored_to_
  case`≥1 E `answer_leak`≥1 (os três critérios-PORTA — zerar qualquer um
  desqualifica, mesmo com soma alta nos outros) com total ≥ 9/14; empate,
  o mais curto. **Não passa `temperature`** (a Claude Sonnet 5 tem
  pensamento adaptativo ligado por padrão e devolve 400 pra qualquer
  parâmetro de sampling explícito — achado real, `headline_engine.json`
  com `julgamentos: null` nas duas rodadas de um projeto real). Falha de
  chamada persiste tipo/mensagem/status HTTP reais (`_detalhar_excecao`).
- **Grupo D — regeneração.** No máximo 1 rodada extra (2 no total) com o
  feedback do juiz (ou dos filtros, se ninguém sobreviveu) da rodada
  anterior. Grupo A roda só UMA vez, nunca repetida na regeneração. Se as
  duas rodadas falharem, persiste o melhor candidato disponível e marca
  `aviso_revisao_humana` — nunca falha o pipeline por causa do headline.
  **Falha do juiz (erro de infraestrutura) NUNCA dispara uma rodada extra
  de geração** — gastaria uma segunda chamada de Grupo B inteira à toa,
  sem chance de resolver um problema que está no juiz. Quando o vencedor
  final nunca foi avaliado por ninguém, `fallback_sem_julgamento=True` —
  campo separado de `aviso_revisao_humana`, com banner próprio na tela de
  thumbnail.
- **Grupo E — persistência.** `thumbnail/headline_engine.json` grava as
  TRÊS etapas separadas: `payload_editorial` (Grupo A, uma vez — inclui
  `conceito_visual`), `rodadas[]` (candidatos/eliminados/sobreviventes de
  Grupo B/C(rejeição) e julgamentos de Grupo C(juiz) por rodada) e o
  vencedor final — auditoria completa pra diagnosticar depois onde um
  resultado ruim se originou.
- **Grupo F — modo degradado.** Se `nucleo_editorial_status`
  (`job_metadata.json`, seção 5.4.1) for `"ausente"` (ou o campo não
  existir), uma chamada extra (`extrair_nucleo_compacto`) deriva um
  núcleo compacto da `pergunta_promessa` ANTES da Grupo A — duas etapas,
  nunca uma só silenciosa. A tela de thumbnail avisa explicitamente
  (banner) quando `fallback_usado` ou `aviso_revisao_humana` estão
  ativos.

Campos persistidos em `thumbnail/metadados.json` → `thumbnail`:
`mechanism`, `withheld_fact`, `judge_score`, `conceito_visual`,
`conceito_visual_ausente` (`validar_consistencia_headline_conceito`,
código puro em `scripts/7_thumbnail.py` — `True` quando `elemento_
principal` veio vazio, substitui o antigo `eixo_editorial_ausente`),
`nucleo_editorial_status`, `fallback_usado`, `aviso_revisao_humana`,
`fallback_sem_julgamento`. Não editáveis pela tela — preservados como
estão se o usuário editar o headline/briefing manualmente; a auditoria
completa sempre fica em `headline_engine.json`.

**Idioma explícito:** `extrair_payload_editorial`, `gerar_candidatos_
headline` e `extrair_nucleo_compacto` recebem o idioma do projeto (lido
de `job_metadata.json.idioma`, com fallback pra `IDIOMA_ROTEIRO`/`en-US`)
como diretiva explícita no corpo da mensagem, nunca inferido
implicitamente do conteúdo — achado real: com instrução implícita,
`withheld_fact`/`nucleo_editorial` saíram inconsistentes entre idiomas
pro MESMO roteiro en-US.

**Consumo do conceito visual pelo briefing (Grupo C da Etapa 7 —
`scripts/thumbnail_briefing.py`, sessão "conceito visual" Parte 2):**

- **`montar_clausula_conceito_visual(conceito)`** — função PURA (mesmo
  padrão de `_linha_pequena_e_grande`) que monta a cláusula em CÓDIGO,
  nunca pede à IA como texto livre (mesma classe de bug já conhecida no
  módulo — `_ajustar_genero_e_prefixo_para_crianca` existe porque texto
  livre concatenado sem checar a relação entre campos produz frases
  incoerentes). Transporta a cadeia causal completa — elemento → ação →
  revelação — nunca só os 3 campos soltos lado a lado. Todos os **6**
  `montar_prompt_<template>` chamam essa função.
- **Prioridade semântica sobre o `background_prompt`**
  (`_frase_dominancia_conceito`) — o conceito e o fundo NUNCA se
  substituem (perderia contexto visual): `papel_na_composicao ==
  "dominante"` faz o conceito ocupar o centro da composição (vem
  primeiro no texto, fundo subordinado, mencionado depois como pano de
  fundo secundário); `"apoio"` (padrão) mantém o fundo como âncora
  primária, com o conceito entrando como detalhe concreto dentro da
  cena.
- **Seleção de template** (`selecionar_template`) recebe um resumo do
  conceito visual como contexto ADICIONAL na mesma chamada que já
  existia (`templates_elegiveis` continua decidindo por categoria de
  papel — questão de layout; o conceito ajuda a escolher qual estética,
  dentro do enum já fechado, narra melhor aquele elemento) — **zero
  chamadas novas de API**.
- **`resolver_relacao_com_sujeitos`** decide, só quando há ambiguidade
  real (2 sujeitos com papéis distintos), a qual sujeito o elemento
  pertence — `None` (fallback seguro) em qualquer outro caso.
- Persistência: o conceito visual BASELINE (extraído pela Grupo A, antes
  de qualquer sujeito existir) fica em `thumbnail/metadados.json` →
  `thumbnail.conceito_visual`; a parte SUBJECT-DEPENDENT
  (`relacao_com_sujeitos`) fica em `thumbnail/briefing.json`. Projeto sem
  `conceito_visual` (antigo, ou Grupo A falhou) nunca quebra — a cláusula
  fica vazia e os templates se comportam como antes desta feature
  existir. Na tela (`/projetos/{id}/thumbnail`), o conceito aparece como
  **bloco de leitura** acima do textarea do briefing — sem campo
  editável próprio; a fonte canônica editável continua sendo o
  `briefing_completo`.

**Pendência conhecida (não corrigir sem decisão explícita):**
`montar_prompt_investigator_update` é o único dos 6 montadores que não
usa `_linha_pequena_e_grande` (usa `headline`/`emphasis_word` direto,
numa linha só com duas cores — ver Correção 1 do histórico).

**Fora de escopo desta versão** (near-term, não implementar sem pedido
explícito): segundo sujeito/upload de sujeito secundário além dos 2
slots já existentes, integração com Analytics API pra medir CTR real do
headline escolhido, simulação competitiva contra títulos/thumbnails de
concorrentes.

### 5.9 — Tela de conclusão

Rota `/projetos/{id}/concluido` (reconstruída na Sessão 29) reúne tudo
que o projeto produziu, **somente leitura** — trocar thumbnail, regerar
briefing ou editar textos continua sendo só na Etapa 7
(`/projetos/{id}/thumbnail`), quantas vezes o usuário quiser; chegar em
"concluído" não bloqueia voltar lá, mas esta tela em si não expõe
nenhuma ação de mutação:

- Preview do vídeo final embarcado + botão de download
- Thumbnail final (`thumbnail/final.jpg`) em tamanho legível + download
  (se o projeto tiver uma — `gerar_thumbnail=False` ou projeto antigo
  simplesmente não renderiza esta seção, nunca quebra a tela)
- Título escolhido pelo usuário na revisão (`titulo.txt`, canônico —
  sessão "título canônico", ver `HISTORICO_BUGS.md`) com botão de copiar,
  seguido das opções da Etapa 3 não escolhidas (`titulos_sugeridos.json`)
  como referência, claramente marcadas como não utilizadas — a tela
  NUNCA gera nem exibe um conjunto de título concorrente
- Descrição completa e tags (`thumbnail/metadados.json`), cada bloco com
  botão de copiar
- Dados do projeto: perfil (`job.json.perfil`), duração
  (`saida/montagem_metadata.json.tempo_total_s`, fallback
  `narracao_alinhamento.json.duracao_s`), custo total **estimado**
  (`_calcular_custo_total_projeto`, server.py — soma best-effort de
  `job_metadata.json`/`narracao_metadata.json`/
  `thumbnail/headline_engine.json`/todo `*.custo.json` em `thumbnail/`;
  não é um total exato — ver `MELHORIAS_PENDENTES.md`)
- Link "abrir pasta do projeto no Explorer"

Todo campo é best-effort — nenhum é obrigatório pra tela renderizar sem
erro. A Home (`home.html`) já abre um projeto com `status == "concluido"`
direto nesta tela em vez de `/status/{id}`.

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
  thumbnail/                  # Etapa 7, secao 5.85
    sujeitos/
      hero.<ext>               # foto ORIGINAL enviada pro slot principal (sem recorte)
      secondary.<ext>          # foto ORIGINAL enviada pro slot secundario (opcional)
      sujeitos.json             # {"hero": {"arquivo","papel"}, "secondary": {...}|null}
    metadados.json            # titulo_escolhido (de titulo.txt, nunca gerado)/titulos_alternativos/descricao/tags/briefing (Grupo D) + hash do roteiro
    briefing.json              # auditoria completa do Grupo C (thumbnail_briefing.py)
    headline_engine.json      # auditoria completa do Headline Engine (secao 5.86)
    composicao_status.json    # resultado da ULTIMA tentativa de composicao por IA (Grupo H, secao 5.85)
    previews/                 # composicoes acumuladas por IA (composicao_ia_01.jpg, _02.jpg, ...) - nunca sobrescritas
    final.jpg                 # composicao escolhida pelo usuario (Grupo G/H) - copia de um arquivo de previews/
  logs/
    etapa1_download.log
    ...
```

O `roteiro.md` (gerado pela IA) e o `roteiro_aprovado.md` (versão final
editada pelo humano) são separados. Preservar os dois pra auditoria.

Não existem mais `plano_edicao.json`, `clipes_veo3/`, `montagem/plano.json`,
`legendas/legenda.ass` nem `opcoes_veo3.json` — eram contratos de
arquiteturas de pipeline já abandonadas (ver seção 5.7 pro histórico de
detecção de cena/Veo3 enrichment). Também não existem mais
`thumbnail/candidatos_rosto/` nem `thumbnail/identificacao_vision.json` —
contratos da identificação por Vision sobre frame de clipe, removida na
reconstrução da Etapa 7 (seção 5.85). E, desde a sessão de simplificação
da Etapa 7 (mesma seção), não existem mais `thumbnail/candidatos_cena/`,
`thumbnail/sujeito_origem.json`, `thumbnail/sujeito.png|.jpg` nem
`thumbnail/sujeito_secundario.png|.jpg` — contratos do scan de cenário e
do recorte de sujeito que só serviam aos 5 templates de composição via
Pillow (`scripts/thumbnail_templates.py`), removidos junto.

## 7. Configuração — `.env` e tela de ajustes

| Variável | Obrigatória? | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | sim | Chave API Claude |
| `ANTHROPIC_MODEL` | não | Default `claude-sonnet-5` |
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
| `VALIDACAO_NUMEROS_ATIVA` | não | Default `true`. Liga/desliga a validação pós-geração de números de duração sem derivação próxima (seção 5.4.1, Grupo C) — desligar se a heurística gerar ruído demais no uso real |
| `HEADLINE_TERMOS_RISCO` | não | Default embutido no código (lista curta). Termos (separados por vírgula) que eliminam um candidato de headline no Headline Engine (seção 5.86, Grupo B) antes do juiz — configurável, não deriva do roteiro nem de nada publicado pelo YouTube, é só proteção editorial |
| `GERAR_THUMBNAIL_PADRAO` | não | Default `true`. Pré-marca o checkbox "Gerar thumbnail" no formulário de Novo projeto (editável por projeto ali mesmo) — só pode ser marcado com `OPENAI_API_KEY` configurada (seção 5.85) |

Removidas desta tabela por não corresponderem a nenhum código real:
`ESTRATEGIA_CORTE`, `CLIPE_MIN_S`, `CLIPE_MAX_S`, `CLIPE_TOLERANCIA_S`
(a Etapa 5 não tem mais estratégia configurável de corte — seção 5.7),
`VEO3_QUALIDADE_PADRAO`/`VEO3_QUANTIDADE_PADRAO`/`VEO3_CACHE_DIR`/`GOOGLE_API_KEY`
(documentavam a implementação de Veo3, nunca construída — seção 5.75,
sem leitura de env var nenhuma no código hoje), `CURADORIA_SEMANTICA`
(obsoleta desde a Sessão 11, não é mais lida nem persistida pela tela de
Ajustes), `IMAGEM_PROVEDOR_PADRAO` (documentava o provedor de FUNDO
`scripts/imagem/nenhum.py`/`gerar()`, removido junto dos templates Pillow
na sessão de simplificação da Etapa 7 — seção 5.85; a composição por IA
hoje é sempre via `gpt-image-2`/`gerar_composicao`, sem escolha de
provedor) e `LEGENDA_COR`/`LEGENDA_CONTORNO_COR`/`LEGENDA_CONTORNO_ESPESSURA`/
`LEGENDA_DESTAQUE_PALAVRA`/`LEGENDA_DESTAQUE_COR` (nomes antigos — ver
`LEGENDA_KARAOKE_ATIVO`/`LEGENDA_DESTAQUE_COR_NOME` acima).

**Tela de ajustes (`/ajustes`)** edita subset via formulário e persiste
no `.env`. Editável pela tela: PROJETOS_DIR, ANTHROPIC_API_KEY,
ANTHROPIC_MODEL, IDIOMA_ROTEIRO, WHISPER_MODEL, KEN_BURNS,
CLIPE_DURACAO_MIN_S, CLIPE_DURACAO_MAX_S, TTS_PROVEDOR_PADRAO,
TTS_VOZ_PADRAO, GOOGLE_TTS_API_KEY, DARKPLANNER_API_KEY,
ELEVENLABS_API_KEY, OPENAI_API_KEY, AZURE_TTS_KEY, AZURE_TTS_REGION,
YOUTUBE_API_KEY, WEB_SEARCH_MAX, COTACAO_USD_BRL, MUSICA_VOLUME_BASE,
GERAR_THUMBNAIL_PADRAO, e todos os `LEGENDA_*`. Resto só editando `.env`.

Override por projeto na tela de revisão: origem do áudio (TTS/upload/
pausar), se TTS provedor e voz específicos, e música de fundo. Override
por projeto no formulário de novo projeto: perfil de conteúdo
(obrigatório), idioma (opcional), marca d'água por fonte (opcional),
tipo de uso por fonte e upload direto de mídia visual (opcional — modo
de fontes separadas, seção 5.7.2).

## 8. Testes

Toda função nova vem com teste. Nenhuma etapa é considerada pronta sem
`pytest` verde. Enforçado por:

1. `CLAUDE.md` (regra explícita aqui)
2. Subagentes `test-writer` e `test-runner` em `.claude/agents/` —
   ver arquivos
3. Hook `PostToolUse` opcional em `.claude/hooks/`

**Convenções:**

- `tests/conftest.py` com fixtures compartilhadas
- Nunca chamar API real do Claude/TTS/YouTube em teste — mockar
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

**Toda sessão termina registrando o que fez.** Ao final de qualquer
sessão que corrija bug ou mude comportamento do produto, registrar a
correção em `HISTORICO_BUGS.md` e qualquer item deixado em aberto em
`MELHORIAS_PENDENTES.md` — sem esperar instrução explícita no prompt
da sessão para fazer isso. Não vale para sessões puramente
exploratórias (leitura de código, resposta a pergunta) que não mudaram
nada.

## 10. Estrutura de pastas do projeto de código

```
broll_foundry/
  server.py                   # Flask, roteia, dispara subprocess
  requirements.txt
  .env.example                # sem valores reais, com comentários
  iniciar.bat                 # cria venv, instala, roda server
  LEIAME.md                   # instalação + uso pro usuário final
  CLAUDE.md                   # este arquivo
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
    criar_atalho.py               # cria atalho na area de trabalho (secao 18.3)
    verificar_servidor.py        # checa porta/aguarda boot/abre navegador (secao 18.3.1)
    watermark_regions.py         # coordenadas de delogo por posicao (secao 5.7.1)
    warnings_traducoes.py        # traducao de avisos exibidos ao usuario
    erros.py                     # DEAD CODE - ver MELHORIAS_PENDENTES.md, referencia arquitetura removida
    1_baixar_videos.py
    2_transcrever.py
    3_gerar_roteiro.py
    4_obter_audio.py
    5_gerar_clipes.py            # geracao de clipes por selecao aleatoria (secao 5.7)
    6_montar_video.py            # concat + mux + legendas + musica (secao 5.8)
    7_thumbnail.py               # geracao de thumbnail - Grupos B/D (secao 5.85)
    thumbnail_briefing.py        # briefing exportavel - Grupo C (secao 5.85)
    headline_engine.py           # Headline Engine v2 - headline + conceito visual (secao 5.86)
    imagem/
      __init__.py
      openai.py                 # composicao completa via gpt-image-2 - Grupo H (secao 5.85)
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
    thumbnail.html             # tela de revisao da thumbnail - Grupo G (secao 5.85)
    concluido.html
    sobre.html                # tela "sobre" (ver seção 16)
  assets/
    fonts/
      Anton-Regular.ttf         # fonte real usada pelo filtro de encaixe tipografico do Headline Engine (secao 5.86)
  static/
    design_system.css         # design system Nocturne (Sessao 14, substituiu o tema escuro antigo)
    style.css
    ajustes.js
    novo_projeto.js
    status.js                 # polling do estado
    revisao.js                # editor + player de trecho de fonte
    thumbnail.js               # upload de sujeitos + briefing + composicao por IA - Grupo G (secao 5.85)
  tests/
    conftest.py
    test_*.py
  .claude/
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
`assets/cv/haarcascade_frontalface_default.xml` também não existe mais —
a detecção de rosto via Haar cascade da Etapa 7 foi removida na
reconstrução pós-Sessão 26 (seção 5.85), junto com o `cv2.CascadeClassifier`
que a usava. `scripts/thumbnail_templates.py`, `scripts/imagem/nenhum.py`,
`assets/fonts/BebasNeue-Regular.ttf` também não existem mais — os 5
templates de composição via Pillow e o provedor de fundo-só que os
alimentava foram removidos na sessão de simplificação da Etapa 7 (seção
5.85); `opencv-python` e `rembg` saíram de `requirements.txt` junto (só
serviam ao scan de cenário e ao recorte de sujeito que essa arquitetura
usava).

## 11. APIs externas — resumo de custo

**Anthropic Messages API.** `claude-sonnet-5` padrão. Web search
$10/1000 buscas + tokens. Custo estimado por vídeo (Etapa 3, roteiro):
$0.10-0.50. A Etapa 5 (geração de clipes) não chama API nenhuma — seleção
aleatória local via ffmpeg (seção 5.7) — não há mais custo de "curadoria
semântica" separado. A Etapa 7 (thumbnail, seção 5.85) soma
~$0.05-0.10/vídeo (metadados + Headline Engine + atributos visuais leves
por foto de sujeito via Vision — nunca identificação, o papel já vem
declarado pelo usuário — todas opcionais, a etapa não falha sem
`ANTHROPIC_API_KEY`).

**OpenAI Images API (`gpt-image-2`).** Único caminho real de gerar a
IMAGEM da thumbnail (seção 5.85, Grupo H) — exige `OPENAI_API_KEY`
própria. Cobrado por imagem gerada, qualidade `"low"` por padrão
(~$0.02/imagem, `CUSTO_USD_ESTIMADO_POR_QUALIDADE` em
`scripts/imagem/openai.py`). Composições acumulam em
`thumbnail/previews/` (nunca se sobrescrevem) — cada clique em "Gerar
thumbnail pela OpenAI" é uma chamada nova e cobrada, o usuário decide
quantas tentativas vale a pena antes de escolher uma.

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
- Claude API: ~$3-15/mês (Etapa 3) + ~$1,50-3/mês (Etapa 7, thumbnail)
- OpenAI Images (composição da thumbnail, se `OPENAI_API_KEY`
  configurada): ~$0,60-2/mês numa média de 1-3 tentativas/vídeo em
  qualidade `"low"`, ou $0 sem a chave (thumbnail fica só no briefing em
  texto)
- Google TTS: ~$0-30/mês, ou $0 se usar upload de voz própria
- YouTube API: $0
- **Total: ~$4,50-50/mês** no estado atual do produto

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
web search e prompt melhor do mundo, Claude ocasionalmente confunde
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
aconteceu antes disso, na Sessão 14 — o tema escuro Claude.ai-style
original foi substituído pelo design system **Nocturne**
(`static/design_system.css`), com refinamentos adicionais nas Sessões
15 (polish geral) e 16/17 (pipeline horizontal sticky + clicável).
Mantido aqui só como registro histórico da referência estética usada:

- `.claude/referencias/visual_ref_zebeyond.png` — SaaS moderno com fundo
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
`faster-whisper` (se OpenAI mudar formato), APIs do Claude/ElevenLabs/
OpenAI/Azure/Google Veo3/YouTube Data.

**Princípios que valem pra qualquer script novo do pipeline:**

### 18.1 Pinning estratégico no `requirements.txt`

- Bibliotecas estáveis (Flask, pytest, python-dotenv, requests,
  Pillow): pinar versão exata (`==`)
- Bibliotecas 100% locais (não contra API externa) mas com risco real
  de quebra em major version: `opencv-python` pinado em `==4.14.0.94`
  de propósito (a série 5.x removeu `cv2.CascadeClassifier`, usado pela
  Etapa 7 — seção 5.85) e `rembg[cpu]==2.0.83` (a sessão de modelo
  usada, `u2net_human_seg`, é forçada explicitamente no código, não o
  default da lib)
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

### 18.3.1 Atalho da área de trabalho abre o navegador automaticamente

`scripts/criar_atalho.py` (chamado por `--instalar-deps`, ver seção
18.3) cria `Broll Foundry.lnk` na área de trabalho apontando direto pra
`iniciar.bat` — mesmo alvo, mesmo diretório de trabalho, mesmo
comportamento de clicar `iniciar.bat` manualmente. **Achado real:** o
atalho subia o servidor mas nunca abria o navegador — a causa não
estava no atalho nem em `criar_atalho.py` (o `.lnk` sempre apontou pro
lugar certo), e sim porque **nenhum lugar do fluxo jamais tentava abrir
o navegador** — nem `iniciar.bat`, nem `server.py`. Faltava a feature
inteira, não havia bug de configuração pra corrigir.

**Correção:** `iniciar.bat` ganhou `scripts/verificar_servidor.py`
(script novo, só biblioteca padrão + `dotenv` opcional), chamado em
dois pontos:

- **Antes de subir o servidor** (`checar-porta`): confere se a porta
  configurada (`PORTA`, default `5000`) já está em uso. Livre → segue
  o fluxo normal. Já ocupada pelo próprio Broll Foundry (confirmado
  batendo na rota `/verificar_atualizacao`, seção 16, e conferindo a
  assinatura do JSON — nunca só "alguém respondeu na porta") → não sobe
  um segundo servidor, só abre o navegador na instância existente.
  Ocupada por outro processo qualquer → avisa o conflito com clareza e
  para (`exit /b 1`), nunca mata nem substitui o processo existente.
- **Depois de disparar `python server.py`** (`aguardar-e-abrir`,
  lançado com `start "" /B` — em segundo plano, mas dentro da mesma
  sessão de console, nunca uma janela/processo desacoplado do
  terminal): faz *polling* real em `/verificar_atualizacao` até o
  Flask responder de verdade (nunca uma espera fixa — o tempo de boot
  varia por máquina), com timeout configurável (`--timeout`, default
  90s) que termina em erro claro no terminal se estourado, e só então
  abre `http://localhost:{PORTA}/` no navegador padrão.

`python server.py` continua sendo a última linha do fluxo principal,
chamado direto (sem `start`, sem `call` desacoplando) — fechar o
terminal continua encerrando o servidor, comportamento inalterado.

Duas checagens de robustez adicionais entraram no mesmo fluxo, ambas
puramente defensivas (nunca travam o boot legítimo):

- Logo após `cd /d "%~dp0"`: se `server.py` não existir no diretório
  resolvido, mostra mensagem clara orientando recriar o atalho —
  cobre o caso de rodar a partir de uma cópia parcial/pasta movida que
  o `.bat` consegue detectar. **Limitação explícita:** se o `.lnk` em
  si estiver com o alvo morto (pasta inteira renomeada/movida), o
  Windows Explorer recusa abrir o atalho e mostra o próprio diálogo
  genérico *antes* de `iniciar.bat` sequer rodar — nenhum código deste
  projeto roda nesse caso, não tem como interceptar.
- Logo após criar/ativar a venv: se `venv\Scripts\python.exe` não
  existir (venv ausente ou corrompida — pasta existe mas o
  interpretador sumiu), mensagem clara orientando
  `iniciar.bat --instalar-deps` em vez de deixar o restante do script
  falhar mais na frente com erro genérico do Windows. Resolve o item
  "iniciar.bat não detecta venv ausente ou quebrado" de
  `MELHORIAS_PENDENTES.md`.

Testes: `tests/test_verificar_servidor.py` (socket/urllib/webbrowser
sempre mockados, nunca abre porta nem navegador de verdade) e novos
casos em `tests/test_iniciar_bat.py` (estáticos sobre o texto do
arquivo, mesmo padrão do resto do arquivo — ver aviso no topo daquele
arquivo de teste sobre nunca invocar o `.bat` de verdade).

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

Toda função nova (por CLAUDE.md seção 8) tem que ter teste que cobre:
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
CLAUDE.md seção 18.2), guardada num global de módulo `AMBIENTE_ATUAL`
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
