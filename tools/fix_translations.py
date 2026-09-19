#!/usr/bin/env python3
"""Fix translations: English default everywhere, German/RU complete, block headers translated."""
import json
import pathlib
import re
BASE = pathlib.Path(__file__).parents[1] / "custom_components/foxair"
regs = json.loads((BASE / "data/foxair_phnix_registers.json").read_text(encoding="utf-8-sig"))
meta = json.loads((BASE / "data/foxair_metadata.json").read_text(encoding="utf-8-sig"))

def load(p): return json.loads(p.read_text(encoding="utf-8-sig"))
strings = load(BASE / "strings.json")
en = load(BASE / "translations/en.json")
de = load(BASE / "translations/de.json")
ru = load(BASE / "translations/ru.json")

CONFIG_TRANSLATIONS = {
    "en": {
        "step": {
            "user": {
                "title": "FoxAir Modbus Heat Pump",
                "description": "Connect to FoxAir / PHNIX via Modbus TCP. {warn} {multi_pump}",
                "data": {
                    "host": "Host",
                    "port": "Port",
                    "slave": "Slave ID",
                    "name_prefix": "Device prefix (e.g. foxair, phnix, house1)",
                    "enable_expert": "Enable expert mode (advanced/dangerous parameters)"
                }
            },
            "reconfigure": {
                "title": "Reconfigure FoxAir Heat Pump",
                "description": "Update connection settings for this pump. {warn}",
                "data": {
                    "host": "Host",
                    "port": "Port",
                    "slave": "Slave ID",
                    "name_prefix": "Device prefix (e.g. foxair, phnix, house1)"
                }
            }
        },
        "abort": {
            "already_configured": "Already configured"
        },
        "error": {
            "already_configured": "This heat pump is already configured — check host, port and slave ID",
            "cannot_connect": "Failed to connect — check host, port and slave ID",
            "need_ack": "You must acknowledge the risk to enable expert mode",
            "invalid_prefix": "Prefix must be lowercase alphanumeric with underscores, 1-32 characters",
            "prefix_in_use": "This prefix is already used by another FoxAir entry — pick a unique one"
        }
    },
    "ru": {
        "step": {
            "user": {
                "title": "FoxAir Modbus Heat Pump",
                "description": "Подключение к FoxAir / PHNIX по Modbus TCP. {warn} {multi_pump}",
                "data": {
                    "host": "Хост",
                    "port": "Порт",
                    "slave": "ID ведомого",
                    "name_prefix": "Префикс устройства (например foxair, phnix, house1)",
                    "enable_expert": "Включить экспертный режим (продвинутые / опасные параметры)"
                }
            },
            "reconfigure": {
                "title": "Перенастройка теплового насоса FoxAir",
                "description": "Обновите параметры подключения этого насоса. {warn}",
                "data": {
                    "host": "Хост",
                    "port": "Порт",
                    "slave": "ID ведомого",
                    "name_prefix": "Префикс устройства (например foxair, phnix, house1)"
                }
            }
        },
        "abort": {
            "already_configured": "Уже настроен"
        },
        "error": {
            "already_configured": "Этот тепловой насос уже настроен — проверьте хост, порт и ID ведомого",
            "cannot_connect": "Не удалось подключиться — проверьте хост, порт и ID ведомого",
            "need_ack": "Для включения экспертного режима нужно подтвердить риски",
            "invalid_prefix": "Префикс должен содержать только строчные буквы, цифры и подчеркивание, 1-32 символа",
            "prefix_in_use": "Этот префикс уже используется другой записью FoxAir — выберите уникальный"
        }
    },
    "de": {
        "step": {
            "user": {
                "title": "FoxAir Modbus Heat Pump",
                "description": "Mit FoxAir / PHNIX über Modbus TCP verbinden. {warn} {multi_pump}",
                "data": {
                    "host": "Host",
                    "port": "Port",
                    "slave": "Slave-ID",
                    "name_prefix": "Geräte-Prefix (z. B. foxair, phnix, haus1)",
                    "enable_expert": "Expertenmodus aktivieren (erweiterte / gefährliche Parameter)"
                }
            },
            "reconfigure": {
                "title": "FoxAir-Wärmepumpe neu konfigurieren",
                "description": "Verbindungseinstellungen dieser Pumpe aktualisieren. {warn}",
                "data": {
                    "host": "Host",
                    "port": "Port",
                    "slave": "Slave-ID",
                    "name_prefix": "Geräte-Prefix (z. B. foxair, phnix, haus1)"
                }
            }
        },
        "abort": {
            "already_configured": "Bereits konfiguriert"
        },
        "error": {
            "already_configured": "Diese Wärmepumpe ist bereits konfiguriert — Host, Port und Slave-ID prüfen",
            "cannot_connect": "Verbindung fehlgeschlagen — Host, Port und Slave-ID prüfen",
            "need_ack": "Sie müssen das Risiko bestätigen, um den Expertenmodus zu aktivieren",
            "invalid_prefix": "Prefix muss Kleinbuchstaben, Zahlen, Unterstrich, 1-32 Zeichen sein",
            "prefix_in_use": "Dieser Prefix wird bereits von einem anderen FoxAir-Eintrag verwendet — wählen Sie einen eindeutigen"
        }
    }
}

