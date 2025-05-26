import os
import sys
import sqlite3
import csv
import io
import time
from datetime import datetime, timedelta
import urllib
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from jinja2 import Environment, FileSystemLoader

from collections import defaultdict

import asciichartpy

import requests

import httpx

app = FastAPI()
@app.middleware("http")
async def fix_backslashes(request: Request, call_next):
	decoded_path = urllib.parse.unquote(request.url.path)
	if '\\' in decoded_path:
		corrected_path = decoded_path.replace('\\', '')
		query = request.url.query
		new_url = corrected_path + ('?' + query if query else '')
		return RedirectResponse(url=new_url, status_code=301)
	return await call_next(request)

app.mount("/monthly_reports", StaticFiles(directory="monthly_reports"), name="monthly_reports")
app.mount("/daily_reports", StaticFiles(directory="daily_reports"), name="daily_reports")
env = Environment(loader=FileSystemLoader("templates"))
templates = Jinja2Templates(directory="templates")

db_f = "btc_prices.db"

def datetimeformat(value, format="%Y-%m-%d"):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)

templates.env.filters["datetimeformat"] = datetimeformat


@app.get("/")
async def index(request: Request, range: str = Query("30d")):
    today = datetime.today().date()
    delta_map = {
        "1d": 1,
        "3d": 3,
        "7d": 7,
        "14d": 14,
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365
    }
    days = delta_map.get(range, 30)
    start_date = today - timedelta(days=days)

    conn = sqlite3.connect("btc_prices.db")
    cursor = conn.cursor()

    # Get daily average prices
    cursor.execute("""
        SELECT date(timestamp) AS day, ROUND(AVG(price), 2) AS avg_price
        FROM prices
        WHERE date(timestamp) BETWEEN ? AND ?
        GROUP BY day
        ORDER BY day ASC
    """, (start_date, today))
    rows = cursor.fetchall()
    conn.close()

    data = [{"timestamp": row[0], "price": row[1]} for row in rows]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "data": data,
        "range": range
    })


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):

	return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload_csv", response_class=HTMLResponse)
async def upload_csv(request: Request, file: UploadFile = File(...)):
	if not file.filename.endswith('.csv'):
		return templates.TemplateResponse('upload.html', {
			"request": request,
			"error": 'only .csv files acceptable!'
		})

	contents = await file.read()
	csv_file = io.StringIO(contents.decode("utf-8"))
	reader = csv.DictReader(csv_file)

	if "timestamp" not in reader.fieldnames or "price" not in reader.fieldnames:
		return templates.TemplateResponse("upload.html", {
			"request": request,
			"error": "csv must contain 'timestamp' and 'price' columns"
		})

	rows = [(row['timestamp'], float(row['price'])) for row in reader]

	conn = sqlite3.connect(db_f)
	conn.executemany('insert into prices (timestamp, price) values (?, ?)', rows)
	conn.commit()
	conn.close()

	return templates.TemplateResponse('success.html', {
		"request": request,
		"row_count": len(rows)
	})

def write_report(template_name, output_path, data, title, with_chart=True):
	template = env.get_template(template_name)
	rendered_html = template.render(title=title, data=data, with_chart=with_chart)
	with open(output_path, "w", encoding="utf-8") as f:
		f.write(rendered_html)

@app.get("/generate-report-{start_date}--{end_date}", response_class=HTMLResponse)
def generate_full_report(start_date: str, end_date: str):
	try:
		start_dt = datetime.strptime(start_date, "%Y-%m-%d")
		end_dt = datetime.strptime(end_date, "%Y-%m-%d")
	except ValueError:
		raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
	if start_dt > end_dt:
		raise HTTPException(status_code=400, detail="Start date must be before end date.")

	conn = sqlite3.connect("btc_prices.db")
	cursor = conn.cursor()
	cursor.execute("""
		SELECT DATE(timestamp), price FROM prices
		WHERE DATE(timestamp) BETWEEN ? AND ?
		ORDER BY timestamp
	""", (start_date, end_date))
	rows = cursor.fetchall()
	conn.close()

	if not rows:
		return HTMLResponse("<h3>⚠️ No data found in selected range.</h3>")

	daily_data = defaultdict(list)
	monthly_data = defaultdict(list)
	for ts, price in rows:
		date_obj = datetime.strptime(ts, "%Y-%m-%d")
		date_str = date_obj.strftime("%Y-%m-%d")
		month_str = date_obj.strftime("%Y-%m")
		daily_data[date_str].append({"timestamp": ts, "price": price})
		monthly_data[month_str].append({"timestamp": ts, "price": price})

	os.makedirs("daily_reports", exist_ok=True)
	os.makedirs("monthly_reports", exist_ok=True)

	# daily reports (no chart)
	for day, records in daily_data.items():
		out_path = f"daily_reports/report_{day}.html"
		write_report("report_template.html", out_path, records, f"Daily Report for {day}", with_chart=False)

	# monthly reports (with chart)
	for month, records in monthly_data.items():
		per_day = defaultdict(float)
		month_obj = datetime.strptime(month, "%Y-%m")
		title_str = f"Bitcoin {month_obj.strftime('%B %Y')} Price"
		for r in records:
			d = r["timestamp"]
			per_day[d] += r["price"]

		summary = [{"timestamp": k, "price": v} for k, v in sorted(per_day.items())]
		out_path = f"monthly_reports/report_{month}.html"
		write_report("report_template.html", out_path, summary, title_str, with_chart=True)


	return HTMLResponse("<h3>✅ Daily and monthly reports generated</h3>")

@app.get("/binance-data-{start_date}--{end_date}", response_class=HTMLResponse)
def binance_data(start_date: str, end_date: str):
	symbol = 'BTCUSDT'
	interval = '1d'

	start_time = datetime.strptime(start_date, "%Y-%m-%d")
	start_time = int(time.mktime(start_time.timetuple()) * 1000)
	end_time = datetime.strptime(end_date, "%Y-%m-%d")
	end_time = int(time.mktime(end_time.timetuple()) * 1000)


	url = 'https://api.binance.com/api/v3/klines'

	params = {
		'symbol': symbol,
		'interval': interval,
		'startTime': start_time,
		'endTime': end_time
	}

	response = requests.get(url, params=params)
	data = response.json()

	filename = 'btc_usdt_{}-{}.csv'.format(start_date, end_date)

	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerow(['timestamp', 'price'])

	for entry in data:
		timestamp = datetime.fromtimestamp(entry[0]/1000).strftime('%Y-%m-%d')
		price = entry[4]
		writer.writerow([timestamp, price])

	output.seek(0)

	return StreamingResponse(
		output,
		media_type="text/csv",
		headers={"Content-Disposition": f"attachment; filename={filename}"}
	)


@app.post("/save_price")
async def save_price(request: Request):
    data = await request.json()
    timestamp = data.get("timestamp")
    price = data.get("price")

    if timestamp is None or price is None:
        return {"error": "Missing timestamp or price"}

    conn = sqlite3.connect("btc_prices.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO prices (timestamp, price) VALUES (?, ?)", (timestamp, price))
    conn.commit()
    conn.close()

    return {"status": "ok"}