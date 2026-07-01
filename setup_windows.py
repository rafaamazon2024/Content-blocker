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
        # "Connected" (EN) or "Conectado"/"Ligado" (PT-BR)
        if any(word in line for word in ("Connected", "Conectado", "Ligado")):
            parts = line.split()
            if len(parts) >= 4:
                interfaces.append(" ".join(parts[3:]))
    return interfaces


def set_dns(dns_ip: str):
    interfaces = get_connected_interfaces()
    if not interfaces:
        # Fallback: apply to the two most common interface names
        print("Interfaces não detectadas automaticamente — aplicando em Wi-Fi e Ethernet...")
        interfaces = ["Wi-Fi", "Ethernet", "Local Area Connection"]

    print(f"Configurando DNS para {dns_ip} em {len(interfaces)} interface(s)…\n")
    for iface in interfaces:
        print(f"  → {iface}")
        run(f'netsh interface ip set dns name="{iface}" static {dns_ip}')
        # Adiciona o servidor como DNS secundário para evitar queda de internet
        run(f'netsh interface ip add dns name="{iface}" {dns_ip} index=1')

    # Desabilita DNS over HTTPS do Windows para evitar bypass pelo sistema
    print("\nDesabilitando DNS over HTTPS do Windows…")
    run('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Dnscache\\Parameters" '
        '/v EnableAutoDoh /t REG_DWORD /d 0 /f')

    print(f"\nPronto! DNS protegido por {dns_ip}.")
    print("Para reverter: python setup_windows.py --revert")


def revert():
    interfaces = get_connected_interfaces()
    print(f"Reverting DNS to automatic (DHCP) on {len(interfaces)} interface(s)…\n")
    for iface in interfaces:
        print(f"  → {iface}")
        run(f'netsh interface ip set dns name="{iface}" dhcp')

    # Restaura DNS over HTTPS
    run('reg delete "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Dnscache\\Parameters" '
        '/v EnableAutoDoh /f')

    print("\nRevertido. DNS controlado pelo roteador/DHCP.")


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
