"""Business Agents (Stage 2).

Currently contains the Vendor Procurement Manager (KAN-16). Agents do
not import each other; coordination is done by the Supervisor
(out of scope for this task).
"""
from .base import AIAgent
from .vendor_procurement_manager import VendorProcurementManagerAgent

__all__ = ["AIAgent", "VendorProcurementManagerAgent"]
