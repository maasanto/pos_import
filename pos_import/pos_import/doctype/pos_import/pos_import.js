// Copyright (c) 2025, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("POS Import", {
	refresh(frm) {
		frm.trigger("set_buttons");
	},

	set_buttons(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0) {
			return;
		}

		if (frm.doc.import_file) {
			frm.add_custom_button(__("Preview"), () => frm.trigger("preview_file"));
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
});
