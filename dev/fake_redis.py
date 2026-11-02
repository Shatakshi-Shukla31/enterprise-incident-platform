"""A Redis-protocol server for machines that cannot run Redis. Development only: it keeps
everything in memory and has none of Redis's durability or performance."""

from fakeredis import TcpFakeServer

ADDRESS = ("127.0.0.1", 6380)

if __name__ == "__main__":
    server = TcpFakeServer(ADDRESS, server_type="redis")
    print(f"Fake Redis listening on {ADDRESS[0]}:{ADDRESS[1]}", flush=True)
    server.serve_forever()
