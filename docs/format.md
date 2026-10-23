# Save format

All multibyte numeric fields are little-endian unless marked opaque.

[← Back to the README](../README.md)

## File layout

```
+0x00  u32  version = 7
+0x04  u32  FNV-1a 32 of payload
+0x08  u32  payload byte length
+0x0c  u32  marker = 1 in all samples
+0x10       typed record stream
```

## Records

Each record begins with `u32 key | u8 type`. Candidate names hash as
`FNV-1a(UPPERCASE(name))`. Containers contain a LEB128 record count; strings and
blobs contain a LEB128 byte length. Parsers validate every read, length, count
and depth. Noncanonical encodings that cannot round-trip are flagged.

| Type | Value |
|---|---|
| `02` | u8 |
| `03` | u16 |
| `04` | Exactly four opaque bytes; never assume they are a little-endian integer |
| `06` | Container with LEB128 child count |
| `08` | **Signed** i32; `ffffffff` reads as -1 |
| `0a` | IEEE-754 float32 |
| `0c` | Byte/boolean |
| `0d` | UTF-8 string bytes |
| `0e` | Opaque binary bytes |

## World-state blobs

World-state blobs (see [World state](coverage.md#world-state)) nest further
record streams:

```
group  := u32 version (3) | u32 count | count × entry
entry  := 16-byte entity GUID | u32 kind | u32 length | <length bytes of records>
```

The record streams use the same format and key space as the outer save. The 8
bytes once reported as a container "signature" (`b13668df f82e7044`) are the
first half of the archstone entity's GUID. Every sample blob and all 166 baseline
files the game ships in `misc/cachedsavedata/` decode and rebuild
byte-identically. Entries that are not a record stream (an unknown type `0x10`,
header-only containers) keep their raw bytes. Kinds 7, 8 and 13 are preserved
without interpretation.

## In the browser

The browser's binary model indexes fields by hash and path, caches serialized
snapshots by revision, and serializes into a preallocated typed buffer. Hidden
views are not rendered. Binary previews read only the first few bytes rather than
hex-encoding whole blobs on every refresh.
