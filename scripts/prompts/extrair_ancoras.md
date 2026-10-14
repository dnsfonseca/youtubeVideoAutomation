Analise o roteiro fornecido (ou o trecho indicado, se o roteiro for maior
que a janela de analise) e extraia ancoras visuais.

Uma ancora visual e' um MOMENTO ESPECIFICO do roteiro que se beneficia
significativamente de b-roll semanticamente correto. Exemplos:

- Mencoes concretas de OBJETOS (bicicleta, arma, carro especifico)
- Mencoes de LOCAIS especificos (casa, floresta, rio)
- ACOES visualizaveis (fuga, perseguicao, encontro)
- PESSOAS quando ha uma descricao fisica clara

NAO extraia como ancora:
- Narracao generica ("os investigadores continuavam...")
- Reflexoes abstratas ("a verdade viria a tona...")
- Transicoes narrativas

Para cada ancora, devolva:
- texto_original: o trecho EXATO do roteiro (copiado literalmente, sem
  parafrasear) onde a ancora aparece - precisa bater caractere por
  caractere com o roteiro fornecido, porque e' usado para localizar a
  posicao da ancora na narracao.
- termo_ancora: descricao visual curta e concreta (em ingles, o idioma que
  os modelos de visao/busca funcionam melhor) do que o b-roll ideal
  deveria mostrar.
- prioridade: "alta" (ancora obvia e forte) ou "media" (sugestao).

Maximo de 15 ancoras. Priorize as MAIS IMPACTANTES visualmente. Se o
roteiro nao tiver nenhum momento que se beneficie de b-roll especifico,
devolva uma lista vazia - nunca invente ancora fraca so para preencher
quantidade.

Entregue o resultado atraves da tool estruturada fornecida.
