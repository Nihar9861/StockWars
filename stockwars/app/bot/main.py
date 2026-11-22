import asyncio, html, logging
from decimal import Decimal, InvalidOperation
from aiogram import Bot, Dispatcher, F, BaseMiddleware, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..db import Session, engine
from ..models import (AuditLog, Base, Company, MarketEvent, MarketState, Sector, ShareOwnership, Trade, User, Wallet,
                      WalletTransaction)
from ..services import finance as fin, company as co, market, players, trading, wallet
from ..models import Ipo
from aiogram.types import MenuButtonWebApp, WebAppInfo
from ..services.events import TEMPLATES
from ..services.seed import seed

log = logging.getLogger("stockwars")
r = Router()
redis = Redis.from_url(settings.redis_url)


def inr(x) -> str:
    x = Decimal(x).quantize(Decimal("0.01"))
    i, d = f"{abs(x):.2f}".split(".")
    if len(i) > 3:
        head, tail, groups = i[:-3], i[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:]); head = head[:-2]
        if head: groups.insert(0, head)
        i = ",".join(groups + [tail])
    return f"{'-' if x < 0 else ''}₹{i}.{d}"


def e(x) -> str:
    return html.escape(str(x))


class RateLimit(BaseMiddleware):  # 5 updates / 3s per user, Redis-backed (works across instances)
    async def __call__(self, handler, event, data):
        u = getattr(event, "from_user", None)
        if u:
            k = f"rl:{u.id}"
            n = await redis.incr(k)
            if n == 1:
                await redis.expire(k, 3)
            if n > 5:
                return
        return await handler(event, data)


async def need_admin(s, m: Message, level="ADMIN"):
    u = await s.get(User, m.from_user.id)
    if not players.has_role(u, level):
        return None  # silent for non-admins: never expose admin surface
    return u


async def need_player(s, m: Message):
    u = await players.get_or_create(s, m.from_user)
    if u.status != "ACTIVE":
        await m.answer(f"Account status: <b>{u.status}</b>. Use /register and wait for approval." if u.status == "PENDING"
                       else f"Account status: <b>{u.status}</b>.")
        return None
    return u


# ---------- registration ----------
@r.message(Command("start", "register"))
async def start(m: Message):
    async with Session() as s, s.begin():
        u = await players.get_or_create(s, m.from_user)
        txt = {"PENDING": "Application received. An admin will review it shortly.",
               "ACTIVE": "Welcome back! /market /portfolio /stocks /news /leaderboard",
               "REJECTED": "Your application was rejected.", "SUSPENDED": "Account suspended.",
               "BANNED": "Account banned."}[u.status]
    await m.answer(f"📈 <b>STOCK WARS</b>\n{txt}")


@r.message(Command("profile"))
async def profile(m: Message):
    async with Session() as s, s.begin():
        u = await need_player(s, m)
        if not u: return
        p = await trading.portfolio(s, u.id)
    await m.answer(f"<b>{e(u.first_name)}</b> — {u.rank}\nCash: {inr(p['cash'])}\nStocks: {inr(p['market_value'])}\n"
                   f"Net worth: <b>{inr(p['net_worth'])}</b>")


# ---------- admin: players ----------
@r.message(Command("pending"))
async def pending(m: Message):
    async with Session() as s:
        if not await need_admin(s, m, "MODERATOR"): return
        rows = (await s.execute(select(User).where(User.status == "PENDING").order_by(User.created_at).limit(30))).scalars().all()
    await m.answer("\n".join(f"{u.id} @{u.username} {e(u.first_name)}" for u in rows) or "No pending players.")


async def _set_status(m: Message, cmd: CommandObject, new: str, action: str, need="ADMIN", only_from=None):
    async with Session() as s, s.begin():
        adm = await need_admin(s, m, need)
        if not adm: return
        if not cmd.args: return await m.answer(f"Usage: /{action.lower()} <id|@username>")
        u = await players.find_user(s, cmd.args.split()[0])
        if not u: return await m.answer("Player not found.")
        if only_from and u.status not in only_from: return await m.answer(f"Player is {u.status}.")
        if u.role == "OWNER": return await m.answer("Cannot modify owner.")
        u.status = new
        if new == "ACTIVE":
            await players.ensure_wallet(s, u)
        await players.audit(s, adm.id, action, str(u.id), new_status=new)
        uid = u.id
    await m.answer(f"{uid} → {new}")
    try:
        await m.bot.send_message(uid, f"Your account status is now <b>{new}</b>.")
    except Exception:
        pass


