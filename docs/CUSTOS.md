# Estimativas de custo

Valores aproximados por vídeo de ~25 minutos de narração. Todos em
dólar (US$), com a conversão pra real (R$) que aparece na interface
usando a cotação configurada em Ajustes (`COTACAO_USD_BRL`, padrão
5,20).

## Etapas gratuitas

Download (Etapa 1), transcrição (Etapa 2) e geração de clipes (Etapa 5)
rodam **100% local** — sem chamada de API paga. Só pagam quem tem
custo: roteiro (Etapa 3), narração (Etapa 4) e, se ativada,
sincronização de clipes por IA.

## Roteiro (Claude + busca web)

Controlado por `WEB_SEARCH_MAX` (Ajustes → Anthropic), que limita
quantas buscas web o modelo pode fazer por roteiro.

| `WEB_SEARCH_MAX` | Custo aproximado |
|---|---|
| 5 (padrão) | ~R$5-6 por roteiro |
| 2 (mínimo econômico) | ~R$3-4 por roteiro |

Aumente se os roteiros saírem desatualizados em relação a
desenvolvimentos recentes de um caso. Reduza pra temas evergreen
(história antiga, por exemplo), onde frescor de informação importa
pouco.

O custo real de cada roteiro aparece no cabeçalho da tela de revisão.

## Narração (TTS)

| Provedor | Custo por vídeo (~25k caracteres) |
|---|---|
| Google TTS (Wavenet) | ~US$0,10 (~R$0,52) |
| DarkPlanner | R$0 marginal — incluso no plano já pago do grupo |
| Áudio próprio (upload) | R$0 |
| ElevenLabs / OpenAI / Azure | não disponíveis nesta versão — ver [CHAVES_API.md](CHAVES_API.md) |

## Sincronização de clipes por IA (opcional)

Ativada nos "Ajustes avançados" da criação do projeto. Cobra conforme
quanto do vídeo você manda sincronizar:

| Trecho sincronizado | Custo aproximado |
|---|---|
| Primeiros 5 min | ~US$0,05 |
| Primeiros 10 min (padrão) | ~US$0,10 |
| Primeiros 15 min | ~US$0,15 |
| Vídeo inteiro | ~US$0,20+ |

O custo real de cada execução fica registrado em `logs/` na pasta do
projeto.

## Reorganização manual de clipes

Gratuita — não chama API nenhuma, só ffmpeg local pra gerar as
miniaturas e a prévia.

## Thumbnail (Etapa 7)

Duas chamadas opcionais e independentes — nenhuma delas bloqueia a
etapa se `ANTHROPIC_API_KEY` não estiver configurada:

| Chamada | Custo aproximado |
|---|---|
| Metadados (título/descrição/tags/briefing) | ~US$0,03-0,05 |
| Identificação do sujeito por Vision (só roda se achar candidato com rosto) | ~US$0,03-0,05 |

Total típico: **~US$0,05-0,10 por vídeo** (~R$0,25-0,50).

## YouTube Data API

Grátis, sempre (10.000 unidades/dia, uma busca de referência custa 100).

## Total típico por vídeo

Com `WEB_SEARCH_MAX=5` (padrão), Google TTS e sem sincronização por IA:

**~R$5,50-6,50 por vídeo de 25 minutos.**

Com DarkPlanner no lugar do Google TTS, o custo de narração cai a zero
(fica só o custo do roteiro). Com áudio próprio (upload), o vídeo
inteiro sai só com o custo do roteiro. Ativando sincronização por IA no
vídeo inteiro, soma até +US$0,20 (~R$1,00) no total.

## Estimativa mensal (1 vídeo/dia)

- Anthropic (roteiro): ~R$150-180/mês
- Google TTS: ~R$15/mês (ou R$0 usando DarkPlanner/áudio próprio)
- YouTube API: R$0
- **Total: ~R$150-200/mês**, variando conforme configuração escolhida.
