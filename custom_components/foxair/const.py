"""Constants reused from FoxAir_Control - do not duplicate pdf."""
DOMAIN = "foxair"
BLOCK_SHORT = {
    "H": "Basis/Hardware",
    "A": "Schutz/Grenzen",
    "F": "Fan",
    "D": "Abtauen",
    "E": "EVI/EEV",
    "C": "Compressor",
    "R": "Sollwerte",
    "T": "Diagnose/Live",
    "Z": "Zone",
    "G": "Legionellen",
    "P": "Pumpe",
    "SG": "SG Ready",
    "KG": "Timer",
    "ERR": "Fehler",
}
# Bulk blocks qty <=125 covering contiguous map derived from 1001-1358 + 2001-2149
POLL_BLOCKS = [
    (1001, 125, "B1 H/A/F/D"),
    (1126, 125, "B2 E/R"),
    (1251, 108, "B3 R/C/SG/P"),
    (2001, 125, "B4 T live"),
    (2126, 24, "B5 ERR tail"),
]
# Popular safe addrs enabled by default (R, T, P, SG, H subset, mode)
POPULAR_ADDRS = {
    1011,1012,1016,1018,1021,1030,1035,
    *range(1157, 1200),  # R block 42
    1197,1198,1199,1205,  # P subset actually 1197-1205 etc but range covers
    1334,8801,2133,2034,
    2044,2045,2046,2048,2049,2051,2053,2057,2062,2071,2072,2074,2077,2020,2069,2019,2065,2066,2067,
}
