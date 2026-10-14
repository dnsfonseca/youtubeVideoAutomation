/exo# Melhorias Pendentes — Broll Foundry

Backlog vivo de melhorias, bugs conhecidos, e decisões adiadas
identificadas durante desenvolvimento. Não é escopo formal — é lista
de trabalho pra atacar em sessões de correção/polish futuras.

**Convenção de prioridade:**
- **CRÍTICO** — bug que quebra o produto ou trava o usuário
- **IMPORTANTE** — problema real de UX ou robustez, mas não bloqueante
- **NICE-TO-HAVE** — melhoria genuína mas não urgente
- **BACKLOG** — ideia pra considerar quando o produto amadurecer

---

## CRÍTICO

*(nada aberto no momento — os críticos identificados nas sessões 2 e
2b foram todos corrigidos)*

---

## IMPORTANTE

### Validação empírica de intro/ending pendente do usuário
- **Origem:** sessão "Intro e ending anexados ao vídeo final"
  (14/09/2026, ver `HISTORICO_BUGS.md`).
- **Pendência:** a suíte automatizada mocka ffmpeg/ffprobe (CLAUDE.md
  seção 8) — falta rodar de verdade: subir uma intro com codec/resolução
  diferente do padrão do projeto, montar, e abrir o vídeo final conferindo
  ausência de corte/dessincronia visual, o início exato da primeira
  legenda embutida coincidindo com o início da narração, a marca d'água
  do canal aparecendo sobre intro/ending, e o comportamento dos blocos
  fixos na tela de reorganização de clipes.

### `reconciliar_titulos_com_headline` avalia contra `withheld_fact` do candidato vencedor, não contra `conclusao_central` do Headline Engine v2
- **Origem:** sessão de reestruturação do Headline Engine (08/09/2026,
  ver `HISTORICO_BUGS.md`, mesma sessão que introduziu `answer_leak`).
  O Headline Engine v2 passou a extrair uma `conclusao_central` (Grupo
  A) e a checar, no próprio juiz (`answer_leak`), se título+headline
  juntos permitem deduzi-la — mas essa checagem usa o `titulo_aprovado`
  que existia NO MOMENTO da geração do headline.
- **O que ficou de fora:** `reconciliar_titulos_com_headline`
  (`scripts/7_thumbnail.py`) é uma chamada SEPARADA, que roda depois, e
  continua avaliando o título só contra o `withheld_fact` do candidato
  vencedor (o segredo PARTICULAR daquele headline) — nunca contra
  `conclusao_central`. Na prática isso raramente importa (o
  `answer_leak` do juiz já protegeu o par título+headline na hora da
  escolha), mas cobre mal o caso em que o usuário troca o título
  aprovado DEPOIS que o Headline Engine já rodou (ex: volta na revisão
  do roteiro e edita o título) sem re-rodar o motor - a reconciliação
  nesse cenário não teria como saber se o título novo, somado ao
  headline antigo, vaza a conclusão central.
- **Prioridade:** baixa - cenário de borda (editar título depois de já
  ter gerado a thumbnail), e a proteção principal (answer_leak no
  momento da geração) já cobre o caso comum.

### Auditoria `titulo_headline_reconciliacao` é persistida mas nunca vira aviso visível na tela
- **Origem:** sessão "título canônico" (08/09/2026, caso real Burke
  Ramsey/JonBenét, ver `HISTORICO_BUGS.md`). Antes desta sessão, a
  Etapa 7 gerava um segundo conjunto de 3 títulos concorrente com o
  escolhido pelo usuário na revisão — corrigido: o título aprovado
  (`titulo.txt`) agora é a única fonte de verdade em todo o pipeline
  (conclusão, briefing, reconciliação).
- **O que ficou de fora:** `reconciliar_titulos_com_headline`
  (`scripts/7_thumbnail.py`) continua rodando sobre `titulo_escolhido`
  contra o headline final e persiste o resultado em
  `thumbnail/metadados.json["titulo_headline_reconciliacao"]` — mas essa
  auditoria é SÓ dados hoje, nenhuma tela (thumbnail ou conclusão) lê
  esse campo pra mostrar um banner tipo "o título aprovado pode revelar
  o que o headline esconde". A escolha do usuário nunca é alterada (é
  soberana, por decisão explícita desta sessão), mas o usuário também
  não é avisado quando ela colide com o headline escolhido depois — só
  descobriria abrindo `thumbnail/metadados.json` manualmente.
- **Por que não foi resolvido nesta sessão:** o pedido era corrigir o
  fluxo de dados (fonte única de verdade), não adicionar UI nova. Já
  existe um padrão de banner pronto pra reaproveitar (`eixo_editorial_
  ausente`, `aviso_revisao_humana`/`fallback_sem_julgamento` do Headline
  Engine, todos em `templates/thumbnail.html`).
- **Se uma sessão futura quiser fechar essa lacuna:** ler
  `titulo_headline_reconciliacao.alterado` (ou um score baixo em
  `scores[0].complementarity_score`) em `server.py:thumbnail()` e passar
  pro template um aviso não-bloqueante, mesmo espírito dos outros
  banners da Etapa 7 — nunca sugerir trocar o título automaticamente,
  só informar.

### Conceito visual não transporta a implicação de "identificação"/consequência narrativa do `hidden_question`/`tension_source` — só o elemento concreto
- **Origem:** sessão "conceito visual", Parte 2, Grupo K (09/09/2026, ver
  `HISTORICO_BUGS.md`) — validação contra a API real, caso Nancy Guthrie.
  O Headline Engine extrai, na Grupo A, tanto o `conceito_visual`
  (elemento/ação/revelação — usado pelo briefing de composição) quanto
  `hidden_question`/`tension_source` (usados só pelos candidatos de
  headline, Grupo B) — este último caso real trouxe explicitamente a
  implicação de identificação ("...how could that one detail be the
  thing that identifies him?"), mas esse campo nunca chega ao
  `briefing_completo` (prompt de composição de imagem), só ao headline
  textual da thumbnail.
- **Por que não foi tratado como bug nesta sessão:** `conceito_visual` é
  deliberadamente escopado a elementos VISUAIS concretos (o que a imagem
  precisa MOSTRAR) — "possibilidade de identificação" é uma implicação
  narrativa abstrata, não um elemento desenhável. A validação empírica
  mostrou que essa implicação já fica carregada pelo HEADLINE em si (ex:
  "THE BRANCH THAT BACKFIRED" já sugere a reviravolta/exposição) —
  headline e conceito visual têm papéis complementares (um narra, o
  outro mostra), não redundantes.
- **Se uma sessão futura achar que a imagem sozinha (sem o headline
  sobreposto, ex: pra reuso externo do briefing) perde a implicação de
  forma importante:** considerar um 6º campo opcional no schema do
  conceito visual (algo como `implicacao_visual` — como ENQUADRAR a cena
  pra sugerir a implicação visualmente, ex: foco dramático no elemento
  revelado) em vez de misturar `hidden_question` (que é sobre CURIOSIDADE
  de headline, não sobre COMPOSIÇÃO de imagem) na cláusula.
- **Prioridade:** NICE-TO-HAVE — validado que o resultado atual já
  funciona bem (thumbnail final = imagem + headline sobreposto, nunca só
  a imagem).

### `descrever_pessoa_para_prompt`/`montar_prompt_*` empilham atributos do Vision sem checar coerência entre eles
- **Origem:** sessão "correção pontual — montagem da relação causal do
  conceito visual" (09/09/2026). Escopo daquela sessão foi só
  `montar_clausula_conceito_visual` (`scripts/thumbnail_briefing.py`),
  mas o pedido notou a MESMA classe de bug (concatenação de campos sem
  checar a relação semântica entre eles) em `descrever_pessoa_para_prompt`
  — caso real observado: "an elderly woman established as the case's
  victim, with a serious, neutral expression with a steady gaze with
  realistic skin texture and an intense emotional expression" — cinco
  descritores encadeados com "with X with Y with Z", e "neutral
  expression"/"intense emotional expression" se contradizendo (atributo
  do Vision concatenado cru com texto fixo do template).
