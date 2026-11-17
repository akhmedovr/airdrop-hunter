import os, time, json, logging, asyncio
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pywebpush import webpush, WebPushException
from screening import preserve_review_state, should_create_review_task

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("airdrop-hunter")
SUPABASE_URL=os.getenv("SUPABASE_URL","").rstrip("/")
SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY","")
SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","")
SUPABASE_SECRET_KEY=os.getenv("SUPABASE_SECRET_KEY","")
OWNER_EMAIL=os.getenv("OWNER_EMAIL","").strip().lower()
VAPID_PUBLIC_KEY=os.getenv("VAPID_PUBLIC_KEY","")
VAPID_PRIVATE_KEY=os.getenv("VAPID_PRIVATE_KEY","")
VAPID_SUBJECT=os.getenv("VAPID_SUBJECT","mailto:admin@example.com")
scheduler=AsyncIOScheduler(timezone="UTC")
RPC_ENDPOINTS={
    "polygon":"https://polygon-bor-rpc.publicnode.com",
    "ethereum":"https://ethereum-rpc.publicnode.com",
    "base":"https://base-rpc.publicnode.com",
    "arbitrum":"https://arbitrum-one-rpc.publicnode.com",
    "optimism":"https://optimism-rpc.publicnode.com",
    "linea":"https://linea-rpc.publicnode.com",
    "scroll":"https://scroll-rpc.publicnode.com",
}
NATIVE_SYMBOLS={"polygon":"POL","ethereum":"ETH","base":"ETH","arbitrum":"ETH","optimism":"ETH","linea":"ETH","scroll":"ETH"}
app=FastAPI(title="Airdrop Hunter API",version="2.0.0")
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","*").split(","),allow_credentials=False,allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],allow_headers=["Authorization","Content-Type"])

async def auth_user(authorization: str|None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"Authentication required")
    token=authorization.split(" ",1)[1]
    async with httpx.AsyncClient(timeout=12) as c:
        r=await c.get(f"{SUPABASE_URL}/auth/v1/user",headers={"apikey":SUPABASE_ANON_KEY,"Authorization":f"Bearer {token}"})
    if r.status_code!=200: raise HTTPException(401,"Invalid or expired session")
    user=r.json()
    if OWNER_EMAIL and (user.get("email") or "").strip().lower()!=OWNER_EMAIL: raise HTTPException(403,"This is a private, single-owner application")
    return user

def db_headers(owner_token: str|None=None):
    h={"apikey":SUPABASE_ANON_KEY,"Content-Type":"application/json"}
    # New Supabase sb_secret_* keys are API keys, not JWTs: send them only in apikey.
    if owner_token and (owner_token.startswith("sb_secret_") or owner_token==SUPABASE_SECRET_KEY):
        h["apikey"]=owner_token
        return h
    if owner_token:
        h["Authorization"]=f"Bearer {owner_token}"
        return h
    if SUPABASE_SECRET_KEY:
        h["apikey"]=SUPABASE_SECRET_KEY
        return h
    if SUPABASE_SERVICE_ROLE_KEY:
        h["Authorization"]=f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
    return h

async def db_get(table,owner_id,query="",owner_token: str|None=None):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY: raise HTTPException(503,"Database is not configured")
    headers=db_headers(owner_token)
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{SUPABASE_URL}/rest/v1/{table}?owner_id=eq.{owner_id}&{query}",headers=headers)
    if r.status_code>=400: raise HTTPException(502,f"Database read failed: {r.text[:250]}")
    return r.json()

async def db_insert(table,payload,owner_token: str|None=None):
    if not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY) and not owner_token: raise HTTPException(503,"Database write is not configured")
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(f"{SUPABASE_URL}/rest/v1/{table}",headers={**db_headers(owner_token),"Prefer":"return=representation"},json=payload)
    if r.status_code>=300: raise HTTPException(502,f"Database write failed: {r.text[:250]}")
    return r.json()

