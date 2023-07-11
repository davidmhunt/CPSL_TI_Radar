from multiprocessing.connection import Client

address = ('localhost', 6000)     # family is deduced to be 'AF_INET'
authkey_str = "TLV_client"
print("Waiting to connect to listener")
conn = Client(address, authkey=authkey_str.encode())

print("connected to listener")

while True:
    try:
        new_points = conn.recv()
        print(new_points)
    except EOFError:
        break

print("Listener connection closed")