import os
import asyncio
import secrets

from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@app.on_event("startup")
async def startup_event():
    """Запуск кэша при старте приложения"""
    update_map_data_cache()  # Инициализация кэша при старте
    asyncio.create_task(periodic_cache_update())  # Запуск периодического обновления


@app.get("/map_data")
async def get_map_data():
    return map_data_cache


@app.get("/admin_stats")
async def get_admin_stats():
    """Эндпоинт для подсчёта посетитлей"""
    unique_visitors = get_unique_visitors()
    total_visits = get_total_visits()
    return {"unique_visitors": unique_visitors, "total_visits": total_visits}


@app.post("/login")
async def login(request: Request):
    """Эндпоинт для авторизации"""
    data = await request.json()
    if data.get("password") == PASSWORD:
        token = secrets.token_urlsafe(32)
        token_store[token] = True
        return {"status": "success", "token": token}
    return {"status": "error", "message": "Неверный пароль"}


@app.post("/check_token")
async def check_token(request: Request):
    """Эндпоинт проверки токена авторизации"""
    data = await request.json()
    token = data.get("token")
    if token in token_store:
        return {"status": "success"}
    return {"status": "error", "message": "Недействительный токен"}


@app.post("/admin_login")
async def admin_login(login_request: LoginRequest):
    """Эндпоинт для авторизации в админ-панели"""
    if login_request.password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        admin_token_store[token] = True
        logger.info("Успешная авторизация в админ-панели")
        return {"status": "success", "token": token}
    logger.warning("Неудачная попытка авторизации в админ-панели")
    return {"status": "error", "message": "Неверный пароль"}


@app.post("/check_admin_token")
async def check_admin_token(token_request: TokenRequest):
    """Эндпоинт для проверки токена админ-панели"""
    if token_request.token in admin_token_store:
        logger.debug("Токен админ-панели действителен")
        return {"status": "success"}
    logger.warning("Недействительный токен админ-панели")
    return {"status": "error", "message": "Недействительный токен"}


@app.get("/progress/{task_id}")
async def get_progress(task_id: str):
    """Эндпоинт для получения прогресса"""
    progress = progress_store.get(task_id, {'progress': 0, 'error': None, 'message': None, 'added_count': 0})
    logger.debug(f"Progress requested for task {task_id}: {progress}")
    return progress


@app.post("/add_users")
async def add_users(user_range: UserRange, background_tasks: BackgroundTasks):
    """Эндпоинт для добавления новых сотрудников"""
    start_id = user_range.start_id
    end_id = user_range.end_id
    task_id = user_range.task_id

    if start_id < 1 or end_id < start_id:
        logger.warning(f"Invalid range {start_id}-{end_id} for task {task_id}")
        return {"message": "Некорректный диапазон ID", "status": "error"}

    # Запускаем обработку в фоновом режиме
    background_tasks.add_task(process_users, start_id, end_id, task_id)
    logger.info(f"Scheduled background task {task_id} for range {start_id}-{end_id}")
    return {"message": "Обработка запущена", "task_id": task_id, "status": "success"}


@app.get("/", response_class=HTMLResponse)
async def get_home():
    """Эндпоинт главной страницы"""
    with open(os.path.join("app", "static", "index.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


@app.get("/admin", response_class=HTMLResponse)
async def get_admin_panel(request: Request):
    """"Эндпоинт страницы админ-панели"""
    admin_token = request.cookies.get("admin_token")
    if not admin_token or admin_token not in admin_token_store:
        logger.warning("Попытка доступа к админ-панели без авторизации")
        with open(os.path.join("app", "static", "admin.html"), "r", encoding="utf-8") as file:
            html_content = file.read()
        return HTMLResponse(content=html_content)
    with open(os.path.join("app", "static", "admin.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


@app.websocket("/ws/map")
async def websocket_map(websocket: WebSocket):
    """WebSocket для отправки данных карты в реальном времени"""
    await websocket.accept()
    try:
        for marker_data in map_data_cache:
            await websocket.send_json(marker_data)
            logger.info(f"Отправлены кэшированные данные для города {marker_data['city']}")
            await asyncio.sleep(0.005)  # Небольшая задержка для имитации потоковой передачи
        await websocket.send_json({'status': 'complete'})
        logger.info("Все кэшированные данные карты отправлены")
    except Exception as e:
        logger.error(f"Ошибка в WebSocket: {e}")
        await websocket.send_json({'status': 'error', 'message': str(e)})
    finally:
        await websocket.close()


@app.get("/map", response_class=HTMLResponse)
async def get_map():
    """Эндпоинт для карты"""
    with open(os.path.join("app", "static", "employees_map.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


@app.post("/update_from_sheet")
async def update_from_sheet(task: SheetTask, background_tasks: BackgroundTasks):
    """Эндпоинт обновления таблицы сотрудников"""
    try:
        sheet = get_google_sheet()
        all_records = sheet.get_all_records()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM employees")
        db_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        progress_store[task.task_id] = {
            "processed": 0,
            "total": len(db_ids),
            "message": "",
            "error": False
        }

        background_tasks.add_task(process_sheet_update, db_ids, all_records, task.task_id)
        return {"status": "success", "total_users": len(db_ids), "task_id": task.task_id}
    except Exception as e:
        logger.error(f"Sheet update error: {str(e)}")
        return {"status": "error", "message": str(e)}


@app.get("/sheet_progress/{task_id}")
async def get_sheet_progress(task_id: str):
    """Эндпоинт обновления статусбара"""
    return progress_store.get(task_id, {"processed": 0, "error": True, "message": "Task not found"})


@app.get("/refresh_cache")
async def refresh_cache():
    """Эндпоинт для ручного обнолвления кэша"""
    update_map_data_cache()
    return {"message": "Map data cache refreshed"}


@app.get("/track_visit")
async def track_visit(request: Request):
    """Эндпоинт для отслеживания посещений карты"""
    # Генерация уникального ID посетителя (можно использовать сессионные cookies или IP-адрес)
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        visitor_id = secrets.token_urlsafe(16)  # Создаём уникальный идентификатор для посетителя
        response = HTMLResponse(content="Карта сотрудников", status_code=200)
        response.set_cookie("visitor_id", visitor_id, max_age=60*60*24)  # Храним ID посетителя в cookie
    else:
        response = HTMLResponse(content="Карта сотрудников", status_code=200)

    # Регистрируем посещение
    record_visit(visitor_id)

    return response
