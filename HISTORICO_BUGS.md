# Histórico de Bugs — Broll Foundry

Registro cronológico dos bugs encontrados no projeto. Mais recente em
cima. Cada entrada segue formato:

**[Sessão / data] Título curto**
- **Status:** corrigido | pendente (link com MELHORIAS_PENDENTES.md)
- **Causa:** o que estava errado
- **Correção:** o que foi feito (ou o que precisa ser feito)
- **Impacto:** o que o usuário via / o que quebrava

Arquivo mantido manualmente. Ao fim de cada sessão de correção,
adicionar as entradas novas no topo.

---

## [Sessão "Intro e ending anexados ao vídeo final" — 14/09/2026] Feature nova: intro/ending opcionais anexados ao início/fim do vídeo montado

- **Status:** implementado. Suíte completa verde (2210 testes, +39 desta sessão).
- **Contexto:** vídeo pronto pra publicação geralmente precisa de uma vinheta
  de abertura e/ou encerramento (branding do canal) que não faz parte do
  b-roll cortado nem da narração — arquivo de vídeo importado pelo usuário,
  sempre primeiro/último, nunca participando da seleção aleatória de clipes
  nem da sincronização com a narração.
- **Decisão de arquitetura (Fase 1 de análise, reportada e seguida):**
  intro/ending são anexados numa etapa SEPARADA, DEPOIS de todo o pipeline
  de montagem já existente (concat de clipes + mux de narração/música +
  legenda queimada + marca d'água do canal) ter produzido o "núcleo" do
  vídeo — nunca entram em `clipes/indice.json` nem no concat/trim batelado
  da Etapa 5/6 existente. Isso evita qualquer mudança no timing interno já
  validado (slots de reorganização manual, sincronização com IA) e faz a
  legenda queimada nunca precisar de deslocamento (é queimada nos pixels
  ANTES de a intro existir no arquivo).
- **O que foi construído:**
  - `scripts/6_montar_video.py`: `descobrir_intro`/`descobrir_ending` (lê
    `entrada/intro.<ext>`/`entrada/ending.<ext>`, ambos opcionais);
    `_obter_specs_video_via_ffprobe`/`_tem_audio_via_ffprobe` (probing);
    `normalizar_intro_ending` (GRUPO B — reencoda pro MESMO
    codec/resolução/fps/pix_fmt do vídeo já montado, pulando o filtro de
    escala quando já bate; áudio sempre reencodado pra AAC, mesmo quando o
    vídeo é copiado — silêncio via `anullsrc` se a fonte não tiver áudio;
    aplica a MESMA marca d'água do canal, se configurada, na mesma
    passada); `anexar_intro_ending` (GRUPO C — concatena
    `[intro?, vídeo_pronto, ending?]` via demuxer `-c copy`, já que os 3
    segmentos compartilham o mesmo padrão após a normalização). Falha em
    QUALQUER ponto (normalização ou concat final) nunca derruba a montagem
    — cai de volta pro vídeo sem intro/ending, com o motivo real registrado
    em `avisos`/`montagem_metadata.json`.
  - **Áudio (decisão fechada da especificação):** a narração NUNCA começa
    junto com a intro — começa exatamente no fim dela (a narração já está
    "dentro" do vídeo-núcleo antes de a intro ser prependida, então isso é
    automático por construção, sem lógica extra). Intro/ending mantêm o
    próprio áudio se tiverem, ou silêncio.
  - **Legenda (decisão fechada da especificação):** legenda queimada nunca
    toca intro/ending (queima acontece antes — caminho escolhido em vez de
    deslocar o timing do ASS). O softsub (SRT sempre embutido, último passo
    do pipeline) É deslocado: `gerar_srt` ganhou `offset_s` — quando a
    intro é aplicada com sucesso, `saida/legendas.srt` é regravado com
    `offset_s = duração real da intro normalizada` antes do embed final.
    Teste obrigatório da especificação
    (`test_montar_video_pipeline_completa_com_intro_desloca_softsub_e_marca_metadata`)
    confirma que a primeira legenda do SRT final bate exatamente com o
    início da narração, nunca antes.
  - `scripts/validators.py`: `validar_extensao_intro_ending` +
    `validar_video_legivel_ffprobe` (checa stream de vídeo decodificável e
    duração > 0 via ffprobe — avisa cedo no formulário, não só na
    montagem).
  - `server.py`: campos `intro_arquivo`/`ending_arquivo` no formulário de
    Novo projeto (compartilhado entre pipeline completa e "vídeos
    pré-gerados"), salvos num arquivo TEMPORÁRIO pra validação via ffprobe
    (nenhum projeto existe ainda no momento da validação) e só movidos pra
    `entrada/intro.<ext>`/`entrada/ending.<ext>` depois que toda a
    validação passa (`_validar_e_preparar_upload_intro_ending`,
    `_salvar_intro_ending`, `_descartar_temp_intro_ending` — erro por
    qualquer outro motivo do formulário descarta o temp, nunca vaza
    arquivo órfão). `_descobrir_intro_ending_info` alimenta a tela de
    reorganização.
  - `templates/novo_projeto.html` + `static/novo_projeto.js`: upload com
    preview de nome + duração (lida do próprio arquivo via
    `<video>.duration` no navegador, sem round-trip ao servidor) + botão
    remover.
  - `templates/reorganizar_clipes.html`: blocos fixos (`.timeline-fixo`,
    `draggable="false"`) nas duas pontas de `#timeline-track`, fora da
    classe `.timeline-clipe` que o JS de drag-and-drop consulta — trava
    estrutural, não uma checagem em runtime (o JS nunca vê esses blocos,
    então nunca há "tentativa de mover" pra rejeitar).
- **Retrocompatibilidade:** projeto sem `entrada/intro.*`/`entrada/ending.*`
  (todo projeto criado antes desta sessão) — `descobrir_intro`/
  `descobrir_ending` retornam `None`, `anexar_intro_ending` retorna o vídeo
  original SEM chamar ffprobe/ffmpeg nenhuma vez (custo zero), e o comando
  de montagem final é byte-a-byte idêntico ao de antes desta sessão.
- **Testes:** `tests/test_montar_video.py` (24 testes novos — descoberta,
  specs/áudio via ffprobe, normalização pura e mockada, concat final,
  falha não-fatal nos dois pontos, offset de SRT, integração ponta-a-ponta
  nos dois tipos de projeto), `tests/test_validators.py` (7 testes novos),
  `tests/test_intro_ending_rotas.py` (9 testes novos — upload/validação no
  formulário, blocos fixos na reorganização). Suíte completa:
  `.\venv\Scripts\python.exe -m pytest -x --tb=short` → 2210 passed.
- **Validação empírica pendente do usuário** (não automatizável): subir uma
  intro com codec/resolução diferente do padrão do projeto, montar um vídeo
  de teste, e abrir o resultado conferindo (1) a intro aparece inteira, sem
  corte nem dessincronia visual, (2) a primeira legenda embutida (softsub)
  aparece exatamente quando a narração começa — não antes, (3) a marca
  d'água do canal (se configurada) aparece sobre a intro/ending também, (4)
  na tela de reorganização de clipes, os blocos "Intro"/"Ending" aparecem
  fixos nas pontas e não acionam nenhum drag ao tentar arrastá-los.

---

## [Sessão "Marca d'água do canal aplicada ao vídeo final" — 11/09/2026] Feature nova: overlay do logo do usuário sobre o vídeo final (Etapa 6)

- **Status:** implementado. Suíte completa verde (2171 testes).
- **Contexto:** até esta sessão só existia remoção de marca d'água das
  FONTES (`entrada/marcas_dagua.json`, filtro `delogo`, Etapa 5). Esta
  sessão implementa o oposto — aplicar a marca d'água do CANAL (logo do
  usuário, PNG com transparência) por cima do vídeo já montado.
- **O que foi construído:**
  - `scripts/marca_dagua_canal.py` (módulo novo, puro/sem I/O): geometria
    das 4 posições de canto, cálculo de largura (10% da largura real do
    vídeo, via `ffprobe`) e margem (2.5% proporcional), sempre em função
    da largura REAL do vídeo — nunca assume 1920 fixo, porque
    "vídeos pré-gerados" (CLAUDE.md seção 3) pode ter outra resolução.
  - `scripts/6_montar_video.py`: `resolver_marca_dagua` decide entre
    "canal" (marca global de Ajustes), "outra" (upload próprio do
    projeto, `entrada/marca_dagua_canal.png`) e "nenhuma"
    (`configuracao_video.json["marca_dagua_projeto"]`, default "canal").
    `aplicar_marca_dagua`/`construir_comando_marca_dagua` fundem o
    overlay da marca com a queima de legenda (`ass=`/`subtitles=`) num
    ÚNICO `filter_complex`, quando as duas estão ativas — nunca uma
    segunda passada de reencode só pra marca quando já existe uma pra
    legenda. Sem marca configurada, o caminho de montagem é
    byte-a-byte idêntico ao de antes desta sessão (nenhuma passada de
    reencode extra é introduzida). Aplicado nos DOIS caminhos de
    montagem (`_montar_video_pipeline_completa` E
    `montar_video_videos_pre_gerados`) — GRUPO D da especificação.
  - `server.py`: PNG global salvo em local fixo fora de qualquer projeto
    (`config/marca_dagua_canal.png` + `config/marca_dagua_canal.json`
    de metadata), upload/remoção via rotas AJAX
    (`/ajustes/marca_dagua/upload`/`/remover`/`arquivo`) — mesmo padrão
    do upload de sujeito da Etapa 7. Posição (4 cantos) persistida como
    `MARCA_DAGUA_CANAL_POSICAO` em `CAMPOS_AJUSTES` (.env, texto normal).
    Sobrescrita por projeto no formulário de Novo projeto (radio
    "canal"/"outra"/"nenhuma", campo compartilhado entre pipeline
    completa e vídeos pré-gerados) persistida em
    `entrada/configuracao_video.json["marca_dagua_projeto"]`.
  - Validação de PNG (`_validar_png_marca_dagua`, via Pillow): formato
    PNG real obrigatório (bloqueia), canal alfa ausente vira só aviso
    (nunca bloqueia — opacidade de 40% ainda funciona sobre fundo opaco,
    só não tem "buraco" transparente).
  - Falha em qualquer ponto (PNG ausente/corrompido, erro real do ffmpeg
    no overlay) nunca derruba a montagem — cai de volta pro caminho sem
    marca (ou só-legenda, se havia), registrando o motivo real do erro em
    `montagem_metadata.json["marca_dagua_aviso"]` e no `avisos` do
    `@PROGRESSO` final (CLAUDE.md seção 18.4/18.5).
- **Retrocompatibilidade:** projeto sem o campo `marca_dagua_projeto`
  (todo projeto criado antes desta sessão) cai no default "canal" — só
  tem efeito visível se o usuário já tiver configurado uma marca global
  em Ajustes; sem isso, comporta-se exatamente como "nenhuma".
- **Testes:** `tests/test_marca_dagua_canal.py` (geometria pura),
  `tests/test_montar_video.py` (resolução/comando/integração ponta-a-
  ponta nos dois tipos de projeto, não-regressão sem marca configurada,
  fusão com legenda numa única passada, falha nunca derruba o vídeo) e
  `tests/test_marca_dagua_canal_rotas.py` (rotas de Ajustes e Novo
  projeto).
- **Validação empírica pendente do usuário** (não automatizável): subir
  um PNG de verdade em Ajustes, rodar uma montagem curta e abrir o vídeo
  final pra conferir posição/tamanho/opacidade reais na tela.

## [Sessão "correção pontual — relação causal do conceito visual" — 09/09/2026] `montar_clausula_conceito_visual` produzia frase quebrada + prefixo de categoria redundante

- **Status:** corrigido. Suíte completa verde (2124 testes).
- **Causa:** `montar_clausula_conceito_visual` (`scripts/
  thumbnail_briefing.py`, Grupo E da sessão "conceito visual" acima)
  tinha dois problemas de montagem textual (nunca de dado — o
  `conceito_visual` extraído pelo Headline Engine estava correto):
  1. Prefixava `elemento_principal` com uma tradução genérica de
     `tipo_elemento` (`_INTRO_POR_TIPO_ELEMENTO`) — quando
     `elemento_principal` já nomeava a coisa concreta (ex: "the doorbell
     camera"), o resultado duplicava a categoria: "a piece of
     recording/camera equipment, the doorbell camera...".
  2. Conectava `acao_ou_momento` e `revelacao` com "- a moment that
     directly leads to {revelacao}" — quebra sempre que `revelacao`
     chegava como oração completa (sujeito+verbo) da IA, caso comum.
     Caso real (Nancy Guthrie): "...to block the doorbell camera lens -
     a moment that directly leads to the blocking motion rotates his
     wrist into view..." — gramaticalmente inválido, "leads to" seguido
     de uma oração com verbo conjugado.
- **Correção:** removido o prefixo de categoria por completo (junto dos
  dicts `_TIPOS_ELEMENTO_VALIDOS`/`_INTRO_POR_TIPO_ELEMENTO`, que
  ficaram sem uso). Conector entre ação e revelação trocado por ", as
  {revelacao}" — encaixa gramaticalmente tanto com revelação em forma de
  oração quanto de frase nominal, sem forçar `revelacao` a completar a
  sintaxe de `acao_ou_momento`. Adicionado um ramo defensivo novo
  (revelação sem ação, sem inventar ação) que a versão anterior não
  cobria explicitamente. Nenhuma mudança em schema, Headline Engine,
  templates, seleção de template, prompts de IA ou persistência —
  correção 100% determinística/local à função.
- **Impacto:** briefing de composição de imagem (Grupo H, `gpt-image-2`)
  recebia instrução com sintaxe quebrada na cláusula do conceito visual
  — risco de o modelo de composição ignorar ou interpretar mal a cadeia
  causal elemento→ação→revelação, que é o mecanismo inteiro que essa
  função existe pra transportar.
- **Pendência relacionada (não corrigida nesta sessão, fora de escopo):**
  `descrever_pessoa_para_prompt` tem a mesma classe de bug (empilhamento
  de atributos do Vision sem checar coerência — ex: "neutral expression"
  e "intense emotional expression" no mesmo texto) — ver
  `MELHORIAS_PENDENTES.md`.

## [Sessão "conceito visual" — 09/09/2026] Eixo editorial de 3 campos livres (evidencia_central/conflito/data_chave) substituído por conceito visual estruturado + consumo pelos 6 templates de composição — Parte 1 e Parte 2

- **Status:** corrigido/implementado nas duas partes. Suíte completa
  verde (2128 testes) ao fim da Parte 2. Validado contra a API real no
  caso Nancy Guthrie (Grupo K, abaixo).
- **Causa raiz (o que motivou a sessão):** o mecanismo anterior de "eixo
  editorial" (`evidencia_central`/`conflito`/`data_chave`, 3 campos de
  texto livre pedidos na chamada de metadados — Grupo D,
  `scripts/7_thumbnail.py`) era injetado DE VOLTA como cabeçalho no
  roteiro entregue ao Headline Engine (`_montar_roteiro_com_eixo_
  editorial`/`_aplicar_headline_engine`) — uma dependência CIRCULAR: o
  Grupo D (que roda depois do Headline Engine na ordem antiga) produzia
  um eixo que só existia pra enriquecer uma chamada anterior, então o
  Headline Engine (Grupo A) nunca tinha esse contexto na primeira vez que
  rodava de verdade. Resultado prático: `evidencia_central`/`conflito`/
  `data_chave` voltavam vazios da chamada real mesmo com título/núcleo
  editorial claros (achado original, caso Burke Ramsey/JonBenét, sessão
  anterior).
- **Parte 1 (Grupos A-D — já concluída antes desta entrada, registrada
  aqui retroativamente porque nunca tinha sido logada):**
  - `scripts/headline_engine.py`: a chamada de Grupo A
    (`extrair_payload_editorial`) ganhou 5 campos novos NA MESMA resposta
    (zero custo de API extra) — `elemento_principal`/`tipo_elemento`
    (enum `pessoa`/`objeto`/`documento`/`camera_filmagem`/`local`/`outro`
    — `camera_filmagem` separado de `objeto` de propósito, ver Parte 2)/
    `acao_ou_momento`/`revelacao`/`papel_na_composicao`
    (`dominante`/`apoio`). `_normalizar_conceito_visual` zera
    `acao_ou_momento`+`revelacao` juntos se um vier vazio (nunca persiste
    revelação órfã).
  - Ordem da pipeline INVERTIDA: `headline_engine.gerar_headline` passou
    a rodar ANTES de `_chamar_claude_metadados` em `gerar_metadados`/
    `regenerar_thumbnail_briefing` — o `elemento_principal` extraído vira
    a âncora obrigatória do `background_prompt` (novo parâmetro
    `elemento_principal` em `_chamar_claude_metadados`), eliminando a
    dependência circular.
  - `evidencia_central`/`conflito`/`data_chave` removidos por inteiro do
    `SCHEMA_METADADOS`/normalização/reparo/prompt (`scripts/prompts/
    metadados_thumbnail.md`); `_montar_roteiro_com_eixo_editorial`/
    `_aplicar_headline_engine`/`_normalizar_evidencia_central`/
    `_eixo_editorial_vazio` removidos, substituídos por
    `_mesclar_headline_em_thumbnail` (merge puro do resultado do Headline
    Engine) + `validar_consistencia_headline_conceito` (código puro —
    `conceito_visual_ausente=True` quando `elemento_principal` vem vazio,
    substitui `eixo_editorial_ausente`).
  - `resolver_relacao_com_sujeitos` (`scripts/thumbnail_briefing.py`)
    também já existia da Parte 1 — resolve a qual sujeito (hero/secondary)
    o elemento pertence, só quando há ambiguidade real (2 sujeitos com
    papéis distintos).
  - **Efeito colateral conhecido e aceito:** 36 testes de
    `tests/test_thumbnail.py` quebraram (mecanismo testado deixou de
    existir) — registrados em `MELHORIAS_PENDENTES.md` como "conhecidos,
    aguardando reescrita na Parte 2", explicitamente para não serem
    confundidos com regressão nova.
- **Parte 2 (Grupos E-L, esta entrada):**
  - `scripts/thumbnail_briefing.py`: `montar_clausula_conceito_visual(
    conceito)` — função PURA nova (mesmo padrão de `_linha_pequena_e_
    grande`) que monta a cláusula em código, nunca pede à IA como texto
    livre. Transporta a cadeia CAUSAL completa (elemento → ação →
    revelação), nunca só os 3 campos concatenados soltos — motivada
    explicitamente pela mesma classe de bug de `_ajustar_genero_e_
    prefixo_para_crianca` (texto livre empilhado sem checar coerência
    produz frases incoerentes/fracas). Os 6 `montar_prompt_<template>`
    (incluindo `DUAL_PORTRAIT`, que antes usava `_descricao_evidencia_
    central`/`evidencia_central` pro mecanismo de tensão — agora usa o
    conceito visual, encaixe natural porque o design do template já era
    "tensão aponta pro objeto/documento, nunca pra pessoa") passaram a
    chamá-la.
  - `_frase_dominancia_conceito(clausula, papel_composicao,
    background_desc)` — prioridade SEMÂNTICA do conceito sobre o
    `background_prompt`: os dois nunca se substituem, só coexistem.
    `papel_na_composicao == "dominante"` põe o conceito primeiro no texto
    (fundo vira pano de fundo secundário, mencionado depois);
    `"apoio"` (padrão) mantém o fundo como âncora primária com o conceito
    como detalhe dentro da cena.
  - `selecionar_template` ganhou um parâmetro `conceito_visual` — resumo
    textual injetado como contexto ADICIONAL na MESMA chamada de seleção
    que já existia (zero chamadas novas). `templates_elegiveis` continua
    decidindo por CATEGORIA de papel (layout); o conceito ajuda a
    escolher, dentro do enum já fechado, qual estética narra melhor
    aquele elemento.
  - Campos mortos removidos por completo: `caso["evidencia_central"/
    "conflito"/"data_chave"]` e a chave `eixo_editorial` da auditoria de
    `briefing.json` (que só existiam como pass-through vazio desde a
    Parte 1 — nunca mais populados pelo Grupo D, mas ainda lidos/
    persistidos até esta sessão terminar de limpar).
  - `templates/thumbnail.html`: bloco de LEITURA do conceito visual
    (elemento/tipo/ação/revelação) acima do textarea do briefing — sem
    campo editável próprio, a fonte canônica editável continua sendo
    `briefing_completo`.
  - **Grupo J — reescrita dos 36 testes conhecidos:** os testes de
    `evidencia_central`/`eixo_editorial`/`_montar_roteiro_com_eixo_
    editorial` sem substituto 1:1 foram apagados (função removida, não
    só renomeada); os que testavam o CONTRATO de schema/prompt foram
    reescritos pro conteúdo novo (`elemento_principal` como âncora); os
    de mock de `cliente_api` (Grupo 3 — presumiam que a primeira chamada
    era a de metadados, agora é a do Headline Engine) foram corrigidos
    com um helper novo `_mockar_headline_engine(monkeypatch, **overrides)`
    que substitui `headline_engine.gerar_headline` por inteiro (mesmo
    padrão já usado, e já verde, por dois testes que sobreviveram à
    Parte 1 sem quebrar). Testes novos: `montar_clausula_conceito_visual`
    por tipo de elemento/com-sem revelação, enforcement estrutural
    parametrizado sobre `_MONTADORES.items()` (marcadores únicos por
    campo, detecta template que só copie `elemento_principal` sem a
    relação causal), fallback quando Grupo A falha, projeto antigo sem
    `conceito_visual`, 0/1/2 sujeitos, mesmo conceito em dois templates
    diferentes. `pytest -x --tb=short` final: **2128 passed**.
  - **Grupo K — validação contra API real (caso Nancy Guthrie, projeto
    `nancyGuthrieProject01`, cópia mínima em scratchpad — roteiro/título/
    fotos de sujeito, nunca o projeto real em disco):** `gerar_metadados`
    real produziu headline `"The Branch That Backfired"` (mecanismo
    `reversao`) e conceito visual `elemento_principal`: "the doorbell
    camera and the suspect's wrist as he reaches to block the lens"
    (`tipo_elemento`: `camera_filmagem`, `papel_na_composicao`:
    `dominante`). O `briefing_completo` final (template
    `INVESTIGATOR_UPDATE`, escolhido automaticamente) expressa os 4 elos
    pedidos pra validação — 3 deles LITERALMENTE no texto da cláusula
    visual: (1) a tentativa de bloquear a câmera — "the masked figure
    reaching up with a branch to block the doorbell camera lens"; (2) o
    movimento do pulso — "the blocking motion rotates his wrist into
    frame"; (3) a tatuagem revelada — "exposing a tattoo on the
    underside of his right wrist", ligada explicitamente ao movimento
    por "a moment that directly leads to". O 4º elo (possibilidade de
    identificação a partir da tatuagem) NÃO aparece como frase literal
    no `briefing_completo` — existe no `hidden_question`/`tension_source`
    do payload editorial do Headline Engine ("...how could that one
    detail be the thing that identifies him?"), mas esses campos não
    fazem parte do `conceito_visual` (que é escopado só a elementos
    VISUAIS concretos, nunca a implicação narrativa) e por isso não são
    transportados pra dentro do prompt de composição de imagem — a
    implicação de identificação fica carregada pelo HEADLINE em si
    ("BACKFIRED" = a ação se voltou contra ele), não pela cena visual.
    Reportado honestamente em vez de forçar aprovação (custo real da
    chamada: ~$0,049 Grupo D+C + ~$0,040 Headline Engine).
- **Impacto:** thumbnails com âncora visual concreta e auditável desde a
  extração (Headline Engine) até a composição final (briefing), sem
  dependência circular entre etapas; 6 templates de composição
  (`DUAL_PORTRAIT` incluído) todos incorporando o mesmo mecanismo de
  forma consistente, cada um com sua própria estética.

---

## [Sessão — 09/09/2026] Briefing stale sobrevivia a upload de sujeito (flag booleana não bastava) + mensagem de indisponibilidade de template mentia em caso de exclusividade

- **Status:** corrigido, cobertura de testes A-H (fingerprint) +
  parametrizado (mensagem contextual) em `tests/test_thumbnail_briefing.py`
  e `tests/test_thumbnail_composicao_rotas.py`. Suíte completa verde
  (2110 testes).
- **Causa raiz 1 (estado do briefing):** `thumbnail.briefing_desatualizado`
  era uma flag booleana setada so' explicitamente por
  `thumbnail_atualizar_papel_sujeito` (troca de papel de um slot JA
  preenchido) — `thumbnail_upload_sujeito` (upload de sujeito NOVO) nunca
  a setava. Resultado: um briefing de `EVIDENCE_SCENE` gerado
  automaticamente pela Etapa 7 ANTES de qualquer sujeito existir
  continuava sendo mandado pra' `POST /thumbnail/gerar_composicao_ia`
  mesmo depois do usuário enviar hero+secondary, porque nenhum caminho de
  código jamais marcava a flag nesse fluxo (caso real Nancy Guthrie:
  thumbnail saiu sem nenhum dos dois rostos apesar das fotos disponíveis).
- **Correção 1:** `scripts/thumbnail_briefing.calcular_fingerprint_sujeitos`
  — hash SHA-256 determinístico de
  `{hero.arquivo, hero.papel, secondary.arquivo, secondary.papel}`
  (`sort_keys=True`, sem timestamp/ordem de upload). `gerar_briefing_completo`
  persiste esse fingerprint em `briefing.json` e devolve
  `subjects_fingerprint`; `_aplicar_briefing_grupo_c`
  (`scripts/7_thumbnail.py`) grava em
  `metadados.thumbnail.briefing_subjects_fingerprint`. `server.py:_briefing_stale`
  compara o fingerprint salvo contra o fingerprint ATUAL de
  `sujeitos.json` — briefing sem fingerprint (legado) é tratado como
  stale por padrão. **O ponto crítico:** essa checagem foi inserida
  dentro de `POST /thumbnail/gerar_composicao_ia`, logo depois de resolver
  `briefing_completo` e ANTES de montar a chamada pra' `imagem_openai.gerar_composicao`
  — bloqueia com `erro_tipo: "briefing_desatualizado"` (HTTP 400) em vez
  de regerar sozinho (mesmo espírito de nunca chamar API paga sem o
  usuário pedir). A flag antiga continua existindo e sendo setada
  (consumida pelo banner da tela, `briefing_stale or textos.briefing_desatualizado`
  no Jinja), mas nunca mais é a única defesa — qualquer rota futura que
  mexer em `sujeitos.json` fica protegida automaticamente só pela
  comparação de fingerprint, sem precisar lembrar de invalidar nada.
- **Causa raiz 2 (mensagem de indisponibilidade):**
  `MOTIVO_CURTO_INDISPONIVEL` era um dict estático por template
  ("requer sujeito principal", "requer 2 sujeitos") que descrevia o
  REQUISITO estrutural sem saber se ele já tinha sido atendido. Em
  hero=vítima + secondary=investigador (`INVESTIGATOR_UPDATE` vence com
  exclusividade), o seletor mostrava "PROFILE_ISOLATION — indisponível:
  requer sujeito principal" mesmo COM sujeito principal presente, e
  "DUAL_PORTRAIT — indisponível: requer 2 sujeitos" mesmo com os dois
  sujeitos presentes.
- **Correção 2:** `thumbnail_briefing.motivo_indisponibilidade(template, hero_papel, secondary_papel)`
  distingue (A) requisito estrutural não atendido (mantém o texto
  estático, ainda correto) de (B) requisito atendido mas outra regra de
  exclusividade de `templates_elegiveis` venceu (usa a mensagem genérica
  `MOTIVO_GENERICO_INDISPONIVEL = "Não elegível para esta combinação de
  sujeitos."`). Só `PROFILE_ISOLATION`/`DUOTONE_DOSSIER`/`DUAL_PORTRAIT`
  podem cair no caso B — os demais nunca perdem por exclusividade uma vez
  que seu requisito é atendido (ver docstring de `templates_elegiveis`).
  `server.py` (tela de thumbnail + `thumbnail_atualizar_papel_sujeito`)
  passa a mandar `thumbnail_briefing.motivos_indisponibilidade(hero_papel, secondary_papel)`
  em vez do dict estático — `static/thumbnail.js:atualizarElegibilidadeTemplate`
  ganhou um 3º parâmetro pra' usar a versão fresca vinda da resposta AJAX
  em vez da cópia estática carregada no load da página.
- **Nenhuma regra de `templates_elegiveis`, do Headline Engine, dos
  templates de composição ou da geração de imagem foi tocada** — escopo
  desta sessão foi deliberadamente restrito a estado do briefing +
  mensagem de indisponibilidade.
- **Impacto:** composição por IA não corre mais o risco de descrever
  sujeitos que não existiam quando o briefing foi gerado; o seletor de
  template nunca mais afirma que falta um sujeito que na verdade está
  presente.

---

## [Sessão — 08/09/2026] DUAL_PORTRAIT confundia "não implicar culpa" com "sem tensão nenhuma" — caso real Burke Ramsey/JonBenét

- **Status:** corrigido, validado com chamada REAL à API Anthropic (Vision
  + seleção de template + protagonista) contra o projeto `jonBenetRamsey01`.
- **Causa raiz:** `montar_prompt_dual_portrait`
  (`scripts/thumbnail_briefing.py`) nasceu com a restrição correta e
  obrigatória de nunca implicar culpa entre os dois sujeitos (Burke
  Ramsey foi excluído por DNA em 1999 e exonerado por carta oficial —
  insinuar culpa dele visualmente é exatamente o ato que gerou o
  processo dele contra a CBS), mas traduziu isso em estética
  inteiramente NEUTRA. Briefing real gerado pra' esse projeto continha,
  literalmente: `"no visual implication of guilt or accusation between
  them"` (correto), `"calm, contemplative half-smile"`,
  `"Neutral, balanced lighting, composed and dignified"` e
  `"portraits of equal visual importance"` — resultado: composição
  parecida com retrospectiva memorial, num feed onde a concorrência usa
  alto contraste, seta vermelha e carga emocional. São duas coisas
  diferentes: não acusar (obrigatório) e não ter tensão (erro — a
  tensão pode e deve existir, apontando pra' outro lugar).
- **Correção:** reescrita de `montar_prompt_dual_portrait` — a restrição
  passa a ser sobre o ALVO da tensão, nunca sobre a existência dela.
  Permitido agora: alto contraste e sombras profundas, composição
  assimétrica (com o protagonista definido pelo eixo editorial
  dominando de verdade, closer to camera), expressão emocional real
  ("never a neutral or calm half-smile" — instrução explícita CONTRA o
  padrão antigo), e um recorte/seta na cor de destaque apontando pra'
  `evidencia_central` (documento, objeto, data, elemento institucional)
  quando disponível. Proibido continua: qualquer seta/fita/elemento
  ligando ou apontando de um sujeito PRA' o outro — isso sim implicaria
  acusação. `"portraits of equal visual importance"` foi removido por
  completo (contradizia textualmente o mecanismo de protagonista
  dominante/complementar já implementado numa sessão anterior -
  `caso["protagonista"]`). Textos auxiliares (`_DESCRICAO_TEMPLATE`,
  `DESCRICAO_AMIGAVEL_TEMPLATE`, `NOME_EXIBICAO_TEMPLATE` — este último
  trocou "Retrato duplo neutro" por "Retrato duplo sem acusação") também
  atualizados pra' não prometer neutralidade.
- **Auditoria dos outros 5 templates** (`ARROW_TRIO`, `PROFILE_ISOLATION`,
  `EVIDENCE_SCENE`, `DUOTONE_DOSSIER`, `INVESTIGATOR_UPDATE`): nenhum
  outro continha `"neutral"`/`"balanced"`/`"dignified"`/`"equal visual"`
  como diretiva estética (grep confirmado). `PROFILE_ISOLATION` usa
  "subtle fog"/"subtle atmospheric lighting" mas isso é textura
  atmosférica combinada com "strong contrast" no mesmo prompt — tom
  "mais contido/reflexivo" é escolha DELIBERADA de design daquele
  template (retrato solo, tom sóbrio), não efeito colateral de uma
  restrição ética como no DUAL_PORTRAIT.
- **Nuance encontrada na validação real (fora do escopo desta correção):**
  `secondary.atributos.expressao` (extraído por Vision, não pelo
  template) ainda voltou "a calm, thoughtful look with a subtle slight
  smile" pra' esta foto específica de Burke — é a leitura genuína da
  IA sobre a foto real enviada (dado, não diretiva editorial), fora do
  critério de validação desta sessão (que cobriu só as 4 frases-diretiva
  do template). Fabricar uma expressão diferente da que a foto realmente
  mostra seria pior, não melhor — não alterado.
- **Impacto:** thumbnails de casos sem relação de acusação clara entre
  dois sujeitos (vítima+parente, duas testemunhas, etc. — exatamente o
  caso Burke Ramsey/JonBenét) saíam visualmente mornas, num nicho onde
  a concorrência aposta pesado em contraste e emoção — sem nenhuma
  necessidade editorial real de suprimir a tensão, só a acusação.
- **Validação real (obrigatória por instrução desta sessão):** chamada
  completa (`gerar_briefing_completo`, Vision + seleção de protagonista
  + montagem do prompt) contra a API Anthropic real, projeto
  `jonBenetRamsey01`, forçando `DUAL_PORTRAIT`. Checagem por frase exata
  (não por palavra solta — "neutral"/"balanced" aparecem legitimamente
  em negações como "never a neutral or calm half-smile" e "deliberately
  unbalanced composition") confirmou AUSÊNCIA de `"neutral, balanced
  lighting"`, `"composed and dignified"`, `"equal visual importance"` e
  `"calm, contemplative half-smile"` no `briefing_completo` final, e
  PRESENÇA de `"high-contrast"`, `"deep shadows"`, `"asymmetric
  composition"` e do recorte apontando pra' `"a sealed forensic evidence
  envelope with a DNA lab report and swab, marked 1999"` (nunca pra'
  nenhuma das duas pessoas). Protagonista corretamente identificado
  como "secondary" (Burke), consistente com o eixo editorial. Testes
  novos em `tests/test_thumbnail_briefing.py` (checagem por frase exata
  das 4 diretivas banidas + presença dos elementos de tensão + evidência
  apontando pro objeto nunca pra' pessoa) e 2 testes existentes
  ajustados pra' nova redação do prompt (mantendo as mesmas garantias
  estruturais: nunca seta entre os dois, protagonista na posição
  dominante). Suíte completa: 2088 testes verdes.

---

## [Sessão — 08/09/2026] Headline Engine v2: o motor escolhia a conclusão do vídeo em vez da consequência parcialmente revelada — caso real Burke Ramsey/JonBenét

- **Status:** corrigido, validado com chamada REAL à API Anthropic (não
  cliente fake) contra o projeto `jonBenetRamsey01`.
- **Causa raiz:** a v1 do Headline Engine (`scripts/headline_engine.py`)
  perguntava, numa única chamada, "qual headline descreve melhor o
  conteúdo" — mesmo com few-shot contrastivo evitando o fato mais
  saliente do roteiro, isso não impede o modelo de convergir em
  reformulações da MESMA ideia central em vez de mecanismos
  genuinamente diferentes. No projeto Burke Ramsey, dos 6 candidatos
  reais gerados pela v1, 4 giravam em torno do mesmo ângulo ("a CBS
  ocultou/ignorou o teste de DNA de 1999" — só reformulado com sujeitos
  diferentes: envelope, teste, silêncio, irmão) e só 2 exploravam
  ângulos genuinamente distintos (tempo e consequência monetária). O
  vencedor automático daquela rodada real ("WHAT $750 MILLION BOUGHT",
  nota 11/12) preservava a lacuna corretamente — mas o usuário, sem
  saber disso, trocou manualmente por "DNA EXCLUDED BURKE RAMSEY?"
  achando que era melhor: na verdade é pior, porque ao lado do título
  aprovado ("What the 1999 DNA Test Really Proved...") essa frase
  confirma a conclusão do vídeo, não pergunta sobre ela. Investigação
  (Fase 1) confirmou que a perda de diversidade acontecia na GERAÇÃO
  (Chamada A), não no juiz — quando um candidato genuinamente diferente
  existia, o juiz escolhia-o corretamente.
- **Correção:** reestruturação em 3 etapas explícitas, cada uma com sua
  própria chamada de API:
  - **Grupo A (novo) — extração de payload editorial**
    (`extrair_payload_editorial`, prompt
    `scripts/prompts/headline_engine_payload.md`): chamada dedicada,
    antes de qualquer candidato, que separa `conclusao_central` (o que
    o vídeo conclui — nunca deve ser revelado) de `payload` (o elemento
    — número, objeto, consequência, contradição, evidência, tempo,
    decisão institucional ou informação retida — que rende mais
    curiosidade quando revelado em parte). Regra explícita no prompt:
    NUNCA escolher automaticamente a conclusão como payload. Falha
    nunca bloqueia — degrada com `_payload_fallback` (deriva do núcleo
    editorial já existente).
  - **Grupo B (reestruturado) — candidatos por mecanismo**
    (`gerar_candidatos_headline`, prompt
    `headline_engine_candidatos.md`): recebe o `payload` da Grupo A e é
    instruído a cobrir pelo menos 4 mecanismos DIFERENTES entre os 6
    candidatos (10 mecanismos possíveis: tempo, número, objeto,
    informação retida, contradição, reversão, consequência,
    institucional, evidência, mistério aberto) — nunca variações da
    mesma ideia. Cada candidato declara seu `mechanism` (substituiu
    `gap_type` da v1).
  - **Grupo C (ampliado) — rejeição automática + juiz com `answer_leak`**:
    4 filtros semânticos determinísticos novos, em código, antes do
    juiz (`filtrar_candidatos_semanticos`) — pergunta respondível com
    sim/não ("DNA excluded him?"), candidato sem mecanismo
    identificável, headline sustentado só por palavra genérica
    (SHOCKING/BOMBSHELL/TRUTH/SECRET) sem termo concreto, e afirmação
    sem lastro no que a Grupo A extraiu do roteiro. O juiz
    (`julgar_candidatos`) ganhou o 7º critério `answer_leak`: diferente
    de `not_revealing` (que só olha o headline sozinho contra o segredo
    PARTICULAR do candidato), `answer_leak` avalia título+headline
    JUNTOS contra a `conclusao_central` do caso inteiro — é o critério
    que teria pego "DNA EXCLUDED HIM?" ao lado daquele título. É
    critério-PORTA (like `opens_gap`/`anchored_to_case`): zerado
    desqualifica o candidato mesmo com soma total alta, nunca é só
    desconto de nota.
  - **Preservado sem alteração de comportamento:** filtros
    determinísticos de FORMATO (tamanho, repetição do título, encaixe
    tipográfico, termo de risco), limite de 1 regeneração, o motivo de
    falha do juiz nunca disparar regeneração extra (bug pós-Sessão 24),
    ausência de `temperature`/`top_p`/`top_k` em qualquer chamada,
    integração com `scripts/7_thumbnail.py` (só 2 pontos de
    mapeamento: `resultado["gap_type"]` → `resultado["mechanism"]`).
  - **Grupo D novo — auditoria em 3 etapas separadas:**
    `thumbnail/headline_engine.json` agora grava `payload_editorial`
    (Grupo A, uma vez) separado de `rodadas[].candidatos_gerados`/
    `eliminados_formato`/`eliminados_semanticos`/`sobreviventes` (Grupo
    B/C) e `rodadas[].julgamentos` (Grupo C juiz) — permite diagnosticar
    depois se um resultado ruim veio de payload errado, geração pobre
    de mecanismo, ou calibração do juiz, sem inferir pela thumbnail
    final.
- **Achado adicional (via validação Grupo G, API real):** a mesma
  chamada real contra o projeto Burke Ramsey devolveu, uma vez,
  `supporting_facts` como uma lista de 37 CARACTERES ISOLADOS (lixo de
  formato — coincidentemente soletrando um fragmento de tag de outro
  estilo de tool-call, `<parameter name="reveal_level">partial`) em vez
  de frases curtas. Corrigido descartando qualquer item de
  `supporting_facts` com menos de 8 caracteres
  (`_TAMANHO_MINIMO_SUPPORTING_FACT`) — reforça a lição já registrada
  neste arquivo de que teste com cliente fake nunca teria pego isso.
- **Impacto:** o headline vencedor podia, de forma sistemática, ter
  pouca diversidade de ângulo (4 de 6 candidatos repetindo a mesma
  ideia) e não havia proteção nenhuma contra um headline que, somado ao
  título já aprovado, entregasse a conclusão do vídeo — só contra o
  headline revelar seu próprio segredo declarado sozinho. Risco maior
  justamente nos casos onde o usuário edita manualmente o headline
  sugerido, como aconteceu de verdade no projeto Burke Ramsey.
- **Validação real (Grupo G, obrigatória por instrução desta sessão):**
  rodada completa contra a API Anthropic real, projeto
  `jonBenetRamsey01`. `payload` extraído: "$750 million defamation
  lawsuit against CBS" (papel `consequencia`) — CONFIRMADO diferente da
  `conclusao_central`: "Scientific DNA testing excluded Burke Ramsey in
  1999, yet CBS aired a theory implicating him 17 years later...".
  Rodada 1: 6 candidatos, 6 mecanismos distintos (`numero`,
  `institucional`, `informacao_retida`, `consequencia`, `reversao`,
  `misterio_aberto`) — 5 eliminados por formato (mais de 6 palavras) e
  1 por `afirmacao_nao_sustentada`, ninguém sobreviveu pro juiz.
  Rodada 2 (regeneração): 6 candidatos, novamente 6 mecanismos
  distintos — vencedor "CBS Settled. Terms Never Revealed."
  (`informacao_retida`, nota 12/14, `answer_leak: 1`). CONFIRMADO: o
  vencedor não entrega a conclusão central junto do título aprovado —
  menciona um acordo não revelado, não a exclusão por DNA. Testes
  novos: `tests/test_headline_engine.py` reescrito (68 testes: Grupo A
  extração/fallback, Grupo B geração por mecanismo, Grupo C rejeição
  semântica + `answer_leak` como porta, Grupo D regeneração, Grupo E
  auditoria em 3 etapas, Grupo F modo degradado), `tests/test_thumbnail.py`
  ajustado (9 contagens de chamada de API atualizadas pra refletir a
  chamada extra da Grupo A). Suíte completa: 2086 testes verdes.

---

## [Sessão — 08/09/2026] Título canônico: a Etapa 7 gerava um segundo conjunto de títulos concorrente com o escolhido na revisão — caso real Burke Ramsey/JonBenét

- **Status:** corrigido, validado contra o projeto real `jonBenetRamsey01`
  (leitura, sem chamar a API Anthropic de novo — as funções puras
  envolvidas não precisam disso pra' esta verificação).
- **Causa raiz:** existiam DOIS geradores de título independentes.
  `3_gerar_roteiro.py` (Etapa 3) gera 3 sugestões na fase de roteiro; o
  usuário escolhe uma na tela de revisão e ela é gravada em `titulo.txt`
  (`server.py:/aprovar_roteiro` — isso já funcionava certo). Mas
  `scripts/7_thumbnail.py` (Grupo D, `SCHEMA_METADADOS`) pedia à IA MAIS
  3 títulos, do zero, na mesma chamada que gera descrição/tags/briefing
  da thumbnail — só usando `titulo.txt` como âncora temática pro eixo
  editorial (`evidencia_central`/`conflito`/`data_chave`), nunca pros
  títulos em si. Esse segundo conjunto era persistido em
  `thumbnail/metadados.json["title"]`, ainda reconciliado contra o
  headline (podendo ser reescrito), e exibido na tela de conclusão ao
  lado do título real do usuário. No projeto Burke Ramsey: usuário
  escolheu "What the 1999 DNA Test Really Proved About JonBenét's
  Brother" na revisão; a Etapa 7 gerou "The DNA Evidence CBS Never Told
  You About" + 2 outros, focando em CBS/processo judicial em vez do
  eixo real do vídeo (Burke, a exclusão por DNA de 1999, JonBenét). O
  título escolhido nunca aparecia na tela de conclusão.
- **Correção (Opção A do pedido — a Etapa 7 não compete mais com a
  Etapa 3):** `SCHEMA_METADADOS` perdeu o campo `title` (Grupo D não
  gera título nenhum mais). `thumbnail/metadados.json` passa a
  persistir `titulo_escolhido` (lido de `titulo.txt` via
  `_ler_eixo_editorial_base`, nunca gerado) e `titulos_alternativos`
  (as outras 2 opções de `titulos_sugeridos.json`, Etapa 3 — só
  referência, nunca tratadas como candidatas a substituir a escolha).
  `reconciliar_titulos_com_headline` continua existindo mas agora roda
  sobre `[titulo_escolhido]` (não mais sobre os 3 títulos do Grupo D) e
  seu retorno vira SÓ auditoria (`titulo_headline_reconciliacao`) —
  mesmo que a IA "reescreva" o título com score alto, o valor persistido
  nunca muda, porque a escolha do usuário é soberana. `server.py:
  concluido()` para de ler `metadados["title"]` e passa a montar
  `titulos_alternativos` direto de `titulos_sugeridos.json` +
  `titulo.txt`; `templates/concluido.html` marca claramente qual é o
  título escolhido e quais são as opções não usadas. Projeto antigo sem
  `titulo.txt`/`titulos_sugeridos.json` cai em listas vazias, nunca
  quebra; `regenerar_thumbnail_briefing` recupera `titulo_escolhido` de
  um `metadados.json` anterior se `titulo.txt` sumir por algum motivo
  externo (fallback, nunca sobrescreve uma seleção já existente).
- **Impacto:** o título que o usuário efetivamente aprovou (e que serve
  de base pro `subject_name`/eixo editorial da própria thumbnail) nunca
  chegava na tela de conclusão — o usuário via 3 títulos diferentes,
  gerados sem revisão humana, com risco real de deriva editorial (no
  caso real, deslocando o foco de Burke/JonBenét pra CBS/processo).
- **Testes:** `tests/test_thumbnail.py` (schema sem `title`,
  `titulo_escolhido`/`titulos_alternativos` persistidos,
  `_ler_titulos_alternativos` pura, reconciliação nunca sobrescreve o
  título mesmo com "alterado=True", fallback de `regenerar_thumbnail_
  briefing` sem `titulo.txt`), `tests/test_concluido.py` (título antigo
  do Grupo D nunca aparece, alternativas marcadas corretamente, projeto
  sem `titulos_sugeridos.json`/`titulo.txt` não quebra),
  `tests/test_aprovar_roteiro.py` (as 3 opções de título, escolhida
  qualquer uma, chegam intactas na tela de conclusão). Suíte completa:
  2064 testes verdes.

## [Sessão — 08/09/2026] Validação contra a API real do DUAL_PORTRAIT/eixo editorial (sessão anterior) revelou 3 bugs que o teste com cliente fake nunca pegaria — caso real Burke Ramsey/JonBenét

- **Status:** corrigido, validado com chamada REAL à API Anthropic (não
  cliente fake) rodada duas vezes contra o projeto `jonBenetRamsey01`.
- **Contexto:** a entrada anterior deste arquivo (mesma data, logo
  abaixo) implementou `DUAL_PORTRAIT`, `selecionar_protagonista_dual_
  portrait` e o eixo editorial (`evidencia_central`/`conflito`/
  `data_chave`), mas só validou com cliente Anthropic FAKE — que devolve
  exatamente o que o teste pede, nunca revela erro de raciocínio do
  modelo de verdade. Regerar o briefing do projeto real contra a API de
  verdade (servidor reiniciado) expôs 3 bugs que a suíte inteira (fake)
  passava sem denunciar.

### Bug 1 — `evidencia_central`/`conflito`/`data_chave` voltavam vazios na chamada real

- **Causa raiz:** `scripts/prompts/metadados_thumbnail.md` dava ao
  modelo uma saída fácil demais ("vazio se o caso não tiver X claro")
  sem reforçar que, quando o título aprovado/núcleo editorial JÁ
  apontam uma evidência/conflito/data (como neste caso: "the 1999 DNA
  Test"), deixar vazio é quase sempre errado. `_chamar_claude_metadados`
  também não tinha nenhum reparo pra esse caso — só pro
  `background_prompt` trivial. Sem eixo editorial, `montar_prompt_dual_
  portrait` caiu de volta pro detalhe mais chamativo (a tigela, a carta
  de 2008) — exatamente o comportamento que a correção anterior
  pretendia eliminar.
- **Correção:** prompt reforçado com um bloco de "PRIORIDADE
  OBRIGATÓRIA" citando o exemplo Burke/DNA/1999 explicitamente. Reparo
  único extraído pra `_reparar_thumbnail_normalizado`
  (`scripts/7_thumbnail.py`) — generalização do reparo de
  `background_prompt` já existente — que também tenta uma segunda
  chamada quando o eixo editorial volta inteiramente vazio E há âncora
  disponível (`titulo_aprovado`/`nucleo_editorial`). Usado tanto por
  `gerar_metadados` (primeira geração) quanto por `regenerar_thumbnail_
  briefing` (o caminho real por trás do botão "Regenerar dados
  automáticos" — que antes desta correção **não tinha reparo nenhum**).
  Campo novo `thumbnail["eixo_editorial_ausente"]` persistido sempre
  (nunca um vazio silencioso — CLAUDE.md seção 18.4), com banner na tela
  de thumbnail quando `True`.

### Bug 2 — protagonista do `DUAL_PORTRAIT` errado na chamada real (JonBenét dominante, não Burke)

- **Causa raiz:** `selecionar_protagonista_dual_portrait` pedia ao
  modelo pra responder com o rótulo abstrato `"hero"`/`"secondary"`,
  mantendo a correspondência hero/secondary ↔ vítima/outro só na cabeça
  do modelo. Na chamada real, o modelo respondeu `"hero"` com um
  `motivo` que dizia literalmente "hero (papel declarado = vítima,
  referente a Burke)" — uma contradição factual (Burke não é a vítima,
  JonBenét é) que mostra o modelo perdendo a amarração entre os dois
  pares de rótulos no meio do raciocínio.
- **Correção:** o modelo agora responde com o próprio PAPEL (enum
  fechado aos dois papéis reais do par, nunca `"hero"`/`"secondary"`) —
  o código, não o modelo, faz a tradução papel → slot depois. Prompt
  também esclarece que `"vitima"` significa estritamente a vítima do
  crime (nunca uma leitura figurada tipo "vítima de uma suspeita
  injusta"), e passa `subject_name` (quando disponível) como âncora
  factual extra. Validado contra a API real duas vezes seguidas:
  `protagonista: "secondary"` (Burke) com `motivo` corretamente
  explicando "ele é o foco da história... não a vítima do crime
  (JonBenét)".

### Bug 3 — descrição de pessoa contraditória ("young child woman")

- **Causa raiz:** `SCHEMA_ATRIBUTOS_FOTO` só permite `genero`
  `"man"`/`"woman"`/`"unknown"` (sem opção de criança), mas
  `faixa_etaria` é texto livre — a foto de JonBenét (vítima criança)
  voltou com `genero: "woman"` + `faixa_etaria: "young child"`, que
  `descrever_pessoa_para_prompt` concatenava sem checar em "young child
  woman" (criança E mulher adulta ao mesmo tempo).
- **Correção:** `_ajustar_genero_e_prefixo_para_crianca` detecta sinal
  de criança em `faixa_etaria` (`"child"`, `"kid"`, `"toddler"`, etc.) e
  troca o substantivo por `"girl"`/`"boy"`/`"child"` (nunca
  `"man"`/`"woman"`), descartando o prefixo de idade original (o
  substantivo novo já carrega a noção de criança). Validado contra a
  API real: "a girl established as the case's victim" — sem
  contradição.
- **Impacto:** os 3 bugs juntos faziam o briefing final do caso Burke
  Ramsey — um vídeo sobre exclusão de DNA — sair sem nenhuma menção a
  DNA ou 1999, com a pessoa errada em destaque, e com uma descrição de
  pessoa logicamente inválida. Nenhum dos 3 aparecia na suíte de testes
  porque toda ela usava cliente Anthropic fake.
- **Lição pra sessões futuras:** decisões que pedem ao modelo pra
  raciocinar sobre uma correspondência entre dois vocabulários paralelos
  (aqui: hero/secondary vs. papéis reais) são um ponto de falha real,
  não só teórico — sempre que possível, fazer o modelo responder no
  vocabulário mais concreto/verificável (o papel, não o rótulo interno)
  e deixar o código fazer a tradução. E: nenhuma correção que envolve
  julgamento de modelo (não só parsing/schema) está validada até rodar
  contra a API de verdade pelo menos uma vez — suíte 100% verde com
  cliente fake não é evidência de que o comportamento real está certo.

---

## [Sessão — 08/09/2026] Dois sujeitos sem relação de acusação não tinham composição própria + briefing free-associava do roteiro inteiro — caso real Burke Ramsey/JonBenét

- **Status:** corrigido (Grupos novos em `scripts/thumbnail_briefing.py` e
  `scripts/7_thumbnail.py`; `scripts/headline_engine.py` intocado — ver
  "Restrição respeitada" abaixo).
- **Caso de teste que motivou a sessão:** vídeo "Burke Ramsey: What the
  1999 DNA Test Really Proved About JonBenét's Brother" — JonBenét
  enviada como sujeito `hero`/papel `vitima`, Burke enviado como
  `secondary`/papel `outro` (nunca `suspeito` — ele foi excluído por DNA
  em 1999, reclassificá-lo pra habilitar um template seria erro
  editorial grave). Eixo editorial real do vídeo: evidência central =
  teste de DNA de 1999; conflito = a exclusão de 1999 revisitada por uma
  teoria televisiva de 2016; data-chave = 1999.

### Problema 1 — sem composição para `vítima + outro`

- **Causa raiz:** `templates_elegiveis` (`scripts/thumbnail_briefing.py`)
  não tinha nenhum template pensado pra dois sujeitos SEM relação de
  acusação (`ARROW_TRIO`/`DUOTONE_DOSSIER`), sem autoridade envolvida
  (`INVESTIGATOR_UPDATE`) e sem o mesmo papel (`DUOTONE_DOSSIER` com
  grid). Essa combinação caía na regra 6 antiga, que devolvia as mesmas
  opções de retrato SOLO (`PROFILE_ISOLATION`/`DUOTONE_DOSSIER`) — a
  segunda foto enviada (Burke) era descartada por completo, mesmo
  disponível.
- **Correção:** novo template `DUAL_PORTRAIT` (`montar_prompt_
  dual_portrait`) — dois retratos de peso visual equilibrado, sem seta,
  sem cobertura/censura, sem pressupor culpa entre os dois. Regra 6 de
  `templates_elegiveis` passou a devolver `("DUAL_PORTRAIT",)` (único
  elegível, sem ambiguidade) pra qualquer combinação de dois sujeitos que
  não caia nas regras 3-5 (autoridade+alvo, acusação, mesmo papel) — a
  regra do `ARROW_TRIO` **não foi enfraquecida**: `_relacao_acusatoria`
  continua exatamente igual, `DUAL_PORTRAIT` só se torna elegível quando
  nenhuma relação mais específica se aplica.
- **Validação 11 do pedido (achado real durante a implementação):** o
  título do vídeo é sobre Burke, mas ele foi enviado no slot
  `secondary` — sem tratamento, ele ficaria na posição visual menor só
  por causa da ORDEM de upload, não do que a história realmente conta.
  Nova função `selecionar_protagonista_dual_portrait` (chamada dedicada,
  tool forçada, enum `["hero", "secondary"]`) decide qual sujeito ocupa a
  posição DOMINANTE olhando pro título aprovado + headline — nunca
  reclassifica papel (`hero_papel`/`secondary_papel` no `caso` continuam
  intocados, só a posição/tamanho na composição muda). Fallback
  determinístico `"hero"` preserva o comportamento de sempre quando não
  há cliente/contexto suficiente pra decidir.

### Problema 2 — briefing puxava o detalhe mais chamativo do roteiro, não o eixo editorial

- **Causa raiz confirmada por leitura de código:** `scripts/prompts/
  metadados_thumbnail.md` (Grupo D, `scripts/7_thumbnail.py:
  gerar_metadados`) pedia `background_prompt`/`secondary`/`subject_name`
  analisando o ROTEIRO INTEIRO, sem nenhuma âncora no título aprovado ou
  no núcleo editorial (que nem era passado nessa chamada) — o modelo era
  livre pra escolher qualquer detalhe visualmente interessante do
  roteiro (a tigela ["the bowl nobody explains"] ou a carta de exoneração
  de 2008 são exatamente esse tipo de detalhe: chamativos, mas
  tangenciais à pergunta que o título promete responder).
- **Correção:**
  - `SCHEMA_METADADOS.thumbnail` (`scripts/7_thumbnail.py`) ganhou 3
    campos novos, na ordem em que devem ser decididos (antes de
    `background_prompt`): `evidencia_central` (`{tipo: dna|documento|
    data|objeto|outro, descricao}`), `conflito`, `data_chave`.
    Normalizados por `_normalizar_evidencia_central`/
    `_normalizar_thumbnail_metadados` — `tipo` fora do enum cai em
    `"outro"`, `descricao` vazia faz o campo inteiro virar `None` (regra
    do pedido: "não inventar evidência").
  - `scripts/prompts/metadados_thumbnail.md` ganhou uma seção "REGRA
    FUNDAMENTAL": um detalhe do roteiro só entra na thumbnail se
    reforçar a promessa do título, a evidência central, ou o conflito
    editorial — nunca só por ser chamativo.
  - `_chamar_claude_metadados`/`gerar_metadados`/
    `regenerar_thumbnail_briefing` passaram a receber e injetar
    `titulo_aprovado` (titulo.txt) + `nucleo_editorial` (job_metadata.json,
    Etapa 3) ANTES do roteiro na mensagem — nova função
    `_ler_eixo_editorial_base`. Projeto antigo sem esses dois arquivos
    nunca quebra e nunca injeta um bloco vazio (validação 9 do pedido).
  - `evidencia_central` passou a virar um ELEMENTO VISUAL concreto em
    `EVIDENCE_SCENE` e `DUAL_PORTRAIT` (`_descricao_evidencia_central`,
    `scripts/thumbnail_briefing.py`) — nunca inventado quando ausente.
- **Restrição respeitada (idêntica à sessão "coordenação título↔headline"
  de 07/09/2026 — ver entrada abaixo):** `scripts/headline_engine.py`
  permanece **100% intocado** (zero linhas mudadas, rubrica/juiz
  idênticos). `nucleo_editorial` já chegava lá via `_ler_contexto`
  (infra anterior, sem mudança). `evidencia_central`/`conflito`/
  `data_chave` chegam ao Headline Engine enriquecendo o TEXTO de entrada
  que `_aplicar_headline_engine` repassa como `roteiro_texto` — nova
  função `_montar_roteiro_com_eixo_editorial` prepend um cabeçalho
  estruturado "## EIXO EDITORIAL DESTE VIDEO" só para essa chamada.
  `roteiro_hash` (usado por `metadados_desatualizados`) continua vindo
  do `roteiro_texto` ORIGINAL, sem o cabeçalho — testado explicitamente
  (`test_montar_roteiro_com_eixo_editorial_nunca_afeta_roteiro_hash`).
- **Validação ponta a ponta (demonstração, não fixture real da API):**
  com um cliente Anthropic fake devolvendo `evidencia_central` = "a 1999
  DNA lab report and test swab", `conflito` = "a 1999 DNA exclusion
  revisited by a 2016 TV theory", `data_chave` = "1999" e headline
  "CLEARED BY DNA, THEN ACCUSED", o briefing final selecionou
  `DUAL_PORTRAIT`, colocou Burke (secondary/`outro`) na posição
  dominante (decisão do protagonista pelo eixo editorial, não pelo
  slot), incluiu o elemento de evidência do DNA de 1999, e nunca conteve
  "bowl"/"2008"/"exoneration" — porque esses termos nunca fazem parte do
  eixo editorial injetado, e o código nunca deriva elemento nenhum
  independentemente do que o Grupo D decidiu. `outro` nunca foi
  reclassificado — descrição final usa "person connected to the case",
  nunca "suspect"/"convicted".
- **Testes novos:** ~35 testes em `tests/test_thumbnail_briefing.py`
  (elegibilidade/prioridade do `DUAL_PORTRAIT`, `selecionar_
  protagonista_dual_portrait`, elemento de evidência em
  `EVIDENCE_SCENE`/`DUAL_PORTRAIT`, caso Burke ponta a ponta,
  retrocompatibilidade sem eixo editorial) e ~15 em
  `tests/test_thumbnail.py` (normalização dos 3 campos novos, wiring de
  `_ler_eixo_editorial_base`, cabeçalho pro Headline Engine, contrato do
  schema/prompt). Suite completa: 2038 passed.
- **Impacto:** thumbnail de casos com dois sujeitos sem relação de
  acusação clara (parente/testemunha do caso, pessoa só citada) perdia a
  segunda foto por completo; briefing podia ancorar a composição num
  detalhe irrelevante ao invés do fato que sustenta a promessa do
  título, arriscando uma thumbnail enganosa ou sem relação clara com o
  vídeo.

---

## [Sessão de melhoria — 07/09/2026] Título e headline da thumbnail podiam colidir semanticamente — CONFIRMADO E CORRIGIDO

- **Status:** corrigido (Grupos A/C/F da sessão; Grupos D/E adaptados —
  ver "Desvios do pedido original" abaixo).
- **Causa raiz real:** existem DOIS conjuntos de "título" no pipeline,
  não um só. (1) `titulo.txt` — escolhido pelo humano na revisão do
  roteiro (Etapa 3/5.5), e é o único que `scripts/headline_engine.py`
  já conhece (`_ler_contexto` lê `titulo.txt` e passa como
  `titulo_aprovado` pra `gerar_candidatos_headline`/`julgar_candidatos`
  — essa coordenação já existia ANTES desta sessão). (2) os "3 títulos
  sugeridos" que aparecem ao lado da thumbnail na tela de conclusão
  (`thumbnail/metadados.json["title"]`) — gerados por
  `_chamar_claude_metadados` (Etapa 7, Grupo D), na MESMA chamada que
  desenha um headline de RASCUNHO que é descartado e substituído pelo
  do Headline Engine logo em seguida. Nada nunca comparava esses 3
  títulos contra o headline FINAL — achado real reportado: título
  "Nancy Guthrie: What the Wrist Tattoo Actually Reveals" ao lado do
  headline "THE MARK ON HIS WRIST" (o título entregava o próprio
  elemento visual — a marca/tatuagem no pulso — que o headline usava
  como lacuna).
- **Correção:**
  - **Grupo A** (`scripts/prompts/perfis/{truecrime,historia,
    atualidades_narrativas}/sistema.md`): parágrafo novo na seção
    "Títulos sugeridos" de cada perfil reforçando que o título serve
    pra CONTEXTO + BUSCA e nunca deve transformar em assunto central
    um único detalhe concreto/visualizável do caso — esse é o material
    bruto de onde a thumbnail (gerada bem depois, na Etapa 7) tira sua
    própria lacuna visual.
  - **Grupo C/F** (nova função `reconciliar_titulos_com_headline` em
    `scripts/7_thumbnail.py` + prompt novo
    `scripts/prompts/titulos_headline_reconciliacao.md`): roda logo
    depois de `_aplicar_headline_engine` decidir o headline definitivo,
    tanto em `gerar_metadados` (primeira geração) quanto em
    `regenerar_thumbnail_briefing` (botão "Regenerar dados
    automáticos" — que preserva os títulos antigos mas troca o
    headline, o outro ponto real de desalinhamento). Reavalia os 3
    títulos contra o headline final e reescreve SÓ o(s) que
    repetem/revelam o headline, preservando os que já funcionam
    palavra por palavra. Nunca bloqueia o pipeline (sem título, sem
    headline ou sem cliente disponível preserva os títulos como
    vieram; falha de API é engolida e também preserva). Persiste
    `thumbnail/metadados.json["titulo_headline_reconciliacao"]` com
    títulos originais, títulos finais, nota de complementaridade
    (0-2) por título e motivo — auditoria completa, no arquivo que a
    Etapa 7 já possui (nunca em `headline_engine.json`, que pertence
    só ao Headline Engine).
- **Desvios do pedido original (documentados, não esquecidos):**
  - **Restrição "não alterar `scripts/headline_engine.py`" foi
    respeitada literalmente** — zero linhas mudadas nesse arquivo. Por
    isso o "novo critério do juiz" (Grupo D do pedido, pontuação 0-2
    de complementaridade dentro da rubrica do Headline Engine) NÃO foi
    implementado como um 7º critério formal em
    `CRITERIOS_JULGAMENTO`/`SCHEMA_JULGAMENTO` (exigiria editar esse
    arquivo). Em vez disso, a complementaridade é avaliada por um juiz
    SEPARADO (a própria `reconciliar_titulos_com_headline`), que
    pontua o PAR título-final/headline-final depois que o Headline
    Engine já decidiu — equivalente em espírito, implementado
    inteiramente fora do arquivo restrito.
  - **`headline_desatualizado` (Grupo E do pedido) não foi implementado
    como flag manual + botão.** Investigação mostrou que não existe
    hoje nenhuma tela que permita ao usuário editar/trocar
    `titulo.txt` OU os 3 títulos da Etapa 7 depois que já foram
    gerados (só o texto do briefing é editável, CLAUDE.md seção 5.85) —
    não havia gatilho real pra uma flag de "desatualizado" além do já
    existente `metadados_desatualizados` (roteiro editado). Em vez de
    construir uma feature de edição de título só pra ter o que marcar
    como desatualizado (fora do escopo do bug reportado — CLAUDE.md
    seção 12, "Extensão de escopo"), a reconciliação roda
    AUTOMATICAMENTE toda vez que o headline é (re)gerado — mais forte
    que uma flag passiva, porque nunca deixa um título sobreviver
    desalinhado esperando o usuário notar e clicar em algo.
- **Impacto:** título e headline podiam entregar o mesmo elemento
  visual/factual da thumbnail, esvaziando a curiosidade antes do
  clique — exatamente o efeito que o Headline Engine (Sessão anterior)
  foi desenhado pra evitar, só que pela porta dos fundos (os 3 títulos
  da Etapa 7, nunca cobertos pela proteção existente).
- **Arquivos alterados:** `scripts/7_thumbnail.py`,
  `scripts/prompts/titulos_headline_reconciliacao.md` (novo),
  `scripts/prompts/perfis/truecrime/sistema.md`,
  `scripts/prompts/perfis/historia/sistema.md`,
  `scripts/prompts/perfis/atualidades_narrativas/sistema.md`,
  `tests/test_thumbnail.py`, `tests/test_gerar_roteiro.py` (hashes de
  guarda de `sistema.md` recalculados conscientemente).
- **Arquivos intencionalmente NÃO alterados:** `scripts/headline_engine.py`
  (restrição explícita), `scripts/3_gerar_roteiro.py` (a geração dos 3
  títulos do roteiro em si não mudou, só o prompt que a orienta),
  `server.py` (nenhuma rota nova — a reconciliação roda dentro das
  funções que as rotas existentes já chamavam).
- **Testes:** `.\venv\Scripts\python.exe -m pytest -x --tb=short` — 1999
  passed (suíte completa, incluindo os testes novos de
  `reconciliar_titulos_com_headline` e do wiring em
  `gerar_metadados`/`regenerar_thumbnail_briefing`).

---

## [Sessão de melhoria — 07/09/2026] Atalho da área de trabalho iniciava o servidor mas nunca abria o navegador — CONFIRMADO E CORRIGIDO

- **Status:** corrigido.
- **Causa:** investigação (CLAUDE.md seção 18.3.1) descartou hipóteses
  óbvias antes de mexer em código — `scripts/criar_atalho.py` sempre
  criou o atalho apontando corretamente pra `iniciar.bat` com o
  `WorkingDirectory` certo, e não havia nada de errado na resolução do
  caminho. A causa real é mais simples e mais chata: **a feature nunca
  existiu**. Nenhum lugar do fluxo (nem `iniciar.bat`, nem `server.py`)
  jamais chamava um navegador — não era regressão nem bug de
  configuração, era funcionalidade que faltava desde sempre.
- **Correção:** `scripts/verificar_servidor.py` (script novo,
  autocontido, só biblioteca padrão + `dotenv` opcional) entra em dois
  pontos de `iniciar.bat`:
  - Antes de subir o servidor (`checar-porta`): se a porta configurada
    já está ocupada pelo próprio Broll Foundry (confirmado batendo na
    rota `/verificar_atualizacao` já existente e conferindo a
    assinatura do JSON — nunca só "algo respondeu"), não sobe uma
    segunda instância, só abre o navegador na existente. Se está
    ocupada por outro processo qualquer, avisa o conflito com clareza
    e para, sem matar nem substituir nada. Se está livre, segue o
    fluxo normal.
  - Depois de disparar `python server.py` (`aguardar-e-abrir`, rodado
    com `start "" /B` — em segundo plano, mas preso à MESMA sessão de
    console, nunca um processo desacoplado do terminal): faz polling
    real (nunca espera fixa) até o Flask responder de verdade, com
    timeout configurável, e só então abre `http://localhost:{PORTA}/`.
  - Duas checagens de robustez extras, ambas puramente defensivas:
    detecta `server.py` ausente (pasta movida/renomeada — mas ver
    limitação abaixo) logo após o `cd /d`, e detecta
    `venv\Scripts\python.exe` ausente (venv corrompida) logo após o
    bloco de criação/ativação da venv — resolve o item correspondente
    de `MELHORIAS_PENDENTES.md` (venv ausente/quebrada).
  - `python server.py` continua a última linha do fluxo, chamado
    direto sem `start`/`call` — fechar o terminal continua encerrando
    o servidor, comportamento inalterado.
- **Limitação documentada, não um bug:** se o `.lnk` do atalho em si
  estiver com o alvo morto (pasta do projeto inteira movida/renomeada
  DEPOIS de o atalho ter sido criado), o Windows Explorer recusa abrir
  o atalho e mostra o próprio diálogo genérico do sistema — nenhum
  código deste projeto chega a rodar nesse caso específico, não tem
  como interceptar de dentro de `iniciar.bat`.
- **Impacto:** usuário clicava no atalho, via o terminal abrir e o
  servidor subir nos logs, mas tinha que abrir o navegador e digitar
  `localhost:5000` manualmente toda vez — funcionava, só não era o
  fluxo "um clique" que o atalho prometia.
- **Testes:** `tests/test_verificar_servidor.py` (novo, 15 casos —
  socket/urllib/webbrowser sempre mockados) + 7 casos novos em
  `tests/test_iniciar_bat.py` (estáticos sobre o texto do arquivo,
  nunca invocam o `.bat` de verdade — ver aviso no topo daquele
  arquivo). Também validado manualmente fora da suíte (nunca dentro de
  teste automatizado, mesmo espírito da seção 8/18.3): `checar-porta`
  contra porta livre real devolve exit code 0, e contra um servidor
  HTTP de mentira respondendo a assinatura exata de
  `/verificar_atualizacao` devolve exit code 2 corretamente. Suíte
  completa rodada de verdade via
  `venv\Scripts\python.exe -m pytest --tb=short`: **1987 passed, 0
  failed** (após corrigir, na mesma sessão, uma falha não relacionada a
  esta feature — ver entrada logo abaixo, sobre a edição acidental em
  `truecrime/sistema.md`).

---

## [Sessão de melhoria — 07/09/2026] Hash-pin de sistema.md pegou uma edição acidental de editor em arquivo crítico do perfil truecrime — CONFIRMADO E CORRIGIDO

Achado durante a sessão do atalho da área de trabalho (entrada acima):
`test_sistema_md_nao_foi_alterado_por_esta_sessao[truecrime]` falhou
rodando a suíte completa. Investigação séria antes de tocar no hash
(pedida explicitamente pelo usuário, porque este arquivo governa a
geração de todos os roteiros do perfil truecrime):

- **Descartado de cara:** não foi esta sessão nem a suíte de testes.
  `scripts/prompts/perfis/truecrime/sistema.md` tinha mtime de
  07/09/2026 20:38:25 — **antes** do primeiro arquivo escrito nesta
  sessão (21:02:53) e depois da sessão anterior do dia (fontes
  separadas, terminou ~20:30). Nenhum teste da suíte escreve nesse
  caminho real (todos usam `tmp_path`). `atualidades_narrativas/
  sistema.md` e `historia/sistema.md` — cujos hashes bateram certinho —
  tinham mtime de 04/09/2026, mesma data da Sessão 19/23 que fixou os
  hashes.
- **Causa real, confirmada pelo usuário via Local History do PyCharm:**
  edição ACIDENTAL de editor, não intencional. Linha 26 virou
  `[palavra.]()` (sintaxe de link Markdown com destino vazio) em vez de
  `palavra.` — atalho de editor disparado sem querer com o texto
  selecionado, quase certamente durante uma sessão anterior do mesmo
  dia enquanto o autor olhava esse arquivo por outro motivo.
- **Correção:** revertida a linha 26 para `palavra.`. Conferido com
  `grep` que nenhuma outra ocorrência de `[texto]()` com destino vazio
  existe em nenhum dos 3 `sistema.md` (truecrime/atualidades_
  narrativas/historia) — a edição acidental foi um caso isolado. Hash
  recalculado sobre o conteúdo corrigido bateu **exatamente** com o
  valor já pinado em `tests/test_gerar_roteiro.py`
  (`3c912f1c8fe462808eb2f9deb5c8bbcd04233f453701c4650a4bf8d5788cedb5`)
  — confirmação independente de que o link vazio era a ÚNICA diferença
  em relação ao estado correto da Sessão 23; **o hash-pin em si não
  precisou de nenhuma alteração**, só o arquivo de prompt.
- **Avaliação do mecanismo de teste:** funcionou exatamente como
  pretendido (CLAUDE.md seção 8/18 — nunca aceitar sucesso sem
  verificar de verdade). Um hash-pin sobre um arquivo de prompt crítico
  pegou uma mutação de 1 caractere invisível na leitura casual
  (`[palavra.]()` renderiza como texto quase idêntico a `palavra.` em
  qualquer visualização que não seja o Markdown bruto) antes que ela
  chegasse a afetar geração de roteiro real. Nenhuma mudança no
  mecanismo de teste é necessária.
- **Impacto:** nenhum roteiro chegou a ser gerado com o link vazio no
  prompt (o teste pegou antes de qualquer uso em produção) — mas o
  arquivo ficou nesse estado, sem detecção, entre ~20:38 e o momento em
  que a suíte completa rodou nesta sessão.
- **Nota de processo:** a edição acidental não foi registrada por
  nenhuma sessão como uma mudança deliberada (CLAUDE.md seção 9 pede
  registro de toda sessão que muda comportamento do produto) — porque
  não era uma sessão gerenciada pelo Claude Code editando o arquivo por
  instrução, e sim um editor externo (PyCharm) usado em paralelo. Vale
  como lembrete de que edições manuais em arquivos de prompt fora do
  fluxo de sessão também podem introduzir regressões silenciosas — o
  hash-pin é exatamente a rede de segurança pra isso, e funcionou.

---

## [Sessão de correção — 07/09/2026] Modo separado de fontes baixava a mesma URL duas vezes quando ela aparecia nas duas listas (transcrição e visual) — CONFIRMADO E CORRIGIDO

Achado real (não hipotético): o projeto já concluído `nancyGuthrieProject03`
tinha `fonte01` (tipo_uso `transcricao`) e `fonte03` (tipo_uso `visual`)
apontando para a MESMA URL
(`https://www.youtube.com/watch?v=xW5A4ffM34k`) — baixada duas vezes,
gastando tempo e espaço em disco à toa numa fonte de 38+ minutos.

- **Status:** corrigido.
- **Causa:** no modo separado (CLAUDE.md seção 5.7.2), `server.py`
  simplesmente concatenava `links = links_transcricao + links_visual` e
  `tipo_uso_por_link = ["transcricao"]*n + ["visual"]*m` sem nenhuma
  checagem de URL repetida entre as duas listas. Como o identificador de
  fonte (`fonteNN`) é 100% posicional (`scripts/1_baixar_videos.py`
  numera pela posição em `entrada/links.txt`), a mesma URL colada nas
  duas listas virava duas posições distintas → dois downloads.
- **Correção:** nova função pura `_mesclar_fontes_separadas` (`server.py`)
  deduplica as duas listas ANTES de `_criar_pasta_projeto` gravar
  `entrada/links.txt` — nova função `chave_dedup_youtube`
  (`scripts/validators.py`) extrai o ID do vídeo do YouTube (11
  caracteres) reconhecendo `youtu.be/<id>`, `youtube.com/watch?v=<id>`,
  `/shorts/<id>`, `/embed/<id>`, `/live/<id>`, ignorando `www.`/`m.` e
  parâmetros extras (`&t=`, `&list=`, `&index=`); URL não reconhecida cai
  para a URL crua em minúsculas (nunca funde por engano — prefere baixar
  duas vezes a fundir errado). Uma URL presente nas duas listas vira UMA
  única entrada com `tipo_uso="ambos"` — valor que
  `scripts/2_transcrever.py` e `scripts/5_gerar_clipes.py` **já tratavam**
  como "processar para os dois propósitos" antes desta sessão, então
  nenhum dos dois scripts precisou de qualquer mudança. Marca d'água da
  entrada mesclada: mantém a da primeira aparição se já for diferente de
  "nenhuma", senão usa a da segunda (nunca perde uma marca real por causa
  da ordem de mescla).
- **Decisão sobre identificador de fonte (avaliada explicitamente antes
  de implementar — risco real de corromper projeto existente se
  decidida errado):** a numeração `fonteNN` continua 100% posicional e
  `scripts/1_baixar_videos.py`/`2_transcrever.py`/`5_gerar_clipes.py`/
  `clipes/indice.json` não mudaram em nada. O dedup roda só em
  `server.py`, na coleta do formulário, ANTES de `entrada/links.txt`
  existir — ou seja, a lista de entrada já nasce sem duplicata para
  projetos novos. Projetos já criados (como `nancyGuthrieProject03`,
  com a duplicata real em disco) nunca são tocados: nada relê ou
  reescreve `entrada/links.txt`/`manifest_fontes.json` de um projeto já
  existente, então continuam funcionando exatamente como antes (sem
  reprocessamento, sem risco de um clipe passar a apontar pra fonte
  errada).
- **Impacto:** usuário que cola a mesma URL nas duas listas do modo
  separado agora baixa o vídeo UMA vez só (fonte aparece uma vez na
  tela de Download, rotulada "Transcrição + clipes" — rótulo
  `TIPO_USO_ROTULOS["ambos"]` já existia, sem mudança de template).
  Projetos criados antes desta correção com duplicata real em disco
  continuam abrindo e funcionando normalmente.
- **Testes:** `tests/test_validators.py` (8 testes novos de
  `chave_dedup_youtube` — watch/youtu.be/shorts equivalentes, www/m.
  ignorados, parâmetros extras ignorados, IDs diferentes não colidem,
  URL não reconhecida cai pra string crua, entrada vazia/malformada
  nunca lança exceção) e `tests/test_fontes_separadas.py` (6 testes de
  `_mesclar_fontes_separadas` + 1 teste de integração via `POST /novo`
  com URL repetida nas duas listas + 1 teste de não-regressão que
  reproduz em miniatura o estado real de `nancyGuthrieProject03` — fonte
  duplicada em disco continua exibindo as mesmas 3 fontes,
  `clipes/indice.json` continua apontando pros arquivos corretos).
  `.\venv\Scripts\python.exe -m pytest -x --tb=short`: 1964 passed.

---

## [Sessão de correção — 07/09/2026] Seletor de template da thumbnail sugeria/rotulava opção errada depois de mudar o papel de um sujeito — CONFIRMADO E CORRIGIDO

Bug reportado em teste real: com sujeito principal = investigador e
sujeito secundário = vítima (persistência já confirmada correta — texto
exibido = valor do dropdown = valor persistido), o seletor de template
mostrava `EVIDENCE_SCENE` como "sugerido pelo sistema" (incorreto, já
havia 2 fotos enviadas) e `INVESTIGATOR_UPDATE` como "indisponível"
(incorreto, é o único template realmente elegível para essa combinação).
`ARROW_TRIO`/`DUOTONE_DOSSIER` apareciam como "elegível" sem estar.

**Hipótese investigada:** que `templates_elegiveis()` (`scripts/
thumbnail_briefing.py`) decidia a elegibilidade pela POSIÇÃO
hero/secondary em vez da COMBINAÇÃO de papéis (ex: tratando
"investigador + vítima" diferente de "vítima + investigador").

**Hipótese REFUTADA por leitura de código e teste.** `templates_elegiveis`
já monta um `set({hero_papel, secondary_papel})` antes de decidir — é
comprovadamente independente de ordem, e já havia testes cobrindo
exatamente vítima+investigador nas duas ordens
(`test_templates_elegiveis_vitima_e_investigador_trava_em_
investigator_update`). Um teste novo mais amplo
(`test_templates_elegiveis_independente_da_ordem_dos_slots`) varre 11
pares hero/secondary trocados e confirma resultado idêntico nos dois
sentidos.

- **Status:** corrigido — duas causas raiz reais e independentes,
  nenhuma delas relacionada à posição do slot.
- **Causa raiz 1 (a principal — bate com o cenário relatado):**
  `server.py:tela_thumbnail` (GET) calculava `template_sugerido` como
  `textos.get("briefing_template") or primeiro_elegivel` — ou seja, se
  já existisse um `briefing_template` persistido em
  `thumbnail/metadados.json` de uma geração ANTERIOR (o Grupo D/C
  automático roda antes de qualquer sujeito ser enviado e grava
  `"EVIDENCE_SCENE"`, único elegível nesse momento), esse valor STALE
  era usado como sugestão pra sempre, mesmo depois do usuário enviar 2
  fotos que tornavam `EVIDENCE_SCENE` inelegível (regra de segurança já
  existente — nunca elegível com sujeito presente) e outro template
  (`INVESTIGATOR_UPDATE`, no caso relatado) o único realmente elegível.
  O HTML do `<option>` combinava `selected` (por ser o "sugerido" stale)
  **e** `disabled` (por não estar em `templates_elegiveis_atual`) no
  mesmo elemento — o dropdown mostrava a opção errada como pré-marcada.
- **Causa raiz 2 (agrava o sintoma quando o papel muda via AJAX, sem
  reload de página):** `static/thumbnail.js:atualizarElegibilidadeTemplate`
  — chamada depois de `server.py:thumbnail_atualizar_papel_sujeito`
  persistir a troca de papel de um sujeito que já tinha foto — só
  atualizava `.disabled` e `.value` de cada `<option>`, nunca o
  **texto** visível (`"(sugerido pelo sistema)"` / `"— indisponível"`),
  que tinha sido montado uma única vez pelo Jinja no carregamento da
  página. Resultado: depois de trocar o papel pelo dropdown (sem
  recarregar a página — decisão deliberada de sessão anterior, pra não
  perder edição em andamento no textarea do briefing), o estado lógico
  (`disabled`/`value`) ficava correto mas o TEXTO lido pelo usuário
  continuava congelado na combinação de papéis anterior — exatamente o
  padrão relatado (`ARROW_TRIO`/`DUOTONE_DOSSIER` com texto de
  "elegível" e `INVESTIGATOR_UPDATE` com texto de "indisponível", ambos
  presos num estado de papéis anterior).
- **Correção 1:** `server.py` (rota GET e rota
  `atualizar_papel_sujeito`) agora valida `briefing_template` salvo
  contra `templates_elegiveis_atual` antes de usá-lo como sugestão; se
  não for mais elegível, cai em `thumbnail_briefing.template_preferido()`
  (nova função — desempate EXPLÍCITO e documentado via
  `ORDEM_PREFERENCIA_TEMPLATE`, nunca a ordem implícita da tupla que
  `templates_elegiveis` monta internamente).
- **Correção 2:** `static/thumbnail.js:atualizarElegibilidadeTemplate`
  agora reconstrói o `textContent`/`title` de CADA opção a partir dos
  mesmos dados que o Jinja usa no load inicial
  (`cfg.templatesNomes`/`templatesDescricoes`/`templatesMotivoCurto`),
  nunca duplicando a REGRA de elegibilidade (que continua vindo pronta
  do servidor).
- **Melhoria de UX (mesmo pedido):** nomes dos templates trocados por
  rótulos amigáveis (`NOME_EXIBICAO_TEMPLATE` — ex: "Dossiê duotone
  (retrato + grid)" → "Retrato dossiê") + descrições novas
  (`DESCRICAO_AMIGAVEL_TEMPLATE`) escritas a partir da composição REAL
  de cada `montar_prompt_*`, exibidas no `title` de cada opção, na linha
  de status abaixo do seletor e num `<details>` "Ver o que cada template
  mostra". Motivo de indisponibilidade agora aparece inline na própria
  opção (`MOTIVO_CURTO_INDISPONIVEL`, ex: "— indisponível: requer
  investigador + suspeito/condenado/vitima"), derivado das mesmas
  constantes de categoria (`_CATEGORIA_ALVO`/`_CATEGORIA_ACUSADO`/
  `_CATEGORIA_AUTORIDADE`) que `templates_elegiveis` usa de verdade —
  não é mais texto solto que pode divergir da regra sem ninguém notar.
- **Arquivos alterados:** `scripts/thumbnail_briefing.py` (nova
  `ORDEM_PREFERENCIA_TEMPLATE`/`template_preferido`, nomes/descrições
  novas, `REQUISITO_TEMPLATE`/`MOTIVO_CURTO_INDISPONIVEL` derivados das
  constantes de categoria), `server.py` (valida `briefing_template`
  stale nas duas rotas, usa `template_preferido`, passa
  `templates_descricoes`/`templates_motivo_curto` pro template),
  `templates/thumbnail.html` (option renderiza motivo curto + `title`
  com descrição + bloco `<details>`, `cfg` expõe os dicts novos pro JS),
  `static/thumbnail.js` (reconstrói texto/title das opções, não só
  disabled/value).
- **Testes:** `tests/test_thumbnail_briefing.py` (Casos 1-8 do pedido —
  ordem invertida hero/secondary, vítima+investigador, vítima+
  suspeito/condenado, mesmo papel, sem relação clara, 0/1/2 sujeitos e
  `EVIDENCE_SCENE`, `suspeito`+`investigador` sem template dedicado —
  regra escolhida: trava em `INVESTIGATOR_UPDATE` igual a vítima+
  investigador, nunca cai em `EVIDENCE_SCENE`; determinismo de
  `template_preferido`; consistência texto↔categoria) e
  `tests/test_thumbnail_rotas.py` (reproduz o cenário exato do bug
  report via rota GET; determinismo do `template_sugerido` retornado
  pela rota de troca de papel). **1947 testes, todos verdes** —
  `.\venv\Scripts\python.exe -m pytest -x --tb=short`.
- **Impacto:** thumbnail podia sair sem nenhum rosto em destaque mesmo
  com fotos de sujeitos disponíveis, se o usuário confiasse na sugestão
  do sistema sem revisar manualmente — mesma classe de risco já descrita
  na regra de segurança original (CLAUDE.md seção 5.85).

---

## [Sessão de correção — 06/09/2026, servidor reiniciado] Papel do sujeito não persistia ao trocar o dropdown — CONFIRMADO E CORRIGIDO

Retomada da sessão anterior (entrada abaixo, "2 e 3... NÃO REPRODUZIDO NO
CÓDIGO ATUAL"). O usuário reproduziu o bug com o servidor **já
reiniciado**, invalidando a hipótese de processo desatualizado. A pista
adicional: na mesma linha de um sujeito, o texto ao lado da miniatura
("papel: condenado") e o valor selecionado no dropdown ("Investigador")
mostravam valores DIFERENTES ao mesmo tempo — sintoma de dois estados
divergentes (um persistido, um só no DOM), não de lógica de elegibilidade
errada. A investigação anterior apontava `thumbnail_briefing.py`; essa
suspeita foi descartada aqui — o arquivo nunca foi tocado.

- **Status:** corrigido.
- **Causa raiz confirmada:** `static/thumbnail.js` só lia o valor do
  dropdown `papel-<slot>` dentro de `uploadSujeito` — ou seja, o valor
  só era enviado ao servidor (e persistido em
  `thumbnail/sujeitos/sujeitos.json` via
  `thumbnail_etapa7.atualizar_sujeito_slot`) no momento de um upload de
  arquivo novo. O `<select id="papel-{{ slot }}">` em
  `templates/thumbnail.html` **não tinha nenhum listener de `change`** —
  trocar a opção alterava só o DOM do navegador, sem nenhuma requisição
  ao servidor. `server.py:tela_thumbnail` (GET) sempre lê `hero_papel`/
  `secondary_papel` direto de `sujeitos.json` em disco (linhas
  4990-4992) tanto pro texto ao lado da miniatura quanto pro `selected`
  do `<option>` no load da página — então, ATÉ o próximo reload, o texto
  refletia o papel persistido (o real) e o dropdown mostrava a escolha
  não salva do usuário (o estado do DOM) — exatamente a divergência
  relatada. `templates_elegiveis()` (regra de elegibilidade,
  `scripts/thumbnail_briefing.py`) estava correta o tempo todo — recebia
  o papel ANTIGO porque nenhum dado novo jamais chegava até ela.
- **Hipótese descartada:** que `thumbnail_briefing.py` continha a
  lógica de elegibilidade ou tradução errada — não continha; o problema
  era 100% de fluxo de persistência/sincronização no par
  `thumbnail.html`/`thumbnail.js`/`server.py`, nunca na regra em si.
- **Papéis aceitos vs. oferecidos no dropdown:** verificado que
  `thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS` (6 itens: `vitima`,
  `suspeito`, `condenado`, `investigador`, `testemunha`, `outro`) já é
  a MESMA lista usada por `templates/thumbnail.html`
  (`papeis_sujeito_validos=list(thumbnail_etapa7.PAPEIS_SUJEITO_VALIDOS)`,
  `server.py`) e por `scripts/thumbnail_briefing.py`
  (`PAPEIS_VALIDOS`, duplicada de propósito — scripts autocontidos,
  CLAUDE.md seção 9). Um teste novo
  (`test_tela_thumbnail_dropdown_de_papel_lista_todos_os_papeis_validos`)
  confirma que os 6 valores aparecem no HTML renderizado, "condenado"
  incluso — **não foi encontrado no código atual nenhum ponto onde o
  dropdown ofereça só um subconjunto** (o "Vitima/Suspeito/Investigador"
  relatado no print provavelmente era o topo de uma lista de 6 opções
  cortada na captura/rolagem, não uma lista truncada de verdade). Já era
  uma lista canônica única antes desta sessão — nenhuma mudança
  necessária aqui, mas documentado porque foi pedido explicitamente
  verificar.
- **Correção implementada:**
  1. Nova rota `POST /projetos/<id>/thumbnail/atualizar_papel_sujeito`
     (`server.py`) — persiste SÓ o papel de um slot que já tem foto
     enviada, reaproveitando o `arquivo` já salvo em disco (via
     `thumbnail_etapa7.atualizar_sujeito_slot`, que já suportava isso —
     não exigia re-upload, só nunca era chamada de forma independente).
     Slot sem foto ainda: responde `persistido: false` sem erro (o valor
     só passa a valer no próximo upload, que já manda o dropdown atual).
  2. `static/thumbnail.js` ganhou um listener de `change` em cada
     `papel-<slot>` que, quando o slot já tem foto
     (`data-tem-foto="true"`, novo atributo do `<select>` em
     `thumbnail.html`), chama a rota nova imediatamente, atualiza o
     texto ao lado da miniatura (`#papel-atual-<slot>`, novo `<span>`
     interno) com o valor confirmado pelo servidor, e recalcula/atualiza
     as opções elegíveis do dropdown de template
     (`atualizarElegibilidadeTemplate`, chama `thumbnail_briefing.
     templates_elegiveis` no backend e devolve a lista pronta — função
     pura, sem custo de API) sem precisar recarregar a página.
  3. Papel muda o SIGNIFICADO do sujeito — um briefing já gerado pode
     estar descrevendo a pessoa errada. Seguindo a mesma filosofia de
     `upload_sujeito`/`remover_sujeito` (nunca chamar API paga sozinho,
     só por ação explícita do usuário), a rota nova marca
     `thumbnail.briefing_desatualizado=True` em `metadados.json` quando
     já existia um `briefing_completo` — `thumbnail.html` mostra um
     banner de aviso claro. A flag é limpa automaticamente dentro de
     `_aplicar_briefing_grupo_c` (`scripts/7_thumbnail.py`) na próxima
     vez que o usuário gera/regenera o briefing de verdade pelo botão já
     existente — que já relê `sujeitos.json` do zero, então o texto novo
     usa o papel atual sem nenhuma mudança adicional nessa função.
- **Arquivos alterados:** `server.py` (rota nova
  `thumbnail_atualizar_papel_sujeito`), `static/thumbnail.js` (listener
  de `change` + `atualizarElegibilidadeTemplate`), `templates/
  thumbnail.html` (atributo `data-tem-foto`, `<span id="papel-atual-
  <slot>">`, banner `briefing_desatualizado`, nova URL no config JS),
  `scripts/7_thumbnail.py` (`_aplicar_briefing_grupo_c` limpa a flag ao
  gerar briefing novo), `tests/test_thumbnail_rotas.py` (12 testes
  novos).
- **Arquivos que NÃO foram alterados** (conforme restrição do pedido e
  verificação de que não eram a causa): `scripts/headline_engine.py`
  (não tocado), `scripts/thumbnail_briefing.py` (`templates_elegiveis`
  não mudou — só chamada com dado agora correto), `thumbnail_etapa7.
  atualizar_sujeito_slot`/`PAPEIS_SUJEITO_VALIDOS` (já corretos, só
  passaram a ser chamados de um novo lugar).
- **Testes novos** (`tests/test_thumbnail_rotas.py`):
  `test_tela_thumbnail_dropdown_de_papel_lista_todos_os_papeis_validos`,
  `test_atualizar_papel_sujeito_fora_de_aguardando_thumbnail_retorna_400`,
  `test_atualizar_papel_sujeito_slot_invalido_retorna_400`,
  `test_atualizar_papel_sujeito_papel_invalido_retorna_400`,
  `test_atualizar_papel_sujeito_sem_foto_nao_persiste`,
  `test_atualizar_papel_sujeito_persiste_sem_reenviar_foto`,
  `test_atualizar_papel_sujeito_sobrevive_a_reload` (texto e dropdown
  batem após um novo GET),
  `test_atualizar_papel_sujeito_recalcula_elegibilidade_arrow_trio`,
  `test_atualizar_papel_sujeito_marca_briefing_desatualizado`,
  `test_atualizar_papel_sujeito_sem_briefing_previo_nao_marca_flag`,
  `test_gerar_briefing_limpa_flag_desatualizado`.
- **Testes executados:** `.\venv\Scripts\python.exe -m pytest -x --tb=short`
  — **1882 passed** (1871 da sessão anterior + 11 novos, listados acima —
  o do dropdown de papéis documenta um achado sem correção de produto
  associada, a lista já estava correta).
- **Impacto:** qualquer troca de papel de sujeito feita SEM reenviar a
  foto era perdida silenciosamente — o usuário via a mudança no
  dropdown, achava que tinha salvo, e o briefing/composição continuavam
  usando o papel antigo (persistido), inclusive alimentando
  `templates_elegiveis()` com dado desatualizado. Corrigido: a troca
  agora persiste na hora, a tela fica sempre sincronizada com o disco, e
  um briefing já gerado nunca mais é apresentado como válido depois de
  uma troca de papel sem regeneração explícita.

---

## [Sessão de correção — 06/09/2026] 3 bugs de teste real com `video_teste_01` (coluna Estado vazia, elegibilidade de template, papel ignorado no briefing)

Teste real do usuário contra `video_teste_01` (primeira validação ao vivo
da Etapa 7 pós-simplificação — item já sinalizado como pendente em
`MELHORIAS_PENDENTES.md`) reportou 3 bugs. Investigação completa de cada
um antes de qualquer alteração de código (CLAUDE.md seção 8/18.8).

### 1. Coluna "Estado" vazia na lista de projetos — CONFIRMADO E CORRIGIDO

- **Status:** corrigido.
- **Causa raiz:** `templates/home.html` mantém um dict `badge_classes`
  PARALELO a `scripts/labels_ui.py:STATUS_LABEL`, só pra decidir a
  cor/estilo do badge (o texto do badge já vinha corretamente do filtro
  `label_status`, que tem fallback pra chave crua — nunca vazio). Esse
  dict paralelo nunca foi atualizado quando os status `aguardando_thumbnail`
  (Etapa 7) e `falhou` entraram em `STATUS_LABEL` — ficou com só 9 das 11
  chaves. `video_teste_01` está parado em `aguardando_thumbnail`
  (`job.json`), que caía no branch `{% else %}` do template — e esse
  branch renderizava `<span class="status-badge status-badge-vazio">`
  **sem nenhum texto dentro**, só um `title=""` (tooltip, não visível sem
  hover). Daí a coluna parecer vazia mesmo com status definido — dois
  bugs empilhados: dict fora de sincronia + fallback sem texto nenhum.
- **Arquivos:** `templates/home.html` (dict `badge_classes` + branch de
  fallback), `static/style.css` (nova classe `.status-badge-neutro`).
- **Correção:** adicionadas as chaves `aguardando_thumbnail`/`falhou` a
  `badge_classes`. Fallback (`{% else %}`) trocado de um `<span>` vazio
  pra um badge neutro com o texto de `label_status` (que já cai pra chave
  crua se nem isso existir) — agora NENHUM status, conhecido ou futuro,
  pode renderizar sem texto visível.
- **Testes:** `tests/test_labels_ui_integracao.py` ganhou
  `test_home_html_badge_classes_cobre_todo_status_de_labels_ui`
  (falha se um status novo entrar em `STATUS_LABEL` sem entrar também em
  `badge_classes` — trava a próxima regressão igual a esta) e
  `test_home_html_fallback_de_status_desconhecido_nunca_fica_vazio`.
  `tests/test_home_abertura_projeto.py` ganhou 2 testes funcionais
  (`GET /` renderizado de verdade) cobrindo `aguardando_thumbnail` e um
  status totalmente desconhecido.

### 2 e 3. Elegibilidade de template ignora papéis / briefing usa "victim" fixo — NÃO REPRODUZIDO NO CÓDIGO ATUAL

- **Status:** investigado a fundo; comportamento relatado **não reproduz**
  contra o código atual de `scripts/thumbnail_briefing.py`. Não foi
  necessária (nem aplicada) nenhuma alteração de lógica nestes dois
  arquivos: `templates_elegiveis`, `descrever_pessoa_para_prompt`,
  `_papel_em_ingles` e `montar_prompt_*` já implementam exatamente a
  regra pedida (papel declarado é a fonte de verdade, nunca um papel
  fixo, nunca inferido só pela posição/quantidade de fotos).
- **Achado da investigação:** os dois bugs descritos (ARROW_TRIO
  indisponível para vítima+suspeito; grid do DUOTONE_DOSSIER disparando
  com um único secundário de papel diferente; papel ignorado no
  briefing) são **literalmente** os "achados reais" que motivaram a
  reescrita de `templates_elegiveis`/`_papel_em_ingles` na "Sessão de
  simplificação da Etapa 7" (05/09/2026, ver entrada abaixo) —
  `video_teste_01` é inclusive o projeto citado em
  `MELHORIAS_PENDENTES.md` como candidato à primeira validação ao vivo
  dessa sessão. O código de produção (`scripts/thumbnail_briefing.py`,
  `scripts/7_thumbnail.py`) não foi modificado desde 05/09 às 19:17 —
  ou seja, a correção de 05/09 já estava em disco quando o teste real de
  06/09 rodou.
- **Verificação feita nesta sessão (não apenas leitura de código):**
  reproduzido o cenário exato do relato (`hero_papel="vitima"`,
  `secondary_papel="suspeito"`) chamando `templates_elegiveis` e
  `gerar_briefing_completo` de ponta a ponta (com cliente Anthropic fake,
  sem gastar API real) — `ARROW_TRIO` sai elegível e preferido (primeiro
  da tupla, que é o que `server.py:tela_thumbnail` usa como
  `template_sugerido`), e o briefing final contém `"the case's victim"`
  e `"the case's suspect"` corretamente, nunca um papel trocado. Testado
  também 1-sujeito-por-papel (vítima/suspeito/investigador/condenado/
  testemunha) e confirmado que trocar o papel muda o texto do briefing.
  Suíte completa (1871 testes, ver abaixo) já cobria boa parte disso
  (`test_templates_elegiveis_vitima_e_acusado_oferece_arrow_trio_e_duotone`,
  `test_gerar_briefing_completo_com_hero_e_secondary_le_papeis_do_disco`,
  `test_duotone_dossier_papel_diferente_do_hero_mas_investigador_nao_tem_grid`)
  antes mesmo desta sessão começar.
- **Hipótese mais provável pra explicar a discrepância observada:** o
  teste ao vivo do usuário foi a PRIMEIRA execução real da Etapa 7
  pós-simplificação (ver `MELHORIAS_PENDENTES.md`, item já sinalizado
  como "sem validação empírica ao vivo"). `video_teste_01/thumbnail/`
  ainda tem artefatos órfãos da arquitetura ANTERIOR à simplificação
  (`sujeito.png`, `sujeito_origem.json`, `candidatos_cena/`,
  `fundo_gerado.jpg`, datados de 05/09 18:16-18:29 — antes da
  simplificação terminar) — indício de que o projeto foi criado com o
  pipeline antigo. Se o processo do servidor Flask que atendeu ao teste
  ao vivo de 06/09 tiver sido iniciado ANTES do código novo estar em
  disco (processo não reiniciado após a sessão de simplificação), ele
  serviria a lógica antiga só de memória, mesmo com os arquivos `.py`
  já corrigidos — reiniciar o servidor (`iniciar.bat`) resolveria sem
  qualquer mudança de código. **Ação recomendada:** repetir o teste ao
  vivo (vítima+suspeito, e 1 sujeito=suspeito sozinho) com o servidor
  recém-reiniciado antes de investigar mais fundo; se o problema
  persistir mesmo assim, precisa de uma sessão nova com print/log do
  `sujeitos.json` e `briefing.json` gerados NO MOMENTO exato do teste
  (não depois, como desta vez).
- **Testes novos adicionados mesmo sem bug reproduzido** (defesa contra
  regressão futura e cobertura literal dos critérios de aceite do
  pedido, `tests/test_thumbnail_briefing.py`, Grupo G):
  `test_gerar_briefing_completo_um_sujeito_usa_o_papel_declarado_nunca_fixo`
  (parametrizado por papel — nunca "victim" quando o papel não é vítima),
  `test_gerar_briefing_completo_trocar_papel_do_hero_muda_o_briefing`,
  `test_gerar_briefing_completo_vitima_suspeito_arrow_trio_eh_o_preferido`
  (reprodução literal do cenário do pedido) e
  `test_duotone_dossier_grid_nunca_dispara_com_secondary_unico_de_papel_diferente`.
- **`scripts/headline_engine.py` não foi tocado** (restrição explícita
  do pedido) — os 3 bugs eram de elegibilidade de template, propagação
  de papel e renderização de status, nenhum deles no motor de headline.

**Testes executados:** `.\venv\Scripts\python.exe -m pytest -x --tb=short`
— **1871 passed** (1859 antes desta sessão + 12 novos: 2 em
`test_home_abertura_projeto.py`, 2 em `test_labels_ui_integracao.py`, 8
(incluindo variações parametrizadas) em `test_thumbnail_briefing.py`).

**Impacto:** bug 1 fazia qualquer projeto em `aguardando_thumbnail` ou
`falhou` parecer "sem status" na lista de projetos, escondendo em qual
etapa o projeto realmente estava. Bugs 2/3 não confirmados contra o
código de produção atual — sem impacto de código a corrigir, mas
registrados aqui pra não se perder o contexto da investigação caso
reapareçam depois de um restart de servidor confirmado.

---

## [Sessão de simplificação da Etapa 7 — 05/09/2026] Remoção dos templates Pillow, composição só via OpenAI, acumulação de tentativas

**Não é bug — é uma simplificação de arquitetura decidida pelo usuário**
após os 5 templates de composição via Pillow (`scripts/thumbnail_templates.py`)
terem saído muito abaixo das referências reais do nicho em teste real. O
caminho validado que sobrou: o Claude gera o briefing exportável, o
usuário edita se quiser, e a OpenAI compõe a thumbnail final a partir do
briefing + fotos dos sujeitos.

**Removido por inteiro:**
- `scripts/thumbnail_templates.py` (5 templates de composição + fundo
  full-bleed + gradientes/selos/setas desenhados em código).
- Grupo A da Etapa 7 (`gerar_candidatos_thumbnail`/`_amostrar_frames_clipe`/
  `_nitidez_laplaciano` em `scripts/7_thumbnail.py`) — scan de frames de
  CENÁRIO via OpenCV, existia só pra alimentar o fundo dos templates.
- Recorte de sujeito via `rembg` (`recortar_sujeito`, contorno branco +
  remoção de fundo) — a composição por IA manda a foto ORIGINAL, sem
  recorte, direto pro modelo. `resolver_sujeito`/`thumbnail/sujeito_origem.json`
  também saíram (não tinham mais consumidor).
- Modo de fundo-só do provedor OpenAI (`scripts/imagem/openai.gerar()`,
  `/v1/images/generations`) e o provedor "nenhum"
  (`scripts/imagem/nenhum.py`) + a fábrica de provedores em
  `scripts/imagem/__init__.py` (só tinha um consumidor real: o modo de
  fundo removido).
- Campos `layout`/`style` do schema de metadados da thumbnail (Grupo D) —
  só alimentavam os templates Pillow (posição do sujeito, grade de
  estilo visual do fundo-só).
- Dependências `opencv-python` e `rembg[cpu]` (`requirements.txt`) e
  `assets/fonts/BebasNeue-Regular.ttf` — sem consumidor restante.
- **Achado crítico durante a análise:** `scripts/headline_engine.py`
  (Grupo B, filtro de encaixe tipográfico) importava direto
  `thumbnail_templates._carregar_fonte`/`FONTE_HEADLINE_PATH`/
  `_quebrar_texto_em_linhas`/`_medir_texto` — não era só docstring, era
  uso real. Migrado pra dentro do próprio `headline_engine.py` (helpers
  de fonte duplicados, convenção de scripts autocontidos — CLAUDE.md
  seção 9) antes de apagar o módulo, senão a remoção quebraria o
  Headline Engine inteiro. `assets/fonts/Anton-Regular.ttf` continua
  existindo por causa disso.

**Adicionado:**
- `template_forcado` em `thumbnail_briefing.selecionar_template`/
  `gerar_briefing_completo` e em `thumbnail_etapa7.gerar_briefing_thumbnail`/
  `_aplicar_briefing_grupo_c` — permite ao usuário forçar manualmente um
  dos 5 templates de composição na tela (seletor pré-selecionado com a
  sugestão do sistema), em vez de deixar só a IA escolher. Valor fora do
  conjunto elegível pro estado atual de sujeitos é ignorado em silêncio
  (nunca confia só no frontend).
- **Correção de regra de elegibilidade (achado real):** `EVIDENCE_SCENE`
  não pode mais ser elegível em NENHUMA combinação onde há foto de
  sujeito enviada — em teste real, um par vítima+investigador tinha
  `EVIDENCE_SCENE` elegível (junto de `DUOTONE_DOSSIER`/etc — não era o
  caso de único-elegível de `INVESTIGATOR_UPDATE`) e o modelo chegou a
  escolhê-lo, produzindo uma thumbnail sem nenhum dos dois rostos apesar
  das fotos disponíveis. `templates_elegiveis` agora só oferece
  `EVIDENCE_SCENE` quando `hero_papel` é `None` — toda combinação com
  hero cai em templates de retrato (`PROFILE_ISOLATION`/`DUOTONE_DOSSIER`/
  `ARROW_TRIO`/`INVESTIGATOR_UPDATE`, conforme os papéis).
- Composições acumulam em `thumbnail/previews/composicao_ia_NN.jpg`
  (nome sequencial, nunca sobrescreve) em vez de um único
  `composicao_ia.jpg` fixo — cada geração custa dinheiro real, o usuário
  compara e escolhe (ou exclui as que não prestam) entre todas as
  tentativas acumuladas. `server.py:_listar_composicoes_thumbnail`/
  `_proximo_arquivo_composicao` são a fonte única de verdade dos
  arquivos existentes.
- Grid da tela populado a partir do disco no `GET /thumbnail` — não
  depende mais de uma geração ter acontecido na mesma sessão de página
  (antes, só existia em memória JS até o próximo F5).
- Rotas novas: `POST /thumbnail/excluir_composicao` (descarta uma
  tentativa), `POST /thumbnail/escolher_composicao` (substitui
  `escolher_template` — valida `arquivo` contra o disco, não mais contra
  nomes de template fixos), `POST /thumbnail/salvar_briefing` (persiste
  edição manual do único campo de texto que sobrou na tela).
- Bloqueio de `OPENAI_API_KEY` ausente ao marcar "Gerar thumbnail" no
  formulário de Novo projeto (`server.py:/novo`) — sem essa chave nunca
  existiria como produzir a imagem de verdade. Checkbox desabilitado no
  client quando a chave não está configurada, com mensagem explicando o
  motivo; validação repetida no servidor (nunca confia só no client).
  Projeto já existente com a flag ligada e sem chave (ou criado pelo
  caminho `videos_pre_gerados`, que não tem esse checkbox) não quebra —
  a Etapa 7 só informa a ausência da chave, o briefing continua
  disponível pra uso externo.
- CSS do grid de composições corrigido — moldura `aspect-ratio:16/9` +
  `overflow:hidden` garante que a imagem nunca sangre pra fora do
  container, independente da resolução exata devolvida pela API.

**Impacto:** usuário via thumbnails Pillow com qualidade muito abaixo do
que referências reais do nicho produzem; cada geração por IA
sobrescrevia a anterior (sem como comparar tentativas nem recuperar uma
composição boa depois de gerar outra); `EVIDENCE_SCENE` podia ser
escolhido mesmo com fotos de sujeito disponíveis, desperdiçando o
upload; grid de composições sumia ao recarregar a página.

**Testes:** suíte inteira reescrita/atualizada onde necessário
(`tests/test_thumbnail.py`, `tests/test_thumbnail_rotas.py`,
`tests/test_thumbnail_composicao_rotas.py`, `tests/test_thumbnail_briefing.py`,
`tests/test_imagem_openai.py`, `tests/test_ui_correcoes_sessao_thumbnail.py`,
`tests/test_novo_e_status.py`, `tests/test_docs_etapa7.py`);
`tests/test_thumbnail_templates.py` e `tests/test_imagem_provedores.py`
removidos por inteiro (testavam só módulos deletados).
`.\venv\Scripts\python.exe -m pytest -x --tb=short` rodado de verdade:
**1859 passed**. **Validação empírica ao vivo (GRUPO I) NÃO foi feita**
nesta sessão — custaria dinheiro real (API da OpenAI) e mutaria um
projeto real do usuário; ele optou por adiar, ver
`MELHORIAS_PENDENTES.md`.

## [Sessão de refinamento — 04/09/2026] 4 correções de teste real com o pipeline completo

Todos os itens vieram de teste real do usuário com o pipeline ponta-a-ponta.

### 1. Tela de Download em modo leitura — link e tipo de uso ausentes

- **Status:** corrigido.
- **Causa:** `_fontes_baixadas_com_origem` (server.py) montava a linha da
  tabela lendo `fonte["url"]`, mas `scripts/1_baixar_videos.py` grava o
  link em `url_original` — a chave nunca existia, então a coluna "Link
  original" ficava sempre com traço. Não havia coluna nenhuma para o
  tipo de uso (`entrada/fontes_tipo_uso.json`, mapa fonteNN →
  ambos/transcricao/visual, CLAUDE.md seção 5.7.2) — dado que já existia
  em disco desde a Sessão 18 mas nunca era lido por essa tela.
- **Correção:** `_fontes_baixadas_com_origem` agora deriva
  `fonte["url"]` de `fonte.get("url_original") or fonte.get("url")`
  (fallback preserva compatibilidade com qualquer fixture/manifest
  antigo que já usasse a chave errada) e lê `entrada/fontes_tipo_uso.json`
  para preencher `fonte["tipo_uso"]`/`tipo_uso_rotulo` (default "ambos"
  se a fonte estiver ausente do mapa ou o arquivo inteiro não existir —
  mesmo default de `scripts/2_transcrever.py`/`scripts/5_gerar_clipes.py`).
  `templates/pipeline_etapa_detalhe.html` (etapa "download") ganhou a
  coluna "Tipo de uso". Bug de regressão pego em teste real: a primeira
  versão da correção não tratava `pasta_projeto is None` (job que só
  existe em `server.jobs`, sem pasta em disco ainda) — `GET /status/<id>`
  quebrava com `TypeError: unsupported operand type(s) for /: 'NoneType'
  and 'str'`; corrigido guardando a leitura de `fontes_tipo_uso.json`
  atrás de um `if pasta_projeto is not None`.
- **Impacto:** usuário via traço em todo link de vídeo-fonte na tela de
  leitura da Etapa 1, e não tinha como saber se uma fonte foi usada para
  clipes, transcrição ou ambos sem abrir o `.json` manualmente.

### 2. "Duração" na página de conclusão mostrava tempo de processamento, não duração do vídeo

- **Status:** corrigido.
- **Causa:** a rota `/projetos/<id>/concluido` lia
  `montagem_metadata.json.tempo_total_s` e rotulava "Duração" — esse
  campo é `time.monotonic() - inicio_total` da Etapa 6
  (`scripts/6_montar_video.py`), ou seja, tempo de PROCESSAMENTO da
  montagem, nunca a duração do vídeo produzido. Vídeo de ~25min
  aparecia como "5:02".
- **Correção:** `scripts/6_montar_video.py` ganhou
  `_obter_duracao_video_via_ffprobe` (mesmo padrão de
  `obter_duracao_via_ffprobe` em `1_baixar_videos.py`, duplicado por
  design — scripts autocontidos, CLAUDE.md seção 9) e passou a persistir
  `duracao_video_s` (via ffprobe no `video_final.mp4` recém-gerado) em
  `montagem_metadata.json`, nos dois caminhos de montagem (pipeline
  completo e `videos_pre_gerados`). `server.py` (`concluido`) agora
  segue uma cascata: `duracao_video_s` persistido → ffprobe direto em
  `saida/video_final.mp4` (cobre projeto montado antes desta correção
  existir, reaproveitando `_obter_duracao_video_ffprobe` já existente) →
  `narracao_alinhamento.json.duracao_s` como último recurso. O antigo
  `tempo_total_s` continua sendo exibido, mas como campo SEPARADO e
  claramente rotulado ("Tempo de processamento (montagem)"), nunca mais
  compartilhando o rótulo "Duração" com a duração real do vídeo.
- **Impacto:** usuário via um número de duração completamente errado
  (tempo de processamento em vez de duração do vídeo) sem nenhuma
  indicação de que os dois conceitos eram diferentes.

### 3. Custo total da tela de conclusão não incluía tudo que foi gasto

- **Status:** corrigido.
- **Causa:** `_calcular_custo_total_projeto` (renomeada para
  `_calcular_custo_detalhado_projeto`) somava só
  `job_metadata.json`/`narracao_metadata.json`/
  `thumbnail/headline_engine.json`/`*.custo.json` dentro de `thumbnail/`.
  Duas fontes de gasto real ficavam de fora por completo:
  (a) `clipes/sincronizacao_vision_log.json.custo_usd_total` (Feature A,
  sincronização de clipes por Vision) nunca era somado, apesar de já
  estar persistido; (b) `thumbnail/metadados.json` nunca teve NENHUM
  campo de custo — a chamada de Grupo D (metadados/thumbnail) e o
  briefing exportável do Grupo C (`scripts/thumbnail_briefing.py`: fotos
  de sujeito via Vision + seleção de template) calculavam o custo
  internamente (`_custo_usd_da_resposta`) e descartavam o valor, sem
  persistir em lugar nenhum.
- **Correção:** `scripts/7_thumbnail.py` (`gerar_metadados`,
  `regenerar_thumbnail_briefing`, `gerar_briefing_thumbnail`) agora
  acumula o custo de Grupo D + Grupo C numa lista local
  (`_custos_proprios`, deliberadamente SEM incluir o Headline Engine,
  que já persiste seu próprio custo em `headline_engine.json` e seria
  contado duas vezes) e persiste em `metadados["custo_usd_estimado"]`
  (campo top-level, fora do sub-dict `thumbnail` — assim
  `thumbnail_salvar_textos` nunca apaga o campo, já que só reescreve
  `metadados["thumbnail"]`). Regeneração parcial (`regenerar_thumbnail_briefing`/
  `gerar_briefing_thumbnail`) ACUMULA sobre o valor já existente, nunca
  substitui — cada chamada gasta dinheiro novo em cima do que já foi
  gasto. `server.py` passou a somar `sincronizacao_vision_log.json` e
  `metadados.json.custo_usd_estimado`, e devolve `{"total_usd", "itens"}`
  em vez de só o total — a tela de conclusão (`templates/concluido.html`)
  ganhou um `<details>` "Ver detalhamento por etapa" listando cada fonte
  de custo com valor > 0.
- **Impacto:** o card de custo total mostrava um valor sistematicamente
  abaixo do gasto real (num caso real de produção, ~$0.10 a menos só
  pela sincronização por Vision, mais o custo nunca rastreado dos
  metadados/briefing da thumbnail) sem nenhuma forma de auditar o que
  compunha o total.

### 4. `confirm()` nativo do navegador destoava do tema escuro

- **Status:** corrigido.
- **Causa:** o único uso real de diálogo nativo do navegador em toda a
  aplicação era `window.confirm(...)` em `static/thumbnail.js`
  (botão "Finalizar projeto") — caixa de diálogo do SISTEMA OPERACIONAL,
  única peça da aplicação fora do tema escuro Nocturne. Auditoria
  completa (grep em todo `static/*.js` e `templates/*.html`) não achou
  nenhum outro `confirm()`/`alert()` nativo — "Cancelar projeto"
  (`templates/revisao_roteiro.html`) já usava um `<dialog class="modal">`
  próprio, não precisou de mudança.
- **Correção:** `static/confirm_modal.js` (novo) define
  `window.BrollFoundryConfirm.perguntar(opcoes)` — um `<dialog>` nativo
  (foco preso, backdrop, Esc fecha) estilizado com as variáveis CSS de
  `design_system.css`/`style.css` (ambos já carregados globalmente),
  devolvendo uma `Promise<boolean>`. Carregado uma vez em
  `templates/base.html`, disponível em toda página sem import adicional.
  `finalizarProjeto()` em `static/thumbnail.js` passou a usar
  `BrollFoundryConfirm.perguntar({...}).then(...)` no lugar do
  `window.confirm` nativo. `tests/test_confirm_modal.py` (novo) audita
  estaticamente que nenhum `static/*.js` nem `templates/*.html` usa
  diálogo nativo (exceto o próprio `confirm_modal.js`, que os
  implementa) — trava qualquer regressão futura.
- **Impacto:** ao finalizar um projeto, o usuário via uma caixa de
  diálogo branca do Windows no meio de uma interface inteiramente
  escura.

**Testes:** suíte completa (`pytest`, 2016 testes) verde após as 4
correções — inclui os testes novos escritos para cada item (link/tipo de
uso da Etapa 1, cascata de duração do vídeo, soma detalhada de custo,
auditoria do modal de confirmação) mais a correção de uma regressão real
pega pela própria suíte (`_fontes_baixadas_com_origem` com
`pasta_projeto=None`).

---

## [Sessão seguinte — 04/09/2026] Composição por IA agora nasce em 16:9 (sem crop)

- **Status:** corrigido.
- **Causa:** a sessão anterior (item 1 logo abaixo) removeu o crop de
  centro 3:2→16:9 de `gerar_composicao`, mas manteve o `size` pedido à
  API em `TAMANHO_API` (1536×1024, 3:2) — premissa registrada no código
  na época era que "a API de imagens da OpenAI (toda a família GPT
  Image) só aceita os tamanhos 1024x1024, 1024x1536 ou 1536x1024".
  Premissa **errada** para o `gpt-image-2` especificamente (valia pra
  `gpt-image-1`) — a documentação oficial confirma `size` customizado
  no `gpt-image-2` (ambas as dimensões múltiplas de 16, proporção entre
  1:3 e 3:1, borda máxima 3840, total de pixels entre 655.360 e
  8.294.400). Resultado prático: sem o crop antigo e sem pedir 16:9
  direto, a composição salva ficava em 3:2 mesmo — só corrigia o corte
  de texto, não a proporção final da imagem.
- **Correção:** `gerar_composicao` (`scripts/imagem/openai.py`) agora
  pede `size="1536x864"` (constante nova, `TAMANHO_API_COMPOSICAO`) —
  16:9 exato, múltiplo de 16 nos dois lados. Continua sem nenhum
  crop/resize/conversão de proporção depois — grava os bytes exatamente
  como a API devolve. `INSTRUCAO_AREA_SEGURA_16_9` mantida (texto
  reescrito pra não descrever mais um crop que não existe), continua
  ajudando o modelo a deixar margem nas bordas pro headline. Escopo
  restrito a `gerar_composicao` — o modo de FUNDO (`gerar()`, Grupo F)
  continua pedindo `TAMANHO_API` (1536×1024) e recortando pro 1280×720
  que os templates Pillow esperam, isso não mudou.
- **Impacto:** a composição completa por IA (Grupo H, seção 5.85) saía
  em 3:2 (1536×1024) mesmo depois da correção anterior — inconsistente
  com o resto da thumbnail (16:9) e exigia crop/letterbox em qualquer
  lugar que exibisse a imagem lado a lado com os 5 templates Pillow
  (16:9 nativos). Agora sai nativamente 16:9, sem qualquer pós-processamento.
- **Validação real:** rodado `gerar_composicao` de verdade (chave real,
  custo ~$0.02) contra `nancyGuthrieProject03` (mesmo briefing/fotos do
  teste anterior) — imagem salva confirmada em exatamente 1536×864,
  "NANCY GUTHRIE UPDATE" (topo) e "THE MARK ON HIS WRIST" (base) ambos
  visíveis por inteiro, nenhum elemento cortado ou deformado. Arquivo
  anterior (3:2) preservado como `.bak_3x2` ao lado do original antes de
  sobrescrever, no diretório do projeto. Suíte relacionada
  (`test_imagem_openai.py` + os 6 arquivos `test_thumbnail*.py`): 388
  passed.

---

## [Sessão de correções de composição/interface — 04/09/2026] 5 correções vindas de teste real

Cinco itens reportados de uma vez, todos originados de teste real (não
leitura de código). Suíte completa rodada ao final:
`.\venv\Scripts\python.exe -m pytest -x --tb=short` → **1985 passed**
(depois de 2 ajustes de teste existente — ver item 2/4 abaixo — e da
adição de ~35 testes novos cobrindo os 5 itens).

### 1 — Composição por IA cortava texto nas bordas (crop 3:2 → 16:9)
- **Status:** corrigido.
- **Causa:** `gerar_composicao` (`scripts/imagem/openai.py`) sempre
  recortava a imagem devolvida pela API (1536×1024) pro 16:9 do canvas
  de thumbnail (`_recortar_centro`), removendo ~8% de cada borda
  vertical — o modelo posiciona texto (headline, texto grande) perto
  das bordas, então o corte cortava letras. Duas tentativas anteriores
  de mitigar só com texto de prompt (`INSTRUCAO_AREA_SEGURA_16_9`, ver
  entrada logo abaixo) reduziram a frequência mas nunca eliminaram —
  `gpt-image-2` trata instrução de enquadramento como preferência
  forte, não como constraint rígido.
- **Correção:** `gerar_composicao` não mexe mais na imagem devolvida —
  grava exatamente os bytes recebidos, na resolução que a API entregar
  (tipicamente 1536×1024, 3:2). Sem crop, resize, padding ou conversão
  de proporção. `INSTRUCAO_AREA_SEGURA_16_9` continua anexada ao prompt
  (ainda ajuda a composição a deixar margem nas bordas), mas deixou de
  ser necessária pra salvar texto — comentários no código atualizados
  pra deixar claro que o "corte" que ela descreve não existe mais.
  `templates/thumbnail.html` (grid de previews) e `templates/
  concluido.html` (já estava correto) não forçam mais `aspect-ratio`/
  `object-fit` na imagem da composição por IA — só nos 5 templates
  Pillow, que são sempre 1280×720 de verdade.
- **Escopo:** só o modo `gerar_composicao` (Grupo A/H). O modo de FUNDO
  (`gerar()`, Grupo F) continua recortando pro tamanho exato que os
  templates Pillow esperam — isso nunca mudou.
- **Impacto:** a composição por IA nunca mais corta texto que o próprio
  app introduziu via crop — qualquer problema de enquadramento restante
  é decisão do modelo, não mais agravado pelo pós-processamento.
- **Testes:** `tests/test_imagem_openai.py` — teste que checava resize
  pra 1280×720 foi reescrito pra confirmar o oposto (bytes idênticos,
  sem redimensionar); teste novo específico confirma isso.

### 2 — Escolher um template já finalizava o projeto sem aviso
- **Status:** corrigido.
- **Causa:** clicar num template no grid da tela de thumbnail chamava
  direto `POST /thumbnail/escolher_template`, que grava `final.jpg` E
  conclui o job — um clique pra "ver de perto" já encerrava o projeto
  inteiro, sem confirmação e sem volta.
- **Correção:** clicar agora só MARCA a seleção (destaque visual: borda
  de accent grossa + brilho externo no item selecionado, opacidade
  reduzida nos outros) — nenhuma chamada ao backend. Botão separado
  "Finalizar projeto" (inicialmente desabilitado, habilita só após uma
  seleção) pede confirmação explícita via `window.confirm` avisando que
  TODO o projeto será concluído e nada mais poderá ser alterado, e só
  então chama `escolher_template` (rota do backend não mudou — ela já
  fazia exatamente "gravar final.jpg + concluir", que é o que
  "Finalizar" deveria fazer mesmo).
- **Impacto:** navegar pelas opções de thumbnail deixou de ser
  irreversível por acidente.
- **Testes:** `tests/test_ui_correcoes_sessao_thumbnail.py` (testes
  estáticos de fonte, mesmo padrão do resto do arquivo — sem runtime JS
  no projeto) confirmam que `selecionarTemplate` nunca chama o backend e
  que `finalizarProjeto` sempre passa por `window.confirm` antes.

### 3 — Telas de pipeline de projeto concluído abriam vazias / sem navegação clara
- **Status:** corrigido.
- **Causa (3a — navegação):** reabrir uma etapa anterior (ex: roteiro em
  modo leitura) só oferecia "Voltar" (pra lista de projetos), sem opção
  de voltar direto pra tela de conclusão.
- **Causa (3b — conteúdo):** Download/Transcrição/Áudio/Clipes nunca
  tiveram tela de revisita — `_determinar_click`/`ETAPAS_COM_TELA`
  (server.py) só cobriam Roteiro/Montagem/Thumbnail; os outros 4
  círculos do pipeline horizontal nunca viravam link, mesmo com a etapa
  concluída. A tela de Thumbnail em modo leitura também nunca mostrava a
  thumbnail final escolhida (só os uploads de sujeito).
- **Correção:**
  - Nova rota genérica somente-leitura `GET /projetos/<id>/pipeline/
    <etapa>` (`ver_etapa_pipeline`, server.py) + template
    `pipeline_etapa_detalhe.html`, cobrindo download (links + fontes
    baixadas), transcrição (texto completo por fonte), áudio (player) e
    clipes (grid com miniatura via `thumb_clipe`, fonte original e
    duração). `_determinar_click`/`ETAPAS_COM_TELA` estendidos pra essas
    4 etapas — clicáveis assim que a própria etapa fica "done".
  - `tela_thumbnail` (modo leitura) agora exibe `thumbnail/final.jpg`
    quando existe.
  - `revisao_roteiro.html`, `thumbnail.html` e `pipeline_etapa_
    detalhe.html` mostram DOIS botões quando o projeto está concluído:
    "Voltar à conclusão" (`/concluido`) e "Voltar aos projetos"
    (`/`) — antes só existia o segundo.
- **Impacto:** todo o histórico de um projeto concluído fica navegável e
  legível, não só roteiro/vídeo final/thumbnail.
- **Testes:** `tests/test_pipeline_etapa_detalhe.py` (novo, cobre as 4
  etapas + navegação), ajustes em `tests/test_pipeline_clicavel.py`
  (contagem de círculos clicáveis subiu de 3 pra 7 quando concluído) e
  `tests/test_thumbnail_rotas.py` (exibição de `final.jpg` sem
  `aspect-ratio` forçado + dois botões).

### 4 — job.json ilegível mostrava projeto vazio mesmo com artefatos reais em disco
- **Status:** corrigido.
- **Causa:** `job.json` ausente/corrompido fazia a tela de status
  mostrar só "Projeto sem dados persistidos." e a pipeline horizontal
  inteira vazia — mesmo com `saida/video_final.mp4`, `roteiro_
  aprovado.md`, `narracao.mp3` etc. presentes (a coluna "Artefatos" já
  listava esses arquivos, mas nada conectava os dois).
- **Correção:** `_detectar_estagio_por_artefatos` (server.py) infere o
  estágio mais avançado que os artefatos em disco PROVAM ter sido
  concluído (roteiro.md → aguardando_revisao; roteiro_aprovado.md →
  aguardando_audio; clipes/indice.json com clipes → aguardando_
  reorganizacao; saida/video_final.mp4 → aguardando_thumbnail;
  thumbnail/final.jpg → concluido) — sempre um status REAL que alguma
  rota do produto já sabe reabrir, nunca um estado inventado. Nova rota
  `POST /projetos/<id>/reconstruir_estado` grava esse job.json
  reconstruído (via `_persistir_job`, que já tolerava JSON corrompido) e
  redireciona pra tela correta. `status.html` troca a mensagem genérica
  por um banner claro ("O estado deste projeto se perdeu") + o botão de
  reconstrução quando algo é reconstruível.
- **Impacto:** projeto com job.json corrompido deixa de parecer "vazio"
  — o usuário vê exatamente o que existe e pode recuperar o estado com
  um clique, sem precisar mexer manualmente no disco.
- **Testes:** `tests/test_reconstruir_estado.py` (novo — cobre todos os
  5 estágios detectáveis + as 2 recusas com 400) e ajuste em
  `tests/test_novo_e_status.py` (mensagem antiga substituída, teste novo
  cobre o botão de reconstrução aparecendo).

### 5 — Cabeçalhos markdown no roteiro indo pro TTS — confirmado em produção real
- **Status:** corrigido (rede de segurança adicionada); causa raiz
  provável é operacional, não de código — ver observação abaixo.
- **Verificação pedida:** "confirmar em roteiro REAL (não por leitura de
  código) que a correção anterior [Sessão 21, `remover_cabecalhos_
  markdown` chamada em `aprovar_roteiro`] pegou."
- **Achado real:** inspecionado `roteiro_aprovado.md` dos 3 projetos
  reais existentes em disco (`PROJETOS_DIR`). `nancyGuthrieProject01`
  (aprovado 03/09) está limpo — mas o modelo simplesmente não gerou
  cabeçalhos nesse caso (roteiro.md também não tinha nenhum, então não
  prova que a remoção funcionou). `nancyGuthrieProject03` (aprovado
  04/09, mesmo dia desta sessão) tem **17 cabeçalhos `## Título de
  seção` intactos** em `roteiro_aprovado.md` — contagem IDÊNTICA à de
  `roteiro.md` (o bruto, pré-aprovação), provando que a remoção NÃO
  rodou nesse caso. Pior: `narracao_alinhamento.json.texto_transcrito`
  (a transcrição forçada de faster-whisper sobre o ÁUDIO REAL já
  gerado) contém literalmente a frase "Woman Who Lived Alone" — ou seja,
  o narrador já leu esse título em voz alta no `video_final.mp4` deste
  projeto, que já está renderizado.
- **Causa provável:** testado isoladamente, `remover_cabecalhos_
  markdown`/`PADRAO_CABECALHO_MARKDOWN` (server.py) removem os 17
  cabeçalhos do texto real sem problema nenhum quando chamados
  diretamente — o código em si está correto. A explicação mais
  provável, dado que os dois projetos foram aprovados no mesmo dia da
  correção (CLAUDE.md marca "Sessão 21" como 04/09/2026) e o processo
  Flask não recarrega funções automaticamente sem reiniciar: o
  servidor rodando no momento da aprovação do projeto 03 ainda tinha o
  código anterior ao fix carregado em memória. Não foi possível
  confirmar isso com certeza (não há log de reinício do processo), mas
  é a explicação que bate com toda a evidência disponível.
- **Correção adicionada nesta sessão (rede de segurança, CLAUDE.md seção
  18.6/18.7):** `scripts/4_obter_audio.py` agora remove cabeçalhos
  markdown de novo (`_remover_cabecalhos_markdown`, duplicado de
  propósito de `server.py` — script autocontido) logo após ler
  `roteiro_aprovado.md`, antes de mandar o texto pro provedor de TTS —
  nunca mais confia cegamente que a tela de aprovação já limpou o
  arquivo, não importa a causa de uma eventual falha futura (servidor
  não reiniciado, path de aprovação novo que esqueça de chamar a
  limpeza, edição manual do arquivo, etc.).
- **Impacto:** `nancyGuthrieProject03` já tem `video_final.mp4`
  renderizado com o narrador lendo pelo menos "The Woman Who Lived
  Alone in the Foothills" (e provavelmente os outros 16 títulos) em voz
  alta — usuário precisa decidir se quer regenerar áudio/vídeo desse
  projeto especificamente (ver `MELHORIAS_PENDENTES.md`). Daqui pra
  frente, mesmo que o servidor não seja reiniciado depois de um fix
  futuro parecido, a Etapa 4 nunca mais deixaria um cabeçalho markdown
  chegar ao TTS.
- **Testes:** `tests/test_obter_audio.py` — 2 testes novos pra
  `_remover_cabecalhos_markdown` (função pura) + 1 teste de integração
  que aprova um roteiro COM cabeçalho e confirma que o texto enviado de
  verdade pro payload da API do Google TTS nunca contém `##` nem o
  título do cabeçalho.

---

## [Sessão seguinte à 29 — 04/09/2026] Instrução de área segura pro corte 3:2 → 16:9 da composição por IA

- **Status:** mitigado, não resolvido (ver `MELHORIAS_PENDENTES.md`).
- **Causa:** `gerar_composicao` (`scripts/imagem/openai.py`) pede a
  imagem em `1536x1024` (3:2, único tamanho paisagem aceito pelo
  `/v1/images/edits`) e `_recortar_centro` corta pro 16:9 final
  (1280x720) removendo as faixas de 0-80 e 944-1024 (~8% de cada borda).
  O modelo, seguindo o `briefing_completo` que já pede texto grande
  "Top:"/"Bottom:", frequentemente posiciona headline encostado nas
  bordas — cortado nessas faixas. Confirmado antes desta sessão contra
  `nancyGuthrieProject03` (headline "NANCY GUTHRIE UPDATE" no topo e
  "THE MARK ON HIS WRIST" na base saindo cortados).
- **Correção:** `INSTRUCAO_AREA_SEGURA_16_9` (novo, `scripts/imagem/
  openai.py`) — parágrafo em inglês anexado ao prompt só na chamada de
  API (`gerar_composicao`, variável local `prompt_api`), nunca ao
  `briefing_completo` persistido em `thumbnail/metadados.json`/
  `briefing.json` (esse continua servindo intacto o caminho manual de
  copiar/colar, onde o corte 16:9 desta função não se aplica). Descreve
  em pixels exatos a faixa cortada e uma margem de segurança extra
  (linha 220 do topo / 804 da base), com instrução explícita pra'
  orçar altura de headline que quebra em 2 linhas.
- **Validação empírica (3 chamadas reais pagas, `nancyGuthrieProject03`,
  mesmo briefing/mesmas fotos):** variância grande entre gerações da
  MESMA chamada com o MESMO prompt — uma geração ficou quase perfeita
  (os dois blocos de texto sobreviveram ao crop com folga real, único
  defeito residual foi a ponta de um elemento decorativo secundário), a
  geração seguinte ignorou a margem quase por completo e voltou a
  cortar as duas pontas como antes da correção. `gpt-image-2` trata a
  instrução como preferência forte, não como constraint rígido
  respeitado 100% das vezes.
- **Impacto:** a correção reduz a frequência/severidade do corte (uma
  instrução explícita em pixels claramente ajuda comparado a nenhuma
  instrução), mas não elimina o defeito — usuário ainda pode ver texto
  cortado numa geração individual e precisa clicar "Gerar composição
  por IA" de novo (layout aleatório novo a cada clique) se a primeira
  sair ruim. Não fechar este item como resolvido — ver
  `MELHORIAS_PENDENTES.md` pro que uma correção de verdade (detecção
  automática + regeneração, ou outpainting em vez de crop) exigiria.
- **Testes:** `tests/test_imagem_openai.py` — teste existente que
  verificava `prompt` enviado por igualdade exata foi ajustado pra'
  checar `startswith`/presença da instrução; teste novo confirma que o
  `briefing_completo` recebido pela função nunca é mutado (a instrução
  só existe no prompt mandado pra API).

---

## [Sessão 29 — 04/09/2026] Composição de thumbnail por IA (Parte 2, Grupo D do backlog) + reconstrução da tela de conclusão

- **Status:** entregue e validado empiricamente contra
  `nancyGuthrieProject03` (par vítima/investigador, mesmo projeto usado
  na validação da Sessão 28) — a API aceitou a composição real na
  primeira tentativa, sem recusa de moderação. Ver "Validação empírica"
  abaixo.

- **Contexto:** a Sessão 28 confirmou que colar o briefing exportável
  (Grupo C) num gerador de imagem externo, junto das fotos dos sujeitos,
  produz resultado no nível das referências do nicho. Esta sessão
  automatiza esse mesmo caminho dentro da ferramenta — a Parte 2 que
  ficara pendente desde a reconstrução da Etapa 7 (ver
  `MELHORIAS_PENDENTES.md`, entrada "Etapa 7 reconstruída — Parte 2
  pendente") — mantendo o caminho manual disponível como sempre
  funcionou.

- **Grupo A — `scripts/imagem/openai.gerar_composicao`.** Modo novo,
  separado de `gerar()` (que continua só gerando o FUNDO via
  `/v1/images/generations`). Manda `thumbnail.briefing_completo` como
  prompt + as fotos ORIGINAIS dos sujeitos (sem recorte — o rembg é só
  do caminho Pillow) como `image[]` pro endpoint `/v1/images/edits`, na
  ordem hero-primeiro/secondary-depois. `input_fidelity` nunca é enviado
  (não é ajustável no `gpt-image-2` — CLAUDE.md seção 5.85). Toda falha
  (sem chave, sem fotos, sem briefing, rede, recusa de moderação,
  resposta sem imagem, falha ao salvar) devolve um dict com
  `erro_tipo`/`erro_mensagem`/`status_http` REAIS (nunca string
  genérica) e persiste em `thumbnail/composicao_status.json`
  (`ler_status_composicao`) — sobrevive a um recarregamento de página,
  mesmo padrão de `fundo_status.json` (Grupo C da sessão anterior).
  Sucesso grava sidecar `.custo.json` igual ao caminho de fundo.

- **Grupo B — botão na Etapa 7.** Nova rota
  `POST /projetos/<id>/thumbnail/gerar_composicao_ia`, só habilitada com
  `OPENAI_API_KEY` configurada (`tem_openai_key` no contexto de
  `tela_thumbnail`). Ação sempre explícita — nunca chamada
  automaticamente por outro fluxo, cada clique custa uma chamada real.
  O resultado é salvo em `thumbnail/previews/composicao_ia.jpg` — o
  MESMO diretório de onde os 5 templates Pillow já são servidos, então
  `thumbnail_escolher_template` só precisou aceitar `"composicao_ia"`
  como nome válido além de `thumbnail_templates.TEMPLATES`, sem nenhum
  caminho especial pra copiar/concluir o job.

- **Grupo C — tela `/concluido` reconstruída.** Antes só mostrava
  vídeo + download + abrir pasta. Agora reúne tudo que o projeto
  produziu, somente leitura: vídeo (preview + download), thumbnail
  final (preview + download), 3 títulos sugeridos com botão de copiar
  cada, descrição completa com copiar, tags com "copiar todas", e dados
  do projeto (perfil, duração, custo total). Custo total é best-effort
  (`_calcular_custo_total_projeto`, server.py) — soma
  `job_metadata.json` (roteiro), `narracao_metadata.json` (TTS),
  `thumbnail/headline_engine.json` e todo `*.custo.json` dentro de
  `thumbnail/`; rotulado como estimativa porque a chamada única de
  metadados da Etapa 7 (Grupo D de `scripts/7_thumbnail.py`) não
  persiste custo em lugar nenhum hoje (ver `MELHORIAS_PENDENTES.md`).
  Todo campo é opcional — projeto antigo sem thumbnail/tags/descrição
  simplesmente não renderiza aquela seção, sem erro. Nenhuma ação de
  mutação na tela — trocar thumbnail/regerar briefing continua sendo só
  na Etapa 7.

- **Grupo D — abertura direta pela Home.** Já estava implementado desde
  antes desta sessão (`home.html`, linha do link de cada projeto já
  resolvia `destino = 'concluido' if status == 'concluido' else
  'status'`) — só ganhou teste de regressão novo
  (`tests/test_home_abertura_projeto.py`).

- **Validação empírica (Grupo F do prompt de sessão):** chamada real
  contra `/v1/images/edits` com o briefing de `nancyGuthrieProject03`
  (template `INVESTIGATOR_UPDATE`, hero=vítima/secondary=investigador)
  e as duas fotos originais — **aceita na primeira tentativa**, sem
  recusa de moderação. Rostos preservados de forma reconhecível nos
  dois sujeitos, cena de fundo (casa suburbana à noite) composta
  corretamente, layout seguiu o template pedido. Custo real: baixo
  ($0.02 estimado, qualidade `low`). **Defeito visual encontrado:** o
  crop central (1536×1024 → 1280×720, mesma lógica de `gerar()`) corta
  a headline no topo ("NANCY GUTHRIE UPDATE") e o texto grande na base
  ("THE MARK ON HIS WRIST") — o modelo compôs o texto perto das bordas
  porque o briefing atual não instrui margem de segurança pensando em
  crop pós-geração (essa instrução existe no `BASE_PROMPT` de `gerar()`,
  mas não é usada pelo prompt de composição, que é o
  `briefing_completo` gerado por `thumbnail_briefing.py`). Registrado
  em `MELHORIAS_PENDENTES.md` — não bloqueia a entrega (a composição em
  si funciona, é ajuste fino de enquadramento).

- **Testes:** `tests/test_imagem_openai.py` (Grupo A, unitário —
  ordem das fotos, um sujeito só, `content_policy_violation` capturado
  sem exceção, falha de rede, resposta sem imagem, persistência de
  status/custo), `tests/test_thumbnail_composicao_rotas.py` (Grupo B —
  botão condicional a `OPENAI_API_KEY`, rota completa mockada,
  integração com `escolher_template`), `tests/test_concluido.py`
  (Grupo C — campos presentes, thumbnail/tags/descrição ausentes não
  quebram, nenhuma rota de mutação exposta), `tests/
  test_home_abertura_projeto.py` (Grupo D). Suite completa
  (`.\venv\Scripts\python.exe -m pytest -x --tb=short`): **1948
  passed** (nenhuma regressão).

---

## [Sessão 28 — 04/09/2026] 4 defeitos no briefing exportável (Grupo C): grid absurdo com investigador, headline substituído pelo nome do caso, papel em português vazando pro prompt em inglês, briefing apagado ao salvar textos

- **Status:** corrigido. Validação empírica real contra
  `nancyGuthrieProject03` (hero=vítima/secondary=investigador, headline
  "The Mark On His Wrist") confirmada ao final da sessão — ver Grupo G
  abaixo.

- **Contexto:** a Sessão 27 entregou o briefing exportável (Grupo C)
  funcionando, e o teste real do usuário confirmou que colar o briefing
  num gerador de imagem externo junto das fotos produz resultado muito
  superior à composição Pillow local. Mas o briefing real gerado (par
  vítima+investigador) tinha 4 defeitos que o usuário teve que contornar
  manualmente:
  ```
  "...On the left, show a tilted evidence-board panel containing
  approximately 12–15 black-and-white male investigator photographs
  arranged in a grid. Add a large amber arrow pointing from the
  photographs toward the vitima. Bottom-left amber banner containing
  "41 MINUTES INSIDE HER HOME — FBI PROFILE" in white italic uppercase
  and "NANCY GUTHRIE" in extremely large white uppercase letters."
  ```

- **Bug 1 (Grupo A) — `templates_elegiveis` cego ao PAPEL, só à presença
  de foto.** Um par vítima+investigador deixava `DUOTONE_DOSSIER`
  elegível (junto com `ARROW_TRIO`/`INVESTIGATOR_UPDATE`/
  `EVIDENCE_SCENE`), e o Claude escolhia `DUOTONE_DOSSIER`, que sempre
  gerava um grid de "12-15 fotos" pra qualquer `secondary` presente —
  produzindo "quinze cópias do mesmo agente" (o único investigador
  enviado). **Correção:** `templates_elegiveis(hero_papel, secondary_papel)`
  agora decide por CATEGORIA (vítima/suspeito-condenado/investigador):
  vítima+investigador trava em `INVESTIGATOR_UPDATE` (único elegível,
  nem chama API); vítima+suspeito/condenado oferece `ARROW_TRIO`/
  `DUOTONE_DOSSIER` (seta de acusação); hero e secondary com o MESMO
  papel habilita o grid do `DUOTONE_DOSSIER` (só faz sentido
  representando múltiplos sujeitos do mesmo tipo); qualquer outra
  combinação sem relação clara só oferece `EVIDENCE_SCENE`. O próprio
  `montar_prompt_duotone_dossier` também passou a checar a relação antes
  de montar o grid, não só a presença de `secondary`. `selecionar_template`
  agora recebe os papéis declarados como contexto extra na chamada.

- **Bug 2 (Grupo B) — cascata `subject_name → emphasis_word → headline`
  fazia o NOME DO CASO virar a linha grande.** `_linha_pequena_e_grande`
  (usada pelos 4 templates com duas linhas de texto) preferia
  `subject_name` sobre o headline do Headline Engine — por isso "NANCY
  GUTHRIE" apareceu em destaque no lugar de "41 MINUTES INSIDE HER
  HOME", a peça com lacuna de curiosidade que o Headline Engine (Sessão
  23) foi desenhado pra produzir. **Correção:** linha grande é SEMPRE o
  headline, sem cascata de fallback — `subject_name` nunca ocupa essa
  linha. Sem cascata silenciosa: headline ausente/vazio agora faz
  `gerar_briefing_completo` devolver `{"sucesso": False, "erro":
  "headline_ausente"}` em vez de inventar uma linha grande a partir de
  outro campo. A rota dedicada `/thumbnail/gerar_briefing` repassa esse
  erro de verdade pro JS (antes sempre devolvia `sucesso: True` mesmo
  quando o Grupo C não tinha conseguido gerar nada útil).
  `montar_prompt_profile_isolation` tinha um label redundante que também
  repetia o headline — corrigido pra usar `subject_name` (único uso
  legítimo que sobrou pra esse label pequeno).

- **Bug 3 (Grupo C) — papel cru em português (`caso['hero_papel']`/
  `caso['secondary_papel']`) interpolado direto em texto de prompt em
  INGLÊS**, em vez de passar pelas funções de tradução
  (`descrever_pessoa_para_prompt`/`descrever_papel_curto`) já existentes
  — daí "pointing from the photographs toward the vitima" no meio de um
  prompt inglês. **Correção:** nova função `_papel_em_ingles` (reusa a
  mesma tabela de `descrever_papel_curto`) usada em toda frase de
  `montar_prompt_arrow_trio`/`montar_prompt_duotone_dossier`/
  `montar_prompt_investigator_update` que menciona o papel diretamente.
  Teste novo garante que nenhum briefing gerado (em nenhuma combinação de
  papéis) contém caractere fora do ASCII básico nem palavra crua em
  português.

- **Bug 4 (Grupo D) — `salvar_textos` apagava `briefing_completo`/
  `briefing_template` de `metadados.json`.** A correção anterior
  (Sessão 27) protegia `background_prompt` contra sobrescrita pela tela
  de textos, mas os dois campos do briefing (adicionados depois) ficaram
  de fora da proteção — salvar qualquer edição de texto na tela apagava
  o briefing já gerado. **Correção:** generalizado numa allowlist única
  em `server.py` (`CAMPOS_THUMBNAIL_PRESERVADOS_DO_SERVIDOR`) em vez de
  listas soltas por campo, pra nunca mais repetir esse defeito com um
  campo futuro.

- **Bug 5 (Grupo E, achado à parte) — botão "Gerar / regenerar briefing"
  nunca preenchia o textarea.** `static/thumbnail.js:gerarBriefing()` lia
  `resultado.dados.briefing_completo`/`resultado.dados.template_escolhido`
  na raiz da resposta, mas a rota devolve
  `{sucesso, thumbnail: {briefing_completo, briefing_template}, metadados}`
  — os dois campos vivem dentro de `thumbnail`. O textarea só era
  preenchido no carregamento inicial da página (Jinja, sempre esteve
  correto); clicar no botão depois nunca atualizava nada. Corrigido pra
  ler o caminho certo.

- **Achado extra durante a validação empírica (Grupo G) —
  `montar_prompt_investigator_update` não forçava uppercase no
  headline.** O headline persistido vem em Title Case ("The Mark On His
  Wrist"), não uppercase — sem `.upper()` no texto inserido, o prompt
  contradizia a própria instrução "in white uppercase" logo ao lado.
  Corrigido (a checagem de substring de `emphasis_word` continua usando
  o case original, só a exibição no prompt é maiúscula).

- **Grupo G (validação empírica real):** rodado contra
  `nancyGuthrieProject03` de verdade (`ANTHROPIC_API_KEY` real, hero=
  vítima/secondary=investigador, headline "The Mark On His Wrist") via
  `thumbnail_etapa7.gerar_briefing_thumbnail`. Resultado: template
  `INVESTIGATOR_UPDATE` (único elegível, sem chamada de API pra
  escolher), linha grande `"THE MARK ON HIS WRIST"` com `"WRIST"` em
  destaque âmbar, papéis traduzidos ("investigator"/"victim"), nenhuma
  palavra em português no texto final. Backup dos arquivos originais
  feito antes da execução real (removido depois, resultado ficou melhor
  que o anterior e é o comportamento desejado).

- **Impacto:** todo briefing exportável envolvendo par vítima+
  investigador (ou qualquer combinação onde `secondary` estava presente)
  vinha com um grid de fotos sem sentido; todo briefing tinha o nome do
  caso na linha de maior destaque em vez do headline com lacuna de
  curiosidade; papel em português vazava pro prompt em inglês; e editar
  qualquer texto na tela depois de gerar o briefing apagava o trabalho.
  `pytest`: 1922 testes verdes ao final (71 no arquivo de testes do
  Grupo C, +19 desta sessão).

## [Sessão 27 — 04/09/2026] Reconstrução da Etapa 7 (thumbnail) — Parte 1: fim do grid de candidatos + Vision-sobre-clipe, upload de sujeitos com papel declarado, briefing exportável

- **Status:** corrigido/implementado (Parte 1 — Grupos A/B/C). Parte 2
  (composição via API `gpt-image-2`, validação pós-geração por Vision,
  caixa alta nos templates Pillow, correção do sangramento de
  `_desenhar_faixa_diagonal`, verificação de `gerar_thumbnail=False`)
  registrada em `MELHORIAS_PENDENTES.md` para sessão futura.

- **Bug raiz (achado real, projeto NancyGuthrieProject01, já documentado
  em comentário de código antes desta sessão mas nunca registrado
  formalmente aqui).** A arquitetura anterior da Etapa 7 varria os
  CLIPES do vídeo final em busca de rosto (Haar cascade do OpenCV) e,
  quando o Grupo D já tinha um `subject_name`, perguntava ao Claude
  (Vision) qual candidato correspondia à pessoa nomeada — uma chamada
  única enviando todos os frames com rosto encontrados. Em teste real
  contra uma fonte de telejornal, a Vision escolheu repetidamente a
  APRESENTADORA do noticiário em vez da vítima do caso, porque o rosto
  mais frequente nos frames extraídos era o de quem narrava a matéria,
  não o de quem o caso era sobre. A causa é estrutural, não um prompt
  mal escrito: pedir a um modelo pra "identificar quem é a pessoa X"
  usando só frames de b-roll, sem nenhuma foto de referência confiável,
  é um problema mal-posto — o modelo não tem como saber a aparência real
  de "X" a partir do próprio material que está tentando classificar.

- **Decisão de reconstrução (não um patch).** Em vez de tentar melhorar
  o prompt da identificação (já tinha uma heurística anti-frequência —
  "não escolha pelo rosto mais frequente, escolha pela identidade" — e
  ainda assim falhou), a arquitetura inteira de origem do sujeito foi
  substituída: o usuário agora faz upload de até 2 fotos (`thumbnail/
  sujeitos/sujeitos.json`) DECLARANDO o papel de cada uma (vítima/
  suspeito/condenado/investigador/testemunha/outro) no momento do
  upload. Vision nunca mais decide identidade — só, opcionalmente
  (`scripts/thumbnail_briefing.py:extrair_atributos_foto`), descreve
  atributos visuais genéricos (enquadramento/expressão/gênero/faixa
  etária) de uma foto cujo papel já é conhecido, com fallback
  determinístico sem chave.

- **O que foi removido:** detecção de rosto via Haar cascade
  (`_abrir_cascade`/`_detectar_maior_rosto`/`CAMINHO_CASCADE` +
  `assets/cv/haarcascade_frontalface_default.xml`), identificação por
  Vision (`identificar_sujeito_por_vision`/`SCHEMA_IDENTIFICACAO`/
  `_status_identificacao`/`identificar_e_resolver_vision`/
  `vision_automatico_ligado`/env var `VISION_AUTOMATICO_THUMBNAIL`),
  grid "Candidatos com rosto"/"Cenário" da tela e as rotas
  `thumbnail/escolher_candidato`, `thumbnail/escolher_candidato_cena`,
  `thumbnail/identificar_vision`. A amostragem de frames de CENÁRIO
  (fundo de último recurso) foi mantida — `opencv-python` continua no
  `requirements.txt`, só o uso de `CascadeClassifier` foi removido.

- **O que foi adicionado:** `resolver_sujeito`/`recortar_sujeito`
  reescritos pra cascata de 2 slots (`atualizar_sujeito_slot`/
  `remover_sujeito_slot`); módulo novo `scripts/thumbnail_briefing.py`
  (Grupo C) com os 5 templates de composição em prompt
  (`ARROW_TRIO`/`PROFILE_ISOLATION`/`EVIDENCE_SCENE`/`DUOTONE_DOSSIER`/
  `INVESTIGATOR_UPDATE` — especificação medida em `referencias/
  thumbnails/`), seleção de template com enum fechado ao que os papéis
  disponíveis permitem, e regra de segurança que só permite tarja de
  censura de rosto quando o papel é suspeito/condenado (nunca vítima/
  investigador/testemunha/outro, mesmo se pedido). Rotas novas
  `thumbnail/upload_sujeito`, `thumbnail/remover_sujeito`,
  `thumbnail/gerar_briefing`, `thumbnail/sujeito_original/<slot>`.

- **Bug corrigido durante a implementação (nunca chegou a produção):**
  a primeira versão de `_aplicar_briefing_grupo_c` não repassava o
  cliente Anthropic mockável do chamador pra `thumbnail_briefing.
  gerar_briefing_completo` — reconstruía um cliente novo só a partir de
  `api_key`. Em teste, isso teria feito testes com `cliente=` fake ainda
  assim tentar uma chamada de API real (CLAUDE.md seção 8). Corrigido
  antes de rodar a suíte (`cliente_api` agora é sempre repassado).

- **Impacto:** thumbnails de casos com fonte de telejornal/entrevista
  paravam de escolher a pessoa errada (a causa raiz nem existe mais —
  não há mais decisão automática de identidade). `pytest` 1897 testes
  verdes ao final da Parte 1.

## [Sessão 24 — 04/09/2026] Juiz do Headline Engine nunca executava (temperature=0 removido na Sonnet 5), regeneração desperdiçada, idioma inconsistente

- Status: corrigido
- Contexto: `thumbnail/headline_engine.json` do `nancyGuthrieProject03`
  mostrava `"julgamentos": null` e `"erro_julgamento":
  "chamada_api_falhou"` nas DUAS rodadas — a Chamada A (geração de
  candidatos) funcionava bem (12 candidatos, todos ancorados), mas a
  Chamada C (juiz) nunca produzia nota nenhuma. Custo total registrado
  (`$0.020943`) era compatível só com as chamadas de geração, nenhuma
  de julgamento — confirmando que o problema estava isolado na Chamada
  B/C.

- **Bug 1 (causa raiz) — `julgar_candidatos` passava `temperature=0`.**
  Investigação confirmou (não assumida — consultada a referência de API
  atual da Claude Sonnet 5): a partir da família Opus 5/Sonnet 5, o
  pensamento adaptativo fica ligado por padrão e a API **removeu** os
  parâmetros de sampling explícitos — `temperature`/`top_p`/`top_k`
  sempre devolvem 400, mesmo `temperature=0`. `gerar_candidatos_headline`
  (Chamada A) nunca passou `temperature` e por isso sempre funcionou;
  `julgar_candidatos` (Chamada C) era a ÚNICA chamada do módulo inteiro
  que passava esse parâmetro — explica por que só o juiz falhava,
  sempre, nas duas rodadas.
  - Correção: removido `temperature=0` da chamada. O código genérico
    `except Exception: return None, "chamada_api_falhou"` (duplicado 3x
    no módulo — Chamada A, Chamada C, `extrair_nucleo_compacto`) também
    escondia a causa real por trás de uma string fixa sem tipo/mensagem/
    status HTTP. Nova função `_detalhar_excecao(exc)` captura
    `{"codigo": "chamada_api_falhou", "tipo": type(exc).__name__,
    "mensagem": str(exc), "status_code": getattr(exc, "status_code",
    None)}` — os três pontos de captura de exceção agora usam ela.
    `status_code` vem de `anthropic.APIStatusError`/subclasses quando
    disponível.

- **Bug 2 — falha do juiz disparava uma segunda rodada de geração à
  toa.** O código antigo tratava "juiz falhou (erro de API)" IGUAL a
  "nenhum candidato passou do limiar de aprovação" — as duas caíam no
  mesmo `feedback` de regeneração, gastando uma chamada de Chamada A
  inteira (6 candidatos novos) sem nenhuma chance de resolver um
  problema que estava na chamada do juiz, não nos candidatos. Isso
  explica por que `nancyGuthrieProject03` tinha DUAS rodadas completas
  de geração (12 candidatos no total) e ZERO julgamentos.
  - Correção: falha do juiz (`erro_julgamento` truthy com sobreviventes
    presentes) agora interrompe o loop imediatamente
    (`juiz_falhou_com_sobreviventes = True; break`), sem disparar
    `gerar_candidatos_headline` de novo. Regeneração continua valendo
    normalmente pro caso genuíno de "todos os candidatos foram
    eliminados pelos filtros determinísticos" ou "juiz avaliou mas
    ninguém passou do limiar" — só a falha de INFRAESTRUTURA do juiz é
    que não dispara mais rodada extra.

- **Bug 3 — fallback sem julgamento não era distinguível do aviso
  genérico.** Quando o juiz falha nas duas tentativas (ou não sobra
  candidato pra avaliar), o fallback (`_melhor_candidato_sem_aprovacao`)
  pega o primeiro candidato bruto da rodada 1 — mas isso só aparecia
  como `aviso_revisao_humana=True` genérico, indistinguível de "foi
  avaliado mas ficou abaixo do limiar" (caso bem menos grave, porque ali
  pelo menos existe uma nota real).
  - Correção: novo campo `fallback_sem_julgamento` (`gerar_headline`,
    `_aplicar_headline_engine` em `scripts/7_thumbnail.py`, allowlist de
    campos de proveniência preservados em `POST
    /thumbnail/salvar_textos` no `server.py`) — `True` quando o
    vencedor final nunca recebeu nota nenhuma (`judge_score is None`).
    `templates/thumbnail.html` ganhou um banner específico e mais
    enfático pra esse caso, separado do banner genérico de
    `aviso_revisao_humana` (que agora só aparece quando o vencedor TEM
    nota mas não passou do limiar). `headline_engine.json` também grava
    `juiz_falhou_com_sobreviventes` e `idioma_usado` na auditoria, pra
    diagnóstico futuro sem precisar reproduzir o bug.

- **Bug 4 — idioma inconsistente entre campos e rodadas.**
  `withheld_fact` saiu em português na rodada 1 e em inglês na rodada 2
  do MESMO roteiro (en-US); `nucleo_editorial_usado` (modo degradado,
  Grupo F) saiu inteiramente em português ("Erros que traem o ladrão
  perfeito") num projeto en-US, apesar de `pergunta_promessa` estar
  100% em inglês. Causa: os prompts (`headline_engine_candidatos.md`,
  `headline_engine_nucleo_compacto.md`) só diziam "mesmo idioma do
  roteiro/da pergunta-promessa fornecida" — instrução IMPLÍCITA, pedindo
  pro modelo inferir do conteúdo, sem nenhuma diretiva explícita de
  idioma. Verificado que `job_metadata.json` já tinha `"idioma": "en-US"`
  persistido (gravado por `3_gerar_roteiro.py`) — o dado correto já
  existia, só não estava sendo lido nem repassado pelo Headline Engine.
  - Correção: `_ler_contexto` agora lê `idioma` de `job_metadata.json`
    (mesma cascata que `server.py` já usa em outro lugar: `idioma` do
    job_metadata → `IDIOMA_ROTEIRO` do ambiente → default `en-US`).
    `gerar_candidatos_headline` e `extrair_nucleo_compacto` recebem esse
    idioma como parâmetro e o incluem como diretiva EXPLÍCITA na
    primeira linha da mensagem do usuário ("Idioma exigido para TODOS os
    campos de texto: <idioma>") — os prompts dos dois foram atualizados
    pra' declarar que essa diretiva é autoritativa, mesmo que outro
    trecho do contexto pareça sugerir idioma diferente.

- Impacto: o Headline Engine v1 (Sessão 22) nunca funcionou de verdade
  em produção desde que foi implementado — rodava, gastava dinheiro de
  API (Chamada A x2 por vídeo), e sempre caía no fallback sem nenhuma
  avaliação de qualidade, silenciosamente, sem nenhum sinal visível na
  tela além de um aviso genérico.
- Validação empírica: confirmado com uma chamada real e isolada de
  `julgar_candidatos` contra a API (antes do rerun completo) que
  `temperature` devolve `400 - "temperature is deprecated for this
  model"` na Claude Sonnet 5, e que a mesma chamada sem esse parâmetro
  funciona e devolve notas reais. Rerun completo de
  `scripts/7_thumbnail.py` contra `nancyGuthrieProject03` (metadados.json/
  headline_engine.json antigos movidos de lado pra forçar regeneração —
  `metadados_desatualizados()` pula a Etapa D quando o roteiro não mudou
  desde a última geração, comportamento correto e não relacionado a este
  bug) confirmou a correção ponta a ponta: `julgamentos` preenchido com
  nota por critério pros 6 candidatos, vencedor "The Mark On His Wrist"
  com `judge_score: 11` (não-nulo), `erro_julgamento: null`,
  `numero_rodadas: 1` (aprovou de primeira, sem precisar de
  regeneração), `idioma_usado: "en-US"` e `nucleo_editorial_usado` em
  inglês ("Careful burglar's small mistakes revealing his identity" —
  antes saía em português no mesmo projeto). Suíte completa (1889
  testes, 9 novos em `tests/test_headline_engine.py`) verde.

## [Sessão 23 — 04/09/2026] Etapa 7 nunca rodava como subprocess (import quebrado), status/tela de thumbnail escondiam a falha, cabeçalhos markdown iam pro TTS

- Status: corrigido
- Contexto: quatro problemas relacionados, todos girando em torno da
  Etapa 7 (thumbnail) e da limpeza pré-TTS do roteiro. Achado real:
  projeto `nancyGuthrieProject03` tinha `video_final.mp4` (1.4GB),
  `job.json` com `status: "aguardando_thumbnail"`, mas nenhuma pasta
  `thumbnail/` em disco e nenhum erro em lugar nenhum.

- **Bug 1 (crítico) — `scripts/7_thumbnail.py` linha 80 fazia
  `from scripts import headline_engine, thumbnail_templates`.** Como
  subprocess (é assim que `_executar_etapa7` chama o script — mesmo
  padrão de `_executar_etapa1..6`), a raiz do projeto não está no
  `sys.path`, então o import falha com `ModuleNotFoundError: No module
  named 'scripts'` antes de QUALQUER linha do script rodar. Os 1857+
  testes da suíte nunca pegaram isso porque o `pytest` roda da raiz do
  projeto (raiz já está no `sys.path` por causa de
  `tests/conftest.py`) — e `server.py` também carrega
  `scripts/7_thumbnail.py` via `importlib` (não subprocess) pras
  chamadas diretas de Grupo B/C/D, o que também mascarava o bug (a
  raiz já está no `sys.path` quando o processo é o próprio `server.py`).
  Só o caminho real de produção (subprocess disparado por
  `_executar_etapa7`) expõe o problema.
  - Correção: `scripts/7_thumbnail.py` ganhou o MESMO padrão que
    `scripts/3_gerar_roteiro.py` e `scripts/4_obter_audio.py` já usam
    pra imports de pacote (`from scripts.X import Y`) — insere a RAIZ
    do projeto (não só `scripts/`) no `sys.path` antes do import
    quebrado. Não inventei padrão novo — `scripts/5_gerar_clipes.py` e
    `scripts/6_montar_video.py` usam um padrão parecido mas mais simples
    (só `scripts/` no path, porque só fazem `import robustez` direto,
    sem `from scripts import X` de pacote) — `7_thumbnail.py` precisa da
    raiz porque `thumbnail_templates.py` importa `from scripts import
    imagem` (pacote), não um módulo solto.
  - Auditoria: todos os 7 scripts numerados (`1_baixar_videos.py` a
    `7_thumbnail.py`) foram executados como SUBPROCESS real (não
    import), a partir de um diretório de trabalho diferente da raiz do
    projeto (`%TEMP%`), com um caminho de pasta inválido — nenhum deles
    apresentou `ModuleNotFoundError`/`Traceback`, e todos saíram com
    `returncode == 1` (falha honesta de validação de input, CLAUDE.md
    seção 18.6), nunca 0 silencioso. Só `7_thumbnail.py` tinha o bug.

- **Bug 2 — `_executar_etapa7` (server.py) marcava
  `status: "aguardando_thumbnail"` incondicionalmente**, mesmo quando
  o subprocess saía com `returncode != 0`. A regra "Etapa 7 nunca falha
  o job" (CLAUDE.md, pra' nunca travar o pipeline com o vídeo final já
  pronto) tinha virado, na prática, "esconde que a etapa não rodou" —
  exatamente o caso do `nancyGuthrieProject03`.
  - Correção: `_executar_etapa7` continua terminando em
    `"aguardando_thumbnail"` (nunca em `"erro"` — o vídeo final está
    pronto e a regra de nunca travar o pipeline continua válida), mas
    agora checa `processo.returncode` e grava `job["etapa7_falhou"] =
    True` + `mensagem_usuario`/`tipo_erro`/`log_erro` (stderr já está
    no próprio `job["log"]`, porque o subprocess roda com
    `stderr=STDOUT`) quando falha. `_montar_estado_status` expõe esse
    flag pro template. Novo campo persistido em `job.json`
    (`etapa7_falhou`), lido via `_persistir_job`/`_ler_job_json` como
    qualquer outro campo dinâmico.

- **Bug 3 — tela de status sem caminho quando `aguardando_thumbnail`.**
  `templates/status.html` não tinha bloco nenhum pra esse status —
  ficava só com "Etapa: Thumbnail / Status: Aguardando thumbnail" e a
  `detalhe` estática ("Preparando candidatos..."), sem link nem botão.
  Reportado mais de uma vez, nunca implementado.
  - Correção: dois blocos novos em `status.html`, mutuamente exclusivos
    por `estado.etapa7_falhou`: (a) etapa 7 concluiu — aviso "Vídeo
    final pronto e thumbnail preparada!" com link direto pra
    `/projetos/<id>/thumbnail`; (b) etapa 7 falhou — banner de erro com
    a mensagem, botão "Tentar novamente" (nova rota
    `POST /projetos/<id>/gerar_thumbnail`, mesmo padrão de retry manual
    de `montar_video_rota`/`transcrever`, mas SEM exigir status
    diferente do atual — é exatamente `aguardando_thumbnail` que uma
    falha de etapa 7 deixa o projeto, então a rota não pode recusar
    rodar nesse status) e link "Revisar manualmente" pra completar a
    mão mesmo sem retry. `static/status.js` ganhou o toggle dos dois
    blocos via polling e o handler de clique do botão de retry.

- **Bug 4 — tela de thumbnail sem explicação com zero candidatos.**
  Grid duplo vazio, botão "Identificar automaticamente (Vision)"
  desaparecia junto (`{% if not modo_readonly and candidatos_rosto %}`
  escondia o botão inteiro quando não havia candidato de rosto).
  - Correção: banner explicativo quando os dois grids (rosto + cenário)
    estão vazios, distinguindo "a geração automática falhou" (`
    etapa7_falhou`) de "rodou e não achou nada" (nenhum rosto/cenário
    qualificado nos clipes) — com botão "Tentar gerar candidatos
    novamente" (mesma rota nova `gerar_thumbnail_rota`, redireciona pra
    tela de status pra acompanhar o progresso). Botão de Vision não
    desaparece mais com zero candidatos — fica com tooltip/texto
    explicando que precisa de candidato com rosto primeiro (a chamada
    já devolvia erro gracioso `pre_condicao_nao_atendida` nesse caso,
    então manter visível não quebra nada, só deixa de esconder o
    caminho). Upload de foto própria continua em destaque, sem mudança.

- **Bug 5 — cabeçalhos markdown iam pro TTS.** O roteiro saía com
  linhas tipo `## The Woman Who Lived Alone in the Foothills`,
  `## A Doorbell Camera and Forty-One Minutes` — o vídeo é contínuo,
  sem cortes de seção, então o narrador (TTS) lia o subtítulo como se
  fosse texto narrado, ou (se removido sem cuidado) a transição ficava
  seca. Causa: `scripts/prompts/perfis/truecrime/sistema.md`, seção
  "Formato de saída", autorizava explicitamente "eventualmente um
  subtítulo se o roteiro for longo o suficiente para se beneficiar de
  seções" — brecha que `atualidades_narrativas` e `historia` nunca
  tiveram (comparação de texto confirmou: os outros dois perfis já
  paravam a frase em "descritas nas regras acima.", sem a permissão de
  subtítulo).
  - Correção (dupla, como pedido — nunca só uma): (1) removida a frase
    de permissão em `truecrime/sistema.md`, cirúrgica — Regra 0,
    estrutura por dívida narrativa, proibições de voz e regra de
    derivação numérica intocadas. Hash de não-regressão em
    `tests/test_gerar_roteiro.py`
    (`test_sistema_md_nao_foi_alterado_por_esta_sessao`) recalculado
    conscientemente, com comentário explicando a exceção. (2) nova
    função `remover_cabecalhos_markdown()` em `server.py`, chamada
    junto de `remover_notas_rodape()` na limpeza que já roda em
    `POST /aprovar_roteiro` (grava `roteiro_aprovado.md`) — remove a
    LINHA do cabeçalho ATX (`#` a `######`) preservando a quebra de
    parágrafo ao redor (colapsa linhas em branco extras pra uma só,
    nunca zero). Cobre os dois ângulos: prompt não oferece mais a
    brecha pra roteiros novos, e o código de limpeza pega qualquer
    cabeçalho que ainda aparecer (do truecrime por hábito residual do
    modelo, ou de qualquer outro perfil) antes de chegar no TTS.
    Retrocompatível por natureza — só afeta o momento de aprovação, não
    mexe em `roteiro_aprovado.md` já gravado de projetos antigos.

- Impacto: `nancyGuthrieProject03` ficaria pra sempre em
  "aguardando_thumbnail" sem thumbnail nenhuma e sem o usuário nunca
  saber que precisava agir — bug crítico de produção. Validado
  rodando `scripts/7_thumbnail.py` de verdade contra esse projeto real
  (228 clipes, 12 candidatos de rosto + 8 de cenário gerados,
  `returncode 0`) e suíte completa (1865 testes, incluindo os novos de
  `remover_cabecalhos_markdown`) verde.

## [Sessão 22 — 04/09/2026] Headline Engine v1 — isola a geração do headline da thumbnail numa chamada dedicada

- Status: implementado, aguardando validação empírica em projeto real
  (Grupo I — ver `MELHORIAS_PENDENTES.md`)
- Contexto: diagnóstico já fechado antes da sessão (não reinvestigado):
  o `headline` da thumbnail saía descritivo ("41 MINUTES INSIDE HER
  HOME" em vez de "WHAT ABDUCTOR WANTED") porque era preenchido no
  MESMO turno da chamada que gera `subject_name`/descrição/tags
  (`scripts/7_thumbnail.py` Grupo D, `entregar_metadados`) — o modelo
  aplica viés de sumarização e devolve o fato mais saliente do caso em
  vez de abrir uma lacuna de curiosidade. Restrição adicional que
  definiu o desenho: não bastava maximizar a lacuna — pesquisa sobre
  8.977 experimentos reais de headline (Aubin Le Quéré & Matias,
  *Scientific Reports* 15:994, 2025) mostra relação curvilinear entre
  concretude e taxa de clique (vago demais, tipo "THE TRUTH REVEALED",
  performa tão mal quanto concreto demais), então o juiz do Grupo C
  pesa "abre lacuna" e "ancorado neste caso" com peso igual.
- Correção: novo módulo `scripts/headline_engine.py` (importado direto
  por `scripts/7_thumbnail.py`, mesmo padrão de `thumbnail_templates.py`
  — CLAUDE.md seção 5.86 tem o desenho completo). Chamada A dedicada (6
  candidatos com `headline`/`gap_type`/`withheld_fact`/`emphasis_word`,
  few-shot contrastivo) → filtros determinísticos em código (tamanho,
  repetição do título, encaixe tipográfico com a fonte real de
  `thumbnail_templates.py`, `emphasis_word` literal, lista de risco
  configurável) → juiz em chamada separada com temperatura zero (nunca
  reescreve) → no máximo 1 rodada de regeneração com o feedback do juiz
  → se as duas rodadas falharem, persiste o melhor candidato disponível
  com aviso de revisão humana (nunca falha o pipeline por causa do
  headline). Modo degradado quando `nucleo_editorial_status` (Sessão
  21) é `"ausente"` ou o campo não existe — deriva um núcleo compacto da
  `pergunta_promessa` numa chamada extra antes da Chamada A. Auditoria
  completa (todos os candidatos das duas rodadas, inclusive eliminados
  com motivo, notas do juiz, versão do prompt, custo) persiste em
  `thumbnail/headline_engine.json`. `gerar_metadados` e
  `regenerar_thumbnail_briefing` sobrescrevem `headline`/`emphasis_word`
  com o resultado do motor novo — as demais chamadas (`subject_name`,
  `background_prompt`, etc.) continuam vindo da chamada única de
  sempre, sem duplicar custo. `templates/thumbnail.html` ganhou dois
  avisos reaproveitando o componente `.thumb-aviso-vision` já existente
  (modo fallback, revisão humana recomendada).
- Achado de calibração durante os testes: a primeira versão do filtro
  de encaixe tipográfico exigia que o headline coubesse numa ÚNICA
  linha em 320px a 36px (o menor tamanho de headline entre todos os
  templates) — medição real com a fonte Anton-Regular.ttf mostrou que
  isso reprovaria até os próprios exemplos de forma do prompt ("WHAT
  ABDUCTOR WANTED" mede 334px, mais largo que 320). Corrigido pra
  aceitar quebra em até 2 linhas (mesma função de quebra dos templates
  reais, `_quebrar_texto_em_linhas`) — só elimina headline realmente
  longo/verboso, não qualquer headline normal de 3-6 palavras.
- Impacto: nenhuma regressão nos templates existentes (5 templates,
  `background_prompt` intocado) — suite completa (1857 testes, 25
  novos em `tests/test_headline_engine.py`) verde. Falta validação
  empírica com projeto real (Grupo I, `MELHORIAS_PENDENTES.md`) — os
  testes cobrem a lógica com fakes, nunca a qualidade real dos
  headlines gerados pela API de verdade.

## [Sessão 21 — 04/09/2026] Três correções pré-thumbnail — reparo de nucleo_editorial, honestidade do banner de nome, duas réguas de palavras narradas

- Status: corrigido
- Contexto: três problemas encontrados revisando a Sessão 20 antes de
  avançar pra sessão de thumbnail. (1) `nucleo_editorial` era obrigatório
  no schema mas `_validar_saida_estruturada` aceitava ausente/vazio sem
  nenhum tratamento — nenhum reparo, nenhum registro do problema, o
  Grupo B simplesmente ficava mudo. (2) o banner do Grupo A dizia "sem
  confirmação em fonte escrita", prometendo uma auditoria documental que
  o código não faz — a comparação é contra o resumo estruturado que o
  **próprio modelo** produziu (a API de web search da Anthropic nunca
  expõe texto bruto de página, `encrypted_content` é opaco), não contra
  texto de fonte externa verificado por fora; a mensagem enganava sobre o
  que a checagem realmente garante. (3) `job_metadata.json` informava
  4.216 palavras narradas mas a tela de revisão mostrava 4.120 — duas
  réguas medindo a mesma coisa: `contar_palavras_narradas()` (canônica,
  usada pra `ratio_tamanho`/expansão/justificativa) ignora notas de
  rodapé e markdown, enquanto `static/revisao.js` fazia
  `texto.trim().split(/\s+/).length` sobre o conteúdo bruto do textarea
  (contando `[F1@04:32]` e símbolos markdown como "palavras"), rodando
  inclusive no carregamento inicial da página, antes de qualquer edição.
- Verificação (item 3): confirmado por leitura de código que a contagem
  divergente do JS **nunca alimenta decisão nenhuma do pipeline** —
  `server.py` não lê `contador-caracteres`/`contador-palavras` em lugar
  nenhum (só `templates/revisao_roteiro.html` e `static/revisao.js`
  referenciam esses ids), e todas as decisões (expansão condicional,
  justificativa forçada, `ratio_tamanho`) já estavam fechadas em
  `job_metadata.json` antes da tela de revisão sequer renderizar. Era
  divergência puramente visual, mas ainda assim uma régua errada visível
  ao usuário.
- Correção: **(1)** `scripts/3_gerar_roteiro.py` ganhou
  `_nucleo_editorial_valido` (2-8 palavras) rodando **depois** de
  `_validar_saida_estruturada` (que continua sem checar o campo, de
  propósito — um roteiro que custou ~US$1 e saiu bom nunca é descartado
  por causa de metadado). Se inválido/ausente: UMA chamada curta e
  forçada (`entregar_nucleo_editorial`, nova tool em
  `TOOLS_FASE_ESTRUTURADA`) tenta reparar só esse campo a partir da
  `pergunta_promessa` já aprovada — nunca regera o roteiro. `job_metadata
  ["nucleo_editorial_status"]` grava `"ok"`/`"reparado"`/`"ausente"`
  (reparo falhou ou devolveu valor ainda inválido) — nunca silencioso.
  **(2)** banner do Grupo A (`revisao_roteiro.html`) trocado para o texto
  literal "Nome não corroborado pelo resumo de pesquisa; confirme em
  fonte escrita antes de aprovar." — CLAUDE.md §5.4.1 ganhou parágrafo
  explícito registrando que isso NUNCA deve voltar a ser lido/escrito
  como checagem factual/documental numa sessão futura. **(3)**
  `static/revisao.js` parou de recalcular o contador de palavras —
  `atualizarContador()` agora só atualiza caracteres (live, útil
  enquanto edita). O template renderiza `job_metadata.palavras_narradas`
  (persistido, servidor) diretamente no `<span id="contador-palavras">`,
  com rótulos diferenciando as duas métricas ("caracteres no editor" vs
  "palavras narradas na geração") em vez de fingir que são a mesma
  coisa. Projeto sem `palavras_narradas` em `job_metadata.json` (roteiro
  gerado antes da métrica existir, ou importado por upload) simplesmente
  omite esse trecho — nunca recalcula como fallback.
- Impacto: reparo de `nucleo_editorial` nunca mais falha silenciosamente
  (status sempre visível em `job_metadata.json`, base pra tela de
  thumbnail futura avisar modo fallback — ver `MELHORIAS_PENDENTES.md`).
  Banner do Grupo A não promete mais checagem que não existe. Tela de
  revisão mostra um número só de "palavras narradas", sempre igual ao
  `job_metadata.json`. 1832 testes passando (suite completa) — 17 novos
  nesta sessão, mais o teste de não-regressão que descobriu que a vasta
  maioria dos testes existentes de `test_gerar_roteiro.py` dependia
  implicitamente de `nucleo_editorial` ausente da fixture default (corrigido
  dando à fixture um valor default válido, igual já acontecia com
  `pergunta_promessa`).

## [Sessão 20 — 04/09/2026] Validações pós-geração — nome próprio sem confirmação, título divergente, número sem derivação

- Status: corrigido
- Contexto: refinamento pós-validação empírica da Sessão 19 (ratio 0,64→1,05
  validado em uso real). Três problemas específicos que a Sessão 19 tentou
  resolver via regra em `sistema.md` continuaram acontecendo no roteiro
  real gerado depois: nome próprio garbado por legenda automática
  ("Tomás Ossioni" em vez do nome correto) sustentado só por nota de
  transcrição `[F#@mm:ss]`; título sugerido divergindo do gancho real do
  roteiro (títulos sobre tatuagem/41 minutos/prisão em vez do fio da
  pergunta-promessa); número de duração ("forty-one minutes") repetido 3x
  no roteiro mas com derivação explicada só na 1ª menção. Padrão: regra de
  prompt pega quando pede decisão discreta antes de escrever (a
  pergunta-promessa pegou, Sessão 19), falha quando pede vigilância
  contínua ao longo de 25-35k caracteres — mais regras em `sistema.md`
  competiriam por atenção com a Regra 0, então nenhum `sistema.md` foi
  tocado nesta sessão.
- Correção: 3 validações pós-geração em `scripts/3_gerar_roteiro.py`
  (nunca bloqueiam, nunca corrigem sozinhas — só avisam na tela de
  revisão, CLAUDE.md seção 5.4.1/5.5). Grupo A
  (`detectar_nomes_suspeitos`): nome próprio candidato ausente de um
  corpus construído a partir do resumo estruturado da fase 1 de pesquisa
  E sustentado só por nota `[F#@mm:ss]` vira nível `alto` (destaque na
  tela); ausente sem nota/nota ambígua vira `medio` (só em
  `job_metadata.json`). Descoberta durante a implementação: a API de web
  search da Anthropic não expõe texto bruto de página (`encrypted_content`
  opaco) nem isso é persistido em lugar nenhum hoje — o resumo estruturado
  (`pessoas_envolvidas` etc., até então descartado após montar o prompt da
  fase 2) é a aproximação mais fiel disponível sem adicionar fetch de
  página externo (fora de escopo). Grupo B (`detectar_titulos_divergentes`):
  `SCHEMA_SAIDA` ganhou campo obrigatório `nucleo_editorial` (3-6
  palavras, gerado junto da pergunta-promessa); título sem termo
  significativo em comum com o núcleo entra num aviso lexical — **só
  sinaliza, nunca regera** (decisão explícita: heurística lexical
  regerando titulo bom seria pior que o problema). Grupo C
  (`detectar_numeros_sem_derivacao`): número de duração/janela temporal
  sem marcador de derivação (registros, horários, "based on") nas 2
  frases anteriores entra no aviso; escopo restrito a duração (nunca
  contagem/valor/distância genérico); configurável via
  `VALIDACAO_NUMEROS_ATIVA`. `templates/revisao_roteiro.html` ganhou 3
  banners novos no mesmo componente `banner banner-aviso` já usado por
  `aviso_tamanho`/`pergunta_promessa` — nenhum aviso, nenhum banner.
- Achado durante a validação empírica (Grupo F do plano da sessão, rodado
  contra o roteiro real de um projeto em produção que continha os dois
  bugs conhecidos): a primeira versão do regex de candidato a nome
  (`\s+` entre tokens) atravessava quebra de linha, produzindo
  candidatos absurdos como `"Foothills\n\nNancy Guthrie"` quando um
  título markdown (`## ...`) vinha logo antes de um parágrafo — títulos
  em Title Case (convenção comum de subtítulo de seção) geravam ruído
  massivo (44 candidatos, 26 nível alto, num roteiro de 4.216 palavras).
  Corrigido escaneando linha a linha e excluindo linhas que começam com
  `#` (`_linhas_narrativas`) — caiu para 24 candidatos/17 alto no mesmo
  teste. As duas ocorrências reais (nome garbado, número sem derivação)
  continuaram sinalizadas corretamente durante toda a correção — ver
  `MELHORIAS_PENDENTES.md` para a ressalva sobre ruído residual em uso
  real (a maior parte do ruído restante são nomes reais e legítimos que,
  numa geração de verdade, apareceriam em `pessoas_envolvidas` do resumo
  real e não seriam sinalizados — o teste usou resumo vazio de propósito,
  pior caso possível, porque o resumo da geração original nunca foi
  persistido).
- Impacto: usuário vê 3 avisos não-bloqueantes novos na tela de revisão
  quando aplicável, sem nenhuma mudança no fluxo de aprovação. 1815
  testes passando (suite completa), incluindo hash-pin dos 3 `sistema.md`
  confirmando que nenhum foi tocado.

## [Sessão 19 — 04/09/2026] Reestruturação do roteiro — pergunta-promessa, estrutura por dívida narrativa, correções factuais

- Status: corrigido
- Contexto: teste real de um roteiro gerado expôs três problemas
  independentes: (1) o título nascia depois do roteiro inteiro, então
  era descritivo do que já tinha sido escrito em vez de organizar a
  narrativa; (2) a métrica de tamanho (`ratio_tamanho`) media caracteres
  com espaços, markdown e notas de rodapé contra um piso que o próprio
  prompt define como "sem espaços" — medição real do roteiro:
  20.644 chars com espaço, 17.502 sem, 99 notas de rodapé somando
  1.559 chars, 3.068 palavras narradas contra 4.800 pedidas; o ratio
  reportado foi 0,86, mas o real em palavras narradas era 0,64; (3) três
  bugs de conteúdo no roteiro gerado: nome próprio errado vindo de
  garble de transcrição automática ("Tomas Ossioni" em vez de Tommaso
  Cioni — pessoa real, viva, não-suspeita), disclaimer proibido pelo
  próprio prompt contornado em prosa na narração ("isto é uma
  interpretação de um analista, não um fato confirmado" — 4
  ocorrências), e número declarado como fato observado ("ficou 41
  minutos dentro da casa") quando na verdade era uma janela derivada de
  dois sinais eletrônicos distintos (violação da Regra 6 do próprio
  prompt, proibição de invenção)
- Correção: nos três `sistema.md` (`truecrime`, `atualidades_narrativas`,
  `historia`) — Regra 0 (pergunta-promessa), formulada antes de
  qualquer frase do roteiro, organizando título/hook/critério de corte
  de material, com arquétipos adaptados por nicho; estrutura por dívida
  narrativa (abertura sem revelar nada → âncora → corpo em dificuldade
  crescente → virada entre 60% e 75% → consequência → fechamento)
  substituindo a estrutura cronológica antiga; proibições de voz
  explícitas (5 disclaimers falados banidos, com exemplo comparativo) e
  regra de derivação numérica (todo número de dados narrado através dos
  dados que o produzem, nunca declarado pronto); regra de nome próprio
  proibindo nota de transcrição para pessoas, exigindo fonte
  jornalística/acadêmica escrita ou uso de parentesco/cargo até
  confirmação. Em `scripts/3_gerar_roteiro.py`: `pergunta_promessa`
  virou campo obrigatório e validado no schema de saída; `ratio_tamanho`
  passou a medir palavras narradas (sem notas de rodapé nem markdown)
  contra `palavras_alvo`, com as contagens de caracteres mantidas só
  como campos informativos; expansão automática (até 2 tentativas,
  aprofundando dentro do fio da pergunta-promessa, nunca reintroduzindo
  material cortado) quando o roteiro fica abaixo de 95% do alvo, com
  cada tentativa descartada se a contagem de notas de rodapé cair mais
  de 10%; justificativa de tamanho obrigatória via chamada forçada
  quando o piso não é atingido após as expansões e o modelo não a
  forneceu por conta própria. `scripts/4_obter_audio.py` ganhou métrica
  de fechamento informativa (palavras por minuto efetivas da voz real,
  pós-TTS)
- Impacto: usuário via um ratio de tamanho inflado (0,86 quando o real
  era 0,64) escondendo um roteiro sistematicamente curto sem aviso
  correspondente; título sem função de retenção real; risco concreto de
  difamação por nome de pessoa real grafado errado num vídeo de true
  crime; disclaimer falado na narração quebrando regra que o próprio
  prompt já proibia

## [Sessão 18 — 31/08/2026] Modo de fontes separadas + upload de mídias

- Status: pendente (validação manual)
- Contexto: introduzido `entrada/fontes_tipo_uso.json` (mapa fonte →
  "ambos"/"transcricao"/"visual") e `entrada/fontes_upload.json` (fontes
  visuais enviadas direto pelo usuário, sem passar por yt-dlp). Cobertura
  de teste (`tests/test_fontes_separadas.py`) usa mocks de upload
- Bug potencial: o fluxo de upload real de arquivo de vídeo/imagem pelo
  formulário não foi validado em ambiente sandbox (sem browser disponível
  na sessão) — só o caminho server-side (leitura do JSON, exclusão da
  transcrição) foi testado
- Correção: nenhuma ainda — item registrado como validação pendente
- Impacto: risco de bug de UI (upload trava, extensão de arquivo não
  aceita, mensagem de erro pouco clara) só aparecer no primeiro uso real

## [Sessão 17 — 31/08/2026] Pipeline horizontal clicável + read-only

- Status: nenhum bug crítico
- Contexto: cada etapa do pipeline horizontal (introduzido na Sessão 16)
  virou clicável, abrindo o resultado daquela etapa em modo leitura
- Correção: N/A
- Impacto: N/A

## [Sessão 16 — 31/08/2026] Pipeline horizontal sticky

- Status: pendente (validação visual)
- Contexto: barra de progresso do pipeline virou horizontal e sticky no
  topo da tela de status/detalhe do projeto
- Correção: nenhuma ainda — `top: 72px` do elemento sticky foi calculado
  a partir da altura do header, mas não foi confirmado empiricamente em
  navegador real (só revisão de CSS)
- Impacto: risco de sobreposição visual entre header e barra sticky em
  resoluções não testadas

## [Sessão 15 — 31/08/2026] Refinamentos visuais

- Status: nenhum bug crítico
- Contexto: ajustes de polish visual sobre o design system Nocturne
  introduzido na Sessão 14
- Correção: N/A
- Impacto: N/A

## [Sessão 14 — 31/08/2026] Reformulação visual — design system Nocturne

- Status: corrigido
- Contexto: reformulação completa de `static/design_system.css` e dos
  templates. O formulário de novo projeto tinha um toggle "Vision"
  (ativar/desativar análise visual opcional de cenas), que já estava sem
  função real desde a mudança de arquitetura em andamento
- Correção: toggle morto removido do formulário junto com o resto do
  polish visual, em vez de deixar controle sem efeito na tela
- Impacto: usuário não via mais opção que não fazia nada

## [Sessão 13 — 31/08/2026] Legendas estilo MrBeast + música de fundo em playlist

- Status: nenhum bug crítico
- Contexto: `6_montar_video.py` ganhou legenda queimada estilo "MrBeast"
  (karaoke por palavra) opcional e música de fundo com ducking e loop
  sequencial de playlist (várias faixas em `entrada/musica_fundo/`)
- Correção: N/A
- Impacto: N/A

## [Sessão 12 — 31/08/2026] Etapa 6 — Montagem final do vídeo

- Status: corrigido
- Contexto: implementação de `6_montar_video.py` (concat de clipes + mux
  com narração + legendas). Validação com o test-writer identificou 6
  bugs nos testes escritos (não no código de produção) antes de fechar a
  sessão
- Correção: os 6 bugs de teste foram corrigidos durante a própria sessão,
  antes de considerar a etapa pronta (CLAUDE.md seção 8: nenhuma etapa
  pronta sem pytest verde)
- Impacto: nenhum — pega em validação, nunca chegou a produção

## [Sessão 11 — 31/08/2026] Abandono da detecção de cena — volta pra round-robin estilo yt_automation

- Status: corrigido
- Contexto: após as sessões 9-10.4 tentarem PySceneDetect + Vision +
  pHash sem resultado que compensasse o custo/tempo (ver entradas
  abaixo), a sessão consolidou `5_dividir_cenas.py` +
  `6_montar_timeline.py` + `7_renderizar_clipes.py` num único
  `5_gerar_clipes.py`, voltando pra seleção aleatória de trechos com
  round-robin de fontes (abordagem do `yt_automation`, Gustavo Xavier),
  sem detecção de cena, sem Vision, sem deduplicação por pHash
- Correção: a correção do bug crítico da Sessão 10.1 (`-ss` depois de
  `-i` no comando ffmpeg, causando seek lento e ~3.5min/clipe) tinha sido
  aplicada manualmente pelo usuário antes desta sessão começar — a nova
  arquitetura de `5_gerar_clipes.py` já nasceu com `-ss` antes de `-i`
- Impacto: eliminou a classe inteira de bugs de performance/custo das
  sessões 9-10.4 trocando a abordagem em vez de continuar corrigindo
  sintoma por sintoma

## [Sessão 10.4 — 31/08/2026] Otimização de detecção de cena

- Status: corrigido
- Contexto: `AdaptiveDetector` do PySceneDetect mudou de API entre
  versões da biblioteca — `auto_downscale=True` no construtor passou a
  bloquear o setter manual de downscale usado pelo código
- Correção: ajustado o uso da API pra versão instalada
- Impacto: sessão de otimização que precedeu o abandono completo da
  abordagem (Sessão 11)

## [Sessão 10.3 — 31/08/2026] Paralelização de extração de frames

- Status: corrigido
- Contexto: teste do aviso de custo (100 cenas fake) acionava
  `ProcessPoolExecutor` de verdade dentro do ambiente de teste, em vez de
  ficar isolado
- Correção: resolvido com fixture que isola o `ProcessPoolExecutor`
- Impacto: sem a fixture, rodar a suíte de testes gastaria CPU/tempo real
  processando frames fake desnecessariamente

## [Sessão 10.2 — 31/08/2026] Análise visual opcional via Claude Vision

- Status: não corrigido (arquitetura removida na Sessão 11)
- Contexto: `categoria_visual` das cenas mantidas aparecia como "N/A" no
  catálogo de cenas — bug menor, não crítico. Além disso, o custo real de
  rodar Vision ($0.82/vídeo) saiu 2x acima do estimado ($0.30-0.50) pra
  descartar só 5 de 82 cenas analisadas
- Correção: nenhuma aplicada — o custo-benefício ruim foi um dos fatores
  que motivou abandonar a arquitetura inteira na Sessão 11, então o bug
  do "N/A" nunca chegou a ser corrigido antes de o código ser removido
- Impacto: nenhum em produção — feature nunca saiu do estágio de
  validação antes de ser descontinuada

## [Sessão 10.1 — 31/08/2026] Correções pós-Sessão 10

- Status: corrigido (posteriormente, arquitetura removida na Sessão 11)
- Contexto: dois bugs críticos de performance na cadeia
  `5_dividir_cenas.py`/`6_montar_timeline.py`/`7_renderizar_clipes.py`:
  (1) `-ss` posicionado DEPOIS de `-i` no comando ffmpeg, forçando seek
  lento e ~3.5min por clipe; (2) timeout hardcoded de 8 minutos
  sobrepondo o timeout adaptativo que já existia, cortando renders
  legítimos de vídeos mais longos. Além disso, 6 bugs foram encontrados
  nos testes do test-writer durante a validação
- Correção: `-ss` movido pra antes de `-i` (aplicação manual do usuário);
  timeout hardcoded removido, voltando a respeitar o timeout adaptativo;
  os 6 bugs de teste corrigidos
- Impacto: sem a correção, renderização de clipes ficava ~100x mais
  lenta que o esperado (seek linear em vez de seek rápido do ffmpeg)

## [Sessão 10 — 31/08/2026] Arquitetura dividir_cenas/montar_timeline/renderizar_clipes

- Status: corrigido (posteriormente, arquitetura removida na Sessão 11)
- Contexto: primeira versão da arquitetura de 3 scripts substituindo o
  corte por janela fixa por detecção de cena. Dois bugs na primeira
  implementação: categorização textual não descartava alertas silenciosos
  (trechos sem áudio, ex.: cartela de aviso de conteúdo sensível sem
  narração); IDs duplicados gerados no `plano_edicao.json`, produzindo
  clipes idênticos na timeline final
- Correção: ambos corrigidos antes de a Sessão 10.1 seguir com as
  otimizações de performance
- Impacto: sem correção, vídeo final teria clipes repetidos e trechos sem
  valor visual (alertas silenciosos) entrando na montagem

---

## [Sessão 9.4 — 30/08/2026] Detecção de cena via ffmpeg gerava excesso de cenas e custo descontrolado de Vision

- Status: corrigido
- Contexto: teste real (Sessão 9.3) detectou 407 cenas num único vídeo
  (esperado: 100-200) porque a detecção anterior (filtro
  `select='gt(scene,X)'` do ffmpeg) tratava movimento de câmera (zoom,
  pan) como corte de cena novo. Resultado: ~$2.72 (R$14) gastos em
  Claude Vision, timeout de 8min estourado no planejamento textual, e
  nenhum `plano_edicao.json` gerado ao final
- Correção: `scripts/detector_cenas.py` reescrito para usar
  `AdaptiveDetector` do PySceneDetect (biblioteca `scenedetect`, ver
  `requirements.txt`) — usa média móvel de diferença de conteúdo no
  espaço de cor HSL, absorvendo movimento de câmera contínuo como parte
  da mesma cena em vez de corte novo. Instalação testada numa venv
  Windows real sem nenhum conflito de DLL com faster-whisper/cuBLAS/cuDNN
- Quatro safeguards de custo adicionados em `scripts/5_planejar_edicao.py`
  pra nunca mais deixar um cenário anômalo gastar sem controle: (1)
  checkpoint de cenas já classificadas visualmente
  (`plano_temp/cenas_classificadas.json`, expira em 24h) evita pagar
  Vision de novo numa retentativa; (2) timeout da chamada de planejamento
  textual agora é adaptativo (300s + 3s/cena, piso 10min, teto 45min) em
  vez de fixo em 8min; (3) aviso de custo estimado antes de rodar Vision,
  com pausa de 5s pra permitir abortar (Ctrl+C) se a estimativa passar de
  $1.00; (4) limite duro de 500 cenas detectadas (`erros.MuitasCenasError`)
  como última linha de defesa
- Impacto: sem essas proteções, uma detecção anômala (vídeo corrompido,
  threshold inadequado) podia gastar dezenas de dólares em Vision sem
  produzir nenhum resultado utilizável, e uma retentativa após falha
  pagava o custo de Vision inteiro de novo

## [Sessão 8.3 — 30/08/2026] Pausas secas entre chunks concatenados de TTS

- Status: em correção nesta sessão
- Contexto: `scripts/tts/google.py:_concatenar_audios_ffmpeg` usava
  ffmpeg concat direto pra colar chunks MP3 gerados pela síntese TTS.
  Transições ficavam "secas" (corte reto), audíveis em produção real.
  Feedback do usuário no teste de Lily & Jack (5 chunks): "As pausas
  entre parágrafos ficaram meio secas, deu pra perceber."
- Correção: `filter_complex` com fade out 150ms + silêncio 500ms +
  fade in 150ms entre chunks. Simula pausa respiratória natural.
  Chunk único preserva comportamento anterior (sem filter_complex).
  Constantes FADE_OUT_S, SILENCIO_ENTRE_CHUNKS_S, FADE_IN_S no topo
  do módulo pra ajuste fino sem tocar lógica

## [Sessão 8.2 — 30/08/2026] cuBLAS/cuDNN não registrados no faster-whisper da Etapa 4

- Status: corrigido
- Contexto: `scripts/4_obter_audio.py` chama faster-whisper pra gerar
  alinhamento por palavra do áudio TTS (Google não retorna alinhamento
  nativo). Erro em teste real: "Library cublas64_12.dll is not found
  or cannot be loaded". Bug conhecido — Sessão 4 tinha resolvido em
  `2_transcrever.py` mas lógica não foi replicada em `4_obter_audio.py`
- Correção: extraiu lógica de registro de DLLs cuBLAS/cuDNN pra
  módulo compartilhado `scripts/whisper_setup.py`. Importado em
  `2_transcrever.py` e `4_obter_audio.py` antes de qualquer import
  de faster_whisper. Evita duplicação de código e prepara pra Sessão
  10 (curadoria semântica) que também usará faster-whisper

## [Sessão 8.1 — 30/08/2026] Chunking do Google TTS media caracteres em vez de bytes

- Status: corrigido
- Contexto: `scripts/tts/google.py:_dividir_em_chunks` usava `len(texto)`
  (número de caracteres) pra validar limite de 5000 do Google TTS.
  Google mede em BYTES UTF-8. Roteiros em inglês têm caracteres
  multibyte (em-dashes `—` = 3 bytes, aspas curvas = 3 bytes,
  reticências = 3 bytes). Chunks legalmente do tamanho em chars
  ultrapassavam limite em bytes, API retornava HTTP 400 "Bad Request"
- Confirmação empírica via script debug: chunk de 4997 chars = 5009
  bytes, 9 bytes acima do limite
- Correção: constante renomeada pra `LIMITE_BYTES_POR_CHAMADA = 4800`
  (margem de segurança 200 bytes). Chunking usa
  `len(texto.encode('utf-8'))`. Salvaguarda `_sub_dividir_por_palavras`
  pra frases individuais > limite (edge case não observado mas coberto)
- Mensagem de erro em `4_obter_audio.py` também melhorada — "Erro
  inesperado na geração de alinhamento" mascarava que a falha era na
  síntese TTS, não no alinhamento

## [Sessão 8 — 29/08/2026] Etapa 4 (obtenção de áudio) implementada

- Status: entregue com sucesso (646 testes verdes, +88 novos)
- Escopo: arquitetura pluggable de provedores TTS (base.py, erros.py,
  __init__.py com get_provedor), Google TTS via REST API (tier Wavenet
  forçado por segurança de custo, chunking automático, cálculo de
  custo por request), stubs de ElevenLabs/OpenAI/Azure pra facilitar
  implementação futura, catálogo curado de vozes
  (`scripts/tts/vozes_catalogo.json` com 30 vozes em 5 idiomas +
  descrições humanas + recomendações por perfil), script principal
  `4_obter_audio.py` suportando fluxo TTS e fluxo upload, integração
  com faster-whisper pra gerar alinhamento forçado quando provedor
  não retorna nativo, endpoint `/api/vozes/<provedor>/<idioma>`,
  dropdown dinâmico de voz na tela de revisão com badge
  "★ Recomendada" por perfil, categorização de erro completa,
  documentação em .env.example e LEIAME.md
- Sem bugs pendentes na entrega original (os 3 acima foram descobertos
  em teste real e corrigidos separadamente)

## [Correção pós-Sessão 7 — 29/08/2026] Notas de rodape narradas literalmente pelo TTS + preview de roteiro nao refletia edicoes

- Status: corrigido (523 testes verdes, +20 novos)
- Causa (bug crítico): `POST /aprovar_roteiro` gravava `roteiro_aprovado.md`
  com o texto exatamente como veio do formulário, notas de rodape
  `[F1@04:32]`/`[N: ...]`/`[⚠ ...]` inclusas. A Etapa 4 (TTS) narraria essas
  notações literalmente ("F 1 arroba 04 32")
- Causa (bug secundário): o preview da tela de revisão era renderizado só
  no servidor a partir do `roteiro.md` original — clicar em "Preview" nunca
  refletia edições feitas no textarea
- Correção: `server.py:remover_notas_rodape()` (nova função) remove as 4
  categorias de nota antes de salvar `roteiro_aprovado.md`, com colapso de
  espaço fantasma deixado pela remoção (inclusive espaço solto antes de
  pontuação). `static/revisao.js` ganhou um parser de notas em JavaScript
  (`gerarPreviewHtml`/`removerNotasRodape`, espelhando a lógica Python) que
  lê o valor atual do textarea sempre que a aba "Preview" é clicada
- UX: notas agora renderizam como badges numerados sequenciais (①②③...)
  em vez da notação crua — clique em nota de fonte abre o mini-player de
  vídeo, nota externa abre a URL (ou um modal com o texto puro se não for
  URL válida), aviso mostra o texto via tooltip. Painel colapsável
  "Sobre as marcações no roteiro" explica os 3 tipos, com botão "Ignorar
  todas as notas" (view-only, persiste em sessionStorage, nunca altera o
  que é submetido além do que o próprio textarea já contém)
- Impacto: sem a correção, todo áudio gerado por TTS a partir de um
  roteiro aprovado teria as marcações de origem narradas junto com o
  texto real

## [Sessão 6.5 — 29/08/2026] Otimização de custo da Etapa 3 (parcial — não resolveu problema principal)

- Status: entregue (434 testes verdes), mas custo não reduziu como esperado
- Contexto: Sessão 6 gerou primeiro roteiro real por $1.49 (5x acima da estimativa de $0.30). Sessão 6.5 refatorou arquitetura de duas fases pra fase 2 não reenviar histórico da fase 1, baixou WEB_SEARCH_MAX de 8 pra 4, adicionou instruções de comprimento (25-35k caracteres) e uso criterioso de web_search
- Resultado do teste real pós-otimização: tokens_input 366k (praticamente inalterado vs 373k anterior), custo $1.54. Roteiro cresceu de 12k pra ~30k caracteres (bom), mas custo não caiu
- Diagnóstico: análise do código revelou que a fase 1 (pesquisa) tem loop de conversação acumulativa (linhas 547-585 de scripts/3_gerar_roteiro.py). Cada iteração reenvia toda a conversa anterior + resultados de web_search anteriores. Custo cresce quadraticamente com número de buscas. Com 4 buscas, o padrão é 10k + 25k + 45k + 65k + 85k + 85k = ~315k tokens só na fase 1 (bate com os 366k medidos)
- Causa raiz: web_search server-side retorna páginas inteiras (3-10k tokens por resultado), não só snippets. 4 buscas × ~15k tokens acumulados = 60k tokens de resultados reenviados a cada iteração seguinte
- Correção prevista: Sessão 6.6 vai implementar prompt caching + baixar WEB_SEARCH_MAX pra 2 (Correção D). Estimativa pós-6.6: $0.30-0.55 por roteiro (redução de 65-80%)
- Lição aprendida: dry-run não mede custo real quando há loops de tool use — só mostra prompt inicial. Custo cresce quadraticamente em loops de agent, não linearmente. Prompt caching é solução padrão pra esse caso de uso

## [Sessão 5b — data] Perfis completos + marca d'água + tela /sobre

- Status: entregue com sucesso (364 testes verdes, +75 novos)
- Escopo: perfis atualidades_narrativas e historia completos (sistema.md
  ~290-315 linhas cada, cobrindo proibições de sensacionalismo, cuidado
  temporal, contextualização histórica, distinção consenso/teoria marginal,
  anacronismo), fontes preferidas por idioma nos 5 idiomas, veo3_estilo.md,
  veo3_linguagem_segura.md, descricao_longa.md; marca d'água por link com
  linhas dinâmicas no formulário /novo, JS pra adicionar/remover linhas,
  persistência em entrada/marcas_dagua.json no formato flat da seção 5.7.1
  do CLAUDE.md, retrocompatibilidade com campo links antigo; tela /sobre
  renderiza os 3 perfis dinamicamente via loader.listar_perfis_detalhado()
  com conversão de descricao_longa.md via lib markdown
- Sem bugs pendentes

## [Pós-Sessão 5a — 28/08/2026] Link "Voltar aos projetos" na tela de status

- Status: implementado (289 testes verdes, +2 novos)
- Contexto: item IMPORTANTE do MELHORIAS_PENDENTES.md — tela de status não tinha botão de voltar, usuário precisava clicar em "Projetos" no menu superior
- Correção: link "← Voltar aos projetos" no topo da tela de status apontando pra home (rota /), classe CSS .link-voltar discreta com hover em cor de acento
- Impacto: navegação mais intuitiva

## [Pós-Sessão 5a — 28/08/2026] Ordenação da home por data de criação decrescente

- Status: implementado (287 testes verdes, +5 novos)
- Contexto: item NICE-TO-HAVE recém-adicionado ao MELHORIAS_PENDENTES.md — lista de projetos aparecia em ordem alfabética, confusa quando havia vários projetos
- Correção: ordenação por data de criação decrescente com cascata de fallback (job.json data_criacao → filesystem timestamp → None no fim). Suporta projetos com job.json ausente ou sem campo de data
- Impacto: projetos mais recentes aparecem primeiro na home

## [Correção pós-Sessão 5a — 28/08/2026] Bloco "Arquivos baixados" mostrava "Nenhum arquivo" mesmo com manifest presente

- Status: corrigido
- Causa: função no server.py que renderiza o bloco não estava lendo
  corretamente o manifest_fontes.json, ou não estava filtrando por
  sucesso=true, ou não formatava duração de forma amigável
- Correção: leitura correta do manifest, filtro por sucesso=true,
  formatação Xmin Ys de duração
- Impacto: projetos históricos concluídos agora exibem informação
  visual dos arquivos baixados na tela de status

## [Sessão 5a — 28/08/2026] Sistema de perfis + perfil truecrime completo + formulário com dropdown

- Status: entregue com sucesso (269 testes verdes, +21 novos)
- Escopo entregue: Loader dinâmico de prompts (scripts/prompts/loader.py
  + erros.py), perfil truecrime completo (config.py + sistema.md +
    5 blocos jurídicos por idioma + fontes preferidas + veo3 stubs +
    descrições), stubs mínimos dos perfis atualidades_narrativas e
    historia (a serem completados na 5b), formulário /novo com dropdown
    obrigatório de perfil + tooltip com descrição curta, persistência
    em entrada/perfil.txt e job.json
- Sem bugs pendentes na entrega

## [Sessão 4 — 28/08/2026] cuBLAS/cuDNN não incluídos no driver NVIDIA moderno

- Status: corrigido (adicionados como dependências pip)
- Causa: driver NVIDIA moderno inclui CUDA runtime mas não inclui
  bibliotecas cuBLAS/cuDNN necessárias pra faster-whisper.
  torch.cuda.is_available() retornava True mas transcrição falhava
  com "Library cublas64_12.dll is not found or cannot be loaded"
- Correção: adicionadas dependências nvidia-cublas-cu12 e
  nvidia-cudnn-cu12 ao requirements.txt. Script registra DLL
  folders no PATH em startup via método além de os.add_dll_directory
- Impacto: sem essa correção, usuário com driver NVIDIA compatível
  não conseguiria rodar transcrição — teria que instalar CUDA
  Toolkit separado, adicionando etapa manual de setup

## [Sessão 4 — 28/08/2026] Regex do nvidia-smi não aceitava formato "CUDA UMD Version:"

- Status: corrigido (regex aceita ambos formatos)
- Causa: drivers NVIDIA modernos reportam "CUDA UMD Version: X.Y"
  em vez do formato antigo "CUDA Version: X.Y". Regex original
  só reconhecia formato antigo
- Correção: regex atualizada pra aceitar ambos formatos
- Impacto: sem correção, GPU compatível (como RTX 3070 Ti com
  driver 610) seria erroneamente detectada como incompatível,
  bloqueando a ferramenta em máquinas onde deveria rodar

## [Sessão 4 — 28/08/2026] Campos de erro persistiam no job.json após retry bem-sucedido

- Status: corrigido
- Causa: se transcrição falhava e usuário retentava (POST
  /projetos/<id>/transcrever), sucesso posterior sobrescrevia
  status="concluido" mas mantinha campos tipo_erro e
  mensagem_usuario da tentativa anterior
- Correção: campos de erro explicitamente limpos ao registrar
  sucesso no job.json
- Impacto: tela de status mostraria projeto concluído mas com
  mensagem de erro visível, confusão pro usuário

## [Sessão 4 — 28/08/2026] Três achados de hardware real na Etapa 2 (transcrição)

- **Status:** corrigidos (248 testes verdes, +72 novos: ambiente.py,
  2_transcrever.py, integração no server.py)
- **Causa/Impacto (três bugs distintos, todos descobertos rodando o
  pipeline de ponta a ponta numa RTX 3070 Ti de verdade, não só em
  testes mockados):**
  1. `scripts/ambiente.py` parseava a versão de CUDA do `nvidia-smi`
     procurando o rótulo `CUDA Version:` — drivers recentes (confirmado
     no 610.62 desta máquina) usam `CUDA UMD Version:` em vez disso, o
     que fazia uma GPU plenamente compatível ser classificada como
     `cuda_antigo` (ambiente incompatível) por engano.
  2. `job.json` acumulava campos de erro obsoletos
     (`tipo_erro`/`mensagem_usuario`/`log_erro`) de uma tentativa
     anterior que falhou, mesmo depois de uma tentativa seguinte
     terminar com sucesso — `_persistir_job` faz merge por cima do que
     já existe em disco, então nada limpava esses campos no caminho de
     sucesso.
  3. Mesmo com driver CUDA 12+ certificado, a Etapa 2 falhava com
     `Library cublas64_12.dll is not found or cannot be loaded`: o
     driver NVIDIA não inclui as bibliotecas de runtime cuBLAS/cuDNN que
     o `ctranslate2` carrega (de forma lazy, só na primeira
     `model.transcribe(...)`) — isso vem à parte via pip, e mesmo
     instalado o pacote não bastava: a pasta `bin/` dele não estava no
     `PATH` do processo.
- **Correção:**
  1. Regex em `scripts/ambiente.py` aceita os dois rótulos
     (`CUDA(?: UMD)? Version:`).
  2. `_executar_etapa1`/`_executar_etapa2` (server.py) agora persistem
     `tipo_erro=None, mensagem_usuario=None, log_erro=None`
     explicitamente no caminho de sucesso.
  3. `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` adicionados ao
     `requirements.txt`; `scripts/2_transcrever.py` registra as pastas
     `bin/` desses pacotes no `PATH` do processo
     (`_registrar_dlls_cuda_do_venv`) antes de importar
     `faster_whisper` — `os.add_dll_directory` sozinho não bastou na
     prática (achado real, não hipotético).
- **Impacto:** sem essas correções, a Etapa 2 falharia (ou seria
  bloqueada por engano) na própria máquina de referência do produto
  (CLAUDE.md seção 13) mesmo com hardware plenamente compatível — os
  três só apareceram testando com GPU de verdade, nenhum teste mockado
  cobriria isso sozinho.

## [Sessão 3c — 28/08/2026] Tela de status não mostrava dados persistidos após reinício do server

- Status: corrigido (176 testes verdes, +9 novos)
- Causa: rota /status/<id> lia apenas estado em memória do server.
  Após reiniciar o server ou clicar em projeto antigo, tela mostrava
  "Etapa: -", "Status: sem job nesta sessao", log vazio
- Correção: job.json persistido em disco nas transições de estado
  (início, sucesso, erro) durante execução da Etapa 1. Rota
  /status/<id> lê job.json + links.txt + manifest_fontes.json sempre.
  status.js para polling ao receber 404 (sem job em memória). Tela
  reorganizada em 5 blocos (cabeçalho, estado, links, arquivos, log)
- Impacto: usuário não conseguia ver informação de projetos antigos,
  não conseguia resgatar links usados em projetos anteriores, tela
  ficava vazia após reiniciar o server no meio de uso normal

## [Sessão 3b — concluído, 28/08/2026] Mensagem de erro de link inválido é genérica

- **Status:** concluído (Sessão 3b)
- **Causa:** quando yt-dlp falha (vídeo removido, privado, geoblock,
  link malformado, erro de rede, etc), o server retorna mensagem
  única "ERRO: nenhum vídeo baixado" sem categorizar
- **Correção prevista:** função `classificar_erro_ytdlp(stderr)` no
  scripts/1_baixar_videos.py que analisa stderr e retorna
  (categoria, mensagem_amigavel) cobrindo 8 categorias (video_removido,
  video_privado, geobloqueio, restricao_idade, membership_only,
  link_malformado, erro_rede, erro_autenticacao, erro_desconhecido).
  Novos campos `tipo_erro` e `mensagem_usuario` no manifest.
  Tela /status/<id> mostra mensagem amigável em vez de log técnico
- **Impacto:** usuário não sabia por que o download falhava e tinha
  que abrir o log técnico pra entender

## [Sessão 3b — concluído, 28/08/2026] Mensagem de erro de validação de nome é sutil demais

- **Status:** concluído (Sessão 3b)
- **Causa:** validação de nome de projeto (ASCII sem espaço/acento)
  aparece em linha discreta no topo do formulário, passa despercebida
- **Correção prevista:** banner vermelho destacado com ícone ⚠, fundo
  vermelho escuro compatível com tema dark, padding generoso,
  permanece até correção. Padrão aplicável a qualquer erro de
  validação futuro
- **Impacto:** usuário digitava nome inválido, formulário rejeitava
  silenciosamente e ele não percebia que precisava corrigir

## [Sessão 3b — concluído, 28/08/2026] Menu superior (header) não é fixo ao rolar

- **Status:** concluído (Sessão 3b)
- **Causa:** header sem `position: sticky` no CSS. Some quando
  conteúdo ultrapassa altura da viewport
- **Correção prevista:** adicionar `position: sticky; top: 0;
  z-index: 100` no header do static/style.css
- **Impacto:** usuário perdia acesso aos links Projetos/Ajustes/Sobre
  ao rolar, precisava rolar de volta ao topo

## [Sessão 3b — concluído, 28/08/2026] Barra de progresso chega a 100% antes do download terminar

- **Status:** concluído (Sessão 3b)
- **Causa:** scripts/1_baixar_videos.py emite pct=100 ao terminar cada
  stream individual (áudio ou vídeo) do yt-dlp, antes do merge do
  ffmpeg e da movimentação do arquivo final acontecer
- **Correção prevista:** pct=100 só emitido quando: streams baixados +
  merge feito + arquivo final movido + manifest atualizado. Durante
  pós-processamento, emitir pct entre 90-99 com detalhe apropriado
  ("Processando arquivo final...", "Combinando vídeo e áudio...").
  Teste valida sequência monotônica crescente
- **Impacto:** usuário via barra completa e pensava que terminou,
  mas na verdade ainda estava processando

## [Ambiente / manual, 28/08/2026] ModuleNotFoundError: No module named 'dotenv' após renomear pasta

- **Status:** corrigido manualmente (recriação de venv). Sub-bug do
  produto ainda pendente — ver `iniciar.bat sem detecção de venv
  quebrado` em MELHORIAS_PENDENTES.md (IMPORTANTE)
- **Causa:** usuário renomeou pasta de "Automação Vídeos Youtube" pra
  "YoutubeVideosAutomation". Venv guarda caminhos absolutos do Python
  dentro dos scripts internos, então após mover a pasta ele fica
  quebrado — iniciar.bat tentou ativar mas caiu no Python global do
  sistema (sem dotenv)
- **Correção manual:** `Remove-Item -Recurse -Force venv`, depois
  `py -3.11 -m venv venv` e `pip install -r requirements.txt` na pasta
  nova
- **Correção pendente do produto:** iniciar.bat deve detectar venv
  ausente ou quebrado (verificar se venv/Scripts/python.exe existe E
  é executável) e avisar claramente ou recriar automaticamente
- **Impacto:** produto crasha silenciosamente em qualquer cenário
  onde venv está ausente/quebrado (primeira instalação, pasta movida,
  venv corrompido). Erro atual não é auto-explicativo

## [Sessão 3 — 28/08/2026] Integração da Etapa 1 no server.py

- **Status:** entregue com sucesso (147 testes verdes, 15 novos)
- **Sem bugs a registrar na entrega em si.** Bugs de UX descobertos no
  teste manual estão listados nas entradas de "Sessão 3b" acima

## [Sessão 2c — 27/08/2026] Winget instala pacotes portable sem ajustar PATH

- **Status:** corrigido (fallback cascata implementado, 132 testes)
- **Causa:** ao executar `winget install ffmpeg`, o pacote padrão do
  Gyan.FFmpeg é portable e não adiciona o executável ao PATH do
  sistema. Winget reporta sucesso mas `ffmpeg -version` continua
  falhando
- **Correção:** cascata de instalação winget → chocolatey (com UAC)
  → documentação de fallback manual. Após winget install de pacote
  portable, buscar executável no LOCALAPPDATA e adicionar ao PATH
  manualmente. Todos os cenários mockados (8 branches novos)
- **Impacto:** primeira tentativa de --instalar-deps parecia funcionar
  mas o produto continuava dando erro de ffmpeg ausente

## [Sessão 2c — 27/08/2026] Instalação real de ffmpeg via winget durante teste

- **Status:** corrigido (todos os testes agora 100% mockados)
- **Causa:** teste da Sessão 2b simulava "winget ausente" filtrando
  PATH, mas na prática invocou o winget real do sistema — instalou
  ffmpeg 9.0.1 de verdade e tentou iniciar server.py. Efeito
  colateral: ffmpeg 9.0.1 registrado como instalado mas fora do PATH
- **Correção:** subprocess do teste killado no meio, teste reescrito
  pra ser 100% estático (sem invocar binários reais). Usuário
  instalou ffmpeg manualmente via `choco install ffmpeg -y` pra sair
  do estado híbrido
- **Impacto:** teste modificou estado real da máquina do usuário

## [Sessão 2b — 27/08/2026] UTF-8 BOM em links.txt quebra parsing

- **Status:** corrigido (utf-8-sig, 118 testes)
- **Causa:** Bloco de Notas do Windows salva arquivos .txt com BOM
  (Byte Order Mark) por padrão. Ao abrir com `encoding="utf-8"`, a
  primeira linha do links.txt vinha com `\ufeff` no começo, quebrando
  a validação de URL do primeiro link
- **Correção:** trocar `encoding="utf-8"` por `encoding="utf-8-sig"`
  na leitura de links.txt. `utf-8-sig` reconhece e remove o BOM
  automaticamente
- **Impacto:** primeiro link sempre falhava se o usuário criou
  links.txt no Bloco de Notas do Windows

## [Sessão 2 — 27/08/2026] 4 bugs iniciais na Etapa 1 (download)

- **Status:** corrigidos (Sessão 2b, 47 testes novos)
- **Causa:** implementação inicial de scripts/1_baixar_videos.py
  tinha 4 problemas de robustez identificados no primeiro teste real:
  captura de stderr insuficiente, validação de entrada frouxa,
  validação de cascata ausente, reporte de sucesso/falha inconsistente
- **Correção:** infraestrutura completa da Seção 18 do CLAUDE.md
  aplicada — stderr capturado com últimas 15 linhas, validação de
  input com mensagens claras, validação de cascata (arquivo existe,
  é executável, versão mínima), reporte honesto de status. Novo
  scripts/robustez.py criado
- **Impacto:** download falhava em silêncio sem informação suficiente
  pra debug, ou reportava sucesso quando na verdade tinha falhado

---

## Registrados no MELHORIAS_PENDENTES.md (não são bugs, mas vinculados)

Estes são itens de melhoria/robustez que estão no backlog mas ainda
não implementados. Contexto completo lá.

- **Fluxo de instalação do ffmpeg testado só via mocks** (IMPORTANTE)
  — ver Sessão 2c acima. Primeira execução real de `--instalar-deps`
  em máquina sem ffmpeg pode expor bugs que os mocks não pegaram
- **Botão "voltar" na tela de detalhe de projeto** (IMPORTANTE) — não
  é bug, é gap de UX. Usuário precisa clicar em "Projetos" no menu
  pra voltar à lista
- **iniciar.bat sem detecção de venv quebrado** (IMPORTANTE) — ver
  entrada "ModuleNotFoundError" acima. Bug real do produto, corrigido
  só manualmente pelo usuário
