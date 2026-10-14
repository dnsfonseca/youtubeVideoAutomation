// Interatividade da tela de revisao de roteiro (CLAUDE.md secao 5.5):
// toggle editar/preview do roteiro, contador de caracteres/palavras,
// mini-player de video das notas de rodape [F<n>@mm:ss], mostrar/esconder
// subcontroles conforme radio/checkbox escolhidos, texto dinamico do botao
// Aprovar, e os modais (video, nota externa, regerar, cancelar). Vanilla
// JS - sem bibliotecas externas (CLAUDE.md - Sessao 7).
//
// Sessao de correcao pos-Sessao 7 (bug critico): o preview de notas de
// rodape mostrava sempre o texto original vindo do servidor, nunca as
// edicoes feitas ao vivo no textarea. Este arquivo agora traz um parser de
// notas de rodape em JavaScript (espelhando renderizar_notas_rodape() e
// remover_notas_rodape() de server.py) para gerar o preview a partir do
// valor atual do textarea sempre que a aba "Preview" e' clicada.
(function () {
  // Guard redundante do modo=readonly (refinamento "pipeline clicavel"):
  // os controles ja vem com disabled/readonly nativos do HTML, que por si
  // so' ja impedem clique/submit no navegador - esta flag e' so' uma
  // segunda camada, lida do form-revisao (a validacao de verdade contra
  // reaprovacao/regeracao/cancelamento continua no backend, ver
  // server.py:revisar_roteiro).
  var MODO_READONLY = document.getElementById("form-revisao")
    ? document.getElementById("form-revisao").dataset.modoReadonly === "true"
    : false;

  var textarea = document.getElementById("roteiro-textarea");
  var preview = document.getElementById("roteiro-preview");
  var tabEditar = document.getElementById("tab-editar");
  var tabPreview = document.getElementById("tab-preview");
  var projetoId = textarea ? (textarea.dataset.projetoId || "") : "";

  // --- Dicionario de warnings acionaveis (Sessao 7.2 - espelha
  // scripts/warnings_traducoes.py). Categoria = trecho antes da primeira
  // virgula dentro de [⚠ ...] (alguns avisos reais trazem texto livre
  // depois da categoria). Categoria desconhecida cai no fallback. ---
  var dadosAvisosEl = document.getElementById("dados-avisos-traducoes");
  var dadosAvisoFallbackEl = document.getElementById("dados-aviso-fallback");
  var AVISOS_TRADUCOES = {};
  var AVISO_FALLBACK = { titulo: "Atenção sinalizada pela IA", descricao: "" };
  try {
    AVISOS_TRADUCOES = dadosAvisosEl ? JSON.parse(dadosAvisosEl.textContent) : {};
  } catch (erro) {
    AVISOS_TRADUCOES = {};
  }
  try {
    if (dadosAvisoFallbackEl) AVISO_FALLBACK = JSON.parse(dadosAvisoFallbackEl.textContent);
  } catch (erro) {
    // mantem o fallback hardcoded acima
  }

  function categoriaDoAviso(textoAviso) {
    if (!textoAviso) return "";
    return textoAviso.split(",")[0].trim();
  }

  function traduzirAviso(textoAviso) {
    var categoria = categoriaDoAviso(textoAviso);
    return AVISOS_TRADUCOES[categoria] || AVISO_FALLBACK;
  }

  // --- Parser de notas de rodape (espelha server.py PADRAO_NOTA_FONTE /
  // PADRAO_NOTA_EXTERNA / PADRAO_AVISO e renderizar_notas_rodape()) ---
  //
  // Uma tag [F...] pode conter MULTIPLAS fontes separadas por virgula (ex.
  // [F2@00:27-01:00, F1@16:00-16:06], correcao pos-Sessao 7.2 - roteiro
  // real gerou esse padrao e nem o badge nem o filtro de remocao
  // reconheciam). PADRAO_NOTA_COMBINADA casa a tag [F...] INTEIRA no grupo
  // nomeado "fonteTag"; PADRAO_FONTE_ITEM extrai cada fonte individual de
  // dentro dela, com seu proprio numero e timestamp(s).
  var TS_NOTA_FONTE = "\\d{1,2}:\\d{2}(?::\\d{2})?";
  var ITEM_NOTA_FONTE = "F\\d+@" + TS_NOTA_FONTE + "(?:-" + TS_NOTA_FONTE + ")?";

  var PADRAO_NOTA_COMBINADA = new RegExp(
    "\\[(?<fonteTag>" + ITEM_NOTA_FONTE + "(?:\\s*,\\s*" + ITEM_NOTA_FONTE + ")*)\\]" +
      "|\\[N:\\s*(?<externaConteudo>[^\\]]+)\\]" +
      "|\\[⚠\\s*(?<avisoTexto>[^\\]]*)\\]",
    "g"
  );

  var PADRAO_FONTE_ITEM = new RegExp(
    "F(?<fonteNum>\\d+)@(?<fonteInicio>" + TS_NOTA_FONTE + ")" +
      "(?:-(?<fonteFim>" + TS_NOTA_FONTE + "))?",
    "g"
  );

  var RE_NOTA_FONTE_REMOCAO = new RegExp(
    "\\[" + ITEM_NOTA_FONTE + "(?:\\s*,\\s*" + ITEM_NOTA_FONTE + ")*\\]",
    "g"
  );
  var RE_NOTA_EXTERNA_REMOCAO = /\[N:\s*[^\]]+\]/g;
  var RE_AVISO_REMOCAO = /\[⚠\s*[^\]]*\]/g;

  function escaparHtml(valor) {
    return String(valor)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function mmssParaSegundos(timestamp) {
    var partes = timestamp.split(":").map(function (p) { return parseInt(p, 10); });
    var horas = 0, minutos, segundos;
    if (partes.length === 3) {
      horas = partes[0];
      minutos = partes[1];
      segundos = partes[2];
    } else {
      minutos = partes[0];
      segundos = partes[1];
    }
    return horas * 3600 + minutos * 60 + segundos;
  }

  function idFonte(numero) {
    var n = parseInt(numero, 10);
    return "fonte" + (n < 10 ? "0" + n : String(n));
  }

  // Numeracao sequencial exibida nos badges (Entrega 3): circulo unicode
  // para 1-20 (faixa mais que suficiente para um roteiro real); alem
  // disso cai para "(N)" em vez de travar.
  function numeroCirculado(n) {
    if (n >= 1 && n <= 20) {
      return String.fromCodePoint(0x2460 + (n - 1));
    }
    return "(" + n + ")";
  }

  // Remove as notas de rodape de origem do texto puro (usado pelo botao
  // "Ignorar todas as notas" - Entrega 4). Espelha
  // server.py:remover_notas_rodape() - mesma logica de colapso de espacos.
  function removerNotasRodape(texto) {
    if (!texto) return texto;
    var semNotas = texto
      .replace(RE_NOTA_FONTE_REMOCAO, "")
      .replace(RE_NOTA_EXTERNA_REMOCAO, "")
      .replace(RE_AVISO_REMOCAO, "");
    semNotas = semNotas.replace(/[ \t]{2,}/g, " ");
    semNotas = semNotas.replace(/[ \t]+\n/g, "\n");
    semNotas = semNotas.replace(/\n[ \t]+/g, "\n");
    semNotas = semNotas.replace(/ ([.,;:!?])/g, "$1");
    return semNotas.trim();
  }

  // Converte o roteiro (com notas de rodape) no HTML do preview, lendo
  // sempre o texto passado como argumento (nunca um valor cacheado do
  // servidor) - e' isso que faz o preview refletir edicoes ao vivo.
  function gerarPreviewHtml(texto, idProjetoAtual) {
    if (!texto) return "";

    var contador = 0;
    var resultado = "";
    var ultimoIndice = 0;
    var m;

    PADRAO_NOTA_COMBINADA.lastIndex = 0;
    while ((m = PADRAO_NOTA_COMBINADA.exec(texto)) !== null) {
      resultado += escaparHtml(texto.slice(ultimoIndice, m.index));
      var g = m.groups || {};

      if (g.fonteTag !== undefined) {
        // Uma ou mais fontes na mesma tag - cada uma vira seu proprio
        // badge sequencial (①②③...), com timestamp e clique proprios.
        var itemFonte;
        PADRAO_FONTE_ITEM.lastIndex = 0;
        while ((itemFonte = PADRAO_FONTE_ITEM.exec(g.fonteTag)) !== null) {
          var gi = itemFonte.groups;
          contador += 1;
          var inicioS = mmssParaSegundos(gi.fonteInicio);
          var fimS = gi.fonteFim ? mmssParaSegundos(gi.fonteFim) : null;
          var tituloFonte = "Fonte " + gi.fonteNum + " • " + gi.fonteInicio +
            (gi.fonteFim ? " → " + gi.fonteFim : "");
          resultado += '<sup class="nota-badge nota-fonte" ' +
            'data-projeto-id="' + escaparHtml(idProjetoAtual) + '" ' +
            'data-fonte="' + idFonte(gi.fonteNum) + '" ' +
            'data-inicio="' + inicioS + '" ' +
            (fimS !== null ? 'data-fim="' + fimS + '" ' : "") +
            'data-tempo="' + inicioS + '" ' +
            'title="' + escaparHtml(tituloFonte) + '">' +
            numeroCirculado(contador) + "</sup>";
        }
      } else if (g.externaConteudo !== undefined) {
        contador += 1;
        var conteudoExterna = g.externaConteudo.trim();
        var ehUrl = /^https?:\/\//i.test(conteudoExterna);
        var classeExterna = ehUrl ? "nota-externa" : "nota-externa-texto";
        resultado += '<sup class="nota-badge ' + classeExterna + ' nota-badge-externa" ' +
          'data-url="' + (ehUrl ? "1" : "0") + '" ' +
          'data-conteudo="' + escaparHtml(conteudoExterna) + '" ' +
          'title="' + escaparHtml(conteudoExterna) + '">' +
          numeroCirculado(contador) + "</sup>";
      } else if (g.avisoTexto !== undefined) {
        var avisoTextoBruto = g.avisoTexto.trim();
        var traducaoAviso = traduzirAviso(avisoTextoBruto);
        resultado += '<sup class="nota-badge nota-aviso abrir-modal-aviso" ' +
          'data-categoria="' + escaparHtml(categoriaDoAviso(avisoTextoBruto)) + '" ' +
          'title="' + escaparHtml(traducaoAviso.titulo) + '">⚠</sup>';
      }

      ultimoIndice = PADRAO_NOTA_COMBINADA.lastIndex;
    }
    resultado += escaparHtml(texto.slice(ultimoIndice));

    var paragrafos = resultado
      .split(/\n\n+/)
      .map(function (p) { return p.trim(); })
      .filter(Boolean);
    return paragrafos.map(function (p) { return "<p>" + p + "</p>"; }).join("\n");
  }

  function aplicarPreviewAoVivo() {
    if (!preview || !textarea) return;
    preview.innerHTML = gerarPreviewHtml(textarea.value, projetoId);
  }

  function mostrarModo(modo) {
    if (!textarea || !preview || !tabEditar || !tabPreview) return;
    var ehPreview = modo === "preview";
    if (ehPreview) aplicarPreviewAoVivo();
    textarea.classList.toggle("oculto", ehPreview);
    preview.classList.toggle("oculto", !ehPreview);
    tabPreview.classList.toggle("ativo", ehPreview);
    tabEditar.classList.toggle("ativo", !ehPreview);
  }

  if (tabEditar && tabPreview) {
    tabEditar.addEventListener("click", function () { mostrarModo("editar"); });
    tabPreview.addEventListener("click", function () { mostrarModo("preview"); });
    mostrarModo("editar");
  }

  // Contador de caracteres do editor (live, atualiza a cada tecla). A
  // contagem de "palavras narradas" NAO e' recalculada aqui de proposito -
  // e' o valor persistido em job_metadata.json (contar_palavras_narradas()
  // em scripts/3_gerar_roteiro.py e' a unica funcao canonica pra essa
  // metrica), renderizado direto pelo servidor no <span id="contador-
  // palavras">. Duas reguas medindo a mesma coisa (o split(/\s+/) ingenuo
  // daqui conta notas de rodape/markdown como palavras, o canonico nao)
  // causavam divergencia visivel entre a tela e job_metadata.json.
  var elContadorChars = document.getElementById("contador-caracteres");

  function atualizarContador() {
    if (!textarea || !elContadorChars) return;
    elContadorChars.textContent = textarea.value.length;
  }

  if (textarea) {
    textarea.addEventListener("input", atualizarContador);
    atualizarContador();
  }

  // Mini-player de video das notas de rodape [F<n>@mm:ss] (clicaveis so no
  // preview, mas o listener e' delegado no documento inteiro por
  // simplicidade - fora do preview nao existe .nota-fonte nenhuma).
  var modalVideo = document.getElementById("modal-video");
  var videoPlayer = document.getElementById("modal-video-player");
  var btnFecharVideo = document.getElementById("btn-fechar-video");

  document.addEventListener("click", function (evento) {
    var alvo = evento.target.closest(".nota-fonte");
    if (!alvo || !modalVideo || !videoPlayer) return;
    evento.preventDefault();

    var projetoId = alvo.dataset.projetoId;
    var fonte = alvo.dataset.fonte;
    var tempo = parseInt(alvo.dataset.tempo, 10) || 0;

    videoPlayer.src = "/projetos/" + encodeURIComponent(projetoId) + "/fontes/" + encodeURIComponent(fonte) + ".mp4";
    modalVideo.showModal();

    var definirTempo = function () {
      videoPlayer.currentTime = tempo;
      videoPlayer.removeEventListener("loadedmetadata", definirTempo);
    };
    videoPlayer.addEventListener("loadedmetadata", definirTempo);
  });

  if (btnFecharVideo && modalVideo && videoPlayer) {
    btnFecharVideo.addEventListener("click", function () {
      videoPlayer.pause();
      videoPlayer.removeAttribute("src");
      videoPlayer.load();
      modalVideo.close();
    });
  }

  // Badges de nota externa ([N: ...], Entrega 3): URL valida abre em nova
  // aba; conteudo que nao parece URL (referencia interna, id de video etc)
  // abre um modal simples so pra mostrar o texto puro sugerido pela IA.
  var modalNotaExterna = document.getElementById("modal-nota-externa");
  var modalNotaExternaTexto = document.getElementById("modal-nota-externa-texto");
  var btnFecharNotaExterna = document.getElementById("btn-fechar-nota-externa");

  document.addEventListener("click", function (evento) {
    var alvo = evento.target.closest(".nota-badge-externa");
    if (!alvo) return;
    evento.preventDefault();

    var conteudo = alvo.dataset.conteudo || "";
    if (alvo.dataset.url === "1") {
      window.open(conteudo, "_blank", "noopener");
      return;
    }
    if (modalNotaExterna && modalNotaExternaTexto) {
      modalNotaExternaTexto.textContent = conteudo;
      modalNotaExterna.showModal();
    }
  });

  if (btnFecharNotaExterna && modalNotaExterna) {
    btnFecharNotaExterna.addEventListener("click", function () { modalNotaExterna.close(); });
  }

  // Badges de aviso ([⚠ ...], Sessao 7.2): clique abre modal com titulo +
  // descricao acionavel do dicionario de warnings (categoria desconhecida
  // cai no fallback). Tooltip (title) ja mostra so o titulo via
  // renderizar_notas_rodape()/gerarPreviewHtml() acima.
  var modalAviso = document.getElementById("modal-aviso");
  var modalAvisoTitulo = document.getElementById("modal-aviso-titulo");
  var modalAvisoDescricao = document.getElementById("modal-aviso-descricao");
  var btnFecharAviso = document.getElementById("btn-fechar-aviso");

  document.addEventListener("click", function (evento) {
    var alvo = evento.target.closest(".abrir-modal-aviso");
    if (!alvo || !modalAviso || !modalAvisoTitulo || !modalAvisoDescricao) return;
    evento.preventDefault();

    var categoria = alvo.dataset.categoria || "";
    var traducao = AVISOS_TRADUCOES[categoria] || AVISO_FALLBACK;
    modalAvisoTitulo.textContent = traducao.titulo;
    modalAvisoDescricao.textContent = traducao.descricao;
    modalAviso.showModal();
  });

  if (btnFecharAviso && modalAviso) {
    btnFecharAviso.addEventListener("click", function () { modalAviso.close(); });
  }

  // Modal "Refazer roteiro com instrucoes"
  var modalRegerar = document.getElementById("modal-regerar");
  var btnRegerar = document.getElementById("btn-regerar");
  var btnFecharRegerar = document.getElementById("btn-fechar-regerar");

  if (btnRegerar && modalRegerar) {
    btnRegerar.addEventListener("click", function () {
      if (MODO_READONLY) return;
      modalRegerar.showModal();
    });
  }
  if (btnFecharRegerar && modalRegerar) {
    btnFecharRegerar.addEventListener("click", function () { modalRegerar.close(); });
  }

  // Modal "Cancelar projeto"
  var modalCancelar = document.getElementById("modal-cancelar");
  var btnCancelar = document.getElementById("btn-cancelar");
  var btnFecharCancelar = document.getElementById("btn-fechar-cancelar");

  if (btnCancelar && modalCancelar) {
    btnCancelar.addEventListener("click", function () {
      if (MODO_READONLY) return;
      modalCancelar.showModal();
    });
  }
  if (btnFecharCancelar && modalCancelar) {
    btnFecharCancelar.addEventListener("click", function () { modalCancelar.close(); });
  }

  // Titulo personalizado - so faz sentido preencher quando o radio "custom"
  // esta selecionado, mas nao bloqueamos o campo (o valor so e' usado pelo
  // servidor quando titulo_opcao == "custom").
  var tituloCustomInput = document.getElementById("titulo_custom");
  var radiosTitulo = document.querySelectorAll('input[name="titulo_opcao"]');
  if (tituloCustomInput && radiosTitulo.length) {
    radiosTitulo.forEach(function (radio) {
      radio.addEventListener("change", function () {
        if (radio.value === "custom" && radio.checked) {
          tituloCustomInput.focus();
        }
      });
    });
  }

  // Origem do audio - mostra/esconde subcontroles de TTS/upload.
  var radiosOrigemAudio = document.querySelectorAll('input[name="origem_audio"]');
  var blocoTts = document.getElementById("bloco-tts");
  var blocoUpload = document.getElementById("bloco-upload");

  function atualizarVisibilidadeOrigemAudio() {
    var selecionado = document.querySelector('input[name="origem_audio"]:checked');
    var valor = selecionado ? selecionado.value : null;
    if (blocoTts) blocoTts.classList.toggle("oculto", valor !== "tts");
    if (blocoUpload) blocoUpload.classList.toggle("oculto", valor !== "upload");
  }

  // Mostra/esconde o campo de upload de faixas conforme o checkbox "Usar
  // musica de fundo" (Grupo B da sessao de UX - bloco movido de
  // novo_projeto.html pra ca; mesmo par de ids com-musica/secao-upload-musica).
  // aplicar() na carga cobre o caso de reload apos erro de validacao com o
  // checkbox ja marcado (com_musica_fundo_marcado preservado pelo servidor).
  (function () {
    var checkboxMusica = document.getElementById("com-musica");
    var secaoMusica = document.getElementById("secao-upload-musica");
    if (!checkboxMusica || !secaoMusica) return;

    function aplicarMusica() {
      secaoMusica.style.display = checkboxMusica.checked ? "" : "none";
    }

    checkboxMusica.addEventListener("change", aplicarMusica);
    aplicarMusica();
  })();

  // Cascata provedor -> voz de TTS. Provedores com catalogo curado
  // ("google" e "darkplanner" - CLAUDE.md secao 5.6) buscam a lista via
  // GET /api/vozes/<provedor>/<idioma>, com descricao e badge de
  // recomendacao por perfil; os demais (stubs sem catalogo real) usam a
  // lista simples {id, nome} ja embutida na pagina (dados-vozes-tts).
  var dadosVozesEl = document.getElementById("dados-vozes-tts");
  var dadosVozes = {};
  try {
    dadosVozes = dadosVozesEl ? JSON.parse(dadosVozesEl.textContent) : {};
  } catch (erro) {
    dadosVozes = {};
  }
  var selectProvedor = document.getElementById("tts_provedor");
  var selectVoz = document.getElementById("tts_voz");
  var formRevisao = document.getElementById("form-revisao");
  var idiomaRoteiro = formRevisao ? (formRevisao.dataset.idiomaRoteiro || "en-US") : "en-US";
  var perfilAtivo = formRevisao ? (formRevisao.dataset.perfilAtivo || "") : "";
  var PROVEDORES_COM_CATALOGO = ["google", "darkplanner"];

  function _preencherOpcoesVoz(opcoes) {
    selectVoz.innerHTML = "";
    opcoes.forEach(function (item) {
      var opcao = document.createElement("option");
      opcao.value = item.value;
      opcao.textContent = item.texto;
      selectVoz.appendChild(opcao);
    });
  }

  function _popularVozesCatalogo(vozes) {
    _preencherOpcoesVoz(
      (vozes || []).map(function (voz) {
        var recomendada = perfilAtivo && (voz.recomendada_para || []).indexOf(perfilAtivo) !== -1;
        var texto = voz.id + " — " + voz.descricao;
        if (recomendada) texto += " ★ Recomendada";
        return { value: voz.id, texto: texto };
      })
    );
  }

  function _popularVozesSimples() {
    var vozes = dadosVozes[selectProvedor.value] || [];
    _preencherOpcoesVoz(
      vozes.map(function (voz) {
        return { value: voz.id, texto: voz.nome };
      })
    );
  }

  function atualizarVozes() {
    if (!selectProvedor || !selectVoz) return;
    var provedor = selectProvedor.value;
    if (PROVEDORES_COM_CATALOGO.indexOf(provedor) !== -1) {
      fetch("/api/vozes/" + encodeURIComponent(provedor) + "/" + encodeURIComponent(idiomaRoteiro))
        .then(function (resposta) {
          return resposta.ok ? resposta.json() : [];
        })
        .then(_popularVozesCatalogo)
        .catch(function () {
          _popularVozesCatalogo([]);
        });
    } else {
      _popularVozesSimples();
    }
  }

  // Texto dinamico do botao "Aprovar" (CLAUDE.md secao 5.5, Bloco F)
  var btnAprovar = document.getElementById("btn-aprovar");

  function atualizarTextoBotaoAprovar() {
    if (!btnAprovar) return;
    var origemSelecionada = document.querySelector('input[name="origem_audio"]:checked');
    var texto = "Aprovar e prosseguir";

    if (origemSelecionada) {
      if (origemSelecionada.value === "tts") {
        var nomeProvedor = "";
        if (selectProvedor && selectProvedor.selectedIndex >= 0) {
          nomeProvedor = selectProvedor.options[selectProvedor.selectedIndex].textContent
            .replace(" (chave não configurada)", "");
        }
        texto = "Aprovar e gerar áudio" + (nomeProvedor ? " (" + nomeProvedor + ")" : "");
      } else if (origemSelecionada.value === "upload") {
        texto = "Aprovar e usar áudio enviado";
      } else if (origemSelecionada.value === "depois") {
        texto = "Aprovar (áudio depois)";
      }
    }

    btnAprovar.textContent = texto;
  }

  radiosOrigemAudio.forEach(function (radio) {
    radio.addEventListener("change", function () {
      atualizarVisibilidadeOrigemAudio();
      atualizarTextoBotaoAprovar();
    });
  });

  // Guard client-side (o servidor tambem valida - server.py:aprovar_roteiro)
  // contra o caso em que nenhum radio de origem_audio vem pre-marcado: no
  // fluxo "decidir depois -> voltar depois" (CLAUDE.md secao 5.6, Caminho C)
  // com algum TTS configurado, nenhum dos tres radios (tts/upload/depois)
  // fica com "checked" no HTML - achado real em teste de ponta a ponta.
  var formRevisao = document.getElementById("form-revisao");
  var erroInlineAprovar = document.getElementById("erro-inline-aprovar");
  var erroInlineAprovarMsg = document.getElementById("erro-inline-aprovar-msg");

  function mostrarErroInlineAprovar(mensagem) {
    if (!erroInlineAprovar || !erroInlineAprovarMsg) return;
    erroInlineAprovarMsg.textContent = mensagem;
    erroInlineAprovar.classList.remove("oculto");
  }

  function ocultarErroInlineAprovar() {
    if (!erroInlineAprovar) return;
    erroInlineAprovar.classList.add("oculto");
  }

  if (formRevisao) {
    formRevisao.addEventListener("submit", function (evento) {
      var origemSelecionada = document.querySelector('input[name="origem_audio"]:checked');
      if (!origemSelecionada) {
        evento.preventDefault();
        mostrarErroInlineAprovar("Selecione a origem do áudio antes de aprovar o roteiro.");
        var primeiroRadio = document.querySelector('input[name="origem_audio"]');
        if (primeiroRadio) {
          primeiroRadio.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      } else {
        ocultarErroInlineAprovar();
      }
    });
  }

  radiosOrigemAudio.forEach(function (radio) {
    radio.addEventListener("change", ocultarErroInlineAprovar);
  });

  if (selectProvedor) {
    selectProvedor.addEventListener("change", function () {
      atualizarVozes();
      atualizarTextoBotaoAprovar();
    });
    atualizarVozes();
  }

  atualizarVisibilidadeOrigemAudio();
  atualizarTextoBotaoAprovar();

  // Painel explicativo sobre as marcacoes do roteiro (Entrega 4): toggle
  // simples de expandir/colapsar, colapsado por padrao.
  var painelBtn = document.querySelector(".painel-notas-explicativo .btn-expandir");
  var painelConteudo = document.querySelector(".painel-notas-explicativo .painel-conteudo");

  if (painelBtn && painelConteudo) {
    painelBtn.addEventListener("click", function () {
      var expandido = painelBtn.getAttribute("aria-expanded") === "true";
      painelBtn.setAttribute("aria-expanded", String(!expandido));
      painelConteudo.hidden = expandido;
    });
  }

  // Botao "Ignorar todas as notas" (Entrega 4): remove as notas do preview
  // E do textarea (view-only - o roteiro.md em disco nunca e' tocado; o
  // roteiro_aprovado.md sempre sai sem notas de qualquer forma, via
  // server.py:remover_notas_rodape() no POST /aprovar_roteiro). Estado
  // persiste em sessionStorage para sobreviver a um recarregamento de
  // pagina. Alternar de volta para "mostrar notas" restaura o ultimo texto
  // com notas conhecido - edicoes feitas enquanto as notas estavam
  // ocultas nao sao mescladas de volta, sao descartadas nesse caso.
  var btnIgnorarNotas = document.querySelector(".btn-ignorar-notas");
  var CHAVE_IGNORAR_NOTAS = "brollfoundry_ignorar_notas_" + projetoId;
  var textoComNotasSalvo = textarea ? textarea.value : "";
  var notasOcultas = false;

  function atualizarBotaoIgnorarNotas() {
    if (!btnIgnorarNotas) return;
    btnIgnorarNotas.textContent = notasOcultas
      ? "Voltar a mostrar notas"
      : "Ignorar todas as notas (só mostrar texto limpo)";
  }

  function definirNotasOcultas(ocultar, persistir) {
    if (!textarea) return;
    if (ocultar && !notasOcultas) {
      textoComNotasSalvo = textarea.value;
      textarea.value = removerNotasRodape(textarea.value);
    } else if (!ocultar && notasOcultas) {
      textarea.value = textoComNotasSalvo;
    }
    notasOcultas = ocultar;
    atualizarBotaoIgnorarNotas();
    atualizarContador();
    if (preview && !preview.classList.contains("oculto")) {
      aplicarPreviewAoVivo();
    }
    if (persistir !== false) {
      try {
        sessionStorage.setItem(CHAVE_IGNORAR_NOTAS, ocultar ? "1" : "0");
      } catch (erro) {
        // sessionStorage indisponivel (modo privado etc) - segue sem persistir.
      }
    }
  }

  if (btnIgnorarNotas) {
    btnIgnorarNotas.addEventListener("click", function () {
      definirNotasOcultas(!notasOcultas, true);
    });
  }

  try {
    if (sessionStorage.getItem(CHAVE_IGNORAR_NOTAS) === "1") {
      definirNotasOcultas(true, false);
    }
  } catch (erro) {
    // sessionStorage indisponivel - mantem notas visiveis por padrao.
  }
})();
