from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import logging
import time
import pytz
import re
import random
from fake_useragent import UserAgent

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Fallback user agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
]

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
            "/sources/status": "Check data source availability",
            "/status/<train_number>": "Get live train status (multi-source)"
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

# ============================================================================
# NTES SCRAPER (Original)
# ============================================================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def fetch_data_with_retry(train_no, target_date, max_retries=2):
    """Fetch data from NTES with retry logic"""
    
    url = f"https://enquiry.indianrail.gov.in/mntes/?opt=TrainRunning&subOpt=FindTrain&trainNo={train_no}&date={target_date}"
    logger.info(f"📡 NTES Fetching: {url}")
    
    for attempt in range(max_retries):
        try:
            logger.info(f"📡 NTES Attempt {attempt + 1}/{max_retries} for train {train_no} on date {target_date}")
            
            response = requests.get(url, headers=HEADERS, timeout=25)
            logger.info(f"📡 NTES Response status: {response.status_code}")
            
            if response.status_code == 200:
                data = parse_ntes_html(response.text, train_no, target_date)
                if data:
                    logger.info(f"✅ NTES Success for {train_no}")
                    return data
                else:
                    logger.warning(f"⚠️ NTES parsed data is None")
            else:
                logger.warning(f"⚠️ NTES status code: {response.status_code}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"⏰ NTES timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                wait_time = 2
                logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
        except Exception as e:
            logger.error(f"❌ NTES error: {e}")
            break
            
    return None

def parse_ntes_html(html, train_no, target_date):
    """Extract train information from NTES HTML"""
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Train name
        train_name = None
        selectors = [
            soup.find('span', {'id': 'lblTrainName'}),
            soup.find('div', {'class': 'train-name'}),
            soup.find('h3'),
            soup.find('h2'),
            soup.find('title'),
        ]
        
        for selector in selectors:
            if selector and selector.text:
                train_name = selector.text.strip()
                if train_name and len(train_name) > 3:
                    break
        
        if not train_name or train_name == '':
            train_name = f"Train {train_no}"
        
        # Status
        status = "Running"
        status_selectors = [
            soup.find('span', {'id': 'lblRunningStatus'}),
            soup.find('div', {'class': 'status'}),
        ]
        
        for selector in status_selectors:
            if selector and selector.text:
                status = selector.text.strip()
                break
        
        # Current location
        current_location = "N/A"
        location_selectors = [
            soup.find('span', {'id': 'lblLastLocation'}),
            soup.find('div', {'class': 'location'}),
            soup.find('span', {'id': 'lblCurrentStation'}),
        ]
        
        for selector in location_selectors:
            if selector and selector.text:
                current_location = selector.text.strip()
                break
        
        # Delay
        delay = 0
        delay_selectors = [
            soup.find('span', {'id': 'lblDelay'}),
            soup.find('div', {'class': 'delay'}),
            soup.find('font', {'color': 'red'})
        ]
        
        for selector in delay_selectors:
            if selector and selector.text:
                delay_text = selector.text.strip()
                numbers = re.findall(r'\d+', delay_text)
                if numbers:
                    delay = int(numbers[0])
                break
        
        # Source and destination
        source = "N/A"
        destination = "N/A"
        
        station_spans = soup.find_all('span', {'class': 'station-code'})
        if station_spans and len(station_spans) >= 2:
            source = station_spans[0].text.strip()
            destination = station_spans[-1].text.strip()
        else:
            # Try to find in text
            text = soup.get_text()
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
            "destination": destination,
            "data_source": "NTES"
        }
        
    except Exception as e:
        logger.error(f"❌ NTES parse error: {e}")
        return None

# ============================================================================
# RAILYATRI SCRAPER
# ============================================================================

