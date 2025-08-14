import os
import random
import json
import requests
import time
from web3 import Web3
from eth_account import Account

# Configuration
BASE_CHAIN_ID = 8453  # Base
SOLANA_CHAIN_ID = 501474  # Solana (Gas.zip uses this ID for Solana)
GAS_ZIP_API_BASE_URL = "https://backend.gas.zip/v2"

# ETH Amount Settings (in ETH)
MIN_ETH_AMOUNT = 0.00015  # Minimum ETH to send
MAX_ETH_AMOUNT = 0.0002  # Maximum ETH to send

# EIP-1559 Gas Settings
MAX_PRIORITY_FEE_MULTIPLIER = 0.1  # Multiplier for priority fee (tip)
MAX_FEE_MULTIPLIER = 2.0  # Multiplier for max fee per gas

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

# Connect to Base network
BASE_RPC_URL = "https://mainnet.base.org"
web3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))

if not web3.is_connected():
    print(f"Error: Could not connect to Base network at {BASE_RPC_URL}")
    exit()

account = Account.from_key(PRIVATE_KEY)
print(f"Sender address: {account.address}")


def get_gas_zip_calldata_quote(deposit_chain_id, deposit_amount_wei, outbound_chain_id, destination_address,
                               sender_address):
    """Get calldata and quote for bridging from Gas.zip API"""
    url = f"{GAS_ZIP_API_BASE_URL}/quotes/{deposit_chain_id}/{deposit_amount_wei}/{outbound_chain_id}"
    params = {
        'to': destination_address,
        'from': sender_address
    }

    try:
        response = requests.get(url, params = params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting calldata quote from Gas.zip: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        return None


def get_inbound_address(chain_id):
    """Get the Gas.zip inbound address for the specified chain"""
    inbound_addresses = {
        8453: "0x391E7C679d29bD940d63be94AD22A25d25b5A604"  # Base Direct Forwarder
    }
    return inbound_addresses.get(chain_id)


def get_eip1559_gas_params():
    """Get EIP-1559 gas parameters for Base network"""
    try:
        # Get latest block to determine base fee
        latest_block = web3.eth.get_block('latest')
        base_fee_per_gas = latest_block.get('baseFeePerGas', 0)

        # Get suggested priority fee from eth_maxPriorityFeePerGas if available
        try:
            priority_fee = web3.eth.max_priority_fee
        except:
            # Fallback: use a reasonable priority fee for Base (typically low)
            priority_fee = web3.to_wei(0.001, 'gwei')  # 0.001 Gwei priority fee

        # Calculate max fees with multipliers
        max_priority_fee_per_gas = int(priority_fee * MAX_PRIORITY_FEE_MULTIPLIER)
        max_fee_per_gas = int((base_fee_per_gas * MAX_FEE_MULTIPLIER) + max_priority_fee_per_gas)

        print(f"EIP-1559 Gas Parameters:")
        print(f"  Base Fee: {web3.from_wei(base_fee_per_gas, 'gwei'):.4f} Gwei")
        print(f"  Priority Fee: {web3.from_wei(max_priority_fee_per_gas, 'gwei'):.4f} Gwei")
        print(f"  Max Fee: {web3.from_wei(max_fee_per_gas, 'gwei'):.4f} Gwei")

        return max_fee_per_gas, max_priority_fee_per_gas

    except Exception as e:
        print(f"Error getting EIP-1559 gas parameters: {e}")
        # Fallback to reasonable defaults for Base
        max_fee_per_gas = web3.to_wei(2, 'gwei')  # 2 Gwei max fee
        max_priority_fee_per_gas = web3.to_wei(0.001, 'gwei')  # 0.001 Gwei priority fee

        print(f"Using fallback EIP-1559 gas parameters:")
        print(f"  Max Fee: {web3.from_wei(max_fee_per_gas, 'gwei'):.4f} Gwei")
        print(f"  Priority Fee: {web3.from_wei(max_priority_fee_per_gas, 'gwei'):.4f} Gwei")

        return max_fee_per_gas, max_priority_fee_per_gas


def send_bridge_transaction(private_key, sender_address, amount_eth, inbound_address, calldata):
    """Send ETH with calldata to Gas.zip for bridging to Solana using EIP-1559"""
    nonce = web3.eth.get_transaction_count(sender_address)
    amount_wei = web3.to_wei(amount_eth, 'ether')

    # Get EIP-1559 gas parameters
    max_fee_per_gas, max_priority_fee_per_gas = get_eip1559_gas_params()

    # Estimate gas for transaction with calldata
    try:
        gas_estimate = web3.eth.estimate_gas({
            'from': sender_address,
            'to': inbound_address,
            'value': amount_wei,
            'data': calldata,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': max_priority_fee_per_gas
        })
        # Add 20% buffer to gas estimate
        gas_limit = int(gas_estimate * 1.2)
        print(f"  Gas Estimate: {gas_limit:,} units")
    except Exception as e:
        print(f"Gas estimation failed: {e}")
        gas_limit = 100000  # Fallback gas limit

    # Calculate estimated transaction cost
    estimated_gas_cost_wei = gas_limit * max_fee_per_gas
    estimated_gas_cost_eth = float(web3.from_wei(estimated_gas_cost_wei, 'ether'))
    total_cost_eth = amount_eth + estimated_gas_cost_eth

    print(f"  Estimated Gas Cost: {estimated_gas_cost_eth:.8f} ETH")
    print(f"  Total Transaction Cost: {total_cost_eth:.8f} ETH")

    # Build EIP-1559 transaction
    transaction = {
        'from': sender_address,
        'to': inbound_address,
        'value': amount_wei,
        'gas': gas_limit,
        'maxFeePerGas': max_fee_per_gas,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'nonce': nonce,
        'data': calldata,  # Include calldata for bridging instructions
        'chainId': BASE_CHAIN_ID,
        'type': 2  # EIP-1559 transaction type
    }

    signed_txn = web3.eth.account.sign_transaction(transaction, private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
    return web3.to_hex(tx_hash)


def track_deposit_status(tx_hash, max_wait_time=300):
    """Track the status of a deposit transaction with timeout"""
    url = f"{GAS_ZIP_API_BASE_URL}/deposit/{tx_hash}"
    start_time = time.time()

    while time.time() - start_time < max_wait_time:
        try:
            response = requests.get(url)
            response.raise_for_status()
            status_data = response.json()

            deposit_info = status_data.get("deposit", {})
            status = deposit_info.get("status", "UNKNOWN")
            outbound_txs = status_data.get("outbound", [])

            print(f"Deposit status for {tx_hash}: {status}")

            if outbound_txs:
                for outbound in outbound_txs:
                    print(f"  Outbound tx: {outbound.get('hash', 'N/A')} on chain {outbound.get('chain', 'N/A')}")

            if status in ["CONFIRMED", "CANCELLED", "FAILED"]:
                return status_data

            time.sleep(15)  # Wait 15 seconds before next check

        except requests.exceptions.RequestException as e:
            print(f"Error tracking deposit status: {e}")
            time.sleep(15)
            continue

    print(f"Timeout waiting for deposit status after {max_wait_time} seconds")
    return {"timeout": True, "last_status": status if 'status' in locals() else "UNKNOWN"}


def validate_solana_address(address):
    """Basic validation for Solana address format"""
    if not address or len(address) < 32 or len(address) > 44:
        return False
    # Solana addresses are base58 encoded and typically 32-44 characters
    try:
        # Basic check - should be alphanumeric with some specific chars
        allowed_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        return all(c in allowed_chars for c in address)
    except:
        return False


# Main execution
results = []
inbound_address_base = get_inbound_address(BASE_CHAIN_ID)

if not inbound_address_base:
    print(f"Error: Inbound address for Base chain ID {BASE_CHAIN_ID} not found.")
    exit()

print(f"Using Gas.zip inbound address: {inbound_address_base}")
print(f"Processing {len(SOLANA_WALLETS)} Solana wallets...")
print(f"\n💰 ETH Amount Configuration:")
print(f"  Minimum ETH per transaction: {MIN_ETH_AMOUNT} ETH")
print(f"  Maximum ETH per transaction: {MAX_ETH_AMOUNT} ETH")
print(f"\n⛽ Gas Configuration (EIP-1559):")
print(f"  Priority Fee Multiplier: {MAX_PRIORITY_FEE_MULTIPLIER}x")
print(f"  Max Fee Multiplier: {MAX_FEE_MULTIPLIER}x")

for i, solana_wallet in enumerate(SOLANA_WALLETS):
    print(f"\n{'=' * 60}")
    print(f"Processing wallet {i + 1}/{len(SOLANA_WALLETS)}: {solana_wallet}")

    # Validate Solana address
    if not validate_solana_address(solana_wallet):
        print(f"Warning: Invalid Solana address format: {solana_wallet}")
        results.append({
            "solana_wallet": solana_wallet,
            "status": "Skipped - Invalid Solana address format",
            "eth_amount": 0
        })
        continue

    # Random ETH amount between configured min and max
    eth_amount = random.uniform(MIN_ETH_AMOUNT, MAX_ETH_AMOUNT)
    eth_amount = max(eth_amount, MIN_ETH_AMOUNT)  # Ensure minimum
    eth_amount = min(eth_amount, MAX_ETH_AMOUNT)  # Ensure maximum
    print(f"Planning to send {eth_amount:.6f} ETH from Base to Solana wallet: {solana_wallet}")

    # Get calldata and quote for bridging
    deposit_amount_wei = web3.to_wei(eth_amount, 'ether')
    calldata_quote = get_gas_zip_calldata_quote(
        deposit_chain_id = BASE_CHAIN_ID,
        deposit_amount_wei = deposit_amount_wei,
        outbound_chain_id = SOLANA_CHAIN_ID,
        destination_address = solana_wallet,
        sender_address = account.address
    )

    if not calldata_quote:
        print("Could not get calldata quote. Skipping this wallet.")
        results.append({
            "solana_wallet": solana_wallet,
            "status": "Skipped - No calldata quote available",
            "eth_amount": eth_amount
        })
        continue

    calldata = calldata_quote.get("calldata")
    quotes = calldata_quote.get("quotes", [])

    if not calldata:
        print("No calldata received from Gas.zip. Skipping this wallet.")
        results.append({
            "solana_wallet": solana_wallet,
            "status": "Skipped - No calldata received",
            "eth_amount": eth_amount
        })
        continue

    print(f"Received calldata: {calldata}")
    if quotes:
        for quote in quotes:
            chain_id = quote.get("chain", "Unknown")
            expected_amount = quote.get("expected", "0")
            usd_value = quote.get("usd", 0)
            print(f"  Expected output on chain {chain_id}: {expected_amount} wei (~${usd_value:.4f})")

    # Send the bridging transaction
    try:
        print("Sending bridge transaction...")
        tx_hash = send_bridge_transaction(
            PRIVATE_KEY,
            account.address,
            eth_amount,
            inbound_address_base,
            calldata
        )
        print(f"Bridge transaction sent! Hash: {tx_hash}")
        print(f"Base explorer: https://basescan.org/tx/{tx_hash}")

        # Track the deposit status
        print("Tracking deposit status...")
        deposit_status = track_deposit_status(tx_hash)

        result_entry = {
            "solana_wallet": solana_wallet,
            "eth_amount": eth_amount,
            "base_tx_hash": tx_hash,
            "calldata": calldata,
            "quotes": quotes,
            "deposit_status": deposit_status
        }

        # Check if bridging was successful
        if deposit_status and not deposit_status.get("timeout"):
            final_status = deposit_status.get("deposit", {}).get("status", "UNKNOWN")
            result_entry["final_status"] = final_status

            outbound_txs = deposit_status.get("outbound", [])
            if outbound_txs:
                result_entry["solana_tx_hashes"] = [tx.get("hash") for tx in outbound_txs]
                print(f"✅ Bridge completed! Solana transaction(s): {result_entry['solana_tx_hashes']}")
            else:
                print(f"⚠️  Bridge status: {final_status} (no outbound transactions yet)")
        else:
            result_entry["final_status"] = "TIMEOUT_OR_ERROR"
            print("❌ Bridge tracking timed out or failed")

        results.append(result_entry)

    except Exception as e:
        print(f"❌ Error sending bridge transaction for {solana_wallet}: {e}")
        results.append({
            "solana_wallet": solana_wallet,
            "eth_amount": eth_amount,
            "status": f"Failed to send transaction: {str(e)}"
        })

    # Add delay between transactions to avoid rate limiting
    if i < len(SOLANA_WALLETS) - 1:
        print("Waiting 10 seconds before next transaction...")
        time.sleep(10)

# Save results to file
output_file = "bridge_results.json"
with open(output_file, "w") as f:
    json.dump(results, f, indent = 4)

print(f"\n{'=' * 60}")
print("🎉 Script completed!")
print(f"Results saved to {output_file}")

# Summary
successful_bridges = sum(1 for r in results if r.get("final_status") == "CONFIRMED")
failed_bridges = sum(
    1 for r in results if "Failed" in r.get("status", "") or r.get("final_status") in ["FAILED", "CANCELLED"])
pending_bridges = len(results) - successful_bridges - failed_bridges

print(f"\nSummary:")
print(f"  ✅ Successful bridges: {successful_bridges}")
print(f"  ❌ Failed bridges: {failed_bridges}")
print(f"  ⏳ Pending/Timeout bridges: {pending_bridges}")
print(f"  📊 Total processed: {len(results)}")

if successful_bridges > 0:
    print(f"\n🎯 Successfully bridged ETH from Base to {successful_bridges} Solana wallet(s)!")
