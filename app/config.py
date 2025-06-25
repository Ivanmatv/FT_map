import os
from dotenv import load_dotenv
from .logger import get_logger

load_dotenv()

REDMINE_URL = "https://tasks.fut.ru"
API_KEY = os.getenv("API_KEY")
PASSWORD = os.getenv("PASSWORD")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")

logger = get_logger()

if not API_KEY:
    logger.error("API_KEY not found in .env file or is empty")
    raise ValueError("API_KEY not found in .env file or is empty")

if not PASSWORD:
    logger.error("PASSWORD not found in .env file or is empty")
    raise ValueError("PASSWORD not found in .env file or is empty")

if not ADMIN_PASSWORD:
    logger.error("ADMIN_PASSWORD not found in .env file or is empty")
    raise ValueError("ADMIN_PASSWORD not found in .env file or is empty")