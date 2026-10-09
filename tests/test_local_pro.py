"""LOCAL_PRO_MODE: localhost enters as PRO without login or Supabase; nobody else does."""
import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio_backend import install_studio


class LocalProTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = {'GEMINI_API_KEY': 'test-key', 'LOCAL_PRO_MODE': '1', 'STUDIO_DATA_DIR': self.tmp.name}
        previous = sys.modules.pop('main', None)
        self.addCleanup(lambda: sys.modules.__setitem__('main', previous) if previous else sys.modules.pop('main', None))
        # Any Supabase call in this mode is a bug: there is no project to talk to.
        with patch.dict(os.environ, env, clear=True), patch('dotenv.load_dotenv', return_value=False), \
                patch('requests.request', side_effect=AssertionError('Supabase no debe usarse')):
            self.main = importlib.import_module('main')
        blocked = patch('requests.request', side_effect=AssertionError('Supabase no debe usarse'))
        blocked.start(); self.addCleanup(blocked.stop)
        app = FastAPI()
        app.add_api_route('/auth/check', self.main.auth_check)
        app.add_api_route('/exports', self.main.list_exports)
        app.add_api_route('/admin/users', self.main.list_users, dependencies=[self.main.Depends(self.main.require_superadmin)])
        install_studio(app, self.main.studio_store, self.main.get_current_user, {})
        self.app = app

    def client(self, host='127.0.0.1', base_url='http://localhost:8000'):
        client = TestClient(self.app, base_url=base_url, client=(host, 50000))
        client.__enter__(); self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_localhost_is_pro_without_token(self):
        client = self.client()
        data = client.get('/auth/check').json()
        self.assertEqual(data['role'], 'SUPERADMIN')
        self.assertEqual(data['tier'], 'PRO')
        self.assertTrue(data['unrestricted'])
        self.assertEqual(data['limits'], {})
        self.assertEqual(client.get('/admin/users').status_code, 200)
        self.assertEqual(client.get('/exports').status_code, 200)
        saved = client.put('/studio/workspace', json={'revision': 0, 'document': {'sessions': [], 'projects': [], 'brand': {}}})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(client.get('/studio/workspace').json()['revision'], saved.json()['revision'])
        self.main._record_usage(data['username'], 600)

    def test_exports_index_is_local(self):
        self.main._save_exports_index({'a.zip': {'username': 'x', 'created_at': '2026-10-09'}})
        self.assertEqual(self.main._get_export_owner('a.zip'), 'x')
        self.assertIsNone(self.main._get_export_owner('b.zip'))

    def test_other_origins_still_need_a_session(self):
        self.assertEqual(self.client(host='192.168.0.20').get('/auth/check').status_code, 401)
        self.assertEqual(self.client(base_url='http://evil.example').get('/auth/check').status_code, 401)
        local = self.client()
        self.assertEqual(local.get('/auth/check', headers={'X-Forwarded-For': '8.8.8.8'}).status_code, 401)
        self.assertEqual(local.get('/auth/check', headers={'Origin': 'https://evil.example'}).status_code, 401)
        self.assertEqual(local.get('/auth/check', headers={'Origin': 'http://localhost:8000'}).status_code, 200)
        # The local account has no password, so it can never be used through /auth/login.
        row = self.main._get_user_row(self.main.LOCAL_PRO_USERNAME)
        self.assertFalse(self.main._verify_password('', row['password_hash'], row['salt']))
