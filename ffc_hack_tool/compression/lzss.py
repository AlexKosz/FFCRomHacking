import struct
from io import BytesIO


COMPRESS_HEADER = 0x10


def decompress(data: bytes) -> bytes:
    reader = BytesIO(data)
    raw_header = struct.unpack("<I", reader.read(4))[0]
    if (raw_header & 0xF0) != COMPRESS_HEADER:
        raise ValueError("Not LZSS compressed data")

    target_size = raw_header >> 8
    output = bytearray()

    while len(output) < target_size:
        flag_data = reader.read(1)
        if not flag_data:
            break
        flags = flag_data[0]

        for bit in range(7, -1, -1):
            if len(output) >= target_size:
                break
            if ((flags >> bit) & 1) == 0:
                output.append(reader.read(1)[0])
            else:
                header = struct.unpack("<H", reader.read(2))[0]
                copy_count = ((header >> 4) & 0xF) + 3
                displacement = (((header & 0xF) << 8) | (header >> 8)) + 1
                start = len(output) - displacement
                for i in range(copy_count):
                    output.append(output[start + (i % displacement)])

    if len(output) != target_size:
        raise ValueError(f"LZSS size mismatch: got {len(output)}, expected {target_size}")
    return bytes(output)


# Match-finder tuning: how many hash-chain candidates to try per position.
# 64 keeps ratios within ~1% of an exhaustive search at a fraction of the
# cost; combined with the optimal parse below, patched files compress back
# into (or within a few hundred bytes of) their original ROM slots.
_MAX_CANDIDATES = 64
_MAX_MATCH = 18  # 4-bit count field + 3
_WINDOW = 0x1000


def _best_matches(data: bytes) -> list[tuple[int, int]]:
    """(max match length, displacement) per position, via 3-byte hash chains."""
    n = len(data)
    best = [(0, 0)] * n
    chains: dict[bytes, list[int]] = {}
    for pos in range(n):
        if pos + 3 > n:
            break
        key = data[pos : pos + 3]
        candidates = chains.get(key)
        if candidates:
            limit = min(n - pos, _MAX_MATCH)
            best_len = 0
            best_disp = 0
            for cand in reversed(candidates[-_MAX_CANDIDATES:]):
                disp = pos - cand
                if disp > _WINDOW:
                    break  # candidates are ascending; older ones only get farther
                length = 3  # hash key guarantees the first 3 bytes
                while length < limit and data[cand + (length % disp)] == data[pos + length]:
                    length += 1
                if length > best_len:
                    best_len, best_disp = length, disp
                    if length == limit:
                        break
            best[pos] = (best_len, best_disp)
            chains[key].append(pos)
        else:
            chains[key] = [pos]
    return best


def _emit(data: bytes, take: list[int], matches: list[tuple[int, int]]) -> bytes:
    n = len(data)
    output = bytearray(struct.pack("<I", COMPRESS_HEADER | (n << 8)))
    pos = 0
    while pos < n:
        flag_pos = len(output)
        output.append(0)
        flags = 0
        for bit in range(7, -1, -1):
            if pos >= n:
                break
            length = take[pos]
            if length:
                dm1 = matches[pos][1] - 1
                token = ((length - 3) << 4) | (dm1 >> 8) | ((dm1 & 0xFF) << 8)
                output.extend(struct.pack("<H", token))
                flags |= 1 << bit
                pos += length
            else:
                output.append(data[pos])
                pos += 1
        output[flag_pos] = flags
    while len(output) % 4:
        output.append(0)
    return bytes(output)


def _parse_optimal(data: bytes, matches: list[tuple[int, int]]) -> list[int]:
    """Backwards DP minimising the exact LZSS bit count (9 per literal, 17
    per match). Smallest possible LZSS stream -- but see STRATEGIES."""
    n = len(data)
    cost = [0] * (n + 1)
    take = [0] * n
    for pos in range(n - 1, -1, -1):
        best_cost = 9 + cost[pos + 1]
        best_take = 0
        max_len, _ = matches[pos]
        if max_len >= 3:
            for length in range(3, max_len + 1):
                c = 17 + cost[pos + length]
                if c < best_cost:
                    best_cost, best_take = c, length
        cost[pos] = best_cost
        take[pos] = best_take
    return take


def _parse_greedy(data: bytes, matches: list[tuple[int, int]], lazy: bool) -> list[int]:
    """Take the longest match at each position; with `lazy`, skip it when the
    next position offers a longer one."""
    n = len(data)
    take = [0] * n
    pos = 0
    while pos < n:
        length = matches[pos][0]
        if length >= 3 and not (lazy and pos + 1 < n and matches[pos + 1][0] > length):
            take[pos] = length
            pos += length
        else:
            take[pos] = 0
            pos += 1
    return take


# The LZSS stream is normally Huffman-coded afterwards (MCM scheme 3/2), and
# the two stages interact: the parse that produces the SMALLEST LZSS stream
# is not the one that produces the smallest file. Optimal parsing spreads its
# matches over many distinct displacements, which is high-entropy and costs
# the Huffman stage far more than the parse saves -- on etc/attack_defs it
# came out 684 bytes worse than retail across six chunks, enough to push the
# file out of its ROM slot, while plain greedy+lazy matching lands 24 bytes
# off retail (and actually beats it on two chunks). So the caller tries every
# strategy and keeps whichever gives the smallest FINAL blob; see
# mcm._encode_chunk.
STRATEGIES = ("greedy_lazy", "greedy", "optimal")


def compress(data: bytes, strategy: str = "greedy_lazy") -> bytes:
    """NDS-style LZSS (type 0x10). `strategy` picks the parse -- see
    STRATEGIES for why the default is not the optimal parse."""
    if len(data) > (1 << 24) - 1:
        raise ValueError("LZSS input too large")
    matches = _best_matches(data)
    if strategy == "optimal":
        take = _parse_optimal(data, matches)
    elif strategy == "greedy":
        take = _parse_greedy(data, matches, lazy=False)
    elif strategy == "greedy_lazy":
        take = _parse_greedy(data, matches, lazy=True)
    else:
        raise ValueError(f"unknown LZSS parse strategy: {strategy!r}")
    return _emit(data, take, matches)
