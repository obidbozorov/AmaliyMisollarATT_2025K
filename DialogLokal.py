# Lokal tarmoqda ikki kompyuter o'rtasida dialog
# Ishlatish: python DialogLokal.py server   (birinchi kompyuter)
#           python DialogLokal.py client <server_ip>   (ikkinchi kompyuter)

import socket
import sys
import threading

PORT = 5000
BUFFER = 1024


def server_mode():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("192.168.63.60", PORT))
    s.listen(1)
    print(f"Server ishga tushdi. Port: {PORT}")
    print("Boshqa kompyuter ulanishini kutyapman...")
    conn, addr = s.accept()
    print(f"Ulandi: {addr}")
    handle_connection(conn, is_server=True)


def client_mode(host):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, PORT))
    print(f"Serverga ulandi: {host}:{PORT}")
    handle_connection(s, is_server=False)


def handle_connection(conn, is_server):
    def receiver():
        while True:
            try:
                data = conn.recv(BUFFER)
                if not data:
                    print("\nUlanish uzildi.")
                    break
                print(f"\nQarshi tomon: {data.decode('utf-8')}")
                print("Siz: ", end="", flush=True)
            except:
                break

    t = threading.Thread(target=receiver, daemon=True)
    t.start()

    try:
        while True:
            msg = input("Siz: ")
            if msg.lower() in ("exit", "quit", "chiqish"):
                conn.sendall("Ulanish tugatildi.".encode("utf-8"))
                break
            conn.sendall(msg.encode("utf-8"))
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Ishlatish:")
        print("  python DialogLokal.py server")
        print("  python DialogLokal.py client <server_ip>")
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode == "server":
        server_mode()
    elif mode == "client":
        if len(sys.argv) < 3:
            print("Server IP manzilini kiriting: python DialogLokal.py client <ip>")
            sys.exit(1)
        client_mode(sys.argv[2])
    else:
        print("Noto'g'ri rejim. 'server' yoki 'client' bo'lishi kerak.")
        sys.exit(1)
