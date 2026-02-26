from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import logging
import time
import pytz  # 👈 Timezone ke liye

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 👈 Enable CORS for all routes

# User-agent for NTES
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# India timezone
ist = pytz.timezone('Asia/Kolkata')

def get_india_date():
    """Return current date in India timezone (DD-MM-YYYY)"""
    india_time = datetime.now(ist)
    return india_time.strftime('%d-%m-%Y')

def get_india_date_offset(days=0):
    """Return date with offset in India timezone"""
    india_time = datetime.now(ist) + timedelta(days=days)
    return india_time.strftime('%d-%m-%Y')

def get_india_datetime():
    """Return current datetime in India timezone for logging"""
    return datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

# 👇 ROOT ENDPOINT
@app.route('/')
def home():
    return jsonify({
        "message": "🚂 Railway API Server is running!",
        "status": "online",
        "server_time_utc": datetime.utcnow().isoformat(),
        "server_time_ist": get_india_datetime(),
        "endpoints": {
            "/": "This info",
            "/health": "Health check",
            "/status/<train_number>": "Get live train status"
        }
    })

# 👇 HEALTH CHECK ENDPOINT
@app.route('/health')
def health():
    # Quick NTES connectivity check
    ntes_status = "unknown"
    ntes_response_time = None
    
    try:
        start_time = time.time()
        test_url = "https://enquiry.indianrail.gov.in"
        r = requests.get(test_url, timeout=5)
        ntes_response_time = round((time.time() - start_time) * 1000)  # in ms
        ntes_status = "reachable" if r.status_code == 200 else "unreachable"
    except requests.exceptions.Timeout:
        ntes_status = "timeout"
    except requests.exceptions.ConnectionError:
        ntes_status = "connection_error"
    except Exception as e:
        ntes_status = f"error: {str(e)[:50]}"
    
    return jsonify({
        "status": "ok",
        "server_time_utc": datetime.utcnow().isoformat(),
        "server_time_ist": get_india_datetime(),
        "ntes_status": ntes_status,
        "ntes_response_time_ms": ntes_response_time,
        "uptime": "running"
    })

# 👇 MAIN ENDPOINT - Get train status
@app.route('/status/<train_no>')
def get_train_status(train_no):
    logger.info(f"🔵 Request received for train: {train_no}")
    logger.info(f"🕐 Server time IST: {get_india_datetime()}")
    
    # ✅ INDIA TIME USE KARO
    today = get_india_date()
    logger.info(f"📅 India date: {today}")
    
    # Try today's date first
    result = fetch_data_with_retry(train_no, today)
    
    # If today fails, try yesterday
    if not result:
        yesterday = get_india_date_offset(-1)
        logger.info(f"⚠️ No data for today, trying yesterday: {yesterday}")
        result = fetch_data_with_retry(train_no, yesterday)
    
    # If yesterday fails, try day before
    if not result:
        day_before = get_india_date_offset(-2)
        logger.info(f"⚠️ No data for yesterday, trying day before: {day_before}")
        result = fetch_data_with_retry(train_no, day_before)
    
    if result:
        logger.info(f"✅ Data found for train {train_no}")
        # Add server timestamp to response
        result['server_time_ist'] = get_india_datetime()
        return jsonify(result)
    else:
        logger.error(f"❌ No data found for train {train_no} after 3 date attempts")
        return jsonify({
            "error": "Train data not found",
            "train_no": train_no,
            "message": "Please check train number or try again later",
            "server_time_ist": get_india_datetime(),
            "dates_tried": [today, get_india_date_offset(-1), get_india_date_offset(-2)]
        }), 404

