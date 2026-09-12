"""Document sequence registry (ADR-032 numbering).

Every business document (CV, PCV, RFP, AR#, SI#, BR#, ...) is numbered by a
per-company, per-year, per-form sequence. The registry is the single source
for numbering so that printed forms match the Excel-era numbering exactly.

Format tokens supported in form patterns (see ADR-032):
    {YYYY} year, {SEQ} zero-padded running number, {MM} month, {CC} cost center
"""

from django.db import IntegrityError, models, transaction

from apps.core.models import AuditableModel

# How many times to retry allocating a number when a concurrent request races
# us to create the same per-company/per-form/per-year sequence row (PostgreSQL
# raises IntegrityError on the fresh-row race; the retry re-reads the row).
MAX_ALLOCATION_RETRIES = 8


class DocumentSequence(AuditableModel):
    """One counter per form per company per year."""

    company = models.ForeignKey(
        "foundation.Company", on_delete=models.PROTECT, related_name="sequences"
    )
    form_code = models.CharField(max_length=32, db_index=True)  # e.g. "RFP", "CV", "AR"
    year = models.PositiveIntegerField()
    pattern = models.CharField(max_length=64, default="{YYYY}-{SEQ:05d}")
    next_seq = models.PositiveBigIntegerField(default=1)
    # Optional 4th segment/cost-center qualifier (ADR-032 GUIDELINES):
    cost_center = models.CharField(max_length=8, blank=True)

    class Meta:
        unique_together = ("company", "form_code", "year", "cost_center")
        ordering = ["form_code", "year"]

    def __str__(self):
        return f"{self.company.code}/{self.form_code}/{self.year} -> {self.next_seq}"

    @classmethod
    def next_number(cls, *, company, form_code, year, cost_center="", pattern=None) -> str:
        """Atomically allocate the next document number.

        Retries a bounded number of times if two requests race to create the
        same sequence row concurrently, so the returned number is unique even
        under load. ``select_for_update`` is a no-op on SQLite, so callers that
        persist a document with the returned number must retry on a duplicate
        key (the counters still advance on each allocation, which is the
        intended ADR-032 numbering behaviour).
        """
        last_exc = None
        for _ in range(MAX_ALLOCATION_RETRIES):
            try:
                with transaction.atomic():
                    seq, _ = cls.objects.select_for_update().get_or_create(
                        company=company,
                        form_code=form_code,
                        year=year,
                        cost_center=cost_center,
                        defaults={"pattern": pattern} if pattern else {},
                    )
                    number = seq.pattern.format(YYYY=year, SEQ=seq.next_seq, MM=0, CC=cost_center)
                    seq.next_seq += 1
                    seq.save(update_fields=["next_seq", "updated_at"])
                    return number
            except IntegrityError as exc:
                last_exc = exc
        raise last_exc