// Carregado no <head>, sem defer: aplica o tema escolhido e o menu recolhido antes da
// primeira pintura. Preferências ficam só neste navegador (localStorage); sem elas,
// o portal segue o tema do sistema operacional.
(function () {
  "use strict";
  var raiz = document.documentElement;
  try {
    var tema = localStorage.getItem("m365up-tema");
    if (tema === "claro" || tema === "escuro") raiz.dataset.tema = tema;
    if (localStorage.getItem("m365up-menu") === "recolhido") raiz.dataset.menu = "recolhido";
  } catch (e) { /* navegação privada ou armazenamento bloqueado: usa o padrão */ }
})();
