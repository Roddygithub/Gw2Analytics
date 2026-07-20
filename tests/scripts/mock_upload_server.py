"""Minimal mock API server for scripts/upload-batch.sh tests.

Consumes the multipart body and always responds with {"status":"completed"}.
"""

import http.server
import sys
import time


class MockAPI(http.server.BaseHTTPRequestHandler):
    request_count = 0

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)
        time.sleep(0.01)
        MockAPI.request_count += 1

        # When started with a second positional argument "retry", the
        # first two requests return rate_limited to exercise the
        # upload script's retry/backoff path.
        if len(sys.argv) > 2 and sys.argv[2] == "retry" and MockAPI.request_count <= 2:
            body = b'{"status":"rate_limited"}'
        else:
            body = b'{"status":"completed"}'

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), MockAPI)
    # When port=0, print the ephemeral port so the caller can discover it.
    print(server.server_address[1])
    sys.stdout.flush()
    server.serve_forever()
