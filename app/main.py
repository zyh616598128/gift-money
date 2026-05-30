"""礼金管理系统 - FastAPI 入口"""
import logging
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings
from app.database import init_db
from app.routes import auth, transactions, categories, stats, people, import_export

# 配置日志系统
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="礼金管理系统", version="2.2.1")


class NoCacheMiddleware(BaseHTTPMiddleware):
    """禁用静态文件缓存"""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS - 修复配置冲突
cors_origins = settings.cors_origins if settings.cors_origins else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(stats.router)
app.include_router(people.router)
app.include_router(import_export.router)


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("应用启动完成")


@app.get("/health")
def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "version": "2.2.0",
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }


@app.get("/")
def read_index():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")
