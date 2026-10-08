#!/usr/bin/env python3
"""Step 3: work out the iShow USB protocol from a Wireshark capture.

Record the original iShow software talking to the box (see README), save the
capture, then run:

    python analyze_capture.py capture.pcapng
    python analyze_capture.py capture.pcapng --device 5 --export session.json

It understands Windows USBPcap captures and Linux usbmon captures, in either
.pcap or .pcapng format. It prints:
  * the control transfers (usually the start-up / configuration sequence),
  * the sizes of the bulk OUT packets (the point data),
  * a hex dump of the first packets,
  * a guess at how many bytes make up one laser point.
"""
import argparse
import collections
import json
import struct
import sys

LINKTYPE_USB_LINUX = 189  # usbmon, 48-byte header
LINKTYPE_USB_LINUX_MMAPPED = 220  # usbmon, 64-byte header
LINKTYPE_USBPCAP = 249  # Windows USBPcap

XFER_NAMES = {0: "iso", 1: "interrupt", 2: "control", 3: "bulk"}


# --------------------------------------------------------------------------
# Capture file readers -> (linktype, raw packet bytes)
# --------------------------------------------------------------------------
def read_packets(path):
    with open(path, "rb") as f:
        blob = f.read()
    magic = blob[:4]
    if magic == b"\x0a\x0d\x0d\x0a":
        yield from _read_pcapng(blob)
    elif magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        yield from _read_pcap(blob, "<")
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        yield from _read_pcap(blob, ">")
    else:
        sys.exit("Not a pcap/pcapng file")


def _read_pcap(blob, e):
    linktype = struct.unpack_from(e + "I", blob, 20)[0]
    pos = 24
    while pos + 16 <= len(blob):
        _, _, incl_len, _ = struct.unpack_from(e + "IIII", blob, pos)
        pos += 16
        yield linktype, blob[pos : pos + incl_len]
        pos += incl_len


