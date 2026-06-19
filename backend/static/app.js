const form = document.getElementById("form");
const submitBtn = document.getElementById("submit");
const logsEl = document.getElementById("logs");
const statusEl = document.getElementById("status");
const healthEl = document.getElementById("health");

let source = null;

function setStatus(label, cls) {
  statusEl.textContent = label;
  statusEl.className = "status " + cls;
}

function addLog(ev) {
  const li = document.createElement("li");
  li.className = ev.level || "info";
  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = new Date().toLocaleTimeString();
  li.appendChild(ts);
  li.appendChild(document.createTextNode(ev.message));
  logsEl.appendChild(li);
  logsEl.scrollTop = logsEl.scrollHeight;
}

async function loadHealth() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    const items = [
      ["GitHub", d.config.github],
      ["Cloudflare", d.config.cloudflare],
      ["NPM", d.config.npm],
    ];
    healthEl.innerHTML = "";
    for (const [name, ok] of items) {
      const span = document.createElement("span");
      span.className = "badge " + (ok ? "on" : "off");
      span.textContent = (ok ? "● " : "○ ") + name;
      healthEl.appendChild(span);
    }
  } catch (_) {
    /* silencieux */
  }
}

function listen(jobId) {
  if (source) source.close();
  source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    addLog(ev);
    if (ev.done) {
      setStatus(ev.ok ? "succès" : "échec", ev.ok ? "ok" : "err");
      source.close();
      submitBtn.disabled = false;
    }
  };
  source.onerror = () => {
    // Le serveur ferme le flux à la fin du job ; on ne réactive le bouton
    // que si aucun statut final n'a été reçu.
    if (!statusEl.classList.contains("ok") && !statusEl.classList.contains("err")) {
      addLog({ level: "error", message: "Connexion au flux de logs perdue." });
      setStatus("déconnecté", "err");
      submitBtn.disabled = false;
    }
    source.close();
  };
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  logsEl.innerHTML = "";
  submitBtn.disabled = true;
  setStatus("en cours", "running");

  const fd = new FormData(form);
  const payload = {
    domain: fd.get("domain").trim(),
    site_type: fd.get("site_type"),
    target_port: Number(fd.get("target_port")),
    repo_name: fd.get("repo_name").trim(),
    private: fd.get("private") === "on",
  };

  try {
    const r = await fetch("/api/provision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      const detail = err.detail
        ? typeof err.detail === "string"
          ? err.detail
          : JSON.stringify(err.detail)
        : `HTTP ${r.status}`;
      throw new Error(detail);
    }
    const { job_id } = await r.json();
    addLog({ level: "info", message: `Job démarré : ${job_id}` });
    listen(job_id);
  } catch (err) {
    addLog({ level: "error", message: "Erreur : " + err.message });
    setStatus("échec", "err");
    submitBtn.disabled = false;
  }
});

loadHealth();