@r.message(Command("approve"))
async def approve(m: Message, command: CommandObject): await _set_status(m, command, "ACTIVE", "APPROVE", only_from={"PENDING"})
@r.message(Command("reject"))
async def reject(m: Message, command: CommandObject): await _set_status(m, command, "REJECTED", "REJECT", only_from={"PENDING"})
@r.message(Command("suspend"))
async def suspend(m: Message, command: CommandObject): await _set_status(m, command, "SUSPENDED", "SUSPEND")
@r.message(Command("unsuspend"))
async def unsuspend(m: Message, command: CommandObject): await _set_status(m, command, "ACTIVE", "UNSUSPEND", only_from={"SUSPENDED"})
@r.message(Command("ban"))
async def ban(m: Message, command: CommandObject): await _set_status(m, command, "BANNED", "BAN", "SUPER_ADMIN")
@r.message(Command("unban"))
async def unban(m: Message, command: CommandObject): await _set_status(m, command, "ACTIVE", "UNBAN", "SUPER_ADMIN", {"BANNED"})


@r.message(Command("playerinfo"))
async def playerinfo(m: Message, command: CommandObject):
    async with Session() as s:
        if not await need_admin(s, m, "MODERATOR") or not command.args: return
        u = await players.find_user(s, command.args.split()[0])
        if not u: return await m.answer("Not found.")
        p = await trading.portfolio(s, u.id) if await s.get(Wallet, u.id) else None
    await m.answer(f"{u.id} @{u.username} {u.status} {u.role}\n" + (f"Net worth {inr(p['net_worth'])}" if p else "No wallet"))


@r.message(Command("addcash", "removecash"))
async def adjust(m: Message, command: CommandObject):
    async with Session() as s, s.begin():
        adm = await need_admin(s, m, "SUPER_ADMIN")
        if not adm: return
        try:
            ref, amt, *why = command.args.split()
            amt = Decimal(amt)
            assert amt > 0
        except Exception:
            return await m.answer(f"Usage: /{command.command} <id|@user> <amount> [reason]")
        u = await players.find_user(s, ref)
        if not u: return await m.answer("Player not found.")
        sign = 1 if command.command == "addcash" else -1
        try:
            tx = await wallet.apply(s, u.id, "ADMIN_ADJUSTMENT", sign * amt, " ".join(why) or "admin adjustment")
        except wallet.WalletError as ex:
            return await m.answer(f"Failed: {e(ex)}")
        await players.audit(s, adm.id, command.command.upper(), str(u.id), amount=str(sign * amt), tx=str(tx.id))
    await m.answer(f"Done. New balance {inr(tx.balance_after)}")


# ---------- market ----------
@r.message(Command("market", "ticker"))
async def market_cmd(m: Message):
    async with Session() as s:
        st = await s.get(MarketState, 1)
        cs = (await s.execute(select(Company).where(Company.listing == "LISTED"))).scalars().all()
        secs = {x.id: x.name for x in (await s.execute(select(Sector))).scalars()}
        evs = (await s.execute(select(MarketEvent).where(MarketEvent.status == "ACTIVE"))).scalars().all()
    chg = lambda c: (c.price / c.prev_close - 1) * 100
    top = sorted(cs, key=chg, reverse=True)
    line = lambda c: f"{c.ticker} {c.price:.2f} ({chg(c):+.2f}%)"
    act = sorted(cs, key=lambda c: c.volume, reverse=True)[:3]
    await m.answer(f"📊 <b>MARKET: {st.status}</b>  Cycle {st.cycle_no}\nSTOCK WARS INDEX: <b>{st.index_value}</b>\n\n"
                   f"🟢 Gainers\n" + "\n".join(line(c) for c in top[:5]) + "\n\n🔴 Losers\n" +
                   "\n".join(line(c) for c in top[-5:][::-1]) + "\n\n🔥 Most active\n" +
                   "\n".join(f"{c.ticker} vol {c.volume}" for c in act) +
                   (f"\n\n⚡ Active events: {', '.join(e_.headline for e_ in evs)}" if evs else ""))


