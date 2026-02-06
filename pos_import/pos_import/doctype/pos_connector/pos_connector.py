# Copyright (c) 2025, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class POSConnector(Document):
	def validate(self):
		self.validate_parser_class()

	def validate_parser_class(self):
		"""Validate that the parser class exists and can be imported."""
		if not self.parser_class:
			return

		try:
			frappe.get_attr(self.parser_class)
		except Exception:
			frappe.throw(
				_("Parser class '{0}' not found. Please check the path.").format(
					self.parser_class
				)
			)

	def get_parser(self):
		"""Get an instance of the parser class."""
		parser_class = frappe.get_attr(self.parser_class)
		return parser_class(self)

	def get_item_for_source_code(self, source_code: str) -> str | None:
		"""Get the mapped Item for a source code.

		Falls back to default_unmapped_item if no mapping is found.
		"""
		mapping = self.get_item_mapping(source_code)
		if mapping:
			return mapping.item

		# Use default unmapped item as fallback
		return self.default_unmapped_item if self.default_unmapped_item else None

	def get_item_mapping(self, source_code: str):
		"""Get the full item mapping for a source code."""
		for mapping in self.item_mapping:
			if mapping.source_code == source_code:
				return mapping
		return None

	def get_mode_of_payment_for_source_code(self, source_code: str) -> str | None:
		"""Get the mapped Mode of Payment for a source code."""
		for mapping in self.payment_mapping:
			if mapping.source_code == source_code:
				return mapping.mode_of_payment
		return None
