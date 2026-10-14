# Chaves de API

Uma chave é **obrigatória** (Anthropic). O resto é opcional — configure
só o que pretende usar.

## Anthropic (obrigatória)

Cada pessoa do grupo precisa da própria chave — **não é compartilhada**.

### Como conseguir

1. Acesse [console.anthropic.com](https://console.anthropic.com/)
2. Crie conta ou faça login
3. Vá em **Settings → API Keys**
4. Clique **Create Key**
5. Copie a chave (começa com `sk-ant-`)

[SCREENSHOT: console Anthropic com o botão "Create Key" em destaque]

### Configurar

Em `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Ou pela tela de Ajustes, seção "Anthropic".

### Custo

Usada na geração do roteiro (Etapa 3), se você ativar a sincronização
de clipes por IA, e na geração de thumbnail (Etapa 7 — metadados de
título/descrição/tags e, se identificar um rosto candidato,
identificação do sujeito por Vision). Ver [CUSTOS.md](CUSTOS.md) pro
detalhamento — na prática, algumas reais por roteiro, mais
~US$0,05-0,10 por vídeo na Etapa 7.

**Sem a chave configurada, a Etapa 7 não falha** — ela só pula a
geração automática de metadados/identificação de rosto e o projeto
pausa em `aguardando_thumbnail` com o vídeo final já pronto, esperando
você escolher a thumbnail manualmente.

## Google Cloud Text-to-Speech (opcional)

Provedor de narração padrão e mais testado. Sem essa chave (nem
DarkPlanner), a única forma de gerar vídeo é fornecendo seu próprio
áudio.

### Como conseguir

1. Acesse [console.cloud.google.com](https://console.cloud.google.com/)
2. Crie um projeto novo (ou use um existente)
3. Ative a API **"Cloud Text-to-Speech API"**
4. Vá em **APIs & Services → Credentials**, crie uma **API Key**
5. Restrinja a chave pra API Text-to-Speech (recomendado, não obrigatório)

[SCREENSHOT: console Google Cloud com a API Key criada]

### Configurar

```
GOOGLE_TTS_API_KEY=AIza...
```

### Custo

O Broll Foundry usa só o tier **Wavenet** ($4 por 1 milhão de
caracteres — nunca os tiers mais caros Neural2/Chirp3-HD/Studio, é
proteção de custo fixa no código). Um roteiro de ~25 mil caracteres
(vídeo de 15-20 min) custa em torno de **US$0,10**.

**Recomendado:** configure um orçamento com alerta em "Faturamento" →
"Orçamentos e alertas" no Console do Google Cloud, pra não ter surpresa
se algo sair muito maior que o esperado.

## DarkPlanner (opcional, chave COMPARTILHADA do grupo)

Serviço de terceiro (app.darkplanner.com.br) que dá acesso a vozes
ElevenLabs através de um plano PRO/Plus já pago. Não é "cole qualquer
chave" — é uma conta paga real, e a chave que o grupo usa é **uma só,
compartilhada**.

### ⚠️ Regras da chave compartilhada

- **Nunca** compartilhe essa chave fora do grupo.
- **Nunca** commite `.env` no git (o `.gitignore` já bloqueia, mas
  redobre o cuidado).
- Se desconfiar que a chave vazou, avise o Daniel **imediatamente**.

### Como conseguir

Peça diretamente ao Daniel, pelo canal privado de sempre.

### Configurar

```
DARKPLANNER_API_KEY=dpk_...
```

### Custo

Não gera custo adicional por vídeo — está incluído no plano já
assinado. Uso consciente mesmo assim (é um recurso do grupo todo).

## ElevenLabs / OpenAI / Azure TTS — ⚠️ ainda NÃO funcionam nesta versão

O formulário de revisão de roteiro **mostra** essas três opções como
provedor de TTS, e elas ficam **habilitadas assim que você preenche a
chave correspondente** — mas a chamada de API real ainda não foi
implementada por trás. Se você configurar uma dessas chaves e escolher
o provedor, a geração de áudio falha com um erro explicando que o
provedor ainda não está disponível — nenhum crédito é gasto, mas você
perde o tempo do teste.

**Recomendação: não preencha essas três chaves por enquanto.** Use
Google TTS ou DarkPlanner, ou forneça seu próprio áudio. Essas três
variáveis existem no `.env.example` só como preparação pra quando forem
implementadas de verdade.

## YouTube Data API v3 (opcional)

Usada só pra buscar títulos de referência de vídeos populares durante a
geração do roteiro — não é necessária pro download dos vídeos-fonte em
si (isso usa `yt-dlp`, sem chave nenhuma).

Sem essa chave, essa busca de referência simplesmente desliga sozinha —
o roteiro continua sendo gerado normalmente.

### Configurar

```
YOUTUBE_API_KEY=...
```

Grátis, 10.000 unidades/dia (uma busca custa 100 unidades — dá pra
rodar bastante projeto por dia sem chegar perto do limite).
