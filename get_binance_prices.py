import requests
import csv
from datetime import datetime, timedelta

# Define parameters
symbol = 'BTCUSDT'
interval = '1d'
limit = 120  # Approximate number of days in two months

# Calculate the start time (in milliseconds)
end_time = int(datetime.now().timestamp() * 1000)
start_time = int((datetime.now() - timedelta(days=limit)).timestamp() * 1000)

# Binance API endpoint
url = 'https://api.binance.com/api/v3/klines'

# Parameters for the API request
params = {
    'symbol': symbol,
    'interval': interval,
    'startTime': start_time,
    'endTime': end_time,
    'limit': limit
}

# Make the API request
response = requests.get(url, params=params)
data = response.json()

# Write data to CSV
with open('btc_usdt_last_2_months.csv', 'w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(['timestamp', 'price'])
    for entry in data:
        timestamp = datetime.fromtimestamp(entry[0]/1000).strftime('%Y-%m-%d')
        price = entry[4]  # Closing price
        writer.writerow([timestamp, price])
