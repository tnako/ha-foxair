"""FoxAir heat pump Modbus model — generated from foxair_phnix_registers.json."""
from modbus_connection.model import Component, gauge, integer

class FoxAir(Component):
    """FoxAir/PHNIX heat pump — all holding registers."""
    max_span = 45  # EW11 gateway drops >60, 65 fails, 45 stable (tested live EW11-host:8899)
    max_gap = 8   # merge nearby registers
    register_space = "holding"

    reg_1011 = integer(1011, signed=True, writable=True)  #  DIGI1
    reg_1012 = integer(1012, signed=True, writable=True)  #  MODE_0_4
    reg_1013 = gauge(1013, 0.1, writable=True)  #  TEMP1 Wassertanktemperatur (vom Zentralregler bei H37-1)
    reg_1014 = integer(1014, signed=True, writable=True)  #  DIGI1
    reg_1015 = gauge(1015, 1.0, writable=True)  #  RAW
    reg_1016 = integer(1016, signed=True, writable=True)  #  DIGI1
    reg_1017 = gauge(1017, 1.0, writable=True)  #  RAW
    reg_1018 = integer(1018, signed=True, writable=True)  # H01 DIGI1
    reg_1019 = integer(1019, signed=True, writable=True)  # H33 DIGI1
    reg_1020 = integer(1020, signed=True, writable=True)  # H34 DIGI1
    reg_1021 = integer(1021, signed=True, writable=True)  # H05 DIGI1
    reg_1022 = gauge(1022, 1.0, writable=True)  #  RAW
    reg_1023 = integer(1023, signed=True, writable=True)  # H07 DIGI1
    reg_1024 = integer(1024, signed=True, writable=True)  # H10 DIGI1
    reg_1025 = gauge(1025, 1.0, writable=True)  # H38 RAW
    reg_1026 = gauge(1026, 1.0, writable=True)  # H39 RAW
    reg_1027 = integer(1027, signed=True, writable=True)  # H27 DIGI1
    reg_1028 = integer(1028, signed=True, writable=True)  # H28 DIGI1
    reg_1029 = integer(1029, signed=True, writable=True)  # H21 DIGI1
    reg_1030 = integer(1030, signed=True, writable=True)  # H22 DIGI1
    reg_1031 = gauge(1031, 0.5, writable=True, unit="°C")  # A35 TEMP05 Electric Heater Off Temp Diff / E-Heizer Ausschalt-Temperaturdifferenz
    reg_1032 = integer(1032, signed=True, writable=True)  # H18 DIGI1
    reg_1033 = integer(1033, signed=True, writable=True)  # H20 DIGI1
    reg_1034 = integer(1034, signed=True, writable=True)  # H29 DIGI1
    reg_1035 = integer(1035, signed=True, writable=True)  # H25 DIGI1
    reg_1036 = gauge(1036, 1.0, writable=True)  # H30 RAW
    reg_1037 = gauge(1037, 0.1, writable=True)  # A03 TEMP1 Abschalttemperatur Umgebung
    reg_1038 = gauge(1038, 0.1, writable=True)  # A04 TEMP1 Frostschutztemperatur
    reg_1039 = gauge(1039, 0.1, writable=True)  # A05 TEMP1 Frostschutztemperaturdifferenz
    reg_1040 = gauge(1040, 0.1, writable=True)  # A06 TEMP1 Max. Abgastemperatur
    reg_1041 = integer(1041, signed=True, writable=True)  # H31 DIGI1
    reg_1042 = integer(1042, signed=True, writable=True)  # A11 DIGI1
    reg_1043 = gauge(1043, 0.1, writable=True)  # A23 TEMP1 Min. Auslasswassertemperatur schutz
    reg_1044 = gauge(1044, 0.1, writable=True)  # A24 TEMP1 Übermäßige Temperaturdifferenz zwischen Einlass- und Auslasswasser
    reg_1045 = integer(1045, signed=True, writable=True)  # H32 DIGI1
    reg_1046 = integer(1046, signed=True, writable=True)  # H37 DIGI1
    reg_1047 = integer(1047, signed=True, writable=True)  # D26 DIGI1
    reg_1048 = gauge(1048, 1.0, writable=True)  #  RAW
    reg_1049 = gauge(1049, 0.1, writable=True)  # A31 TEMP1 Electric-Heater-On AT Grenzwert / Temperaturparameter (ASM)
    reg_1050 = gauge(1050, 1.0, writable=True, unit="min")  # A32 MINUTES
    reg_1051 = gauge(1051, 0.1, writable=True)  # A30 TEMP1 Min. Umgebungstemperatur im Kühlmodus
    reg_1052 = integer(1052, signed=True, writable=True)  # A21 DIGI1
    reg_1053 = gauge(1053, 0.1, writable=True)  # A22 TEMP1 Min. Frostschutztemperatur
    reg_1054 = integer(1054, signed=True, writable=True)  # A26 DIGI1
    reg_1055 = gauge(1055, 0.1, writable=True)  # A25 TEMP1 Minimale Verdampfungstemperatur der Kühlung
    reg_1056 = gauge(1056, 0.1, writable=True)  # A27 TEMP1 Temperaturdifferenz der Begrenzungsfrequenz
    reg_1057 = gauge(1057, 0.1, writable=True)  # A28 TEMP1 Temperaturdifferenz zwischen Auslass- und WW-Temperatur
    reg_1058 = integer(1058, signed=True, writable=True)  # A29 DIGI1
    reg_1059 = integer(1059, signed=True, writable=True)  # F01 DIGI1
    reg_1060 = gauge(1060, 0.1, writable=True)  # F02 TEMP1 Verdampfertemperatur für maximale Lüfterdrehzahl im Kühlbetrieb
    reg_1061 = gauge(1061, 1.0, writable=True, unit="rpm")  # F27 RAW
    reg_1062 = gauge(1062, 0.1, writable=True)  # F03 TEMP1 Verdampfertemperatur für minimale Lüfterdrehzahl im Kühlbetrieb
    reg_1063 = gauge(1063, 0.1, writable=True, unit="°C")  # A33 TEMP1 E-Heizer Einschalt-Temperaturdifferenz
    reg_1064 = gauge(1064, 1.0, writable=True, unit="min")  # A34 MINUTES
    reg_1065 = gauge(1065, 1.0, writable=True)  #  RAW
    reg_1066 = gauge(1066, 0.1, writable=True)  # F05 TEMP1 Verdampfertemperatur für maximale Lüfterdrehzahl im Heizbetrieb
    reg_1067 = gauge(1067, 1.0, writable=True)  #  RAW
    reg_1068 = gauge(1068, 0.1, writable=True)  # F06 TEMP1 Verdampfertemperatur für minimale Lüfterdrehzahl im Heizbetrieb
    reg_1069 = integer(1069, signed=True, writable=True)  # Z01 DIGI1
    reg_1070 = gauge(1070, 0.1, writable=True)  # Z02 TEMP1 Zone 1 Raumtemperatur-Sollwert
    reg_1071 = gauge(1071, 0.1, writable=True, unit="K")  # Z03 TEMP1 Zone 1 Raumtemperatur-Differenz zum Start
    reg_1072 = gauge(1072, 0.1, writable=True)  # Z04 TEMP1 Zone 2 Raumtemperatur-Sollwert
    reg_1073 = gauge(1073, 0.1, writable=True, unit="K")  # Z05 TEMP1 Zone 2 Raumtemperatur-Differenz zum Start
    reg_1074 = integer(1074, signed=True, writable=True)  # F10 DIGI1
    reg_1075 = gauge(1075, 0.1, writable=True)  # Z06 TEMP1 Zone 1 Heizungs-Auslasswasser-Sollwert
    reg_1076 = gauge(1076, 0.1, writable=True)  # Z07 TEMP1 Zone 2 Mischwasser-Auslasswasser-Sollwert
    reg_1077 = integer(1077, signed=True, writable=True)  # Z17 DIGI1
    reg_1078 = gauge(1078, 1.0, writable=True)  #  RAW
    reg_1079 = gauge(1079, 1.0, writable=True)  #  RAW
    reg_1080 = gauge(1080, 1.0, writable=True, unit="%")  # Z08 PERCENT
    reg_1081 = integer(1081, signed=True, writable=True)  # F18 DIGI1
    reg_1082 = gauge(1082, 1.0, writable=True, unit="s")  # Z09 SECONDS
    reg_1083 = integer(1083, signed=True, writable=True)  # F19 DIGI1
    reg_1084 = gauge(1084, 1.0, writable=True, unit="s")  # Z10 SECONDS
    reg_1085 = gauge(1085, 0.1, writable=True)  # Z11 DIGI5 Mischventil Regelung P-Anteil (PID)
    reg_1086 = integer(1086, signed=True, writable=True)  # F21 DIGI1
    reg_1087 = integer(1087, signed=True, writable=True)  # F22 DIGI1
    reg_1088 = gauge(1088, 0.1, writable=True)  # Z12 DIGI5 Mischventil Regelung I-Anteil (PID)
    reg_1089 = integer(1089, signed=True, writable=True)  # F23 DIGI1
    reg_1090 = gauge(1090, 1.0, writable=True, unit="min")  # Z13 MINUTES
    reg_1101 = gauge(1101, 0.1, writable=True)  # F28 TEMP1 Verdampfertemperatur des Einzel-/Doppellüfterschalters im Kühlbetrieb
    reg_1102 = gauge(1102, 0.1, writable=True)  # F29 TEMP1 Verdampfertemperatur des Einzellüfterstopps im Kühlbetrieb
    reg_1103 = gauge(1103, 1.0, writable=True, unit="rpm")  # F25 RPM
    reg_1104 = gauge(1104, 1.0, writable=True, unit="rpm")  # F26 RPM
    reg_1105 = gauge(1105, 0.1, writable=True)  # D01 TEMP1 Umgebungstemperatur des Start-Abtauens
    reg_1106 = gauge(1106, 1.0, writable=True, unit="min")  # D02 MINUTES
    reg_1107 = gauge(1107, 1.0, writable=True, unit="min")  # D03 MINUTES
    reg_1108 = gauge(1108, 0.1, writable=True)  # D04 TEMP1 Heißgastemperaturkorrektur für den Abtauzyklus
    reg_1109 = gauge(1109, 0.1, writable=True)  # D05-1 DIGI5 Abtau-Saugsdruck 1
    reg_1110 = gauge(1110, 0.1, writable=True)  # D05-2 DIGI5 Abtau-Saugsdruck 2
    reg_1111 = integer(1111, signed=True, writable=True)  # D06 DIGI1
    reg_1112 = gauge(1112, 0.1, writable=True)  # D07 TEMP1 Umgebungstemperatur des Start-Gleitabtauens
    reg_1113 = gauge(1113, 0.1, writable=True)  # D08 TEMP1 Saugsungstemperatur des Start-Gleitabtauens
    reg_1114 = gauge(1114, 0.1, writable=True)  # D09 TEMP1 Umgebungstemperatur des Stopp-Gleitabtauens
    reg_1115 = gauge(1115, 0.1, writable=True)  # D10 TEMP1 Saugsungstemperatur des Stopp-Gleitabtauens
    reg_1116 = gauge(1116, 0.1, writable=True, unit="°C")  # D11 TEMP1 Min. Einlasswassertemperatur des Abtauens
    reg_1117 = gauge(1117, 0.1, writable=True, unit="bar")  # D12 BAR_X10 Saugsdruck des erzwungenen Abtauens
    reg_1118 = gauge(1118, 1.0, writable=True, unit="min")  # D13 MINUTES
    reg_1119 = gauge(1119, 0.01, writable=True)  # D14 DIGI19 Lüftermotorleistungsverhältnis zur Verlängerung des Abtauzyklus
    reg_1120 = gauge(1120, 0.01, writable=True)  # D15 DIGI19 Lüftermotorleistungsverhältnis zum Eintritt in das erzwungene Abtauen
    reg_1121 = gauge(1121, 1.0, writable=True, unit="W")  # D16 WATT
    reg_1122 = gauge(1122, 0.1, writable=True)  # D17 TEMP1 Verdampfertemperatur des Abtauausgangs
    reg_1123 = gauge(1123, 0.1, writable=True)  # D18 TEMP1 Verteilerrohrtemperatur des Abtauausgangs
    reg_1124 = gauge(1124, 1.0, writable=True, unit="min")  # D19 MINUTES
    reg_1125 = gauge(1125, 1.0, writable=True, unit="Hz")  # D20 HZ
    reg_1126 = integer(1126, signed=True, writable=True)  # D21 DIGI1
    reg_1127 = gauge(1127, 0.1, writable=True, unit="m³/h")  # D22 FLOW_M3H_X10 Wasserdurchfluss beim Abtauen
    reg_1128 = gauge(1128, 1.0, writable=True, unit="min")  # D23 MINUTES
    reg_1129 = integer(1129, signed=True, writable=True)  # D24 DIGI1
    reg_1130 = gauge(1130, 0.1, writable=True)  # D25 TEMP1 Max. Einlasswassertemperaturabfall beim Abtauen
    reg_1131 = integer(1131, signed=True, writable=True)  # E01 DIGI1
    reg_1132 = gauge(1132, 0.1, writable=True, unit="°C")  # E02 TEMP1 Ziel-Überhitzung Heizen
    reg_1133 = gauge(1133, 1.0, writable=True, unit="N")  # E03 STEPS_N
    reg_1134 = gauge(1134, 1.0, writable=True, unit="%")  # Z14 PERCENT
    reg_1135 = gauge(1135, 0.1, writable=True)  # Z15 TEMP1 Zone 2 maximale Wasser-Solltemperatur
    reg_1136 = gauge(1136, 0.1, writable=True)  # Z16 DIGI5 Mischventil Regel-I (DIGI5 laut ASM-Kommentar) (ASM)
    reg_1137 = gauge(1137, 1.0, writable=True, unit="N")  # E07 STEPS_N
    reg_1138 = gauge(1138, 1.0, writable=True, unit="N")  # E08 STEPS_N
    reg_1139 = integer(1139, signed=True, writable=True)  # E09 DIGI1
    reg_1140 = gauge(1140, 1.0, writable=True, unit="N")  # E10 STEPS_N
    reg_1141 = gauge(1141, 1.0, writable=True)  #  RAW
    reg_1142 = gauge(1142, 1.0, writable=True, unit="N")  # E03-2 STEPS_N
    reg_1143 = gauge(1143, 0.1, writable=True, unit="°C")  # E13 TEMP1 EVI-EEV Ziel-Überhitzungsgrad
    reg_1144 = gauge(1144, 1.0, writable=True, unit="N")  # E14 STEPS_N
    reg_1145 = gauge(1145, 0.1, writable=True)  # E15 TEMP1 Temperatur-/Hystereseparameter (ASM)
    reg_1146 = gauge(1146, 0.1, writable=True)  # E16 TEMP1 Temperatur-/Hystereseparameter (ASM)
    reg_1147 = gauge(1147, 1.0, writable=True, unit="N")  # E17 STEPS_N
    reg_1148 = gauge(1148, 0.1, writable=True, unit="°C")  # E18 TEMP1 Ziel-Überhitzung Kühlen
    reg_1149 = gauge(1149, 1.0, writable=True, unit="%")  # E19 PERCENT
    reg_1150 = gauge(1150, 1.0, writable=True)  #  RAW
    reg_1151 = gauge(1151, 1.0, writable=True)  #  RAW
    reg_1152 = gauge(1152, 0.1, writable=True, unit="°C")  # G01 TEMP1 Desinfektionswassertemperatur
    reg_1153 = gauge(1153, 1.0, writable=True, unit="min")  # G02 MINUTES
    reg_1154 = gauge(1154, 1.0, writable=True, unit="h")  # G03 HOURS
    reg_1155 = gauge(1155, 1.0, writable=True, unit="days")  # G04 DAYS
    reg_1156 = integer(1156, signed=True, writable=True)  # G05 DIGI1
    reg_1157 = gauge(1157, 0.1, writable=True, unit="°C")  # R01 TEMP1 Warmwasser-Solltemperatur
    reg_1158 = gauge(1158, 0.1, writable=True, unit="°C")  # R02 TEMP1 Heizungssolltemperatur
    reg_1159 = gauge(1159, 0.1, writable=True, unit="°C")  # R03 TEMP1 Kühlsolltemperatur
    reg_1160 = gauge(1160, 0.1, writable=True, unit="°C")  # R04 TEMP1 Heizung Einschalt-Rücklaufdifferenz
    reg_1161 = gauge(1161, 0.1, writable=True, unit="°C")  # R05 TEMP1 Heizung Standby-/Abschalt-Temperaturdifferenz
    reg_1162 = gauge(1162, 0.1, writable=True, unit="°C")  # R08 TEMP1 Min. Kühlsolltemperatur
    reg_1163 = gauge(1163, 0.1, writable=True, unit="°C")  # R09 TEMP1 Max. Kühlsolltemperatur
    reg_1164 = gauge(1164, 0.1, writable=True, unit="°C")  # R10 TEMP1 Min. Heizungssolltemperatur
    reg_1165 = gauge(1165, 0.1, writable=True, unit="°C")  # R11 TEMP1 Max. Heizungssolltemperatur
    reg_1166 = gauge(1166, 0.1, writable=True, unit="°C")  # R15 TEMP1 Rückkehrdifferenz zum Verlassen des Hochtemperatur-Modus
    reg_1167 = gauge(1167, 0.1, writable=True, unit="°C")  # R29 TEMP1 Niedrige AT für Wassertemperaturbegrenzung EIN
    reg_1168 = gauge(1168, 0.1, writable=True, unit="°C")  # R30 TEMP1 Niedrige AT für Wassertemperaturbegrenzung AUS
    reg_1169 = gauge(1169, 0.1, writable=True, unit="°C")  # R31 TEMP1 Max. Auslasswassertemperaturbegrenzung bei niedriger AT
    reg_1170 = gauge(1170, 0.1, writable=True, unit="°C")  # R32 TEMP1 Hohe AT für Wassertemperaturbegrenzung EIN
    reg_1171 = gauge(1171, 0.1, writable=True, unit="°C")  # R33 TEMP1 Hohe AT für Wassertemperaturbegrenzung AUS
    reg_1172 = gauge(1172, 0.1, writable=True, unit="°C")  # R34 TEMP1 Max. Auslasswassertemperaturbegrenzung bei hoher AT
    reg_1173 = integer(1173, signed=True, writable=True)  # R35 DIGI1
    reg_1174 = gauge(1174, 0.1, writable=True, unit="°C")  # R06 TEMP1 Kühlung Einschalt-Rücklaufdifferenz
    reg_1175 = gauge(1175, 0.1, writable=True, unit="°C")  # R07 TEMP1 Kühlung Standby-/Abschalt-Temperaturdifferenz
    reg_1176 = gauge(1176, 0.1, writable=True, unit="°C")  # R36 TEMP1 Min. WW-Solltemperatur
    reg_1177 = gauge(1177, 0.1, writable=True, unit="°C")  # R37 TEMP1 Max. WW-Solltemperatur
    reg_1178 = gauge(1178, 0.1, writable=True, unit="°C")  # R12 TEMP1 Temperatur-/Hystereseparameter R12
    reg_1179 = gauge(1179, 0.1, writable=True, unit="°C")  # R13 TEMP1 Temperatur-/Hystereseparameter R13
    reg_1180 = gauge(1180, 0.1, writable=True, unit="°C")  # R14 TEMP1 Temperatur-/Hystereseparameter R14
    reg_1192 = gauge(1192, 0.1, writable=True, unit="°C")  # R39 TEMP1 AT für Auto-Start Heizmodus
    reg_1193 = gauge(1193, 0.1, writable=True)  # R40 TEMP1 Temperaturparameter, Celsius-Grenze 60 °C (ASM V1.3)
    reg_1194 = gauge(1194, 0.1, writable=True)  # R41 TEMP1 Temperaturparameter, Celsius-Grenze 60 °C (ASM V1.3)
    reg_1195 = gauge(1195, 0.1, writable=True, unit="°C")  # R16 TEMP1 WW-Tank Einschalt-Rücklaufdifferenz
    reg_1196 = gauge(1196, 0.1, writable=True, unit="°C")  # R17 TEMP1 WW-Tank Standby-Temperaturdifferenz
    reg_1197 = integer(1197, signed=True, writable=True)  # P01 DIGI1
    reg_1198 = gauge(1198, 1.0, writable=True, unit="min")  # P02 MINUTES
    reg_1199 = gauge(1199, 1.0, writable=True, unit="min")  # P03 MINUTES
    reg_1200 = gauge(1200, 1.0, writable=True, unit="N")  # E03-1 STEPS_N
    reg_1201 = integer(1201, signed=True, writable=True)  # P05 DIGI1
    reg_1202 = integer(1202, signed=True, writable=True)  # P06 DIGI1
    reg_1203 = gauge(1203, 1.0, writable=True, unit="days")  # P09 DAYS
    reg_1204 = gauge(1204, 1.0, writable=True, unit="W")  # P08 RAW
    reg_1205 = gauge(1205, 1.0, writable=True, unit="%")  # P10 PERCENT
    reg_1206 = gauge(1206, 1.0, writable=True, unit="N")  # E03-3 STEPS_N
    reg_1207 = gauge(1207, 1.0, writable=True, unit="N")  # E03-4 STEPS_N
    reg_1208 = gauge(1208, 1.0, writable=True, unit="N")  # E03-5 STEPS_N
    reg_1209 = gauge(1209, 1.0, writable=True, unit="N")  # E07-1 STEPS_N
    reg_1210 = gauge(1210, 1.0, writable=True, unit="N")  # E07-2 STEPS_N
    reg_1211 = gauge(1211, 1.0, writable=True, unit="N")  # E07-3 STEPS_N
    reg_1212 = gauge(1212, 0.1, writable=True, unit="K")  #  TEMP1 Offset Inlet Temperatur
    reg_1213 = gauge(1213, 0.1, writable=True, unit="K")  #  TEMP1 Offset outlet Temperatur
    reg_1214 = gauge(1214, 0.1, writable=True, unit="K")  #  TEMP1 Offset WW Temperatur
    reg_1215 = gauge(1215, 1.0, writable=True, unit="N")  # E07-4 STEPS_N
    reg_1216 = gauge(1216, 1.0, writable=True, unit="N")  # E07-5 STEPS_N
    reg_1217 = gauge(1217, 1.0, writable=True, unit="Hz")  # C11 HZ
    reg_1218 = gauge(1218, 1.0, writable=True, unit="Hz")  # C01 HZ
    reg_1219 = gauge(1219, 1.0, writable=True, unit="Hz")  # C02 HZ
    reg_1220 = gauge(1220, 1.0, writable=True, unit="Hz")  # C03 HZ
    reg_1221 = integer(1221, signed=True, writable=True)  # C04 DIGI1
    reg_1222 = gauge(1222, 1.0, writable=True, unit="Hz")  # C05 HZ
    reg_1223 = integer(1223, signed=True, writable=True)  # C06 DIGI1
    reg_1224 = gauge(1224, 1.0, writable=True, unit="Hz")  # C07 HZ
    reg_1225 = gauge(1225, 1.0, writable=True, unit="Hz")  # C08 HZ
    reg_1226 = gauge(1226, 1.0, writable=True, unit="Hz")  # C09 HZ
    reg_1227 = gauge(1227, 1.0, writable=True, unit="Hz")  # C10 HZ
    reg_1228 = gauge(1228, 0.1, writable=True, unit="°C")  # R42 TEMP1 Max. Auslasswassertemperatur im Heizbetrieb
    reg_1229 = gauge(1229, 0.1, writable=True, unit="°C")  # R43 TEMP1 Max. Zielwassertemperaturbegrenzung bei niedriger AT im Heizbetrieb
    reg_1230 = gauge(1230, 0.1, writable=True, unit="°C")  # R44 TEMP1 Max. Zielwassertemperaturbegrenzung bei hoher AT im Heizbetrieb
    reg_1231 = gauge(1231, 0.1, writable=True, unit="°C")  # R45 TEMP1 AT zum Starten des elektrischen Heizers ohne Verzögerung
    reg_1232 = gauge(1232, 0.1, writable=True, unit="°C")  # R46 TEMP1 Temp.-Differenz zwischen max. WW-Solltemp. und max. Auslasstemp.
    reg_1233 = gauge(1233, 0.1, writable=True, unit="°C")  # R60 TEMP1 AT zum Start der Frequenzbegrenzung im Kühlbetrieb
    reg_1234 = gauge(1234, 0.1, writable=True)  #  DIGI5 AT-Kompensation Slope / Steigung
    reg_1235 = gauge(1235, 0.1, writable=True, unit="°C")  #  TEMP1 AT-Kompensation Offset / Versatz
    reg_1236 = integer(1236, signed=True, writable=True)  # H36 DIGI1
    reg_1237 = gauge(1237, 0.1, writable=True, unit="°C")  # R61 TEMP1 AT zum Stoppen der Frequenzbegrenzung im Kühlbetrieb
    reg_1238 = gauge(1238, 0.1, writable=True, unit="°C")  # R62 TEMP1 Max. Wärmepumpen-Auslasswassertemperatur
    reg_1239 = gauge(1239, 0.1, writable=True, unit="°C")  # R70 TEMP1 Ziel-Raumtemperatur
    reg_1240 = gauge(1240, 0.1, writable=True, unit="°C")  # R71 TEMP1 Raumtemperaturdifferenz zum Einschalten im Heizbetrieb
    reg_1241 = gauge(1241, 0.1, writable=True, unit="°C")  # R72 TEMP1 Raumtemperaturdifferenz für Standby im Heizbetrieb
    reg_1242 = gauge(1242, 0.1, writable=True, unit="°C")  # R73 TEMP1 Raumtemperaturdifferenz zum Einschalten im Kühlbetrieb
    reg_1243 = gauge(1243, 0.1, writable=True, unit="°C")  # R74 TEMP1 Raumtemperaturdifferenz für Standby im Kühlbetrieb
    reg_1244 = integer(1244, signed=True, writable=True)  #  DIGI1
    reg_1245 = integer(1245, signed=True, writable=True)  #  DIGI1
    reg_1246 = integer(1246, signed=True, writable=True)  #  DIGI1
    reg_1247 = integer(1247, signed=True, writable=True)  #  DIGI1
    reg_1248 = integer(1248, signed=True, writable=True)  #  DIGI1
    reg_1249 = integer(1249, signed=True, writable=True)  #  DIGI1
    reg_1250 = integer(1250, signed=True, writable=True)  #  DIGI1
    reg_1251 = integer(1251, signed=True, writable=True)  #  DIGI1
    reg_1252 = integer(1252, signed=True, writable=True)  #  DIGI1
    reg_1253 = integer(1253, signed=True, writable=True)  #  DIGI1
    reg_1254 = integer(1254, signed=True, writable=True)  #  DIGI1
    reg_1255 = gauge(1255, 1.0, writable=True)  #  RAW
    reg_1256 = integer(1256, signed=False, writable=True)  # KG1 TIME_HHMM WP Ein/Aus Timer 1 Startzeit
    reg_1257 = integer(1257, signed=False, writable=True)  # KG2 TIME_HHMM WP Ein/Aus Timer 1 Stopzeit
    reg_1258 = integer(1258, signed=False, writable=True)  # KG3 TIME_HHMM WP Ein/Aus Timer 2 Startzeit
    reg_1259 = integer(1259, signed=False, writable=True)  # KG4 TIME_HHMM WP Ein/Aus Timer 2 Stopzeit
    reg_1260 = integer(1260, signed=False, writable=True)  # KG5 TIME_HHMM WP Ein/Aus Timer 3 Startzeit
    reg_1261 = integer(1261, signed=False, writable=True)  # KG6 TIME_HHMM WP Ein/Aus Timer 3 Stopzeit
    reg_1262 = integer(1262, signed=False, writable=True)  # KG7 TIME_HHMM WP Ein/Aus Timer 4 Startzeit
    reg_1263 = integer(1263, signed=False, writable=True)  # KG8 TIME_HHMM WP Ein/Aus Timer 4 Stopzeit
    reg_1264 = integer(1264, signed=False, writable=True)  # KG9 TIME_HHMM WP Ein/Aus Timer 5 Startzeit
    reg_1265 = integer(1265, signed=False, writable=True)  # KG10 TIME_HHMM WP Ein/Aus Timer 5 Stopzeit
    reg_1266 = integer(1266, signed=False, writable=True)  # KG11 TIME_HHMM WP Ein/Aus Timer 6 Startzeit
    reg_1267 = integer(1267, signed=False, writable=True)  # KG12 TIME_HHMM WP Ein/Aus Timer 6 Stopzeit
    reg_1268 = integer(1268, signed=True, writable=True)  # KG13-KG28 TIMER_BITPAIR
    reg_1269 = integer(1269, signed=True, writable=True)  # KG29-KG44 TIMER_BITPAIR
    reg_1270 = integer(1270, signed=True, writable=True)  # KG45-KG60 TIMER_BITPAIR
    reg_1281 = integer(1281, signed=False, writable=True)  #  TIME_HHMM Timer 1 Einschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1282 = integer(1282, signed=False, writable=True)  #  TIME_HHMM Timer 1 Ausschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1283 = gauge(1283, 0.1, writable=True)  #  TEMP1 Timer 1 WW-Zieltemperatur (ASM)
    reg_1284 = gauge(1284, 0.1, writable=True)  #  TEMP1 Timer 1 HZ-Zieltemperatur (ASM)
    reg_1285 = gauge(1285, 0.1, writable=True)  #  TEMP1 Timer 1 Kühlen-Zieltemperatur (ASM)
    reg_1286 = integer(1286, signed=True, writable=True)  #  TIMER_MODE
    reg_1287 = gauge(1287, 0.1, writable=True)  #  POWER_KW_X10 Timer 1 max. Leistung (ASM)
    reg_1288 = integer(1288, signed=False, writable=True)  #  TIME_HHMM Timer 2 Einschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1289 = integer(1289, signed=False, writable=True)  #  TIME_HHMM Timer 2 Ausschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1290 = gauge(1290, 0.1, writable=True)  #  TEMP1 Timer 2 WW-Zieltemperatur (ASM)
    reg_1291 = gauge(1291, 0.1, writable=True)  #  TEMP1 Timer 2 HZ-Zieltemperatur (ASM)
    reg_1292 = gauge(1292, 0.1, writable=True)  #  TEMP1 Timer 2 Kühlen-Zieltemperatur (ASM)
    reg_1293 = integer(1293, signed=True, writable=True)  #  TIMER_MODE
    reg_1294 = gauge(1294, 0.1, writable=True)  #  POWER_KW_X10 Timer 2 max. Leistung (ASM)
    reg_1295 = integer(1295, signed=False, writable=True)  #  TIME_HHMM Timer 3 Einschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1296 = integer(1296, signed=False, writable=True)  #  TIME_HHMM Timer 3 Ausschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1297 = gauge(1297, 0.1, writable=True)  #  TEMP1 Timer 3 WW-Zieltemperatur (ASM)
    reg_1298 = gauge(1298, 0.1, writable=True)  #  TEMP1 Timer 3 HZ-Zieltemperatur (ASM)
    reg_1299 = gauge(1299, 0.1, writable=True)  #  TEMP1 Timer 3 Kühlen-Zieltemperatur (ASM)
    reg_1300 = integer(1300, signed=True, writable=True)  #  TIMER_MODE
    reg_1301 = gauge(1301, 0.1, writable=True)  #  POWER_KW_X10 Timer 3 max. Leistung (ASM)
    reg_1302 = integer(1302, signed=False, writable=True)  #  TIME_HHMM Timer 4 Einschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1303 = integer(1303, signed=False, writable=True)  #  TIME_HHMM Timer 4 Ausschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1304 = gauge(1304, 0.1, writable=True)  #  TEMP1 Timer 4 WW-Zieltemperatur (ASM)
    reg_1305 = gauge(1305, 0.1, writable=True)  #  TEMP1 Timer 4 HZ-Zieltemperatur (ASM)
    reg_1306 = gauge(1306, 0.1, writable=True)  #  TEMP1 Timer 4 Kühlen-Zieltemperatur (ASM)
    reg_1307 = integer(1307, signed=True, writable=True)  #  TIMER_MODE
    reg_1308 = gauge(1308, 0.1, writable=True)  #  POWER_KW_X10 Timer 4 max. Leistung (ASM)
    reg_1309 = integer(1309, signed=False, writable=True)  #  TIME_HHMM Timer 5 Einschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1310 = integer(1310, signed=False, writable=True)  #  TIME_HHMM Timer 5 Ausschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1311 = gauge(1311, 0.1, writable=True)  #  TEMP1 Timer 5 WW-Zieltemperatur (ASM)
    reg_1312 = gauge(1312, 0.1, writable=True)  #  TEMP1 Timer 5 HZ-Zieltemperatur (ASM)
    reg_1313 = gauge(1313, 0.1, writable=True)  #  TEMP1 Timer 5 Kühlen-Zieltemperatur (ASM)
    reg_1314 = integer(1314, signed=True, writable=True)  #  TIMER_MODE
    reg_1315 = gauge(1315, 0.1, writable=True)  #  POWER_KW_X10 Timer 5 max. Leistung (ASM)
    reg_1316 = integer(1316, signed=False, writable=True)  #  TIME_HHMM Timer 6 Einschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1317 = integer(1317, signed=False, writable=True)  #  TIME_HHMM Timer 6 Ausschaltzeit (HH:MM aus High-/Low-Byte) (ASM)
    reg_1318 = gauge(1318, 0.1, writable=True)  #  TEMP1 Timer 6 WW-Zieltemperatur (ASM)
    reg_1319 = gauge(1319, 0.1, writable=True)  #  TEMP1 Timer 6 HZ-Zieltemperatur (ASM)
    reg_1320 = gauge(1320, 0.1, writable=True)  #  TEMP1 Timer 6 Kühlen-Zieltemperatur (ASM)
    reg_1321 = integer(1321, signed=True, writable=True)  #  TIMER_MODE
    reg_1322 = gauge(1322, 0.1, writable=True)  #  POWER_KW_X10 Timer 6 max. Leistung (ASM)
    reg_1323 = integer(1323, signed=True, writable=True)  #  TIMER_BITPAIR
    reg_1324 = integer(1324, signed=True, writable=True)  #  TIMER_BITPAIR
    reg_1325 = integer(1325, signed=True, writable=True)  #  TIMER_BITPAIR
    reg_1326 = gauge(1326, 1.0, writable=True)  #  RAW
    reg_1327 = gauge(1327, 1.0, writable=True)  #  RAW
    reg_1328 = gauge(1328, 1.0, writable=True)  #  RAW
    reg_1329 = gauge(1329, 1.0, writable=True)  #  RAW
    reg_1330 = gauge(1330, 1.0, writable=True)  #  RAW
    reg_1331 = gauge(1331, 1.0, writable=True)  #  RAW
    reg_1332 = gauge(1332, 1.0, writable=True)  #  RAW
    reg_1333 = gauge(1333, 1.0, writable=True)  #  RAW
    reg_1334 = integer(1334, signed=True, writable=True)  # SG01 SG_MODE
    reg_1335 = gauge(1335, 1.0, writable=True, unit="min")  # SG02 RAW
    reg_1336 = gauge(1336, 0.1, writable=True, unit="kW")  # SG03 POWER_KW_X10 SG Mode 2 Leistung / wenig PV
    reg_1337 = gauge(1337, 0.1, writable=True, unit="kW")  # SG04 POWER_KW_X10 SG Mode 3 Leistung / mittel PV
    reg_1338 = gauge(1338, 0.1, writable=True)  # SG05 TEMP1 SG Mode 4 WW-Zieltemperatur-Anhebung
    reg_1339 = gauge(1339, 0.1, writable=True)  # SG06 TEMP1 SG Mode 4 HZ-Zieltemperatur-Anhebung
    reg_1340 = gauge(1340, 0.1, writable=True)  # SG07 TEMP1 SG Mode 4 Kühlen-Zieltemperatur-Anhebung
    reg_1341 = integer(1341, signed=True, writable=True)  # SG08 DIGI1
    reg_1342 = gauge(1342, 0.1, writable=True, unit="bar")  # A38 BAR_X10 Niederdruck-Grenzwert für Frequenzbegrenzung
    reg_1343 = gauge(1343, 0.5, writable=True, unit="A")  # A39 AMP_X2 Maximaler Stromwert
    reg_1344 = gauge(1344, 0.01, writable=False, unit="m³/h")  # A40 FLOW_M3H_X100 Nenn-Wasserdurchfluss
    reg_1345 = integer(1345, signed=True, writable=True)  # H40 DIGI1
    reg_1346 = gauge(1346, 1.0, writable=False)  # H41 RAW
    reg_1347 = gauge(1347, 1.0, writable=True, unit="Hz")  # C12 HZ
    reg_1348 = gauge(1348, 1.0, writable=True)  # C13 RAW
    reg_1349 = gauge(1349, 1.0, writable=True)  # C14 RAW
    reg_1350 = gauge(1350, 1.0, writable=True)  # C15 RAW
    reg_1351 = gauge(1351, 1.0, writable=True)  # E20 RAW
    reg_1352 = gauge(1352, 1.0, writable=True)  # E21 RAW
    reg_1353 = gauge(1353, 1.0, writable=True)  #  RAW
    reg_1354 = gauge(1354, 1.0, writable=True)  #  RAW
    reg_1355 = gauge(1355, 1.0, writable=True)  #  RAW
    reg_1356 = gauge(1356, 0.1, writable=True, unit="°C")  # H42 TEMP1 H42 Einschalt-AT Gehaeusewannenheizung (D30/1437 erst wirksam, wenn AT kleiner H42 ist)
    reg_1357 = gauge(1357, 0.1, writable=True, unit="K")  # Z19 TEMP1 Differenz: Keine Pumpe Ein bei niedriger Wassertemperatur
    reg_1358 = integer(1358, signed=True, writable=True)  # Z20 DIGI1
    reg_1371 = gauge(1371, 1.0, writable=True)  #  RAW
    reg_1372 = gauge(1372, 1.0, writable=True)  #  RAW
    reg_1373 = gauge(1373, 1.0, writable=True)  #  RAW
    reg_1374 = gauge(1374, 0.1, writable=True)  #  TEMP1 Automatischer Werkstest Zieltemperatur (ASM)
    reg_1375 = gauge(1375, 1.0, writable=True)  #  RAW
    reg_1376 = gauge(1376, 1.0, writable=True)  #  RAW
    reg_1377 = gauge(1377, 1.0, writable=True)  #  RAW
    reg_1378 = gauge(1378, 1.0, writable=True)  #  RAW
    reg_1379 = gauge(1379, 1.0, writable=True)  #  RAW
    reg_1380 = gauge(1380, 1.0, writable=True)  #  RAW
    reg_1432 = gauge(1432, 0.1, writable=True, unit="°C")  # P11 TEMP1 Ziel-Temperaturdifferenz für Pumpendrehzahlregelung
    reg_1433 = gauge(1433, 1.0, writable=True, unit="N")  # P12 STEPS_N
    reg_1435 = gauge(1435, 1.0, writable=True, unit="days")  # P13 DAYS
    reg_1436 = gauge(1436, 1.0, writable=True, unit="s")  # P14 SECONDS
    reg_1437 = gauge(1437, 1.0, writable=True, unit="min")  # D30 MINUTES
    reg_1438 = gauge(1438, 0.1, writable=True, unit="bar")  # P15 BAR_X10 Ziel-Wasserdruck (IDU)
    reg_1444 = gauge(1444, 0.1, writable=True, unit="bar")  # P16 BAR_X10 Stopp-Nachfülldruckdifferenz (IDU)
    reg_1464 = gauge(1464, 1.0, writable=False)  #  RAW
    reg_1466 = gauge(1466, 1.0, writable=False)  #  RAW
    reg_1476 = gauge(1476, 1.0, writable=False)  #  RAW
    reg_2011 = integer(2011, signed=True, writable=False)  #  DIGI1
    reg_2012 = integer(2012, signed=True, writable=False)  #  DIGI1
    reg_2013 = gauge(2013, 0.1, writable=False)  #  TEMP1 Temperaturwert nach Begrenzung
    reg_2014 = gauge(2014, 0.1, writable=False)  #  TEMP1 Temperaturwert nach Wetterkompensation während des Heizens
    reg_2015 = integer(2015, signed=True, writable=False)  #  DIGI1
    reg_2016 = gauge(2016, 0.1, writable=False, unit="°C")  #  TEMP1 Solltemperatur wie 2013 / 2014
    reg_2017 = gauge(2017, 1.0, writable=False)  #  RAW
    reg_2018 = integer(2018, signed=True, writable=False)  #  DIGI1
    reg_2019 = integer(2019, signed=True, writable=False)  #  BITFIELD
    reg_2020 = integer(2020, signed=True, writable=False)  #  DIGI1
    reg_2021 = gauge(2021, 1.0, writable=False)  #  RAW
    reg_2022 = integer(2022, signed=True, writable=False)  #  DIGI1
    reg_2023 = gauge(2023, 1.0, writable=False)  #  RAW
    reg_2024 = gauge(2024, 1.0, writable=False)  #  RAW
    reg_2025 = gauge(2025, 1.0, writable=False)  #  RAW
    reg_2026 = gauge(2026, 1.0, writable=False)  #  RAW
    reg_2027 = gauge(2027, 1.0, writable=False)  #  RAW
    reg_2028 = gauge(2028, 1.0, writable=False)  #  RAW
    reg_2029 = gauge(2029, 0.1, writable=False, unit="A")  # T-Diag5 DIGI5 Eingangsstrom L1
    reg_2030 = gauge(2030, 0.1, writable=False, unit="A")  # T-Diag6 DIGI5 Eingangsstrom L2
    reg_2031 = gauge(2031, 0.1, writable=False, unit="A")  # T-Diag7 DIGI5 Eingangsstrom L3
    reg_2032 = gauge(2032, 1.0, writable=False, unit="h")  # T-Diag8 RAW
    reg_2033 = gauge(2033, 1.0, writable=False)  #  RAW
    reg_2034 = integer(2034, signed=True, writable=False)  # S01 BITFIELD
    reg_2035 = gauge(2035, 0.1, writable=False)  # T40 TEMP1 Heizungsrücklauftemperatur
    reg_2036 = gauge(2036, 0.1, writable=False)  # T41 TEMP1 Heizungsvorlauftemperatur
    reg_2037 = gauge(2037, 0.1, writable=False)  # T42 TEMP1 Mischrohrauslasswassertemperatur
    reg_2038 = gauge(2038, 0.1, writable=False)  # T43 TEMP1 WW-Rücklauftemperatur
    reg_2039 = gauge(2039, 0.1, writable=False)  # T44 TEMP1 WW-Vorlauftemperatur
    reg_2040 = gauge(2040, 1.0, writable=False)  #  RAW
    reg_2041 = gauge(2041, 1.0, writable=False)  #  RAW
    reg_2042 = gauge(2042, 0.1, writable=False, unit="A")  # T36 AMP_X10 Phasenstrom des Kompressors
    reg_2043 = gauge(2043, 1.0, writable=False, unit="V")  # T37 VOLT
    reg_2044 = gauge(2044, 0.1, writable=False)  # T38 TEMP1 IPM-Temperatur.
    reg_2045 = gauge(2045, 0.1, writable=False)  # T01 TEMP1 Einlasswassertemperatur
    reg_2046 = gauge(2046, 0.1, writable=False)  # T02 TEMP1 Auslasswassertemperatur
    reg_2047 = gauge(2047, 0.1, writable=False)  # T08 TEMP1 WW-Tanktemperatur
    reg_2048 = gauge(2048, 0.1, writable=False)  # T04 TEMP1 Umgebungstemperatur (AT)
    reg_2049 = gauge(2049, 0.1, writable=False)  # T03 TEMP1 Verdampfertemperatur
    reg_2050 = gauge(2050, 0.1, writable=False)  # T14 TEMP1 Verteilerrohrtemperatur
    reg_2051 = gauge(2051, 0.1, writable=False)  # T05 TEMP1 Saugsungstemperatur
    reg_2052 = gauge(2052, 0.1, writable=False)  # T07 TEMP1 Puffertanktemperatur
    reg_2053 = gauge(2053, 0.1, writable=False)  # T12 TEMP1 Abgastemperatur
    reg_2054 = gauge(2054, 0.1, writable=False, unit="kW")  # T54 POWER_KW_X10 Elektrische Leistung / Unit Power
    reg_2055 = gauge(2055, 0.1, writable=False)  # T06 TEMP1 Frostschutztemperatur (Am PlattenWT)
    reg_2056 = gauge(2056, 0.1, writable=False)  #  TEMP1 T? / System 1 Frostschutztemperatur 2 / Coil/Frost Temp 2 (ASM V1.3)
    reg_2057 = gauge(2057, 1.0, writable=False, unit="A")  #  RAW
    reg_2058 = gauge(2058, 0.1, writable=False)  # T09 DIGI5 Raumtemperatur
    reg_2059 = gauge(2059, 0.1, writable=False, unit="kW")  # T59 POWER_KW_X10 Wärmeleistung / Unit Capacity
    reg_2060 = gauge(2060, 0.01, writable=False, unit="COP")  # T60 COP_X100 COP
    reg_2061 = gauge(2061, 0.1, writable=False)  # T33 TEMP1 IPM-Hochfehler-Temperatur
    reg_2062 = gauge(2062, 1.0, writable=False, unit="V")  # T34 VOLT
    reg_2063 = gauge(2063, 0.1, writable=False, unit="°C")  # T10 TEMP1 EVI-Einlasstemperatur
    reg_2064 = gauge(2064, 0.1, writable=False)  # T11 TEMP1 EVI-Auslasstemperatur
    reg_2065 = gauge(2065, 0.1, writable=False, unit="°C")  # T-Diag1 TEMP1 Verdampfungstemperatur / Evaporating Temp (ASM)
    reg_2066 = gauge(2066, 0.1, writable=False, unit="K")  # T-Diag2 TEMP1 Abgas-Überhitzung / Exhaust Superheat (ASM)
    reg_2067 = gauge(2067, 0.1, writable=False, unit="K")  # T-Diag3 TEMP1 Rückgas-/Saug-Überhitzung / Suction Superheat (ASM)
    reg_2068 = gauge(2068, 0.1, writable=False)  #  DIGI5 System 2 Strom / Current (ASM)
    reg_2069 = gauge(2069, 0.1, writable=False, unit="bar")  # T15 BAR_X10 Niederdruck
    reg_2070 = gauge(2070, 0.1, writable=False)  #  DIGI5 System 2 Druck / Pressure (ASM)
    reg_2071 = integer(2071, signed=True, writable=False)  # T30 DIGI1
    reg_2072 = integer(2072, signed=True, writable=False)  # T31 DIGI1
    reg_2073 = integer(2073, signed=True, writable=False)  # T32 DIGI1
    reg_2074 = integer(2074, signed=True, writable=False)  # T27 DIGI1
    reg_2075 = integer(2075, signed=True, writable=False)  # T28 DIGI1
    reg_2076 = integer(2076, signed=True, writable=False)  # T29 DIGI1
    reg_2077 = gauge(2077, 0.01, writable=False, unit="m³/h")  # T39 FLOW_M3H_X100 Wasserdurchflussrate
    reg_2078 = gauge(2078, 1.0, writable=False, unit="kWh")  #  KWH
    reg_2079 = gauge(2079, 1.0, writable=False, unit="kWh")  #  KWH
    reg_2080 = gauge(2080, 1.0, writable=False, unit="raw")  #  RAW
    reg_2081 = integer(2081, signed=True, writable=False)  # ERR07 BITFIELD
    reg_2082 = integer(2082, signed=True, writable=False)  # ERR08 BITFIELD
    reg_2083 = integer(2083, signed=True, writable=False)  # ERR09 BITFIELD
    reg_2084 = gauge(2084, 1.0, writable=False)  #  RAW
    reg_2085 = integer(2085, signed=True, writable=False)  # ERR01 BITFIELD
    reg_2086 = integer(2086, signed=True, writable=False)  # ERR02 BITFIELD
    reg_2087 = integer(2087, signed=True, writable=False)  # ERR03 BITFIELD
    reg_2088 = integer(2088, signed=True, writable=False)  # ERR04 BITFIELD
    reg_2089 = integer(2089, signed=True, writable=False)  # ERR05 BITFIELD
    reg_2090 = integer(2090, signed=True, writable=False)  # ERR06 BITFIELD
    reg_2101 = gauge(2101, 1.0, writable=False)  #  RAW
    reg_2102 = gauge(2102, 1.0, writable=False)  #  RAW
    reg_2103 = gauge(2103, 1.0, writable=False)  #  RAW
    reg_2104 = gauge(2104, 1.0, writable=False)  #  RAW
    reg_2105 = gauge(2105, 1.0, writable=False)  #  RAW
    reg_2106 = gauge(2106, 1.0, writable=False)  #  RAW
    reg_2107 = gauge(2107, 1.0, writable=False)  #  RAW
    reg_2108 = gauge(2108, 1.0, writable=False)  #  RAW
    reg_2109 = gauge(2109, 1.0, writable=False)  #  RAW
    reg_2110 = gauge(2110, 1.0, writable=False)  #  RAW
    reg_2111 = gauge(2111, 1.0, writable=False)  #  RAW
    reg_2112 = gauge(2112, 1.0, writable=False)  #  RAW
    reg_2113 = gauge(2113, 1.0, writable=False)  #  RAW
    reg_2114 = gauge(2114, 1.0, writable=False)  #  RAW
    reg_2115 = gauge(2115, 1.0, writable=False, unit="%")  #  PERCENT
    reg_2116 = gauge(2116, 1.0, writable=False, unit="%")  #  PERCENT
    reg_2117 = gauge(2117, 1.0, writable=False)  #  RAW
    reg_2118 = gauge(2118, 1.0, writable=False, unit="kWh")  #  KWH
    reg_2119 = gauge(2119, 1.0, writable=False)  #  RAW
    reg_2120 = gauge(2120, 1.0, writable=False, unit="kWh")  #  KWH
    reg_2121 = gauge(2121, 1.0, writable=False)  #  RAW
    reg_2122 = gauge(2122, 1.0, writable=False, unit="kWh")  #  KWH
    reg_2123 = gauge(2123, 1.0, writable=False)  #  RAW
    reg_2124 = gauge(2124, 1.0, writable=False, unit="kWh")  #  KWH
    reg_2125 = gauge(2125, 1.0, writable=False)  #  RAW
    reg_2126 = gauge(2126, 1.0, writable=False)  #  RAW
    reg_2127 = gauge(2127, 1.0, writable=False)  #  RAW
    reg_2128 = gauge(2128, 1.0, writable=False)  #  RAW
    reg_2129 = gauge(2129, 1.0, writable=False)  #  RAW
    reg_2130 = gauge(2130, 0.1, writable=False)  # T46 DIGI5 IPM-Temperatur des externen Lüftermotorantriebs
    reg_2131 = integer(2131, signed=True, writable=False)  # T47 DIGI1
    reg_2132 = gauge(2132, 0.001, writable=False)  # T48 DIGI6 Strom des externen Lüftermotorantriebs.
    reg_2133 = gauge(2133, 1.0, writable=False)  # SGstatus RAW
    reg_2134 = gauge(2134, 1.0, writable=False)  #  RAW
    reg_2135 = gauge(2135, 1.0, writable=False)  #  RAW
    reg_2136 = gauge(2136, 0.1, writable=False, unit="°C")  #  TEMP1 T04 Außentemperatur – zweiter Veröffentlichungsweg
    reg_2137 = gauge(2137, 0.1, writable=False, unit="kW")  #  POWER_KW_X10 Elektrische WP-/Inverterleistung ohne Zusatzanteil
    reg_2138 = gauge(2138, 0.1, writable=False, unit="kW")  #  POWER_KW_X10 Thermische WP-Leistung ohne Zusatzanteil
    reg_2139 = gauge(2139, 1.0, writable=False)  #  RAW
    reg_2140 = gauge(2140, 1.0, writable=False)  #  RAW
    reg_2141 = gauge(2141, 1.0, writable=False)  #  RAW
    reg_2142 = gauge(2142, 1.0, writable=False)  #  RAW
    reg_2143 = gauge(2143, 1.0, writable=False)  #  RAW
    reg_2144 = gauge(2144, 1.0, writable=False)  #  RAW
    reg_2145 = gauge(2145, 1.0, writable=False)  #  RAW
    reg_2146 = gauge(2146, 1.0, writable=False)  #  RAW
    reg_2147 = gauge(2147, 1.0, writable=False)  #  RAW
    reg_2148 = gauge(2148, 1.0, writable=False)  #  RAW
    reg_2149 = gauge(2149, 1.0, writable=False)  #  RAW
    reg_2178 = gauge(2178, 0.1, writable=False, unit="°C")  #  TEMP1 Temperatur des Temperatur-/Feuchtesensors
    reg_2179 = gauge(2179, 0.1, writable=False, unit="% rF")  #  DIGI5 Relative Luftfeuchtigkeit
    reg_2180 = gauge(2180, 0.1, writable=False, unit="°C")  #  TEMP1 Berechneter Taupunkt

    def as_dict(self, regmap=None):
        """Compat shim: return {addr: {raw, value, info}} like old coordinator.data."""
        out = {}
        for name, field in self.declared_fields.items():
            if not name.startswith('reg_'): continue
            try: addr=int(name.split('_')[1])
            except: continue
            val=getattr(self, name, None)
            # raw words not directly exposed; use value for both (compat: raw==value for scaled? keep value)
            # For diagnostics we store value as both raw/value; caller can read .value
            info={}
            if regmap and str(addr) in regmap:
                info=regmap[str(addr)]
            # Try to get raw word via private _values? fallback to value
            raw=val
            out[addr]={'raw': raw, 'value': val, 'info': info}
        return out

    @property
    def poll_addrs(self):
        return [int(n.split('_')[1]) for n in self.declared_fields if n.startswith('reg_')]

