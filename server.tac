from twisted.application import internet, service
from twisted.internet import protocol, reactor, defer
from twisted.protocols import basic
from twisted.web import resource, server, static
from twisted.web.resource import Resource
from twisted.python import log

import cgi
import ast
import redis

OPTIONS = {
    "socket_host" : "",
    "socket_port": 9090,
    "http_port" : 8000
}

class SocketListenerProtocol(basic.LineReceiver):
    def connectionMade(self):
        log.msg("Received socket connection: %s" % self)
        self.device_id = None

    def lineReceived(self, device_id):
        self.device_id = device_id
        log.msg("Received request to register device with ID: {0}. Socket: {1}".format(self.device_id, self))
        self.factory.registerDevice(self.device_id, self)

    def connectionLost(self, reason):
        log.msg("Lost connection with {0}. Reason: {1}".format(self.device_id, reason))
        self.factory.registerDevice(self.device_id, None)

class EventResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_GET(self, request):
        return 'OK'

    def render_POST(self, request):
        #Event happened. Handle it
        event = request.args["event"][0]
        device_id = request.args["device_id"][0]
        log.msg("Received event {evt} meant for device {dev}. Forwarding...".format(evt=event, dev=device_id))
        self.service.sendEvent(device_id, event)
        #TODO: Defer the above call
        return 'OK'
        
class cBridgeService(service.Service):
    def __init__(self):
        self.device_sockets = {} #Tuple(string, socket)

    def sendEvent(self, device_id, event):
        log.msg("Forwarding event {evt} to device {dev}".format(evt=event, dev=device_id))
        
        try:
            socket = self.device_sockets[device_id]
            if socket == None:
                log.err("No device socket active for device_id: {0}".format(device_id))
                return
            socket.transport.write(event)#+'\r\n')
        except KeyError:
            log.err()

    def registerDevice(self, device_id, device_socket):
        log.msg("Registering device with device_id = {0}".format(device_id))
        try:
            self.device_sockets[device_id] = device_socket
        except:
            log.err()

    def getResource(self):
        root = Resource()
        root.putChild("event", EventResource(self))
        return root

    def getSocketListenerFactory(self):
        f = protocol.ServerFactory()
        f.protocol = SocketListenerProtocol
        f.registerDevice = self.registerDevice
        return f

application = service.Application('cbridge')
cbridge_service = cBridgeService()
serviceCollection = service.IServiceCollection(application)
cbridge_service.setServiceParent(serviceCollection)
internet.TCPServer(OPTIONS['socket_port'], cbridge_service.getSocketListenerFactory()).setServiceParent(serviceCollection)
internet.TCPServer(OPTIONS['http_port'], server.Site(cbridge_service.getResource())).setServiceParent(serviceCollection)
