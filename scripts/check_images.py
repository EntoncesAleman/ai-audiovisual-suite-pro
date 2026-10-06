"""Optional live smoke test: consumes ONE image generation; writes only to /tmp."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from google import genai
from PIL import Image
from studio_store import RecordStore
from studio_tools import ImageRequest, generate_images

load_dotenv(Path(__file__).resolve().parents[1]/'.env')
key=os.getenv('GEMINI_API_KEY')
if not key:raise SystemExit('Falta GEMINI_API_KEY.')
with tempfile.TemporaryDirectory(prefix='avsuite_image_smoke_') as root:
    store=RecordStore(root,mode='local')
    try:
        from google.genai import types
        client=genai.Client(api_key=key,http_options=types.HttpOptions(timeout=30000,retry_options=types.HttpRetryOptions(attempts=1)))
        result=generate_images(client,store,'qa',ImageRequest(prompt='Una placa abstracta minimalista, fondo azul y círculo dorado, sin texto.',aspect_ratio='16:9'))
        path,_=store.media_path('qa',result['images'][0]['id'])
        with Image.open(path) as image:print(f'Imagen verificada: {image.width} × {image.height}.')
    except Exception as error:
        # No full provider error: it may include identifiers or request details.
        print(f'No se pudo generar la imagen. Tipo: {type(error).__name__}; código: {getattr(error,"code",getattr(error,"status_code","sin código"))}.')
        sys.exit(1)
