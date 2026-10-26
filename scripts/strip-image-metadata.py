"""Remove identifying PNG/ICNS ancillary metadata without changing pixel data."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

PNG = b"\x89PNG\r\n\x1a\n"
PRIVATE = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def strip_png(data: bytes) -> bytes:
    if not data.startswith(PNG):
        raise ValueError("Expected a PNG image.")
    output = bytearray(PNG)
    offset = len(PNG)
    while offset < len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + length + 12
        if end > len(data):
            raise ValueError("Invalid PNG chunk length.")
        if data[offset + 4 : offset + 8] not in PRIVATE:
            output.extend(data[offset:end])
        offset = end
    return bytes(output)


def strip_icns(data: bytes) -> bytes:
    if data[:4] != b"icns" or struct.unpack_from(">I", data, 4)[0] != len(data):
        raise ValueError("Expected a valid ICNS image.")
    output = bytearray()
    offset = 8
    while offset < len(data):
        tag = data[offset : offset + 4]
        length = struct.unpack_from(">I", data, offset + 4)[0]
        if length < 8 or offset + length > len(data):
            raise ValueError("Invalid ICNS element length.")
        payload = data[offset + 8 : offset + length]
        if payload.startswith(PNG):
            payload = strip_png(payload)
        output.extend(tag + struct.pack(">I", len(payload) + 8) + payload)
        offset += length
    return b"icns" + struct.pack(">I", len(output) + 8) + output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", type=Path, nargs="+")
    for file in parser.parse_args().files:
        value = file.read_bytes()
        result = strip_png(value) if value.startswith(PNG) else strip_icns(value)
        file.write_bytes(result)


if __name__ == "__main__":
    main()
