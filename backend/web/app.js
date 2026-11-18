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

document.getElementById("nftMarketForm")?.addEventListener("submit", loadNftMarket);
document.querySelectorAll('[data-view="nft-market"]').forEach((button) => {
  button.addEventListener("click", () => loadNftMarket(null, true));
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

function renderEmpty(root, icon, title, description) {
  root.replaceChildren();
  const card = document.createElement("article");
  card.className = "panel empty-page";
  const symbol = document.createElement("span");
  symbol.className = "empty-icon large";
  symbol.textContent = icon;
  const heading = document.createElement("h3");
  heading.textContent = title;
  const detail = document.createElement("p");
  detail.textContent = description;
  card.append(symbol, heading, detail);
  root.append(card);
}

function safeLink(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch (_) {
    return null;
  }
}

function recordCard(title, description, meta, url) {
  const card = document.createElement("article");
  card.className = "panel record-card";
  const heading = document.createElement("h3");
  heading.textContent = title || "Без названия";
  const detail = document.createElement("p");
  detail.textContent = description || "";
  const info = document.createElement("small");
  info.className = "record-meta";
  info.textContent = meta || "";
  card.append(heading, info, detail);
  const href = safeLink(url);
  if (href) {
    const link = document.createElement("a");
    link.className = "record-link";
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Открыть источник";
    card.append(link);
  }
  return card;
}

function shortAddress(address) {
  const value = String(address || "");
  return value.length > 16 ? value.slice(0, 8) + "…" + value.slice(-6) : value;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

let allOpportunities = [];
let activeOpportunityFilter = "all";
let opportunitySearchTerm = "";

function opportunityCategory(item) {
  const text = [item.title,item.project_name,item.reward_description,item.ai_summary,
    ...(item.evidence || []).map((entry) => entry.source || "")].join(" ").toLowerCase();
  const nft = /\bnft\b|mint|whitelist|collectible|collection|opensea|blur|magic eden|ordinals|inscription/.test(text);
  const resale = /marketplace|floor price|floor\b|resale|перепродаж|листинг|order book|bid|offer|торговл.*nft/.test(text);
  if (nft && resale) return "resale";
  if (nft) return "nft";
  if (/staking|stake|deposit|liquidity|\blp\b|collateral|trading volume|торгов.*объ[её]м|стейкинг|депозит|ликвидност/.test(text)) return "capital";
  if (/airdrop|retrodrop|testnet|points|quest|galxe|faucet|incentiv|drop|тестнет|дроп|поинт|квест/.test(text)) return "airdrop";
  return "web3";
}

function renderOpportunities() {
  const root = document.getElementById("opportunitiesList");
  if (!root) return;
  const filtered = allOpportunities.filter((item) => {
    const category = opportunityCategory(item);
    const text = [item.title,item.project_name,item.reward_description,item.ai_summary].join(" ").toLowerCase();
    return (activeOpportunityFilter === "all" || category === activeOpportunityFilter)
      && (!opportunitySearchTerm || text.includes(opportunitySearchTerm));
  });
  const count = document.getElementById("opportunityCount");
  if (count) count.textContent = "Показано " + filtered.length + " из " + allOpportunities.length + " возможностей";
  root.replaceChildren();
  if (!filtered.length) {
    renderEmpty(root, "⌕", "Ничего не найдено", allOpportunities.length
      ? "Попробуй другой фильтр или поисковый запрос."
      : "Запусти сканирование публичных источников. Новые записи появятся здесь.");
    return;
  }
  filtered.forEach((item) => {
    const category = opportunityCategory(item);
    const source = item.evidence?.[0]?.source || "Источник не указан";
    const meta = [source,item.chain || "Сеть не определена","Eligibility: " + (item.eligibility || "unknown"),"Статус: " + (item.status || "discovered")].join(" · ");
    const card = recordCard(item.title,item.reward_description || item.ai_summary,meta,item.url);
    card.classList.add("opportunity-card");
    card.dataset.category = category;
    const tag = document.createElement("span");
    tag.className = "category-tag category-" + category;
    tag.textContent = ({airdrop:"AIRDROP",capital:"CAPITAL",nft:"NFT",resale:"NFT MARKET",web3:"WEB3"})[category];
    card.prepend(tag);
    root.append(card);
  });
}

async function loadOpportunities() {
  const root = document.getElementById("opportunitiesList");
  if (!root) return;
  try {
    const data = await request("/api/opportunities");
    allOpportunities = data.items || [];
    renderOpportunities();
  } catch (error) {
    allOpportunities = [];
    renderEmpty(root, "!", "Не удалось загрузить возможности", error.message);
  }
}

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    activeOpportunityFilter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((chip) => chip.classList.toggle("active", chip === button));
    renderOpportunities();
  });
});
document.getElementById("opportunitySearch")?.addEventListener("input", (event) => {
  opportunitySearchTerm = event.target.value.trim().toLowerCase();
  renderOpportunities();
});
document.querySelectorAll("[data-open-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    activeOpportunityFilter = button.dataset.openFilter;
    document.querySelectorAll("[data-filter]").forEach((chip) => chip.classList.toggle("active", chip.dataset.filter === activeOpportunityFilter));
    activateView("opportunities");
    renderOpportunities();
  });
});

