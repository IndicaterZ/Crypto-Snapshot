import requests
import os
import concurrent.futures
from datetime import datetime, timezone, timedelta
from openpyxl import Workbook, load_workbook

EXCEL_FILE = "crypto_volume.xlsx"

def get_binance_th_top_5():
    try:
        # First get exchange info to find all THB pairs
        exchange_info = requests.get('https://api.binance.th/api/v1/exchangeInfo')
        exchange_info.raise_for_status()
        symbols = [s['symbol'] for s in exchange_info.json()['symbols'] if s['symbol'].endswith('THB')]
        
        # Function to get ticker for a single symbol
        def fetch_ticker(symbol):
            try:
                resp = requests.get(f'https://api.binance.th/api/v1/ticker/24hr?symbol={symbol}')
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                print(f"Failed to fetch {symbol}: {e}")
                return None
                
        # Fetch all tickers concurrently
        tickers = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetch_ticker, symbols)
            tickers = [t for t in results if t is not None]
        
        # Filter and parse THB pairs
        thb_pairs = []
        for t in tickers:
            try:
                t['quoteVolume'] = float(t['quoteVolume'])
                t['lastPrice'] = float(t.get('lastPrice', 0))
                thb_pairs.append(t)
            except (ValueError, KeyError):
                continue
        
        # Sort by quoteVolume descending
        thb_pairs.sort(key=lambda x: x['quoteVolume'], reverse=True)
        top_5 = thb_pairs[:5]
        
        results = []
        for i, pair in enumerate(top_5):
            results.append({
                'Exchange': 'Binance TH',
                'Rank': i + 1,
                'Symbol': pair['symbol'],
                'Volume (THB)': pair['quoteVolume'],
                'Price (THB)': pair['lastPrice']
            })
        return results
    except Exception as e:
        print(f"Error fetching Binance TH data: {e}")
        return []

def get_bitkub_top_5():
    try:
        response = requests.get('https://api.bitkub.com/api/market/ticker')
        response.raise_for_status()
        data = response.json()
        
        thb_pairs = []
        for symbol, info in data.items():
            if symbol.startswith('THB_'):
                try:
                    quote_vol = float(info['quoteVolume'])
                    last_price = float(info['last'])
                    thb_pairs.append({
                        'symbol': symbol,
                        'quoteVolume': quote_vol,
                        'lastPrice': last_price
                    })
                except (ValueError, KeyError):
                    continue
                    
        thb_pairs.sort(key=lambda x: x['quoteVolume'], reverse=True)
        top_5 = thb_pairs[:5]
        
        results = []
        for i, pair in enumerate(top_5):
            results.append({
                'Exchange': 'Bitkub',
                'Rank': i + 1,
                'Symbol': pair['symbol'],
                'Volume (THB)': pair['quoteVolume'],
                'Price (THB)': pair['lastPrice']
            })
        return results
    except Exception as e:
        print(f"Error fetching Bitkub data: {e}")
        return []

def save_to_excel(data):
    if os.path.exists(EXCEL_FILE):
        wb = load_workbook(EXCEL_FILE)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Volume Snapshot"
        headers = ["Date", "Exchange", "Rank", "Symbol", "Volume (THB)", "Price (THB)"]
        ws.append(headers)
    
    th_tz = timezone(timedelta(hours=7))
    current_time = datetime.now(th_tz).strftime("%Y-%m-%d %H:%M:%S")
    
    for item in data:
        row = [
            current_time,
            item['Exchange'],
            item['Rank'],
            item['Symbol'],
            item['Volume (THB)'],
            item['Price (THB)']
        ]
        ws.append(row)
        
    wb.save(EXCEL_FILE)
    print(f"Successfully saved {len(data)} rows to {EXCEL_FILE}")

def main():
    print("Starting snapshot...")
    # Fetch data concurrently for both exchanges
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_binance = executor.submit(get_binance_th_top_5)
        future_bitkub = executor.submit(get_bitkub_top_5)
        
        binance_data = future_binance.result()
        bitkub_data = future_bitkub.result()
    
    all_data = binance_data + bitkub_data
    if all_data:
        save_to_excel(all_data)
        print("Data snapshot complete.")
        for item in all_data:
            print(f"{item['Exchange']} #{item['Rank']} {item['Symbol']}: {item['Volume (THB)']:,.2f} THB")
    else:
        print("No data fetched. Check API connectivity.")

if __name__ == "__main__":
    main()
