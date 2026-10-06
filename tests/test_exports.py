"""Real FFmpeg/CapCut checks with synthetic media; no user projects or API calls."""
import asyncio
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from studio_store import RecordStore
from studio_tools import CapCutPackageRequest, INSTALLER, build_capcut_package
from studio_render import StudioRenderRequest, render_studio


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('ffmpeg'):
            raise unittest.SkipTest('FFmpeg is required for synthetic exports')
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        fake_response=SimpleNamespace(ok=True,status_code=200,json=lambda:[],text='')
        env={'GEMINI_API_KEY':'test-key','SUPABASE_URL':'https://example.invalid','SUPABASE_SERVICE_KEY':'test-key',
             'STUDIO_STORAGE':'local','STUDIO_DATA_DIR':str(Path(cls.tmp.name)/'store'),
             'PATH':os.environ.get('PATH','')}
        with patch.dict(os.environ,env,clear=True),patch('dotenv.load_dotenv',return_value=False),patch('requests.request',return_value=fake_response):
            cls.main=importlib.import_module('main')
        cls.source=Path(cls.tmp.name)/'synthetic.mp4'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(cls.source)],check=True,timeout=30)
        cls.music=Path(cls.tmp.name)/'music.wav'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i','sine=frequency=220:sample_rate=48000','-t','2',str(cls.music)],check=True,timeout=20)

    def test_server_paths_and_foreign_assets_are_rejected(self):
        request=self.main.ExportClipsInput(video_path=str(self.source),clips=[{'start':'00:00','end':'00:01'}])
        with self.assertRaises(HTTPException) as error:asyncio.run(self.main._validate_media_input(request,{'username':'alice'}))
        self.assertEqual(error.exception.status_code,400);self.assertTrue(self.source.exists())
        media=self.main.studio_store.save_media('alice',self.source)
        request=self.main.ExportClipsInput(asset_id=media['id'],clips=[{'start':'00:00','end':'00:01'}])
        with self.assertRaises(HTTPException):asyncio.run(self.main._validate_media_input(request,{'username':'bob'}))

    def test_urls_and_cache_globs_are_rejected(self):
        for url in ['http://youtube.com/watch?v=x','https://localhost/video','https://youtube.com:8000/x','https://evil.example/video']:
            with self.assertRaises(HTTPException):self.main._validate_source_url(url)
        with self.assertRaises(HTTPException):self.main.cache_video_path('../*',{'username':'alice'})

    def test_advanced_render_precise_cuts_crop_music_and_subtitles(self):
        store=self.main.studio_store
        music=store.save_media('alice',self.music)
        output=Path(self.tmp.name)/'advanced.mp4'
        request=StudioRenderRequest(clips=[{'start':'00:01','end':'00:02','subtitles':[{'start':0,'end':.7,'text':'Texto de prueba'}]},
            {'start':'00:03','end':'00:04'}],aspect_ratio='9:16',framing='fill',focus_x=.8,output_width=320,
            music_id=music['id'],music_volume=.12,duck_music=True,normalize_audio=True,burn_subtitles=True,
            subtitle_style={'font':'anton','color':'#ffffff','border_color':'#000000','border_width':2})
        result=render_studio(request,self.source,output,store,'alice',self.main.ts_to_seconds_f,self.main.inspect_media_file,
            self.main.burn_subtitles,self.main.SubtitleStyle)
        info=self.main.inspect_media_file(str(output))
        self.assertTrue(info['has_audio']);self.assertTrue(info['has_video'])
        self.assertAlmostEqual(info['duration_seconds'],2,delta=.12)
        self.assertEqual(info['width'],result['width']);self.assertEqual(info['height'],result['height'])

    def test_portable_capcut_zip_and_isolated_installer(self):
        cli=self.main.capcut_export._find_capcut_cli()
        if not cli:self.skipTest('capcut-cli is not installed')
        output=Path(self.tmp.name)/'capcut.zip'
        request=CapCutPackageRequest(project_name='Prueba sintética',clips=[{'start':'00:00','end':'00:02',
            'subtitles':[{'start':0,'end':1,'text':'Texto editable'}]}])
        build_capcut_package(request,self.source,output,cli,self.main.cut_single_clip,self.main.ts_to_seconds_f,self.main.inspect_media_file)
        extracted=Path(self.tmp.name)/'package'
        with zipfile.ZipFile(output) as archive:
            names=archive.namelist();self.assertIn('importar_capcut.py',names);self.assertIn('subtitulos.srt',names)
            self.assertTrue(any(name.startswith('draft/media/') for name in names))
            for name in names:
                if name.endswith('.json'):self.assertNotIn(str(self.source),archive.read(name).decode())
            archive.extractall(extracted)
        fake_home=Path(self.tmp.name)/'fake-home'
        draft_store=fake_home/'Movies/CapCut/User Data/Projects/com.lveditor.draft'
        draft_store.mkdir(parents=True)
        with patch('pathlib.Path.home',return_value=fake_home),patch.object(sys,'platform','darwin'):
            exec(compile(INSTALLER,str(extracted/'importar_capcut.py'),'exec'),{'__file__':str(extracted/'importar_capcut.py')})
        drafts=list(draft_store.iterdir());self.assertEqual(len(drafts),1)
        material_paths=[]
        for path in drafts[0].rglob('*.json'):
            raw=path.read_text();self.assertNotIn('__AVSUITE_ROOT__',raw)
            if path.name in {'draft_content.json','draft_info.json'}:
                data=json.loads(raw)
                material_paths.extend(video.get('path') for video in data.get('materials',{}).get('videos',[]))
        self.assertTrue(material_paths)
        self.assertTrue(all(Path(path).is_file() for path in material_paths))

    def test_animated_crop_uses_bounded_ai_centers(self):
        calls=[]
        def generate(**kwargs):
            calls.append(kwargs['model'])
            if kwargs['model']=='test-model':
                error=Exception('429 quota PerDay');error.code=429;raise error
            return SimpleNamespace(text=json.dumps({'centers':[{'index':0,'x':.2,'y':.4},{'index':1,'x':.8,'y':.5}]}))
        fake=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        output=Path(self.tmp.name)/'tracking.mp4'
        request=StudioRenderRequest(clips=[{'start':'00:00','end':'00:02'}],aspect_ratio='9:16',framing='fill',track_speaker=True,output_width=320)
        render_studio(request,self.source,output,self.main.studio_store,'alice',self.main.ts_to_seconds_f,
            self.main.inspect_media_file,self.main.burn_subtitles,self.main.SubtitleStyle,fake,'test-model')
        info=self.main.inspect_media_file(str(output))
        self.assertTrue(info['has_video']);self.assertAlmostEqual(info['duration_seconds'],2,delta=.12)
        self.assertEqual(calls[0],'test-model');self.assertNotEqual(calls[1],'test-model')


if __name__=='__main__':unittest.main()
