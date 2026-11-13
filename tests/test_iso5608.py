"""Разбор кодов оснастки ISO 5608: ожидания из ТЗ 3.2 и все модели из таблиц."""
import unittest

from src.iso5608 import (
    BLADE,
    BLOCK,
    BORING,
    EXTERNAL,
    GROOVING_EXTERNAL,
    GROOVING_FACE,
    GROOVING_INTERNAL,
    THREAD_EXTERNAL,
    THREAD_INTERNAL,
    parse_holder_code,
)

# 38 наружных державок из таблиц: код, форма, задний угол, размер пластины, серия.
EXTERNAL_MODELS = [
    ("DDJNR 2020K-1504-M-A", "D", "N", "15", "DDJN-15"),
    ("DDJNR 2525M-1504-M-A", "D", "N", "15", "DDJN-15"),
    ("DDJNL 2525M-1504-M-A", "D", "N", "15", "DDJN-15"),
    ("DCLNR 2020K-12-M-A", "C", "N", "12", "DCLN-12"),
    ("DCLNR 2525M-12-M-A", "C", "N", "12", "DCLN-12"),
    ("DCLNL 2525M-12-M-A", "C", "N", "12", "DCLN-12"),
    ("DCLNR 2525M-16-M-A", "C", "N", "16", "DCLN-16"),
    ("DCLNR 3232P-16-M-A", "C", "N", "16", "DCLN-16"),
    ("DCLNR 3232P-19-M-A", "C", "N", "19", "DCLN-19"),
    ("DWLNR 2020K-08-M-A", "W", "N", "08", "DWLN-08"),
    ("DWLNR 2525M-08-M-A", "W", "N", "08", "DWLN-08"),
    ("DWLNL 2525M-08-M-A", "W", "N", "08", "DWLN-08"),
    ("DSSNR 2020K-12-M-A", "S", "N", "12", "DSSN-12"),
    ("DSSNR 2525M-12-M-A", "S", "N", "12", "DSSN-12"),
    ("DSSNR 3232P-19-M-A", "S", "N", "19", "DSSN-19"),
    ("PSSNR 3232P-19-M-A", "S", "N", "19", "PSSN-19"),
    ("MVJNR 2020K-16-M-A", "V", "N", "16", "MVJN-16"),
    ("MVJNR 2525M-16-M-A", "V", "N", "16", "MVJN-16"),
    ("MVJNL 2525M-16-M-A", "V", "N", "16", "MVJN-16"),
    ("MTJNR 2525M-16-M-A", "T", "N", "16", "MTJN-16"),
    ("MTJNL 2525M-16-M-A", "T", "N", "16", "MTJN-16"),
    ("SCLCR 1616H-09-M-A", "C", "C", "09", "SCLC-09"),
    ("SCLCL 1616H-09-M-A", "C", "C", "09", "SCLC-09"),
    ("SCLCR 2020K-09-M-A", "C", "C", "09", "SCLC-09"),
    ("SCLCL 2020K-09-M-A", "C", "C", "09", "SCLC-09"),
    ("SCLCR 2525M-09-M-A", "C", "C", "09", "SCLC-09"),
    ("SCLCR 2525M-12-M-A", "C", "C", "12", "SCLC-12"),
    ("SCLCL 2525M-12-M-A", "C", "C", "12", "SCLC-12"),
    ("SDJCR 1616H-11-M-A", "D", "C", "11", "SDJC-11"),
    ("SDJCL 1616H-11-M-A", "D", "C", "11", "SDJC-11"),
    ("SDJCR 2020K-11-M-A", "D", "C", "11", "SDJC-11"),
    ("SDJCL 2020K-11-M-A", "D", "C", "11", "SDJC-11"),
    ("SDJCR 2525M-11-M-A", "D", "C", "11", "SDJC-11"),
    ("SVJCR 1616H-16-M-A", "V", "C", "16", "SVJC-16"),
    ("SVJCR 2020K-16-M-A", "V", "C", "16", "SVJC-16"),
    ("SVJCL 2020K-16-M-A", "V", "C", "16", "SVJC-16"),
    ("SVJCR 2525M-16-M-A", "V", "C", "16", "SVJC-16"),
    ("SVJCL 2525M-16-M-A", "V", "C", "16", "SVJC-16"),
]

