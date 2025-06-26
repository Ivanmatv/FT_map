import sqlite3
from .config import DB_PATH, logger, REDMINE_URL


def init_db():
    """Создание базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            city TEXT NOT NULL,
            department TEXT,
            position TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            visit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def get_or_fetch_user_data(user_id: int):
    """Функция для получения данных из базы или API"""
    # Проверяем наличие пользователя в базе
    user_data = None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name, email, city, department, position FROM employees WHERE id = ?", (user_id,))
            result = cursor.fetchone()

        if result:
            name, email, city, department, position = result
            logger.debug(f"User {user_id} found in database: {name}, {email}, {city}, {department}, {position}")
            return {
                'user': {
                    'id': user_id,
                    'firstname': name.split()[0],
                    'lastname': ' '.join(name.split()[1:]),
                    'mail': email,
                    'custom_fields': [
                        {'name': 'Город проживания', 'value': city},
                        {'name': 'Отдел', 'value': department or ''},
                        {'name': 'Должность', 'value': position or ''}
                    ]
                }
            }
    except sqlite3.Error as e:
        logger.error(f"Database error when fetching user {user_id}: {e}")

    # Если не нашли в базе, получаем из API
    from .services import get_user_data, clean_city_name
    if not user_data:
        user_data = get_user_data(user_id)
        if user_data:
            user = user_data['user']
            email = user.get('mail', '')
            if email.endswith('@futuretoday.ru'):
                name = f"{user['firstname']} {user['lastname']}"
                city = "No city"
                department = None
                position = None
                for field in user.get('custom_fields', []):
                    if field['name'] == 'Город проживания':
                        city = field.get('value') or "No city"
                    elif field['name'] == 'Отдел':
                        department = field.get('value') or None
                    elif field['name'] == 'Должность':
                        position = field.get('value') or None
                city = clean_city_name(city) or "No city"

                try:
                    with sqlite3.connect(DB_PATH) as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT OR REPLACE INTO employees (id, name, email, city, department, position)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (user_id, name, email, city, department, position))
                        conn.commit()
                        logger.info(f"User {user_id} saved to database: {name}, {email}, {city}, {department}, {position}")
                except sqlite3.Error as e:
                    logger.error(f"Database error when saving user {user_id}: {e}")

    return user_data


def get_all_employees():
    """Получение сотрудиков из базы данных"""
    employees = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, email, city, department, position FROM employees")
            for row in cursor.fetchall():
                employees.append({
                    'id': row[0],
                    'name': row[1],
                    'profile_url': f"{REDMINE_URL}/users/{row[0]}",
                    'city': row[3],
                    'department': row[4] if row[4] and row[4] != 'None' else None,
                    'position': row[5] if row[5] and row[5] != 'None' else None
                })
            logger.info(f"Извлечено {len(employees)} сотрудников из базы данных")
    except sqlite3.Error as e:
        logger.error(f"Database error when fetching all employees: {e}")
    return employees


def get_unique_visitors(date_start, date_end):
    """Получение уникальных посетителей из базы данных"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Если даты одинаковые, фильтруем по точной дате
            if date_start == date_end:
                cursor.execute("""
                    SELECT COUNT(DISTINCT visitor_id)
                    FROM visits
                    WHERE DATE(visit_time) = ?
                """, (date_start,))
            else:
                cursor.execute("""
                    SELECT COUNT(DISTINCT visitor_id)
                    FROM visits
                    WHERE visit_time BETWEEN ? AND ?
                """, (date_start, date_end))
            unique_count = cursor.fetchone()[0]
            return unique_count
    except sqlite3.Error as e:
        logger.error(f"Database error when counting unique visitors: {e}")
        return 0


def get_total_visits(date_start, date_end):
    """Получение всех посетителей из базы данных"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Если даты одинаковые, фильтруем по точной дате
            if date_start == date_end:
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM visits
                    WHERE DATE(visit_time) = ?
                """, (date_start,))
            else:
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM visits
                    WHERE visit_time BETWEEN ? AND ?
                """, (date_start, date_end))
            total_count = cursor.fetchone()[0]
            return total_count
    except sqlite3.Error as e:
        logger.error(f"Database error when counting total visits: {e}")
        return 0


def record_visit(visitor_id):
    """Запись посетителей в базу данных"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO visits (visitor_id) VALUES (?)", (visitor_id,))
            conn.commit()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка записи в базу данных: {e}")        
