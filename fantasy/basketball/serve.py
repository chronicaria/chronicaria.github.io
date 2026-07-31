#!/usr/bin/env python3
"""Dev server: python3 serve.py [port] — serves the site folder regardless of launch cwd."""
import http.server
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8901


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # ponytail: dev server, always fresh
        super().end_headers()


http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
