from pathlib import Path
import struct
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "spptab-icon.ico"
PREVIEW = Path(tempfile.gettempdir()) / "spptab-icon-preview.png"

PALETTE = {
    "tile": (241, 246, 255, 255),
    "border": (220, 233, 255, 255),
    "blue1": (23, 96, 189, 255),
    "blue2": (75, 134, 223, 255),
    "blue3": (50, 136, 245, 255),
}


def in_round_rect(x, y, x0, y0, x1, y1, radius):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + radius), x1 - radius)
    cy = min(max(y, y0 + radius), y1 - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def pixel_color(x, y):
    if in_round_rect(x, y, 8, 8, 248, 248, 56):
        if not in_round_rect(x, y, 9.5, 9.5, 246.5, 246.5, 54.5):
            return PALETTE["border"]
        squares = (
            (44, 48, "blue1"),
            (104, 48, "blue2"),
            (164, 48, "blue3"),
            (104, 108, "blue1"),
            (104, 168, "blue3"),
        )
        for x0, y0, color in squares:
            if in_round_rect(x, y, x0, y0, x0 + 48, y0 + 48, 11):
                return PALETTE[color]
        return PALETTE["tile"]
    return (0, 0, 0, 0)


def png_bytes(size, supersample):
    rows = []
    for py in range(size):
        row = bytearray((0,))
        for px in range(size):
            totals = [0, 0, 0, 0]
            for sy in range(supersample):
                for sx in range(supersample):
                    x = (px + (sx + 0.5) / supersample) * 256 / size
                    y = (py + (sy + 0.5) / supersample) * 256 / size
                    for channel, value in enumerate(pixel_color(x, y)):
                        totals[channel] += value
            row.extend(round(value / supersample**2) for value in totals)
        rows.append(bytes(row))

    def chunk(kind, data):
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def main():
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    images = [(size, png_bytes(size, 8 if size <= 64 else 4)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = []
    blobs = []
    for size, image in images:
        dimension = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(image), offset))
        blobs.append(image)
        offset += len(image)
    OUTPUT.write_bytes(header + b"".join(entries) + b"".join(blobs))
    PREVIEW.write_bytes(dict(images)[256])
    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    print(f"Preview: {PREVIEW}")


if __name__ == "__main__":
    main()
