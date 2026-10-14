// Mantem a barra de pipeline horizontal (.pipeline-track) atualizada nas
// telas revisar_roteiro/concluido via polling de /api/status/<id> - antes
// desta correcao, essas duas telas so recebiam o pipeline renderizado uma
// vez no carregamento da pagina (macro Jinja _pipeline_horizontal.html) e
// nunca refletiam uma etapa que avancasse depois (ex: geracao de clipes
// terminando enquanto o usuario ainda esta na tela de revisao do roteiro
// anterior, ou o video final ficando pronto enquanto a tela de concluido
// de uma corrida anterior ainda estava aberta).
//
// NAO incluir em status.html - ela ja tem polling completo (status.js).
(function () {
  var INTERVALO_MS = 5000;

  var container = document.querySelector(".pipeline-track");
  if (!container) return;

  var projetoId = document.body.dataset.projetoId;
  if (!projetoId) return;

  function atualizarPipeline() {
    fetch("/api/status/" + encodeURIComponent(projetoId))
      .then(function (resposta) {
        return resposta.ok ? resposta.json() : null;
      })
      .then(function (dados) {
        if (dados && dados.pipeline_steps) {
          container.innerHTML = window.BrollFoundryPipeline.renderizarPipelineHTML(dados.pipeline_steps);
        }
      })
      .catch(function () {
        // Falha de rede pontual nao interrompe o polling - tenta de novo
        // no proximo intervalo (mesmo espirito de static/status.js).
      });
  }

  setInterval(atualizarPipeline, INTERVALO_MS);
})();
