import os
import secrets
import asyncio
import json
import redis

from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import HTMLResponse

from ..services import update_map_data_cache
from ..database import record_visit
from ..config import logger
from ..state import map_data_cache


router = APIRouter()

# Инициализация Redis-клиента
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


@router.get("/map_data")
async def get_map_data():
    """Эндпоинт получения данных карты"""
    cached_data = redis_client.get("map_data_cache")
    data = json.loads(cached_data) if cached_data else []
    logger.info(f"map_data_cache in /map_data: {data}")
    return data


@router.websocket("/ws/map")
async def websocket_map(websocket: WebSocket):
    """Эндпоинт передачи данных на карту"""
    await websocket.accept()
    try:
        cached_data = redis_client.get("map_data_cache")
        data = json.loads(cached_data) if cached_data else []
        for marker_data in data:
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