@r.message(Command("stocks"))
async def stocks(m: Message, command: CommandObject):
    page = int(command.args) if command.args and command.args.isdigit() else 1
    async with Session() as s:
        cs = (await s.execute(select(Company).where(Company.listing == "LISTED").order_by(Company.ticker)
                              .offset((page - 1) * 15).limit(15))).scalars().all()
    await m.answer("\n".join(f"<code>{c.ticker:5}</code> {c.price:>9.2f} ({(c.price / c.prev_close - 1) * 100:+.2f}%) {e(c.name)}"
                             for c in cs) + f"\n\nPage {page} — /stocks {page + 1}" if cs else "No more stocks.")


@r.message(Command("stock"))
async def stock(m: Message, command: CommandObject):
    if not command.args: return await m.answer("Usage: /stock TICKER")
    async with Session() as s:
        c = (await s.execute(select(Company).where(Company.ticker == command.args.upper().strip()))).scalar_one_or_none()
        if not c: return await m.answer("Unknown ticker.")
        sec = await s.get(Sector, c.sector_id)
    await m.answer(f"<b>{e(c.name)}</b> ({c.ticker}) — {sec.name}\nPrice {c.price:.2f} ({(c.price / c.prev_close - 1) * 100:+.2f}%)\n"
                   f"Mkt cap {inr(c.price * c.total_shares)}\nRevenue {inr(c.revenue)} | Profit {inr(c.profit)} | Debt {inr(c.debt)}\n"
                   f"Reputation {c.reputation} | Risk {c.risk_level} | Status {c.status}\nCEO {e(c.ceo)}")


async def _confirm(m: Message, command: CommandObject, side: str):
    try:
        ticker, q = command.args.split(); qty = int(q); assert qty > 0
    except Exception:
        return await m.answer(f"Usage: /{side.lower()} TICKER QUANTITY")
    async with Session() as s:
        if not await need_player(s, m): return
        c = (await s.execute(select(Company).where(Company.ticker == ticker.upper()))).scalar_one_or_none()
    if not c: return await m.answer("Unknown ticker.")
    value, fee = trading.estimate(c.price, qty)
    total = value + fee if side == "BUY" else value - fee
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Confirm", callback_data=f"t:{side}:{c.ticker}:{qty}"),
                                                InlineKeyboardButton(text="✖ Cancel", callback_data="t:x")]])
    await m.answer(f"<b>{side} {qty} {c.ticker}</b> @ {c.price:.2f}\nValue {inr(value)}\nFee {inr(fee)}\n"
                   f"{'Total cost' if side == 'BUY' else 'You receive'}: <b>{inr(total)}</b>", reply_markup=kb)


@r.message(Command("buy"))
async def buy(m: Message, command: CommandObject): await _confirm(m, command, "BUY")
@r.message(Command("sell"))
async def sell(m: Message, command: CommandObject): await _confirm(m, command, "SELL")


@r.callback_query(F.data == "t:x")
async def cancel(cq: CallbackQuery):
    await cq.message.edit_text("Cancelled."); await cq.answer()


@r.callback_query(F.data.startswith("t:"))
async def do_trade(cq: CallbackQuery):
    _, side, ticker, qty = cq.data.split(":")
    key = f"tg:{cq.from_user.id}:{cq.message.chat.id}:{cq.message.message_id}"  # one confirm message = one order
    try:
        async with Session() as s, s.begin():
            t = await trading.execute(s, cq.from_user.id, ticker, side, int(qty), key)
        msg = f"✅ {side} {t.quantity} {ticker} @ {t.price:.2f} | fee {inr(t.fee)}"
    except (trading.TradeError, wallet.WalletError, IntegrityError) as ex:
        msg = "⚠️ Duplicate order ignored." if isinstance(ex, (wallet.DuplicateOperation, IntegrityError)) else f"❌ {e(ex)}"
    await cq.message.edit_text(msg); await cq.answer()


