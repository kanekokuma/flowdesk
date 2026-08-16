import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


engine = None
SessionLocal = None


def init_engine():
    global engine, SessionLocal
    if engine is not None:
        return

    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "3306")
    name = os.environ.get("DB_NAME", "workflow_app")
    user = os.environ.get("DB_USER", "workflow_user")
    password = os.environ.get("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORDを環境変数に設定してください。")
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"
    engine = create_engine(url, pool_pre_ping=True, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    ensure_schema()


def ensure_schema():
    with engine.begin() as connection:
        column_exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'applications'
                  AND COLUMN_NAME = 'returned_fields_json'
                """
            )
        ).scalar()
        if not column_exists:
            connection.execute(text("ALTER TABLE applications ADD COLUMN returned_fields_json TEXT NULL AFTER detail_json"))
        table_exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'application_templates'
                """
            )
        ).scalar()
        if not table_exists:
            connection.execute(
                text(
                    """
                    CREATE TABLE application_templates (
                      id INT AUTO_INCREMENT PRIMARY KEY,
                      employee_id VARCHAR(20) NOT NULL,
                      name VARCHAR(120) NOT NULL,
                      application_type_id VARCHAR(20) NOT NULL,
                      form_json TEXT NOT NULL,
                      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (employee_id) REFERENCES employees(id),
                      FOREIGN KEY (application_type_id) REFERENCES application_types(id)
                    )
                    """
                )
            )
        route_table_exists = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'application_type_approval_routes'
                """
            )
        ).scalar()
        if not route_table_exists:
            connection.execute(
                text(
                    """
                    CREATE TABLE application_type_approval_routes (
                      application_type_id VARCHAR(20) NOT NULL,
                      step_no INT NOT NULL,
                      position_id VARCHAR(20) NOT NULL,
                      PRIMARY KEY (application_type_id, step_no),
                      FOREIGN KEY (application_type_id) REFERENCES application_types(id) ON DELETE CASCADE,
                      FOREIGN KEY (position_id) REFERENCES positions(id)
                    )
                    """
                )
            )


@contextmanager
def db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
