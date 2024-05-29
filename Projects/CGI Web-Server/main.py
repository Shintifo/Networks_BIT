from socket import socket, AF_INET, SOCK_STREAM, timeout, SOL_SOCKET, SO_REUSEADDR
from threading import Thread
import os
import subprocess

MAX_CONNECTIONS = 10
PORT = 8888

BASE_PATH = os.path.join(os.getcwd(), "webroot")
print(BASE_PATH)


# TODO POST
# TODO Log files


class RequestType:
	GET = "GET"
	POST = "POST"
	HEAD = "HEAD"


class Server:
	def __init__(self):
		self.sock = socket(AF_INET, SOCK_STREAM)
		self.sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
		self.sock.bind(('localhost', PORT))

		self.threads: [Thread] = []

	def __del__(self):
		self.sock.close()

	def start(self):
		self.sock.listen()
		while True:
			client_sock, addr = self.sock.accept()
			if len(self.threads) == MAX_CONNECTIONS:
				oldest_thread = self.threads.pop(0)
				oldest_thread.join()

			thread = Thread(target=self.handler, args=(client_sock,))
			thread.start()
			self.threads.append(thread)

	@staticmethod
	def parse_request(request):
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

	@staticmethod
	def open_not_found(client_sock):
		path = os.path.join(BASE_PATH, '404.html')
		file_size = os.path.getsize(path)
		response_header = (f'HTTP/1.1 404 Not Found\r\n'
						   f'Content-Type: text/html\r\n'
						   f'Content-Length: {file_size}\r\n\r\n')
		client_sock.send(response_header.encode())
		file = open(path, "rb")
		client_sock.sendfile(file, 0)
		file.close()

	def handler(self, client_sock):
		data = client_sock.recv(1024)
		print(data)
		data = data.decode('utf-8')
		data = self.parse_request(data)

		if 'cgi-bin' in data['Path']:
			self.cgi(data=data, client_sock=client_sock)
		else:
			self.static_web(data=data, client_sock=client_sock)

	def static_web(self, data, client_sock):
		file_path = BASE_PATH + "/" + data["Path"]
		match data['Method']:
			case RequestType.GET:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					client_sock.close()
					return

				if data['Path'] == '/':
					file_path = os.path.join(BASE_PATH, "index.html")
					file_size = os.path.getsize(file_path)
				else:
					file_size = os.path.getsize(file_path)

				response_header = (f'HTTP/1.1 200 OK\r\n'
								   f'Content-Type: text/html\r\n'
								   f'Content-Length: {file_size}\r\n\r\n')
				client_sock.send(response_header.encode())

				file = open(file_path, "rb")
				client_sock.sendfile(file, 0)
				file.close()
				print("Send!")
			case RequestType.HEAD:
				if not os.path.exists(file_path):
					response_header = (f'HTTP/1.1 404 Not Found\r\n'
									   f'Content-Type: text/html\r\n\r\n')
				else:
					response_header = (f'HTTP/1.1 200 OK\r\n'
									   f'Content-Type: text/html\r\n\r\n')
				client_sock.send(response_header.encode())

		client_sock.close()

	def cgi(self, data, client_sock):
		file_path = BASE_PATH + "/" + data["Path"]
		match data["Method"]:
			case RequestType.GET:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					client_sock.close()
					return

				process = subprocess.Popen([BASE_PATH + data['Path']], stdout=subprocess.PIPE,
										   stderr=subprocess.PIPE)
				stdout, stderr = process.communicate()
				ans = stdout.decode()
				response_header = f'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(ans)}\r\n\r\n'
				client_sock.send(response_header.encode())
				client_sock.send(ans.encode())
			case RequestType.HEAD:
				if not os.path.exists(file_path):
					response_header = (f'HTTP/1.1 404 Not Found\r\n'
									   f'Content-Type: text/html\r\n\r\n')
				else:
					response_header = (f'HTTP/1.1 200 OK\r\n'
									   f'Content-Type: text/html\r\n\r\n')
				client_sock.send(response_header.encode())
			case RequestType.POST:
				pass
		client_sock.close()


if __name__ == "__main__":
	try:
		server = Server()
		server.start()
	except KeyboardInterrupt:
		print("That's it")
