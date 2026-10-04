"""Configurable stateless MCP command access; synchronization belongs to TaskSync.

One independently configured instance per application/endpoint. Configuration
contains environment-variable secret references, never bearer credentials.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_connection import TaskConnection,TaskError,COMMAND_SCOPE,strict,encode

def definitions(config):
    return [{'name':'shared_task_command','description':'Read or change the configured application using exact native task IDs and revisions. Reuse the original operationId and payload after an unknown outcome. Queued requests are not executions; MCP does not synchronize data.',
             'inputSchema':{'type':'object','properties':{'operationId':{'type':'string','pattern':'^[A-Za-z0-9_-]{8,100}$'},'command':{'type':'string','enum':[c for c,s in COMMAND_SCOPE.items() if s in config['scopes']]},'arguments':{'type':'object'}},'required':['operationId','command','arguments'],'additionalProperties':False}}]
def serve(connection,source=sys.stdin.buffer,sink=sys.stdout.buffer):
    while True:
        raw=source.readline(16001)
        if not raw:return
        ident=None
        try:
            if len(raw)>16000:raise TaskError('mcp_frame_limit')
            request=strict(raw);ident=request.get('id');method=request['method'];params=request.get('params',{})
            if method.startswith('notifications/'):continue
            if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2025-03-26'),'capabilities':{'tools':{}},'serverInfo':{'name':'shared-task-command-access','version':'1.0.0'}}
            elif method=='ping':result={}
            elif method=='tools/list':result={'tools':definitions(connection.config)}
            elif method=='tools/call':
                try:
                    args=params['arguments']
                    if params['name']!='shared_task_command' or type(args)!=dict or set(args)!={'operationId','command','arguments'}:raise TaskError('unsupported_mcp_command')
                    value=connection.call(args['operationId'],args['command'],args['arguments'])
                    result={'content':[{'type':'text','text':encode(value).decode()}],'structuredContent':value,'isError':False}
                except TaskError as error:
                    value={'code':error.code,'status':error.status,'current':error.current}
                    result={'content':[{'type':'text','text':error.code}],'structuredContent':value,'isError':True}
                except Exception:result={'content':[{'type':'text','text':'application_unavailable_or_outcome_unknown'}],'isError':True}
            else:raise TaskError('unsupported_mcp_method')
            response={'jsonrpc':'2.0','id':ident,'result':result}
        except Exception:response={'jsonrpc':'2.0','id':ident,'error':{'code':-32600,'message':'Invalid request'}}
        sink.write(encode(response)+b'\n');sink.flush()
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--connection',type=Path,required=True);args=parser.parse_args()
    serve(TaskConnection(strict(args.connection.read_bytes())))
if __name__=='__main__':main()
