"""MCP stdio and authenticated HTTP transports for any AI client."""
from __future__ import annotations
import argparse
import hmac
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path[:0] = [str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
from src.ai_gateway import Gateway, TOOLS

MAX_REQUEST = 1024 * 1024
PROTOCOLS = ('2024-11-05','2025-03-26','2025-06-18')

def rpc(gateway, request):
    if not isinstance(request,dict) or request.get('jsonrpc') != '2.0':
        return {'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'invalid request'}}
    method, request_id = request.get('method'), request.get('id')
    if 'id' not in request:
        return None
    response = {'jsonrpc':'2.0','id':request_id}
    params = request.get('params',{})
    if not isinstance(params,dict):
        return {**response,'error':{'code':-32602,'message':'params must be an object'}}
    if method == 'initialize':
        version = params.get('protocolVersion')
        return {**response,'result':{'protocolVersion':version if version in PROTOCOLS else PROTOCOLS[-1],
            'capabilities':{'tools':{}},'serverInfo':{'name':'solidworks-ai','version':'1.0.0'}}}
    if method == 'ping':
        return {**response,'result':{}}
    if method == 'tools/list':
        return {**response,'result':{'tools':TOOLS}}
    if method == 'tools/call':
        try:
            result = gateway.call(params.get('name'),params.get('arguments',{}))
            return {**response,'result':{'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}],
                'isError':result.get('status') in {'failed','timed_out'}}}
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return {**response,'result':{'content':[{'type':'text','text':str(exc)}],'isError':True}}
    return {**response,'error':{'code':-32601,'message':'method not found'}}

def stdio(gateway, source=None, sink=None):
    source, sink = source or sys.stdin.buffer, sink or sys.stdout
    while True:
        line = source.readline(MAX_REQUEST+1)
        if not line:
            return
        if len(line) > MAX_REQUEST:
            raise ValueError('MCP request exceeds size limit')
        try:
            response = rpc(gateway,json.loads(line))
        except (ValueError,UnicodeError):
            response = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'invalid JSON'}}
        if response is not None:
            sink.write(json.dumps(response,ensure_ascii=False)+'\n')
            sink.flush()

def handler(gateway, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)
        def log_message(self,*args):
            pass  # Never log Authorization or CAD request bodies.
        def reply(self,status,value):
            body = json.dumps(value,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def authorized(self):
            return hmac.compare_digest(self.headers.get('Authorization','').encode('utf-8'), ('Bearer '+token).encode('utf-8'))
        def do_GET(self):
            if not self.authorized():
                return self.reply(401,{'error':'bearer token required'})
            if self.path == '/v1/tools':
                return self.reply(200,{'tools':TOOLS})
            return self.reply(404,{'error':'unknown route'})
        def do_POST(self):
            if not self.authorized():
                return self.reply(401,{'error':'bearer token required'})
            if self.path != '/v1/tools/call':
                return self.reply(404,{'error':'unknown route'})
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= MAX_REQUEST:
                    return self.reply(413,{'error':'request must be 1..1048576 bytes'})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload,dict) or set(payload) - {'name','arguments'}:
                    raise ValueError('expected name and arguments object')
                result = gateway.call(payload.get('name'),payload.get('arguments',{}))
                return self.reply(200,result)
            except (ValueError,KeyError,TypeError,OSError) as exc:
                return self.reply(400,{'error':str(exc)})
    return Handler

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',choices=['stdio','http'],default='stdio')
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--sw-exe',help='Host-controlled native opt-in; never supplied by a tool caller')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    gateway = Gateway(args.workspace,sw_exe=args.sw_exe)
    if args.transport == 'stdio':
        return stdio(gateway)
    token = os.environ.get('SOLIDWORKS_AI_TOKEN','')
    if len(token) < 32 or not token.isascii():
        parser.error('HTTP requires SOLIDWORKS_AI_TOKEN with at least 32 ASCII characters')
    if args.host not in {'127.0.0.1','localhost','::1'}:
        parser.error('HTTP binds to loopback only; use an authenticated TLS reverse proxy for remote clients')
    server = ThreadingHTTPServer((args.host,args.port),handler(gateway,token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
