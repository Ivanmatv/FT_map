import secrets
import os
import sqlite3
import json
import redis

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse

from ..models import LoginRequest, TokenRequest, UserRange, SheetTask
from ..services import process_users, process_sheet_update, get_google_sheet, update_map_data_cache
from ..database import get_unique_visitors, get_total_visits
from ..config import ADMIN_PASSWORD, logger, DB_PATH
from ..state import admin_token_store, progress_store


router = APIRouter()

# Инициализация Redis-клиента
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


@router.get("/admin_stats")
async def get_admin_stats(date_start: str, date_end: str):
    """Эндпоинт статистики посещений"""
    unique_visitors = get_unique_visitors(date_start, date_end)
    total_visits = get_total_visits(date_start, date_end)
    return {"unique_visitors": unique_visitors, "total_visits": total_visits}


@router.post("/admin_login")
async def admin_login(login_request: LoginRequest):
    """Эндпоинт авторизации админа"""
    if login_request.password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        admin_token_store[token] = True
        logger.info("Успешная авторизация в админ-панели")
        return {"status": "success", "token": token}
    logger.warning("Неудачная попытка авторизации в админ-панели")
    return {"status": "error", "message": "Неверный пароль"}


@router.post("/check_admin_token")
async def check_admin_token(token_request: TokenRequest):
    """Эндпоинт проверки токена адмниа"""
    if token_request.token in admin_token_store:
        logger.debug("Токен админ-панели действителен")
        return {"status": "success"}
    logger.warning("Недействительный токен админ-панели")
    return {"status": "error", "message": "Недействительный токен"}


@router.get("/admin", response_class=HTMLResponse)
async def get_admin_panel(request: Request):
    """Эндпоинт страницы админа"""
    admin_token = request.cookies.get("admin_token")
    with open(os.path.join(os.path.dirname(__file__), "..", "static", "admin.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    if not admin_token or admin_token not in admin_token_store:
        logger.warning("Попытка доступа к админ-панели без авторизации")
        return HTMLResponse(content=html_content)
    return HTMLResponse(content=html_content)


@router.post("/add_users")
async def add_users(user_range: UserRange, background_tasks: BackgroundTasks):
    """Эндпроинт добавления пользователй в БД"""
    start_id = user_range.start_id
    end_id = user_range.end_id
    task_id = user_range.task_id

    if start_id < 1 or end_id < start_id:
        logger.warning(f"Invalid range {start_id}-{end_id} for task {task_id}")
        return {"message": "Некорректный диапазон ID", "status": "error"}

    background_tasks.add_task(process_users, start_id, end_id, task_id)
    logger.info(f"Scheduled background task {task_id} for range {start_id}-{end_id}")
    return {"message": "Обработка запущена", "task_id": task_id, "status": "success"}


@router.get("/progress/{task_id}")
async def get_progress(task_id: str):
    """Получение прогресса поиска сотрудников"""
    progress = progress_store.get(task_id, {'progress': 0, 'error': None, 'message': None, 'added_count': 0})
    logger.debug(f"Progress requested for task {task_id}: {progress}")
    return progress


@router.post("/update_from_sheet")
async def update_from_sheet(task: SheetTask, background_tasks: BackgroundTasks):
    """Эндпоинт загрузки данных из гугл таблицы"""
    try:
        sheet = get_google_sheet()
        all_records = sheet.get_all_records()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM employees")
        db_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        redis_client.set(task.task_id, json.dumps({
            "processed": 0,
            "total": len(db_ids),
            "message": "",
            "error": False
        }))

        background_tasks.add_task(process_sheet_update, db_ids, all_records, task.task_id)
        return {"status": "success", "total_users": len(db_ids), "task_id": task.task_id}
    except Exception as e:
        logger.error(f"Sheet update error: {str(e)}")
        return {"status": "error", "message": str(e)}


@router.get("/sheet_progress/{task_id}")
async def get_sheet_progress(task_id: str):
    """Получение прогресса по обновлению данных из Google Sheets"""
    progress = json.loads(redis_client.get(task_id) or '{"processed": 0, "error": True, "message": "Task not found"}')
    logger.debug(f"Sheet progress requested for task {task_id}: {progress}")
    return progress


@router.get("/refresh_cache")
async def refresh_cache():
    """Эндпоинт ручного обновления кэша карты"""
    update_map_data_cache()
    return {"message": "Map data cache refreshed"}
