from owner_client import authorize
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import threading
import http.client
import provider_store
import server
import availability
import provider_runtime

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.registry=provider_store.ProviderStore(self.temp.name,server.PROVIDERS)
    def tearDown(self):self.temp.cleanup()
    def change(self,ident,mode='api',policy='all'):
        return self.registry.change('settings',{'id':ident,'settings':{'accessMode':mode,'catalogPolicy':policy}},self.registry.snapshot()['revision'])
    def test_defaults_persist_restore_and_invalid_settings_are_atomic(self):
        self.assertFalse(self.registry.path.exists())
        self.assertEqual('confirmed-free-only',self.registry.sources()['groq']['catalogPolicy'])
        self.change('groq','subscription')
        reopened=provider_store.ProviderStore(self.temp.name,server.PROVIDERS)
        self.assertEqual('subscription',reopened.sources()['groq']['accessMode'])
        self.assertEqual('all',reopened.sources()['groq']['catalogPolicy'])
        self.assertEqual('confirmed-free-only',reopened.sources()['zen']['catalogPolicy'])
        before=self.registry.path.read_bytes()
        with self.assertRaises(provider_store.ProviderError):self.change('groq','logged-in')
        self.assertEqual(before,self.registry.path.read_bytes())
        self.registry.change('remove',{'id':'groq'},self.registry.snapshot()['revision'])
        self.registry.change('add',{'website':'https://groq.com'},self.registry.snapshot()['revision'])
        self.assertEqual('subscription',self.registry.sources()['groq']['accessMode'])
    def test_revision_conflicts_preserve_existing_settings(self):
        previous=self.registry.snapshot()['revision'];self.change('groq')
        with self.assertRaises(provider_store.ProviderConflict):self.registry.change('settings',{'id':'zen','settings':{'accessMode':'api','catalogPolicy':'all'}},previous)
        self.assertEqual('confirmed-free-only',self.registry.sources()['zen']['catalogPolicy'])
    def test_full_metadata_separate_from_free_routes(self):
        result=server.normalize_catalog('openrouter',{'data':[{'id':'test/free:free','pricing':{'prompt':'0','completion':'0'},'architecture':{'input_modalities':['text'],'output_modalities':['text']}},{'id':'test/paid','pricing':{'prompt':'1','completion':'2'}},{'id':'test/unknown'}]})
        self.assertEqual(['test/free:free'],[m['id'] for m in result['models']])
        self.assertEqual(['confirmed-free','paid','unknown'],[m['priceStatus'] for m in result['allModels']])
        snapshot={'sources':[{'id':'openrouter','accessMode':'subscription'}],'credentials':{'openrouter':True},'catalogs':{'openrouter':result}}
        self.assertEqual([],availability.summarize(snapshot)['pendingRoutes'])
    def test_full_catalog_retains_non_chat_and_unknown_types(self):
        result=server.normalize_catalog('openrouter',{'data':[{'id':'vendor/speech','architecture':{'modality':'text->audio'}},{'id':'vendor/guard','type':'moderation'},{'id':'vendor/system'},{'id':'vendor/embedding','type':'embedding'}]})
        self.assertEqual(['audio','moderation','unknown','embedding'],[m['kind'] for m in result['allModels']])
        self.assertEqual(4,len(result['allModels']))
        self.assertTrue(all(m['priceVerified'] is False for m in result['allModels']))
    def test_http_settings_requires_csrf_and_never_refreshes_or_reads_key(self):
        (Path(self.temp.name)/'skills').mkdir()
        store=server.Store(self.temp.name,skills_root=Path(self.temp.name)/'skills',repo_roots=[self.temp.name],codex_home=Path(self.temp.name)/'codex')
        service=server.Server(('127.0.0.1',0),store);thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
        owner_cookie=authorize(service)
        try:
            body=json.dumps({'id':'groq','settings':{'accessMode':'subscription','catalogPolicy':'all'},'revision':store.providers.snapshot()['revision']})
            connection=http.client.HTTPConnection(*service.server_address)
            headers={'Cookie':owner_cookie,'Content-Type':'application/json','X-Agent-City':'1','Host':service.owner_host+':'+str(service.server_port),'Origin':'http://'+service.owner_host+':'+str(service.server_port)}
            connection.request('POST','/api/providers/settings',body,headers);response=connection.getresponse();response.read();self.assertEqual(403,response.status)
            headers['X-Agent-City-Token']=store.csrf_token
            with patch.object(store,'refresh',side_effect=AssertionError('no refresh')),patch.object(server.access,'key_available',return_value=False),patch.object(server.credentials,'info',return_value={'available':False}),patch.object(server.credentials,'read_key',side_effect=AssertionError('no key read')):
                connection.request('POST','/api/providers/settings',body,headers);response=connection.getresponse();data=json.loads(response.read());self.assertEqual(200,response.status)
                source=next(s for s in data['sources'] if s['id']=='groq');self.assertEqual('subscription',source['accessMode'])
            connection.close()
        finally:service.shutdown();service.server_close();thread.join()


class RuntimeTests(unittest.TestCase):
    def test_local_observation_excludes_private_fields_and_does_not_imply_entitlement(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'provider-runtime-status.json'
            path.write_text(json.dumps({'openai':{'client':'codex','source':'codex-login-status','status':'authenticated','auth':'chatgpt','checkedAt':'2026-10-01T16:00:00+00:00','email':'private@example.invalid','token':'private','entitlement':'all'}}))
            result=provider_runtime.read(Path(directory))
            self.assertEqual('not_checked',result['openai']['entitlement'])
            self.assertNotIn('email',result['openai']);self.assertNotIn('token',result['openai'])
            path.write_text('{bad json');self.assertEqual({},provider_runtime.read(Path(directory)))
