import { useState } from "react";
import { useLoad } from "./hooks";
import Business from "./Business";
import { api, inr, pct, haptic } from "./api";

type Stock = { ticker: string; name: string; price: string; prev: string; risk: string };
type Mkt = { status: string; cycle: number; index: string; fee_pct: string; stocks: Stock[] };
type Holding = { ticker: string; qty: string; avg: string; price: string; value: string; pnl: string; pnl_pct: string };
type Me = { debt: string; cash: string; invested: string; market_value: string; unrealized: string; realized: string; net_worth: string; holdings: Holding[] };
type News = { id: number; headline: string; description: string; severity: string; impact: number; remaining: number; duration: number; status: string; scope: string[] };
type Row = { rank: number; name: string; net_worth: string; me: boolean };
type Pt = { price: string; cycle: number };

const card = "bg-card border border-line rounded-2xl p-3";
const col = (n: number) => (n >= 0 ? "text-up" : "text-down");
const Chg = ({ v }: { v: number }) => <span className={col(v)}>{v >= 0 ? "▲" : "▼"} {Math.abs(v).toFixed(2)}%</span>;

function Spark({ pts }: { pts: Pt[] }) {
  if (pts.length < 2) return <div className="h-40 grid place-items-center text-sm text-gray-500">Waiting for market cycles…</div>;
  const v = pts.map((p) => Number(p.price)), mn = Math.min(...v), mx = Math.max(...v), r = mx - mn || 1;
  const d = v.map((y, i) => `${(i / (v.length - 1)) * 300},${96 - ((y - mn) / r) * 88}`).join(" ");
  const up = v[v.length - 1] >= v[0];
  return (
    <svg viewBox="0 0 300 100" className="w-full h-40">
      <polyline fill="none" stroke={up ? "#22c55e" : "#ef4444"} strokeWidth="2" points={d} />
      <text x="2" y="10" fontSize="8" fill="#6b7280">{mx.toFixed(2)}</text>
      <text x="2" y="98" fontSize="8" fill="#6b7280">{mn.toFixed(2)}</text>
    </svg>
  );
}

const Loading = ({ err }: { err: string }) => <div className="p-8 text-center text-gray-400">{err || "Loading…"}</div>;

function TradeSheet({ s, side, fee, held, onClose, onDone }: { s: Stock; side: "BUY" | "SELL"; fee: number; held: number; onClose: () => void; onDone: () => void }) {
  const [qty, setQty] = useState("1");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const q = Math.max(0, parseInt(qty) || 0), val = q * Number(s.price), f = val * fee;
  const go = async () => {
    setBusy(true); setMsg("");
    try { await api("/trade", { ticker: s.ticker, side, qty: q, key }); haptic(); onDone(); onClose(); }
    catch (e) { setMsg((e as Error).message); setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/70 flex items-end z-20" onClick={onClose}>
      <div className="bg-card w-full rounded-t-3xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="font-semibold">{side} {s.ticker} @ {inr(s.price)}</div>
        <input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} className="w-full bg-bg border border-line rounded-xl p-3 text-lg" />
        {side === "SELL" && <button className="text-acc text-sm" onClick={() => setQty(String(held))}>Max ({held})</button>}
        <div className="text-sm text-gray-400">Value {inr(val)} · Fee {inr(f)}<br /><b className="text-white">{side === "BUY" ? "Total" : "You receive"} {inr(side === "BUY" ? val + f : val - f)}</b></div>
        {msg && <div className="text-down text-sm">{msg}</div>}
        <button disabled={busy || q < 1} onClick={go} className={`w-full py-3 rounded-xl font-semibold disabled:opacity-40 ${side === "BUY" ? "bg-up" : "bg-down"}`}>{busy ? "Placing…" : `Confirm ${side}`}</button>
      </div>
    </div>
  );
}

