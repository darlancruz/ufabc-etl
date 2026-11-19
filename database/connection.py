"""Conexão com o PostgreSQL (SQLAlchemy). Importado só quando há carga real."""
import os
from pathlib import Path

from dotenv import load_dotenv

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_engine():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    load_dotenv()
    faltando = [v for v in ("DB_USER", "DB_PASSWORD", "DB_NAME") if not os.getenv(v)]
    if faltando:
        raise RuntimeError(f"Variáveis ausentes no .env: {faltando}")

    # URL.create escapa senhas com caracteres especiais (@, :, /...)
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME"),
    )
    return create_engine(url)


class SqlAlchemyDb:
    """Adapta uma Connection do SQLAlchemy à interface `Db` usada em etl/load.py."""

    def __init__(self, conn):
        from sqlalchemy import text

        self._conn, self._text = conn, text

    def execute(self, sql, params=None):
        resultado = self._conn.execute(self._text(sql), params or {})
        return [tuple(r) for r in resultado.fetchall()] if resultado.returns_rows else []

    def executemany(self, sql, rows):
        if rows:
            self._conn.execute(self._text(sql), rows)


def init_schema(engine) -> bool:
    """Cria as tabelas se ainda não existirem. Retorna True se criou."""
    from sqlalchemy import text

    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass('public.turma')")).scalar():
            return False
        conn.exec_driver_sql(SCHEMA_PATH.read_text(encoding="utf-8"))
    return True
