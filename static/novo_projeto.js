// Tooltip do dropdown "Tipo de conteudo" (perfil) - mostra a
// descricao_curta do perfil selecionado. Trocar de perfil atualiza o
// texto automaticamente; o icone "?" so alterna a visibilidade (util
// quando o usuario ainda nao escolheu nenhum perfil).
(function () {
  var select = document.getElementById("perfil");
  var icone = document.getElementById("info-icone-perfil");
  var tooltip = document.getElementById("tooltip-perfil");
  if (!select || !icone || !tooltip) return;

  function descricaoDoSelecionado() {
    var opcao = select.options[select.selectedIndex];
    return opcao ? opcao.dataset.descricao || "" : "";
  }

  function atualizarTexto() {
    var descricao = descricaoDoSelecionado();
    tooltip.textContent = descricao || "Selecione um tipo de conteudo para ver a descricao.";
  }

  select.addEventListener("change", function () {
    atualizarTexto();
    tooltip.classList.remove("oculto");
  });

  icone.addEventListener("click", function () {
    atualizarTexto();
    tooltip.classList.toggle("oculto");
  });

  atualizarTexto();
})();

// Linhas dinamicas de "Links dos videos-fonte" (CLAUDE.md secao 5.7.1) -
// cada linha tem uma URL + um dropdown de posicao de marca d'agua. Botao
// "+ Adicionar outro link" clona a ultima linha (limpando os valores);
// botao "x" remove a linha, exceto quando e' a unica restante (sempre
// precisa sobrar pelo menos 1 link no formulario).
(function () {
  var lista = document.getElementById("lista-links");
  var botaoAdicionar = document.getElementById("btn-adicionar-link");
  if (!lista || !botaoAdicionar) return;

  // Formato aceito pela Etapa 1 (yt-dlp): youtube.com/... ou youtu.be/...,
  // com ou sem "www."/"m.". Validacao so de formato, no mesmo espirito de
  // scripts/validators.py:validar_url_youtube - o servidor sempre revalida.
  var PADRAO_URL_YOUTUBE = /^https?:\/\/(www\.|m\.)?(youtube\.com\/|youtu\.be\/)/i;

  function validarUrlInline(input) {
    if (input.value.trim() && !PADRAO_URL_YOUTUBE.test(input.value.trim())) {
      input.setCustomValidity("Cole um link valido do YouTube (youtube.com ou youtu.be).");
    } else {
      input.setCustomValidity("");
    }
  }

  function atualizarBotoesRemover() {
    var linhas = lista.querySelectorAll(".linha-link");
    var podeRemover = linhas.length > 1;
    linhas.forEach(function (linha) {
      var botaoRemover = linha.querySelector(".btn-remover-link");
      if (botaoRemover) botaoRemover.disabled = !podeRemover;
    });
  }

  function ligarEventosDaLinha(linha) {
    var input = linha.querySelector('input[name="links[]"]');
    var botaoRemover = linha.querySelector(".btn-remover-link");
    if (input) {
      input.addEventListener("input", function () { validarUrlInline(input); });
    }
    if (botaoRemover) {
      botaoRemover.addEventListener("click", function () {
        if (lista.querySelectorAll(".linha-link").length <= 1) return;
        linha.remove();
        atualizarBotoesRemover();
      });
    }
  }

  lista.querySelectorAll(".linha-link").forEach(ligarEventosDaLinha);
  atualizarBotoesRemover();

  botaoAdicionar.addEventListener("click", function () {
    var linhas = lista.querySelectorAll(".linha-link");
    var novaLinha = linhas[linhas.length - 1].cloneNode(true);

    var input = novaLinha.querySelector('input[name="links[]"]');
    if (input) {
      input.value = "";
      input.setCustomValidity("");
    }
    var select = novaLinha.querySelector('select[name="marcas_dagua[]"]');
    if (select) select.selectedIndex = 0;

    lista.appendChild(novaLinha);
    ligarEventosDaLinha(novaLinha);
    atualizarBotoesRemover();
    var modoAtual = document.querySelector('input[name="modo_fontes"]:checked');
    ajustarRequiredsConformeModo(modoAtual ? modoAtual.value : "unificado");
    if (input) input.focus();
  });
})();

