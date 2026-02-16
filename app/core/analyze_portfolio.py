import csv
import collections
import urllib.request
import json
import statistics
from datetime import datetime
import sys
import os
import ssl

# Fix for SSL: CERTIFICATE_VERIFY_FAILED
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- Configuration ---
# Valid assets to track (ignoring small dust or fiat unless specified)
TRACKED_ASSETS = ['BTC', 'ETH', 'SOL', 'PEPE', 'DOT', 'ADA', 'XRP', 'LTC', 'USDG', 'DOGE'] 
FIAT_ASSETS = ['EUR', 'EUR.HOLD', 'USD']

# ANSI Colors
class Color:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_colored(text, color):
    print(f"{color}{text}{Color.ENDC}")

# --- Data Structures ---
Transaction = collections.namedtuple('Transaction', ['txid', 'refid', 'time', 'type', 'subtype', 'aclass', 'asset', 'amount', 'fee', 'balance'])

def validate_kraken_ledger(filepath):
    """Checks if the CSV has the required Kraken columns."""
    required_columns = {'txid', 'refid', 'time', 'type', 'asset', 'amount'}
    try:
        with open(filepath, mode='r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            if not reader.fieldnames:
                return False, "Empty CSV file."
            
            # Normalize fieldnames to lowercase/stripped for comparison
            headers = {h.strip().replace('"', '').lower() for h in reader.fieldnames if h}
            missing = required_columns - headers
            
            if missing:
                return False, f"Missing columns: {', '.join(missing)}"
            
            return True, "Valid Kraken Ledger"
    except Exception as e:
        return False, str(e)

def validate_wallet_csv(filepath):
    """Checks if the CSV has the required Wallet export columns."""
    # Trezor Suite export usually has: Date, Type, Amount (in some form)
    # Based on load_wallet_csv, we need 'Type', 'Amount', 'Date' (case sensitive in load function but lets be flexible here or strict based on usage)
    # The load function uses: row.get('Type'), row.get('Amount'), row.get('Date')
    
    required_columns = {'Date', 'Type', 'Amount'} # Case sensitive matching load_wallet_csv
    try:
        with open(filepath, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            if not reader.fieldnames:
                 return False, "Empty CSV file."
            
            headers = {h.strip().replace('"', '') for h in reader.fieldnames if h}
            
            # Check for intersection. Since wallet exports vary, we check if we have matching subsets
            # Or strict? The user said "Trezor Suite CSV exports".
            # Let's check if ALL required are present.
            
            missing = required_columns - headers
            if missing:
                return False, f"Missing columns: {', '.join(missing)}. Ensure this is a Trezor Suite export."
                
            return True, "Valid Wallet CSV"
            
    except Exception as e:
        return False, str(e)

def parse_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def load_csv(filepath):
    transactions = []
    try:
        with open(filepath, mode='r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Basic cleaning
                for key, val in row.items():
                    row[key] = val.strip().replace('"', '')
                
                t = Transaction(
                    txid=row['txid'],
                    refid=row['refid'],
                    time=row['time'],
                    type=row['type'],
                    subtype=row['subtype'],
                    aclass=row['aclass'],
                    asset=row['asset'],
                    amount=parse_float(row['amount']),
                    fee=parse_float(row['fee']),
                    balance=parse_float(row['balance'])
                )
                transactions.append(t)
    except FileNotFoundError:
        print_colored(f"Error: File '{filepath}' not found.", Color.FAIL)
        sys.exit(1)
    return transactions

def get_crypto_prices(assets):
    # Kraken API public ticker
    # Mapping some common names to Kraken pairs (simple mapping)
    # Note: Kraken uses specific pair names (e.g., XXBTZEUR for BTC/EUR)
    # We will try to fetch generic pairs.
    
    mapping = {
        'BTC': 'XXBTZEUR',
        'ETH': 'XETHZEUR',
        'SOL': 'SOLEUR',
        'PEPE': 'PEPEEUR',
        'LTC': 'XLTCZEUR',
        'DOGE': 'XDGEUR',
        'USDG': 'USDGUSD' 
    }
    
    prices = {}
    
    # Construct comma-separated pair list
    pairs = []
    reverse_map = {}
    for asset in assets:
        if asset in mapping:
            pair = mapping[asset]
            pairs.append(pair)
            reverse_map[pair] = asset
        else:
            # Try generic construction
            pair = asset + 'EUR'
            pairs.append(pair)
            reverse_map[pair] = asset

    if not pairs:
        return {}

    # Try batch first
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={','.join(pairs)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            if 'error' in data and data['error']:
                # If batch fails, try individual
                print_colored(f"Batch API failed ({data['error']}), trying individual pairs...", Color.WARNING)
                raise ValueError("Batch failed")
            
            if 'result' in data:
                # Process batch results (same logic as before)
                for pair, details in data['result'].items():
                     price = float(details['c'][0])
                     found_asset = reverse_map.get(pair)
                     if not found_asset:
                         for p_req, a_req in reverse_map.items():
                            if p_req in pair or pair in p_req:
                                found_asset = a_req
                                break
                     if found_asset:
                         prices[found_asset] = price

    except Exception:
        # Fallback: Individual Requests
        for asset in assets:
            pair = mapping.get(asset, asset + 'EUR')
            url = f"https://api.kraken.com/0/public/Ticker?pair={pair}"
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read().decode())
                    if 'result' in data:
                        for _, details in data['result'].items():
                            prices[asset] = float(details['c'][0])
                            print(f"Fetched {asset}: €{prices[asset]}")
            except Exception as e:
                print(f"Failed to fetch {asset} ({pair}): {e}")

    return prices

def analyze_portfolio(transactions):
    portfolio = collections.defaultdict(lambda: {'amount': 0.0, 'fees_paid': 0.0, 'rewards': 0.0, 'buy_cost': 0.0, 'buy_amt': 0.0, 'withdrawn': 0.0})
    
    # Group by RefID to handle trades (Source Currency -> Target Currency)
    # A trade usually involves two rows with same RefID: one negative amount (sell), one positive (buy).
    # However, fees might be a separate entry or included.
    
    # Simplification: We will track net EUR flow for "Cost Basis".
    # For every Crypto 'Buy' (positive amount), we look for corresponding EUR 'Spend' (negative amount).
    
    tx_by_refid = collections.defaultdict(list)
    for t in transactions:
        tx_by_refid[t.refid].append(t)
        
    # 1. Total Holdings & Rewards
    for t in transactions:
        if t.asset in FIAT_ASSETS:
             portfolio['EUR']['amount'] += t.amount # Net EUR flow
             continue

        if t.asset not in TRACKED_ASSETS and t.amount < 0.0000001: continue # Skip dust
        
        portfolio[t.asset]['amount'] += t.amount
        portfolio[t.asset]['fees_paid'] += t.fee
        
        if t.type in ['earn', 'reward']:
             portfolio[t.asset]['rewards'] += t.amount
             
        # Track withdrawals (Moved to Wallet)
        if t.type == 'withdrawal':
            portfolio[t.asset]['withdrawn'] += abs(t.amount)

    # 2. Approximate Cost Basis (EUR Spent on Buys)
    # We look at 'trade' groups.
    for refid, group in tx_by_refid.items():
        # Identify if this is a buy order
        # Criteria: Positive Crypto Amount AND Negative Fiat Amount
        crypto_tx = None
        fiat_tx = None
        
        for t in group:
            if t.asset in TRACKED_ASSETS and t.amount > 0 and t.type == 'trade':
                crypto_tx = t
            if t.asset in FIAT_ASSETS and t.amount < 0:
                fiat_tx = t
        
        if crypto_tx and fiat_tx:
            # We found a buy formatted transaction
            
            # --- CALCULATION LOGIC EXPLAINED ---
            # To calculate "Cost Basis" (How much EUR we put in):
            # We look for a 'Trade' where we gained Crypto (Positive) and lost EUR (Negative).
            # The amount of EUR lost is our 'Cost'.
            # Note: Kraken 'Spend' usually includes the fee.
            
            cost = abs(fiat_tx.amount) 
            
            # Add to the total cost for this asset
            portfolio[crypto_tx.asset]['buy_cost'] += cost
            
            # --- AVERAGE PRICE LOGIC ---
            # To calculate the true "Average Buy Price", we must track the TOTAL amount
            # of coins we ever bought, regardless of whether we sold or withdrew them later.
            # Avg Price = Total EUR Spent / Total Coins Bought
            portfolio[crypto_tx.asset]['buy_amt'] += crypto_tx.amount 

    return portfolio

def run_dca_scenarios(asset, current_holdings, cost_basis, total_bought, current_price, scenarios=[100, 200, 500, 1000, 2000], print_output=True):
    if print_output:
        print_colored(f"\n--- Scenario Analysis: Averaging Down {asset} ---", Color.CYAN)
    
    # --- CALCULATION ---
    # Avg Price = Total EUR Spent (cost_basis) / Total Coins Bought (total_bought)
    avg_price = cost_basis / total_bought if total_bought > 0 else 0
    
    dca_data = {
        'asset': asset,
        'total_bought': total_bought,
        'total_cost': cost_basis,
        'current_avg_price': avg_price,
        'current_market_price': current_price,
        'is_profit': current_price >= avg_price,
        'scenarios': []
    }

    if print_output:
        print(f"Total BTC Bought:    {total_bought:,.6f} (This is the sum of all your 'Buy' orders)")
        print(f"Total Cost Basis:    €{cost_basis:,.2f}  (This is the sum of all EUR spent on those orders)")
        print(f"Current Avg Price:   {Color.BOLD}€{avg_price:,.2f}{Color.ENDC}  (Cost Basis / Total Bought)")
        print(f"Current Market Price: {Color.BOLD}€{current_price:,.2f}{Color.ENDC}")
        
        if dca_data['is_profit']:
            print_colored("You are currently in profit on your historical buys. Averaging UP.", Color.GREEN)
        else:
            print_colored("You are currently in loss on your historical buys. Averaging DOWN.", Color.WARNING)

        print("\nImpact of new purchases:")
        print(f"{'Invest (€)':<12} | {'Buy Amount':<12} | {'New Total BTC':<15} | {'New Avg Price':<15} | {'Reduction %':<10}")
        print("-" * 75)
    
    # Data for plotting
    plot_data = [] # (investment, new_avg_price)
    plot_data.append((0, avg_price))
    
    for invest_amount in scenarios:
        # Assume 0.26% fee
        fee = invest_amount * 0.0026
        net_invest = invest_amount - fee
        amount_bought = net_invest / current_price
        
        new_total_cost = cost_basis + invest_amount
        new_total_bought = total_bought + amount_bought 
        
        new_avg_price = new_total_cost / new_total_bought
        
        reduction = ((avg_price - new_avg_price) / avg_price) * 100
        
        scenario_result = {
            'investment': invest_amount,
            'buy_amount': amount_bought,
            'new_total_btc': new_total_bought,
            'new_avg_price': new_avg_price,
            'reduction_percent': reduction
        }
        dca_data['scenarios'].append(scenario_result)
        
        if print_output:
            color = Color.GREEN if new_avg_price < avg_price else Color.FAIL
            print(f"€{invest_amount:<11,.0f} | {amount_bought:<12.6f} | {new_total_bought:<15.6f} | {color}€{new_avg_price:<14,.2f}{Color.ENDC} | {reduction:.2f}%")
        
        plot_data.append((invest_amount, new_avg_price))
        
    return plot_data, dca_data

def generate_charts(portfolio_data, dca_data_btc, prices, dca_summary=None, output_dir='data'):
    """
    Generate two separate chart images:
    1. portfolio_summary.png - Pie, Bar, and Portfolio Table
    2. dca_analysis.png - Stats text, Line Chart, Scenario Table (only if BTC data exists)
    
    Returns a list of generated file paths.
    """
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
        from pandas.plotting import table as mpl_table
    except ImportError:
        print_colored("\nWarning: matplotlib or pandas not found. Skipping charts.", Color.WARNING)
        return []

    os.makedirs(output_dir, exist_ok=True)
    plt.style.use('dark_background')
    chart_paths = []

    # --- Helper: Format Function ---
    def fmt(x, currency=True, decimals=2):
        if currency:
            return f"€{x:,.{decimals}f}"
        return f"{x:,.{decimals}f}"

    # ========================================================
    # IMAGE 1: Portfolio Summary
    # ========================================================
    fig1 = plt.figure(figsize=(14, 14))
    fig1.suptitle('📊 Portfolio Summary', fontsize=20, color='white', y=0.98)
    grid1 = plt.GridSpec(2, 2, hspace=0.35, wspace=0.25, height_ratios=[1, 1.5])

    # -- Pie Chart (Top Left) --
    ax_pie = fig1.add_subplot(grid1[0, 0])
    labels, values = [], []
    for asset, data in portfolio_data.items():
        if asset == 'EUR' or data['amount'] <= 0.0001: continue
        price = prices.get(asset, 0)
        value = data['amount'] * price
        if value > 1.0:
            labels.append(asset)
            values.append(value)
    if values:
        ax_pie.pie(values, labels=labels, autopct='%1.1f%%', startangle=140,
                   colors=plt.cm.Paired.colors, textprops={'color': 'w'})
        ax_pie.set_title('Value Distribution', fontsize=14)

    # -- Bar Chart (Top Right) --
    ax_bar = fig1.add_subplot(grid1[0, 1])
    bar_assets, bar_costs, bar_vals = [], [], []
    for asset, data in portfolio_data.items():
        if asset == 'EUR' or data['amount'] <= 0.0001: continue
        price = prices.get(asset, 0)
        val = data['amount'] * price
        if val > 10.0:
            bar_assets.append(asset)
            bar_costs.append(data['buy_cost'])
            bar_vals.append(val)
    if bar_assets:
        x = range(len(bar_assets))
        w = 0.35
        ax_bar.bar([i - w/2 for i in x], bar_costs, w, label='Cost', color='#ff6b6b')
        ax_bar.bar([i + w/2 for i in x], bar_vals, w, label='Value', color='#51cf66')
        ax_bar.set_xticks(x)
        ax_bar.set_xticklabels(bar_assets)
        ax_bar.legend()
        ax_bar.set_title('Cost vs Value', fontsize=14)
        ax_bar.grid(axis='y', linestyle='--', alpha=0.3)
        ax_bar.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, p: f"€{int(x):,}"))

    # -- Portfolio Table (Bottom, spans both columns) --
    ax_tbl = fig1.add_subplot(grid1[1, :])
    ax_tbl.axis('off')
    ax_tbl.set_title('Holdings Detail', fontsize=14, pad=10)

    tbl_rows = []
    total_val_sum, total_cost_sum = 0.0, 0.0
    for asset in sorted(portfolio_data.keys()):
        data = portfolio_data[asset]
        if asset == 'EUR': continue
        if data['amount'] < 0.000001 and data['withdrawn'] < 0.000001: continue
        price = prices.get(asset, 0)
        val = data['amount'] * price
        cost = data['buy_cost']
        pl = val - cost
        total_val_sum += val
        total_cost_sum += cost
        tbl_rows.append([
            asset,
            fmt(data['amount'], False, 5),
            fmt(price), fmt(val), fmt(cost), fmt(pl),
            fmt(data['rewards'], False, 5),
            fmt(data['withdrawn'], False, 5)
        ])

    # Add totals row
    net_pl = total_val_sum - total_cost_sum
    tbl_rows.append([
        'TOTAL', '', '',
        fmt(total_val_sum), fmt(total_cost_sum), fmt(net_pl),
        '', ''
    ])

    df = pd.DataFrame(tbl_rows, columns=['Asset', 'Balance', 'Price', 'Value', 'Cost', 'P/L', 'Rewards', 'Wallet'])
    if not df.empty:
        t = mpl_table(ax_tbl, df, loc='center', cellLoc='center',
                      colWidths=[0.08, 0.14, 0.12, 0.12, 0.12, 0.12, 0.14, 0.14])
        t.auto_set_font_size(False)
        t.set_fontsize(10)
        t.scale(1.1, 1.8)
        for (row, col), cell in t.get_celld().items():
            cell.set_edgecolor('#555555')
            if row == 0:  # header
                cell.set_facecolor('#2a2a2a')
                cell.set_text_props(color='white', weight='bold')
            elif row == len(tbl_rows):  # totals row
                cell.set_facecolor('#1a1a2e')
                cell.set_text_props(color='#ffd43b', weight='bold')
            else:
                cell.set_facecolor('none')
                cell.set_text_props(color='white')
                if col == 5:  # P/L column
                    txt = cell.get_text().get_text().replace('€', '').replace(',', '')
                    try:
                        if float(txt) >= 0:
                            cell.set_text_props(color='#51cf66', weight='bold')
                        else:
                            cell.set_text_props(color='#ff6b6b', weight='bold')
                    except: pass

    fig1.tight_layout(rect=[0, 0, 1, 0.96])
    path1 = os.path.join(output_dir, 'portfolio_summary.png')
    fig1.savefig(path1, dpi=150, bbox_inches='tight')
    plt.close(fig1)
    chart_paths.append(os.path.abspath(path1))
    print_colored(f"Portfolio chart saved to {os.path.abspath(path1)}", Color.GREEN)

    # ========================================================
    # IMAGE 2: DCA Analysis (only if BTC data)
    # ========================================================
    if dca_data_btc and dca_summary:
        fig2 = plt.figure(figsize=(12, 14))
        fig2.suptitle('📉 DCA Scenario Analysis: BTC', fontsize=20, color='white', y=0.98)
        grid2 = plt.GridSpec(3, 1, hspace=0.4, height_ratios=[0.8, 1.5, 1])

        # -- Row 1: Stats Text Box --
        ax_stats = fig2.add_subplot(grid2[0])
        ax_stats.axis('off')

        status_text = "Averaging UP ▲" if dca_summary['is_profit'] else "Averaging DOWN ▼"
        status_color = '#51cf66' if dca_summary['is_profit'] else '#ff6b6b'

        stats_lines = [
            f"Total BTC Bought:     {dca_summary['total_bought']:,.6f}",
            f"Total Cost Basis:     €{dca_summary['total_cost']:,.2f}",
            f"Current Avg Price:    €{dca_summary['current_avg_price']:,.2f}",
            f"Current Market Price: €{dca_summary['current_market_price']:,.2f}",
        ]
        stats_text = "\n".join(stats_lines)

        # Background box
        ax_stats.text(0.5, 0.65, stats_text, transform=ax_stats.transAxes,
                      fontsize=13, color='white', family='monospace',
                      ha='center', va='center',
                      bbox=dict(boxstyle='round,pad=0.8', facecolor='#1a1a2e', edgecolor='#555555', alpha=0.9))
        ax_stats.text(0.5, 0.1, f"Status: {status_text}", transform=ax_stats.transAxes,
                      fontsize=15, color=status_color, weight='bold',
                      ha='center', va='center')

        # -- Row 2: Line Chart --
        ax_line = fig2.add_subplot(grid2[1])
        investments, new_prices = zip(*dca_data_btc)
        ax_line.plot(investments, new_prices, marker='o', linestyle='-', color='#339af0', linewidth=2.5, markersize=8)
        current_avg = new_prices[0]
        ax_line.axhline(y=current_avg, color='#ffd43b', linestyle='--', alpha=0.6, label='Current Avg')
        ax_line.set_title('Impact of Additional Investment', fontsize=14)
        ax_line.set_xlabel('Additional Investment', fontsize=12)
        ax_line.set_ylabel('New Average Price', fontsize=12)
        ax_line.grid(True, linestyle='--', alpha=0.3)
        ax_line.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, p: f"€{int(x):,}"))
        ax_line.get_xaxis().set_major_formatter(plt.FuncFormatter(lambda x, p: f"€{int(x):,}"))
        ax_line.legend()
        for i, price in enumerate(new_prices):
            ax_line.annotate(f'€{price:,.0f}', (investments[i], price),
                             textcoords="offset points", xytext=(0, 12), ha='center', color='white', fontsize=9)

        # -- Row 3: Scenario Table --
        ax_dca_tbl = fig2.add_subplot(grid2[2])
        ax_dca_tbl.axis('off')
        ax_dca_tbl.set_title('Scenario Breakdown', fontsize=14, pad=10)

        base_price = new_prices[0]
        dca_rows = []
        for s in dca_summary.get('scenarios', []):
            reduction = s['reduction_percent']
            dca_rows.append([
                fmt(s['investment'], True, 0),
                fmt(s['buy_amount'], False, 6),
                fmt(s['new_total_btc'], False, 6),
                fmt(s['new_avg_price'], True, 2),
                f"{reduction:.2f}%"
            ])

        df_dca = pd.DataFrame(dca_rows, columns=['Invest', 'Buy Amt', 'New Total', 'New Avg Price', 'Reduction'])
        if not df_dca.empty:
            t2 = mpl_table(ax_dca_tbl, df_dca, loc='center', cellLoc='center',
                           colWidths=[0.15, 0.18, 0.18, 0.18, 0.15])
            t2.auto_set_font_size(False)
            t2.set_fontsize(11)
            t2.scale(1, 1.8)
            for (row, col), cell in t2.get_celld().items():
                cell.set_edgecolor('#555555')
                if row == 0:
                    cell.set_facecolor('#2a2a2a')
                    cell.set_text_props(color='white', weight='bold')
                else:
                    cell.set_facecolor('none')
                    cell.set_text_props(color='white')

        fig2.tight_layout(rect=[0, 0, 1, 0.96])
        path2 = os.path.join(output_dir, 'dca_analysis.png')
        fig2.savefig(path2, dpi=150, bbox_inches='tight')
        plt.close(fig2)
        chart_paths.append(os.path.abspath(path2))
        print_colored(f"DCA chart saved to {os.path.abspath(path2)}", Color.GREEN)

    return chart_paths

