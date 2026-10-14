"""Etapa 3 do pipeline (CLAUDE.md secao 5.3) - gera o roteiro do video via
API de Mensagens da Anthropic, usando o sistema de perfis de conteudo
(CLAUDE.md secao 3.1) e busca web para checagem factual.

Uso: python "scripts/3_gerar_roteiro.py" <caminho_da_pasta_do_projeto>

Saida:
- roteiro.md - texto do roteiro em markdown, com notas de rodape de
  origem (CLAUDE.md secao 5.4).
- titulos_sugeridos.json - {"titulos": [...3...], "descricoes": [...3...]}.
- job_metadata.json - metadados da geracao (perfil, idioma, custo
  estimado, tempo, etc - CLAUDE.md secao 5.3).

Fluxo de chamada a API, em duas fases (otimizado na sessao de reducao de
custo pos-Sessao 6 - ver nota abaixo sobre o motivo):

1. Pesquisa: `messages.create` com a tool server-side `web_search` (o
   Google/Anthropic resolve as buscas automaticamente dentro da mesma
   resposta) e, se `YOUTUBE_API_KEY` estiver configurada, a tool
   client-side `youtube_top_titles` (scripts/tools/youtube.py) - essa
   precisa de um loop manual: o modelo emite um bloco `tool_use`, este
   script executa a busca de verdade e devolve o resultado como
   `tool_result` na proxima chamada, ate o modelo parar de pedir tools.
   Ao final do loop, uma chamada extra com `tool_choice` forcado na tool
   `entregar_resumo_pesquisa` extrai um RESUMO ESTRUTURADO (fatos,
   cronologia, pessoas envolvidas, conflitos entre fontes) dos achados -
   nao o roteiro final.
2. Geracao do roteiro: uma conversa NOVA (sem o historico da fase 1),
   contendo so o prompt de sistema, o resumo estruturado da fase 1 e as
   transcricoes (necessarias para os timestamps das notas de rodape), com
   `tool_choice` forcado na tool `entregar_roteiro` (schema fixo abaixo).

Motivo de nao reenviar o historico da fase 1 na fase 2: o historico de
pesquisa acumula os resultados brutos de `web_search` (paginas inteiras
de resultado) a cada rodada do loop - reenviar isso inteiro numa segunda
chamada inflava o input em 10x do esperado num teste real (~373k tokens
de input pra um roteiro de ~12k caracteres). O resumo estruturado
carrega so o que a fase 2 realmente precisa.

Prompt caching (sessao de otimizacao de custo pos-Sessao 6.5, revisada na
Sessao 6.7 apos teste real mostrar cache_hit_rate de so 0.2182 quando o
esperado era 0.60-0.75 - ver "GOTCHA de cache invalidado por `tools`"
abaixo): mesmo isolando a fase 2, a fase 1 sozinha ainda reenvia a
conversa acumulada inteira a cada rodada do loop de pesquisa (custo
quadratico no numero de rodadas). `_montar_system_blocks` marca o prompt
de sistema (identico em toda chamada desta etapa) com `cache_control`, o
prompt de usuario inicial da fase 1 (`mensagens_fase1[0]`) tambem chega
marcado, e `_executar_fase_pesquisa` mantem uma janela deslizante de
cache_control nos 2 tool_result mais recentes de cada rodada - a API
aceita no maximo 4 breakpoints de cache por chamada, entao o teto e'
sistema + usuario inicial + 2 tool_results. `_contar_tokens` reporta as 4
categorias de token (input nao cacheado, output, cache criado, cache
lido) separadas, e o custo de cada uma e' calculado com o multiplicador
certo (ver MULTIPLICADOR_CACHE_WRITE/MULTIPLICADOR_CACHE_READ) - cache
lido custa 90% menos que input normal.

GOTCHA de cache invalidado por `tools` (diagnostico da Sessao 6.7): a API
da Anthropic computa o prefixo cacheavel na ordem `tools` -> `system` ->
`messages`. Isso significa que QUALQUER cache_control marcado no bloco de
`system` so' produz cache HIT se o array `tools` da chamada atual for
BYTE A BYTE IDENTICO ao de uma chamada anterior recente (mesmo que o
texto do `system` em si seja identico) - mudar a lista de tools, mesmo so'
adicionando/removendo um item, invalida qualquer cache anterior que
dependa do `system` vir depois dele. Antes desta revisao, o loop de
pesquisa usava `tools_pesquisa` (web_search [+ youtube_top_titles]), a
chamada forcada de resumo usava so' `[SCHEMA_RESUMO]`, e a chamada final
da fase 2 usava so' `[SCHEMA_SAIDA]` - 3 listas de tools DIFERENTES, o que
fazia o cache do prompt de sistema (~7-8k tokens) ser reescrito do zero
em cada uma das 3 chamadas, nunca lido. A correcao: a chamada de resumo e
a chamada final da fase 2 agora compartilham a MESMA lista de tools
(`TOOLS_FASE_ESTRUTURADA`, definida abaixo, com tool_choice forcando qual
delas executa em cada caso) - como essas duas chamadas sempre rodam em
sequencia ao final de toda geracao bem-sucedida, isso garante um cache
HIT do prompt de sistema na chamada final. O loop de pesquisa continua
com `tools_pesquisa` PROPOSITALMENTE sem unificar com
`TOOLS_FASE_ESTRUTURADA`: expor `entregar_resumo_pesquisa`/
`entregar_roteiro` como tools disponiveis durante o loop (que roda com
`tool_choice="auto"`, nao forcado) arriscaria o modelo chama-las cedo
demais no meio da pesquisa, quebrando o fluxo de duas fases (CLAUDE.md
secao 5.3) - risco pior que o cache perdido nessa transicao especifica, e
nao verificavel sem chamada real a API (fora do escopo desta sessao).

Este script e' autocontido (CLAUDE.md secao 9) - exceto por
scripts/prompts/loader.py e scripts/tools/youtube.py, infra transversal
ja estabelecida por sessoes anteriores (nao logica de pipeline
duplicavel por script).

Modo DRY_RUN_API (calibracao de prompt sem custo de API): se a env var
DRY_RUN_API estiver como "true", o script monta o prompt de sistema e
de usuario normalmente, mas NAO chama a API da Anthropic - em vez
disso grava o prompt final montado em dry_run_output.md na pasta do
projeto (com metadados: perfil, idioma, modelo que seria chamado,
tokens estimados e custo estimado) e marca job.json com
status="dry_run_concluido". Default (ausente ou "false"):
comportamento normal, chama a API de verdade.
"""

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# scripts/3_gerar_roteiro.py precisa da RAIZ do projeto no sys.path (nao so
# scripts/) porque scripts/prompts/loader.py e scripts/tools/youtube.py sao
# importados via caminho absoluto de pacote (`scripts.prompts...`,
# `scripts.tools...`) - mesma convencao que server.py ja usa. Quando este
# script roda standalone (`python scripts/3_gerar_roteiro.py <pasta>`), a
# raiz nao entra no sys.path sozinha; quando carregado via importlib nos
# testes, a raiz ja esta' no sys.path por causa de tests/conftest.py, mas o
# insert aqui e' inofensivo (sys.path aceita duplicatas sem efeito colateral).
_RAIZ_PROJETO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ_PROJETO))

from scripts.prompts import loader as prompts_loader  # noqa: E402
from scripts.prompts.erros import PromptErro  # noqa: E402
from scripts.tools import youtube as youtube_tool  # noqa: E402

try:
    import anthropic
except ImportError:
    anthropic = None

MODELO_PADRAO = "claude-sonnet-5"
IDIOMA_PADRAO = "en-US"
# Elevado de 2 para 5 na Sessao 22: 2 buscas se mostraram insuficientes em
# teste real (roteiro gerado nao refletiu desenvolvimento recente de um
# caso, porque as poucas buscas disponiveis foram gastas em outros pontos).
# O prompt caching (ver _executar_fase_pesquisa) ja derruba o custo do
# historico acumulado da fase 1, entao o custo marginal das buscas extras
# (~$0.10-0.15/roteiro) compensa o ganho de frescor de dados.
WEB_SEARCH_MAX_PADRAO = 5

# Elevado de 8192 pos-Sessao de correcoes UX: 8192 tokens de output (~30-33k
# caracteres depois do overhead de escaping JSON do tool_choice estruturado)
# e' insuficiente pro alvo de 25-35k caracteres de roteiro (secao
# "Comprimento do roteiro" de cada perfil) somado aos titulos/descricoes no
# mesmo payload - teste empirico real mostrou roteiro cortado abaixo do
# minimo aceitavel. Usado tambem nas chamadas de pesquisa/resumo da fase 1
# (que nunca precisam de perto disso) so' por simplicidade de ter uma
# constante unica - nao aumenta custo real, so' o teto.
MAX_TOKENS_RESPOSTA = 16000

# Config duro (mesmo espirito do timeout de 60min da Etapa 2, CLAUDE.md
# secao 5.2) - nao editavel via .env de proposito.
TIMEOUT_TOTAL_S = 15 * 60

# Teto defensivo de rodadas do loop de pesquisa (fase 1) - nunca deveria
# chegar perto disso na pratica (o modelo para de pedir tools quando tem
# informacao suficiente), mas evita loop infinito se o modelo ficar
# pedindo a mesma tool repetidamente.
MAX_ITERACOES_FERRAMENTAS = 10

NOME_TOOL_SAIDA = "entregar_roteiro"

SCHEMA_SAIDA = {
    "name": NOME_TOOL_SAIDA,
    "description": (
        "Entrega o resultado final da geracao de roteiro: o roteiro "
        "completo em markdown (com notas de rodape de origem), 3 titulos "
        "sugeridos e 3 descricoes sugeridas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pergunta_promessa": {
                "type": "string",
                "description": (
                    "A pergunta central que o roteiro inteiro existe para "
                    "responder (Regra 0 do prompt de sistema) - formulada "
                    "como pergunta especifica deste caso/evento/tema, nunca "
                    "generica. E' o que organiza o hook, o corte de "
                    "material e os titulos sugeridos."
                ),
            },
            "roteiro_md": {
                "type": "string",
                "description": (
                    "Roteiro completo em markdown, pronto para narracao, "
                    "com as notas de rodape de origem inline (formato "
                    "[F1@04:32], [N: url], [warning single-source], "
                    "[warning conflict] conforme as regras do prompt de sistema)."
                ),
            },
            "nucleo_editorial": {
                "type": "string",
                "description": (
                    "Nucleo compacto (2 a 8 palavras) do qual os 3 titulos "
                    "devem derivar - a essencia da pergunta_promessa em "
                    "forma curta o suficiente para orientar um titulo (ex: "
                    "'mistakes that identify him'). Gerado junto da "
                    "pergunta_promessa, nao a substitui - a pergunta_promessa "
                    "continua podendo ser longa/matizada, o nucleo_editorial "
                    "e' o resumo dela em poucas palavras."
                ),
            },
            "titulos": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Exatamente 3 titulos: factual, emocional, pergunta.",
            },
            "descricoes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Exatamente 3 descricoes curtas (2-4 frases) para o YouTube.",
            },
            "justificativa_tamanho": {
                "type": "string",
                "description": (
                    "Preencher APENAS se roteiro_md ficou abaixo do minimo de "
                    "caracteres exigido pelo bloco de tamanho do projeto: "
                    "explique o que faltou no material verificado (fontes/"
                    "transcricoes insuficientes) para justificar o roteiro "
                    "mais curto. Nunca usar para justificar repeticao, "
                    "especulacao ou reformulacao usadas para inflar tamanho - "
                    "essas nunca sao aceitaveis. Omitir se o minimo foi "
                    "atingido normalmente."
                ),
            },
        },
        "required": ["pergunta_promessa", "roteiro_md", "titulos", "descricoes", "nucleo_editorial"],
    },
}

NOME_TOOL_RESUMO = "entregar_resumo_pesquisa"