- **Por que não foi corrigido nesta sessão:** o pedido explícito era
  escopo estrito — corrigir só `montar_clausula_conceito_visual`, sem
  tocar em templates/seleção/schema/prompts de IA. `descrever_pessoa_
  para_prompt` é usado por TODOS os 6 `montar_prompt_<template>`
  (`scripts/thumbnail_briefing.py`), então mexer nela é mudança de maior
  superfície do que o pedido autorizava.
- **Se uma sessão futura quiser corrigir:** aplicar o mesmo princípio já
  documentado em `_ajustar_genero_e_prefixo_para_crianca` (mesmo
  arquivo) — nunca concatenar frases soltas com "with X with Y"; montar
  a descrição em código verificando se os atributos vindos do Vision
  colidem entre si (ex: expressão "neutral" vs. "intense emotional")
  antes de encadear, e preferir uma única cláusula coesa a uma cadeia de
  `with`.
- **Prioridade:** IMPORTANTE — atributos contraditórios na descrição do
  sujeito podem confundir o modelo de composição de imagem (`gpt-image-2`,
  Grupo H, seção 5.85) da mesma forma que o bug do conceito visual
  confundia a composição da cena.

### `selecionar_protagonista_dual_portrait` só existe pro `DUAL_PORTRAIT` — outros templates de dois sujeitos não decidem protagonista pelo eixo editorial
- **Origem:** mesma sessão acima (validação 11 do pedido — caso Burke,
  título sobre o sujeito enviado como `secondary`). A correção ficou
  deliberadamente restrita ao `DUAL_PORTRAIT` porque foi o caso de teste
  real do pedido; `ARROW_TRIO`/`DUOTONE_DOSSIER` (relação de acusação)
  continuam usando SEMPRE a mesma posição fixa por papel (vítima
  central/direita, acusado à esquerda) independente de qual dos dois o
  título enfatiza mais.
- **Se uma sessão futura achar um caso real onde isso importa** (ex:
  título focado no acusado, mas ele foi enviado como `hero` e a
  composição do `ARROW_TRIO` já o coloca em destaque por acaso, ou
  vice-versa): generalizar `selecionar_protagonista_dual_portrait` pra um
  helper compartilhado entre os templates de dois sujeitos, não duplicar
  a lógica.

### Complementaridade título↔headline: juiz separado, não um 7º critério dentro do Headline Engine
- **Origem:** sessão "coordenação entre título e headline" (07/09/2026,
  ver `HISTORICO_BUGS.md`). O pedido original da sessão (Grupo D)
  queria uma nova pontuação de complementaridade DENTRO da rubrica de
  `scripts/headline_engine.py:CRITERIOS_JULGAMENTO`, com peso igual a
  `opens_gap`/`anchored_to_case`. A sessão também trazia a restrição
  explícita de não alterar `scripts/headline_engine.py` — as duas coisas
  são incompatíveis (o critério é um `tuple`/`SCHEMA_JULGAMENTO`
  hardcoded nesse mesmo arquivo).
- **O que foi feito em vez disso:** `reconciliar_titulos_com_headline`
  (`scripts/7_thumbnail.py`) é um juiz SEPARADO que avalia o PAR
  título-final/headline-final DEPOIS que o Headline Engine já decidiu o
  vencedor — mesma pontuação 0-2, mesma semântica de "não redundante +
  relação semântica + cada um acrescenta informação", só que fora do
  arquivo restrito e sem interferir na seleção do headline em si (que
  continua decidida só pelos 6 critérios originais).
- **Se uma sessão futura quiser o critério DENTRO do Headline Engine de
  verdade** (ex: pra pesar complementaridade já na escolha do vencedor,
  não só depois): precisa reabrir a restrição de não mexer em
  `headline_engine.py`, e nesse caso o candidato vencedor precisaria
  conhecer os 3 títulos da Etapa 7 (`thumbnail/metadados.json["title"]`)
  ANTES de ser escolhido — hoje ele só conhece `titulo.txt` (Etapa 3).
  Mudança de escopo maior que vale uma sessão dedicada, não um ajuste
  pontual.

### Sem UI pra trocar título/headline manualmente — `headline_desatualizado` não implementado como flag+botão
- **Origem:** mesma sessão acima (Grupo E do pedido original). O pedido
  assumia um fluxo "usuário troca o título → headline marcado
  desatualizado → usuário clica em regenerar". Esse fluxo não existe
  hoje: nem `titulo.txt` (Etapa 3) nem os 3 títulos da Etapa 7
  (`metadados.json["title"]`) têm qualquer tela de edição depois de
  gerados — só o texto do briefing é editável (CLAUDE.md seção 5.85).
- **O que foi feito em vez disso:** a reconciliação (item acima) roda
  AUTOMATICAMENTE toda vez que o headline é gerado ou regenerado
  (`gerar_metadados` E `regenerar_thumbnail_briefing`), então não existe
  hoje uma janela real em que um título sobreviva desalinhado do
  headline esperando o usuário notar.
- **Se uma sessão futura adicionar edição manual de título** (fora do
  escopo desta sessão — CLAUDE.md seção 12, "Extensão de escopo"): essa
  sessão precisaria então SIM adicionar uma flag `headline_desatualizado`
  de verdade (mesmo padrão de `briefing_desatualizado`,
  `scripts/7_thumbnail.py`), porque nesse caso o usuário poderia editar
  o título DEPOIS da última reconciliação automática, sem disparar nova
  chamada de IA.

