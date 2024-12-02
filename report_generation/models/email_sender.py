from tqdm import tqdm
from clients.outlook_email_client import OutlookEmailClient
from enums.email_enums import EmailConfig, EmailRecipientType


class EmailSender:
    def __init__(
        self,
        email_secrets: dict,
        email_config: EmailConfig,
        report_summary: dict,
        account_email_mapping: dict | None = None,
    ) -> None:
        self.email_client = OutlookEmailClient(**email_secrets)
        self.report_summary = report_summary
        self.email_config = email_config
        self.account_email_mapping = account_email_mapping

        if self.email_config.recipient_type == EmailRecipientType.ACCOUNT and (
            self.account_email_mapping is None or self.account_email_mapping.empty
        ):
            raise ValueError(
                "Account-based email requires a non-empty account email mapping"
            )

    def _derive_recipients(self, key: str) -> list[str]:
        """Derive email recipients based on recipient type and account mapping.

        Args:
            key: The account key to look up in the mapping

        Returns:
            List of email addresses
        """
        if self.email_config.recipient_type == EmailRecipientType.INTERNAL:
            return self.email_config.default_recipients

        mapped_email = self.account_email_mapping.get(key)
        return [mapped_email] if mapped_email else self.email_config.default_recipients

    def send_emails(self) -> None:
        """Sends individual emails for each entry in report_summary"""
        with self.email_client:
            for key, attachment in tqdm(
                self.report_summary.items(), desc="Sending emails"
            ):
                for recipient_email in self._derive_recipients(key):
                    self.email_client.send_email(
                        recipient_email=recipient_email,
                        subject=self.email_config.subject,
                        body=self.email_config.body,
                        attachments=[attachment],
                    )