def _read_pcapng(blob):
    pos = 0
    e = "<"
    linktypes = []
    while pos + 12 <= len(blob):
        if blob[pos : pos + 4] == b"\x0a\x0d\x0d\x0a":  # section header
            e = "<" if blob[pos + 8 : pos + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            linktypes = []
        btype, blen = struct.unpack_from(e + "II", blob, pos)
        if blen < 12:
            break
        body = blob[pos + 8 : pos + blen - 4]
        if btype == 1:  # interface description
            linktypes.append(struct.unpack_from(e + "H", body, 0)[0])
        elif btype == 6:  # enhanced packet
            iface, _, _, caplen, _ = struct.unpack_from(e + "IIIII", body, 0)
            yield linktypes[iface], body[20 : 20 + caplen]
        elif btype == 3:  # simple packet
            caplen = struct.unpack_from(e + "I", body, 0)[0]
            yield linktypes[0], body[4 : 4 + caplen]
        pos += blen


# --------------------------------------------------------------------------
# USB header decoders -> normalised transfer dicts
# --------------------------------------------------------------------------
def decode(linktype, pkt):
    """Return a dict for host->device data and device->host replies, else None."""
    if linktype == LINKTYPE_USBPCAP:
        return _decode_usbpcap(pkt)
    if linktype in (LINKTYPE_USB_LINUX, LINKTYPE_USB_LINUX_MMAPPED):
        return _decode_usbmon(pkt, 64 if linktype == LINKTYPE_USB_LINUX_MMAPPED else 48)
    return None


def _decode_usbpcap(pkt):
    if len(pkt) < 27:
        return None
    hlen, _irp, _status, _func, info, bus, dev, ep, xfer, dlen = struct.unpack_from(
        "<HQIHBHHBBI", pkt, 0
    )
    from_device = bool(info & 1)
    data = pkt[hlen : hlen + dlen]
    t = {"bus": bus, "device": dev, "endpoint": ep, "type": XFER_NAMES.get(xfer, "?")}
    if xfer == 2:  # control
        stage = pkt[27] if len(pkt) > 27 else 0
        if stage == 0 and not from_device:  # SETUP (+ OUT data on some versions)
            t.update(kind="setup", setup=data[:8], data=data[8:])
            return t
        if stage == 1 and not from_device:  # OUT data stage
            t.update(kind="control_data", data=data)
            return t
        if from_device and data:
            t.update(kind="in", data=data)
            return t
        return None
    if ep & 0x80:
        if from_device and data:
            t.update(kind="in", data=data)
            return t
        return None
    if not from_device and data:
        t.update(kind="out", data=data)
        return t
    return None


def _decode_usbmon(pkt, hdr_len):
    if len(pkt) < hdr_len:
        return None
    (_id, ev, xfer, epnum, devnum, busnum, flag_setup, _fd, _s, _us, _st, _length,
     len_cap, setup) = struct.unpack_from("<QBBBBHbbqiiII8s", pkt, 0)
    data = pkt[hdr_len : hdr_len + len_cap]
    ev = chr(ev)
    t = {"bus": busnum, "device": devnum, "endpoint": epnum, "type": XFER_NAMES.get(xfer, "?")}
    if xfer == 2 and ev == "S" and flag_setup == 0:
        t.update(kind="setup", setup=setup, data=data if not setup[0] & 0x80 else b"")
        return t
    if ev == "S" and not epnum & 0x80 and data:
        t.update(kind="out", data=data)
        return t
    if ev == "C" and epnum & 0x80 and data:
        t.update(kind="in", data=data)
        return t
    return None


def load_transfers(path):
    transfers = []
    for linktype, pkt in read_packets(path):
        t = decode(linktype, pkt)
        if t is None:
            continue
        # USBPcap may log the OUT data stage separately; glue it on.
        if t["kind"] == "control_data" and transfers and transfers[-1]["kind"] == "setup":
            transfers[-1]["data"] += t["data"]
            continue
        transfers.append(t)
    return transfers


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def hexdump(data, limit=64):
    s = data[:limit].hex(" ")
    return s + (" ..." if len(data) > limit else "")


def describe_setup(setup):
    bm, req, val, idx, ln = struct.unpack("<BBHHH", setup)
    direction = "IN " if bm & 0x80 else "OUT"
    kind = ("standard", "class", "vendor", "reserved")[(bm >> 5) & 3]
    return f"{direction} {kind:<8} bRequest=0x{req:02x} wValue=0x{val:04x} wIndex=0x{idx:04x} wLength={ln}"


def guess_stride(stream, max_stride=16):
    """Score each candidate record size: real point records change smoothly
    from one record to the next, so byte k of record n is close to byte k of
    record n+1. Returns [(stride, score)], lower score = more likely."""
    if len(stream) < 512:
        return []
    stream = stream[:65536]
    scores = []
    for stride in range(3, max_stride + 1):
        total = count = 0
        for k in range(stride):
            col = stream[k::stride]
            total += sum(abs(a - b) for a, b in zip(col, col[1:]))
            count += len(col) - 1
        scores.append((stride, total / max(count, 1)))
    return sorted(scores, key=lambda s: s[1])


def best_stride(scores):
    # Multiples of the true size score just as well, so take the smallest
    # stride whose score is within 15% of the best one.
    if not scores:
        return None
    best = scores[0][1]
    return min(s for s, v in scores if v <= best * 1.15 + 0.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--device", type=int, help="USB device address to analyse (default: busiest)")
    ap.add_argument("--packets", type=int, default=8, help="bulk packets to hex dump")
    ap.add_argument("--export", help="write the init sequence + sample frames to this JSON file")
    args = ap.parse_args()

    transfers = load_transfers(args.capture)
    if not transfers:
        sys.exit("No USB transfers found. Is this a USBPcap/usbmon capture?")

    traffic = collections.Counter()
    for t in transfers:
        if t["kind"] == "out":
            traffic[(t["bus"], t["device"])] += len(t["data"])
    print("Bytes sent to each device (bus, address):")
    for (bus, dev), n in traffic.most_common():
        print(f"  bus {bus} device {dev}: {n} bytes")

    if args.device is None:
        if not traffic:
            sys.exit("No bulk/interrupt OUT data found in the capture.")
        args.device = traffic.most_common(1)[0][0][1]
    print(f"\nAnalysing device {args.device}\n")
    mine = [t for t in transfers if t["device"] == args.device]

    # ---- control transfers ------------------------------------------------
    first_out = next((i for i, t in enumerate(mine) if t["kind"] == "out"), len(mine))
    print(f"== Control transfers ({sum(t['kind'] == 'setup' for t in mine)} total) ==")
    print("   (* = before the first point data, i.e. likely the start-up sequence)")
    shown = 0
    for i, t in enumerate(mine):
        if t["kind"] != "setup":
            continue
        if shown < 60:
            star = "*" if i < first_out else " "
            line = f" {star} {describe_setup(t['setup'])}"
            if t["data"]:
                line += f"  data: {hexdump(t['data'], 32)}"
            print(line)
            # show the reply to an IN request
            nxt = mine[i + 1] if i + 1 < len(mine) else None
            if t["setup"][0] & 0x80 and nxt and nxt["kind"] == "in" and nxt["endpoint"] & 0x7F == 0:
                print(f"       reply: {hexdump(nxt['data'], 32)}")
        shown += 1
    if shown > 60:
        print(f"   ... {shown - 60} more")

    # ---- bulk OUT ---------------------------------------------------------
    outs = [t for t in mine if t["kind"] == "out"]
    print(f"\n== OUT data packets: {len(outs)} ==")
    by_ep = collections.Counter(t["endpoint"] for t in outs)
    for ep, n in by_ep.items():
        print(f"  endpoint 0x{ep:02x}: {n} packets")
    sizes = collections.Counter(len(t["data"]) for t in outs)
    print("  most common sizes: " + ", ".join(f"{s} B x{n}" for s, n in sizes.most_common(8)))

    ins = [t for t in mine if t["kind"] == "in" and t["endpoint"] & 0x7F]
    if ins:
        print(f"\n== IN data packets (status from the box): {len(ins)} ==")
        for t in ins[:5]:
            print(f"  ep 0x{t['endpoint']:02x}: {hexdump(t['data'], 32)}")

    print(f"\n== First {args.packets} OUT packets ==")
    for t in outs[: args.packets]:
        print(f"  [{len(t['data']):5d} B] {hexdump(t['data'])}")

    # Look for a fixed header: bytes identical at the start of every packet.
    hdr = 0
    datas = [t["data"] for t in outs[:200]]
    if len(set(datas)) == 1:
        print("\n  All packets are identical: capture a moving pattern to learn more.")
    elif len(datas) > 3:
        while hdr < min(16, *map(len, datas)) and len({d[hdr] for d in datas}) == 1:
            hdr += 1
        if hdr:
            print(f"\n  Every packet starts with the same {hdr} byte(s): {datas[0][:hdr].hex(' ')}"
                  "  <- probably a command/header")
        print("  Bytes that change between packets of the same size often hold the point count.")

    stream = b"".join(t["data"][hdr:] for t in outs)
    scores = guess_stride(stream)
    if scores:
        stride = best_stride(scores)
        print("\n== Bytes-per-point guess (lower score = smoother) ==")
        for s, v in scores[:6]:
            print(f"  {s:2d} bytes/point  score {v:6.1f}")
        print(f"\n  Best guess: {stride} bytes per point. First 16 points of the biggest packet")
        print(f"  (after skipping {hdr} header bytes; adjust if a count field follows it):")
        big = max(outs, key=lambda t: len(t["data"]))["data"][hdr:]
        for i in range(min(16, len(big) // stride)):
            rec = big[i * stride : (i + 1) * stride]
            print("   " + " | ".join(rec[j : j + 2].hex() for j in range(0, stride, 2)))
        print("\n  Tip: capture while iShow shows a simple, slow pattern (a single colour")
        print("  dot that moves left->right). The column that ramps is X, the column that")
        print("  changes with colour is R/G/B. Put what you learn in protocol.json.")

    if args.export:
        init = [
            {"setup": t["setup"].hex(), "data": t["data"].hex()}
            for t in mine[:first_out]
            if t["kind"] == "setup" and (t["setup"][0] >> 5) & 3 != 0  # skip standard requests
        ]
        session = {
            "device": args.device,
            "init_control_transfers": init,
            "out_endpoints": sorted({f"0x{ep:02x}" for ep in by_ep}),
            "sample_packets": [t["data"].hex() for t in outs[:50]],
        }
        with open(args.export, "w") as f:
            json.dump(session, f, indent=2)
        print(f"\nWrote {args.export} ({len(init)} init transfers, {len(session['sample_packets'])} sample packets)")


if __name__ == "__main__":
    main()
