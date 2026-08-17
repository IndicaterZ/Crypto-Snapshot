import requests
import os
import concurrent.futures
from datetime import datetime, timezone, timedelta
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

EXCEL_FILE = "crypto_volume.xlsx"

def get_binance_th_top_5():
    try:
        exchange_info = requests.get('https://api.binance.th/api/v1/exchangeInfo')
        exchange_info.raise_for_status()
        symbols = [s['symbol'] for s in exchange_info.json()['symbols'] if s['symbol'].endswith('THB')]
        
        def fetch_ticker(symbol):
            try:
                resp = requests.get(f'https://api.binance.th/api/v1/ticker/24hr?symbol={symbol}')
                resp.raise_for_status()
                return resp.json()
            except Exception:
                return None
                
        tickers = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetch_ticker, symbols)
            tickers = [t for t in results if t is not None]
        
        thb_pairs = []
        for t in tickers:
            try:
                t['quoteVolume'] = float(t['quoteVolume'])
                t['lastPrice'] = float(t.get('lastPrice', 0))
                thb_pairs.append(t)
            except (ValueError, KeyError):
                continue
        
        thb_pairs.sort(key=lambda x: x['quoteVolume'], reverse=True)
        return thb_pairs[:5]
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
        return thb_pairs[:5]
    except Exception as e:
        print(f"Error fetching Bitkub data: {e}")
        return []

def update_excel(binance_data, bitkub_data):
    if os.path.exists(EXCEL_FILE):
        wb = load_workbook(EXCEL_FILE)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Volume Snapshot"
    
    # 1. Update Top Section (Rows 1-6)
    for row in range(1, 7):
        for col in range(1, 6):
            ws.cell(row=row, column=col).value = None

    ws.cell(row=1, column=2).value = "Bitkub"
    ws.cell(row=1, column=3).value = "Ave. daily vol. (THB)"
    ws.cell(row=1, column=4).value = "Binance TH"
    ws.cell(row=1, column=5).value = "Ave. daily vol. (THB)"

    for i in range(5):
        row = i + 2
        ws.cell(row=row, column=1).value = i + 1
        
        if i < len(bitkub_data):
            ws.cell(row=row, column=2).value = bitkub_data[i]['symbol']
            c = ws.cell(row=row, column=3)
            c.value = bitkub_data[i]['quoteVolume']
            c.number_format = '#,##0.00'
            
        if i < len(binance_data):
            ws.cell(row=row, column=4).value = binance_data[i]['symbol']
            c = ws.cell(row=row, column=5)
            c.value = binance_data[i]['quoteVolume']
            c.number_format = '#,##0.00'

    # 2. Historical Section
    ws.cell(row=13, column=1).value = "Date"
    
    # Read existing headers in row 13
    header_map = {}
    bitkub_end_col = 1
    binance_end_col = 1
    
    for col in range(2, 200):
        val = ws.cell(row=13, column=col).value
        if val:
            if not val.endswith("7d-Avg"): 
                header_map[val] = col
            if val.startswith("THB_") or "7d-Avg" in val and "THB_" in val:
                bitkub_end_col = max(bitkub_end_col, col)
            else:
                binance_end_col = max(binance_end_col, col)
    
    # Initialize ends if fresh sheet
    if bitkub_end_col == 1:
        bitkub_end_col = 1
    if binance_end_col == 1:
        binance_end_col = bitkub_end_col + 1 # At least leave a gap if empty
        
    # Process Bitkub Coins (Insert them if new so they stay on the left)
    for d in bitkub_data:
        symbol = d['symbol']
        if symbol not in header_map:
            insert_col = bitkub_end_col + 1
            if binance_end_col > 1:
                # If Binance coins already exist to the right, we push them right
                # to maintain the gap
                ws.insert_cols(insert_col)
                binance_end_col += 1
                
            ws.cell(row=13, column=insert_col).value = symbol
            header_map[symbol] = insert_col
            bitkub_end_col += 1
            
            if "BTC" in symbol:
                insert_col = bitkub_end_col + 1
                if binance_end_col > 1:
                    ws.insert_cols(insert_col)
                    binance_end_col += 1
                ws.cell(row=13, column=insert_col).value = f"{symbol} 7d-Avg"
                bitkub_end_col += 1
                
            # Re-read headers to update the map because shifting changes columns
            header_map = {}
            for col in range(2, 200):
                val = ws.cell(row=13, column=col).value
                if val and not val.endswith("7d-Avg"):
                    header_map[val] = col

    # Process Binance Coins (Append to the far right)
    # Ensure there is a gap between bitkub and binance
    if binance_end_col <= bitkub_end_col:
        binance_end_col = bitkub_end_col + 1

    for d in binance_data:
        symbol = d['symbol']
        if symbol not in header_map:
            insert_col = binance_end_col + 1
            ws.cell(row=13, column=insert_col).value = symbol
            header_map[symbol] = insert_col
            binance_end_col += 1
            
            if "BTC" in symbol:
                insert_col = binance_end_col + 1
                ws.cell(row=13, column=insert_col).value = f"{symbol} 7d-Avg"
                binance_end_col += 1

    # Find next empty row for historical data (starting from 14)
    next_row = 14
    while ws.cell(row=next_row, column=1).value is not None:
        next_row += 1

    # Write Date
    th_tz = timezone(timedelta(hours=7))
    current_date = datetime.now(th_tz).day
    ws.cell(row=next_row, column=1).value = current_date

    # Write volumes and formulas for all current coins
    all_current_coins = [(d['symbol'], d['quoteVolume']) for d in bitkub_data] + [(d['symbol'], d['quoteVolume']) for d in binance_data]
    
    for symbol, vol in all_current_coins:
        vol_col = header_map[symbol]
        c_vol = ws.cell(row=next_row, column=vol_col)
        c_vol.value = vol
        c_vol.number_format = '#,##0.00'
        
        # Write formula for 7-day average ONLY for BTC
        if "BTC" in symbol:
            if next_row >= 20: # 14 + 6 = 20, meaning we have 7 days of rows
                col_letter = get_column_letter(vol_col)
                formula = f"=AVERAGE({col_letter}{next_row-6}:{col_letter}{next_row})"
                c_avg = ws.cell(row=next_row, column=vol_col+1)
                c_avg.value = formula
                c_avg.number_format = '#,##0.00'

    wb.save(EXCEL_FILE)
    print(f"Successfully updated {EXCEL_FILE} with new format.")

def main():
    print("Starting snapshot...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_binance = executor.submit(get_binance_th_top_5)
        future_bitkub = executor.submit(get_bitkub_top_5)
        
        binance_data = future_binance.result()
        bitkub_data = future_bitkub.result()
    
    if binance_data or bitkub_data:
        update_excel(binance_data, bitkub_data)
    else:
        print("No data fetched. Check API connectivity.")

if __name__ == "__main__":
    main()
