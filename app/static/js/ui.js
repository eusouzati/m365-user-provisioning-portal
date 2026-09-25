// Interações do layout: tema (automático → claro → escuro), menu lateral recolhível
// (desktop) e gaveta (celular). Sem dependências; funciona sem JavaScript no essencial.
(function () {
  "use strict";
  var raiz = document.documentElement;

  function salvar(chave, valor) {
    try {
      if (valor) localStorage.setItem(chave, valor); else localStorage.removeItem(chave);
    } catch (e) { /* sem armazenamento: vale só nesta página */ }
  }

  // ---------------------------------------------------------------- tema
  var ROTULOS = { "": "automático", claro: "claro", escuro: "escuro" };
  var PROXIMO = { "": "claro", claro: "escuro", escuro: "" };
  var botaoTema = document.querySelector("[data-tema-alternar]");
  function mostrarTema() {
    if (!botaoTema) return;
    var t = raiz.dataset.tema || "";
    var texto = "Tema: " + ROTULOS[t] + " (clique para mudar)";
    botaoTema.setAttribute("aria-label", texto);
    botaoTema.title = texto;
  }
  if (botaoTema) {
    mostrarTema();
    botaoTema.addEventListener("click", function () {
      var novo = PROXIMO[raiz.dataset.tema || ""];
      if (novo) raiz.dataset.tema = novo; else delete raiz.dataset.tema;
      salvar("m365up-tema", novo);
      mostrarTema();
    });
  }

  // ------------------------------------------------- menu lateral (desktop)
  var recolher = document.querySelector("[data-recolher-menu]");
  function mostrarRecolhido() {
    if (!recolher) return;
    var r = raiz.dataset.menu === "recolhido";
    var texto = r ? "Expandir menu" : "Recolher menu";
    recolher.setAttribute("aria-label", texto);
    recolher.title = texto;
    recolher.setAttribute("aria-expanded", r ? "false" : "true");
  }
  if (recolher) {
    mostrarRecolhido();
    recolher.addEventListener("click", function () {
      var r = raiz.dataset.menu === "recolhido";
      if (r) delete raiz.dataset.menu; else raiz.dataset.menu = "recolhido";
      salvar("m365up-menu", r ? "" : "recolhido");
      mostrarRecolhido();
    });
  }

  // --------------------------------------------------- gaveta (celular)
  var abrir = document.querySelector("[data-abrir-menu]");
  var menu = document.getElementById("menu-lateral");
  var veu = document.querySelector("[data-fechar-menu]");
  function gaveta(aberta) {
    if (!abrir || !menu) return;
    raiz.toggleAttribute("data-gaveta", aberta);
    abrir.setAttribute("aria-expanded", aberta ? "true" : "false");
    if (veu) veu.hidden = !aberta;
    if (aberta) {
      var atual = menu.querySelector("[aria-current=page]") || menu.querySelector("a");
      if (atual) atual.focus();
    }
  }
  if (abrir && menu) {
    abrir.addEventListener("click", function () { gaveta(!raiz.hasAttribute("data-gaveta")); });
    if (veu) veu.addEventListener("click", function () { gaveta(false); abrir.focus(); });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && raiz.hasAttribute("data-gaveta")) { gaveta(false); abrir.focus(); }
    });
    window.matchMedia("(min-width: 1024px)").addEventListener("change", function (m) {
      if (m.matches) gaveta(false);
    });
  }
})();
