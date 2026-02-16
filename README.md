# 📊 Kraken & Trezor Portfolio Auditing Bot

![Python](https://img.shields.io/badge/Python-3.12-blue) ![Docker](https://img.shields.io/badge/Docker-Enabled-blue) ![License](https://img.shields.io/badge/License-MIT-green)

A Dockerized Telegram bot that analyzes your **Kraken** ledger history and verifies your withdrawals against your **Trezor Suite** wallet export.

##  Features

*   **Portfolio Summary**: Calculates total holdings, cost basis, current value, and P/L (Profit/Loss).
*   **DCA Scenarios**: Simulates "Averaging Down" strategies for Bitcoin based on your historical cost basis.
*   **Wallet Reconciliation**: Automatically checks if your Kraken withdrawals actually arrived in your Trezor wallet.
*   **Orphan Detection**: Identifies transactions in your wallet history that are missing from your Kraken ledger.
*   **Interactive Charts**: Generates and sends portfolio visualizations directly in Telegram.
*   **Sentry Integration**: Optional error tracking for production reliability.

##  Project Structure

```text
.
├── Makefile             # Build & Run shortcuts
├── docker-compose.yml   # Docker orchestration
├── .env.example         # Config template
├── app/                 # Source code
│   ├── core/            # Analysis logic
│   └── bot.py           # Telegram bot
└── data/                # Persistent data storage
```

##  Running with Docker (Recommended)

### 1. Configuration
Create a `.env` file from the example:
```bash
cp .env.example .env
```
Open `.env` and fill in your details:
*   `TELEGRAM_TOKEN`: Get from [@BotFather](https://t.me/BotFather).
*   `SENTRY_DSN`: (Optional) Get from Sentry.io.

### 2. Run
Use the Makefile shortcuts:
```bash
make build
make run
```
Your bot is now live! Send `/start` to begin.

##  Running Locally (CLI)

You can also run the analysis script directly without the bot:

1.  Install dependencies:
    ```bash
    pip install -r app/requirements.txt
    ```
2.  Run the script:
    ```bash
    python3 app/core/analyze_portfolio.py path/to/kraken_ledger.csv --wallet path/to/wallet.csv
    ```
    *(Ensure your CSV files are in the correct path or modify the script)*

##  Usage Guide

1.  **Start**: Send `/start` to the bot.
2.  **Upload Ledger**: Send your **Kraken Ledger** CSV file.
3.  **Upload Wallet**: Send your **Trezor Suite** CSV file (or press **Skip**).
4.  **View Report**: The bot will generate a detailed text report and charts.

##  Notes
*   **Trezor Only**: The wallet verification feature is currently optimized for Trezor Suite CSV exports.
*   **Privacy**: All data is processed locally within your container. No data is sent to external servers (except Sentry if enabled).

