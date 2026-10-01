from __future__ import annotations

from .base_executor import BaseExecutor, Group


class FoundationExecutor(BaseExecutor):
    module_name = "foundation"
    screen_key = "coa_list"

    def _query(self) -> list[Group]:
        from apps.foundation.models import Account, Company

        filtered = not self.browsing
        want_accounts = filtered or self._has("account", "coa", "chart") or not self._has("company")
        want_companies = filtered or self._has("company", "entity", "segment")

        groups: list[Group] = []
        if want_accounts:
            qs = Account.objects.select_related("parent")
            groups.append(self._make_group(
                "COA Accounts", qs,
                lambda a: {
                    "type": "account", "id": a.id, "name": a.name, "code": a.code,
                    "account_type": a.account_type, "link": f"/reports/ledger/{a.id}/",
                },
                search_fields=["code", "name", "description"],
            ))
        if want_companies:
            qs = Company.objects.all()
            groups.append(self._make_group(
                "Companies", qs,
                lambda c: {
                    "type": "company", "id": c.id, "name": c.name,
                    "code": c.code, "link": "/",
                },
                search_fields=["code", "name"],
            ))
        return groups
