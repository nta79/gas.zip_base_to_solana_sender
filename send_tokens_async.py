import os
import random
import json
import asyncio
import aiohttp
import time
from web3 import Web3
from eth_account import Account
from typing import Dict, Any

# ==================== CONFIG ====================
MIN_ETH_AMOUNT = 0.00015
MAX_ETH_AMOUNT = 0.0002
MAX_CONCURRENT_TX = 5  # Количество одновременно выполняемых бриджей
MAX_PRIORITY_FEE_MULTIPLIER = 0.1
MAX_FEE_MULTIPLIER = 2.0
BASE_CHAIN_ID = 8453
SOLANA_CHAIN_ID = 501474
GAS_ZIP_API_BASE_URL = "https://backend.gas.zip/v2"
BASE_RPC_URL = "https://mainnet.base.org"
# =================================================

# Читаем приватный ключ
with open("pk.txt", "r") as f:
    PRIVATE_KEY = f.read().strip()

# Читаем Solana адреса
with open("wallets.txt", "r") as f:
    SOLANA_WALLETS = [line.strip() for line in f if line.strip()]

web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
if not web3.is_connected():
    raise SystemExit("Не удалось подключиться к Base RPC")

account = Account.from_key(PRIVATE_KEY)
print(f"Sender: {account.address}")

# nonce контроль
nonce_lock = asyncio.Lock()
current_nonce = None


def validate_solana_address(address: str) -> bool:
    if not (32 <= len(address) <= 44):
        return False
    allowed_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return all(c in allowed_chars for c in address)


async def get_gas_zip_calldata_quote(session: aiohttp.ClientSession,
                                     deposit_chain_id: int,
                                     deposit_amount_wei: int,
                                     outbound_chain_id: int,
                                     destination_address: str,
                                     sender_address: str) -> Dict[str, Any] | None:
    url = f"{GAS_ZIP_API_BASE_URL}/quotes/{deposit_chain_id}/{deposit_amount_wei}/{outbound_chain_id}"
    params = {'to': destination_address, 'from': sender_address}
    try:
        async with session.get(url, params=params, timeout=15) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        print(f"❌ Ошибка при получении calldata quote: {e}")
        return None


def get_inbound_address(chain_id: int) -> str | None:
    inbound_addresses = {
        8453: "0x391E7C679d29bD940d63be94AD22A25d25b5A604"
    }
    return inbound_addresses.get(chain_id)


def get_eip1559_gas_params() -> tuple[int, int]:
    try:
        latest_block = web3.eth.get_block('latest')
        base_fee_per_gas = latest_block.get('baseFeePerGas', 0)
        try:
            priority_fee = web3.eth.max_priority_fee
        except:
            priority_fee = web3.to_wei(0.001, 'gwei')

        max_priority_fee_per_gas = int(priority_fee * MAX_PRIORITY_FEE_MULTIPLIER)
        max_fee_per_gas = int((base_fee_per_gas * MAX_FEE_MULTIPLIER) + max_priority_fee_per_gas)
        return max_fee_per_gas, max_priority_fee_per_gas
    except:
        return web3.to_wei(2, 'gwei'), web3.to_wei(0.001, 'gwei')


async def send_bridge_transaction(private_key: str, sender_address: str, amount_eth: float, inbound_address: str,
                                  calldata: str) -> str:
    global current_nonce

    async with nonce_lock:
        if current_nonce is None:
            current_nonce = await asyncio.to_thread(web3.eth.get_transaction_count, sender_address)
        nonce = current_nonce
        current_nonce += 1

    amount_wei = web3.to_wei(amount_eth, 'ether')
    max_fee_per_gas, max_priority_fee_per_gas = get_eip1559_gas_params()

    try:
        gas_estimate = await asyncio.to_thread(
            web3.eth.estimate_gas,
            {
                'from': sender_address,
                'to': inbound_address,
                'value': amount_wei,
                'data': calldata,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee_per_gas
            }
        )
        gas_limit = int(gas_estimate * 1.2)
    except:
        gas_limit = 100000

    transaction = {
        'from': sender_address,
        'to': inbound_address,
        'value': amount_wei,
        'gas': gas_limit,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': nonce,
        'data': calldata,
        'chainId': BASE_CHAIN_ID,
        'type': 2
    }

    signed_txn = web3.eth.account.sign_transaction(transaction, private_key)
    tx_hash = await asyncio.to_thread(web3.eth.send_raw_transaction, signed_txn.rawTransaction)
    return web3.to_hex(tx_hash)


async def process_wallet(semaphore: asyncio.Semaphore, session: aiohttp.ClientSession, solana_wallet: str) -> dict:
    async with semaphore:
        if not validate_solana_address(solana_wallet):
            print(f"⚠️ Пропуск: неверный Solana адрес {solana_wallet}")
            return {"wallet": solana_wallet, "status": "invalid_address"}

        eth_amount = round(random.uniform(MIN_ETH_AMOUNT, MAX_ETH_AMOUNT), 8)
        print(f"🔄 Отправка {eth_amount} ETH -> {solana_wallet}")

        deposit_amount_wei = web3.to_wei(eth_amount, 'ether')
        calldata_quote = await get_gas_zip_calldata_quote(session,
                                                          BASE_CHAIN_ID,
                                                          deposit_amount_wei,
                                                          SOLANA_CHAIN_ID,
                                                          solana_wallet,
                                                          account.address)
        if not calldata_quote or not calldata_quote.get("calldata"):
            print(f"❌ Нет calldata для {solana_wallet}")
            return {"wallet": solana_wallet, "status": "no_calldata"}

        calldata = calldata_quote["calldata"]
        inbound_address = get_inbound_address(BASE_CHAIN_ID)
        try:
            tx_hash = await send_bridge_transaction(PRIVATE_KEY, account.address, eth_amount, inbound_address, calldata)
            print(f"✅ TX: {tx_hash}")
            return {"wallet": solana_wallet, "status": "sent", "tx_hash": tx_hash}
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")
            return {"wallet": solana_wallet, "status": f"error: {e}"}


async def main():
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TX)
    async with aiohttp.ClientSession() as session:
        tasks = [process_wallet(semaphore, session, w) for w in SOLANA_WALLETS]
        results = await asyncio.gather(*tasks)

    with open("bridge_results.json", "w") as f:
        json.dump(results, f, indent=4)
    print("🎉 Готово, результаты сохранены.")


if __name__ == "__main__":
    asyncio.run(main())
