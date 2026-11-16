// Wabi: the robot bee flies from the hive (next to the logo) to the chat window.
"use strict";

(() => {
  const home = document.getElementById("wabi-home");
  const panel = document.getElementById("wabi-panel");
  if (!home || !panel) return;

  const flyer = document.getElementById("wabi-flyer");
  const avatar = document.getElementById("wabi-avatar");
  const log = document.getElementById("wabi-log");
  const form = document.getElementById("wabi-form");
  const input = document.getElementById("wabi-input");
  const hint = document.getElementById("wabi-hint");
  const suggestions = document.getElementById("wabi-suggestions");
  const sendButton = form.querySelector("button[type='submit']");
  const configured = panel.dataset.configured === "1";
  const HINT_KEY = "wabi-hinweis-gelesen";
  const history = [];  // only in memory: gone when the page is left
  let busy = false;

  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function storageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
  function storageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* ignore */ } }

  function wiggle(element) {
    element.classList.remove("is-wiggling");
    void element.offsetWidth;  // restart the animation
    element.classList.add("is-wiggling");
    setTimeout(() => element.classList.remove("is-wiggling"), 1500);
  }

  // The flying bee: from one element's position to another's.
  function fly(from, to) {
    if (reducedMotion() || !flyer.animate) return Promise.resolve();
    const a = from.getBoundingClientRect();
    const b = to.getBoundingClientRect();
    const midX = (a.left + b.left) / 2 - 40;
    const midY = Math.min(a.top, b.top) + Math.abs(b.top - a.top) * 0.35;
    flyer.classList.add("is-flying");
    const animation = flyer.animate([
      { transform: `translate(${a.left}px, ${a.top}px) rotate(0deg)` },
      { transform: `translate(${midX}px, ${midY}px) rotate(12deg) scale(1.15)` },
      { transform: `translate(${b.left}px, ${b.top}px) rotate(0deg)` },
    ], { duration: 650, easing: "ease-in-out" });
    return animation.finished.catch(() => {}).then(() => flyer.classList.remove("is-flying"));
  }

  function addMessage(text, from, isError = false) {
    const bubble = document.createElement("div");
    bubble.className = `wabi-msg from-${from}` + (isError ? " is-error" : "");
    bubble.textContent = text;  // never HTML: safe against injected markup
    log.append(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  // Link buttons from Wabi: only addresses inside this app are allowed.
  function addLinks(links) {
    const safe = (links || []).filter((link) =>
      typeof link.url === "string" && link.url.startsWith("/") && !link.url.startsWith("//") && !link.url.includes("\\"));
    if (!safe.length) return;
    const row = document.createElement("div");
    row.className = "wabi-links";
    for (const link of safe) {
      const a = document.createElement("a");
      a.className = "wabi-link";
      a.href = link.url;
      a.textContent = `Zu ${link.title} →`;
      row.append(a);
    }
    log.append(row);
    log.scrollTop = log.scrollHeight;
  }

  function greet() {
    if (log.childElementCount) return;
    addMessage(configured
      ? "Hallo, ich bin Wabi! Frag mich etwas zu deinen Finanzen, zum Beispiel was du im Oktober für Supermarkt ausgegeben hast."
      : "Hallo, ich bin Wabi! Ich muss noch eingerichtet werden: Lege deinen API-Schlüssel als Datei „anthropic_api_key“ in den Finanzwabe-Ordner in OneDrive und starte die App neu.",
    "wabi");
  }

  async function open() {
    if (!panel.hidden) return;
    home.setAttribute("aria-expanded", "true");
    panel.hidden = false;
    panel.classList.add("is-measuring");
    avatar.classList.add("is-hidden");
    home.classList.add("is-away");
    await fly(home, avatar);
    panel.classList.remove("is-measuring");
    panel.classList.add("is-opening");
    setTimeout(() => panel.classList.remove("is-opening"), 300);
    avatar.classList.remove("is-hidden");
    hint.hidden = storageGet(HINT_KEY) === "1";
    greet();
    input.focus();
  }

  async function close() {
    if (panel.hidden) return;
    home.setAttribute("aria-expanded", "false");
    avatar.classList.add("is-hidden");
    const start = avatar;
    panel.classList.add("is-measuring");
    await fly(start, home);
    panel.hidden = true;
    panel.classList.remove("is-measuring");
    avatar.classList.remove("is-hidden");
    home.classList.remove("is-away");
    home.focus();
  }

  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    busy = true;
    sendButton.disabled = true;
    suggestions.hidden = true;
    addMessage(question, "user");
    history.push({ role: "user", content: question });
    const typing = document.createElement("div");
    typing.className = "wabi-msg from-wabi wabi-typing";
    typing.setAttribute("aria-label", "Wabi schreibt …");
    typing.innerHTML = "<i></i><i></i><i></i>";
    log.append(typing);
    log.scrollTop = log.scrollHeight;

    let reply = "Ich konnte gerade nicht antworten. Versuch es bitte noch einmal.";
    let failed = true;
    let links = [];
    try {
      const response = await fetch(panel.dataset.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": panel.dataset.csrf },
        body: JSON.stringify({ messages: history.slice(-12) }),
      });
      const data = await response.json();
      if (data.reply) reply = data.reply;
      else if (data.error) reply = data.error;
      failed = !response.ok || Boolean(data.error) || data.configured === false;
      links = data.links || [];
    } catch {
      reply = "Ich erreiche die App gerade nicht. Bist du noch verbunden?";
    }
    typing.remove();
    addMessage(reply, "wabi", failed && reply !== "" && !reply.startsWith("Ich bin noch nicht"));
    if (!failed) addLinks(links);
    if (failed) history.pop();  // keep only real question/answer pairs
    else {
      // Wabi only sees text in the history, so note which link buttons were shown.
      const note = links.length ? `\n[Link-Knöpfe: ${links.map((link) => link.title).join(", ")}]` : "";
      history.push({ role: "assistant", content: reply + note });
    }
    wiggle(avatar);
    busy = false;
    sendButton.disabled = false;
    input.focus();
  }

  home.addEventListener("click", () => (panel.hidden ? open() : close()));
  document.getElementById("wabi-close").addEventListener("click", close);
  document.getElementById("wabi-hint-ok").addEventListener("click", () => {
    storageSet(HINT_KEY, "1");
    hint.hidden = true;
    input.focus();
  });
  panel.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value;
    input.value = "";
    input.style.height = "";
    ask(text);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  });
  suggestions.addEventListener("click", (event) => {
    const chip = event.target.closest(".wabi-chip");
    if (chip) ask(chip.textContent);
  });

  // Wabi has something to say: the cloud notice was not read yet.
  if (storageGet(HINT_KEY) !== "1") setTimeout(() => wiggle(home), 1200);
})();
