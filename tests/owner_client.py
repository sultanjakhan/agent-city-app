"""Synthetic owner obtains a session through the real one-use HTTP bootstrap."""
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, build_opener, ProxyHandler

cookies = {}

def authorize(server):
    base = 'http://127.0.0.1:'+str(server.server_port)
    capability = server.owner_sessions.issue_bootstrap()
    req = Request(base+'/api/owner-bootstrap', data=json.dumps({'capability':capability}).encode(), headers={'X-Agent-City':'1','Origin':'http://'+server.owner_host+':'+str(server.server_port),'Host':server.owner_host+':'+str(server.server_port),'Content-Type':'application/json'})
    with build_opener(ProxyHandler({})).open(req, timeout=3) as response:
        assert response.status == 200
        cookies[base] = (response.headers['Set-Cookie'].split(';',1)[0],server.owner_host+':'+str(server.server_port))
    return cookies[base][0]

def headers(url, original=None):
    result = dict(original or {})
    base = urlsplit(url).scheme+'://'+urlsplit(url).netloc
    if base in cookies:
        cookie,host=cookies[base];result['Cookie']=cookie
        if result.get('Host', urlsplit(url).netloc) in {urlsplit(url).netloc,host}: result['Host']=host
        if result.get('Origin') == base: result['Origin']='http://'+host
    return result

def owner_urlopen(request, **kwargs):
    if isinstance(request,str): request=Request(request)
    for key,value in headers(request.full_url,dict(request.header_items())).items(): request.add_header(key,value)
    return urlopen(request, **kwargs)
