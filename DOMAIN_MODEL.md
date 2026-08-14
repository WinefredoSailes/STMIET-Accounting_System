# Django Domain Model

## 1. Foundation Layer

### 1.1 Company
```python
class Company(models.Model):
    code = models.CharField(max_length=20, unique=True)        # STPC
    name = models.CharField(max_length=255)                    # Seven-Trent Machineries...
    address = models.TextField(blank=True)
    tin = models.CharField(max_length=20, blank=True)          # Tax ID
    proprietor = models.CharField(max_length=255, blank=True)  # E. Bagatua
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 1.2 Segment
```python
class Segment(models.Model):
    code = models.CharField(max_length=10, unique=True)        # DHPP, DMIE, OPS
    name = models.CharField(max_length=255)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
```

### 1.3 FiscalYear
```python
class FiscalYear(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    code = models.CharField(max_length=9)                      # "2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)
```

### 1.4 FiscalPeriod
```python
class FiscalPeriod(models.Model):
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE)
    period_number = models.IntegerField()                      # 1-12
    period_code = models.CharField(max_length=6)               # "2026-01"
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)
    is_adjustment = models.BooleanField(default=False)         # For adjustment period

    class Meta:
        unique_together = ('fiscal_year', 'period_number')
```

### 1.5 Account
```python
class Account(models.Model):
    MAJOR_ACCOUNT_CHOICES = [
        ('CURRENT_ASSET', 'Current Assets'),
        ('NON_CURRENT_ASSET', 'Non-Current Assets'),
        ('CURRENT_LIABILITY', 'Current Liability'),
        ('NON_CURRENT_LIABILITY', 'Non-Current Liability'),
        ('EQUITY', 'Equity'),
        ('REVENUE', 'Revenue'),
        ('COST_OF_SALES', 'Cost of Sales'),
        ('OPERATING_EXPENSE', 'Operating Expense'),
        ('NON_OPERATING_EXPENSE', 'Non-Operating Expense'),
    ]
    NORMAL_BALANCE_CHOICES = [('Dr', 'Debit'), ('Cr', 'Credit')]

    code = models.CharField(max_length=20)                      # "10000", "50000"
    title = models.CharField(max_length=255)                    # "Petty Cash Fund"
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT, null=True)
    classification = models.CharField(max_length=255)           # "Cash & Cash in Bank"
    category = models.CharField(max_length=255)                 # "Petty Cash"
    sub_account_group = models.CharField(max_length=255)       # "Current Assets"
    major_account = models.CharField(max_length=50, choices=MAJOR_ACCOUNT_CHOICES)
    normal_balance = models.CharField(max_length=2, choices=NORMAL_BALANCE_CHOICES, default='Dr')

    # Expense dimensions (only relevant for expense accounts)
    behavior = models.CharField(max_length=20, null=True, blank=True)           # Variable, Fixed
    traceability = models.CharField(max_length=20, null=True, blank=True)       # Direct, Indirect
    controllability = models.CharField(max_length=20, null=True, blank=True)     # Controllable, Uncontrollable

    # Metadata
    is_active = models.BooleanField(default=True)
    is_contra = models.BooleanField(default=False)              # Sales Discount, Accum. Dep'n
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True)
    fsli_sequence = models.IntegerField(default=0)              # Order in Financial Statements
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('code', 'segment')
        ordering = ['code']

    @property
    def full_title(self):
        if self.segment:
            return f"{self.title} [{self.segment.code}]"
        return self.title
