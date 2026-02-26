from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import logging
import time

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 👈 Enable CORS for all routes (Fixes CORS error)

# User-agent for NTES
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# 👇 ROOT ENDPOINT - Browser open karne pe error nahi aayega
@app.route('/')
def home():
    return jsonify({
        "message": "🚂 Railway API Server is running!",
        "status": "online",
        "endpoints": {
            "/": "This info",
            "/health": "Health check",
            "/status/<train_number>": "Get live train status"
        },
        "timestamp": datetime.now().isoformat()
    })

# 👇 HEALTH CHECK ENDPOINT - For Render keep-alive
@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    })

# 👇 MAIN ENDPOINT - Get train status
@app.route('/status/<train_no>')
def get_train_status(train_no):
    logger.info(f"🔵 Request received for train: {train_no}")
    
    # Try today's date first
    today = datetime.now().strftime('%d-%m-%Y')
    result = fetch_data_with_retry(train_no, today)
    
    # If today fails, try yesterday
    if not result:
        logger.info(f"⚠️ No data for today, trying yesterday...")
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%d-%m-%Y')
        result = fetch_data_with_retry(train_no, yesterday)
    
    # If yesterday fails, try day before
    if not result:
        logger.info(f"⚠️ No data for yesterday, trying day before...")
        day_before = (datetime.now() - timedelta(days=2)).strftime('%d-%m-%Y')
        result = fetch_data_with_retry(train_no, day_before)
    
    if result:
        logger.info(f"✅ Data found for train {train_no}")
        return jsonify(result)
    else:
        logger.error(f"❌ No data found for train {train_no}")
        return jsonify({
            "error": "Train data not found",
            "train_no": train_no,
            "message": "Please check train number or try again later"
        }), 404

# 👇 FETCH DATA WITH RETRY LOGIC
def fetch_data_with_retry(train_no, target_date, max_retries=3):
    """Fetch data from NTES with retry logic and timeout handling"""
    
    url = f"https://enquiry.indianrail.gov.in/mntes/?opt=TrainRunning&subOpt=FindTrain&trainNo={train_no}&date={target_date}"
    logger.info(f"📡 Fetching URL: {url}")
    
    for attempt in range(max_retries):
        try:
            logger.info(f"📡 Attempt {attempt + 1} for train {train_no} on date {target_date}")
            
            # 👈 TIMEOUT 45 SECONDS (increased from 15)
            response = requests.get(url, headers=HEADERS, timeout=45)
            logger.info(f"📡 Response status: {response.status_code}")
            
            if response.status_code == 200:
                # Parse HTML response
                data = parse_ntes_html(response.text, train_no, target_date)
                if data:
                    return data
                else:
                    logger.warning(f"⚠️ Parsed data is None")
            else:
                logger.warning(f"⚠️ Status code: {response.status_code}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"⏰ Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                
        except Exception as e:
            logger.error(f"❌ Error: {e}")
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
            soup.find('title')  # Fallback
        ]
        
        for selector in selectors:
            if selector and selector.text:
                train_name = selector.text.strip()
                break
        
        if not train_name:
            train_name = f"Train {train_no}"
        
        # Try to get status
        status = "Running"
        status_selectors = [
            soup.find('span', {'id': 'lblRunningStatus'}),
            soup.find('div', {'class': 'status'}),
            soup.find('p', {'class': 'running-status'})
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
            soup.find('span', {'id': 'lblCurrentStation'})
        ]
        
        for selector in location_selectors:
            if selector and selector.text:
                current_location = selector.text.strip()
                break
        
        # Try to get delay
        delay = 0
        delay_selectors = [
            soup.find('span', {'id': 'lblDelay'}),
            soup.find('div', {'class': 'delay'})
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
        source = "NDLS"  # Default
        destination = "BCT"  # Default
        
        route_spans = soup.find_all('span', {'class': 'station-code'})
        if len(route_spans) >= 2:
            source = route_spans[0].text.strip()
            destination = route_spans[-1].text.strip()
        
        return {
            "train_no": train_no,
            "train_name": train_name,
            "status": status,
            "current_location": current_location,
            "delay_minutes": delay,
            "date": target_date,
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            "source": source,
            "destination": destination
        }
        
    except Exception as e:
        logger.error(f"❌ Error parsing HTML: {e}")
        return None

# 👇 Run the app
if __name__ == "__main__":
    logger.info("🚂 Railway API Server Starting...")
    logger.info("📍 Endpoints:")
    logger.info("   - /")
    logger.info("   - /health")
    logger.info("   - /status/<train_number>")
    app.run(host='0.0.0.0', port=5000, debug=False)
