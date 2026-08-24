// ==UserScript==
// @name         Offline Chat Copilot
// @namespace    local.offline-chat-copilot
// @version      1.1
// @description  On Claimed: scroll history, POST to local engine, fill logbook + draft. Never sends.
// @match        https://YOUR-OPERATOR-DASHBOARD.example/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==UserScript==

/*
  Do not use @match https://*/*. This script is for ONE operator dashboard.

  Start the desktop controller first:
    python3 -m offline_copilot serve --port 8765

  This userscript never clicks Send / Submit.
*/

(function () {
  "use strict";

  const CONFIG = {
    engineUrl: "http://127.0.0.1:8765",
    personaCity: "",
    autoFillDraft: true,
    autoSaveLogbook: true,
    autoSend: false, // locked. This script never clicks Send.
    scrollPasses: 8,
    scrollWaitMs: 450,
    selectors: {
      chatContainer: ".chat-history-container, [data-chat-history], .message-list",
      messageItem: ".message-bubble, [data-message], .chat-message",
      clientMessage: ".client-msg, .message-in, [data-sender='client']",
      operatorMessage: ".operator-msg, .message-out, [data-sender='operator']",
      claimStatus: ".status-badge, [data-status], .claim-status",
      chatId: "[data-chat-id], .conversation-id",
      clientName: ".client-name, [data-client-name]",
      logbookButton: "#open-logbook-btn, [data-open-logbook]",
      logbookFields: {
        clientName: "#logbook-client-name, [name='clientName']",
        clientCity: "#logbook-client-city, [name='clientCity']",
        clientInterests: "#logbook-interests, [name='interests']",
        personaCity: "#logbook-my-city, [name='personaCity']",
      },
      saveLogbookBtn: "#save-logbook-btn, [data-save-logbook]",
      inputBox: "textarea.reply-input, textarea[name='message'], [contenteditable='true'].reply-input",
      sendButton: "button.send, [data-send], button[type='submit']",
    },
  };

  if (CONFIG.autoSend) {
    console.error("[Copilot] autoSend is forbidden. Leaving.");
    return;
  }

  const state = {
    lastStatus: "",
    lastChatId: "",
    busy: false,
  };

  function qs(sel, root) {
    if (!sel) return null;
    const node = root || document;
    for (const part of sel.split(",")) {
      const hit = node.querySelector(part.trim());
      if (hit) return hit;
    }
    return null;
  }

  function qsa(sel, root) {
    const node = root || document;
    const out = [];
    const seen = new Set();
    for (const part of sel.split(",")) {
      node.querySelectorAll(part.trim()).forEach((el) => {
        if (!seen.has(el)) {
          seen.add(el);
          out.push(el);
        }
      });
    }
    return out;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function setNativeValue(el, value) {
    if (!el) return false;
    if (el.isContentEditable) {
      el.focus();
      el.textContent = value;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function statusText() {
    const el = qs(CONFIG.selectors.claimStatus);
    return (el && (el.innerText || el.textContent || el.getAttribute("data-status"))) || "";
  }

  function chatId() {
    const el = qs(CONFIG.selectors.chatId);
    if (el) return (el.getAttribute("data-chat-id") || el.innerText || "").trim();
    return location.pathname + location.hash;
  }

  function isClaimed(text) {
    const t = (text || "").toLowerCase();
    if (/\bunclaimed\b/.test(t)) return false;
    return /\bclaimed\b/.test(t);
  }

  function claimRisingEdge(prev, curr) {
    return isClaimed(curr) && !isClaimed(prev);
  }

  function senderFor(el) {
    if (el.matches(CONFIG.selectors.clientMessage) || el.classList.contains("client-msg")) return "client";
    if (el.matches(CONFIG.selectors.operatorMessage) || el.classList.contains("operator-msg")) return "operator";
    if (el.closest && el.closest(CONFIG.selectors.clientMessage)) return "client";
    if (el.closest && el.closest(CONFIG.selectors.operatorMessage)) return "operator";
    const side = (el.getAttribute("data-sender") || "").toLowerCase();
    if (side === "client" || side === "operator") return side;
    return el.className.toLowerCase().includes("out") ? "operator" : "client";
  }

  async function scrollAndFetchHistory() {
    const box = qs(CONFIG.selectors.chatContainer);
    if (!box) return readMessages();
    for (let i = 0; i < CONFIG.scrollPasses; i += 1) {
      const before = box.scrollHeight;
      box.scrollTop = Math.max(0, box.scrollTop - box.clientHeight);
      if (box.scrollTop === 0) box.scrollTop = 0;
      await sleep(CONFIG.scrollWaitMs);
      if (box.scrollHeight <= before && box.scrollTop === 0) break;
    }
    return readMessages();
  }

  function readMessages() {
    return qsa(CONFIG.selectors.messageItem).map((el) => ({
      sender: senderFor(el),
      text: (el.innerText || "").trim(),
    })).filter((row) => row.text);
  }

  function engineRequest(path, payload) {
    return new Promise((resolve, reject) => {
      const url = CONFIG.engineUrl.replace(/\/$/, "") + path;
      if (typeof GM_xmlhttpRequest === "function") {
        GM_xmlhttpRequest({
          method: payload ? "POST" : "GET",
          url,
          headers: { "Content-Type": "application/json" },
          data: payload ? JSON.stringify(payload) : undefined,
          onload: (res) => {
            try {
              resolve(JSON.parse(res.responseText || "{}"));
            } catch (err) {
              reject(err);
            }
          },
          onerror: () => reject(new Error("controller offline — start python3 -m offline_copilot serve")),
        });
        return;
      }
      fetch(url, {
        method: payload ? "POST" : "GET",
        headers: { "Content-Type": "application/json" },
        body: payload ? JSON.stringify(payload) : undefined,
      }).then((r) => r.json()).then(resolve).catch(reject);
    });
  }

  async function fillLogbook(fields, shouldSave) {
    const openBtn = qs(CONFIG.selectors.logbookButton);
    if (openBtn) {
      openBtn.click();
      await sleep(250);
    }
    const map = CONFIG.selectors.logbookFields;
    if (fields.clientName) setNativeValue(qs(map.clientName), fields.clientName);
    if (fields.clientCity) setNativeValue(qs(map.clientCity), fields.clientCity);
    if (fields.clientInterests) setNativeValue(qs(map.clientInterests), fields.clientInterests);
    if (fields.personaCity) setNativeValue(qs(map.personaCity), fields.personaCity);
    if (shouldSave && CONFIG.autoSaveLogbook) {
      const save = qs(CONFIG.selectors.saveLogbookBtn);
      const send = qs(CONFIG.selectors.sendButton);
      if (save && save !== send) save.click();
    }
  }

  function fillDraft(text) {
    if (!CONFIG.autoFillDraft || !text) return;
    const box = qs(CONFIG.selectors.inputBox);
    if (!box) return;
    setNativeValue(box, text);
  }

  function showPanel(payload) {
    let panel = document.getElementById("ocp-panel");
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "ocp-panel";
      panel.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483647;max-width:380px;background:#111;color:#eee;border:1px solid #444;border-radius:10px;padding:12px;font:13px/1.4 sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.4)";
      document.body.appendChild(panel);
    }
    const options = payload.options || [];
    const blocked = payload.blocked ? `<div style="color:#f66">${payload.reason || "blocked"}</div>` : "";
    panel.innerHTML = `<strong>Offline copilot</strong> · never sends
      ${blocked}
      ${options.map((opt, i) => `<div style="margin-top:8px"><em>Option ${i + 1}</em><div>${opt}</div></div>`).join("")}
      <div style="margin-top:8px;opacity:.7">${payload.save_reason || ""}</div>`;
  }

  async function processClaimedChat() {
    if (state.busy) return;
    state.busy = true;
    try {
      const history = await scrollAndFetchHistory();
      const nameEl = qs(CONFIG.selectors.clientName);
      const payload = {
        client_id: chatId(),
        client_name: nameEl ? (nameEl.innerText || "").trim() : "",
        persona_city: CONFIG.personaCity || "",
        history,
        remember: true,
      };
      const result = await engineRequest("/claim", payload);
      showPanel(result);
      if (result.logbook_fields) {
        await fillLogbook(result.logbook_fields, !!result.save_logbook);
      }
      const draft = result.fill_draft || (result.options && result.options[0]);
      if (draft) fillDraft(draft);
    } catch (err) {
      showPanel({ blocked: true, reason: String(err && err.message ? err.message : err), options: [] });
    } finally {
      state.busy = false;
    }
  }

  function tick() {
    const status = statusText();
    const id = chatId();
    if (id !== state.lastChatId) {
      state.lastChatId = id;
      state.lastStatus = "";
    }
    if (claimRisingEdge(state.lastStatus, status)) {
      processClaimedChat();
    }
    state.lastStatus = status;
  }

  const observer = new MutationObserver(() => {
    if (tick._t) return;
    tick._t = setTimeout(() => {
      tick._t = 0;
      tick();
    }, 200);
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  tick();
})();
