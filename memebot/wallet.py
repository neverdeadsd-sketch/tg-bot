"""Работа с ключом кошелька и подпись транзакций."""
from __future__ import annotations

import base64
import json

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

# Номер инструкции CloseAccount одинаков в SPL Token и Token-2022.
CLOSE_ACCOUNT_IX = 9


class WalletError(Exception):
    pass


def load_keypair(secret: str) -> Keypair:
    """Принимает приватный ключ в base58 (экспорт из Phantom/Solflare)
    или JSON-массив из 64 чисел (файл solana-keygen)."""
    value = secret.strip()
    try:
        if value.startswith("["):
            numbers = json.loads(value)
            if len(numbers) != 64:
                raise WalletError("JSON-ключ должен содержать 64 числа")
            return Keypair.from_bytes(bytes(numbers))
        return Keypair.from_base58_string(value)
    except WalletError:
        raise
    except Exception as exc:  # solders бросает разные типы ошибок
        raise WalletError(
            "Не удалось прочитать WALLET_PRIVATE_KEY. Нужен приватный ключ (base58 из Phantom "
            "или JSON-массив), а не адрес кошелька и не сид-фраза."
        ) from exc


def sign_swap_transaction(tx_base64: str, keypair: Keypair) -> tuple[bytes, str]:
    """Подписывает транзакцию от Jupiter. Возвращает (байты транзакции, подпись)."""
    tx = VersionedTransaction.from_bytes(base64.b64decode(tx_base64))
    payer = tx.message.account_keys[0]
    if payer != keypair.pubkey():
        raise WalletError(f"Транзакция оплачивается не нашим кошельком ({payer}) — не подписываю")
    signed = VersionedTransaction(tx.message, [keypair])
    return bytes(signed), str(signed.signatures[0])


def build_close_accounts_tx(
    keypair: Keypair, accounts: list[tuple[str, str]], blockhash: str
) -> tuple[bytes, str]:
    """Закрывает пустые токен-аккаунты и возвращает ~0.002 SOL ренты за каждый.

    accounts — список (адрес токен-аккаунта, программа токена).
    """
    owner = keypair.pubkey()
    instructions = [
        Instruction(
            program_id=Pubkey.from_string(program),
            data=bytes([CLOSE_ACCOUNT_IX]),
            accounts=[
                AccountMeta(Pubkey.from_string(address), is_signer=False, is_writable=True),
                AccountMeta(owner, is_signer=False, is_writable=True),
                AccountMeta(owner, is_signer=True, is_writable=False),
            ],
        )
        for address, program in accounts
    ]
    message = MessageV0.try_compile(owner, instructions, [], Hash.from_string(blockhash))
    tx = VersionedTransaction(message, [keypair])
    return bytes(tx), str(tx.signatures[0])
