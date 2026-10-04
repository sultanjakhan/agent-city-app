import json
from pathlib import Path
import unittest
import published_catalogs as published

class TypedFallbackTests(unittest.TestCase):
    def test_declared_types_preserve_every_id(self):
        text='<table><tr><th>Model ID</th><th>Type</th></tr>'+''.join(
            f'<tr><td>{ident}</td><td>{kind}</td></tr>' for ident,kind in
            [('model-chat','chat'),('model-speech','speech'),('model-moderation','moderation'),('model-unknown','')])+'</table>'
        result=published.parse('groq',text)
        self.assertEqual({m['id']:m['kind'] for m in result['models']},
                         {'model-chat':'chat','model-speech':'audio','model-moderation':'moderation','model-unknown':'unknown'})
        self.assertEqual(result['skippedCount'],0)
        self.assertTrue(all(m['priceVerified'] is False for m in result['models']))
        self.assertEqual(result['accountAccess'],'unknown')

    def test_names_never_prove_kind(self):
        text='<table><tr><th>Model ID</th></tr>'+''.join(
            f'<tr><td>{ident}</td></tr>' for ident in ['whisper-large-v3','prompt-guard','chat-model'])+'</table>'
        self.assertEqual([m['kind'] for m in published.parse('groq',text)['models']],['unknown']*3)

    def test_zen_exact_documented_endpoints(self):
        rows=[('decision','https://opencode.ai/zen/v1/systemone','structured'),
              ('completion','https://opencode.ai/zen/v1/chat/completions','chat'),
              ('responses','https://opencode.ai/zen/v1/responses','chat'),
              ('messages','https://opencode.ai/zen/v1/messages','chat'),
              ('unproven','https://opencode.ai/zen/v1/models/something','unknown'),
              ('foreign','https://example.com/zen/v1/messages','unknown')]
        text='| Model ID | Endpoint |\n| --- | --- |\n'+'\n'.join(f'| {ident} | `{endpoint}` |' for ident,endpoint,_ in rows)
        self.assertEqual({m['id']:m['kind'] for m in published.parse('zen',text)['models']},
                         {ident:kind for ident,_,kind in rows})

    def test_seed_preserves_counts_and_unknown_evidence(self):
        root=Path(__file__).parent
        seed_path=root/'published_catalog_seed.json'
        if not seed_path.exists():seed_path=root.parent/'published_catalog_seed.json'
        seed=json.loads(seed_path.read_text(encoding='utf8'))
        self.assertEqual({k:len(v['models']) for k,v in seed.items()},{'zen':82,'groq':13,'cerebras':2})
        self.assertTrue(all(m['kind']=='unknown' for v in seed.values() for m in v['models']))

if __name__=='__main__':unittest.main()
