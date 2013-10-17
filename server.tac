from twisted.application import internet, service

from twisted.internet import epollreactor
epollreactor.install() #EPoll scales much better than the default reactor implementation on Linux

from twisted.internet import protocol, reactor, defer, task
from twisted.protocols import basic
from twisted.web import resource, server, static
from twisted.web.resource import Resource
from twisted.python import log

from time import gmtime, strftime
import cgi
import ast
import json
import redis

OPTIONS = {
    "socket_host" : "",
    "socket_port": 9090,
    "http_port" : 8000
}

redis_metrics = redis.Redis(host='', db=0)
redis = redis.Redis(host='', db=1)

# OK message (no errors, no significant messages)
def okMessageJSON():
    response = { 'status' : 'ok' }
    return json.dumps(response)

# Message to return then connected to new device
def connectedMessageJSON(paired_device_id):
    response = { 'status' : 'ok', 'message' : '', 'paired_device_id' : paired_device_id }
    return json.dumps(response)

# Error occured; Send the message (reason) back to the client
def errorMessageJSON(message):
    response = { 'status' : 'error', 'message' : message, 'paired_device_id' : ''}
    return json.dumps(response)

def get_date_stamp():
    return strftime("%Y-%m-%d-%H:00:00", gmtime())

# Listen to and communicate with incoming socket connections
class SocketListenerProtocol(basic.LineReceiver):
    def __init__(self):
        self.device_id = None
        self.timeout_task = None
        self.socket_timeout = 86400 #24 hours
        self.sent_message = True

    def timeout_connection(self):
        if self.sent_message == False:
            log.msg("Timing out old connection: {0}; Reason: {1}s timeout passed".format(self.device_id, self.socket_timeout))
            self.transport.abortConnection()
        else:
            self.sent_message = False
            
    # Log new connection being made
    def connectionMade(self):
        log.msg("Received socket connection: %s" % self)
        self.timeout_task = task.LoopingCall(self.timeout_connection)
        self.timeout_task.start(self.socket_timeout)
        self.device_id = None

    # Receive a message from the socket
    def lineReceived(self, line):
        parsed_json = json.loads(line)

        try:
            # Get message type and message data
            message_type = parsed_json["message_type"]
            message = parsed_json["message"]

            # New device registration; Save the socket connection
            if message_type == 'register_device':
                self.device_id = message
                self.factory.registerDevice(self.device_id, self)
            # Register and save a new pairing key to connect devices
            elif message_type == 'register_pairing_key':
                redis_key = 'pairing_device:' + message
                redis.set(redis_key, self.device_id)
                redis.expire(redis_key, 86400) #1-day expiry
                log.msg("Registering pairing key {0} from device {1}.".format(message, self.device_id))
            else:
                raise Exception
                
        except:
            # Broken or malicious client. Close the connection
            log.err()
            log.msg("Invalid message {0} from socket {1}".format(line, self))
            self.transport.abortConnection()

    # When the connection is lost, unregister the device and forget the socket
    def connectionLost(self, reason):
        log.msg("Lost connection with device {0}. Reason: {1}".format(self.device_id, reason))
        self.factory.unregisterDevice(self.device_id)
        self.timeout_task.stop()

class EventResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        # Handle incoming event
        event = request.args["event"][0]
        device_id = request.args["device_id"][0]

        if self.service.sendEvent(device_id, event):
            return connectedMessageJSON(device_id)
        else:
            return errorMessageJSON("Lost computer connection")

class ConnectResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        device_id = request.args["device_id"][0]
        pairing_key = request.args["pairing_key"][0]
        event = request.args["event"][0]
        
        redis_key = 'pairing_device:' + pairing_key
        pairing_device_id = redis.get(redis_key)

        log.msg(event)

        if pairing_device_id is None:
            log.msg('No matching device found for pairing key: ' + pairing_key)
            return errorMessageJSON("Invalid pairing key")
            
        log.msg('Connected devices {0} and {1} using key {2}.'.format(device_id, pairing_device_id, pairing_key))
        redis.delete(redis_key)
        if self.service.sendEvent(pairing_device_id, event):
            return connectedMessageJSON(pairing_device_id)
        else:
            return errorMessageJSON("Lost computer connection")

class DisconnectResource(resource.Resource):
    def __init__(self, service):
        resource.Resource.__init__(self)
        self.service = service
    
    def render_POST(self, request):
        device_id = request.args["device_id"][0]
        paired_device_id = request.args["paired_device_id"][0]
        event = request.args["event"][0]

        log.msg("Received disconnect message from " + device_id + " intended for recipient " + paired_device_id)

        listening_devices = self.service.getListeningDevices()
        if paired_device_id != "" and paired_device_id in listening_devices.keys() and listening_devices[paired_device_id] != None:
            log.msg("Device is connected. Forwarding disconnect request to " + paired_device_id)
            
            if self.service.sendEvent(paired_device_id, event):
                return okMessageJSON()

        return errorMessageJSON("Lost computer connection")

class TriggrService(service.Service):
    def __init__(self):
        self.device_sockets = {} #dict(string, socket)

    def getListeningDevices(self):
        return self.device_sockets

    def sendEvent(self, device_id, event_json):
        event = json.loads(event_json)
        event_type = event["type"]
        
        log.msg("Forwarding event {evt} to device {dev}".format(evt=event_json, dev=device_id))
    
        redis_metrics.incr("events_total")
        redis_metrics.incr("{0}".format(event_type))
        redis_metrics.incr("{0}:{1}".format(event_type, get_date_stamp()))

        try:
            socket = self.device_sockets[device_id]
            socket.transport.write(event_json + '\r\n')
            socket.sent_message = True
            return True
        except KeyError:
            log.msg("Invalid device_id %s" % device_id)
            return False
        except:
            log.err()
            return False

    def registerDevice(self, device_id, device_socket):
        # This device is already registered
        if device_id in self.device_sockets:
            # Don't log the connection; Overwrite the old one and return
            redis_metrics.incr("connected_devices_duplicates")
            redis_metrics.incr("connected_devices_duplicates:{0}".format(get_date_stamp()))
            self.device_sockets[device_id] = device_socket
            return
        
        try:
            num_connected_devices = len(self.device_sockets)
            
            redis_metrics.set("connected_devices", num_connected_devices)
            redis_metrics.set("connected_devices:{0}".format(get_date_stamp()), num_connected_devices)
            redis_metrics.incr("connections")
            redis_metrics.incr("connections:{0}".format(get_date_stamp()))
            
            self.device_sockets[device_id] = device_socket
            log.msg("Registered new device: {0}. Number of connected devices: {1}".format(device_id, num_connected_devices))
        except:
            log.err()

    def unregisterDevice(self, device_id):
        if device_id in self.device_sockets:
            del(self.device_sockets[device_id])

            num_connected_devices = len(self.device_sockets)

            redis_metrics.set("connected_devices", num_connected_devices)
            redis_metrics.set("connected_devices:{0}".format(get_date_stamp()), num_connected_devices)
            redis_metrics.incr("disconnections")
            redis_metrics.incr("disconnections:{0}".format(get_date_stamp()))
            
            log.msg("Unregistered device {0}. Number of connected devices: {1}".format(device_id, num_connected_devices))
        else:
            log.msg("Unregistration for device {0} failed. Device has not been registered".format(device_id))

    def getResource(self):
        root = Resource()
        root.putChild("events", EventResource(self))
        root.putChild("connect", ConnectResource(self))
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
