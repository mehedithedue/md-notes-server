import http.server
import socketserver
import socket
import sys
import os

PORT = 8080

def get_local_ip():
    """
    Try to find the local network IP (192.168.x.x / 10.x.x.x etc.)
    Works reasonably well cross-platform (Windows, macOS, Linux).
    """
    s = None
    try:
        # Create a dummy UDP socket and connect to a public DNS → gets the outgoing interface IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        # Doesn't need to actually send data
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        # Filter out loopback
        if ip.startswith('127.'):
            raise Exception("Got loopback")
        return ip
    except Exception:
        # Fallback: try gethostbyname
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if not ip.startswith('127.'):
                return ip
        except:
            pass
    # Last fallback: show common possibilities
    print("Could not auto-detect network IP reliably.")
    print("Try these commands manually:")
    print("  Windows: ipconfig → look for IPv4 under Wi-Fi")
    print("  macOS/Linux: ifconfig or ip addr → look for inet under Wi-Fi interface")
    return None

def print_qr(url):
    try:
        import qrcode
        qr = qrcode.QRCode()
        qr.add_data(url)
        qr.make(fit=True)
        print("\nScan this QR code from your tablet:\n")
        qr.print_ascii(tty=True)   # Nice inverted look in most terminals
        print("")
    except ImportError:
        print("(Install 'qrcode' with: pip install qrcode  → for fancy terminal QR)")
    except Exception as e:
        print(f"QR failed: {e}")

def main():
    ip = get_local_ip()

    if ip:
        url = f"http://{ip}:{PORT}"
        print("\n" + "="*60)
        print(f"  Local Markdown Server started!")
        print(f"  Folder: {os.path.abspath('.')}")
        print(f"  Access from your tablet → {url}")
        print(f"  (open any .md file like {url}/notes.md)")
        print("="*60 + "\n")
        
        # Show QR code
        print_qr(url)
    else:
        url = f"http://YOUR_IP_HERE:{PORT}"
        print("\nServer will start → but edit the URL with your real IP\n")

    print("Press Ctrl+C to stop the server.\n")

    # Start the server
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at port {PORT} ...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            sys.exit(0)

if __name__ == "__main__":
    main()