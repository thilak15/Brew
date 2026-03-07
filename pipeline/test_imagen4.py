import os
import io
from google import genai
from PIL import Image

def test_imagen4():
    try:
        client = genai.Client()
        response = client.models.generate_images(
            model='imagen-4.0-fast-generate-001',
            prompt='A delicious hamburger with perfectly melted cheese, lettuce, and tomato, highly detailed food photography on a solid background.',
            config=dict(
                number_of_images=1,
                aspect_ratio="1:1"
            )
        )
        for gen_img in response.generated_images:
            image = Image.open(io.BytesIO(gen_img.image.image_bytes))
            image.save("/tmp/test_burger_v4.png")
            print("Successfully saved image to /tmp/test_burger_v4.png")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_imagen4()
