from enums.email_enums import EmailRecipientType


class EmailSender:
    def __init__(
        self,
        email_recipient_type: EmailRecipientType,
        report_summary: dict,
        account_email_mapping: dict | None,
    ) -> None:
        self.email_recipient_type = email_recipient_type
        self.report_summary = report_summary
        self.account_email_mapping = account_email_mapping

        if (
            email_recipient_type == EmailRecipientType.ACCOUNT
            and not account_email_mapping
        ):
            raise ValueError(
                "account_email_mapping is required for account notifications"
            )

    def send_report(self, report) -> None:
        if report.recipient_type.is_internal:
            self._handle_internal_report(report)
        elif report.recipient_type.is_account:
            self._handle_account_reports(report)
