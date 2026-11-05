import base64
import json

import pytest
from conftest import FakeJupiter, make_settings
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from memebot.config import LAMPORTS_PER_SOL, SOL_MINT
from memebot.solana_rpc import TokenAccount
from memebot.trader import LiveTrader, TradeError
from memebot.wallet import WalletError, build_close_accounts_tx, load_keypair, sign_swap_transaction

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def test_load_keypair_formats():
    kp = Keypair()
    assert load_keypair(str(kp)).pubkey() == kp.pubkey()
    assert load_keypair(json.dumps(list(bytes(kp)))).pubkey() == kp.pubkey()
    with pytest.raises(WalletError):
        load_keypair(str(kp.pubkey()))  # адрес вместо ключа
    with pytest.raises(WalletError):
        load_keypair("abandon abandon abandon")


def _jupiter_style_tx(payer: Pubkey) -> str:
    ix = Instruction(Pubkey.from_string(TOKEN_PROGRAM), b"\x01", [AccountMeta(payer, True, True)])
    msg = MessageV0.try_compile(payer, [ix], [], Hash.default())
    from solders.signature import Signature

    tx = VersionedTransaction.populate(msg, [Signature.default()])
    return base64.b64encode(bytes(tx)).decode()


def test_sign_swap_transaction():
    kp = Keypair()
    raw, sig = sign_swap_transaction(_jupiter_style_tx(kp.pubkey()), kp)
    tx = VersionedTransaction.from_bytes(raw)
    assert str(tx.signatures[0]) == sig
    assert all(tx.verify_with_results())


def test_refuses_to_sign_foreign_transaction():
    with pytest.raises(WalletError):
        sign_swap_transaction(_jupiter_style_tx(Keypair().pubkey()), Keypair())


def test_close_accounts_tx():
    kp = Keypair()
    ata = str(Keypair().pubkey())
    raw, sig = build_close_accounts_tx(kp, [(ata, TOKEN_PROGRAM)], str(Hash.default()))
    tx = VersionedTransaction.from_bytes(raw)
    assert all(tx.verify_with_results())
    ix = tx.message.instructions[0]
    assert bytes(ix.data) == bytes([9])


class FakeChain:
    """Кошелёк в сети: балансы меняются, когда «подтверждается» транзакция."""

    def __init__(self, sol: int):
        self.sol = sol
        self.tokens: dict[str, int] = {}
        self.pending = None
        self.fail_next = False
        self.accounts_closed = 0
        self.ata = str(Keypair().pubkey())

    # --- SolanaRpc API ---
    async def get_balance(self, pubkey):
        return self.sol

    async def token_balance(self, owner, mint):
        return self.tokens.get(mint, 0), 6

    async def token_accounts(self, owner, mint):
        if mint in self.tokens:
            return [TokenAccount(self.ata, TOKEN_PROGRAM, self.tokens[mint], 6, 2_039_280)]
        return []

    async def latest_blockhash(self):
        return str(Hash.default()), 10

    async def send_and_confirm(self, raw, last_valid):
        tx = VersionedTransaction.from_bytes(raw)
        assert all(tx.verify_with_results())
        if self.fail_next:
            self.fail_next = False
            return "SIGFAIL", "failed: slippage"
        effect = self.pending or self.close_effect
        self.pending = None
        effect()
        return "SIG", "confirmed"

    def close_effect(self):
        for mint, amount in list(self.tokens.items()):
            if amount == 0:
                del self.tokens[mint]
                self.sol += 2_039_280
                self.accounts_closed += 1


class FakeSwapJupiter(FakeJupiter):
    def __init__(self, chain: FakeChain, payer: Pubkey):
        super().__init__()
        self.chain = chain
        self.payer = payer

    async def swap_transaction(self, quote, user, max_fee, level):
        assert user == str(self.payer)
        fee = 105_000
        rent = 2_039_280

        def effect():
            if quote.input_mint == SOL_MINT:
                first = quote.output_mint not in self.chain.tokens
                self.chain.sol -= quote.in_amount + fee + (rent if first else 0)
                self.chain.tokens[quote.output_mint] = self.chain.tokens.get(quote.output_mint, 0) + quote.out_amount
            else:
                self.chain.tokens[quote.input_mint] -= quote.in_amount
                self.chain.sol += quote.out_amount - fee

        self.chain.pending = effect
        return _jupiter_style_tx(self.payer), 10


async def test_live_trader_accounts_real_balance_changes():
    kp = Keypair()
    chain = FakeChain(sol=1 * LAMPORTS_PER_SOL)
    jup = FakeSwapJupiter(chain, kp.pubkey())
    jup.tokens_per_sol["MEME"] = 1_000_000_000
    trader = LiveTrader(jup, chain, kp, make_settings(TRADING_MODE="live", WALLET_PRIVATE_KEY=str(kp)))

    buy = await trader.buy("MEME", 50_000_000)
    assert buy.token_amount == 50_000_000
    assert buy.lamports_spent == 50_000_000 + 105_000  # сумма + комиссия; залог за аккаунт отдельно
    assert buy.rent_lamports == 2_039_280
    assert buy.signature == "SIG"

    sell = await trader.sell("MEME", buy.token_amount, 800)
    assert sell.token_sold == buy.token_amount
    assert sell.lamports_received == 50_000_000 - 105_000

    refund = await trader.cleanup("MEME")
    assert refund == 2_039_280 and chain.accounts_closed == 1


async def test_live_trader_failed_swap_raises(monkeypatch):
    import memebot.trader as trader_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(trader_mod.asyncio, "sleep", no_sleep)
    kp = Keypair()
    chain = FakeChain(sol=LAMPORTS_PER_SOL)
    jup = FakeSwapJupiter(chain, kp.pubkey())
    jup.tokens_per_sol["MEME"] = 1_000_000_000
    trader = LiveTrader(jup, chain, kp, make_settings(TRADING_MODE="live", WALLET_PRIVATE_KEY=str(kp)))
    chain.fail_next = True
    with pytest.raises(TradeError, match="покупка не прошла"):
        await trader.buy("MEME", 50_000_000)
    with pytest.raises(TradeError, match="нет этих токенов"):
        await trader.sell("MEME", 10, 800)


async def test_engine_live_round_trip_accounting(store):
    from conftest import Clock, FakeDex, FakeRug, clean_report, good_pair

    from memebot.engine import Engine

    kp = Keypair()
    start = LAMPORTS_PER_SOL
    chain = FakeChain(sol=start)
    jup = FakeSwapJupiter(chain, kp.pubkey())
    jup.tokens_per_sol["MEME"] = 1_000_000_000
    settings = make_settings(TRADING_MODE="live", WALLET_PRIVATE_KEY=str(kp))
    trader = LiveTrader(jup, chain, kp, settings)
    messages = []

    async def notify(text, buttons=None):
        messages.append(text)

    engine = Engine(
        settings, store, FakeDex([good_pair("MEME")]), FakeRug({"MEME": clean_report()}), jup, trader, notify, clock=Clock()
    )
    await engine.scan_once()
    [pos] = await store.open_positions()
    assert pos.entry_lamports == settings.buy_amount_lamports + 105_000

    await engine.sell_position(pos.id, 1.0, "тест")
    [closed] = await store.closed_positions()
    assert closed.pnl_lamports == -2 * 105_000  # при неизменной цене теряем только комиссии
    assert chain.sol == start - 2 * 105_000  # залог за аккаунт вернулся
    assert chain.tokens == {}
