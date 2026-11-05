(function () {
  "use strict";

  const API_URL = "/api/convert";
  const MAX_BYTES = 1000000; // mesmo limite do back-end (1 MB)

  const $ = (id) => document.getElementById(id);

  /* ---------- tema claro / escuro ---------- */
  let savedTheme = null;
  try { savedTheme = localStorage.getItem("theme"); } catch (e) { /* armazenamento indisponível */ }
  document.body.dataset.theme = savedTheme === "light" ? "light" : "dark";

  $("btnTheme").addEventListener("click", () => {
    const next = document.body.dataset.theme === "light" ? "dark" : "light";
    document.body.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* ignora */ }
  });

  /* ---------- modais (Sobre nós / Tutorial) ---------- */
  function setupModal(overlayId, openBtnId, closeBtnId) {
    const overlay = $(overlayId), openBtn = $(openBtnId), closeBtn = $(closeBtnId);
    const open = () => { overlay.classList.add("show"); closeBtn.focus(); };
    const close = () => { overlay.classList.remove("show"); openBtn.focus(); };
    openBtn.addEventListener("click", open);
    closeBtn.addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.classList.contains("show")) close();
    });
  }
  setupModal("aboutOverlay", "btnAbout", "btnCloseAbout");
  setupModal("tutorialOverlay", "btnTutorial", "btnCloseTutorial");

  // "Saiba mais": o link já baixa o PDF (atributo download); também abre numa nova aba
  $("btnSaibaMais").addEventListener("click", () => {
    window.open($("btnSaibaMais").getAttribute("href"), "_blank", "noopener");
  });

  /* ---------- utilitários ---------- */
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  /* ---------- árvore de widgets (lida do XML do .ui, só para exibição) ---------- */
  function kids(el, tag) {
    return Array.from(el.children).filter((c) => c.tagName === tag);
  }

  function readDim(widgetEl) {
    const prop = kids(widgetEl, "property").find((p) => p.getAttribute("name") === "geometry");
    if (!prop) return null;
    const w = prop.querySelector("width"), h = prop.querySelector("height");
    return w && h ? `${w.textContent.trim()}×${h.textContent.trim()}` : null;
  }

  function nodeFromWidget(el) {
    const node = { kind: "widget", cls: el.getAttribute("class") || "QWidget", name: el.getAttribute("name") || "", dim: readDim(el), children: [] };
    Array.from(el.children).forEach((c) => {
      if (c.tagName === "layout") node.children.push(nodeFromLayout(c));
      else if (c.tagName === "widget") node.children.push(nodeFromWidget(c));
    });
    return node;
  }

  function nodeFromLayout(el) {
    const node = { kind: "layout", cls: el.getAttribute("class") || "QLayout", name: el.getAttribute("name") || "", children: [] };
    kids(el, "item").forEach((item) => {
      const w = item.querySelector(":scope > widget");
      const l = item.querySelector(":scope > layout");
      const s = item.querySelector(":scope > spacer");
      if (w) node.children.push(nodeFromWidget(w));
      else if (l) node.children.push(nodeFromLayout(l));
      else if (s) node.children.push({ kind: "spacer", cls: "QSpacerItem", name: s.getAttribute("name") || "", children: [] });
    });
    return node;
  }

  function parseTree(text) {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.querySelector("parsererror")) return null;
    const ui = doc.documentElement;
    if (!ui || ui.tagName !== "ui") return null;
    const rootEl = kids(ui, "widget")[0];
    const classEl = kids(ui, "class")[0];
    if (!rootEl) return null;
    return { root: nodeFromWidget(rootEl), formClass: classEl ? classEl.textContent.trim() : "Form" };
  }

  function renderNode(node) {
    const div = document.createElement("div");
    div.className = "tnode";

    const card = document.createElement("div");
    card.className = "tcard k-" + node.kind;

    const cls = document.createElement("div");
    cls.className = "tclass";
    if (node.kind !== "widget") {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = node.kind;
      cls.appendChild(tag);
      cls.appendChild(document.createTextNode(" " + node.cls));
    } else {
      cls.textContent = node.cls;
    }
    card.appendChild(cls);

    const name = document.createElement("div");
    name.className = "tname";
    name.textContent = node.name;
    card.appendChild(name);

    if (node.dim) {
      const dim = document.createElement("div");
      dim.className = "tdim";
      dim.textContent = node.dim;
      card.appendChild(dim);
    }
    div.appendChild(card);

    const wrap = document.createElement("div");
    node.children.forEach((c) => wrap.appendChild(renderNode(c)));
    div.appendChild(wrap);
    return div;
  }

  /* ---------- realce de sintaxe (apenas visual) ---------- */
  const KEYWORDS = new Set(["def", "class", "import", "from", "if", "__name__", "__main__", "as", "self", "return", "sys"]);
  const TOKEN_RE = /(&quot;&quot;&quot;[\s\S]*?&quot;&quot;&quot;|&quot;.*?&quot;|\b(?:def|class|import|from|if|__name__|__main__|as|self|return|sys)\b|\b(?:QtWidgets|QtCore|QtGui)\.[A-Za-z0-9_.]+)/g;

  function highlightPython(code) {
    // uma única passada evita casar texto dos <span> inseridos
    return escapeHtml(code).split("\n").map((line) => {
      let html;
      if (/^\s*#/.test(line)) {
        html = `<span class="com">${line}</span>`;
      } else {
        html = line.replace(TOKEN_RE, (m) => {
          if (m.startsWith("&quot;")) return `<span class="str">${m}</span>`;
          if (KEYWORDS.has(m)) return `<span class="kw">${m}</span>`;
          return `<span class="cls">${m}</span>`;
        });
      }
      return `<span class="line">${html || " "}</span>`;
    }).join("");
  }

  /* ---------- interface ---------- */
  const sheet = $("sheet"), fileInput = $("fileInput"), statusEl = $("status"), results = $("results");
  let currentBlob = null;
  let currentName = "form.py";

  function setStatus(kind, msg) {
    statusEl.className = "status show " + kind;
    statusEl.textContent = msg;
    sheet.classList.toggle("has-error", kind === "error");
  }
  function clearStatus() {
    statusEl.className = "status";
    statusEl.textContent = "";
    sheet.classList.remove("has-error");
  }

  async function processFile(file) {
    clearStatus();
    if (!file) return;
    if (!/\.ui$/i.test(file.name)) {
      return setStatus("error", "Esse arquivo não tem extensão .ui — exporte a tela do Qt Designer nesse formato.");
    }
    if (file.size > MAX_BYTES) {
      return setStatus("error", "Arquivo muito grande (limite de 1 MB).");
    }

    sheet.classList.add("loading");
    setStatus("info", "Convertendo…");

    try {
      const text = await file.text();
      const tree = parseTree(text);
      if (!tree) {
        throw new Error("Esse arquivo não parece um .ui válido do Qt Designer.");
      }

      let res;
      try {
        res = await fetch(API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
          body: file
        });
      } catch (netErr) {
        throw new Error("Não foi possível falar com o servidor. Verifique sua conexão e tente de novo.");
      }

      if (!res.ok) {
        let msg = "Não foi possível converter o arquivo.";
        try { msg = (await res.json()).error || msg; } catch (e) { /* resposta sem JSON */ }
        throw new Error(msg);
      }

      currentBlob = await res.blob();
      const code = await currentBlob.text();
      currentName = file.name.replace(/\.ui$/i, "") + ".py";

      $("fileName").textContent = file.name;
      $("fileMeta").textContent = `classe Ui_${tree.formClass} · raiz ${tree.root.cls}`;
      $("codeTitle").textContent = currentName;

      const treeBody = $("treeBody");
      treeBody.textContent = "";
      const container = document.createElement("div");
      container.className = "troot";
      container.appendChild(renderNode(tree.root));
      treeBody.appendChild(container);

      $("codeBody").innerHTML = highlightPython(code);

      clearStatus();
      results.classList.add("show");
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      results.classList.remove("show");
      setStatus("error", err.message || "Não foi possível converter esse arquivo.");
    } finally {
      sheet.classList.remove("loading");
      fileInput.value = "";
    }
  }

  $("btnSelect").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => processFile(e.target.files[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    sheet.addEventListener(evt, (e) => { e.preventDefault(); sheet.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((evt) =>
    sheet.addEventListener(evt, (e) => { e.preventDefault(); sheet.classList.remove("dragging"); }));
  sheet.addEventListener("drop", (e) => processFile(e.dataTransfer.files && e.dataTransfer.files[0]));

  $("btnClear").addEventListener("click", () => {
    results.classList.remove("show");
    currentBlob = null;
    clearStatus();
    sheet.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  $("btnCopy").addEventListener("click", async () => {
    if (!currentBlob) return;
    const btn = $("btnCopy"), original = btn.textContent;
    try {
      await navigator.clipboard.writeText(await currentBlob.text());
      btn.textContent = "Copiado!";
    } catch (e) {
      btn.textContent = "Não foi possível copiar";
    }
    setTimeout(() => { btn.textContent = original; }, 1400);
  });

  $("btnDownload").addEventListener("click", () => {
    if (!currentBlob) return;
    const url = URL.createObjectURL(currentBlob);
    const a = document.createElement("a");
    a.href = url;
    a.download = currentName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