// Ajusta o atributo "required" conforme o modo de fontes ativo. Um campo
// obrigatorio escondido via display:none trava o submit em silencio - o
// navegador tenta focar o campo pra mostrar a mensagem nativa de validacao
// e nao consegue, entao o form simplesmente nao envia e nao aparece erro
// nenhum. Por isso todo campo [required] da secao que fica oculta precisa
// perder o atributo (guardado em data-required-quando pra ser restaurado
// quando a secao volta a ficar visivel).
function ajustarRequiredsConformeModo(modo) {
  var secaoUnificada = document.getElementById("secao-fontes-unificada");
  var secaoSeparada = document.getElementById("secao-fontes-separadas");
  if (!secaoUnificada || !secaoSeparada) return;

  if (modo === "unificado") {
    secaoUnificada.querySelectorAll('[data-required-quando="unificado"]').forEach(function (el) {
      el.setAttribute("required", "");
    });
    secaoSeparada.querySelectorAll("[required]").forEach(function (el) {
      el.dataset.requiredQuando = "separado";
      el.removeAttribute("required");
    });
  } else {
    secaoUnificada.querySelectorAll("[required]").forEach(function (el) {
      el.dataset.requiredQuando = "unificado";
      el.removeAttribute("required");
    });
    secaoSeparada.querySelectorAll('[data-required-quando="separado"]').forEach(function (el) {
      el.setAttribute("required", "");
    });
  }
}

// Modo "fontes separadas" (CLAUDE.md secao 5.7.1-bis) - toggle entre a
// secao unica (modo unificado, ja tratada acima) e as 3 secoes do modo
// separado (transcricao / visual-links / upload). O toggle so troca
// display:none - o servidor sempre revalida o modo_fontes recebido.
(function () {
  var radios = document.querySelectorAll('input[name="modo_fontes"]');
  var secaoUnificada = document.getElementById("secao-fontes-unificada");
  var secaoSeparada = document.getElementById("secao-fontes-separadas");
  if (!radios.length || !secaoUnificada || !secaoSeparada) return;

  function aplicarModo() {
    var selecionado = document.querySelector('input[name="modo_fontes"]:checked');
    var modo = selecionado ? selecionado.value : "unificado";
    secaoUnificada.style.display = modo === "separado" ? "none" : "";
    secaoSeparada.style.display = modo === "separado" ? "" : "none";
    ajustarRequiredsConformeModo(modo);
  }

  radios.forEach(function (radio) {
    radio.addEventListener("change", aplicarModo);
  });
  aplicarModo();
})();

