DOC_TYPES = {
    "application_form": ["name", "father_name", "date_of_birth", "mobile", "district",
                         "pin_code", "application_number"],
    "public_notice": ["notice_number", "date", "department", "last_date", "fee"],
    "income_certificate": ["certificate_number", "name", "father_name", "annual_income",
                           "district", "issue_date"],
    "electricity_bill": ["consumer_number", "name", "units_consumed", "bill_amount", "due_date"],
}
ALL_FIELDS = sorted({f for fs in DOC_TYPES.values() for f in fs})

FIELD_LABELS = {
    "name": "Name", "father_name": "Father's name", "date_of_birth": "Date of birth",
    "mobile": "Mobile number", "district": "District", "pin_code": "PIN code",
    "application_number": "Application number", "notice_number": "Notice number",
    "date": "Date", "department": "Department", "last_date": "Last date", "fee": "Fee",
    "certificate_number": "Certificate number", "annual_income": "Annual income",
    "issue_date": "Issue date", "consumer_number": "Consumer number",
    "units_consumed": "Units consumed", "bill_amount": "Bill amount", "due_date": "Due date",
}

DATE_FIELDS = {"date_of_birth", "date", "last_date", "issue_date", "due_date"}
AMOUNT_FIELDS = {"fee", "annual_income", "bill_amount"}
ID_FIELDS = {"application_number", "notice_number", "certificate_number", "consumer_number"}
TEXT_FIELDS = {"name", "father_name", "district", "department"}

LABEL_RULES = [
    ("father_name", ["father", "parent", "husband", "guardian"], []),
    ("date_of_birth", ["birth", "dob", "born"], []),
    ("mobile", ["mobile", "phone", "contact", "cell"], []),
    ("pin_code", ["pin", "postal", "zip", "post code"], []),
    ("consumer_number", ["consumer", "customer", "account no", "user", "connection no"], []),
    ("application_number", ["application"], ["date", "fee"]),
    ("notice_number", ["notice", "notification", "announcement", "advertisement", "publication"], ["date"]),
    ("certificate_number", ["certificate"], ["date", "issue"]),
    ("annual_income", ["income", "earning"], []),
    ("units_consumed", ["unit", "consumption", "consumed", "usage", "used"], []),
    ("bill_amount", ["bill amount", "amount", "total", "payable"], ["date"]),
    ("due_date", ["due", "payment", "pay "], []),
    ("last_date", ["last date", "deadline", "last day", "closing", "final date", "end date"], []),
    ("fee", ["fee", "charge"], []),
    ("department", ["department", "office", "ministry", "section"], []),
    ("issue_date", ["issue", "issued", "granted", "given"], []),
    ("district", ["district"], []),
    ("name", ["name"], []),
    ("date", ["date", "dated"], []),
]

QUESTION_RULES = [
    ("name", ["whose", "in whose name"], ["father"]),
    ("father_name", ["father", "parent", "guardian"], []),
    ("date_of_birth", ["birth", "born", "dob"], []),
    ("mobile", ["mobile", "phone", "contact number", "cell"], []),
    ("pin_code", ["pin", "postal code", "zip"], []),
    ("consumer_number", ["consumer number", "customer number", "consumer no", "account number"], []),
    ("application_number", ["application number", "application no"], []),
    ("notice_number", ["notice number", "notice no", "reference number of the notice"], []),
    ("certificate_number", ["certificate number", "certificate no"], []),
    ("annual_income", ["income", "earn"], []),
    ("units_consumed", ["unit", "consum", "electricity used"], ["consumer number"]),
    ("bill_amount", ["bill amount", "amount", "how much", "payable", "total"], ["fee", "income"]),
    ("due_date", ["due", "pay the bill", "pay by", "payment"], []),
    ("last_date", ["last date", "deadline", "till when", "until when", "by when", "apply by",
                   "last day", "closing date"], []),
    ("fee", ["fee", "charge", "cost to apply"], []),
    ("department", ["department", "which office", "issued the notice", "issued this notice",
                    "who issued", "issuing authority"], []),
    ("issue_date", ["issued on", "issue date", "date of issue", "when was"], []),
    ("district", ["district", "where", "which place"], []),
    ("name", ["name", "who"], []),
    ("date", ["date", "dated", "when"], []),
]

FIELD_SYNONYMS = {
    "last_date": ["due_date"], "due_date": ["last_date"],
    "date": ["issue_date"], "issue_date": ["date"],
    "bill_amount": ["fee", "annual_income"], "fee": ["bill_amount"],
}

DOC_TYPE_KEYWORDS = [
    ("electricity_bill", ["electricity", "power bill", "bill", "energy"]),
    ("income_certificate", ["income certificate", "certificate of income", "income", "certificate"]),
    ("public_notice", ["notice", "notification", "announcement", "circular", "advertisement"]),
    ("application_form", ["application", "form", "request"]),
]


def match_rules(text_en: str, rules) -> str | None:
    t = " " + text_en.lower().replace("’", "'") + " "
    for field, anyof, noneof in rules:
        if any(k in t for k in anyof) and not any(k in t for k in noneof):
            return field
    return None


def resolve_for_doc(field: str | None, doc_type: str | None) -> str | None:
    if not field or not doc_type or doc_type not in DOC_TYPES:
        return field
    allowed = DOC_TYPES[doc_type]
    if field in allowed:
        return field
    for alt in FIELD_SYNONYMS.get(field, []):
        if alt in allowed:
            return alt
    return field
