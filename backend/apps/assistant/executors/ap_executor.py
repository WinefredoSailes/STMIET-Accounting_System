from __future__ import annotations

from django.db.models import Count, Sum

from .base_executor import BaseExecutor, Group


class APExecutor(BaseExecutor):
    module_name = "ap"
    screen_key = "supplier_list"

    def _query(self) -> list[Group]:
        from apps.ap.models import (
            Supplier, CheckVoucher, PurchaseOrder, RFPDocument,
            CONSOBatch, AdvanceToEmployee,
        )

        h_cv = self._has("cv", "check", "voucher", "disburse")
        h_po = self._has("po", "purchase")
        h_rfp = self._has("rfp")
        h_conso = self._has("conso", "batch")
        h_adv = self._has("advance")
        h_sup = self._has("supplier", "vendor", "payee")
        any_doc = any([h_cv, h_po, h_rfp, h_conso, h_adv])
        # Only fan out across every AP doc type when the user named a real
        # item/word but NOT a document type (e.g. "tire"). If they named a
        # type (CV, RFP...), stay on exactly that type.
        fan_out = self.is_text_search and not any_doc

        show_suppliers = h_sup or not any_doc
        show_cvs = h_cv or fan_out
        show_pos = h_po or fan_out
        show_rfps = h_rfp or fan_out
        show_consos = h_conso or fan_out
        show_advances = h_adv or fan_out

        groups: list[Group] = []

        if show_suppliers:
            qs = Supplier.objects.select_related("default_segment").annotate(
                total_amount=Sum("cv__gross_amount", default=0),
                total_cv=Count("cv", distinct=True),
                total_po=Count("pos", distinct=True),
            )
            groups.append(self._make_group(
                "Suppliers", qs,
                lambda s: {
                    "type": "supplier", "id": s.id, "name": s.name,
                    "code": s.code, "total_po": s.total_po, "total_cv": s.total_cv,
                    "amount": str(s.total_amount or 0),
                    "link": f"/ap/ledger/{s.id}/",
                },
                search_fields=["name", "code", "owner_name"],
                amount_field="total_amount", order=("name",),
            ))

        if show_cvs:
            qs = CheckVoucher.objects.select_related("payee", "rfp", "created_by", "approved_by")
            groups.append(self._make_group(
                "Check Vouchers", qs,
                lambda c: {
                    "type": "check_voucher", "id": c.id, "name": c.cv_number,
                    "code": c.cv_number, "payee": c.payee.name if c.payee_id else "",
                    "amount": str(c.net_amount), "status": c.status,
                    "date": c.cv_date.isoformat() if c.cv_date else None,
                    "by": (c.created_by.get_full_name() or c.created_by.username) if c.created_by_id else "",
                    "link": f"/ap/cv/{c.id}/",
                },
                search_fields=["cv_number", "payee__name", "check_no", "rfp__particulars"],
                date_field="cv_date", status_field="status",
                status_map={"pending": ["created"], "approved": ["cleared"],
                            "posted": ["cleared"], "cleared": ["cleared"],
                            "rejected": ["rejected"]},
                amount_field="net_amount",
            ))

        if show_pos:
            qs = PurchaseOrder.objects.select_related("supplier", "created_by")
            groups.append(self._make_group(
                "Purchase Orders", qs,
                lambda p: {
                    "type": "purchase_order", "id": p.id, "name": p.po_number,
                    "code": p.po_number, "supplier": p.supplier.name if p.supplier_id else "",
                    "amount": str(p.amount), "status": p.status,
                    "date": p.po_date.isoformat() if p.po_date else None,
                    "by": (p.created_by.get_full_name() or p.created_by.username) if p.created_by_id else "",
                    "link": f"/ap/pos/{p.id}/",
                },
                search_fields=["po_number", "supplier__name", "particulars"],
                date_field="po_date", status_field="status",
                status_map={"pending": ["prepared", "submitted"], "approved": ["approved"]},
                amount_field="amount",
            ))

        if show_rfps:
            qs = RFPDocument.objects.select_related("payee", "created_by")
            groups.append(self._make_group(
                "RFPs", qs,
                lambda r: {
                    "type": "rfp", "id": r.id, "name": r.ap_number,
                    "code": r.ap_number, "payee": r.payee.name if r.payee_id else "",
                    "amount": str(r.amount), "status": r.status,
                    "date": r.rfp_date.isoformat() if r.rfp_date else None,
                    "by": (r.created_by.get_full_name() or r.created_by.username) if r.created_by_id else "",
                    "link": f"/ap/rfps/{r.id}/",
                },
                search_fields=["ap_number", "payee__name", "particulars", "purpose"],
                date_field="rfp_date", status_field="status",
                status_map={"pending": ["prepared", "submitted"],
                            "approved": ["fin_approved", "posted"],
                            "posted": ["posted"], "submitted": ["submitted"]},
                amount_field="amount",
            ))

        if show_consos:
            qs = CONSOBatch.objects.all()
            groups.append(self._make_group(
                "CONSO Batches", qs,
                lambda c: {
                    "type": "conso", "id": c.id, "name": c.batch_no,
                    "code": c.batch_no, "amount": str(c.total_amount),
                    "status": c.status, "date": c.conso_date.isoformat() if c.conso_date else None,
                    "link": f"/ap/conso/{c.id}/",
                },
                search_fields=["batch_no"],
                date_field="conso_date", status_field="status",
                status_map={"pending": ["open"], "approved": ["posted"],
                            "posted": ["posted"], "rejected": ["rejected"]},
                amount_field="total_amount",
            ))

        if show_advances:
            qs = AdvanceToEmployee.objects.all()
            groups.append(self._make_group(
                "Advances to Employees", qs,
                lambda a: {
                    "type": "advance", "id": a.id, "name": a.employee_name,
                    "code": a.kind, "amount": str(a.amount),
                    "status": a.status, "date": a.granted_date.isoformat() if a.granted_date else None,
                    "link": "/ap/advances/",
                },
                search_fields=["employee_name"],
                date_field="granted_date", status_field="status",
                status_map={"pending": ["granted"], "liquidated": ["liquidated"]},
                amount_field="amount",
            ))

        return groups
