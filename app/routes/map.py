import os
import secrets
import asyncio

from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import HTMLResponse

from ..services import update_map_data_cache
from ..database import record_visit
from ..config import logger


router = APIRouter()

# Глобальный кэш для данных карты
map_data_cache = {}


@router.get("/map_data")
async def get_map_data():
    return map_data_cache


@router.websocket("/ws/map")
async def websocket_map(websocket: WebSocket):
    """Эндпоинт передачи данных на карту"""
    await websocket.accept()
    try:
        for marker_data in map_data_cache:
            await websocket.send_json(marker_data)
            logger.info(f"Отправлены кэшированные данные для города {marker_data['city']}")
            await asyncio.sleep(0.005)
        await websocket.send_json({'status': 'complete'})
        logger.info("Все кэшированные данные карты отправлены")
    except Exception as e:
        logger.error(f"Ошибка в WebSocket: {e}")
        await websocket.send_json({'status': 'error', 'message': str(e)})
    finally:
        await websocket.close()


@router.get("/map", response_class=HTMLResponse)
async def get_map():
    """Эндпоинт страницы карты"""
    with open(os.path.join(os.path.dirname(__file__), "..", "static", "employees_map.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


@router.get("/track_visit")
async def track_visit(request: Request):
    """Эндпоинт подсчёта посетителей"""
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        visitor_id = secrets.token_urlsafe(16)
        response = HTMLResponse(content="Карта сотрудников", status_code=200)
        response.set_cookie("visitor_id", visitor_id, max_age=60*60*24)
    else:
        response = HTMLResponse(content="Карта сотрудников", status_code=200)

    record_visit(visitor_id)
    return response


@router.get("/refresh_cache")
async def refresh_cache():
    """Эндпоинт ручного обновления кэша карты"""
    update_map_data_cache()
    return {"message": "Map data cache refreshed"}