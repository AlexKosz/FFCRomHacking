import struct
from io import BytesIO

from .mcm import compress_mcm_uncompressed, decompress_mcm, repack_mcm_like

MAR_MAGIC = 0x0052414D


def decompress_mar(data: bytes) -> list[bytes]:
    reader = BytesIO(data)
    magic = struct.unpack("<I", reader.read(4))[0]
    if magic != MAR_MAGIC:
        raise ValueError("Not a MAR archive")

    count = struct.unpack("<I", reader.read(4))[0]
    entries = [struct.unpack("<II", reader.read(8)) for _ in range(count)]

    files: list[bytes] = []
    for index, (offset, _) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < count else len(data)
        reader.seek(offset)
        raw = reader.read(end - offset)
        files.append(decompress_mcm(raw))
    return files


def compress_mar(files: list[bytes]) -> bytes:
    """Pack decompressed payloads into a MAR archive (uncompressed MCM entries)."""
    if not files:
        raise ValueError("MAR archive requires at least one file")

    mcm_blobs = [compress_mcm_uncompressed(blob) for blob in files]
    header_size = 8 + len(files) * 8
    offset = header_size
    indices: list[tuple[int, int]] = []
    for blob, source in zip(mcm_blobs, files):
        indices.append((offset, len(source)))
        offset += len(blob)

    out = bytearray()
    out.extend(struct.pack("<I", MAR_MAGIC))
    out.extend(struct.pack("<I", len(files)))
    for file_offset, decompressed_size in indices:
        out.extend(struct.pack("<II", file_offset, decompressed_size))
    for blob in mcm_blobs:
        out.extend(blob)
    return bytes(out)


def repack_mar_like(original: bytes, files: list[bytes], fit: int | None = None) -> bytes:
    """Pack new payloads into a MAR archive, giving each entry the same MCM
    compression scheme its counterpart used in `original`. Unchanged chunks
    keep their original stored bytes, so edits produce minimal diffs and
    near-original file sizes. `fit` (a total-file byte budget, e.g. the
    original FAT slot) lets single-entry archives fall back to a
    better-compressing retail scheme rather than outgrow their slot."""
    if struct.unpack_from("<I", original, 0)[0] != MAR_MAGIC:
        raise ValueError("Not a MAR archive")
    count = struct.unpack_from("<I", original, 4)[0]
    if count != len(files):
        raise ValueError(f"MAR entry count mismatch: original has {count}, got {len(files)}")
    entries = [struct.unpack_from("<II", original, 8 + i * 8) for i in range(count)]

    header_size = 8 + count * 8
    mcm_fit = fit - header_size if fit is not None and count == 1 else None
    mcm_blobs: list[bytes] = []
    for index, (offset, _) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < count else len(original)
        mcm_blobs.append(repack_mcm_like(original[offset:end], files[index], fit=mcm_fit))

    header_size = 8 + count * 8
    out = bytearray()
    out.extend(struct.pack("<II", MAR_MAGIC, count))
    cursor = header_size
    for blob, payload in zip(mcm_blobs, files):
        out.extend(struct.pack("<II", cursor, len(payload)))
        cursor += len(blob)
    for blob in mcm_blobs:
        out.extend(blob)
    return bytes(out)
