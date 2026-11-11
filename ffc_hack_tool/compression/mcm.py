import struct
from io import BytesIO

from . import huffman, lzss, rle

MCM_MAGIC = 0x004D434D
COMPRESSION = {
    0: None,
    1: rle.decompress,
    2: lzss.decompress,
    3: huffman.decompress,
}
ENCODERS = {
    0: None,
    1: rle.compress,
    2: lzss.compress,
    3: huffman.compress,
}


def decompress_mcm(data: bytes) -> bytes:
    reader = BytesIO(data)
    magic = struct.unpack("<I", reader.read(4))[0]
    if magic != MCM_MAGIC:
        raise ValueError("Not an MCM file")

    decompressed_size, max_chunk, chunk_count = struct.unpack("<III", reader.read(12))
    comp1, comp2 = struct.unpack("<BB", reader.read(2))
    reader.read(2)

    offsets = list(struct.unpack(f"<{chunk_count + 1}I", reader.read(4 * (chunk_count + 1))))
    output = bytearray()

    for i in range(chunk_count):
        start, end = offsets[i], offsets[i + 1]
        reader.seek(start)
        chunk = reader.read(end - start)

        stream = chunk
        fn1 = COMPRESSION.get(comp1)
        if fn1:
            stream = fn1(stream)
        fn2 = COMPRESSION.get(comp2)
        if fn2:
            stream = fn2(stream)
        output.extend(stream)

    if len(output) != decompressed_size:
        raise ValueError(f"MCM size mismatch: {len(output)} != {decompressed_size}")
    return bytes(output)


def mcm_scheme(data: bytes) -> tuple[int, int, int]:
    """(comp1, comp2, max_chunk) of an MCM blob without decompressing it."""
    if struct.unpack_from("<I", data, 0)[0] != MCM_MAGIC:
        raise ValueError("Not an MCM file")
    max_chunk = struct.unpack_from("<I", data, 8)[0]
    comp1, comp2 = struct.unpack_from("<BB", data, 16)
    return comp1, comp2, max_chunk


def _encode_chunk(chunk: bytes, comp1: int, comp2: int) -> bytes:
    """Stored chunk bytes for one payload chunk. Decompression applies comp1
    then comp2, so encoding applies comp2 first and comp1 outermost.

    When an LZSS stage is involved its parse strategy is chosen by measuring
    the FINAL blob, not the LZSS stream: the following Huffman stage reacts
    strongly to how repetitive the LZSS tokens are, and the parse that
    minimises the LZSS stream is reliably the wrong one (see lzss.STRATEGIES
    -- on etc/attack_defs it cost 684 bytes across six chunks, versus 24 for
    plain greedy+lazy). Trying each parse and keeping the smallest result is
    what lets an edited file compress back into its retail ROM slot."""
    def build(strategy: str | None) -> bytes:
        stream = chunk
        for comp in (comp2, comp1):
            encoder = ENCODERS.get(comp)
            if not encoder:
                continue
            if comp == 2 and strategy is not None:
                stream = encoder(stream, strategy)
            else:
                stream = encoder(stream)
        return stream

    if 2 not in (comp1, comp2):
        return build(None)
    return min((build(s) for s in lzss.STRATEGIES), key=len)


def _assemble(chunks: list[bytes], total_size: int, max_chunk: int, comp1: int, comp2: int) -> bytes:
    header_size = 20 + (len(chunks) + 1) * 4
    offsets: list[int] = []
    cursor = header_size
    for chunk in chunks:
        offsets.append(cursor)
        cursor += len(chunk)
    offsets.append(cursor)

    out = bytearray()
    out.extend(struct.pack("<I", MCM_MAGIC))
    out.extend(struct.pack("<III", total_size, max_chunk, len(chunks)))
    out.extend(struct.pack("<BB", comp1, comp2))
    out.extend(b"\x00\x00")
    for offset in offsets:
        out.extend(struct.pack("<I", offset))
    for chunk in chunks:
        out.extend(chunk)
    return bytes(out)


def compress_mcm(data: bytes, comp1: int = 2, comp2: int = 0, max_chunk: int = 0x2000) -> bytes:
    """Build an MCM blob with the given compression scheme, self-verified."""
    if not data:
        raise ValueError("cannot pack an empty payload")
    chunks = [
        _encode_chunk(data[i : i + max_chunk], comp1, comp2)
        for i in range(0, len(data), max_chunk)
    ]
    blob = _assemble(chunks, len(data), max_chunk, comp1, comp2)
    if decompress_mcm(blob) != data:
        raise RuntimeError("MCM self-check failed")
    return blob


def compress_mcm_uncompressed(data: bytes, max_chunk: int = 0x2000) -> bytes:
    """Build an uncompressed MCM blob (valid for in-ROM replacement)."""
    return compress_mcm(data, 0, 0, max_chunk)


# Every scheme below appears in the retail FFC ROM, so the game's chunk
# decoder handles any of them (tried in this order when a repack has to
# shrink to fit a fixed slot).
FALLBACK_SCHEMES = [(3, 2), (3, 0), (2, 0), (1, 0), (0, 0)]


def repack_mcm_like(original: bytes, payload: bytes, fit: int | None = None) -> bytes:
    """Re-encode `payload` into an MCM blob using the *original* blob's
    compression scheme and chunk size. Chunks whose decompressed bytes are
    unchanged reuse the original stored bytes verbatim, so a small edit
    produces a nearly identical file. If `fit` is given and the result is
    larger, other retail schemes are tried and the smallest blob wins.
    Self-verified."""
    comp1, comp2, max_chunk = mcm_scheme(original)
    chunk_count = struct.unpack_from("<I", original, 12)[0]
    offsets = struct.unpack_from(f"<{chunk_count + 1}I", original, 20)
    old_payload = decompress_mcm(original)

    chunks: list[bytes] = []
    for i in range(0, max(1, -(-len(payload) // max_chunk))):
        lo = i * max_chunk
        new_slice = payload[lo : lo + max_chunk]
        if i < chunk_count and old_payload[lo : lo + max_chunk] == new_slice:
            chunks.append(original[offsets[i] : offsets[i + 1]])
        else:
            chunks.append(_encode_chunk(new_slice, comp1, comp2))

    blob = _assemble(chunks, len(payload), max_chunk, comp1, comp2)
    if fit is not None and len(blob) > fit:
        for scheme in FALLBACK_SCHEMES:
            if scheme == (comp1, comp2):
                continue
            candidate = compress_mcm(payload, *scheme, max_chunk=max_chunk)
            if len(candidate) < len(blob):
                blob = candidate
    if decompress_mcm(blob) != payload:
        raise RuntimeError("MCM repack self-check failed")
    return blob
