import ast
from threading import Thread
from socket import *
import tornado.httpserver
import tornado.web
import tornado.ioloop
import redis

OPTIONS = {
    "socket_host" : "",
    "socket_port": 9090,
    "http_port" : 8000
}
DEVICE_SOCKETS = {}

def redis_listener():
    r = redis.Redis(host='localhost', db=2)
    pubsub = r.pubsub()
    pubsub.subscribe('new_request')
    for request in pubsub.listen():
        if request['data'] == 1L: continue

        data = ast.literal_eval(request['data'])
        try:
            device_id = data['device_id'][0]
            event = data['event'][0]

            print device_id
            print event

            DEVICE_SOCKETS[device_id].send(event)
        except KeyError, e:
            print e

def device_socket_registration(socket, addr):
    device_id = socket.recv(256) #Blocking call, waits for at most 256 bytes. Might want to verify the ID as well
    print "Registering " + device_id
    DEVICE_SOCKETS[device_id] = socket
    

def socket_listener():
    socket_addr = (OPTIONS["socket_host"], OPTIONS["socket_port"])
    socket_server = socket( AF_INET, SOCK_STREAM )
    
    socket_server.bind( socket_addr )
    socket_server.listen(5)

    while 1:
        socket_connection, socket_address = socket_server.accept()
        print "Socket accepted"
        Thread(target=device_socket_registration, args = (socket_connection, socket_address)).start()

class NewRequestHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")

    def post(self):
        data = self.request.arguments
        r = redis.Redis(host='localhost', db=2)
        r.publish('new_request', data)

class NewDeviceHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")

    def post(self):
        self.write("OK")

settings = {
    'auto_reload': True,
}

application = tornado.web.Application([
        (r'/events', NewRequestHandler),
        (r'/register', NewDeviceHandler)
], **settings)

if __name__ == "__main__":
    try:
        Thread(target=redis_listener).start()
        Thread(target=socket_listener).start()
        http_server = tornado.httpserver.HTTPServer(application)
        http_server.listen(OPTIONS["http_port"])
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
         print '^C received. Shutting down...'
         tornado.ioloop.IOLoop.instance().stop()
         for device_id, socket in DEVICE_SOCKETS:
             socket.close()
