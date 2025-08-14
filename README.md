Base → Solana Sender via Gas.zip

Этот скрипт автоматизирует перевод ETH из сети Base на адреса кошельков Solana через сервис Gas.zip.

📌 Возможности

Читает приватный ключ отправителя из файла pk.txt.

Читает список Solana-кошельков из wallets.txt.

Для каждого кошелька:

Генерирует случайную сумму перевода в диапазоне 0.001–0.005 ETH.

Запрашивает котировку у API Gas.zip.

Отправляет ETH на inbound-адрес Gas.zip в сети Base.

Отслеживает статус депозита до подтверждения или отмены.

Сохраняет результат в transaction_results.json.

⚙️ Установка

Клонируйте репозиторий

git clone https://github.com/nta79/gas.zip_base_to_solana_sender.git
cd gas.zip_base_to_solana_sender


Создайте виртуальное окружение и установите зависимости

python3 -m venv venv
source venv/bin/activate  # для Linux/Mac
venv\Scripts\activate     # для Windows

pip install -r requirements.txt


Если файла requirements.txt нет, установите вручную:

pip install web3 eth-account requests


Создайте файл pk.txt с приватным ключом отправителя

0xВАШ_ПРИВАТНЫЙ_КЛЮЧ


Создайте файл wallets.txt с адресами Solana-кошельков

4Nd1mQZg...your_solana_wallet
7B2tgYxQ...another_wallet

🚀 Запуск
python send_tokens.py

📂 Структура проекта
send_tokens.py              # Основной скрипт
pk.txt                      # Приватный ключ (не храните публично!)
wallets.txt                 # Список Solana-адресов
transaction_results.json    # Результаты работы скрипта

🛠 Как это работает

Подключается к публичному RPC Base Mainnet (https://mainnet.base.org).

Запрашивает inbound-адрес для Base (0x391E7C679d29bD940d63be94AD22A25d25b5A604).

Получает котировку у Gas.zip API:

GET https://backend.gas.zip/v2/quotes/{deposit_chain_id}/{amount_wei}/{outbound_chain_id}


Отправляет ETH на inbound-адрес.

Проверяет статус депозита через:

GET https://backend.gas.zip/v2/deposit/{tx_hash}


Ждёт подтверждения или отмены, повторно проверяя каждые 10 секунд.

⚠️ Важные предупреждения

Не храните приватный ключ в публичном репозитории!

Перед запуском убедитесь, что у вас достаточно ETH в сети Base для переводов и газа.

Используйте собственный RPC-эндпоинт для Base для стабильной работы.
