"""Synthetic test authority arrives over stdin, never argv or production config."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_mcp import LocalAPI, serve

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    headers = json.loads(sys.stdin.buffer.readline(16385))
    api = LocalAPI(args.port)
    opener = api.opener
    class AuthorizedFixture:
        def open(self, request, **kwargs):
            for key, value in headers.items():
                request.add_header(key, value)
            return opener.open(request, **kwargs)
    api.opener = AuthorizedFixture()
    serve(api)
