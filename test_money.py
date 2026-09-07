import unittest
from decimal import Decimal

from main import extract_product, money


class MoneyParsingTests(unittest.TestCase):
    def test_italian_format(self):
        self.assertEqual(money("1.639,00"), Decimal("1639.00"))
        self.assertEqual(money("1.234.567,89"), Decimal("1234567.89"))

    def test_international_format(self):
        self.assertEqual(money("1,639.00"), Decimal("1639.00"))
        self.assertEqual(money("1,234,567.89"), Decimal("1234567.89"))

    def test_plain_values(self):
        self.assertEqual(money("9,90"), Decimal("9.90"))
        self.assertEqual(money("9.90"), Decimal("9.90"))
        self.assertEqual(money(1.639), Decimal("1.64"))
        self.assertEqual(money("1234.567"), Decimal("1234.57"))
        self.assertEqual(money("1\u00a0639,00"), Decimal("1639.00"))

    def test_invalid_values(self):
        for value in (None, True, "", "EUR 9,90", "1.2.3,00"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    money(value)

    def test_extracts_italian_jsonld_price(self):
        page = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Prodotto di prova",
          "offers": {"@type": "Offer", "price": "1.639,00", "priceCurrency": "EUR"}
        }
        </script>
        """
        product = extract_product(page, "https://example.com/prodotto")
        self.assertEqual(product["price"], "1639.00")
        self.assertEqual(product["currency"], "EUR")


if __name__ == "__main__":
    unittest.main()
