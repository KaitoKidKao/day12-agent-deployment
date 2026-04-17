import os
import time
import signal
import json
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Local modules
from .config import settings
from .auth import verify_api_key
from .rate_limiter import check_rate_limit, r as redis_client
from .cost_guard import check_and_record_cost

# Mock LLM
from utils.mock_llm import ask as llm_ask

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

# Metrics & State
START_TIME = time.time()
_is_ready = False
_active_requests = 0
_total_requests = 0
_error_count = 0

# ─────────────────────────────────────────────────────────
# Lifespan - Graceful Startup & Shutdown
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "env": settings.environment
    }))
    
    # 1. Kiểm tra kết nối Redis trước khi Ready
    if redis_client:
        try:
            redis_client.ping()
            logger.info(json.dumps({"event": "redis_connected"}))
        except Exception as e:
            logger.error(json.dumps({"event": "redis_error", "error": str(e)}))
            # Vẫn khởi động nhưng không set ready
    else:
        logger.warning(json.dumps({"event": "redis_disabled", "msg": "Running without Redis"}))
    
    _is_ready = True
    yield
    
    # 2. Shutdown
    _is_ready = False
    logger.info(json.dumps({"event": "shutdown_started"}))
    
    # Chờ các request dở dang hoàn thành (tối đa 5s)
    wait_time = 0
    while _active_requests > 0 and wait_time < 5:
        logger.info(json.dumps({"event": "waiting_in_flight", "count": _active_requests}))
        time.sleep(1)
        wait_time += 1
        
    logger.info(json.dumps({"event": "shutdown_completed"}))

# ─────────────────────────────────────────────────────────
# App Config
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Agent Production",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# ─────────────────────────────────────────────────────────
# Middleware for logging and security headers
# ─────────────────────────────────────────────────────────
@app.middleware("http")
async def context_middleware(request: Request, call_next):
    global _active_requests, _total_requests, _error_count
    start = time.time()
    _active_requests += 1
    _total_requests += 1
    
    try:
        response: Response = await call_next(request)
        
        # Thêm Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if "server" in response.headers:
            del response.headers["server"]
        
        if response.status_code >= 400:
            _error_count += 1

        duration = round((time.time() - start) * 1000, 2)
        logger.info(json.dumps({
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration
        }))
        return response
    finally:
        _active_requests -= 1

# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)

class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    timestamp: str

# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/")
def info():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
            "metrics": "GET /metrics (requires X-API-Key)"
        }
    }

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _total_requests,
        "checks": {
            "llm": "mock" if not settings.openai_api_key else "openai",
            "redis": "connected" if redis_client else "disabled"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Service initializing")
    if not redis_client:
        return {"ready": True, "redis": "disabled"}
    try:
        redis_client.ping()
        return {"ready": True, "redis": "connected"}
    except:
        raise HTTPException(status_code=503, detail="Redis connection failed")

@app.get("/metrics")
def metrics(user_id: str = Depends(verify_api_key)):
    # Lấy chi phí hiện tại từ Redis nếu có
    daily_cost = 0.0
    if redis_client:
        today = time.strftime("%Y-%m-%d")
        cost_key = f"cost:{user_id}:{today}"
        daily_cost = float(redis_client.get(cost_key) or 0.0)
        
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _total_requests,
        "error_count": _error_count,
        "daily_cost_usd": daily_cost,
        "daily_budget_usd": settings.daily_budget_usd,
        "budget_used_pct": round((daily_cost / settings.daily_budget_usd) * 100, 1) if settings.daily_budget_usd > 0 else 0
    }

@app.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    user_id: str = Depends(verify_api_key)
):
    # 1. Rate Limiting (Redis-based)
    check_rate_limit(user_id)
    
    # 2. Cost Guard (Redis-based)
    # Giả lập token count
    in_tokens = len(body.question.split()) * 2
    check_and_record_cost(user_id, input_tokens=in_tokens)
    
    # 3. Stateless Chat History (Redis-based)
    history_raw = []
    if redis_client:
        history_key = f"chat_history:{user_id}"
        # Lấy 5 tin nhắn gần nhất
        history_raw = redis_client.lrange(history_key, 0, 4)
    
    history = [json.loads(m) for m in history_raw]
    
    # 4. Call LLM (Mock)
    # Trong thực tế sẽ gửi history kèm theo request
    answer = llm_ask(body.question)
    
    # 5. Save History & Record Out-tokens
    out_tokens = len(answer.split()) * 2
    check_and_record_cost(user_id, output_tokens=out_tokens)
    
    if redis_client:
        new_message = {"q": body.question, "a": answer, "ts": time.time()}
        redis_client.lpush(history_key, json.dumps(new_message))
        redis_client.ltrim(history_key, 0, 19) # Giữ tối đa 20 tin nhắn
        redis_client.expire(history_key, 3600) # Expire sau 1h
    
    return AskResponse(
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        timestamp=datetime.now(timezone.utc).isoformat()
    )

# ─────────────────────────────────────────────────────────
# Graceful Shutdown Handling (SIGTERM)
# ─────────────────────────────────────────────────────────
def handle_sigterm(signum, frame):
    """Handle SIGTERM signal for graceful shutdown."""
    global _is_ready
    _is_ready = False
    logger.info(json.dumps({"event": "signal_received", "signal": "SIGTERM"}))

# Register signal handlers
signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=settings.debug)
