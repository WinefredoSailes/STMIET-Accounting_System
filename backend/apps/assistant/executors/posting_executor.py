from __future__ import annotations

from .base_executor import BaseExecutor, Group


class PostingExecutor(BaseExecutor):
    module_name = "posting"
    screen_key = "je_list"

    def _query(self) -> list[Group]:
        from apps.posting.models import JournalEntry

        qs = JournalEntry.objects.select_related("segment", "company", "created_by", "approved_by")
        return [self._make_group(
            "Journal Entries", qs,
            lambda j: {
                "type": "journal_entry", "id": j.id, "name": j.entry_no,
                "code": j.entry_no, "description": j.description[:120],
                "amount": str(j.total_debit), "date": j.transaction_date.isoformat(),
                "status": j.status,
                "by": (j.created_by.get_full_name() or j.created_by.username) if j.created_by_id else "",
                "link": f"/journal/{j.id}/",
            },
            search_fields=["entry_no", "description", "source_doc_no",
                           "supplier_name", "po", "ref_number"],
            date_field="transaction_date", status_field="status",
            status_map={"pending": ["draft"], "approved": ["posted"],
                        "posted": ["posted"], "reversed": ["reversed"],
                        "draft": ["draft"]},
            amount_field="total_debit",
        )]
