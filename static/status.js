// Faz polling de GET /api/status/<projeto_id> a cada 2s e atualiza a
// barra de progresso, etapa atual e log da tela de status. Para de
// consultar assim que o job terminar (sucesso ou erro) - nao ha etapa
// seguinte disparada automaticamente ainda (isso fica para uma sessao
// futura, ver CLAUDE.md secao 5).
(function () {
  var INTERVALO_MS = 2000;

  var card = document.getElementById("status-card");
  if (!card) return;

  var projetoId = card.dataset.projetoId;
  var elEtapa = document.getElementById("status-etapa");
  var elTexto = document.getElementById("status-texto");
  var elBarraContainer = document.getElementById("barra-progresso-container");
  var elBarra = document.getElementById("barra-preenchimento");
  var elDetalhe = document.getElementById("status-detalhe");
  var elProximaEtapa = document.getElementById("status-proxima-etapa");
  var elAguardandoRevisao = document.getElementById("status-aguardando-revisao");
  var elAguardandoAudio = document.getElementById("status-aguardando-audio");
  var elAguardandoLegendas = document.getElementById("status-aguardando-legendas");
  var elAguardandoReorganizacao = document.getElementById("status-aguardando-reorganizacao");
  var elConcluido = document.getElementById("status-concluido");
  var elAguardandoThumbnailOk = document.getElementById("status-aguardando-thumbnail-ok");
  var elAguardandoThumbnailFalhou = document.getElementById("status-aguardando-thumbnail-falhou");
  var elErro = document.getElementById("status-erro");
  var elLog = document.getElementById("status-log");

  // Item 4 (sessao de correcoes de composicao/interface): job.json
  // ausente/corrompido com artefatos reconhecidos em disco oferece este
  // botao (server.py:reconstruir_estado) - so' aparece quando
  // `estagio_reconstruivel` foi calculado no template.
  var btnReconstruirEstado = document.getElementById("btn-reconstruir-estado");
  var statusReconstruirEstado = document.getElementById("status-reconstruir-estado");
  if (btnReconstruirEstado) {
    btnReconstruirEstado.addEventListener("click", function () {
      btnReconstruirEstado.disabled = true;
      if (statusReconstruirEstado) statusReconstruirEstado.textContent = "Reconstruindo...";
      fetch(btnReconstruirEstado.dataset.url, { method: "POST" })
        .then(function (resposta) {
          return resposta.json().then(function (dados) {
            return { ok: resposta.ok, dados: dados };
          });
        })
        .then(function (resultado) {
          if (!resultado.ok || !resultado.dados.sucesso) {
            btnReconstruirEstado.disabled = false;
            if (statusReconstruirEstado) {
              statusReconstruirEstado.textContent = (resultado.dados && resultado.dados.mensagem) || "Falha ao reconstruir o estado.";
            }
            return;
          }
          window.location.href = resultado.dados.redirect;
        })
        .catch(function () {
          btnReconstruirEstado.disabled = false;
          if (statusReconstruirEstado) statusReconstruirEstado.textContent = "Falha de rede ao reconstruir o estado.";
        });
    });
  }

  var btnTentarThumbnail = document.getElementById("btn-tentar-thumbnail");
  if (btnTentarThumbnail) {
    btnTentarThumbnail.addEventListener("click", function () {
      btnTentarThumbnail.disabled = true;
      btnTentarThumbnail.textContent = "Gerando candidatos...";
      fetch(btnTentarThumbnail.dataset.url, { method: "POST" })
        .then(function () {
          setTimeout(consultar, INTERVALO_MS);
        })
        .catch(function () {
          btnTentarThumbnail.disabled = false;
          btnTentarThumbnail.innerHTML = '<i class="ph ph-arrow-clockwise"></i> Tentar novamente';
        });
    });
  }

  // "aguardando_legendas" NAO e' uma pausa real esperando acao do usuario
  // (ao contrario de aguardando_revisao/aguardando_audio/
  // aguardando_reorganizacao) - server.py grava esse status e, na MESMA
  // thread de fundo, imediatamente segue para a Feature A/B (sincronizacao
  // com IA / thumbnails) e so' depois para a Etapa 6, sem nenhuma pausa de
  // verdade (ver server.py:_executar_etapa5 -> _apos_etapa5_sucesso). Achado
  // real de producao (Grupo C/G3): quando a Feature A roda (chamadas Vision
  // podem levar dezenas de segundos), um poll quase sempre pega esse status
  // no meio do caminho - e como ele nao contava como "em andamento" aqui,
  // o polling parava pra sempre e o usuario via a tela congelada em
  // "aguardando_legendas" ate' recarregar a pagina manualmente, mesmo com o
  // pipeline continuando a trabalhar (e eventualmente terminando) por tras.
  function statusEmAndamento(status) {
    return status === "em_andamento" || status === "pendente" || status === "aguardando_legendas";
  }

  function atualizarTela(job) {
    elEtapa.textContent = "Etapa: " + (job.etapa_label || job.etapa);
    elTexto.textContent = "Status: " + (job.status_label || job.status);
    elBarra.style.width = (job.pct || 0) + "%";
    elDetalhe.textContent = job.detalhe || "";
    elLog.textContent = (job.log || []).join("\n");

    if (statusEmAndamento(job.status)) {
      elBarraContainer.classList.remove("oculto");
    } else {
      elBarraContainer.classList.add("oculto");
    }

    if (job.proxima_etapa) {
      elProximaEtapa.textContent = job.proxima_etapa_mensagem || "";
      elProximaEtapa.classList.remove("oculto");
    } else {
      elProximaEtapa.classList.add("oculto");
    }

    if (job.status === "aguardando_revisao") {
      elAguardandoRevisao.classList.remove("oculto");
    } else {
      elAguardandoRevisao.classList.add("oculto");
    }

    if (elAguardandoAudio) {
      if (job.status === "aguardando_audio") {
        elAguardandoAudio.classList.remove("oculto");
      } else {
        elAguardandoAudio.classList.add("oculto");
      }
    }

    if (elAguardandoLegendas) {
      if (job.status === "aguardando_legendas") {
        elAguardandoLegendas.classList.remove("oculto");
      } else {
        elAguardandoLegendas.classList.add("oculto");
      }
    }

    if (elAguardandoReorganizacao) {
      if (job.status === "aguardando_reorganizacao") {
        elAguardandoReorganizacao.classList.remove("oculto");
      } else {
        elAguardandoReorganizacao.classList.add("oculto");
      }
    }

    if (elConcluido) {
      if (job.status === "concluido") {
        elConcluido.classList.remove("oculto");
      } else {
        elConcluido.classList.add("oculto");
      }
    }

    if (elAguardandoThumbnailOk) {
      if (job.status === "aguardando_thumbnail" && !job.etapa7_falhou) {
        elAguardandoThumbnailOk.classList.remove("oculto");
      } else {
        elAguardandoThumbnailOk.classList.add("oculto");
      }
    }

    if (elAguardandoThumbnailFalhou) {
      if (job.status === "aguardando_thumbnail" && job.etapa7_falhou) {
        elAguardandoThumbnailFalhou.classList.remove("oculto");
      } else {
        elAguardandoThumbnailFalhou.classList.add("oculto");
      }
    }

    if (job.status === "erro") {
      elErro.textContent = job.erro || "Ocorreu um erro nesta etapa.";
      elErro.classList.remove("oculto");
    } else {
      elErro.classList.add("oculto");
    }

    if (job.pipeline_steps) {
      atualizarPipeline(job.pipeline_steps);
    }
    if (job.arquivos_baixados) {
      atualizarArquivosBaixados(job.arquivos_baixados);
    }
    if (job.artefatos) {
      atualizarArtefatos(job.artefatos);
    }
  }

  // Renderizacao compartilhada com pipeline_polling.js (revisar_roteiro/
  // concluido) - ver static/pipeline_render.js.
  function atualizarPipeline(steps) {
    var container = document.querySelector(".pipeline-track");
    if (!container) return;
    container.innerHTML = window.BrollFoundryPipeline.renderizarPipelineHTML(steps);
  }

  function atualizarArquivosBaixados(fontes) {
    var container = document.getElementById("arquivos-baixados-lista");
    if (!container) return;
    if (fontes.length === 0) {
      container.innerHTML = "<p>Nenhum arquivo baixado ainda.</p>";
      return;
    }
    var itens = fontes
      .map(function (fonte) {
        var duracao = fonte.duracao_formatada ? " — " + fonte.duracao_formatada : "";
        var origem = fonte.origem === "upload" ? "enviado" : "baixado";
        return "<li>" + fonte.arquivo + duracao + " (" + origem + ")</li>";
      })
      .join("");
    container.innerHTML = "<ul class=\"lista-arquivos\">" + itens + "</ul>";
  }

  function atualizarArtefatos(artefatos) {
    var container = document.getElementById("artefatos-lista");
    if (!container) return;
    if (artefatos.length === 0) {
      container.innerHTML = '<p class="text-muted" style="font-size:12px;">Nenhum artefato gerado ainda.</p>';
      return;
    }
    var itens = artefatos
      .map(function (artefato) {
        return (
          '<div style="display:flex; align-items:center; gap:8px; color:var(--color-neutral-400);">' +
          '<i class="ph ph-file" style="font-size:14px; color:var(--color-neutral-600);"></i>' +
          '<span style="min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + artefato.nome + "</span>" +
          '<span style="margin-left:auto; color:var(--color-neutral-700); flex:none;">' + artefato.tamanho + "</span>" +
          "</div>"
        );
      })
      .join("");
    container.innerHTML = '<div style="display:flex; flex-direction:column; gap:5px; font-size:12px;">' + itens + "</div>";
  }

  function consultar() {
    fetch("/api/status/" + encodeURIComponent(projetoId))
      .then(function (resposta) {
        return resposta.json();
      })
      .then(function (job) {
        if (job.status === "nao_encontrado") return;
        atualizarTela(job);
        if (statusEmAndamento(job.status)) {
          setTimeout(consultar, INTERVALO_MS);
        }
      })
      .catch(function () {
        // Falha de rede pontual no polling nao derruba a tela - tenta de
        // novo no proximo intervalo.
        setTimeout(consultar, INTERVALO_MS);
      });
  }

  setTimeout(consultar, INTERVALO_MS);
})();
