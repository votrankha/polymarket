"""
Shared Polymarket API Client
Dùng chung cho Agent 1 và Agent 2
- Gamma API:  market data, activity, leaderboard
- CLOB API:   orderbook, signed order submission (L2 auth)
- WebSocket:  realtime trade stream (wss://ws-subscriptions-clob.polymarket.com)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
import aiohttp.client_exceptions
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "shared", ".env"))

logger = logging.getLogger("polybot.client")

GAMMA_API   = os.getenv("GAMMA_API",   "https://gamma-api.polymarket.com")
CLOB_API    = os.getenv("CLOB_API",    "https://clob.polymarket.com")
DATA_API    = os.getenv("DATA_API",    "https://data-api.polymarket.com")  # trades, positions
POLY_KEY    = os.getenv("POLY_API_KEY", "")
POLY_SECRET = os.getenv("POLY_API_SECRET", "")
POLY_PASS   = os.getenv("POLY_API_PASSPHRASE", "")
WALLET_ADDR = os.getenv("WALLET_ADDRESS", "")

HEADERS_BASE = {
    "User-Agent": "PolyBot/2.0",
    "Accept": "application/json",
}


def _clob_auth_headers(method: str, path: str, body: str = "") -> dict:
    """
    Generate CLOB L2 auth headers.
    Polymarket CLOB uses HMAC-SHA256: timestamp + method + path + body
    """
    ts = str(int(time.time() * 1000))
    msg = ts + method.upper() + path + (body or "")
    sig = hmac.new(
        POLY_SECRET.encode(),
        msg.encode(),
        hashlib.sha256,
    ).hexdigest()

    return {
        "POLY_ADDRESS":     WALLET_ADDR,
        "POLY_SIGNATURE":   sig,
        "POLY_TIMESTAMP":   ts,
        "POLY_API_KEY":     POLY_KEY,
        "POLY_PASSPHRASE":  POLY_PASS,
    }


class PolymarketClient:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _session_(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=HEADERS_BASE,
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def close(self):
        if self._session:
            await self._session.close()

    async def _get(self, base: str, path: str, params: dict = None) -> Any:
        url = base.rstrip("/") + path
        session = await self._session_()
        try:
            async with session.get(url, params=params) as r:
                if r.status == 429:
                    logger.warning("Rate limited, sleeping 5s...")
                    await asyncio.sleep(5)
                    return None
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            logger.debug(f"GET {url}: {e}")
            return None

    async def _post_clob(self, path: str, payload: dict) -> Any:
        url = CLOB_API.rstrip("/") + path
        body = json.dumps(payload)
        auth = _clob_auth_headers("POST", path, body)
        session = await self._session_()
        try:
            async with session.post(
                url,
                data=body,
                headers={**HEADERS_BASE, **auth, "Content-Type": "application/json"},
            ) as r:
                return await r.json()
        except Exception as e:
            logger.debug(f"POST {url}: {e}")
            return {"error": str(e)}

    # ════════════════════════════════════════
    #  GAMMA API
    # ════════════════════════════════════════

    async def get_leaderboard(self, limit: int = 300) -> List[Dict]:
        """
        Leaderboard chính thức từ data-api /v1/leaderboard.
        Docs: https://docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings
        limit tối đa 50/request → tự paginate để lấy đủ số cần.
        """
        results = []
        offset  = 0
        per_page = 50  # max theo docs

        while len(results) < limit:
            data = await self._get(
                DATA_API, "/v1/leaderboard",
                {
                    "limit":      per_page,
                    "offset":     offset,
                    "timePeriod": "ALL",   # lấy all-time traders tốt nhất
                    "orderBy":    "PNL",
                }
            )
            if not data:
                break
            rows = data.get("data", data) if isinstance(data, dict) else data
            if not rows:
                break
            results.extend(rows)
            if len(rows) < per_page:
                break  # hết data
            offset += per_page
            await asyncio.sleep(0.2)

        logger.info(f"[leaderboard] Fetched {len(results)} traders from /v1/leaderboard")
        # Normalize: đảm bảo có field "address" để code cũ dùng
        for r in results:
            if "address" not in r:
                r["address"] = r.get("proxyWallet", "")
        return results[:limit]

    async def get_wallet_activity(self, address: str, limit: int = 500) -> List[Dict]:
        """
        Full trade history for a wallet.
        Docs: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets
        - size = shares (không phải USDC)
        - usdcSize = size * price (tính tay)
        - takerOnly=false để lấy cả maker orders
        """
        data = await self._get(
            DATA_API, "/trades",
            {
                "user":      address.lower(),
                "limit":     min(limit, 10000),  # max theo docs
                "takerOnly": "false",             # lấy cả maker + taker
            }
        )
        if not data:
            return []
        rows = data.get("data", data) if isinstance(data, dict) else data
        normalized = []
        for r in (rows or []):
            shares   = float(r.get("size",  0) or 0)
            price    = float(r.get("price", 0) or 0)
            usdc     = shares * price  # size trong API = shares, nhân price = USDC
            normalized.append({
                "market":       r.get("conditionId", ""),
                "conditionId":  r.get("conditionId", ""),
                "side":         r.get("side", "BUY"),
                "price":        price,
                "size":         shares,
                "usdcSize":     round(usdc, 4),
                "timestamp":    r.get("timestamp", 0),
                "createdAt":    r.get("timestamp", 0),
                "outcomeIndex": str(r.get("outcomeIndex", "0")),
                "outcome":      r.get("outcome", ""),
                "title":        r.get("title", ""),
                "tokenId":      r.get("asset", ""),
                "asset":        r.get("asset", ""),
                "category":     "",  # không có trong response
            })
        return normalized

    async def get_closed_positions(self, address: str, limit: int = 500) -> List[Dict]:
        """
        Closed positions cho 1 ví — đây là nguồn chính xác nhất để tính win/loss.
        Mỗi entry = 1 market đã resolved với realizedPnl sẵn.
        Docs: https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user
        max 50/request → tự paginate.
        """
        results = []
        offset  = 0
        per_page = 50  # max theo docs

        while len(results) < limit:
            data = await self._get(
                DATA_API, "/closed-positions",
                {
                    "user":   address.lower(),
                    "limit":  per_page,
                    "offset": offset,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                }
            )
            if not data:
                break
            rows = data.get("data", data) if isinstance(data, dict) else data
            if not rows:
                break
            results.extend(rows)
            if len(rows) < per_page:
                break
            offset += per_page
            await asyncio.sleep(0.2)

        return results[:limit]

    async def get_open_positions(self, address: str,
                                  limit: int = 500) -> List[Dict]:
        """
        Open positions của 1 ví — vị thế đang nắm chưa resolve.
        Endpoint: data-api /positions
        Mỗi entry = 1 outcome token đang nắm với currentPrice + unrealizedPnl.

        Dùng để:
          - Phát hiện average down (so sánh với open_positions table trong DB)
          - Tính unrealized PnL realtime cho dashboard
          - Filter copy quality: is_new_position() trong Agent 2
        """
        results = []
        offset   = 0
        per_page = min(limit, 100)

        while len(results) < limit:
            data = await self._get(
                DATA_API, "/positions",
                {
                    "user":          address.lower(),
                    "limit":         per_page,
                    "offset":        offset,
                    "sortBy":        "CASH_INVESTED",
                    "sortDirection": "DESC",
                    "sizeThreshold": "0.01",
                }
            )
            if not data:
                break
            rows = data.get("data", data) if isinstance(data, dict) else data
            if not rows:
                break
            results.extend(rows)
            if len(rows) < per_page:
                break
            offset += per_page
            await asyncio.sleep(0.15)

        return results[:limit]

    async def get_market(self, condition_id: str) -> Optional[Dict]:
        return await self._get(GAMMA_API, f"/markets/{condition_id}")

    async def get_markets(
        self,
        limit: int = 200,
        category: str = None,
        active: bool = True,
    ) -> List[Dict]:
        params = {"limit": limit, "active": str(active).lower()}
        if category:
            params["category"] = category
        data = await self._get(GAMMA_API, "/markets", params)
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_market_trades(
        self,
        condition_id: str,
        limit: int = 200,
        since_ts: int = None,
    ) -> List[Dict]:
        params = {"market": condition_id, "limit": limit}
        if since_ts:
            params["after"] = since_ts
        data = await self._get(DATA_API, "/trades", params)
        if not data:
            return []
        return data.get("data", data) if isinstance(data, dict) else data

    # ════════════════════════════════════════
    #  CLOB API
    # ════════════════════════════════════════

    async def get_orderbook(self, token_id: str) -> Optional[Dict]:
        return await self._get(CLOB_API, "/book", {"token_id": token_id})

    async def get_best_ask(self, token_id: str) -> Optional[float]:
        """Best ask price to BUY an outcome token."""
        book = await self.get_orderbook(token_id)
        if not book:
            return None
        asks = book.get("asks", [])
        return float(asks[0]["price"]) if asks else None

    async def get_best_bid(self, token_id: str) -> Optional[float]:
        book = await self.get_orderbook(token_id)
        if not book:
            return None
        bids = book.get("bids", [])
        return float(bids[0]["price"]) if bids else None

    async def post_order(self, signed_order: dict) -> Dict:
        return await self._post_clob("/order", signed_order)

    async def cancel_order(self, order_id: str) -> Dict:
        return await self._post_clob("/cancel", {"orderID": order_id})

    async def get_open_orders(self) -> List[Dict]:
        path = "/orders"
        url = CLOB_API.rstrip("/") + path
        auth = _clob_auth_headers("GET", path)
        session = await self._session_()
        try:
            async with session.get(url, headers={**HEADERS_BASE, **auth}) as r:
                data = await r.json()
                return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.debug(f"get_open_orders: {e}")
            return []

    async def get_trades_history(self, maker: str = None) -> List[Dict]:
        path = "/data/trades"
        params = {}
        if maker:
            params["maker"] = maker
        return await self._get(CLOB_API, path, params) or []

    async def get_large_trades(
        self,
        min_size: float = 10_000,
        limit: int = 100,
    ) -> List[Dict]:
        """
        REST fallback cho Stage 1 khi WebSocket không kết nối được.
        Dùng filterType=CASH&filterAmount=N để server filter theo USDC trực tiếp.
        Docs: size = shares, usdcSize = shares * price
        """
        data = await self._get(
            DATA_API, "/trades",
            {
                "limit":        min(limit, 10000),
                "filterType":   "CASH",
                "filterAmount": min_size,  # server tự filter >= min_size USDC
            }
        )
        if not data:
            return []
        rows = data.get("data", data) if isinstance(data, dict) else data
        results = []
        for r in (rows or []):
            shares = float(r.get("size",  0) or 0)
            price  = float(r.get("price", 1) or 1)
            usdc   = shares * price
            results.append({
                "trader_address":    r.get("proxyWallet", ""),
                "market":            r.get("conditionId", ""),
                "outcome":           r.get("outcome", ""),
                "price":             price,
                "size_usdc":         round(usdc, 2),
                "side":              r.get("side", "BUY"),
                "timestamp":         r.get("timestamp", 0),
                "token_id":          r.get("asset", ""),
                "title":             r.get("title", ""),
                "transaction_hash":  r.get("transactionHash", ""),
            })
        return results


# ════════════════════════════════════════════════════════
#  WEBSOCKET TRADE STREAM
#  wss://ws-subscriptions-clob.polymarket.com/ws/market
#  Subscribe to all market trades → filter by size
# ════════════════════════════════════════════════════════
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

class TradeStream:
    """
    WebSocket stream theo đúng Polymarket docs:
    https://docs.polymarket.com/api-reference/wss/market

    Protocol:
    1. Connect to wss://ws-subscriptions-clob.polymarket.com/ws/market
    2. Send subscribe: {"assets_ids": [...], "type": "market"}
       - Phải có assets_ids cụ thể — empty list không nhận được gì
    3. Ping mỗi 10s: gửi "{}" — server phản hồi "{}"
    4. Trade event: event_type="last_trade_price"
       - KHÔNG có trader_address trong WS → dùng REST /trades để lookup

    Vì WS không có trader_address, flow thực tế:
    - WS nhận last_trade_price → biết có trade lớn trên asset nào
    - REST /trades?filterType=CASH&filterAmount=N → lấy trader_address
    """

    def __init__(
        self,
        on_trade: Callable[[Dict], None],
        min_size: float = 10_000,
        market_ids: Optional[List[str]] = None,
    ):
        self.on_trade   = on_trade
        self.min_size   = min_size
        self.market_ids = market_ids
        self._stop      = False
        self._reconnect_delay = 3
        self._asset_ids: List[str] = []   # fetched from active markets
        self._ws_event_count = 0

    def stop(self):
        self._stop = True

    async def _fetch_asset_ids(self, limit: int = 200) -> List[str]:
        """
        Fetch active market asset_ids để subscribe.
        WS yêu cầu assets_ids cụ thể — không thể subscribe all với [].
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{CLOB_API}/markets",
                    params={"next_cursor": "MQ==", "limit": limit},
                    headers=HEADERS_BASE,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status != 200:
                        return []
                    data = await r.json()
                    markets = data.get("data", []) if isinstance(data, dict) else data
                    ids = []
                    for m in (markets or []):
                        for token in m.get("tokens", []):
                            tid = token.get("token_id", "")
                            if tid:
                                ids.append(tid)
                    logger.info(f"[WS] Fetched {len(ids)} asset_ids from {len(markets)} markets")
                    return ids[:500]  # giới hạn để tránh subscribe msg quá lớn
        except Exception as e:
            logger.warning(f"[WS] Failed to fetch asset_ids: {e}")
            return []

    async def run(self):
        """Main loop — kết nối và tự reconnect khi bị ngắt."""
        # Fetch asset_ids trước lần kết nối đầu
        if not self._asset_ids:
            self._asset_ids = await self._fetch_asset_ids()

        while not self._stop:
            try:
                await self._connect()
            except Exception as e:
                logger.warning(f"[WS] Disconnected: {e}. Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)
                # Refresh asset_ids sau mỗi lần reconnect
                if self._reconnect_delay > 6:
                    self._asset_ids = await self._fetch_asset_ids()
            else:
                self._reconnect_delay = 3

    async def _connect(self):
        logger.info(f"[WS] Connecting to {WS_URL}...")
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                WS_URL,
                timeout=aiohttp.ClientWSTimeout(ws_close=30),
            ) as ws:
                logger.info(f"[WS] Connected. Subscribing {len(self._asset_ids)} assets...")
                self._reconnect_delay = 3

                # Subscribe theo đúng docs: assets_ids + type
                sub_msg = {
                    "assets_ids": self._asset_ids,
                    "type": "market",
                }
                await ws.send_str(json.dumps(sub_msg))

                # Ping task — gửi {} mỗi 10s theo docs
                async def _ping():
                    while not self._stop:
                        await asyncio.sleep(10)
                        try:
                            await ws.send_str("{}")
                        except Exception:
                            break

                ping_task = asyncio.ensure_future(_ping())

                try:
                    async for msg in ws:
                        if self._stop:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._ws_event_count += 1
                            if self._ws_event_count <= 3:
                                logger.info(f"[WS] Raw msg #{self._ws_event_count}: {msg.data[:300]}")
                            await self._handle(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"[WS] Connection closed/error: {msg}")
                            break
                finally:
                    ping_task.cancel()

    async def _handle(self, raw: str):
        """
        Parse WS event. Theo docs, trade event là last_trade_price:
        {
          "event_type": "last_trade_price",
          "asset_id": "...",
          "market": "0x...",
          "price": "0.456",
          "size": "219.217767",   ← đây là USDC (không phải shares)
          "side": "BUY",
          "timestamp": "...",
          "transaction_hash": "0x..."
        }
        KHÔNG có trader_address — phải dùng REST để lấy.
        price_change event cũng có size và side.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Pong response "{}" — bỏ qua
        if data == {} or data == "{}":
            return

        events = data if isinstance(data, list) else [data]

        for ev in events:
            if not isinstance(ev, dict):
                continue

            etype = str(ev.get("event_type", "")).lower()

            # Chỉ xử lý trade events
            if etype == "last_trade_price":
                await self._process_trade_event(ev)

            elif etype == "price_change":
                # price_change chứa list price_changes, mỗi item có thể là trade
                for pc in ev.get("price_changes", []):
                    if isinstance(pc, dict):
                        pc["market"] = ev.get("market", "")
                        pc["timestamp"] = ev.get("timestamp", "")
                        await self._process_trade_event(pc)

    async def _process_trade_event(self, ev: dict):
        """
        Xử lý 1 trade event. size trong last_trade_price = USDC theo docs.
        Vì WS không có trader_address, emit event với trader_address="" —
        Stage 1 sẽ dùng REST /trades để lookup trader ngay sau khi detect.
        """
        price = float(ev.get("price", 0) or 0)
        if price <= 0 or price > 1:
            return

        # Trong last_trade_price, size = USDC value của trade
        size_usdc = float(ev.get("size", 0) or 0)
        if size_usdc <= 0:
            return

        if size_usdc < self.min_size:
            return

        self._ws_event_count += 1
        if self._ws_event_count <= 10 or self._ws_event_count % 50 == 0:
            logger.debug(
                f"[WS trade #{self._ws_event_count}] "
                f"asset={str(ev.get('asset_id',''))[:16]} "
                f"price={price} usdc=${size_usdc:,.0f}"
            )

        trade = {
            "event_type":     "trade",
            "market":         ev.get("market", ""),
            "outcome":        ev.get("side", "BUY"),
            "price":          price,
            "size_usdc":      round(size_usdc, 2),
            "side":           ev.get("side", "BUY"),
            "trader_address": "",   # WS không có — Stage 1 sẽ lookup qua REST
            "timestamp":      int(float(ev.get("timestamp", time.time()) or time.time()) / 1000
                                  if float(ev.get("timestamp", 0) or 0) > 1e12
                                  else float(ev.get("timestamp", time.time()) or time.time())),
            "token_id":       ev.get("asset_id", ""),
        }
        await asyncio.get_event_loop().run_in_executor(
            None, self.on_trade, trade
        )