function StockPage({ s, mkt, me, back, refresh }: { s: Stock; mkt: Mkt; me: Me | null; back: () => void; refresh: () => void }) {
  const { data: hist } = useLoad<Pt[]>(`/stock/${s.ticker}/history`);
  const [side, setSide] = useState<"BUY" | "SELL" | null>(null);
  const h = me?.holdings.find((x) => x.ticker === s.ticker);
  const open = mkt.status === "OPEN";
  return (
    <div className="space-y-3">
      <button onClick={back} className="text-acc">← Back</button>
      <div className={card}>
        <div className="text-sm text-gray-400">{s.name} · Risk {s.risk}</div>
        <div className="text-3xl font-bold">{inr(s.price)} <span className="text-base"><Chg v={pct(Number(s.price), Number(s.prev))} /></span></div>
        <Spark pts={hist ?? []} />
      </div>
      {h && <div className={card + " text-sm"}>You hold {h.qty} · avg {inr(h.avg)} · P/L <span className={col(Number(h.pnl))}>{inr(h.pnl)}</span></div>}
      {!open && <div className="text-center text-sm text-yellow-400">Market is {mkt.status} — trading disabled</div>}
      <div className="grid grid-cols-2 gap-3">
        <button disabled={!open} onClick={() => setSide("BUY")} className="bg-up py-3 rounded-xl font-semibold disabled:opacity-30">Buy</button>
        <button disabled={!open || !h} onClick={() => setSide("SELL")} className="bg-down py-3 rounded-xl font-semibold disabled:opacity-30">Sell</button>
      </div>
      {side && <TradeSheet s={s} side={side} fee={Number(mkt.fee_pct)} held={Number(h?.qty ?? 0)} onClose={() => setSide(null)} onDone={refresh} />}
    </div>
  );
}

const NewsItem = ({ n }: { n: News }) => (
  <div className={card}>
    <div className="flex justify-between text-xs text-gray-400"><span>{n.severity}</span><span>{n.status}</span></div>
    <div className="font-semibold">{n.headline}</div>
    <div className="text-sm text-gray-300">{n.description}</div>
    <div className="text-xs mt-1 text-gray-400">{n.scope.join(", ")} · <span className={col(n.impact)}>{(n.impact * 100).toFixed(2)}%/cycle</span> · {n.remaining}/{n.duration} cycles</div>
  </div>
);

