import string, cgi, time
from os import curdir, sep
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from socket import *

HOST = ""
HTTP_SERVER_PORT = 8000
SOCKET_PORT = 9090
HTTP_ADDR = (HOST, HTTP_SERVER_PORT)
SOCKET_ADDR = (HOST, SOCKET_PORT)
BUFFER_SIZE = 256

server = None
socket_server = socket(AF_INET,SOCK_STREAM)
socket_connection = None
socket_address = None

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path.endswith("incoming_call"):
                #Send data via socket to indicate 'mute' action
                socket_connection.send("incoming_call")
        
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write("Accepted IncomingCall Status")
                return
            elif self.path.endswith("call_ended"):
                #Send data via socket to indicate 'un-mute' action
                socket_connection.send("call_ended")

                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write("Accepted CallEnded Status")
                return
        except IOError:
            self.send_error(404, 'File Not Found: %s' % file_name)

def main():
    global socket_connection, socket_address, server

    try:
        socket_server.bind(SOCKET_ADDR)
        socket_server.listen(5)
        print "Socket listening..."

        socket_connection, socket_address = socket_server.accept()
        print "Socket connected!"

        server = HTTPServer(('', 8000), RequestHandler)
        print "Starting HTTPServer on port 8000"
        server.serve_forever()
    except KeyboardInterrupt:
        print '^C received. Shutting down...'
        socket_connection.close()
        server.socket.close()

if __name__ == '__main__':
    main()
