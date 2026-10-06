"""Regression tests: name changes during revise/resubmit must persist.

Covers the reported bug — "changed the name to revise the entry, it did not
change when submitted again for approval; all other changes worked" — across
every revise path that carries a name:

- RFP payee (Supplier NAME) — ``RFPService.revise``
- PO supplier (Supplier NAME) — ``PurchaseOrderService.revise``
- Direct CV payee (Supplier NAME + rebuilt JE) — ``CVPaymentService.revise``
- PCF payee_name (free-text NAME) — ``PCFService.revise_replenishment``
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.ap.models import Supplier
from apps.ap.services import CVPaymentService, PurchaseOrderService, RFPService
from apps.cash.services import PCFService
from apps.core.exceptions import ValidationError


@pytest.fixture
def supplier(db, segment):
    return Supplier.objects.create(code="S001", name="Shandong Fuel Depot", default_segment=segment)


@pytest.fixture
def supplier2(db, segment):
    return Supplier.objects.create(code="S002", name="Corrected Vendor Inc", default_segment=segment)


@pytest.fixture
def alywin(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="alywin_rev", password="x")


@pytest.fixture
def head(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="head_rev", password="x")


@pytest.fixture
def pcf_fund(db, segment, accounts):
    from apps.cash.models import PettyCashFund
    from django.contrib.auth import get_user_model

    User = get_user_model()
    custodian = User.objects.create_user(username="leaslyn_rev", password="x")
    return PettyCashFund.objects.create(
        fund_code="general-rev", name="PCF-General (Rev Test)",
        custodian=custodian, imprest_amount=Decimal("20000.00"),
        replenish_trigger_pct=Decimal("0.85"),
        gl_account=accounts["10000"], company=segment.company,
    )


def _rfp_lines(segment):
    return [
        {"side": "dr", "segment": segment, "account_code": "61100",
         "amount": "50000.00", "description": "Fuel delivery"},
        {"side": "cr", "segment": segment, "account_code": "20000",
         "amount": "50000.00", "description": "AP - Fuel"},
    ]


def _rejected_rfp(segment, supplier, alywin, head, accounts, ap_number="A9901"):
    rfp = RFPService.create_rfp(
        ap_number=ap_number, rfp_date=date(2026, 1, 18), payee=supplier,
        segment=segment, lines=_rfp_lines(segment), user=alywin,
    )
    rfp.status = "submitted"
    rfp.save(update_fields=["status", "updated_at"])
    return RFPService.reject(rfp, user=head, note="Wrong vendor.")


class TestRFPRevisePersistsName:
    def test_revise_with_new_payee_persists(self, company, segment, supplier, supplier2,
                                            alywin, head, accounts):
        rfp = _rejected_rfp(segment, supplier, alywin, head, accounts)
        assert rfp.payee_id == supplier.id

        rfp = RFPService.revise(
            rfp, user=alywin, lines=_rfp_lines(segment), purpose="corrected",
            payee=supplier2, segment=segment, rfp_date=date(2026, 1, 20),
        )
        rfp.refresh_from_db()
        assert rfp.payee_id == supplier2.id
        assert rfp.payee.name == "Corrected Vendor Inc"
        assert rfp.rfp_date == date(2026, 1, 20)
        assert rfp.status == "submitted"
        assert rfp.revision_count == 1

    def test_revise_without_header_keeps_old_payee(self, company, segment, supplier,
                                                  alywin, head, accounts):
        """Backward compatibility: old callers passing only lines/purpose keep
        the stored payee (no silent wipe)."""
        rfp = _rejected_rfp(segment, supplier, alywin, head, accounts)
        rfp = RFPService.revise(rfp, user=alywin, lines=_rfp_lines(segment), purpose="x")
        rfp.refresh_from_db()
        assert rfp.payee_id == supplier.id
        assert rfp.status == "submitted"

    def test_revise_new_payee_against_old_po_supplier_rejected(
            self, company, segment, supplier, supplier2, alywin, head, accounts):
        """Changing the payee while keeping a PO of another vendor must fail
        loudly (PO gate re-validated with the NEW payee), never silently."""
        from apps.sequences.models import DocumentSequence

        po = PurchaseOrderService.create_po(
            po_number=DocumentSequence.next_number(
                company=segment.company, form_code="PO", year=2026,
                pattern="PO-{YYYY}-{SEQ:05d}"),
            po_date=date(2026, 1, 5), supplier=supplier, segment=segment,
            lines=[{"pr_number": "", "qty": "10", "unit": "DRUM",
                    "description": "Engine oil", "unit_price": "10000.00"}],
            user=alywin,
        )
        po.status = "approved"
        po.save(update_fields=["status", "updated_at"])

        rfp = RFPService.create_rfp(
            ap_number="A9902", rfp_date=date(2026, 1, 18), payee=supplier,
            segment=segment, lines=_rfp_lines(segment), user=alywin, po=po,
        )
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        rfp = RFPService.reject(rfp, user=head, note="Fix vendor.")
        with pytest.raises(ValidationError, match="same supplier"):
            RFPService.revise(
                rfp, user=alywin, lines=_rfp_lines(segment),
                payee=supplier2, segment=segment,
            )


class TestPORevisePersistsName:
    def _rejected_po(self, segment, supplier, alywin, head):
        from apps.sequences.models import DocumentSequence

        po = PurchaseOrderService.create_po(
            po_number=DocumentSequence.next_number(
                company=segment.company, form_code="PO", year=2026,
                pattern="PO-{YYYY}-{SEQ:05d}"),
            po_date=date(2026, 1, 5), supplier=supplier, segment=segment,
            lines=[{"pr_number": "", "qty": "10", "unit": "DRUM",
                    "description": "Engine oil", "unit_price": "10000.00"}],
            user=alywin,
        )
        po.status = "submitted"
        po.save(update_fields=["status", "updated_at"])
        return PurchaseOrderService.reject(po, user=head, note="Wrong vendor.")

    def test_revise_with_new_supplier_persists(self, company, segment, supplier,
                                               supplier2, alywin, head):
        po = self._rejected_po(segment, supplier, alywin, head)
        po = PurchaseOrderService.revise(
            po, user=alywin,
            lines=[{"pr_number": "", "qty": "10", "unit": "DRUM",
                    "description": "Engine oil", "unit_price": "10000.00"}],
            supplier=supplier2, segment=segment, po_date=date(2026, 1, 9),
        )
        po.refresh_from_db()
        assert po.supplier_id == supplier2.id
        assert po.supplier.name == "Corrected Vendor Inc"
        assert po.po_date == date(2026, 1, 9)
        assert po.status == "submitted"
        assert po.revision_count == 1

    def test_revise_without_header_keeps_old_supplier(self, company, segment, supplier,
                                                      alywin, head):
        po = self._rejected_po(segment, supplier, alywin, head)
        po = PurchaseOrderService.revise(
            po, user=alywin,
            lines=[{"pr_number": "", "qty": "10", "unit": "DRUM",
                    "description": "Engine oil", "unit_price": "10000.00"}],
        )
        po.refresh_from_db()
        assert po.supplier_id == supplier.id


class TestCVRevisePersistsName:
    def test_direct_cv_revise_with_new_payee_persists_and_rebuilds_je(
            self, company, segment, supplier, supplier2, alywin, accounts,
            segment_account_map):
        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0901", cv_date=date(2026, 1, 27),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="10000.00", check_no="CHK-1", user=alywin,
        )
        cv = CVPaymentService.reject(cv, user=alywin, note="Wrong payee")
        cv = CVPaymentService.revise(
            cv, user=alywin, bank_account=accounts["10010"],
            gross_amount="10000.00", withheld_tax="0.00", check_no="CHK-2",
            payee=supplier2,
        )
        cv.refresh_from_db()
        assert cv.payee_id == supplier2.id
        assert cv.status == "created"
        assert cv.revision_count == 1
        assert supplier2.name in cv.journal_entry.description

    def test_rfp_sourced_cv_payee_change_rejected_loudly(
            self, company, segment, supplier, supplier2, alywin, head, accounts,
            segment_account_map):
        """An RFP-sourced CV derives its payee from the posted RFP: attempting
        a different payee must raise, never silently keep the old one."""
        from apps.ap.models import CONSOBatch
        from apps.ap.services import CONSOService
        from apps.sequences.models import DocumentSequence

        rfp = RFPService.create_rfp(
            ap_number="A9903", rfp_date=date(2026, 1, 18), payee=supplier,
            segment=segment, lines=_rfp_lines(segment), user=alywin,
        )
        # Post the RFP straight through to make it CV-eligible.
        rfp.status = "submitted"
        rfp.save(update_fields=["status", "updated_at"])
        for role in ("checked", "acctg_approved"):
            rfp = RFPService.advance_step(rfp, role=role, user=head)
        rfp.finance_notes = "OK for CV test."
        rfp.save(update_fields=["finance_notes", "updated_at"])
        rfp = RFPService.advance_step(rfp, role="fin_approved", user=head)
        batch = CONSOBatch.objects.create(
            batch_no=DocumentSequence.next_number(
                company=segment.company, form_code="CONSO", year=2026,
                pattern="CONSO-{YYYY}-{SEQ:02d}"),
            conso_date=date(2026, 1, 25),
        )
        rfp.conso = batch
        rfp.save(update_fields=["conso", "updated_at"])
        CONSOService.post_batch(batch, user=head)
        rfp.refresh_from_db()
        assert rfp.status == "posted"

        cv = CVPaymentService.create_cv(
            cv_number="CV-2026-0902", cv_date=date(2026, 1, 28),
            payee=supplier, bank_account=accounts["10010"],
            gross_amount="50000.00", rfp=rfp, user=alywin,
        )
        cv = CVPaymentService.reject(cv, user=alywin, note="Fix check no")
        with pytest.raises(ValidationError, match="linked RFP"):
            CVPaymentService.revise(
                cv, user=alywin, bank_account=accounts["10010"],
                gross_amount="50000.00", check_no="CHK-9", payee=supplier2,
            )


class TestReviseViewsEndToEnd:
    """The exact reported flow through HTTP: reject, change the NAME on the
    revise form, resubmit, and the approval queue shows the new name."""

    def test_rfp_revise_post_with_new_payee_persists(
            self, client, company, segment, supplier, supplier2,
            alywin, head, accounts):
        rfp = _rejected_rfp(segment, supplier, alywin, head, accounts,
                            ap_number="A9911")
        client.force_login(alywin)
        resp = client.post(f"/ap/rfps/{rfp.id}/revise/", {
            "payee": str(supplier2.id),
            "segment": str(segment.id),
            "rfp_date": "2026-01-20",
            "purpose": "GEN-FUEL",
            "line_segment": [segment.id, segment.id],
            "line_account": ["61100", "20000"],
            "line_debit": ["35000.00", ""],
            "line_credit": ["", "35000.00"],
            "line_description": ["Fuel purchase", "AP - Corrected Vendor"],
        })
        assert resp.status_code == 302
        rfp.refresh_from_db()
        assert rfp.status == "submitted"
        assert rfp.payee_id == supplier2.id

    def test_po_revise_post_with_new_supplier_persists(
            self, client, company, segment, supplier, supplier2, alywin, head):
        from apps.sequences.models import DocumentSequence

        po = PurchaseOrderService.create_po(
            po_number=DocumentSequence.next_number(
                company=segment.company, form_code="PO", year=2026,
                pattern="PO-{YYYY}-{SEQ:05d}"),
            po_date=date(2026, 1, 5), supplier=supplier, segment=segment,
            lines=[{"pr_number": "", "qty": "10", "unit": "DRUM",
                    "description": "Engine oil", "unit_price": "10000.00"}],
            user=alywin,
        )
        po.status = "submitted"
        po.save(update_fields=["status", "updated_at"])
        po = PurchaseOrderService.reject(po, user=head, note="Wrong vendor.")
        client.force_login(alywin)
        resp = client.post(f"/ap/pos/{po.id}/revise/", {
            "supplier": str(supplier2.id),
            "segment": str(segment.id),
            "po_date": "2026-01-09",
            "line_pr_no": [""],
            "line_qty": ["10"],
            "line_unit": ["DRUM"],
            "line_description": ["Engine oil"],
            "line_unit_price": ["10000.00"],
        })
        assert resp.status_code == 302
        po.refresh_from_db()
        assert po.status == "submitted"
        assert po.supplier_id == supplier2.id


class TestPCFRevisePersistsName:
    def test_revise_with_new_payee_name_persists(self, segment, accounts, pcf_fund):
        from apps.cash.models import PCFReplenishment

        replen = PCFService.request_replenishment(
            pcf_fund,
            [{"account_code": "61100", "account_name": "Cost of Sales",
              "side": "dr", "amount": "5000.00", "description": "Fuel",
              "segment": segment.code}],
            user=pcf_fund.custodian,
        )
        replen.payee_name = "Old Name"
        replen.save(update_fields=["payee_name", "updated_at"])
        PCFService.submit_replenishment(replen, user=pcf_fund.custodian)
        PCFService.reject_replenishment(replen, user=pcf_fund.custodian, note="Fix name")

        replen = PCFService.revise_replenishment(
            replen, user=pcf_fund.custodian, payee_name="Corrected Name",
        )
        replen.refresh_from_db()
        assert replen.payee_name == "Corrected Name"
        assert replen.status == "requested"
        assert replen.amount == Decimal("5000.00")

    def test_revise_without_fields_keeps_old_name(self, segment, accounts, pcf_fund):
        replen = PCFService.request_replenishment(
            pcf_fund,
            [{"account_code": "61100", "account_name": "Cost of Sales",
              "side": "dr", "amount": "5000.00", "description": "Fuel",
              "segment": segment.code}],
            user=pcf_fund.custodian,
        )
        replen.payee_name = "Old Name"
        replen.save(update_fields=["payee_name", "updated_at"])
        PCFService.submit_replenishment(replen, user=pcf_fund.custodian)
        PCFService.reject_replenishment(replen, user=pcf_fund.custodian, note="Fix lines")
        replen = PCFService.revise_replenishment(replen, user=pcf_fund.custodian)
        replen.refresh_from_db()
        assert replen.payee_name == "Old Name"
        assert replen.status == "requested"
