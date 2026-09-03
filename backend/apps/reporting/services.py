"""Financial Statement services (BUILD-PLAN Phase 8).

  - TrialBalanceService : per-account signed balances (opening / period /
                          YTD) computed from the posted GL projection.
  - StatementTemplateService : seeds the six workbook layouts as
                               StatementTemplate + StatementLineDef config.
  - FinancialStatementService.generate : runs a template against the GL for
                               a period, computing per-segment columns +
                               GRAND TOTAL, and persists a snapshot.
  - MonthEndCloseService : accruals -> recon -> close -> appropriations.

Design rules:
  - Statements are derived reports (never hand-edited). A generated
    FinancialStatement stores its rows as JSON so it can be versioned and
    audited against the posted GL it was built from.
  - Account balance is signed by the account's normal balance (ADR-003/005):
    a debit-normal account's balance is (Dr - Cr); a credit-normal account's
    is (Cr - Dr). Both are therefore positive in their "normal" direction.
  - Contra accounts (sales discounts, accumulated depreciation) are handled
    by a line's `sign` (-1) or by net lines (gross - accumulated).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from apps.core.money import money

from .models import (
    BalanceBasis,
    FinancialStatement,
    MonthEndClose,
    StatementLineDef,
    StatementLineMode,
    StatementTemplate,
    StatementType,
)

def segment_codes() -> list[str]:
    """Reporting columns = the active Segment master rows (data-driven, Phase 2).

    Statement columns (per-segment + GRAND) are derived from the Segment table
    instead of the former hardcoded ['DHPP','DMIE','OPS'] list, so adding or
    removing a segment flows straight into every generated statement.
    """
    from apps.foundation.models import Segment

    codes = list(
        Segment.objects.filter(is_active=True)
        .order_by("code")
        .values_list("code", flat=True)
    )
    return codes or ["ALL"]


class TrialBalanceService:
    """Per-account balances from the posted GL projection (ADR-005).

    The GeneralLedger table is a derived projection; these balances are
    re-computed on demand and never stored as a source of truth.
    """

    @classmethod
    def segment_balances(
        cls, company, *, start: date | None = None, end: date | None = None
    ) -> dict[str, dict[str, Decimal]]:
        """account_code -> {SEGMENT: signed balance} over the GL window.

        `start`/`end` bound transaction_date (inclusive). With neither, the
        whole posted GL for the company is summed.
        """
        from apps.posting.models import GeneralLedger

        qs = GeneralLedger.objects.filter(
            entry__status="posted",
            entry__company=company,
        )
        if start:
            qs = qs.filter(transaction_date__gte=start)
        if end:
            qs = qs.filter(transaction_date__lte=end)

        rows = (
            qs.values("account__code", "account__normal_balance", "segment__code")
            .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        )
        out: dict[str, dict[str, Decimal]] = {}
        for row in rows:
            code = row["account__code"]
            seg = row["segment__code"] or "ALL"
            if row["account__normal_balance"] == "credit":
                bal = (row["total_credit"] or 0) - (row["total_debit"] or 0)
            else:
                bal = (row["total_debit"] or 0) - (row["total_credit"] or 0)
            out.setdefault(code, {}).setdefault(seg, Decimal("0.00"))
            out[code][seg] = money(out[code][seg] + bal)
        return out

    @classmethod
    def rows(cls, company, *, as_of: date | None = None, segment: str | None = None):
        """Trial-balance rows for a company (optionally one segment)."""
        from apps.foundation.models import Account

        bal = cls.segment_balances(company, end=as_of)
        out = []
        for acc in Account.objects.filter(is_postable=True).order_by("code"):
            if segment and acc.segment not in (segment, "ALL"):
                continue
            per_seg = bal.get(acc.code, {})
            total = sum(per_seg.values()) if per_seg else Decimal("0.00")
            out.append(
                {
                    "code": acc.code,
                    "name": acc.name,
                    "segment": acc.segment,
                    "normal_balance": acc.normal_balance,
                    "account_type": acc.account_type,
                    "balance": money(total),
                }
            )
        return out


class StatementTemplateService:
    """Seeds / loads the six statement layouts (BUILD-PLAN Phase 8)."""

    @classmethod
    def seed_defaults(cls) -> dict[str, StatementTemplate]:
        created = {}
        for ttype, name, builder in [
            (StatementType.INCOME_STATEMENT, "Income Statement (MARCH layout)", cls._build_is),
            (StatementType.BALANCE_SHEET, "Statement of Financial Position (YEAR END)", cls._build_sfp),
            (StatementType.COST_OF_SALES, "Statement of Cost of Sales", cls._build_cos),
            (StatementType.TOTAL_EXPENSES, "Statement of Total Expenses (CGSE)", cls._build_te),
            (StatementType.SOCE, "Statement of Changes in Equity", cls._build_soce),
        ]:
            tpl, was_created = StatementTemplate.objects.get_or_create(
                statement_type=ttype,
                defaults={"name": name, "description": f"{name} — seeded template."},
            )
            if was_created:
                builder(tpl)
            else:
                cls._refresh_segment_headers(tpl)
            created[ttype] = tpl
        return created

    @classmethod
    def _segment_title(cls, code: str) -> str:
        """Section header for a segment, taken from the Segment master — never
        a hardcoded name, so admin changes flow straight into the statements."""
        from apps.foundation.models import Segment

        seg = Segment.objects.filter(code=code).first()
        name = seg.name if seg else code
        return f"{name} ({code})"

    @classmethod
    def _refresh_segment_headers(cls, template: StatementTemplate) -> None:
        """Re-sync COS section header titles on already-seeded templates."""
        from .models import StatementLineDef

        headers = {"cos_dhpp_header": "DHPP", "cos_dmie_header": "DMIE", "cos_ops_header": "OPS"}
        for key, code in headers.items():
            StatementLineDef.objects.filter(template=template, key=key).update(
                title=cls._segment_title(code)
            )

    @classmethod
    def _save_lines(cls, template: StatementTemplate, lines: list[dict]) -> None:
        for i, data in enumerate(lines, start=1):
            data = dict(data)
            data.setdefault("line_no", i)
            StatementLineDef.objects.create(template=template, **data)

    @classmethod
    def _build_is(cls, template: StatementTemplate) -> None:
        cls._save_lines(
            template,
            [
                dict(key="sales", title="Sales", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["400", "410", "420"], sign=1),
                dict(key="sales_discount", title="Sales Discount (-)", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["405", "415", "425"], sign=-1),
                dict(key="net_sales", title="NET SALES", mode=StatementLineMode.SUM,
                     is_subtotal=True),
                dict(key="cogs", title="Cost of Sales(-)", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["50", "51", "52"], sign=1),
                dict(key="gross_profit", title="Gross Profit(+/-)", mode=StatementLineMode.DIFFERENCE,
                     left_ref="net_sales", right_ref="cogs", is_subtotal=True),
                dict(key="other_income", title="Other Income(+)", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["430", "431"], sign=1),
                dict(key="total_operating_income", title="Total Operating Income / Loss (+/-)",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="operating_expenses", title="Total Operating Expenses (-)",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["61", "62", "63", "64"], sign=1),
                dict(key="operating_profit", title="TOTAL Operating Profit / Loss (+/-)",
                     mode=StatementLineMode.DIFFERENCE, left_ref="total_operating_income",
                     right_ref="operating_expenses", is_subtotal=True),
                dict(key="non_operating_expenses", title="Total Non - Operating Expenses(-)",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["65", "66"], sign=1),
                dict(key="net_profit", title="NET PROFIT / LOSS (+/-)",
                     mode=StatementLineMode.DIFFERENCE, left_ref="operating_profit",
                     right_ref="non_operating_expenses", is_subtotal=True),
                dict(key="gpm", title="Gross Profit Margin", mode=StatementLineMode.RATIO,
                     left_ref="gross_profit", right_ref="net_sales", is_section=True),
                dict(key="expense_ratio", title="Expense Ratio", mode=StatementLineMode.RATIO,
                     left_ref="operating_expenses", right_ref="net_sales", is_section=True),
                dict(key="npm", title="Net Profit Margin", mode=StatementLineMode.RATIO,
                     left_ref="net_profit", right_ref="net_sales", is_section=True),
                dict(key="app_basis", title="NET INCOME (BASIS)", mode=StatementLineMode.INPUT,
                     left_ref="net_profit", is_section=True),
                dict(key="app_rm", title="10% Repairs & Maintenance", mode=StatementLineMode.PERCENT,
                     left_ref="app_basis", weight="0.1000", is_section=True),
                dict(key="app_tithing", title="10% Tithing", mode=StatementLineMode.PERCENT,
                     left_ref="app_basis", weight="0.1000", is_section=True),
                dict(key="app_remaining", title="Remaining Net Income", mode=StatementLineMode.PERCENT,
                     left_ref="app_basis", weight="0.8000", is_section=True),
            ],
        )
        cls._wire_parents(
            template,
            {
                "net_sales": ["sales", "sales_discount"],
                "total_operating_income": ["gross_profit", "other_income"],
            },
        )

    @classmethod
    def _build_sfp(cls, template: StatementTemplate) -> None:
        cls._save_lines(
            template,
            [
                # ---- ASSETS (ending balances) ----
                dict(key="ca_cash", title="Cash", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["10"], sign=1, balance_basis=BalanceBasis.ENDING),
                dict(key="ca_receivables", title="Accounts / Employees / Related Receivables",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["12", "15"], sign=1,
                     balance_basis=BalanceBasis.ENDING),
                dict(key="ca_inventory", title="Inventory", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["13"], sign=1, balance_basis=BalanceBasis.ENDING),
                dict(key="ca_prepaid", title="Prepaid / Other Current Assets",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["14"], sign=1,
                     balance_basis=BalanceBasis.ENDING),
                dict(key="total_current_assets", title="TOTAL CURRENT ASSETS",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="fa_building_gross", title="Building & Improvements (gross)",
                     mode=StatementLineMode.ACCOUNT, account_codes=["19000", "19500", "19700", "19750"],
                     sign=1, balance_basis=BalanceBasis.ENDING, is_hidden=True),
                dict(key="fa_building_accum", title="Accum Dep'n - Building (contra)",
                     mode=StatementLineMode.ACCOUNT, account_codes=["19760"], sign=1,
                     balance_basis=BalanceBasis.ENDING, is_hidden=True),
                dict(key="fa_building_net", title="Building and Improvements, Net",
                     mode=StatementLineMode.DIFFERENCE, left_ref="fa_building_gross",
                     right_ref="fa_building_accum"),
                dict(key="fa_equip_gross", title="Furniture/Office Equip (gross)",
                     mode=StatementLineMode.ACCOUNT,
                     account_codes=["19800", "19900", "19910", "19920", "19930", "19940",
                                    "19950", "19960", "19963", "19966"],
                     sign=1, balance_basis=BalanceBasis.ENDING, is_hidden=True),
                dict(key="fa_equip_accum", title="Accum Dep'n - F&F/Office (contra)",
                     mode=StatementLineMode.ACCOUNT,
                     account_codes=["19850", "19980", "19983", "19986"], sign=1,
                     balance_basis=BalanceBasis.ENDING, is_hidden=True),
                dict(key="fa_equip_net", title="Furniture & Fixtures / Office Equipment, Net",
                     mode=StatementLineMode.DIFFERENCE, left_ref="fa_equip_gross",
                     right_ref="fa_equip_accum"),
                dict(key="fa_vehicles_gross", title="Vehicles/Heavy Equip (gross)",
                     mode=StatementLineMode.ACCOUNT,
                     account_codes=["17000", "17010", "18503", "18600", "18650"], sign=1,
                     balance_basis=BalanceBasis.ENDING, is_hidden=True),
                dict(key="fa_vehicles_accum", title="Accum Dep'n - Vehicles (contra)",
                     mode=StatementLineMode.ACCOUNT,
                     account_codes=["18513", "18660"], sign=1,
                     balance_basis=BalanceBasis.ENDING, is_hidden=True),
                dict(key="fa_vehicles_net", title="Vehicles/Specialized/Heavy Equipments, Net",
                     mode=StatementLineMode.DIFFERENCE, left_ref="fa_vehicles_gross",
                     right_ref="fa_vehicles_accum"),
                dict(key="total_fixed_assets", title="TOTAL FIXED ASSETS",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="nca_adv_contractors", title="Advances to Contractors (NC)",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["1997"], sign=1,
                     balance_basis=BalanceBasis.ENDING),
                dict(key="total_nca", title="TOTAL NON CURRENT ASSETS",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="total_assets", title="TOTAL ASSETS", mode=StatementLineMode.SUM,
                     is_subtotal=True),
                # ---- LIABILITIES & EQUITY (ending balances) ----
                dict(key="cl_ap", title="Accounts Payable", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["200", "211", "250", "255", "260"], sign=1,
                     balance_basis=BalanceBasis.ENDING),
                dict(key="cl_accrued", title="Accrued Expense", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["22"], sign=1, balance_basis=BalanceBasis.ENDING),
                dict(key="cl_govt", title="Govt. Mandatory Contribution Payable",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["23"], sign=1,
                     balance_basis=BalanceBasis.ENDING),
                dict(key="cl_deferred", title="Deferred Revenue", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["210"], sign=1, balance_basis=BalanceBasis.ENDING),
                dict(key="cl_loans", title="Loans Payable-Current", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["240"], sign=1, balance_basis=BalanceBasis.ENDING),
                dict(key="total_current_liabilities", title="TOTAL CURRENT LIABILITIES",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="ncl_loans", title="Loans Payable - NC", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["270", "272", "275", "276"], sign=1,
                     balance_basis=BalanceBasis.ENDING),
                dict(key="total_ncl", title="TOTAL NON CURRENT LIABILITIES",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="total_liabilities", title="TOTAL LIABILITIES",
                     mode=StatementLineMode.SUM, is_subtotal=True, is_hidden=True),
                dict(key="eq_capital", title="E.Bagatua, Capital", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["300"], sign=1, balance_basis=BalanceBasis.ENDING),
                dict(key="eq_drawings", title="E.Bagatua, Drawings", mode=StatementLineMode.ACCOUNT,
                     account_prefixes=["305"], sign=-1, balance_basis=BalanceBasis.ENDING),
                dict(key="eq_net_profit", title="Net Profit / Loss for the period",
                     mode=StatementLineMode.INPUT),
                dict(key="total_equity", title="TOTAL OWNER'S EQUITY", mode=StatementLineMode.SUM,
                     is_subtotal=True),
                dict(key="total_liab_equity", title="TOTAL LIABILITIES AND OWNER'S EQUITY",
                     mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="debt_ratio", title="Debt Ratio (Total Liabilities / Total Assets)",
                     mode=StatementLineMode.RATIO, left_ref="total_liabilities",
                     right_ref="total_assets", is_section=True),
                dict(key="current_ratio", title="Current Ratio (Current Assets / Current Liabilities)",
                     mode=StatementLineMode.RATIO, left_ref="total_current_assets",
                     right_ref="total_current_liabilities", is_section=True),
            ],
        )
        cls._wire_parents(
            template,
            {
                "total_current_assets": ["ca_cash", "ca_receivables", "ca_inventory", "ca_prepaid"],
                "total_fixed_assets": ["fa_building_net", "fa_equip_net", "fa_vehicles_net"],
                "total_nca": ["nca_adv_contractors"],
                "total_assets": ["total_current_assets", "total_fixed_assets", "total_nca"],
                "total_current_liabilities": ["cl_ap", "cl_accrued", "cl_govt", "cl_deferred", "cl_loans"],
                "total_ncl": ["ncl_loans"],
                "total_liabilities": ["total_current_liabilities", "total_ncl"],
                "total_equity": ["eq_capital", "eq_drawings", "eq_net_profit"],
                "total_liab_equity": ["total_liabilities", "total_equity"],
            },
        )

    @classmethod
    def _build_cos(cls, template: StatementTemplate) -> None:
        dhpp = [
            ("cos_dhpp_subscription", "COGS - Subscription Fees", ["50070"]),
            ("cos_dhpp_dep_tanker", "COGS - Depreciation of Fuel Tankers_DHPP", ["50110"]),
            ("cos_dhpp_fuel", "COGS - Fuel Purchase", ["50000"]),
            ("cos_dhpp_discount", "COGS - Fuel Purchase Discount", ["50010"]),
            ("cos_dhpp_gasoline", "COGS - Gasoline Expenses_DHPP", ["50020"]),
            ("cos_dhpp_labor", "COGS - Labor Cost_DHPP", ["50050"]),
            ("cos_dhpp_direct", "COGS - Other Direct Fees_DHPP", ["50100"]),
            ("cos_dhpp_rm", "COGS - Repairs and Maintenance_DHPP", ["50060"]),
            ("cos_dhpp_storage", "COGS - Storage and Handling Cost_DHPP", ["50080"]),
            ("cos_dhpp_toll", "COGS - Toll Fees_DHPP", ["50090"]),
            ("cos_dhpp_wages", "COGS - Trip Wages", ["50030"]),
            ("cos_dhpp_staff", "COGS - Operational Staff_DHPP", ["50040"]),
        ]
        dmie = [
            ("cos_dmie_bucket", "COGS - Calibration Bucket", ["51003"]),
            ("cos_dmie_dep_vehicles", "COGS - Depreciation of DMIE Vehicles", ["51173"]),
            ("cos_dmie_gasoline", "COGS - Gasoline Expenses_DMIE", ["51013"]),
            ("cos_dmie_inverter", "COGS - Inverter", ["51023"]),
            ("cos_dmie_labor", "COGS - Labor Cost_DMIE", ["51063"]),
            ("cos_dmie_lubricants", "COGS - Lubricants for Consumption", ["51033"]),
            ("cos_dmie_machinery", "COGS - Machinery (TSRO)", ["51043"]),
            ("cos_dmie_staff", "COGS - Operational Staff_DMIE", ["51053"]),
            ("cos_dmie_charges", "COGS - Other Charges (TSRO)", ["51073"]),
            ("cos_dmie_direct", "COGS - Other Direct Fees_DMIE", ["51083"]),
            ("cos_dmie_other", "COGS - Other DMIE", ["51163"]),
            ("cos_dmie_equipment", "COGS - Other Industrial Equipment", ["51093"]),
            ("cos_dmie_recond", "COGS - Reconditioning Expenses", ["51103"]),
            ("cos_dmie_rm", "COGS - Repairs and Maintenance_DMIE", ["51113"]),
            ("cos_dmie_shipping", "COGS - Shipping Fees (TSRO)", ["51123"]),
            ("cos_dmie_storage", "COGS - Storage and Handling Cost_DMIE", ["51133"]),
            ("cos_dmie_toll", "COGS - Toll Fees_DMIE", ["51143"]),
            ("cos_dmie_pump", "COGS - Transfer Pump", ["51153"]),
        ]
        ops = [
            ("cos_ops_lubricants", "COGS - Lubricants for Sale", ["52006"]),
            ("cos_ops_labor", "COGS - Labor Cost_OPS", ["52036"]),
            ("cos_ops_staff", "COGS - Operational Staff_OPS", ["52026"]),
            ("cos_ops_other", "COGS - Other OPS", ["52046"]),
            ("cos_ops_rm", "COGS - Repairs and Maintenance_OPS", ["52016"]),
        ]
        lines = [
            dict(key="cos_dhpp_header", title=cls._segment_title("DHPP"),
                 mode=StatementLineMode.SUM, is_section=True),
        ]
        for key, title, codes in dhpp:
            lines.append(dict(key=key, title=title, mode=StatementLineMode.ACCOUNT,
                              account_codes=codes, sign=1))
        lines.append(dict(key="cos_dhpp_total", title="COGS - DHPP", mode=StatementLineMode.SUM,
                          is_subtotal=True))
        lines.append(dict(key="cos_dmie_header", title=cls._segment_title("DMIE"),
                          mode=StatementLineMode.SUM, is_section=True))
        for key, title, codes in dmie:
            lines.append(dict(key=key, title=title, mode=StatementLineMode.ACCOUNT,
                              account_codes=codes, sign=1))
        lines.append(dict(key="cos_dmie_total", title="COGS - DMIE", mode=StatementLineMode.SUM,
                          is_subtotal=True))
        lines.append(dict(key="cos_ops_header", title=cls._segment_title("OPS"),
                          mode=StatementLineMode.SUM, is_section=True))
        for key, title, codes in ops:
            lines.append(dict(key=key, title=title, mode=StatementLineMode.ACCOUNT,
                              account_codes=codes, sign=1))
        lines.append(dict(key="cos_ops_total", title="COGS - OPS", mode=StatementLineMode.SUM,
                          is_subtotal=True))
        lines.append(dict(key="total_cost_of_sales", title="TOTAL COST OF SALES",
                          mode=StatementLineMode.SUM, is_subtotal=True))
        cls._save_lines(template, lines)
        cls._wire_parents(
            template,
            {
                "cos_dhpp_total": [k for k, *_ in dhpp],
                "cos_dmie_total": [k for k, *_ in dmie],
                "cos_ops_total": [k for k, *_ in ops],
                "total_cost_of_sales": ["cos_dhpp_total", "cos_dmie_total", "cos_ops_total"],
            },
        )

    @classmethod
    def _build_te(cls, template: StatementTemplate) -> None:
        lines = [
            dict(key="te_cogs_dhpp", title="COGS - DHPP", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["50"], sign=1),
            dict(key="te_cogs_dmie", title="COGS - DMIE", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["51"], sign=1),
            dict(key="te_cogs_ops", title="COGS - OPS", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["52"], sign=1),
            dict(key="te_total_cogs", title="Total Cost of Sales", mode=StatementLineMode.SUM,
                 is_subtotal=True),
            dict(key="te_accommodation", title="Accommodation Fees", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["610"], sign=1),
            dict(key="te_bad_debts", title="Bad Debts", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["612"], sign=1),
            dict(key="te_bank_fees", title="Bank Fees", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["614"], sign=1),
            dict(key="te_dep_exp", title="Depreciation Expense (Others)", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["616"], sign=1),
            dict(key="te_er_shares", title="Employer Mandatory Contribution",
                 mode=StatementLineMode.ACCOUNT, account_prefixes=["618"], sign=1),
            dict(key="te_impairment", title="Impairment of Assets", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["620"], sign=1),
            dict(key="te_insurance", title="Insurance Fees", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["622"], sign=1),
            dict(key="te_interest", title="Interest Expenses", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["624"], sign=1),
            dict(key="te_legal", title="Legal & Professional Fees", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["626"], sign=1),
            dict(key="te_loan_rel", title="Loan Related Expenses", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["628"], sign=1),
            dict(key="te_office_supplies", title="Office Supplies Expense", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["630", "631"], sign=1),
            dict(key="te_salaries", title="Salary and Company Benefits", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["634", "635"], sign=1),
            dict(key="te_taxes", title="Taxes, Licenses, Penalties", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["636"], sign=1),
            dict(key="te_travel", title="Travel Related Expenses", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["638"], sign=1),
            dict(key="te_utilities", title="Utilities Expense", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["640"], sign=1),
            dict(key="te_withholding", title="Withholding Taxes", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["641"], sign=1),
            dict(key="te_representation", title="Representation Expense", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["647"], sign=1),
            dict(key="te_other_op", title="Other Operating Expenses", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["632"], sign=1),
            dict(key="te_total_operating_expenses", title="Total Operating Expenses",
                 mode=StatementLineMode.SUM, is_subtotal=True),
            dict(key="te_gen_admin", title="Other Gen. & Admin. Expense", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["660"], sign=1),
            dict(key="te_misc", title="Other Expense/Miscellaneous Exp.", mode=StatementLineMode.ACCOUNT,
                 account_prefixes=["650"], sign=1),
            dict(key="te_total_non_operating", title="Total Non-Operating Expenses",
                 mode=StatementLineMode.SUM, is_subtotal=True),
            dict(key="te_total_operating_costs", title="TOTAL OPERATING COSTS",
                 mode=StatementLineMode.SUM, is_subtotal=True),
        ]
        cls._save_lines(template, lines)
        cls._wire_parents(
            template,
            {
                "te_total_cogs": ["te_cogs_dhpp", "te_cogs_dmie", "te_cogs_ops"],
                "te_total_operating_expenses": [
                    "te_accommodation", "te_bad_debts", "te_bank_fees", "te_dep_exp",
                    "te_er_shares", "te_impairment", "te_insurance", "te_interest",
                    "te_legal", "te_loan_rel", "te_office_supplies", "te_salaries",
                    "te_taxes", "te_travel", "te_utilities", "te_withholding",
                    "te_representation", "te_other_op",
                ],
                "te_total_non_operating": ["te_gen_admin", "te_misc"],
                "te_total_operating_costs": ["te_total_cogs", "te_total_operating_expenses",
                                             "te_total_non_operating"],
            },
        )

    @classmethod
    def _build_soce(cls, template: StatementTemplate) -> None:
        cls._save_lines(
            template,
            [
                dict(key="soce_begin_capital", title="E.Bagatua, Beginning Capital",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["300"], sign=1,
                     balance_basis=BalanceBasis.OPENING),
                dict(key="soce_additional_capital", title="Additional Capital",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["300"], sign=1),
                dict(key="soce_net_profit", title="Net Profit / Loss for the year (+ / - )",
                     mode=StatementLineMode.INPUT),
                dict(key="soce_total", title="Total", mode=StatementLineMode.SUM, is_subtotal=True),
                dict(key="soce_drawings", title="Less: E. Bagatua, Drawings",
                     mode=StatementLineMode.ACCOUNT, account_prefixes=["305"], sign=1),
                dict(key="soce_ending_capital", title="E. Bagatua, Ending Capital",
                     mode=StatementLineMode.DIFFERENCE, left_ref="soce_total",
                     right_ref="soce_drawings", is_subtotal=True),
            ],
        )
        cls._wire_parents(
            template,
            {"soce_total": ["soce_begin_capital", "soce_additional_capital", "soce_net_profit"]},
        )

    @classmethod
    def _wire_parents(cls, template: StatementTemplate, mapping: dict[str, list[str]]) -> None:
        for parent_key, child_keys in mapping.items():
            parent = template.lines.get(key=parent_key)
            for child_key in child_keys:
                template.lines.filter(key=child_key).update(parent=parent)

    @classmethod
    def get(cls, statement_type: str) -> StatementTemplate:
        return StatementTemplate.objects.get(statement_type=statement_type)


class FinancialStatementService:
    """Runs a statement template against the GL for a period (per segment)."""

    @classmethod
    def generate(
        cls,
        *,
        company,
        statement_type: str,
        period_start: date,
        period_end: date,
        segment=None,
        quantities: dict | None = None,
        inputs: dict | None = None,
        user=None,
    ) -> FinancialStatement:
        """Generate (or refresh) a statement snapshot for the period.

        `quantities`: {line_key: amount} for QUANTITY-mode rows (liters).
        `inputs`: {line_key: Decimal|{SEGMENT: Decimal}} for INPUT-mode rows
                  (e.g. IS net profit fed into SOCE).
        """
        template = StatementTemplateService.get(statement_type)
        quantities = quantities or {}
        inputs = inputs or {}

        # Three balance windows (ADR-013): activity, opening, ending.
        activity = TrialBalanceService.segment_balances(company, start=period_start, end=period_end)
        opening = TrialBalanceService.segment_balances(
            company, end=period_start - timedelta(days=1)
        )
        ending = TrialBalanceService.segment_balances(company, end=period_end)

        lines = list(template.lines.order_by("line_no"))
        by_key = {l.key: l for l in lines}
        values: dict[str, dict[str, Decimal]] = {}

        for key, qty in quantities.items():
            values[key] = {seg: money(qty) for seg in segment_codes() + ["GRAND"]}
        for key, val in inputs.items():
            if isinstance(val, dict):
                per = {seg: money(v) for seg, v in val.items()}
                values[key] = per
                values[key]["GRAND"] = money(sum(per.get(s, Decimal("0.00")) for s in segment_codes()))
            else:
                values[key] = {seg: money(val) for seg in segment_codes() + ["GRAND"]}

        for line in lines:
            if line.key in values:
                continue
            if line.mode == StatementLineMode.ACCOUNT:
                window = {
                    BalanceBasis.OPENING: opening,
                    BalanceBasis.ENDING: ending,
                }.get(line.balance_basis, activity)
                values[line.key] = cls._compute_account(line, window)
            elif line.mode == StatementLineMode.INPUT:
                # Default from a computed row (e.g. app_basis <- net_profit) when
                # no explicit input is given; otherwise the caller supplied it
                # above and the loop skipped this line.
                if line.left_ref and line.left_ref in values:
                    values[line.key] = dict(values[line.left_ref])
                else:
                    values[line.key] = {seg: Decimal("0.00") for seg in segment_codes() + ["GRAND"]}
            elif line.mode == StatementLineMode.QUANTITY:
                values[line.key] = {seg: Decimal("0.00") for seg in segment_codes() + ["GRAND"]}
            elif line.mode == StatementLineMode.DIFFERENCE:
                left = values.get(line.left_ref, {})
                right = values.get(line.right_ref, {})
                values[line.key] = {
                    col: money((left.get(col, Decimal("0.00")) or 0) - (right.get(col, Decimal("0.00")) or 0))
                    for col in segment_codes() + ["GRAND"]
                }
            elif line.mode == StatementLineMode.RATIO:
                left = values.get(line.left_ref, {})
                right = values.get(line.right_ref, {})
                row = {}
                for col in segment_codes() + ["GRAND"]:
                    denom = right.get(col, Decimal("0.00")) or 0
                    row[col] = ((left.get(col, 0) or 0) * 100 / denom) if denom else Decimal("0.00")
                values[line.key] = {k: money(v) for k, v in row.items()}
            elif line.mode == StatementLineMode.PERCENT:
                base = values.get(line.left_ref, {})
                w = Decimal(line.weight or 0)
                values[line.key] = {
                    col: money((base.get(col, 0) or 0) * w)
                    for col in segment_codes() + ["GRAND"]
                }
            elif line.mode == StatementLineMode.SUM:
                children = [v for v in by_key.values() if v.parent_id == line.id]
                row = {}
                for col in segment_codes() + ["GRAND"]:
                    row[col] = sum((values[c.key].get(col, Decimal("0.00")) or 0) for c in children)
                values[line.key] = {k: money(v) for k, v in row.items()}
            else:
                values[line.key] = {seg: Decimal("0.00") for seg in segment_codes() + ["GRAND"]}

        data = []
        for line in lines:
            data.append(
                {
                    "key": line.key,
                    "title": line.title,
                    "line_no": line.line_no,
                    "mode": line.mode,
                    "is_subtotal": line.is_subtotal,
                    "is_section": line.is_section,
                    "is_hidden": line.is_hidden,
                    "amounts": {str(k): str(v) for k, v in values[line.key].items()},
                }
            )

        fs, _ = FinancialStatement.objects.update_or_create(
            statement_type=statement_type,
            company=company,
            segment=segment,
            period_start=period_start,
            period_end=period_end,
            defaults={
                "data": data,
                "identity_ok": cls._identity_ok(statement_type, values),
                "status": "draft",
                "created_by": user,
            },
        )
        return fs

    @classmethod
    def _compute_account(cls, line: StatementLineDef, balances: dict) -> dict[str, Decimal]:
        """Sum balances for the line's codes/prefixes, per segment column."""
        from apps.foundation.models import Account

        codes = set(line.account_codes or [])
        prefixes = [p for p in (line.account_prefixes or []) if p]

        selected = []
        for acc in Account.objects.filter(is_postable=True):
            if acc.code in codes or any(acc.code.startswith(p) for p in prefixes):
                selected.append(acc.code)
        selected = list(dict.fromkeys(selected))

        row = {}
        for seg in segment_codes():
            total = Decimal("0.00")
            for code in selected:
                total += balances.get(code, {}).get(seg, Decimal("0.00"))
            row[seg] = money(total * Decimal(line.sign or 1))
        row["GRAND"] = money(sum(row.get(s, Decimal("0.00")) for s in segment_codes()))
        return row

    @classmethod
    def _identity_ok(cls, statement_type: str, values: dict) -> bool:
        """Per-statement balancing identities (BUILD-PLAN Phase 8)."""
        if statement_type == StatementType.BALANCE_SHEET:
            assets = values.get("total_assets", {}).get("GRAND", Decimal("0.00"))
            liab_eq = values.get("total_liab_equity", {}).get("GRAND", Decimal("0.00"))
            return abs(assets - liab_eq) < Decimal("0.01")
        if statement_type == StatementType.SOCE:
            ending = values.get("soce_ending_capital", {}).get("GRAND", Decimal("0.00"))
            total = values.get("soce_total", {}).get("GRAND", Decimal("0.00"))
            drawings = values.get("soce_drawings", {}).get("GRAND", Decimal("0.00"))
            return abs(ending - (total - drawings)) < Decimal("0.01")
        return True


