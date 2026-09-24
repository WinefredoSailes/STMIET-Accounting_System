# Navigation configuration — single source of truth for sidebar structure.
# Adding a new module = add one dict entry here, zero template edits.

NAV_SECTIONS = [
    {
        'label': None,  # pinned, no accordion
        'pinned': True,
        'items': [
            {'name': 'dashboard', 'label': 'Dashboard', 'icon': 'dashboard', 'pinned': True},
            {'name': 'my_approvals', 'label': 'My Approvals', 'icon': 'bell-alert', 'badge': 'pending_approval_count'},
        ],
    },
    {
        'label': 'Journal',
        'items': [
            {'name': 'je_list', 'label': 'Journal Entries', 'icon': 'document-text'},
            {'name': 'general_journal', 'label': 'General Journal', 'icon': 'table-cells'},
        ],
    },
    {
        'label': 'Fleet',
        'items': [
            {'name': 'fleet_fuel', 'label': 'Fleet Fuel Report', 'icon': 'fire'},
        ],
    },
    {
        'label': 'Foundation',
        'items': [
            {'name': 'coa_list', 'label': 'Chart of Accounts', 'icon': 'hashtag'},
        ],
    },
    {
        'label': 'Receivables (AR)',
        'items': [
            {'name': 'customer_list', 'label': 'Customers', 'icon': 'user-group'},
            {'name': 'si_list', 'label': 'Sales Invoices', 'icon': 'receipt'},
            {'name': 'receipt_list', 'label': 'Acknowledgment Receipts', 'icon': 'document-check'},
            {'name': 'ar_aging', 'label': 'AR Aging / Register', 'icon': 'exclamation-triangle'},
            {'name': 'ar_ledger', 'label': 'AR Subsidiary Ledger', 'icon': 'rectangle-group'},
        ],
    },
    {
        'label': 'Payables (AP)',
        'items': [
            {'name': 'supplier_list', 'label': 'Suppliers', 'icon': 'building-office'},
            {'name': 'po_list', 'label': 'Purchase Orders', 'icon': 'shopping-cart'},
            {'name': 'rfp_list', 'label': 'RFPs (Disbursements)', 'icon': 'credit-card'},
            {'name': 'conso_list', 'label': 'CONSO Batches', 'icon': 'folder-open'},
            {'name': 'cv_list', 'label': 'Check Vouchers', 'icon': 'banknotes'},
            {'name': 'ap_aging', 'label': 'AP Aging / Register', 'icon': 'inbox'},
            {'name': 'ap_ledger', 'label': 'AP Subsidiary Ledger', 'icon': 'archive-box'},
            {'name': 'advances', 'label': 'Advances to Employees', 'icon': 'hand-raised'},
        ],
    },
    {
        'label': 'Billing',
        'items': [
            {'name': 'billing_list', 'label': 'Billing Transactions', 'icon': 'paper-airplane'},
        ],
    },
    {
        'label': 'Cash',
        'items': [
            {'name': 'bank_list', 'label': 'Bank Accounts', 'icon': 'bank'},
            {'name': 'cycle_list', 'label': 'Weekly Cycles', 'icon': 'calendar-days'},
            {'name': 'recon_list', 'label': 'Bank Reconciliation', 'icon': 'magnifying-glass-circle'},
            {'name': 'cash_short_list', 'label': 'Cash Short', 'icon': 'alert-circle'},
            {'name': 'collections_summary', 'label': 'Daily Collections Summary', 'icon': 'download'},
            {'name': 'collectibles', 'label': 'Collectibles Worksheet', 'icon': 'clock'},
            {'name': 'transfers', 'label': 'Inter-Account Transfers', 'icon': 'arrows-right-left'},
            {'name': 'pcf_list', 'label': 'Petty Cash Funds', 'icon': 'puzzle-piece'},
            {'name': 'pcf_replenishment_list', 'label': 'Petty Cash Vouchers', 'icon': 'ticket'},
        ],
    },
    {
        'label': 'Fixed Assets',
        'items': [
            {'name': 'asset_list', 'label': 'Assets', 'icon': 'cube'},
        ],
    },
    {
        'label': 'Tax & Compliance',
        'items': [
            {'name': 'tax_dashboard', 'label': 'Tax Dashboard', 'icon': 'info'},
            {'name': 'tax_vat', 'label': 'VAT (SI level)', 'icon': 'receipt-percent'},
            {'name': 'tax_wht', 'label': 'WHT Certificates', 'icon': 'check'},
            {'name': 'tax_provision', 'label': 'Income Tax Provision', 'icon': 'calculator'},
            {'name': 'tax_calendar', 'label': 'Tax Calendar', 'icon': 'flag'},
        ],
    },
    {
        'label': 'Reports',
        'items': [
            {'name': 'trial_balance', 'label': 'Trial Balance', 'icon': 'scale'},
            {'name': 'ledger_index', 'label': 'Ledger', 'icon': 'book-open',
             'also_active': ['ledger_account_detail']},
            {'name': 'cash_flow', 'label': 'Cash Flow Statement', 'icon': 'trending-up'},
            {'name': 'statement', 'args': ['is'], 'label': 'Income Statement', 'icon': 'document-chart-bar'},
            {'name': 'statement', 'args': ['sfp'], 'label': 'Financial Position', 'icon': 'building-library'},
            {'name': 'statement', 'args': ['cos'], 'label': 'Cost of Sales', 'icon': 'trending-down'},
            {'name': 'statement', 'args': ['te'], 'label': 'Total Expenses', 'icon': 'minus-circle'},
            {'name': 'statement', 'args': ['soce'], 'label': 'Changes in Equity', 'icon': 'circle-stack'},
            {'name': 'month_end_close', 'label': 'Month-End Close', 'icon': 'lock-closed'},
        ],
    },
    {
        'label': 'Settings / Admin',
        # Visible to the superadmin or the Accounting & Finance Head (the head
        # shares user management per the "who does what" policy).
        'superuser_only': True,
        'roles_allowed': ['head'],
        'items': [
            {'name': 'user_management', 'label': 'User Management', 'icon': 'users'},
        ],
    },
]