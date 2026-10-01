from __future__ import annotations

from .base_executor import BaseExecutor, Group


class CashExecutor(BaseExecutor):
    module_name = "cash"
    screen_key = "bank_list"

    def _query(self) -> list[Group]:
        from apps.cash.models import BankAccount, InterAccountTransfer, PettyCashFund

        h_transfer = self._has("transfer", "ftv")
        h_pcf = self._has("pcf", "petty")
        h_bank = self._has("bank", "balance", "cash")
        any_doc = h_transfer or h_pcf
        fan_out = self.is_text_search and not any_doc

        want_banks = h_bank or not any_doc
        want_transfers = h_transfer or fan_out
        want_pcfunds = h_pcf or fan_out

        groups: list[Group] = []

        if want_banks:
            qs = BankAccount.objects.select_related("company")
            groups.append(self._make_group(
                "Bank Accounts", qs,
                lambda b: {
                    "type": "bank_account", "id": b.id, "name": b.name,
                    "code": b.code, "bank": b.bank_name,
                    "account_number": b.account_number,
                    "link": "/cash/banks/",
                },
                search_fields=["name", "code", "bank_name", "account_number"],
            ))

        if want_transfers:
            qs = InterAccountTransfer.objects.select_related("from_account", "to_account")
            groups.append(self._make_group(
                "Transfers", qs,
                lambda t: {
                    "type": "transfer", "id": t.id, "name": t.voucher_no,
                    "code": t.voucher_no or "",
                    "amount": str(t.amount), "purpose": t.purpose[:100],
                    "status": t.status,
                    "date": t.transfer_date.isoformat() if t.transfer_date else None,
                    "link": f"/cash/transfers/{t.id}/",
                },
                search_fields=["voucher_no", "purpose", "reference",
                               "from_account__name", "to_account__name"],
                date_field="transfer_date", status_field="status",
                status_map={"pending": ["requested", "submitted"],
                            "approved": ["approved"], "posted": ["approved"]},
                amount_field="amount",
            ))

        if want_pcfunds:
            qs = PettyCashFund.objects.all()
            groups.append(self._make_group(
                "Petty Cash Funds", qs,
                lambda f: {
                    "type": "pcf_fund", "id": f.id, "name": f.name,
                    "code": f.fund_code, "amount": str(f.imprest_amount),
                    "link": "/cash/pcf/",
                },
                search_fields=["fund_code", "name", "custodian_name"],
                amount_field="imprest_amount",
            ))

        return groups
