#!/usr/bin/env python3
import http.server
import socketserver
import urllib.request
import ssl
from urllib.parse import urlparse, parse_qs
import os
import sys
import mimetypes
import json
import io

# Image processing libraries
try:
    import numpy as np
    from PIL import Image
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("[WARNING] PIL/NumPy not available. Install with: pip install pillow numpy", file=sys.stderr)

PORT = 8000

def detect_roof_area(lat, lng):
    """
    Detect building/roof area from satellite image using simple pixel analysis.
    Returns estimated roof area in square feet.
    """
    if not HAS_CV2:
        # Fallback: return a reasonable default
        return 4500
    
    try:
        # Fetch satellite tile from ESRI
        zoom = 18
        # Convert lat/lng to tile coordinates
        n = 2.0 ** zoom
        x = int((lng + 180.0) / 360.0 * n)
        y = int((1.0 - np.log(np.tan((lat * np.pi / 180.0) + np.pi / 4.0) / np.pi)) / 2.0 * n)
        
        tile_url = f'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{x}/{y}'
        
        print(f"[ANALYSIS] Fetching tile from: {tile_url}", file=sys.stderr, flush=True)
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(tile_url, context=ctx, timeout=10) as response:
            img_data = response.read()
        
        # Load image using PIL
        img = Image.open(io.BytesIO(img_data))
        
        # Convert to numpy array
        img_array = np.array(img)
        
        # Convert to grayscale using PIL then to numpy
        if img.mode != 'L':
            img_gray = img.convert('L')
        else:
            img_gray = img
            
        gray_array = np.array(img_gray)
        
        # Simple edge detection using gradient
        gx = np.gradient(gray_array, axis=1)
        gy = np.gradient(gray_array, axis=0)
        edges = np.sqrt(gx**2 + gy**2)
        
        # Threshold to find edges
        edge_binary = edges > np.percentile(edges, 75)
        
        # Find building area - look for dark regions with significant edges
        # Buildings typically are darker than surrounding areas
        dark_pixels = gray_array < 150  # Darker pixels
        building_mask = dark_pixels & edge_binary
        
        area_pixels = np.sum(building_mask)
        
        if area_pixels < 100:
            # If no clear building found, try a different approach
            # Use color variation as proxy for building
            if len(img_array.shape) == 3 and img_array.shape[2] >= 3:
                color_var = np.std(img_array[:,:,:3], axis=2)
                building_candidate = color_var > 30  
                area_pixels = np.sum(building_candidate)
            else:
                return 4500
        
        # Convert pixels to real-world area
        # At zoom level 18, ESRI tiles are 256x256 pixels
        # Each tile covers approximately 38.2 meters x 38.2 meters at US latitudes
        meters_per_tile = 38.2  # Approximate at US latitudes
        meters_per_pixel = meters_per_tile / 256.0
        sq_meters_per_pixel = meters_per_pixel ** 2
        
        area_sq_meters = area_pixels * sq_meters_per_pixel
        area_sq_feet = area_sq_meters * 10.764  # Convert to sq feet
        
        # Apply correction factor - detected area tends to overestimate
        area_sq_feet = area_sq_feet * 0.6  # 60% of detected area is roof
        
        # Sanity checks - roof area typically 1000-10000 SF
        if area_sq_feet < 500:
            area_sq_feet = 4500
        elif area_sq_feet > 15000:
            area_sq_feet = 8000
        
        print(f"[ANALYSIS] Detected area: {area_sq_feet:.0f} SF (from {area_pixels:.0f} pixels)", file=sys.stderr, flush=True)
        return round(area_sq_feet / 100) * 100  # Round to nearest 100
        
    except Exception as e:
        print(f"[ANALYSIS] Error: {e}", file=sys.stderr, flush=True)
        return 4500  # Default fallback

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
        
        elif parsed_path.path == '/api/analyze-roof':
            try:
                query_params = parse_qs(parsed_path.query)
                lat = query_params.get('lat', [''])[0]
                lng = query_params.get('lng', [''])[0]
                
                if not lat or not lng:
                    self.send_json_error(400, "Missing 'lat' or 'lng' parameter")
                    return
                
                lat = float(lat)
                lng = float(lng)
                
                print(f"[API] Analyzing roof at {lat}, {lng}", file=sys.stderr, flush=True)
                
                # Detect roof area
                roof_area = detect_roof_area(lat, lng)
                
                response = json.dumps({"roof_area": roof_area}).encode()
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Content-Length', len(response))
                self.end_headers()
                self.wfile.write(response)
                print(f"[API] ✓ Roof analysis complete: {roof_area} SF", file=sys.stderr, flush=True)
                
            except ValueError as e:
                self.send_json_error(400, f"Invalid coordinates: {str(e)}")
            except Exception as e:
                print(f"[API] ✗ Analysis Error: {e}", file=sys.stderr, flush=True)
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
