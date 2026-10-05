"""Read-only deployment preflight. Never prints secrets or database contents."""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1]/'.env')
url=(os.getenv('SUPABASE_URL') or '').rstrip('/')
key=os.getenv('SUPABASE_SERVICE_KEY')
schema=os.getenv('SUPABASE_SCHEMA','avsuite')
bucket=os.getenv('STUDIO_MEDIA_BUCKET','avsuite-media')
if not url or not key:
    raise SystemExit('Faltan SUPABASE_URL / SUPABASE_SERVICE_KEY.')
headers={'apikey':key,'Authorization':f'Bearer {key}','Accept-Profile':schema}
checks=[('Tabla del estudio',f'{url}/rest/v1/studio_records',{'select':'id','limit':'0'}),
        ('Bucket privado',f'{url}/storage/v1/bucket/{bucket}',None)]
failed=False
for label,endpoint,params in checks:
    try:
        response=requests.get(endpoint,headers=headers,params=params,timeout=15)
    except requests.RequestException:
        print(f'{label}: no se pudo contactar al servidor.')
        failed=True
        continue
    if response.ok:
        if label=='Bucket privado' and response.json().get('public'):
            print(f'{label}: debe cambiarse a privado.');failed=True
        else:print(f'{label}: disponible.')
    else:
        print(f'{label}: no disponible (HTTP {response.status_code}).');failed=True
sys.exit(1 if failed else 0)