// Linhas dinamicas dos dois grupos do modo separado (transcricao e
// visual-links) - mesmo comportamento de "+ Adicionar link"/"remover" do
// modo unificado, generalizado por grupo via data-grupo.
(function () {
  var PADRAO_URL_YOUTUBE = /^https?:\/\/(www\.|m\.)?(youtube\.com\/|youtu\.be\/)/i;

  function validarUrlInline(input) {
    if (input.value.trim() && !PADRAO_URL_YOUTUBE.test(input.value.trim())) {
      input.setCustomValidity("Cole um link valido do YouTube (youtube.com ou youtu.be).");
    } else {
      input.setCustomValidity("");
    }
  }

  function configurarGrupo(grupo) {
    var lista = document.getElementById("lista-" + (grupo === "transcricao" ? "transcricao" : "visual-links"));
    var botaoAdicionar = document.querySelector('.btn-adicionar-link-grupo[data-grupo="' + grupo + '"]');
    if (!lista || !botaoAdicionar) return;

    function atualizarBotoesRemover() {
      var linhas = lista.querySelectorAll(".linha-link");
      linhas.forEach(function (linha) {
        var botaoRemover = linha.querySelector(".btn-remover-link");
        // Diferente do modo unificado, aqui e' valido zerar o grupo visual
        // (o usuario pode confiar so em uploads) - so o grupo de
        // transcricao exige sempre sobrar 1 linha.
        var podeRemover = grupo === "transcricao" ? linhas.length > 1 : true;
        if (botaoRemover) botaoRemover.disabled = !podeRemover;
      });
    }

    function ligarEventosDaLinha(linha) {
      var input = linha.querySelector("input[type=url]");
      var botaoRemover = linha.querySelector(".btn-remover-link");
      if (input) {
        input.addEventListener("input", function () { validarUrlInline(input); });
      }
      if (botaoRemover) {
        botaoRemover.addEventListener("click", function () {
          if (grupo === "transcricao" && lista.querySelectorAll(".linha-link").length <= 1) return;
          linha.remove();
          atualizarBotoesRemover();
        });
      }
    }

    lista.querySelectorAll(".linha-link").forEach(ligarEventosDaLinha);
    atualizarBotoesRemover();

    botaoAdicionar.addEventListener("click", function () {
      var linhas = lista.querySelectorAll(".linha-link");
      var novaLinha = linhas[linhas.length - 1].cloneNode(true);

      var input = novaLinha.querySelector("input[type=url]");
      if (input) {
        input.value = "";
        input.setCustomValidity("");
      }
      var select = novaLinha.querySelector("select");
      if (select) select.selectedIndex = 0;

      lista.appendChild(novaLinha);
      ligarEventosDaLinha(novaLinha);
      atualizarBotoesRemover();
      var modoAtual = document.querySelector('input[name="modo_fontes"]:checked');
      ajustarRequiredsConformeModo(modoAtual ? modoAtual.value : "unificado");
      if (input) input.focus();
    });
  }

  configurarGrupo("transcricao");
  configurarGrupo("visual");
})();

// Preview dos arquivos selecionados para upload (fontes visuais proprias) -
// so lista nome + tamanho, a validacao de verdade (extensao/tamanho) e'
// sempre feita no servidor (scripts/validators.py:classificar_extensao_upload).
(function () {
  var botaoSelecionar = document.getElementById("btn-selecionar-uploads");
  var input = document.getElementById("upload-input");
  var lista = document.getElementById("lista-uploads");
  if (!botaoSelecionar || !input || !lista) return;

  botaoSelecionar.addEventListener("click", function () {
    input.click();
  });

  input.addEventListener("change", function () {
    lista.innerHTML = "";
    Array.from(this.files).forEach(function (arquivo) {
      var tamanhoMB = (arquivo.size / 1024 / 1024).toFixed(1);
      var linha = document.createElement("div");
      linha.className = "linha-upload";
      var nome = document.createElement("span");
      nome.textContent = arquivo.name;
      var tamanho = document.createElement("span");
      tamanho.className = "text-muted";
      tamanho.style.margin = "0";
      tamanho.textContent = tamanhoMB + " MB";
      linha.appendChild(nome);
      linha.appendChild(tamanho);
      lista.appendChild(linha);
    });
  });
})();

