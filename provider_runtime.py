"""Read a sanitized local observation. Never run clients, login or inspect credentials."""
import json
from datetime import datetime

def read(directory):
    path=directory/'provider-runtime-status.json'
    if not path.exists() or path.is_symlink() or path.stat().st_size>65536:return {}
    try:
        raw=json.loads(path.read_text(encoding='utf8'));result={}
        for ident,expected in {'openai':('codex','codex-login-status'),'zen':('opencode','panel-status-and-official-docs')}.items():
            row=raw.get(ident,{})
            if row.get('client')!=expected[0] or row.get('source')!=expected[1]:continue
            if row.get('status') not in ('authenticated','unverified') or row.get('auth') not in ('chatgpt','api-key','unknown'):continue
            stamp=row.get('checkedAt');parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if parsed.tzinfo is None:continue
            clean={key:row[key] for key in ('client','source','status','auth','checkedAt')}
            clean.update(entitlement='not_checked',inference='not_checked')
            for key in ('keyAvailable','clientInPath'):
                if isinstance(row.get(key),bool):clean[key]=row[key]
            result[ident]=clean
        return result
    except (ValueError,TypeError,AttributeError,KeyError,OSError):return {}
