#!/usr/bin/env python3
import http.server
import socketserver
import urllib.request
import ssl
from urllib.parse import urlparse, parse_qs
import os
import sys
import mimetypes

PORT = 8000

class CombinedHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Parse the request
        parsed_path = urlparse(self.path)
        
        # Handle API endpoints
        if parsed_path.path == '/api/geocode':
            try:
                query_params = parse_qs(parsed_path.query)
                q = query_params.get('q', [''])[0]
                limit = query_params.get('limit', ['1'])[0]
                
                if not q:
                    self.send_json_error(400, "Missing 'q' parameter")
                    return
                
                # Make request to Nominatim
                nominatim_url = f'https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(q)}&limit={limit}&addressdetails=1'
                
                print(f"[API] Geocoding: {q}", file=sys.stderr, flush=True)
                
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                req = urllib.request.Request(nominatim_url)
                req.add_header('User-Agent', 'RoofEstimator/1.0')
                
                with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                    data = response.read()
                    
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Content-Length', len(data))
                self.end_headers()
                self.wfile.write(data)
                print(f"[API] ✓ Sent {len(data)} bytes", file=sys.stderr, flush=True)
                
            except urllib.error.URLError as e:
                print(f"[API] ✗ URL Error: {e}", file=sys.stderr, flush=True)
                self.send_json_error(503, f"Nominatim unavailable: {str(e)}")
            except Exception as e:
                print(f"[API] ✗ Error: {e}", file=sys.stderr, flush=True)
                self.send_json_error(500, str(e))
        
        elif parsed_path.path == '/api/image':
            try:
                query_params = parse_qs(parsed_path.query)
                url = query_params.get('url', [''])[0]
                
                if not url:
                    self.send_json_error(400, "Missing 'url' parameter")
                    return
                
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(url, context=ctx, timeout=10) as response:
                    data = response.read()
                    content_type = response.headers.get('Content-Type', 'image/png')
                    
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', len(data))
                self.end_headers()
                self.wfile.write(data)
                
            except Exception as e:
                print(f"[API] ✗ Image Error: {e}", file=sys.stderr, flush=True)
                self.send_json_error(500, str(e))
        
        else:
            # Serve static files
            super().do_GET()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS, POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def send_json_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        body = f'{{"error": "{message}"}}'.encode()
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def log_message(self, format, *args):
        print(f"[HTTP] {format % args}", file=sys.stderr, flush=True)

if __name__ == '__main__':
    os.chdir('/workspaces/htlmpdfscanmath')
    
    with socketserver.TCPServer(("0.0.0.0", PORT), CombinedHandler) as httpd:
        print(f"🌐 Server running on 0.0.0.0:{PORT}", file=sys.stderr, flush=True)
        print(f"   Website: http://localhost:{PORT}", file=sys.stderr, flush=True)
        print(f"   API: /api/geocode?q=address&limit=5", file=sys.stderr, flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n⚠️  Shutting down server...", file=sys.stderr, flush=True)
