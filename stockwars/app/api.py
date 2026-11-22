"""FastAPI backend for the Mini App. Every request is authenticated via Telegram initData HMAC."""
import hashlib, hmac, json, time
from urllib.parse import parse_qsl
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import select
from .config import settings
from .db import Session
from .models import Company, MarketState, PriceHistory, User
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from .models import MarketEvent, ShareOwnership, Wallet
from .services import trading, wallet

app = FastAPI(title="Stock Wars API")


def auth(x_init_data: str = Header(...)) -> int:
    data = dict(parse_qsl(x_init_data, keep_blank_values=True))
    got = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
        raise HTTPException(401, "bad initData")
    if time.time() - int(data.get("auth_date", 0)) > 86400:
        raise HTTPException(401, "expired")
    return json.loads(data["user"])["id"]


@app.get("/api/market")
async def market(uid: int = Depends(auth)):
    async with Session() as s:
        st = await s.get(MarketState, 1)
        cs = (await s.execute(select(Company).where(Company.listing == "LISTED"))).scalars().all()
    return {"status": st.status, "cycle": st.cycle_no, "index": str(st.index_value), "fee_pct": str(settings.trading_fee_pct),
            "stocks": [dict(ticker=c.ticker, name=c.name, price=str(c.price), prev=str(c.prev_close), risk=c.risk_level) for c in cs]}


@app.get("/api/me")
async def me(uid: int = Depends(auth)):
    async with Session() as s:
        u = await s.get(User, uid)
        if not u or u.status != "ACTIVE": raise HTTPException(403, "not approved")
        p = await trading.portfolio(s, uid)
    return {k: (str(v) if not isinstance(v, list) else [{a: str(b) for a, b in h.items()} for h in v]) for k, v in p.items()}


@app.get("/api/stock/{ticker}/history")
async def hist(ticker: str, uid: int = Depends(auth)):
    async with Session() as s:
        c = (await s.execute(select(Company).where(Company.ticker == ticker.upper()))).scalar_one_or_none()
        if not c: raise HTTPException(404)
        rows = (await s.execute(select(PriceHistory).where(PriceHistory.company_id == c.id)
                                .order_by(PriceHistory.id.desc()).limit(300))).scalars().all()
    return [dict(t=x.created_at.isoformat(), price=str(x.price), cycle=x.cycle_no) for x in reversed(rows)]


class TradeIn(BaseModel):
    ticker: str
    side: str
    qty: int
    key: str


@app.post("/api/trade")
async def trade(b: TradeIn, uid: int = Depends(auth)):
    try:
        async with Session() as s, s.begin():
            t = await trading.execute(s, uid, b.ticker, b.side.upper(), b.qty, f"mini:{uid}:{b.key[:64]}")
        return {"ok": True, "price": str(t.price), "fee": str(t.fee)}
    except (wallet.DuplicateOperation, IntegrityError):
        raise HTTPException(409, "Duplicate order ignored")
    except (trading.TradeError, wallet.WalletError) as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/news")
async def news(uid: int = Depends(auth)):
    async with Session() as s:
        rows = (await s.execute(select(MarketEvent).order_by(desc(MarketEvent.id)).limit(30))).scalars().all()
    return [dict(id=x.id, headline=x.headline, description=x.description, type=x.event_type, severity=x.severity,
                 impact=x.impact, remaining=x.remaining, duration=x.duration, status=x.status,
                 scope=x.sectors or x.tickers) for x in rows]