def print_glossary():
    glossary = (
        "Asset:       The specific cryptocurrency symbol (e.g., BTC, ETH).\n"
        "Balance:     Total amount of coins currently in your account.\n"
        "Price (€):   Current market price for ONE single coin.\n"
        "Value (€):   Total value of your holdings (Balance × Price).\n"
        "Cost Basis:  Total Euros you originally spent to buy these specific coins.\n"
        "               * calculation: Sum of all historical 'Spend' EUR amounts.\n"
        "P/L (€):     Profit or Loss (Value - Cost Basis).\n"
        "               * Green: Profit.\n"
        "               * Red:   Loss.\n"
        "Rewards:     Coins earned from passive income (Staking, Earn, Airdrops), not bought.\n"
        "Wallet:      Total coins moved/withdrawn to your private wallet.\n\n"
        "--- DCA (Averaging Down) Explained ---\n"
        "If you bought Bitcoin at a high price, your 'Average Buy Price' is high.\n"
        "Buying more now (at a lower price) lowers that average.\n"
        "New Avg Price:  (Old Total Cost + New Investment) / (Old Total Coins + New Coins)\n"
        "Reduction %:    How much your break-even price drops by investing this amount."
    )
    print_colored("\n=== 📊 REPORT GUIDE: COLUMN DEFINITIONS ===", Color.HEADER)
    print(glossary)

