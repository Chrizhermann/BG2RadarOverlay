"""Dump every creature (CRE) a BG:EE / BG2:EE / EET install can spawn into a CSV.

Lab tool for designing encounter tiers: it answers "which ResRefs exist in *this* install,
what are they called, and how dangerous are they" without guessing - an EET install renames
part of BG1's creatures and mods overwrite plenty in override, so resrefs from a wiki are
not trustworthy. It is also the prototype for an in-overlay creature search.

Resolution order matches the engine: override/ wins over the BIFs listed in chitin.key.
Formats per IESDP (KEY V1, BIFF V1, CRE V1.0, TLK V1).

Usage:
    python cre_catalog.py "C:\\Games\\<install>" [--lang en_US] [--out creatures.csv]
"""

import argparse
import csv
import os
import struct
import sys

CRE_TYPE = 0x03F1

# EA.IDS: everything above EVILCUTOFF (199) is hostile to the party.
EA_EVILCUTOFF = 199


def read_key(game_dir):
    with open(os.path.join(game_dir, "chitin.key"), "rb") as f:
        data = f.read()
    if data[0:8] != b"KEY V1  ":
        raise ValueError("chitin.key is not KEY V1")
    bif_count, res_count, bif_off, res_off = struct.unpack_from("<4I", data, 8)

    bifs = []
    for i in range(bif_count):
        _length, name_off, name_len, _loc = struct.unpack_from("<IIHH", data, bif_off + i * 12)
        name = data[name_off:name_off + name_len].split(b"\0", 1)[0].decode("latin-1")
        bifs.append(name.replace("\\", os.sep).replace("/", os.sep))

    cres = {}
    for i in range(res_count):
        base = res_off + i * 14
        resref = data[base:base + 8].split(b"\0", 1)[0].decode("latin-1").upper()
        res_type, locator = struct.unpack_from("<HI", data, base + 8)
        if res_type == CRE_TYPE:
            cres[resref] = (bifs[locator >> 20], locator & 0x3FFF)
    return cres


class BifCache:
    def __init__(self, game_dir):
        self.game_dir = game_dir
        self.entries = {}

    def read(self, bif_name, index):
        if bif_name not in self.entries:
            path = os.path.join(self.game_dir, bif_name)
            with open(path, "rb") as f:
                data = f.read()
            if data[0:8] != b"BIFFV1  ":
                raise ValueError(f"{bif_name} is not an uncompressed BIFF V1")
            count, _tiles, off = struct.unpack_from("<3I", data, 8)
            table = {}
            for i in range(count):
                locator, data_off, size, _type = struct.unpack_from("<IIIH", data, off + i * 16)
                table[locator & 0x3FFF] = (data_off, size)
            self.entries[bif_name] = (data, table)
        data, table = self.entries[bif_name]
        data_off, size = table[index]
        return data[data_off:data_off + size]


def read_tlk(game_dir, lang):
    with open(os.path.join(game_dir, "lang", lang, "dialog.tlk"), "rb") as f:
        data = f.read()
    if data[0:8] != b"TLK V1  ":
        raise ValueError("dialog.tlk is not TLK V1")
    count, strings_off = struct.unpack_from("<II", data, 0x0A)

    def lookup(strref):
        if strref < 0 or strref >= count:
            return ""
        entry = 0x12 + strref * 0x1A
        offset, length = struct.unpack_from("<II", data, entry + 0x12)
        raw = data[strings_off + offset:strings_off + offset + length]
        return raw.decode("utf-8", errors="replace").strip()

    return lookup


def resref_field(cre, offset):
    return cre[offset:offset + 8].split(b"\0", 1)[0].decode("latin-1").upper()


def parse_cre(cre, tlk):
    if cre[0:8] != b"CRE V1.0":
        return None
    long_name, = struct.unpack_from("<i", cre, 0x08)
    xp_value, = struct.unpack_from("<I", cre, 0x14)
    max_hp, = struct.unpack_from("<h", cre, 0x26)
    levels = cre[0x234], cre[0x235], cre[0x236]
    ea, general, race, klass = cre[0x270], cre[0x271], cre[0x272], cre[0x273]
    death_var = cre[0x280:0x2A0].split(b"\0", 1)[0].decode("latin-1")
    # Plenty of CREs spell "no dialog" as the literal ResRef NONE rather than leaving it empty.
    dialog = resref_field(cre, 0x2CC)
    if dialog == "NONE":
        dialog = ""
    return {
        "name": tlk(long_name),
        "level": levels[0],
        "levels": "/".join(str(l) for l in levels if l),
        "xp_value": xp_value,
        "max_hp": max_hp,
        "ea": ea,
        "hostile": ea > EA_EVILCUTOFF,
        "general": general,
        "race": race,
        "class": klass,
        "death_var": death_var,
        "dialog": dialog,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("game_dir")
    parser.add_argument("--lang", default="en_US")
    parser.add_argument("--out", default="creatures.csv")
    args = parser.parse_args()

    tlk = read_tlk(args.game_dir, args.lang)
    key_cres = read_key(args.game_dir)
    bifs = BifCache(args.game_dir)

    override_dir = os.path.join(args.game_dir, "override")
    override_cres = {}
    with os.scandir(override_dir) as it:
        for entry in it:
            stem, ext = os.path.splitext(entry.name)
            if ext.lower() == ".cre" and len(stem) <= 8:
                override_cres[stem.upper()] = entry.path

    rows, failures = [], 0
    for resref in sorted(set(key_cres) | set(override_cres)):
        try:
            if resref in override_cres:
                with open(override_cres[resref], "rb") as f:
                    cre = f.read()
                source = "override"
            else:
                cre = bifs.read(*key_cres[resref])
                source = key_cres[resref][0]
            parsed = parse_cre(cre, tlk)
        except (OSError, ValueError, KeyError, struct.error, IndexError):
            parsed, failures = None, failures + 1
        if parsed is None:
            continue
        rows.append({"resref": resref, "source": source, **parsed})

    fields = ["resref", "name", "level", "levels", "xp_value", "max_hp", "hostile", "ea",
              "general", "race", "class", "death_var", "dialog", "source"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} creatures -> {args.out} ({failures} unreadable)", file=sys.stderr)


if __name__ == "__main__":
    main()
