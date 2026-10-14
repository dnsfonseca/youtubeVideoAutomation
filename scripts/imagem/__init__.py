"""Pacote de geracao de imagem (Etapa 7 - thumbnail). Hoje so' existe
`scripts/imagem/openai.py`, com uma unica funcao real de composicao
(`gerar_composicao` - manda o briefing exportavel + as fotos originais dos
sujeitos pro `/v1/images/edits` do gpt-image-2). Consumida direto por
`server.py` (`from scripts.imagem import openai as imagem_openai`) - sem
fabrica/registro de provedores, porque so' existe um provedor real.

O modo antigo de gerar SO' o fundo (`gerar()`, `/v1/images/generations`) e
o provedor "nenhum" (sem geracao real) foram removidos na sessao de
simplificacao da Etapa 7 (ver HISTORICO_BUGS.md) - existiam so' pra
alimentar os 5 templates de composicao via Pillow, tambem removidos."""
