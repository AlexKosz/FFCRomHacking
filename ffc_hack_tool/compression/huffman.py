import heapq
import struct
from io import BytesIO


COMPRESSION_HEADER = 2 << 4


def _drop_lowest_bit(value: int) -> int:
    return value & ~1


def decompress(data: bytes) -> bytes:
    """GBA/NDS BIOS-style Huffman decompress (4- or 8-bit symbols)."""
    reader = BytesIO(data)
    raw_header = struct.unpack("<I", reader.read(4))[0]
    if (raw_header & 0xF0) != COMPRESSION_HEADER:
        raise ValueError("Not Huffman compressed data")

    data_size_flag = raw_header & 0xF
    target_size = (raw_header >> 8) & 0xFFFFFF
    four_bit = data_size_flag == 4

    payload = data[4:]
    branch_node_count = payload[0]
    tree_length = 2 * branch_node_count + 1
    root_offset = 1
    bitstream_offset = root_offset + tree_length

    output = bytearray()
    current_offset = root_offset
    half_written = None

    while len(output) < target_size and bitstream_offset + 4 <= len(payload):
        chunk = struct.unpack_from("<I", payload, bitstream_offset)[0]
        bitstream_offset += 4

        for chunk_bit in range(31, -1, -1):
            node_data = payload[current_offset]
            current_bit = (chunk >> chunk_bit) & 1

            if current_bit == 0:
                child_offset = _drop_lowest_bit(current_offset) + 2 * ((node_data & 0x3F) + 1)
                is_data = (node_data >> 7) & 1
            else:
                child_offset = _drop_lowest_bit(current_offset) + 2 * ((node_data & 0x3F) + 1) + 1
                is_data = (node_data >> 6) & 1

            current_offset = child_offset

            if is_data:
                symbol = payload[current_offset]
                if four_bit:
                    if half_written is None:
                        half_written = symbol
                    else:
                        output.append((symbol << 4) | half_written)
                        half_written = None
                else:
                    output.append(symbol)
                current_offset = root_offset

            if len(output) >= target_size:
                break

    if len(output) != target_size:
        raise ValueError(f"Huffman size mismatch: got {len(output)}, expected {target_size}")
    return bytes(output)


def compress(data: bytes) -> bytes:
    """NDS-style Huffman compress with 4-bit symbols (type 0x24).

    The tree contains the nibbles that actually occur, padded to an even
    leaf count so the branch count is odd and the bitstream starts 4-byte
    aligned -- the same shape as every retail tree (observed branch counts
    are all odd). With at most 16 leaves the 6-bit child offsets can never
    overflow.
    """
    if not data:
        raise ValueError("cannot Huffman-compress empty data")

    freqs = [0] * 16
    for byte in data:
        freqs[byte & 0xF] += 1
        freqs[byte >> 4] += 1

    symbols = [s for s in range(16) if freqs[s]]
    if len(symbols) % 2 or len(symbols) < 2:
        # keep the leaf count even (odd branch count => aligned bitstream)
        symbols.append(next(s for s in range(16) if s not in symbols))

    # standard Huffman tree; entries are (freq, tiebreak, node) where a node
    # is either an int symbol (leaf) or a [left, right] pair
    heap: list[tuple[int, int, object]] = [(max(freqs[s], 1), s, s) for s in symbols]
    heapq.heapify(heap)
    tiebreak = 16
    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)
        f2, _, n2 = heapq.heappop(heap)
        heapq.heappush(heap, (f1 + f2, tiebreak, [n1, n2]))
        tiebreak += 1
    root = heap[0][2]

    # bit codes per symbol (path from root; left=0, right=1)
    codes: dict[int, tuple[int, int]] = {}  # symbol -> (bit count, value)

    def assign(node, depth, value):
        if isinstance(node, int):
            codes[node] = (depth, value)
        else:
            assign(node[0], depth + 1, value << 1)
            assign(node[1], depth + 1, (value << 1) | 1)

    assign(root, 0, 0)

    # serialize the tree breadth-first: root at offset 1, child pairs from 2.
    # node byte: bits 0-5 = pairs to skip to reach the children pair,
    # bit 7 / bit 6 = left / right child is a leaf.
    branch_count = len(symbols) - 1
    tree = bytearray(2 * branch_count + 2)
    tree[0] = branch_count
    queue: list[tuple[list, int]] = [(root, 1)]
    next_pair = 2
    while queue:
        node, pos = queue.pop(0)
        offset = (next_pair - (pos & ~1)) // 2 - 1
        if not 0 <= offset <= 0x3F:
            raise AssertionError("huffman tree offset overflow")  # impossible with 16 leaves
        flags = 0
        for side, child in enumerate(node):
            child_pos = next_pair + side
            if isinstance(child, int):
                tree[child_pos] = child
                flags |= 0x80 >> side  # bit7 = left leaf, bit6 = right leaf
            else:
                queue.append((child, child_pos))
        tree[pos] |= offset | flags
        next_pair += 2

    # bitstream: MSB-first within little-endian u32 words
    words: list[int] = []
    acc = 0
    acc_bits = 0
    for byte in data:
        for nibble in (byte & 0xF, byte >> 4):  # decoder emits low nibble first
            bits, value = codes[nibble]
            acc = (acc << bits) | value
            acc_bits += bits
            while acc_bits >= 32:
                acc_bits -= 32
                words.append((acc >> acc_bits) & 0xFFFFFFFF)
    if acc_bits:
        words.append((acc << (32 - acc_bits)) & 0xFFFFFFFF)

    header = struct.pack("<I", COMPRESSION_HEADER | 4 | (len(data) << 8))
    return header + bytes(tree) + struct.pack(f"<{len(words)}I", *words)
