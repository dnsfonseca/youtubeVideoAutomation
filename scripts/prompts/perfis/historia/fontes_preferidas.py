"""Fontes academicas e museologicas preferidas do perfil Historia, por
idioma alvo do roteiro (CLAUDE.md secao 3.1). Usadas pelo loader
(scripts/prompts/loader.py) para injetar o placeholder {FONTES_PREFERIDAS}
no sistema.md deste perfil."""

FONTES = {
    "en-US": [
        "Encyclopedia Britannica (britannica.com)",
        "Stanford Encyclopedia of Philosophy (plato.stanford.edu)",
        "JSTOR (jstor.org)",
        "History.com",
        "United States Holocaust Memorial Museum (ushmm.org)",
        "Imperial War Museum (iwm.org.uk)",
        "Yad Vashem (yadvashem.org)",
        "Smithsonian Magazine (smithsonianmag.com)",
        "The National Archives (archives.gov)",
    ],
    "en-GB": [
        "Encyclopedia Britannica (britannica.com)",
        "BBC History (bbc.co.uk/history)",
        "Imperial War Museum (iwm.org.uk)",
        "The National Archives UK (nationalarchives.gov.uk)",
        "History Today (historytoday.com)",
        "Stanford Encyclopedia of Philosophy (plato.stanford.edu)",
    ],
    "pt-BR": [
        "Enciclopédia Britânica em português (britannica.com/pt)",
        "Arquivo Nacional (arquivonacional.gov.br)",
        "Museu do Holocausto Curitiba (museudoholocausto.org.br)",
        "Revista de História (revistadehistoria.com.br)",
        "SciELO (scielo.br) — para artigos acadêmicos brasileiros",
        "Fundação Getúlio Vargas / CPDOC (cpdoc.fgv.br)",
    ],
    "es": [
        "Encyclopedia Britannica en español (britannica.com/es)",
        "Museo Nacional del Prado — sección histórica (museodelprado.es)",
        "Real Academia de la Historia (rah.es)",
        "El País — sección cultura/historia",
        "National Geographic España (nationalgeographic.com.es)",
    ],
    "de": [
        "Encyclopedia Britannica (britannica.com)",
        "Deutsches Historisches Museum (dhm.de)",
        "Bundesarchiv (bundesarchiv.de)",
        "Yad Vashem (yadvashem.org)",
        "Der Spiegel — sección Geschichte (spiegel.de/geschichte)",
    ],
}
