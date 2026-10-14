// Preview de audio da voz TTS selecionada na tela de revisao (CLAUDE.md
// secao 5.6) - toca um trecho curto (Google, sintetizado on-demand) ou o
// preview_url pronto da API (DarkPlanner - scripts/tts/darkplanner.py)
// antes do usuario aprovar o roteiro. Reage tanto a troca manual do
// <select> de voz quanto a repopulacao automatica das opcoes feita por
// revisao.js (cascata provedor -> voz via GET /api/vozes/<provedor>/<idioma>)
// - um MutationObserver no <select id="tts_voz"> cobre esse segundo caso,
// ja que revisao.js nao dispara nenhum evento customizado ao terminar de
// popular as opcoes.
//
// Falha de geracao do preview do Google BLOQUEIA o submit do formulario
// quando a origem do audio escolhida e' "tts" (o backend valida a mesma
// coisa de novo em server.py:aprovar_roteiro - nunca confia so' nesta
// checagem do lado do cliente). Para DarkPlanner isso NAO se aplica: o
// preview_url vem de um CDN externo (ElevenLabs) que o navegador pode
// falhar em carregar por bloqueio de referer/CORS - isso e' so' o preview
// quebrando, a geracao real do audio (chamada server-side, sem CORS de
// navegador) continua funcionando normalmente. Ver onErroCarregarAudio
// abaixo: so marca a voz indisponivel (bloqueia submit) quando o backend
// responde disponivel=false; falha do <audio> em si nunca bloqueia.
(function () {
  var selectVoz = document.getElementById("tts_voz");
  var selectProvedor = document.getElementById("tts_provedor");
  if (!selectVoz) return;

  var container = document.getElementById("preview-voz-container");
  var carregando = document.getElementById("preview-voz-carregando");
  var audio = document.getElementById("preview-voz-audio");
  var erroBox = document.getElementById("preview-voz-erro");
  var erroMsg = document.getElementById("preview-voz-erro-msg");

  function ocultarTudo() {
    if (carregando) carregando.classList.add("oculto");
    if (audio) audio.classList.add("oculto");
    if (erroBox) erroBox.classList.add("oculto");
  }

  function onErroCarregarAudio() {
    // O backend disse que a URL existia, mas o navegador nao conseguiu
    // tocar (CDN externo bloqueando referer/CORS, link expirado, etc).
    // NAO marca vozIndisponivel - a geracao real acontece server-side e
    // nao passa por essa restricao de navegador.
    if (audio) audio.classList.add("oculto");
    if (erroMsg) erroMsg.textContent = "Preview indisponivel (nao foi possivel carregar o audio). A voz continua utilizavel para gerar a narracao.";
    if (erroBox) erroBox.classList.remove("oculto");
  }

  if (audio) audio.addEventListener("error", onErroCarregarAudio);

  function carregarPreview(vozId) {
    if (!vozId || !container) return;
    var provedor = selectProvedor ? selectProvedor.value : "google";
    container.classList.remove("oculto");
    ocultarTudo();
    if (carregando) carregando.classList.remove("oculto");
    selectVoz.dataset.vozIndisponivel = "false";

    fetch("/api/preview_voz/" + encodeURIComponent(vozId) + "?provedor=" + encodeURIComponent(provedor))
      .then(function (resposta) {
        return resposta.json();
      })
      .then(function (dados) {
        ocultarTudo();
        if (dados.disponivel) {
          if (audio) {
            audio.src = dados.url;
            audio.classList.remove("oculto");
          }
        } else {
          // Google: "indisponivel" reflete falha real de sintese (mesma
          // voz que seria usada na geracao) - bloqueia submit. DarkPlanner:
          // so significa que a API nao devolveu preview_url pra essa voz -
          // nao diz nada sobre a geracao real, entao nao bloqueia.
          if (provedor !== "darkplanner") {
            selectVoz.dataset.vozIndisponivel = "true";
          }
          if (erroMsg) erroMsg.textContent = dados.erro || "Voz indisponivel no momento.";
          if (erroBox) erroBox.classList.remove("oculto");
        }
      })
      .catch(function () {
        ocultarTudo();
        if (provedor !== "darkplanner") {
          selectVoz.dataset.vozIndisponivel = "true";
        }
        if (erroMsg) erroMsg.textContent = "Nao foi possivel carregar o preview desta voz.";
        if (erroBox) erroBox.classList.remove("oculto");
      });
  }

  selectVoz.addEventListener("change", function () {
    carregarPreview(selectVoz.value);
  });

  // revisao.js repopula as <option> de #tts_voz de forma assincrona
  // (troca de provedor, ou carga inicial da pagina) sem disparar "change"
  // - observar mutacoes na lista de opcoes cobre esses casos tambem.
  var observer = new MutationObserver(function () {
    carregarPreview(selectVoz.value);
  });
  observer.observe(selectVoz, { childList: true });

  // Bloqueio no submit (segunda camada, alem do backend): so' impede
  // enviar se a origem do audio escolhida for "tts" e a voz atual estiver
  // marcada indisponivel - nao interfere com os fluxos de upload/depois.
  var formRevisao = document.getElementById("form-revisao");
  if (formRevisao) {
    formRevisao.addEventListener("submit", function (evento) {
      var origemSelecionada = document.querySelector('input[name="origem_audio"]:checked');
      var origemEhTts = origemSelecionada && origemSelecionada.value === "tts";
      if (origemEhTts && selectVoz.dataset.vozIndisponivel === "true") {
        evento.preventDefault();
        if (erroBox) erroBox.classList.remove("oculto");
        container.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  }
})();