async function loadNftMarket(event, initial = false) {
  if (event) event.preventDefault();
  const input = document.getElementById("nftCollectionSlug");
  const root = document.getElementById("nftMarketResults");
  const button = document.getElementById("nftMarketSearch");
  if (!root || !input || !button) return;
  const slug = input.value.trim().toLowerCase();
  if (!slug) {
    if (initial) return;
    showToast("Укажи slug коллекции OpenSea.");
    input.focus();
    return;
  }
  if (!/^[a-z0-9][a-z0-9-]{0,99}$/.test(slug)) {
    showToast("Slug может содержать только латинские буквы, цифры и дефис.");
    return;
  }
  button.disabled = true;
  button.textContent = "Загружаю…";
  try {
    const data = await request("/api/nft/market/" + encodeURIComponent(slug));
    document.getElementById("nftListingsSeen").textContent = String(data.items_seen ?? "—");
    document.getElementById("nftListingsActive").textContent = String(data.active_listings ?? "—");
    document.getElementById("nftListingsChecked").textContent = formatDate(data.checked_at) || "—";
    document.getElementById("nftProviderName").textContent = data.provider || "OpenSea";
    root.replaceChildren();
    const notice = document.createElement("p");
    notice.className = "form-note";
    notice.textContent = data.notice || "Публичные данные; исполнимость не гарантируется.";
    root.append(notice);
    const items = data.listings || [];
    if (!items.length) {
      renderEmpty(root, "⌕", "Активные листинги не найдены", "Проверь slug или повтори запрос позже.");
      return;
    }
    items.forEach((item) => {
      const meta = [item.chain, item.currency + " " + item.price, "Token #" + item.token_id, "Статус: " + item.status].join(" · ");
      root.append(recordCard(item.collection, "Контракт: " + (item.contract || "не указан") + " · Количество: " + (item.remaining_quantity ?? "не указано"), meta, item.url));
    });
  } catch (error) {
    const message = error.message || "Не удалось загрузить листинги.";
    renderEmpty(root, "!", "Сканер пока недоступен", message);
    if (message.toLowerCase().includes("api key")) {
      const hint = document.createElement("p");
      hint.className = "form-note";
      hint.textContent = "Нужно добавить OPENSEA_API_KEY в серверные переменные Railway. Не вставляй ключ в форму или чат.";
      root.append(hint);
    }
  } finally {
    button.disabled = false;
    button.textContent = "Загрузить листинги";
  }
}

function strategyStatus(item) {
  const blockers = Array.isArray(item.blockers) ? item.blockers : [];
  const eligibility = item.country_eligibility || "unknown";
  const reward = item.reward_value_verified && item.estimated_reward_usd != null
    ? formatMoney(item.estimated_reward_usd) : "не подтверждена";
  const cost = item.cost_verified && item.cost_estimate_usd != null
    ? formatMoney(item.cost_estimate_usd) : "не подтверждены";
  const capital = item.required_capital_usd == null
    ? "не определён" : formatMoney(item.required_capital_usd);
  const checked = item.checked_at ? formatDate(item.checked_at) : "дата проверки неизвестна";
  const mode = item.activity_mode || "не определён";
  const details = [
    "Eligibility: " + eligibility,
    "KYC: " + (item.kyc_required == null ? "неизвестно" : item.kyc_required ? "требуется" : "не требуется"),
    "Награда: " + reward,
    "Расходы: " + cost,
    "Капитал: " + capital,
    "Механика: " + mode,
    "Проверено: " + checked
  ];
  if (item.lockup_days != null) details.push("Lock-up: " + item.lockup_days + " дн.");
  if (blockers.length) details.push("Блокеры: " + blockers.join(", "));
  else details.push("Блокеры: не выявлены; это всё ещё не разрешение на участие");
  return details.join(" · ");
}

