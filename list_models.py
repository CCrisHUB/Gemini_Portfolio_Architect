import os
import requests
from dotenv import load_dotenv

# 1. Load the API key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("FATAL ERROR: API Key not found.")
    exit()

# 2. Query the Google REST API directly
print("System: Querying Google API for available models...")
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
response = requests.get(url)

# 3. Parse and print the results
if response.status_code == 200:
    models = response.json().get('models', [])
    print("\n=== AVAILABLE GEMINI MODELS FOR YOUR KEY ===")
    for m in models:
        name = m.get('name')
        # Filter to show only active text-generation models
        if 'gemini' in name and 'generateContent' in m.get('supportedGenerationMethods', []):
            print(name)
    print("============================================\n")
else:
    print(f"FATAL ERROR: HTTP {response.status_code}")
    print(response.text)