```

### 1.6 JournalEntry
```python
class JournalEntry(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('POSTED', 'Posted'),
        ('REVERSED', 'Reversed'),
    ]
    SOURCE_CHOICES = [
        ('MANUAL', 'Manual'),
        ('AUTO_AR', 'Auto - AR'),
        ('C', 'Auto - AP'),
        ('AUTO_INV', 'Auto - Inventory'),
        ('AUTO_PAYROLL', 'Auto - Payroll'),
        ('AUTO_PURCHASE', 'Auto - Purchase'),
        ('AUTO_FLEET', 'Auto - Fleet'),
        ('AUTO_DEPR', 'Auto - Depreciation'),
        ('AUTO_CASH', 'Auto - Cash'),
        ('RECURRING', 'Recurring'),
        ('ADJUSTING', 'Adjusting'),
        ('CLOSING', 'Closing'),
    ]

    entry_number = models.CharField(max_length=50, unique=True)  # JE-2026-00001
    description = models.TextField()
    entry_date = models.DateField()
    fiscal_period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='MANUAL')
    is_recurring = models.BooleanField(default=False)
    recurring_schedule = models.CharField(max_length=50, null=True, blank=True)  # cron-like
    is_reversal = models.BooleanField(default=False)
    reversal_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    reversal_date = models.DateField(null=True, blank=True)
    reference_type = models.CharField(max_length=50, null=True, blank=True)  # SI, PO, DV, etc.
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_debit(self):
        return self.lines.aggregate(total=models.Sum('debit'))['total'] or 0

    @property
    def total_credit(self):
        return self.lines.aggregate(total=models.Sum('credit'))['total'] or 0
```

### 1.7 JournalEntryLine
```python
class JournalEntryLine(models.Model):
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    line_number = models.IntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    # Optional: link to source document
    source_type = models.CharField(max_length=50, null=True, blank=True)
    source_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['journal_entry', 'line_number']
```

### 1.8 GeneralLedger
```python
class GeneralLedger(models.Model):
    """Period-end balances per account per segment."""
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT, null=True, blank=True)
    fiscal_period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT)
    beginning_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    ending_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        unique_together = ('account', 'segment', 'fiscal_period')
        indexes = [
            models.Index(fields=['account', 'fiscal_period']),
        ]
```

### 1.9 PostingRule
```python
class PostingRule(models.Model):
    name = models.CharField(max_length=255)                     # "Sales Invoice - Fuel Hauling"
    event_type = models.CharField(max_length=100)               # "sales.invoice.posted"
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def get_lines(self):
        return self.rule_lines.order_by('line_number')

class PostingRuleLine(models.Model):
    rule = models.ForeignKey(PostingRule, on_delete=models.CASCADE, related_name='lines')
    line_number = models.IntegerField()
    debit_account_code_prefix = models.CharField(max_length=20)  # Pattern matching
    credit_account_code_prefix = models.CharField(max_length=20)
    amount_formula = models.CharField(max_length=255)            # "total_amount", "vat_amount"
    condition = models.CharField(max_length=255, null=True, blank=True)  # JSON expression