// Origem do roteiro (feature de upload de roteiro pronto) - "ia" (default)
// mostra o formulario de sempre; "upload" mostra o campo de arquivo e
// esconde "Modo de fontes" (nao faz sentido sem geracao via IA - todo link
// vira fonte visual, o servidor forca isso independente do que estava
// selecionado, ver server.py:novo()). O rotulo da lista de links unica
// tambem muda pra deixar claro que sao so fontes visuais nesse modo.
(function () {
  var radios = document.querySelectorAll('input[name="origem_roteiro"]');
  var secaoUpload = document.getElementById("secao-upload-roteiro");
  var blocoModoFontes = document.getElementById("bloco-modo-fontes");
  var rotuloFontes = document.getElementById("rotulo-fontes-unificada");
  var radioModoUnificado = document.getElementById("modo-fontes-unificado");
  var blocoTamanhoRoteiro = document.getElementById("bloco-tamanho-roteiro");
  if (!radios.length || !secaoUpload || !blocoModoFontes || !rotuloFontes) return;

  function aplicarOrigemRoteiro() {
    var selecionado = document.querySelector('input[name="origem_roteiro"]:checked');
    var origem = selecionado ? selecionado.value : "ia";
    var ehUpload = origem === "upload";

    secaoUpload.style.display = ehUpload ? "" : "none";
    blocoModoFontes.style.display = ehUpload ? "none" : "";
    rotuloFontes.textContent = ehUpload ? "Fontes visuais (b-roll) *" : "Links dos videos-fonte *";
    // Tamanho alvo so' se aplica a roteiro gerado via IA - sem geracao nao
    // ha o que ajustar (o roteiro ja vem pronto do upload).
    if (blocoTamanhoRoteiro) blocoTamanhoRoteiro.style.display = ehUpload ? "none" : "";

    if (ehUpload && radioModoUnificado && !radioModoUnificado.checked) {
      radioModoUnificado.checked = true;
      radioModoUnificado.dispatchEvent(new Event("change"));
    }
  }

  radios.forEach(function (radio) {
    radio.addEventListener("change", aplicarOrigemRoteiro);
  });
  aplicarOrigemRoteiro();
})();

// Mostra/esconde o dropdown de duracao da Sincronizacao inteligente com IA
// (Feature A, ajustes avancados) conforme o checkbox correspondente.
(function () {
  var checkbox = document.getElementById("sincronizacao-ia-ativa");
  var opcoes = document.getElementById("sincronizacao-ia-opcoes");
  if (!checkbox || !opcoes) return;

  function aplicar() {
    opcoes.style.display = checkbox.checked ? "" : "none";
  }

  checkbox.addEventListener("change", aplicar);
  aplicar();
})();

// Preset de tamanho do roteiro (Grupo C da sessao de UX): o <select>
// palavras_alvo carrega a duracao em minutos de cada opcao em
// data-minutos; o hidden duracao_alvo_minutos e' o que server.py de fato
// le junto com palavras_alvo (scripts/3_gerar_roteiro.py:_ler_configuracao_tamanho).
(function () {
  var select = document.getElementById("palavras_alvo");
  var hiddenMinutos = document.getElementById("duracao_alvo_minutos");
  if (!select || !hiddenMinutos) return;

  function aplicar() {
    var opcao = select.options[select.selectedIndex];
    if (opcao && opcao.dataset.minutos) {
      hiddenMinutos.value = opcao.dataset.minutos;
    }
  }

  select.addEventListener("change", aplicar);
  aplicar();
})();