# 11 расточных из таблиц: код, форма, задний угол, размер пластины, серия.
BORING_MODELS = [
    ("S08K-SCLCR-06-M-A", "C", "C", "06", "SCLC-06"),
    ("S10K-SCLCR-06-M-A", "C", "C", "06", "SCLC-06"),
    ("S12M-SCLCR-06-M-A", "C", "C", "06", "SCLC-06"),
    ("S16Q-SCLCR-09-M-A", "C", "C", "09", "SCLC-09"),
    ("S20R-SCLCR-09-M-A", "C", "C", "09", "SCLC-09"),
    ("S25S-SCLCR-12-M-A", "C", "C", "12", "SCLC-12"),
    ("S10K-SDUCR-07-M-A", "D", "C", "07", "SDUC-07"),
    ("S12M-SDUCR-07-M-A", "D", "C", "07", "SDUC-07"),
    ("S16Q-SDUCR-11-M-A", "D", "C", "11", "SDUC-11"),
    ("S20R-SDUCR-11-M-A", "D", "C", "11", "SDUC-11"),
    ("S25S-SDUCR-11-M-A", "D", "C", "11", "SDUC-11"),
]

# 6 резьбовых из таблиц: код, вид, размер, тип пластины.
THREAD_MODELS = [
    ("SER 1616H-16-M-A", THREAD_EXTERNAL, "16", "16ER"),
    ("SER 2020K-16-M-A", THREAD_EXTERNAL, "16", "16ER"),
    ("SER 2525M-16-M-A", THREAD_EXTERNAL, "16", "16ER"),
    ("SNR 0016Q-16-M-A", THREAD_INTERNAL, "16", "16IR"),
    ("SNR 0020R-16-M-A", THREAD_INTERNAL, "16", "16IR"),
    ("SNR 0025S-16-M-A", THREAD_INTERNAL, "16", "16IR"),
]

# 13 канавочных и лезвий из таблиц: код, вид, ширина паза.
GROOVING_MODELS = [
    ("KGDR 2020K-2T17-M", GROOVING_EXTERNAL, 2.0),
    ("KGDR 2020K-3T20-M", GROOVING_EXTERNAL, 3.0),
    ("KGDR 2525M-3T20-M", GROOVING_EXTERNAL, 3.0),
    ("KGDR 2525M-4T20-M", GROOVING_EXTERNAL, 4.0),
    ("KGFDR 2020K-2535-3-M", GROOVING_FACE, 3.0),
    ("KGFDR 2525M-3550-4-M", GROOVING_FACE, 4.0),
    ("S16Q-KGIR-3", GROOVING_INTERNAL, 3.0),
    ("S20R-KGIR-3", GROOVING_INTERNAL, 3.0),
    ("S25S-KGIR-3", GROOVING_INTERNAL, 3.0),
    ("KGFH 26-2-M", BLADE, 2.0),
    ("KGFH 26-3-M", BLADE, 3.0),
    ("KGFH 32-3-M", BLADE, 3.0),
    ("KGFH 32-4-M", BLADE, 4.0),
]

# 2 блока под лезвия из таблиц: код, высота лезвия.
BLOCK_MODELS = [
    ("KGFH 2020-26", 26.0),
    ("KGFH 2525-32", 32.0),
]


class DocExpectationsTest(unittest.TestCase):
    """17 строк из раздела 3.2 ТЗ."""

    def test_compact_external(self):
        info = parse_holder_code("DCLNR2525M12")
        self.assertEqual((info["kind"], info["shape"], info["clearance"], info["insert_size"]),
                         (EXTERNAL, "C", "N", "12"))
        self.assertEqual(info["shank_mm"], 25.0)
        self.assertEqual(info["hand"], "R")
        self.assertTrue(info["turning"])

    def test_deskar_suffix_does_not_shift_size(self):
        info = parse_holder_code("DCLNR2525M-12-M-A")
        self.assertEqual(info["insert_size"], "12")
        self.assertEqual(info["series_key"], "DCLN-12")

    def test_four_digit_size_is_first_two_digits(self):
        info = parse_holder_code("DDJNR2020K1504")
        self.assertEqual(info["insert_size"], "15")
        self.assertEqual(info["series_key"], "DDJN-15")

    def test_spaced_record(self):
        info = parse_holder_code("DCLNR 2525M-12-M-A")
        self.assertEqual((info["shape"], info["clearance"], info["insert_size"]), ("C", "N", "12"))

    def test_boring_record(self):
        info = parse_holder_code("S16Q-SCLCR-09-M-A")
        self.assertEqual((info["kind"], info["shape"], info["clearance"], info["insert_size"]),
                         (BORING, "C", "C", "09"))
        self.assertEqual(info["shank_diameter_mm"], 16.0)

    def test_thread_records(self):
        ext = parse_holder_code("SER 1616H-16-M-A")
        self.assertEqual((ext["kind"], ext["insert_type"]), (THREAD_EXTERNAL, "16ER"))
        inner = parse_holder_code("SNR 0016Q-16-M-A")
        self.assertEqual((inner["kind"], inner["insert_type"]), (THREAD_INTERNAL, "16IR"))
        self.assertEqual(inner["shank_diameter_mm"], 16.0)

    def test_grooving_records(self):
        ext = parse_holder_code("KGDR 2525M-3T20-M")
        self.assertEqual((ext["kind"], ext["groove_width_mm"]), (GROOVING_EXTERNAL, 3.0))
        inner = parse_holder_code("S16Q-KGIR-3")
        self.assertEqual((inner["kind"], inner["groove_width_mm"]), (GROOVING_INTERNAL, 3.0))

    def test_turning_flag_only_for_turning_holders(self):
        self.assertTrue(parse_holder_code("DCLNR2525M12")["turning"])
        self.assertTrue(parse_holder_code("S16Q-SCLCR-09-M-A")["turning"])
        self.assertFalse(parse_holder_code("SER 1616H-16-M-A")["turning"])


