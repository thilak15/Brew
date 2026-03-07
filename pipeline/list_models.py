import os
from google import genai

def test_models():
    client = genai.Client()
    for m in client.models.list():
        if "imagen" in m.name.lower() or "image" in m.name.lower():
            print(m.name)

if __name__ == "__main__":
    test_models()
