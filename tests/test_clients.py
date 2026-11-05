"""Проверяем, что клиенты формируют правильные запросы и правильно разбирают ответы.
Формат ответов взят из документации API; живые запросы здесь не делаются."""
import base64
import json

import httpx
import pytest

from memebot.config import SOL_MINT
from memebot.dexscreener import DexScreener, best_pairs
from memebot.jupiter import Jupiter, QuoteError, SwapError
from memebot.rugcheck import parse_report
from memebot.solana_rpc import SolanaRpc


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_jupiter_quote_request_and_parse():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"inAmount": "50000000", "outAmount": "123456789", "routePlan": []})

    async with client(handler) as http:
        jup = Jupiter(http, "https://api.jup.ag/swap/v1", api_key="KEY")
        q = await jup.quote(SOL_MINT, "MINT", 50_000_000, 300)
    assert q.in_amount == 50_000_000 and q.out_amount == 123_456_789
    assert seen["url"].startswith("https://api.jup.ag/swap/v1/quote?")
    for part in ("inputMint=" + SOL_MINT, "outputMint=MINT", "amount=50000000", "slippageBps=300", "swapMode=ExactIn"):
        assert part in seen["url"]
    assert seen["key"] == "KEY"


async def test_jupiter_quote_no_route_raises():
    def handler(request):
        return httpx.Response(400, json={"error": "Could not find any route", "errorCode": "COULD_NOT_FIND_ANY_ROUTE"})

    async with client(handler) as http:
        with pytest.raises(QuoteError, match="route"):
            await Jupiter(http, "https://x/swap/v1").quote(SOL_MINT, "MINT", 1, 100)


async def test_jupiter_quote_retries_on_429():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"inAmount": "1", "outAmount": "2"})

    async with client(handler) as http:
        q = await Jupiter(http, "https://x/swap/v1", retry_delay=0).quote(SOL_MINT, "MINT", 1, 100)
    assert q.out_amount == 2 and calls["n"] == 2


async def test_jupiter_swap_body():
    body = {}

    def handler(request):
        body.update(json.loads(request.content))
        return httpx.Response(200, json={"swapTransaction": "AAAA", "lastValidBlockHeight": 123})

    async with client(handler) as http:
        jup = Jupiter(http, "https://x/swap/v1")
        from memebot.jupiter import Quote

        tx, height = await jup.swap_transaction(Quote(SOL_MINT, "M", 1, 2, {"q": 1}), "PUBKEY", 300_000, "high")
    assert (tx, height) == ("AAAA", 123)
    assert body["quoteResponse"] == {"q": 1}
    assert body["userPublicKey"] == "PUBKEY"
    assert body["wrapAndUnwrapSol"] is True
    assert body["prioritizationFeeLamports"]["priorityLevelWithMaxLamports"] == {"maxLamports": 300_000, "priorityLevel": "high"}


async def test_jupiter_swap_error():
    async with client(lambda r: httpx.Response(400, json={"error": "bad"})) as http:
        with pytest.raises(SwapError):
            from memebot.jupiter import Quote

            await Jupiter(http, "https://x").swap_transaction(Quote(SOL_MINT, "M", 1, 2, {}), "P", 1, "high")


def _raw_pair(mint, liquidity, chain="solana", pair="P"):
    return {
        "chainId": chain,
        "dexId": "raydium",
        "url": f"https://dexscreener.com/solana/{pair}",
        "pairAddress": pair,
        "baseToken": {"address": mint, "name": "Name", "symbol": "SYM"},
        "quoteToken": {"address": SOL_MINT, "symbol": "SOL"},
        "priceUsd": "0.001",
        "txns": {"h1": {"buys": 10, "sells": 5}},
        "volume": {"h24": 1000, "h1": 100},
        "priceChange": {"m5": 1, "h1": 2, "h24": 3},
        "liquidity": {"usd": liquidity},
        "fdv": 5000,
        "marketCap": 4000,
        "pairCreatedAt": 1_700_000_000_000,
    }


def test_best_pairs_picks_most_liquid_base_pool():
    raw = [
        _raw_pair("A", 100, pair="small"),
        _raw_pair("A", 900, pair="big"),
        _raw_pair("A", 99999, chain="ethereum", pair="eth"),
        _raw_pair("OTHER", 5000, pair="other"),
    ]
    result = best_pairs(raw, {"A"})
    assert list(result) == ["A"]
    p = result["A"]
    assert p.pair_address == "big" and p.liquidity_usd == 900 and p.mcap_usd == 4000
    assert p.buys_h1 == 10 and p.change_h1 == 2 and p.created_at_ms == 1_700_000_000_000


