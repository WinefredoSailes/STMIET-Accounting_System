from django.contrib import admin

from .models import GeneralLedger, JournalEntry, JournalEntryLine, PostingRule, PostingRuleLine


class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 0
    readonly_fields = ("line_no",)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_no", "transaction_date", "status", "total_debit", "total_credit", "source_doc_type", "source_doc_no")
    list_filter = ("status", "company", "segment", "source_doc_type")
    search_fields = ("entry_no", "source_doc_no", "description")
    readonly_fields = ("entry_no", "reversal_token")
    inlines = [JournalEntryLineInline]

    def has_delete_permission(self, request, obj=None):
        # ADR-004: journal entries are never physically deletable.
        return False


@admin.register(GeneralLedger)
class GeneralLedgerAdmin(admin.ModelAdmin):
    list_display = ("transaction_date", "account", "debit", "credit", "company", "segment")
    list_filter = ("company", "segment", "account")
    readonly_fields = tuple(f.name for f in GeneralLedger._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PostingRuleLineInline(admin.TabularInline):
    model = PostingRuleLine
    extra = 1


@admin.register(PostingRule)
class PostingRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "event", "name", "is_active")
    list_filter = ("event", "is_active")
    search_fields = ("code", "name", "event")
    inlines = [PostingRuleLineInline]