import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from agent_mcp import invoke, serve, tools_for


class Fake:
    def call(self, request): self.request=request;return {'accepted':True}


class McpTests(unittest.TestCase):
    def test_stdio_initialize_tool_list_and_strict_call(self):
        messages=[{'id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},{'method':'notifications/initialized'},
                  {'id':2,'method':'tools/list'},{'id':3,'method':'tools/call','params':{'name':'cicada_list_tasks','arguments':{}}},
                  {'id':4,'method':'tools/call','params':{'name':'cicada_list_tasks','arguments':{'owner':'invented'}}}]
        raw=io.BytesIO(('\n'.join(json.dumps(item) for item in messages)+'\n').encode());out=io.StringIO();fake=Fake()
        with patch('sys.stdin',type('Input',(),{'buffer':raw})()),patch('sys.stdout',out):serve('cicada',fake)
        replies=[json.loads(row) for row in out.getvalue().splitlines()]
        self.assertEqual(len(replies),4);self.assertEqual(replies[0]['result']['protocolVersion'],'2025-11-25')
        self.assertEqual(replies[2]['result']['structuredContent'],{'accepted':True});self.assertTrue(replies[3]['result']['isError'])
        self.assertEqual(fake.request['action'],'list')
    def test_inventory_route_and_full_report_contract(self):
        fake=Fake();invoke('agent-city',fake,'agent_city_inventory',{'kind':'skill-inventory'})
        self.assertEqual(fake.request,{'method':'GET','path':'/api/v1/skill-inventory','body':None})
        report=next(item for item in tools_for('cicada') if item['name']=='cicada_report_ai_work')['inputSchema']['properties']['report']
        self.assertEqual(set(report['properties']),set(report['required']));self.assertFalse(report['additionalProperties'])


if __name__=='__main__':unittest.main()
