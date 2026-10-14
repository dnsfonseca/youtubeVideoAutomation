// Realca o campo de chave do provedor de TTS selecionado no dropdown
// "TTS_PROVEDOR_PADRAO". Os demais campos continuam no DOM (e sao
// enviados no POST normalmente) - so a aparencia visual muda, nenhum
// dado e perdido ao trocar a selecao.
(function () {
  var select = document.getElementById("TTS_PROVEDOR_PADRAO");
  if (!select) return;

  var campos = document.querySelectorAll(".tts-chave");

  function atualizar() {
    var provedor = select.value;
    campos.forEach(function (campo) {
      if (!provedor || campo.dataset.provedor === provedor) {
        campo.classList.remove("tts-chave-inativa");
      } else {
        campo.classList.add("tts-chave-inativa");
      }
    });
  }

  select.addEventListener("change", atualizar);
  atualizar();
})();

// Botao "Regerar todos os previews de voz" (secao TTS) - apaga o cache
// de static/previews_vozes/ inteiro e gera tudo de novo via
// POST /api/regerar_previews_vozes (scripts/tts/preview_vozes.py).
(function () {
  var botao = document.getElementById("btn-regerar-previews");
  var status = document.getElementById("regerar-previews-status");
  if (!botao || !status) return;

  botao.addEventListener("click", function () {
    botao.disabled = true;
    status.classList.remove("oculto");
    status.textContent = "Regerando previews... isso pode levar alguns minutos.";

    fetch("/api/regerar_previews_vozes", { method: "POST" })
      .then(function (resposta) {
        return resposta.json();
      })
      .then(function (dados) {
        status.textContent =
          "Concluido: " + dados.geradas_agora + " novos, " +
          dados.ja_existiam + " ja existiam, " + dados.falharam + " falharam.";
      })
      .catch(function () {
        status.textContent = "Erro ao regenerar previews. Verifique o console do servidor.";
      })
      .finally(function () {
        botao.disabled = false;
      });
  });
})();

// Marca d'agua do canal (secao "Marca d'agua do canal aplicada ao video
// final") - upload/remocao via AJAX (POST /ajustes/marca_dagua/upload e
// /remover), fora do form principal de Ajustes (que so' tem campos de
// texto/select). Mesmo espirito do botao "Regerar previews" acima: fetch +
// atualiza o DOM sem recarregar a pagina.
(function () {
  var botaoSelecionar = document.getElementById("btn-selecionar-marca-dagua-canal");
  var input = document.getElementById("marca-dagua-canal-input");
  var botaoRemover = document.getElementById("btn-remover-marca-dagua-canal");
  var blocoPreview = document.getElementById("marca-dagua-canal-preview");
  var imagem = document.getElementById("marca-dagua-canal-img");
  var nomeArquivo = document.getElementById("marca-dagua-canal-nome");
  var status = document.getElementById("marca-dagua-canal-status");
  if (!botaoSelecionar || !input) return;

  function mostrarStatus(texto) {
    if (!status) return;
    status.textContent = texto;
    status.classList.remove("oculto");
  }

  botaoSelecionar.addEventListener("click", function () {
    input.click();
  });

  input.addEventListener("change", function () {
    var arquivo = input.files && input.files[0];
    if (!arquivo) return;

    var formData = new FormData();
    formData.append("arquivo", arquivo);
    mostrarStatus("Enviando...");

    fetch("/ajustes/marca_dagua/upload", { method: "POST", body: formData })
      .then(function (resposta) {
        return resposta.json().then(function (dados) {
          return { ok: resposta.ok, dados: dados };
        });
      })
      .then(function (resultado) {
        if (!resultado.ok) {
          mostrarStatus("Erro: " + (resultado.dados.mensagem || "falha ao enviar."));
          return;
        }
        if (imagem) {
          imagem.src = "/ajustes/marca_dagua/arquivo?t=" + Date.now();
        }
        if (nomeArquivo) {
          nomeArquivo.textContent = resultado.dados.nome_original || arquivo.name;
        }
        if (blocoPreview) blocoPreview.classList.remove("oculto");
        botaoSelecionar.style.display = "none";
        input.style.display = "none";
        mostrarStatus(resultado.dados.aviso || "Marca d'água salva.");
      })
      .catch(function () {
        mostrarStatus("Erro ao enviar a marca d'água.");
      });
  });

  if (botaoRemover) {
    botaoRemover.addEventListener("click", function () {
      botaoRemover.disabled = true;
      fetch("/ajustes/marca_dagua/remover", { method: "POST" })
        .then(function () {
          if (blocoPreview) blocoPreview.classList.add("oculto");
          botaoSelecionar.style.display = "";
          input.style.display = "";
          input.value = "";
          mostrarStatus("Marca d'água removida.");
        })
        .catch(function () {
          mostrarStatus("Erro ao remover a marca d'água.");
        })
        .finally(function () {
          botaoRemover.disabled = false;
        });
    });
  }
})();
