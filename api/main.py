import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.routes import health, trace, learning, platform
from nexus_platform.contexts import register_company_contexts

START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("NexusIQ API: registering platform company contexts...")
    register_company_contexts()
    print("NexusIQ API: ready. Docs at /docs")
    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="NexusIQ AI API",
    description="Multi-agent business intelligence API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(trace.router, prefix="/api/v1", tags=["trace"])
app.include_router(learning.router, prefix="/api/v1", tags=["learning"])
app.include_router(platform.router, prefix="/api/v1", tags=["platform"])


@app.get("/")
def root():
    return {
        "name": "NexusIQ AI API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }
