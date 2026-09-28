"""Shared FastAPI dependencies."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from vibing import db
from vibing.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when the response is done."""
    conn = db.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[sqlite3.Connection, Depends(get_db)]
