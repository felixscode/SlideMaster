#!/usr/bin/env python3
import http.server
import socketserver
import urllib.parse
import os
import json
import time
import sys
import logging

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('slidev_auth')

# Path to the tokens file (shared with the main app)
TOKENS_FILE = os.environ.get('SLIDEV_TOKENS_FILE', '../secrets/slidev_tokens.json')

def get_valid_tokens():
    """
    Load valid tokens from the tokens file
    Returns an empty dict if file doesn't exist or can't be read
    """
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Tokens file not found: {TOKENS_FILE}")
            return {}
    except Exception as e:
        logger.error(f"Error reading tokens file: {e}")
        return {}

class TokenAuthHandler(http.server.SimpleHTTPRequestHandler):
    """
    HTTP handler that requires a valid access token for all requests
    """
    def do_GET(self):
        # Parse URL to extract query parameters
        parsed_url = urllib.parse.urlparse(self.path)
        query = parsed_url.query
        params = urllib.parse.parse_qs(query)
        
        # Extract token from query parameters
        token = params.get('access_token', [''])[0]
        
        # Validate the token
        if not self._validate_token(token):
            self.send_response(403)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'Access Denied: Valid token required')
            logger.warning(f"Access denied for request: {self.path}")
            return
        
        # If we get here, token is valid
        # Clean the path to serve the requested file without query parameters
        self.path = parsed_url.path if parsed_url.path else '/'
        
        # Make sure we serve index.html for the root path
        # if self.path == '/':
        #     self.path = '/index.html'
            
        # Continue with normal request handling
        return super().do_GET()
    
    def _validate_token(self, token):
        """
        Check if a token is valid and not expired
        """
        # For debugging, log token details
        logger.info(f"Validating token request")
        
        if not token:
            logger.info("No token provided")
            return False
            
        # Debug token storage
        tokens = get_valid_tokens()
        logger.info(f"Found {len(tokens)} tokens in storage")
            
        # Production validation logic (currently disabled for debugging)
        if token not in tokens:
            logger.info(f"Invalid token")
            return False
            
        # Check if token is expired
        token_data = tokens[token]
        current_time = time.time()
        
        if "expires" not in token_data or token_data["expires"] < current_time:
            logger.info(f"Expired token")
            return False
            
        logger.info(f"Valid token access")
        return True
        
    def log_message(self, format, *args):
        """
        Override to use our logger instead of printing to stderr
        """
        logger.info("%s - %s" % (self.address_string(), format % args))

def run_server(port=3030, bind="0.0.0.0"):
    """
    Run the token-authenticated HTTP server
    """
    server_address = (bind, port)
    
    # Create the HTTP server with our custom handler
    httpd = socketserver.TCPServer(server_address, TokenAuthHandler)
    
    logger.info(f"Serving on {bind}:{port} with token authentication")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by keyboard interrupt")
        httpd.server_close()

if __name__ == "__main__":
    # Get port from command line argument, default to 3030
    port = 3030
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
        
    run_server(port=port)