export default function App() {
  const [tab, setTab] = useState("home");
  const [sel, setSel] = useState<Stock | null>(null);
  const [q, setQ] = useState("");
  const { data: mkt, err, reload: rm } = useLoad<Mkt>("/market");
  const { data: me, err: meErr, reload: rme } = useLoad<Me>("/me");
  const { data: news } = useLoad<News[]>("/news");
  const { data: board } = useLoad<Row[]>("/leaderboard");
  const refresh = () => { rm(); rme(); };
  if (meErr) return <div className="p-8 text-center">⏳ {meErr}<br /><span className="text-gray-400 text-sm">Register in the bot and wait for approval.</span></div>;
  if (!mkt || !me) return <Loading err={err} />;
  const mv = [...mkt.stocks].sort((a, b) => pct(Number(b.price), Number(b.prev)) - pct(Number(a.price), Number(a.prev)));
  const Row = ({ s }: { s: Stock }) => (
    <button onClick={() => setSel(s)} className={card + " w-full flex justify-between items-center text-left"}>
      <div><b>{s.ticker}</b><div className="text-xs text-gray-400">{s.name}</div></div>
      <div className="text-right"><div>{inr(s.price)}</div><div className="text-xs"><Chg v={pct(Number(s.price), Number(s.prev))} /></div></div>
    </button>
  );
  let body;
  if (sel) body = <StockPage s={mkt.stocks.find((x) => x.ticker === sel.ticker) ?? sel} mkt={mkt} me={me} back={() => setSel(null)} refresh={refresh} />;
  else if (tab === "home") body = (
    <div className="space-y-3">
      <div className={card}><div className="text-sm text-gray-400">Net worth</div><div className="text-3xl font-bold">{inr(me.net_worth)}</div>
        <div className="text-sm text-gray-400 mt-1">Cash {inr(me.cash)} · Stocks {inr(me.market_value)}{Number(me.debt) > 0 && <> · <span className="text-down">Debt {inr(me.debt)}</span></>}</div></div>
      <div className="grid grid-cols-2 gap-3">
        <div className={card}><div className="text-xs text-gray-400">STOCK WARS INDEX</div><b className="text-xl">{mkt.index}</b></div>
        <div className={card}><div className="text-xs text-gray-400">Market · Cycle {mkt.cycle}</div><b className={mkt.status === "OPEN" ? "text-up" : "text-yellow-400"}>{mkt.status}</b></div>
      </div>
      <div className="font-semibold">🟢 Top gainers</div>{mv.slice(0, 3).map((s) => <Row key={s.ticker} s={s} />)}
      <div className="font-semibold">🔴 Top losers</div>{mv.slice(-3).reverse().map((s) => <Row key={s.ticker} s={s} />)}
      <div className="font-semibold">📰 Latest news</div>{(news ?? []).slice(0, 2).map((n) => <NewsItem key={n.id} n={n} />)}
    </div>
  );
  else if (tab === "market") body = (
    <div className="space-y-2">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search ticker or name" className="w-full bg-card border border-line rounded-xl p-3" />
      {mkt.stocks.filter((s) => (s.ticker + s.name).toLowerCase().includes(q.toLowerCase())).map((s) => <Row key={s.ticker} s={s} />)}
    </div>
  );
  else if (tab === "portfolio") body = (
    <div className="space-y-2">
      <div className={card + " text-sm space-y-1"}>
        <div>Invested {inr(me.invested)} · Value {inr(me.market_value)}</div>
        <div>Unrealized <span className={col(Number(me.unrealized))}>{inr(me.unrealized)}</span> · Realized <span className={col(Number(me.realized))}>{inr(me.realized)}</span></div></div>
      {me.holdings.length === 0 && <div className="text-center text-gray-500 py-8">No holdings yet. Pick a stock in Market.</div>}
      {me.holdings.map((h) => (
        <button key={h.ticker} onClick={() => setSel(mkt.stocks.find((s) => s.ticker === h.ticker)!)} className={card + " w-full text-left"}>
          <div className="flex justify-between"><b>{h.ticker} ×{h.qty}</b><span>{inr(h.value)}</span></div>
          <div className="text-xs text-gray-400">avg {inr(h.avg)} · now {inr(h.price)} · <span className={col(Number(h.pnl))}>{inr(h.pnl)} ({Number(h.pnl_pct).toFixed(1)}%)</span></div>
        </button>))}
    </div>
  );
  else if (tab === "business") body = <Business onChange={refresh} />;
  else if (tab === "news") body = <div className="space-y-2">{(news ?? []).map((n) => <NewsItem key={n.id} n={n} />)}{news?.length === 0 && <div className="text-center text-gray-500 py-8">No news yet.</div>}</div>;
  else body = <div className="space-y-2">{(board ?? []).map((r) => (
    <div key={r.rank} className={card + " flex justify-between " + (r.me ? "border-acc" : "")}><span>#{r.rank} {r.name}</span><b>{inr(r.net_worth)}</b></div>))}</div>;
  const tabs = [["home", "🏠", "Home"], ["market", "📈", "Market"], ["portfolio", "💼", "Portfolio"], ["business", "🏢", "Business"], ["news", "📰", "News"], ["board", "🏆", "Ranks"]];
  return (
    <div className="min-h-screen pb-20 p-3 max-w-md mx-auto">
      {body}
      <nav className="fixed bottom-0 inset-x-0 bg-card border-t border-line flex justify-around py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
        {tabs.map(([k, i, l]) => (
          <button key={k} onClick={() => { setSel(null); setTab(k); haptic(); }} className={`text-xs flex flex-col items-center ${tab === k && !sel ? "text-acc" : "text-gray-400"}`}><span className="text-lg">{i}</span>{l}</button>))}
      </nav>
    </div>
  );
}
