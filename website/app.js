(() => {
  "use strict";

  // Entirely fictional data. This demo never contacts Discord or an AI service.
  const ariId = "100000000000000001";
  const messages = [
    { id: "sample-01", scope: "build", author: "Ari", userId: ariId, time: "10:42", text: "Friday works. Fix auth before we ship.", color: "green" },
    { id: "sample-02", scope: "build", author: "Jules", userId: "100000000000000002", time: "10:44", text: "Small rollout first. Then everyone.", color: "orange" },
    { id: "sample-03", scope: "build", author: "Mina", userId: "100000000000000003", time: "10:46", text: "Friday release plan is in the notes. Keep the first rollout invite-only.", color: "orange" },
    { id: "sample-04", scope: "build", author: "Ari", userId: ariId, time: "11:08", text: "Auth fix is ready for review. The session timeout was the issue.", color: "green" },
    { id: "sample-05", scope: "build", author: "Jules", userId: "100000000000000002", time: "11:13", text: "Approved. Start with the small rollout after the auth fix lands.", color: "orange" },
    { id: "sample-06", scope: "dm", author: "You", userId: "100000000000000004", time: "14:20", text: "Can you send the notes from our design chat?", color: "orange" },
    { id: "sample-07", scope: "dm", author: "Ari", userId: ariId, time: "14:22", text: "Yep. Keep the sidebar compact and put search up front.", color: "green" },
    { id: "sample-08", scope: "dm", author: "Ari", userId: ariId, time: "14:23", text: "Also: keep the empty state useful. Tell people what to try next.", color: "green" }
  ];
  const channelNames = { build: "# build-room", dm: "DM with Ari" };
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

  function showContext(message) {
    document.querySelector("#context-title").textContent = channelNames[message.scope];
    const container = document.querySelector("#context-messages");
    container.replaceChildren();
    for (const item of messages.filter(entry => entry.scope === message.scope)) {
      const block = el("article", "context-message" + (item.id === message.id ? " is-selected" : ""));
      if (item.id === message.id) block.setAttribute("aria-label", "Selected source message");
      block.append(messageMeta(item), highlightedText(item.text, currentQuery));
      block.append(el("p", "sample-id", "Sample user ID: " + item.userId));
      container.append(block);
    }
    dialog.showModal();
    dialog.scrollTop = 0;
  }

  function renderResults() {
    currentQuery = input.value.trim();
    const query = currentQuery.toLowerCase();
    const isUserId = /^\d+$/.test(query);
    const matches = messages.filter(message => {
      const inScope = currentScope === "all" || message.scope === currentScope;
      const matchesQuery = !query || (isUserId ? message.userId === query : message.text.toLowerCase().includes(query) || message.author.toLowerCase().includes(query));
      return inScope && matchesQuery;
    });
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
      const source = el("button", "context-button", "↳ Read sample context ↗");
      source.type = "button";
      source.setAttribute("aria-label", "Read sample context for " + message.author + "’s message at " + message.time);
      source.addEventListener("click", () => showContext(message));
      content.append(messageMeta(message), highlightedText(message.text, currentQuery), source);
      card.append(avatar, content);
      results.append(card);
    }
  }

  function setScope(scope) {
    currentScope = scope;
    document.querySelectorAll(".scope-button").forEach(button => {
      const active = button.dataset.scope === scope;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    renderResults();
  }

  document.querySelector("#search-form").addEventListener("submit", event => { event.preventDefault(); renderResults(); });
  input.addEventListener("search", renderResults);
  document.querySelectorAll(".scope-button").forEach(button => button.addEventListener("click", () => setScope(button.dataset.scope)));
  document.querySelectorAll("[data-preset]").forEach(button => button.addEventListener("click", () => {
    const preset = button.dataset.preset;
    input.value = preset === "decision" ? "Friday" : preset === "person" ? ariId : "";
    setScope(preset === "dm" ? "dm" : "all");
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

  renderResults();
})();
