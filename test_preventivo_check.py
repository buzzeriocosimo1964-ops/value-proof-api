import unittest
from decimal import Decimal

from preventivo_core import analyze_quote_text, compare_quotes, extract_total


COMPLETE = """
PREVENTIVO RISTRUTTURAZIONE
Fornitura materiali marca Alfa modello X, quantità 80 mq.
Oneri di sicurezza D.Lgs. 81 compresi. Trasporto e smaltimento macerie compresi.
Durata lavori: 6 settimane. Pagamento: acconto 20%, SAL e saldo.
Garanzia sui vizi. Esclusioni: opere strutturali non comprese.
Offerta valida 30 giorni. IVA 10% inclusa.
Totale preventivo € 24.500,00
"""

INCOMPLETE = """
Preventivo lavori appartamento
Demolizioni e nuove finiture a corpo.
Pagamento da concordare.
Totale lavori 19.900,00 euro
"""


class PreventivoCheckTests(unittest.TestCase):
    def test_extracts_italian_total(self):
        self.assertEqual(extract_total(COMPLETE), Decimal("24500.00"))

    def test_scores_document_completeness(self):
        result = analyze_quote_text(COMPLETE, "A.pdf")
        self.assertEqual(result["total"], Decimal("24500.00"))
        self.assertGreaterEqual(result["score"], 90)

    def test_flags_sparse_quote(self):
        result = analyze_quote_text(INCOMPLETE, "B.pdf")
        self.assertLess(result["score"], 40)
        self.assertIn("IVA e aliquota", result["missing"])
        self.assertIn("Oneri di sicurezza", result["missing"])

    def test_compares_totals_and_coverage(self):
        first = analyze_quote_text(COMPLETE, "A.pdf")
        second = analyze_quote_text(INCOMPLETE, "B.pdf")
        result = compare_quotes(first, second)
        self.assertEqual(result["delta"], Decimal("4600.00"))
        self.assertEqual(result["lower"], "B.pdf")
        self.assertIn("IVA e aliquota", result["different_items"])


if __name__ == "__main__":
    unittest.main()
