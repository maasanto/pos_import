# Copyright (c) 2025, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def after_install():
	"""Setup default data after app installation."""
	create_item_group()
	create_default_items()
	create_default_customer()
	create_restomax_connector()
	create_restomax_pdf_connector()
	frappe.db.commit()


def get_or_create_root_item_group():
	"""Get or create the root Item Group."""
	root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name")
	if root:
		return root

	root = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
	if root:
		return root

	if not frappe.db.exists("Item Group", "All Item Groups"):
		root_group = frappe.new_doc("Item Group")
		root_group.item_group_name = "All Item Groups"
		root_group.is_group = 1
		root_group.insert(ignore_permissions=True)

	return "All Item Groups"


def create_item_group():
	"""Create POS Import item group."""
	if frappe.db.exists("Item Group", "POS Import"):
		return

	parent = get_or_create_root_item_group()

	item_group = frappe.new_doc("Item Group")
	item_group.item_group_name = "POS Import"
	item_group.parent_item_group = parent
	item_group.insert(ignore_permissions=True)


def get_or_create_default_uom():
	"""Get or create a default Unit of Measure."""
	uom = frappe.db.get_value("UOM", {"name": ["in", ["Unit", "Nos", "Unité"]]}, "name")
	if uom:
		return uom

	uom = frappe.db.get_value("UOM", {}, "name")
	if uom:
		return uom

	if not frappe.db.exists("UOM", "Unit"):
		new_uom = frappe.new_doc("UOM")
		new_uom.uom_name = "Unit"
		new_uom.insert(ignore_permissions=True)

	return "Unit"


def create_default_items():
	"""Create default POS items for common categories."""
	default_uom = get_or_create_default_uom()

	default_items = [
		{
			"item_code": "POS-FOOD",
			"item_name": "Ventes Nourriture POS",
			"description": "Ventes de nourriture importées du POS",
		},
		{
			"item_code": "POS-BEVERAGE",
			"item_name": "Ventes Boissons POS",
			"description": "Ventes de boissons importées du POS",
		},
		{
			"item_code": "POS-OTHER",
			"item_name": "Autres Ventes POS",
			"description": "Autres ventes importées du POS",
		},
	]

	for item_data in default_items:
		if frappe.db.exists("Item", item_data["item_code"]):
			continue

		item = frappe.new_doc("Item")
		item.item_code = item_data["item_code"]
		item.item_name = item_data["item_name"]
		item.description = item_data["description"]
		item.item_group = "POS Import"
		item.stock_uom = default_uom
		item.is_stock_item = 0
		item.include_item_in_manufacturing = 0
		item.insert(ignore_permissions=True)


def get_customer_group():
	"""Get an existing customer group (site must be set up first)."""
	group = frappe.db.get_single_value("Selling Settings", "customer_group")
	if group and frappe.db.exists("Customer Group", group):
		return group

	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	if group:
		return group

	return frappe.db.get_value("Customer Group", {}, "name")


def get_territory():
	"""Get an existing territory (site must be set up first)."""
	territory = frappe.db.get_single_value("Selling Settings", "territory")
	if territory and frappe.db.exists("Territory", territory):
		return territory

	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if territory:
		return territory

	return frappe.db.get_value("Territory", {}, "name")


def get_default_income_account(company):
	"""Get default income account for a company."""
	# Try to get from company default
	income_account = frappe.db.get_value(
		"Company", company, "default_income_account"
	)
	if income_account:
		return income_account

	# Get any income account for this company
	income_account = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_type": "Income Account",
			"is_group": 0,
		},
		"name",
	)
	if income_account:
		return income_account

	# Get any revenue account
	income_account = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"root_type": "Income",
			"is_group": 0,
		},
		"name",
	)
	return income_account


def get_default_tax_account(company):
	"""Get default tax account for a company."""
	# Look for VAT/Sales Tax account
	tax_account = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_type": ["in", ["Tax", "Chargeable"]],
			"is_group": 0,
		},
		"name",
	)
	if tax_account:
		return tax_account

	# Look for any liability account that might be tax-related
	tax_account = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"root_type": "Liability",
			"is_group": 0,
		},
		"name",
		order_by="name",
	)
	return tax_account


def create_default_customer():
	"""Create default POS customer (requires site setup wizard to have been run)."""
	customer_name = "Client Comptoir POS"

	if frappe.db.exists("Customer", customer_name):
		return customer_name

	customer_group = get_customer_group()
	territory = get_territory()

	if not customer_group or not territory:
		frappe.log_error(
			title="POS Import Setup",
			message="Customer Group or Territory not found. Run ERPNext setup wizard first.",
		)
		return None

	customer = frappe.new_doc("Customer")
	customer.customer_name = customer_name
	customer.customer_type = "Individual"
	customer.customer_group = customer_group
	customer.territory = territory
	customer.insert(ignore_permissions=True)

	return customer_name


