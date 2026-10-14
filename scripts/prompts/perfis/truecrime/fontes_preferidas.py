"""Fontes jornalisticas preferidas por idioma para o perfil True Crime
(CLAUDE.md secao 3.1). Injetadas no prompt via {FONTES_PREFERIDAS} - o
modelo prioriza (nao se restringe exclusivamente) essas fontes na busca
web e na atribuicao de notas de rodape."""

FONTES = {
    "en-US": [
        "CNN (cnn.com)",
        "The New York Times (nytimes.com)",
        "Reuters (reuters.com)",
        "Associated Press (apnews.com)",
        "ABC News (abcnews.go.com)",
        "NBC News (nbcnews.com)",
        "The Washington Post (washingtonpost.com)",
    ],
    "en-GB": [
        "BBC (bbc.co.uk)",
        "The Guardian (theguardian.com)",
        "Sky News (news.sky.com)",
        "Reuters (reuters.com)",
        "The Times (thetimes.co.uk)",
    ],
    "pt-BR": [
        "G1 (g1.globo.com)",
        "Folha de S.Paulo (folha.uol.com.br)",
        "UOL (uol.com.br)",
        "Estadao (estadao.com.br)",
        "R7 (r7.com)",
        "CNN Brasil (cnnbrasil.com.br)",
    ],
    "es": [
        "El Pais (elpais.com)",
        "El Mundo (elmundo.es)",
        "ABC Espana (abc.es)",
        "Clarin (clarin.com)",
        "La Nacion (lanacion.com.ar)",
    ],
    "de": [
        "Der Spiegel (spiegel.de)",
        "Sueddeutsche Zeitung (sueddeutsche.de)",
        "Die Zeit (zeit.de)",
        "Frankfurter Allgemeine (faz.net)",
        "Tagesschau (tagesschau.de)",
    ],
}
