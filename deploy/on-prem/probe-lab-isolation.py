"""Run inside each lab guest through the hypervisor guest agent.

Synthetic TCP probes only; no business data or credentials. A timeout is
reported separately from a refusal: a closed port is NOT isolation evidence.
The operator must also verify target port availability from the host, and
correlate blocked probes with hypervisor firewall counters.
"""
import concurrent.futures
import argparse
import json
import socket
import subprocess


def probe(item):
    name, address, port = item
    try:
        with socket.create_connection((address, port), timeout=3):
            state = "connected"
    except TimeoutError:
        state = "timed_out"
    except ConnectionRefusedError:
        state = "refused_not_proof_of_isolation"
    except OSError as error:
        state = "error_errno_" + str(error.errno)
    return {"target": name, "address": address, "port": port, "result": state}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--management-ip", required=True)
    parser.add_argument("--office-gateway", required=True)
    args = parser.parse_args()
    addresses = subprocess.check_output(["hostname", "-I"], text=True).split()
    own = next(ip for ip in addresses if ip.startswith("10.77."))
    subnet = own.rsplit(".", 1)[0]
    probes = [
        ("public_https", "cloud-images.ubuntu.com", 443),
        ("host_bridge_ssh", subnet + ".1", 22),
        ("host_office_ssh", args.management_ip, 22),
        ("host_management", args.management_ip, 8006),
        ("office_gateway", args.office_gateway, 80),
        ("metadata", "169.254.169.254", 80),
    ]
    probes += [("other_guest_ssh", ip, 22)
               for ip in ["10.77.100.2", "10.77.101.2", "10.77.102.2"]
               if ip != own]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(probe, probes))
    print(json.dumps({"own_address": own, "probes": results,
                      "ipv6_routes": subprocess.check_output(
                          ["ip", "-6", "route"], text=True)}, indent=2))
    if not all(p["result"] == ("connected" if p["target"] == "public_https"
                               else "timed_out") for p in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
