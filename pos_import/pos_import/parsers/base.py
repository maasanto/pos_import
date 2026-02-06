# Copyright (c) 2025, Dokos SAS and contributors
# For license information, please see license.txt

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from pos_import.pos_import.doctype.pos_connector.pos_connector import POSConnector


@dataclass
class POSLine:
	"""A single line item from a POS report."""

	source_code: str
	description: str
	net_amount: Decimal
	tax_rate: Decimal
	tax_amount: Decimal
	gross_amount: Decimal


@dataclass
class POSPayment:
	"""A payment method entry from a POS report."""

	source_code: str
	source_name: str
	amount: Decimal


@dataclass
class POSReport:
	"""A complete POS report (typically one Z report / closing)."""

	report_number: str
	report_date: date
	lines: list[POSLine] = field(default_factory=list)
	payments: list[POSPayment] = field(default_factory=list)
	vat_by_rate: dict[Decimal, Decimal] = field(default_factory=dict)

	@property
	def total_net(self) -> Decimal:
		return sum((line.net_amount for line in self.lines), Decimal(0))

	@property
	def total_tax(self) -> Decimal:
		# Use actual VAT from CSV if available, otherwise calculate from lines
		if self.vat_by_rate:
			return sum(self.vat_by_rate.values(), Decimal(0))
		return sum((line.tax_amount for line in self.lines), Decimal(0))

	@property
	def total_gross(self) -> Decimal:
		# Use HT + actual VAT if VAT from CSV is available
		if self.vat_by_rate:
			return self.total_net + self.total_tax
		return sum((line.gross_amount for line in self.lines), Decimal(0))

	@property
	def total_payments(self) -> Decimal:
		return sum((payment.amount for payment in self.payments), Decimal(0))


class BasePOSParser(ABC):
	"""Abstract base class for POS file parsers."""

	def __init__(self, connector: "POSConnector"):
		self.connector = connector

	@abstractmethod
	def parse(self, file_content: bytes) -> list[POSReport]:
		"""
		Parse the file content and return a list of POS reports.

		Args:
		        file_content: Raw bytes of the uploaded file

		Returns:
		        List of POSReport objects
		"""

	@abstractmethod
	def validate_file(self, file_content: bytes) -> tuple[bool, str]:
		"""
		Validate that the file is in the expected format.

		Args:
		        file_content: Raw bytes of the uploaded file

		Returns:
		        Tuple of (is_valid, error_message)
		"""

	def get_preview_data(self, reports: list[POSReport]) -> dict:
		"""Generate preview data for UI display."""
		return {
			"total_reports": len(reports),
			"total_revenue": float(sum(r.total_gross for r in reports)),
			"total_tax": float(sum(r.total_tax for r in reports)),
			"total_payments": float(sum(r.total_payments for r in reports)),
			"reports": [
				{
					"report_number": r.report_number,
					"report_date": str(r.report_date),
					"total_gross": float(r.total_gross),
					"total_net": float(r.total_net),
					"total_tax": float(r.total_tax),
					"line_count": len(r.lines),
					"payment_count": len(r.payments),
				}
				for r in reports
			],
		}