def load_wallet_csv(filepath):
    """Loads receiver transactions from a wallet CSV."""
    txs = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Filter for Received transactions
                    # Trezor Suite: "Type" == "Recv", "Amount", "Date"
                    # We accept "RECV" or "Recv" (case insensitive check might be safer but stick to observed)
                    r_type = row.get('Type', '').upper()
                    if 'RECV' in r_type or 'RECEIVED' in r_type:
                        amount = float(row.get('Amount', 0))
                        date_str = row.get('Date', '')
                        # Simple date matching: just keep the string or parse if needed
                        txs.append({'amount': amount, 'date': date_str, 'found': False})
                except ValueError:
                    continue
    except Exception as e:
        print_colored(f"Error reading wallet CSV: {e}", Color.WARNING)
    return txs

def verify_withdrawals(kraken_txs, wallet_txs, print_output=True):
    """Checks if Kraken BTC withdrawals appear in the Wallet CSV."""
    
    # Filter Kraken BTC Withdrawals
    kraken_withdrawals = [t for t in kraken_txs if t.asset == 'BTC' and t.type == 'withdrawal']
    
    verification_results = {
        'matches': [],
        'orphans': [],
        'totals': {}
    }
    
    if print_output:
        print_colored(f"\n=== 🛡️ WALLET VERIFICATION ===", Color.HEADER)
        print(f"{'Kraken Date':<20} | {'Amount (BTC)':<14} | {'Status':<20} | {'Wallet Match'}")
        print("-" * 80)
    
    for kt in kraken_withdrawals:
        k_amount = abs(kt.amount)
        status = "Not Found ❌"
        status_color = Color.FAIL
        match_info = ""
        
        # Look for a match in wallet_txs
        best_match = None
        for wt in wallet_txs:
            if wt['found']: continue 
            
            # 1. Exact match
            diff = abs(wt['amount'] - k_amount)
            if diff < 0.00000001: 
                best_match = wt
                break
            
            # 2. Match with fee (sometimes Kraken withdrawal fee is deducted from amount or separate)
            # Standard Kraken BTC fee is 0.00001 or similar. 
            # Let's verify against common fee subtracted: amount - 0.00001 
            # But here k_amount is from ledger. Ledger usually shows [ -Amount ] [ -Fee ].
            # If ledger amount is gross, wallet receives net. 
            if abs(wt['amount'] - (k_amount - 0.00001)) < 0.000001:
                 best_match = wt
                 break
            if abs(wt['amount'] - (k_amount - 0.00002)) < 0.000001:
                 best_match = wt
                 break
                 
        if best_match:
            status = "Verified ✅"
            status_color = Color.GREEN
            match_info = f"Found: {best_match['amount']} on {best_match['date']}"
            best_match['found'] = True 
            
            verification_results['matches'].append({
                'kraken_date': kt.time,
                'amount': k_amount,
                'wallet_date': best_match['date'],
                'wallet_amount': best_match['amount']
            })
        
        if print_output:
            print(f"{kt.time:<20} | {k_amount:<14.8f} | {status_color}{status:<20}{Color.ENDC} | {match_info}")

    # --- Totals Reconciliation ---
    total_kraken_out = sum(abs(t.amount) for t in kraken_withdrawals)
    total_wallet_in = sum(t['amount'] for t in wallet_txs)
    diff = total_wallet_in - total_kraken_out
    
    verification_results['totals'] = {
        'kraken_out': total_kraken_out,
        'wallet_in': total_wallet_in,
        'diff': diff
    }
    
    if print_output:
        print("-" * 80)
        print(f"{'TOTALS':<20} | {'Kraken Out':<14} | {'Wallet In':<14} | {'Difference'}")
        print(f"{'':<20} | {total_kraken_out:<14.8f} | {total_wallet_in:<14.8f} | {diff:+.8f}")
        
        if abs(diff) > 0.0001:
            print_colored(f"\n⚠️ Mismatch Detected: {diff:+.8f} BTC", Color.WARNING)
            print("Possible reasons:\n1. Missing Kraken transactions (e.g. older history not exported).\n2. Deposits from other sources (not Kraken).\n3. Fees deducted differently.")
        else:
            print_colored("\n✅ Totals Match perfectly!", Color.GREEN)

    # --- Orphan Wallet Transactions ---
    orphans = [t for t in wallet_txs if not t['found']]
    verification_results['orphans'] = orphans
    
    if print_output and orphans:
        print_colored(f"\n⚠️ FOUND IN WALLET BUT NOT IN KRAKEN ({len(orphans)}):", Color.WARNING)
        print(f"{'Wallet Date':<20} | {'Amount (BTC)':<14}")
        print("-" * 40)
        for t in orphans:
             print(f"{t['date']:<20} | {t['amount']:<14.8f}")
             
        print_colored("These transactions account for the difference shown above.", Color.CYAN)
        
    return verification_results