function renderStrategyRecords(rootId, items, emptyTitle, emptyText) {
  const root = document.getElementById(rootId);
  if (!root) return;
  root.replaceChildren();
  if (!items || !items.length) {
    root.className = "empty-state compact";
    const strong = document.createElement("strong");
    strong.textContent = emptyTitle;
    const p = document.createElement("p");
    p.textContent = emptyText;
    root.append(strong, p);
    return;
  }
  root.className = "record-list";
  items.forEach((item) => {
    const source = item.source || "Источник не указан";
    const meta = [source, item.chain || "Сеть не определена", "Статус: " + (item.assessment_status || "не проверен")].join(" · ");
    const card = recordCard(item.title, item.reward_description || item.ai_summary, meta, item.official_url || item.url);
    const detail = document.createElement("p");
    detail.className = "strategy-record-detail";
    detail.textContent = strategyStatus(item);
    card.append(detail);
    root.append(card);
  });
}

async function loadStrategies() {
  try {
    const data = await request("/api/strategies");
    const tracks = data.tracks || {};
    const noCapital = tracks.no_capital || [];
    const capital = tracks.capital || [];
    const unclassified = tracks.unclassified || [];
    document.getElementById("strategyNoCapitalCount").textContent = String(noCapital.length);
    document.getElementById("strategyCapitalCount").textContent = String(capital.length);
    document.getElementById("strategyUnclassifiedCount").textContent = String(unclassified.length);
    const scan = data.last_scan || {};
    document.getElementById("strategyLastScan").textContent = scan.started_at ? formatDate(scan.started_at) : "—";
    document.getElementById("strategyLastScanNote").textContent = scan.status
      ? scan.status + " · " + (scan.items_found ?? 0) + " записей"
      : "Сканирование ещё не зарегистрировано";
    renderStrategyRecords("strategyNoCapitalRecords", noCapital,
      "Нет подтверждённых low-touch кандидатов",
      "Система продолжает искать программы с понятной моделью выплат и минимальными расходами. Кандидаты с неизвестной экономикой остаются заблокированными.");
    renderStrategyRecords("strategyCapitalRecords", capital,
      "Капиталоёмкие кандидаты пока не отобраны",
      "Ни один депозит, стейкинг или пул ликвидности не одобрен. Сначала требуется расчёт риска и экономики.");
    renderStrategyRecords("strategyUnclassifiedRecords", unclassified,
      "Очередь пуста",
      "Неоднозначные программы появятся здесь до получения достаточных данных для классификации.");
    const accounting = data.accounting || {};
    const no = accounting.no_capital || {};
    const yes = accounting.capital || {};
    const box = document.getElementById("strategyAccounting");
    box.replaceChildren();
    [
      ["Без вложений", no],
      ["С вложениями", yes]
    ].forEach(([label, row]) => {
      const group = document.createElement("div");
      group.className = "strategy-accounting-group";
      const title = document.createElement("strong");
      title.textContent = label;
      const line = document.createElement("span");
      line.textContent = "Вложено: " + formatMoney(row.capital_invested_usd || 0)
        + " · Комиссии: " + formatMoney(row.fees_spent_usd || 0)
        + " · Получено: " + formatMoney(row.realized_rewards_usd || 0)
        + " · Чистый реализованный результат*: " + formatMoney(row.realized_net_usd || 0);
      group.append(title, line);
      box.append(group);
    });
    const note = document.createElement("small");
    note.textContent = "Учтено записей с привязкой к треку: " + (accounting.attributed_records || 0)
      + ". Без привязки: " + (accounting.unassigned_records || 0)
      + ". *Без оценки возврата principal и нереализованной стоимости активов.";
    box.append(note);
  } catch (error) {
    renderStrategyRecords("strategyNoCapitalRecords", [], "Не удалось загрузить трек", error.message);
    renderStrategyRecords("strategyCapitalRecords", [], "Не удалось загрузить трек", error.message);
    renderStrategyRecords("strategyUnclassifiedRecords", [], "Не удалось загрузить очередь", error.message);
  }
}

