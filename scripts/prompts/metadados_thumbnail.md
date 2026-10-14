Analise o roteiro fornecido (a versao aprovada, ja revisada por humano) e
produza os metadados de publicacao do video e o briefing de composicao da
thumbnail.

Quando fornecidos, o titulo aprovado do video e o nucleo editorial (Etapa
3) aparecem ANTES do roteiro, como contexto de ancoragem geral - use-os
como ponto de partida do eixo editorial do video, nunca como texto a
repetir literalmente.

Tambem aparece, quando disponivel, o `elemento_principal` - o elemento
visual concreto que o Headline Engine ja identificou como o CONCEITO
VISUAL deste video (extraido ANTES desta chamada, numa etapa dedicada).
Este e' o dado mais confiavel de ancoragem visual que voce recebe: e' o
elemento que a THUMBNAIL final precisa mostrar. **`background_prompt`
(abaixo) e' obrigatoriamente ancorado nele quando fornecido** - nunca em
outro detalhe do roteiro que nao o sustente.

## REGRA FUNDAMENTAL (vale para background_prompt e secondary)

Um detalhe do roteiro so' deve entrar na thumbnail se ele reforcar (1) a
promessa do titulo aprovado, ou (2) o `elemento_principal` fornecido -
nunca so' porque e' um detalhe chamativo, visual ou memoravel isolado no
meio da narrativa. Um objeto mencionado en passant, um documento
periferico, uma curiosidade lateral - se nenhum deles sustenta a pergunta
que o TITULO promete responder nem o elemento principal fornecido, ele
nao aparece na thumbnail, mesmo que seja um detalhe interessante do
roteiro. Prefira um briefing mais simples e fielmente ancorado a um
briefing "rico em detalhes" que se desvia do que o video realmente
promete.

## description

Descricao para o campo de descricao do YouTube: 2-4 paragrafos curtos,
resume o caso/tema sem entregar a resolucao inteira (preserva o gancho de
assistir), no mesmo idioma do roteiro.

## tags

Lista de palavras-chave relevantes pra busca do YouTube (nomes, local,
tema, genero de conteudo). Sem hashtag, sem duplicar o titulo inteiro.

## thumbnail

Briefing pra composicao automatica da thumbnail (16:9). O sujeito (pessoa)
sempre vem de foto real enviada pelo usuario - NUNCA gerado por IA; o rosto
e' preservado pela API de composicao a partir dessa foto. O restante da
cena (fundo/atmosfera) e' descrito por `background_prompt` abaixo e vira
parte do mesmo prompt de composicao - por isso este campo e' consumido de
verdade, nunca opcional.

- `subject_name`: nome completo da pessoa CENTRAL DO CASO - a vitima, a
  suspeita/investigada, ou quem protagoniza os fatos narrados. NUNCA o
  apresentador, reporter ou jornalista que so' narra a materia nos
  videos-fonte, mesmo que o rosto dele apareca com mais frequencia nos
  clipes (fontes de telejornal tem o apresentador na tela o tempo todo -
  isso nao faz dele o sujeito da thumbnail). String vazia se o video nao
  tem uma pessoa central clara (caso mais generico/ambiental).
