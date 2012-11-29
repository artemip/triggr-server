import threading
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import redis

DEVICE_SOCKETS = dict()

def redis_listener():
    r = redis.Redis(host='localhost', db=2)
    pubsub = r.pubsub()
    pubsub.subscribe('new_request')
    for request in pubsub.listen():
        DEVICE_SOCKETS[request['device_id']].write_message(unicode(request['event']))

class NewRequestHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")

    def post(self):
        data = self.request.arguments
        r = redis.Redis(host='localhost', db=2)
        pubsub = r.pubsub()
        pubsub.publish('new_request', data)

class NewDeviceHandler(tornado.websocket.WebSocketHandler):
    def open(self):
        pass #DEVICE_SOCKETS[""] = ""

    def on_message(self, message):
        if(message.startswith("device_id:")):
            self.device_id = message[10:]
            DEVICE_SOCKETS[self.device_id] = self
    
    def on_close(self):
        pass

settings = {
    'auto_reload': True,
}

application = tornado.web.Application([
        (r'/', NewRequestHandler),
        (r'/add_device', NewDeviceHandler),
], **settings)

if __name__ == "__main__":
    threading.Thread(target=redis_listener).start()
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(8000)
    tornado.ioloop.IOLoop.instance().start()