```

## 2. Order-to-Cash (AR)

### 2.1 Customer
```python
class Customer(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    tin = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    credit_limit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    terms_days = models.IntegerField(default=30)                # Payment terms
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 2.2 SalesInvoice
```python
class SalesInvoice(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('POSTED', 'Posted'),
        ('PAID', 'Paid'),
        ('CANCELLED', 'Cancelled'),
    ]
    si_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    invoice_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    total_gross = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_discount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_net = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True, blank=True)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SalesInvoiceLine(models.Model):
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=16, decimal_places=2)
    discount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)  # Revenue account
```

### 2.3 CollectionReceipt
```python
class CollectionReceipt(models.Model):
    cr_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    receipt_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(max_length=50)            # Cash, Check, Bank Transfer, GCash
    check_number = models.CharField(max_length=50, blank=True)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, null=True)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
    invoice_allocations = models.ManyToManyField(SalesInvoice, through='ReceiptAllocation')
    status = models.CharField(max_length=20, default='POSTED')
    created_at = models.DateTimeField(auto_now_add=True)

class ReceiptAllocation(models.Model):
    receipt = models.ForeignKey(CollectionReceipt, on_delete=models.CASCADE)
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
```

### 2.4 OfficialReceipt
```python
class OfficialReceipt(models.Model):
    or_number = models.CharField(max_length=50, unique=True)
    collection_receipt = models.ForeignKey(CollectionReceipt, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    issued_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    is_printed = models.BooleanField(default=False)
```

### 2.5 CashReceiptJournal
```python
class CashReceiptJournal(models.Model):
    """Daily summary of collections — matches COLLECTIBLES sheet."""
    cycle_start = models.DateField()
    cycle_end = models.DateField()
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)

    # From Distribution & Hauling side
    total_client_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_depot_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    gross_markup = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    # From Finance & Accounting side
    total_deposited = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    borrowings = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    other_payments = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    ending_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    # Reconciliation
    cash_short = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    reconciled = models.BooleanField(default=False)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
```

## 3. Procure-to-Pay (AP)

### 3.1 Supplier
```python
class Supplier(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    tin = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    terms_days = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True)
```

### 3.2 PurchaseRequest
```python
class PurchaseRequest(models.Model):
    pr_number = models.CharField(max_length=50, unique=True)
    requester = models.CharField(max_length=255)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    request_date = models.DateField()
    status = models.CharField(max_length=20, default='DRAFT')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='pr_approved')
    notes = models.TextField(blank=True)

class PurchaseRequestItem(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    estimated_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
```

### 3.3 PurchaseOrder
```python
class PurchaseOrder(models.Model):
    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    order_date = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='DRAFT')  # DRAFT, APPROVED, PARTIAL, RECEIVED, CLOSED
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=16, decimal_places=2)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
```

### 3.4 ReceivingReport
```python
class ReceivingReport(models.Model):
    rr_number = models.CharField(max_length=50, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT)
    received_date = models.DateField()
    received_by = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default='DRAFT')
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)

class ReceivingReportItem(models.Model):
    receiving_report = models.ForeignKey(ReceivingReport, on_delete=models.CASCADE, related_name='items')
    po_item = models.ForeignKey(PurchaseOrderItem, on_delete=models.PROTECT)
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2)
```

### 3.5 SupplierInvoice
```python
class SupplierInvoice(models.Model):
    si_number = models.CharField(max_length=100)                # Supplier's invoice #
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    invoice_date = models.DateField()
    due_date = models.DateField()
    total_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, default='DRAFT')
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, null=True)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = ('supplier', 'si_number')
```

### 3.6 DisbursementVoucher
```python
class DisbursementVoucher(models.Model):
    dv_number = models.CharField(max_length=50, unique=True)
    payee = models.CharField(max_length=255)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    voucher_date = models.DateField()
    total_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, default='DRAFT')   # DRAFT, APPROVED, PAID
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
    # Applied to supplier invoices
    invoice_payments = models.ManyToManyField(SupplierInvoice, through='DVAllocation')

class DVAllocation(models.Model):
    dv = models.ForeignKey(DisbursementVoucher, on_delete=models.CASCADE)
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
```

## 4. Inventory

### 4.1 ProductCategory
```python
class ProductCategory(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    inventory_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='inv_account')
    revenue_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='rev_account')
    cogs_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='cogs_account')
```

### 4.2 Product
```python
class Product(models.Model):
    PRODUCT_TYPE_CHOICES = [
        ('FUEL', 'Fuel'),
        ('LUBRICANT', 'Lubricant'),
        ('SPARE_PART', 'Spare Part'),
        ('EQUIPMENT', 'Industrial Equipment'),
        ('SUPPLIES', 'Supplies/Consumables'),
    ]
    code = models.CharField(max_length=50, unique=True)
    barcode = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=255)
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT)
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    unit_of_measure = models.CharField(max_length=20)           # Liters, Pcs, Units
    is_active = models.BooleanField(default=True)
    is_stockable = models.BooleanField(default=True)
    standard_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
```

### 4.3 Warehouse / Location
```python
class Warehouse(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)                    # Dohinob, San Pedro, Office
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

class StockTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('GR', 'Goods Receipt'),
        ('GI', 'Goods Issue'),
        ('TR', 'Transfer'),
        ('ADJ', 'Adjustment'),
        ('SR', 'Sales Return'),
    ]
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    transaction_type = models.CharField(max_length=3, choices=TRANSACTION_TYPE_CHOICES)
    transaction_date = models.DateTimeField(auto_now_add=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)  # Positive = IN, Negative = OUT
    unit_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    reference_type = models.CharField(max_length=50, null=True, blank=True)
    reference_id = models.IntegerField(null=True, blank=True)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
    remarks = models.TextField(blank=True)

class InventoryBalance(models.Model):
    """Running balance per product per warehouse."""
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)  # Moving average
    total_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'warehouse')

class PhysicalCount(models.Model):
    count_date = models.DateField()
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    system_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    actual_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    variance = models.DecimalField(max_digits=12, decimal_places=2)
    remarks = models.TextField(blank=True)
    is_adjusted = models.BooleanField(default=False)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
```

## 5. Fleet

### 5.1 VehicleType
```python
class VehicleType(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)                    # Fuel Tanker, Boom Truck, Office Vehicle
    asset_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='+')
    depreciation_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='+')
    accum_depreciation_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='+')
```

### 5.2 Vehicle
```python
class Vehicle(models.Model):
    plate_number = models.CharField(max_length=50, unique=True)
    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.PROTECT)
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.IntegerField()
    acquisition_cost = models.DecimalField(max_digits=16, decimal_places=2)
    acquisition_date = models.DateField()
    status = models.CharField(max_length=20, default='ACTIVE')  # ACTIVE, IN_REPAIR, DECOMMISSIONED
    assigned_driver = models.CharField(max_length=255, blank=True)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    asset = models.ForeignKey('Asset', on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
```

### 5.3 Trip
```python
class Trip(models.Model):
    trip_number = models.CharField(max_length=50, unique=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    driver = models.CharField(max_length=255)
    departure_date = models.DateTimeField()
    return_date = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    load_description = models.CharField(max_length=255)
    load_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default='IN_PROGRESS')
    trip_wages = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    toll_fees = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    other_expenses = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
```

### 5.4 FuelConsumption
```python
class FuelConsumption(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, null=True)
    refuel_date = models.DateTimeField()
    liters = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=16, decimal_places=2)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2)
    odometer_reading = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
```

### 5.5 MaintenanceRecord
```python
class MaintenanceRecord(models.Model):
    MAINTENANCE_TYPE_CHOICES = [
        ('ROUTINE', 'Routine'),
        ('REPAIR', 'Repair'),
        ('OVERHAUL', 'Overhaul'),
    ]
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    maintenance_date = models.DateField()
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPE_CHOICES)
    description = models.TextField()
    service_provider = models.CharField(max_length=255)
    cost = models.DecimalField(max_digits=16, decimal_places=2)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)  # COGS or OpEx account
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
```

## 6. Payroll

### 6.1 Employee
```python
class Employee(models.Model):
    LEVEL_CHOICES = [
        ('RF', 'Rank & File'),
        ('SUP', 'Supervisor'),
        ('DH', 'Department Head'),
        ('EXEC', 'Executive'),
    ]
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    position = models.CharField(max_length=255)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    basic_salary = models.DecimalField(max_digits=16, decimal_places=2)
    tax_status = models.CharField(max_length=50, default='S/ME')  # Tax status
    sss_number = models.CharField(max_length=20, blank=True)
    phic_number = models.CharField(max_length=20, blank=True)
    hdmf_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    date_hired = models.DateField()
```

### 6.2 PayrollPeriod
```python
class PayrollPeriod(models.Model):
    code = models.CharField(max_length=50, unique=True)         # "2026-01-15"
    period_start = models.DateField()
    period_end = models.DateField()
    fiscal_period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT)
    is_closed = models.BooleanField(default=False)
```

### 6.3 PayrollRun
```python
class PayrollRun(models.Model):
    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    run_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=20, default='DRAFT')   # DRAFT, POSTED, CLOSED
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)

class PayrollItem(models.Model):
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='items')
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)

    # Earnings
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    overtime_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    load_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    meals_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    thirteenth_month = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Deductions
    sss_ee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    phic_ee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hdmf_ee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    withholding_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Employer contributions
    sss_er = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    phic_er = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hdmf_er = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Net
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
```

## 7. Fixed Assets

### 7.1 AssetCategory
```python
class AssetCategory(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)                    # Building, Vehicle, Office Equipment, etc.
    useful_life_years = models.IntegerField()
    depreciation_method = models.CharField(max_length=50, default='SL')  # Straight Line
    asset_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='+')
    depreciation_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='+')
    accum_depreciation_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='+')
    gain_disposal_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='+')
    loss_disposal_account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, related_name='+')
```

### 7.2 Asset
```python
class Asset(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('DEPRECIATED', 'Fully Depreciated'),
        ('DISPOSED', 'Disposed'),
        ('IMPAIRED', 'Impaired'),
    ]
    asset_code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    acquisition_date = models.DateField()
    acquisition_cost = models.DecimalField(max_digits=16, decimal_places=2)
    salvage_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    useful_life_years = models.IntegerField()
    depreciation_method = models.CharField(max_length=50, default='SL')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    location = models.CharField(max_length=255, blank=True)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)

class DepreciationEntry(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='depreciation_entries')
    fiscal_period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('asset', 'fiscal_period')

class AssetDisposal(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE)
    disposal_date = models.DateField()
    disposal_type = models.CharField(max_length=20)              # SALE, SCRAP, DONATION
    proceeds = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    gain_loss = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
```

## 8. Cash & Bank

### 8.1 BankAccount
```python
class BankAccount(models.Model):
    bank_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=50, unique=True)
    account_name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=20)               # Savings, Checking
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    gl_account = models.ForeignKey(Account, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)
    maintaining_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
```

### 8.2 PettyCashFund
```python
class PettyCashFund(models.Model):
    fund_code = models.CharField(max_length=50, unique=True)
    custodian = models.CharField(max_length=255)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT)
    imprest_amount = models.DecimalField(max_digits=16, decimal_places=2)
    current_balance = models.DecimalField(max_digits=16, decimal_places=2)
    gl_account = models.ForeignKey(Account, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

class PettyCashReplenishment(models.Model):
    pcf = models.ForeignKey(PettyCashFund, on_delete=models.CASCADE)
    replenishment_date = models.DateField()
    total_expenses = models.DecimalField(max_digits=16, decimal_places=2)
    replenishment_amount = models.DecimalField(max_digits=16, decimal_places=2)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, default='APPROVED')

class PettyCashExpense(models.Model):
    replenishment = models.ForeignKey(PettyCashReplenishment, on_delete=models.CASCADE, related_name='expenses')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
```

### 8.3 BankReconciliation
```python
class BankReconciliation(models.Model):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT)
    statement_date = models.DateField()
    book_balance = models.DecimalField(max_digits=16, decimal_places=2)
    bank_balance = models.DecimalField(max_digits=16, decimal_places=2)
    deposits_in_transit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    outstanding_checks = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    other_credits = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    other_charges = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    is_reconciled = models.BooleanField(default=False)
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.SET_NULL, null=True)
```

## 9. Relationships Overview

```
Company
  └── Segment (DHPP, DMIE, OPS)
        ├── Account COA
        ├── Customer / Supplier / Employee
        ├── Product / Warehouse
        ├── Vehicle
        ├── Asset
        └── BankAccount

JournalEntry
  ├── JournalEntryLine → Account
  └── (referenced by all operational modules)

GeneralLedger → Account + Segment + FiscalPeriod

Each operational module creates JournalEntry via PostingRule.
```
