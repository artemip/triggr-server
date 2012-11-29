import ast
import threading
import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import redis

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

            DEVICE_SOCKETS[device_id].write_message(event)
        except KeyError, e:
            print e

class NewRequestHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("OK")

    def post(self):
        data = self.request.arguments
        r = redis.Redis(host='localhost', db=2)
        r.publish('new_request', data)

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
