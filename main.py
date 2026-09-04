"""Точка входа: запуск uvicorn (``uv run main.py``), настройки — ``common.settings``."""

import uvicorn

from common.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()
    try:
        uvicorn.run(
            app="src.app:app",
            host=settings.app_host,
            port=settings.app_port,
            reload=False,
            workers=settings.app_workers,
        )
    finally:
        print("Сервис остановлен")
