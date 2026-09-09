import os
import requests
import json
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("FATAL ERROR: GEMINI_API_KEY not found. Check your .env file.")
    exit()

# 2. Define the target model and endpoint
model_name = "gemini-3.6-flash" 
url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

# 3. Construct the strict JSON payload
headers = {'Content-Type': 'application/json'}
payload = {
    "contents": [{
        "parts": [{"text": "Acknowledge connection. Reply with exactly: 'API BOUNDARY ESTABLISHED.'"}]
    }],
    "generationConfig": {
        "temperature": 0.0, 
        "maxOutputTokens": 800 # Increased to accommodate reasoning overhead
    }
}

# 4. Execute the API call
print(f"System: Attempting connection to {model_name} via REST API...")
try:
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    
    if response.status_code == 200:
        response_data = response.json()
        candidate = response_data.get('candidates', [{}])[0]
        
        # Check if the model was cut off
        if candidate.get('finishReason') == 'MAX_TOKENS':
            print("FATAL ERROR: Model hit token limit before finishing.")
        else:
            # Safely extract the text
            try:
                text_output = candidate['content']['parts'][0]['text']
                print(f"Response: {text_output.strip()}")
            except KeyError:
                print("FATAL ERROR: Unexpected JSON structure. Raw output:")
                print(json.dumps(response_data, indent=2))
    else:
        print(f"FATAL ERROR: HTTP {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"FATAL ERROR during API call: {e}")