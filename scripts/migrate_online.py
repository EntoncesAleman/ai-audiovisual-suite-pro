"""Apply the reviewed studio migration through Supabase's Management API.

Requires a personal access token with database write access, never a service key.
Provider responses and credentials are deliberately excluded from output.
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


def main():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    token = os.getenv('SUPABASE_ACCESS_TOKEN')
    if not token:
        raise SystemExit('Falta SUPABASE_ACCESS_TOKEN: la clave de servicio no puede ejecutar SQL.')
    hostname = urlparse(os.getenv('SUPABASE_URL', '')).hostname or ''
    match = re.fullmatch(r'([a-z0-9]+)\.supabase\.co', hostname)
    if not match:
        raise SystemExit('SUPABASE_URL debe identificar el proyecto Supabase alojado.')
    if os.getenv('SUPABASE_SCHEMA', 'avsuite') != 'avsuite' or os.getenv('STUDIO_MEDIA_BUCKET', 'avsuite-media') != 'avsuite-media':
        raise SystemExit('El schema/bucket configurado no coincide con la migración revisada.')
    sql = (root / 'migrations/001_online_studio.sql').read_text()
    try:
        response = requests.post(
            f'https://api.supabase.com/v1/projects/{match[1]}/database/query',
            headers={'Authorization': f'Bearer {token}'},
            json={'query': sql, 'read_only': False}, timeout=(10, 120),
        )
    except requests.RequestException:
        raise SystemExit('No se confirmó la migración. Verificá Supabase antes de reintentar o publicar.')
    if not response.ok:
        raise SystemExit(f'Migración no confirmada (HTTP {response.status_code}). Verificá permisos Database Write y SQL Editor.')
    print('Migración SQL confirmada por Supabase. Verificando Data API y almacenamiento…')
    return subprocess.call([sys.executable, str(root / 'scripts/check_online.py')], cwd=root)


if __name__ == '__main__':
    sys.exit(main())
