from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

from .database import init_db
from .services import update_map_data_cache
from .routes.auth import router as auth_router
from .routes.admin import router as admin_router
from .routes.map import router as map_router
from .routes.home import router as home_router


app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Include routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(map_router)
app.include_router(home_router)


@app.on_event("startup")
async def startup_event():
    init_db()   # Инициализация базы данных
    update_map_data_cache()         # Инициализация кэша при старте
    # asyncio.create_task(periodic_cache_update())       # Запуск периодического обновления