@app.get("/api/leaderboard")
async def leaderboard(uid: int = Depends(auth)):
    async with Session() as s:
        sv = (select(ShareOwnership.user_id, func.sum(ShareOwnership.quantity * Company.price).label("sv"))
              .join(Company, Company.id == ShareOwnership.company_id).group_by(ShareOwnership.user_id).subquery())
        from .models import Loan
        dv = select(Loan.user_id, func.sum(Loan.outstanding).label('d')).where(Loan.status.in_(['ACTIVE', 'DEFAULTED'])).group_by(Loan.user_id).subquery()
        q = (select(User, (Wallet.available + func.coalesce(sv.c.sv, 0) - func.coalesce(dv.c.d, 0)).label("nw"))
             .join(Wallet, Wallet.user_id == User.id).outerjoin(sv, sv.c.user_id == User.id).outerjoin(dv, dv.c.user_id == User.id)
             .where(User.status == "ACTIVE").order_by(desc("nw")).limit(50))
        rows = (await s.execute(q)).all()
    return [dict(rank=i, name=u.first_name, id=u.id, net_worth=str(nw), me=u.id == uid) for i, (u, nw) in enumerate(rows, 1)]



from decimal import Decimal
from .models import Ipo, IpoSubscription, Sector
from .services import company as co


@app.get("/health")
async def health():
    return {"ok": True}


async def _guard(fn):
    try:
        return await fn()
    except (wallet.DuplicateOperation, IntegrityError):
        raise HTTPException(409, "Duplicate request ignored")
    except (co.GameError, trading.TradeError, wallet.WalletError) as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/sectors")
async def sectors(uid: int = Depends(auth)):
    async with Session() as s:
        rows = (await s.execute(select(Sector).order_by(Sector.name))).scalars().all()
    return {"sectors": [dict(id=x.id, name=x.name) for x in rows],
            "rules": dict(company_fee=str(settings.company_fee), min_capital=str(settings.min_capital), ipo_fee=str(settings.ipo_fee),
                          ipo_min_age_hours=settings.ipo_min_age_hours, ipo_min_reputation=settings.ipo_min_reputation,
                          ipo_max_public_pct=settings.ipo_max_public_pct),
            "upgrades": [dict(key=k, name=v[0], cost=v[1], cooldown_h=v[2], rep=v[3], growth=v[4], risk=v[5]) for k, v in co.UPGRADES.items()]}


