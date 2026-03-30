#!/usr/bin/env python3

import argparse
import asyncio
import atexit
import os
import struct
import socket
import signal
import sys

# Global verbose flag
VERBOSE = False

def log(msg):
    """Print debug message if verbose mode is enabled."""
    if VERBOSE:
        print(f"[host-address-advertiser] {msg}", file=sys.stderr)
        sys.stderr.flush()

def get_default_gateway():
    """Read the default gateway IP from /proc/net/route."""
    try:
        with open("/proc/net/route", "r") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    gw_hex = fields[2]
                    return socket.inet_ntoa(struct.pack("<L", int(gw_hex, 16)))
    except Exception as e:
        log(f"Error reading routing table: {e}")
    return "0.0.0.0"

async def serve_fifo(fifo_path):
    """
    Loop that opens the FIFO for writing.
    Opening a FIFO for writing blocks until a reader opens it for reading.
    """
    while True:
        try:
            # We use run_in_executor because opening a FIFO for writing
            # is a blocking operation in the OS kernel.
            log("Waiting for a reader on the FIFO...")

            def open_and_write():
                # This line blocks until someone runs 'cat'
                with open(fifo_path, 'w') as f:
                    gw_ip = get_default_gateway()
                    log(f"Reader detected. Writing IP: {gw_ip}")
                    f.write(f"{gw_ip}\n")

            await asyncio.get_event_loop().run_in_executor(None, open_and_write)

        except asyncio.CancelledError:
            break
        except Exception as e:
            log(f"FIFO Error: {e}")
            await asyncio.sleep(1)

def daemonize(pidfile):
    """Standard double-fork daemonization."""
    try:
        if os.fork() > 0: sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #1 failed: {e}\n")
        sys.exit(1)

    os.setsid()
    os.umask(0)

    try:
        if os.fork() > 0: sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #2 failed: {e}\n")
        sys.exit(1)

    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, 'r') as si, open(os.devnull, 'a+') as so, open(os.devnull, 'a+') as se:
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

    with open(pidfile, 'w') as f:
        f.write(f"{os.getpid()}\n")

def cleanup(path, pidfile):
    log("Cleaning up files...")
    if os.path.exists(path):
        os.remove(path)
    if os.path.exists(pidfile):
        os.remove(pidfile)

def main():
    parser = argparse.ArgumentParser(description='Advertise default gateway via FIFO (Named Pipe)')
    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='Verbose logging'
    )
    parser.add_argument(
        '--no-daemon',
        action='store_true',
        help='Run in foreground'
    )
    parser.add_argument(
        '--socket',
        default='/run/host-address.txt',
        help='Path to the FIFO (named socket in your config)'
    )
    parser.add_argument(
        '--pidfile',
        default='/run/host-address.pid',
        help='Path to the PID file'
    )
    parser.add_argument(
        '--mode',
        default='0666',
        help='FIFO permissions (octal)'
    )
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    # Setup FIFO
    if os.path.exists(args.socket):
        os.remove(args.socket)
    os.mkfifo(args.socket)
    os.chmod(args.socket, int(args.mode, 8))

    # Register cleanup
    atexit.register(cleanup, args.socket, args.pidfile)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    if not args.no_daemon:
        daemonize(args.pidfile)
    else:
        with open(args.pidfile, 'w') as f:
            f.write(f"{os.getpid()}\n")

    log(f"Starting FIFO server on {args.socket}")
    try:
        asyncio.run(serve_fifo(args.socket))
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