def translate_block_to_en(german):
    """Translate Blockkopf German to English."""
    s = german
    replacements = [
        ("Blockkopf Paket Status", "Block Header Packet Status"),
        ("Blockkopf Paket", "Block Header Packet"),
        (" / Kennung Wort ", " ID Word "),
        (" / WiFi Barcode ASCII Zeichen ", " WiFi Barcode ASCII Char "),
        (" / ASCII Zeichen ", " ASCII Char "),
        (" / Reserve 1", " Reserved 1"),
        (" / Reserve 2", " Reserved 2"),
        (" / Reserve/Ende", " Reserved/End"),
        (" / Marker-Länge", " Marker Length"),
        (" / erstes Blockkopf-Register", " First Header Register"),
        (" / Status 1 / Reserve", " Status 1 / Reserved"),
        (" / Status 2 / Reserve", " Status 2 / Reserved"),
        (" – ", " - "),
        (" –", " -"),
    ]
    for germ, eng in replacements:
        s = s.replace(germ, eng)
    # Also handle "ASCII Reserve/Ende" case
    s = s.replace("ASCII Reserve/Ende", "ASCII Reserved/End")
    return s

# Explicit EN names for new/changed regs
EN_OVERRIDES = {
    "200": "PHNIX/Aliyun ProductKey Word 1/16",
    "201": "PHNIX/Aliyun ProductKey Word 2/16",
    "202": "PHNIX/Aliyun ProductKey Word 3/16",
    "203": "PHNIX/Aliyun ProductKey Word 4/16",
    "204": "PHNIX/Aliyun ProductKey Word 5/16",
    "205": "PHNIX/Aliyun ProductKey Word 6/16",
    "206": "PHNIX/Aliyun ProductKey Word 7/16",
    "207": "PHNIX/Aliyun ProductKey Word 8/16",
    "208": "PHNIX/Aliyun ProductKey Word 9/16",
    "209": "PHNIX/Aliyun ProductKey Word 10/16",
    "210": "PHNIX/Aliyun ProductKey Word 11/16",
    "211": "PHNIX/Aliyun ProductKey Word 12/16",
    "212": "PHNIX/Aliyun ProductKey Word 13/16",
    "213": "PHNIX/Aliyun ProductKey Word 14/16",
    "214": "PHNIX/Aliyun ProductKey Word 15/16",
    "215": "PHNIX/Aliyun ProductKey Word 16/16",
    "1019": "Integrated fan motor and compressor drive",
    "1021": "Enable Cooling",
    "1028": "Heating/Cooling and DHW Function Enabled",
    "1051": "Min. Ambient Temp in Cooling Mode",
    "1055": "Min. Cooling Evaporation Temperature",
    "1059": "Fan Motor Type",
    "1060": "Evaporator Temp for Max Fan Speed in Cooling",
    "1061": "Fan Motor Power Curve",
    "1062": "Evaporator Temp for Min Fan Speed in Cooling",
    "1063": "E-Heater Switch-on Temp Differential",
    "1064": "Crankcase Heater Preheat Time",
    "1066": "Evaporator Temp for Max Fan Speed in Heating",
    "1068": "Evaporator Temp for Min Fan Speed in Heating",
    "1074": "Number of Fans",
    "1075": "Zone 1 Heating Outlet Water Setpoint",
    "1080": "Mixing Valve Manual Stroke Rate (0% = Auto Control)",
    "1081": "Min. Fan Speed in Cooling",
    "1082": "Mixing Valve Opening Time",
    "1083": "Min. Fan Speed in Heating",
    "1084": "Mixing Valve Closing Time",
    "1085": "Mixing Valve PID P-Term",
    "1087": "Enable Manual Fan Speed",
    "1088": "Mixing Valve PID I-Term",
    "1089": "Rated DC Fan Motor Speed",
    "1090": "Mixing Valve PID Cycle",
    "1101": "Evaporator Temp for Single/Dual Fan Switch in Cooling",
    "1102": "Evaporator Temp for Single Fan Stop in Cooling",
    "1103": "Max. Fan Speed in Cooling",
    "1104": "Max. Fan Speed in Heating",
    "1119": "Fan Motor Power Ratio to Extend Defrost Cycle",
    "1120": "Fan Motor Power Ratio to Enter Forced Defrost",
    "1121": "Max. Fan Motor Power to Enter Forced Defrost",
    "1122": "Evaporator Temp at Defrost Exit",
    "1126": "Enable Electric Heater During Defrost",
    "1128": "Max. Defrost Cycles via Fan Motor Power",
    "1129": "Water Tank Defrost Source in Heating+DHW/Cooling+DHW Mode",
    "1134": "Mixing Valve Stroke in Cooling",
    "1136": "Mixing Valve Control I (DIGI5 per ASM comment) (ASM)",
    "1138": "EEV Initial Steps in Cooling",
    "1148": "Target Superheat in Cooling",
    "1158": "Heating Set Temperature",
    "1159": "Cooling Set Temperature",
    "1160": "Heating Switch-on Return Differential",
    "1161": "Heating Standby/Off Temp Differential",
    "1162": "Min. Cooling Set Temperature",
    "1163": "Max. Cooling Set Temperature",
    "1164": "Min. Heating Set Temperature",
    "1165": "Max. Heating Set Temperature",
    "1174": "Cooling Switch-on Return Differential",
    "1175": "Cooling Standby/Off Temp Differential",
    "1195": "DHW Tank Switch-on Return Differential",
    "1217": "Max. Compressor Frequency in Cooling at High Ambient Temp",
    "1222": "Min. Compressor Frequency in Cooling at Low Ambient Temp",
    "1233": "Ambient Temp to Start Frequency Limiting in Cooling",
    "1237": "Ambient Temp to Stop Frequency Limiting in Cooling",
    "1240": "Room Temp Differential for Switch-on in Heating",
    "1242": "Room Temp Differential for Switch-on in Cooling",
    "1243": "Room Temp Differential for Standby in Cooling",
    "1340": "SG Mode 4 Cooling Target Temp Boost",
    "1356": "Condensate Pan Heater Switch-on AT (D30/1437 effective only when AT < H42)",
    "1358": "Enable Zone 1 Water Pump in Cooling",
    "1437": "Condensate Pan Heater Delays Off Time After Defrost",
    "2035": "Heating Return Temp",
    "2036": "Heating Supply Temp",
    "2049": "Evaporator Temperature",
    "2074": "Fan Motor 1 Speed",
    "2075": "Fan Motor 2 Speed",
    "2076": "Fan Motor Target Speed",
    "2125": "DHW Electric Energy High Word",
    "2126": "DHW Electric Energy Low Word",
    "2127": "DHW Thermal Energy High Word",
    "2128": "DHW Thermal Energy Low Word",
    "2130": "External Fan Drive IPM Temperature",
    "2131": "External Fan Drive Power",
    "2132": "External Fan Drive Current",
    "2136": "T04 Outdoor Temperature - Secondary Path",
    "2137": "Heat Pump Electrical Power (without booster)",
    "2138": "Heat Pump Thermal Power (without booster)",
    "2178": "Temperature/Humidity Sensor Temperature",
    "2179": "Relative Humidity",
    "2180": "Calculated Dew Point",
    "50043": "Service/OTA SSID (C37B)",
    "50044": "C37B Acknowledge Status",
    "50500": "Service/OTA SSID (C544)",
    "50501": "Hardware Code ASCII Word 1/4",
    "50502": "Hardware Code ASCII Word 2/4",
    "50503": "Hardware Code ASCII Word 3/4",
    "50504": "Hardware Code ASCII Word 4/4",
    "50505": "Hardware Version ASCII Word 1/2",
    "50506": "Hardware Version ASCII Word 2/2",
    "50507": "Software Code ASCII Word 1/4",
    "50508": "Software Code ASCII Word 2/4",
    "50509": "Software Code ASCII Word 3/4",
    "50510": "Software Code ASCII Word 4/4",
    "50511": "Internal Software Version ASCII Word 1/2",
    "50512": "Internal Software Version ASCII Word 2/2",
}
DE_OVERRIDES = {
    "200": "PHNIX/Aliyun ProductKey Wort 1/16",
    "201": "PHNIX/Aliyun ProductKey Wort 2/16",
    "202": "PHNIX/Aliyun ProductKey Wort 3/16",
    "203": "PHNIX/Aliyun ProductKey Wort 4/16",
    "204": "PHNIX/Aliyun ProductKey Wort 5/16",
    "205": "PHNIX/Aliyun ProductKey Wort 6/16",
    "206": "PHNIX/Aliyun ProductKey Wort 7/16",
    "207": "PHNIX/Aliyun ProductKey Wort 8/16",
    "208": "PHNIX/Aliyun ProductKey Wort 9/16",
    "209": "PHNIX/Aliyun ProductKey Wort 10/16",
    "210": "PHNIX/Aliyun ProductKey Wort 11/16",
    "211": "PHNIX/Aliyun ProductKey Wort 12/16",
    "212": "PHNIX/Aliyun ProductKey Wort 13/16",
    "213": "PHNIX/Aliyun ProductKey Wort 14/16",
    "214": "PHNIX/Aliyun ProductKey Wort 15/16",
    "215": "PHNIX/Aliyun ProductKey Wort 16/16",
    "1019": "Lüftermotorantrieb und Kompressorantrieb integriert",
    "1021": "Kühlfunktion aktivieren",
    "1028": "Heiz-/Kühl- und Warmwasserfunktion aktiviert",
    "1051": "Min. Umgebungstemperatur im Kühlmodus",
    "1055": "Minimale Verdampfungstemperatur der Kühlung",
    "1059": "Lüftermotortyp",
    "1060": "Verdampfertemperatur für maximale Lüfterdrehzahl im Kühlbetrieb",
    "1061": "Fan Motor Power Curve / Lüftermotor-Leistungskurve",
    "1062": "Verdampfertemperatur für minimale Lüfterdrehzahl im Kühlbetrieb",
    "1063": "E-Heizer Einschalt-Temperaturdifferenz",
    "1064": "Kurbelgehäuseheizung Vorheizzeit",
    "1066": "Verdampfertemperatur für maximale Lüfterdrehzahl im Heizbetrieb",
    "1068": "Verdampfertemperatur für minimale Lüfterdrehzahl im Heizbetrieb",
    "1074": "Lüfteranzahl",
    "1075": "Zone 1 Heizungs-Auslasswasser-Sollwert",
    "1080": "Mischventil manuelle Stellrate (0% = Auto-Regelung)",
    "1081": "Min. Lüfterdrehzahl im Kühlbetrieb",
    "1082": "Mischventil Öffnungszeit",
    "1083": "Min. Lüfterdrehzahl im Heizbetrieb",
    "1084": "Mischventil Schließzeit",
    "1085": "Mischventil Regelung P-Anteil (PID)",
    "1087": "Manuelle Lüfterdrehzahl aktivieren",
    "1088": "Mischventil Regelung I-Anteil (PID)",
    "1089": "Nenn-DC-Lüftermotordrehzahl",
    "1090": "Mischventil PID-Zyklus",
    "1101": "Verdampfertemperatur des Einzel-/Doppellüfterschalters im Kühlbetrieb",
    "1102": "Verdampfertemperatur des Einzellüfterstopps im Kühlbetrieb",
    "1103": "Max. Lüfterdrehzahl im Kühlbetrieb",
    "1104": "Max. Lüfterdrehzahl im Heizbetrieb",
    "1119": "Lüftermotorleistungsverhältnis zur Verlängerung des Abtauzyklus",
    "1120": "Lüftermotorleistungsverhältnis zum Eintritt in das erzwungene Abtauen",
    "1121": "Max. Lüftermotorleistung zum Eintritt in das erzwungene Abtauen",
    "1122": "Verdampfertemperatur des Abtauausgangs",
    "1126": "Elektrische Heizung während des Abtauens aktivieren",
    "1128": "Max. Abtauzyklus durch Lüftermotorleistung",
    "1129": "Wassertank-Abtauquelle im Heizung+WW/Kühlung+WW-Modus",
    "1134": "Mischventil-Stellwert im Kühlbetrieb",
    "1136": "Mischventil Regel-I (DIGI5 laut ASM-Kommentar) (ASM)",
    "1138": "EEV Anfangsschritte Kühlen",
    "1148": "Ziel-Überhitzung Kühlen",
    "1158": "Heizungssolltemperatur",
    "1159": "Kühlsolltemperatur",
    "1160": "Heizung Einschalt-Rücklaufdifferenz",
    "1161": "Heizung Standby-/Abschalt-Temperaturdifferenz",
    "1162": "Min. Kühlsolltemperatur",
    "1163": "Max. Kühlsolltemperatur",
    "1164": "Min. Heizungssolltemperatur",
    "1165": "Max. Heizungssolltemperatur",
    "1174": "Kühlung Einschalt-Rücklaufdifferenz",
    "1175": "Kühlung Standby-/Abschalt-Temperaturdifferenz",
    "1195": "WW-Tank Einschalt-Rücklaufdifferenz",
    "1217": "Max. Kompressorfrequenz im Kühlbetrieb bei hoher Umgebungstemperatur",
    "1222": "Min. Kompressorfrequenz im Kühlbetrieb bei niedriger Umgebungstemperatur",
    "1233": "AT zum Start der Frequenzbegrenzung im Kühlbetrieb",
    "1237": "AT zum Stoppen der Frequenzbegrenzung im Kühlbetrieb",
    "1240": "Raumtemperaturdifferenz zum Einschalten im Heizbetrieb",
    "1242": "Raumtemperaturdifferenz zum Einschalten im Kühlbetrieb",
    "1243": "Raumtemperaturdifferenz für Standby im Kühlbetrieb",
    "1340": "SG Mode 4 Kühlen-Zieltemperatur-Anhebung",
    "1356": "Einschalt-AT Gehäusewannenheizung (D30/1437 erst wirksam, wenn AT kleiner H42 ist)",
    "1358": "Zone 1 Wasserpumpe im Kühlbetrieb aktivieren",
    "1437": "Gehäusewannenheizung Delays Off Time after Defrost",
    "2035": "Heizungsrücklauftemperatur",
    "2036": "Heizungsvorlauftemperatur",
    "2049": "Verdampfertemperatur",
    "2074": "Drehzahl des Lüftermotors 1",
    "2075": "Drehzahl des Lüftermotors 2",
    "2076": "Zieldrehzahl des Lüftermotors",
    "2125": "Energiezähler elektrisch Warmwasser - High Word",
    "2126": "Energiezähler elektrisch Warmwasser - Low Word",
    "2127": "Energiezähler thermisch Warmwasser - High Word",
    "2128": "Energiezähler thermisch Warmwasser - Low Word",
    "2130": "IPM-Temperatur des externen Lüftermotorantriebs",
    "2131": "Leistung des externen Lüftermotorantriebs",
    "2132": "Strom des externen Lüftermotorantriebs.",
    "2136": "T04 Außentemperatur - zweiter Veröffentlichungsweg",
    "2137": "Elektrische WP-/Inverterleistung ohne Zusatzanteil",
    "2138": "Thermische WP-Leistung ohne Zusatzanteil",
    "2178": "Temperatur des Temperatur-/Feuchtesensors",
    "2179": "Relative Luftfeuchtigkeit",
    "2180": "Berechneter Taupunkt",
    "50043": "Service-/OTA-SSID (C37B)",
    "50044": "C37B Quittungsstatus",
    "50500": "Service-/OTA-SSID (C544)",
    "50501": "Hardwarecode ASCII Wort 1/4",
    "50502": "Hardwarecode ASCII Wort 2/4",
    "50503": "Hardwarecode ASCII Wort 3/4",
    "50504": "Hardwarecode ASCII Wort 4/4",
    "50505": "Hardwareversion ASCII Wort 1/2",
    "50506": "Hardwareversion ASCII Wort 2/2",
    "50507": "Softwarecode ASCII Wort 1/4",
    "50508": "Softwarecode ASCII Wort 2/4",
    "50509": "Softwarecode ASCII Wort 3/4",
    "50510": "Softwarecode ASCII Wort 4/4",
    "50511": "Interne Softwareversion ASCII Wort 1/2",
    "50512": "Interne Softwareversion ASCII Wort 2/2",
}
RU_OVERRIDES = {
    "200": "PHNIX/Aliyun ProductKey Слово 1/16",
    "201": "PHNIX/Aliyun ProductKey Слово 2/16",
    "202": "PHNIX/Aliyun ProductKey Слово 3/16",
    "203": "PHNIX/Aliyun ProductKey Слово 4/16",
    "204": "PHNIX/Aliyun ProductKey Слово 5/16",
    "205": "PHNIX/Aliyun ProductKey Слово 6/16",
    "206": "PHNIX/Aliyun ProductKey Слово 7/16",
    "207": "PHNIX/Aliyun ProductKey Слово 8/16",
    "208": "PHNIX/Aliyun ProductKey Слово 9/16",
    "209": "PHNIX/Aliyun ProductKey Слово 10/16",
    "210": "PHNIX/Aliyun ProductKey Слово 11/16",
    "211": "PHNIX/Aliyun ProductKey Слово 12/16",
    "212": "PHNIX/Aliyun ProductKey Слово 13/16",
    "213": "PHNIX/Aliyun ProductKey Слово 14/16",
    "214": "PHNIX/Aliyun ProductKey Слово 15/16",
    "215": "PHNIX/Aliyun ProductKey Слово 16/16",
    "1019": "Интегрированный привод вентилятора и компрессора",
    "1021": "Включить функцию охлаждения",
    "1028": "Включены функции отопления/охлаждения и ГВС",
    "1051": "Мин. температура окружающей среды в режиме охлаждения",
    "1055": "Мин. температура испарения при охлаждении",
    "1059": "Тип двигателя вентилятора",
    "1060": "Температура испарителя для макс. оборотов вентилятора в охлаждении",
    "1061": "Кривая мощности двигателя вентилятора",
    "1062": "Температура испарителя для мин. оборотов вентилятора в охлаждении",
    "1063": "Дельта температуры включения электронагревателя",
    "1064": "Время преднагрева картерного обогревателя",
    "1066": "Температура испарителя для макс. оборотов вентилятора в отоплении",
    "1068": "Температура испарителя для мин. оборотов вентилятора в отоплении",
    "1074": "Количество вентиляторов",
    "1075": "Зона 1: уставка воды на выходе (отопление)",
    "1080": "Ручной ход смесительного клапана (0% = авто)",
    "1081": "Мин. обороты вентилятора в охлаждении",
    "1082": "Время открытия смесительного клапана",
    "1083": "Мин. обороты вентилятора в отоплении",
    "1084": "Время закрытия смесительного клапана",
    "1085": "ПИД смесительного клапана: P-составляющая",
    "1087": "Включить ручные обороты вентилятора",
    "1088": "ПИД смесительного клапана: I-составляющая",
    "1089": "Номинальные обороты DC-двигателя вентилятора",
    "1090": "Цикл ПИД смесительного клапана",
    "1101": "Температура испарителя переключения одиночный/двойной вентилятор в охлаждении",
    "1102": "Температура испарителя остановки одиночного вентилятора в охлаждении",
    "1103": "Макс. обороты вентилятора в охлаждении",
    "1104": "Макс. обороты вентилятора в отоплении",
    "1119": "Коэффициент мощности вентилятора для продления цикла разморозки",
    "1120": "Коэффициент мощности вентилятора для входа в принудительную разморозку",
    "1121": "Макс. мощность вентилятора для входа в принудительную разморозку",
    "1122": "Температура испарителя при выходе из разморозки",
    "1126": "Включать электронагреватель во время разморозки",
    "1128": "Макс. циклов разморозки по мощности вентилятора",
    "1129": "Источник разморозки бака в режиме отопление+ГВС/охлаждение+ГВС",
    "1134": "Ход смесительного клапана в охлаждении",
    "1136": "Смесительный клапан: регулятор I (DIGI5 по комментарию ASM) (ASM)",
    "1138": "Начальные шаги ЭТРВ при охлаждении",
    "1148": "Целевой перегрев при охлаждении",
    "1158": "Уставка температуры отопления",
    "1159": "Уставка температуры охлаждения",
    "1160": "Дельта обратки включения отопления",
    "1161": "Дельта standby/выключения отопления",
    "1162": "Мин. уставка охлаждения",
    "1163": "Макс. уставка охлаждения",
    "1164": "Мин. уставка отопления",
    "1165": "Макс. уставка отопления",
    "1174": "Дельта обратки включения охлаждения",
    "1175": "Дельта standby/выключения охлаждения",
    "1195": "Дельта обратки включения бака ГВС",
    "1217": "Макс. частота компрессора в охлаждении при высокой температуре воздуха",
    "1222": "Мин. частота компрессора в охлаждении при низкой температуре воздуха",
    "1233": "AT начала ограничения частоты в охлаждении",
    "1237": "AT конца ограничения частоты в охлаждении",
    "1240": "Дельта комнатной температуры для включения отопления",
    "1242": "Дельта комнатной температуры для включения охлаждения",
    "1243": "Дельта комнатной температуры для standby в охлаждении",
    "1340": "SG режим 4 — повышение целевой температуры охлаждения",
    "1356": "Температура включения обогрева поддона (D30/1437 действует, только если AT < H42)",
    "1358": "Включать насос зоны 1 в охлаждении",
    "1437": "Обогрев поддона задерживает выключение после разморозки",
    "2035": "Температура обратки отопления",
    "2036": "Температура подачи отопления",
    "2049": "Температура испарителя",
    "2074": "Обороты двигателя вентилятора 1",
    "2075": "Обороты двигателя вентилятора 2",
    "2076": "Целевые обороты двигателя вентилятора",
    "2125": "Счётчик эл. энергии ГВС старший",
    "2126": "Счётчик эл. энергии ГВС младший",
    "2127": "Счётчик тепл. энергии ГВС старший",
    "2128": "Счётчик тепл. энергии ГВС младший",
    "2130": "IPM-температура внешнего привода вентилятора",
    "2131": "Мощность внешнего привода вентилятора",
    "2132": "Ток внешнего привода вентилятора",
    "2136": "T04 Температура наружного воздуха — второй путь",
    "2137": "Эл. мощность теплового насоса (без догрева)",
    "2138": "Тепл. мощность теплового насоса (без догрева)",
    "2178": "Температура датчика влажности",
    "2179": "Относительная влажность",
    "2180": "Расчётная точка росы",
    "50043": "Service/OTA SSID (C37B)",
    "50044": "Статус подтверждения C37B",
    "50500": "Service/OTA SSID (C544)",
    "50501": "Код оборудования ASCII Слово 1/4",
    "50502": "Код оборудования ASCII Слово 2/4",
    "50503": "Код оборудования ASCII Слово 3/4",
    "50504": "Код оборудования ASCII Слово 4/4",
    "50505": "Версия оборудования ASCII Слово 1/2",
    "50506": "Версия оборудования ASCII Слово 2/2",
    "50507": "Код ПО ASCII Слово 1/4",
    "50508": "Код ПО ASCII Слово 2/4",
    "50509": "Код ПО ASCII Слово 3/4",
    "50510": "Код ПО ASCII Слово 4/4",
    "50511": "Внутр. версия ПО ASCII Слово 1/2",
    "50512": "Внутр. версия ПО ASCII Слово 2/2",
}

