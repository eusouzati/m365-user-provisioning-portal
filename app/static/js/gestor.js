// Busca de usuários no diretório (Microsoft Graph via API do portal).
// Usada para escolher o gestor (novo colaborador) e o colaborador (desligamento).
// Cada busca usa os ids <prefixo>_busca, _resultados, _id, _nome e _escolhido;
// o prefixo vem de data-busca-usuario (padrão: "gestor").
(function () {
  "use strict";
  const marcados = Array.from(document.querySelectorAll("[data-busca-usuario]"));
  const prefixos = marcados.length ? marcados.map(function (el) { return el.dataset.buscaUsuario; }) : ["gestor"];
  prefixos.forEach(configurar);

  function configurar(p) {
  const busca = document.getElementById(p + "_busca");
  const lista = document.getElementById(p + "_resultados");
  const idCampo = document.getElementById(p + "_id");
  const nomeCampo = document.getElementById(p + "_nome");
  const escolhido = document.getElementById(p + "_escolhido");
  if (!busca || !lista || !idCampo) return;
  const raiz = document.querySelector('[data-busca-usuario="' + p + '"]');
  const extra = raiz && raiz.dataset.buscaExtra ? "&" + raiz.dataset.buscaExtra : "";

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

  function aviso(texto) {
    limpar();
    const li = document.createElement("li");
    li.className = "vazio";
    li.textContent = texto;
    lista.appendChild(li);
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
      b.textContent = u.nome + " — " + (u.cargo || u.upn) + (u.ativo === false ? " (desativada)" : "");
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
      fetch("/api/diretorio/usuarios?q=" + encodeURIComponent(q) + extra, { credentials: "same-origin" })
        .then(function (r) {
          if (r.ok) return r.json();
          if (r.status === 401) throw new Error("Sua sessão expirou. Recarregue a página.");
          if (r.status === 403) throw new Error("Você não tem permissão para buscar no diretório.");
          throw new Error("Não foi possível consultar o diretório agora. Tente novamente em instantes.");
        })
        .then(function (dados) { if (q === ultimo) mostrar(dados); })
        .catch(function (err) {
          if (q === ultimo) aviso(err && err.message ? err.message : "Falha na busca.");
        });
    }, 300);
  });
  }
})();