SCHEMA_RESUMO = {
    "name": NOME_TOOL_RESUMO,
    "description": (
        "Entrega o resumo estruturado dos achados da fase de pesquisa "
        "(fatos verificados, cronologia, pessoas envolvidas, conflitos "
        "entre fontes, titulos populares no YouTube sobre o caso e "
        "observacoes editoriais). Este resumo - e nao o historico bruto de "
        "pesquisa - e' o que sera usado para escrever o roteiro final numa "
        "etapa seguinte, entao deve conter tudo que for essencial."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fatos_verificados": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fato": {"type": "string"},
                        "fonte": {"type": "string"},
                        "confianca": {"type": "string"},
                    },
                    "required": ["fato", "fonte"],
                },
            },
            "cronologia": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string"},
                        "evento": {"type": "string"},
                    },
                    "required": ["evento"],
                },
            },
            "pessoas_envolvidas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"},
                        "papel": {"type": "string"},
                        "status_legal": {"type": "string"},
                    },
                    "required": ["nome"],
                },
            },
            "conflitos_entre_fontes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tema": {"type": "string"},
                        "versao_a": {"type": "string"},
                        "versao_b": {"type": "string"},
                    },
                    "required": ["tema"],
                },
            },
            "titulos_top_youtube": {
                "type": "array",
                "items": {"type": "string"},
            },
            "observacoes_editoriais": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["fatos_verificados", "cronologia", "pessoas_envolvidas"],
    },
}

NOME_TOOL_JUSTIFICATIVA = "entregar_justificativa_tamanho"

SCHEMA_JUSTIFICATIVA = {
    "name": NOME_TOOL_JUSTIFICATIVA,
    "description": (
        "Explica por que o roteiro nao atingiu o piso de tamanho definido "
        "para este projeto, mesmo apos as tentativas de expansao "
        "(Investigacao de tamanho curto - Grupo E). Usada so' quando o "
        "roteiro final ficou abaixo do piso E o campo justificativa_tamanho "
        "de entregar_roteiro nao foi preenchido."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "justificativa": {
                "type": "string",
                "description": (
                    "O que faltou no material verificado (fontes/"
                    "transcricoes insuficientes) para sustentar o piso de "
                    "tamanho com qualidade. Nunca citar repeticao, "
                    "especulacao ou reformulacao como motivo - essas nunca "
                    "sao aceitaveis."
                ),
            },
        },
        "required": ["justificativa"],
    },
}

NOME_TOOL_NUCLEO = "entregar_nucleo_editorial"

SCHEMA_NUCLEO = {
    "name": NOME_TOOL_NUCLEO,
    "description": (
        "Entrega SOMENTE o nucleo_editorial (2 a 8 palavras) derivado da "
        "pergunta_promessa de um roteiro ja gerado - usada so' quando o "
        "roteiro original saiu sem esse campo (ou com valor invalido) e "
        "precisa de reparo pontual, sem regerar o roteiro inteiro."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nucleo_editorial": {
                "type": "string",
                "description": (
                    "Nucleo compacto (2 a 8 palavras) do qual titulos "
                    "devem derivar - a essencia da pergunta_promessa "
                    "fornecida, em forma curta o suficiente para orientar "
                    "um titulo (ex: 'mistakes that identify him')."
                ),
            },
        },
        "required": ["nucleo_editorial"],
    },
}

# Lista de tools COMPARTILHADA e ESTAVEL entre a chamada forcada de resumo
# (fim da fase 1), a chamada final da fase 2, as chamadas de expansao, a
# chamada de justificativa e a chamada de reparo de nucleo_editorial
# (Sessao 6.7 - ver "GOTCHA de cache invalidado por `tools`" no docstring
# do modulo). Todas usam `tool_choice` para forcar qual das tools executa
# em cada chamada - so' a lista de tools precisa ser identica para o cache
# do prompt de sistema poder ser lido (nao reescrito) nas chamadas
# seguintes. Ordem fixa de proposito (a ordem faz parte do prefixo
# cacheado).
TOOLS_FASE_ESTRUTURADA = [SCHEMA_RESUMO, SCHEMA_SAIDA, SCHEMA_JUSTIFICATIVA, SCHEMA_NUCLEO]

# Precos aproximados (CLAUDE.md secao 11 - "Web search $10/1000 buscas +
# tokens"). Estimativa informativa, nao cobranca exata - a Anthropic pode
# mudar precos sem aviso.
CUSTO_INPUT_POR_MILHAO_USD = 3.0
CUSTO_OUTPUT_POR_MILHAO_USD = 15.0
CUSTO_WEB_SEARCH_POR_BUSCA_USD = 0.01
# Multiplicadores de prompt caching sobre CUSTO_INPUT_POR_MILHAO_USD
# (docs.anthropic.com/en/docs/build-with-claude/prompt-caching): escrever
# no cache custa 25% a mais que input normal (o cache dura 5 minutos, o
# que cobre folgadamente as poucas dezenas de segundos entre rodadas do
# loop de pesquisa desta etapa); ler do cache custa 90% menos.
MULTIPLICADOR_CACHE_WRITE = 1.25
MULTIPLICADOR_CACHE_READ = 0.10

_MENSAGENS_ERRO_API = {
    "chave_invalida": "Chave da API Anthropic invalida. Verifique em console.anthropic.com.",
    "credito_insuficiente": "Credito Anthropic insuficiente. Recarregue em console.anthropic.com/billing.",
    "rate_limit": "Limite de requisicoes atingido. Aguarde alguns minutos e tente novamente.",
}


def emitir_progresso(pct, detalhe, eta_s=None, **extra):
    payload = {"pct": round(pct, 1), "detalhe": detalhe}
    if eta_s is not None:
        payload["eta_s"] = eta_s
    payload.update(extra)
    print(f"@PROGRESSO {json.dumps(payload, ensure_ascii=False)}", flush=True)


def classificar_erro_api(exc: Exception) -> tuple:
    """Classifica uma excecao levantada por `client.messages.create(...)`
    numa categoria conhecida (CLAUDE.md secao 5.3), com mensagem amigavel
    pro usuario final.

    Usa `status_code` (presente em qualquer `anthropic.APIStatusError`,
    incluindo `AuthenticationError`/`RateLimitError`/etc, todas
    subclasses dela) em vez de `isinstance` por classe especifica -
    402 (credito insuficiente) nao tem subclasse propria no SDK, so
    aparece como `APIStatusError` generico com esse status_code."""
    status_code = getattr(exc, "status_code", None)
    texto = str(exc).lower()

    if status_code == 401:
        return "chave_invalida", _MENSAGENS_ERRO_API["chave_invalida"]
    if status_code == 402 or "insufficient credit" in texto or "credit balance" in texto:
        return "credito_insuficiente", _MENSAGENS_ERRO_API["credito_insuficiente"]
    if status_code == 429:
        return "rate_limit", _MENSAGENS_ERRO_API["rate_limit"]

    trecho = str(exc).strip()[:200]
    return "erro_desconhecido", f"Erro inesperado ao gerar roteiro. Detalhe tecnico: {trecho}"