async def test_dexscreener_candidates_and_pairs():
    def handler(request: httpx.Request):
        path = request.url.path
        if path.startswith("/token-boosts/top"):
            return httpx.Response(200, json=[{"chainId": "solana", "tokenAddress": "A"}, {"chainId": "base", "tokenAddress": "X"}])
        if path.startswith("/token-boosts/latest"):
            return httpx.Response(200, json=[{"chainId": "solana", "tokenAddress": "A"}, {"chainId": "solana", "tokenAddress": "B"}])
        if path.startswith("/token-profiles"):
            return httpx.Response(500)
        if path == "/tokens/v1/solana/A,B":
            return httpx.Response(200, json=[_raw_pair("A", 10), _raw_pair("B", 20)])
        return httpx.Response(404)

    async with client(handler) as http:
        dex = DexScreener(http)
        import memebot.http as h

        original = h.asyncio.sleep

        async def no_sleep(_):
            return None

        h.asyncio.sleep = no_sleep
        try:
            mints = await dex.candidate_mints()
        finally:
            h.asyncio.sleep = original
        assert mints == ["A", "B"]
        pairs = await dex.pairs_for(mints)
    assert set(pairs) == {"A", "B"}


def test_rugcheck_parse_full_report():
    report = parse_report(
        {
            "tokenProgram": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "token": {"mintAuthority": None, "freezeAuthority": None},
            "score": 501,
            "score_normalised": 12,
            "risks": [{"name": "Low Liquidity", "level": "danger", "description": "..."}],
            "markets": [
                {"lp": {"lpLockedPct": 0, "baseUSD": 100, "quoteUSD": 100}},
                {"lp": {"lpLockedPct": 99.5, "baseUSD": 50_000, "quoteUSD": 50_000}},
            ],
            "rugged": False,
            "transferFee": {"pct": 0},
        }
    )
    assert report.mint_authority_known and report.mint_authority is None
    assert report.freeze_authority_known and report.freeze_authority is None
    assert report.score == 12
    assert report.lp_locked_pct == 99.5
    assert report.risks[0].level == "danger"


def test_rugcheck_parse_missing_fields_is_unknown():
    report = parse_report({"risks": []})
    assert not report.mint_authority_known and not report.freeze_authority_known
    assert report.score is None and report.lp_locked_pct is None


def test_rugcheck_top_level_authority_wins():
    report = parse_report({"mintAuthority": "Evil", "freezeAuthority": None, "lpLockedPct": 100})
    assert report.mint_authority == "Evil" and report.lp_locked_pct == 100


def _rpc_handler(statuses):
    calls = []

    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        calls.append(payload["method"])
        method = payload["method"]
        if method == "sendTransaction":
            assert payload["params"][1]["encoding"] == "base64"
            base64.b64decode(payload["params"][0])
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "SIG"})
        if method == "getSignatureStatuses":
            status = statuses.pop(0) if statuses else None
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": [status]}})
        if method == "getBlockHeight":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 100})
        if method == "getTokenAccountsByOwner":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "value": [
                            {
                                "pubkey": "ATA1",
                                "account": {
                                    "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                    "data": {"parsed": {"info": {"tokenAmount": {"amount": "123456789012345678901", "decimals": 9}}}},
                                },
                            }
                        ]
                    },
                },
            )
        if method == "getBalance":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": 5}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "unknown"}})

    return handler, calls


async def test_rpc_confirm_flow():
    handler, calls = _rpc_handler([None, {"confirmationStatus": "processed", "err": None}, {"confirmationStatus": "confirmed", "err": None}])
    async with client(handler) as http:
        sig, status = await SolanaRpc(http, "https://rpc").send_and_confirm(b"tx", 200, poll=0, resend_every=0)
    assert (sig, status) == ("SIG", "confirmed")
    assert calls.count("sendTransaction") >= 2  # переотправка, пока не подтвердилась


async def test_rpc_failed_and_expired():
    handler, _ = _rpc_handler([{"confirmationStatus": "confirmed", "err": {"InstructionError": [3, {"Custom": 6001}]}}])
    async with client(handler) as http:
        _, status = await SolanaRpc(http, "https://rpc").send_and_confirm(b"tx", 200, poll=0)
    assert status.startswith("failed")

    handler, _ = _rpc_handler([])
    async with client(handler) as http:
        _, status = await SolanaRpc(http, "https://rpc").send_and_confirm(b"tx", 50, poll=0)
    assert status == "expired"


async def test_rpc_token_balance_handles_huge_amounts():
    handler, _ = _rpc_handler([])
    async with client(handler) as http:
        rpc = SolanaRpc(http, "https://rpc")
        amount, decimals = await rpc.token_balance("OWNER", "MINT")
        assert amount == 123456789012345678901 and decimals == 9
        assert await rpc.get_balance("OWNER") == 5
