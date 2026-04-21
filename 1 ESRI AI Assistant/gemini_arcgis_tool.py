

import arcpy
import requests

# Get user input
user_prompt = arcpy.GetParameterAsText(0)

API_KEY = "Add Your API_KEY"

url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={API_KEY}"

headers = {
    "Content-Type": "application/json"
}

data = {
    "contents": [
        {
            "parts": [
                {"text": user_prompt}
            ]
        }
    ]
}

response = requests.post(url, headers=headers, json=data)

if response.status_code == 200:
    result = response.json()
    output_text = result["candidates"][0]["content"]["parts"][0]["text"]
    arcpy.AddMessage(output_text)
else:
    arcpy.AddError("Error from Gemini API:")
    arcpy.AddError(str(response.json()))

    
