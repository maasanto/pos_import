# Copyright (c) 2025, Dokos SAS and contributors
# For license information, please see license.txt

import re
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from pos_import.pos_import.parsers.base import BasePOSParser, POSLine, POSPayment, POSReport


class RestomaxPDFParser(BasePOSParser):
	"""
	Parser for Restomax Z-ticket PDF files.

	Extracts data from the structured text format of Z-tickets:
	- Z number and closing date
	- TVA breakdown by rate
	- Payment methods (eft, cash)
	"""

	def validate_file(self, file_content: bytes) -> tuple[bool, str]:
		"""Validate that the file is a valid Restomax Z-ticket PDF."""
		try:
			text = self._extract_text(file_content)
			if not text:
				return False, "Impossible d'extraire le texte du PDF"

			if "Z financier" not in text:
				return False, "Le fichier ne semble pas être un ticket Z Restomax"

			return True, ""
		except Exception as e:
			return False, f"Erreur de lecture du PDF: {e}"

	def parse(self, file_content: bytes) -> list[POSReport]:
		"""Parse the PDF and return list of POS reports."""
		text = self._extract_text(file_content)
		return self._parse_text(text)

	def _extract_text(self, file_content: bytes) -> str:
		"""Extract text from PDF using pdfplumber."""
		try:
			import pdfplumber
		except ImportError:
			raise ImportError(
				"pdfplumber is required for PDF parsing. "
				"Install it with: pip install pdfplumber"
			)

		text_parts = []
		with pdfplumber.open(BytesIO(file_content)) as pdf:
			for page in pdf.pages:
				page_text = page.extract_text()
				if page_text:
					text_parts.append(page_text)

		return "\n".join(text_parts)

	def _parse_text(self, text: str) -> list[POSReport]:
		"""Parse the extracted text and return list of reports."""
		# Split by Z-ticket headers if multiple reports
		z_pattern = r"Z financier (\d+)"
		z_matches = list(re.finditer(z_pattern, text))

		if not z_matches:
			return []

		reports = []
		for i, match in enumerate(z_matches):
			start = match.start()
			end = z_matches[i + 1].start() if i + 1 < len(z_matches) else len(text)
			z_text = text[start:end]
			z_number = match.group(1)

			report = self._parse_single_report(z_number, z_text)
			if report:
				reports.append(report)

		return sorted(reports, key=lambda r: (r.report_date, r.report_number))

	def _parse_single_report(self, z_number: str, text: str) -> POSReport | None:
		"""Parse a single Z-ticket text block."""
		report = POSReport(
			report_number=z_number,
			report_date=self._extract_date(text),
		)

		# Extract TVA breakdown
		tva_lines = self._extract_tva_breakdown(text)
		for tva_line in tva_lines:
			report.lines.append(tva_line)

		# Extract payments
		payments = self._extract_payments(text)
		for payment in payments:
			report.payments.append(payment)

		return report

	def _extract_date(self, text: str) -> datetime.date:
		"""Extract closing date from text."""
		# Pattern: "Date : 01/01/2026 07:42" or "Fermeture : 01/01/2026 07:42"
		patterns = [
			r"Date\s*:\s*(\d{2}/\d{2}/\d{4})",
			r"Fermeture\s*:\s*(\d{2}/\d{2}/\d{4})",
		]

		for pattern in patterns:
			match = re.search(pattern, text)
			if match:
				try:
					return datetime.strptime(match.group(1), "%d/%m/%Y").date()
				except ValueError:
					continue

		return datetime.now().date()

	def _extract_tva_breakdown(self, text: str) -> list[POSLine]:
		"""Extract TVA breakdown lines from text."""
		lines = []

		# Look for TVA table pattern:
		# Code TVA % HTVA TVA % TVAC
		# A 21.0 6.395,04 1.342,96 7.738,00
		# Pattern matches: letter rate htva tva tvac
		tva_pattern = r"^([A-Z])\s+([\d,\.]+)\s+([\d\.\s,]+)\s+([\d\.\s,]+)\s+([\d\.\s,]+)$"

		for line in text.split("\n"):
			line = line.strip()
			match = re.match(tva_pattern, line)
			if match:
				code = match.group(1)
				rate = self._parse_rate(match.group(2))
				htva = self._parse_number(match.group(3))
				tva = self._parse_number(match.group(4))
				tvac = self._parse_number(match.group(5))

				# Skip zero lines
				if htva == 0 and tvac == 0:
					continue

				lines.append(
					POSLine(
						source_code=f"TVA-{code}",
						description=f"TVA {rate}%" if rate > 0 else "Exonéré TVA",
						net_amount=htva,
						tax_rate=rate,
						tax_amount=tva,
						gross_amount=tvac,
					)
				)

		return lines

	def _extract_payments(self, text: str) -> list[POSPayment]:
		"""Extract payment methods from text."""
		payments = []

		# Pattern: "eft - 822x : 8.152,50 EUR" or "cash - 58x (rendu 3) : 59,50 EUR"
		payment_pattern = r"(eft|cash|carte|cb|especes|cheque|ticket)\s*[-–]\s*\d+x?[^:]*:\s*([\d\.\s,]+)\s*EUR"

		for match in re.finditer(payment_pattern, text, re.IGNORECASE):
			payment_type = match.group(1).lower()
			amount = self._parse_number(match.group(2))

			if amount <= 0:
				continue

			# Normalize payment type
			if payment_type in ("eft", "carte", "cb"):
				source_code = "eft"
				source_name = "Carte bancaire"
			elif payment_type in ("cash", "especes"):
				source_code = "cash"
				source_name = "Espèces"
			elif payment_type == "cheque":
				source_code = "cheque"
				source_name = "Chèque"
			elif payment_type == "ticket":
				source_code = "ticket"
				source_name = "Ticket Restaurant"
			else:
				source_code = payment_type
				source_name = payment_type.capitalize()

			payments.append(
				POSPayment(
					source_code=source_code,
					source_name=source_name,
					amount=amount,
				)
			)

		return payments

	def _parse_rate(self, value: str) -> Decimal:
		"""Parse tax rate (uses English decimal notation: 21.0)."""
		if not value:
			return Decimal(0)

		text = value.strip()
		try:
			return Decimal(text).quantize(Decimal("0.01"))
		except Exception:
			return Decimal(0)

	def _parse_number(self, value: str) -> Decimal:
		"""Parse European number format (dot=thousands, comma=decimal)."""
		if not value:
			return Decimal(0)

		# Clean up: remove spaces, replace comma with dot
		text = value.strip()
		text = text.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
		text = text.replace(".", "")  # Remove thousands separator
		text = text.replace(",", ".")  # Decimal separator

		try:
			return Decimal(text).quantize(Decimal("0.01"))
		except Exception:
			return Decimal(0)
