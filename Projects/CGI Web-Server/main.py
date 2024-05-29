from socket import socket, AF_INET, SOCK_STREAM, timeout, SOL_SOCKET, SO_REUSEADDR
from threading import Thread
import os
import subprocess

MAX_CONNECTIONS = 10
PORT = 8888

BASE_PATH = os.path.join(os.getcwd(), "webroot")


class RequestType:
	GET = "GET"
	POST = "POST"
	HEAD = "HEAD"


class Server:
	def __init__(self):
		self.threads: [Thread] = []
		self.sock = socket(AF_INET, SOCK_STREAM)
		self.sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
		self.sock.bind(('localhost', PORT))

		self.client_thread = Thread(target=self.handler)

	def __del__(self):
		self.sock.close()
		print("CLOOOOOOOOOOOSE")

	def start(self):
		self.sock.listen()
		while True:
			client_sock, addr = self.sock.accept()
			if len(self.threads) == MAX_CONNECTIONS:
				print("Too much!!!!!!!!!!!!!")
				oldest_thread = self.threads.pop(0)
				oldest_thread.join()
			thread = Thread(target=self.handler, args=(client_sock,))
			thread.start()
			self.threads.append(thread)

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

	def handler(self, client_sock):
		data = client_sock.recv(1024)
		print(data)
		data = data.decode('utf-8')
		data = self.parse_request(data)
		match data['Method']:
			case RequestType.GET:
				print("Yes it's get")
				if data['Path'] == '/':
					file_path = os.path.join(BASE_PATH, "index.html")
					file_size = os.path.getsize(file_path)

					response_header = f'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {file_size}\r\n\r\n'
					client_sock.send(response_header.encode())

					file = open(file_path, "rb")
					client_sock.sendfile(file, 0)
					file.close()
					print("Send!")
				# elif data['Path'] == '/cgi-bin/number.py':
				# 	ans = subprocess.call([f"sudo python3 {os.path.join(BASE_PATH, 'cgi-bin/number.py')}"],
				# 						  universal_newlines=True)
				#
				# 	response_header = f'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(ans)}\r\n\r\n'
				# 	client_sock.send(response_header.encode())
				# 	client_sock.send(ans.to_bytes())
				else:
					client_sock.send("Oops!".encode('utf-8'))
					print("Or not")
			case RequestType.POST:
				pass
			case RequestType.HEAD:
				pass
		client_sock.close()
		print("Closed client socket!")


if __name__ == "__main__":
	try:
		server = Server()
		server.start()
	except KeyboardInterrupt:
		print("That's it")
