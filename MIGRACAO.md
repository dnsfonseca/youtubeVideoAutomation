# Migração do broll_alfa para Broll Foundry

**Status: Concluída na Sessão 1 (agosto/2026)**

## Contexto histórico

O Broll Foundry começou como evolução do projeto `broll_alfa`. A migração
aconteceu na Sessão 1, aproveitando estrutura de servidor, templates,
detecção de projeto por marcador e convenções Windows-safe já validadas
naquele projeto.

## O que foi preservado

- Estrutura Flask (`server.py`)
- Detecção de projeto por marcador (`entrada/links.txt` ou `job.json`)
- Templates base (`base.html`, `home.html`, `ajustes.html`,
  `novo_projeto.html`, `status.html`)
- Convenções Windows-safe (UTF-8, subprocess sem shell, nomes ASCII)
- Suíte de testes + subagentes `test-writer`/`test-runner`

## O que evoluiu depois

Todo o pipeline de vídeo (scripts 1-6), sistema de perfis, TTS, uploads,
modo de fontes separadas, design system e as demais telas de projeto
foram construídos do zero nas sessões seguintes.

Para arquitetura atual, ver `CLAUDE.md`.
Para histórico de sessões e próximos passos, ver `prompt_abertura.md`.
