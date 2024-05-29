from socket import socket, AF_INET, SOCK_STREAM, timeout
from threading import Thread

MAX_CONNECTIONS = 10


class RequestType:
	GET = "GET"
	POST = "POST"
	HEAD = "HEAD"


class Server:
	def __init__(self):
		self.sock = socket(AF_INET, SOCK_STREAM)
		self.sock.bind(('localhost', 7777))
		self.working_thread = Thread(target=self.main_thread)
		self.working_thread.start()

		self.client_sock = None
		self.client_thread = Thread(target=self.handler)

	def main_thread(self):
		self.sock.listen()
		while True:
			self.client_sock, addr = self.sock.accept()
			self.client_thread.start()

	def parse_request(self, request):
		req_lines = request.split('\r\n')
		req_dict = {}
		first_line = req_lines[0].split(' ')
		req_dict['Method'] = first_line[0]
		req_dict['Path'] = first_line[1]
		req_dict['HTTP_Version'] = first_line[2]

		for line in req_lines[1:]:
			if line == '':
				break
			key, value = line.split(': ', 1)
			req_dict[key] = value

		return req_dict

	def handler(self):
		try:
			while True:
				data = self.client_sock.recv(1024)
				print(data)
				data = data.decode('utf-8')
				data = self.parse_request(data)
				match data['Method']:
					case RequestType.GET:
						if data['Path'] == '/':

					case RequestType.POST:
						pass
					case RequestType.HEAD:
						pass
		except KeyboardInterrupt:
			self.client_sock.close()
			self.sock.close()
			exit()
		# GET /index.html


if __name__ == "__main__":
	server = Server()
