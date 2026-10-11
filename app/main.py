import logging

import uvicorn

from app.api.application import create_application
from app.config import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    uvicorn.run(
        create_application(settings), host=settings.APP_HOST, port=settings.APP_PORT
    )


if __name__ == "__main__":
    main()
