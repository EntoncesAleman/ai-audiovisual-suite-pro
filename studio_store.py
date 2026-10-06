"""Private studio records and media. Supabase online; SQLite for local use/tests."""
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import requests
from fastapi import HTTPException


class RecordStore:
    def __init__(self, root, mode="supabase", url="", key="", schema="avsuite"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.mode, self.url, self.key, self.schema = mode, url.rstrip("/"), key, schema
        self.bucket = os.getenv("STUDIO_MEDIA_BUCKET", "avsuite-media")
        if mode == "local":
            with self.connection() as db:
                db.execute("CREATE TABLE IF NOT EXISTS records (owner TEXT, kind TEXT, id TEXT, payload TEXT, revision INTEGER, updated REAL, PRIMARY KEY(owner,kind,id))")
        elif mode != "supabase":
            raise ValueError("STUDIO_STORAGE debe ser supabase o local")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.root / "studio.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def request(self, method, path, **kwargs):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
                   "Accept-Profile": self.schema, "Content-Profile": self.schema}
        headers.update(kwargs.pop("headers", {}))
        try:
            response = requests.request(method, f"{self.url}{path}", headers=headers, timeout=(10, 180), **kwargs)
        except requests.RequestException as exc:
            raise HTTPException(503, "No se pudo contactar al almacenamiento. Reintentá sin cerrar el proyecto.") from exc
        if not response.ok:
            # Never return provider responses: they can contain keys, paths or SQL.
            if response.status_code == 409:
                raise HTTPException(409, "El proyecto cambió en otra pestaña. Revisá la versión online antes de guardar.")
            raise HTTPException(503, "El almacenamiento online no está disponible. Verificá la migración del estudio y el bucket privado.")
        return response

    @staticmethod
    def decode(row):
        if not row:
            return None
        row = dict(row)
        if isinstance(row["payload"], str):
            row["payload"] = json.loads(row["payload"])
        return row

    def get(self, owner, kind, record_id):
        if self.mode == "local":
            with self.connection() as db:
                return self.decode(db.execute("SELECT * FROM records WHERE owner=? AND kind=? AND id=?", (owner, kind, record_id)).fetchone())
        rows = self.request("GET", "/rest/v1/studio_records", params={"owner": f"eq.{owner}", "kind": f"eq.{kind}", "id": f"eq.{record_id}", "limit": "1"}).json()
        return rows[0] if rows else None

    def list(self, owner, kind, limit=100):
        if self.mode == "local":
            with self.connection() as db:
                return [self.decode(row) for row in db.execute("SELECT * FROM records WHERE owner=? AND kind=? ORDER BY updated DESC LIMIT ?", (owner, kind, limit))]
        return self.request("GET", "/rest/v1/studio_records", params={"owner": f"eq.{owner}", "kind": f"eq.{kind}", "order": "updated.desc", "limit": str(limit)}).json()

    def put(self, owner, kind, record_id, payload, expected=None):
        if self.mode == "local":
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT revision FROM records WHERE owner=? AND kind=? AND id=?", (owner, kind, record_id)).fetchone()
                revision = row["revision"] if row else 0
                if expected is not None and expected != revision:
                    raise HTTPException(409, "El proyecto cambió en otra pestaña. Revisá la versión online antes de guardar.")
                result = {"owner": owner, "kind": kind, "id": record_id, "payload": payload, "revision": revision + 1, "updated": time.time()}
                db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)", (owner, kind, record_id, json.dumps(payload), result["revision"], result["updated"]))
                return result
        result = self.request("POST", "/rest/v1/rpc/studio_write", json={"p_owner": owner, "p_kind": kind, "p_id": record_id, "p_payload": payload, "p_expected": expected}).json()
        if result.get("conflict"):
            raise HTTPException(409, "El proyecto cambió en otra pestaña. Revisá la versión online antes de guardar.")
        return result

    def owner_dir(self, owner):
        folder = self.root / "media" / hashlib.sha256(owner.encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def save_media(self, owner, source, name=None, kind="source", media_id=None, metadata=None):
        import shutil
        source = Path(source)
        media_id = media_id or uuid.uuid4().hex
        if not media_id.isalnum():
            raise ValueError("Identificador inválido")
        suffix = source.suffix.lower()
        if len(suffix) > 10 or not suffix.lstrip(".").isalnum():
            suffix = ".bin"
        target = self.owner_dir(owner) / f"{media_id}{suffix}"
        if source.resolve() != target:
            shutil.copyfile(source, target)
        object_key = f"{hashlib.sha256(owner.encode()).hexdigest()}/{target.name}"
        if self.mode == "supabase":
            with target.open("rb") as content:
                self.request("POST", f"/storage/v1/object/{self.bucket}/{object_key}", data=content,
                             headers={"Content-Type": "application/octet-stream", "x-upsert": "true"})
        safe_name = (name or source.name).replace("\\", "/").rsplit("/", 1)[-1][:200] or target.name
        payload = {"name": safe_name, "kind": kind, "suffix": suffix,
                   "object_key": object_key, "bytes": target.stat().st_size, "created_at": time.time(),
                   "metadata": metadata or {}}
        self.put(owner, "media", media_id, payload)
        return {"id": media_id, **payload, "download_url": f"/studio/media/{media_id}"}

    def media_path(self, owner, media_id):
        if not media_id or not media_id.isalnum():
            raise HTTPException(400, "Identificador de archivo inválido.")
        row = self.get(owner, "media", media_id)
        if not row:
            raise HTTPException(404, "Archivo no encontrado para esta cuenta.")
        data = row["payload"]
        path = self.owner_dir(owner) / f"{media_id}{data['suffix']}"
        if not path.exists() and self.mode == "supabase":
            response = self.request("GET", f"/storage/v1/object/authenticated/{self.bucket}/{quote(data['object_key'], safe='/')}", stream=True)
            temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.part")
            try:
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        output.write(chunk)
                temporary.replace(path)
            finally:
                response.close()
                temporary.unlink(missing_ok=True)
        if not path.exists():
            raise HTTPException(404, "El archivo ya no está disponible.")
        return path, data

    def reserve_quota(self, owner, key, amount, maximum):
        for _ in range(10):
            row = self.get(owner, "quota", key)
            used = row["payload"].get("used", 0) if row else 0
            if used + amount > maximum:
                raise HTTPException(429, "Alcanzaste la cuota de esta herramienta por hoy. Cada variante o clip solicitado cuenta como un intento.")
            try:
                self.put(owner, "quota", key, {"used": used + amount}, row["revision"] if row else 0)
                return
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        raise HTTPException(503, "No se pudo reservar cuota. Reintentá en unos segundos.")

    def delete_media(self, owner, media_id):
        row=self.get(owner,"media",media_id)
        if not row:
            raise HTTPException(404,"Archivo no encontrado para esta cuenta.")
        data=row["payload"]
        if self.mode=="supabase":
            self.request("DELETE",f"/storage/v1/object/{self.bucket}",json={"prefixes":[data["object_key"]]})
            self.request("DELETE","/rest/v1/studio_records",params={"owner":f"eq.{owner}","kind":"eq.media","id":f"eq.{media_id}"})
        else:
            with self.connection() as db:
                db.execute("DELETE FROM records WHERE owner=? AND kind='media' AND id=?",(owner,media_id))
        (self.owner_dir(owner)/f"{media_id}{data['suffix']}").unlink(missing_ok=True)

    def save_session(self, token, username, role):
        session={"username":username,"role":role,"expires_at":time.time()+(24*3600 if role=='GUEST' else 7*24*3600)}
        self.put("__sessions","session",hashlib.sha256(token.encode()).hexdigest(),session)
        return session

    def get_session(self, token):
        if not token or len(token)!=48 or any(c not in '0123456789abcdef' for c in token):
            return None
        row=self.get("__sessions","session",hashlib.sha256(token.encode()).hexdigest())
        return row["payload"] if row and row["payload"].get("expires_at",0)>time.time() else None

    def revoke_session(self, token):
        token_id=hashlib.sha256(token.encode()).hexdigest()
        if self.mode=="local":
            with self.connection() as db:db.execute("DELETE FROM records WHERE owner='__sessions' AND kind='session' AND id=?",(token_id,))
        else:
            self.request("DELETE","/rest/v1/studio_records",params={"owner":"eq.__sessions","kind":"eq.session","id":f"eq.{token_id}"})

    def revoke_user_sessions(self, username):
        if self.mode=="local":
            with self.connection() as db:db.execute("DELETE FROM records WHERE owner='__sessions' AND kind='session' AND json_extract(payload,'$.username')=?",(username,))
        else:
            self.request("DELETE","/rest/v1/studio_records",params={"owner":"eq.__sessions","kind":"eq.session","payload->>username":f"eq.{username}"})
