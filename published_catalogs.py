"""Allowlisted first-party published model catalogues. No auth, inference or price assumptions."""
from html.parser import HTMLParser
from urllib.request import Request, build_opener, HTTPRedirectHandler
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

URLS={'zen':'https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/content/docs/zen.mdx',
      'groq':'https://console.groq.com/docs/models',
      'cerebras':'https://inference-docs.cerebras.ai/models/overview'}
LIMIT=4*1024*1024
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): raise ValueError('catalog redirect disabled')
class Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='table':self.table=[]
        elif tag=='tr' and self.table is not None:self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        elif tag=='tr' and self.row is not None:self.table.append(self.row);self.row=None
        elif tag=='table' and self.table is not None:self.tables.append(self.table);self.table=None

def _kind(provider,headers,cells):
    """Use declared metadata, never an ID/name heuristic or missing evidence."""
    for column in ('type','model type','task'):
        if column not in headers:continue
        index=headers.index(column)
        declared=cells[index].strip().lower() if len(cells)>index else ''
        # Speech uses the application's existing audio kind, not a new enum.
        declared={'speech':'audio','speech to text':'audio','text to speech':'audio'}.get(declared,declared)
        if declared in ('chat','structured','audio','moderation','embedding','image'):
            return declared
    if provider=='zen' and 'endpoint' in headers:
        index=headers.index('endpoint')
        endpoint=cells[index].strip().strip('`') if len(cells)>index else ''
        url=urlsplit(endpoint)
        if url.scheme=='https' and url.netloc=='opencode.ai' and not url.query and not url.fragment:
            if url.path=='/zen/v1/systemone':return 'structured'
            if url.path in ('/zen/v1/chat/completions','/zen/v1/messages','/zen/v1/responses'):
                return 'chat'
    return 'unknown'

def parse(provider,text):
    tables=[]
    if provider=='zen':
        table=[]
        for line in text.splitlines():
            if line.strip().startswith('|'):
                cells=[cell.strip().strip('`') for cell in line.strip().strip('|').split('|')]
                table.append(cells)
            elif table:tables.append(table);table=[]
        if table:tables.append(table)
    else:
        parser=Tables();parser.feed(text);tables=parser.tables
    models={}
    for table in tables:
        if not table:continue
        headers=[cell.lower() for cell in table[0]]
        if 'model id' not in headers:continue
        index=headers.index('model id')
        for cells in table[1:]:
            if len(cells)<=index:continue
            raw=cells[index].strip().strip('`')
            if provider=='groq':raw=raw.split()[-1] if raw.split() else ''
            if not re.fullmatch(r'[a-z0-9][a-z0-9._/-]{1,199}',raw):continue
            models[raw]={'id':raw,'name':raw,'developer':'unknown','kind':_kind(provider,headers,cells),'priceVerified':False,'context':None,'tools':None,'vision':False,'chinese':False}
    if not models or len(models)>500:raise ValueError('published catalog table schema changed')
    return {'models':list(models.values()),'skippedCount':0,'sourceKind':'official_docs_repository' if provider=='zen' else 'official_docs',
            'sourceUrl':URLS[provider],'catalogScope':'published','accountAccess':'unknown','pricingEvidence':'unverified',
            'observedAt':datetime.now(timezone.utc).isoformat(timespec='seconds')}

def fetch(provider):
    with build_opener(NoRedirect()).open(Request(URLS[provider],headers={'Accept':'text/html, text/plain'}),timeout=15) as response:
        raw=response.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError('published catalog too large')
    return parse(provider,raw.decode('utf8'))
