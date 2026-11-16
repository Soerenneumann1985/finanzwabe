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
    // Browsers pause animations on pages that are not drawn (app in the background).
    // The chat window must open anyway, so the flight ends after 0.9 s at the latest.
    const timeout = new Promise((resolve) => setTimeout(resolve, 900));
    return Promise.race([animation.finished.catch(() => {}), timeout]).then(() => {
      animation.cancel();
      flyer.classList.remove("is-flying");
    });
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
    stopListening();
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

  // --- Booking suggestion: preview card, saved only with "Bestätigen" ----------------------
  function addProposal(p, historyEntry) {
    const summary = `${p.amount_label} ${p.description || p.category}`.replace(/[[\]]/g, "");
    const mark = (state) => {  // tells Wabi in the next request what became of the suggestion
      historyEntry.content = historyEntry.content.replace(/\n\[Vorschlag[^\]]*\]$/, "") +
        `\n[Vorschlag ${summary}: ${state}]`;
    };
    mark("offen, noch nicht gespeichert");

    const card = document.createElement("div");
    card.className = "wabi-card";
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", "Buchungsvorschlag");
    const title = document.createElement("div");
    title.className = "wabi-card-title";
    title.textContent = `Vorschlag: ${p.kind_label}`;
    const rows = document.createElement("dl");
    const fields = [["Datum", p.date_label], ["Betrag", p.amount_label], ["Beschreibung", p.description || "–"],
                    ["Kategorie", p.category], [p.counter_account ? "Von Konto" : "Konto", p.account]];
    if (p.counter_account) fields.push(["Auf Konto", p.counter_account]);
    for (const [label, value] of fields) {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      rows.append(dt, dd);
    }
    const status = document.createElement("p");
    status.className = "wabi-card-status";
    status.setAttribute("role", "status");
    status.textContent = "Noch nicht gespeichert.";

    const actions = document.createElement("div");
    actions.className = "wabi-card-actions";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "wabi-card-confirm";
    confirm.textContent = "Bestätigen";
    const change = document.createElement("a");
    change.className = "wabi-card-secondary";
    change.textContent = "Ändern";
    const params = new URLSearchParams({ datum: p.date, art: p.kind, betrag: p.amount, beschreibung: p.description,
                                         kategorie: p.category_id, konto: p.account_id });
    if (p.counter_account_id) params.set("gegenkonto", p.counter_account_id);
    change.href = `${panel.dataset.newBookingUrl}?${params}`;
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "wabi-card-secondary";
    cancel.textContent = "Abbrechen";
    actions.append(confirm, change, cancel);

    card.append(title, rows, status, actions);
    log.append(card);
    log.scrollTop = log.scrollHeight;

    const finish = (state, text) => {
      card.classList.add(`is-${state}`);
      status.textContent = text;
      actions.replaceChildren();
    };

    cancel.addEventListener("click", () => {
      finish("cancelled", "Abgebrochen. Es wurde nichts gespeichert.");
      mark("abgebrochen, nicht gespeichert");
    });

    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      cancel.disabled = true;
      status.textContent = "Speichere …";
      try {
        const response = await fetch(panel.dataset.bookingUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": panel.dataset.csrf },
          body: JSON.stringify({ amount: p.amount, category_id: p.category_id, account_id: p.account_id,
                                 counter_account_id: p.counter_account_id, description: p.description,
                                 date: p.date }),
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Speichern hat nicht geklappt.");
        finish("saved", "✓ Gespeichert.");
        mark("vom Nutzer gespeichert");
        if (data.month_url && data.month_url.startsWith("/") && !data.month_url.startsWith("//")) {
          const link = document.createElement("a");
          link.className = "wabi-link";
          link.href = data.month_url;
          link.textContent = `Im ${data.month_label} ansehen →`;
          actions.append(link);
        }
        wiggle(avatar);
      } catch (error) {
        status.textContent = error.message || "Speichern hat nicht geklappt.";
        confirm.disabled = false;
        cancel.disabled = false;
      }
    });
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
    let proposal = null;
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
      proposal = data.proposal || null;
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
      if (proposal) addProposal(proposal, history[history.length - 1]);
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

  // --- Voice input (Web Speech API of the browser) -------------------------------------------
  // Only on secure pages (HTTPS or localhost): browsers block the microphone elsewhere,
  // e.g. on http://192.168.… in the home Wi-Fi. Then the button stays hidden and typing works.
  const mic = document.getElementById("wabi-mic");
  const Recognition = () => window.SpeechRecognition || window.webkitSpeechRecognition;
  const SPEECH_ERRORS = {
    "not-allowed": "Ich darf das Mikrofon nicht benutzen. Erlaube es in den Browser-Einstellungen für diese Seite.",
    "service-not-allowed": "Die Spracherkennung ist in diesem Browser gesperrt. Du kannst deine Frage gern tippen.",
    "no-speech": "Ich habe nichts gehört. Tipp noch mal aufs Mikrofon und sprich ruhig etwas lauter.",
    "audio-capture": "Ich finde kein Mikrofon. Ist eins angeschlossen?",
    "network": "Die Spracherkennung ist gerade nicht erreichbar. Du kannst deine Frage gern tippen.",
  };
  let recognition = null;
  const placeholder = input.placeholder;

  function setListening(on) {
    mic.classList.toggle("is-listening", on);
    mic.setAttribute("aria-pressed", on ? "true" : "false");
    mic.setAttribute("aria-label", on ? "Spracheingabe beenden" : "Spracheingabe starten");
    input.placeholder = on ? "Ich höre zu …" : placeholder;
  }

  function stopListening() {
    if (recognition) recognition.abort();
  }

  function startListening() {
    const SpeechRecognition = Recognition();
    if (!SpeechRecognition || busy) return;
    const session = new SpeechRecognition();
    session.lang = "de-DE";
    session.interimResults = true;  // show the words while speaking
    session.continuous = false;     // one question, then stop by itself
    session.maxAlternatives = 1;
    let spoken = "";
    let failed = false;

    session.onresult = (event) => {
      spoken = Array.from(event.results).map((result) => result[0].transcript).join("");
      input.value = spoken;
    };
    session.onerror = (event) => {
      failed = true;
      if (event.error !== "aborted") {
        addMessage(SPEECH_ERRORS[event.error] || "Die Spracheingabe hat nicht geklappt. Du kannst gern tippen.",
                   "wabi", true);
      }
    };
    session.onend = () => {
      recognition = null;
      setListening(false);
      const question = spoken.trim();
      if (!failed && question) {
        input.value = "";
        ask(question);  // a booking still needs "Bestätigen" on the card
      }
    };

    try {
      session.start();
    } catch {
      addMessage("Die Spracheingabe ließ sich nicht starten. Du kannst gern tippen.", "wabi", true);
      return;
    }
    recognition = session;
    setListening(true);
  }

  if (mic && Recognition() && window.isSecureContext) {
    mic.hidden = false;
    mic.addEventListener("click", () => (recognition ? recognition.stop() : startListening()));
  }

  // Wabi has something to say: the cloud notice was not read yet.
  if (storageGet(HINT_KEY) !== "1") setTimeout(() => wiggle(home), 1200);
})();
