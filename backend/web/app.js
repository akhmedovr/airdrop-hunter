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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (authSession?.access_token) {
    headers.Authorization = "Bearer " + authSession.access_token;
  }
  const response = await fetch(API + path, { ...options, headers });
  if (!response.ok) {
    let detail = "HTTP " + response.status;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[char]));
}
function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:","https:"].includes(url.protocol) ? escapeHtml(url.href) : "#";
  } catch (_) { return "#"; }
}
const statusLabels = {
  discovered:"Найдено · не проверено", reviewed:"На проверке", eligible:"Доступно",
  unknown:"Условия неизвестны", ineligible:"Не подходит", planned:"В плане",
  in_progress:"В работе", completed:"Выполнено", claimable:"Можно получить",
  claimed:"Получено", realized:"Результат учтён", rejected:"Отклонено", expired:"Истекло",
  todo:"К выполнению", ready:"Готово", waiting_user:"Нужно твоё действие",
  skipped:"Пропущено", blocked:"Заблокировано"
};
function renderOpportunities(items) {
  const root=document.getElementById("opportunityList");
  if (!items?.length) { root.innerHTML='<article class="panel empty-page"><h3>Кандидатов пока нет</h3><p>Нажми «Запустить сканирование». Новые записи будут помечены как непроверенные.</p></article>'; return; }
  root.innerHTML=items.map(item=>`<article class="panel data-card">
    <div class="data-card-head"><div><p class="eyebrow">${escapeHtml(item.chain || "Web3")}</p><h3>${escapeHtml(item.title || item.project_name || "Без названия")}</h3></div><span class="muted-pill">${escapeHtml(statusLabels[item.status] || item.status || "Статус неизвестен")}</span></div>
    <p>${escapeHtml(item.reward_description || item.ai_summary || "Нужна проверка официальных условий.")}</p>
    <div class="data-meta">Уверенность: ${item.confidence == null ? "не оценена" : Math.round(Number(item.confidence)*100)+"%"} · Расходы: ${formatMoney(item.cost_estimate_usd)}</div>
    <a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">Открыть источник ↗</a>
  </article>`).join("");
}
function renderTasks(items) {
  const root=document.getElementById("taskList");
  const plan=document.getElementById("planList");
  if (!items?.length) {
    root.innerHTML='<article class="panel empty-page"><h3>Заданий пока нет</h3><p>Они появятся после проверки условий кампаний.</p></article>';
    plan.className="empty-state"; plan.innerHTML='<span class="empty-icon">⌁</span><strong>План пока не сформирован</strong><p>Сначала нужно подтвердить условия кампаний.</p>'; return;
  }
  root.innerHTML=items.map(item=>`<article class="panel data-card">
    <div class="data-card-head"><h3>${escapeHtml(item.title || "Задание")}</h3><span class="muted-pill">${escapeHtml(statusLabels[item.status] || item.status)}</span></div>
    <p>${escapeHtml(item.description || "Дополнительные инструкции пока не добавлены.")}</p>
    ${item.due_at ? '<div class="data-meta">Срок: '+escapeHtml(new Date(item.due_at).toLocaleString("ru-RU"))+'</div>' : ""}
    ${item.task_url ? '<a href="'+safeUrl(item.task_url)+'" target="_blank" rel="noopener noreferrer">Открыть задание ↗</a>' : ""}
    ${["todo","ready","in_progress","waiting_user"].includes(item.status) ? '<div class="data-actions"><button class="secondary-button" data-task-complete="'+escapeHtml(item.id)+'" type="button">Отметить выполненным</button></div>' : ""}
  </article>`).join("");
  const planned=items.filter(item=>["todo","ready","in_progress","waiting_user"].includes(item.status)).slice(0,5);
  plan.className=planned.length ? "data-list" : "empty-state";
  plan.innerHTML=planned.length ? planned.map((item,i)=>'<article class="data-card"><div class="data-card-head"><strong>'+(i+1)+'. '+escapeHtml(item.title || "Задание")+'</strong><span class="muted-pill">'+escapeHtml(statusLabels[item.status] || item.status)+'</span></div></article>').join("") : '<strong>Все текущие задания закрыты</strong>';
  root.querySelectorAll("[data-task-complete]").forEach(button=>button.addEventListener("click",async()=>{
    button.disabled=true;
    try { await request("/api/tasks/"+encodeURIComponent(button.dataset.taskComplete),{method:"PATCH",body:JSON.stringify({status:"completed"})}); await loadAppData(); showToast("Задание отмечено выполненным."); }
    catch(error){button.disabled=false;showToast("Не удалось обновить задание: "+error.message);}
  }));
}
function renderWallets(items) {
  const root=document.getElementById("walletList");
  if (!items?.length) {root.innerHTML='<article class="panel empty-page"><h3>Кошельки не подключены</h3><p>Добавь публичный адрес. Приватные ключи не нужны.</p></article>';return;}
  root.innerHTML=items.map(item=>`<article class="panel data-card"><div class="data-card-head"><h3>${escapeHtml(item.label || "Кошелёк")}</h3><span class="muted-pill">${escapeHtml(item.chain || "EVM")}</span></div><p class="wallet-address">${escapeHtml(item.address)}</p></article>`).join("");
}
function renderNotifications(items) {
  const root=document.getElementById("notificationList");
  if (!items?.length) {root.innerHTML='<div class="empty-state"><span class="empty-icon">♧</span><strong>Пока нет уведомлений</strong><p>Новые события появятся здесь.</p></div>';return;}
  root.innerHTML=items.map(item=>`<article class="panel data-card ${item.read_at ? "" : "unread"}"><div class="data-card-head"><h3>${escapeHtml(item.title || "Уведомление")}</h3><span class="muted-pill">${escapeHtml(item.category || "Событие")}</span></div><p>${escapeHtml(item.body || "")}</p><div class="data-meta">${item.created_at ? escapeHtml(new Date(item.created_at).toLocaleString("ru-RU")) : ""}</div>${item.read_at ? "" : '<button class="text-button" data-notification-read="'+escapeHtml(item.id)+'" type="button">Отметить прочитанным</button>'}</article>`).join("");
  root.querySelectorAll("[data-notification-read]").forEach(button=>button.addEventListener("click",async()=>{
    button.disabled=true;
    try {await request("/api/notifications/"+encodeURIComponent(button.dataset.notificationRead)+"/read",{method:"PATCH"});await loadAppData();}
    catch(error){button.disabled=false;showToast("Не удалось обновить уведомление: "+error.message);}
  }));
}
async function loadAppData() {
  if (!authSession?.access_token) return;
  const connection = document.getElementById("connection");
  const status = document.getElementById("systemStatus");
  try {
    const health = await request("/api/health");
    connection.classList.add("online");
    connection.innerHTML = "<i></i> Сервер подключён";
    status.textContent = health.status === "ok" ? "API на связи · сканирование по запросу" : "Сервер отвечает";
    const [dashboard, notifications, opportunities, tasks, wallets] = await Promise.all([
      request("/api/dashboard"), request("/api/notifications"), request("/api/opportunities"),
      request("/api/tasks"), request("/api/wallets")
    ]);
    document.getElementById("metricCampaigns").textContent = dashboard.active_campaigns ?? "—";
    document.getElementById("metricTasks").textContent = dashboard.tasks_today ?? "—";
    document.getElementById("metricClaimable").textContent = formatMoney(dashboard.claimable_rewards_usd);
    document.getElementById("metricPnl").textContent = formatMoney(dashboard.realized_pnl_usd);
    document.getElementById("unreadCount").textContent = String(Number(notifications.unread_count || 0));
    renderOpportunities(opportunities.items || []);
    renderTasks(tasks.items || []);
    renderWallets(wallets.items || []);
    renderNotifications(notifications.items || []);
  } catch (error) {
    connection.classList.remove("online");
    connection.innerHTML = "<i></i> Ошибка соединения";
    status.textContent = "Не удалось загрузить данные: " + error.message;
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

document.getElementById("scanButton").addEventListener("click",async()=>{
  const button=document.getElementById("scanButton"), label=document.getElementById("scanStatus");
  button.disabled=true; label.textContent="Получаю список протоколов и сверяю кандидатов…";
  try {
    const result=await request("/api/agent/run-scan",{method:"POST"});
    label.textContent="Проверено кандидатов: "+result.items_found+". Добавлено новых: "+result.candidates_added+". Награды не подтверждены.";
    await loadAppData();
    showToast("Сканирование завершено.");
  } catch(error) {label.textContent="Сканирование не выполнено: "+error.message;showToast("Ошибка сканирования.");}
  finally {button.disabled=false;}
});
document.getElementById("walletForm").addEventListener("submit",async(event)=>{
  event.preventDefault();
  const button=event.currentTarget.querySelector('button[type="submit"]'); button.disabled=true;
  try {
    const payload={label:document.getElementById("walletLabel").value.trim(),address:document.getElementById("walletAddress").value.trim(),chain:document.getElementById("walletChain").value};
    await request("/api/wallets",{method:"POST",body:JSON.stringify(payload)});
    event.currentTarget.reset(); await loadAppData(); showToast("Публичный адрес добавлен.");
  } catch(error) {showToast("Не удалось добавить адрес: "+error.message);}
  finally {button.disabled=false;}
});
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
const loginSubmit = document.querySelector("#loginForm button[type=\"submit\"]");
const resetPasswordButton = document.getElementById("resetPasswordButton");
let recoveryMode = false;
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
  authMessage.textContent = recoveryMode ? "Сохраняю новый пароль…" : "Проверяю доступ…";
  try {
    if (recoveryMode) {
      const { error } = await authClient.auth.updateUser({ password });
      if (error) throw error;
      recoveryMode = false;
      document.getElementById("loginPassword").value = "";
      document.getElementById("loginPassword").placeholder = "Пароль";
      loginSubmit.textContent = "Войти";
      authMessage.textContent = "Пароль обновлён. Теперь войди с новым паролем.";
      await authClient.auth.signOut();
      return;
    }
    const { data, error } = await authClient.auth.signInWithPassword({ email, password });
    if (error) throw error;
    setAuthenticated(data.session);
    authMessage.textContent = "Вход выполнен.";
  } catch (error) {
    const message = error.message || "Не удалось выполнить вход.";
    authMessage.textContent = /invalid login credentials/i.test(message)
      ? "Неверный email или пароль. Если пароль не помнишь, нажми «Сбросить пароль»."
      : message;
  } finally {
    submit.disabled = false;
  }
});
resetPasswordButton.addEventListener("click", async () => {
  const email = document.getElementById("loginEmail").value.trim().toLowerCase();
  if (!email) {
    authMessage.textContent = "Сначала введи email.";
    document.getElementById("loginEmail").focus();
    return;
  }
  resetPasswordButton.disabled = true;
  authMessage.textContent = "Отправляю ссылку для сброса пароля…";
  try {
    const { error } = await authClient.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin + "/"
    });
    if (error) throw error;
    authMessage.textContent = "Если для этого email есть аккаунт, Supabase отправит письмо со ссылкой для сброса пароля. Проверь входящие и спам.";
  } catch (error) {
    authMessage.textContent = error.message || "Не удалось отправить письмо для сброса.";
  } finally {
    resetPasswordButton.disabled = false;
  }
});
signOutButton.addEventListener("click", async () => { await authClient.auth.signOut(); setAuthenticated(null); });
authClient.auth.onAuthStateChange((event, session) => {
  if (event === "PASSWORD_RECOVERY") {
    recoveryMode = true;
    authGate.hidden = false;
    document.querySelector("main").style.visibility = "hidden";
    document.querySelector(".mobile-nav").style.visibility = "hidden";
    document.getElementById("loginPassword").value = "";
    document.getElementById("loginPassword").placeholder = "Новый пароль (минимум 8 символов)";
    loginSubmit.textContent = "Сохранить новый пароль";
    authMessage.textContent = "Придумай новый пароль и нажми «Сохранить новый пароль».";
  } else {
    setAuthenticated(session);
  }
});
authClient.auth.getSession().then(({ data }) => setAuthenticated(data.session));
