from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MockVendor:
    vendor_id: str
    name: str
    service_type: str
    price: Decimal
    available: bool


class MockVendorService:
    def list_available(self) -> list[MockVendor]:
        return [vendor for vendor in self._vendors() if vendor.available]

    @staticmethod
    def _vendors() -> list[MockVendor]:
        return [
            MockVendor("VEN-001", "Sydney Catering", "Catering", Decimal("3500.00"), True),
            MockVendor("VEN-002", "Harbour Lights", "Lighting", Decimal("1200.00"), True),
            MockVendor("VEN-003", "City Sound", "Audio", Decimal("900.00"), False),
        ]

