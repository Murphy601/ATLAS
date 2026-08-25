// ==UserScript==
// @name         Offline Chat Copilot
// @namespace    local.offline-chat-copilot
// @version      1.2
// @description  Chat Home Base claimed chats: scroll history, local engine, fill logbook + draft. Never sends.
// @match        https://chathomebase.com/*
// @match        https://*.chathomebase.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// ==UserScript==

/*
  Preferred: attach from Python to the already-open IX profile:

    cd offline-chat-copilot
    python -m offline_copilot attach

  This userscript is the in-page fallback. Never clicks Send.
*/

(function () {
  "use strict";

  const CONFIG = {
    engineUrl: "http://127.0.0.1:8765",
    personaCity: "",
    autoFillDraft: true,
    autoSaveLogbook: true,
    autoSend: false, // locked. This script never clicks Send.
    scrollPasses: 12,
    scrollWaitMs: 450,
    selectors: {
      chatContainer: '[data-testid="messagesList"]',
      messageItem: '[data-testid="messageItem"]',
      clientMessage: ".message-customer",
      operatorMessage: ".message-profile",
      claimLoader: '[data-testid="claimLoaderContainer"]',
      draftRoot: '[data-testid="messageTextArea"]',
      chatId: '[data-testid="chat-id"]',
      clientName: '[data-testid="logbookCustomerName"]',
      profileLocation: '[data-testid="profileLocation"]',
      logbookButton: '[data-testid="addNewLogbookButton-customer"]',
      logbookCategory: '[data-testid="logbookCategorySelect"]',
      logbookComment: '[data-testid="logbookComment"]',
      logbookFields: {
        clientName: '[data-testid="logbookCustomerName"]',
        clientCity: '[data-testid="profileLocation"]',
        clientInterests: '[data-testid="logbookComment"]',
        personaCity: '[data-testid="logbookProfileName"]',
      },
      saveLogbookBtn: '[data-testid="logbookSaveButton"]',
      inputBox: '[data-testid="messageTextArea"] textarea, [data-testid="messageTextArea"]',
      sendButton: '[data-testid="sendChatMessageButton"]',
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
    const target = el.tagName === "TEXTAREA" || el.tagName === "INPUT" ? el : el.querySelector("textarea, input") || el;
    if (target.isContentEditable) {
      target.focus();
      target.textContent = value;
      target.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }
    const proto = target.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(target, value);
    else target.value = value;
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function isLiveClaimed() {
    const loader = qs(CONFIG.selectors.claimLoader);
    const draft = qs(CONFIG.selectors.draftRoot);
    if (loader && !draft) return false;
    return !!draft;
  }

  function statusText() {
    return isLiveClaimed() ? "claimed" : "waiting";
  }

  function chatId() {
    const el = qs(CONFIG.selectors.chatId);
    if (el) return (el.getAttribute("data-chat-id") || el.innerText || "").trim();
    return location.pathname + location.hash;
  }

  function isClaimed(text) {
    const t = (text || "").toLowerCase();
    if (/\bunclaimed\b/.test(t) || t === "waiting") return false;
    return t === "claimed" || /\bclaimed\b/.test(t);
  }

  function claimRisingEdge(prev, curr) {
    return isClaimed(curr) && !isClaimed(prev);
  }

  function senderFor(el) {
    if (el.querySelector && el.querySelector(".message-customer")) return "client";
    if (el.querySelector && el.querySelector(".message-profile")) return "operator";
    if (el.matches && (el.matches(CONFIG.selectors.clientMessage) || el.classList.contains("message-customer"))) return "client";
    if (el.matches && (el.matches(CONFIG.selectors.operatorMessage) || el.classList.contains("message-profile"))) return "operator";
    return "client";
  }

  async function scrollAndFetchHistory() {
    const box = qs(CONFIG.selectors.chatContainer);
    if (!box) return readMessages();
    let root = box;
    for (let hop = 0; hop < 8 && root && root.scrollHeight <= root.clientHeight + 4; hop += 1) {
      root = root.parentElement;
    }
    root = root || box;
    for (let i = 0; i < CONFIG.scrollPasses; i += 1) {
      const before = qsa(CONFIG.selectors.messageItem).length;
      root.scrollTop = 0;
      const zone = document.querySelector(".trigger-zone");
      if (zone && zone.scrollIntoView) zone.scrollIntoView({ block: "start" });
      await sleep(CONFIG.scrollWaitMs);
      const after = qsa(CONFIG.selectors.messageItem).length;
      if (after === before && root.scrollTop === 0) break;
    }
    root.scrollTop = root.scrollHeight;
    await sleep(200);
    return readMessages();
  }

  function readMessages() {
    return qsa(CONFIG.selectors.messageItem).map((el) => ({
      sender: senderFor(el),
      text: ((el.querySelector(".message-content") || el).innerText || "").trim(),
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

  function composeComment(fields) {
    const parts = [];
    if (fields.clientName) parts.push("Name: " + fields.clientName);
    if (fields.clientCity) parts.push("City: " + fields.clientCity);
    if (fields.clientInterests) parts.push("Interests: " + fields.clientInterests);
    return parts.join(". ");
  }

  async function fillLogbook(fields, shouldSave) {
    const openBtn = qs(CONFIG.selectors.logbookButton);
    if (openBtn) {
      openBtn.click();
      await sleep(250);
    }
    const category = qs(CONFIG.selectors.logbookCategory);
    if (category) {
      category.click();
      await sleep(150);
      const other = [...document.querySelectorAll(".v-list-item, [role='option']")].find((el) => (el.innerText || "").trim() === "Other");
      if (other) other.click();
      await sleep(150);
    }
    const comment = composeComment(fields);
    if (comment) setNativeValue(qs(CONFIG.selectors.logbookComment), comment);
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
    const target = box.tagName === "TEXTAREA" || box.tagName === "INPUT" ? box : box.querySelector("textarea, input") || box;
    target.focus();
    if (typeof target.select === "function") {
      try { target.select(); } catch (err) {}
    }
    document.execCommand("delete");
    for (const ch of String(text)) {
      if (ch === "\n" || ch === "\r") continue;
      document.execCommand("insertText", false, ch);
    }
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

  function personaCity() {
    if (CONFIG.personaCity) return CONFIG.personaCity;
    const el = qs(CONFIG.selectors.profileLocation);
    if (!el) return "";
    const blob = ((el.parentElement && el.parentElement.innerText) || el.innerText || "").trim();
    const match = blob.match(/locality:\s*([^,\n]+)/i);
    return match ? match[1].trim() : "";
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
        persona_city: personaCity(),
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