document.getElementById("strategyRefresh")?.addEventListener("click", async () => {
  const button = document.getElementById("strategyRefresh");
  button.disabled = true;
  button.textContent = "Обновляю…";
  await loadStrategies();
  button.disabled = false;
  button.textContent = "Обновить анализ";
});

async function loadTasks() {
  const root = document.getElementById("tasksList");
  if (!root) return;
  try {
    const data = await request("/api/tasks");
    const items = data.items || [];
    if (!items.length) {
      renderEmpty(root, "☷", "Очередь заданий пуста", "Задания появятся после отдельной проверки правил и eligibility кампаний.");
      return;
    }
    root.replaceChildren();
    items.forEach((item) => {
      const meta = ["Статус: " + item.status, item.due_at ? "Срок: " + formatDate(item.due_at) : ""].filter(Boolean).join(" · ");
      const card=recordCard(item.title, item.description, meta, item.task_url);
      if (["todo","ready","in_progress","waiting_user"].includes(item.status)) {
        const button=document.createElement("button");
        button.type="button"; button.className="secondary-button"; button.textContent="Отметить выполненным";
        button.addEventListener("click",async()=>{
          button.disabled=true;
          try {
            await request("/api/tasks/"+encodeURIComponent(item.id),{method:"PATCH",body:JSON.stringify({status:"completed"})});
            showToast("Задание отмечено выполненным.");
            await loadAppData();
          } catch(error) {button.disabled=false;showToast("Не удалось обновить задание: "+error.message);}
        });
        card.append(button);
      }
      root.append(card);
    });
  } catch (error) {
    renderEmpty(root, "!", "Не удалось загрузить задания", error.message);
  }
}

async function loadWallets() {
  const root = document.getElementById("walletsList");
  if (!root) return;
  try {
    const data = await request("/api/wallets");
    const items = data.items || [];
    if (!items.length) {
      renderEmpty(root, "◇", "Кошельки пока не добавлены", "Добавь публичный адрес для read-only мониторинга. Seed-фразы и приватные ключи не нужны.");
      return;
    }
    root.replaceChildren();
    items.forEach((item) => {
      const usd=item.balance_usd==null ? "" : " · ≈ "+formatMoney(item.balance_usd);
      const balance=item.balance_status==="ok" ? "Баланс: "+item.native_balance+" "+item.balance_symbol+usd : (item.balance_status==="unsupported" ? "Баланс этой сети пока не поддержан" : "Баланс временно недоступен");
      root.append(recordCard(item.label, shortAddress(item.address), item.chain + " · Только чтение · " + balance, null));
    });
  } catch (error) {
    renderEmpty(root, "!", "Не удалось загрузить кошельки", error.message);
  }
}

async function loadNotifications() {
  const root = document.getElementById("notificationsList");
  if (!root) return;
  try {
    const data = await request("/api/notifications");
    document.getElementById("unreadCount").textContent = String(data.unread_count || 0);
    const items = data.items || [];
    if (!items.length) {
      renderEmpty(root, "♧", "Пока нет уведомлений", "События сканирования, кампании и дедлайны будут появляться здесь.");
      return;
    }
    root.replaceChildren();
    items.forEach((item) => {
      const card=recordCard(item.title, item.body, [item.category, formatDate(item.created_at), item.read_at ? "Прочитано" : "Новое"].filter(Boolean).join(" · "), item.target_url);
      if (!item.read_at) {
        const button=document.createElement("button");
        button.type="button"; button.className="text-button"; button.textContent="Отметить прочитанным";
        button.addEventListener("click",async()=>{
          button.disabled=true;
          try {
            await request("/api/notifications/"+encodeURIComponent(item.id)+"/read",{method:"PATCH"});
            await loadNotifications();
          } catch(error) {button.disabled=false;showToast("Не удалось обновить уведомление: "+error.message);}
        });
        card.append(button);
      }
      root.append(card);
    });
    const recent=document.getElementById("recentEventsList");
    if (recent) {
      const latest=items.slice(0,3);
      recent.replaceChildren();
      if (!latest.length) {
        recent.className="empty-state compact";
        recent.innerHTML='<span class="empty-icon">◷</span><strong>Событий пока нет</strong><p>Новые события появятся здесь.</p>';
      } else {
        recent.className="record-list";
        latest.forEach(item=>recent.append(recordCard(item.title,item.body,formatDate(item.created_at),item.target_url)));
      }
    }
  } catch (error) {
    renderEmpty(root, "!", "Не удалось загрузить уведомления", error.message);
  }
}

