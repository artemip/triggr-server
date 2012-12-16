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

redis = redis.Redis(host='localhost', db=2)

class SocketListenerProtocol(basic.LineReceiver):
    def connectionMade(self):
        log.msg("Received socket connection: %s" % self)
        self.device_id = None

    #TODO: use format of <message_type>:<data> to generalize messages being sent from the client
    def lineReceived(self, line):
        split_line = line.split(':')
        
        if len(split_line) != 2:
            log.msg("Received invalid message {0} from socket {1}".format(line, self))

        message_type = split_line[0]
        message = split_line[1]

        if message_type == 'device_id':
            self.device_id = message
            log.msg("Received request to register device with ID: {0}. Socket: {1}".format(self.device_id, self))
            self.factory.registerDevice(self.device_id, self)            
        elif message_type == 'pairing_key':
            redis_key = 'pairing_device:' + message
            redis.set(redis_key, self.device_id)
            redis.expire(redis_key, 86400) #1-day expiry
            log.msg("Acknowledging pairing attempt for device {0}. Using pairing key {1}.".format(self.device_id, message))

    def connectionLost(self, reason):
        log.msg("Lost connection with {0}. Reason: {1}".format(self.device_id, reason))
        self.factory.registerDevice(self.device_id, None)

class EventResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        #Event happened. Handle it
        event = request.args["event"][0]
        device_id = request.args["device_id"][0]
        log.msg("Received event {evt} meant for device {dev}. Forwarding...".format(evt=event, dev=device_id))
        self.service.sendEvent(device_id, event)
        #TODO: Defer the above call; May take a while
        return 'OK' #TODO: return some relevant message

class PairingResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        device_id = request.args["device_id"][0]
        pairing_key = request.args["pairing_key"][0]
        pairing_device_id = redis.get('pairing_device:' + pairing_key)

        if pairing_device_id == None:
            return "Invalid ID"
        else:
            sendEvent(pairing_device_id, 'pairing_successful')
            return pairing_device_id
        
        
class cBridgeService(service.Service):
    def __init__(self):
        self.device_sockets = {} #dict(string, socket)

    def sendEvent(self, device_id, event):
        log.msg("Forwarding event {evt} to device {dev}".format(evt=event, dev=device_id))
        
        try:
            socket = self.device_sockets[device_id]
            if socket == None:
                log.err("Socket has disconnected for device_id: {0}".format(device_id))
                return
            socket.transport.write(event + '\r\n')
        except KeyError:
            log.err()

    def registerDevice(self, device_id, device_socket):
        log.msg("Registering device with device_id: {0}".format(device_id))
        try:
            self.device_sockets[device_id] = device_socket
        except:
            log.err()

    def getResource(self):
        root = Resource()
        root.putChild("events", EventResource(self))
        root.putChild("pair", PairingResource(self))
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