// Tipo de projeto (CLAUDE.md secao 3, "Vídeos pré-gerados") - "pipeline_completa"
// (default) mostra o formulario de sempre; "videos_pre_gerados" esconde tudo
// isso e mostra so' o upload de videos + legenda opcional (caminho separado
// no servidor, sem download/transcricao/roteiro/audio/clipes). Regressao da
// Sessao 20.1 (mesmo bug do modo_fontes): campos com `required` fixo no HTML
// dentro de #secao-pipeline-completa ficavam com o atributo quando a secao
// virava display:none, travando o submit em silencio. Aqui capturamos TODOS
// os [required] de dentro da secao no momento em que ela e' escondida (cobre
// o grupo de links ativo no modo_fontes - unificado ou separado - e qualquer
// linha adicionada dinamicamente) e restauramos ao voltar. Usa
// `data-required-tipo-projeto` (namespace proprio, distinto do
// `data-required-quando` do toggle de modo_fontes acima) pra nao colidir com
// o bookkeeping dele - os dois toggles convivem sem se pisar porque so' um
// dos dois pode estar "escondendo" a secao de fontes por vez. "nome" NAO
// mora mais dentro de #secao-pipeline-completa (Grupo D da sessao de
// correcoes UX seguinte - CLAUDE.md nao documenta essa secao, ver
// templates/novo_projeto.html): ele e' sempre visivel, entao nunca precisa
// desse bookkeeping.
(function () {
  var radios = document.querySelectorAll('input[name="tipo_projeto"]');
  var secaoPipelineCompleta = document.getElementById("secao-pipeline-completa");
  var secaoVideosPreGerados = document.getElementById("secao-videos-pre-gerados");
  var inputVideos = document.getElementById("videos-pre-gerados-input");
  if (!radios.length || !secaoPipelineCompleta || !secaoVideosPreGerados) return;

  function aplicarTipoProjeto() {
    var selecionado = document.querySelector('input[name="tipo_projeto"]:checked');
    var tipo = selecionado ? selecionado.value : "pipeline_completa";
    var ehVideosPreGerados = tipo === "videos_pre_gerados";

    secaoPipelineCompleta.style.display = ehVideosPreGerados ? "none" : "";
    secaoVideosPreGerados.style.display = ehVideosPreGerados ? "" : "none";

    if (ehVideosPreGerados) {
      secaoPipelineCompleta.querySelectorAll("[required]").forEach(function (el) {
        el.dataset.requiredTipoProjeto = "1";
        el.removeAttribute("required");
      });
    } else {
      secaoPipelineCompleta.querySelectorAll('[data-required-tipo-projeto="1"]').forEach(function (el) {
        el.setAttribute("required", "");
        delete el.dataset.requiredTipoProjeto;
      });
    }

    if (inputVideos) {
      if (ehVideosPreGerados) {
        inputVideos.setAttribute("required", "");
      } else {
        inputVideos.removeAttribute("required");
      }
    }
  }

  radios.forEach(function (radio) {
    radio.addEventListener("change", aplicarTipoProjeto);
  });
  aplicarTipoProjeto();
})();

// Preview dos videos pre-gerados selecionados - mesmo espirito do preview
// de uploads de fontes visuais (btn-selecionar-uploads acima), so lista
// nome + tamanho.
(function () {
  var botaoSelecionar = document.getElementById("btn-selecionar-videos-pre-gerados");
  var input = document.getElementById("videos-pre-gerados-input");
  var lista = document.getElementById("lista-videos-pre-gerados");
  if (!botaoSelecionar || !input || !lista) return;

  botaoSelecionar.addEventListener("click", function () {
    input.click();
  });

  input.addEventListener("change", function () {
    lista.innerHTML = "";
    Array.from(this.files).forEach(function (arquivo) {
      var tamanhoMB = (arquivo.size / 1024 / 1024).toFixed(1);
      var linha = document.createElement("div");
      linha.className = "linha-upload";
      var nome = document.createElement("span");
      nome.textContent = arquivo.name;
      var tamanho = document.createElement("span");
      tamanho.className = "text-muted";
      tamanho.style.margin = "0";
      tamanho.textContent = tamanhoMB + " MB";
      linha.appendChild(nome);
      linha.appendChild(tamanho);
      lista.appendChild(linha);
    });
  });
})();

// Mostra/esconde o campo de upload do SRT conforme o checkbox "Adicionar
// legenda queimada (SRT)" (tipo de projeto videos_pre_gerados).
(function () {
  var checkbox = document.getElementById("com-legenda-srt");
  var secao = document.getElementById("secao-arquivo-srt");
  if (!checkbox || !secao) return;

  function aplicar() {
    secao.style.display = checkbox.checked ? "" : "none";
  }

  checkbox.addEventListener("change", aplicar);
  aplicar();
})();

