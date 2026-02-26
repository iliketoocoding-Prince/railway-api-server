import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

# User-agent taaki NTES ko lage ki koi browser use kar raha hai
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def fetch_data(train_no, target_date):
    url = f"https://enquiry.indianrail.gov.in/mntes/?opt=TrainRunning&subOpt=FindTrain&trainNo={train_no}&date={target_date}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # NOTE: Agar NTES HTML change kare toh yahan soup.find badalna hoga
        # Hum train ka naam aur status nikalne ki koshish kar rahe hain
        train_name = soup.find('h1') # Dummy tag
        status_msg = soup.find('div', {'id': 'runningStatus'}) # Dummy ID
        
        return {
            "train_no": train_no,
            "train_name": train_name.text.strip() if train_name else "Unknown Train",
            "status": status_msg.text.strip() if status_msg else "Status Not Available",
            "date": target_date,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        print(f"Error: {e}")
        return None

@app.route('/status/<train_no>')
def get_train_status(train_no):
    # 1. Aaj ki date check karo
    today = datetime.now().strftime('%d-%m-%Y')
    result = fetch_data(train_no, today)
    
    # 2. Agar aaj data nahi mila (train starts yesterday), toh yesterday check karo
    if not result or "Not Available" in result['status']:
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%d-%m-%Y')
        result = fetch_data(train_no, yesterday)
        
    if result:
        return jsonify(result)
    else:
        return jsonify({"error": "Train data not found"}), 404

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