def ensure_domain(data, domain):
    if "entity" not in data:
        data["entity"]={}
    if domain not in data["entity"]:
        data["entity"][domain]={}
    return data["entity"][domain]

# Fix block headers and new regs
fixed = {"sensor":0, "number":0, "select":0, "total_en_leak":0, "added":0, "updated":0}
# Process all addrs in regs that are not BLOCK? Actually all including BLOCK need translation
# But we include all addrs except service 50043+ (excluded from poll) — but still fix if exists
# For sensor domain, all addrs should have entry; for number/select only editable

# First, fix sensor entries for all addrs (including BLOCK)
for addr_str, rec in regs.items():
    if addr_str.startswith("_"):
        continue
    addr = addr_str
    german_name = rec.get("name","")
    # Determine expected names
    if addr in EN_OVERRIDES:
        en_name = EN_OVERRIDES[addr]
        de_name = DE_OVERRIDES[addr]
        ru_name = RU_OVERRIDES[addr]
    elif rec.get("type")=="BLOCK":
        en_name = translate_block_to_en(german_name)
        de_name = german_name
        ru_name = en_name  # diagnostic fallback to English for RU
    else:
        # For other regs, keep existing EN if exists and not German leak, else translate
        # If not in overrides and not BLOCK, use existing en if present else German
        # Try to keep existing
        en_name = None
        de_name = german_name
        ru_name = None
        # Check existing
        key = f"foxair_{addr}"
        existing_en = en.get("entity",{}).get("sensor",{}).get(key,{}).get("name") or strings.get("entity",{}).get("sensor",{}).get(key,{}).get("name")
        if existing_en and "Blockkopf" not in existing_en and "Kennung" not in existing_en:
            # keep if not obviously German leak and not outdated candidate/reserved mismatch
            # Detect outdated for 2125 etc: if german is energy but en is Reserved -> need update, but that is covered by overrides
            en_name = existing_en
        else:
            # fallback: for non-block, just keep german as de, en as german translated via simple? Use german as en fallback but ideally English
            # For now, if not BLOCK and not override, keep german as en only if no better — but we have existing hack: if existing_en is German leak, translate block else keep german
            if rec.get("type")=="BLOCK":
                en_name = translate_block_to_en(german_name)
            else:
                # For regular regs that changed, we already handled via overrides; otherwise keep existing
                en_name = existing_en or german_name
        # ru fallback
        existing_ru = ru.get("entity",{}).get("sensor",{}).get(key,{}).get("name")
        if existing_ru and any(ord(c)>127 for c in existing_ru):
            # has Cyrillic
            ru_name = existing_ru
        else:
            ru_name = en_name

        # If we didn't decide, skip
        if en_name is None:
            continue

    # Now ensure entries in all files for sensor domain
    # prefix CODE for strong tabs.txt order (friendly name sort == tabs order), keep friendly names like "T02: Name"
    for data, name, lang in [(strings, en_name, "strings"), (en, en_name, "en"), (de, de_name, "de"), (ru, ru_name, "ru")]:
        # apply prefix if code exists and not already prefixed (skip if name already starts with CODE:)
        _code_for_prefix = (regs.get(addr) or {}).get("code","")
        if _code_for_prefix and not name.startswith(_code_for_prefix + ":"):
            name = f"{_code_for_prefix}: {name}"
        domain_dict = ensure_domain(data, "sensor")
        key = f"foxair_{addr}"
        if key not in domain_dict:
            domain_dict[key] = {"name": name}
            fixed["added"]+=1
        else:
            if domain_dict[key].get("name") != name:
                # Only update if mismatch and lang is en/strings with German leak or override
                # For en/strings, update if German leak or override; for de/ru update accordingly
                should_update = False
                if lang in ("strings","en"):
                    if addr in EN_OVERRIDES or "Blockkopf" in domain_dict[key].get("name","") or "Kennung" in domain_dict[key].get("name",""):
                        should_update=True
                elif lang=="de":
                    if addr in DE_OVERRIDES or "Blockkopf" not in name:
                        # de should be German, if en was German leak then de was correct, no need? but ensure de is German
                        if domain_dict[key].get("name") != name:
                            should_update=True
                elif lang=="ru":
                    if addr in RU_OVERRIDES or "Blockkopf" in domain_dict[key].get("name",""):
                        should_update=True
                if should_update:
                    domain_dict[key]["name"] = name
                    fixed["updated"]+=1

