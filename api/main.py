"""Run with: python -m uvicorn api.main:app --port 8000"""

from api.app import create_app

app = create_app()
