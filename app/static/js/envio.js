// Evita duplo clique: desabilita os botões de formulários marcados com data-envio-unico
// (o servidor também é idempotente).
(function () {
  "use strict";
  document.querySelectorAll("form[data-envio-unico]").forEach(function (form) {
    form.addEventListener("submit", function (ev) {
      if (form.dataset.enviando === "1") { ev.preventDefault(); return; }
      form.dataset.enviando = "1";
      setTimeout(function () {
        form.querySelectorAll("button[type=submit]").forEach(function (b) {
          b.disabled = true;
          b.setAttribute("aria-busy", "true");
        });
      }, 0);
    });
  });
})();