@r.message(Command("portfolio", "holdings"))
async def portfolio(m: Message):
    async with Session() as s, s.begin():
        u = await need_player(s, m)
        if not u: return
        p = await trading.portfolio(s, u.id)
    hl = "\n".join(f"{h['ticker']} ×{h['qty']} avg {h['avg']:.2f} now {h['price']:.2f} P/L {inr(h['pnl'])} ({h['pnl_pct']:+.1f}%)"
                   for h in p["holdings"]) or "No holdings yet."
    await m.answer(f"💼 <b>Portfolio</b>\nCash {inr(p['cash'])}\nInvested {inr(p['invested'])}\nMarket value {inr(p['market_value'])}\n"
                   f"Unrealized {inr(p['unrealized'])} | Realized {inr(p['realized'])}\n<b>Net worth {inr(p['net_worth'])}</b>\n\n{hl}")


@r.message(Command("history"))
async def history(m: Message):
    async with Session() as s:
        u = await need_player(s, m)
        if not u: return
        rows = (await s.execute(select(WalletTransaction).where(WalletTransaction.user_id == u.id)
                                .order_by(desc(WalletTransaction.created_at)).limit(15))).scalars().all()
    await m.answer("\n".join(f"{x.created_at:%d %b %H:%M} {x.category} {inr(x.amount)}" for x in rows) or "No transactions.")


@r.message(Command("news", "marketnews", "events"))
async def news(m: Message):
    async with Session() as s:
        rows = (await s.execute(select(MarketEvent).order_by(desc(MarketEvent.id)).limit(8))).scalars().all()
    await m.answer("\n\n".join(f"<b>{e(x.headline)}</b> [{x.status}]\n{e(x.description)}\nImpact {x.impact * 100:+.2f}%/cycle · "
                               f"{x.remaining}/{x.duration} cycles" for x in rows) or "No news yet.")


@r.message(Command("leaderboard", "rank", "wealth"))
async def leaderboard(m: Message):
    async with Session() as s:
        stock_val = (select(ShareOwnership.user_id, func.sum(ShareOwnership.quantity * Company.price).label("sv"))
                     .join(Company, Company.id == ShareOwnership.company_id).group_by(ShareOwnership.user_id).subquery())
        from ..models import Loan
        dv = select(Loan.user_id, func.sum(Loan.outstanding).label('d')).where(Loan.status.in_(['ACTIVE', 'DEFAULTED'])).group_by(Loan.user_id).subquery()
        q = (select(User, (Wallet.available + func.coalesce(stock_val.c.sv, 0) - func.coalesce(dv.c.d, 0)).label("nw"))
             .join(Wallet, Wallet.user_id == User.id).outerjoin(stock_val, stock_val.c.user_id == User.id).outerjoin(dv, dv.c.user_id == User.id)
             .where(User.status == "ACTIVE").order_by(desc("nw")).limit(10))
        rows = (await s.execute(q)).all()
    await m.answer("🏆 <b>Richest players</b>\n" + "\n".join(f"{i}. {e(u.first_name)} — {inr(nw)}" for i, (u, nw) in enumerate(rows, 1)))


# ---------- admin: market ----------
async def _market_ctl(m: Message, halt: bool):
    async with Session() as s, s.begin():
        adm = await need_admin(s, m, "ADMIN")
        if not adm: return
        st = (await s.execute(select(MarketState).where(MarketState.id == 1).with_for_update())).scalar_one()
        st.halted = halt
        await market.refresh_status(s, st)
        await players.audit(s, adm.id, "MARKET_PAUSE" if halt else "MARKET_RESUME")
    await m.answer(f"Market: {st.status}")


@r.message(Command("marketpause"))
async def mpause(m: Message): await _market_ctl(m, True)
@r.message(Command("marketresume"))
async def mresume(m: Message): await _market_ctl(m, False)


@r.message(Command("forceevent"))
async def forceevent(m: Message, command: CommandObject):
    async with Session() as s, s.begin():
        adm = await need_admin(s, m, "ADMIN")
        if not adm: return
        ev = await market.force_event(s, (command.args or "").strip())
        if not ev:
            return await m.answer("Keys: " + ", ".join(t["key"] for t in TEMPLATES))
        await players.audit(s, adm.id, "FORCE_EVENT", ev.template_key)
    await m.answer(f"Event started: {e(ev.headline)}")


