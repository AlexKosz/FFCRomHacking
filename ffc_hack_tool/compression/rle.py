import struct
from io import BytesIO


COMPRESSION_HEADER = 3 << 4
COMPRESS_FLAG = 1 << 7
MAX_FLAG_DATA = COMPRESS_FLAG - 1


def decompress(data: bytes) -> bytes:
    reader = BytesIO(data)
    raw_header = struct.unpack("<I", reader.read(4))[0]
    if (raw_header & 0xF0) != COMPRESSION_HEADER:
        raise ValueError("Not RLE compressed data")

    target_size = raw_header >> 8
    output = bytearray()

    while len(output) < target_size:
        flag_raw = reader.read(1)[0]
        flag_type = flag_raw >> 7
        flag_data = flag_raw & MAX_FLAG_DATA

        if flag_type == 0:
            repeat = flag_data + 1
            output.extend(reader.read(repeat))
        else:
            repeat = flag_data + 3
            value = reader.read(1)[0]
            output.extend([value] * repeat)

    if len(output) != target_size:
        raise ValueError(f"RLE size mismatch: got {len(output)}, expected {target_size}")
    return bytes(output)


def compress(data: bytes) -> bytes:
    """NDS-style RLE compress (type 0x30)."""
    output = bytearray(struct.pack("<I", COMPRESSION_HEADER | (len(data) << 8)))
    pos = 0
    n = len(data)
    literal_start = pos

    def flush_literals(end: int) -> None:
        start = literal_start
        while start < end:
            count = min(end - start, MAX_FLAG_DATA + 1)
            output.append(count - 1)
            output.extend(data[start : start + count])
            start += count

    while pos < n:
        run = 1
        while pos + run < n and run < MAX_FLAG_DATA + 3 and data[pos + run] == data[pos]:
            run += 1
        if run >= 3:
            flush_literals(pos)
            output.append(COMPRESS_FLAG | (run - 3))
            output.append(data[pos])
            pos += run
            literal_start = pos
        else:
            pos += run
    flush_literals(pos)
    while len(output) % 4:
        output.append(0)
    return bytes(output)
