# Copyright (c) 2025, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from pos_import.pos_import.parsers.base import POSReport


class POSImport(Document):
	def get_indicator(self):
		"""Return status indicator for list view."""
		status_map = {
			"Success": ("green", "Success"),
			"Partial Success": ("orange", "Partial Success"),
			"Error": ("red", "Error"),
			"Pending": ("gray", "Pending"),
		}
		return status_map.get(self.import_status, ("gray", "Unknown"))

	def validate(self):
		if not self.import_status:
			self.import_status = "Pending"
		if self.import_file and not self.get("preview_html"):
			self.parse_and_preview()

	def on_submit(self):
		"""Create Sales Invoices for all parsed reports."""
		connector = frappe.get_doc("POS Connector", self.connector)
		reports = self._parse_file()

		log_messages = []
		success_count = 0
		error_count = 0

		for report in reports:
			row = self._find_or_create_report_row(report)

			# Skip reports with no revenue lines (only summary/total lines)
			if not report.lines:
				row.status = "Skipped"
				row.error_message = "No revenue lines found (only summary lines)"
				row.db_update()
				log_messages.append(f"Z-{report.report_number}: Ignoré - Aucune ligne de revenu")
				continue

			try:
				self._validate_tax_amounts(report)
				sales_invoice = self._create_sales_invoice(report, connector)

				row.sales_invoice = sales_invoice.name
				row.status = "Created"
				row.db_update()
				log_messages.append(f"Z-{report.report_number}: Facture {sales_invoice.name} créée")
				success_count += 1

			except Exception as e:
				row.status = "Error"
				row.error_message = str(e)
				row.db_update()
				log_messages.append(f"Z-{report.report_number}: Erreur - {e}")
				error_count += 1
				frappe.log_error(
					title=f"POS Import Error: {self.name} - Z-{report.report_number}",
					message=frappe.get_traceback(),
				)

		self.import_log = "\n".join(log_messages)
		self.db_set("import_log", self.import_log)

		# Set import status based on results
		total = success_count + error_count
		if total == 0:
			import_status = "Error"
		elif error_count == 0:
			import_status = "Success"
		elif success_count == 0:
			import_status = "Error"
		else:
			import_status = "Partial Success"

		self.db_set("import_status", import_status)

	def on_cancel(self):
		"""Cancel all linked Sales Invoices."""
		for row in self.imported_reports:
			if row.sales_invoice:
				si = frappe.get_doc("Sales Invoice", row.sales_invoice)
				if si.docstatus == 1:
					si.cancel()

	@frappe.whitelist()
	def preview_import(self):
		"""Parse file and generate preview HTML."""
		self.parse_and_preview()
		self.save()
		return self.get("preview_html")

	@frappe.whitelist()
	def reprocess_failed(self):
		"""Reprocess failed or pending invoices."""
		if self.docstatus != 1:
			frappe.throw(_("Document must be submitted to reprocess"))

		connector = frappe.get_doc("POS Connector", self.connector)
		reports = self._parse_file()
		log_messages = []

		for row in self.imported_reports:
			if row.status in ("Error", "Pending"):
				report = next((r for r in reports if r.report_number == row.report_number), None)
				if not report:
					continue

				try:
					self._validate_tax_amounts(report)
					sales_invoice = self._create_sales_invoice(report, connector)

					row.sales_invoice = sales_invoice.name
					row.status = "Created"
					row.error_message = None
					row.db_update()
					log_messages.append(f"Z-{report.report_number}: Facture {sales_invoice.name} créée")

				except Exception as e:
					row.status = "Error"
					row.error_message = str(e)
					row.db_update()
					log_messages.append(f"Z-{report.report_number}: Erreur - {e}")
					frappe.log_error(
						title=f"POS Import Reprocess Error: {self.name} - Z-{report.report_number}",
						message=frappe.get_traceback(),
					)

		if log_messages:
			self.import_log = (self.import_log or "") + "\n\n" + "\n".join(log_messages)
			self.db_set("import_log", self.import_log)

		# Recalculate overall status based on all reports
		self.reload()
		success_count = sum(1 for row in self.imported_reports if row.status == "Created")
		error_count = sum(1 for row in self.imported_reports if row.status in ("Error", "Pending"))
		total = len(self.imported_reports)

		if total == 0:
			import_status = "Error"
		elif error_count == 0:
			import_status = "Success"
		elif success_count == 0:
			import_status = "Error"
		else:
			import_status = "Partial Success"

		self.db_set("import_status", import_status)

		frappe.msgprint(_("Reprocessing complete. Check the import log for details."))
		return len(log_messages)

	def parse_and_preview(self):
		"""Parse the file and generate preview data."""
		reports = self._parse_file()
		preview_data = self._get_parser().get_preview_data(reports)

		# Clear existing report rows and create new ones
		self.imported_reports = []
		for report in reports:
			self.append(
				"imported_reports",
				{
					"report_number": report.report_number,
					"report_date": report.report_date,
					"total_amount": float(report.total_gross),
					"status": "Pending",
				},
			)

		self.preview_html = self._render_preview_html(preview_data)

	def _parse_file(self) -> list[POSReport]:
		"""Parse the uploaded file and return list of reports."""
		parser = self._get_parser()
		file_content = self._get_file_content()

		is_valid, error_message = parser.validate_file(file_content)
		if not is_valid:
			frappe.throw(_("Invalid file format: {0}").format(error_message))

		return parser.parse(file_content)

	def _get_parser(self):
		"""Get the parser instance from the connector."""
		connector = frappe.get_doc("POS Connector", self.connector)
		return connector.get_parser()

	def _get_file_content(self) -> bytes:
		"""Get the raw content of the uploaded file."""
		file_doc = frappe.get_doc("File", {"file_url": self.import_file})
		content = file_doc.get_content()

		if isinstance(content, str):
			content = content.encode("utf-8")

		return content

	def _find_or_create_report_row(self, report: POSReport):
		"""Find existing report row or create a new one."""
		for row in self.imported_reports:
			if row.report_number == report.report_number:
				return row

		return self.append(
			"imported_reports",
			{
				"report_number": report.report_number,
				"report_date": report.report_date,
				"total_amount": float(report.total_gross),
				"status": "Pending",
			},
		)

	def _validate_tax_amounts(self, report: POSReport):
		"""Validate that tax amounts are consistent within the Z-ticket itself."""
		# Skip validation if using actual VAT from CSV (vat_by_rate populated)
		# In this case, we trust the VAT amounts from the POS system
		if report.vat_by_rate:
			return

		for line in report.lines:
			if line.tax_rate <= 0:
				continue

			expected_tax = line.net_amount * line.tax_rate / 100
			diff = abs(float(expected_tax) - float(line.tax_amount))

			if diff > 1.0:
				frappe.throw(
					_(
						"Tax discrepancy for {0}: expected {1}, got {2} (difference: {3})"
					).format(
						line.description,
						flt(expected_tax, 2),
						flt(line.tax_amount, 2),
						flt(diff, 2),
					)
				)
			elif diff > 0.01:
				frappe.msgprint(
					_(
						"Minor tax discrepancy for {0}: expected {1}, got {2} (difference: {3})"
					).format(
						line.description,
						flt(expected_tax, 2),
						flt(line.tax_amount, 2),
						flt(diff, 2),
					),
					indicator="orange",
					alert=True,
				)

	def _validate_invoice_against_z_ticket(self, si, report: POSReport):
		"""
		Validate Sales Invoice amounts against Z-ticket before submission.

		Compares:
		- Net total (HT)
		- Tax total (TVA)
		- Grand total (TTC)
		- Payment total

		Raises an error if discrepancies exceed tolerance (1 EUR).
		"""
		tolerance = 1.0  # EUR

		# Z-ticket totals
		z_net = float(report.total_net)
		z_tax = float(report.total_tax)
		z_gross = float(report.total_gross)
		z_payments = float(report.total_payments)

		# Invoice totals (after insert, ERPNext has calculated these)
		inv_net = flt(si.net_total, 2)
		inv_tax = flt(si.total_taxes_and_charges, 2)
		inv_gross = flt(si.grand_total, 2)
		inv_payments = flt(sum(p.amount for p in si.payments), 2)

		errors = []

		# Validate Net Total (HT)
		net_diff = abs(z_net - inv_net)
		if net_diff > tolerance:
			errors.append(
				_("Net Total (HT): Z-ticket={0}, Invoice={1}, Diff={2}").format(
					flt(z_net, 2), inv_net, flt(net_diff, 2)
				)
			)

		# Validate Tax Total (TVA)
		tax_diff = abs(z_tax - inv_tax)
		if tax_diff > tolerance:
			errors.append(
				_("Tax Total (TVA): Z-ticket={0}, Invoice={1}, Diff={2}").format(
					flt(z_tax, 2), inv_tax, flt(tax_diff, 2)
				)
			)

		# Validate Grand Total (TTC)
		gross_diff = abs(z_gross - inv_gross)
		if gross_diff > tolerance:
			errors.append(
				_("Grand Total (TTC): Z-ticket={0}, Invoice={1}, Diff={2}").format(
					flt(z_gross, 2), inv_gross, flt(gross_diff, 2)
				)
			)

		# Validate Payments match Grand Total
		payment_diff = abs(z_payments - inv_payments)
		if payment_diff > tolerance:
			errors.append(
				_("Payments: Z-ticket={0}, Invoice={1}, Diff={2}").format(
					flt(z_payments, 2), inv_payments, flt(payment_diff, 2)
				)
			)

		if errors:
			frappe.throw(
				_("Z-{0}: Invoice amounts do not match Z-ticket:<br>{1}").format(
					report.report_number, "<br>".join(errors)
				),
				title=_("Amount Validation Failed"),
			)

	def _create_sales_invoice(self, report: POSReport, connector) -> "Document":
		"""Create a Sales Invoice for a single POS report."""
		# Check for existing invoice with same Z-ticket (idempotency)
		po_no = f"Z-{report.report_number}"
		existing = frappe.db.get_value(
			"Sales Invoice",
			{"po_no": po_no, "company": connector.company, "docstatus": ["!=", 2]},
			["name", "docstatus"],
			as_dict=True
		)

		if existing:
			if existing.docstatus == 1:
				# Already submitted, return existing
				frappe.msgprint(
					_("Sales Invoice {0} already exists for {1}").format(existing.name, po_no),
					indicator="orange",
					alert=True
				)
				return frappe.get_doc("Sales Invoice", existing.name)
			else:
				# Draft exists, delete and recreate
				frappe.delete_doc("Sales Invoice", existing.name)
				frappe.msgprint(
					_("Deleted existing draft invoice {0} for {1}").format(existing.name, po_no),
					indicator="orange",
					alert=True
				)

		company_currency = frappe.get_cached_value("Company", connector.company, "default_currency")

		# Get a cash account for POS change amount
		cash_account = frappe.db.get_value(
			"Account",
			{"company": connector.company, "account_type": "Cash", "is_group": 0},
			"name"
		)

		# Get default cost center for the company
		cost_center = frappe.db.get_value(
			"Cost Center",
			{"company": connector.company, "is_group": 0},
			"name"
		)

		# Use configured tax account from connector
		tax_account = connector.default_tax_account

		si = frappe.new_doc("Sales Invoice")
		si.customer = connector.default_customer
		si.company = connector.company
		si.currency = company_currency
		si.posting_date = report.report_date
		si.set_posting_time = 1
		si.is_pos = 1
		si.update_stock = 0
		if cash_account:
			si.account_for_change_amount = cash_account

		# Reference to POS report
		si.po_no = f"Z-{report.report_number}"

		# Add items from lines - just HT amounts, no tax calculation
		for line in report.lines:
			# Get item mapping (may be None if using default_unmapped_item)
			item_mapping = connector.get_item_mapping(line.source_code)

			# Get item code from mapping or fallback to default unmapped item
			item_code = item_mapping.item if item_mapping else connector.default_unmapped_item
			if not item_code:
				frappe.throw(
					_(
						"No item mapping found for source code {0}. Please configure the connector or set a default item for unmapped codes."
					).format(line.source_code)
				)

			item = frappe.get_doc("Item", item_code)

			# Determine UOM: use mapping UOM, or fallback to item's selling/stock UOM
			uom = (item_mapping.uom if item_mapping and item_mapping.uom else None) or item.sales_uom or item.stock_uom

			si.append("items", {
				"item_code": item.name,
				"item_name": item.item_name,
				"description": line.description or item.description,
				"qty": 1,
				"uom": uom,
				"rate": float(line.net_amount),
				"income_account": connector.default_income_account,
				"cost_center": cost_center,
			})

		# Add tax rows using actual VAT amounts from CSV (451000 accounts)
		if tax_account and report.vat_by_rate:
			for rate, amount in sorted(report.vat_by_rate.items()):
				si.append(
					"taxes",
					{
						"charge_type": "Actual",
						"account_head": tax_account,
						"cost_center": cost_center,
						"description": f"TVA {rate}%",
						"tax_amount": flt(amount, 2),
					},
				)

		# Add payments
		for payment in report.payments:
			mode_of_payment = connector.get_mode_of_payment_for_source_code(payment.source_code)
			if not mode_of_payment:
				frappe.throw(
					_(
						"No payment mapping found for source code {0}. Please configure the connector."
					).format(payment.source_code)
				)

			si.append(
				"payments",
				{
					"mode_of_payment": mode_of_payment,
					"amount": float(payment.amount),
				},
			)

		si.insert(ignore_permissions=True)

		# Validate invoice amounts against Z-ticket before submission
		self._validate_invoice_against_z_ticket(si, report)

		# Submit only if not creating drafts
		if not connector.create_draft_invoices:
			si.submit()

		return si

	def _render_preview_html(self, preview_data: dict) -> str:
		"""Render preview data as HTML."""
		currency = frappe.get_cached_value("Company", self.company, "default_currency") or "EUR"

		reports_html = ""
		for r in preview_data["reports"]:
			date_str = str(r["report_date"]) if r["report_date"] else ""
			total_str = f"{r['total_gross']:.2f} {currency}"
			reports_html += f"""
			<tr>
				<td>{r['report_number']}</td>
				<td>{date_str}</td>
				<td>{r['line_count']}</td>
				<td>{r['payment_count']}</td>
				<td class="text-right">{total_str}</td>
			</tr>
			"""

		total_revenue_str = f"{preview_data['total_revenue']:.2f} {currency}"
		total_tax_str = f"{preview_data['total_tax']:.2f} {currency}"

		return f"""
		<div class="pos-import-preview">
			<div class="row mb-4">
				<div class="col-md-4">
					<div class="card">
						<div class="card-body text-center">
							<h3 class="mb-0">{preview_data['total_reports']}</h3>
							<p class="text-muted mb-0">{_('Reports')}</p>
						</div>
					</div>
				</div>
				<div class="col-md-4">
					<div class="card">
						<div class="card-body text-center">
							<h3 class="mb-0">{total_revenue_str}</h3>
							<p class="text-muted mb-0">{_('Total Revenue')}</p>
						</div>
					</div>
				</div>
				<div class="col-md-4">
					<div class="card">
						<div class="card-body text-center">
							<h3 class="mb-0">{total_tax_str}</h3>
							<p class="text-muted mb-0">{_('Total Tax')}</p>
						</div>
					</div>
				</div>
			</div>

			<table class="table table-bordered">
				<thead>
					<tr>
						<th>{_('Report #')}</th>
						<th>{_('Date')}</th>
						<th>{_('Lines')}</th>
						<th>{_('Payments')}</th>
						<th class="text-right">{_('Total')}</th>
					</tr>
				</thead>
				<tbody>
					{reports_html}
				</tbody>
			</table>
		</div>
		"""
