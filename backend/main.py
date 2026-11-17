import os, time, json, logging, asyncio
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
                    "reward_description":"Публичная активная кампания. Наличие токеновой награды и eligibility не подтверждено.",
                    "confidence":0.35,
                    "evidence":[{
                        "source":"Galxe",
                        "campaign_id":item["id"],
                        "observed_status":item["status"],
                        "checked_at":datetime.now(timezone.utc).isoformat(),
                    }],
                    "ai_summary":"Найдено активное публичное задание. Перед выполнением нужно проверить официальные правила, доступность региона, KYC, сроки и расходы.",
                    "anti_sybil_notes":"Не обходить KYC, географические ограничения, CAPTCHA и anti-Sybil правила.",
                }
    return list(campaigns.values())

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
    return {"status":"ok","service":"airdrop-hunter","scheduler_running":scheduler.running,"database_configured":bool(SUPABASE_URL and SUPABASE_ANON_KEY),"worker_write_enabled":bool(SUPABASE_SERVICE_ROLE_KEY),"time":datetime.now(timezone.utc).isoformat()}

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
    token=authorization.split(" ",1)[1]
    owner_id=user["id"]
    run_rows=await db_insert("agent_runs",{
        "owner_id":owner_id,
        "job_type":"manual_scan",
        "status":"running",
        "started_at":datetime.now(timezone.utc).isoformat(),
        "summary":"Проверяю публичные источники DeFiLlama и Galxe.",
    },token)
    run_id=run_rows[0]["id"] if run_rows else None
    try:
        source_rows=await db_upsert("sources",[
            {"owner_id":owner_id,"name":"DeFiLlama","source_type":"protocol_discovery","base_url":"https://defillama.com","enabled":True,"last_checked_at":datetime.now(timezone.utc).isoformat()},
            {"owner_id":owner_id,"name":"Galxe","source_type":"campaign_discovery","base_url":"https://app.galxe.com","enabled":True,"last_checked_at":datetime.now(timezone.utc).isoformat()},
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
        saved=await db_upsert("campaigns",records,"owner_id,url",token) if records else []
        if errors and not saved:
            final_status="failed"
        else:
            final_status="succeeded"
        summary=f"Найдено записей: {len(saved)}. DeFiLlama: {counts['DeFiLlama']}; Galxe: {counts['Galxe']}."
        await db_patch("agent_runs",{"id":run_id,"owner_id":owner_id},{
            "status":final_status,
            "finished_at":datetime.now(timezone.utc).isoformat(),
            "items_found":len(saved),
            "summary":summary,
            "error":"; ".join(errors) if errors else None,
            "metadata":{"source_counts":counts,"errors":errors},
        },token)
        if saved:
            await db_insert("notifications",{
                "owner_id":owner_id,
                "title":"Проверка источников завершена",
                "body":summary+" Все найденные записи требуют отдельной проверки eligibility и награды.",
                "category":"discovery",
            },token)
        return {
            "accepted":True,
            "status":final_status,
            "items_found":len(saved),
            "source_counts":counts,
            "errors":errors,
            "message":summary,
        }
    except Exception as error:
        if run_id:
            try:
                await db_patch("agent_runs",{"id":run_id,"owner_id":owner_id},{
                    "status":"failed",
                    "finished_at":datetime.now(timezone.utc).isoformat(),
                    "error":str(error)[:500],
                },token)
            except Exception:
                log.exception("Could not mark scan run as failed")
        raise

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
