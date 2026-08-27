"""FoxAir constants - block names and poll layout identical to FoxAir_Control."""
DOMAIN = "foxair"
BLOCK_SHORT = {
    "H": "Base/Hardware",
    "A": "Protection/Limits",
    "F": "Fan",
    "D": "Defrost",
    "E": "EVI/EEV",
    "C": "Compressor",
    "R": "Setpoints",
    "T": "Diagnostics/Live",
    "Z": "Zone",
    "G": "Legionella",
    "P": "Pump",
    "SG": "SG Ready",
    "KG": "Timer",
    "ERR": "Fault",
}
# Bulk poll blocks (qty <=125) covering 1001-1358 and 2001-2149
POLL_BLOCKS = [
    (1001, 125, "B1 H/A/F/D"),
    (1126, 125, "B2 E/R"),
    (1251, 108, "B3 R/C/SG/P"),
    (2001, 125, "B4 T live"),
    (2126, 24, "B5 ERR tail"),
]
# Everyday controls stay visible, installer controls are Diagnostic and disabled by default
POPULAR_ADDRS = {
    1011,1012,1016,1018,1021,1030,1035,
    *range(1157, 1200),  # R
    1197,1198,1199,1205,
    1334,8801,2133,2034,
    2044,2045,2046,2048,2049,2051,2053,2057,2062,2071,2072,2074,2077,2020,2069,2019,2065,2066,2067,
}