@r.message(Command("stop_event"))
async def stop_event(m: Message, command: CommandObject):
    async with Session() as s, s.begin():
        adm = await need_admin(s, m, "ADMIN")
        if not adm or not (command.args or "").isdigit(): return
        ev = await s.get(MarketEvent, int(command.args))
        if ev: ev.status = "STOPPED"
        await players.audit(s, adm.id, "STOP_EVENT", str(command.args))
    await m.answer("Stopped.")


@r.message(Command("audit"))
async def audit_cmd(m: Message):
    async with Session() as s:
        if not await need_admin(s, m, "SUPER_ADMIN"): return
        rows = (await s.execute(select(AuditLog).order_by(desc(AuditLog.id)).limit(15))).scalars().all()
    await m.answer("\n".join(f"{x.created_at:%d %b %H:%M} {x.admin_id} {x.action} {x.target}" for x in rows) or "Empty.")


# ---------- companies / IPO ----------
def _app_kb(label="Open Stock Wars"):
    if not settings.webapp_url: return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=settings.webapp_url))]])


@r.message(Command("createcompany", "mycompany", "ipos", "company"))
async def company_cmds(m: Message):
    async with Session() as s:
        cs = (await s.execute(select(Company).where(Company.owner_id == m.from_user.id))).scalars().all()
        ipos_ = (await s.execute(select(Ipo, Company).join(Company, Company.id == Ipo.company_id).where(Ipo.status == "OPEN"))).all()
    txt = "\n".join(f"<b>{c.ticker}</b> {e(c.name)} — {c.listing}, rep {c.reputation}, val {inr(c.price * c.total_shares)}" for c in cs) or "No companies yet."
    txt += "\n\n<b>Open IPOs</b>\n" + ("\n".join(f"{c.ticker} @ {i.price:.2f} · {i.public_shares} shares" for i, c in ipos_) or "None")
    await m.answer(txt + "\n\nCreate companies, upgrade them and subscribe to IPOs in the Mini App.", reply_markup=_app_kb("Open Business"))


async def _ipo_decide(m: Message, command: CommandObject, approve: bool):
    async with Session() as s, s.begin():
        adm = await need_admin(s, m, "ADMIN")
        if not adm or not (command.args or "").isdigit(): return
        try:
            await co.decide_ipo(s, int(command.args), approve)
        except co.GameError as ex:
            return await m.answer(str(ex))
        await players.audit(s, adm.id, "APPROVE_IPO" if approve else "REJECT_IPO", command.args)
    await m.answer("Done.")


@r.message(Command("approveipo"))
async def approveipo(m: Message, command: CommandObject): await _ipo_decide(m, command, True)
@r.message(Command("rejectipo"))
async def rejectipo(m: Message, command: CommandObject): await _ipo_decide(m, command, False)


async def ipo_job(bot: Bot):
    async with Session() as s:
        ids = await co.due_ipo_ids(s)
    for i in ids:
        try:
            async with Session() as s, s.begin():
                res = await co.close_ipo(s, i)
            if not res: continue
            c, ipo = res["company"], res["ipo"]
            msg = (f"🎉 <b>IPO CLOSED — {c.ticker}</b>\nAllocated {res['allocated']} shares @ {inr(ipo.price)} to {res['subs']} investors. Raised {inr(res['raised'])}.\nNow listed!"
                   if ipo.status == "CLOSED" else f"IPO for {c.ticker} ended with no subscriptions.")
            for chat in {c.owner_id, settings.news_channel_id or None}:
                if chat:
                    try: await bot.send_message(chat, msg)
                    except Exception: pass
        except Exception:
            log.exception("ipo close failed %s", i)


