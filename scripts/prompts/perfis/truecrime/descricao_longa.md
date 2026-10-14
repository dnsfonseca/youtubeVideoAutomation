# True Crime

## Para que serve

O perfil **True Crime** gera roteiros sobre casos criminais reais —
homicídios, desaparecimentos, fraudes de grande escala, sequestros — com
o rigor factual e o cuidado editorial que esse tipo de conteúdo exige.
Cada afirmação factual do roteiro sai com nota de rodapé indicando de
onde veio (o vídeo-fonte e o minuto exato, ou a matéria jornalística
específica), e o modelo é instruído a nunca inventar detalhe algum para
deixar a história mais redonda.

## Bom para

Canais de true crime no estilo "faceless" já consolidado no YouTube em
inglês (e crescente em outros idiomas) — narração sobre b-roll,
geralmente 12-25 minutos, cobrindo um caso por vídeo. Funciona bem tanto
para casos amplamente conhecidos (cobertura farta disponível) quanto
para casos menos conhecidos mas bem documentados localmente.

## Tom

Investigativo. O roteiro constrói o caso passo a passo, como uma
investigação real se desenrola, sem tratar a morte ou o sofrimento das
vítimas como espetáculo. Vocabulário sóbrio — evita adjetivos
sensacionalistas ("chocante", "bizarro") deixando os fatos reais
carregarem o peso dramático da história.

## Cuidados especiais deste perfil

- **Revisão factual humana é obrigatória antes de aprovar o roteiro.**
  Mesmo com busca web e prompt cuidadoso, o modelo ocasionalmente
  confunde detalhes factuais em casos reais (troca de nome, confusão
  entre "indiciado" e "condenado", timestamp de nota de rodapé
  impreciso). A tela de revisão existe justamente para isso — leia com
  atenção antes de aprovar, especialmente as notas marcadas
  `[⚠ single-source]` e `[⚠ conflict]`.
- **Terminologia jurídica varia por idioma e é tratada com precisão.**
  O perfil injeta um bloco de regras jurídicas específico para o idioma
  escolhido (inglês americano, inglês britânico, português brasileiro,
  espanhol, ou alemão) — cada um define os termos processuais corretos
  (suspeito, indiciado, réu, condenado etc) e como usá-los sem afirmar
  culpa antes da condenação formal.
- **Presunção de inocência é aplicada como princípio editorial geral**,
  não só nos casos óbvios — qualquer pessoa mencionada sem condenação
  definitiva recebe qualificadores ("suposto", "de acordo com a
  acusação") no roteiro gerado.
- **Custo estimado por vídeo: $3 a $15**, dominado pelas chamadas de
  busca web da API do Claude (o modelo tipicamente faz várias buscas
  por roteiro para checar e corroborar fatos) mais o custo normal de
  tokens.

## Quando NÃO usar este perfil

- **Casos fictícios ou especulativos** ("e se um crime assim
  acontecesse...") — este perfil é calibrado para rigor factual sobre
  eventos reais; usar para ficção produz um roteiro cheio de notas de
  rodapé desnecessárias e tom incompatível com narrativa inventada.
- **Cobertura de caso em andamento sem verificação cuidadosa da fase
  processual atual** — casos muito recentes (dias ou poucas semanas)
  tendem a ter cobertura jornalística ainda inconsistente sobre o
  status exato (indiciado vs. denunciado, por exemplo); considere
  esperar a cobertura se estabilizar ou revisar com atenção redobrada
  antes de publicar.
- **Conteúdo tabloide sem compromisso com precisão** — se o objetivo é
  puro entretenimento sensacionalista sem preocupação com rigor
  factual, este não é o perfil certo; a arquitetura inteira dele
  (notas de rodapé obrigatórias, marcação de conflito/fonte única,
  bloco jurídico) existe para produzir o oposto disso.
