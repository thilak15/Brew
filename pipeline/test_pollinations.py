import urllib.parse
import urllib.request
from PIL import Image
import io

def test_pollinations():
    try:
        prompt = "A delicious fast food hamburger with perfectly melted cheese, highly detailed food photography on a solid background."
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&nologo=true"
        print(f"Fetching from {url}...")
        
        req = urllib.request.Request(url, headers={'User-Agent': 'DriveAI-Test/1.0'})
        with urllib.request.urlopen(req) as response:
            image_bytes = response.read()
            image = Image.open(io.BytesIO(image_bytes))
            image.save("/tmp/test_burger.png")
            print("Successfully saved image via Pollinations!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_pollinations()
