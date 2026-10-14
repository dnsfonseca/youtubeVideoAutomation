// Tela de reorganizacao manual de clipes (Feature B): timeline horizontal
// com drag livre (dentro da timeline ou do banco de clipes pra timeline),
// cursor sincronizado com o player de narracao (TTS), preview de video sob
// demanda, e disparo da montagem final.
(function () {
  var cfg = window.BrollFoundryReorganizar;
  if (!cfg) return;

  var pxPorSegundo = cfg.pxPorSegundo || 10;

  var ttsPlayer = document.getElementById("tts-player");
  var tempoCorrente = document.getElementById("tempo-corrente");
  var timelineScroll = document.getElementById("timeline-scroll");
  var timelineTrack = document.getElementById("timeline-track");
  var timelineCursor = document.getElementById("timeline-cursor");
  var bancoGrid = document.getElementById("banco-grid");
  var buscaInput = document.getElementById("busca-clipes");
  var avisoReorg = document.getElementById("aviso-reorg");
  var avisoPreview = document.getElementById("aviso-preview");
  var previewPlayer = document.getElementById("preview-player");
  var btnAtualizarPreview = document.getElementById("btn-atualizar-preview");
  var btnContinuar = document.getElementById("btn-continuar");

  function formatarTempo(segundos) {
    segundos = Math.max(0, Math.floor(segundos || 0));
    var m = Math.floor(segundos / 60);
    var s = segundos % 60;
    return (m < 10 ? "0" + m : m) + ":" + (s < 10 ? "0" + s : s);
  }

  function mostrarAviso(el, texto) {
    if (!el) return;
    el.textContent = texto;
    el.style.display = texto ? "" : "none";
  }

  // --- Indice de posicoes (GRUPO A da sessao de correcoes UX) -------------
  // Le data-posicao/data-inicio-s/data-fim-s de cada card UMA VEZ no
  // carregamento da tela (nao recalculado a cada tick de timeupdate, que e'
  // o padrao antigo - reparsear o DOM inteiro varias vezes por segundo
  // durante a reproducao). inicio-s/fim-s ja vem corretos do servidor
  // (`_montar_timeline_reorganizacao`, com o fallback de duracao aproximada
  // ja resolvido la' - a marcacao visual de "aproximado" tambem e'
  // server-side, classe `.timeline-clipe-aproximado`). Indexado por
  // posicao para lookup O(1) a partir da tabela de swaps (GRUPO B) e do
  // cursor de reproducao (GRUPO D).
  var indicePosicoes = [];
  if (timelineTrack) {
    timelineTrack.querySelectorAll(".timeline-clipe").forEach(function (el) {
      var posicao = parseInt(el.dataset.posicao, 10);
      if (isNaN(posicao)) return;
      indicePosicoes[posicao] = {
        el: el,
        inicioS: parseFloat(el.dataset.inicioS) || 0,
        fimS: parseFloat(el.dataset.fimS) || 0,
      };
    });
  }

  // --- Audio da narracao pode nao existir (projeto ainda sem narracao.mp3,
  // ou origem_audio = upload que falhou) - os timestamps continuam vindo do
  // servidor normalmente, so' o "salto" do player fica inativo (GRUPO D).
  var audioIndisponivel = false;
  if (ttsPlayer) {
    ttsPlayer.addEventListener("error", function () {
      audioIndisponivel = true;
    });
  }

  function saltarPlayerPara(inicioS) {
    if (!ttsPlayer || audioIndisponivel || isNaN(inicioS)) return;
    try {
      ttsPlayer.currentTime = inicioS;
    } catch (e) {
      audioIndisponivel = true;
    }
  }

  // --- Destaque persistente (selecao vinda da tabela de swaps, GRUPO C) ---
  // Distinto do outline transiente do timeupdate (posicao atual de
  // reproducao) - fica ate outro card ser selecionado, mesmo com o player
  // pausado ou o audio indisponivel.
  var cardSelecionado = null;

  function selecionarCard(el) {
    if (cardSelecionado && cardSelecionado !== el) cardSelecionado.classList.remove("selecionado");
    cardSelecionado = el || null;
    if (cardSelecionado) cardSelecionado.classList.add("selecionado");
  }

  // Rola a timeline para CENTRALIZAR o card (nao so' o minimo necessario
  // para entrar na area visivel - diferente do auto-scroll por borda do
  // timeupdate abaixo) - para o card selecionado pela tabela ficar visivel
  // mesmo que a timeline ja estivesse rolada para outro trecho.
  function rolarParaCentro(el) {
    if (!timelineScroll || !el) return;
    var alvo = el.offsetLeft + el.offsetWidth / 2 - timelineScroll.clientWidth / 2;
    timelineScroll.scrollLeft = Math.max(0, alvo);
  }

  function irParaPosicao(posicao) {
    var entrada = indicePosicoes[posicao];
    if (!entrada) return;
    selecionarCard(entrada.el);
    rolarParaCentro(entrada.el);
    saltarPlayerPara(entrada.inicioS);
  }

  // --- Cursor sincronizado com o player de narracao ------------------------

  if (ttsPlayer && timelineTrack) {
    ttsPlayer.addEventListener("timeupdate", function () {
      var tempo = ttsPlayer.currentTime;
      if (tempoCorrente) tempoCorrente.textContent = formatarTempo(tempo);

      var posicaoPx = tempo * pxPorSegundo;
      if (timelineCursor) timelineCursor.style.left = posicaoPx + "px";

      if (timelineScroll) {
        var scrollLeft = timelineScroll.scrollLeft;
        var viewportRight = scrollLeft + timelineScroll.clientWidth;
        if (posicaoPx > viewportRight - 100) {
          timelineScroll.scrollLeft = posicaoPx - timelineScroll.clientWidth + 200;
        } else if (posicaoPx < scrollLeft + 50) {
          timelineScroll.scrollLeft = Math.max(0, posicaoPx - 100);
        }
      }

      indicePosicoes.forEach(function (entrada) {
        if (!entrada) return;
        var atual = tempo >= entrada.inicioS && tempo < entrada.fimS;
        entrada.el.style.outline = atual ? "2px solid var(--color-accent)" : "";
      });
    });
  }

  // Clique num clipe da timeline pula o player pra o inicio dele.
  if (timelineTrack && ttsPlayer) {
    timelineTrack.addEventListener("click", function (evento) {
      if (arrastando) return;
      var card = evento.target.closest(".timeline-clipe");
      if (!card) return;
      saltarPlayerPara(parseFloat(card.dataset.inicioS));
    });
  }

  // --- Tabela de swaps da Feature A: linha inteira clicavel (GRUPO B) -----
  // Salta o player, rola a timeline ate o card e destaca (persistente).
  document.querySelectorAll(".swap-row").forEach(function (linha) {
    linha.addEventListener("click", function () {
      var posicaoAttr = linha.dataset.posicao;
      if (posicaoAttr === "" || posicaoAttr === undefined) return;
      var posicao = parseInt(posicaoAttr, 10);
      if (isNaN(posicao)) return;
      irParaPosicao(posicao);
    });
  });

  // --- Drag and drop (timeline <-> timeline, banco -> timeline) -----------

  var arrastando = false;
  var origemArrastada = null;

  function indicePosicaoDoElemento(el) {
    var valor = parseInt(el.dataset.posicao, 10);
    return isNaN(valor) ? null : valor;
  }

  function enviarReordenacao(origem, destino) {
    if (origem === destino) return;
    mostrarAviso(avisoReorg, "Reorganizando...");
    fetch(cfg.urlReordenar, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origem: origem, destino: destino }),
    })
      .then(function (resposta) {
        return resposta.json().then(function (dados) {
          return { ok: resposta.ok, dados: dados };
        });
      })
      .then(function (resultado) {
        if (!resultado.ok || !resultado.dados.sucesso) {
          mostrarAviso(avisoReorg, (resultado.dados && resultado.dados.mensagem) || "Falha ao reorganizar.");
          return;
        }
        window.location.reload();
      })
      .catch(function () {
        mostrarAviso(avisoReorg, "Falha de rede ao reorganizar.");
      });
  }

  function ligarDragSource(el) {
    el.addEventListener("dragstart", function () {
      arrastando = true;
      origemArrastada = indicePosicaoDoElemento(el);
      el.classList.add("arrastando");
    });
    el.addEventListener("dragend", function () {
      arrastando = false;
      el.classList.remove("arrastando");
    });
  }

  function ligarDragAlvoTimeline(el) {
    el.addEventListener("dragover", function (evento) {
      evento.preventDefault();
      el.classList.add("drag-alvo");
    });
    el.addEventListener("dragleave", function () {
      el.classList.remove("drag-alvo");
    });
    el.addEventListener("drop", function (evento) {
      evento.preventDefault();
      el.classList.remove("drag-alvo");
      if (origemArrastada === null) return;
      var destino = indicePosicaoDoElemento(el);
      if (destino === null) return;
      enviarReordenacao(origemArrastada, destino);
    });
  }

  if (timelineTrack) {
    timelineTrack.querySelectorAll(".timeline-clipe").forEach(function (el) {
      ligarDragSource(el);
      ligarDragAlvoTimeline(el);
    });
  }
  if (bancoGrid) {
    bancoGrid.querySelectorAll(".banco-clipe").forEach(function (el) {
      ligarDragSource(el);
    });
  }

  // --- Busca no banco de clipes --------------------------------------------

  if (buscaInput && bancoGrid) {
    buscaInput.addEventListener("input", function () {
      var termo = buscaInput.value.trim().toLowerCase();
      bancoGrid.querySelectorAll(".banco-clipe").forEach(function (card) {
        var descricao = card.dataset.descricao || "";
        var visivel = !termo || descricao.indexOf(termo) !== -1;
        card.style.display = visivel ? "" : "none";
      });
    });
  }

  // --- Preview em video (gerado sob demanda) -------------------------------

  if (btnAtualizarPreview && previewPlayer) {
    btnAtualizarPreview.addEventListener("click", function () {
      btnAtualizarPreview.disabled = true;
      btnAtualizarPreview.textContent = "Gerando preview...";
      mostrarAviso(avisoPreview, "Gerando preview (pode levar alguns minutos se houve reorganizacao)...");

      previewPlayer.src = cfg.urlPreview + "?v=" + Date.now();
      previewPlayer.style.display = "";
      previewPlayer.load();

      function reabilitar() {
        btnAtualizarPreview.disabled = false;
        btnAtualizarPreview.innerHTML = '<i class="ph ph-arrow-clockwise"></i> Gerar preview em video';
        previewPlayer.removeEventListener("loadeddata", aoCarregar);
        previewPlayer.removeEventListener("error", aoFalhar);
      }
      function aoCarregar() {
        mostrarAviso(avisoPreview, "");
        reabilitar();
      }
      function aoFalhar() {
        mostrarAviso(avisoPreview, "Falha ao gerar o preview - tente novamente.");
        previewPlayer.style.display = "none";
        reabilitar();
      }
      previewPlayer.addEventListener("loadeddata", aoCarregar);
      previewPlayer.addEventListener("error", aoFalhar);
    });
  }

  // --- Continuar montagem ------------------------------------------------

  if (btnContinuar) {
    btnContinuar.addEventListener("click", function () {
      btnContinuar.disabled = true;
      btnContinuar.textContent = "Iniciando montagem...";
      fetch(cfg.urlMontar, { method: "POST" })
        .then(function () {
          window.location.href = cfg.urlStatus;
        })
        .catch(function () {
          btnContinuar.disabled = false;
          btnContinuar.textContent = "Continuar montagem →";
          mostrarAviso(avisoReorg, "Falha ao iniciar a montagem - tente novamente.");
        });
    });
  }
})();
