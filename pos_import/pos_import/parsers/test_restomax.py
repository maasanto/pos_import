# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

import unittest
from decimal import Decimal

from pos_import.pos_import.parsers.restomax import RestomaxParser

HEADER_WITHOUT_ID = "N° Z;Date clôture;Compte général;Description;TVA;DEBIT;CREDIT"
HEADER_WITH_ID = "N° Z;Date clôture;ID Restomax;Compte général;Description;TVA;DEBIT;CREDIT"


def csv_without_id(rows: list[tuple]) -> bytes:
	"""(Z, date, account, description, tva, debit, credit)"""
	body = "\n".join(";".join(str(c) for c in r) for r in rows)
	return f"{HEADER_WITHOUT_ID}\n{body}\n".encode()


def csv_with_id(rows: list[tuple]) -> bytes:
	"""(Z, date, id_restomax, account, description, tva, debit, credit)"""
	body = "\n".join(";".join(str(c) for c in r) for r in rows)
	return f"{HEADER_WITH_ID}\n{body}\n".encode()


class TestRestomaxParser(unittest.TestCase):
	"""Behaviour of the Restomax CSV/Excel parser after the dedup workaround was removed."""

	def setUp(self):
		self.parser = RestomaxParser(connector=None)

	def test_validate_without_id_restomax_column(self):
		"""The post-fix Restomax export no longer ships an ID Restomax column — validation must pass."""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "100"),
			]
		)
		valid, err = self.parser.validate_file(content)
		self.assertTrue(valid, msg=f"validation failed: {err!r}")

	def test_validate_rejects_missing_description_column(self):
		"""Without Description, the summary-line filters would silently fail and inflate totals."""
		content = "N° Z;Date clôture;Compte général;TVA;DEBIT;CREDIT\n1;21/01/2026;700000;21;0;100\n".encode()
		valid, err = self.parser.validate_file(content)
		self.assertFalse(valid)
		self.assertIn("Description", err)

	def test_amounts_not_halved(self):
		"""Without the /2 workaround, a single revenue row must be exposed at its raw amount."""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "100"),
				("1", "21/01/2026", "451000", "TVA sur Vente DEFAUT TVA", "21", "0", "21"),
				("1", "21/01/2026", "580000", "DEFAUT PAIEMENT", "0", "121", "0"),
			]
		)
		reports = self.parser.parse(content)
		self.assertEqual(len(reports), 1)
		(report,) = reports
		self.assertEqual(report.total_net, Decimal("100.00"))
		self.assertEqual(report.total_tax, Decimal("21.00"))
		self.assertEqual(report.total_gross, Decimal("121.00"))
		self.assertEqual(report.total_payments, Decimal("121.00"))

	def test_no_dedup_of_legitimately_identical_rows(self):
		"""Two genuinely identical detail rows must both count.

		The old parser silently collapsed them via seen_lines — masking real data.
		"""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "50"),
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "50"),
				("1", "21/01/2026", "451000", "TVA sur Vente DEFAUT TVA", "21", "0", "21"),
				("1", "21/01/2026", "580000", "DEFAUT PAIEMENT", "0", "121", "0"),
			]
		)
		(report,) = self.parser.parse(content)
		self.assertEqual(report.total_net, Decimal("100.00"))
		self.assertEqual(len(report.lines), 2)

	def test_vat_line_with_empty_id_restomax_is_kept(self):
		"""The 'skip VAT lines without ID Restomax' workaround is gone.

		Even when the column is present but empty for a VAT row, the amount must be picked up.
		"""
		content = csv_with_id(
			[
				("1", "21/01/2026", "ITEM1", "700000", "DEFAUT VENTE", "21", "0", "100"),
				("1", "21/01/2026", "", "451000", "TVA sur Vente DEFAUT TVA", "21", "0", "21"),
				("1", "21/01/2026", "PAY1", "580000", "DEFAUT PAIEMENT", "0", "121", "0"),
			]
		)
		(report,) = self.parser.parse(content)
		self.assertEqual(report.total_tax, Decimal("21.00"))

	def test_payment_with_empty_id_restomax_falls_back_to_description(self):
		"""Without ID Restomax on a payment row, source_code must fall back to description."""
		content = csv_with_id(
			[
				("1", "21/01/2026", "ITEM1", "700000", "DEFAUT VENTE", "21", "0", "100"),
				("1", "21/01/2026", "", "451000", "TVA", "21", "0", "21"),
				("1", "21/01/2026", "", "580000", "DEFAUT PAIEMENT", "0", "121", "0"),
			]
		)
		(report,) = self.parser.parse(content)
		(payment,) = report.payments
		self.assertEqual(payment.source_code, "DEFAUT PAIEMENT")

	def test_summary_total_rows_are_skipped(self):
		"""Total CA / Total PAIEMENT / 'total' keyword lines must not feed amounts into the report."""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "100"),
				("1", "21/01/2026", "700000", "Sous-total", "21", "0", "999"),
				("1", "21/01/2026", "451000", "TVA sur Vente DEFAUT TVA", "21", "0", "21"),
				("1", "21/01/2026", "451000", "Total TVA", "0", "0", "999"),
				("1", "21/01/2026", "580000", "Total CA Z 1", "0", "121", "0"),
				("1", "21/01/2026", "580000", "DEFAUT PAIEMENT", "0", "121", "0"),
				("1", "21/01/2026", "580000", "Total PAIEMENT Z 1", "0", "0", "121"),
			]
		)
		(report,) = self.parser.parse(content)
		self.assertEqual(report.total_net, Decimal("100.00"))
		self.assertEqual(report.total_tax, Decimal("21.00"))
		self.assertEqual(report.total_payments, Decimal("121.00"))

	def test_all_summary_report_yields_empty_report(self):
		"""A Z containing only summary rows produces a report with no lines / payments / VAT."""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "Total ventes", "21", "0", "100"),
				("1", "21/01/2026", "580000", "Total CA Z 1", "0", "100", "0"),
				("1", "21/01/2026", "580000", "Total PAIEMENT Z 1", "0", "0", "100"),
			]
		)
		(report,) = self.parser.parse(content)
		self.assertEqual(report.lines, [])
		self.assertEqual(report.payments, [])
		self.assertEqual(report.vat_by_rate, {})

	def test_multiple_z_reports_sorted_by_date_then_number(self):
		content = csv_without_id(
			[
				("2", "22/01/2026", "700000", "DEFAUT VENTE", "21", "0", "100"),
				("2", "22/01/2026", "451000", "TVA", "21", "0", "21"),
				("2", "22/01/2026", "580000", "DEFAUT PAIEMENT", "0", "121", "0"),
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "50"),
				("1", "21/01/2026", "451000", "TVA", "21", "0", "10.5"),
				("1", "21/01/2026", "580000", "DEFAUT PAIEMENT", "0", "60.5", "0"),
			]
		)
		reports = self.parser.parse(content)
		self.assertEqual([r.report_number for r in reports], ["1", "2"])

	def test_negative_revenue_lines_are_included(self):
		"""Refund lines (CREDIT < DEBIT on a 700xxx account) must surface as negative revenue."""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "10", "0"),
				("1", "21/01/2026", "451000", "TVA", "21", "2.1", "0"),
				("1", "21/01/2026", "580000", "DEFAUT PAIEMENT", "0", "0", "12.1"),
			]
		)
		(report,) = self.parser.parse(content)
		self.assertEqual(report.total_net, Decimal("-10.00"))

	def test_amounts_are_rounded_to_2_decimals(self):
		"""Quantization went back to 2 decimals after the halving workaround was removed."""
		content = csv_without_id(
			[
				("1", "21/01/2026", "700000", "DEFAUT VENTE", "21", "0", "33.333"),
				("1", "21/01/2026", "451000", "TVA", "21", "0", "7.001"),
				("1", "21/01/2026", "580000", "DEFAUT PAIEMENT", "0", "40.334", "0"),
			]
		)
		(report,) = self.parser.parse(content)
		(line,) = report.lines
		self.assertEqual(line.net_amount, Decimal("33.33"))
		(payment,) = report.payments
		self.assertEqual(payment.amount, Decimal("40.33"))


if __name__ == "__main__":
	unittest.main()