### ~~Reconfirmar bugs de elegibilidade de template / papel no briefing com servidor recém-reiniciado (video_teste_01)~~ — RESOLVIDO
- **Status: corrigido** na sessão de 06/09/2026 com servidor reiniciado
  (ver `HISTORICO_BUGS.md`, entrada "Papel do sujeito não persistia ao
  trocar o dropdown"). A hipótese de processo desatualizado estava
  **errada** — o bug era real e a causa raiz não era
  `thumbnail_briefing.py`/`templates_elegiveis` (que sempre estiveram
  corretos), e sim `static/thumbnail.js`: o `<select>` de papel não
  tinha nenhum listener de `change`, então trocar a opção no dropdown
  nunca chegava ao servidor — só era enviada junto de um upload de
  arquivo novo. `sujeitos.json` ficava com o papel antigo, e
  `templates_elegiveis()` recebia esse dado desatualizado (a regra em si
  nunca foi o problema).
- Corrigido com: rota nova `POST /thumbnail/atualizar_papel_sujeito`
  (persiste o papel sem exigir reenvio da foto), listener de `change`
  no dropdown (`thumbnail.js`), sincronização do texto ao lado da
  miniatura com o valor persistido, recálculo imediato da elegibilidade
  de template sem reload, e marcação de `briefing_desatualizado` quando
  um briefing já gerado deixa de refletir o papel atual.
- Testes: 11 novos em `tests/test_thumbnail_rotas.py` (persistência,
  sobrevivência a reload, recálculo de elegibilidade, invalidação de
  briefing, lista completa de papéis no dropdown). Suíte completa
  (1882 testes) verde.

### `REQUISITO_TEMPLATE` (texto longo do requisito) ficou sem consumidor na tela depois da correção do seletor
- Contexto: sessão de correção do seletor de template (07/09/2026, ver
  `HISTORICO_BUGS.md`) trocou o `title` de cada opção e o motivo inline
  de indisponibilidade por `DESCRICAO_AMIGAVEL_TEMPLATE`/
  `MOTIVO_CURTO_INDISPONIVEL` (mais amigáveis pro usuário final).
  `REQUISITO_TEMPLATE` (a frase completa do requisito, ex: "Requer 2
  sujeitos com relação de acusação: um suspeito/condenado e um vitima.")
  continua existindo em `scripts/thumbnail_briefing.py` — coberto por
  teste (`test_requisito_e_motivo_curto_*`) e ainda é a fonte mais
  precisa/completa — mas não é mais renderizado em lugar nenhum de
  `templates/thumbnail.html`.
- Ação sugerida: decidir entre (a) remover `REQUISITO_TEMPLATE` de vez
  se `MOTIVO_CURTO_INDISPONIVEL` cobrir bem o caso de uso real, ou (b)
  reaproveitar como texto expandido dentro do `<details>` "Ver o que
  cada template mostra" (hoje só usa `DESCRICAO_AMIGAVEL_TEMPLATE`).
- Prioridade: NICE-TO-HAVE (não é bug — o dado está correto e testado,
  só não tem consumidor de UI hoje).

### Trocar/remover a FOTO de um sujeito também não marca o briefing como desatualizado
- Contexto: achado durante a correção do bug de papel não persistido
  (ver `HISTORICO_BUGS.md`, sessão 06/09/2026 com servidor reiniciado).
  A correção fez `POST /thumbnail/atualizar_papel_sujeito` marcar
  `thumbnail.briefing_desatualizado=True` quando o PAPEL de um sujeito
  muda depois de já existir um briefing gerado — mas
  `thumbnail_upload_sujeito` (trocar a foto) e `thumbnail_remover_sujeito`
  (remover a foto) continuam sem essa marcação, mesmo pré-existindo a
  esta sessão. Trocar a foto de "hero" também muda o que a composição por
  IA vai receber (a foto é enviada direto, sem recorte) — um briefing já
  gerado referenciando a foto antiga fica igualmente desatualizado, só
  que por causa da imagem, não do texto do papel.
- Ação sugerida: reaproveitar o mesmo campo
  `thumbnail.briefing_desatualizado` nas duas rotas (mesmo padrão desta
  sessão) — sem chamar a API de novo sozinho, só marcar e deixar o
  usuário decidir quando regenerar.
- Prioridade: NICE-TO-HAVE (o usuário já reenvia a foto de propósito,
  mais fácil de perceber visualmente do que uma troca de papel; o botão
  "Gerar / regenerar briefing" já está sempre visível e disponível)

### Simplificação da Etapa 7 (sessão 05/09/2026) sem validação empírica ao vivo com composição de imagem real
- Contexto: a sessão de simplificação (remoção dos templates Pillow,
  composição só via OpenAI, acumulação de tentativas, seletor manual de
  template) foi validada por testes automatizados (mockando toda
  chamada paga) e por smoke-tests diretos das rotas (GET /thumbnail,
  gerar_briefing com template forçado, escolher_composicao) — mas
  **nunca contra o servidor real rodando com uma chave OpenAI de
  verdade pra gerar uma composição de imagem completa**. O teste ao
  vivo de 06/09/2026 (ver item acima) validou upload de sujeitos +
  geração de briefing, mas não chegou a clicar em "Gerar thumbnail pela
  OpenAI" pra confirmar a composição de imagem em si.
- Ação sugerida: na próxima sessão com o usuário disponível, gerar 2
  composições reais e confirmar que ambas acumulam em
  `thumbnail/previews/`, recarregar a página e confirmar que o grid
  persiste, e trocar o template no seletor confirmando que o briefing
  muda de verdade.
- Quando fazer: próxima sessão com o usuário disponível pra autorizar o
  gasto e escolher o projeto
- Prioridade: IMPORTANTE (a lógica está coberta por teste, mas nenhuma
  chamada real à API da OpenAI foi feita ainda com o código novo)

### `nancyGuthrieProject03` já tem vídeo renderizado com cabeçalhos narrados em voz alta
- Contexto: sessão de correções de composição/interface (04/09/2026)
  confirmou, contra o projeto real `nancyGuthrieProject03`, que
  `roteiro_aprovado.md` chegou à Etapa 4 com 17 cabeçalhos markdown
  intactos (a limpeza da Sessão 21 não rodou nesse caso - causa provável
  operacional, não de código, ver `HISTORICO_BUGS.md`) e que a narração
  REAL já gravada (`narracao_alinhamento.json.texto_transcrito`) contém
  literalmente "Woman Who Lived Alone" - o narrador leu o título da
  seção em voz alta. `saida/video_final.mp4` deste projeto já está
  renderizado com esse defeito.
- Ação sugerida: decidir com o usuário se regenera áudio (Etapa 4) +
  montagem (Etapa 6) deste projeto especificamente agora que
  `scripts/4_obter_audio.py` tem a rede de segurança que remove
  cabeçalhos antes de sintetizar - ou se aceita o vídeo como está.
- Quando fazer: próxima sessão com o usuário disponível pra decidir
  (não é uma correção de código - é uma decisão de reprocessar ou não
  um projeto específico já concluído)
- Prioridade: IMPORTANTE (vídeo já publicável tem defeito audível, mas
  não é um bug de código pendente - a rede de segurança já está no
  lugar pra projetos futuros)

### Layout da tela /sobre precisa expandir
- Contexto: cards de perfis ficam centralizados com muito espaço vazio nas laterais em telas grandes. Textos longos ocupam muito espaço vertical
- Ação sugerida: grid expandir até ~1400px, descrições longas colapsáveis (só título + descrição curta visíveis por padrão, clique expande)
- Quando fazer: Sessão 15 (polish)

### Bloco "Arquivos baixados" só atualiza no reload da página
- Contexto: durante execução ativa, o bloco continua mostrando "Nenhum arquivo baixado ainda" mesmo após conclusão da etapa. Só atualiza quando usuário recarrega manualmente
- Causa técnica: decisão da Sessão 3c de manter status.js simples — polling atualiza só campos dinâmicos (barra, log, status), bloco de arquivos vem do HTML inicial
- Ação sugerida: adicionar campo "arquivos" no endpoint /api/status/<id> e atualizar bloco via JS durante polling
- Quando fazer: pode ser sessão isolada quando incomodar, ou junto com outros ajustes de status na Sessão 15

### iniciar.bat não detecta venv ausente ou quebrado — RESOLVIDO (sessão de melhoria do atalho, 07/09/2026)
- Contexto original: se o usuário nunca rodou --instalar-deps, se
  moveu/renomeou a pasta, ou se venv corrompeu, iniciar.bat crasha com
  ModuleNotFoundError em vez de resolver ou dar mensagem clara
- **Resolvido:** `iniciar.bat` agora verifica `venv\Scripts\python.exe`
  logo após o bloco de criação/ativação da venv (antes de qualquer
  outra checagem que dependa de rodar `python` de verdade) e mostra
  mensagem clara orientando `iniciar.bat --instalar-deps` (ou apagar a
  pasta `venv` se persistir) em vez de deixar o script falhar mais na
  frente com erro genérico. Também ganhou uma checagem irmã pra "pasta
  do projeto movida/renomeada": se `server.py` não existir no diretório
  resolvido por `%~dp0`, mensagem clara orientando recriar o atalho.
  Ver CLAUDE.md seção 18.3.1 e `HISTORICO_BUGS.md` (mesma data) pro
  detalhe completo, incluindo a limitação documentada de que um `.lnk`
  com alvo morto é interceptado pelo próprio Windows Explorer antes de
  `iniciar.bat` sequer rodar — fora do alcance de qualquer código deste
  projeto.
- Testes: casos novos em `tests/test_iniciar_bat.py` (estáticos, ver
  aviso no topo do arquivo sobre nunca invocar o `.bat` de verdade).

### Fluxo de instalação do ffmpeg via winget/chocolatey testado só via mocks
- **Contexto:** sessão de correção do `--instalar-deps` cobriu 8 cenários
  com testes mockados, mas só o cenário "ffmpeg já instalado" foi
  validado ao vivo (na máquina do usuário, ffmpeg já estava presente
  via chocolatey da correção manual anterior)
- **Risco:** primeira vez que um usuário sem ffmpeg rodar
  `--instalar-deps` de verdade, pode aparecer bug que os mocks não
  pegaram (encoding de mensagens do winget, timing de UAC, mensagens
  específicas do chocolatey)
- **Ação sugerida:** se aparecer bug real reportado, abrir sessão
  específica pra corrigir. Alternativa mais defensiva: testar em VM
  Windows limpa antes de considerar o produto pronto pra distribuição
  externa (esforço grande, não vale agora)

### Botão "voltar" na tela de detalhe de projeto
- **Contexto:** ao clicar num projeto na home, não há botão pra voltar
  à lista — usuário precisa clicar em "Projetos" no menu superior
- **Ação sugerida:** adicionar breadcrumb ou botão "← Voltar aos
  projetos" no header da tela de status/detalhe do projeto
- **Onde encaixar:** próxima sessão de correção/polish, ou junto com
  Sessão 15 (polish + LEIAME)

### HUD numerada de progresso das etapas na tela de detalhe do projeto
- **Contexto:** hoje a tela /projetos/<id> mostra estado em texto
  simples. Deve virar HUD visual com 7 círculos numerados agrupando
  as 8 etapas do pipeline (Veo3 fica embutido em uma delas)
- **Especificação:**
  - 7 etapas agrupadas: (1) Download, (2) Transcrição,
    (3) Roteiro + Revisão, (4) Áudio, (5) Clipes,
    (6) Montagem, (7) Concluído
  - 5 estados por etapa (cor de fundo do círculo): pendente,
    em andamento, concluída, aguardando ação do usuário, falhou
  - Tooltip no hover mostra estado detalhado e % de progresso
  - Etapas concluídas clicáveis pra revisitar o resultado daquela
    etapa
  - Estilo visual: referência guardada em
    .claude/referencias/hud_ref_progress_bar.png (imagem enviada
    pelo usuário na sessão)
- **Quando fazer:** Sessão 15 (polish) ou sessão dedicada logo antes.
  NÃO antes do pipeline estar completo (Sessão 13+)
- **NÃO incluir:** botões "pular etapa" — decisão adiada pra v2 se
  demanda real aparecer

### Expor chaves de API e configs sensíveis na tela de Ajustes
- Contexto: hoje várias variáveis ficam só no .env, usuário precisa
  editar arquivo manualmente. Não escala pra distribuição do produto.
- Variáveis a expor:
  - ANTHROPIC_API_KEY (obrigatória)
  - ANTHROPIC_MODEL (default claude-sonnet-5)
  - WEB_SEARCH_MAX (default 2)
  - GOOGLE_TTS_API_KEY (obrigatória se usar Google TTS)
  - GOOGLE_TTS_TIER (wavenet/neural2/chirp3)
  - AZURE_SPEECH_KEY + AZURE_SPEECH_REGION (se suportar Azure futuramente)
  - OPENAI_API_KEY (se suportar OpenAI futuramente)
  - ELEVENLABS_API_KEY (se suportar ElevenLabs futuramente)
  - YOUTUBE_API_KEY
  - COTACAO_USD_BRL
  - DRY_RUN_API
- Requisitos:
  - Validação de chave ao salvar (testar chamada real de sanity check)
  - Máscara na exibição (mostra só últimos 4 chars)
  - Botão "Testar chave" pra validar sem gerar conteúdo
  - Categorização visual: obrigatórias vs opcionais
- Quando fazer: Sessão 15 (polish) ou sessão dedicada antes de
  distribuição comercial
- Prioridade: NICE-TO-HAVE pra desenvolvimento, IMPORTANTE pra v2 comercial

### CLAUDE.md e prompt_abertura.md ficam desatualizados rápido
- Contexto: as sessões 9-18 divergiram bastante do que estava planejado
  originalmente (detecção de cena foi implementada E abandonada, TTS virou
  Google em vez de multi-provedor por padrão, Veo3 ficou só como
  scaffolding de prompt). `CLAUDE.md` e `prompt_abertura.md` foram
  atualizados nesta sessão de manutenção documental, mas tendem a ficar
  obsoletos de novo se sessões futuras não atualizarem as seções tocadas
- Ação sugerida: ao final de qualquer sessão que mude a arquitetura de
  pipeline (adicionar/remover/consolidar script), atualizar a seção
  correspondente do `CLAUDE.md` como parte da própria sessão, não deixar
  acumular
- Quando fazer: prática contínua, não uma sessão isolada
- Prioridade: IMPORTANTE pra manutenibilidade

### Cantos arredondados na legenda "pill" (estilo MrBeast)
- Contexto: documentado na Sessão 12 como limitação conhecida — o filtro
  `subtitles`/ASS do ffmpeg não desenha caixa com cantos arredondados atrás
  da palavra destacada, só retangular
- Ação sugerida: investigar alternativa via `drawtext` com máscara, ou
  aceitar caixa retangular como padrão definitivo
- Quando fazer: sessão de polish de legendas, sem urgência
- Prioridade: NICE-TO-HAVE, cosmético

### Heurística de agrupamento de legenda por pontuação vs duração
- Contexto: `6_montar_video.py` agrupa palavras em linhas de legenda usando
  uma heurística combinando pontuação e duração máxima por linha. Funciona
  mas pode gerar quebras de linha um pouco não naturais em frases longas
  sem pontuação
- Ação sugerida: revisar heurística com mais exemplos reais de roteiro
  antes de considerar definitiva
- Quando fazer: sessão de polish de legendas
- Prioridade: NICE-TO-HAVE

### ~~Botão "Regenerar briefing do fundo" só aparece após a primeira renderização~~ — OBSOLETO
- **Status: obsoleto** desde a sessão de simplificação da Etapa 7 (ver
  `HISTORICO_BUGS.md`) — o botão em questão vivia no aviso
  `fundo_status.json`, que só existia porque a etapa gerava um fundo
  SEPARADO pros templates Pillow (Grupo F antigo, `scripts/imagem/
  nenhum.py`/`gerar()`). Ambos foram removidos: a composição hoje é
  única (sujeito + fundo + texto numa imagem só, Grupo H) e o botão
  "Regenerar dados automáticos" da nova tela cobre o caso de
  `background_prompt` ruim sem depender de nenhuma renderização
  anterior. Mantido aqui só como registro histórico - remover numa
  próxima limpeza.

### Grupo A (nomes suspeitos) ainda não foi validado com resumo real de uma geração ao vivo
- Contexto: a Sessão 20 implementou `detectar_nomes_suspeitos`
  (CLAUDE.md seção 5.4.1) comparando nomes do roteiro contra um corpus
  construído do resumo estruturado da fase 1 de pesquisa
  (`pessoas_envolvidas` etc). A validação empírica da sessão (contra o
  roteiro real de `nancyGuthrieProject03`) precisou usar um resumo
  VAZIO como corpus, porque o resumo dessa geração original nunca foi
  persistido em disco (só passa em memória, é descartado após montar o
  prompt da fase 2) — então o teste rodou no pior caso possível (nenhuma
  confirmação disponível), não no caso real de produção
- Risco: com resumo vazio, a maioria dos ~17-24 nomes reais e legítimos
  do roteiro (Nancy Guthrie, Bryan Kohberger, Sheriff Nanos etc.) também
  aparece como suspeito nível `alto`/`medio` — em uma geração real, esses
  nomes normalmente estariam em `pessoas_envolvidas` (vieram de pesquisa
  real) e não seriam sinalizados, mas isso não foi confirmado numa
  chamada real à API
- Ação sugerida: na próxima geração real de roteiro (com `ANTHROPIC_API_KEY`
  configurada), conferir `job_metadata.json["nomes_nao_confirmados"]` —
  se o volume de nível `alto` continuar alto mesmo com resumo real
  preenchido, a heurística de extração de candidato (`PADRAO_CANDIDATO_NOME`)
  ou o corpus precisam de mais um ajuste
- Quando fazer: primeira sessão que revisar um roteiro gerado depois
  desta mudança
- Prioridade: IMPORTANTE

### Grupo C (número sem derivação) só reconhece números por extenso em inglês
- Contexto: `detectar_numeros_sem_derivacao` (CLAUDE.md seção 5.4.1)
  reconhece números por extenso ("forty-one") só em inglês — para
  pt-BR/es/de, só números em dígito são detectados. Números por extenso
  em outros idiomas simplesmente não disparam o aviso (falso negativo
  silencioso, nunca falso positivo)
- Ação sugerida: se o produto passar a gerar volume relevante de
  roteiros em pt-BR/es/de, adicionar as listas de números por extenso
  desses idiomas em `_NUMEROS_EXTENSO_EN` (renomear a constante)
- Quando fazer: quando houver uso real em idioma não-inglês
- Prioridade: NICE-TO-HAVE

### Grupo B (título divergente) nunca foi observado em uso real
- Contexto: a heurística lexical de `detectar_titulos_divergentes`
  (CLAUDE.md seção 5.4.1) foi calibrada só com exemplos inventados nos
  testes — nunca rodou contra uma geração real com `nucleo_editorial`
  preenchido pelo modelo (campo novo desta sessão)
- Ação sugerida: depois de algumas gerações reais, conferir se o aviso
  aparece com frequência razoável (nem sempre, nem nunca) e se os
  títulos sinalizados de fato divergem do gancho do roteiro
- Quando fazer: revisão de rotina após uso real acumular
- Prioridade: NICE-TO-HAVE

### Lista de risco do Headline Engine não é editável pela tela de Ajustes
- Contexto: `HEADLINE_TERMOS_RISCO` (CLAUDE.md seção 5.86/7) só é
  editável direto no `.env` — não foi adicionada ao formulário de
  `/ajustes` como os outros campos de texto configuráveis, decisão
  deliberada da Sessão 22 pra manter o escopo da sessão contido.
  Validação empírica da Sessão 24 (rodada real contra
  `nancyGuthrieProject03`, ver `HISTORICO_BUGS.md`) mostrou o juiz
  calibrando de forma razoável (notas 8-11/12 entre 6 candidatos
  diversos, aprovação de primeira rodada) — nenhum sinal ainda de que a
  lista padrão embutida precise de ajuste
- Ação sugerida: se a lista padrão embutida se mostrar insuficiente/
  ruidosa em uso real acumulado, adicionar campo de texto em Ajustes
  junto dos outros `LEGENDA_*`/TTS
- Quando fazer: sessão de polish da tela de Ajustes, ou antes se ficar
  claro que a lista padrão precisa de ajuste
- Prioridade: NICE-TO-HAVE

### Etapa 7 — composição via API (histórico das Sessões pós-26/29; itens 4-6 obsoletos desde a simplificação)
- Contexto: rastreador histórico da evolução da Etapa 7 desde a
  reconstrução pós-Sessão 26 (upload de sujeitos com papel declarado +
  briefing exportável) até a Sessão 29 (composição real via
  `gpt-image-2`/`gerar_composicao`, entregue e validada). Itens 4-6
  (caixa alta/sangramento da faixa diagonal nos templates Pillow,
  verificação de `gerar_thumbnail=False` contra o fluxo Pillow) ficaram
  **obsoletos por completo** na sessão de simplificação da Etapa 7 (ver
  `HISTORICO_BUGS.md`) — os 5 templates de composição via Pillow
  (`scripts/thumbnail_templates.py`) foram removidos por inteiro, então
  não há mais "caixa alta"/"faixa diagonal" nenhuma pra corrigir. O único
  item que sobreviveu é o 3:
  3. **Validação pós-geração por Vision.** Continua NÃO implementado.
     Depois que uma imagem sai do Grupo H, uma chamada Vision poderia
     conferir se os papéis estão nos lugares certos e se a composição
     bate com o template pedido — falha dispararia no máximo UMA
     regeneração com correção específica. Reavaliar depois de mais usos
     reais mostrarem (ou não) erros de composição que essa validação
     pegaria.
- Quando fazer: item 3 só depois de mais uso real acumulado
- Prioridade: NICE-TO-HAVE

### ~~Crop da composição por IA corta texto nas bordas (headline/texto grande)~~ — RESOLVIDO
- **Status: implementado** (sessão de correções de composição/interface,
  04/09/2026) — a raiz do problema nunca foi "a margem de segurança é
  fraca demais", era o próprio crop pós-geração: `_recortar_centro`
  (1536×1024 → 1280×720) rodava sobre QUALQUER imagem devolvida pela
  API em `gerar_composicao`, e o modelo posiciona texto (headline, texto
  grande) perto das bordas seguindo o próprio `briefing_completo` — duas
  tentativas de mitigar isso só com texto de prompt
  (`INSTRUCAO_AREA_SEGURA_16_9`, ver histórico abaixo) reduziram a
  frequência mas nunca eliminaram, porque `gpt-image-2` trata instrução
  de enquadramento como preferência forte, não como constraint rígido.
  A correção de verdade (opção "(b)" já cogitada abaixo, na prática
  mais simples que outpainting: não recortar em absoluto) — `gerar_composicao`
  passou a gravar exatamente os bytes que a API devolve, sem
  crop/resize/conversão de proporção nenhuma. A tela de thumbnail e a
  página de conclusão exibem essa imagem na proporção real (sem
  `aspect-ratio`/`object-fit` forçado por CSS) em vez de assumir 16:9.
  **Atualização (sessão seguinte, mesmo dia):** a correção acima resolveu
  o corte de texto mas deixou a imagem saindo em 3:2 (1536×1024) de
  verdade, porque o `size` pedido à API continuava sendo o mesmo do modo
  de fundo — premissa registrada na época ("API só aceita
  1024x1024/1024x1536/1536x1024") estava errada pro `gpt-image-2`
  especificamente. `gerar_composicao` agora pede `size="1536x864"`
  (16:9 exato, `TAMANHO_API_COMPOSICAO`) direto — nasce 16:9, sem crop
  nenhum em lugar nenhum do caminho. `INSTRUCAO_AREA_SEGURA_16_9`
  continua anexada ao prompt (ajuda a composição a deixar espaço
  generoso nas bordas), mas deixou de ser necessária pra "salvar" texto
  nem pra corrigir proporção. Ver `HISTORICO_BUGS.md` (duas entradas,
  04/09/2026) pro detalhe completo e `tests/test_imagem_openai.py::
  test_gerar_composicao_nunca_recorta_nem_redimensiona_a_imagem_devolvida`.
  Mantido aqui só como registro histórico do que já foi tentado antes
  desta correção - remover numa próxima limpeza.
- **Histórico (tentativas anteriores, já superadas):** Sessão 29
  reaproveitou `_recortar_centro` do modo de fundo-só sem margem de
  segurança nenhuma (achado real, `nancyGuthrieProject03`: "NANCY
  GUTHRIE UPDATE" e "THE MARK ON HIS WRIST" cortados). A sessão seguinte
  tentou mitigar só com `INSTRUCAO_AREA_SEGURA_16_9` (texto em pixels
  exatos anexado ao prompt) — validação empírica real (3 gerações pagas,
  mesmo briefing) mostrou variância grande: uma geração ficou quase
  perfeita, a seguinte com o MESMO prompt voltou a cortar as duas
  pontas, confirmando que texto de prompt sozinho não é solução
  confiável pra um crop que sempre vai acontecer depois.

### Emphasis_word sem destaque de cor em 5 dos 6 templates do briefing exportável (montar_prompt_investigator_update não usa _linha_pequena_e_grande)
- Contexto: só `INVESTIGATOR_UPDATE` destaca `emphasis_word` com a cor de
  accent dentro do headline (`"WRIST" in amber uppercase and the rest...
  in white uppercase"`) — é também o ÚNICO dos 6 montadores que não usa
  o helper compartilhado `_linha_pequena_e_grande` (usa `headline`/
  `emphasis_word` direto, numa linha só com duas cores). Os outros 5
  templates (`ARROW_TRIO`/`PROFILE_ISOLATION`/`EVIDENCE_SCENE`/
  `DUOTONE_DOSSIER`/`DUAL_PORTRAIT` — este último adicionado depois desta
  entrada original, ver sessão "conceito visual" em `HISTORICO_BUGS.md`)
  escrevem o headline inteiro numa cor só via `_linha_pequena_e_grande` —
  correto (nunca mais confundem `subject_name` com o headline, Sessão
  28), mas não aproveitam `emphasis_word` pra destacar a palavra-chave
  dentro da linha grande como as referências reais fazem
- Ação sugerida: extrair a lógica de destaque já usada em
  `montar_prompt_investigator_update` (headline + emphasis_word colorido
  como substring, nunca substituindo o headline) pra uma função
  compartilhada e reusar nos outros 5 templates
- Quando fazer: sessão de polish do briefing exportável — não bloqueia
  nada, o headline completo já aparece correto sem essa cor extra.
  Registrada deliberadamente como pendência (não corrigir sem decisão
  explícita — sessão "conceito visual", Parte 2, 09/09/2026)
- Prioridade: NICE-TO-HAVE

## NICE-TO-HAVE

### Margem da marca d'água do canal (2.5% da largura) é um ponto de partida, não validado visualmente ainda
- Contexto: sessão "Marca d'água do canal aplicada ao vídeo final"
  (11/09/2026, ver `HISTORICO_BUGS.md`) implementou o overlay
  (`scripts/marca_dagua_canal.py`) com margem das bordas proporcional a
  2.5% da largura real do vídeo (`MARGEM_PROPORCAO`) — valor escolhido
  por analogia com a margem segura de thumbnail (seção 5.85), nunca
  validado contra um PNG real renderizado na tela.
- Ação sugerida: depois da validação empírica desta sessão (subir um PNG
  de verdade em Ajustes, rodar uma montagem curta, abrir o vídeo final —
  ver `HISTORICO_BUGS.md`), se a margem ficar visualmente errada
  (grudada demais na borda, ou longe demais), ajustar só a constante
  `MARGEM_PROPORCAO` em `scripts/marca_dagua_canal.py` — mesmo espírito
  de `scripts/watermark_regions.py` ("pontos de partida... ajustar as
  constantes").
- Quando fazer: na primeira sessão em que o usuário reportar o resultado
  visual real (ou nunca, se a margem já ficar boa).

### Dedup de URL do modo separado só cobre YouTube, e só entre as duas listas do formulário
- Contexto: sessão de correção (07/09/2026, ver `HISTORICO_BUGS.md`)
  implementou `chave_dedup_youtube` (`scripts/validators.py`) +
  `_mesclar_fontes_separadas` (`server.py`) pra parar de baixar a mesma
  URL duas vezes quando ela aparece nas listas de transcrição E visual do
  modo separado (CLAUDE.md seção 5.7.2). Dois recortes deliberados,
  documentados aqui pra não serem confundidos com "não pensado":
  - **Só reconhece formato de URL do YouTube.** `yt-dlp` baixa de vários
    sites, mas o formulário já exige (`validar_url_youtube`) que todo
    link colado seja YouTube, então isso não é lacuna prática hoje — só
    fica documentado caso o produto um dia aceite outros domínios.
    URL não reconhecida como YouTube cai pra comparação de string crua
    (nunca funde por engano, mas também nunca detecta um mirror
    fora do YouTube apontando pro mesmo vídeo).
  - **Não deduplica dentro do MODO UNIFICADO** (uma única lista de
    links, sem distinção transcrição/visual) nem duas ocorrências da
    mesma URL dentro da MESMA lista do modo separado além do que já
    foi feito (isso já é coberto - ver
    `test_mesclar_fontes_duplicata_dentro_da_mesma_lista_nao_vira_ambos`).
    O cenário relatado pelo usuário era especificamente cross-lista;
    dedup dentro do modo unificado não foi pedido e ficou fora de
    escopo desta sessão.
- Ação sugerida: se um usuário reportar colar a mesma URL duas vezes
  dentro da lista única do modo unificado, `_mesclar_fontes_separadas`
  já tem a lógica pronta pra ser reaproveitada ali (aplicar o mesmo
  `chave_dedup_youtube` sobre uma lista só, sem a parte de mesclar
  tipo_uso).
- Quando fazer: só se/quando o cenário acima for reportado de verdade -
  não implementar preventivamente (CLAUDE.md seção 12, "extensão de
  escopo").

### Dois sistemas de modal coexistindo (dialog.modal antigo vs bf-confirm-* novo)
- Contexto: sessão de refinamento (04/09/2026) criou
  `static/confirm_modal.js` (`window.BrollFoundryConfirm.perguntar`) pra
  substituir `window.confirm()` nativo no botão "Finalizar projeto"
  (`static/thumbnail.js`) — auditoria completa não achou nenhum outro
  `confirm()`/`alert()` nativo, então nenhuma outra tela precisou mudar.
  Só que `templates/revisao_roteiro.html` ("Cancelar projeto") já usava
  um `<dialog class="modal">` PRÓPRIO, com classes antigas (`.botao`,
  `.botao-perigo`, `static/style.css`) — diferente do componente novo
  (classes `bf-confirm-*`, CSS injetado por `confirm_modal.js`,
  variáveis de `design_system.css`). Os dois visualmente parecidos (ambos
  usam `<dialog>` nativo com backdrop) mas não são o MESMO componente —
  duplicação de conceito, não de bug visível.
- Ação sugerida: migrar `modal-cancelar` (e qualquer outro `<dialog>` ad
  hoc que apareça) para `BrollFoundryConfirm.perguntar()`, ou o inverso
  (unificar tudo no padrão antigo) — o que importa é ter UM padrão só de
  modal de confirmação na aplicação inteira.
- Quando fazer: sessão de polish de UI, sem urgência — nenhum dos dois
  quebra o tema escuro hoje, é só duplicação de implementação.
- Prioridade: NICE-TO-HAVE

### ~~Escolha manual do frame de cenário como fundo da thumbnail~~ — OBSOLETO
- **Status: obsoleto** desde a sessão de simplificação da Etapa 7 (ver
  `HISTORICO_BUGS.md`) — não existe mais "fundo separado" nem candidato
  de cenário nenhum (`thumbnail/candidatos_cena/` removido); a
  composição nasce inteira (sujeito + fundo + texto) numa única chamada
  à OpenAI a partir do briefing. Mantido aqui só como registro histórico
  - remover numa próxima limpeza.

### ~~Segundo upload de sujeito na tela de thumbnail~~ — RESOLVIDO
- **Status: implementado** na reconstrução da Etapa 7 (sessão pós-Sessão
  26, CLAUDE.md seção 5.85) — foi além do pedido original: dois slots
  distintos (hero/secondary), cada um com papel declarado obrigatório,
  substituição/remoção direta na tela sem reload manual de código (o JS
  recarrega a página após upload/remoção, mas a ação em si é um clique).
  Mantido aqui só como registro histórico - remover numa próxima limpeza.

### Verificação automática de aderência à estrutura por dívida narrativa
- Contexto: a reestruturação do roteiro (Sessão 19) introduziu a
  Regra 0 (pergunta-promessa) e a estrutura por dívida narrativa
  (virada entre 60-75%, blocos fechando em pergunta aberta), mas a
  aderência do modelo a essas regras não é verificada automaticamente —
  só pela checklist final que o próprio prompt pede ao modelo
- Ação sugerida: um juiz por rubrica (chamada separada avaliando o
  roteiro gerado contra os critérios da Regra 0/estrutura) poderia
  validar isso automaticamente
- Quando fazer: só implementar se a validação empírica (Grupo H da
  Sessão 19) mostrar que o prompt sozinho não é suficiente — não
  implementar de antemão
- Prioridade: NICE-TO-HAVE, condicional

### Preview de upload com drag-and-drop
- Contexto: o formulário de upload de fontes visuais (Sessão 18, modo
  fontes separadas) aceita arquivo por input padrão, sem preview nem
  arrastar-e-soltar
- Ação sugerida: adicionar zona de drag-and-drop com preview de
  thumbnail/nome de arquivo antes de enviar
- Quando fazer: sessão de polish de UI de upload
- Prioridade: NICE-TO-HAVE

### Progress bar de upload de arquivo
- Contexto: upload de fontes visuais grandes (Sessão 18) não mostra
  progresso — usuário só vê "enviando..." sem indicação de %
- Ação sugerida: usar XHR com evento de progresso ou fetch com
  ReadableStream pra mostrar % de upload
- Quando fazer: sessão de polish de UI de upload
- Prioridade: NICE-TO-HAVE

### Paginação da lista de projetos
- **Contexto:** hoje a home mostra todos os projetos em lista simples.
  Quando chegar em 20+ projetos, vai ficar ruim de navegar
- **Ação sugerida:** paginação com contador total ("Mostrando 1-10 de
  47 projetos"), filtros por estado (concluído, em andamento, com
  erro), busca por nome
- **Quando fazer:** deixar pra Sessão 15 (polish) ou quando o usuário
  efetivamente tiver 20+ projetos e sentir a dor

### Fila de projetos em processamento simultâneo
- **Contexto:** hoje cada projeto processa isoladamente. Se o usuário
  criar 3 projetos seguidos, provavelmente eles vão competir por GPU
  (whisper) e API rate limits (Claude)
- **Ação sugerida:** implementar fila serializada (um projeto por vez)
  ou fila com limite configurável (2 em paralelo, por exemplo)
- **Quando fazer:** só se o usuário efetivamente precisar. Se ele
  sempre roda 1 projeto de cada vez, não é problema real

### Estimativa de tempo restante mais precisa
- **Contexto:** hoje o @PROGRESSO mostra pct mas não tempo estimado
  pra terminar cada etapa
- **Ação sugerida:** cada script mantém histórico interno de duração
  de execuções anteriores e usa isso pra estimar tempo restante mais
  realista
- **Quando fazer:** pós-MVP, quando tiver dados históricos suficientes

### Ordenação da lista de projetos
- Contexto: hoje a rota /projetos lista projetos em ordem
  alfabética, ignorando data de criação. Isso deixa a lista
  com ordem confusa quando o usuário cria vários projetos
- Ação sugerida: ordenar por data de criação decrescente
  (mais recentes primeiro). Baseado no timestamp da pasta
  ou no data_criacao do job.json
- Quando fazer: Sessão 15 (polish) junto com outras melhorias
  da home (paginação, filtros, botão voltar)

---

## BACKLOG (pós-MVP)

### Integração Veo3 pra geração de b-roll adicional
- **Contexto:** o scaffolding de prompt que existia (`veo3_estilo.md`/
  `veo3_linguagem_segura.md` por perfil, bloco de UI na tela de revisão,
  `opcoes_veo3.json`, campo `veo3_sera_oferecido` no `job_metadata.json`)
  foi removido numa sessão de limpeza de Ajustes (pós-Sessão 18) por não
  ter geração de cena real por trás e ter ficado sem manutenção. Uma
  implementação futura parte do zero, não deste scaffolding —
  `scripts/veo3/` e `5b_enriquecer_veo3.py` nunca chegaram a existir.
  CLAUDE.md seção 5.75 ainda documenta o desenho original como
  especificação de referência, mas está desatualizada quanto ao estado
  do código (não descreve mais nada que exista hoje) até uma sessão de
  manutenção documental
- **Quando:** sessão dedicada, custo alto por vídeo — ver CLAUDE.md
  seção 11

### Revisão manual de clipes gerados
- **Contexto:** hoje `5_gerar_clipes.py` roda e os clipes vão direto pra
  montagem. Adicionar etapa opcional entre geração de clipes e montagem
  final onde o usuário revisa e deleta os que não gostou, seguindo com
  os restantes
- **Quando:** sessão futura (planejada como Sessão 19 no
  `prompt_abertura.md`)

### Intro/ending customizados
- **Contexto:** permitir upload de `intro.mp4`/`ending.mp4` em `entrada/`,
  concatenados antes/depois do vídeo montado
- **Quando:** sessão futura pequena (planejada como Sessão 20 no
  `prompt_abertura.md`)

### Detecção visual pra deduplicar clipes similares (pHash ou Vision)
- **Contexto:** tentativa anterior (Sessões 9-10) usou PySceneDetect +
  pHash + Claude Vision e foi abandonada na Sessão 11 por custo/tempo sem
  ganho de qualidade suficiente (ver HISTORICO_BUGS.md). Reativar só faz
  sentido com abordagem mais barata/rápida que a testada
- **Quando:** só se duplicata visual virar reclamação real de qualidade

### Dashboard de tendências (Google Trends + YouTube trending + Reddit)
- **Contexto:** documentado no CLAUDE.md como "fora do escopo do MVP,
  fica pra v2"
- **Quando:** só depois de o produto amadurecer com o usuário
  produzindo vídeos regularmente

### Análise de performance de vídeos publicados via YouTube Analytics API
- **Quando:** v2

### Música de fundo com ducking automático
- **Quando:** v2

### Versão vertical 9:16 pra YouTube Shorts
- **Quando:** v2

### Detecção automática de posição de marca d'água
- **Contexto:** hoje é escolha manual do usuário no dropdown (6
  opções). Automação via análise de vários frames pra identificar
  região estática é possível mas complexa e falso positivo é péssimo
- **Quando:** só se manual virar dor de verdade

### Perfis adicionais além dos 3 do MVP
- **Contexto:** truecrime + atualidades_narrativas + historia são o
  MVP. Arquitetura permite adicionar novos sem tocar em código
- **Ideias pra futuro:** motivacional, culinária, tecnologia,
  educacional infantil, esportes
- **Quando:** só quando o usuário sentir vontade de expandir pra
  outros nichos

### Sistema de licença/ativação online
- **Contexto:** documentado no CLAUDE.md seção 17. Só faz sentido
  se/quando comercializar de verdade
- **Quando:** Fase 3 do faseamento de comercialização (100+ clientes
  pagantes mapeados)

---

## DECISÕES REGISTRADAS (contexto, não ação)

### faster-whisper permanece pinado exato no requirements.txt
- **Contexto:** apesar da seção 18.1 do CLAUDE.md sugerir pinning
  mínimo pra libs voláteis, faster-whisper foi mantido pinado exato
- **Razão:** faster-whisper recente exige CUDA 12 e cuDNN 9. Upgrade
  automático arrisca quebrar a compatibilidade da RTX 3070 Ti do
  usuário sem aviso
- **Quando reavaliar:** se surgir versão de faster-whisper com
  compatibilidade CUDA garantida mais ampla, ou se o usuário mudar de
  GPU

### Distribuição local, não SaaS
- **Contexto:** decisão firme documentada no CLAUDE.md seção 17
- **Razão:** custo operacional de SaaS com GPU + APIs proibitivo pra
  developer solo. Público-alvo valoriza "seus dados na sua máquina"

### Notas de rodapé de origem existem só no roteiro pra revisão
- **Contexto:** discussão explícita entre desenvolvedor e usuário
- **Regra:** notas `[F1@04:32]` aparecem no roteiro em Markdown na
  tela de revisão pra o humano conferir fatos, MAS são filtradas
  antes do TTS. O vídeo final não tem nem áudio nem visual de citação
- **Créditos no YouTube (descrição do vídeo):** responsabilidade do
  usuário, não da ferramenta

---

## SUGESTÕES DE OTIMIZAÇÃO DE COTA (Claude Code)

Baseado em análise de `/usage` do usuário (agosto 2026):
- 79% do uso veio de sessões subagent-heavy
- 15% em contexto >150k tokens
- 11% do uso especificamente do subagente `test-writer`

**Ações sugeridas se cota virar problema:**
1. Trocar modelo do `test-writer` em `.claude/agents/test-writer.md`
   de `claude-sonnet-5` pra `claude-haiku-4-5-20251001` (perde
   qualidade dos testes escritos, ganha bastante economia)
2. Usar `/compact` mid-task pra reduzir contexto em sessões longas
3. Usar `/clear` ao trocar de tarefa dentro da mesma sessão
