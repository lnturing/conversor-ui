(function () {
  "use strict";

  const API_URL = "/api/convert";
  const MAX_BYTES = 1000000; // limite de tamanho por arquivo (1 MB) — igual ao do back-end
  const MAX_FILES = 10;      // limite de arquivos por vez  <-- ALTERE AQUI para mudar o máximo

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
  function baseName(name) { return name.replace(/\.ui$/i, "") || "form"; }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
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

  /* ---------- gerador de .zip (sem bibliotecas; arquivos armazenados sem compressão) ---------- */
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  // entries: [{ name: "arquivo.py", data: Uint8Array }]
  function buildZip(entries) {
    const enc = new TextEncoder();
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    const parts = [], central = [];
    let offset = 0;

    entries.forEach((e) => {
      const nameBytes = enc.encode(e.name);
      const crc = crc32(e.data);
      const size = e.data.length;

      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);          // nomes em UTF-8
      local.setUint16(8, 0, true);               // sem compressão
      local.setUint16(10, dosTime, true);
      local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, size, true);
      local.setUint32(22, size, true);
      local.setUint16(26, nameBytes.length, true);
      local.setUint16(28, 0, true);
      parts.push(local.buffer, nameBytes, e.data);

      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true);
      cen.setUint16(4, 20, true);
      cen.setUint16(6, 20, true);
      cen.setUint16(8, 0x0800, true);
      cen.setUint16(10, 0, true);
      cen.setUint16(12, dosTime, true);
      cen.setUint16(14, dosDate, true);
      cen.setUint32(16, crc, true);
      cen.setUint32(20, size, true);
      cen.setUint32(24, size, true);
      cen.setUint16(28, nameBytes.length, true);
      cen.setUint32(42, offset, true);
      central.push(cen.buffer, nameBytes);

      offset += 30 + nameBytes.length + size;
    });

    const cdSize = central.reduce((s, b) => s + b.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, cdSize, true);
    end.setUint32(16, offset, true);

    return new Blob([...parts, ...central, end.buffer], { type: "application/zip" });
  }

  /* ---------- interface ---------- */
  const sheet = $("sheet"), fileInput = $("fileInput"), statusEl = $("status"), results = $("results");
  let items = [];   // um item por arquivo enviado: { name, status: "ok" | "error", message, blob, code, tree }
  let selected = 0; // índice do arquivo exibido nos painéis

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

  // Valida e converte UM arquivo. Nunca lança erro: falhas voltam em item.message.
  async function convertOne(file) {
    const item = { name: file.name, status: "error", message: "", blob: null, code: "", tree: null };

    if (!/\.ui$/i.test(file.name)) {
      item.message = "Esse arquivo não tem extensão .ui — exporte a tela do Qt Designer nesse formato.";
      return item;
    }
    if (file.size > MAX_BYTES) {
      item.message = "Arquivo muito grande (limite de 1 MB).";
      return item;
    }

    try {
      const tree = parseTree(await file.text());
      if (!tree) throw new Error("Esse arquivo não parece um .ui válido do Qt Designer.");

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

      item.blob = await res.blob();
      item.code = await item.blob.text();
      item.tree = tree;
      item.status = "ok";
    } catch (err) {
      item.message = err.message || "Não foi possível converter esse arquivo.";
    }
    return item;
  }

  async function processFiles(fileList) {
    const all = Array.from(fileList || []); // copia já: limpar o input esvazia a lista original
    if (!all.length) return;

    clearStatus();
    const files = all.slice(0, MAX_FILES);
    const extra = all.length - files.length;

    sheet.classList.add("loading");
    const done = [];
    try {
      for (let i = 0; i < files.length; i++) {
        setStatus("info", files.length > 1 ? `Convertendo ${i + 1} de ${files.length}…` : "Convertendo…");
        done.push(await convertOne(files[i]));
      }
    } finally {
      sheet.classList.remove("loading");
      fileInput.value = "";
    }

    items = done;
    selected = Math.max(0, items.findIndex((it) => it.status === "ok"));
    render();

    if (extra > 0) {
      setStatus("info", `Você enviou ${all.length} arquivos; só os primeiros ${MAX_FILES} foram convertidos.`);
    } else {
      clearStatus();
    }
    results.classList.add("show");
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function render() {
    const okCount = items.filter((it) => it.status === "ok").length;
    $("summary").textContent = items.length === 1
      ? items[0].name
      : `${okCount} de ${items.length} arquivos convertidos`;
    $("btnZip").hidden = okCount < 2;     // o .zip só faz sentido com 2 ou mais
    $("fileList").hidden = items.length < 2;
    renderList();
    renderSelected();
  }

  function renderList() {
    const list = $("fileList");
    list.textContent = "";
    items.forEach((it, i) => {
      const chip = document.createElement("div");
      chip.className = "chip" + (i === selected ? " active" : "") + (it.status === "error" ? " error" : "");

      const pick = document.createElement("button");
      pick.type = "button";
      pick.className = "chip-pick";
      pick.setAttribute("aria-pressed", String(i === selected));
      const dot = document.createElement("span");
      dot.className = "chip-dot";
      dot.textContent = it.status === "ok" ? "✓" : "!";
      const label = document.createElement("span");
      label.className = "chip-name";
      label.textContent = it.name;
      pick.append(dot, label);
      pick.addEventListener("click", () => { selected = i; renderList(); renderSelected(); });
      chip.appendChild(pick);

      if (it.status === "ok") {
        const dl = document.createElement("button");
        dl.type = "button";
        dl.className = "chip-dl";
        dl.title = "Baixar " + baseName(it.name) + ".py";
        dl.setAttribute("aria-label", "Baixar " + baseName(it.name) + ".py");
        dl.textContent = "↓";
        dl.addEventListener("click", () => saveBlob(it.blob, baseName(it.name) + ".py"));
        chip.appendChild(dl);
      }
      list.appendChild(chip);
    });
  }

  function renderSelected() {
    const it = items[selected];
    const panels = $("panels"), errBox = $("fileError");
    if (!it) return;

    if (it.status === "error") {
      panels.hidden = true;
      errBox.hidden = false;
      errBox.textContent = `${it.name}: ${it.message}`;
      $("fileMeta").textContent = "";
      return;
    }

    errBox.hidden = true;
    panels.hidden = false;
    $("fileMeta").textContent = `classe Ui_${it.tree.formClass} · raiz ${it.tree.root.cls}`;
    $("codeTitle").textContent = baseName(it.name) + ".py";

    const treeBody = $("treeBody");
    treeBody.textContent = "";
    const container = document.createElement("div");
    container.className = "troot";
    container.appendChild(renderNode(it.tree.root));
    treeBody.appendChild(container);

    $("codeBody").innerHTML = highlightPython(it.code);
  }

  /* ---------- eventos ---------- */
  $("btnSelect").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => processFiles(e.target.files));

  ["dragenter", "dragover"].forEach((evt) =>
    sheet.addEventListener(evt, (e) => { e.preventDefault(); sheet.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((evt) =>
    sheet.addEventListener(evt, (e) => { e.preventDefault(); sheet.classList.remove("dragging"); }));
  sheet.addEventListener("drop", (e) => processFiles(e.dataTransfer.files));

  $("btnClear").addEventListener("click", () => {
    results.classList.remove("show");
    items = [];
    clearStatus();
    sheet.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  $("btnCopy").addEventListener("click", async () => {
    const it = items[selected];
    if (!it || it.status !== "ok") return;
    const btn = $("btnCopy"), original = btn.textContent;
    try {
      await navigator.clipboard.writeText(it.code);
      btn.textContent = "Copiado!";
    } catch (e) {
      btn.textContent = "Não foi possível copiar";
    }
    setTimeout(() => { btn.textContent = original; }, 1400);
  });

  $("btnDownload").addEventListener("click", () => {
    const it = items[selected];
    if (it && it.status === "ok") saveBlob(it.blob, baseName(it.name) + ".py");
  });

  $("btnZip").addEventListener("click", async () => {
    const used = new Set();
    const entries = [];
    for (const it of items.filter((x) => x.status === "ok")) {
      // evita nomes repetidos dentro do .zip (form.py, form_2.py, ...)
      let name = baseName(it.name), n = 2;
      while (used.has(name.toLowerCase())) name = `${baseName(it.name)}_${n++}`;
      used.add(name.toLowerCase());
      entries.push({ name: name + ".py", data: new Uint8Array(await it.blob.arrayBuffer()) });
    }
    saveBlob(buildZip(entries), "arquivos_convertidos.zip");
  });
})();
