"""Select reachable local IPv4 addresses for phone sharing."""
import socket


def route_address():
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        connection.connect(('10.255.255.255', 1))
        return connection.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        connection.close()


def phone_reachable_addresses():
    preferred = route_address()
    discovered = []
    try:
        records = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for record in records:
            address = record[4][0]
            if address not in discovered and not address.startswith(('127.', '169.254.')):
                discovered.append(address)
    except OSError:
        pass

    def rank(address):
        if address == preferred:
            return 0
        if address.startswith('192.168.'):
            return 1
        if address.startswith('10.'):
            return 2
        if address.startswith('172.'):
            return 3
        return 4

    candidates = discovered + ([preferred] if preferred != '127.0.0.1' else [])
    result = sorted(set(candidates), key=rank)
    return result or ['127.0.0.1']