async def db_upsert(table,payload,conflict,owner_token):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(503,"Database is not configured")
    if not payload:
        return []
    async with httpx.AsyncClient(timeout=25) as c:
        r=await c.post(
            f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict}",
            headers={**db_headers(owner_token),"Prefer":"resolution=merge-duplicates,return=representation"},
            json=payload,
        )
    if r.status_code>=300:
        raise HTTPException(502,f"Database upsert failed ({table}): {r.text[:250]}")
    return r.json()

async def db_patch(table,filters,payload,owner_token):
    query="&".join(f"{key}=eq.{value}" for key,value in filters.items())
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.patch(
            f"{SUPABASE_URL}/rest/v1/{table}?{query}",
            headers={**db_headers(owner_token),"Prefer":"return=representation"},
            json=payload,
        )
    if r.status_code>=300:
        raise HTTPException(502,f"Database update failed ({table}): {r.text[:250]}")
    return r.json()

async def fetch_defillama_candidates():
    url="https://api.llama.fi/protocols"
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as c:
        response=await c.get(url)
        response.raise_for_status()
        protocols=response.json()
    if not isinstance(protocols,list):
        raise RuntimeError("DeFiLlama returned an unexpected response")
    blocked={"cex","chain","prediction market"}
    candidates=[]
    for item in protocols:
        chains=item.get("chains") or []
        if not any("polygon" in str(chain).lower() for chain in chains):
            continue
        if str(item.get("symbol") or "").strip() not in ("","-"):
            continue
        category=str(item.get("category") or "").strip().lower()
        if not category or category in blocked:
            continue
        tvl=item.get("tvl") or 0
        if not isinstance(tvl,(int,float)) or not 1_000_000 <= tvl <= 500_000_000:
            continue
        slug=item.get("slug") or ""
        project_url=item.get("url") or (f"https://defillama.com/protocol/{slug}" if slug else "")
        if not project_url:
            continue
        candidates.append({
            "title":item.get("name") or "Unknown project",
            "project_name":item.get("name") or "Unknown project",
            "url":project_url,
            "chain":"Polygon",
            "reward_description":"Возможный кандидат для исследования. Факт аирдропа или награды не подтверждён.",
            "confidence":0.15,
            "evidence":[{
                "source":"DeFiLlama",
                "source_url":f"https://defillama.com/protocol/{slug}" if slug else url,
                "checked_at":datetime.now(timezone.utc).isoformat(),
                "signals":{"tvl_usd":tvl,"category":category,"token_symbol":item.get("symbol") or None},
            }],
            "ai_summary":"Это только сигнал для дальнейшей проверки. Отсутствие тикера не доказывает наличие будущего аирдропа.",
            "anti_sybil_notes":"Правила проекта, eligibility, KYC и anti-Sybil не проверены.",
        })
    candidates.sort(key=lambda item: item["evidence"][0]["signals"]["tvl_usd"],reverse=True)
    return candidates[:40]

