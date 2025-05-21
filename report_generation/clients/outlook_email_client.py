from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib

import logging

logger = logging.getLogger(__name__)


class OutlookEmailClient:
    def __init__(
        self,
        sender_email: str,
        sender_password: str,
        smtp_server: str = "smtp-mail.outlook.com",
        smtp_port: int = 587,
    ) -> None:
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port

    def __enter__(self):
        self.connection = self._create_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.connection.close()

    def _create_connection(self) -> smtplib.SMTP:
        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
        except smtplib.SMTPAuthenticationError:
            raise ValueError("Authentication failed. Check credentials.")
        except Exception as e:
            raise ValueError(f"Connection failed: {e}")

        return server

    def send_email(
        self,
        recipient_email: str,
        cc_recipients: list[str],
        subject: str,
        body: str,
        attachments: list[str] | None,
    ) -> None:
        """
        Send a single email with optional attachments.

        Args:
            recipient_email (str): Email address of the recipient
            cc_recipients (list[str]): List of email addresses to CC
            subject (str): Email subject line
            body (str): Email body content
            attachments (list[str], optional): List of file paths to attach
        """
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject

        if cc_recipients:
            msg["Cc"] = ", ".join(cc_recipients)

        msg.attach(MIMEText(body, "html"))

        if attachments:
            for file_path in attachments:
                with open(file_path, "rb") as f:
                    attachment = MIMEApplication(f.read(), _subtype="xlsx")
                    filename = file_path.split("/")[-1]
                    attachment.add_header(
                        "Content-Disposition", "attachment", filename=filename
                    )
                    msg.attach(attachment)

        # try:
        #     self.connection.send_message(msg)
        # except (smtplib.SMTPException, OSError) as smtp_err:
        #     raise ValueError(f"SMTP error: {smtp_err}")

    def send_email_with_memory_attachment(
        self,
        recipient_email: str,
        cc_recipients: list[str],
        subject: str,
        body: str,
        attachment_data: bytes,
        attachment_name: str,
    ) -> None:
        """
        Send a single email with an in-memory attachment.

        Args:
            recipient_email (str): Email address of the recipient
            cc_recipients (list[str]): List of email addresses to CC
            subject (str): Email subject line
            body (str): Email body content
            attachment_data (bytes): The attachment data in bytes
            attachment_name (str): Name to give the attachment file
        """
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject

        if cc_recipients:
            msg["Cc"] = ", ".join(cc_recipients)

        msg.attach(MIMEText(body, "html"))

        attachment = MIMEApplication(attachment_data, _subtype="zip")
        attachment.add_header(
            "Content-Disposition", "attachment", filename=attachment_name
        )
        msg.attach(attachment)

        # try:
        #     self.connection.send_message(msg)
        # except (smtplib.SMTPException, OSError) as smtp_err:
        #     raise ValueError(f"SMTP error: {smtp_err}")
