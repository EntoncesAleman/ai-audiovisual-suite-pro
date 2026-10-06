"""Ordered Gemini alternatives and expiring quota cooldowns (one API key)."""
import os
import re
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# Models with a documented free tier. Availability depends on the API project.
TEXT_MODELS = ('gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite',
               'gemini-3.1-flash-lite', 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3-flash-preview')
TTS_MODELS = ('gemini-3.8-flash-lite-tts', 'gemini-3.8-flash-tts',
              'gemini-3.1-flash-tts-preview', 'gemini-2.5-flash-preview-tts', 'gemini-2.5-pro-preview-tts')
# These only generate images if the project has image quota; no free tier today.
IMAGE_MODELS = ('gemini-3.1-flash-image', 'gemini-3.1-flash-lite-image', 'gemini-3-pro-image')


def configured_models(variable, defaults, preferred=None):
    configured = os.getenv(variable, '').strip()
    models = configured.split(',') if configured else defaults
    return list(dict.fromkeys(m.strip().removeprefix('models/') for m in ([preferred] if preferred else []) + list(models) if m.strip()))


def error_code(error):
    code = getattr(error, 'code', None) or getattr(error, 'status_code', None)
    try:
        return int(code)
    except (TypeError, ValueError):
        match = re.search(r'\b(400|401|403|404|429|500|502|503|504)\b', str(error))
        return int(match[1]) if match else None


def daily_quota_exhausted(error):
    message = str(error).lower()
    quota = error_code(error) == 429 or 'resource_exhausted' in message
    return quota and (any(word in message for word in ('perday', 'per_day', 'daily'))
                      or bool(re.search(r'["\']?(?:limit|quota_value|quotavalue)["\']?\s*[:=]\s*["\']?0\b', message)))


class ModelCooldowns:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.until = {}
        self.lock = threading.Lock()

    def __contains__(self, model):
        with self.lock:
            expiry = self.until.get(model, 0)
            if expiry <= self.clock():
                self.until.pop(model, None)
                return False
            return True

    def add(self, model, seconds=None):
        now = self.clock()
        if seconds is None:
            local = datetime.fromtimestamp(now, ZoneInfo('America/Los_Angeles'))
            tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            seconds = max(1, tomorrow.timestamp() - now)
        with self.lock:
            self.until[model] = max(self.until.get(model, 0), now + seconds)

    def note_failure(self, model, error):
        code = error_code(error)
        if daily_quota_exhausted(error):
            self.add(model)
        elif code == 404:
            self.add(model, 3600)
        elif code == 429:
            match = re.search(r'retry[_ ]?delay["\']?\s*[:=]\s*["\']?(\d+)', str(error), re.I)
            self.add(model, max(1, min(int(match[1]) if match else 60, 300)))
        elif code in (500, 502, 503, 504):
            self.add(model, 30)


cooldowns = ModelCooldowns()


class ModelsUnavailable(Exception):
    def __init__(self, capability, quota=False):
        self.quota = quota
        super().__init__(f'No hay un modelo Gemini disponible para {capability} con esta clave. Se probaron las alternativas disponibles; revisá la cuota o reintentá más tarde.')


def generate_with_fallback(client, models, *, contents, config, valid, capability):
    quota = False
    for model in models:
        if model in cooldowns:
            quota = True
            continue
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            if valid(response):
                return response, model
        except Exception as error:
            # A different model cannot repair an invalid API key.
            if error_code(error) == 401:
                raise ModelsUnavailable(capability) from None
            quota = quota or error_code(error) == 429
            cooldowns.note_failure(model, error)
    raise ModelsUnavailable(capability, quota) from None
