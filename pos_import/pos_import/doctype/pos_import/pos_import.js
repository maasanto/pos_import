// Copyright (c) 2025, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("POS Import", {
	refresh(frm) {
		frm.trigger("set_buttons");
		frm.trigger("render_preview");
	},

	render_preview(frm) {
		if (frm.doc.preview_data) {
			frm.get_field("preview_html").$wrapper.html(frm.doc.preview_data);
		}
	},

	set_buttons(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.docstatus === 0 && frm.doc.import_file) {
			frm.add_custom_button(__("Preview"), () => frm.trigger("preview_file"));
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Reprocess Failed"), () => frm.trigger("reprocess_failed"));

			if (frm.doc.create_draft_invoices) {
				frm.add_custom_button(
					__("Create Payment Entries"),
					() => frm.trigger("create_payment_entries"),
					__("Actions")
				);
			}
		}
	},

	import_file(frm) {
		// Auto-preview when file is uploaded
		if (frm.doc.import_file && !frm.is_new()) {
			frm.trigger("preview_file");
		}
	},

	preview_file(frm) {
		frm.call({
			method: "preview_import",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Parsing file..."),
			callback(r) {
				if (r.message) {
					frm.reload_doc();
				}
			},
		});
	},

	reprocess_failed(frm) {
		frm.call({
			method: "reprocess_failed",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Reprocessing failed invoices..."),
			callback(r) {
				frm.reload_doc();
			},
		});
	},

	create_payment_entries(frm) {
		frm.call({
			method: "create_pending_payment_entries",
			doc: frm.doc,
			freeze: true,
			freeze_message: __("Creating payment entries..."),
			callback(r) {
				frm.reload_doc();
			},
		});
	},
});
