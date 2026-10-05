import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel

from studio_backend import install_studio, upload_media
from studio_store import RecordStore
from studio_tools import CampaignRequest, ImageRequest, generate_campaign, generate_images


class ValueInput(BaseModel):
    value: str


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = RecordStore(self.tmp.name, mode="local")

    def test_workspace_conflicts_do_not_overwrite_other_tab(self):
        self.store.put("alice", "workspace", "main", {"sessions": [1]}, expected=0)
        with self.assertRaises(HTTPException) as error:
            self.store.put("alice", "workspace", "main", {"sessions": [2]}, expected=0)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.store.get("alice", "workspace", "main")["payload"]["sessions"], [1])
        self.assertIsNone(self.store.get("bob", "workspace", "main"))

    def test_media_owner_and_path_validation(self):
        source = Path(self.tmp.name) / "source.mp4"
        source.write_bytes(b"synthetic")
        media = self.store.save_media("alice", source)
        with self.assertRaises(HTTPException) as error:
            self.store.media_path("bob", media["id"])
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.store.media_path("alice", "../../source")
        source.unlink()
        restored, _ = self.store.media_path("alice", media["id"])
        self.assertEqual(restored.read_bytes(), b"synthetic")
        reopened = RecordStore(self.tmp.name, mode="local")
        self.assertEqual(reopened.media_path("alice", media["id"])[0].read_bytes(), b"synthetic")

    def test_private_object_restored_after_local_cache_loss(self):
        online = RecordStore(self.tmp.name, mode="supabase", url="https://example.invalid", key="test")
        objects, rows = {}, {}
        def request(method, path, **kwargs):
            if path.startswith('/storage/v1/object/'):
                if method == 'POST':
                    objects[path.rsplit('/',1)[-1]] = kwargs['data'].read()
                    return SimpleNamespace()
                value = objects[path.rsplit('/',1)[-1]]
                return SimpleNamespace(iter_content=lambda size: [value],close=lambda:None)
            if method == 'POST':
                data=kwargs['json']; key=(data['p_owner'],data['p_kind'],data['p_id'])
                row={'owner':key[0],'kind':key[1],'id':key[2],'payload':data['p_payload'],'revision':1,'updated':0};rows[key]=row
                return SimpleNamespace(json=lambda:row)
            params=kwargs['params']; key=tuple(params[field][3:] for field in ['owner','kind','id'])
            return SimpleNamespace(json=lambda:[rows[key]] if key in rows else [])
        online.request=request
        source=Path(self.tmp.name)/'clip.mp4';source.write_bytes(b'persisted object')
        asset=online.save_media('alice',source)
        local,_=online.media_path('alice',asset['id']);local.unlink();source.unlink()
        restored,_=online.media_path('alice',asset['id'])
        self.assertEqual(restored.read_bytes(),b'persisted object')

    def test_image_generation_and_foreign_reference(self):
        data=io.BytesIO();Image.new('RGB',(24,24),'red').save(data,'PNG')
        part=SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png',data=data.getvalue()))
        fake=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:SimpleNamespace(parts=[part])))
        result=generate_images(fake,self.store,'alice',ImageRequest(prompt='Una imagen',variants=2))
        self.assertEqual(len(result['images']),2)
        with self.assertRaises(HTTPException):
            generate_images(fake,self.store,'bob',ImageRequest(prompt='Editar imagen',reference_id=result['images'][0]['id']))
        for image in result['images']:
            path,_=self.store.media_path('alice',image['id'])
            with Image.open(path) as generated:self.assertEqual(generated.size,(24,24))

    def test_campaign_rejects_invented_clip_indexes(self):
        request=CampaignRequest(transcript='TIMESTAMP: 00:00\nDIALOGUE: Una entrevista.',clips=[{'id':'clip_a','start':'00:00','end':'00:05'}])
        def response(index):
            return json.dumps({'title':'Campaña','clips':[{'clip_index':index,'title':'Título','caption':'Copy','image_prompt':'Imagen'}]})
        with self.assertRaises(HTTPException):generate_campaign(lambda prompt:response(4),request)
        result=generate_campaign(lambda prompt:response(0),request)
        self.assertEqual(result['source_ids'],['clip_a'])

    def test_quota_reservation_and_private_deletion(self):
        self.store.reserve_quota('alice','images:today',29,30)
        self.store.reserve_quota('alice','images:today',1,30)
        with self.assertRaises(HTTPException) as error:self.store.reserve_quota('alice','images:today',1,30)
        self.assertEqual(error.exception.status_code,429)
        self.store.reserve_quota('bob','images:today',1,30)
        source=Path(self.tmp.name)/'test.mp4';source.write_bytes(b'file')
        media=self.store.save_media('alice',source)
        with self.assertRaises(HTTPException):self.store.delete_media('bob',media['id'])
        self.store.delete_media('alice',media['id'])
        self.assertIsNone(self.store.get('alice','media',media['id']));self.assertTrue(source.exists())

    def test_sessions_survive_restart_and_revoke_per_user(self):
        token_a='a'*48;token_b='b'*48
        self.store.save_session(token_a,'alice','USER');self.store.save_session(token_b,'bob','USER')
        restarted=RecordStore(self.tmp.name,mode='local')
        self.assertEqual(restarted.get_session(token_a)['username'],'alice')
        self.assertIsNone(restarted.get_session('../../token'))
        restarted.revoke_user_sessions('alice')
        self.assertIsNone(restarted.get_session(token_a));self.assertEqual(restarted.get_session(token_b)['username'],'bob')
        restarted.revoke_session(token_b);self.assertIsNone(restarted.get_session(token_b))


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=RecordStore(self.tmp.name,mode='local')
        self.app=FastAPI()
        self.done=asyncio.Event()
        async def current(x_api_key: str = Header(default='')):
            if x_api_key not in {'alice','bob','free'}:raise HTTPException(401,'Ingresá')
            return {'username':x_api_key,'plan':'FREE' if x_api_key=='free' else 'PRO','unrestricted':False}
        async def work(payload,user):
            async def events():
                yield 'data: {"stage":"info","message":"En curso"}\n\n'
                await asyncio.sleep(.04)
                yield 'data: '+json.dumps({'stage':'done','message':'Listo','result':{'value':payload['value']}})+'\n\n'
                self.done.set()
            return StreamingResponse(events())
        self.manager=install_studio(self.app,self.store,current,{'test':(ValueInput,work,True)})
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test',headers={'X-API-Key':'alice'})
        self.addAsyncCleanup(self.client.aclose)

    async def test_workspace_requires_login_and_is_private(self):
        response=await self.client.get('/studio/workspace',headers={'X-API-Key':''});self.assertEqual(response.status_code,401)
        response=await self.client.put('/studio/workspace',json={'revision':0,'document':{'sessions':[{'id':1}],'projects':[]}})
        self.assertEqual(response.status_code,200)
        other=await self.client.get('/studio/workspace',headers={'X-API-Key':'bob'});self.assertEqual(other.json()['document']['sessions'],[])
        conflict=await self.client.put('/studio/workspace',json={'revision':0,'document':{'sessions':[]}});self.assertEqual(conflict.status_code,409)

    async def test_job_continues_after_submit_and_is_idempotent(self):
        body={'action':'test','payload':{'value':'done'},'request_id':'1234567890123456'}
        response=await self.client.post('/studio/jobs',json=body);self.assertEqual(response.status_code,202)
        job_id=response.json()['id']
        other=await self.client.get('/studio/jobs/'+job_id,headers={'X-API-Key':'bob'});self.assertEqual(other.status_code,404)
        repeated=await self.client.post('/studio/jobs',json=body);self.assertEqual(repeated.json()['id'],job_id)
        await asyncio.wait_for(self.done.wait(),2)
        await asyncio.gather(*self.manager.tasks)
        finished=(await self.client.get('/studio/jobs/'+job_id)).json()
        self.assertEqual(finished['status'],'done');self.assertEqual(finished['result']['result']['value'],'done')
        self.assertEqual([event['seq'] for event in finished['events']],[1,2])
        self.assertEqual(len((await self.client.get('/studio/jobs')).json()['jobs']),1)

    async def test_pro_gate_and_unknown_actions(self):
        result=await self.client.post('/studio/jobs',headers={'X-API-Key':'free'},json={'action':'test','payload':{'value':'a'}})
        self.assertEqual(result.status_code,403)
        result=await self.client.post('/studio/jobs',json={'action':'arbitrary','payload':{}});self.assertEqual(result.status_code,400)

    async def test_upload_limits_and_safe_filenames(self):
        file=UploadFile(filename='../../tiny.mp4',file=io.BytesIO(b'12345'))
        with self.assertRaises(HTTPException) as error:
            await upload_media(self.store,{'username':'alice'},file,max_bytes=4)
        self.assertEqual(error.exception.status_code,413)
        self.assertEqual(list(self.store.owner_dir('alice').glob('upload_*')),[])
        file=UploadFile(filename='../../reference.png',file=io.BytesIO(b'not an image'))
        with self.assertRaises(HTTPException):await upload_media(self.store,{'username':'alice'},file)
        data=io.BytesIO();Image.new('RGB',(10,10)).save(data,'PNG')
        result=await self.client.post('/studio/media',files={'file':('../../reference.png',data.getvalue(),'image/png')})
        self.assertEqual(result.status_code,200)
        media_id=result.json()['id']
        result=await self.client.get('/studio/media/'+media_id,headers={'X-API-Key':'bob'});self.assertEqual(result.status_code,404)


if __name__=='__main__':unittest.main()
