const form = document.getElementById("form");
const submitBtn = document.getElementById("submit");
const logsEl = document.getElementById("logs");
const statusEl = document.getElementById("status");
const healthEl = document.getElementById("health");
const hasBackend = document.getElementById("has_backend");
const backendFields = document.getElementById("backend_fields");

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

// Affiche/masque la section backend et (dé)active ses champs requis.
function toggleBackend() {
  const on = hasBackend.checked;
  backendFields.hidden = !on;
  for (const n of ["be_domain", "be_container", "be_port"]) {
    form.elements[n].required = on;
    if (!on) form.elements[n].value = "";
  }
  // Suggère api-<frontend> si le domaine backend est vide.
  if (on && !form.elements.be_domain.value && form.elements.fe_domain.value) {
    form.elements.be_domain.value = "api-" + form.elements.fe_domain.value.trim();
  }
}
hasBackend.addEventListener("change", toggleBackend);
form.elements.fe_domain.addEventListener("blur", () => {
  if (hasBackend.checked && !form.elements.be_domain.value && form.elements.fe_domain.value) {
    form.elements.be_domain.value = "api-" + form.elements.fe_domain.value.trim();
  }
});

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
    repo_name: fd.get("repo_name").trim(),
    site_type: fd.get("site_type"),
    private: fd.get("private") === "on",
    frontend: {
      domain: fd.get("fe_domain").trim(),
      container: fd.get("fe_container").trim(),
      port: Number(fd.get("fe_port")),
    },
    backend: hasBackend.checked
      ? {
          domain: fd.get("be_domain").trim(),
          container: fd.get("be_container").trim(),
          port: Number(fd.get("be_port")),
        }
      : null,
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

// Copie du mémo de pré-requis dans le presse-papier.
const copyBtn = document.getElementById("copy-setup");
if (copyBtn) {
  copyBtn.addEventListener("click", async () => {
    const text = document.getElementById("setup-prompt").textContent;
    try {
      await navigator.clipboard.writeText(text);
      copyBtn.textContent = "Copié ✓";
    } catch (_) {
      // Fallback si l'API clipboard est indisponible (http, vieux navigateur).
      const r = document.createRange();
      r.selectNodeContents(document.getElementById("setup-prompt"));
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      document.execCommand("copy");
      copyBtn.textContent = "Copié ✓";
    }
    setTimeout(() => (copyBtn.textContent = "Copier"), 2000);
  });
}

loadHealth();