# Also ensure number and select domains are synced for editable entities
for addr_str, meta_rec in meta.items():
    platform = meta_rec.get("platform")
    if platform not in ("number","select"):
        continue
    if not meta_rec.get("editable"):
        continue
    key = f"foxair_{addr_str}"
    # Sensor name is source
    sensor_en = en["entity"]["sensor"].get(key,{}).get("name") or strings["entity"]["sensor"].get(key,{}).get("name") or meta_rec.get("name","")
    sensor_de = de["entity"]["sensor"].get(key,{}).get("name") or sensor_en
    sensor_ru = ru["entity"]["sensor"].get(key,{}).get("name") or sensor_en
    for domain in [platform]:
        for data, name in [(strings, sensor_en), (en, sensor_en), (de, sensor_de), (ru, sensor_ru)]:
            d = ensure_domain(data, domain)
            if key not in d:
                # Copy from sensor with same name
                d[key] = {"name": name}
                fixed[domain]+=1
            else:
                # ensure name matches sensor
                if d[key].get("name") != name:
                    # Keep existing to avoid overwriting manually translated? But ensure sync
                    # For number/select, names should match sensor
                    d[key]["name"] = name
                    fixed["updated"]+=1
            # Also ensure state for select copied? States are separate, keep existing states

# Also fix block headers that were missing in strings sensor but present in regs but we already added sensor entries above
# Additionally, ensure number/select translations for all languages have same structure as strings (top-level config/options)
# Ensure en translations mirror strings for config/options
# Registry-driven sensor enum states: sensors with value_map get "N — Label" translations
# GER->EN/RU mapping for common values; fallback to registry label
GER_TO_EN_STATE = {"Aus":"Off","Ein":"On","Kühlen":"Cooling","Heizen":"Heating","Abtauen":"Defrost","Sterilisieren":"Sterilization","Warmwasser":"DHW","Nein":"No","Ja":"Yes","Abtau-Modus verfügbar":"Defrost Available","WP Aus oder SG deaktiviert":"HP Off / SG Disabled","SG Mode 1 / Schlafmodus":"SG Mode 1 / Sleep","SG Mode 2 / wenig PV":"SG Mode 2 / Low PV","SG Mode 3 / mittel PV":"SG Mode 3 / Medium PV","SG Mode 4 / High PV":"SG Mode 4 / High PV","Normalbetrieb":"Normal","disabled":"Disabled","enabled":"Enabled",



}
GER_TO_RU_STATE = {"Aus":"Выкл","Ein":"Вкл","Kühlen":"Охлаждение","Heizen":"Отопление","Abtauen":"Разморозка","Sterilisieren":"Стерилизация","Warmwasser":"ГВС","Nein":"Нет","Ja":"Да","Abtau-Modus verfügbar":"Разморозка доступна","WP Aus oder SG deaktiviert":"ТН выкл / SG откл","SG Mode 1 / Schlafmodus":"SG режим 1 / Сон","SG Mode 2 / wenig PV":"SG режим 2 / мало PV","SG Mode 3 / mittel PV":"SG режим 3 / средн. PV","SG Mode 4 / High PV":"SG режим 4 / макс. PV","Normalbetrieb":"Норма","disabled":"Откл","enabled":"Вкл",



}
for addr_str, rec in regs.items():
    if addr_str.startswith("_"):
        continue
    if not isinstance(rec, dict):
        continue
    vm = rec.get("value_map")
    if not vm or not isinstance(vm, dict):
        continue
    # only for sensor platform (non-editable) — select has its own state generation
    plat = meta.get(addr_str, {}).get("platform")
    if plat != "sensor":
        continue
    for lang_data, trans_map, use_en in [(strings, GER_TO_EN_STATE, True), (en, GER_TO_EN_STATE, True), (de, {}, False), (ru, GER_TO_RU_STATE, False)]:
        states = {}
        for k, label in vm.items():
            if use_en:
                lab = trans_map.get(label, label)
            elif lang_data is de:
                lab = label
            else:
                lab = trans_map.get(label, label)
            states[str(k)] = lab
        lang_data.setdefault("entity",{}).setdefault("sensor",{}).setdefault(f"foxair_{addr_str}", {})["state"] = states