class TableModelsTest(unittest.TestCase):
    """Все 70 моделей из таблиц совместимости разбираются без ошибок."""

    def test_external_holders(self):
        for code, shape, clearance, size, series in EXTERNAL_MODELS:
            with self.subTest(code=code):
                info = parse_holder_code(code)
                self.assertIsNotNone(info)
                self.assertEqual(info["kind"], EXTERNAL)
                self.assertEqual(
                    (info["shape"], info["clearance"], info["insert_size"], info["series_key"]),
                    (shape, clearance, size, series),
                )

    def test_boring_holders(self):
        for code, shape, clearance, size, series in BORING_MODELS:
            with self.subTest(code=code):
                info = parse_holder_code(code)
                self.assertIsNotNone(info)
                self.assertEqual((info["kind"], info["shape"], info["clearance"]), (BORING, shape, clearance))
                self.assertEqual((info["insert_size"], info["series_key"]), (size, series))

    def test_thread_holders(self):
        for code, kind, size, insert_type in THREAD_MODELS:
            with self.subTest(code=code):
                info = parse_holder_code(code)
                self.assertIsNotNone(info)
                self.assertEqual((info["kind"], info["insert_size"], info["insert_type"]),
                                 (kind, size, insert_type))

    def test_grooving_holders_and_blades(self):
        for code, kind, width in GROOVING_MODELS:
            with self.subTest(code=code):
                info = parse_holder_code(code)
                self.assertIsNotNone(info)
                self.assertEqual((info["kind"], info["groove_width_mm"]), (kind, width))

    def test_blocks(self):
        for code, blade_height in BLOCK_MODELS:
            with self.subTest(code=code):
                info = parse_holder_code(code)
                self.assertIsNotNone(info)
                self.assertEqual((info["kind"], info["blade_height_mm"]), (BLOCK, blade_height))

    def test_total_table_models(self):
        total = (len(EXTERNAL_MODELS) + len(BORING_MODELS) + len(THREAD_MODELS)
                 + len(GROOVING_MODELS) + len(BLOCK_MODELS))
        self.assertEqual(total, 70)


class NormalizationTest(unittest.TestCase):
    """Омоглифы, кириллица и неверная раскладка."""

    def test_cyrillic_homoglyph_in_code(self):
        info = parse_holder_code("MCВNR3232P19")  # В - кириллица
        self.assertEqual((info["code"], info["shape"], info["clearance"], info["insert_size"]),
                         ("MCBNR3232P19", "C", "N", "19"))
        self.assertEqual(info["series_key"], "MCBN-19")

    def test_fully_cyrillic_code(self):
        info = parse_holder_code("ДСЛНР2525М12")
        self.assertEqual((info["shape"], info["clearance"], info["insert_size"]), ("C", "N", "12"))

    def test_russian_keyboard_layout(self):
        info = parse_holder_code("ВСДТК2525Ь12")  # DCLNR2525M12 в русской раскладке
        self.assertEqual((info["shape"], info["clearance"], info["insert_size"]), ("C", "N", "12"))

    def test_case_and_separators(self):
        info = parse_holder_code("dclnr 2525m-12-m-a")
        self.assertEqual(info["code"], "DCLNR-2525M-12-M-A")
        self.assertEqual(info["insert_size"], "12")

    def test_boring_size_two_digits_kept(self):
        self.assertEqual(parse_holder_code("S08K-SCLCR-06-M-A")["insert_size"], "06")


class RejectionTest(unittest.TestCase):
    """Пластины, фрезы, свёрла, патроны и минирезцы державками не считаются."""

    def test_non_holder_codes(self):
        for code in (
            "CNMG120408", "CCMT09T304", "DCMT11T304",   # пластины
            "BAP400R-50-22-4T", "KM12-63-22-5T",           # корпуса фрез
            "WC-2D-14-20",                                  # сверло
            "BT30", "SK40", "HSK63A",                       # патроны и оправки
            "MFR", "MGL", "MPR",                            # минирезцы
            "SHB", "MD-Y2114",                              # крепёж и прижимы
        ):
            with self.subTest(code=code):
                self.assertIsNone(parse_holder_code(code))

    def test_empty_input(self):
        self.assertIsNone(parse_holder_code(None))
        self.assertIsNone(parse_holder_code(""))


if __name__ == "__main__":
    unittest.main()
