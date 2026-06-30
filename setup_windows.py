"""
Configure Windows DNS to point to the content blocker server.
Must be run as Administrator.

Usage:
    python setup_windows.py --dns 1.2.3.4
    python setup_windows.py --revert
"""
import sys, subprocess, argparse, ctypes


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(cmd: str) -> bool:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip()}")
    return r.returncode == 0


def get_connected_interfaces() -> list[str]:
    r = subprocess.run(
        'netsh interface show interface',
        shell=True, capture_output=True, text=True
    )
    interfaces = []
    for line in r.stdout.splitlines():
        if "Connected" in line:
            # last field is the interface name (may contain spaces)
            parts = line.split()
            if len(parts) >= 4:
                interfaces.append(" ".join(parts[3:]))
    return interfaces


def set_dns(dns_ip: str):
    interfaces = get_connected_interfaces()
    if not interfaces:
        print("No connected interfaces found.")
        sys.exit(1)

    print(f"Setting DNS to {dns_ip} on {len(interfaces)} interface(s)…\n")
    for iface in interfaces:
        print(f"  → {iface}")
        run(f'netsh interface ip set dns name="{iface}" static {dns_ip}')

    # Block access to alternative DNS servers via Windows Firewall
    print("\nBlocking outbound DNS to other servers (port 53)…")
    run('netsh advfirewall firewall delete rule name="BlockAltDNS"')
    run(
        'netsh advfirewall firewall add rule '
        'name="BlockAltDNS" protocol=UDP dir=out remoteport=53 action=block'
    )
    run(
        'netsh advfirewall firewall add rule '
        'name="BlockAltDNS-TCP" protocol=TCP dir=out remoteport=53 action=block'
    )
    # Allow our DNS server specifically
    run(
        f'netsh advfirewall firewall add rule '
        f'name="AllowBlockerDNS" protocol=UDP dir=out remoteport=53 '
        f'remoteip={dns_ip} action=allow'
    )
    run(
        f'netsh advfirewall firewall add rule '
        f'name="AllowBlockerDNS-TCP" protocol=TCP dir=out remoteport=53 '
        f'remoteip={dns_ip} action=allow'
    )

    # Block common DoH endpoints so the browser can't bypass via HTTPS DNS
    DOH_IPS = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "149.112.112.112"]
    print("\nBlocking known DoH servers…")
    for ip in DOH_IPS:
        run(
            f'netsh advfirewall firewall add rule '
            f'name="BlockDoH-{ip}" protocol=TCP dir=out '
            f'remoteip={ip} remoteport=443 action=block'
        )

    print(f"\nDone. Your DNS is now protected by {dns_ip}.")
    print("To undo everything run: python setup_windows.py --revert")


def revert():
    interfaces = get_connected_interfaces()
    print(f"Reverting DNS to automatic (DHCP) on {len(interfaces)} interface(s)…\n")
    for iface in interfaces:
        print(f"  → {iface}")
        run(f'netsh interface ip set dns name="{iface}" dhcp')

    print("\nRemoving firewall rules…")
    for name in ["BlockAltDNS", "BlockAltDNS-TCP", "AllowBlockerDNS", "AllowBlockerDNS-TCP"]:
        run(f'netsh advfirewall firewall delete rule name="{name}"')

    DOH_IPS = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "149.112.112.112"]
    for ip in DOH_IPS:
        run(f'netsh advfirewall firewall delete rule name="BlockDoH-{ip}"')

    print("\nReverted. DNS is now controlled by your router/DHCP.")


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This script is for Windows only.")
        sys.exit(1)

    if not is_admin():
        print("Run this script as Administrator (right-click → Run as administrator).")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Configure DNS for content blocker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dns",    metavar="IP", help="IP of the content blocker DNS server")
    group.add_argument("--revert", action="store_true", help="Remove all rules and restore DHCP DNS")
    args = parser.parse_args()

    if args.dns:
        set_dns(args.dns)
    else:
        revert()
