import json
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import DATABASE_URL

# ── Engine ────────────────────────────────────────────────────────────────────
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
_pool_cls     = StaticPool if DATABASE_URL.startswith("sqlite") else None

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    **({"poolclass": _pool_cls} if _pool_cls else {}),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── ORM base ─────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Tables ────────────────────────────────────────────────────────────────────
class StockModel(Base):
    __tablename__ = "stocks"

    ticker       = Column(String, primary_key=True)
    last_updated = Column(DateTime, default=datetime.utcnow)


class SignalModel(Base):
    __tablename__ = "signals"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    run_id     = Column(String,  nullable=False, index=True)
    ticker     = Column(String,  nullable=False, index=True)
    timestamp  = Column(DateTime, default=datetime.utcnow)
    agent_name = Column(String,  nullable=False)
    score      = Column(Float,   nullable=False)
    details    = Column(Text)

    def set_details(self, d: dict) -> None:
        self.details = json.dumps(d, default=str)

    def get_details(self) -> dict:
        return json.loads(self.details) if self.details else {}


class RankingModel(Base):
    __tablename__ = "rankings"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    run_id           = Column(String,  nullable=False, index=True)
    timestamp        = Column(DateTime, default=datetime.utcnow)
    rank             = Column(Integer, nullable=False)
    ticker           = Column(String,  nullable=False, index=True)
    final_score      = Column(Float,   nullable=False)
    momentum_score   = Column(Float,   default=0.0)
    volume_score     = Column(Float,   default=0.0)
    technical_score  = Column(Float,   default=0.0)
    vwap_score       = Column(Float,   default=0.0)
    breakout_score   = Column(Float,   default=0.0)
    sentiment_score  = Column(Float,   default=0.0)
    smart_money_score = Column(Float,  default=0.0)
    explanation      = Column(Text)
    curr_close       = Column(Float, nullable=True)
    details          = Column(Text, nullable=True)
    filtered_out     = Column(Boolean, default=False)
    filter_reason    = Column(String)


class PortfolioHolding(Base):
    __tablename__ = "portfolio"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    ticker    = Column(String,  nullable=False, index=True)
    shares    = Column(Float,   nullable=False)
    buy_price = Column(Float,   nullable=False)
    buy_date  = Column(String,  nullable=True)
    notes     = Column(String,  nullable=True)
    added_at  = Column(DateTime, default=datetime.utcnow)


class PortfolioSell(Base):
    __tablename__ = "portfolio_sells"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    holding_id  = Column(Integer, nullable=False, index=True)
    shares_sold = Column(Float,   nullable=False)
    sell_price  = Column(Float,   nullable=False)
    sell_date   = Column(String,  nullable=True)
    notes       = Column(String,  nullable=True)
    sold_at     = Column(DateTime, default=datetime.utcnow)


# ── Helpers ───────────────────────────────────────────────────────────────────
def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for col_sql in [
            "ALTER TABLE rankings ADD COLUMN details TEXT",
            "ALTER TABLE rankings ADD COLUMN curr_close REAL",
        ]:
            try:
                conn.execute(__import__('sqlalchemy').text(col_sql))
                conn.commit()
            except Exception:
                pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
