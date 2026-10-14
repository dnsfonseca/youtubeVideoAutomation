# Broll Foundry

Ferramenta local (roda no seu Windows, nunca na nuvem) que automatiza a
produção de vídeos "faceless" pra YouTube. Especialmente pensada pra
nichos de true crime, história e atualidades narrativas.

## O que faz

Pipeline completa, do link até o MP4 pronto pra upload:

1. Baixa vídeos-fonte do YouTube
2. Transcreve com `faster-whisper` (local, na sua GPU)
3. Gera roteiro original via Claude, com busca web e notas de rodapé de origem
4. Pausa pra você revisar e aprovar o roteiro
5. Sintetiza a narração (Google TTS ou DarkPlanner/ElevenLabs) ou usa um áudio seu
6. Corta clipes de b-roll dos vídeos-fonte, com Ken Burns e remoção de marca d'água
7. Opcionalmente sincroniza os clipes com o roteiro via IA e/ou deixa você reorganizar na mão
8. Monta o vídeo final com legendas embutidas (e legendas queimadas + música de fundo opcionais)
9. Gera candidatos de thumbnail (rosto identificado por IA + cenário) pra você escolher um template pronto

Também dá pra pular a maior parte disso: importar vídeos já prontos (ex:
gerados no DarkPlanner Flow/Veo3) só pra montagem, ou subir seu próprio
roteiro pronto e pular a geração via IA.

## Requisitos mínimos

- Windows 10/11 x64
- Python 3.11 (com o "py launcher" instalado)
- GPU NVIDIA com CUDA 12+ (qualquer GTX 1060 ou RTX em diante)
- 16 GB RAM (32 GB recomendado)
- Espaço em disco livre — projetos com vídeo-fonte + clipes ocupam alguns GB cada,
  mais ~176MB baixados uma única vez no primeiro projeto que chega na geração
  de thumbnail (modelo de remoção de fundo)

## Instalação rápida

Ver [docs/INSTALACAO.md](docs/INSTALACAO.md) pra passo a passo completo.

Resumindo:

1. Clone o repositório
2. Copie `.env.example` pra `.env` e preencha `ANTHROPIC_API_KEY` e
   `PROJETOS_DIR` — ver [docs/CHAVES_API.md](docs/CHAVES_API.md)
3. Rode `iniciar.bat --instalar-deps` (só na primeira vez — instala
   tudo e já sobe o servidor)

## Primeiro projeto

Ver [docs/PRIMEIRO_PROJETO.md](docs/PRIMEIRO_PROJETO.md) pra um tutorial ponta a ponta.

## Documentação

- [docs/INSTALACAO.md](docs/INSTALACAO.md) — passo a passo de instalação
- [docs/PRIMEIRO_PROJETO.md](docs/PRIMEIRO_PROJETO.md) — tutorial completo do primeiro vídeo
- [docs/FLUXO_APLICACAO.md](docs/FLUXO_APLICACAO.md) — o que cada tela faz
- [docs/CHAVES_API.md](docs/CHAVES_API.md) — como conseguir cada chave de API
- [docs/CUSTOS.md](docs/CUSTOS.md) — quanto custa cada vídeo
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — erros comuns e como resolver
- [CLAUDE.md](CLAUDE.md) — arquitetura e decisões de produto (referência técnica; algumas seções estão desatualizadas em relação ao código mais recente)

## Suporte

Projeto privado, uso restrito ao grupo. Suporte pelo canal interno de sempre.

## Privacidade

Produto 100% local. Seus vídeos, transcrições e chaves de API ficam só
na sua máquina — não existe servidor do Broll Foundry pra onde algo seja
enviado.

## Licença

Uso restrito ao grupo. Não redistribuir. Ver [LICENSE.txt](LICENSE.txt).
