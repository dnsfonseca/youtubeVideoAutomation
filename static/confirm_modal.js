// Modal de confirmacao centralizado, no tema da aplicacao (design_system.css
// + style.css, ambos ja carregados globalmente por base.html) - substitui os
// dialogos nativos do navegador (window, metodos "confirm" e "alert"), que
// renderizam como caixa de dialogo do SISTEMA OPERACIONAL (fora do tema
// escuro, unica peca da aplicacao assim - correcao de sessao de
// refinamento). Carregado uma vez em base.html, disponivel em toda pagina
// como `window.BrollFoundryConfirm`.
//
// Uso: BrollFoundryConfirm.perguntar({
//   titulo: "Finalizar projeto",
//   mensagem: "Isso conclui o projeto e nada mais podera ser alterado.",
//   textoConfirmar: "Sim, finalizar",
//   textoCancelar: "Voltar",
//   destrutivo: true,
// }).then(function (confirmado) { if (!confirmado) return; ... });
(function () {
  "use strict";

  var ESTILOS_ID = "bf-confirm-modal-estilos";

  function garantirEstilos() {
    if (document.getElementById(ESTILOS_ID)) return;
    var style = document.createElement("style");
    style.id = ESTILOS_ID;
    style.textContent =
      ".bf-confirm-dialog { border: none; padding: 0; border-radius: var(--radius-lg, 14px);\n" +
      "  background: var(--color-bg, #161826); color: var(--color-text, #e9e9ed);\n" +
      "  box-shadow: inset 0 0 0 1px var(--color-divider, rgba(233,233,237,0.16)), 0 20px 60px rgba(0,0,0,0.55);\n" +
      "  width: min(420px, calc(100vw - 48px)); }\n" +
      ".bf-confirm-dialog::backdrop { background: rgba(8,9,15,0.6); backdrop-filter: blur(2px); }\n" +
      ".bf-confirm-corpo { padding: 22px 24px 18px; }\n" +
      ".bf-confirm-titulo { margin: 0 0 10px; font-size: 17px; font-weight: 600; }\n" +
      ".bf-confirm-mensagem { margin: 0; font-size: 13.5px; line-height: 1.5;\n" +
      "  color: color-mix(in srgb, var(--color-text, #e9e9ed) 78%, transparent); white-space: pre-wrap; }\n" +
      ".bf-confirm-acoes { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 24px 20px; }\n" +
      ".bf-confirm-btn { border-radius: var(--radius-md, 8px); padding: 8px 16px; font-size: 13.5px;\n" +
      "  cursor: pointer; border: 1px solid var(--color-divider, rgba(233,233,237,0.16));\n" +
      "  background: transparent; color: var(--color-text, #e9e9ed); }\n" +
      ".bf-confirm-btn:hover { background: color-mix(in srgb, var(--color-text, #e9e9ed) 8%, transparent); }\n" +
      ".bf-confirm-btn-primario { border-color: var(--color-accent, #b5abfc); color: var(--color-accent, #b5abfc); }\n" +
      ".bf-confirm-btn-primario:hover { background: color-mix(in srgb, var(--color-accent, #b5abfc) 14%, transparent); }\n" +
      ".bf-confirm-btn-destrutivo { border-color: var(--cor-perigo-borda, rgba(212,102,79,0.45));\n" +
      "  background: var(--cor-perigo-fundo, rgba(212,102,79,0.16)); color: var(--cor-perigo-texto, #e08a76); }\n" +
      ".bf-confirm-btn-destrutivo:hover { background: color-mix(in srgb, #d4664f 26%, transparent); }\n";
    document.head.appendChild(style);
  }

  // Devolve uma Promise<boolean> - true se o usuario confirmou, false se
  // cancelou (botao Cancelar, tecla Esc, ou clique fora do dialogo).
  function perguntar(opcoes) {
    opcoes = opcoes || {};
    garantirEstilos();

    return new Promise(function (resolve) {
      var dialog = document.createElement("dialog");
      dialog.className = "bf-confirm-dialog";

      var corpo = document.createElement("div");
      corpo.className = "bf-confirm-corpo";

      if (opcoes.titulo) {
        var titulo = document.createElement("h2");
        titulo.className = "bf-confirm-titulo";
        titulo.textContent = opcoes.titulo;
        corpo.appendChild(titulo);
      }

      var mensagem = document.createElement("p");
      mensagem.className = "bf-confirm-mensagem";
      mensagem.textContent = opcoes.mensagem || "";
      corpo.appendChild(mensagem);

      var acoes = document.createElement("div");
      acoes.className = "bf-confirm-acoes";

      var btnCancelar = document.createElement("button");
      btnCancelar.type = "button";
      btnCancelar.className = "bf-confirm-btn";
      btnCancelar.textContent = opcoes.textoCancelar || "Cancelar";

      var btnConfirmar = document.createElement("button");
      btnConfirmar.type = "button";
      btnConfirmar.className = "bf-confirm-btn " + (opcoes.destrutivo ? "bf-confirm-btn-destrutivo" : "bf-confirm-btn-primario");
      btnConfirmar.textContent = opcoes.textoConfirmar || "Confirmar";

      acoes.appendChild(btnCancelar);
      acoes.appendChild(btnConfirmar);

      dialog.appendChild(corpo);
      dialog.appendChild(acoes);
      document.body.appendChild(dialog);

      var resolvido = false;
      function finalizar(resultado) {
        if (resolvido) return;
        resolvido = true;
        resolve(resultado);
        if (dialog.open) dialog.close();
      }

      btnCancelar.addEventListener("click", function () { finalizar(false); });
      btnConfirmar.addEventListener("click", function () { finalizar(true); });
      // Tecla Esc dispara "cancel" antes de "close" - garante resultado false.
      dialog.addEventListener("cancel", function () { finalizar(false); });
      dialog.addEventListener("close", function () {
        finalizar(false);
        dialog.remove();
      });
      dialog.addEventListener("click", function (evento) {
        // Clique no backdrop (fora do conteudo) - dialog nativo nao tem
        // "clique fora" embutido, so' o retangulo inteiro recebe o evento;
        // aproximacao: so' fecha se o alvo for o proprio <dialog>.
        if (evento.target === dialog) finalizar(false);
      });

      dialog.showModal();
      btnConfirmar.focus();
    });
  }

  window.BrollFoundryConfirm = { perguntar: perguntar };
})();
