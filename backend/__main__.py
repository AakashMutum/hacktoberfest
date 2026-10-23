"""Run the server: python -m backend

Binds to 127.0.0.1 unless HOST is set (the Docker image sets HOST=0.0.0.0 inside the container).
"""
import os

import uvicorn

DEFAULT_HOST = "127.0.0.1"


def settings() -> tuple[str, int]:
    return os.getenv("HOST", DEFAULT_HOST), int(os.getenv("PORT", "8000"))


if __name__ == "__main__":
    host, port = settings()
    uvicorn.run("backend.api:app", host=host, port=port)