def _valor(obj, chave, default=None):
    """Le `chave` de `obj` seja ele um dict (fakes de teste) ou um objeto
    com atributos (respostas reais do SDK anthropic, que sao modelos
    pydantic) - evita duas versoes de cada funcao que le campos de
    `resposta`/`bloco`/`usage`."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(chave, default)
    return getattr(obj, chave, default)


def _checar_timeout(inicio: float):
    if time.monotonic() - inicio > TIMEOUT_TOTAL_S:
        raise TimeoutError("Geracao de roteiro excedeu tempo limite (15min).")


def _contar_web_searches(resposta) -> int:
    usage = _valor(resposta, "usage")
    server_tool_use = _valor(usage, "server_tool_use")
    return _valor(server_tool_use, "web_search_requests", 0) or 0


def _contar_tokens(resposta) -> tuple:
    """Retorna (tokens_input, tokens_output, tokens_cache_criados,
    tokens_cache_lidos). `tokens_input` e' so a parcela NAO cacheada do
    input (`usage.input_tokens`) - a Anthropic reporta as parcelas de
    cache em separado (`cache_creation_input_tokens`,
    `cache_read_input_tokens`); o input total de uma chamada e' a soma
    dos tres. Respostas sem prompt caching (ou fakes de teste antigos que
    nao definem esses campos) retornam 0 nos dois ultimos - o calculo de
    custo trata isso como "sem cache" corretamente."""
    usage = _valor(resposta, "usage")
    return (
        _valor(usage, "input_tokens", 0) or 0,
        _valor(usage, "output_tokens", 0) or 0,
        _valor(usage, "cache_creation_input_tokens", 0) or 0,
        _valor(usage, "cache_read_input_tokens", 0) or 0,
    )


def _registrar_chamada_debug(chamadas_debug, nome, entrada_tok, saida_tok, cache_criado_tok, cache_lido_tok):
    """Acrescenta o detalhe de uma chamada `messages.create` a
    `chamadas_debug` (Sessao 6.7 - rastreamento aprimorado de cache, ver
    B.3) - usado para gravar debug_cache.log ao final de `gerar_roteiro`,
    pra investigacao futura de hit rate baixo sem precisar reproduzir a
    chamada real."""
    total = entrada_tok + cache_criado_tok + cache_lido_tok
    chamadas_debug.append(
        {
            "chamada": nome,
            "tokens_input_nao_cacheado": entrada_tok,
            "tokens_output": saida_tok,
            "tokens_cache_criados": cache_criado_tok,
            "tokens_cache_lidos": cache_lido_tok,
            "tokens_input_total": total,
            "cache_hit_rate": round(cache_lido_tok / total, 4) if total else 0.0,
        }
    )


def _gravar_debug_cache_log(pasta_projeto: Path, chamadas_debug: list, cache_hit_rate: float) -> None:
    """Grava logs/debug_cache.log com o detalhe de cada chamada
    `messages.create` desta geracao (Sessao 6.7, ver B.3) - facilita
    investigar hit rate baixo numa geracao especifica sem precisar
    reproduzir a chamada real a API. Nunca falha a etapa por causa deste
    log (best-effort, so' diagnostico)."""
    try:
        pasta_logs = pasta_projeto / "logs"
        pasta_logs.mkdir(exist_ok=True)
        linhas = [f"cache_hit_rate final: {cache_hit_rate}", ""]
        for chamada in chamadas_debug:
            linhas.append(
                f"{chamada['chamada']}: input_nao_cacheado={chamada['tokens_input_nao_cacheado']} "
                f"output={chamada['tokens_output']} cache_criados={chamada['tokens_cache_criados']} "
                f"cache_lidos={chamada['tokens_cache_lidos']} "
                f"hit_rate_da_chamada={chamada['cache_hit_rate']}"
            )
        (pasta_logs / "debug_cache.log").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    except OSError:
        pass


def _montar_system_blocks(prompt_sistema: str) -> list:
    """Prompt de sistema como bloco unico com cache_control (CLAUDE.md
    secao 11 - otimizacao de custo pos-Sessao 6.5): o prompt de sistema e'
    identico em toda chamada desta etapa (loop de pesquisa, chamada
    forcada que extrai o resumo, e a chamada final da fase 2), entao
    cachea-lo e' o maior ganho isolado de prompt caching disponivel aqui."""
    return [{"type": "text", "text": prompt_sistema, "cache_control": {"type": "ephemeral"}}]


def _ler_web_search_max() -> int:
    valor = os.environ.get("WEB_SEARCH_MAX")
    if not valor:
        print(
            f"[INFO] WEB_SEARCH_MAX nao configurado. Usando default {WEB_SEARCH_MAX_PADRAO}.",
            flush=True,
        )
        return WEB_SEARCH_MAX_PADRAO
    try:
        return max(1, int(valor))
    except ValueError:
        print(
            f"[INFO] WEB_SEARCH_MAX invalido ('{valor}'). Usando default {WEB_SEARCH_MAX_PADRAO}.",
            flush=True,
        )
        return WEB_SEARCH_MAX_PADRAO


# Defaults identicos aos de scripts/validators.py:PALAVRAS_ALVO_PADRAO/
# DURACAO_ALVO_MINUTOS_PADRAO - duplicado aqui de proposito (CLAUDE.md
# secao 9, script autocontido) em vez de importar server.py (que e' quem
# importa scripts/, nunca o contrario).
PALAVRAS_ALVO_PADRAO = 4000
DURACAO_ALVO_MINUTOS_PADRAO = 25
# Chars/palavra em portugues e' ~5.5-6 sem espacos; usar uma faixa (min/max)
# em vez de um numero fixo da margem pro modelo escrever com naturalidade
# sem cair no "produza mais curto" do prompt do perfil por poucos chars.
CHARS_POR_PALAVRA_MIN = 5.0
CHARS_POR_PALAVRA_MAX = 6.0

# Reestruturacao do roteiro (Problema 2 - a metrica media a coisa errada):
# ratio_tamanho passa a ser medido em PALAVRAS NARRADAS (o roteiro sem
# notas de rodape e sem marcacao markdown - o que a voz de fato le em voz
# alta), nunca em caracteres com espacos/markdown/notas. Os padroes abaixo
# sao DUPLICADOS de proposito de server.py:PADRAO_NOTA_FONTE/
# PADRAO_NOTA_EXTERNA/PADRAO_AVISO/PADRAO_FONTE_ITEM (mesma fonte da
# verdade sobre o que conta como nota, usada la' para remover_notas_rodape()
# antes de gravar roteiro_aprovado.md) - nao uma regex nova inventada aqui.
# server.py e' quem importa scripts/, nunca o contrario (CLAUDE.md secao 9 -
# cada script e' autocontido), entao a duplicacao e' a forma correta de
# reaproveitar a mesma logica sem violar essa direcao de import.
_TS_NOTA_FONTE = r"\d{1,2}:\d{2}(?::\d{2})?"
_ITEM_NOTA_FONTE = rf"F\d+@{_TS_NOTA_FONTE}(?:-{_TS_NOTA_FONTE})?"
PADRAO_NOTA_FONTE = re.compile(rf"\[{_ITEM_NOTA_FONTE}(?:\s*,\s*{_ITEM_NOTA_FONTE})*\]")
PADRAO_FONTE_ITEM = re.compile(rf"F(\d+)@({_TS_NOTA_FONTE})(?:-({_TS_NOTA_FONTE}))?")
PADRAO_NOTA_EXTERNA = re.compile(r"\[N:\s*([^\]]+)\]")
PADRAO_AVISO = re.compile(r"\[⚠\s*([^\]]*)\]")
# Marcacao markdown leve que o prompt de sistema permite (paragrafos,
# eventual subtitulo) - removida so' para a CONTAGEM de palavras narradas,
# nunca do roteiro_md persistido em disco.
PADRAO_MARKDOWN_LEVE = re.compile(r"[*_#>`]")

# Limiar de expansao (Grupo E): abaixo de 95% do alvo em palavras narradas,
# o roteiro e' considerado abaixo do piso e dispara ate MAX_EXPANSOES
# chamadas de expansao antes de aceitar o resultado como final.
EXPANSAO_LIMIAR_RATIO = 0.95
MAX_EXPANSOES = 2
# Queda de notas de rodape acima desta fracao entre uma tentativa de
# expansao e a anterior invalida a tentativa (perdeu rigor factual pra
# ganhar tamanho) - a versao anterior e' mantida.
QUEDA_NOTAS_MAX_FRACAO = 0.10


def _remover_notas_e_markdown(texto: str) -> str:
    """Roteiro sem notas de rodape de origem nem marcacao markdown leve -
    o que a voz efetivamente narra. Mesma remocao que server.py faz antes
    de gravar roteiro_aprovado.md (ver comentario acima dos padroes),
    usada aqui so' para CONTAR palavras, nunca para persistir em disco."""
    if not texto:
        return ""
    sem_notas = PADRAO_NOTA_FONTE.sub("", texto)
    sem_notas = PADRAO_NOTA_EXTERNA.sub("", sem_notas)
    sem_notas = PADRAO_AVISO.sub("", sem_notas)
    sem_notas = PADRAO_MARKDOWN_LEVE.sub("", sem_notas)
    return sem_notas


def contar_palavras_narradas(roteiro_md: str) -> int:
    """Numero de palavras que a narracao efetivamente le em voz alta -
    ignora notas de rodape e marcacao markdown (Problema 2: len() com
    espacos/markdown/notas media a coisa errada e comparava contra um piso
    definido pelo prompt como 'sem espacos')."""
    return len(_remover_notas_e_markdown(roteiro_md).split())


def _contar_notas_rodape(roteiro_md: str) -> int:
    """Numero total de notas de rodape de origem (cada fonte dentro de uma
    tag [F1@.., F2@..] conta separadamente, e cada [N: url] conta uma vez) -
    usado para detectar queda de rigor factual entre tentativas de
    expansao (Grupo E)."""
    if not roteiro_md:
        return 0
    contagem = sum(
        len(PADRAO_FONTE_ITEM.findall(m.group(0))) for m in PADRAO_NOTA_FONTE.finditer(roteiro_md)
    )
    contagem += len(PADRAO_NOTA_EXTERNA.findall(roteiro_md))
    return contagem


def _ler_configuracao_tamanho(pasta_projeto: Path) -> tuple[int, int]:
    """Le entrada/configuracao_video.json (formulario de Novo projeto -
    campos palavras_alvo/duracao_alvo_minutos) e retorna
    (palavras_alvo, duracao_alvo_minutos). Ausente/corrompido/campos
    ausentes ou invalidos cai nos defaults (CLAUDE.md secao 18.6/18.7 -
    nunca levanta excecao, nunca trava a geracao por causa de config
    opcional ausente - retrocompatibilidade total com projetos criados
    antes deste campo existir)."""
    caminho = pasta_projeto / "entrada" / "configuracao_video.json"
    if not caminho.exists():
        return PALAVRAS_ALVO_PADRAO, DURACAO_ALVO_MINUTOS_PADRAO
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PALAVRAS_ALVO_PADRAO, DURACAO_ALVO_MINUTOS_PADRAO
    if not isinstance(dados, dict):
        return PALAVRAS_ALVO_PADRAO, DURACAO_ALVO_MINUTOS_PADRAO

    try:
        palavras_alvo = int(dados.get("palavras_alvo", PALAVRAS_ALVO_PADRAO))
    except (TypeError, ValueError):
        palavras_alvo = PALAVRAS_ALVO_PADRAO
    if palavras_alvo < 1000 or palavras_alvo > 15000:
        palavras_alvo = PALAVRAS_ALVO_PADRAO

    try:
        duracao_alvo_minutos = int(dados.get("duracao_alvo_minutos", DURACAO_ALVO_MINUTOS_PADRAO))
    except (TypeError, ValueError):
        duracao_alvo_minutos = DURACAO_ALVO_MINUTOS_PADRAO
    if duracao_alvo_minutos < 5 or duracao_alvo_minutos > 120:
        duracao_alvo_minutos = DURACAO_ALVO_MINUTOS_PADRAO

    return palavras_alvo, duracao_alvo_minutos


def _montar_bloco_tamanho_alvo(palavras_alvo: int, duracao_alvo_minutos: int) -> str:
    """Monta o bloco de instrucao de tamanho especifico deste projeto,
    apendado ao prompt de sistema (loader.montar_prompt ja injeta o alvo
    generico do perfil - 25-35k caracteres - este bloco sobrescreve com o
    numero exato escolhido no formulario, CLAUDE.md - Investigacao de
    tamanho curto). Apendice, nao substituicao: fica sempre no fim do
    prompt de sistema, entao o modelo le por ultimo e pesa mais (recencia)
    sem exigir editar sistema.md de cada perfil."""
    caracteres_min = int(palavras_alvo * CHARS_POR_PALAVRA_MIN)
    caracteres_max = int(palavras_alvo * CHARS_POR_PALAVRA_MAX)
    return (
        "\n\n# TAMANHO ALVO DESTE PROJETO (sobrescreve o alvo generico "
        "acima - este e' o UNICO numero de tamanho valido neste prompt)\n\n"
        f"Este roteiro deve ter {palavras_alvo} palavras "
        f"({caracteres_min}-{caracteres_max} caracteres sem espacos), "
        f"gerando um video de {duracao_alvo_minutos} minutos narrados. "
        "Isto e' uma configuracao especifica deste projeto, escolhida "
        "pelo usuario no formulario - siga este numero, nao qualquer "
        "outro valor generico que apareca em outro ponto do prompt.\n\n"
        f"{caracteres_min} caracteres e' PISO, nao aproximacao: abaixo "
        "disso o roteiro e' considerado incompleto. Se o material das "
        "fontes/pesquisa for insuficiente para esse tamanho com "
        "qualidade e sem invencao, expanda com (sempre ancorado em "
        "fatos verificaveis, nunca especulacao):\n"
        "- Contexto historico da regiao/epoca\n"
        "- Descricao sensorial detalhada de cenas relevantes\n"
        "- Perfil aprofundado das pessoas envolvidas\n"
        "- Cronologia minuciosa dos eventos\n"
        "- Analise das evidencias disponiveis\n"
        "- Impacto social, familiar e institucional do caso\n\n"
        "Nao repita informacao ja dada so' para atingir tamanho - "
        "aprofunde e detalhe partes ainda nao exploradas. Esta faixa "
        f"({caracteres_min}-{caracteres_max} caracteres) vale para o "
        "corpo do roteiro (roteiro_md), nao para o prompt inteiro. Se, "
        f"mesmo assim, o mínimo de {caracteres_min} caracteres nao for "
        "atingivel com material verificado, preencha o campo "
        "justificativa_tamanho explicando o que faltou - nunca complete "
        "com repeticao, especulacao ou reformulacao do que ja foi dito."
    )


def _tool_web_search(max_usos: int) -> dict:
    return {"type": "web_search_20250305", "name": "web_search", "max_uses": max_usos}


def _dry_run_ativo() -> bool:
    return (os.environ.get("DRY_RUN_API") or "").strip().lower() == "true"


def _estimar_tokens(texto: str) -> int:
    """Aproximacao simples (chars / 4) - nao precisa ser precisa, so
    dar uma nocao de ordem de grandeza pro usuario calibrando prompt."""
    return max(0, len(texto) // 4)


def _persistir_job_simples(pasta_projeto: Path, **campos):
    """Mesma logica de merge de server.py:_persistir_job, duplicada aqui
    de proposito (CLAUDE.md secao 9 - cada script e' autocontido)."""
    caminho = pasta_projeto / "job.json"
    atual = {}
    if caminho.exists():
        try:
            atual = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            atual = {}
    atual.update(campos)
    caminho.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")


def _rodar_dry_run(pasta_projeto: Path, perfil: str, idioma: str, modelo: str, prompt_sistema: str, prompt_usuario: str) -> dict:
    """Modo de calibracao de prompt (ver docstring do modulo) - monta o
    prompt normalmente mas nunca chama a API da Anthropic."""
    tokens_estimados = _estimar_tokens(prompt_sistema) + _estimar_tokens(prompt_usuario)
    custo_estimado_usd = round((tokens_estimados / 1_000_000) * CUSTO_INPUT_POR_MILHAO_USD, 4)

    conteudo = (
        "=== PROMPT DE SISTEMA ===\n"
        f"{prompt_sistema}\n\n"
        "=== PROMPT DE USUARIO ===\n"
        f"{prompt_usuario}\n\n"
        "=== METADADOS ===\n"
        f"Perfil: {perfil}\n"
        f"Idioma: {idioma}\n"
        f"Modelo (nao chamado): {modelo}\n"
        f"Tokens input estimados: ~{tokens_estimados}\n"
        f"Custo estimado se chamado: ~${custo_estimado_usd}\n"
    )
    (pasta_projeto / "dry_run_output.md").write_text(conteudo, encoding="utf-8")

    _persistir_job_simples(pasta_projeto, status="dry_run_concluido", etapa_atual="roteiro")

    emitir_progresso(
        100.0,
        "Modo dry-run: prompt montado e salvo em dry_run_output.md (API nao foi chamada)",
        sucesso=True,
        dry_run=True,
    )
    return {"sucesso": True, "dry_run": True}


def _ler_perfil(pasta_projeto: Path) -> str:
    caminho = pasta_projeto / "entrada" / "perfil.txt"
    if not caminho.exists():
        return ""
    return caminho.read_text(encoding="utf-8-sig").strip()


def _formatar_timestamp(segundos) -> str:
    total = int(segundos or 0)
    horas, resto = divmod(total, 3600)
    minutos, s = divmod(resto, 60)
    if horas:
        return f"{horas:02d}:{minutos:02d}:{s:02d}"
    return f"{minutos:02d}:{s:02d}"


def _carregar_transcricoes(pasta_projeto: Path, manifest: dict) -> dict:
    pasta_transcricoes = pasta_projeto / "transcricoes"
    transcricoes = {}
    for fonte in manifest.get("fontes", []):
        id_fonte = fonte.get("id")
        if not id_fonte:
            continue
        caminho = pasta_transcricoes / f"{id_fonte}.json"
        if not caminho.exists():
            continue
        try:
            transcricoes[id_fonte] = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return transcricoes


def _montar_bloco_transcricoes(manifest: dict, transcricoes: dict) -> list:
    """Bloco de transcricoes de cada video-fonte com sucesso, identificadas
    claramente por fonte e com timestamp por segmento (necessario para as
    notas de rodape [F<n>@mm:ss] - CLAUDE.md secao 5.4). Compartilhado
    pelos prompts de usuario das duas fases (CLAUDE.md secao 5.3): a fase 2
    tambem precisa das transcricoes, mesmo ja tendo o resumo da fase 1,
    porque e' delas que vem o timestamp exato de cada nota de rodape."""
    blocos = []
    for fonte in manifest.get("fontes", []):
        if not fonte.get("sucesso"):
            continue
        id_fonte = fonte.get("id") or ""
        transcricao = transcricoes.get(id_fonte)
        if not transcricao:
            continue
        numero_exibicao = id_fonte.replace("fonte", "") or id_fonte
        blocos.append(
            f"=== FONTE {numero_exibicao}: {fonte.get('arquivo')} "
            f"(URL: {fonte.get('url_original')}) ==="
        )
        for segmento in transcricao.get("segmentos", []):
            texto = (segmento.get("text") or "").strip()
            if not texto:
                continue
            timestamp = _formatar_timestamp(segmento.get("start", 0))
            blocos.append(f"[{timestamp}] {texto}")
    return blocos


def montar_prompt_usuario(manifest: dict, transcricoes: dict, feedback: str | None = None) -> str:
    """Prompt de usuario da FASE 1 (pesquisa): transcricoes de cada
    video-fonte + instrucao para, ao final da pesquisa, entregar um resumo
    estruturado dos achados (nao o roteiro final - isso e' a fase 2).

    `feedback`, se informado (POST /projetos/<id>/regerar_roteiro - CLAUDE.md
    secao 5.5, botao "Refazer roteiro com instrucoes"), e' o texto que o
    usuario escreveu pedindo mudancas no roteiro anterior - injetado como
    primeiro bloco do prompt, antes das transcricoes."""
    blocos = []
    if feedback:
        blocos.append(
            "O usuario revisou o roteiro anterior e pediu as seguintes "
            f"mudancas: {feedback}. Considere isso ao gerar o novo roteiro."
        )
    blocos.append(
        "As transcricoes abaixo sao dos videos-fonte deste projeto. Ao citar "
        "uma delas numa nota de rodape [F<numero>@mm:ss], use o numero da "
        "fonte sem zero a esquerda (ex: a transcricao de FONTE 01 vira F1)."
    )
    blocos.extend(_montar_bloco_transcricoes(manifest, transcricoes))
    blocos.append(
        "\nPesquise e colete todas as informacoes necessarias para o "
        "roteiro (fatos verificados com suas fontes, cronologia, pessoas "
        "envolvidas, conflitos entre fontes, titulos populares no YouTube "
        "sobre o caso). Ao final, entregue um RESUMO ESTRUTURADO desses "
        f"achados atraves da tool '{NOME_TOOL_RESUMO}' - nao escreva o "
        "roteiro final nesta etapa, isso acontece numa etapa seguinte."
    )
    return "\n".join(blocos)


def montar_prompt_usuario_fase2(
    resumo: dict, manifest: dict, transcricoes: dict, palavras_alvo: int, caracteres_alvo_min: int
) -> str:
    """Prompt de usuario da FASE 2 (geracao do roteiro final): contem SOMENTE
    o resumo estruturado produzido na fase 1 (nunca o historico bruto de
    pesquisa/web_search - motivo no docstring do modulo) mais as
    transcricoes (necessarias para os timestamps das notas de rodape
    [F<n>@mm:ss]).

    Reforco de tamanho (CLAUDE.md - Investigacao de tamanho curto, Grupo C):
    o bloco de sistema `_montar_bloco_tamanho_alvo` ja instrui o alvo, mas
    fica separado do ponto onde o modelo escreve por este turno inteiro de
    usuario (resumo + transcricoes, potencialmente dezenas de milhares de
    tokens). Repetir o numero minimo aqui, como ULTIMO bloco do prompt de
    usuario (imediatamente antes do modelo comecar a escrever), e'
    repeticao intencional para combater perda por recencia - nao
    redundancia a eliminar. Nao toca o prompt de sistema, entao nao afeta
    o cache_control marcado la (ver docstring do modulo)."""
    blocos = [
        "Resumo estruturado dos achados da fase de pesquisa (use como base "
        "factual do roteiro; cite as fontes originais indicadas nele nas "
        "notas de rodape, nunca 'o resumo' em si):",
        json.dumps(resumo, ensure_ascii=False, indent=2),
        "\nAs transcricoes abaixo sao dos videos-fonte deste projeto. Ao citar "
        "uma delas numa nota de rodape [F<numero>@mm:ss], use o numero da "
        "fonte sem zero a esquerda (ex: a transcricao de FONTE 01 vira F1).",
    ]
    blocos.extend(_montar_bloco_transcricoes(manifest, transcricoes))
    blocos.append(
        "\nGere o roteiro final, titulos e descricoes no formato JSON "
        "especificado no prompt de sistema, usando o resumo e as "
        "transcricoes acima como base factual."
    )
    blocos.append(
        f"\nLEMBRETE DE TAMANHO: roteiro_md deve ter no minimo "
        f"{caracteres_alvo_min} caracteres sem espacos (~{palavras_alvo} "
        "palavras). Abaixo disso o roteiro e' incompleto - se o material "
        "nao sustentar esse minimo, preencha justificativa_tamanho em vez "
        "de completar com repeticao ou especulacao."
    )
    return "\n".join(blocos)


def montar_prompt_expansao(
    roteiro_md: str, pergunta_promessa: str, palavras_atuais: int, palavras_alvo: int
) -> str:
    """Prompt da chamada de expansao (Grupo E - roteiro abaixo do piso de
    95% do alvo em palavras narradas). Critico: a expansao precisa
    aprofundar DENTRO do fio da pergunta-promessa (Regra 0 do sistema.md),
    nunca reintroduzir material cortado nem voltar a cobrir o caso inteiro -
    sem essa instrucao explicita a expansao desfaz o proposito do Grupo A."""
    deficit = max(0, palavras_alvo - palavras_atuais)
    return (
        "O roteiro abaixo ficou aquem do piso de tamanho definido para "
        f"este projeto: tem aproximadamente {palavras_atuais} palavras "
        f"narradas (sem contar notas de rodape), o alvo e' {palavras_alvo} "
        f"(faltam cerca de {deficit} palavras).\n\n"
        f'A pergunta-promessa deste roteiro e: "{pergunta_promessa}"\n\n'
        "Expanda o roteiro ABAIXO aprofundando EXCLUSIVAMENTE dentro do "
        "fio dessa pergunta-promessa - mais evidencia, mais derivacao "
        "(regra de derivacao numerica do prompt de sistema), mais contexto "
        "das pessoas envolvidas NESSE fio especifico. NUNCA reintroduza "
        "material que foi cortado por nao pertencer a esse fio, e NUNCA "
        "volte a cobrir o caso/evento/tema inteiro por assunto - isso "
        "desfaz o proposito da pergunta-promessa. Nunca repita informacao "
        "ja dada, nunca especule, nunca reformule so para ganhar tamanho.\n\n"
        "Devolva o roteiro COMPLETO (nao so' o trecho novo), com a mesma "
        "pergunta_promessa, nucleo_editorial, titulos, descricoes e TODAS "
        "as notas de rodape de origem originais preservadas, atraves da "
        "mesma tool de saida.\n\n"
        "=== ROTEIRO ATUAL ===\n"
        f"{roteiro_md}"
    )


def montar_prompt_justificativa(roteiro_md: str, palavras_atuais: int, palavras_alvo: int) -> str:
    """Prompt da chamada curta de justificativa (Grupo E) - so' usada
    quando o roteiro ficou abaixo do piso mesmo apos as tentativas de
    expansao E o modelo nao preencheu justificativa_tamanho por conta
    propria."""
    return (
        f"O roteiro abaixo ficou com {palavras_atuais} palavras narradas, "
        f"abaixo do piso de {palavras_alvo} palavras definido para este "
        "projeto, mesmo apos tentativas de expansao. Explique em poucas "
        "frases o que faltou no material verificado (fontes/transcricoes "
        "insuficientes) para sustentar o piso com qualidade. Nunca cite "
        "repeticao, especulacao ou reformulacao como motivo - essas nunca "
        "sao aceitaveis.\n\n=== ROTEIRO ===\n"
        f"{roteiro_md}"
    )


# Faixa de tamanho aceitavel do nucleo_editorial (Correcao 1 - sessao pre-
# thumbnail): schema pede 2-8 palavras, esta constante e' o que o codigo
# de fato aceita como valido (fonte unica da verdade, tanto pra decidir se
# reparo e' necessario quanto pro teste).
NUCLEO_EDITORIAL_PALAVRAS_MIN = 2
NUCLEO_EDITORIAL_PALAVRAS_MAX = 8


def _nucleo_editorial_valido(texto) -> bool:
    """True se `texto` e' um nucleo_editorial utilizavel: string, nao
    vazia apos strip, entre NUCLEO_EDITORIAL_PALAVRAS_MIN e _MAX palavras.
    Usada pra decidir se a chamada de reparo (ver `montar_prompt_reparo_
    nucleo`) e' necessaria - nunca pra invalidar o roteiro inteiro (esse
    campo nunca passa por `_validar_saida_estruturada`, de proposito:
    perder um roteiro que custou ~US$1 e saiu bom por causa de um campo de
    metadado seria caro e desnecessario)."""
    if not isinstance(texto, str):
        return False
    aparado = texto.strip()
    if not aparado:
        return False
    n_palavras = len(aparado.split())
    return NUCLEO_EDITORIAL_PALAVRAS_MIN <= n_palavras <= NUCLEO_EDITORIAL_PALAVRAS_MAX


def montar_prompt_reparo_nucleo(pergunta_promessa: str) -> str:
    """Prompt da chamada curta de reparo (Correcao 1) - so' usada quando o
    roteiro original saiu sem nucleo_editorial valido. Gera SOMENTE o
    nucleo, nunca toca no roteiro/titulos/descricoes ja gerados."""
    return (
        "O roteiro abaixo foi gerado com sucesso, mas saiu sem um "
        "nucleo_editorial valido (2 a 8 palavras). A pergunta-promessa "
        f'deste roteiro e: "{pergunta_promessa}"\n\n'
        "Derive dela um nucleo_editorial compacto (2 a 8 palavras) - a "
        "essencia da pergunta em forma curta o suficiente para orientar "
        "um titulo (ex: 'mistakes that identify him'). Entregue SOMENTE "
        "o nucleo_editorial, atraves da tool indicada."
    )


# =============================================================================
# Validacoes pos-geracao (sessao de refinamento pos-validacao empirica) -
# GRUPOS A/B/C. Regra central: NUNCA bloqueiam a geracao, nunca corrigem
# nada sozinhas - so' anexam avisos a job_metadata.json para a tela de
# revisao (CLAUDE.md secao 5.5) exibir. Vigilancia continua ao longo do
# texto (nome garbado de legenda automatica, numero repetido sem re-
# derivar) e' exatamente o tipo de instrucao que sistema.md mostrou NAO
# conseguir sustentar de forma confiavel - a correcao entra aqui, em
# codigo, depois da geracao, nunca no prompt.
# =============================================================================


def _normalizar_texto(texto: str) -> str:
    """minusculas + sem acento - usado para comparar nomes/termos sem
    depender de acentuacao exata (o roteiro e a transcricao original
    podem grafar o mesmo nome com acentos diferentes)."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return sem_acento.lower()


# --- GRUPO A: nomes proprios sustentados so' por transcricao ---------------

# Nao e' uma lista exaustiva de stopwords - so' os casos comuns o
# suficiente para gerar falso positivo em "Palavra1 Palavra2" no inicio de
# frase (ex: "The Suspect fled" casaria "The Suspect" sem este filtro).
# Cobre en/pt/es/de (os 5 idiomas suportados - CLAUDE.md secao 3.1).
_STOPWORDS_INICIO_NOME = {
    "the", "a", "an", "this", "that", "these", "those", "he", "she", "it", "they",
    "but", "and", "after", "before", "during", "when", "while", "however",
    "meanwhile", "then", "now", "if", "so", "yet",
    "on", "in", "at", "by", "as", "for", "from", "with", "since", "until", "within",
    "o", "os", "as", "um", "uma", "este", "esta", "esse", "essa", "ele", "ela",
    "eles", "elas", "mas", "e", "depois", "antes", "durante", "quando",
    "enquanto", "porem", "entao",
    "el", "la", "los", "las", "un", "una", "ese", "esa", "el", "ella", "pero",
    "y", "despues", "durante", "cuando", "mientras", "entonces",
    "der", "die", "das", "ein", "eine", "dieser", "diese", "dieses", "er",
    "sie", "es", "aber", "und", "nach", "vor", "wahrend", "wenn", "dann",
}

# Sequencias de 2+ palavras iniciadas por maiuscula - candidato a nome
# proprio (pessoa, lugar ou instituicao - o filtro de lugar/instituicao
# abaixo reduz o ruido). Exige pelo menos 1 letra minuscula depois da
# maiuscula em cada token, entao nunca casa uma tag de nota sozinha
# ([F1@.. ou [N: ..).
PADRAO_CANDIDATO_NOME = re.compile(
    r"\b[A-ZÀ-Ý][a-zà-ÿß'\-]+(?:\s+[A-ZÀ-Ý][a-zà-ÿß'\-]+)+\b"
)

# Se qualquer token do candidato bater com uma destas palavras, e' tratado
# como lugar/instituicao (baixo risco, nunca sinalizado) em vez de nome de
# pessoa - lista curta e deliberadamente conservadora (CLAUDE.md secao 18 -
# falso negativo aqui so' gera um aviso a mais, nunca um erro escondido).
_PALAVRAS_INSTITUICAO_LUGAR = {
    "police", "department", "county", "city", "state", "court", "university",
    "hospital", "school", "street", "avenue", "boulevard", "road", "district",
    "bureau", "agency", "corporation", "company", "inc", "llc", "ltd", "church",
    "prison", "center", "centre", "airport", "river", "lake", "mountain",
    "national", "federal", "united", "republic", "kingdom", "institute",
    "association", "committee", "council", "force", "squad", "union", "records",
    "tribunal", "policia", "departamento", "prefeitura", "universidade",
    "prisao", "rua", "avenida", "cidade", "estado", "policia",
    "ayuntamiento", "universidad", "carcel", "calle", "ciudad",
    "polizei", "abteilung", "gericht", "universitat", "krankenhaus",
    "gefangnis", "strasse", "stadt", "staat",
}


def _eh_lugar_ou_instituicao(candidato: str) -> bool:
    tokens = {_normalizar_texto(t) for t in candidato.split()}
    return bool(tokens & _PALAVRAS_INSTITUICAO_LUGAR)


def _linhas_narrativas(texto: str):
    """(offset_absoluto, linha) para cada linha do roteiro que NAO e' um
    titulo markdown (`# `/`## `/etc) - titulos em Title Case (convencao
    comum de subtitulo de secao) geram ruido massivo no Grupo A sem serem
    nomes de pessoa, e permitir que o candidato atravesse a quebra de linha
    entre um titulo e o paragrafo seguinte produzia candidatos absurdos
    (ex: 'Foothills\\n\\nNancy Guthrie' como um so' 'nome'). Escanear
    linha a linha resolve os dois problemas de uma vez."""
    offset = 0
    for linha in texto.splitlines(keepends=True):
        if not linha.lstrip().startswith("#"):
            yield offset, linha
        offset += len(linha)


def _construir_corpus_fontes_escritas(resumo) -> str:
    """Corpus de texto usado como proxy de 'fontes escritas' para o Grupo A
    (CLAUDE.md - ver docstring do modulo/PLANO da sessao): a API de web
    search da Anthropic nao expõe o texto bruto das paginas encontradas
    (`encrypted_content`, opaco) nem persiste isso em lugar nenhum hoje -
    so' o resumo estruturado que a fase 1 produz (SCHEMA_RESUMO) fica
    disponivel em codigo apos a geracao. Usar esse resumo como corpus e' a
    aproximacao mais fiel possivel sem adicionar fetch de pagina externo
    (fora de escopo desta sessao): `pessoas_envolvidas` em particular vem
    da pesquisa real (web_search), entao um nome que so aparece via nota de
    transcricao [F#@mm:ss] e nao aparece aqui e' sinal real de possivel
    erro de transcricao automatica, nao so' de "resumo incompleto"."""
    if not isinstance(resumo, dict):
        return ""
    partes = []
    for pessoa in resumo.get("pessoas_envolvidas", []) or []:
        if isinstance(pessoa, dict):
            partes.extend(str(pessoa.get(campo, "")) for campo in ("nome", "papel", "status_legal"))
    for fato in resumo.get("fatos_verificados", []) or []:
        if isinstance(fato, dict):
            partes.extend(str(fato.get(campo, "")) for campo in ("fato", "fonte"))
    for item in resumo.get("cronologia", []) or []:
        if isinstance(item, dict):
            partes.append(str(item.get("evento", "")))
    for conflito in resumo.get("conflitos_entre_fontes", []) or []:
        if isinstance(conflito, dict):
            partes.extend(str(conflito.get(campo, "")) for campo in ("tema", "versao_a", "versao_b"))
    partes.extend(str(o) for o in resumo.get("observacoes_editoriais", []) or [])
    return _normalizar_texto(" ".join(p for p in partes if p))


def detectar_nomes_suspeitos(roteiro_md: str, resumo) -> list:
    """Grupo A: candidatos a nome proprio no roteiro que NAO aparecem no
    corpus de fontes escritas (ver `_construir_corpus_fontes_escritas`).
    Classificacao em 3 niveis (nunca bloqueia, nunca corrige - so' marca):

    - 'alto': ausente do corpus E sustentado APENAS por nota de transcricao
      [F#@mm:ss] nas proximidades (sem nenhuma nota [N: ...] junto) - e' o
      padrao exato do caso real que motivou este grupo (legenda automatica
      garbou um nome, a nota so' aponta pro video-fonte, nunca pra uma
      fonte escrita que confirmaria a grafia).
    - 'medio': ausente do corpus, mas sem nota nenhuma por perto ou com
      nota ambigua (nota [F#@..] E [N: ...] juntas).
    - ignorado (nao entra no retorno): presente no corpus, ou reconhecido
      como lugar/instituicao (`_eh_lugar_ou_instituicao`).

    Retorna lista ordenada com 'alto' primeiro."""
    roteiro_md = roteiro_md or ""
    corpus = _construir_corpus_fontes_escritas(resumo)
    resultados = []
    vistos = set()

    for offset_linha, linha in _linhas_narrativas(roteiro_md):
        for match in PADRAO_CANDIDATO_NOME.finditer(linha):
            candidato = match.group(0)
            primeiro_token = _normalizar_texto(candidato.split()[0])
            if primeiro_token in _STOPWORDS_INICIO_NOME:
                continue

            chave = _normalizar_texto(candidato)
            if chave in vistos:
                continue
            vistos.add(chave)

            if _eh_lugar_ou_instituicao(candidato):
                continue
            if corpus and chave in corpus:
                continue

            inicio_abs = offset_linha + match.start()
            fim_abs = offset_linha + match.end()
            janela = roteiro_md[inicio_abs:min(len(roteiro_md), fim_abs + 200)]
            tem_nota_f = bool(PADRAO_NOTA_FONTE.search(janela))
            tem_nota_n = bool(PADRAO_NOTA_EXTERNA.search(janela))
            nivel = "alto" if (tem_nota_f and not tem_nota_n) else "medio"

            contexto = roteiro_md[max(0, inicio_abs - 80):min(len(roteiro_md), fim_abs + 80)].strip()
            resultados.append({"nome": candidato, "nivel": nivel, "contexto": contexto})

    ordem = {"alto": 0, "medio": 1}
    resultados.sort(key=lambda r: ordem.get(r["nivel"], 2))
    return resultados


# --- GRUPO B: titulos possivelmente divergentes do nucleo editorial --------

_STOPWORDS_TERMOS_TITULO = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "but",
    "is", "was", "were", "his", "her", "their", "its", "that", "this", "how",
    "why", "who", "what", "when", "where", "did", "does", "with", "from",
    "o", "a", "os", "as", "de", "da", "do", "das", "dos", "e", "ou", "em",
    "que", "como", "por", "para", "seu", "sua",
    "el", "la", "los", "las", "en", "y", "o",
    "der", "die", "das", "und", "oder", "auf", "zu", "fur", "wie", "warum",
}


def _termos_significativos(texto: str) -> set:
    normalizado = _normalizar_texto(texto)
    tokens = re.findall(r"[a-z0-9]+", normalizado)
    return {t for t in tokens if len(t) > 2 and t not in _STOPWORDS_TERMOS_TITULO}


def detectar_titulos_divergentes(nucleo_editorial, titulos) -> list:
    """Grupo B: heuristica lexical CONSERVADORA, so' sinaliza - nunca
    regera titulo nenhum (primeira versao, ver PLANO da sessao). Um titulo
    que nao compartilha nenhum termo significativo com `nucleo_editorial`
    entra na lista retornada. `nucleo_editorial` pode estar ausente
    (roteiro gerado antes deste campo existir, ou modelo nao preencheu) -
    nesse caso retorna lista vazia (nada a comparar, nunca falha)."""
    if not isinstance(nucleo_editorial, str) or not nucleo_editorial.strip():
        return []
    if not isinstance(titulos, list) or not titulos:
        return []
    termos_nucleo = _termos_significativos(nucleo_editorial)
    if not termos_nucleo:
        return []
    return [
        titulo
        for titulo in titulos
        if isinstance(titulo, str) and not (termos_nucleo & _termos_significativos(titulo))
    ]


# --- GRUPO C: numero de duracao/janela temporal sem derivacao proxima ------

_NUMEROS_EXTENSO_EN = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    "thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
)
_NUMERO_TOKEN = rf"(?:\d+|(?:{_NUMEROS_EXTENSO_EN})(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?)"

# Escopo minimo deliberado (Grupo C, ajuste 4): so' duracao/janela
# temporal, NUNCA qualquer numero/contagem/valor/distancia - o objetivo e'
# marcar "quanto tempo" declarado sem derivacao por perto, nao auditar
# todo numero do roteiro.
_UNIDADES_TEMPO = (
    "seconds?|minutes?|hours?|days?|weeks?|months?|"
    "segundos?|minutos?|horas?|dias?|semanas?|meses?|"
    "d[ií]as?|semanas?|mes(?:es)?|"
    "sekunden?|minuten?|stunden?|tage?n?|wochen?"
)
PADRAO_NUMERO_TEMPO = re.compile(
    rf"\b{_NUMERO_TOKEN}\b[\s-]+(?:{_UNIDADES_TEMPO})\b", re.IGNORECASE
)

# Marcadores de derivacao (horarios, registros, sequencia de sinais) - se
# aparecerem na janela (frase atual + 2 anteriores), o numero NAO e'
# sinalizado. Lista curta de proposito (falso negativo aqui so' evita um
# aviso a mais, nunca esconde um erro - CLAUDE.md secao 18).
_MARCADORES_DERIVACAO = re.compile(
    r"\b(records?|logs?|log\s+entries|timestamps?|according to|based on|"
    r"call log|dispatch|signals?|sequence of (?:events|calls|signals)|"
    r"registros?|de acordo com|baseado em|baseada em|sequ[eê]ncia de sinais|"
    r"seg[uú]n los registros|de acuerdo con|basado en|"
    r"laut (?:den )?aufzeichnungen|gem[aä]ß|basierend auf)\b",
    re.IGNORECASE,
)
# Horario tipo "3:15" na janela tambem conta como marcador de derivacao -
# aplicado sobre o texto JA SEM notas (PADRAO_NOTA_FONTE removida antes),
# entao nunca casa o timestamp de uma nota [F#@mm:ss] por engano.
PADRAO_HORARIO = re.compile(r"\b\d{1,2}:\d{2}\b")

_PADRAO_SENTENCA = re.compile(r"(?<=[.!?])\s+")


def _numeros_sem_derivacao_ativo() -> bool:
    """Grupo C e' configuravel/desligavel (CLAUDE.md - Grupo C, ajuste 4):
    se a heuristica gerar ruido demais no uso real, e' melhor desligar do
    que treinar o usuario a ignorar avisos. Default ligado."""
    valor = os.environ.get("VALIDACAO_NUMEROS_ATIVA")
    if valor is None:
        return True
    return valor.strip().lower() not in ("false", "0", "nao", "não")


def detectar_numeros_sem_derivacao(roteiro_md: str) -> list:
    """Grupo C: numeros de duracao/contagem temporal citados sem nenhum
    marcador de derivacao na frase atual ou nas 2 anteriores. Nunca prova
    que a derivacao esta errada - so' marca uma frase que merece revisao
    humana (CLAUDE.md secao 12 - revisao humana e' a mitigacao de risco
    factual, nao automacao que decide sozinha)."""
    if not _numeros_sem_derivacao_ativo():
        return []

    texto = _remover_notas_e_markdown(roteiro_md)
    sentencas = [s for s in _PADRAO_SENTENCA.split(texto) if s.strip()]

    resultados = []
    for i, sentenca in enumerate(sentencas):
        match = PADRAO_NUMERO_TEMPO.search(sentenca)
        if not match:
            continue
        janela = " ".join(sentencas[max(0, i - 2):i + 1])
        if _MARCADORES_DERIVACAO.search(janela) or PADRAO_HORARIO.search(janela):
            continue
        resultados.append(
            {"trecho": sentenca.strip()[:220], "numero_detectado": match.group(0).strip()}
        )
    return resultados


def _extrair_tool_use(resposta, nome_tool):
    for bloco in _valor(resposta, "content", []) or []:
        if _valor(bloco, "type") == "tool_use" and _valor(bloco, "name") == nome_tool:
            return _valor(bloco, "input")
    return None


def _validar_saida_estruturada(dados) -> tuple:
    if not isinstance(dados, dict):
        return False, "Resposta da API em formato inesperado. Tente novamente."

    pergunta_promessa = dados.get("pergunta_promessa")
    if not isinstance(pergunta_promessa, str) or not pergunta_promessa.strip():
        return False, "Resposta da API nao contem o campo 'pergunta_promessa'."
    pergunta_promessa = pergunta_promessa.strip()
    if len(pergunta_promessa) < 15 or "?" not in pergunta_promessa:
        return (
            False,
            "Campo 'pergunta_promessa' generico demais - precisa ser uma "
            "pergunta especifica deste caso/evento/tema (formulada com '?').",
        )

    roteiro_md = dados.get("roteiro_md")
    if not isinstance(roteiro_md, str) or not roteiro_md.strip():
        return False, "Resposta da API nao contem o campo 'roteiro_md'."

    titulos = dados.get("titulos")
    if not isinstance(titulos, list) or len(titulos) < 3:
        return False, "Resposta da API contem menos de 3 titulos sugeridos."

    descricoes = dados.get("descricoes")
    if not isinstance(descricoes, list) or len(descricoes) < 3:
        return False, "Resposta da API contem menos de 3 descricoes sugeridas."

    return True, None


def _validar_pre_condicoes(pasta_projeto: Path):
    """Valida tudo que este script precisa ANTES de chamar a API
    (CLAUDE.md secao 18.6). Retorna (True, None, None) se pode prosseguir,
    ou (False, mensagem_de_erro, tipo_erro) caso contrario."""
    pasta_transcricoes = pasta_projeto / "transcricoes"
    tem_transcricoes = pasta_transcricoes.is_dir() and any(pasta_transcricoes.glob("*.json"))
    if not tem_transcricoes:
        return (
            False,
            "Transcricoes nao encontradas. Etapa 2 pode ter falhado.",
            "transcricoes_ausentes",
        )

    caminho_manifest = pasta_projeto / "fontes" / "manifest_fontes.json"
    if not caminho_manifest.exists():
        return (
            False,
            "fontes/manifest_fontes.json nao encontrado. Rode a Etapa 1 antes desta etapa.",
            "transcricoes_ausentes",
        )

    if not _ler_perfil(pasta_projeto):
        return False, "entrada/perfil.txt nao encontrado ou vazio.", "perfil_invalido"

    return True, None, None


def _executar_fase_pesquisa(cliente, modelo, prompt_sistema, mensagens, tools_pesquisa, youtube_key, idioma, inicio):
    """Fase 1 completa: primeiro deixa o modelo pesquisar (web_search
    server-side + tool client-side youtube_top_titles, se disponivel) ate
    parar de pedir tools, depois faz UMA chamada extra com `tool_choice`
    forcado em `entregar_resumo_pesquisa` para extrair o resumo estruturado
    dos achados (nao o roteiro final - isso e' a fase 2, numa conversa
    nova, ver `montar_prompt_usuario_fase2`).

    Prompt caching (otimizacao de custo pos-Sessao 6.5): o loop de
    pesquisa e' o ponto que mais inflava o input (cada rodada reenvia
    a conversa inteira acumulada ate ali). `mensagens[0]` (o prompt de
    usuario inicial com as transcricoes) ja chega com cache_control
    marcado pelo chamador. Aqui, a cada rodada nova de tool_result,
    marcamos o ULTIMO bloco da rodada mais recente com cache_control e
    mantemos so os 2 mais recentes marcados (janela deslizante) - a API
    aceita no maximo 4 breakpoints de cache por chamada, e os outros 2 ja
    estao ocupados por sistema + prompt de usuario inicial.

    Retorna (resumo, tokens_input, tokens_output, tokens_cache_criados,
    tokens_cache_lidos, web_searches_usadas, chamadas_debug). `resumo` e'
    `None` se a chamada final nao devolveu o tool_use esperado (defesa
    contra resposta inesperada da API, mesmo espirito de
    `_validar_saida_estruturada`). `chamadas_debug` e' a lista de detalhe
    por chamada (Sessao 6.7, ver `_registrar_chamada_debug`) - gravada em
    debug_cache.log pelo chamador. `mensagens` e' mutado in-place com o
    historico da conversa - usado so dentro desta fase, nunca reaproveitado
    na fase 2."""
    tokens_input = 0
    tokens_output = 0
    tokens_cache_criados = 0
    tokens_cache_lidos = 0
    web_searches_usadas = 0
    system_blocks = _montar_system_blocks(prompt_sistema)
    janela_cache_tool_results = []
    chamadas_debug = []

    for rodada in range(MAX_ITERACOES_FERRAMENTAS):
        _checar_timeout(inicio)
        resposta = cliente.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_RESPOSTA,
            system=system_blocks,
            messages=mensagens,
            tools=tools_pesquisa,
        )
        entrada_tok, saida_tok, cache_criado_tok, cache_lido_tok = _contar_tokens(resposta)
        tokens_input += entrada_tok
        tokens_output += saida_tok
        tokens_cache_criados += cache_criado_tok
        tokens_cache_lidos += cache_lido_tok
        web_searches_usadas += _contar_web_searches(resposta)
        _registrar_chamada_debug(
            chamadas_debug, f"pesquisa_rodada_{rodada + 1}", entrada_tok, saida_tok, cache_criado_tok, cache_lido_tok
        )

        blocos_tool_use = [
            bloco for bloco in (_valor(resposta, "content", []) or []) if _valor(bloco, "type") == "tool_use"
        ]
        if not blocos_tool_use:
            break

        mensagens.append({"role": "assistant", "content": _valor(resposta, "content", [])})
        resultados_tool = []
        for bloco in blocos_tool_use:
            nome_tool = _valor(bloco, "name")
            id_tool_use = _valor(bloco, "id")
            entrada_tool = _valor(bloco, "input") or {}
            if nome_tool == "youtube_top_titles":
                resultado = youtube_tool.buscar_titulos_top(
                    entrada_tool.get("query", ""),
                    entrada_tool.get("idioma", idioma),
                    youtube_key,
                )
                conteudo = json.dumps(resultado, ensure_ascii=False)
            else:
                conteudo = "Tool desconhecida - ignorada."
            resultados_tool.append(
                {"type": "tool_result", "tool_use_id": id_tool_use, "content": conteudo}
            )

        if resultados_tool:
            resultados_tool[-1]["cache_control"] = {"type": "ephemeral"}
            janela_cache_tool_results.append(resultados_tool[-1])
            if len(janela_cache_tool_results) > 2:
                janela_cache_tool_results.pop(0).pop("cache_control", None)

        mensagens.append({"role": "user", "content": resultados_tool})

    _checar_timeout(inicio)
    resposta_resumo = cliente.messages.create(
        model=modelo,
        max_tokens=MAX_TOKENS_RESPOSTA,
        system=system_blocks,
        messages=mensagens,
        tools=TOOLS_FASE_ESTRUTURADA,
        tool_choice={"type": "tool", "name": NOME_TOOL_RESUMO},
    )
    entrada_tok, saida_tok, cache_criado_tok, cache_lido_tok = _contar_tokens(resposta_resumo)
    tokens_input += entrada_tok
    tokens_output += saida_tok
    tokens_cache_criados += cache_criado_tok
    tokens_cache_lidos += cache_lido_tok
    web_searches_usadas += _contar_web_searches(resposta_resumo)
    _registrar_chamada_debug(chamadas_debug, "resumo_estruturado", entrada_tok, saida_tok, cache_criado_tok, cache_lido_tok)

    resumo = _extrair_tool_use(resposta_resumo, NOME_TOOL_RESUMO)

    return (
        resumo,
        tokens_input,
        tokens_output,
        tokens_cache_criados,
        tokens_cache_lidos,
        web_searches_usadas,
        chamadas_debug,
    )


def gerar_roteiro(pasta_projeto: Path) -> dict:
    inicio = time.monotonic()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        mensagem = "Configure ANTHROPIC_API_KEY no arquivo .env. Consulte LEIAME.md."
        emitir_progresso(
            0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="chave_ausente", mensagem_usuario=mensagem
        )
        return {"sucesso": False, "erro_fatal": mensagem, "tipo_erro": "chave_ausente"}

    ok_precondicoes, mensagem_erro, tipo_erro = _validar_pre_condicoes(pasta_projeto)
    if not ok_precondicoes:
        emitir_progresso(
            0.0, f"ERRO: {mensagem_erro}", sucesso=False, tipo_erro=tipo_erro, mensagem_usuario=mensagem_erro
        )
        return {"sucesso": False, "erro_fatal": mensagem_erro, "tipo_erro": tipo_erro}

    if anthropic is None:
        mensagem = "Biblioteca anthropic nao esta instalada no ambiente Python atual."
        emitir_progresso(
            0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="erro_desconhecido", mensagem_usuario=mensagem
        )
        return {"sucesso": False, "erro_fatal": mensagem, "tipo_erro": "erro_desconhecido"}

    perfil = _ler_perfil(pasta_projeto)
    idioma = os.environ.get("IDIOMA_ROTEIRO") or IDIOMA_PADRAO
    modelo = os.environ.get("ANTHROPIC_MODEL") or MODELO_PADRAO
    web_search_max = _ler_web_search_max()
    youtube_key = os.environ.get("YOUTUBE_API_KEY")
    palavras_alvo, duracao_alvo_minutos = _ler_configuracao_tamanho(pasta_projeto)
    caracteres_alvo_min = int(palavras_alvo * CHARS_POR_PALAVRA_MIN)
    caracteres_alvo_max = int(palavras_alvo * CHARS_POR_PALAVRA_MAX)

    emitir_progresso(2.0, f"Montando prompt para o perfil '{perfil}' ({idioma})...")

    try:
        prompt_sistema = prompts_loader.montar_prompt(
            perfil, idioma, web_search_max=web_search_max
        ).replace("{IDIOMA}", idioma)
        prompt_sistema += _montar_bloco_tamanho_alvo(palavras_alvo, duracao_alvo_minutos)
    except PromptErro as exc:
        mensagem = str(exc)
        emitir_progresso(
            0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="perfil_invalido", mensagem_usuario=mensagem
        )
        return {"sucesso": False, "erro_fatal": mensagem, "tipo_erro": "perfil_invalido"}

    manifest = json.loads((pasta_projeto / "fontes" / "manifest_fontes.json").read_text(encoding="utf-8"))
    transcricoes = _carregar_transcricoes(pasta_projeto, manifest)

    # Feedback de regeneracao (POST /projetos/<id>/regerar_roteiro -
    # CLAUDE.md secao 5.5): se o usuario pediu mudancas no roteiro anterior,
    # o arquivo existe e seu conteudo entra no prompt de usuario da fase 1.
    # Apagado so' apos geracao bem-sucedida (mais abaixo) - se esta tentativa
    # falhar, o feedback continua disponivel para a proxima.
    caminho_feedback = pasta_projeto / "entrada" / "feedback_regeneracao.txt"
    feedback = caminho_feedback.read_text(encoding="utf-8").strip() if caminho_feedback.exists() else None

    prompt_usuario_fase1 = montar_prompt_usuario(manifest, transcricoes, feedback=feedback)

    if _dry_run_ativo():
        return _rodar_dry_run(pasta_projeto, perfil, idioma, modelo, prompt_sistema, prompt_usuario_fase1)

    tools_pesquisa = [_tool_web_search(web_search_max)]
    if youtube_key:
        tools_pesquisa.append(youtube_tool.TOOL_DEFINITION)

    cliente = anthropic.Anthropic(api_key=api_key)
    mensagens_fase1 = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_usuario_fase1, "cache_control": {"type": "ephemeral"}}
            ],
        }
    ]

    emitir_progresso(10.0, "Gerando roteiro com IA (pesquisando fontes)...")

    try:
        (
            resumo,
            tokens_input,
            tokens_output,
            tokens_cache_criados,
            tokens_cache_lidos,
            web_searches_usadas,
            chamadas_debug,
        ) = _executar_fase_pesquisa(
            cliente, modelo, prompt_sistema, mensagens_fase1, tools_pesquisa, youtube_key, idioma, inicio
        )

        if not isinstance(resumo, dict):
            mensagem_validacao = "Fase de pesquisa nao retornou o resumo estruturado esperado. Tente novamente."
            emitir_progresso(
                0.0,
                f"ERRO: {mensagem_validacao}",
                sucesso=False,
                tipo_erro="resposta_malformada",
                mensagem_usuario=mensagem_validacao,
            )
            return {"sucesso": False, "erro_fatal": mensagem_validacao, "tipo_erro": "resposta_malformada"}

        emitir_progresso(60.0, "Resumo de pesquisa pronto. Gerando roteiro final...")

        # Fase 2: conversa NOVA, sem o historico da fase 1 (motivo no
        # docstring do modulo) - so o resumo estruturado + transcricoes.
        prompt_usuario_fase2 = montar_prompt_usuario_fase2(
            resumo, manifest, transcricoes, palavras_alvo, caracteres_alvo_min
        )
        mensagens_fase2 = [{"role": "user", "content": prompt_usuario_fase2}]

        _checar_timeout(inicio)
        # Mesmo prompt de sistema da chamada de resumo, byte a byte, E
        # MESMA lista de tools (TOOLS_FASE_ESTRUTURADA) - reaproveita de
        # verdade o cache criado la' (ver "GOTCHA de cache invalidado por
        # `tools`" no docstring do modulo: tools diferente teria invalidado
        # o cache do system mesmo com texto identico), mesmo sendo uma
        # conversa nova.
        resposta_final = cliente.messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_RESPOSTA,
            system=_montar_system_blocks(prompt_sistema),
            messages=mensagens_fase2,
            tools=TOOLS_FASE_ESTRUTURADA,
            tool_choice={"type": "tool", "name": NOME_TOOL_SAIDA},
        )
    except TimeoutError as exc:
        mensagem = str(exc) or "Geracao de roteiro excedeu tempo limite."
        emitir_progresso(0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="timeout", mensagem_usuario=mensagem)
        return {"sucesso": False, "erro_fatal": mensagem, "tipo_erro": "timeout"}
    except Exception as exc:  # abrange qualquer excecao do SDK anthropic
        categoria, mensagem = classificar_erro_api(exc)
        emitir_progresso(
            0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro=categoria, mensagem_usuario=mensagem
        )
        return {"sucesso": False, "erro_fatal": mensagem, "tipo_erro": categoria}

    entrada_tok_final, saida_tok_final, cache_criado_tok_final, cache_lido_tok_final = _contar_tokens(
        resposta_final
    )
    tokens_input += entrada_tok_final
    tokens_output += saida_tok_final
    tokens_cache_criados += cache_criado_tok_final
    tokens_cache_lidos += cache_lido_tok_final
    web_searches_usadas += _contar_web_searches(resposta_final)
    _registrar_chamada_debug(
        chamadas_debug, "roteiro_final", entrada_tok_final, saida_tok_final, cache_criado_tok_final, cache_lido_tok_final
    )

    dados_saida = _extrair_tool_use(resposta_final, NOME_TOOL_SAIDA)
    valido, mensagem_validacao = _validar_saida_estruturada(dados_saida)
    if not valido:
        stop_reason_final = getattr(resposta_final, "stop_reason", None)
        print(
            f"[INFO] Resposta final invalida (stop_reason={stop_reason_final}): "
            f"{mensagem_validacao}",
            flush=True,
        )
        if stop_reason_final == "max_tokens":
            mensagem_validacao += (
                " A resposta foi cortada por atingir MAX_TOKENS_RESPOSTA "
                f"({MAX_TOKENS_RESPOSTA}) - considere reduzir o tamanho alvo "
                "do roteiro."
            )
        emitir_progresso(
            0.0,
            f"ERRO: {mensagem_validacao}",
            sucesso=False,
            tipo_erro="resposta_malformada",
            mensagem_usuario=mensagem_validacao,
        )
        return {"sucesso": False, "erro_fatal": mensagem_validacao, "tipo_erro": "resposta_malformada"}

    stop_reason_final = getattr(resposta_final, "stop_reason", None)
    palavras_narradas = contar_palavras_narradas(dados_saida["roteiro_md"])
    notas_atuais = _contar_notas_rodape(dados_saida["roteiro_md"])
    ratio_tamanho = round(palavras_narradas / palavras_alvo, 2) if palavras_alvo else 0.0
    print(
        f"[INFO] Roteiro gerado: {palavras_narradas} palavras narradas "
        f"({len(dados_saida['roteiro_md'])} caracteres brutos, com notas e "
        f"markdown). Alvo era {palavras_alvo} palavras. Ratio: "
        f"{ratio_tamanho * 100:.0f}%. stop_reason={stop_reason_final}.",
        flush=True,
    )

    # Expansao condicional (Investigacao de tamanho curto - Grupo E): abaixo
    # do piso de EXPANSAO_LIMIAR_RATIO (95% do alvo em palavras narradas),
    # ate MAX_EXPANSOES chamadas tentam aprofundar dentro do fio da
    # pergunta-promessa (nunca reintroduzir material cortado nem voltar a
    # cobrir o caso/evento/tema inteiro - ver montar_prompt_expansao). Cada
    # tentativa passa pela mesma _validar_saida_estruturada e tem a
    # contagem de notas de rodape comparada com a versao anterior - queda
    # significativa (QUEDA_NOTAS_MAX_FRACAO) invalida a tentativa e mantem
    # a versao anterior, consumindo uma das MAX_EXPANSOES tentativas.
    expansoes = []
    tentativas = 0
    while ratio_tamanho < EXPANSAO_LIMIAR_RATIO and tentativas < MAX_EXPANSOES:
        tentativas += 1
        emitir_progresso(
            85.0,
            f"Roteiro abaixo do piso ({ratio_tamanho * 100:.0f}%). "
            f"Expandindo (tentativa {tentativas}/{MAX_EXPANSOES})...",
        )
        try:
            _checar_timeout(inicio)
            prompt_expansao = montar_prompt_expansao(
                dados_saida["roteiro_md"],
                dados_saida["pergunta_promessa"],
                palavras_narradas,
                palavras_alvo,
            )
            resposta_expansao = cliente.messages.create(
                model=modelo,
                max_tokens=MAX_TOKENS_RESPOSTA,
                system=_montar_system_blocks(prompt_sistema),
                messages=[{"role": "user", "content": prompt_expansao}],
                tools=TOOLS_FASE_ESTRUTURADA,
                tool_choice={"type": "tool", "name": NOME_TOOL_SAIDA},
            )
        except TimeoutError as exc:
            mensagem = str(exc) or "Geracao de roteiro excedeu tempo limite."
            emitir_progresso(0.0, f"ERRO: {mensagem}", sucesso=False, tipo_erro="timeout", mensagem_usuario=mensagem)
            return {"sucesso": False, "erro_fatal": mensagem, "tipo_erro": "timeout"}
        except Exception as exc:  # abrange qualquer excecao do SDK anthropic
            categoria, mensagem = classificar_erro_api(exc)
            print(
                f"[INFO] Expansao {tentativas} falhou ({categoria}): {mensagem}. "
                "Mantendo versao anterior.",
                flush=True,
            )
            expansoes.append(
                {
                    "tentativa": tentativas,
                    "aceita": False,
                    "motivo_rejeicao": f"erro_api:{categoria}",
                    "palavras_antes": palavras_narradas,
                }
            )
            break

        (
            entrada_tok_exp,
            saida_tok_exp,
            cache_criado_tok_exp,
            cache_lido_tok_exp,
        ) = _contar_tokens(resposta_expansao)
        tokens_input += entrada_tok_exp
        tokens_output += saida_tok_exp
        tokens_cache_criados += cache_criado_tok_exp
        tokens_cache_lidos += cache_lido_tok_exp
        web_searches_usadas += _contar_web_searches(resposta_expansao)
        _registrar_chamada_debug(
            chamadas_debug,
            f"expansao_{tentativas}",
            entrada_tok_exp,
            saida_tok_exp,
            cache_criado_tok_exp,
            cache_lido_tok_exp,
        )
        custo_expansao_usd = round(
            (entrada_tok_exp / 1_000_000) * CUSTO_INPUT_POR_MILHAO_USD
            + (cache_criado_tok_exp / 1_000_000) * (CUSTO_INPUT_POR_MILHAO_USD * MULTIPLICADOR_CACHE_WRITE)
            + (cache_lido_tok_exp / 1_000_000) * (CUSTO_INPUT_POR_MILHAO_USD * MULTIPLICADOR_CACHE_READ)
            + (saida_tok_exp / 1_000_000) * CUSTO_OUTPUT_POR_MILHAO_USD,
            4,
        )

        dados_expandidos = _extrair_tool_use(resposta_expansao, NOME_TOOL_SAIDA)
        valido_exp, mensagem_validacao_exp = _validar_saida_estruturada(dados_expandidos)
        registro_expansao = {
            "tentativa": tentativas,
            "palavras_antes": palavras_narradas,
            "notas_antes": notas_atuais,
            "custo_usd": custo_expansao_usd,
        }
        if not valido_exp:
            registro_expansao["aceita"] = False
            registro_expansao["motivo_rejeicao"] = mensagem_validacao_exp
            expansoes.append(registro_expansao)
            print(
                f"[INFO] Expansao {tentativas} invalida: {mensagem_validacao_exp}. "
                "Mantendo versao anterior.",
                flush=True,
            )
            break

        palavras_depois = contar_palavras_narradas(dados_expandidos["roteiro_md"])
        notas_depois = _contar_notas_rodape(dados_expandidos["roteiro_md"])
        registro_expansao["palavras_depois"] = palavras_depois
        registro_expansao["notas_depois"] = notas_depois

        queda_notas = notas_atuais > 0 and notas_depois < notas_atuais * (1 - QUEDA_NOTAS_MAX_FRACAO)
        if queda_notas:
            registro_expansao["aceita"] = False
            registro_expansao["motivo_rejeicao"] = (
                f"queda de notas de rodape ({notas_atuais} -> {notas_depois})"
            )
            expansoes.append(registro_expansao)
            print(
                f"[INFO] Expansao {tentativas} descartada: queda de notas de "
                f"rodape ({notas_atuais} -> {notas_depois}). Mantendo versao "
                "anterior.",
                flush=True,
            )
            break

        registro_expansao["aceita"] = True
        expansoes.append(registro_expansao)
        dados_saida = dados_expandidos
        palavras_narradas = palavras_depois
        notas_atuais = notas_depois
        ratio_tamanho = round(palavras_narradas / palavras_alvo, 2) if palavras_alvo else 0.0
        print(
            f"[INFO] Expansao {tentativas} aceita: {palavras_narradas} palavras "
            f"({ratio_tamanho * 100:.0f}% do alvo).",
            flush=True,
        )

    # Justificativa obrigatoria (Grupo E): se o piso nao foi atingido apos
    # as expansoes e o modelo nao preencheu justificativa_tamanho por conta
    # propria, uma chamada curta e forcada pergunta o que faltou.
    if ratio_tamanho < EXPANSAO_LIMIAR_RATIO:
        justificativa_existente = dados_saida.get("justificativa_tamanho")
        if not (isinstance(justificativa_existente, str) and justificativa_existente.strip()):
            try:
                _checar_timeout(inicio)
                prompt_justificativa = montar_prompt_justificativa(
                    dados_saida["roteiro_md"], palavras_narradas, palavras_alvo
                )
                resposta_justificativa = cliente.messages.create(
                    model=modelo,
                    max_tokens=1024,
                    system=_montar_system_blocks(prompt_sistema),
                    messages=[{"role": "user", "content": prompt_justificativa}],
                    tools=TOOLS_FASE_ESTRUTURADA,
                    tool_choice={"type": "tool", "name": NOME_TOOL_JUSTIFICATIVA},
                )
                (
                    entrada_tok_j,
                    saida_tok_j,
                    cache_criado_tok_j,
                    cache_lido_tok_j,
                ) = _contar_tokens(resposta_justificativa)
                tokens_input += entrada_tok_j
                tokens_output += saida_tok_j
                tokens_cache_criados += cache_criado_tok_j
                tokens_cache_lidos += cache_lido_tok_j
                _registrar_chamada_debug(
                    chamadas_debug,
                    "justificativa_tamanho",
                    entrada_tok_j,
                    saida_tok_j,
                    cache_criado_tok_j,
                    cache_lido_tok_j,
                )
                dados_justificativa = _extrair_tool_use(resposta_justificativa, NOME_TOOL_JUSTIFICATIVA)
                if isinstance(dados_justificativa, dict):
                    justificativa_obtida = dados_justificativa.get("justificativa")
                    if isinstance(justificativa_obtida, str) and justificativa_obtida.strip():
                        dados_saida["justificativa_tamanho"] = justificativa_obtida.strip()
            except Exception as exc:  # nunca falha a etapa por causa deste extra
                print(f"[INFO] Chamada de justificativa de tamanho falhou: {exc}", flush=True)

    # Reparo de nucleo_editorial (Correcao 1, sessao pre-thumbnail): campo
    # e' obrigatorio no schema mas o modelo pode sair sem ele (ou com
    # valor invalido) mesmo assim - NUNCA invalida o roteiro por causa
    # disso (`_validar_saida_estruturada` de proposito nao checa este
    # campo). Em vez disso, uma chamada curta e forcada tenta reparar so'
    # o nucleo a partir da pergunta_promessa ja aprovada; se falhar
    # tambem, persiste status "ausente" e segue - nunca silencioso (a
    # tela de thumbnail, quando ler nucleo_editorial_status, deve avisar
    # explicitamente que entrou em modo fallback).
    nucleo_editorial_status = "ok"
    if not _nucleo_editorial_valido(dados_saida.get("nucleo_editorial")):
        nucleo_editorial_status = "ausente"
        try:
            _checar_timeout(inicio)
            prompt_reparo_nucleo = montar_prompt_reparo_nucleo(dados_saida["pergunta_promessa"])
            resposta_reparo_nucleo = cliente.messages.create(
                model=modelo,
                max_tokens=256,
                system=_montar_system_blocks(prompt_sistema),
                messages=[{"role": "user", "content": prompt_reparo_nucleo}],
                tools=TOOLS_FASE_ESTRUTURADA,
                tool_choice={"type": "tool", "name": NOME_TOOL_NUCLEO},
            )
            (
                entrada_tok_nu,
                saida_tok_nu,
                cache_criado_tok_nu,
                cache_lido_tok_nu,
            ) = _contar_tokens(resposta_reparo_nucleo)
            tokens_input += entrada_tok_nu
            tokens_output += saida_tok_nu
            tokens_cache_criados += cache_criado_tok_nu
            tokens_cache_lidos += cache_lido_tok_nu
            _registrar_chamada_debug(
                chamadas_debug,
                "reparo_nucleo_editorial",
                entrada_tok_nu,
                saida_tok_nu,
                cache_criado_tok_nu,
                cache_lido_tok_nu,
            )
            dados_reparo_nucleo = _extrair_tool_use(resposta_reparo_nucleo, NOME_TOOL_NUCLEO)
            nucleo_reparado = (
                dados_reparo_nucleo.get("nucleo_editorial") if isinstance(dados_reparo_nucleo, dict) else None
            )
            if _nucleo_editorial_valido(nucleo_reparado):
                dados_saida["nucleo_editorial"] = nucleo_reparado.strip()
                nucleo_editorial_status = "reparado"
            else:
                dados_saida["nucleo_editorial"] = None
                print(
                    "[INFO] Reparo de nucleo_editorial devolveu valor invalido. "
                    "Mantendo status 'ausente'.",
                    flush=True,
                )
        except Exception as exc:  # nunca falha a etapa por causa deste extra
            dados_saida["nucleo_editorial"] = None
            print(f"[INFO] Chamada de reparo de nucleo_editorial falhou: {exc}", flush=True)

    # Grupos A/B/C (sessao de refinamento pos-validacao empirica): rodam
    # sobre o roteiro FINAL (pos-expansao), nunca bloqueiam, so' anexam
    # avisos a job_metadata.json. `resumo` ainda esta em escopo desde
    # `_executar_fase_pesquisa` - e' o corpus de fontes escritas do Grupo A.
    nomes_nao_confirmados = detectar_nomes_suspeitos(dados_saida["roteiro_md"], resumo)
    titulos_possivel_divergencia = detectar_titulos_divergentes(
        dados_saida.get("nucleo_editorial"), dados_saida.get("titulos")
    )
    numeros_sem_derivacao = detectar_numeros_sem_derivacao(dados_saida["roteiro_md"])

    (pasta_projeto / "roteiro.md").write_text(dados_saida["roteiro_md"], encoding="utf-8")
    (pasta_projeto / "titulos_sugeridos.json").write_text(
        json.dumps(
            {"titulos": dados_saida["titulos"], "descricoes": dados_saida["descricoes"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    tempo_geracao_s = round(time.monotonic() - inicio, 1)

    tokens_input_total = tokens_input + tokens_cache_criados + tokens_cache_lidos
    cache_hit_rate = round(tokens_cache_lidos / tokens_input_total, 4) if tokens_input_total else 0.0

    custo_input_normal = (tokens_input / 1_000_000) * CUSTO_INPUT_POR_MILHAO_USD
    custo_cache_write = (tokens_cache_criados / 1_000_000) * (
        CUSTO_INPUT_POR_MILHAO_USD * MULTIPLICADOR_CACHE_WRITE
    )
    custo_cache_read = (tokens_cache_lidos / 1_000_000) * (
        CUSTO_INPUT_POR_MILHAO_USD * MULTIPLICADOR_CACHE_READ
    )
    custo_estimado_usd = round(
        custo_input_normal
        + custo_cache_write
        + custo_cache_read
        + (tokens_output / 1_000_000) * CUSTO_OUTPUT_POR_MILHAO_USD
        + web_searches_usadas * CUSTO_WEB_SEARCH_POR_BUSCA_USD,
        4,
    )
    _gravar_debug_cache_log(pasta_projeto, chamadas_debug, cache_hit_rate)

    job_metadata = {
        "perfil_usado": perfil,
        "idioma": idioma,
        "modelo": modelo,
        "web_searches_usadas": web_searches_usadas,
        "tokens_input_total": tokens_input_total,
        "tokens_input_nao_cacheado": tokens_input,
        "tokens_cache_criados": tokens_cache_criados,
        "tokens_cache_lidos": tokens_cache_lidos,
        "cache_hit_rate": cache_hit_rate,
        "tokens_output": tokens_output,
        "custo_estimado_usd": custo_estimado_usd,
        "tempo_geracao_s": tempo_geracao_s,
        "data_geracao": datetime.now(timezone.utc).isoformat(),
        "pergunta_promessa": dados_saida["pergunta_promessa"],
        "palavras_narradas": palavras_narradas,
        "palavras_alvo": palavras_alvo,
        "duracao_alvo_minutos": duracao_alvo_minutos,
        # Contagens de caracteres: puramente INFORMATIVAS a partir daqui -
        # nao entram mais no calculo de ratio_tamanho nem em nenhuma
        # decisao do pipeline (Problema 2 - len() com espacos/markdown/
        # notas media a coisa errada). ratio_tamanho e' medido em palavras
        # narradas (ver contar_palavras_narradas), comparado contra
        # palavras_alvo.
        "caracteres_alvo_min_informativo": caracteres_alvo_min,
        "caracteres_alvo_max_informativo": caracteres_alvo_max,
        "caracteres_roteiro_com_espacos_informativo": len(dados_saida["roteiro_md"]),
        "ratio_tamanho": ratio_tamanho,
        "stop_reason_final": stop_reason_final,
        "numero_expansoes": len(expansoes),
        "nucleo_editorial": dados_saida.get("nucleo_editorial"),
        # "ok" (veio valido do modelo na saida original), "reparado"
        # (invalido/ausente na saida original, corrigido pela chamada de
        # reparo) ou "ausente" (reparo tambem falhou/nao produziu valor
        # valido - a tela de thumbnail deve avisar explicitamente que
        # entrou em modo fallback quando ler este status, CLAUDE.md
        # secao 5.4.1/5.85).
        "nucleo_editorial_status": nucleo_editorial_status,
    }
    if expansoes:
        job_metadata["expansoes"] = expansoes
    # Grupos A/B/C - sempre gravados (mesmo vazios) para a tela de revisao
    # nao depender de campo ausente; o template so' renderiza banner quando
    # a lista correspondente nao esta vazia.
    job_metadata["nomes_nao_confirmados"] = nomes_nao_confirmados
    job_metadata["titulos_possivel_divergencia"] = titulos_possivel_divergencia
    job_metadata["numeros_sem_derivacao"] = numeros_sem_derivacao
    if cache_hit_rate < 0.5:
        job_metadata["aviso_cache"] = (
            "Cache hit rate baixo (< 0.5) pode indicar breakpoints mal "
            "posicionados. Ver debug_cache.log."
        )
    if ratio_tamanho < 1.0:
        job_metadata["aviso_tamanho"] = (
            f"Roteiro gerado abaixo do alvo ({ratio_tamanho * 100:.0f}% de "
            f"{palavras_alvo} palavras narradas). stop_reason da chamada "
            f"final: {stop_reason_final}."
        )
        justificativa_tamanho = dados_saida.get("justificativa_tamanho")
        if isinstance(justificativa_tamanho, str) and justificativa_tamanho.strip():
            job_metadata["justificativa_tamanho"] = justificativa_tamanho.strip()
    (pasta_projeto / "job_metadata.json").write_text(
        json.dumps(job_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if caminho_feedback.exists():
        caminho_feedback.unlink()

    emitir_progresso(
        100.0,
        f"Roteiro gerado com sucesso ({len(dados_saida['titulos'])} titulos sugeridos)",
        sucesso=True,
    )
    return {"sucesso": True, "job_metadata": job_metadata}


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/3_gerar_roteiro.py <caminho_da_pasta_do_projeto>")
        sys.exit(1)

    pasta_projeto = Path(sys.argv[1])
    resultado = gerar_roteiro(pasta_projeto)

    if not resultado.get("sucesso", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
