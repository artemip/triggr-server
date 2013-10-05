import httplib, urllib
from functools import partial
import select
import socket
from timeit import Timer
import threading
import json

POST_HEADER = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}

event_counter = 0
run_test = True
connected_cond = None
connection_countdown = None

def get_execution_time(function, *args, **kwargs):
    """Return the execution time of a function in seconds."""
    return round(Timer(partial(function, *args, **kwargs))
                 .timeit(1), 6)

class TestServer(threading.Thread):
    def __init__(self, id, server_host, server_port):
        super(TestServer, self).__init__()
        self.id = id
        self.socket_endpoint = (server_host, server_port)
        self.socket = None

    def run(self):
        self.connect()
        self.recv()
        self.close()

    def registration_json(self):
        return json.dumps({"message_type":"register_device","message":"%s" % self.id})

    def connect(self):
        global connected_cond
        global connection_countdown
        
        with connected_cond:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(self.socket_endpoint)
            self.socket.settimeout(2)
            self.socket.send(self.registration_json() + "\r\n")

            connection_countdown -= 1
            if connection_countdown == 0:
                connected_cond.notifyAll()

    def close(self):
        self.socket.close()

    def recv(self):
        global event_counter
        global run_test

        while run_test:
            try:
                self.socket.recv(512)
                event_counter += 1
            except socket.timeout:
                pass #Keep receiving
            except socket.error as se:
                print "Socket error(%s):%s" % (se.errno, se.strerror)
                break

class TestClient(threading.Thread):
    def __init__(self, id, api_endpoint, num_events):
        super(TestClient, self).__init__()
        self.id = id
        self.api_conn = httplib.HTTPConnection(api_endpoint)
        self.num_events = num_events

    def __del__(self):
        self.api_conn.close()

    def __POST_event(self, params):
        self.api_conn.request("POST", "/events", params, POST_HEADER)
        self.api_conn.getresponse().read()

    def __get_params(self):
        event_json = {
            "sender_id":"%s" % self.id,
            "type":"test_event",
            "notification": {
                "icon_uri":"test_uri",
                "title":"Test",
                "subtitle":"SGH-i745a",
                "description":"test_description"},
            "handlers":["notify"]
        }
        
        return urllib.urlencode({
            'event':json.dumps(event_json),
            'device_id':self.id
        })

    def run(self):
        for i in xrange(self.num_events):
            self.__POST_event(self.__get_params())

    def event_json(self):
        return json.dumps({"message_type":"register_device","message":"%s" % self.id})

class LoadTester():
    global event_counter
    global run_test

    def __init__(self, api_endpoint, server_host, server_port):
        self.client_threads = []
        self.server_threads = []
        self.server_host = server_host
        self.server_port = server_port
        self.api_endpoint = api_endpoint

    def __start_servers(self, num_servers):
        self.server_threads = []

        for i in range(0, num_servers):
            thread = TestServer(i, self.server_host, self.server_port)
            self.server_threads.append(thread)

        for thread in self.server_threads:
            thread.start()

    def __start_clients(self, num_clients, num_events):
        self.client_threads = []
        events_per_client = num_events / num_clients
        extra_events = num_events % num_clients

        t = TestClient(0, self.api_endpoint, events_per_client + extra_events)
        self.client_threads.append(t)
        
        for i in range(1, num_clients):
            thread = TestClient(i, self.api_endpoint, events_per_client)
            self.client_threads.append(thread)

        for thread in self.client_threads:
            thread.start()

    def __stop_clients(self):
        for thread in self.client_threads:
            thread.join()
            del(thread)

    def __stop_servers(self):
        for thread in self.server_threads:
            thread.join()
            del(thread)


    def test(self, num_devices, num_events):
        global run_test
        global event_counter
        global connected_cond
        global connection_countdown

        run_test = True
        event_counter = 0
        connected_cond = threading.Condition()
        connection_countdown = num_devices
        
        with connected_cond:
            self.__start_servers(num_devices)
            if connection_countdown > 0:
                connected_cond.wait() # Wait for clients to be connected

        self.__start_clients(num_devices, num_events)
        self.__stop_clients()
        
        run_test = False

        self.__stop_servers()

        if event_counter == num_events:
            print "Test Succeeded: (Clients: {0}, Events: {1})".format(num_devices, num_events)
        else:
            print "Test Failed: (Clients: {0}, Events: {1}). Events processed: {2}".format(num_devices, num_events, event_counter)

def main():
    load_tester = LoadTester(
        api_endpoint = "localhost:8000", 
        server_host = "localhost",
        server_port = 9090)

    num_devices = [10, 100, 1000] 
    num_events = [100, 1000, 10000]

    for c in num_devices:
        for e in num_events:
            print "Time taken: %ss" % get_execution_time(load_tester.test, num_devices = c, num_events = e)

if __name__ == '__main__':
    main()
