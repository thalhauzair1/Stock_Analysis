from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class StockResult(BaseModel):
    ticker:           str
    rank:             int
    final_score:      float = Field(ge=0.0, le=1.0)
    momentum_score:   float
    volume_score:     float
    technical_score:  float
    vwap_score:       float
    breakout_score:   float
    sentiment_score:  float
    smart_money_score: float
    explanation:      str
    timestamp:        str
    run_id:           str


class SignalDetail(BaseModel):
    score:   float
    details: dict[str, Any]


class StockSignals(BaseModel):
    ticker:      str
    final_score: float
    explanation: str
    signals:     dict[str, SignalDetail]


class HealthResponse(BaseModel):
    status:             str
    timestamp:          datetime
    db_ok:              bool
    last_run:           Optional[datetime] = None
    stocks_analyzed:    int = 0
    openai_enabled:     bool = False
    anthropic_enabled:  bool = False
    news_enabled:       bool = False


class AddHoldingRequest(BaseModel):
    ticker:    str
    shares:    float = Field(gt=0)
    buy_price: float = Field(gt=0)
    buy_date:  Optional[str] = None
    notes:     Optional[str] = None


class RecordSellRequest(BaseModel):
    shares_sold: float = Field(gt=0)
    sell_price:  float = Field(gt=0)
    sell_date:   Optional[str] = None
    notes:       Optional[str] = None
