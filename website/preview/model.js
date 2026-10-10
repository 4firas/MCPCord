/* Fictional demo data and pure selection rules. No network, storage, or credentials. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MCPCordDemo = api;
})(typeof window === "undefined" ? globalThis : window, function () {
  "use strict";
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

  function findMessages(query = "", scope = "all") {
    const needle = String(query).trim().toLowerCase();
    const exactId = /^\d+$/.test(needle);
    return messages.filter(message => (scope === "all" || message.scope === scope) &&
      (!needle || (exactId ? message.userId === needle : message.text.toLowerCase().includes(needle) || message.author.toLowerCase().includes(needle))));
  }
  function contextFor(id) {
    const selected = messages.find(message => message.id === id);
    return selected ? messages.filter(message => message.scope === selected.scope) : [];
  }
  function motionAllowed({ reduced = false, fine = false, paused = false, hidden = false } = {}) {
    return !reduced && fine && !paused && !hidden;
  }
  messages.forEach(Object.freeze);
  return Object.freeze({ ariId, messages: Object.freeze(messages), channelNames: Object.freeze(channelNames), findMessages, contextFor, motionAllowed });
});
