#!/usr/bin/env python3
import http.server
import socketserver
import urllib.request
import json
import ssl
from urllib.parse import urlparse, parse_qs

PORT = 8001

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Parse the request
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/geocode':
            try:
                query_params = parse_qs(parsed_path.query)
                q = query_params.get('q', [''])[0]
                limit = query_params.get('limit', ['1'])[0]
                
                if not q:
                    self.send_error(400, "Missing 'q' parameter")
                    return
                
                # Make request to Nominatim
                nominatim_url = f'https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(q)}&limit={limit}&addressdetails=1'
                
                # Disable SSL verification for self-signed certs (if needed)
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(nominatim_url, context=ctx) as response:
                    data = response.read().decode('utf-8')
                    
                # Send response with CORS headers
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                self.wfile.write(data.encode('utf-8'))
                
            except Exception as e:
                self.send_error(500, str(e))
        
        elif parsed_path.path == '/api/image':
            try:
                query_params = parse_qs(parsed_path.query)
                url = query_params.get('url', [''])[0]
                
                if not url:
                    self.send_error(400, "Missing 'url' parameter")
                    return
                
                # Make request to image URL
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(url, context=ctx) as response:
                    data = response.read()
                    content_type = response.headers.get('Content-Type', 'image/png')
                    
                # Send response
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
                
            except Exception as e:
                self.send_error(500, str(e))
        
        else:
            self.send_error(404, "Endpoint not found")
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def log_message(self, format, *args):
        # Reduced logging
        print(f"[PROXY] {format % args}")

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), ProxyHandler) as httpd:
        print(f"🌐 Proxy server running on http://localhost:{PORT}")
        print(f"   Geocode endpoint: http://localhost:{PORT}/api/geocode?q=address")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down proxy server...")