def generate_analysis_report(ledger_path, wallet_path=None, output_dir='data'):
    """
    Analyzes the portfolio and returns a dictionary with all data.
    Used by both CLI and Bot.
    """
    report = {}
    
    # 1. Load Data
    transactions = load_csv(ledger_path)
    report['transactions_count'] = len(transactions)
    
    # 2. Process Portfolio
    portfolio = analyze_portfolio(transactions)
    
    # 3. Fetch Prices
    assets_held = [a for a, d in portfolio.items() if (d['amount'] > 0 or d['withdrawn'] > 0) and a not in FIAT_ASSETS]
    prices = get_crypto_prices(assets_held)
    
    # 4. Build Summary Data
    summary_data = []
    total_value = 0.0
    total_cost = 0.0
    dca_btc_data = []
    
    for asset in sorted(assets_held):
        data = portfolio[asset]
        balance = data['amount']
        withdrawn = data['withdrawn']
        
        if balance < 0.000001 and withdrawn < 0.000001: continue
        
        current_price = prices.get(asset, 0)
        current_value = balance * current_price
        cost_basis = data['buy_cost']
        pl_euro = current_value - cost_basis
        
        asset_info = {
            'asset': asset,
            'balance': balance,
            'price': current_price,
            'value': current_value,
            'cost_basis': cost_basis,
            'pl_euro': pl_euro,
            'rewards': data['rewards'],
            'withdrawn': withdrawn
        }
        summary_data.append(asset_info)
        
        total_value += current_value
        total_cost += cost_basis
        
        # Calculate DCA data for BTC but don't print
        if asset == 'BTC' and current_price > 0:
              pass
 
    report['portfolio'] = summary_data
    report['total_value'] = total_value
    report['total_cost'] = total_cost
    report['net_pl'] = total_value - total_cost
    
    # 5. Charts
    btc_data = portfolio['BTC']
    btc_price = prices.get('BTC', 0)
    dca_plot_data = []
    dca_summary = None
    
    if btc_price > 0:
        dca_plot_data, dca_summary = run_dca_scenarios('BTC', btc_data['amount'], btc_data['buy_cost'], btc_data['buy_amt'], btc_price, print_output=False)
        report['dca_analysis'] = dca_summary
    else:
        report['dca_analysis'] = None
    
    # Save charts (returns list of paths)
    chart_paths = generate_charts(portfolio, dca_plot_data, prices, dca_summary=dca_summary, output_dir=output_dir)
    report['chart_paths'] = chart_paths
    
    # 6. Wallet Verification
    if wallet_path and os.path.exists(wallet_path):
        wallet_txs = load_wallet_csv(wallet_path)
        report['wallet_verification'] = verify_withdrawals(transactions, wallet_txs, print_output=False)
        
    return report

