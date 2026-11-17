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
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
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
  const email = document.getElementById("loginEmail").value.trim();
  authMessage.textContent = "Отправляю ссылку…";
  const { error } = await authClient.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
  authMessage.textContent = error ? error.message : "Ссылка отправлена. Открой письмо и перейди по ссылке на этом устройстве.";
});
signOutButton.addEventListener("click", async () => { await authClient.auth.signOut(); setAuthenticated(null); });
authClient.auth.onAuthStateChange((_event, session) => setAuthenticated(session));
authClient.auth.getSession().then(({ data }) => setAuthenticated(data.session));
