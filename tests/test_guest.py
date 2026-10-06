"""Public FREE entry: no user account, no saved history, private current files."""
import importlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import BaseModel

from studio_backend import install_studio
from studio_store import RecordStore


class Input(BaseModel):
    value: str


class GuestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = {'GEMINI_API_KEY': 'test-key', 'SUPABASE_URL': 'https://example.invalid',
               'SUPABASE_SERVICE_KEY': 'test-key', 'STUDIO_STORAGE': 'local', 'STUDIO_DATA_DIR': self.tmp.name}
        fake = SimpleNamespace(ok=True, status_code=200, json=lambda: [], text='')
        with patch.dict(os.environ, env, clear=True), patch('dotenv.load_dotenv', return_value=False), patch('requests.request', return_value=fake):
            self.main = importlib.import_module('main')
        self.store = RecordStore(self.tmp.name, mode='local')
        for name, value in [('studio_store', self.store), ('_rate_limit_buckets', {}), ('_user_active_jobs', {})]:
            change = patch.object(self.main, name, value); change.start(); self.addCleanup(change.stop)
        app = FastAPI()
        app.add_api_route('/auth/guest', self.main.auth_guest, methods=['POST'])
        app.add_api_route('/auth/check', self.main.auth_check)
        app.add_api_route('/auth/logout', self.main.auth_logout, methods=['POST'])
        app.add_api_route('/exports', self.main.list_exports)
        async def run(payload, user): return {'value': payload['value']}
        install_studio(app, self.store, self.main.get_current_user, {'pro': (Input, run, True), 'analyze': (Input, run, False)})
        self.client = TestClient(app); self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def guest(self):
        result = self.client.post('/auth/guest')
        self.assertEqual(result.status_code, 200)
        data = result.json()
        return data, {'X-API-Key': data['token']}

    def test_guest_limits_and_quota_survive_new_sessions(self):
        with patch.object(self.main, '_save_users', side_effect=AssertionError('No crear usuarios')):
            first, _ = self.guest(); second, headers = self.guest()
        self.assertNotEqual(first['username'], second['username'])
        self.assertEqual(first['plan'], 'FREE'); self.assertFalse(first['unrestricted'])
        self.assertFalse(first['limits']['history'])
        self.main._record_usage(first['username'], 600)
        self.assertEqual(self.client.get('/auth/check', headers=headers).json()['daily_usage_seconds'], 600)
        user = self.main.get_current_user(second['token'])
        with self.assertRaises(HTTPException): self.main._check_free_quota(user, 3001)
        with self.assertRaises(HTTPException): self.main._check_batch_allowed(user, 4)
        with self.assertRaises(HTTPException): self.main.require_pro(user)
        self.main._check_batch_allowed(user, 3)
        self.main._check_free_quota(user, 30)

    def test_guest_cannot_read_or_save_history_or_use_pro(self):
        _, headers = self.guest()
        for path in ['/studio/workspace', '/studio/jobs', '/studio/media', '/exports']:
            self.assertEqual(self.client.get(path, headers=headers).status_code, 403, path)
        self.assertEqual(self.client.put('/studio/workspace', headers=headers, json={'revision': 0, 'document': {'sessions': []}}).status_code, 403)
        self.assertEqual(self.client.post('/studio/jobs', headers=headers, json={'action': 'pro', 'payload': {'value': 'test'}}).status_code, 403)
        response = self.client.post('/studio/jobs', headers=headers, json={'action': 'analyze', 'payload': {'value': 'test'}})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.get('/studio/jobs/'+response.json()['id'], headers=headers).status_code, 200)
        _, other = self.guest()
        self.assertEqual(self.client.get('/studio/jobs/'+response.json()['id'], headers=other).status_code, 404)

    def test_current_files_are_private_and_logout_revokes_guest(self):
        _, headers = self.guest(); _, other = self.guest()
        data = io.BytesIO(); Image.new('RGB', (12, 12), 'blue').save(data, 'PNG')
        upload = self.client.post('/studio/media', headers=headers, files={'file': ('test.png', data.getvalue(), 'image/png')})
        self.assertEqual(upload.status_code, 200)
        path = '/studio/media/'+upload.json()['id']
        self.assertEqual(self.client.get(path, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(path, headers=other).status_code, 404)
        self.assertEqual(self.client.post('/auth/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/auth/check', headers=headers).status_code, 401)
