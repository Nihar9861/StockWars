import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON,
                        Numeric, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MONEY = Numeric(20, 2)
PRICE = Numeric(18, 4)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)  # PENDING/ACTIVE/REJECTED/SUSPENDED/BANNED
    role: Mapped[str] = mapped_column(String(16), default="PLAYER")  # PLAYER/MODERATOR/ADMIN/SUPER_ADMIN/OWNER
    rank: Mapped[str] = mapped_column(String(32), default="Beginner")
    notify_mode: Mapped[str] = mapped_column(String(16), default="ALL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Wallet(Base):
    __tablename__ = "wallets"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    available: Mapped[Decimal] = mapped_column(MONEY, default=0)
    reserved: Mapped[Decimal] = mapped_column(MONEY, default=0)
    __table_args__ = (CheckConstraint("available >= 0", name="ck_wallet_nonneg"),)


class WalletTransaction(Base):
    """Append-only ledger. Never UPDATE/DELETE rows."""
    __tablename__ = "wallet_transactions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)  # signed
    balance_before: Mapped[Decimal] = mapped_column(MONEY)
    balance_after: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(String(255), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Sector(Base):
    __tablename__ = "sectors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    momentum: Mapped[float] = mapped_column(default=0.0)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    ticker: Mapped[str] = mapped_column(String(8), unique=True)
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ceo: Mapped[str] = mapped_column(String(64), default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # null = NPC
    total_shares: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal] = mapped_column(PRICE)
    prev_close: Mapped[Decimal] = mapped_column(PRICE)
    revenue: Mapped[Decimal] = mapped_column(MONEY, default=0)
    profit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    debt: Mapped[Decimal] = mapped_column(MONEY, default=0)
    reputation: Mapped[int] = mapped_column(default=50)
    growth_rate: Mapped[float] = mapped_column(default=0.0)  # % per year-ish, drives drift
    volatility: Mapped[float] = mapped_column(default=0.01)
    risk_level: Mapped[str] = mapped_column(String(8), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE/DISTRESSED/SUSPENDED/BANKRUPT
    listing: Mapped[str] = mapped_column(String(16), default="LISTED")
    cash: Mapped[Decimal] = mapped_column(MONEY, default=0)
    pressure: Mapped[int] = mapped_column(BigInteger, default=0)  # net shares bought this cycle
    volume: Mapped[int] = mapped_column(BigInteger, default=0)  # shares traded this cycle
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ShareOwnership(Base):
    __tablename__ = "share_ownership"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_price: Mapped[Decimal] = mapped_column(PRICE, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=0)
    __table_args__ = (UniqueConstraint("user_id", "company_id"), CheckConstraint("quantity >= 0", name="ck_qty_nonneg"))


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal] = mapped_column(PRICE)
    value: Mapped[Decimal] = mapped_column(MONEY)
    fee: Mapped[Decimal] = mapped_column(MONEY)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class MarketState(Base):
    __tablename__ = "market_state"
    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    status: Mapped[str] = mapped_column(String(16), default="CLOSED")
    halted: Mapped[bool] = mapped_column(Boolean, default=False)
    cycle_no: Mapped[int] = mapped_column(default=0)
    sentiment: Mapped[float] = mapped_column(default=0.0)  # -1..1
    index_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    index_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=1000)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    cycle_no: Mapped[int]
    price: Mapped[Decimal] = mapped_column(PRICE)
    ret: Mapped[float]
    inputs: Mapped[dict] = mapped_column(JSON)  # every input used for this price update
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("company_id", "cycle_no"), Index("ix_ph_company_time", "company_id", "created_at"))


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_no: Mapped[int] = mapped_column(unique=True)
    index_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MarketEvent(Base):
    __tablename__ = "market_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_key: Mapped[str] = mapped_column(String(48), index=True)
    headline: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(16))  # SECTOR/COMPANY/GLOBAL/SPECIAL
    severity: Mapped[str] = mapped_column(String(12))  # NORMAL/STRONG/EXCEPTIONAL
    sectors: Mapped[list] = mapped_column(JSON, default=list)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    impact: Mapped[float]  # signed per-cycle return contribution
    duration: Mapped[int]
    remaining: Mapped[int]
    start_cycle: Mapped[int]
    cooldown_until: Mapped[int]
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE/EXPIRED/STOPPED
    announced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only admin audit trail."""
    __tablename__ = "admin_audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanyUpgrade(Base):
    __tablename__ = "company_upgrades"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    cost: Mapped[Decimal] = mapped_column(MONEY)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Ipo(Base):
    __tablename__ = "ipo"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    price: Mapped[Decimal] = mapped_column(PRICE)
    public_shares: Mapped[int] = mapped_column(BigInteger)
    min_sub: Mapped[int] = mapped_column(BigInteger, default=1)
    max_sub: Mapped[int] = mapped_column(BigInteger)
    duration_hours: Mapped[int] = mapped_column(default=24)
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)  # PENDING/OPEN/CLOSED/FAILED/REJECTED
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_allocated: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IpoSubscription(Base):
    __tablename__ = "ipo_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    ipo_id: Mapped[int] = mapped_column(ForeignKey("ipo.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    shares: Mapped[int] = mapped_column(BigInteger)
    paid: Mapped[Decimal] = mapped_column(MONEY)
    allocated: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("ipo_id", "user_id"),)


class Dividend(Base):
    __tablename__ = "dividends"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    per_share: Mapped[Decimal] = mapped_column(PRICE)
    reserved: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(12), default="ANNOUNCED", index=True)  # ANNOUNCED/RECORDED/PAID
    record_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pay_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DividendPayment(Base):
    __tablename__ = "dividend_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    dividend_id: Mapped[int] = mapped_column(ForeignKey("dividends.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    shares: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("dividend_id", "user_id"),)


class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    principal: Mapped[Decimal] = mapped_column(MONEY)
    total_due: Mapped[Decimal] = mapped_column(MONEY)  # principal + interest (+ late fee)
    outstanding: Mapped[Decimal] = mapped_column(MONEY)
    rate_per_day: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    term_days: Mapped[int]
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    late_fee_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE/REPAID/DEFAULTED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
