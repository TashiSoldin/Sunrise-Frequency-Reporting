from tqdm import tqdm
from clients.outlook_email_client import OutlookEmailClient
from enums.email_enums import EmailConfig, EmailRecipientType
from helpers.datetime_helper import DatetimeHelper
from helpers.os_helper import OSHelper


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
        self.account_email_mapping = account_email_mapping or {}

    def _send_to_default_recipients(self, attachment: str) -> None:
        """Sends an email with the given attachment to all default recipients."""
        for recipient_email in self.email_config.default_recipients:
            self.email_client.send_email(
                recipient_email=recipient_email,
                subject=self.email_config.subject,
                body=self.email_config.body,
                attachments=[attachment],
            )

    def _send_internal_reports(self) -> None:
        """Sends all reports to default recipients when in internal mode."""
        for attachment in tqdm(
            self.report_summary.values(), desc="Sending internal reports"
        ):
            self._send_to_default_recipients(attachment)

    def _group_files_by_recipient(self) -> tuple[dict, list]:
        """
        Groups files based on whether they have mapped recipients.
        Only used in account-based email mode.

        Returns:
            tuple: (files_with_recipients, files_without_recipients)
        """
        files_with_recipients = {}
        files_without_recipients = []

        for account_number, attachment in self.report_summary.items():
            mapped_email = self.account_email_mapping.get(account_number)
            if mapped_email:
                files_with_recipients[account_number] = attachment
            else:
                files_without_recipients.append(attachment)

        return files_with_recipients, files_without_recipients

    def _send_account_based_emails(self) -> None:
        """Handles sending emails in account-based mode."""
        files_with_recipients, files_without_recipients = (
            self._group_files_by_recipient()
        )

        # Send individual emails for mapped recipients
        for account_number, attachment in tqdm(
            files_with_recipients.items(), desc="Sending frequency reports with emails"
        ):
            self.email_client.send_email(
                recipient_email=self.account_email_mapping.get(account_number),
                subject=self.email_config.subject,
                body=self.email_config.body,
                attachments=[attachment],
            )

        # Handle files without recipients
        if files_without_recipients:
            zip_buffer = OSHelper.create_zip_in_memory(files_without_recipients)

            # Send the in-memory zip file
            for recipient_email in tqdm(
                self.email_config.default_recipients,
                desc="Sending frequency reports without emails",
            ):
                self.email_client.send_email_with_memory_attachment(
                    recipient_email=recipient_email,
                    subject=self.email_config.subject,
                    body=self.email_config.body,
                    attachment_data=zip_buffer.getvalue(),
                    attachment_name=f"frequency_reports {DatetimeHelper.get_current_datetime()}.zip",
                )

    def send_emails(self) -> None:
        """Sends emails based on the configured recipient type."""
        with self.email_client:
            if self.email_config.recipient_type == EmailRecipientType.INTERNAL:
                self._send_internal_reports()
            else:
                self._send_account_based_emails()
