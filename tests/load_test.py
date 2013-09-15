import httplib, urllib
from functools import partial
import select
import socket
from timeit import Timer
import threading

POST_HEADER = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}

event_counter = 0
run_test = True
connected_cond = None
connection_countdown = None

def get_execution_time(function, *args, **kwargs):
    """Return the execution time of a function in seconds."""
    return round(Timer(partial(function, *args, **kwargs))
                 .timeit(1), 6)

class TestClient(threading.Thread):
    def __init__(self, id, server_host, server_port):
        super(TestClient, self).__init__()
        self.socket_endpoint = (server_host, server_port)
        self.socket = None
        self.id = id

    def run(self):
        self.connect()
        self.recv()
        self.close()

    def connect(self):
        global connected_cond
        global connection_countdown
        
        with connected_cond:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect(self.socket_endpoint)
            self.socket.settimeout(2)
            self.socket.send("device_id:{0}\r\n".format(self.id))

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
        
class LoadTester():
    global event_counter
    global run_test

    def __init__(self, api_endpoint, server_host, server_port):
        self.client_threads = []
        self.api_conn = httplib.HTTPConnection(api_endpoint)
        self.server_host = server_host
        self.server_port = server_port

    def __del__(self):
        self.api_conn.close()

    def __POST_event(self, params):
        self.api_conn.request("POST", "/events", params, POST_HEADER)
        self.api_conn.getresponse().read()

    def __start_clients(self, num_clients):
        run_test = True
        self.client_threads = []

        for i in range(0, num_clients):
            thread = TestClient(i, self.server_host, self.server_port)
            self.client_threads.append(thread)

        for thread in self.client_threads:
            thread.start()

    def __get_params(self, id):
        return urllib.urlencode({
                'event':'test_event',
                'device_id':id
                })

    def __stop_clients(self):
        for thread in self.client_threads:
            thread.join()
            del(thread)

    def test(self, num_clients, num_events):
        global run_test
        global event_counter
        global connected_cond
        global connection_countdown

        run_test = True
        event_counter = 0
        connected_cond = threading.Condition()
        connection_countdown = num_clients
        
        with connected_cond:
            self.__start_clients(num_clients)
            if connection_countdown > 0:
                connected_cond.wait() # Wait for clients to be connected
        
        try:
            for i in range(0, num_events):
                self.__POST_event(self.__get_params(i % num_clients))
        finally:
            run_test = False
            self.__stop_clients()

        if event_counter == num_events:
            print "Test Succeeded: (Clients: {0}, Events: {1})".format(num_clients, num_events)
        else:
            print "Test Failed: (Clients: {0}, Events: {1}). Events processed: {2}".format(num_clients, num_events, event_counter)

def main():
    load_tester = LoadTester(
        api_endpoint = "localhost:8000", 
        server_host = "localhost",
        server_port = 9090)

    num_clients = [10000] 
    num_events = [10000]

    for c in num_clients:
        for e in num_events:
            print "Time taken: %ss" % get_execution_time(load_tester.test, num_clients = c, num_events = e)

if __name__ == '__main__':
    main()
