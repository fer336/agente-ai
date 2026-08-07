from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.webhook import router as webhook_router
from app.config.settings import get_settings

app = FastAPI(title="Clinic AI Agent")
app.include_router(health_router)
app.include_router(webhook_router)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port)