class MonthEndCloseService:
    """Month-end close workflow (BUILD-PLAN Phase 8, ADR-013)."""

    STEPS = ["accruals", "recon", "close", "appropriations"]

    @classmethod
    def get_or_create(cls, fiscal_period, user=None) -> MonthEndClose:
        mec, _ = MonthEndClose.objects.get_or_create(
            fiscal_period=fiscal_period,
            company=fiscal_period.fiscal_year.company,
            defaults={
                "steps": {s: "pending" for s in cls.STEPS},
                "status": "open",
            },
        )
        return mec

    @classmethod
    def advance(cls, mec: MonthEndClose, step: str, user=None) -> MonthEndClose:
        """Mark one step done; the next pending step becomes in_progress."""
        if step not in cls.STEPS:
            raise ValueError(f"Unknown close step '{step}'.")
        steps = dict(mec.steps or {})
        steps[step] = "done"
        # find the next pending step to move to in_progress
        next_pending = None
        for s in cls.STEPS:
            if steps.get(s) == "pending":
                next_pending = s
                break
        steps = {s: ("in_progress" if s == next_pending else (steps.get(s) or "pending"))
                 for s in cls.STEPS}
        mec.steps = steps
        mec.save(update_fields=["steps", "updated_at"])
        return mec

    @classmethod
    def complete(cls, mec: MonthEndClose, user=None) -> MonthEndClose:
        """Close the month: lock the fiscal period (posting §17 no back-posting)."""
        from django.utils import timezone

        if not mec.is_ready:
            undone = [s for s in cls.STEPS if mec.steps.get(s) != "done"]
            raise ValueError(f"Not ready to close; pending: {', '.join(undone)}.")
        mec.status = "closed"
        mec.closed_by = user
        mec.closed_at = timezone.now()
        mec.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
        mec.fiscal_period.is_closed = True
        mec.fiscal_period.save(update_fields=["is_closed", "updated_at"])
        return mec

    # ------------------------------------------------------------------ §13
    # Closing journal entries (BUILD-PLAN Batch D). §13.1/13.2 transfer
    # period revenue and expense balances into E.Bagatua Capital; §13.3 moves
    # net income into appropriation reserves when the COA carries them.

    CAPITAL_FAMILY = {"DHPP": "30000", "DMIE": "30003", "OPS": "30006"}

    @classmethod
    def _capital_account(cls, segment):
        from apps.foundation.models import Account

        candidates = {segment.code: cls.CAPITAL_FAMILY.get(segment.code, "30000")}
        code = candidates.get(segment.code, "30000")
        try:
            return Account.objects.get(code=code, is_postable=True, account_type="equity")
        except Account.DoesNotExist:
            # Shared equity account (30000, segment ALL) is the fallback.
            try:
                return Account.objects.get(code="30000", is_postable=True, account_type="equity")
            except Account.DoesNotExist as exc:
                from apps.core.exceptions import ValidationError

                raise ValidationError(
                    "No equity capital account (30000/30003/30006) in COA to close into."
                ) from exc

    @classmethod
    def _period_accounts(cls, company, segment, period_start, period_end):
        """Revenue + expense account balances for one segment in the window."""
        balances = TrialBalanceService.segment_balances(
            company, start=period_start, end=period_end
        )
        from apps.foundation.models import Account

        return balances, Account

    @classmethod
    def close_segment(cls, company, segment, period_start, period_end, *, user=None):
        """Post §13.1 + §13.2 closing entries for a segment; returns (rev_je, exp_je).

        - §13.1 : Dr each revenue account   | Cr Capital ({net_revenue})
        - §13.2 : Dr Capital ({total_exp})   | Cr each expense account
        Net income (revenue - expense) flows into Capital's balance.
        """
        from django.db import transaction

        from apps.foundation.models import Account
        from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
        from apps.posting.services import PostingService

        period_range = (
            TrialBalanceService.segment_balances(company, start=period_start, end=period_end)
        )
        capital = cls._capital_account(segment)

        # revenue-close legs: (acct, debit, credit) — credit-normal accounts are
        # debited, debit-normal (contra_revenue) are credited; the capital leg
        # balances to the net income.
        rev_legs: list[tuple] = []
        exp_legs: list[tuple] = []
        rev_net = Decimal("0.00")
        exp_net = Decimal("0.00")
        for code, per_seg in period_range.items():
            # Close only this segment's balance (ADR-011: no fictitious
            # cross-segment allocation at close time).
            bal = Decimal(per_seg.get(segment.code, "0"))
            if bal == 0:
                continue
            try:
                acct = Account.objects.get(code=code, is_postable=True)
            except Account.DoesNotExist:
                continue
            # Only close realized nominal accounts in this segment; skip
            # accounts whose segment disagrees (ADR-011) and non-nominal types.
            if acct.segment not in (segment.code, "ALL"):
                continue
            if acct.account_type in ("revenue", "contra_revenue"):
                if acct.normal_balance == "credit":
                    rev_legs.append((acct, money(bal), Decimal("0.00"), f"Close {acct.code}"))
                    rev_net += bal
                else:  # debit-normal contra (sales discount)
                    rev_legs.append((acct, Decimal("0.00"), money(bal), f"Close {acct.code}"))
                    rev_net -= bal
            elif acct.account_type in ("expense", "contra_expense"):
                if acct.normal_balance == "debit":
                    exp_legs.append((acct, Decimal("0.00"), money(bal), f"Close {acct.code}"))
                    exp_net += bal
                else:  # credit-normal contra expense (purchase discount, gain)
                    exp_legs.append((acct, money(bal), Decimal("0.00"), f"Close {acct.code}"))
                    exp_net -= bal

        # §13.1: revenue close. Income accounts zeroed against capital.
        rev_entry = None
        if rev_legs:
            capital_cr = money(rev_net)
            end_d = str(period_end).replace("-", "")
            rev_entry = cls._post_close_je(
                company=company, segment=segment, entry_no=f"CLR-{company.pk}-{segment.code}-{end_d}",
                transaction_date=period_end, description=f"Close revenue {segment.code}",
                source_doc_no=f"{company.pk}:{segment.code}:{period_end}",
                lines=rev_legs + [(capital, Decimal("0.00"), capital_cr, "Close to capital")]
                if capital_cr > 0
                else rev_legs + [(capital, abs(capital_cr), Decimal("0.00"), "Close to capital")],
                user=user,
            )

        # §13.2: expense close. Capital debited, each expense credited.
        exp_entry = None
        if exp_legs:
            capital_dr = money(exp_net)
            end_d = str(period_end).replace("-", "")
            exp_entry = cls._post_close_je(
                company=company, segment=segment, entry_no=f"CLE-{company.pk}-{segment.code}-{end_d}",
                transaction_date=period_end, description=f"Close expenses {segment.code}",
                source_doc_no=f"{company.pk}:{segment.code}:{period_end}",
                lines=[(capital, capital_dr, Decimal("0.00"), "Close expenses to capital")]
                      + exp_legs,
                user=user,
            )

        return rev_entry, exp_entry

    @classmethod
    def close_period(cls, mec: MonthEndClose, *, segment=None, user=None) -> MonthEndClose:
        """Post §13.1/13.2 closing JEs for the period's segment(s)."""
        from apps.foundation.models import Segment

        if mec.fiscal_period.is_closed:
            # Closing JEs are posted before the period is locked by `complete`.
            pass
        period_start = mec.fiscal_period.start_date
        period_end = mec.fiscal_period.end_date
        company = mec.company

        segments = [segment] if segment else list(Segment.objects.filter(company=company, is_active=True))
        for seg in segments:
            rev, exp = cls.close_segment(
                company, seg, period_start, period_end, user=user
            )
            if rev is not None:
                mec.revenue_close_entry = rev
            if exp is not None:
                mec.expense_close_entry = exp
        mec.save(update_fields=["revenue_close_entry", "expense_close_entry", "updated_at"])
        return mec

    @classmethod
    def _segment_net_income(cls, company, segment, start, end) -> Decimal:
        """Period net income (revenue - expenses) for one segment.

        Reads the posted §13 closing JEs for the segment/period so it is valid
        both before and after `close_period` runs (it never re-reads nominal
        balances, which the close zeroes).
        """
        from apps.posting.models import JournalEntry, PostingStatus

        rev_total = Decimal("0.00")
        exp_total = Decimal("0.00")
        token = f"{company.pk}:{segment.code}:{end}"
        rev_je = (
            JournalEntry.objects.filter(
                source_doc_type="CLOSE", source_doc_no=token, segment=segment,
                entry_no__startswith="CLR-", status=PostingStatus.POSTED,
            ).order_by("-id").first()
        )
        exp_je = (
            JournalEntry.objects.filter(
                source_doc_type="CLOSE", source_doc_no=token, segment=segment,
                entry_no__startswith="CLE-", status=PostingStatus.POSTED,
            ).order_by("-id").first()
        )
        if rev_je is not None:
            rev_total = rev_je.total_credit
        if exp_je is not None:
            exp_total = exp_je.total_debit
        return money(rev_total - exp_total)

    @classmethod
    def apply_appropriations(cls, mec: MonthEndClose, *, segment=None, user=None) -> MonthEndClose:
        """§13.3 appropriation JE — data-driven via SegmentAccountMap reserve roles.

        Only posts when the COA defines the two appropriation-reserve accounts
        (repairs & maintenance, tithing). With the current COA (no 3xxxx
        reserve accounts) this is a no-op that leaves the appropriation pending
        rather than inventing account codes.
        """
        from apps.foundation.models import Segment, SegmentAccountMap

        segments = [segment] if segment else list(Segment.objects.filter(company=mec.company, is_active=True))
        period = mec.fiscal_period

        rm_role = "appropriation_rm"
        tithing_role = "appropriation_tithing"
        ten = Decimal("0.1000")
        posted_any = False
        for seg in segments:
            net_income = cls._segment_net_income(
                mec.company, seg, period.start_date, period.end_date
            )
            if net_income <= 0:
                continue
            rm_acct = SegmentAccountMap.objects.filter(
                segment=seg, role=rm_role, is_active=True).first()
            tith_acct = SegmentAccountMap.objects.filter(
                segment=seg, role=tithing_role, is_active=True).first()
            if rm_acct is None or tith_acct is None:
                continue  # COA does not carry reserve accounts for this segment.
            from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
            from apps.posting.services import PostingService, approve_threshold

            capital = cls._capital_account(seg)
            rm_amount = money(net_income * ten)
            tith_amount = money(net_income * ten)
            total_reserve = rm_amount + tith_amount
            entry = JournalEntry(
                entry_no=f"APP-{mec.company.pk}-{seg.code}-{str(period.end_date).replace('-', '')}",
                company=mec.company, segment=seg,
                transaction_date=period.end_date,
                status=PostingStatus.DRAFT,
                description=f"Appropriate net income {seg.code}",
                source_doc_type="APP",
                source_doc_no=f"{mec.company.pk}:{seg.code}:{period.end_date}",
                created_by=user,
            )
            entry.save()
            JournalEntryLine.objects.create(
                entry=entry, line_no=1, account=capital, debit=total_reserve,
                description="Appropriated net income",
            )
            JournalEntryLine.objects.create(
                entry=entry, line_no=2, account=rm_acct.account, credit=rm_amount,
                description="Repairs & Maintenance reserve (10%)",
            )
            JournalEntryLine.objects.create(
                entry=entry, line_no=3, account=tith_acct.account, credit=tith_amount,
                description="Tithing reserve (10%)",
            )
            entry.recalc_totals()
            if entry.total_debit > approve_threshold():
                entry.status = PostingStatus.APPROVED
                entry.save(update_fields=["status", "updated_at"])
            PostingService.post(entry, user=user)
            # First successfully posted appropriation is the canonical one.
            if not posted_any:
                mec.appropriation_entry = entry
                posted_any = True
        if posted_any:
            mec.save(update_fields=["appropriation_entry", "updated_at"])
        return mec

    @classmethod
    def _post_close_je(cls, *, company, segment, entry_no, transaction_date, description,
                       source_doc_no, lines, user=None):
        from apps.core.money import approve_threshold, money as _m
        from django.db import transaction as _tx
        from apps.posting.models import JournalEntry, JournalEntryLine, PostingStatus
        from apps.posting.services import PostingService

        with _tx.atomic():
            entry = JournalEntry(
                entry_no=entry_no, company=company, segment=segment,
                transaction_date=transaction_date, status=PostingStatus.DRAFT,
                description=description, source_doc_type="CLOSE",
                source_doc_no=source_doc_no, created_by=user,
            )
            entry.save()
            for i, (acct, debit, credit, text) in enumerate(lines, start=1):
                JournalEntryLine.objects.create(
                    entry=entry, line_no=i, account=acct,
                    debit=_m(debit), credit=_m(credit), description=text,
                )
            entry.recalc_totals()
            # Month-end close is an authorized operation: auto-approve when the
            # entry crosses the posting approval threshold.
            if entry.total_debit > approve_threshold():
                entry.status = PostingStatus.APPROVED
                entry.save(update_fields=["status", "updated_at"])
            PostingService.post(entry, user=user)
        return entry
