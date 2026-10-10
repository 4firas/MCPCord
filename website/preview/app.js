(() => {
  "use strict";

  // Entirely fictional data. This demo never contacts Discord or an AI service.
  const { messages, ariId, channelNames, findMessages, contextFor, motionAllowed } = window.MCPCordDemo;
  const input = document.querySelector("#search-input");
  const results = document.querySelector("#search-results");
  const status = document.querySelector("#result-status");
  const dialog = document.querySelector("#context-dialog");
  let currentScope = "all";
  let currentQuery = "Friday";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function highlightedText(text, query) {
    const paragraph = el("p", "result-text");
    const start = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
    if (start === -1) {
      paragraph.textContent = text;
      return paragraph;
    }
    paragraph.append(document.createTextNode(text.slice(0, start)));
    paragraph.append(el("mark", "", text.slice(start, start + query.length)));
    paragraph.append(document.createTextNode(text.slice(start + query.length)));
    return paragraph;
  }

  function messageMeta(message) {
    const meta = el("div", "result-meta");
    const time = el("time", "", message.time);
    time.dateTime = message.time;
    meta.append(el("strong", "", message.author), time, el("span", "channel-tag", channelNames[message.scope]));
    return meta;
  }

  let selectedMessage = messages[0];
  let contextTrigger = null;

  function showContext(message, trigger) {
    contextTrigger = trigger || document.activeElement;
    selectSource(message);
    setView("source");
    document.querySelector("#context-title").textContent = channelNames[message.scope];
    const container = document.querySelector("#context-messages");
    container.replaceChildren();
    for (const item of contextFor(message.id)) {
      const block = el("article", "context-message" + (item.id === message.id ? " is-selected" : ""));
      if (item.id === message.id) block.setAttribute("aria-label", "Selected source message");
      block.append(messageMeta(item), highlightedText(item.text, currentQuery));
      block.append(el("p", "sample-id", "Sample user ID: " + item.userId));
      container.append(block);
    }
    dialog.showModal();
    dialog.scrollTop = 0;
    document.querySelector("#close-context").focus();
  }

  function renderResults() {
    currentQuery = input.value.trim();
    const query = currentQuery.toLowerCase();
    const isUserId = /^\d+$/.test(query);
    const matches = findMessages(currentQuery, currentScope);
    status.textContent = matches.length + " message" + (matches.length === 1 ? "" : "s") + " found";
    if (isUserId && matches.length) status.textContent = matches.length + " message" + (matches.length === 1 ? "" : "s") + " found from " + matches[0].author;
    results.replaceChildren();
    if (!matches.length) {
      const empty = el("div", "empty-state");
      empty.append(el("h3", "", "Nothing in this little sample."), el("p", "", "Try “Friday”, “auth”, or “search”. There are only eight fictional messages here."));
      const reset = el("button", "", "Show all sample messages");
      reset.type = "button";
      reset.addEventListener("click", () => { input.value = ""; setScope("all"); input.focus(); });
      empty.append(reset);
      results.append(empty);
      return;
    }
    for (const message of matches) {
      const card = el("article", "result-card");
      const avatar = el("span", "avatar avatar-" + message.color, message.author[0]);
      avatar.setAttribute("aria-hidden", "true");
      const content = el("div", "result-body");
      const source = el("button", "context-button", "Read source ↗");
      source.type = "button";
      source.setAttribute("aria-label", "Read sample context for " + message.author + "’s message at " + message.time);
      source.addEventListener("click", () => showContext(message, source));
      content.append(messageMeta(message), highlightedText(message.text, currentQuery), source);
      card.append(avatar, content);
      results.append(card);
    }
  }

  function setScope(scope) {
    currentScope = scope;
    workbench.dataset.scope = scope;
    document.querySelectorAll(".scope-button").forEach(button => {
      const active = button.dataset.scope === scope;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderResults();
  }

  document.querySelector("#search-form").addEventListener("submit", event => { event.preventDefault(); setView("search"); renderResults(); });
  input.addEventListener("search", renderResults);
  document.querySelectorAll(".scope-button").forEach(button => button.addEventListener("click", () => setScope(button.dataset.scope)));
  document.querySelectorAll("[data-preset]").forEach(button => button.addEventListener("click", () => {
    const preset = button.dataset.preset;
    input.value = preset === "decision" ? "Friday" : preset === "person" ? ariId : "";
    setScope(preset === "dm" ? "dm" : "all");
    setView("search");
  }));
  document.querySelector("#close-context").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    }
  });

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch { /* Fall back to a local selection. */ }
    }
    const active = document.activeElement;
    const fallback = el("textarea", "visually-hidden", text);
    fallback.setAttribute("readonly", "");
    document.body.append(fallback);
    fallback.select();
    let success = false;
    try { success = document.execCommand("copy"); } catch { success = false; }
    fallback.remove();
    if (active && typeof active.focus === "function") active.focus();
    return success;
  }

  const release = window.MCPCORD_RELEASE || {};
  let validRepo = null;
  try {
    const url = new URL(release.repository);
    if (url.protocol === "https:" && url.hostname === "github.com" && /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/.test(url.pathname)) validRepo = url.href.replace(/\/$/, "");
  } catch { /* Unverified release links stay on the local release note. */ }
  if (validRepo) {
    document.querySelectorAll(".repo-link").forEach(link => { link.href = validRepo; });
    document.querySelectorAll(".repo-docs-link").forEach(link => { link.href = validRepo + (release.docsPath || "#readme"); });
    document.querySelector(".header-source").firstChild.textContent = "GitHub ";
  }
  const fields = { "platform-tag": release.platformLabel, "install-prerequisites": release.prerequisites, "connection-details": release.connectionDetails, "client-details": release.clientDetails };
  for (const [id, value] of Object.entries(fields)) if (typeof value === "string" && value.trim()) document.getElementById(id).textContent = value;
  if (typeof release.installCommand === "string" && release.installCommand.trim()) {
    document.querySelector("#install-command").textContent = release.installCommand;
    document.querySelector("#copy-install").disabled = false;
  }
  if (validRepo && release.installCommand) document.querySelector("#release-notes").hidden = true;
  document.querySelector("#copy-install").addEventListener("click", async () => {
    const success = await copyText(release.installCommand);
    document.querySelector("#copy-status").textContent = success ? "Copied. Paste it into your terminal." : "Couldn’t copy automatically. Select the command and copy it.";
    document.querySelector("#copy-install span").textContent = success ? "Copied" : "Copy";
  });
  document.querySelector("#copy-prompt").addEventListener("click", async () => {
    const prompt = "Show my available DMs. I’ll pick one to catch up on from the last seven days.";
    const success = await copyText(prompt);
    document.querySelector("#copy-prompt").textContent = success ? "Copied" : "Copy";
    document.querySelector("#prompt-copy-status").textContent = success ? "Example prompt copied." : "Couldn’t copy automatically. Select the example prompt to copy it.";
  });

  // Spatial presentation is progressive enhancement; all controls are native HTML.
  const workbench = document.querySelector("#playground");
  const camera = document.querySelector("#bench-camera");
  const motionButton = document.querySelector("#motion-toggle");
  const reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const fineQuery = window.matchMedia("(hover: hover) and (pointer: fine) and (min-width: 1100px)");
  let paused = false;
  let motion = false;
  let pointerFrame = null;
  let pointerX = 0;
  let pointerY = 0;

  function selectSource(message) {
    selectedMessage = message;
    document.querySelector("#source-meta").textContent = channelNames[message.scope] + " · " + message.time;
    document.querySelector("#source-quote").textContent = message.text;
    document.querySelector("#source-author").textContent = message.author + " · fictional message";
    document.querySelector("#source-id").textContent = "SOURCE / " + message.id.slice(-2).padStart(3, "0");
    document.querySelector("#source-sheet").dataset.scope = message.scope;
  }
  function setView(view) {
    if (!["overview", "search", "source"].includes(view)) return;
    workbench.dataset.view = view;
    document.querySelectorAll("[data-view][type=button]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.view === view));
    });
    resetTilt();
  }
  function resetTilt() {
    if (pointerFrame !== null) window.cancelAnimationFrame(pointerFrame);
    pointerFrame = null;
    camera.style.setProperty("--pointer-x", "0deg");
    camera.style.setProperty("--pointer-y", "0deg");
  }
  function updateMotion() {
    motion = motionAllowed({ reduced: reducedQuery.matches, fine: fineQuery.matches, paused, hidden: document.hidden });
    document.documentElement.dataset.motion = motion ? "on" : "off";
    motionButton.disabled = reducedQuery.matches || !fineQuery.matches;
    motionButton.setAttribute("aria-pressed", String(!motion));
    motionButton.textContent = reducedQuery.matches ? "Reduced motion" : !fineQuery.matches ? "Motion off" : paused ? "Resume motion" : "Pause motion";
    if (!motion) resetTilt();
  }
  document.querySelectorAll("[data-view][type=button]").forEach(button => button.addEventListener("click", () => {
    setView(button.dataset.view);
    if (button.dataset.view === "search") input.focus();
    if (button.dataset.view === "source") document.querySelector("#open-source").focus();
  }));
  document.querySelector("#open-source").addEventListener("click", event => showContext(selectedMessage, event.currentTarget));
  dialog.addEventListener("close", () => {
    if (contextTrigger && contextTrigger.isConnected) contextTrigger.focus({ preventScroll: true });
  });
  motionButton.addEventListener("click", () => { paused = !paused; updateMotion(); });
  reducedQuery.addEventListener("change", updateMotion);
  fineQuery.addEventListener("change", updateMotion);
  document.addEventListener("visibilitychange", updateMotion);
  workbench.addEventListener("pointermove", event => {
    if (!motion || dialog.open || workbench.contains(document.activeElement)) return;
    const bounds = workbench.getBoundingClientRect();
    pointerX = Math.max(-1, Math.min(1, (event.clientX - bounds.left) / bounds.width * 2 - 1));
    pointerY = Math.max(-1, Math.min(1, (event.clientY - bounds.top) / bounds.height * 2 - 1));
    if (pointerFrame !== null) return;
    pointerFrame = window.requestAnimationFrame(() => {
      camera.style.setProperty("--pointer-x", (pointerX * 2).toFixed(2) + "deg");
      camera.style.setProperty("--pointer-y", (-pointerY * 1.2).toFixed(2) + "deg");
      pointerFrame = null;
    });
  });
  workbench.addEventListener("pointerleave", resetTilt);
  workbench.addEventListener("focusin", resetTilt);
  document.querySelector("#bench-controls").hidden = false;
  updateMotion();
  renderResults();
  // Disabled in the static HTML so a no-JS form cannot send the query in a URL.
  document.querySelectorAll("#search-input, .search-button, .scope-button, [data-preset], #open-source, #copy-prompt").forEach(control => { control.disabled = false; });
})();