async function loadPlan() {
  const root=document.getElementById("planList");
  if (!root) return;
  try {
    const data=await request("/api/plan/today");
    const items=data.items||[];
    root.replaceChildren();
    if (!items.length) {
      root.className="empty-state";
      root.innerHTML='<span class="empty-icon">⌁</span><strong>План пока не сформирован</strong><p>После проверки кампаний появятся задания. Сейчас доступна сортировка по правилам; AI API ещё не настроен.</p>';
      return;
    }
    root.className="record-list";
    items.forEach((item,index)=>{
      const row=document.createElement("article");
      row.className="record-card";
      const heading=document.createElement("h3");
      heading.textContent=(index+1)+". "+(item.title||"Задание");
      const meta=document.createElement("small");
      meta.className="record-meta";
      meta.textContent="Приоритет "+item.priority+" · "+(item.estimated_minutes||"—")+" мин · "+item.status;
      row.append(heading,meta);
      root.append(row);
    });
  } catch(error) {
    root.className="empty-state";
    root.textContent="Не удалось сформировать план: "+error.message;
  }
}

async function loadAppData() {
  if (!authSession?.access_token) return;
  const connection = document.getElementById("connection");
  const status = document.getElementById("systemStatus");
  try {
    try { await request("/api/profile/bootstrap",{method:"POST",body:JSON.stringify({})}); }
    catch (profileError) { console.warn("Profile bootstrap pending:",profileError.message); }
    const health = await request("/api/health");
    connection.classList.add("online");
    connection.innerHTML = "<i></i> Сервер подключён";
    status.textContent = health.status === "ok" ? (health.worker_write_enabled ? "API на связи · фоновый сканер готов" : "API на связи · сканирование по запросу") : "Сервер отвечает";
    const pushStatus=document.getElementById("pushStatus");
    if (pushStatus && health.push_configured && pushStatus.textContent==="Не настроено") pushStatus.textContent="Готово к подключению";
    const dashboard = await request("/api/dashboard");
    document.getElementById("metricCampaigns").textContent = dashboard.active_campaigns ?? "—";
    document.getElementById("metricTasks").textContent = dashboard.tasks_today ?? "—";
    document.getElementById("metricClaimable").textContent = formatMoney(dashboard.claimable_rewards_usd);
    document.getElementById("metricPnl").textContent = formatMoney(dashboard.realized_pnl_usd);
    await Promise.all([loadOpportunities(), loadTasks(), loadWallets(), loadNotifications(), loadPlan(), loadStrategies()]);
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

document.getElementById("scanButton")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Проверяю источники…";
  try {
    const result = await request("/api/agent/run-scan", { method: "POST" });
    showToast(result.message || "Проверка завершена.");
    await loadAppData();
  } catch (error) {
    showToast("Сканирование не выполнено: " + error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Запустить сканирование";
  }
});

document.getElementById("walletForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await request("/api/wallets", {
      method: "POST",
      body: JSON.stringify({
        label: document.getElementById("walletLabel").value.trim(),
        address: document.getElementById("walletAddress").value.trim(),
        chain: document.getElementById("walletChain").value,
      }),
    });
    form.reset();
    await loadWallets();
    showToast("Публичный адрес добавлен.");
  } catch (error) {
    showToast("Не удалось добавить адрес: " + error.message);
  } finally {
    submit.disabled = false;
  }
});
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
