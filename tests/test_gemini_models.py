"""Quota rotation tests with fake providers; no API consumption."""
import io
import importlib
import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from PIL import Image

from gemini_models import ModelCooldowns, ModelsUnavailable, configured_models, generate_with_fallback
from studio_store import RecordStore
from studio_tools import ImageRequest, generate_images


class ProviderError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.now = [datetime(2026, 10, 5, 23, 59, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()]
        self.pool = ModelCooldowns(clock=lambda: self.now[0])
        self.patch = patch('gemini_models.cooldowns', self.pool)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_configuration_preserves_order_without_duplicates(self):
        with patch.dict(os.environ, {'GEMINI_IMAGE_MODELS': 'models/image-b, image-a, image-b'}):
            self.assertEqual(configured_models('GEMINI_IMAGE_MODELS', ['image-c'], 'image-a'), ['image-a', 'image-b'])
        with patch.dict(os.environ, {'GEMINI_IMAGE_MODELS': ' '}):
            self.assertEqual(configured_models('GEMINI_IMAGE_MODELS', ['image-c']), ['image-c'])

    def test_daily_and_zero_quotas_reset_at_pacific_midnight(self):
        for model, message in [('daily', '429 RESOURCE_EXHAUSTED quota PerDay'), ('zero', '429 limit: 0')]:
            self.pool.note_failure(model, ProviderError(429, message))
            self.assertIn(model, self.pool)
        self.now[0] += 60
        self.assertNotIn('daily', self.pool)
        self.assertNotIn('zero', self.pool)

    def test_minute_limit_and_missing_models_expire_separately(self):
        self.pool.note_failure('busy', ProviderError(429, '429 retryDelay: 15s'))
        self.pool.note_failure('missing', ProviderError(404, 'NOT_FOUND'))
        self.now[0] += 16
        self.assertNotIn('busy', self.pool)
        self.assertIn('missing', self.pool)
        self.now[0] += 3600
        self.assertNotIn('missing', self.pool)

    def test_rotation_skips_failed_models_without_waiting(self):
        calls = []
        def generate(**kwargs):
            model = kwargs['model']; calls.append(model)
            if model == 'quota': raise ProviderError(429, '429 quota PerDay')
            if model == 'missing': raise ProviderError(404, '404 NOT_FOUND')
            return SimpleNamespace(text='' if model == 'empty' else 'Valid answer')
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        response, used = generate_with_fallback(client, ['quota', 'missing', 'empty', 'working'],
            contents='prompt', config=None, valid=lambda r: bool(r.text), capability='texto')
        self.assertEqual(used, 'working')
        self.assertEqual(response.text, 'Valid answer')
        self.assertEqual(calls, ['quota', 'missing', 'empty', 'working'])
        calls.clear()
        generate_with_fallback(client, ['quota', 'missing', 'working'], contents='prompt', config=None,
            valid=lambda r: bool(r.text), capability='texto')
        self.assertEqual(calls, ['working'])

    def test_invalid_key_does_not_repeat_across_models(self):
        calls = []
        def generate(**kwargs):
            calls.append(kwargs['model']); raise ProviderError(401, 'Invalid key secret-provider-details')
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        with self.assertRaises(ModelsUnavailable) as error:
            generate_with_fallback(client, ['one', 'two'], contents='prompt', config=None, valid=bool, capability='texto')
        self.assertEqual(calls, ['one'])
        self.assertNotIn('secret-provider-details', str(error.exception))

    def test_main_text_rotates_then_skips_exhausted_model(self):
        with tempfile.TemporaryDirectory() as root:
            env = {'GEMINI_API_KEY': 'test-key', 'SUPABASE_URL': 'https://example.invalid',
                   'SUPABASE_SERVICE_KEY': 'test-key', 'STUDIO_STORAGE': 'local', 'STUDIO_DATA_DIR': root}
            fake_response = SimpleNamespace(ok=True, status_code=200, json=lambda: [], text='')
            with patch.dict(os.environ, env, clear=True), patch('dotenv.load_dotenv', return_value=False), patch('requests.request', return_value=fake_response):
                main = importlib.import_module('main')
            calls = []
            def generate(**kwargs):
                calls.append(kwargs['model'])
                if kwargs['model'] == 'text-quota': raise ProviderError(429, '429 quota PerDay')
                return SimpleNamespace(text='Respuesta válida del segundo modelo.')
            client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
            with patch.object(main, 'client', client), patch.object(main, 'GEMINI_MODELS', ['text-quota', 'text-good']), patch.object(main, '_exhausted_models', self.pool), patch.object(main, 'cooldowns', self.pool), patch.object(main.time, 'sleep', side_effect=AssertionError('No esperar entre alternativas')):
                self.assertIn('segundo modelo', main._call_gemini_text('Un prompt', max_cycles=1))
                main._call_gemini_text('Otro prompt', max_cycles=1)
            self.assertEqual(calls, ['text-quota', 'text-good', 'text-good'])

    def test_images_use_next_model_and_record_actual_provider(self):
        data = io.BytesIO(); Image.new('RGB', (24, 24), 'red').save(data, 'PNG')
        calls = []
        def generate(**kwargs):
            calls.append(kwargs['model'])
            if kwargs['model'] == 'image-quota': raise ProviderError(429, '429 limit: 0')
            return SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png', data=data.getvalue()))])
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'GEMINI_IMAGE_MODEL': '', 'GEMINI_IMAGE_MODELS': 'image-quota,image-good'}):
            store = RecordStore(root, mode='local')
            result = generate_images(client, store, 'alice', ImageRequest(prompt='Una imagen', variants=2))
            self.assertEqual(calls, ['image-quota', 'image-good', 'image-good'])
            self.assertTrue(all(image['metadata']['model'] == 'image-good' for image in result['images']))

    def test_images_stop_after_all_quotas_without_false_success(self):
        def generate(**kwargs): raise ProviderError(429, '429 limit: 0')
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'GEMINI_IMAGE_MODEL': '', 'GEMINI_IMAGE_MODELS': 'image-one,image-two'}):
            store = RecordStore(root, mode='local')
            with self.assertRaises(HTTPException) as error:
                generate_images(client, store, 'alice', ImageRequest(prompt='Una imagen'))
            self.assertEqual(error.exception.status_code, 429)
            self.assertIn('no ofrecen nivel gratuito', error.exception.detail)
            self.assertEqual(store.list('alice', 'media'), [])