def fetch_from_railyatri(train_no):
    """RailYatri se train data scrape karo"""
    try:
        ua = UserAgent()
        headers = {
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.railyatri.in/',
        }
    except:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
    
    url = f"https://www.railyatri.in/train-tracking/{train_no}"
    logger.info(f"📡 RailYatri: Fetching {train_no}...")
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            logger.warning(f"RailYatri status: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Train name
        train_name = None
        selectors = [
            soup.find('h1', class_='train-heading'),
            soup.find('div', class_='train-name'),
            soup.find('title')
        ]
        for sel in selectors:
            if sel and sel.text:
                train_name = sel.text.strip()
                break
        
        # Current location
        current_location = "N/A"
        loc_selectors = [
            soup.find('span', class_='current-location'),
            soup.find('div', class_='live-location'),
            soup.find('div', class_='station-name')
        ]
        for sel in loc_selectors:
            if sel and sel.text:
                current_location = sel.text.strip()
                break
        
        # Delay
        delay = 0
        delay_elem = soup.find('span', class_='delay-value')
        if delay_elem:
            numbers = re.findall(r'\d+', delay_elem.text)
            if numbers:
                delay = int(numbers[0])
        
        # Source/Destination
        source = "N/A"
        destination = "N/A"
        station_codes = soup.find_all('span', class_='station-code')
        if station_codes and len(station_codes) >= 2:
            source = station_codes[0].text.strip()
            destination = station_codes[-1].text.strip()
        
        # Last updated time
        last_updated = datetime.now(ist).strftime("%H:%M:%S")
        time_elem = soup.find('span', class_='update-time')
        if time_elem:
            last_updated = time_elem.text.strip()
        
        return {
            "train_no": train_no,
            "train_name": train_name or f"Train {train_no}",
            "status": "Running",
            "current_location": current_location,
            "delay_minutes": delay,
            "date": get_india_date(),
            "last_updated": last_updated,
            "source": source,
            "destination": destination,
            "data_source": "RailYatri"
        }
    except Exception as e:
        logger.error(f"❌ RailYatri error: {e}")
        return None

# ============================================================================
# IXIGO SCRAPER
# ============================================================================

def fetch_from_ixigo(train_no):
    """Ixigo se train data scrape karo"""
    try:
        ua = UserAgent()
        headers = {'User-Agent': ua.random}
    except:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
    
    url = f"https://www.ixigo.com/trains/{train_no}/live-train-status"
    logger.info(f"📡 Ixigo: Fetching {train_no}...")
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            logger.warning(f"Ixigo status: {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Train name
        train_name = None
        h1 = soup.find('h1')
        if h1:
            train_name = h1.text.strip()
        
        # Current location
        current_location = "N/A"
        loc_selectors = [
            soup.find('div', class_='current-location'),
            soup.find('span', class_='station-name'),
            soup.find('div', class_='live-location')
        ]
        for sel in loc_selectors:
            if sel and sel.text:
                current_location = sel.text.strip()
                break
        
        # Delay
        delay = 0
        delay_selectors = [
            soup.find('span', class_='delay'),
            soup.find('div', class_='delay-info')
        ]
        for sel in delay_selectors:
            if sel and sel.text:
                numbers = re.findall(r'\d+', sel.text)
                if numbers:
                    delay = int(numbers[0])
                break
        
        return {
            "train_no": train_no,
            "train_name": train_name or f"Train {train_no}",
            "status": "Running",
            "current_location": current_location,
            "delay_minutes": delay,
            "date": get_india_date(),
            "last_updated": datetime.now(ist).strftime("%H:%M:%S"),
            "source": "N/A",
            "destination": "N/A",
            "data_source": "Ixigo"
        }
    except Exception as e:
        logger.error(f"❌ Ixigo error: {e}")
        return None

# ============================================================================
# MULTI-SOURCE FETCHER
# ============================================================================

def fetch_train_data_multi_source(train_no):
    """Multiple sources se train data fetch karo"""
    
    # Priority order
    sources = [
        {"name": "NTES", "func": lambda t: fetch_data_with_retry(t, get_india_date())},
        {"name": "RailYatri", "func": fetch_from_railyatri},
        {"name": "Ixigo", "func": fetch_from_ixigo},
    ]
    
    # Agar NTES fail ho to yesterday try karo
    def try_ntes_with_yesterday(t):
        result = fetch_data_with_retry(t, get_india_date())
        if not result:
            yesterday = get_india_date_offset(-1)
            logger.info(f"📅 NTES trying yesterday: {yesterday}")
            result = fetch_data_with_retry(t, yesterday)
        return result
    
    sources[0]["func"] = try_ntes_with_yesterday
    
    for source in sources:
        logger.info(f"🔍 Trying {source['name']}...")
        data = source['func'](train_no)
        
        if data:
            logger.info(f"✅ Success from {source['name']}")
            data['source_used'] = source['name']
            return data
        
        logger.info(f"⚠️ {source['name']} failed, waiting 1 second...")
        time.sleep(1)
    
    logger.error(f"❌ All sources failed for train {train_no}")
    return None

# ============================================================================
# SOURCE STATUS ENDPOINT
# ============================================================================

@app.route('/sources/status')
def sources_status():
    """Check which sources are working"""
    
    def check_ntes():
        try:
            r = requests.get("https://enquiry.indianrail.gov.in", timeout=5)
            return r.status_code == 200
        except:
            return False
    
    def check_railyatri():
        try:
            r = requests.get("https://www.railyatri.in", timeout=5)
            return r.status_code == 200
        except:
            return False
    
    def check_ixigo():
        try:
            r = requests.get("https://www.ixigo.com", timeout=5)
            return r.status_code == 200
        except:
            return False
    
    return jsonify({
        "ntes": check_ntes(),
        "railyatri": check_railyatri(),
        "ixigo": check_ixigo(),
        "timestamp": get_india_datetime()
    })

# ============================================================================
# MAIN STATUS ENDPOINT
# ============================================================================

@app.route('/status/<train_no>')
def get_train_status_multi(train_no):
    logger.info(f"🔵 Multi-source request for train: {train_no}")
    logger.info(f"🕐 Server time IST: {get_india_datetime()}")
    
    result = fetch_train_data_multi_source(train_no)
    
    if result:
        return jsonify(result)
    else:
        return jsonify({
            "error": "Train data not found from any source",
            "train_no": train_no,
            "message": "All railway data sources are currently unavailable. Please try again later.",
            "server_time_ist": get_india_datetime()
        }), 404

# ============================================================================
# RUN APP
# ============================================================================

if __name__ == "__main__":
    logger.info("🚂 Railway API Server Starting...")
    logger.info(f"🕐 Server time IST: {get_india_datetime()}")
    logger.info("📍 Endpoints:")
    logger.info("   - /")
    logger.info("   - /health")
    logger.info("   - /sources/status")
    logger.info("   - /status/<train_number>")
    app.run(host='0.0.0.0', port=5000, debug=False)