// Preview de intro/ending (secao "Intro e ending anexados ao video final",
// GRUPO A) - nome + duracao (lida do proprio arquivo via <video>.duration,
// sem round-trip ao servidor - a validacao de verdade, incluindo
// legibilidade via ffprobe, e' sempre feita no servidor) + botao remover
// (limpa o <input type=file> - nao da pra pre-popular um <input type=file>
// por seguranca do navegador, entao "remover" so' reseta a selecao).
(function () {
  function configurarUploadIntroEnding(idBotao, idInput, idPreview) {
    var botaoSelecionar = document.getElementById(idBotao);
    var input = document.getElementById(idInput);
    var preview = document.getElementById(idPreview);
    if (!botaoSelecionar || !input || !preview) return;

    function limparPreview() {
      preview.innerHTML = "";
      input.value = "";
    }

    function renderizarSemDuracao(arquivo) {
      var linha = document.createElement("div");
      linha.className = "linha-upload";
      var nome = document.createElement("span");
      nome.textContent = arquivo.name;
      linha.appendChild(nome);
      adicionarBotaoRemover(linha);
      preview.appendChild(linha);
    }

    function adicionarBotaoRemover(linha) {
      var botaoRemover = document.createElement("button");
      botaoRemover.type = "button";
      botaoRemover.className = "btn btn-ghost";
      botaoRemover.style.padding = "0 6px";
      botaoRemover.textContent = "×";
      botaoRemover.addEventListener("click", limparPreview);
      linha.appendChild(botaoRemover);
    }

    function formatarDuracao(segundosTotais) {
      var segundos = Math.round(segundosTotais);
      var minutos = Math.floor(segundos / 60);
      var resto = segundos % 60;
      return minutos + ":" + (resto < 10 ? "0" : "") + resto;
    }

    botaoSelecionar.addEventListener("click", function () {
      input.click();
    });

    input.addEventListener("change", function () {
      preview.innerHTML = "";
      var arquivo = this.files && this.files[0];
      if (!arquivo) return;

      var videoTemporario = document.createElement("video");
      videoTemporario.preload = "metadata";
      videoTemporario.onloadedmetadata = function () {
        URL.revokeObjectURL(videoTemporario.src);
        var linha = document.createElement("div");
        linha.className = "linha-upload";
        var nome = document.createElement("span");
        nome.textContent = arquivo.name;
        var duracao = document.createElement("span");
        duracao.className = "text-muted";
        duracao.style.margin = "0";
        duracao.textContent = formatarDuracao(videoTemporario.duration);
        linha.appendChild(nome);
        linha.appendChild(duracao);
        adicionarBotaoRemover(linha);
        preview.innerHTML = "";
        preview.appendChild(linha);
      };
      videoTemporario.onerror = function () {
        renderizarSemDuracao(arquivo);
      };
      videoTemporario.src = URL.createObjectURL(arquivo);
    });
  }

  configurarUploadIntroEnding("btn-selecionar-intro", "intro_arquivo", "preview-intro");
  configurarUploadIntroEnding("btn-selecionar-ending", "ending_arquivo", "preview-ending");
})();

// Mostra/esconde o upload de PNG conforme a opcao "marca_dagua_projeto"
// selecionada (radio "canal"/"outra"/"nenhuma" - Marca d'agua do canal).
(function () {
  var radios = document.querySelectorAll('input[name="marca_dagua_projeto"]');
  var secaoMarcaDagua = document.getElementById("secao-marca-dagua-arquivo");
  if (!radios.length || !secaoMarcaDagua) return;

  function aplicarMarcaDagua() {
    var selecionado = document.querySelector('input[name="marca_dagua_projeto"]:checked');
    secaoMarcaDagua.style.display = selecionado && selecionado.value === "outra" ? "" : "none";
  }

  radios.forEach(function (radio) {
    radio.addEventListener("change", aplicarMarcaDagua);
  });
  aplicarMarcaDagua();
})();

