// Busca de gestor no diretório (Microsoft Graph via API do portal).
(function () {
  "use strict";
  const busca = document.getElementById("gestor_busca");
  const lista = document.getElementById("gestor_resultados");
  const idCampo = document.getElementById("gestor_id");
  const nomeCampo = document.getElementById("gestor_nome");
  const escolhido = document.getElementById("gestor_escolhido");
  if (!busca || !lista || !idCampo) return;

  let timer = null;
  let ultimo = "";

  function limpar() { lista.replaceChildren(); }

  function escolher(u) {
    idCampo.value = u.id;
    nomeCampo.value = u.nome;
    escolhido.textContent = u.nome + " (" + u.upn + ")";
    busca.value = "";
    limpar();
  }

  function mostrar(usuarios) {
    limpar();
    if (!usuarios.length) {
      const li = document.createElement("li");
      li.className = "vazio";
      li.textContent = "Nenhum usuário encontrado.";
      lista.appendChild(li);
      return;
    }
    usuarios.forEach(function (u) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = u.nome + " — " + (u.cargo || u.upn);
      b.addEventListener("click", function () { escolher(u); });
      li.appendChild(b);
      lista.appendChild(li);
    });
  }

  busca.addEventListener("input", function () {
    const q = busca.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { limpar(); return; }
    timer = setTimeout(function () {
      ultimo = q;
      fetch("/api/diretorio/usuarios?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (dados) { if (q === ultimo) mostrar(dados); })
        .catch(limpar);
    }, 300);
  });
})();
