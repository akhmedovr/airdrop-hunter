"""
src/core/database.py
SQLAlchemy: engine, session, модели и функции для работы с БД.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from src.core.config import BASE_DIR, settings


# =========================================================================
# БАЗОВЫЙ КЛАСС
# =========================================================================
class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


# =========================================================================
# МОДЕЛИ
# =========================================================================
class Wallet(Base):
    """Крипто-кошелёк (farming или cold)."""
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(64), default="wallet")
    wallet_type: Mapped[str] = mapped_column(String(16), default="farming")  # farming | cold
    encrypted_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    balance_usd: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Связи
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="wallet", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Wallet {self.label} | {self.address[:10]}...>"


class Airdrop(Base):
    """Найденный аирдроп."""
    __tablename__ = "airdrops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(32))  # zealy | galxe | layer3 | other
    url: Mapped[str] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reward_estimate: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | in_progress | completed | failed
    score: Mapped[int] = mapped_column(Integer, default=0)  # рейтинг перспективности
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Связи
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="airdrop", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Airdrop {self.name} | {self.status}>"


class Task(Base):
    """Задание внутри аирдропа."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airdrop_id: Mapped[int] = mapped_column(ForeignKey("airdrops.id"))
    description: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(32))  # social | swap | bridge | other
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | completed | failed
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Связи
    airdrop: Mapped["Airdrop"] = relationship("Airdrop", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task {self.task_type} | {self.status}>"


class Transaction(Base):
    """Транзакция кошелька."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    tx_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    chain: Mapped[str] = mapped_column(String(32), default="polygon")
    tx_type: Mapped[str] = mapped_column(String(32))  # swap | bridge | receive | send
    token_from: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    token_to: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    amount_from: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount_to: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gas_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | success | failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи
    wallet: Mapped["Wallet"] = relationship("Wallet", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction {self.tx_type} | {self.status}>"


# =========================================================================
# ENGINE И SESSION
# =========================================================================
# SQLite не требует отдельного драйвера. Позже — PostgreSQL без изменения кода.
DB_PATH = BASE_DIR / "data" / "airdrop.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Формируем URL БД
database_url = settings.DATABASE_URL
if database_url.startswith("sqlite:///./"):
    # Преобразуем относительный путь в абсолютный
    relative = database_url.replace("sqlite:///./", "")
    database_url = f"sqlite:///{BASE_DIR / relative}"

engine = create_engine(
    database_url,
    echo=False,           # True — для отладки SQL-запросов
    future=True,
    pool_pre_ping=True,   # проверка соединения перед использованием
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


# =========================================================================
# ФУНКЦИИ
# =========================================================================
def init_db() -> None:
    """Создаёт все таблицы, если их нет."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    """Возвращает новую сессию. Использовать через `with get_session() as s:`."""
    return SessionLocal()
