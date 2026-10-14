# Prompt de abertura — Broll Foundry

Roteiro de trabalho com Claude Code. Documenta:
- Arquitetura ATUAL do projeto
- Histórico compacto de sessões já executadas
- Próximas sessões planejadas

Para arquitetura técnica completa (contratos de dados, convenções,
posições firmes do projeto), ver `CLAUDE.md` — este documento não repete
o que já está lá.

---

## Arquitetura atual (pós-Sessão 18)

Pipeline de 6 etapas, cada uma um script autocontido em `scripts/`:

1. `1_baixar_videos.py` — yt-dlp via `python -m yt_dlp`; suporta também
   fontes enviadas por upload direto (`entrada/fontes_upload.json`)
2. `2_transcrever.py` — faster-whisper GPU; pula fontes marcadas como
   `visual` em `entrada/fontes_tipo_uso.json` (modo fontes separadas)
3. `3_gerar_roteiro.py` — Claude Sonnet API, web search + tool YouTube,
   sistema de perfis (`truecrime`/`atualidades_narrativas`/`historia`)
4. `4_obter_audio.py` — TTS (só Google implementado; ElevenLabs/OpenAI/
   Azure são stubs de interface) ou upload de áudio próprio
5. `5_gerar_clipes.py` — seleção aleatória de trechos, round-robin de
   fontes, Ken Burns + delogo via ffmpeg (`h264_nvenc` se disponível).
   Sem detecção de cena, sem Vision, sem deduplicação — ver histórico
   abaixo (Sessões 9-11) pra entender por que essa abordagem foi
   descartada em favor desta mais simples
6. `6_montar_video.py` — concat + mux + legendas (SRT sempre, ASS
   "MrBeast" queimada opcional) + música de fundo em playlist opcional

Custo por vídeo: ~$0.20-0.70 (roteiro) + custo de TTS (zero se voz
própria, ~$0.25-8 se TTS). Veo3 seguem *desligado por padrão* e sem
geração real implementada (só scaffolding de prompt) — ver seção
"Próximas sessões".

Ver `CLAUDE.md` pra contratos de dados completos, convenções de código,
e detalhes de cada etapa.

---

## Histórico compacto de sessões

- **Sessão 1** — Fundação + migração do `broll_alfa` (ver `MIGRACAO.md`)
- **Sessão 2-3** — Etapa 1 (download) + integração no `server.py`
- **Sessão 4** — Etapa 2 (transcrição), requisitos mínimos de GPU/CUDA
- **Sessão 5A/5B** — Sistema de perfis, marcas d'água, formulário de
  seleção de fonte
- **Sessões 6-6.5** — Etapa 3 (roteiro) + otimização de custo da Claude
  API (redução de `WEB_SEARCH_MAX`)
- **Sessão 7** — Tela de revisão do roteiro
- **Sessão 8-8.3** — Etapa 4 (TTS Google), correções de chunking por
  bytes, cuBLAS/cuDNN no alinhamento, pausas naturais entre chunks
- **Sessões 9-9.4** — Primeira tentativa de corte de clipes com Ken
  Burns + enriquecimento Veo3 (scaffolding), depois detecção de cena via
  ffmpeg — abandonada por excesso de cenas detectadas e custo de Vision
  descontrolado (ver `HISTORICO_BUGS.md`)
- **Sessões 10-10.4** — Segunda tentativa: arquitetura
  `5_dividir_cenas.py`/`6_montar_timeline.py`/`7_renderizar_clipes.py`
  com PySceneDetect + Vision opcional + pHash. Vários bugs de
  performance corrigidos, mas custo-benefício do Vision ficou ruim
- **Sessão 11** — Abandono definitivo da detecção de cena. Consolidação
  em `5_gerar_clipes.py`: seleção aleatória round-robin estilo
  `yt_automation` (Gustavo Xavier), sem PySceneDetect/Vision/pHash
- **Sessão 12** — Etapa 6 (montagem final: concat + mux + legendas)
- **Sessão 13** — Legendas estilo "MrBeast" + música de fundo em playlist
- **Sessão 14** — Reformulação visual: design system Nocturne
- **Sessão 15** — Refinamentos visuais
- **Sessão 16** — Pipeline horizontal sticky na tela de status
- **Sessão 17** — Pipeline clicável (cada etapa abre resultado read-only)
- **Sessão 18** — Modo de fontes separadas (`fontes_tipo_uso.json`) +
  upload direto de mídias visuais (`fontes_upload.json`)

Detalhe completo de cada bug/decisão em `HISTORICO_BUGS.md`. Pendências
abertas em `MELHORIAS_PENDENTES.md`.

---

## Próximas sessões

### Sessão 19 (opcional) — Revisão manual de clipes

Adicionar etapa opcional entre `5_gerar_clipes.py` e `6_montar_video.py`:
usuário revisa os clipes gerados, deleta os que não quer, o pipeline
segue com os restantes.

Escopo: médio (~35-45% de janela).

### Sessão 20 (opcional) — Intro/ending customizados

Permitir upload de `intro.mp4` e `ending.mp4` em `entrada/`.
`6_montar_video.py` concatena antes/depois do vídeo montado.

Escopo: pequeno (~20% de janela).

### Sessão 21 (opcional) — Integração Veo3 de verdade

Hoje só existe scaffolding de prompt (`veo3_estilo.md` por perfil,
injetado se `opcoes_veo3.ativado`). Implementar geração real de b-roll
via Veo3 API quando fontes visuais forem insuficientes, conforme
desenhado no `CLAUDE.md` seção 5.75 (análise de gaps, cache global,
tratamento de rejeição). Custo alto ($0.15-0.75/s de vídeo gerado) —
fase 2 do produto.

Escopo: grande (~60% de janela).

---

## Regras gerais pra todas as sessões

**Antes de começar:** sempre "leia CLAUDE.md e os agents". Conteúdo
evolui — não confiar em memória de sessões anteriores.

**Depois de escrever código:** delega pro `test-writer` os testes e pro
`test-runner` a execução.

**Ao fim de cada sessão:** "roda pytest e me mostra resultado. Pare
quando testes verdes." Nunca prossegue pra próxima tarefa dentro da
mesma sessão.

**Se a arquitetura de pipeline mudar** (script novo, script removido,
consolidação): atualizar a seção correspondente do `CLAUDE.md` como
parte da própria sessão — não deixar acumular pra uma sessão de
manutenção documental depois (ver `MELHORIAS_PENDENTES.md`).

**Se bater limite de 5 horas:** interrompe com Esc, `/exit`, aguarda
reset, abre nova sessão continuando de onde parou.
