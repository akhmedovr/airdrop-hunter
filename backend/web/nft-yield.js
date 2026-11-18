(() => {
  const root = document.getElementById("nftYieldList");
  if (!root) return;
  let records = [];
  let activeFilter = "all";
  const money = (value) => value == null ? "Не подтверждена" : new Intl.NumberFormat("ru-RU").format(value) + " ₽";
  const date = (value) => value ? new Date(value).toLocaleString("ru-RU") : "—";
  const safeUrl = (value) => { try { const u = new URL(value); return u.protocol === "https:" ? u.href : null; } catch (_) { return null; } };
  function node(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  function render() {
    root.replaceChildren();
    const list = records.filter((item) => activeFilter === "all" ||
      (activeFilter === "free" && item.capital_rub === 0) ||
      (activeFilter === "nft" && item.category === "nft") ||
      (activeFilter === "depin" && item.category === "depin"));
    if (!list.length) {
      root.append(node("p", "nft-yield-empty", "По этому фильтру кандидатов нет."));
      return;
    }
    list.forEach((item) => {
      const card = node("article", "panel nft-yield-card");
      const top = node("div", "nft-yield-top");
      const title = node("div", "");
      title.append(node("p", "eyebrow", item.category.toUpperCase() + " · " + item.network));
      title.append(node("h3", "", item.name));
      const status = node("span", "nft-yield-status " + (item.buy_allowed ? "is-buy" : "is-watch"), item.status_label);
      top.append(title, status); card.append(top);
      card.append(node("p", "nft-yield-desc", item.asset_type));
      const stats = node("div", "nft-yield-stats");
      [[ "Вход", money(item.capital_rub) ], ["Награда", item.reward_asset], ["Доходность", item.reward_rate || "Не подтверждена"], ["Ликвидность", item.reward_value == null ? "Не доказана" : String(item.reward_value)]].forEach(([k,v]) => {
        const cell=node("div","nft-yield-stat"); cell.append(node("small","",k),node("strong","",v)); stats.append(cell);
      });
      card.append(stats);
      const details = node("div","nft-yield-details");
      [["Механика",item.reward_type],["Условия блокировки",item.lockup],["Выход",item.exit],["Риски",item.risk],["Статус России",item.country_eligibility],["Почему пока не покупать",item.why_not_buy]].forEach(([k,v]) => {
        const row=node("p",""); row.append(node("strong","",k+": "),document.createTextNode(v || "Неизвестно")); details.append(row);
      });
      card.append(details);
      const footer=node("div","nft-yield-footer");
      footer.append(node("small","", "Проверено: "+date(item.checked_at)));
      const href=safeUrl(item.official_url);
      if(href){const a=node("a","record-link","Официальные правила ↗");a.href=href;a.target="_blank";a.rel="noopener noreferrer";footer.append(a);}
      card.append(footer);
      root.append(card);
    });
  }
  async function load() {
    root.replaceChildren(node("p","nft-yield-empty","Загружаю проверенные источники…"));
    try {
      const response=await fetch("/api/nft/yield");
      if(!response.ok) throw new Error("API вернул HTTP "+response.status);
      const data=await response.json(); records=data.items||[];
      const summary=data.summary||{};
      const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
      set("nftYieldTotal",String(summary.total??"—"));
      set("nftYieldBuy",String(summary.buy_recommendations??"—"));
      set("nftYieldFree",String(summary.free_candidates??"—"));
      set("nftYieldChecked",date(data.checked_at));
      render();
    } catch(error) {
      root.replaceChildren(node("p","nft-yield-empty","Не удалось загрузить список: "+error.message));
    }
  }
  document.querySelectorAll("[data-yield-filter]").forEach((button)=>button.addEventListener("click",()=>{
    activeFilter=button.dataset.yieldFilter;
    document.querySelectorAll("[data-yield-filter]").forEach((b)=>b.classList.toggle("active",b===button));
    render();
  }));
  document.getElementById("nftYieldRefresh")?.addEventListener("click",load);
  document.querySelectorAll('[data-view="nft-yield"]').forEach((button)=>button.addEventListener("click",load));
  const authObserver=setInterval(()=>{ if(window.__AH_AUTH_TOKEN){clearInterval(authObserver);load();}},250);
  window.addEventListener("beforeunload",()=>clearInterval(authObserver));
})();
