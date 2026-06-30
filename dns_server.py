"""
DNS filtering server — listens on UDP + TCP port 53.
Blocked domains return NXDOMAIN; allowed ones are forwarded to upstream.
"""
import os, socket, threading, time, logging
from dnslib import DNSRecord, RCODE
from dnslib.server import DNSServer, BaseResolver
import db
from dotenv import load_dotenv

load_dotenv()

UPSTREAM_DNS     = os.getenv("UPSTREAM_DNS", "1.1.1.1")
DNS_PORT         = int(os.getenv("DNS_PORT", "53"))
LOG_QUERIES      = os.getenv("LOG_QUERIES", "true").lower() == "true"
RELOAD_INTERVAL  = int(os.getenv("RELOAD_INTERVAL", "300"))  # seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dns")

PH = "%s" if os.getenv("DATABASE_URL") else "?"


class BlocklistCache:
    def __init__(self):
        self._domains: set[str] = set()
        self._lock = threading.RLock()
        self.reload()

    def reload(self):
        try:
            rows = db.fetchall("SELECT domain FROM blocklist")
            domains: set[str] = set()
            for r in rows:
                d = r["domain"].lower().strip(".")
                domains.add(d)
                if not d.startswith("www."):
                    domains.add("www." + d)
            with self._lock:
                self._domains = domains
            log.info(f"Blocklist loaded: {len(domains):,} entries")
        except Exception as e:
            log.error(f"Blocklist reload failed: {e}")

    def is_blocked(self, domain: str) -> bool:
        domain = domain.lower().strip(".")
        with self._lock:
            if domain in self._domains:
                return True
            # match subdomains: sub.bad.com → bad.com
            parts = domain.split(".")
            for i in range(1, len(parts) - 1):
                if ".".join(parts[i:]) in self._domains:
                    return True
        return False


_cache: BlocklistCache | None = None


def get_cache() -> BlocklistCache:
    global _cache
    if _cache is None:
        _cache = BlocklistCache()
    return _cache


class FilteringResolver(BaseResolver):
    def resolve(self, request, handler):
        qname = str(request.q.qname).lower().strip(".")
        client_ip = getattr(handler, "client_address", ("unknown",))[0]

        cache   = get_cache()
        blocked = cache.is_blocked(qname)

        if LOG_QUERIES:
            try:
                db.execute(
                    f"INSERT INTO query_logs (domain, client_ip, blocked) VALUES ({PH},{PH},{PH})",
                    (qname, client_ip, blocked),
                )
            except Exception:
                pass

        if blocked:
            log.info(f"BLOCKED  {qname}  [{client_ip}]")
            reply = request.reply()
            reply.header.rcode = RCODE.NXDOMAIN
            return reply

        # Forward to upstream DNS
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.sendto(request.pack(), (UPSTREAM_DNS, 53))
            data, _ = sock.recvfrom(8192)
            sock.close()
            return DNSRecord.parse(data)
        except Exception as e:
            log.error(f"Upstream error for {qname}: {e}")
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL
            return reply


def _reload_loop():
    while True:
        time.sleep(RELOAD_INTERVAL)
        get_cache().reload()


if __name__ == "__main__":
    db.init_db()

    resolver = FilteringResolver()

    udp = DNSServer(resolver, port=DNS_PORT, address="0.0.0.0")
    tcp = DNSServer(resolver, port=DNS_PORT, address="0.0.0.0", tcp=True)
    udp.start_thread()
    tcp.start_thread()

    threading.Thread(target=_reload_loop, daemon=True).start()

    log.info(f"DNS server running on :{DNS_PORT} (UDP + TCP)")
    log.info(f"Upstream: {UPSTREAM_DNS}  |  Reload every {RELOAD_INTERVAL}s")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down…")
        udp.stop()
        tcp.stop()
