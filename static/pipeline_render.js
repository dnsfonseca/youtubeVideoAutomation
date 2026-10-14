// Renderizacao HTML da barra de pipeline horizontal (.pipeline-track),
// compartilhada entre status.js (polling ja existente) e
// pipeline_polling.js (Sessao de correcoes UX - polling em
// revisar_roteiro/concluido, que antes so recebiam o pipeline renderizado
// uma vez no carregamento da pagina via macro Jinja _pipeline_horizontal.html).
//
// Espelha a macro Jinja renderizar_pipeline (_pipeline_horizontal.html) -
// manter os dois em sincronia se a estrutura de passo mudar.
window.BrollFoundryPipeline = (function () {
  function iconeCirculo(passo) {
    if (passo.estado === "done") return '<i class="ph ph-check"></i>';
    if (passo.estado === "failed") return '<i class="ph ph-x"></i>';
    return passo.numero;
  }

  function renderizarPipelineHTML(steps) {
    return steps
      .map(function (passo, indice) {
        var clicavel = passo.clicavel && passo.url;
        var tag = clicavel ? "a" : "div";
        var href = clicavel ? ' href="' + passo.url + '"' : "";
        var classeClicavel = clicavel ? " pipeline-step-clicavel" : "";
        var html =
          "<" + tag + href + ' class="pipeline-step pipeline-step-' + passo.estado + classeClicavel + '">' +
          '<div class="pipeline-circle">' + iconeCirculo(passo) + "</div>" +
          '<div class="pipeline-label">' + passo.rotulo + "</div>" +
          '<div class="pipeline-duracao">' + passo.duracao + "</div>" +
          "</" + tag + ">";
        if (indice < steps.length - 1) {
          html += '<div class="pipeline-connector pipeline-connector-' + passo.estado + '"></div>';
        }
        return html;
      })
      .join("");
  }

  return { iconeCirculo: iconeCirculo, renderizarPipelineHTML: renderizarPipelineHTML };
})();
