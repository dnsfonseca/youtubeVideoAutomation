"""Fontes jornalisticas preferidas do perfil Atualidades Narrativas, por
idioma alvo do roteiro (CLAUDE.md secao 3.1). Usadas pelo loader
(scripts/prompts/loader.py) para injetar o placeholder {FONTES_PREFERIDAS}
no sistema.md deste perfil. Veiculos de cobertura internacional/factual
com historico de apuracao seria, sem tabloides."""

FONTES = {
    "en-US": [
        "Reuters (reuters.com)",
        "Associated Press (apnews.com)",
        "BBC News (bbc.com)",
        "Al Jazeera English (aljazeera.com)",
        "The New York Times (nytimes.com)",
        "The Washington Post (washingtonpost.com)",
        "NPR (npr.org)",
    ],
    "en-GB": [
        "BBC News (bbc.co.uk)",
        "The Guardian (theguardian.com)",
        "Reuters (reuters.com)",
        "Financial Times (ft.com)",
        "The Times (thetimes.co.uk)",
    ],
    "pt-BR": [
        "Reuters Brasil (reuters.com/brazil)",
        "G1 (g1.globo.com)",
        "Folha de S.Paulo (folha.uol.com.br)",
        "Deutsche Welle Brasil (dw.com/pt-br)",
        "BBC Brasil (bbc.com/portuguese)",
        "Nexo Jornal (nexojornal.com.br)",
    ],
    "es": [
        "Reuters en Español (reuters.com/es)",
        "BBC Mundo (bbc.com/mundo)",
        "El País (elpais.com)",
        "Deutsche Welle Español (dw.com/es)",
        "Agencia EFE (efe.com)",
    ],
    "de": [
        "Deutsche Welle (dw.com)",
        "Tagesschau (tagesschau.de)",
        "Der Spiegel (spiegel.de)",
        "Süddeutsche Zeitung (sueddeutsche.de)",
        "Zeit Online (zeit.de)",
    ],
}