- `headline`: texto principal da thumbnail. Curto, de alto impacto,
  MAIUSCULAS opcionais (o template decide), no mesmo idioma do roteiro.

  **Regra central: o headline abre uma lacuna de curiosidade, nao entrega
  informacao.** Um headline que resume o que aconteceu satisfaz a
  curiosidade antes do clique e reduz CTR - o espectador ja sabe o
  suficiente pra nao precisar assistir. Um headline que levanta uma
  pergunta sem resposta obriga a assistir pra saber. Ex: "41 MINUTES
  INSIDE HER HOME" informa (o espectador ja sabe o fato central, resta so'
  detalhe) e nao gera clique; "WHAT HE FOUND INSIDE HER HOME" abre a
  lacuna (o que foi encontrado? por que importa?) e gera.

  Formula de 4 camadas pra pensar o headline + secondary juntos (nem
  sempre as 4 aparecem explicitas no texto final - e' um guia de
  construcao, nao um template rigido a preencher literalmente):
  1. **Contexto** - situa o espectador no que aconteceu (geralmente vai
     no `secondary`, nao no headline)
  2. **Autoridade** - fonte/orgao/registro que da credibilidade ao fato
     (pode aparecer no `secondary` como etiqueta, ex: "POLICE REPORT",
     "COURT RECORDS")
  3. **Emocao** - o peso humano do caso (tom, nao necessariamente
     palavra explicita)
  4. **Misterio** - a pergunta sem resposta que so' o video responde
     (vai no `headline` - e' o elemento dominante)

  Nao repita o titulo inteiro - e' uma chamada visual, nao uma legenda.
- `emphasis_word`: UMA palavra ou expressao curta que precisa aparecer
  LITERALMENTE dentro de `headline` (copie exatamente) - e' a palavra que
  o template vai destacar em tamanho gigante. Normalmente e' o elemento
  de misterio (camada 4) ou o detalhe mais chocante sem ser sensacionalista.
  Deixe vazio se nenhuma palavra do headline merece esse destaque isolado.
- `secondary`: texto secundario curto (subtitulo/etiqueta) - normalmente
  carrega contexto (camada 1) e/ou autoridade (camada 2), pode ficar
  vazio.
- `accent`: cor de destaque - exatamente um de "red", "amber", "blue"
  (escolha pelo tom do caso: red = violencia/urgencia, amber =
  investigacao/misterio, blue = frio/institucional/policial).
- `censor`: `true` se `headline` ou `secondary` contiver uma palavra
  sensivel que deveria aparecer parcialmente censurada (ex: K*LLER),
  `false` caso contrario.
- `background_prompt`: descricao visual curta (em ingles) do fundo/cenario
  ideal pra thumbnail - **campo obrigatorio, nunca deixe vazio.** Quando
  `elemento_principal` foi fornecido, ANCORE esta descricao nele - o
  elemento precisa aparecer (ou estar claramente presente) na cena
  descrita, nunca substituido por outro detalhe do roteiro so' porque e'
  mais chamativo. Sem `elemento_principal` disponivel (projeto antigo, ou
  a etapa que o extrai falhou), ancore no titulo aprovado/nucleo
  editorial como sempre foi feito. E' combinado com o resto do briefing
  (template de composicao + sujeito) e mandado pra API de geracao de
  imagem. Descreva CENA: local, objetos presentes, atmosfera, iluminacao -
  nunca pessoa real identificavel (o sujeito e' sempre a foto real
  enviada, nunca gerado), nunca texto/letras/numeros/logotipo dentro da
  imagem (isso e' descrito separadamente no briefing de composicao). NUNCA
  inclua o texto de `headline` nem de `secondary` dentro de
  `background_prompt` - e' so' descricao de cenario/composicao visual,
  nunca texto a ser renderizado.
  Exemplo de forma adequada (adapte pro caso real, nunca copie literal):
  "A dimly lit suburban street at night, a doorbell camera mounted beside
  the front door, police cruiser lights reflecting off wet pavement,
  moody atmosphere."

### Exemplos de headline/secondary

Exemplos de FORMA (a lacuna de curiosidade, o peso das palavras, o
tamanho), nao de conteudo - adapte pro caso real e pro idioma do roteiro,
nunca copie o texto literal:

| headline (misterio, dominante) | secondary (contexto/autoridade) |
|---|---|
| WHAT HE FOUND INSIDE HER HOME | Neighbors called 911 at 2 AM |
| THE CALL SHE MADE BEFORE SHE VANISHED | Last seen: March 4, 2019 |
| WHY POLICE REOPENED THE CASE | New evidence, 12 years later |
| THE LIE THAT UNRAVELED IN COURT | Trial transcript, day 3 |
| WHAT THE TEXTS REVEALED | Recovered from a deleted phone |
| HE WAS THE LAST PERSON TO SEE HER | Investigators still have questions |
| THE DETAIL POLICE KEPT SECRET | Case file, released after appeal |
| WHAT SHE SAW THROUGH THE WINDOW | Only witness statement on record |

Note o padrao: nenhum headline entrega o desfecho. Todos terminam numa
pergunta implicita que so' o video responde.

Entregue o resultado atraves da tool estruturada fornecida.
