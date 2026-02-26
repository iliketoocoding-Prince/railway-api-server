import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from flask_cors import CORS  # Install: pip install flask-cors
from datetime import datetime, timedelta
import time
import logging

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Flutter app se connect karne ke liye

# User-agent taaki NTES ko lage ki koi browser use kar raha hai
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def fetch_data_with_retry(train_no, target_date, max_retries=3):
    """Retry logic ke saath data fetch karo"""
    
    url = f"https://enquiry.indianrail.gov.in/mntes/?opt=TrainRunning&subOpt=FindTrain&trainNo={train_no}&date={target_date}"
    
    for attempt in range(max_retries):
        try:
            logger.info(f"📡 Attempt {attempt + 1} for train {train_no} on date {target_date}")
            
            # Timeout increase kiya 30 seconds
            response = requests.get(url, headers=HEADERS, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"✅ Success on attempt {attempt + 1}")
                return parse_html(response.text, train_no, target_date)
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

def parse_html(html, train_no, target_date):
    """NTES HTML parse karo actual data nikalne ke liye"""
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # 🔍 ACTUAL SELECTORS - NTES ke current structure ke hisaab se
    # Ye selectors adjust karne pad sakte hain actual HTML dekh kar
    
    # Train name find karo
    train_name_elem = soup.find('span', {'id': 'lblTrainName'})
    if not train_name_elem:
        train_name_elem = soup.find('div', {'class': 'train-name'})
    if not train_name_elem:
        train_name_elem = soup.find('h3')
    
    train_name = train_name_elem.text.strip() if train_name_elem else f"Train {train_no}"
    
    # Running status find karo
    status_elem = soup.find('span', {'id': 'lblRunningStatus'})
    if not status_elem:
        status_elem = soup.find('div', {'class': 'status'})
    if not status_elem:
        status_elem = soup.find('p', {'class': 'running-status'})
    
    status = status_elem.text.strip() if status_elem else "Running"
    
    # Current location find karo
    location_elem = soup.find('span', {'id': 'lblLastLocation'})
    if not location_elem:
        location_elem = soup.find('div', {'class': 'location'})
    
    current_location = location_elem.text.strip() if location_elem else "N/A"
    
    # Delay find karo
    delay_elem = soup.find('span', {'id': 'lblDelay'})
    delay = delay_elem.text.strip() if delay_elem else "0"
    
    # Extract delay minutes
    delay_minutes = 0
    if 'late' in delay.lower():
        import re
        numbers = re.findall(r'\d+', delay)
        delay_minutes = int(numbers[0]) if numbers else 0
    
    return {
        "train_no": train_no,
        "train_name": train_name,
        "status": status,
        "current_location": current_location,
        "delay_minutes": delay_minutes,
        "date": target_date,
        "last_updated": datetime.now().strftime("%H:%M:%S"),
        "source": "NTES"
    }

@app.route('/health')
def health():
    """Health check endpoint - keep-alive ke liye"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "server": "Railway API Server"
    })

@app.route('/status/<train_no>')
def get_train_status(train_no):
    """Main endpoint - train status fetch karo"""
    
    logger.info(f"🔵 Request received for train: {train_no}")
    
    # 1. Aaj ki date try karo
    today = datetime.now().strftime('%d-%m-%Y')
    result = fetch_data_with_retry(train_no, today)
    
    # 2. Agar aaj ka data nahi mila to kal try karo
    if not result:
        logger.info(f"⚠️ No data for today, trying yesterday...")
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%d-%m-%Y')
        result = fetch_data_with_retry(train_no, yesterday)
    
    # 3. Agar kal ka bhi nahi mila to parson try karo
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

@app.route('/train/<train_no>')
def train_info(train_no):
    """Alias for /status endpoint"""
    return get_train_status(train_no)

if __name__ == "__main__":
    logger.info("🚂 Railway API Server Starting...")
    app.run(host='0.0.0.0', port=5000, debug=False)