# 👇 FETCH DATA WITH RETRY LOGIC
def fetch_data_with_retry(train_no, target_date, max_retries=3):
    """Fetch data from NTES with retry logic and timeout handling"""
    
    url = f"https://enquiry.indianrail.gov.in/mntes/?opt=TrainRunning&subOpt=FindTrain&trainNo={train_no}&date={target_date}"
    logger.info(f"📡 Fetching URL: {url}")
    
    for attempt in range(max_retries):
        try:
            logger.info(f"📡 Attempt {attempt + 1}/{max_retries} for train {train_no} on date {target_date}")
            
            # 👉 TIMEOUT 30 seconds (connect + read)
            response = requests.get(url, headers=HEADERS, timeout=30)
            
            logger.info(f"📡 Response status: {response.status_code}")
            logger.info(f"📡 Response size: {len(response.text)} bytes")
            
            if response.status_code == 200:
                # Parse HTML response
                data = parse_ntes_html(response.text, train_no, target_date)
                if data:
                    logger.info(f"✅ Successfully parsed data for {train_no}")
                    return data
                else:
                    logger.warning(f"⚠️ Parsed data is None - HTML structure may have changed")
                    # Log first 500 chars of HTML for debugging
                    logger.debug(f"HTML preview: {response.text[:500]}")
            else:
                logger.warning(f"⚠️ Status code: {response.status_code}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"⏰ Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                
        except requests.exceptions.ConnectionError as e:
            logger.error(f"🔌 Connection error: {e}")
            if attempt < max_retries - 1:
                wait_time = 5
                logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                break
                
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            break
            
    return None

# 👇 PARSE NTES HTML
def parse_ntes_html(html, train_no, target_date):
    """Extract train information from NTES HTML"""
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try different selectors for train name
        train_name = None
        selectors = [
            soup.find('span', {'id': 'lblTrainName'}),
            soup.find('div', {'class': 'train-name'}),
            soup.find('h3'),
            soup.find('h2'),
            soup.find('title'),
            soup.find('font', {'size': '4'})  # Older NTES format
        ]
        
        for selector in selectors:
            if selector and selector.text:
                train_name = selector.text.strip()
                if train_name and len(train_name) > 3:
                    break
        
        if not train_name or train_name == '':
            train_name = f"Train {train_no}"
        
        # Try to get status
        status = "Running"
        status_selectors = [
            soup.find('span', {'id': 'lblRunningStatus'}),
            soup.find('div', {'class': 'status'}),
            soup.find('p', {'class': 'running-status'}),
            soup.find('td', text=lambda t: t and 'status' in t.lower())
        ]
        
        for selector in status_selectors:
            if selector and selector.text:
                status = selector.text.strip()
                break
        
        # Try to get current location
        current_location = "N/A"
        location_selectors = [
            soup.find('span', {'id': 'lblLastLocation'}),
            soup.find('div', {'class': 'location'}),
            soup.find('span', {'id': 'lblCurrentStation'}),
            soup.find('td', text=lambda t: t and 'current' in t.lower())
        ]
        
        for selector in location_selectors:
            if selector and selector.text:
                current_location = selector.text.strip()
                break
        
        # Try to get delay
        delay = 0
        delay_selectors = [
            soup.find('span', {'id': 'lblDelay'}),
            soup.find('div', {'class': 'delay'}),
            soup.find('font', {'color': 'red'})
        ]
        
        for selector in delay_selectors:
            if selector and selector.text:
                delay_text = selector.text.strip()
                import re
                numbers = re.findall(r'\d+', delay_text)
                if numbers:
                    delay = int(numbers[0])
                break
        
        # Try to get source and destination
        source = "N/A"
        destination = "N/A"
        
        # Method 1: Look for station codes
        station_spans = soup.find_all('span', {'class': 'station-code'})
        if station_spans and len(station_spans) >= 2:
            source = station_spans[0].text.strip()
            destination = station_spans[-1].text.strip()
        else:
            # Method 2: Look in text
            text = soup.get_text()
            import re
            station_codes = re.findall(r'[A-Z]{4}', text)
            if station_codes and len(station_codes) >= 2:
                source = station_codes[0]
                destination = station_codes[-1]
        
        return {
            "train_no": train_no,
            "train_name": train_name,
            "status": status,
            "current_location": current_location,
            "delay_minutes": delay,
            "date": target_date,
            "last_updated": datetime.now(ist).strftime("%H:%M:%S"),
            "source": source,
            "destination": destination
        }
        
    except Exception as e:
        logger.error(f"❌ Error parsing HTML: {e}")
        return None

# 👇 Run the app
if __name__ == "__main__":
    logger.info("🚂 Railway API Server Starting...")
    logger.info(f"🕐 Server time IST: {get_india_datetime()}")
    logger.info("📍 Endpoints:")
    logger.info("   - /")
    logger.info("   - /health")
    logger.info("   - /status/<train_number>")
    app.run(host='0.0.0.0', port=5000, debug=False)
