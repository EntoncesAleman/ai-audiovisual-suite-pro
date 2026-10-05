"""Online workspace, private uploads and detached, observable studio jobs."""
import asyncio
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError


class WorkspaceInput(BaseModel):
    revision: int = Field(ge=0)
    document: dict[str, Any]


class JobInput(BaseModel):
    action: str = Field(max_length=50)
    payload: dict[str, Any]
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-zA-Z0-9-]{16,64}$")


def account(user):
    username = user.get("username")
    if not username or username == "legacy":
        raise HTTPException(401, "Ingresá con tu cuenta personal para usar el estudio online.")
    return username


async def upload_media(store, user, file, max_bytes=512 * 1024 * 1024, inspect=None):
    owner = account(user)
    media_id = uuid.uuid4().hex
    suffix = Path(file.filename or "archivo.bin").suffix.lower()
    allowed = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".png", ".jpg", ".jpeg", ".webp"}
    if suffix not in allowed:
        raise HTTPException(415, "Subí un video, audio o imagen compatible.")
    temporary = store.owner_dir(owner) / f"upload_{media_id}{suffix}"
    try:
        size = 0
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
                await asyncio.to_thread(output.write, chunk)
        if not size:
            raise HTTPException(400, "El archivo está vacío.")
        metadata = {}
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            from PIL import Image
            try:
                with Image.open(temporary) as image:
                    image.verify()
                with Image.open(temporary) as image:
                    metadata = {"width": image.width, "height": image.height}
            except Exception as exc:
                raise HTTPException(400, "La imagen no se pudo leer.") from exc
        elif inspect:
            metadata = await asyncio.to_thread(inspect, str(temporary))
            if not metadata.get("has_audio") and not metadata.get("has_video"):
                raise HTTPException(400, "El archivo no contiene audio ni video legible.")
        return await asyncio.to_thread(store.save_media, owner, temporary, file.filename, "source", media_id, metadata)
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()


class JobManager:
    def __init__(self, store, handlers):
        self.store, self.handlers = store, handlers
        self.tasks = set()
        self.submission_lock = asyncio.Lock()

    async def submit(self, body, user):
        owner = account(user)
        if body.action not in self.handlers:
            raise HTTPException(400, "Tipo de trabajo no disponible.")
        model, handler, pro = self.handlers[body.action]
        if pro and user.get("plan") != "PRO" and not user.get("unrestricted"):
            raise HTTPException(403, "Esta herramienta requiere el plan PRO.")
        try:
            validated = model.model_validate(body.payload).model_dump()
        except ValidationError as exc:
            raise HTTPException(422, "Revisá los parámetros del trabajo.") from exc
        if len(json.dumps(validated)) > 2 * 1024 * 1024:
            raise HTTPException(413, "El pedido es demasiado grande.")
        async with self.submission_lock:
            existing = await asyncio.to_thread(self.store.get, owner, "job", body.request_id)
            if existing:
                return self.public(existing)
            jobs = await asyncio.to_thread(self.store.list, owner, "job", 100)
            running = [row for row in jobs if row["payload"]["status"] in {"queued", "running"} and time.time() - row["updated"] < 300]
            maximum = 3 if user.get("plan") == "PRO" or user.get("unrestricted") else 1
            if len(running) >= maximum:
                raise HTTPException(429, "Ya tenés trabajos en curso. Esperá a que termine alguno.")
            if body.action == "generate-images":
                today = time.strftime("%Y-%m-%d", time.gmtime())
                await asyncio.to_thread(self.store.reserve_quota, owner, "images:" + today, validated.get("variants", 1), 30)
            data = {"action": body.action, "status": "queued", "created_at": time.time(), "events": [], "result": None,
                    "label": body.action.replace("-", " "), "usage_day": time.strftime("%Y-%m-%d", time.gmtime()),
                    "image_count": validated.get("variants", 0) if body.action == "generate-images" else 0}
            data["request"]=validated
            data["media_ids"]=[validated[key] for key in ["asset_id","cache_key","music_id","reference_id"] if validated.get(key)]+validated.get("media_ids",[])
            row = await asyncio.to_thread(self.store.put, owner, "job", body.request_id, data, 0)
            task = asyncio.create_task(self.run(row, validated, user, handler))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return self.public(row)

    async def run(self, row, payload, user, handler):
        owner, job_id, data = row["owner"], row["id"], row["payload"]
        write_lock = asyncio.Lock()
        async def persist():
            async with write_lock:
                await asyncio.to_thread(self.store.put, owner, "job", job_id, json.loads(json.dumps(data)))
        async def heartbeat():
            while True:
                await asyncio.sleep(30)
                await persist()
        timer = None
        try:
            data["status"] = "running"
            await persist()
            timer = asyncio.create_task(heartbeat())
            response = await handler(payload, user)
            if hasattr(response, "body_iterator"):
                buffer = ""
                async for chunk in response.body_iterator:
                    buffer += chunk.decode() if isinstance(chunk, bytes) else chunk
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        lines = [line[5:].strip() for line in frame.splitlines() if line.startswith("data:")]
                        if not lines:
                            continue
                        event = json.loads("\n".join(lines))
                        if isinstance(event.get("result"), dict):
                            if data["action"] == "analyze-url":
                                event["result"]["source_url"] = payload.get("url", "")
                            elif data["action"] == "analyze-file":
                                event["result"]["asset_id"] = payload.get("asset_id", "")
                        data["event_seq"] = data.get("event_seq", 0) + 1
                        event["seq"] = data["event_seq"]
                        data["events"].append(event)
                        data["events"] = data["events"][-80:]
                        data["message"] = event.get("message", "")
                        if event.get("stage") == "error":
                            data["status"] = "error"
                        elif event.get("stage") == "done":
                            data["status"] = "done"
                            data["result"] = event
                        await persist()
                if data["status"] == "running":
                    raise RuntimeError("El trabajo terminó sin confirmar el resultado.")
            else:
                data["result"] = response
                data["status"] = "done"
                data["message"] = "Trabajo completado."
                data["event_seq"] = data.get("event_seq", 0) + 1
                data["events"].append({"stage": "done", "message": data["message"], "result": response, "seq": data["event_seq"]})
        except asyncio.CancelledError:
            data["status"], data["message"] = "interrupted", "El servidor se reinició durante el trabajo. Podés volver a iniciarlo."
            raise
        except Exception as exc:
            data["status"] = "error"
            data["message"] = exc.detail if isinstance(exc, HTTPException) else "No se pudo completar el trabajo. Revisá los parámetros y reintentá."
            data["event_seq"] = data.get("event_seq", 0) + 1
            data["events"].append({"stage": "error", "message": data["message"], "seq": data["event_seq"]})
            import logging
            logging.getLogger(__name__).exception("Studio job failed: %s", job_id)
        finally:
            if timer:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)
            data["finished_at"] = time.time()
            try:
                await persist()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Could not save final job status: %s", job_id)

    @staticmethod
    def public(row):
        data = dict(row["payload"])
        data.pop("request",None)
        if data["status"] in {"queued", "running"} and time.time() - row["updated"] > 300:
            data["status"] = "interrupted"
            data["message"] = "El servidor dejó de responder durante este trabajo. Podés volver a iniciarlo."
        return {"id": row["id"], "updated_at": row["updated"], **data}


