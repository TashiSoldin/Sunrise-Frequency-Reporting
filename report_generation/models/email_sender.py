import logging
from tqdm import tqdm
from clients.outlook_email_client import OutlookEmailClient
from enums.email_enums import EmailConfig, EmailRecipientType
from helpers.os_helper import OSHelper

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(
        self,
        email_secrets: dict,
        email_config: EmailConfig,
        report_summary: dict,
    ) -> None:
        """
        Args:
            email_secrets (dict): The email secrets.
            email_config (EmailConfig): The email configuration.
            report_summary (dict): The report summary.

            Example report_summary:
            {
                "1234567890": {
                    "file_path": "path/to/file.xlsx",
                    "client_name": "Client Name"
                },
                "1234567891": {
                    "file_path": "path/to/file2.xlsx",
                    "client_name": "Client Name 2"
                }
            }
        """
        self.email_client = OutlookEmailClient(**email_secrets)
        self.report_summary = report_summary
        self.email_config = email_config

    def _send_to_default_recipients(self, attachment: str) -> None:
        """Sends an email with the given attachment to all default recipients."""
        for recipient_email in self.email_config.default_recipients:
            self.email_client.send_email(
                recipient_email=recipient_email,
                cc_recipients=self.email_config.cc_recipients,
                subject=self.email_config.subject,
                body=self.email_config.body,
                attachments=[attachment],
            )
            logger.info(f"Internal email sent to {recipient_email}")
        logger.info("All internal emails sent successfully")

    def _send_internal_reports(self) -> None:
        """Sends all reports to default recipients when in internal mode."""
        for summary in tqdm(
            self.report_summary.values(), desc="Sending internal reports"
        ):
            self._send_to_default_recipients(summary["file_path"])

    def _group_files_by_recipient(self) -> tuple[dict, list]:
        """
        Groups files based on whether they have mapped recipients.
        Only used in external email mode.

        Returns:
            tuple: (summaries_with_recipients, summaries_without_recipients)
        """
        summaries_with_recipients = {}
        summaries_without_recipients = []

        for account_number, summary in self.report_summary.items():
            if summary.get("email"):
                summaries_with_recipients[account_number] = summary
            else:
                summaries_without_recipients.append(summary)

        logger.info(f"Summaries with recipients: {summaries_with_recipients}")
        logger.info(f"Summaries without recipients: {summaries_without_recipients}")

        return summaries_with_recipients, summaries_without_recipients

    def _send_external_reports(self) -> None:
        """Handles sending emails in external mode."""
        summaries_with_recipients, summaries_without_recipients = (
            self._group_files_by_recipient()
        )

        # Send individual emails for mapped recipients
        for account_number, summary in tqdm(
            summaries_with_recipients.items(),
            desc="Sending external reports with emails",
        ):
            recipient_email = summary.get("email")
            self.email_client.send_email(
                recipient_email=recipient_email,
                cc_recipients=self.email_config.cc_recipients,
                subject=f"{summary['client_name']} - {self.email_config.subject}",
                body=self.email_config.body,
                attachments=[summary["file_path"]],
            )
            logger.info(f"External email sent to {recipient_email}")
        logger.info("All external emails sent successfully")

        # Handle files without recipients
        if summaries_without_recipients:
            files_without_recipients = [
                summary["file_path"] for summary in summaries_without_recipients
            ]
            zip_buffer = OSHelper.create_zip_in_memory(files_without_recipients)

            # Send the in-memory zip file
            for recipient_email in tqdm(
                self.email_config.default_recipients,
                desc="Sending external reports without emails",
            ):
                self.email_client.send_email_with_memory_attachment(
                    recipient_email=recipient_email,
                    cc_recipients=self.email_config.default_ccs,
                    subject=self.email_config.subject,
                    body=self.email_config.body,
                    attachment_data=zip_buffer.getvalue(),
                    attachment_name=f"{self.email_config.subject}.zip",
                )
                logger.info(f"Internal email sent to {recipient_email}")
            logger.info("All internal emails sent successfully")

    def send_emails(self) -> None:
        """Sends emails based on the configured recipient type."""
        with self.email_client:
            if self.email_config.recipient_type == EmailRecipientType.INTERNAL:
                self._send_internal_reports()
            else:
                self._send_external_reports()
