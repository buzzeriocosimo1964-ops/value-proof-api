import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class LandingPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_landing_is_available_without_payment_link(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STRIPE_PAYMENT_LINK_URL", None)
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Il risparmio", response.text)
        self.assertIn("Acquisto temporaneamente non disponibile", response.text)
        self.assertNotIn("href=\"https://buy.stripe.com/", response.text)

    def test_landing_uses_only_a_stripe_payment_link(self):
        link = "https://buy.stripe.com/test_example"
        with patch.dict(os.environ, {"STRIPE_PAYMENT_LINK_URL": link}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'href="{link}"', response.text)

    def test_landing_rejects_an_untrusted_checkout_url(self):
        with patch.dict(os.environ, {"STRIPE_PAYMENT_LINK_URL": "https://example.com/pay"}):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Acquisto temporaneamente non disponibile", response.text)
        self.assertNotIn("example.com/pay", response.text)


if __name__ == "__main__":
    unittest.main()