async def fetch_galxe_campaigns():
    endpoint="https://graphigo.prd.galaxy.eco/query"
    query="""query GetCampaigns($first: Int!, $listType: ListType) {
      campaigns(input: {first: $first, listType: $listType}) {
        list { id name status space { alias } }
      }
    }"""
    campaigns={}
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as c:
        for list_type in ("Newest","Trending"):
            response=await c.post(endpoint,json={
                "query":query,
                "variables":{"first":30,"listType":list_type},
            })
            response.raise_for_status()
            data=response.json()
            if data.get("errors"):
                raise RuntimeError("Galxe GraphQL returned an error")
            rows=((data.get("data") or {}).get("campaigns") or {}).get("list") or []
            for item in rows:
                if item.get("status")!="Active" or not item.get("id") or not item.get("name"):
                    continue
                alias=((item.get("space") or {}).get("alias") or "").strip()
                path=f"{alias}/{item['id']}" if alias else str(item["id"])
                campaigns[item["id"]]={
                    "title":item["name"],
                    "project_name":alias or "Galxe",
                    "url":f"https://app.galxe.com/quest/{path}",
                    "chain":None,
                    "reward_description":"Galxe API сообщил status=Active на момент сканирования. Тип награды, дедлайн конкретного квеста, требования eligibility, стоимость участия и возможность вывода не проверены. Общий срок участия на платформе — до 5 декабря 2026; получение уже заработанных наград — до 15 декабря 2026.",
                    "confidence":0.35,
                    "evidence":[{
                        "source":"Galxe (sunsetting)",
                        "campaign_id":item["id"],
                        "observed_status":item["status"],
                        "checked_at":datetime.now(timezone.utc).isoformat(),
                        "official_notice":"https://help.galxe.com/en/articles/18361711-galxe-is-integrating-into-gravity-what-you-need-to-know",
                    }],
                    "ai_summary":"Статус Active получен из публичного API Galxe на момент сканирования. Это не подтверждает наличие денежной награды или право пользователя на неё. Необходимо отдельно проверить страницу квеста, точный дедлайн, требования, платные условия и механику выплаты. Общие даты закрытия Galxe: участие до 5 декабря 2026, claim до 15 декабря 2026.",
                    "anti_sybil_notes":"Не обходить KYC, географические ограничения, CAPTCHA и anti-Sybil правила. Учитывать объявленное закрытие Galxe Quest.",
                }
    return list(campaigns.values())

@app.on_event("startup")
async def startup():
    if os.getenv("ENABLE_SCHEDULER","true").lower()=="true":
        scheduler.add_job(scheduled_health_scan,"interval",minutes=int(os.getenv("SCAN_INTERVAL_MINUTES","360")),next_run_time=datetime.now(timezone.utc),id="source-scan",replace_existing=True,max_instances=1)
        scheduler.start()

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running: scheduler.shutdown(wait=False)

@app.get("/api/health")
async def health():
    return {"status":"ok","service":"airdrop-hunter","scheduler_running":scheduler.running,"scanner_mode":"manual","database_configured":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"worker_write_enabled":bool(SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY),"push_configured":bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY),"time":datetime.now(timezone.utc).isoformat()}