@app.get("/api/business")
async def business(uid: int = Depends(auth)):
    async with Session() as s:
        cs = (await s.execute(select(Company).where(Company.owner_id == uid).order_by(Company.id))).scalars().all()
        out = []
        for c in cs:
            held = (await s.execute(select(ShareOwnership.quantity).where(ShareOwnership.company_id == c.id, ShareOwnership.user_id == uid))).scalar() or 0
            ipo = (await s.execute(select(Ipo).where(Ipo.company_id == c.id).order_by(Ipo.id.desc()).limit(1))).scalar_one_or_none()
            out.append(dict(id=c.id, name=c.name, ticker=c.ticker, price=str(c.price), total_shares=c.total_shares, founder_shares=held,
                            reputation=c.reputation, growth=round(c.growth_rate, 2), cash=str(c.cash), listing=c.listing, status=c.status,
                            valuation=str(c.price * c.total_shares), age_h=int((datetime.now(timezone.utc) - c.created_at.replace(tzinfo=timezone.utc)).total_seconds() // 3600),
                            ipo=ipo and dict(id=ipo.id, status=ipo.status)))
    return out


class CreateIn(BaseModel):
    name: str
    ticker: str
    sector_id: int
    description: str = ""
    capital: Decimal
    total_shares: int
    key: str


@app.post("/api/company/create")
async def create_company(b: CreateIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            c = await co.create_company(s, uid, b.name, b.ticker, b.sector_id, b.description, b.capital, b.total_shares, f"mini:{uid}:{b.key[:64]}")
            return {"id": c.id, "ticker": c.ticker}
    return await _guard(go)


class UpIn(BaseModel):
    kind: str
    key: str


@app.post("/api/company/{cid}/upgrade")
async def upgrade(cid: int, b: UpIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            return await co.upgrade_company(s, uid, cid, b.kind, f"mini:{uid}:{b.key[:64]}")
    return await _guard(go)


class IpoIn(BaseModel):
    public_shares: int
    price: Decimal
    duration_hours: int = 24
    min_sub: int = 1
    max_sub: int | None = None
    key: str


@app.post("/api/company/{cid}/ipo")
async def launch(cid: int, b: IpoIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            i = await co.launch_ipo(s, uid, cid, b.public_shares, b.price, b.duration_hours, b.min_sub, b.max_sub, f"mini:{uid}:{b.key[:64]}")
            return {"id": i.id, "status": i.status}
    return await _guard(go)


@app.get("/api/ipos")
async def ipos(uid: int = Depends(auth)):
    async with Session() as s:
        rows = (await s.execute(select(Ipo, Company).join(Company, Company.id == Ipo.company_id)
                                .where(Ipo.status != "REJECTED").order_by(Ipo.id.desc()).limit(30))).all()
        subs = {x.ipo_id: x for x in (await s.execute(select(IpoSubscription).where(IpoSubscription.user_id == uid))).scalars()}
    return [dict(id=i.id, ticker=c.ticker, name=c.name, status=i.status, price=str(i.price), public_shares=i.public_shares, min_sub=i.min_sub,
                 max_sub=i.max_sub, closes_at=i.closes_at and i.closes_at.isoformat(), allocated=i.total_allocated, mine=c.owner_id == uid,
                 my_sub=subs[i.id].shares if i.id in subs else None, my_alloc=subs[i.id].allocated if i.id in subs else None) for i, c in rows]


class SubIn(BaseModel):
    shares: int
    key: str


@app.post("/api/ipo/{iid}/subscribe")
async def subscribe(iid: int, b: SubIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            x = await co.subscribe(s, uid, iid, b.shares, f"mini:{uid}:{b.key[:64]}")
            return {"ok": True, "paid": str(x.paid)}
    return await _guard(go)


from .models import Dividend, DividendPayment
from .services import finance as fin


@app.get("/api/loan")
async def loan(uid: int = Depends(auth)):
    async with Session() as s:
        return await fin.loan_status(s, uid)


class LoanIn(BaseModel):
    amount: Decimal
    days: int = 7
    key: str


@app.post("/api/loan/take")
async def loan_take(b: LoanIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            l = await fin.take_loan(s, uid, b.amount, b.days, f"mini:{uid}:{b.key[:64]}")
            return {"id": l.id, "total_due": str(l.total_due)}
    return await _guard(go)


@app.post("/api/loan/repay")
async def loan_repay(b: LoanIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            l = await fin.repay(s, uid, b.amount, f"mini:{uid}:{b.key[:64]}")
            return {"outstanding": str(l.outstanding), "status": l.status}
    return await _guard(go)


class DivIn(BaseModel):
    per_share: Decimal
    key: str = ""


@app.post("/api/company/{cid}/dividend")
async def dividend(cid: int, b: DivIn, uid: int = Depends(auth)):
    async def go():
        async with Session() as s, s.begin():
            d = await fin.announce_dividend(s, uid, cid, b.per_share)
            return {"id": d.id, "total": str(d.reserved), "pay_at": d.pay_at.isoformat()}
    return await _guard(go)


@app.get("/api/dividends")
async def dividends(uid: int = Depends(auth)):
    async with Session() as s:
        rec = (await s.execute(select(DividendPayment, Dividend, Company).join(Dividend, Dividend.id == DividendPayment.dividend_id)
                               .join(Company, Company.id == Dividend.company_id).where(DividendPayment.user_id == uid)
                               .order_by(DividendPayment.id.desc()).limit(20))).all()
        ann = (await s.execute(select(Dividend, Company).join(Company, Company.id == Dividend.company_id)
                               .where(Dividend.status != "PAID").order_by(Dividend.id.desc()).limit(10))).all()
    return {"received": [dict(ticker=c.ticker, shares=p.shares, amount=str(p.amount), paid=p.paid) for p, d, c in rec],
            "upcoming": [dict(ticker=c.ticker, per_share=str(d.per_share), record_at=d.record_at.isoformat(), pay_at=d.pay_at.isoformat(), status=d.status) for d, c in ann]}


import os
from datetime import datetime, timezone
from fastapi.staticfiles import StaticFiles
if os.path.isdir("webapp/dist"):
    app.mount("/", StaticFiles(directory="webapp/dist", html=True), name="web")
