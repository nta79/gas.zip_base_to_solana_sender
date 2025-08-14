
import os
import random
import json
import requests
from web3 import Web3
from eth_account import Account

# Configuration
BASE_CHAIN_ID = 8453  # Base
SOLANA_CHAIN_ID = 501474  # Solana
GAS_ZIP_API_BASE_URL = "https://backend.gas.zip/v2"

# Read private key
try:
    with open("pk.txt", "r") as f:
        PRIVATE_KEY = f.read().strip()
except FileNotFoundError:
    print("Error: pk.txt not found. Please create it and add your private key.")
    exit()

# Read Solana wallet addresses
try:
    with open("wallets.txt", "r") as f:
        SOLANA_WALLETS = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Error: wallets.txt not found. Please create it and add Solana wallet addresses.")
    exit()

if not SOLANA_WALLETS:
    print("Error: wallets.txt is empty. Please add Solana wallet addresses.")
    exit()

# Connect to Base network (using a public RPC for demonstration, replace with your own if needed)
# You might need to find a reliable RPC URL for Base Mainnet
BASE_RPC_URL = "https://mainnet.base.org"
web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

if not web3.is_connected():
    print(f"Error: Could not connect to Base network at {BASE_RPC_URL}")
    exit()

account = Account.from_key(PRIVATE_KEY)
print(f"Sender address: {account.address}")

def get_gas_zip_quote(deposit_chain_id, outbound_chain_id, deposit_amount_wei):
    url = f"{GAS_ZIP_API_BASE_URL}/quotes/{deposit_chain_id}/{deposit_amount_wei}/{outbound_chain_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting quote from Gas.zip: {e}")
        return None

def get_inbound_address(chain_id):
    # This information should ideally come from a reliable source or API.
    # For Base, the inbound address from documentation is 0x391E7C679d29bD940d63be94AD22A25d25b5A604
    # In a real application, you'd fetch this dynamically or confirm from official sources.
    inbound_addresses = {
        8453: "0x391E7C679d29bD940d63be94AD22A25d25b5A604" # Base Direct Forwarder
    }
    return inbound_addresses.get(chain_id)

def send_eth_to_gas_zip(private_key, sender_address, amount_eth, inbound_address):
    nonce = web3.eth.get_transaction_count(sender_address)
    gas_price = web3.eth.gas_price
    amount_wei = web3.to_wei(amount_eth, 'ether')

    transaction = {
        'from': sender_address,
        'to': inbound_address,
        'value': amount_wei,
        'gas': 21000,  # Standard gas limit for ETH transfer
        'gasPrice': gas_price,
        'nonce': nonce,
        'chainId': BASE_CHAIN_ID
    }

    signed_txn = web3.eth.account.sign_transaction(transaction, private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
    return web3.to_hex(tx_hash)

def track_deposit_status(tx_hash):
    url = f"{GAS_ZIP_API_BASE_URL}/deposit/{tx_hash}"
    while True:
        try:
            response = requests.get(url)
            response.raise_for_status()
            status_data = response.json()
            status = status_data.get("deposit", {}).get("status")
            print(f"Deposit status for {tx_hash}: {status}")
            if status in ["CONFIRMED", "CANCELLED"]:
                return status_data
            # Wait for a few seconds before checking again
            import time
            time.sleep(10)
        except requests.exceptions.RequestException as e:
            print(f"Error tracking deposit status: {e}")
            return None

results = []
inbound_address_base = get_inbound_address(BASE_CHAIN_ID)

if not inbound_address_base:
    print(f"Error: Inbound address for Base chain ID {BASE_CHAIN_ID} not found.")
    exit()

for i, solana_wallet in enumerate(SOLANA_WALLETS):
    print(f"\nProcessing wallet {i+1}/{len(SOLANA_WALLETS)}: {solana_wallet}")

    # Random ETH amount between 0.001 and 0.005 ETH
    eth_amount = random.uniform(0.001, 0.005)
    print(f"Sending {eth_amount:.5f} ETH from Base to Gas.zip for transfer to Solana.")

    # Get quote (deposit_amount_wei is not directly used for sending ETH, but for quote)
    # The quote API expects the amount in wei
    deposit_amount_wei_for_quote = web3.to_wei(eth_amount, 'ether')
    quote_data = get_gas_zip_quote(BASE_CHAIN_ID, SOLANA_CHAIN_ID, deposit_amount_wei_for_quote)

    if quote_data and quote_data.get("quotes"):
        # Assuming the first quote is sufficient for demonstration
        # In a real scenario, you might want to choose the best quote
        print(f"Quote received: {quote_data['quotes'][0]}")
    else:
        print("Could not get a valid quote. Skipping this wallet.")
        results.append({
            "solana_wallet": solana_wallet,
            "status": "Skipped - No valid quote",
            "eth_sent": eth_amount
        })
        continue

    # Send ETH to Gas.zip inbound address
    try:
        tx_hash = send_eth_to_gas_zip(PRIVATE_KEY, account.address, eth_amount, inbound_address_base)
        print(f"Transaction sent. Hash: {tx_hash}")

        # Track deposit status
        deposit_status = track_deposit_status(tx_hash)
        if deposit_status:
            results.append({
                "solana_wallet": solana_wallet,
                "eth_sent": eth_amount,
                "base_tx_hash": tx_hash,
                "deposit_status": deposit_status
            })
        else:
            results.append({
                "solana_wallet": solana_wallet,
                "eth_sent": eth_amount,
                "base_tx_hash": tx_hash,
                "deposit_status": "Failed to track"
            })

    except Exception as e:
        print(f"Error sending transaction for {solana_wallet}: {e}")
        results.append({
            "solana_wallet": solana_wallet,
            "eth_sent": eth_amount,
            "status": f"Failed to send transaction: {e}"
        })

# Save results to file
with open("transaction_results.json", "w") as f:
    json.dump(results, f, indent=4)

print("\nScript finished. Results saved to transaction_results.json")


