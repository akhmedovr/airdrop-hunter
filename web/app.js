const API = "";
const SUPABASE_URL = "https://pgzsuidkgxtoxnnxodfv.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_tyDBw7jgciKdIdlFz1sBgQ_wBZPpoxd";
const authClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
let authSession = null;
const toast = document.getElementById("toast");
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function activateView(name) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.id === "view-" + name);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => activateView(button.dataset.view));
});
document.querySelectorAll("[data-go]").forEach((button) => {
  button.addEventListener("click", () => activateView(button.dataset.go));
});

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n);
}

async function request(path, options = {}) {
  const response = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(authSession?.access_token ? { Authorization: `Bearer ${authSession.access_token}` } : {}), ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

async function loadAppData() {
  const connection = document.getElementById("connection");
  const status = document.getElementById("systemStatus");
  try {
    const health = await request("/api/health");
    connection.classList.add("online");
    connection.innerHTML = "<i></i> Сервер подключён";
    status.textContent = health.status === "ok" ? "Система на связи" : "Сервер отвечает";
    const dashboard = await request("/api/dashboard");
    await loadAcurastProcessor();
    document.getElementById("metricCampaigns").textContent = dashboard.active_campaigns ?? "—";
    document.getElementById("metricTasks").textContent = dashboard.tasks_today ?? "—";
    document.getElementById("metricClaimable").textContent = formatMoney(dashboard.claimable_rewards_usd);
    document.getElementById("metricPnl").textContent = formatMoney(dashboard.realized_pnl_usd);
    const notifications = await request("/api/notifications");
    const unread = Number(notifications.unread_count || 0);
    document.getElementById("unreadCount").textContent = String(unread);
  } catch (error) {
    connection.classList.remove("online");
    connection.innerHTML = "<i></i> Сервер не подключён";
    status.textContent = "Ожидает подключения сервера";
  }
}

const ACURAST_PROCESSOR_ADDRESS = "5CY4Yme4LjjSAM36Pcb8tqAwAokdGb2SmYfPUr5ukPuXDqNY";
const ACURAST_MANAGER_ADDRESS = "5CrVT6Yca1njygjKDSRRQ3XiVazKXcGu2XDwoK1BDM3J4FQK";

function renderAcurastProcessor(item) {
  const status = document.getElementById("acurastStatus");
  const note = document.getElementById("acurastNote");
  const button = document.getElementById("connectAcurastButton");
  if (!status || !note || !button) return;
  if (!item) {
    status.textContent = "Не подключён";
    button.disabled = false;
    button.textContent = "Подключить к Airdrop Hunter";
    note.textContent = "Статус Hub пока не синхронизируется автоматически. Сохраняем только публичные идентификаторы и подтверждённые тобой сведения.";
    return;
  }
  status.textContent = item.hub_status === "reported_active" ? "Active · по Hub" : "Сохранён";
  button.disabled = true;
  button.textContent = "Устройство подключено";
  note.textContent = "Сохранено " + new Date(item.observed_at).toLocaleString("ru-RU") + ". Attested: " + (item.attested ? "да" : "не подтверждено") + "; Reputation: " + (item.reputation ?? "—") + "; версия: " + (item.processor_version || "—") + ". Это последнее подтверждённое наблюдение, не live-мониторинг.";
}

async function loadAcurastProcessor() {
  if (!authSession?.access_token) return;
  try {
    const data = await request("/api/acurast/processors");
    const item = (data.items || []).find((row) => row.processor_address === ACURAST_PROCESSOR_ADDRESS);
    renderAcurastProcessor(item);
  } catch (error) {
    const note = document.getElementById("acurastNote");
    if (note) note.textContent = "Не удалось загрузить устройство: " + error.message;
  }
}

document.getElementById("connectAcurastButton")?.addEventListener("click", async () => {
  const button = document.getElementById("connectAcurastButton");
  button.disabled = true;
  button.textContent = "Сохраняю…";
  try {
    const result = await request("/api/acurast/processors", {
      method: "POST",
      body: JSON.stringify({
        processor_address: ACURAST_PROCESSOR_ADDRESS,
        manager_address: ACURAST_MANAGER_ADDRESS,
        label: "iPhone Acurast Lite",
        attested: true,
        reputation: 0.5,
        processor_version: "Lite 1.11.0",
      }),
    });
    renderAcurastProcessor(result.item);
    showToast("Acurast Processor добавлен в Airdrop Hunter.");
  } catch (error) {
    button.disabled = false;
    button.textContent = "Повторить подключение";
    showToast("Не удалось сохранить Acurast: " + error.message);
  }
});

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    showToast("Этот браузер не поддерживает Web Push. На iPhone открой PWA с экрана «Домой».");
    return;
  }
  try {
    const config = await request("/api/push/public-key");
    if (!config.public_key) throw new Error("VAPID public key is not configured");
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("Разрешение на уведомления не выдано");
    const registration = await navigator.serviceWorker.register("/sw.js");
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key),
    });
    await request("/api/push/subscribe", {
      method: "POST",
      body: JSON.stringify(subscription),
    });
    document.getElementById("pushStatus").textContent = "Включено";
    showToast("Push-уведомления включены.");
  } catch (error) {
    showToast("Push пока недоступен: " + error.message);
  }
}

