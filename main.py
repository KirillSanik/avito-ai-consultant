import uvicorn
from utils.config import CONFIG

if __name__ == "__main__":
    try:
        uvicorn.run(
            app="src.app:app",
            host=CONFIG.APP_HOST,
            port=CONFIG.APP_PORT,
            reload=False,
            workers=CONFIG.APP_WORKERS,
        )
    finally:
        print("Сервис остановлен")