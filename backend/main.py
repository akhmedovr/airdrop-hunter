import os, time, json, logging
from datetime import datetime, timezone
from typing import Any
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("airdrop-hunter")
SUPABASE_URL=os.getenv("SUPABASE_URL","").rstrip("/")
SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY","")
SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","")
OWNER_EMAIL=os.getenv("OWNER_EMAIL","").strip().lower()
VAPID_PUBLIC_KEY=os.getenv("VAPID_PUBLIC_KEY","")
VAPID_PRIVATE_KEY=os.getenv("VAPID_PRIVATE_KEY","")
VAPID_SUBJECT=os.getenv("VAPID_SUBJECT","mailto:admin@example.com")
scheduler=AsyncIOScheduler(timezone="UTC")
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
    bearer=owner_token or SUPABASE_SERVICE_ROLE_KEY
    if bearer: h["Authorization"]=f"Bearer {bearer}"
    return h

async def db_get(table,owner_id,query="",owner_token: str|None=None):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY: raise HTTPException(503,"Database is not configured")
    headers=db_headers(owner_token)
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.get(f"{SUPABASE_URL}/rest/v1/{table}?owner_id=eq.{owner_id}&{query}",headers=headers)
    if r.status_code>=400: raise HTTPException(502,f"Database read failed: {r.text[:250]}")
    return r.json()

async def db_insert(table,payload,owner_token: str|None=None):
    if not SUPABASE_SERVICE_ROLE_KEY and not owner_token: raise HTTPException(503,"Database write is not configured")
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post(f"{SUPABASE_URL}/rest/v1/{table}",headers={**db_headers(owner_token),"Prefer":"return=representation"},json=payload)
    if r.status_code>=300: raise HTTPException(502,f"Database write failed: {r.text[:250]}")
    return r.json()

async def db_patch(table, owner_id, row_id, payload, owner_token):
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.patch(
            f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}&owner_id=eq.{owner_id}",
            headers={**db_headers(owner_token),"Prefer":"return=representation"},
            json=payload,
        )
    if r.status_code>=300: raise HTTPException(502,f"Database update failed: {r.text[:250]}")
    return r.json()

async def discover_defillama_candidates():
    url="https://api.llama.fi/protocols"
    allowed={"dexes","lending","yield","liquid staking","bridge","derivatives","cdp","farm","launchpad","yield aggregator","restaking","liquid restaking","perpetuals","options","insurance","oracle","nft marketplace","nft lending","rwa"}
    async with httpx.AsyncClient(timeout=35,follow_redirects=True,headers={"User-Agent":"AirdropHunter/2.0"}) as client:
        response=await client.get(url)
        response.raise_for_status()
        protocols=response.json()
    if not isinstance(protocols,list): raise HTTPException(502,"DeFiLlama вернул неожиданный формат данных")
    found=[]
    for item in protocols:
        chains=item.get("chains") or []
        symbol=(item.get("symbol") or "").strip()
        category=(item.get("category") or "").strip().lower()
        tvl=item.get("tvl") or 0
        if not any("polygon" in str(chain).lower() for chain in chains): continue
        if symbol not in ("","-") or category not in allowed: continue
        if not isinstance(tvl,(int,float)) or tvl<500_000 or tvl>500_000_000: continue
        slug=(item.get("slug") or "").strip()
        if not slug: continue
        llama_url=f"https://defillama.com/protocol/{slug}"
        found.append({
            "title":str(item.get("name") or slug)[:180],
            "project_name":str(item.get("name") or slug)[:180],
            "url":llama_url,
            "chain":"Polygon",
            "status":"discovered",
            "eligibility":"unknown",
            "region_restrictions":[],
            "kyc_required":None,
            "reward_description":"Награда и наличие аирдропа не подтверждены. Это только кандидат для проверки официальных источников.",
            "confidence":0.15,
            "cost_estimate_usd":0,
            "official_rules_url":None,
            "evidence":[{
                "source":"DeFiLlama",
                "url":llama_url,
                "observed_at":datetime.now(timezone.utc).isoformat(),
                "signal":"Протокол присутствует в каталоге DeFiLlama, работает в Polygon, TVL от $500 тыс. до $500 млн, тикер токена не указан.",
                "limitation":"Сигнал не подтверждает аирдроп, eligibility, доступность в стране или будущую стоимость награды."
            }],
            "ai_summary":"Непроверенный кандидат. Требуется отдельная проверка сайта проекта, официальных правил, географических ограничений, KYC, сроков и затрат."
        })
    found.sort(key=lambda x: x["title"].lower())
    return found[:40]