# Validate select state completeness: keep as is

for lang, data in [("strings", strings), ("en", en), ("de", de), ("ru", ru)]:
    cfg = CONFIG_TRANSLATIONS.get(lang, CONFIG_TRANSLATIONS["en"])
    data["config"] = cfg

# Save — sort keys numerically (foxair_2127 < foxair_2136 < foxair_50043) for deterministic diffs
def _sort_key(k: str):
    m = re.match(r"foxair_(\d+)", k)
    return (0, int(m.group(1)), k) if m else (1, k)

for path, data in [(BASE/"strings.json", strings), (BASE/"translations/en.json", en), (BASE/"translations/de.json", de), (BASE/"translations/ru.json", ru)]:
    if "entity" in data:
        for domain in list(data["entity"].keys()):
            data["entity"][domain] = dict(sorted(data["entity"][domain].items(), key=lambda kv: _sort_key(kv[0])))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(f"Fixed: {fixed}")
# validate
print(f"strings sensor: {len(strings['entity']['sensor'])} en sensor: {len(en['entity']['sensor'])} de sensor: {len(de['entity']['sensor'])} ru sensor: {len(ru['entity']['sensor'])}")
print(f"strings number: {len(strings['entity'].get('number',{}))} select: {len(strings['entity'].get('select',{}))}")
# check missing 2178
for addr in ["2178","2179","2180"]:
    for lang, data in [("strings", strings),("en",en),("de",de),("ru",ru)]:
        print(f"{lang}  {addr}: {data['entity']['sensor'].get(f'foxair_{addr}',{}).get('name')}")
# check block 1181
for addr in ["1181","2125","2136","200"]:
    for lang, data in [("strings", strings),("en",en)]:
        print(f"{lang} {addr}: {data['entity']['sensor'].get(f'foxair_{addr}',{}).get('name')}")
