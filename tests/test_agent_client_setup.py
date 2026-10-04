import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools/configure_agent_clients.py'
spec = importlib.util.spec_from_file_location('client_setup', MODULE)
setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)


class ClientSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Другой user O'Neill $model"
        self.root.mkdir()
        self.home = self.root / 'home'; self.home.mkdir()
        self.native = self.root / 'native'; self.native.mkdir()
        for name in setup.NATIVE_FILES: (self.native / name).write_bytes(b'synthetic')
        self.cicada = self.root / 'cicada'; self.cicada.mkdir()
        (self.cicada / 'calendar.db').touch()
        self.city = self.root / 'city'; self.city.mkdir()
        (self.city / 'connection.json').write_text('{}')
        self.kw = dict(tools_dir=self.root/'private-tools', native_client=self.native/'LocalPipeClient.exe',
            cicada_profile=self.cicada, city_profile=self.city/'connection.json', clients=['codex','claude'],
            hooks=True, personal_roots=[self.home], user_home=self.home, codex_home=self.home/'.codex')

    def test_plan_does_not_write_and_apply_is_idempotent(self):
        prepared = setup.plan(**self.kw)
        self.assertFalse(self.kw['tools_dir'].exists())
        self.assertGreater(setup.apply(prepared)['changedFiles'], 0)
        second = setup.apply(setup.plan(**self.kw))
        self.assertEqual(second, dict(changedFiles=0, backup=None))
        profile = tomllib.loads((self.home/'.codex/config.toml').read_text(encoding='utf-8'))
        self.assertEqual(profile['mcp_servers']['cicada-local']['command'], sys.executable)
        self.assertIn(str(self.kw['tools_dir']/'agent_mcp.py'), profile['mcp_servers']['agent-city-local']['args'])
        for path in (self.home/'.codex/hooks.json', self.home/'.claude/settings.json'):
            value = json.loads(path.read_text(encoding='utf-8'))
            self.assertTrue(all(len(groups)==1 for groups in value['hooks'].values()))

    def test_foreign_mcp_hooks_and_settings_survive(self):
        codex = self.home/'.codex'; codex.mkdir()
        (codex/'config.toml').write_text('model = "owner-model"\n[mcp_servers.foreign]\ncommand = "foreign"\n')
        foreign_hook = {'hooks':[{'type':'command','command':'owner-hook'}]}
        (codex/'hooks.json').write_text(json.dumps({'ownerSetting':True,'hooks':{'Stop':[foreign_hook]}}))
        (self.home/'.claude.json').write_text(json.dumps({'ownerSetting':17,'mcpServers':{'foreign':{'command':'owner'}}}))
        result = setup.apply(setup.plan(**self.kw))
        self.assertTrue(Path(result['backup'],'manifest.json').exists())
        parsed = tomllib.loads((codex/'config.toml').read_text(encoding='utf-8'))
        self.assertEqual(parsed['model'], 'owner-model')
        self.assertEqual(parsed['mcp_servers']['foreign']['command'], 'foreign')
        self.assertEqual(json.loads((codex/'hooks.json').read_text(encoding='utf-8'))['hooks']['Stop'][0], foreign_hook)
        self.assertEqual(json.loads((self.home/'.claude.json').read_text(encoding='utf-8'))['ownerSetting'], 17)

    def test_conflicting_server_stops_before_any_write(self):
        codex=self.home/'.codex'; codex.mkdir()
        target=codex/'config.toml'; text='[mcp_servers.cicada-local]\ncommand="existing-owner"\n'; target.write_text(text)
        with self.assertRaisesRegex(ValueError,'different configuration'): setup.plan(**self.kw)
        self.assertEqual(target.read_text(),text)
        self.assertFalse(self.kw['tools_dir'].exists())

    def test_concurrent_config_edit_is_not_overwritten(self):
        prepared=setup.plan(**self.kw)
        target=self.home/'.claude.json';target.write_text('{"ownerConcurrentEdit":true}')
        with self.assertRaisesRegex(ValueError,'changed after the plan'):setup.apply(prepared)
        self.assertTrue(json.loads(target.read_text())['ownerConcurrentEdit'])
        self.assertFalse(self.kw['tools_dir'].exists())

    def test_explicit_roots_and_complete_client_are_required(self):
        with self.assertRaisesRegex(ValueError,'personal directories'):setup.plan(**dict(self.kw,personal_roots=[]))
        (self.native/'LocalPipeClient.dll').unlink()
        with self.assertRaisesRegex(ValueError,'complete LocalPipeClient'):setup.plan(**self.kw)

    def test_repository_and_app_data_are_not_transport_destinations(self):
        for directory in (setup.REPOSITORY/'private-transport',self.cicada/'transport',self.city/'transport'):
            with self.assertRaises(ValueError):setup.plan(**dict(self.kw,tools_dir=directory))

    @unittest.skipUnless(os.name=='nt','Windows shell contract')
    def test_hook_command_with_unicode_spaces_quotes_and_dollar_is_executable(self):
        setup.apply(setup.plan(**self.kw))
        settings=json.loads((self.home/'.codex/hooks.json').read_text(encoding='utf-8'))
        command=settings['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
        program=base64.b64decode(command.split()[-1]).decode('utf-16-le')
        self.assertIn("O''Neill $model",program)
        event=json.dumps(dict(session_id='synthetic-session',hook_event_name='UserPromptSubmit',cwd='C:/Windows',prompt='NEVER_STORE_PROMPT'))
        for binary,args in [('powershell.exe',['-NoProfile','-NonInteractive','-Command',command]),('cmd.exe',['/d','/s','/c',command])]:
            response=subprocess.run([binary,*args],input=event.encode(),capture_output=True,timeout=15)
            self.assertEqual(response.returncode,0,response.stderr)
            self.assertEqual(response.stdout,b'')
        self.assertFalse((self.kw['tools_dir']/'outbox.db').exists())


if __name__=='__main__':unittest.main()