@app.post("/api/profile/bootstrap")
async def profile_bootstrap(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    token=authorization.split(" ",1)[1]
    await db_upsert("profiles",{
        "id":user["id"],
        "display_name":str((user.get("user_metadata") or {}).get("name") or "Airdrop Hunter Owner")[:100],
        "updated_at":datetime.now(timezone.utc).isoformat(),
    },"id",token)
    return {"ok":True}

@app.get("/api/dashboard")
async def dashboard(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization); uid=user["id"]
    campaigns=await db_get("campaigns",uid,"select=id,status",authorization.split(" ",1)[1])
    tasks=await db_get("tasks",uid,"select=id,status,due_at",authorization.split(" ",1)[1])
    rewards=await db_get("rewards",uid,"select=estimated_usd,realized_usd,status",authorization.split(" ",1)[1])
    notifications=await db_get("notifications",uid,"select=id,read_at",authorization.split(" ",1)[1])
    return {"active_campaigns":sum(1 for x in campaigns if x["status"] not in ("expired","rejected","realized")),"tasks_today":sum(1 for x in tasks if x["status"] in ("todo","ready","in_progress","waiting_user")),"claimable_rewards_usd":round(sum(float(x.get("estimated_usd") or 0) for x in rewards if x["status"]=="claimable"),2),"realized_pnl_usd":round(sum(float(x.get("realized_usd") or 0) for x in rewards if x["status"]=="realized"),2),"unread_notifications":sum(1 for x in notifications if not x["read_at"])}

@app.get("/api/notifications")
async def notifications(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization); rows=await db_get("notifications",user["id"],"select=*&order=created_at.desc&limit=100",authorization.split(" ",1)[1])
    return {"items":rows,"unread_count":sum(1 for x in rows if not x["read_at"])}

@app.patch("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id:str,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    rows=await db_patch("notifications",{"id":notification_id,"owner_id":user["id"]},{"read_at":datetime.now(timezone.utc).isoformat()},authorization.split(" ",1)[1])
    if not rows: raise HTTPException(404,"Notification not found")
    return {"item":rows[0]}

@app.get("/api/opportunities")
async def opportunities(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("campaigns",user["id"],"select=*&order=discovered_at.desc&limit=100",authorization.split(" ",1)[1])}

@app.get("/api/tasks")
async def tasks(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("tasks",user["id"],"select=*&order=priority.desc,due_at.asc&limit=100",authorization.split(" ",1)[1])}

@app.get("/api/plan/today")
async def plan_today(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    rows=await db_get("tasks",user["id"],"select=*&status=in.(todo,ready,in_progress,waiting_user)&order=priority.desc,due_at.asc&limit=10",authorization.split(" ",1)[1])
    return {"engine":"rules","ai_enabled":False,"items":rows,"note":"План отсортирован по приоритету и срокам. LLM-планирование включится после отдельной настройки OpenAI API."}

class TaskStatusInput(BaseModel):
    status:str

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id:str,payload:TaskStatusInput,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    if payload.status not in {"todo","ready","in_progress","waiting_user","completed","skipped","blocked"}:
        raise HTTPException(400,"Invalid task status")
    token=authorization.split(" ",1)[1]
    now=datetime.now(timezone.utc).isoformat()
    data={"status":payload.status,"updated_at":now}
    if payload.status=="completed": data["completed_at"]=now
    rows=await db_patch("tasks",{"id":task_id,"owner_id":user["id"]},data,token)
    if not rows: raise HTTPException(404,"Task not found")
    await db_insert("task_events",{"owner_id":user["id"],"task_id":task_id,"event_type":"status_changed","details":{"status":payload.status,"source":"PWA"}},token)
    return {"item":rows[0]}

async def read_wallet_balance(client, wallet):
    chain=str(wallet.get("chain") or "").strip().lower()
    endpoint=RPC_ENDPOINTS.get(chain)
    if not endpoint:
        return {**wallet,"native_balance":None,"balance_symbol":None,"balance_status":"unsupported"}
    address=str(wallet.get("address") or "")
    if not (len(address)==42 and address.startswith("0x")):
        return {**wallet,"native_balance":None,"balance_symbol":NATIVE_SYMBOLS[chain],"balance_status":"invalid_address"}
    try:
        response=await client.post(endpoint,json={
            "jsonrpc":"2.0","id":1,"method":"eth_getBalance","params":[address,"latest"]
        })
        response.raise_for_status()
        payload=response.json()
        if payload.get("error") or not payload.get("result"):
            raise RuntimeError("RPC returned no balance")
        wei=int(payload["result"],16)
        return {
            **wallet,
            "native_balance":f"{wei/10**18:.6f}",
            "balance_symbol":NATIVE_SYMBOLS[chain],
            "balance_status":"ok",
            "balance_checked_at":datetime.now(timezone.utc).isoformat(),
        }
    except Exception as error:
        log.warning("Wallet balance read failed for %s: %s",wallet.get("id"),str(error)[:120])
        return {**wallet,"native_balance":None,"balance_symbol":NATIVE_SYMBOLS[chain],"balance_status":"unavailable"}

async def fetch_native_prices(client):
    try:
        response=await client.get("https://coins.llama.fi/prices/current/coingecko:ethereum,coingecko:polygon-ecosystem-token")
        response.raise_for_status()
        return (response.json() or {}).get("coins") or {}
    except Exception as error:
        log.warning("Native token price lookup failed: %s",str(error)[:120])
        return {}

@app.get("/api/wallets")
async def wallets(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    token=authorization.split(" ",1)[1]
    rows=await db_get("wallets",user["id"],"select=*&order=created_at.desc",token)
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
        items=await asyncio.gather(*(read_wallet_balance(client,row) for row in rows))
        prices=await fetch_native_prices(client)
    now=datetime.now(timezone.utc)
    price_ids={"polygon":"coingecko:polygon-ecosystem-token"}
    for chain in ("ethereum","base","arbitrum","optimism","linea","scroll"):
        price_ids[chain]="coingecko:ethereum"
    for item in items:
        chain=str(item.get("chain") or "").lower()
        price_data=prices.get(price_ids.get(chain) or "")
        if item.get("balance_status")=="ok" and price_data and price_data.get("price") is not None:
            item["balance_usd"]=round(float(item["native_balance"])*float(price_data["price"]),2)
            item["price_confidence"]=price_data.get("confidence")
        else:
            item["balance_usd"]=None
            item["price_confidence"]=None
    try:
        previous=await db_get("wallet_snapshots",user["id"],"select=wallet_id,captured_at&order=captured_at.desc&limit=200",token)
        latest={}
        for snapshot in previous:
            latest.setdefault(snapshot["wallet_id"],snapshot.get("captured_at"))
        snapshot_rows=[]
        for item in items:
            if item.get("balance_status")!="ok": continue
            captured=latest.get(item["id"])
            recent=False
            if captured:
                try:
                    recent=(now-datetime.fromisoformat(captured.replace("Z","+00:00"))).total_seconds()<3600
                except Exception:
                    recent=False
            if not recent:
                chain=str(item.get("chain") or "").lower()
                price_id=price_ids.get(chain)
                price_data=prices.get(price_id or {}) or {}
                snapshot_rows.append({
                    "owner_id":user["id"],"wallet_id":item["id"],
                    "native_balance":item["native_balance"],
                    "token_balances":{"native_symbol":item["balance_symbol"],"price_usd":price_data.get("price"),"price_confidence":price_data.get("confidence")},
                    "total_usd":item.get("balance_usd"),
                    "captured_at":now.isoformat(),
                })
        if snapshot_rows:
            await db_insert("wallet_snapshots",snapshot_rows,token)
    except Exception:
        log.exception("Could not save wallet balance snapshots")
    return {"items":items}

@app.get("/api/wallets/{wallet_id}/history")
async def wallet_history(wallet_id:str,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    rows=await db_get("wallet_snapshots",user["id"],f"select=*&wallet_id=eq.{wallet_id}&order=captured_at.desc&limit=30",authorization.split(" ",1)[1])
    return {"items":rows}

@app.get("/api/push/public-key")
async def push_key():
    return {"public_key":VAPID_PUBLIC_KEY or None}

@app.post("/api/push/subscribe")
async def push_subscribe(request:Request,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization); data=await request.json()
    keys=data.get("keys") or {}
    endpoint=data.get("endpoint")
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"): raise HTTPException(400,"Invalid push subscription")
    await db_insert("push_subscriptions",{"owner_id":user["id"],"endpoint":endpoint,"p256dh":keys["p256dh"],"auth_secret":keys["auth"],"user_agent":request.headers.get("user-agent")},authorization.split(" ",1)[1])
    return {"ok":True}

async def send_push_to_owner(owner_id, title, body, target_url="/", owner_token=None):
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return 0
    try:
        subscriptions=await db_get("push_subscriptions",owner_id,"select=endpoint,p256dh,auth_secret",owner_token)
    except Exception:
        log.exception("Could not load push subscriptions")
        return 0
    payload=json.dumps({"title":title,"body":body,"url":target_url},ensure_ascii=False)
    async def deliver(subscription):
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint":subscription["endpoint"],
                    "keys":{"p256dh":subscription["p256dh"],"auth":subscription["auth_secret"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub":VAPID_SUBJECT},
            )
            return True
        except WebPushException as error:
            log.warning("Web Push delivery failed: %s",str(error)[:180])
            return False
        except Exception as error:
            log.warning("Web Push error: %s",str(error)[:180])
            return False
    results=await asyncio.gather(*(deliver(item) for item in subscriptions))
    return sum(1 for result in results if result)

async def perform_scan(owner_id, token):
    run_rows=await db_insert("agent_runs",{
        "owner_id":owner_id,
        "job_type":"scheduled_scan" if token in (SUPABASE_SERVICE_ROLE_KEY,SUPABASE_SECRET_KEY) else "manual_scan",
        "status":"running",
        "started_at":datetime.now(timezone.utc).isoformat(),
        "summary":"Проверяю публичные источники DeFiLlama и Galxe.",
    },token)
    run_id=run_rows[0]["id"] if run_rows else None
    try:
        source_rows=await db_upsert("sources",[
            {"owner_id":owner_id,"name":"DeFiLlama","source_type":"api","base_url":"https://defillama.com","enabled":True,"last_checked_at":datetime.now(timezone.utc).isoformat()},
            {"owner_id":owner_id,"name":"Galxe","source_type":"platform","base_url":"https://app.galxe.com","enabled":True,"last_checked_at":datetime.now(timezone.utc).isoformat()},
        ],"owner_id,name",token)
        source_ids={row["name"]:row["id"] for row in source_rows}
        results=await asyncio.gather(
            fetch_defillama_candidates(),
            fetch_galxe_campaigns(),
            return_exceptions=True,
        )
        errors=[]
        records=[]
        counts={"DeFiLlama":0,"Galxe":0}
        for source_name,result in zip(("DeFiLlama","Galxe"),results):
            if isinstance(result,Exception):
                errors.append(f"{source_name}: {str(result)[:180]}")
                continue
            counts[source_name]=len(result)
            for item in result:
                item.update({
                    "owner_id":owner_id,
                    "source_id":source_ids.get(source_name),
                    "status":"discovered",
                    "eligibility":"unknown",
                    "region_restrictions":[],
                    "cost_estimate_usd":0,
                    "official_rules_url":item["url"] if source_name=="Galxe" else None,
                    "discovered_at":datetime.now(timezone.utc).isoformat(),
                    "checked_at":datetime.now(timezone.utc).isoformat(),
                })
                records.append(item)
        existing_campaign_rows=await db_get(
            "campaigns",owner_id,
            "select=url,status,eligibility,deadline,official_rules_url,confidence,estimated_reward_usd,region_restrictions,kyc_required,anti_sybil_notes,cost_estimate_usd,reward_description,ai_summary",
            token,
        )
        existing_by_url={
            str(row.get("url") or "").rstrip("/").lower():row
            for row in existing_campaign_rows
        }
        existing_urls=set(existing_by_url)
        unique_records={}
        for record in records:
            key=str(record.get("url") or "").rstrip("/").lower()
            if not key: continue
            if key in existing_by_url:
                record=preserve_review_state(record,existing_by_url[key])
            unique_records[key]=record
        records=list(unique_records.values())
        saved=await db_upsert("campaigns",records,"owner_id,url",token) if records else []
        new_saved=[row for row in saved if str(row.get("url") or "").rstrip("/").lower() not in existing_urls]
        if new_saved:
            existing_task_rows=await db_get("tasks",owner_id,"select=campaign_id",token)
            task_campaign_ids={row.get("campaign_id") for row in existing_task_rows if row.get("campaign_id")}
            review_tasks=[]
            for campaign in new_saved:
                if campaign.get("id") in task_campaign_ids: continue
                evidence=campaign.get("evidence") or []
                source_name=str((evidence[0] if evidence else {}).get("source") or "")
                # DeFiLlama protocol/TVL signals are watchlist entries, not reward tasks.
                # Galxe tasks enter the queue only when the title signals a cash reward
                # and does not advertise capital-intensive or hardware-dependent actions.
                if not should_create_review_task(campaign, source_name):
                    continue
                is_galxe=source_name.startswith("Galxe")
                note=("Учитывай закрытие Galxe Quest: участие до 5 декабря 2026, получение наград до 15 декабря 2026. " if is_galxe else "")
                review_tasks.append({
                    "owner_id":owner_id,"campaign_id":campaign["id"],
                    "title":"Проверить денежную награду: "+str(campaign.get("title") or campaign.get("project_name") or "кампания")[:120],
                    "description":note+"Это только кандидат с признаком денежной награды, а не подтверждённый доход. Проверить официальные правила, актуальный дедлайн, географию, KYC, anti-Sybil, вероятность/механику выплаты и обязательные расходы. Не вносить депозит, не торговать и не подписывать транзакции ради проверки.",
                    "task_url":campaign.get("official_rules_url") or campaign.get("url"),
                    "status":"todo","requires_user_action":True,"priority":65,"estimated_minutes":8,
                })
            if review_tasks:
                await db_insert("tasks",review_tasks,token)
        if errors and not saved:
            final_status="failed"
        else:
            final_status="succeeded"
        summary=f"Проверено кандидатов: {len(saved)}; новых: {len(new_saved)}. DeFiLlama: {counts['DeFiLlama']}; Galxe: {counts['Galxe']}."
        await db_patch("agent_runs",{"id":run_id,"owner_id":owner_id},{
            "status":final_status,
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "items_found":len(saved),
            "summary":summary,
            "error":"; ".join(errors) if errors else None,
            "metadata":{"source_counts":counts,"errors":errors,"new_candidates":len(new_saved)},
        },token)
        if new_saved:
            title="Новые кандидаты и задачи проверки"
            body=summary+" Награды и eligibility не подтверждены; сначала проверь условия."
            await db_insert("notifications",{
                "owner_id":owner_id,"title":title,"body":body,"category":"discovery",
            },token)
            await send_push_to_owner(owner_id,title,body,"/",token)
        return {
            "accepted":True,"status":final_status,"items_found":len(saved),
            "new_candidates":len(new_saved),"source_counts":counts,
            "errors":errors,"message":summary,
        }
    except Exception as error:
        if run_id:
            try:
                await db_patch("agent_runs",{"id":run_id,"owner_id":owner_id},{
                    "status":"failed","finished_at":datetime.now(timezone.utc).isoformat(),
                    "error":str(error)[:500],
                },token)
            except Exception:
                log.exception("Could not mark scan run as failed")
        raise

async def scheduled_health_scan():
    privileged_key=SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY
    if not privileged_key or not OWNER_EMAIL:
        log.info("Scheduled scan skipped: Supabase secret/service key or owner email is not configured.")
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles?select=id&limit=1",
                headers=db_headers(privileged_key),
            )
            response.raise_for_status()
            profiles=response.json()
        if not profiles:
            log.info("Scheduled scan skipped: owner profile has not been initialized by a login yet.")
            return
        await perform_scan(profiles[0]["id"],privileged_key)
    except Exception:
        log.exception("Scheduled discovery scan failed")

@app.post("/api/agent/run-scan")
async def run_scan(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return await perform_scan(user["id"],authorization.split(" ",1)[1])

class WalletInput(BaseModel):
    label:str
    address:str
    chain:str

@app.post("/api/wallets")
async def add_wallet(payload:WalletInput,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    address=payload.address.strip()
    if len(address)<10 or len(address)>128: raise HTTPException(400,"Invalid public wallet address")
    rows=await db_insert("wallets",{"owner_id":user["id"],"label":payload.label[:80],"address":address,"chain":payload.chain[:40]},authorization.split(" ",1)[1])
    return {"item":rows[0] if rows else None}

@app.get("/api/health/ready")
async def ready():
    needs=[]
    if not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY):
        needs.append("SUPABASE_SECRET_KEY (or legacy service_role key) for scheduled scans")
    if not (VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY):
        needs.append("VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY for push delivery")
    if not OWNER_EMAIL:
        needs.append("OWNER_EMAIL for single-owner scheduled scans")
    return {"ready":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"needs":needs}

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

@app.get("/", include_in_schema=False)
async def web_home():
    return FileResponse("web/index.html")

app.mount("/", StaticFiles(directory="web", html=True), name="web")