async def scan_for_owner(owner_id, owner_token):
    candidates=await discover_defillama_candidates()
    existing=await db_get("campaigns",owner_id,"select=url,project_name",owner_token)
    known={str(row.get("url") or "").rstrip("/").lower() for row in existing}
    fresh=[item for item in candidates if item["url"].rstrip("/").lower() not in known]
    inserted=await db_insert("campaigns",[{**item,"owner_id":owner_id} for item in fresh],owner_token) if fresh else []
    now=datetime.now(timezone.utc).isoformat()
    await db_insert("agent_runs",{
        "owner_id":owner_id,"job_type":"discovery_scan","status":"succeeded",
        "started_at":now,"finished_at":now,"items_found":len(candidates),
        "summary":f"Проверен каталог DeFiLlama. Новых кандидатов: {len(inserted)}. Награды и eligibility не подтверждены.",
        "metadata":{"source":"DeFiLlama /protocols","candidates_total":len(candidates),"new_candidates":len(inserted)}
    },owner_token)
    if inserted:
        await db_insert("notifications",{
            "owner_id":owner_id,"title":"Новые кандидаты для проверки",
            "body":f"Найдено {len(inserted)} новых кандидатов в Polygon. Это не подтверждённые аирдропы — условия требуют проверки.",
            "category":"discovery","target_url":"/"
        },owner_token)
    return {"items_found":len(candidates),"candidates_added":len(inserted),"items":inserted}

@app.on_event("startup")
async def startup():
    if os.getenv("ENABLE_SCHEDULER","true").lower()=="true":
        scheduler.add_job(scheduled_health_scan,"interval",minutes=int(os.getenv("SCAN_INTERVAL_MINUTES","360")),id="source-scan",replace_existing=True,max_instances=1)
        scheduler.start()

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running: scheduler.shutdown(wait=False)

@app.get("/api/health")
async def health():
    return {"status":"ok","service":"airdrop-hunter","scheduler_running":scheduler.running,"scanner_mode":"manual","database_configured":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"worker_write_enabled":bool(SUPABASE_SERVICE_ROLE_KEY),"push_configured":bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY),"time":datetime.now(timezone.utc).isoformat()}

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

@app.get("/api/opportunities")
async def opportunities(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("campaigns",user["id"],"select=*&order=discovered_at.desc&limit=100",authorization.split(" ",1)[1])}

@app.get("/api/tasks")
async def tasks(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("tasks",user["id"],"select=*&order=priority.desc,due_at.asc&limit=100",authorization.split(" ",1)[1])}

@app.get("/api/wallets")
async def wallets(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    return {"items":await db_get("wallets",user["id"],"select=*&order=created_at.desc",authorization.split(" ",1)[1])}

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

async def scheduled_health_scan():
    # Worker heartbeat only until official-source connectors and service credentials are configured.
    log.info("Scheduled scan heartbeat: connectors not yet configured; no wallet or transaction actions are performed.")

@app.post("/api/agent/run-scan")
async def run_scan(authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    try:
        result=await scan_for_owner(user["id"],authorization.split(" ",1)[1])
    except httpx.HTTPError as error:
        log.exception("DeFiLlama scan failed")
        raise HTTPException(502,"Не удалось получить данные DeFiLlama") from error
    return {"accepted":True,**result}

class TaskStatusInput(BaseModel):
    status:str

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id:str,payload:TaskStatusInput,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    if payload.status not in {"todo","ready","in_progress","waiting_user","completed","skipped","blocked"}:
        raise HTTPException(400,"Invalid task status")
    data={"status":payload.status,"updated_at":datetime.now(timezone.utc).isoformat()}
    if payload.status=="completed": data["completed_at"]=datetime.now(timezone.utc).isoformat()
    rows=await db_patch("tasks",user["id"],task_id,data,authorization.split(" ",1)[1])
    if not rows: raise HTTPException(404,"Task not found")
    return {"item":rows[0]}

@app.patch("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id:str,authorization: str|None=Header(default=None)):
    user=await auth_user(authorization)
    rows=await db_patch("notifications",user["id"],notification_id,{"read_at":datetime.now(timezone.utc).isoformat()},authorization.split(" ",1)[1])
    if not rows: raise HTTPException(404,"Notification not found")
    return {"item":rows[0]}

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
    return {"ready":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"needs":["SUPABASE_SERVICE_ROLE_KEY","VAPID keys","owner authentication setup"] if not SUPABASE_SERVICE_ROLE_KEY or not VAPID_PUBLIC_KEY else []}

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

@app.get("/", include_in_schema=False)
async def web_home():
    return FileResponse("web/index.html")

app.mount("/", StaticFiles(directory="web", html=True), name="web")
