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

redis = redis.Redis(host='', db=2)

class SocketListenerProtocol(basic.LineReceiver):
    def connectionMade(self):
        log.msg("Received socket connection: %s" % self)
        self.device_id = None

    def lineReceived(self, line):
        split_line = line.split(':')
        
        if len(split_line) != 2:
            log.msg("Invalid message {0} from socket {1}".format(line, self))
            return

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
        elif message_type == 'heartbeat_check':
            redis_key = "device_heartbeat:" + message
            heartbeat = redis.get(redis_key)

            if heartbeat is not None:
                redis.delete(redis_key)
                self.factory.sendEvent(self.device_id, 'paired_device_heartbeat')
	else:
	    log.msg("Received unknown message {0} from socket {1}".format(line, self))

    def connectionLost(self, reason):
        log.msg("Lost connection with {0}. Reason: {1}".format(self.device_id, reason))
        self.factory.unregisterDevice(self.device_id)

class EventResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        #Event happened. Handle it
        event = request.args["event"][0]
        device_id = request.args["device_id"][0]

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
        redis_key = 'pairing_device:' + pairing_key
        pairing_device_id = redis.get(redis_key)

        if pairing_device_id is None:
            log.msg('No pairing device found for key ' + pairing_key)
            return None
        else:
            log.msg('Completing pairing. Sending acknowledgement messages.')
            redis.delete(redis_key)
            self.service.sendEvent(pairing_device_id, 'pairing_successful:' + device_id)
            return pairing_device_id
        
class HeartbeatResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        device_id = request.args["device_id"][0]
        paired_device_id = request.args["paired_device_id"][0]
        
        listening_devices = self.service.getListeningDevices()
        if paired_device_id != "" and paired_device_id in listening_devices.keys() and listening_devices[paired_device_id] != None: #Device is listening; send it a message via socket
            self.service.sendEvent(paired_device_id, 'paired_device_heartbeat')
            return "OK"

        #Device is not connected. Leave a message in Redis to let it know of the heartbeat
        redis_key = 'device_heartbeat:' + device_id
        redis.set(redis_key, paired_device_id)
        redis.expire(redis_key, 240) #4-minute expiry
        return "OK"

class DisconnectResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        device_id = request.args["device_id"][0]
        paired_device_id = request.args["paired_device_id"][0]
        log.msg("Received disconnect  message from " + device_id + " intended for recipient " + paired_device_id)
        
        redis.delete('device_heartbeat:' + device_id)

        listening_devices = self.service.getListeningDevices()
        if paired_device_id != "" and paired_device_id in listening_devices.keys() and listening_devices[paired_device_id] != None: #Device is listening; send it a message via socket
            log.msg("Device is connected. Forwarding disconnect request to " + paired_device_id)
            self.service.sendEvent(paired_device_id, 'paired_device_disconnected')
        
        return "OK"

class TriggrService(service.Service):
    def __init__(self):
        self.device_sockets = {} #dict(string, socket)

    def getListeningDevices(self):
        return self.device_sockets

    def sendEvent(self, device_id, event):
        log.msg("Forwarding event {evt} to device {dev}".format(evt=event, dev=device_id))

	event_type = event.split(':', 1)[0]
        
	#Metrics
	redis.incr("total_events")
	redis.incr("total_events_{0}".format(event_type))

        try:
            socket = self.device_sockets[device_id]
            if socket == None:
                log.err("Socket has disconnected for device_id: {0}".format(device_id))
                return
            socket.transport.write(event + '\r\n')
        except KeyError:
            log.err("Socket has disconnected for device_id: {0}".format(device_id))

    def unregisterDevice(self, device_id):
        if device_id in self.device_sockets.keys():
            log.msg("Unregistering device {0}".format(device_id))
	    log.msg("Unregistered device. Number of connected devices: {0}".format(len(self.device_sockets)))
            del(self.device_sockets[device_id])
        else:
            log.msg("Unregistration for device {0} failed. Device has not been registered".format(device_id))

    def registerDevice(self, device_id, device_socket):
        log.msg("Registering device with device_id: {0}".format(device_id))
        try:
            self.device_sockets[device_id] = device_socket
	    log.msg("New device registered. Number of connected devices: {0}".format(len(self.device_sockets)))
        except:
            log.err()

    def getResource(self):
        root = Resource()
        root.putChild("events", EventResource(self))
        root.putChild("pair", PairingResource(self))
        root.putChild("heartbeat", HeartbeatResource(self))
        root.putChild("disconnect", DisconnectResource(self))
        return root

    def getSocketListenerFactory(self):
        f = protocol.ServerFactory()
        f.protocol = SocketListenerProtocol
        f.registerDevice = self.registerDevice
        f.unregisterDevice = self.unregisterDevice
        f.sendEvent = self.sendEvent
        f.getListeningDevices = self.getListeningDevices
        return f

application = service.Application('triggr')
triggr_service = TriggrService()
serviceCollection = service.IServiceCollection(application)
triggr_service.setServiceParent(serviceCollection)
internet.TCPServer(OPTIONS['socket_port'], triggr_service.getSocketListenerFactory()).setServiceParent(serviceCollection)
internet.TCPServer(OPTIONS['http_port'], server.Site(triggr_service.getResource())).setServiceParent(serviceCollection)