# ---------- bank / dividends ----------
@r.message(Command("loan", "repay", "dividends"))
async def bank_cmds(m: Message, command: CommandObject):
    uid = m.from_user.id
    async with Session() as s, s.begin():
        u = await need_player(s, m)
        if not u: return
        if command.command == "repay":
            try:
                l = await fin.repay(s, uid, Decimal(command.args or "0"), f"tg:{uid}:{m.message_id}")
                return await m.answer(f"Repaid. Outstanding {inr(l.outstanding)}")
            except (co.GameError, wallet.WalletError, InvalidOperation) as ex:
                return await m.answer(f"❌ {e(ex) or 'Usage: /repay <amount>'}")
        if command.command == "dividends":
            from ..models import DividendPayment, Dividend
            rows = (await s.execute(select(DividendPayment, Company).join(Dividend, Dividend.id == DividendPayment.dividend_id)
                                    .join(Company, Company.id == Dividend.company_id).where(DividendPayment.user_id == uid)
                                    .order_by(DividendPayment.id.desc()).limit(10))).all()
            return await m.answer("💰 <b>Dividends</b>\n" + ("\n".join(f"{c.ticker} ×{p.shares} → {inr(p.amount)} {'✓' if p.paid else '⏳'}" for p, c in rows) or "None yet."))
        st = await fin.loan_status(s, uid)
    l = st["loan"]
    await m.answer(f"🏦 <b>Bank</b>\nCredit score {st['credit_score']}\nMax loan {inr(st['max_amount'])} · {Decimal(st['rate_per_day']) * 100}%/day\n"
                   + (f"Active loan: outstanding {inr(l['outstanding'])}, due {l['due_at'][:16]}" if l else "No active loan.")
                   + "\nBorrow in the Mini App · repay with /repay <amount>", reply_markup=_app_kb("Open Bank"))


async def finance_job(bot: Bot):
    if not await redis.set("lock:finance", "1", nx=True, ex=50):
        return
    try:
        async with Session() as s, s.begin():
            divs = await fin.process_dividends(s)
            loans = await fin.process_loans(s)
        for d in divs:
            txt = f"💰 <b>DIVIDEND PAID — {d['ticker']}</b>\n{inr(d['per_share'])}/share · total {inr(d['total'])} to {d['holders']} holders"
            for chat in {d["owner"], settings.news_channel_id or None}:
                if chat:
                    try: await bot.send_message(chat, txt)
                    except Exception: pass
        for x in loans:
            msg = (f"⚠️ Loan overdue — late fee {inr(x['fee'])} added. Repay with /repay." if x["kind"] == "LATE"
                   else f"❌ Loan defaulted. Remaining debt {inr(x['remaining'])}. Credit score hit; new loans blocked until cleared.")
            try: await bot.send_message(x["user"], msg)
            except Exception: pass
    except Exception:
        log.exception("finance job failed")


# ---------- scheduler ----------
async def cycle_job(bot: Bot):
    if not await redis.set("lock:cycle", "1", nx=True, ex=max(settings.cycle_minutes * 60 - 5, 30)):
        return  # another instance is running this cycle
    try:
        async with Session() as s, s.begin():
            res = await market.run_cycle(s)
        if res["ran"] and settings.news_channel_id:
            for head, desc_, sev, imp, dur, secs, ticks in res["new_events"]:
                await bot.send_message(settings.news_channel_id,
                                       f"🚨 <b>MARKET ALERT</b>\n<b>{e(head)}</b>\n{e(desc_)}\nSeverity: {sev}\n"
                                       f"Affected: {e(', '.join(secs or ticks))}\nImpact: {imp * 100:+.2f}%/cycle · {dur} cycles")
            await bot.send_message(settings.news_channel_id, f"📊 Cycle {res['cycle']} — INDEX {res['index']}")
    except Exception:
        log.exception("cycle failed")


async def main():
    logging.basicConfig(level=logging.INFO)
    if settings.auto_create_tables:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
    async with Session() as s, s.begin():
        await seed(s)
        st = await s.get(MarketState, 1)
        await market.refresh_status(s, st)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.message.outer_middleware(RateLimit())
    dp.callback_query.outer_middleware(RateLimit())
    dp.include_router(r)
    sch = AsyncIOScheduler(timezone="UTC")
    sch.add_job(cycle_job, "interval", minutes=settings.cycle_minutes, args=[bot], max_instances=1, coalesce=True)
    sch.add_job(finance_job, "interval", minutes=1, args=[bot], max_instances=1, coalesce=True)
    sch.add_job(ipo_job, "interval", minutes=1, args=[bot], max_instances=1, coalesce=True)
    sch.start()
    if settings.webapp_url:
        try: await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Stock Wars", web_app=WebAppInfo(url=settings.webapp_url)))
        except Exception: log.exception("menu button")
    await dp.start_polling(bot, handle_signals=False)


if __name__ == "__main__":
    asyncio.run(main())
