// Tela de revisao da thumbnail (simplificacao da Etapa 7 - ver
// HISTORICO_BUGS.md): upload dos 2 sujeitos com papel declarado, briefing
// exportavel (unico campo de texto editavel), selecao manual do template
// de composicao, geracao da thumbnail pela OpenAI (acumula em vez de
// sobrescrever) e escolha final entre as composicoes acumuladas. Os 5
// templates de composicao via Pillow e o grid de candidatos de cenario
// foram removidos por inteiro (scripts/thumbnail_templates.py nao existe
// mais).
(function () {
  var cfg = window.BrollFoundryThumbnail;
  if (!cfg) return;

  var statusBriefing = document.getElementById("status-briefing");
  var blocoPrevisews = document.getElementById("bloco-previews");
  var gridPreviews = document.getElementById("grid-previews");
  var campoBriefing = document.getElementById("campo-briefing");
  var campoTemplate = document.getElementById("campo-template");
  var statusMotivoTemplate = document.getElementById("status-motivo-template");
  var btnTentarCandidatos = document.getElementById("btn-tentar-candidatos");

  // Etapa 7 falhou (ou nao rodou ainda) - reroda a etapa inteira e manda o
  // usuario acompanhar o progresso na tela de status, mesmo padrao de
  // "Continuar montagem" em reorganizar_clipes.js.
  if (btnTentarCandidatos) {
    btnTentarCandidatos.addEventListener("click", function () {
      btnTentarCandidatos.disabled = true;
      btnTentarCandidatos.textContent = "Gerando...";
      fetch(btnTentarCandidatos.dataset.url, { method: "POST" })
        .then(function () {
          window.location.href = btnTentarCandidatos.dataset.urlStatus;
        })
        .catch(function () {
          btnTentarCandidatos.disabled = false;
          btnTentarCandidatos.innerHTML = '<i class="ph ph-arrow-clockwise"></i> Tentar novamente';
        });
    });
  }

  function postJson(url, corpo) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo || {}),
    }).then(function (resposta) {
      return resposta.json().then(function (dados) {
        return { ok: resposta.ok, dados: dados };
      });
    });
  }

  // Upload de um slot (hero|secondary) com o papel escolhido no dropdown
  // ao lado do input de arquivo - ambos obrigatorios no backend.
  function uploadSujeito(slot, input) {
    var arquivo = input.files && input.files[0];
    if (!arquivo) return;
    var campoPapel = document.getElementById("papel-" + slot);
    var papel = campoPapel ? campoPapel.value : "";
    var statusSlot = document.getElementById("status-slot-" + slot);

    var formData = new FormData();
    formData.append("foto", arquivo);
    formData.append("slot", slot);
    formData.append("papel", papel);
    if (statusSlot) statusSlot.textContent = "Enviando foto...";

    fetch(cfg.urlUploadSujeito, { method: "POST", body: formData })
      .then(function (resposta) {
        return resposta.json().then(function (dados) {
          return { ok: resposta.ok, dados: dados };
        });
      })
      .then(function (resultado) {
        if (!resultado.ok || !resultado.dados.sucesso) {
          if (statusSlot) statusSlot.textContent = (resultado.dados && resultado.dados.mensagem) || "Falha ao enviar a foto.";
          return;
        }
        // Recarrega a pagina - mais simples e confiavel do que reconstruir
        // a miniatura/preview em JS, e o upload nao e' uma acao frequente.
        window.location.reload();
      })
      .catch(function () {
        if (statusSlot) statusSlot.textContent = "Falha de rede ao enviar a foto.";
      });
  }

  // Atualiza as opcoes elegiveis do dropdown de template (Grupo F) sem
  // recarregar a pagina - chamado apos uma troca de papel persistida
  // com sucesso (server.py:thumbnail_atualizar_papel_sujeito).
  //
  // Correcao de bug real (ver HISTORICO_BUGS.md): esta funcao so' mexia
  // em `.disabled`/`.value`, nunca no TEXTO visivel de cada opcao - o
  // texto ("(sugerido pelo sistema)" / "— indisponível: ...") e' montado
  // pelo Jinja UMA VEZ no carregamento da pagina (templates/thumbnail.html)
  // e ficava congelado depois disso. Resultado observado em teste real:
  // trocar o papel de um sujeito (fluxo que NAO recarrega a pagina, ao
  // contrario do upload) deixava o estado logico (disabled/value) correto
  // mas o texto lido pelo usuario continuava refletindo a combinacao de
  // papeis ANTERIOR - um template que virou elegivel continuava rotulado
  // "indisponível", e um que deixou de ser sugerido continuava rotulado
  // "(sugerido pelo sistema)". Agora o texto de CADA opcao e' reconstruido
  // aqui a partir dos mesmos dados (`cfg.templatesNomes`/
  // `templatesMotivoCurto`/`templatesDescricoes`) que o Jinja usou pra'
  // montar o texto inicial - nunca duplica a REGRA de elegibilidade (essa
  // continua vindo pronta do servidor em `templatesElegiveis`).
  function atualizarElegibilidadeTemplate(templatesElegiveis, templateSugerido, templatesMotivoCurto) {
    if (!campoTemplate) return;
    // `templatesMotivoCurto` (Fase 1 - correcao da mensagem de
    // indisponibilidade): quando o chamador manda uma versao fresca
    // (server.py recalcula por par hero_papel/secondary_papel a cada
    // resposta de `thumbnail_atualizar_papel_sujeito`), usa ela em vez
    // da copia estatica de `cfg.templatesMotivoCurto` carregada so' no
    // load da pagina - senao o texto ficaria congelado na combinacao
    // ANTERIOR de papeis, mesmo achado de bug real que motivou esta
    // funcao existir (ver comentario acima).
    var motivoCurto = templatesMotivoCurto || cfg.templatesMotivoCurto;
    var opcoes = campoTemplate.querySelectorAll("option");
    for (var i = 0; i < opcoes.length; i++) {
      var opcao = opcoes[i];
      var codigo = opcao.value;
      var elegivel = templatesElegiveis.indexOf(codigo) !== -1;
      var ehSugerido = codigo === templateSugerido;
      opcao.disabled = !elegivel;
      opcao.title = (cfg.templatesDescricoes && cfg.templatesDescricoes[codigo]) || "";
      var nome = (cfg.templatesNomes && cfg.templatesNomes[codigo]) || codigo;
      var texto = nome;
      if (ehSugerido) texto += " (sugerido pelo sistema)";
      if (!elegivel) {
        var motivo = (motivoCurto && motivoCurto[codigo]) || "";
        texto += " — indisponível" + (motivo ? ": " + motivo : "");
      }
      opcao.textContent = texto;
    }
    if (templateSugerido && templatesElegiveis.indexOf(templateSugerido) !== -1) {
      campoTemplate.value = templateSugerido;
    } else if (templatesElegiveis.length && templatesElegiveis.indexOf(campoTemplate.value) === -1) {
      campoTemplate.value = templatesElegiveis[0];
    }
    if (statusMotivoTemplate) {
      statusMotivoTemplate.textContent = (cfg.templatesDescricoes && cfg.templatesDescricoes[campoTemplate.value]) || "";
    }
  }

  // Correcao de bug (HISTORICO_BUGS.md): trocar o papel de um sujeito
  // que JA tem foto enviada tem que persistir imediatamente - antes,
  // o valor do dropdown so' era lido/enviado de novo no proximo
  // UPLOAD (uploadSujeito abaixo), entao o texto ao lado da miniatura
  // (renderizado a partir de sujeitos.json) e o dropdown (estado do
  // DOM) podiam divergir indefinidamente. Slot sem foto ainda: nada
  // pra' persistir, o valor escolhido so' passa a valer no proximo
  // upload (que ja le o dropdown na hora de enviar).
  ["hero", "secondary"].forEach(function (slot) {
    var campoPapel = document.getElementById("papel-" + slot);
    if (!campoPapel) return;
    campoPapel.addEventListener("change", function () {
      if (campoPapel.dataset.temFoto !== "true") return;
      var papel = campoPapel.value;
      var statusSlot = document.getElementById("status-slot-" + slot);
      postJson(cfg.urlAtualizarPapelSujeito, { slot: slot, papel: papel })
        .then(function (resultado) {
          if (!resultado.ok || !resultado.dados.sucesso) {
            if (statusSlot) statusSlot.textContent = (resultado.dados && resultado.dados.mensagem) || "Falha ao atualizar o papel.";
            return;
          }
          if (!resultado.dados.persistido) return;
          var papelAtualEl = document.getElementById("papel-atual-" + slot);
          if (papelAtualEl) papelAtualEl.textContent = papel;
          atualizarElegibilidadeTemplate(
            resultado.dados.templates_elegiveis || [],
            resultado.dados.template_sugerido,
            resultado.dados.templates_motivo_curto
          );
          if (statusBriefing) {
            statusBriefing.textContent = "Papel atualizado — se já havia um briefing gerado, ele está desatualizado; gere de novo antes de compor a thumbnail.";
          }
        })
        .catch(function () {
          if (statusSlot) statusSlot.textContent = "Falha de rede ao atualizar o papel.";
        });
    });
  });

  function removerSujeito(slot) {
    postJson(cfg.urlRemoverSujeito, { slot: slot })
      .then(function (resultado) {
        if (!resultado.ok || !resultado.dados.sucesso) return;
        window.location.reload();
      })
      .catch(function () {
        var statusSlot = document.getElementById("status-slot-" + slot);
        if (statusSlot) statusSlot.textContent = "Falha de rede ao remover a foto.";
      });
  }

  // Gera/regera thumbnail.briefing_completo a partir do estado atual em
  // disco (fotos + papeis + headline ja aprovado), forcando o template
  // selecionado no dropdown - nunca deixa a IA escolher quando o usuario
  // ja escolheu manualmente.
  function gerarBriefing() {
    if (statusBriefing) statusBriefing.textContent = "Gerando briefing...";
    var template = campoTemplate ? campoTemplate.value : null;
    postJson(cfg.urlGerarBriefing, { template: template })
      .then(function (resultado) {
        if (!resultado.ok || !resultado.dados.sucesso) {
          if (statusBriefing) {
            statusBriefing.textContent = (resultado.dados && resultado.dados.mensagem) || "Falha ao gerar o briefing.";
          }
          return;
        }
        var thumb = resultado.dados.thumbnail || {};
        if (campoBriefing) campoBriefing.value = thumb.briefing_completo || "";
        if (statusBriefing) {
          var templateEscolhido = thumb.briefing_template;
          statusBriefing.textContent = templateEscolhido ? "Briefing gerado (template: " + templateEscolhido + ")." : "Briefing gerado.";
        }
      })
      .catch(function () {
        if (statusBriefing) statusBriefing.textContent = "Falha de rede ao gerar o briefing.";
      });
  }

  // Trocar a selecao do template regera o briefing automaticamente com o
  // template escolhido (Grupo F).
  if (campoTemplate) {
    campoTemplate.addEventListener("change", function () {
      if (statusMotivoTemplate) {
        statusMotivoTemplate.textContent = (cfg.templatesDescricoes && cfg.templatesDescricoes[campoTemplate.value]) || "";
      }
      gerarBriefing();
    });
  }

  // Auto-salva a edicao manual do texto do briefing (Grupo B - unico campo
  // de texto editavel da tela) ao sair do campo, pra' nao se perder num
  // recarregamento de pagina - `gerarComposicaoIa` tambem manda o valor
  // atual direto no corpo da chamada, entao a edicao nunca fica so' no
  // navegador antes de gastar uma chamada real de composicao.
  if (campoBriefing) {
    campoBriefing.addEventListener("blur", function () {
      postJson(cfg.urlSalvarBriefing, { briefing_completo: campoBriefing.value }).catch(function () {});
    });
  }

  function copiarBriefing() {
    if (!campoBriefing) return;
    campoBriefing.select();
    var copiado = false;
    try {
      copiado = document.execCommand && document.execCommand("copy");
    } catch (e) {
      copiado = false;
    }
    if (!copiado && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(campoBriefing.value).catch(function () {});
    }
    if (statusBriefing) statusBriefing.textContent = "Copiado.";
  }

  // Regera SOMENTE os dados automaticos (headline/background_prompt/etc)
  // via nova chamada a' IA - title/description/tags e qualquer edicao ja
  // aprovada continuam intactos (server.py:thumbnail_regenerar_metadados).
  // Isso tambem regera o briefing_completo (a partir dos dados novos),
  // entao a textarea e' atualizada direto.
  function regenerarMetadados() {
    if (statusBriefing) statusBriefing.textContent = "Regenerando dados automáticos...";
    postJson(cfg.urlRegenerarMetadados, {})
      .then(function (resultado) {
        if (!resultado.ok || !resultado.dados.sucesso) {
          if (statusBriefing) {
            statusBriefing.textContent = (resultado.dados && resultado.dados.mensagem) || "Falha ao regenerar.";
          }
          return;
        }
        var thumb = resultado.dados.thumbnail || {};
        if (campoBriefing) campoBriefing.value = thumb.briefing_completo || campoBriefing.value;
        if (campoTemplate && thumb.briefing_template) campoTemplate.value = thumb.briefing_template;
        if (statusBriefing) statusBriefing.textContent = "Dados automáticos regenerados.";
      })
      .catch(function () {
        if (statusBriefing) statusBriefing.textContent = "Falha de rede ao regenerar.";
      });
  }

  // Composicoes acumuladas (Grupo D/E): grid populado pelo servidor no
  // load (thumbnail.html) - `adicionarComposicao`/`removerComposicaoDoGrid`
  // so' mantem o DOM em sincronia apos uma acao desta sessao.
  var statusComposicaoIa = document.getElementById("status-composicao-ia");
  var btnComposicaoIa = document.getElementById("btn-composicao-ia");

  function adicionarComposicao(arquivo, url) {
    if (!gridPreviews || !blocoPrevisews) return;
    var item = document.createElement("div");
    item.className = "thumb-preview-item";
    item.dataset.arquivo = arquivo;
    item.innerHTML =
      '<img src="' + url + '?t=' + Date.now() + '" alt="' + arquivo + '">' +
      '<button type="button" class="thumb-preview-excluir" title="Excluir esta composição">×</button>';
    item.addEventListener("click", function () {
      selecionarComposicao(arquivo, item);
    });
    var botaoExcluir = item.querySelector(".thumb-preview-excluir");
    botaoExcluir.addEventListener("click", function (evento) {
      evento.stopPropagation();
      excluirComposicao(arquivo);
    });
    gridPreviews.appendChild(item);
    blocoPrevisews.hidden = false;
  }

  function removerComposicaoDoGrid(arquivo) {
    if (!gridPreviews) return;
    var item = gridPreviews.querySelector('[data-arquivo="' + arquivo + '"]');
    if (item) item.remove();
    if (templateSelecionado === arquivo) {
      templateSelecionado = null;
      atualizarBotaoFinalizar();
    }
    if (blocoPrevisews && !gridPreviews.querySelector(".thumb-preview-item")) {
      blocoPrevisews.hidden = true;
    }
  }

  function gerarComposicaoIa() {
    if (btnComposicaoIa) btnComposicaoIa.disabled = true;
    if (statusComposicaoIa) statusComposicaoIa.textContent = "Gerando pela OpenAI (pode levar até um minuto)...";
    var briefingAtual = campoBriefing ? campoBriefing.value : "";
    postJson(cfg.urlGerarComposicaoIa, { briefing_completo: briefingAtual })
      .then(function (resultado) {
        if (btnComposicaoIa) btnComposicaoIa.disabled = false;
        if (!resultado.ok || !resultado.dados.sucesso) {
          var motivo = (resultado.dados && (resultado.dados.mensagem || resultado.dados.erro_mensagem)) || "Falha desconhecida.";
          if (statusComposicaoIa) statusComposicaoIa.textContent = "Recusado/falhou: " + motivo;
          return;
        }
        if (statusComposicaoIa) {
          statusComposicaoIa.textContent = "Gerado — escolha abaixo se quiser usar, ou gere de novo (nova chamada, novo custo).";
        }
        adicionarComposicao(resultado.dados.arquivo, resultado.dados.preview_url);
      })
      .catch(function () {
        if (btnComposicaoIa) btnComposicaoIa.disabled = false;
        if (statusComposicaoIa) statusComposicaoIa.textContent = "Falha de rede ao gerar a composição por IA.";
      });
  }

  function excluirComposicao(arquivo) {
    postJson(cfg.urlExcluirComposicao, { arquivo: arquivo })
      .then(function (resultado) {
        if (!resultado.ok || !resultado.dados.sucesso) return;
        removerComposicaoDoGrid(arquivo);
      })
      .catch(function () {});
  }

  // Clicar numa composicao so' MARCA a escolha (destaque visual: borda de
  // accent grossa + brilho externo no selecionado, opacidade reduzida nos
  // outros) - nao chama o backend nem navega. So' "Finalizar projeto" (com
  // confirmacao explicita) grava thumbnail/final.jpg e conclui o job.
  var templateSelecionado = null;
  var btnFinalizarProjeto = document.getElementById("btn-finalizar-projeto");
  var statusFinalizar = document.getElementById("status-finalizar-projeto");

  function atualizarBotaoFinalizar() {
    if (!btnFinalizarProjeto) return;
    btnFinalizarProjeto.disabled = !templateSelecionado;
  }

  function selecionarComposicao(arquivo, itemEl) {
    if (gridPreviews) {
      var itens = gridPreviews.querySelectorAll(".thumb-preview-item");
      for (var i = 0; i < itens.length; i++) itens[i].classList.remove("selecionado");
    }
    if (itemEl) itemEl.classList.add("selecionado");
    templateSelecionado = arquivo;
    if (statusFinalizar) statusFinalizar.textContent = "";
    atualizarBotaoFinalizar();
  }

  // Liga o clique dos itens ja renderizados pelo servidor no load.
  if (gridPreviews) {
    var itensIniciais = gridPreviews.querySelectorAll(".thumb-preview-item");
    for (var i = 0; i < itensIniciais.length; i++) {
      (function (item) {
        var arquivo = item.dataset.arquivo;
        item.addEventListener("click", function () {
          selecionarComposicao(arquivo, item);
        });
        var botaoExcluir = item.querySelector(".thumb-preview-excluir");
        if (botaoExcluir) {
          botaoExcluir.addEventListener("click", function (evento) {
            evento.stopPropagation();
            excluirComposicao(arquivo);
          });
        }
      })(itensIniciais[i]);
    }
  }

  function finalizarProjeto() {
    if (!templateSelecionado) return;
    // Modal do tema (static/confirm_modal.js, carregado globalmente por
    // base.html) - substitui o dialogo nativo do navegador.
    window.BrollFoundryConfirm.perguntar({
      titulo: "Finalizar projeto",
      mensagem:
        "Finalizar o projeto agora? TODO o projeto sera' concluido e nada " +
        "mais podera' ser alterado depois - nem a thumbnail, nem o video, " +
        "nem os textos.",
      textoConfirmar: "Sim, finalizar",
      textoCancelar: "Voltar",
      destrutivo: true,
    }).then(function (confirmado) {
      if (!confirmado) return;

      if (btnFinalizarProjeto) btnFinalizarProjeto.disabled = true;
      if (statusFinalizar) statusFinalizar.textContent = "Finalizando...";

      postJson(cfg.urlEscolherComposicao, { arquivo: templateSelecionado })
        .then(function (resultado) {
          if (!resultado.ok || !resultado.dados.sucesso) {
            if (statusFinalizar) statusFinalizar.textContent = "Falha ao finalizar o projeto.";
            atualizarBotaoFinalizar();
            return;
          }
          window.location.href = resultado.dados.redirect;
        })
        .catch(function () {
          if (statusFinalizar) statusFinalizar.textContent = "Falha de rede ao finalizar o projeto.";
          atualizarBotaoFinalizar();
        });
    });
  }

  window.BrollFoundryThumbnail.uploadSujeito = uploadSujeito;
  window.BrollFoundryThumbnail.removerSujeito = removerSujeito;
  window.BrollFoundryThumbnail.gerarBriefing = gerarBriefing;
  window.BrollFoundryThumbnail.copiarBriefing = copiarBriefing;
  window.BrollFoundryThumbnail.regenerarMetadados = regenerarMetadados;
  window.BrollFoundryThumbnail.gerarComposicaoIa = gerarComposicaoIa;
  window.BrollFoundryThumbnail.excluirComposicao = excluirComposicao;
  window.BrollFoundryThumbnail.finalizarProjeto = finalizarProjeto;
})();