# --- Main Execution ---
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze Kraken Portfolio and Verify Trezor Wallet.')
    parser.add_argument('ledger', help='Path to Kraken Ledger CSV')
    parser.add_argument('--wallet', help='Path to Trezor Wallet CSV (optional)', default=None)
    
    args = parser.parse_args()
    
    print_colored(f"Analyzing {args.ledger}...", Color.HEADER)
    
    # 1. Load Data
    transactions = load_csv(args.ledger)
    
    # 2. Process
    portfolio = analyze_portfolio(transactions)
    
    # 3. Prices
    print("Fetching current market prices...")
    assets_held = [a for a, d in portfolio.items() if (d['amount'] > 0 or d['withdrawn'] > 0) and a not in FIAT_ASSETS]
    prices = get_crypto_prices(assets_held)
    
    # 4. Print Report (Manual Printing for CLI fidelity)
    print_colored("\n=== PORTFOLIO SUMMARY ===", Color.HEADER)
    print(f"{'Asset':<6} | {'Balance':<12} | {'Price (€)':<10} | {'Value (€)':<12} | {'Cost Basis':<12} | {'P/L (€)':<10} | {'Rewards':<10} | {'Wallet':<12}")
    print("-" * 105)
    
    total_val = 0
    total_cost = 0
    dca_btc = []
    
    for asset in sorted(assets_held):
        data = portfolio[asset]
        if data['amount'] < 0.000001 and data['withdrawn'] < 0.000001: continue
        
        price = prices.get(asset, 0)
        val = data['amount'] * price
        cost = data['buy_cost']
        pl = val - cost
        
        total_val += val
        total_cost += cost
        
        pl_color = Color.GREEN if pl >= 0 else Color.FAIL
        print(f"{Color.BOLD}{asset:<6}{Color.ENDC} | {data['amount']:<12.5f} | {price:<10.2f} | {val:<12.2f} | {cost:<12.2f} | {pl_color}{pl:<10.2f}{Color.ENDC} | {data['rewards']:<10.5f} | {data['withdrawn']:<12.5f}")
        
        if asset == 'BTC' and price > 0:
            dca_btc = run_dca_scenarios(asset, data['amount'], cost, data['buy_amt'], price)

    print("-" * 105)
    print(f"Total Portfolio Value: {Color.BOLD}€{total_val:,.2f}{Color.ENDC}")
    print(f"Total Cost Basis:      €{total_cost:,.2f}")
    net = total_val - total_cost
    net_c = Color.GREEN if net >= 0 else Color.FAIL
    print(f"Net P/L:               {net_c}€{net:,.2f}{Color.ENDC}")

    # 5. Charts
    print_colored("\nGenerating Charts...", Color.BLUE)
    generate_charts(portfolio, dca_btc, prices)
    
    # 6. Glossary
    print_glossary()
    
    # 7. Wallet Verification
    if args.wallet and os.path.exists(args.wallet):
        wallet_txs = load_wallet_csv(args.wallet)
        verify_withdrawals(transactions, wallet_txs, print_output=True)

    print("\nDone.")