def install_studio(app, store, current_user, handlers, inspect=None):
    manager = JobManager(store, handlers)

    @app.get("/studio/workspace")
    async def workspace(user: dict = Depends(current_user)):
        row = await asyncio.to_thread(store.get, account(user), "workspace", "main")
        return {"revision": row["revision"] if row else 0, "document": row["payload"] if row else {"sessions": [], "projects": [], "brand": {}}}

    @app.put("/studio/workspace")
    async def save_workspace(body: WorkspaceInput, user: dict = Depends(current_user)):
        if len(json.dumps(body.document)) > 8 * 1024 * 1024:
            raise HTTPException(413, "El proyecto supera el máximo de guardado. Exportá parte del historial.")
        if not isinstance(body.document.get("sessions", []), list) or not isinstance(body.document.get("projects", []), list):
            raise HTTPException(422, "Formato de proyecto inválido.")
        row = await asyncio.to_thread(store.put, account(user), "workspace", "main", body.document, body.revision)
        return {"revision": row["revision"], "document": row["payload"]}

    @app.post("/studio/media")
    async def upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
        return await upload_media(store, user, file, inspect=inspect)

    @app.get("/studio/media")
    async def media_list(user: dict = Depends(current_user)):
        rows = await asyncio.to_thread(store.list, account(user), "media", 100)
        return {"media": [{"id": row["id"], **row["payload"], "download_url": f"/studio/media/{row['id']}"} for row in rows]}

    @app.get("/studio/media/{media_id}")
    async def download_media(media_id: str, user: dict = Depends(current_user)):
        path, data = await asyncio.to_thread(store.media_path, account(user), media_id)
        return FileResponse(path, filename=data["name"], media_type=mimetypes.guess_type(data["name"])[0] or "application/octet-stream")

    @app.delete("/studio/media/{media_id}")
    async def delete_media(media_id: str, user: dict = Depends(current_user)):
        owner=account(user)
        jobs=await asyncio.to_thread(store.list,owner,"job",100)
        if any(row["payload"]["status"] in {"queued","running"} and time.time()-row["updated"]<300 and media_id in row["payload"].get("media_ids",[]) for row in jobs):
            raise HTTPException(409,"Este archivo se está usando en un trabajo. Esperá a que termine.")
        await asyncio.to_thread(store.delete_media,owner,media_id)
        return {"deleted":True}

    @app.post("/studio/jobs", status_code=202)
    async def submit_job(body: JobInput, user: dict = Depends(current_user)):
        return await manager.submit(body, user)

    @app.get("/studio/jobs")
    async def list_jobs(user: dict = Depends(current_user)):
        rows = await asyncio.to_thread(store.list, account(user), "job", 50)
        return {"jobs": [manager.public(row) for row in rows]}

    @app.get("/studio/jobs/{job_id}")
    async def get_job(job_id: str, user: dict = Depends(current_user)):
        row = await asyncio.to_thread(store.get, account(user), "job", job_id)
        if not row:
            raise HTTPException(404, "Trabajo no encontrado para esta cuenta.")
        return manager.public(row)

    @app.post("/studio/jobs/{job_id}/retry",status_code=202)
    async def retry_job(job_id: str, user: dict = Depends(current_user)):
        row=await asyncio.to_thread(store.get,account(user),"job",job_id)
        if not row:
            raise HTTPException(404,"Trabajo no encontrado para esta cuenta.")
        if manager.public(row)["status"] not in {"error","interrupted"}:
            raise HTTPException(409,"Solo se pueden reintentar trabajos fallidos o interrumpidos.")
        if not row["payload"].get("request"):
            raise HTTPException(409,"Este trabajo anterior no conservó sus parámetros. Inicialo desde el editor.")
        return await manager.submit(JobInput(action=row["payload"]["action"],payload=row["payload"]["request"]),user)

    return manager
