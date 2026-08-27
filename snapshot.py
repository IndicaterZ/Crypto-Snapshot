import requests
import os
import concurrent.futures
import hmac
import hashlib
import time
import uuid
import json
from datetime import datetime, timezone, timedelta
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

EXCEL_FILE = "crypto_volume.xlsx"

def get_binance_th_data():
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
        return thb_pairs
    except Exception as e:
        print(f"Error fetching Binance TH data: {e}")
        return []

def get_bitkub_data():
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
        return thb_pairs
    except Exception as e:
        print(f"Error fetching Bitkub data: {e}")
        return []

def get_orbix_data():
    try:
        response = requests.get('https://satangcorp.com/api/v3/ticker/24hr')
        response.raise_for_status()
        data = response.json()
        
        thb_pairs = []
        for d in data:
            if d['symbol'].endswith('_thb'):
                try:
                    quote_vol = float(d['quoteVolume'])
                    last_price = float(d['lastPrice'])
                    thb_pairs.append({
                        'symbol': d['symbol'].upper(),
                        'quoteVolume': quote_vol,
                        'lastPrice': last_price
                    })
                except (ValueError, KeyError):
                    continue
        
        thb_pairs.sort(key=lambda x: x['quoteVolume'], reverse=True)
        return thb_pairs
    except Exception as e:
        print(f"Error fetching Orbix data: {e}")
        return []

def get_innovestx_data():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Please install it using 'pip install playwright' and 'playwright install chromium'")
        return []
        
    print("Scraping InnovestX website for 24h Volume...")
    thb_pairs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://trade.innovestxonline.com/digitalassets")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)
            
            # Scroll down multiple times to load all coins
            for _ in range(10):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(500)
                
            content = page.evaluate("document.body.innerText")
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            
            try:
                start_idx = lines.index("Volume (24h)") + 1
                for i in range(start_idx, len(lines), 5):
                    if i + 3 < len(lines):
                        symbol = lines[i]
                        if not symbol.endswith("/THB"):
                            continue
                        price_str = lines[i+1].replace(",", "")
                        vol_thb_str = lines[i+3].replace(" THB", "").replace(",", "")
                        try:
                            price = float(price_str)
                            vol = float(vol_thb_str)
                            thb_pairs.append({
                                'symbol': symbol.replace("/", ""),
                                'quoteVolume': vol,
                                'lastPrice': price
                            })
                        except ValueError:
                            pass
            except ValueError:
                print("Could not find 'Volume (24h)' in the page text.")
                
            browser.close()
            
        thb_pairs.sort(key=lambda x: x['quoteVolume'], reverse=True)
        print(f"Successfully scraped {len(thb_pairs)} coins from InnovestX.")
        return thb_pairs
    except Exception as e:
        print(f"Error fetching InnovestX data via scraper: {e}")
        return []

def update_excel(bitkub_data, binance_data, orbix_data, innovestx_data):
    if os.path.exists(EXCEL_FILE):
        wb = load_workbook(EXCEL_FILE)
    else:
        wb = Workbook()
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
            
    # Clean up old single-sheet layout if it exists
    if "Volume Snapshot" in wb.sheetnames:
        del wb["Volume Snapshot"]
        
    sheet_names = ["Top 5 Summary", "Bitkub", "Binance TH", "Orbix", "InnovestX"]
    for sn in sheet_names:
        if sn not in wb.sheetnames:
            wb.create_sheet(sn)
            
    # 1. Update Top Section (Top 5 Summary Sheet)
    ws_summary = wb["Top 5 Summary"]
    # Clear existing summary
    for row in range(1, 10):
        for col in range(1, 15):
            ws_summary.cell(row=row, column=col).value = None
            
    headers = [
        ("Bitkub", 2), ("Ave. daily vol.", 3),
        ("Binance TH", 5), ("Ave. daily vol.", 6),
        ("Orbix", 8), ("Ave. daily vol.", 9),
        ("InnovestX", 11), ("Ave. daily vol.", 12)
    ]
    for text, col in headers:
        ws_summary.cell(row=1, column=col).value = text

    groups = [
        (bitkub_data, 2),
        (binance_data, 5),
        (orbix_data, 8),
        (innovestx_data, 11)
    ]

    for i in range(5):
        row = i + 2
        ws_summary.cell(row=row, column=1).value = i + 1
        
        for data, start_col in groups:
            if i < len(data):
                ws_summary.cell(row=row, column=start_col).value = data[i]['symbol']
                c = ws_summary.cell(row=row, column=start_col+1)
                c.value = data[i]['quoteVolume']
                c.number_format = '#,##0.00'

    # 2. Historical Sections (Separate Sheets)
    th_tz = timezone(timedelta(hours=7))
    current_date = datetime.now(th_tz).day
    
    def update_history_sheet(sheet_name, data):
        ws = wb[sheet_name]
        
        if ws.max_row == 1 and ws.cell(row=1, column=1).value is None:
            ws.cell(row=1, column=1).value = "Date"
            
        header_map = {}
        max_col = 1
        for col in range(2, 2000):
            val = ws.cell(row=1, column=col).value
            if val and not str(val).endswith("7d-Avg"):
                header_map[val] = col
                max_col = max(max_col, col)
                if "BTC" in val: # BTC takes 2 cols
                    max_col = max(max_col, col + 1)
                    
        # Add new headers
        next_col = max_col + 1
        for d in data:
            sym = d['symbol']
            if sym not in header_map:
                ws.cell(row=1, column=next_col).value = sym
                header_map[sym] = next_col
                next_col += 1
                if "BTC" in sym:
                    ws.cell(row=1, column=next_col).value = f"{sym} 7d-Avg"
                    next_col += 1
                    
        # Find next row
        next_row = 2
        while ws.cell(row=next_row, column=1).value is not None:
            next_row += 1
            
        ws.cell(row=next_row, column=1).value = current_date
        
        # Write data
        for d in data:
            sym = d['symbol']
            vol = d['quoteVolume']
            col_idx = header_map.get(sym)
            if not col_idx: continue
            
            c_vol = ws.cell(row=next_row, column=col_idx)
            c_vol.value = vol
            c_vol.number_format = '#,##0.00'
            
            if "BTC" in sym:
                if next_row >= 8: # Requires 7 days of data
                    col_letter = get_column_letter(col_idx)
                    formula = f"=AVERAGE({col_letter}{next_row-6}:{col_letter}{next_row})"
                    c_avg = ws.cell(row=next_row, column=col_idx+1)
                    c_avg.value = formula
                    c_avg.number_format = '#,##0.00'

    update_history_sheet("Bitkub", bitkub_data)
    update_history_sheet("Binance TH", binance_data)
    update_history_sheet("Orbix", orbix_data)
    update_history_sheet("InnovestX", innovestx_data)

    wb.save(EXCEL_FILE)
    print(f"Successfully updated {EXCEL_FILE} with multi-sheet layout.")

def main():
    print("Starting snapshot for ALL coins with multi-sheet...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f_binance = executor.submit(get_binance_th_data)
        f_bitkub = executor.submit(get_bitkub_data)
        f_orbix = executor.submit(get_orbix_data)
        f_innovestx = executor.submit(get_innovestx_data)
        
        binance_data = f_binance.result()
        bitkub_data = f_bitkub.result()
        orbix_data = f_orbix.result()
        innovestx_data = f_innovestx.result()
    
    if any([binance_data, bitkub_data, orbix_data, innovestx_data]):
        update_excel(bitkub_data, binance_data, orbix_data, innovestx_data)
    else:
        print("No data fetched from any exchange.")

if __name__ == "__main__":
    main()
