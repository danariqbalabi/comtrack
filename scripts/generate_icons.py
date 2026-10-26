"""Render the code-native radar mark to installable PNGs, using only stdlib."""
import math
import struct
import zlib
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'frontend' / 'public'
for size in (192, 512):
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            px, py = x * 512 / size, y * 512 / size
            distance = math.hypot(px - 256, py - 256)
            ink = any(abs(distance - radius) < 6.5 for radius in (142, 89, 35))
            ink |= 256 <= px <= 356 and 156 <= py <= 256 and abs(px + py - 512) < 9
            ink |= math.hypot(px - 327, py - 185) < 22
            pixels.extend((216, 244, 156) if ink else (25, 61, 53))
    def chunk(kind, body):
        return struct.pack('!I', len(body)) + kind + body + struct.pack('!I', zlib.crc32(kind + body))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', size, size, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
    (root / f'icon-{size}.png').write_bytes(png)
