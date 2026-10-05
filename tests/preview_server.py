"""Isolated browser fixture. Synthetic data, fake users/providers; no real API calls."""
import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

scratch = tempfile.TemporaryDirectory(prefix="avsuite_browser_")
env = {"GEMINI_API_KEY":"test-key","SUPABASE_URL":"https://example.invalid","SUPABASE_SERVICE_KEY":"test-key",
       "STUDIO_STORAGE":"local","STUDIO_DATA_DIR":scratch.name,"PATH":os.environ.get("PATH","")}
with patch.dict(os.environ,env,clear=True),patch("dotenv.load_dotenv",return_value=False):
    import main

users = {}
for username in ["alice","bob","free"]:
    digest,salt = main._hash_password("test-password")
    users[username] = {"role":"USER","plan":"FREE" if username=="free" else "PRO","active":True,"password_hash":digest,"salt":salt,
                       "daily_usage_seconds":0,"daily_usage_date":main._today_str()}
main._load_users=lambda:users
main._get_user_row=lambda username:users.get(username)
main._supabase_upsert=lambda *args,**kwargs:None
main._record_usage=lambda *args,**kwargs:None
exports={}
original_register=main._register_export
def register(filename,username):
    original_register(filename,username)
    exports[filename]={"username":username,"created_at":"2026-10-05"}
main._register_export=register
main._get_export_owner=lambda filename:exports.get(filename,{}).get("username")
main._load_exports_index=lambda:exports
image_data=io.BytesIO();Image.new('RGB',(480,270),'#ddad55').save(image_data,'PNG')
main.client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs:SimpleNamespace(parts=[
    SimpleNamespace(inline_data=SimpleNamespace(mime_type='image/png',data=image_data.getvalue()))])))
def text_response(prompt,*args,**kwargs):
    if 'clip_index' in str(prompt):
        data=json.loads(prompt.split('\n',1)[1])
        return json.dumps({'title':'Campaña de prueba','summary':'Material sintético','clips':[
            {'clip_index':i,'title':f'Título {i+1}','caption':'Copy de prueba','image_prompt':'Una miniatura dorada','hashtags':['#prueba']}
            for i,_ in enumerate(data['clips'])]})
    return 'Respuesta de prueba'
main._call_gemini_text=text_response
raw="TIMESTAMP: 00:00\nSPEAKER: O'Brien\nDIALOGUE: Una conversación de prueba.\n---\nTIMESTAMP: 00:04\nSPEAKER: Speaker 2\nDIALOGUE: Otra parte del material."
workspace={'sessions':[{'id':100,'timestamp':'5/10/2026','data':{'title':'Prueba del estudio','raw_timeline':raw,'source_url':'',
    'editor':{'clips':[{'id':'clip1','start':'00:00','end':'00:03','label':'Primer clip','selected':True}],
              'platform':None,'chat':[],'controls':{}}}}], 'projects':[{'id':'proj_1','name':'Proyecto de prueba'}],'brand':{}}
main.studio_store.put('alice','workspace','main',workspace,0)
app=main.app

@app.post('/__test/reset')
def reset_fixture():
    with main.studio_store.connection() as db:
        db.execute('DELETE FROM records')
    main.studio_store.put('alice','workspace','main',workspace)
    main._rate_limit_buckets.clear()
    return {'ok':True}