document.getElementById("enablePush").addEventListener("click", enablePush);
document.getElementById("refreshButton").addEventListener("click", () => {
  loadAppData();
  showToast("Обновляю данные…");
});

let deferredInstallPrompt = null;
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  const button = document.getElementById("installButton");
  if (button) button.hidden = false;
});
const installButton = document.getElementById("installButton");
if (installButton) {
  installButton.addEventListener("click", async () => {
    if (!deferredInstallPrompt) {
      showToast("В Safari нажми «Поделиться» → «На экран Домой».");
      return;
    }
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
  });
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}

const today = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" }).format(new Date());
document.getElementById("todayLabel").textContent = today;
loadAppData();

const authGate = document.getElementById("authGate");
const authMessage = document.getElementById("authMessage");
const signOutButton = document.getElementById("signOutButton");
function setAuthenticated(session) {
  authSession = session;
  const active = Boolean(session?.access_token);
  authGate.hidden = active;
  signOutButton.hidden = !active;
  document.querySelector("main").style.visibility = active ? "visible" : "hidden";
  document.querySelector(".mobile-nav").style.visibility = active ? "visible" : "hidden";
  if (active) loadAppData();
}
document.getElementById("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("loginEmail").value.trim().toLowerCase();
  const password = document.getElementById("loginPassword").value;
  const submit = event.currentTarget.querySelector('button[type="submit"]');
  submit.disabled = true;
  authMessage.textContent = "Проверяю доступ…";
  try {
    let result = await authClient.auth.signInWithPassword({ email, password });
    if (result.error && /invalid login credentials/i.test(result.error.message)) {
      const created = await authClient.auth.signUp({ email, password });
      if (created.error) throw created.error;
      if (!created.data.session) {
        throw new Error("Регистрация требует подтверждения email. Владелец проекта должен отключить Email confirmations в Supabase Auth.");
      }
      result = { data: created.data, error: null };
    }
    if (result.error) throw result.error;
    setAuthenticated(result.data.session);
    authMessage.textContent = "Вход выполнен.";
  } catch (error) {
    authMessage.textContent = error.message || "Не удалось выполнить вход.";
  } finally {
    submit.disabled = false;
  }
});
signOutButton.addEventListener("click", async () => { await authClient.auth.signOut(); setAuthenticated(null); });
authClient.auth.onAuthStateChange((_event, session) => setAuthenticated(session));
authClient.auth.getSession().then(({ data }) => setAuthenticated(data.session));
