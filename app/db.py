from datetime import datetime, timezone
import hashlib
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from config import AppConfig


class Base(DeclarativeBase):
    pass


engine = create_engine(AppConfig.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NeuAccount(Base):
    __tablename__ = "neu_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    neu_username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    neu_password: Mapped[str] = mapped_column(Text)
    neu_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    jobs: Mapped[list["RegistrationJob"]] = relationship(back_populates="account")


class RegistrationJob(Base):
    __tablename__ = "registration_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    neu_account_id: Mapped[str] = mapped_column(ForeignKey("neu_accounts.id"), index=True)
    regist_type: Mapped[str] = mapped_column(String(50), default="NKH")
    course_ids: Mapped[list[str]] = mapped_column(JSON)
    target_timestamp: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    account: Mapped[NeuAccount] = relationship(back_populates="jobs")
    events: Mapped[list["JobEvent"]] = relationship(back_populates="job")


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("registration_jobs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    job: Mapped[RegistrationJob] = relationship(back_populates="events")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("neu_accounts"):
        return
    columns = {column["name"] for column in inspector.get_columns("neu_accounts")}
    with engine.begin() as connection:
        if "neu_token_hash" not in columns:
            connection.execute(text("ALTER TABLE neu_accounts ADD COLUMN neu_token_hash VARCHAR(64)"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_neu_accounts_neu_token_hash "
                "ON neu_accounts (neu_token_hash)"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_account_by_neu_token(db: Session, token: str) -> NeuAccount | None:
    token_hash = hash_token(token)
    return db.execute(select(NeuAccount).where(NeuAccount.neu_token_hash == token_hash)).scalar_one_or_none()


def record_job_event(db: Session, job_id: str, event_type: str, message: str, metadata: dict | None = None) -> None:
    db.add(
        JobEvent(
            job_id=job_id,
            event_type=event_type,
            message=message,
            metadata_json=metadata or {},
        )
    )
    db.commit()