def create_restomax_connector():
	"""Create default Restomax connector (requires site to be fully set up)."""
	connector_name = "Restomax"

	if frappe.db.exists("POS Connector", connector_name):
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		company = frappe.db.get_value("Company", {}, "name")

	if not company:
		frappe.log_error(
			title="POS Import Setup",
			message="No company found. Restomax connector not created. Run setup wizard first.",
		)
		return

	customer = "Client Comptoir POS"
	if not frappe.db.exists("Customer", customer):
		customer = create_default_customer()

	if not customer:
		frappe.log_error(
			title="POS Import Setup",
			message="Could not create default customer. Restomax connector not created.",
		)
		return

	# Get required accounts
	income_account = get_default_income_account(company)
	tax_account = get_default_tax_account(company)

	if not income_account or not tax_account:
		frappe.log_error(
			title="POS Import Setup",
			message=f"Missing required accounts for company {company}. Income: {income_account}, Tax: {tax_account}",
		)
		return

	connector = frappe.new_doc("POS Connector")
	connector.connector_name = connector_name
	connector.connector_code = "RESTOMAX"
	connector.parser_class = "pos_import.pos_import.parsers.restomax.RestomaxParser"
	connector.file_type = "Excel"
	connector.company = company
	connector.default_customer = customer
	connector.default_income_account = income_account
	connector.default_tax_account = tax_account
	connector.enabled = 1

	default_payments = [
		{"source_code": "580000", "source_name": "Cash", "mode": "Cash"},
		{"source_code": "580100", "source_name": "Carte bancaire", "mode": "Bank Draft"},
		{"source_code": "580200", "source_name": "Ticket Restaurant", "mode": "Bank Draft"},
	]

	for payment in default_payments:
		mode_of_payment = payment["mode"]
		if not frappe.db.exists("Mode of Payment", mode_of_payment):
			mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name")

		if mode_of_payment:
			connector.append(
				"payment_mapping",
				{
					"source_code": payment["source_code"],
					"source_name": payment["source_name"],
					"mode_of_payment": mode_of_payment,
				},
			)

	connector.insert(ignore_permissions=True)


def create_restomax_pdf_connector():
	"""Create Restomax PDF connector for parsing Z-ticket PDFs."""
	connector_name = "Restomax PDF"

	if frappe.db.exists("POS Connector", connector_name):
		return

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		company = frappe.db.get_value("Company", {}, "name")

	if not company:
		return

	customer = "Client Comptoir POS"
	if not frappe.db.exists("Customer", customer):
		customer = create_default_customer()

	if not customer:
		return

	# Get required accounts
	income_account = get_default_income_account(company)
	tax_account = get_default_tax_account(company)

	if not income_account or not tax_account:
		frappe.log_error(
			title="POS Import Setup",
			message=f"Missing required accounts for company {company}. Income: {income_account}, Tax: {tax_account}",
		)
		return

	connector = frappe.new_doc("POS Connector")
	connector.connector_name = connector_name
	connector.connector_code = "RESTOMAX-PDF"
	connector.parser_class = "pos_import.pos_import.parsers.restomax_pdf.RestomaxPDFParser"
	connector.file_type = "PDF"
	connector.company = company
	connector.default_customer = customer
	connector.default_income_account = income_account
	connector.default_tax_account = tax_account
	connector.enabled = 1

	# Item mappings by TVA code (A=21%, B=12%, C=6%, D=0%)
	default_items = [
		{"source_code": "TVA-A", "source_name": "TVA 21%", "item": "POS-BEVERAGE"},
		{"source_code": "TVA-B", "source_name": "TVA 12%", "item": "POS-FOOD"},
		{"source_code": "TVA-C", "source_name": "TVA 6%", "item": "POS-FOOD"},
		{"source_code": "TVA-D", "source_name": "Exonéré TVA", "item": "POS-OTHER"},
	]

	for item_data in default_items:
		item_code = item_data["item"]
		if not frappe.db.exists("Item", item_code):
			item_code = frappe.db.get_value("Item", {}, "name")

		if item_code:
			connector.append(
				"item_mapping",
				{
					"source_code": item_data["source_code"],
					"source_name": item_data["source_name"],
					"item": item_code,
				},
			)

	# Payment mappings
	default_payments = [
		{"source_code": "eft", "source_name": "Carte bancaire", "mode": "Bank Draft"},
		{"source_code": "cash", "source_name": "Espèces", "mode": "Cash"},
		{"source_code": "cheque", "source_name": "Chèque", "mode": "Bank Draft"},
		{"source_code": "ticket", "source_name": "Ticket Restaurant", "mode": "Bank Draft"},
	]

	for payment in default_payments:
		mode_of_payment = payment["mode"]
		if not frappe.db.exists("Mode of Payment", mode_of_payment):
			mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name")

		if mode_of_payment:
			connector.append(
				"payment_mapping",
				{
					"source_code": payment["source_code"],
					"source_name": payment["source_name"],
					"mode_of_payment": mode_of_payment,
				},
			)

	connector.insert(ignore_permissions=True)
