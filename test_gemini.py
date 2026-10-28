import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL")

print("API key loaded:", bool(api_key))
print("Configured model:", repr(model))

if not api_key or not model:
    raise SystemExit("Missing Gemini configuration in .env")

try:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents="Reply with exactly one word: OK",
    )
    print("Gemini response:", response.text)
except Exception as exc:
    print("Error type:", type(exc).__name__)
    print("Error details:", str(exc)[:1200])