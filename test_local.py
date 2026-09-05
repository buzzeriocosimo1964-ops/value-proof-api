
from main import extract_product, make_proof

before = extract_product(open("fixtures/before.html", encoding="utf-8").read(), "https://shop-a.example/item")
after = extract_product(open("fixtures/after.html", encoding="utf-8").read(), "https://shop-b.example/item")
proof = make_proof(before, after)

assert proof["status"] == "VERIFIED", proof
assert proof["verified_value_delta"] == "60.00", proof
assert proof["verification_scope"] == "price_plus_known_shipping", proof
assert proof["identity_method"] == "matching_sku", proof
print("PASS:", proof["status"], proof["verified_value_delta"], proof["currency"])
